#!/usr/bin/env python3
"""六十四卦密碼 (Hexagram Cipher) — a four-layer keyed cipher.

All key material is derived from a passphrase, so without it the ciphertext
is just a wall of I Ching hexagrams.

  Layer 1  UTF-8        text -> bytes
  Layer 2  影子鏈        c[i] = (p[i] + k[i mod 11] + c[i-1]) mod 256
                         (keyed additive cipher with ciphertext feedback,
                          so every byte is tainted by the one before it)
  Layer 3  洗牌          keyed columnar transposition, 17 columns
  Layer 4  六十四卦      bit stream -> 6-bit groups -> keyed permutation of
                         the 64 hexagrams U+4DC0..U+4DFF

Usage:
  python3 hexagram_cipher.py encrypt PASSPHRASE < plain.txt > cipher.txt
  python3 hexagram_cipher.py decrypt PASSPHRASE < cipher.txt
"""
import hashlib
import random
import sys

KEY_LEN = 11
COLUMNS = 17
HEXAGRAMS = [chr(0x4DC0 + i) for i in range(64)]


def derive_keys(passphrase):
    seed = hashlib.sha256(("hexagram-cipher:" + passphrase).encode()).digest()
    rng = random.Random(seed)
    add_key = [rng.randrange(256) for _ in range(KEY_LEN)]
    iv = rng.randrange(256)
    col_order = list(range(COLUMNS))
    rng.shuffle(col_order)
    alphabet = HEXAGRAMS[:]
    rng.shuffle(alphabet)
    return add_key, iv, col_order, alphabet


def chain_encrypt(data, key, iv):
    out, prev = [], iv
    for i, b in enumerate(data):
        prev = (b + key[i % len(key)] + prev) % 256
        out.append(prev)
    return out


def chain_decrypt(data, key, iv):
    out, prev = [], iv
    for i, c in enumerate(data):
        out.append((c - key[i % len(key)] - prev) % 256)
        prev = c
    return out


def column_lengths(n, order):
    rows, extra = divmod(n, len(order))
    return [rows + (1 if col < extra else 0) for col in range(len(order))]


def transpose(data, order):
    out = []
    for col in order:
        out.extend(data[col::len(order)])
    return out


def untranspose(data, order):
    lengths = column_lengths(len(data), order)
    out = [None] * len(data)
    pos = 0
    for col in order:
        chunk = data[pos:pos + lengths[col]]
        pos += lengths[col]
        out[col::len(order)] = chunk
    return out


def to_hexagrams(data, alphabet):
    bits = "".join(f"{b:08b}" for b in data)
    bits += "0" * (-len(bits) % 6)
    return "".join(alphabet[int(bits[i:i + 6], 2)] for i in range(0, len(bits), 6))


def from_hexagrams(text, alphabet):
    index = {h: i for i, h in enumerate(alphabet)}
    bits = "".join(f"{index[ch]:06b}" for ch in text if ch in index)
    n = len(bits) // 8
    return [int(bits[i * 8:i * 8 + 8], 2) for i in range(n)]


def layout(text, group=8, per_line=6):
    groups = [text[i:i + group] for i in range(0, len(text), group)]
    lines = [" ".join(groups[i:i + per_line]) for i in range(0, len(groups), per_line)]
    return "\n".join(lines)


def encrypt(plaintext, passphrase):
    key, iv, order, alphabet = derive_keys(passphrase)
    data = list(plaintext.encode("utf-8"))
    data = chain_encrypt(data, key, iv)
    data = transpose(data, order)
    return layout(to_hexagrams(data, alphabet))


def decrypt(ciphertext, passphrase):
    key, iv, order, alphabet = derive_keys(passphrase)
    data = from_hexagrams(ciphertext, alphabet)
    data = untranspose(data, order)
    data = chain_decrypt(data, key, iv)
    return bytes(data).decode("utf-8")


def main():
    if len(sys.argv) != 3 or sys.argv[1] not in ("encrypt", "decrypt"):
        sys.exit(__doc__)
    mode, passphrase = sys.argv[1], sys.argv[2]
    text = sys.stdin.read()
    if mode == "encrypt":
        print(encrypt(text, passphrase))
    else:
        sys.stdout.write(decrypt(text, passphrase))


if __name__ == "__main__":
    main()
