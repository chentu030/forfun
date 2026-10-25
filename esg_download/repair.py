"""檢查並修復下載不完整的 PDF。

完整的 PDF 結尾附近會有 %%EOF；伺服器提早斷線時，檔案會被截斷而沒有 %%EOF。
每個 job 檢查自己分到的報告：讀 GCS 上 PDF 的最後 4KB，沒有 %%EOF 就重新下載
（核對 Content-Length 與 %%EOF，最多 6 次），再重新抽字、上傳。

用法：python repair.py <shard> <總 shard 數>
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
report = []


def complete(b):
    return b[:4] == b"%PDF" and b"%%EOF" in b[-4096:]


def fetch(url):
    last = ""
    for attempt in range(6):
        try:
            r = requests.get(url, headers=UA, timeout=900)
            b = r.content
            cl = r.headers.get("Content-Length")
            if r.status_code == 200 and complete(b) and (not cl or int(cl) == len(b)):
                return b
            last = f"HTTP {r.status_code}，{len(b)} bytes，Content-Length {cl}，結尾有 EOF：{b'%%EOF' in b[-4096:]}"
        except Exception as e:
            last = str(e)[:150]
        time.sleep(20 * (attempt + 1))
    raise RuntimeError(last)


def process(x):
    key = x["key"]
    blob = bucket.blob(f"pdfs/{key}.pdf")
    blob.reload()
    tail = blob.download_as_bytes(start=max(0, blob.size - 4096))
    head = blob.download_as_bytes(end=3)
    if head[:4] != b"%PDF":  # 補救時由 ZIP／Word 轉來的，原始來源不是 PDF，跳過
        return
    if b"%%EOF" in tail:
        return
    old_size = blob.size
    try:
        data = fetch(x["url"])
    except Exception as e:
        report.append({"key": key, "status": "重新下載失敗", "old_mb": round(old_size / 1e6, 2), "error": str(e)})
        print(key, "重新下載失敗", e, flush=True)
        return
    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
        f.write(data)
        path = f.name
    out_json = path + ".json"
    try:
        r = subprocess.run([sys.executable, "extract_one.py", path, out_json], capture_output=True, timeout=600)
        if r.returncode != 0 or not os.path.exists(out_json):
            raise RuntimeError(f"抽字失敗 {r.stderr.decode('utf-8', 'ignore')[-150:]}")
        pages = json.load(open(out_json, encoding="utf-8"))
    except Exception as e:
        report.append({"key": key, "status": "抽字失敗", "old_mb": round(old_size / 1e6, 2), "new_mb": round(len(data) / 1e6, 2), "error": str(e)[:200]})
        print(key, "抽字失敗", flush=True)
        return
    finally:
        for p in (path, out_json):
            if os.path.exists(p):
                os.remove(p)
    snips = [s for i, t in enumerate(pages, 1) for s in extract.page_snippets(i, t)]
    chosen, used = [], 0
    for s in sorted(snips, key=lambda s: -s["score"]):
        if used + len(s["text"]) <= extract.MAX_CHARS:
            chosen.append(s)
            used += len(s["text"])
    chosen.sort(key=lambda s: s["page"])
    strong = sum(len(extract.re.findall(extract.STRONG, t, flags=extract.re.I)) for t in pages)
    meta = {**x, "n_pages": len(pages), "total_chars": sum(len(t) for t in pages), "pdf_mb": round(len(data) / 1e6, 2), "repaired": True}
    bucket.blob(f"pdfs/{key}.pdf").upload_from_string(data, content_type="application/pdf")
    bucket.blob(f"snippets/{key}.json").upload_from_string(json.dumps(
        {**meta, "file": f"{key}.pdf", "strong_hits": strong, "n_snippets_all": len(snips), "snippets": chosen}, ensure_ascii=False))
    bucket.blob(f"text/{key}.json.gz").upload_from_string(gzip.compress(json.dumps({**meta, "pages": pages}, ensure_ascii=False).encode()))
    report.append({"key": key, "status": "已修復", "old_mb": round(old_size / 1e6, 2), "new_mb": round(len(data) / 1e6, 2), "pages": len(pages)})
    print(key, "已修復", round(old_size / 1e6, 2), "→", round(len(data) / 1e6, 2), "MB，", len(pages), "頁", flush=True)


with ThreadPoolExecutor(4) as ex:
    list(ex.map(process, items))
bucket.blob(f"repair/shard_{SHARD:02d}.json").upload_from_string(json.dumps(report, ensure_ascii=False, indent=1))
print(f"shard {SHARD}：檢查 {len(items)} 份，處理 {len(report)} 份", flush=True)
