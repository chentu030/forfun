"""GitHub Actions worker：下載自己分到的報告 → 上傳 PDF 到 GCS → 抽全文與關鍵字段落 → 上傳 → 刪本機檔。

用法：python worker.py <shard> <總 shard 數>
需要環境變數 GCS_BUCKET，以及 google-github-actions/auth 設好的憑證。
已經處理過的（GCS 上有 text/<key>.json.gz）會跳過，所以可以重跑。
"""
import gzip
import json
import os
import subprocess
import sys
import tempfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import requests
from google.cloud import storage

import extract

SHARD, TOTAL = int(sys.argv[1]), int(sys.argv[2])
CONNS = int(os.environ.get("CONNS", "3"))  # 公開資訊觀測站不回報檔案大小、容易中途斷線，總連線數建議 ≤ 20
UA = {"User-Agent": "Mozilla/5.0"}

bucket = storage.Client().bucket(os.environ["GCS_BUCKET"])
items = json.loads(Path("manifest.json").read_text(encoding="utf-8"))[SHARD::TOTAL]
done = {b.name[5:-8] for b in bucket.list_blobs(prefix="text/")}
todo = [x for x in items if x["key"] not in done]
print(f"shard {SHARD}/{TOTAL}: 分到 {len(items)} 份，已完成 {len(items) - len(todo)}，待處理 {len(todo)}", flush=True)

lock = threading.Lock()
stats = {"ok": 0, "fail": 0, "mb": 0.0}
failures = []
t0 = time.time()


def complete_pdf(b, content_length=None):
    """完整的 PDF：開頭 %PDF、結尾 4KB 內有 %%EOF，且（伺服器有回報時）大小與 Content-Length 相同。
    公開資訊觀測站用 HTTP/1.0 且不回報大小，傳到一半斷線時看起來和正常結束一樣，所以一定要檢查 %%EOF。"""
    if not (b[:4] == b"%PDF" and b"%%EOF" in b[-4096:]):
        return False
    return not content_length or int(content_length) == len(b)


def fetch(url):
    last = None
    for attempt in range(6):
        try:
            r = requests.get(url, headers=UA, timeout=900)
            b = r.content
            if r.status_code == 200 and complete_pdf(b, r.headers.get("Content-Length")):
                return b
            # ZIP、舊版 Word 等非 PDF 檔，交給 rescue.py 轉檔，這裡不重試
            if r.status_code == 200 and len(b) > 1000 and (b[:2] == b"PK" or b[:4] == bytes.fromhex("d0cf11e0")):
                raise RuntimeError(f"非 PDF 檔（{b[:4]!r}），需轉檔")
            last = f"HTTP {r.status_code}，{len(b)} bytes，Content-Length {r.headers.get('Content-Length')}，有 EOF：{b'%%EOF' in b[-4096:]}"
        except RuntimeError:
            raise
        except Exception as e:
            last = str(e)[:200]
        time.sleep(20 * (attempt + 1))  # 被擋、逾時或檔案不完整就退避
    raise RuntimeError(last)


def process(x):
    key = x["key"]
    try:
        data = fetch(x["url"])
        bucket.blob(f"pdfs/{key}.pdf").upload_from_string(data, content_type="application/pdf")
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
            f.write(data)
            path = f.name
        out_json = path + ".json"
        try:
            # 抽字放到子程序：PyMuPDF 不是 thread-safe，壞檔當掉也只影響這一份
            r = subprocess.run([sys.executable, "extract_one.py", path, out_json], capture_output=True, timeout=600)
            if r.returncode != 0 or not os.path.exists(out_json):
                raise RuntimeError(f"抽字失敗（exit {r.returncode}）：{r.stderr.decode('utf-8', 'ignore')[-200:]}")
            with open(out_json, encoding="utf-8") as f:
                pages = json.load(f)
        finally:
            for fp in (path, out_json):
                if os.path.exists(fp):
                    os.remove(fp)
        snips = [s for i, t in enumerate(pages, 1) for s in extract.page_snippets(i, t)]
        chosen, used = [], 0
        for s in sorted(snips, key=lambda s: -s["score"]):
            if used + len(s["text"]) <= extract.MAX_CHARS:
                chosen.append(s)
                used += len(s["text"])
        chosen.sort(key=lambda s: s["page"])
        strong = sum(len(extract.re.findall(extract.STRONG, t, flags=extract.re.I)) for t in pages)
        meta = {**x, "n_pages": len(pages), "total_chars": sum(len(t) for t in pages), "pdf_mb": round(len(data) / 1e6, 2)}
        bucket.blob(f"snippets/{key}.json").upload_from_string(json.dumps(
            {**meta, "file": f"{key}.pdf", "strong_hits": strong, "n_snippets_all": len(snips), "snippets": chosen},
            ensure_ascii=False), content_type="application/json")
        # 全文最後上傳，當作「這份已完成」的標記
        bucket.blob(f"text/{key}.json.gz").upload_from_string(
            gzip.compress(json.dumps({**meta, "pages": pages}, ensure_ascii=False).encode("utf-8")),
            content_type="application/gzip")
        with lock:
            stats["ok"] += 1
            stats["mb"] += len(data) / 1e6
            n = stats["ok"] + stats["fail"]
            if n % 20 == 0:
                el = time.time() - t0
                print(f"[{n}/{len(todo)}] 成功 {stats['ok']} 失敗 {stats['fail']}，{stats['mb']:.0f} MB，{stats['mb']/el:.2f} MB/s，{el/60:.0f} 分", flush=True)
    except Exception as e:
        with lock:
            stats["fail"] += 1
            failures.append({"key": key, "url": x["url"], "error": str(e)[:300]})
        print(f"{key} 失敗：{str(e)[:200]}", flush=True)


with ThreadPoolExecutor(CONNS) as ex:
    list(ex.map(process, todo))

if failures:
    bucket.blob(f"failures/shard_{SHARD:02d}.json").upload_from_string(json.dumps(failures, ensure_ascii=False, indent=1))
el = time.time() - t0
print(f"shard {SHARD} 結束：成功 {stats['ok']}，失敗 {stats['fail']}，{stats['mb']:.0f} MB，{el/60:.0f} 分鐘", flush=True)
