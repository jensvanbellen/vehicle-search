"""Perceptual image hashing for duplicate detection (all local, no network).

Dealers reuse the same photos across platforms, so near-identical images are a very
strong cross-post signal. We store per-image pHash hex strings on listings and compare
by Hamming distance. The test suite uses in-memory/precomputed hashes — never live URLs.
"""

from __future__ import annotations

from io import BytesIO
from typing import Any, cast

import imagehash
from PIL import Image


def phash_bytes(data: bytes) -> str:
    """Perceptual hash (hex string) of raw image bytes."""
    with Image.open(BytesIO(data)) as img:
        return str(imagehash.phash(img))


def hamming(hash_a: str, hash_b: str) -> int:
    """Hamming distance between two pHash hex strings (0 = identical)."""
    a = cast("Any", imagehash.hex_to_hash(hash_a))
    b = cast("Any", imagehash.hex_to_hash(hash_b))
    return int(a - b)


def count_near_identical(hashes_a: list[str], hashes_b: list[str], max_hamming: int) -> int:
    """Count images in A that have a near-identical match (<= max_hamming) in B."""
    if not hashes_a or not hashes_b:
        return 0
    matches = 0
    for ha in hashes_a:
        if any(hamming(ha, hb) <= max_hamming for hb in hashes_b):
            matches += 1
    return matches
