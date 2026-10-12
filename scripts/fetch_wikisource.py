"""從中文維基文庫下載古籍原文，每本存成一個 .txt。

用法：pip install requests && python fetch_wikisource.py [書名 ...]
不帶書名就抓全部。輸出在 ./books/ 資料夾。

GitHub Actions 平行抓取用：
  python fetch_wikisource.py plan 20    # 列出章節並分成 20 片
  python fetch_wikisource.py fetch 3    # 抓第 3 片
  python fetch_wikisource.py merge      # 合併成每本一個檔
"""
import json
import os
import re
import sys
import time
from html import unescape
from html.parser import HTMLParser

import requests

API = "https://zh.wikisource.org/w/api.php"
HEADERS = {"User-Agent": "classics-fetcher/1.0 (personal reading)"}

# 書名 -> (維基文庫的子頁面前綴, 篩選子頁面的條件)
BOOKS = {
    "莊子": ("莊子/", None),
    "黃帝內經·素問": ("黃帝內經/", lambda t: "素問" in t),
    "鬼谷子": ("鬼谷子/", None),
    "傳習錄": ("傳習錄/", None),
    "抱朴子": ("抱朴子/", None),
    "易經": ("周易/", None),  # 維基文庫以《周易》為主條目
}


class TextExtractor(HTMLParser):
    """把 parse API 回傳的 HTML 轉成純文字，略過目錄、註腳、導覽框。"""

    SKIP_CLASSES = ("toc", "reference", "mw-editsection", "header", "navbox",
                    "noprint", "ws-noexport", "licenseContainer")
    BLOCK_TAGS = {"p", "div", "br", "h1", "h2", "h3", "h4", "li", "tr", "dd"}

    def __init__(self):
        super().__init__()
        self.parts, self.skip_depth, self.stack = [], 0, []

    def handle_starttag(self, tag, attrs):
        cls = dict(attrs).get("class", "") or ""
        skipping = self.skip_depth > 0 or any(c in cls for c in self.SKIP_CLASSES) \
            or tag in ("style", "script", "sup")
        if tag not in ("br", "img", "hr", "meta", "link", "wbr"):
            self.stack.append(skipping)
            if skipping:
                self.skip_depth += 1
        if tag in self.BLOCK_TAGS and not self.skip_depth:
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in ("br", "img", "hr", "meta", "link", "wbr"):
            return
        if self.stack and self.stack.pop():
            self.skip_depth -= 1
        if tag in self.BLOCK_TAGS and not self.skip_depth:
            self.parts.append("\n")

    def handle_data(self, data):
        if not self.skip_depth:
            self.parts.append(data)

    def text(self):
        return re.sub(r"\n\s*\n+", "\n\n", "".join(self.parts)).strip()


def api(**params):
    params.update(format="json", formatversion=2, maxlag=5)
    for attempt in range(6):
        r = requests.get(API, params=params, headers=HEADERS, timeout=30)
        if r.ok:
            data = r.json()
            if data.get("error", {}).get("code") != "maxlag":
                return data
        wait = int(r.headers.get("Retry-After", 0) or 0) or 5 * 2 ** attempt
        print(f"  HTTP {r.status_code}，{wait} 秒後重試")
        time.sleep(wait)
    r.raise_for_status()
    raise RuntimeError("維基文庫一直回 maxlag，稍後再試")


def linked_pages(title, name):
    """主頁面沒有子頁面時，改抓主頁面（目錄頁）連到的、標題含書名的頁面。"""
    titles, cont = [], {}
    while True:
        data = api(action="query", prop="links", titles=title, plnamespace=0,
                   pllimit="max", redirects=1, **cont)
        for page in data["query"]["pages"]:
            titles += [l["title"] for l in page.get("links", [])]
        if "continue" not in data:
            return [t for t in titles if name in t]
        cont = data["continue"]


def subpages(prefix):
    titles, cont = [], {}
    while True:
        data = api(action="query", list="allpages", apprefix=prefix,
                   apnamespace=0, aplimit="max", **cont)
        titles += [p["title"] for p in data["query"]["allpages"]]
        if "continue" not in data:
            return titles
        cont = data["continue"]


