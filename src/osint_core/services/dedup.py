"""Near-duplicate detection using SimHash."""
from __future__ import annotations

import hashlib
import re

_STOPWORDS = frozenset(
    [
        "a", "an", "the", "and", "or", "but", "in", "on", "at", "to",
        "for", "of", "is", "it", "this", "that", "with", "from", "by", "as",
    ]
)


def normalize_title(title: str | None) -> str:
    if not title:
        return ""
    text = title.lower().strip()
    text = re.sub(r"[^\w\s]", "", text)
    return text


def _shingle(text: str, n: int = 3) -> list[str]:
    words = [w for w in text.split() if w not in _STOPWORDS]
    if len(words) < n:
        return [" ".join(words)] if words else []
    return [" ".join(words[i : i + n]) for i in range(len(words) - n + 1)]


def compute_simhash(text: str, bits: int = 64) -> int:
    text = normalize_title(text)
    shingles = _shingle(text)
    if not shingles:
        return 0

    v = [0] * bits
    for shingle in shingles:
        h = int(hashlib.md5(shingle.encode()).hexdigest(), 16) % (2**bits)
        for i in range(bits):
            if h & (1 << i):
                v[i] += 1
            else:
                v[i] -= 1

    result = 0
    for i in range(bits):
        if v[i] > 0:
            result |= 1 << i
    return result


def simhash_distance(h1: int, h2: int) -> int:
    return bin(h1 ^ h2).count("1")
