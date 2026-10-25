"""步驟 2：抽 PDF 文字，用關鍵字切出和自然碳匯相關的段落（附頁碼）。

輸出 data/snippets/<code>_<year>.json
用法：python -X utf8 step2_extract_snippets.py
"""
import json
import re
from pathlib import Path

import fitz  # PyMuPDF

ROOT = Path(__file__).parent
PDF_DIR = ROOT / "data" / "pdfs"
OUT_DIR = ROOT / "data" / "snippets"
OUT_DIR.mkdir(parents=True, exist_ok=True)

# 強關鍵字：直接跟自然碳匯有關
STRONG = r"碳匯|增匯|藍碳|綠碳|黃碳|造林|植林|植樹|種樹|育苗|認養.{0,6}(林|森林|樹|濕地|溼地|海岸)|紅樹林|海草|海藻床|濕地|溼地|土壤碳|土壤有機碳|固碳|碳吸存|吸存量|碳移除|移除量|自然解方|自然為本|Nature[- ]based|NbS|竹林|森林經營|林地"
# 弱關鍵字：要附近有自然相關字才算，避免一般碳權/綠化段落太多
WEAK = r"碳權|碳抵換|抵換專案|減量額度|自願減量|綠化|森林"
NATURE_NEAR = r"林|樹|紅樹|藍碳|海洋|濕地|溼地|土壤|竹|植被|生態"

WINDOW = 350          # 命中處前後各取幾個字
MAX_CHARS = 30000     # 每本報告送給模型的上限


def clean(t):
    return re.sub(r"[ \t　]+", " ", re.sub(r"\n+", "\n", t)).strip()


def extract(pdf_path):
    doc = fitz.open(pdf_path)
    pages = [clean(p.get_text()) for p in doc]
    doc.close()
    return pages


def find_spans(text):
    spans = []
    for m in re.finditer(STRONG, text, flags=re.I):
        spans.append((m.start(), m.end(), 2))
    for m in re.finditer(WEAK, text):
        ctx = text[max(0, m.start() - 150): m.end() + 150]
        if re.search(NATURE_NEAR, ctx):
            spans.append((m.start(), m.end(), 1))
    return spans


def page_snippets(page_no, text):
    spans = find_spans(text)
    if not spans:
        return []
    # 合併相近的命中區間
    wins = sorted((max(0, s - WINDOW), min(len(text), e + WINDOW), w) for s, e, w in spans)
    merged = []
    for s, e, w in wins:
        if merged and s <= merged[-1][1]:
            ps, pe, pw, pn = merged[-1]
            merged[-1] = (ps, max(pe, e), pw + w, pn + 1)
        else:
            merged.append((s, e, w, 1))
    return [{"page": page_no, "score": w, "hits": n, "text": text[s:e]} for s, e, w, n in merged]


def main():
    for pdf in sorted(PDF_DIR.glob("*.pdf")):
        out = OUT_DIR / (pdf.stem + ".json")
        if out.exists():
            continue
        try:
            pages = extract(pdf)
        except Exception as e:
            print(f"{pdf.name} 讀取失敗：{e}")
            continue
        snips = [s for i, t in enumerate(pages, 1) for s in page_snippets(i, t)]
        total_chars = sum(len(t) for t in pages)
        # 超過上限時，先留分數高的段落，再按頁碼排回去
        chosen, used = [], 0
        for s in sorted(snips, key=lambda s: -s["score"]):
            if used + len(s["text"]) > MAX_CHARS:
                continue
            chosen.append(s)
            used += len(s["text"])
        chosen.sort(key=lambda s: s["page"])
        strong_hits = sum(len(re.findall(STRONG, t, flags=re.I)) for t in pages)
        out.write_text(json.dumps({
            "file": pdf.name, "n_pages": len(pages), "total_chars": total_chars,
            "strong_hits": strong_hits, "n_snippets_all": len(snips),
            "snippets": chosen,
        }, ensure_ascii=False, indent=1), encoding="utf-8")
        flag = "（幾乎沒有文字，可能是掃描檔）" if total_chars < len(pages) * 50 else ""
        print(f"{pdf.stem}: {len(pages)} 頁, 強關鍵字 {strong_hits} 次, 段落 {len(chosen)}/{len(snips)}, {used} 字{flag}", flush=True)


if __name__ == "__main__":
    main()
