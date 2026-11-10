"""Small geometry / image helpers used across the pipeline."""

from __future__ import annotations

import os
import re
import unicodedata
from typing import Iterable, Sequence

import numpy as np


Point = tuple[float, float]
Rect = tuple[float, float, float, float]  # x0, y0, x1, y1


def normalize_text(text: str) -> str:
    """Normalise PDF/OCR text: ligatures, line-break hyphenation, whitespace."""
    if not text:
        return ""
    text = unicodedata.normalize("NFKC", text)
    text = re.sub(r"(\w)-\s+(\w)", r"\1\2", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def ensure_dir(path: str | None) -> str | None:
    if not path:
        return None
    os.makedirs(path, exist_ok=True)
    return path


def union_rects(rects: Sequence[Rect]) -> Rect:
    xs0 = min(r[0] for r in rects)
    ys0 = min(r[1] for r in rects)
    xs1 = max(r[2] for r in rects)
    ys1 = max(r[3] for r in rects)
    return (xs0, ys0, xs1, ys1)


def rect_intersection(a: Rect, b: Rect) -> float:
    """Area of the intersection of two axis-aligned rectangles."""
    ix0 = max(a[0], b[0])
    iy0 = max(a[1], b[1])
    ix1 = min(a[2], b[2])
    iy1 = min(a[3], b[3])
    if ix1 <= ix0 or iy1 <= iy0:
        return 0.0
    return (ix1 - ix0) * (iy1 - iy0)


def rect_area(r: Rect) -> float:
    return max(0.0, r[2] - r[0]) * max(0.0, r[3] - r[1])


def rect_center(r: Rect) -> Point:
    return ((r[0] + r[2]) / 2.0, (r[1] + r[3]) / 2.0)


def point_rect_distance(p: Point, r: Rect) -> float:
    dx = max(r[0] - p[0], 0.0, p[0] - r[2])
    dy = max(r[1] - p[1], 0.0, p[1] - r[3])
    return float(np.hypot(dx, dy))


def rect_distance(a: Rect, b: Rect) -> float:
    """Shortest distance between two axis-aligned rectangles (0 if overlapping)."""
    dx = max(a[0] - b[2], 0.0, b[0] - a[2])
    dy = max(a[1] - b[3], 0.0, b[1] - a[3])
    return float(np.hypot(dx, dy))


def transform_points(points: np.ndarray, matrix: np.ndarray) -> np.ndarray:
    """Apply a 3x3 homography to an (N, 2) array of points."""
    pts = np.asarray(points, dtype=np.float64)
    if pts.ndim != 2 or pts.shape[1] != 2:
        raise ValueError("points must be (N, 2)")
    homog = np.hstack([pts, np.ones((pts.shape[0], 1), dtype=np.float64)])
    out = homog @ matrix.T
    w = out[:, 2:3]
    w = np.where(np.abs(w) < 1e-9, 1e-9, w)
    return out[:, :2] / w


def transformed_bbox(rect: Rect, matrix: np.ndarray) -> Rect:
    """Bounding box of a transformed rectangle (handles rotation/skew)."""
    x0, y0, x1, y1 = rect
    corners = np.array(
        [[x0, y0], [x1, y0], [x1, y1], [x0, y1]], dtype=np.float64
    )
    tp = transform_points(corners, matrix)
    return (
        float(tp[:, 0].min()),
        float(tp[:, 1].min()),
        float(tp[:, 0].max()),
        float(tp[:, 1].max()),
    )


def image_rect_to_pdf_rect(rect: Rect, scale: float, page_height_pts: float) -> list[float]:
    """Convert an image-space bbox (top-left origin) to Zotero PDF coords.

    ``scale`` is pixels-per-point (dpi / 72). Zotero stores annotation rects
    with a bottom-left origin, so the y axis is flipped here.
    """
    x0, y0, x1, y1 = rect
    px0 = x0 / scale
    px1 = x1 / scale
    py0 = page_height_pts - (y0 / scale)
    py1 = page_height_pts - (y1 / scale)
    return [
        round(min(px0, px1), 3),
        round(min(py0, py1), 3),
        round(max(px0, px1), 3),
        round(max(py0, py1), 3),
    ]


def clamp_rect_to_page(rect: Rect, width: float, height: float) -> Rect:
    return (
        max(0.0, min(rect[0], width)),
        max(0.0, min(rect[1], height)),
        max(0.0, min(rect[2], width)),
        max(0.0, min(rect[3], height)),
    )
