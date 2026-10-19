#!/usr/bin/env python3
"""六十四卦密碼・輕量版 (Hexagram Cipher Lite) — a two-layer cipher.

  Layer 1  UTF-8 bytes XOR a repeating key (the key's own UTF-8 bytes)
  Layer 2  bit stream -> 6-bit groups -> hexagram whose six lines spell
           those bits (bottom line first, yang = 1, yin = 0)

Usage:
  python3 hexagram_lite.py encrypt KEY < plain.txt > cipher.txt
  python3 hexagram_lite.py decrypt KEY < cipher.txt
"""
import sys

# 八卦, lines listed bottom to top (yang = 1).
TRIGRAMS = {
    "乾": "111", "兌": "110", "離": "101", "震": "100",
    "巽": "011", "坎": "010", "艮": "001", "坤": "000",
}

# King Wen order (= Unicode order U+4DC0..U+4DFF), as (lower, upper).
KING_WEN = [
    ("乾", "乾"), ("坤", "坤"), ("震", "坎"), ("坎", "艮"), ("乾", "坎"), ("坎", "乾"),
    ("坎", "坤"), ("坤", "坎"), ("乾", "巽"), ("兌", "乾"), ("乾", "坤"), ("坤", "乾"),
    ("離", "乾"), ("乾", "離"), ("艮", "坤"), ("坤", "震"), ("震", "兌"), ("巽", "艮"),
    ("兌", "坤"), ("坤", "巽"), ("震", "離"), ("離", "艮"), ("坤", "艮"), ("震", "坤"),
    ("震", "乾"), ("乾", "艮"), ("震", "艮"), ("巽", "兌"), ("坎", "坎"), ("離", "離"),
    ("艮", "兌"), ("巽", "震"), ("艮", "乾"), ("乾", "震"), ("坤", "離"), ("離", "坤"),
    ("離", "巽"), ("兌", "離"), ("艮", "坎"), ("坎", "震"), ("兌", "艮"), ("震", "巽"),
    ("乾", "兌"), ("巽", "乾"), ("坤", "兌"), ("巽", "坤"), ("坎", "兌"), ("巽", "坎"),
    ("離", "兌"), ("巽", "離"), ("震", "震"), ("艮", "艮"), ("艮", "巽"), ("兌", "震"),
    ("離", "震"), ("艮", "離"), ("巽", "巽"), ("兌", "兌"), ("坎", "巽"), ("兌", "坎"),
    ("兌", "巽"), ("艮", "震"), ("離", "坎"), ("坎", "離"),
]

LINES_TO_HEX = {
    TRIGRAMS[lower] + TRIGRAMS[upper]: chr(0x4DC0 + i)
    for i, (lower, upper) in enumerate(KING_WEN)
}
HEX_TO_LINES = {h: bits for bits, h in LINES_TO_HEX.items()}
assert len(LINES_TO_HEX) == 64


def xor(data, key):
    return bytes(b ^ key[i % len(key)] for i, b in enumerate(data))


def layout(text, group=8, per_line=6):
    groups = [text[i:i + group] for i in range(0, len(text), group)]
    return "\n".join(" ".join(groups[i:i + per_line]) for i in range(0, len(groups), per_line))


def encrypt(plaintext, key):
    data = xor(plaintext.encode("utf-8"), key.encode("utf-8"))
    bits = "".join(f"{b:08b}" for b in data)
    bits += "0" * (-len(bits) % 6)
    return layout("".join(LINES_TO_HEX[bits[i:i + 6]] for i in range(0, len(bits), 6)))


def decrypt(ciphertext, key):
    bits = "".join(HEX_TO_LINES[ch] for ch in ciphertext if ch in HEX_TO_LINES)
    data = bytes(int(bits[i:i + 8], 2) for i in range(0, len(bits) // 8 * 8, 8))
    return xor(data, key.encode("utf-8")).decode("utf-8")


def main():
    if len(sys.argv) != 3 or sys.argv[1] not in ("encrypt", "decrypt"):
        sys.exit(__doc__)
    mode, key = sys.argv[1], sys.argv[2]
    text = sys.stdin.read()
    if mode == "encrypt":
        print(encrypt(text, key))
    else:
        sys.stdout.write(decrypt(text, key))


if __name__ == "__main__":
    main()
