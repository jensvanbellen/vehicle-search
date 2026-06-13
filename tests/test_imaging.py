"""Perceptual-hash tests — images generated in-memory, never fetched."""

from __future__ import annotations

from io import BytesIO

from PIL import Image

from vehicle_finder.imaging import count_near_identical, hamming, phash_bytes

SIZE = 64


def _encode(pixels: list[tuple[int, int, int]], fmt: str, **kw: int) -> bytes:
    img = Image.new("RGB", (SIZE, SIZE))
    img.putdata(pixels)
    buf = BytesIO()
    img.save(buf, format=fmt, **kw)
    return buf.getvalue()


def _gradient() -> list[tuple[int, int, int]]:
    return [
        (min(255, x * 4), min(255, x * 4), min(255, x * 4))
        for _y in range(SIZE)
        for x in range(SIZE)
    ]


def _checker() -> list[tuple[int, int, int]]:
    return [
        (255, 255, 255) if (x // 8 + y // 8) % 2 == 0 else (0, 0, 0)
        for y in range(SIZE)
        for x in range(SIZE)
    ]


def test_identical_images_hash_equal() -> None:
    data = _encode(_gradient(), "PNG")
    assert hamming(phash_bytes(data), phash_bytes(data)) == 0


def test_recompressed_photo_is_near_identical_distinct_is_far() -> None:
    grad = _gradient()
    png = phash_bytes(_encode(grad, "PNG"))
    jpeg = phash_bytes(_encode(grad, "JPEG", quality=70))  # same photo, re-compressed
    different = phash_bytes(_encode(_checker(), "PNG"))
    assert hamming(png, jpeg) <= 8  # the cross-post case: same image, different encoding
    assert hamming(png, different) > 8


def test_count_near_identical() -> None:
    a = ["ffffffff00000000", "aaaaaaaa55555555"]
    b = ["ffffffff00000000", "aaaaaaaa55555555", "1234567890abcdef"]
    assert count_near_identical(a, b, max_hamming=0) == 2
    assert count_near_identical(a, [], max_hamming=8) == 0
