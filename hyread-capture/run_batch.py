#!/usr/bin/env python3
"""一鍵觸發 GitHub Actions 批次擷取 + 完成後自動下載 PDF 到本機。

用法:
    python run_batch.py                    # 產生 books.json → push → 觸發 workflow → 等完成 → 下載
    python run_batch.py --skip-trigger     # 只下載上一次跑的 artifacts
    python run_batch.py --local            # 不走 Actions，直接在本機用 patchright 跑
"""

import argparse
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

REPO = "chentu030/forfun"
OUTPUT_DIR = Path(r"D:\HyRead解密書籍")
HERE = Path(__file__).resolve().parent


def sh(cmd, check=True, capture=True):
    print(f"  $ {cmd}")
    r = subprocess.run(cmd, shell=True, capture_output=capture, text=True, encoding="utf-8")
    if check and r.returncode != 0:
        print(r.stderr or r.stdout)
        sys.exit(1)
    return r.stdout.strip() if capture else ""


def prepare_books(since="2025-01-01", limit=0):
    cmd = f'python "{HERE / "prepare_books.py"}" --write --since {since}'
    if limit:
        cmd += f" --limit {limit}"
    sh(cmd, capture=False)
    return json.loads((HERE / "books.json").read_text(encoding="utf-8"))


def push_books():
    """把 books.json 推到 GitHub repo"""
    repo_dir = HERE / "_repo"
    if not repo_dir.exists():
        sh(f'gh repo clone {REPO} "{repo_dir}"')
    else:
        sh(f'git -C "{repo_dir}" pull --ff-only')

    import shutil
    for f in ["capture.py", "requirements.txt", "books.json"]:
        src = HERE / f
        if src.exists():
            shutil.copy2(src, repo_dir / f)

    sh(f'git -C "{repo_dir}" add -A')
    diff = sh(f'git -C "{repo_dir}" diff --cached --stat')
    if diff:
        sh(f'git -C "{repo_dir}" commit -m "update books.json"')
        sh(f'git -C "{repo_dir}" push')
        print("  pushed to GitHub")
    else:
        print("  no changes to push")


def trigger_workflow(chunks=10, limit=0):
    cmd = f'gh workflow run "HyRead Capture" -R {REPO} -f chunks={chunks}'
    if limit:
        cmd += f" -f limit={limit}"
    sh(cmd)
    print(f"  workflow triggered with {chunks} runners")


def wait_workflow():
    """等待最近一次 workflow run 完成"""
    print("waiting for workflow to start...")
    time.sleep(10)
    for _ in range(300):  # 最多等 50 分鐘啟動
        out = sh(f'gh run list -R {REPO} -w "HyRead Capture" --limit 1 --json status,databaseId')
        runs = json.loads(out)
        if runs and runs[0]["status"] in ("in_progress", "queued"):
            run_id = runs[0]["databaseId"]
            print(f"  run {run_id} is {runs[0]['status']}")
            break
        time.sleep(10)
    else:
        print("workflow did not start"); return None

    print(f"watching run {run_id}...")
    for _ in range(360):  # 最多等 3 小時
        out = sh(f'gh run view {run_id} -R {REPO} --json status,conclusion')
        info = json.loads(out)
        if info["status"] == "completed":
            print(f"  run {run_id} completed: {info['conclusion']}")
            return run_id
        time.sleep(30)
    print("  timeout waiting for workflow")
    return run_id


def download_artifacts(run_id=None):
    """下載所有 PDF artifacts 到 OUTPUT_DIR"""
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    if run_id:
        sh(f'gh run download {run_id} -R {REPO} -D "{OUTPUT_DIR}" --pattern "pdfs-*"', capture=False)
    else:
        # 下載最新一次
        out = sh(f'gh run list -R {REPO} -w "HyRead Capture" --limit 1 --json databaseId,status')
        runs = json.loads(out)
        if runs:
            sh(f'gh run download {runs[0]["databaseId"]} -R {REPO} -D "{OUTPUT_DIR}" --pattern "pdfs-*"',
               capture=False)

    # gh 下載會建子資料夾 pdfs-0, pdfs-1...，把 PDF 搬到根目錄
    moved = 0
    for sub in OUTPUT_DIR.iterdir():
        if sub.is_dir() and sub.name.startswith("pdfs-"):
            for pdf in sub.glob("*.pdf"):
                dest = OUTPUT_DIR / pdf.name
                if not dest.exists():
                    pdf.rename(dest)
                    moved += 1
                else:
                    pdf.unlink()
            sub.rmdir()
    print(f"  downloaded {moved} PDFs to {OUTPUT_DIR}")


def run_local(books_path, limit=0):
    """在本機用 patchright 直接跑"""
    cmd = (
        f'python "{HERE / "capture.py"}" '
        f'--books "{books_path}" '
        f'--output "{OUTPUT_DIR}"'
    )
    sh(cmd, capture=False)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--since", default="2025-01-01")
    p.add_argument("--limit", type=int, default=0)
    p.add_argument("--chunks", type=int, default=10)
    p.add_argument("--skip-trigger", action="store_true", help="只下載，不觸發")
    p.add_argument("--local", action="store_true", help="本機執行，不用 GitHub Actions")
    args = p.parse_args()

    books = prepare_books(args.since, args.limit)
    if not books:
        print("沒有待抓的書"); return

    if args.local:
        run_local(HERE / "books.json", args.limit)
        return

    if not args.skip_trigger:
        push_books()
        trigger_workflow(args.chunks, args.limit)
        run_id = wait_workflow()
    else:
        run_id = None

    download_artifacts(run_id)


if __name__ == "__main__":
    main()
