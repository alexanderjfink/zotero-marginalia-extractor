"""Cheap page fingerprints for matching scan pages to PDF pages.

The scanner output and the PDF are two renderings of the same page, so a
perceptual hash of the rendered page is a reliable, fast way to find which PDF
page a given scan page belongs to. This lets the extractor handle scans that
contain only the annotated pages, reordered pages, or a front-matter offset.
"""

from __future__ import annotations

import cv2
import numpy as np


def dhash(gray: np.ndarray, hash_size: int = 8) -> int:
    """Difference hash of a grayscale image, as a Python int."""
    resized = cv2.resize(gray, (hash_size + 1, hash_size), interpolation=cv2.INTER_AREA)
    diff = resized[:, 1:] > resized[:, :-1]
    value = 0
    for bit in diff.flatten():
        value = (value << 1) | int(bit)
    return value


def layout_hash(gray: np.ndarray, grid: int = 16) -> int | None:
    """Hash the ink-density layout of a page.

    Plain dHash on a text page averages the text away, so two different pages
    can hash identically. This thresholds the page to an ink mask first, then
    hashes the relative density of a coarse grid, which captures paragraph and
    line layout. Returns None for an effectively blank page.
    """
    if gray.size == 0:
        return None
    _, ink = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    if int(ink.sum()) < 255 * max(50, gray.size // 1000):
        return None
    density = cv2.resize(ink, (grid, grid), interpolation=cv2.INTER_AREA).astype(np.float32)
    median = float(np.median(density))
    bits = (density > median).flatten()
    value = 0
    for bit in bits:
        value = (value << 1) | int(bit)
    return value


def hamming(a: int, b: int) -> int:
    return int((a ^ b).bit_count())


def best_match(
    scan_hash: int,
    pdf_hashes: list[tuple[int, int]],
    max_distance: int = 13,
) -> tuple[int, int] | None:
    """Return (pdf_page_index, distance) for the closest PDF page, if close enough."""
    best_index = -1
    best_distance = 10_000
    for page_index, pdf_hash in pdf_hashes:
        distance = hamming(scan_hash, pdf_hash)
        if distance < best_distance:
            best_distance = distance
            best_index = page_index
    if best_index < 0 or best_distance > max_distance:
        return None
    return best_index, best_distance