def page_text(title):
    data = api(action="parse", page=title, prop="text", redirects=1)
    if "error" in data:
        return ""
    p = TextExtractor()
    p.feed(data["parse"]["text"])
    return p.text()


def index_order(index):
    """目錄頁上的連結，依它們在頁面出現的先後排列（也就是書的章節順序）。"""
    data = api(action="parse", page=index, prop="text", redirects=1)
    if "error" in data:
        return []
    html = data["parse"]["text"]
    seen = []
    for m in re.finditer(r'<a [^>]*title="([^"]+)"', html):
        t = unescape(m.group(1))
        if t not in seen:
            seen.append(t)
    return seen


def chapter_titles(name):
    prefix, keep = BOOKS[name]
    index = prefix.rstrip("/")
    titles = [t for t in subpages(prefix) if keep is None or keep(t)]
    if not titles:  # 沒有子頁面時，改從目錄頁的連結找章節
        titles = [t for t in linked_pages(index, index[:2])
                  if keep is None or keep(t)]
    if not titles:  # 還是沒有，全文可能就在主頁面
        return [index]
    # API 給的是字碼順序；改照目錄頁的順序，目錄沒列到的放最後
    order = {t: i for i, t in enumerate(index_order(index))}
    return sorted(titles, key=lambda t: (order.get(t, len(order)), t))


# ---- 分三步，讓 GitHub Actions 把章節分給多個 job 平行抓 ----

def plan(shards):
    """列出所有書的所有章節，輪流分配到 shards 個分片，寫進 plan.json。"""
    tasks = []
    for name in BOOKS:
        titles = chapter_titles(name)
        print(f"{name}: {len(titles)} 頁")
        tasks += [{"book": name, "idx": i, "title": t} for i, t in enumerate(titles)]
    for n, task in enumerate(tasks):
        task["shard"] = n % shards
    with open("plan.json", "w", encoding="utf-8") as f:
        json.dump(tasks, f, ensure_ascii=False, indent=1)
    print(f"共 {len(tasks)} 頁，分成 {shards} 片")


def fetch(shard):
    """抓 plan.json 裡屬於這個分片的章節，每章存成 parts/<書名>/<序號>.txt。"""
    with open("plan.json", encoding="utf-8") as f:
        tasks = [t for t in json.load(f) if t["shard"] == shard]
    for t in tasks:
        body = page_text(t["title"])
        folder = os.path.join("parts", t["book"])
        os.makedirs(folder, exist_ok=True)
        with open(os.path.join(folder, f"{t['idx']:04d}.txt"), "w", encoding="utf-8") as f:
            f.write(f"==== {t['title']} ====\n\n{body}" if body else "")
        time.sleep(0.5)  # 對維基伺服器客氣一點
    print(f"分片 {shard}：抓了 {len(tasks)} 頁")


def merge():
    """把 parts/ 依序合併成 books/<書名>.txt。"""
    os.makedirs("books", exist_ok=True)
    for name in sorted(os.listdir("parts")):
        folder = os.path.join("parts", name)
        chapters = []
        for fn in sorted(os.listdir(folder)):
            with open(os.path.join(folder, fn), encoding="utf-8") as f:
                if text := f.read():
                    chapters.append(text)
        with open(os.path.join("books", f"{name}.txt"), "w", encoding="utf-8") as f:
            f.write(f"《{name}》 來源：中文維基文庫（公有領域）\n\n\n"
                    + "\n\n\n".join(chapters))
        print(f"{name}: {len(chapters)} 章 -> books/{name}.txt")


def main(args):
    if args and args[0] == "plan":
        plan(int(args[1]))
    elif args and args[0] == "fetch":
        fetch(int(args[1]))
    elif args and args[0] == "merge":
        merge()
    else:  # 本機一次跑完：可指定書名，不指定就抓全部
        names = args or list(BOOKS)
        plan(1)
        with open("plan.json", encoding="utf-8") as f:
            tasks = [t for t in json.load(f) if t["book"] in names]
        with open("plan.json", "w", encoding="utf-8") as f:
            json.dump(tasks, f, ensure_ascii=False)
        fetch(0)
        merge()


if __name__ == "__main__":
    main(sys.argv[1:])
