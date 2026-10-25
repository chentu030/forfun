"""大小比對：確認雲端上每份 PDF 與來源檔完全相同。

- 證交所 ESG 平台（2023 年起）：只要求第 1 個 byte，從 Content-Range 取得原始大小，直接比對。
- 公開資訊觀測站（2022 年以前）：伺服器不回報大小，只能完整重新下載一次比對；
  大小不同就再下載第三次，以兩次相同、且結構完整（有 %%EOF、PyMuPDF 讀得到頁數）的版本為準，必要時替換並重新抽字。
- 補救時從 ZIP／Word／PPTX 轉成的 PDF（來源不是 PDF），標記後略過。

用法：python sizecheck.py <shard> <總 shard 數>
結果寫到 GCS sizecheck/shard_XX.json
"""
import gzip
import json
import os
import subprocess
import sys
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import requests
from google.cloud import storage

import extract

SHARD, TOTAL = int(sys.argv[1]), int(sys.argv[2])
UA = {"User-Agent": "Mozilla/5.0"}
bucket = storage.Client().bucket(os.environ["GCS_BUCKET"])
items = json.loads(Path("manifest.json").read_text(encoding="utf-8"))[SHARD::TOTAL]
results = []


def get(url, **kw):
    last = ""
    for attempt in range(5):
        try:
            r = requests.get(url, headers={**UA, **kw.pop("headers", {})}, timeout=900, **kw)
            if r.status_code in (200, 206):
                return r
            last = f"HTTP {r.status_code}"
        except Exception as e:
            last = str(e)[:120]
        time.sleep(15 * (attempt + 1))
    raise RuntimeError(last)


def pages_ok(data):
    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
        f.write(data)
        path = f.name
    out = path + ".json"
    try:
        r = subprocess.run([sys.executable, "extract_one.py", path, out], capture_output=True, timeout=600)
        if r.returncode == 0 and os.path.exists(out):
            pages = json.load(open(out, encoding="utf-8"))
            return pages if pages else None
        return None
    finally:
        for p in (path, out):
            if os.path.exists(p):
                os.remove(p)


def replace(x, data, pages):
    key = x["key"]
    snips = [s for i, t in enumerate(pages, 1) for s in extract.page_snippets(i, t)]
    chosen, used = [], 0
    for s in sorted(snips, key=lambda s: -s["score"]):
        if used + len(s["text"]) <= extract.MAX_CHARS:
            chosen.append(s)
            used += len(s["text"])
    chosen.sort(key=lambda s: s["page"])
    strong = sum(len(extract.re.findall(extract.STRONG, t, flags=extract.re.I)) for t in pages)
    meta = {**x, "n_pages": len(pages), "total_chars": sum(len(t) for t in pages), "pdf_mb": round(len(data) / 1e6, 2), "sizecheck_replaced": True}
    bucket.blob(f"pdfs/{key}.pdf").upload_from_string(data, content_type="application/pdf")
    bucket.blob(f"snippets/{key}.json").upload_from_string(json.dumps(
        {**meta, "file": f"{key}.pdf", "strong_hits": strong, "n_snippets_all": len(snips), "snippets": chosen}, ensure_ascii=False))
    bucket.blob(f"text/{key}.json.gz").upload_from_string(gzip.compress(json.dumps({**meta, "pages": pages}, ensure_ascii=False).encode()))


def check(x):
    key = x["key"]
    blob = bucket.blob(f"pdfs/{key}.pdf")
    blob.reload()
    stored = blob.size
    row = {"key": key, "year": x["year"], "stored": stored}
    try:
        if "FileStream" in x["url"]:
            r = get(x["url"], headers={"Range": "bytes=0-0"}, stream=True)
            cr = r.headers.get("Content-Range", "")
            head = r.raw.read(4)
            r.close()
            if not head:
                row.update(status="來源為空檔，略過（已由補救程式處理）")
            elif head[:1] != b"%":
                row.update(status="來源非 PDF，略過")
            elif "/" in cr:
                src = int(cr.split("/")[-1])
                row.update(source=src, status="一致" if src == stored else "大小不同")
            else:
                row.update(status="來源未回報大小")
            if row["status"] == "大小不同":
                data = get(x["url"]).content
                pages = pages_ok(data) if len(data) == row["source"] else None
                if pages:
                    replace(x, data, pages)
                    row.update(status="已替換", new=len(data), pages=len(pages))
                else:
                    row.update(status="大小不同但重新下載仍不完整", new=len(data))
        else:
            d1 = get(x["url"]).content
            if not d1:
                row.update(status="來源為空檔，略過（已由補救程式處理）")
            elif not d1.startswith(b"%PDF"):
                row.update(status="來源非 PDF，略過", new=len(d1))
            elif len(d1) == stored:
                row.update(status="一致", new=len(d1))
            else:
                d2 = get(x["url"]).content
                row.update(new=len(d1), third=len(d2))
                cand = d1 if len(d1) == len(d2) else max((d1, d2), key=len)
                if len(d2) == stored:
                    row.update(status="一致（第三次與原檔相同）")
                else:
                    pages = pages_ok(cand) if b"%%EOF" in cand[-4096:] else None
                    if pages and len(cand) > stored:
                        replace(x, cand, pages)
                        row.update(status="已替換", pages=len(pages))
                    else:
                        row.update(status="大小不同，無法確認哪個正確")
    except Exception as e:
        row.update(status="錯誤", error=str(e)[:150])
    results.append(row)
    if row["status"] not in ("一致", "一致（第三次與原檔相同）"):
        print(key, row, flush=True)


with ThreadPoolExecutor(3) as ex:
    list(ex.map(check, items))
from collections import Counter  # noqa: E402
bucket.blob(f"sizecheck/shard_{SHARD:02d}.json").upload_from_string(json.dumps(results, ensure_ascii=False, indent=1))
print(f"shard {SHARD}：", dict(Counter(r["status"] for r in results)), flush=True)
