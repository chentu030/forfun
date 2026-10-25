"""在獨立子程序裡抽一份 PDF 的逐頁文字（PyMuPDF 不是 thread-safe，壞檔也可能讓它當掉）。

用法：python extract_one.py <pdf> <輸出 json>
"""
import json
import sys

import extract

pages = extract.extract(sys.argv[1])
with open(sys.argv[2], "w", encoding="utf-8") as f:
    json.dump(pages, f, ensure_ascii=False)
