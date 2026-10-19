"""解出 article.md 裡藏的密語。"""
import re
import sys
from pathlib import Path

path = Path(sys.argv[1] if len(sys.argv) > 1 else Path(__file__).with_name("article.md"))
body = "".join(l for l in path.read_text(encoding="utf-8").splitlines() if not l.startswith("#"))
sentences = [s for s in re.split(r"[。！？]", body) if s.strip()]
picked = [re.sub(r"[^一-鿿]", "", s)[-2] for s in sentences]
print(len(sentences), "句")
print("".join(reversed(picked)))
