#!/usr/bin/env python3
"""從卷期清單 Excel 產生 books.json 與 Chrome 擴充功能 queue.json。

用法:
    python prepare_books.py                          # 列出待抓數量
    python prepare_books.py --write                   # 輸出 books.json
    python prepare_books.py --write --limit 20        # 只取前 20 本
    python prepare_books.py --queue                   # 產生 Chrome 擴充功能 queue.json（全部）
    python prepare_books.py --queue --limit 50        # 只排前 50 本
    python prepare_books.py --queue --magazine 先探    # 只排某雜誌
"""

import json, os, re, sys, collections, argparse, time
from pathlib import Path
import openpyxl

XLSX = Path(r"C:\Users\User\Desktop\HyRead雜誌最新一期\HyRead雜誌卷期清單_2026-11-11.xlsx")
DEFAULT_SINCE = "2025-01-01"
OUTPUT_DIR = Path(r"D:\HyRead解密書籍")
QUEUE_PATH = Path(r"C:\Users\User\Desktop\hyread_tools\chrome_ext\queue.json")

sys.stdout.reconfigure(encoding="utf-8")


def safe(s):
    s = re.sub(r"(\d{4})/(\d{2})/(\d{2})", r"\1\2\3", s)
    s = re.sub(r'[<>:"/\\|?*]', "", s)
    return re.sub(r"\s+", " ", s).strip()


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--since", default=DEFAULT_SINCE)
    p.add_argument("--write", action="store_true", help="輸出 books.json")
    p.add_argument("--queue", action="store_true", help="產生 Chrome 擴充功能 queue.json")
    p.add_argument("--limit", type=int, default=0, help="只取前 N 本")
    p.add_argument("--magazine", default="", help="只排某雜誌（部分名稱即可）")
    p.add_argument("--oldest-first", action="store_true", help="從最舊的開始抓")
    p.add_argument("--xlsx", default=str(XLSX))
    p.add_argument("--output-dir", default=str(OUTPUT_DIR))
    p.add_argument("--out", default=str(Path(__file__).resolve().parent / "books.json"))
    args = p.parse_args()

    wb = openpyxl.load_workbook(args.xlsx, read_only=True)
    rows = list(wb["全部卷期"].iter_rows(values_only=True))[1:]

    out_dir = Path(args.output_dir)
    done = set()
    if out_dir.exists():
        for pdf in out_dir.glob("*.pdf"):
            stem = re.sub(r" \(缺\d+頁\)$", "", pdf.stem)
            done.add(stem)

    sel = [r for r in rows if r[2] and str(r[2])[:10] >= args.since]
    todo = [r for r in sel if safe(r[1]) not in done]
    todo.sort(key=lambda r: str(r[2])[:10], reverse=not args.oldest_first)

    if args.magazine:
        todo = [r for r in todo if args.magazine in r[0]]

    print(f"全部 {len(rows)} 期；{args.since} 之後 {len(sel)} 期；已抓 {len(sel)-len(todo)}；待抓 {len(todo)}")
    print("各刊待抓：", collections.Counter(r[0] for r in todo).most_common())

    if args.limit:
        todo = todo[: args.limit]

    books = []
    for r in todo:
        books.append({
            "magazine": r[0],
            "title": safe(r[1]),
            "date": str(r[2])[:10],
            "issue": r[3],
            "url": r[4],
        })

    if args.write:
        Path(args.out).write_text(json.dumps(books, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"已寫入 {args.out} ({len(books)} 本)")

    if args.queue:
        urls = [b["url"] for b in books]
        q = {"id": f"batch_{int(time.time())}", "urls": urls}
        QUEUE_PATH.write_text(json.dumps(q, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"已寫入 {QUEUE_PATH} ({len(urls)} 本)")
        est_min = len(urls) * 4
        print(f"預估時間：{est_min // 60} 小時 {est_min % 60} 分（每本約 4 分鐘）")

    if not args.write and not args.queue:
        print("加 --write 輸出 books.json；加 --queue 產生 Chrome 擴充功能 queue.json")


if __name__ == "__main__":
    main()
