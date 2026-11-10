"""Colour and ink segmentation on a scan warped into the PDF page frame.

The input image has already been aligned/warped so that (0, 0) is the top-left
of the rendered PDF page. Every rectangle returned here is therefore directly
convertible to PDF points by dividing by ``dpi / 72``.
"""

from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np

from .models import ColorRule
from .util import Rect, rect_distance, union_rects

DARK_INK_MAX_VAL = 120  # pixels darker than this may be pen ink
MIN_UNDERLINE_LEN = 40
HORIZONTAL_KERNEL = cv2.getStructuringElement(cv2.MORPH_RECT, (25, 1))


@dataclass
class ColorRegion:
    rule: ColorRule
    rect: Rect
    area: float
    kind: str = "highlighter"  # highlighter | pen


def rgb_to_hsv(rgb: np.ndarray) -> np.ndarray:
    return cv2.cvtColor(rgb, cv2.COLOR_RGB2HSV)


def white_balance(rgb: np.ndarray) -> np.ndarray:
    """Gray-world white balance.

    Scanners and phone cameras cast a colour onto the paper; without this the
    HSV ranges drift and highlights are missed or mis-classified.
    """
    arr = rgb.astype(np.float32)
    means = arr.reshape(-1, 3).mean(axis=0)
    gray = float(means.mean())
    if gray <= 1e-6:
        return rgb
    gains = gray / np.maximum(means, 1e-6)
    balanced = np.clip(arr * gains, 0, 255).astype(np.uint8)
    return balanced


def normalize_illumination(rgb: np.ndarray) -> np.ndarray:
    """Remove gutter shadows and lighting gradients from a page image.

    A large morphological close approximates the paper background; dividing by
    it flattens shadows near a book spine and uneven phone-photo lighting.
    """
    gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (61, 61))
    background = cv2.morphologyEx(gray, cv2.MORPH_CLOSE, kernel)
    background = cv2.GaussianBlur(background, (0, 0), 15)
    background = np.maximum(background.astype(np.float32), 1.0)
    level = float(np.median(background)) or 255.0
    corrected = rgb.astype(np.float32) / background[..., None] * level
    return np.clip(corrected, 0, 255).astype(np.uint8)


def estimate_skew(gray: np.ndarray, max_angle: float = 12.0) -> float:
    """Median angle of long near-horizontal lines, in degrees."""
    height, width = gray.shape[:2]
    edges = cv2.Canny(gray, 50, 150)
    lines = cv2.HoughLinesP(
        edges, 1, np.pi / 180, threshold=80,
        minLineLength=max(40, int(width * 0.25)), maxLineGap=20,
    )
    if lines is None:
        return 0.0
    angles: list[float] = []
    for x0, y0, x1, y1 in np.asarray(lines).reshape(-1, 4):
        angle = float(np.degrees(np.arctan2(y1 - y0, x1 - x0)))
        if abs(angle) <= max_angle:
            angles.append(angle)
    if not angles:
        return 0.0
    angles.sort()
    return angles[len(angles) // 2]


def deskew(rgb: np.ndarray, max_angle: float = 12.0) -> np.ndarray:
    """Rotate a page by the median text-line angle when it is visibly skewed."""
    gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
    angle = estimate_skew(gray, max_angle)
    if abs(angle) < 0.3:
        return rgb
    height, width = rgb.shape[:2]
    matrix = cv2.getRotationMatrix2D((width / 2.0, height / 2.0), angle, 1.0)
    return cv2.warpAffine(
        rgb, matrix, (width, height),
        flags=cv2.INTER_CUBIC, borderMode=cv2.BORDER_REPLICATE,
    )


def _rule_reference_lab(rule: ColorRule) -> np.ndarray:
    """A representative Lab colour for a rule, used for nearest-colour matching."""
    hue = (rule.hue_min + rule.hue_max) / 2.0
    sat = min(255, max(rule.sat_min, (rule.sat_min + 255) / 2))
    val = 150 if rule.kind == "pen" else 225
    hsv = np.array([[[hue, sat, val]]], dtype=np.uint8)
    rgb = cv2.cvtColor(hsv, cv2.COLOR_HSV2RGB)
    return cv2.cvtColor(rgb, cv2.COLOR_RGB2LAB).reshape(3).astype(np.float32)


def assign_rule_lab(rgb: np.ndarray, mask: np.ndarray, colors: list[ColorRule]) -> ColorRule | None:
    """Pick the configured colour whose reference is nearest the masked pixels."""
    if not mask.any():
        return None
    lab = cv2.cvtColor(rgb, cv2.COLOR_RGB2LAB).astype(np.float32)
    pixels = lab[mask > 0]
    if pixels.size == 0:
        return None
    mean = pixels.mean(axis=0)
    best_rule = None
    best_distance = float("inf")
    for rule in colors:
        if not rule.enabled:
            continue
        ref = _rule_reference_lab(rule)
        distance = float(np.linalg.norm(mean - ref))
        if distance < best_distance:
            best_distance = distance
            best_rule = rule
    return best_rule


def color_mask(hsv: np.ndarray, rule: ColorRule) -> np.ndarray:
    """Binary mask of pixels matching a colour rule, handling hue wrap."""
    h, s, v = hsv[:, :, 0], hsv[:, :, 1], hsv[:, :, 2]
    if rule.hue_min <= rule.hue_max:
        hue_ok = (h >= rule.hue_min) & (h <= rule.hue_max)
    else:  # wraps around 0 (e.g. red)
        hue_ok = (h >= rule.hue_min) | (h <= rule.hue_max)
    sat_ok = (s >= rule.sat_min) & (s <= rule.sat_max)
    val_ok = (v >= rule.val_min) & (v <= rule.val_max)
    mask = (hue_ok & sat_ok & val_ok).astype(np.uint8) * 255
    return mask


def detect_color_regions(rgb: np.ndarray, colors: list[ColorRule], min_area: float = 40) -> list[ColorRegion]:
    """Find coloured blobs, assigning each pixel to the first matching rule."""
    hsv = rgb_to_hsv(rgb)
    regions: list[ColorRegion] = []
    claimed = np.zeros(rgb.shape[:2], dtype=np.uint8)

    for rule in colors:
        if not rule.enabled:
            continue
        mask = color_mask(hsv, rule)
        mask[claimed > 0] = 0
        mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((3, 3), np.uint8))
        mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))
        if not mask.any():
            continue
        count, labels, stats, _centroids = cv2.connectedComponentsWithStats(mask, 8)
        for label in range(1, count):
            x, y, w, h, area = stats[label]
            if area < min_area:
                continue
            kind = rule.kind if rule.kind != "any" else _classify_kind(area, w, h)
            regions.append(
                ColorRegion(rule=rule, rect=(float(x), float(y), float(x + w), float(y + h)), area=float(area), kind=kind)
            )
            claimed[labels == label] = 255
    return regions


def refine_region_rule(rgb: np.ndarray, rect: Rect, colors: list[ColorRule]) -> ColorRule | None:
    """Re-assign a region's colour using Lab nearest-match over its pixels.

    HSV thresholds get a region into the candidate set; this second pass makes
    the final colour robust to scanner white balance and overlapping ranges.
    """
    h, w = rgb.shape[:2]
    x0 = max(0, int(rect[0]))
    y0 = max(0, int(rect[1]))
    x1 = min(w, int(rect[2]))
    y1 = min(h, int(rect[3]))
    if x1 <= x0 or y1 <= y0:
        return None
    sub = rgb[y0:y1, x0:x1]
    hsv = rgb_to_hsv(sub)
    union = np.zeros(sub.shape[:2], dtype=np.uint8)
    for rule in colors:
        if rule.enabled:
            union = cv2.bitwise_or(union, color_mask(hsv, rule))
    return assign_rule_lab(sub, union, colors)


def _classify_kind(area: float, w: int, h: int) -> str:
    if h <= 8 and w >= 30:
        return "pen"
    if w >= 3 * max(1, h) or (w > 60 and h < 22):
        return "highlighter"
    return "pen"


def merge_regions(rects: list[Rect], max_gap: float, min_x_overlap: float = 0.25) -> list[Rect]:
    """Merge rectangles stacked vertically that share horizontal extent.

    A single highlighter stroke spanning several lines shows up as several
    blobs separated by the inter-line whitespace; this joins them back.
    """
    remaining = list(rects)
    merged: list[Rect] = []
    while remaining:
        current = remaining.pop(0)
        changed = True
        while changed:
            changed = False
            for i, other in enumerate(remaining):
                if _should_merge(current, other, max_gap, min_x_overlap):
                    current = union_rects([current, other])
                    remaining.pop(i)
                    changed = True
                    break
        merged.append(current)
    return merged


def _should_merge(a: Rect, b: Rect, max_gap: float, min_x_overlap: float) -> bool:
    ax0, ay0, ax1, ay1 = a
    bx0, by0, bx1, by1 = b
    # Horizontal overlap fraction relative to the narrower rect.
    overlap = max(0.0, min(ax1, bx1) - max(ax0, bx0))
    narrower = max(1.0, min(ax1 - ax0, bx1 - bx0))
    if overlap / narrower < min_x_overlap:
        return False
    if by0 > ay1:
        gap = by0 - ay1
    elif ay0 > by1:
        gap = ay0 - by1
    else:
        return True  # vertical overlap
    return gap <= max_gap


def ink_mask(rgb: np.ndarray) -> np.ndarray:
    """Binary mask of dark ink (printed text + handwriting)."""
    gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
    binary = cv2.adaptiveThreshold(
        gray, 255, cv2.ADAPTIVE_THRESH_MEAN_C, cv2.THRESH_BINARY_INV, 31, 12
    )
    # Also catch genuinely dark pixels regardless of local contrast.
    _, very_dark = cv2.threshold(gray, DARK_INK_MAX_VAL, 255, cv2.THRESH_BINARY_INV)
    mask = cv2.bitwise_or(binary, very_dark)
    return cv2.morphologyEx(mask, cv2.MORPH_OPEN, np.ones((2, 2), np.uint8))


def mask_out_rects(mask: np.ndarray, rects: list[Rect], expand: int = 3) -> np.ndarray:
    out = mask.copy()
    for x0, y0, x1, y1 in rects:
        cv2.rectangle(
            out,
            (int(x0) - expand, int(y0) - expand),
            (int(x1) + expand, int(y1) + expand),
            0,
            thickness=-1,
        )
    return out


def component_rects(mask: np.ndarray, min_area: float = 60) -> list[Rect]:
    count, _labels, stats, _centroids = cv2.connectedComponentsWithStats(mask, 8)
    rects: list[Rect] = []
    for label in range(1, count):
        x, y, w, h, area = stats[label]
        if area < min_area:
            continue
        rects.append((float(x), float(y), float(x + w), float(y + h)))
    return rects


def find_underlines(mask: np.ndarray, min_length: int = MIN_UNDERLINE_LEN) -> list[Rect]:
    """Extract long, thin horizontal strokes (underlines)."""
    horizontal = cv2.morphologyEx(mask, cv2.MORPH_OPEN, HORIZONTAL_KERNEL)
    rects = component_rects(horizontal, min_area=min_length)
    result: list[Rect] = []
    for x0, y0, x1, y1 in rects:
        w = x1 - x0
        h = max(1.0, y1 - y0)
        if w >= min_length and (w / h) >= 8.0:
            result.append((x0, y0, x1, y1))
    return result


def find_margin_blobs(
    ink: np.ndarray,
    text_bbox: Rect | None,
    page_width: float,
    margin_fraction: float,
    min_area: float = 60,
) -> list[Rect]:
    """Candidate handwritten marks restricted to the page margins.

    When the printed text block is known, a margin is anything to the left or
    right of it (with a small tolerance). Otherwise fall back to a fraction of
    the page width on each side.
    """
    if text_bbox is not None:
        left_limit = text_bbox[0]
        right_limit = text_bbox[2]
    else:
        left_limit = page_width * margin_fraction
        right_limit = page_width * (1.0 - margin_fraction)

    rects = component_rects(ink, min_area=min_area)
    margin: list[Rect] = []
    for x0, y0, x1, y1 in rects:
        # A mark counts as marginal if its centre lies outside the text block.
        cx = 0.5 * (x0 + x1)
        if cx < left_limit or cx > right_limit:
            margin.append((x0, y0, x1, y1))
    return margin


def cluster_word_like(rects: list[Rect], max_gap: float = 22.0) -> list[Rect]:
    """Group nearby blobs (letters, strokes, words) into compact clusters.

    Unlike :func:`merge_regions` (which joins vertically-stacked highlight
    lines that share horizontal extent), this merges in any direction so the
    individual letters of a handwritten word form one note region.
    """
    if not rects:
        return []
    result = _cluster_once(rects, max_gap)
    # A merge can cascade (A-B close, B-C close); repeat until stable.
    while len(result) < len(rects):
        rects = result
        result = _cluster_once(rects, max_gap)
    return result


def _cluster_once(rects: list[Rect], gap: float) -> list[Rect]:
    result: list[Rect] = []
    for rect in rects:
        for i, existing in enumerate(result):
            if _boxes_near(existing, rect, gap):
                result[i] = union_rects([existing, rect])
                break
        else:
            result.append(rect)
    return result


def _boxes_near(a: Rect, b: Rect, gap: float) -> bool:
    return not (
        b[0] > a[2] + gap
        or b[2] < a[0] - gap
        or b[1] > a[3] + gap
        or b[3] < a[1] - gap
    )


def touches_border(rect: Rect, width: float, height: float, margin: float = 4.0) -> bool:
    """True when a component runs along the very edge of the image.

    Scanner output often has a black border / shadow line along one edge; those
    components are not annotations.
    """
    x0, y0, x1, y1 = rect
    return x0 <= margin or y0 <= margin or x1 >= width - margin or y1 >= height - margin


def is_line_like(rect: Rect, max_thickness: float = 16.0, min_aspect: float = 6.0) -> bool:
    """True for long, thin strokes (drawn connector lines / arrows)."""
    w = max(1.0, rect[2] - rect[0])
    h = max(1.0, rect[3] - rect[1])
    thickness = min(w, h)
    aspect = max(w, h) / thickness
    return thickness <= max_thickness and aspect >= min_aspect


def strip_border(mask: np.ndarray, margin: int = 6) -> np.ndarray:
    out = mask.copy()
    if margin > 0:
        out[:margin, :] = 0
        out[-margin:, :] = 0
        out[:, :margin] = 0
        out[:, -margin:] = 0
    return out


def nearest(rect: Rect, candidates: list[Rect]) -> tuple[int, float]:
    if not candidates:
        return -1, float("inf")
    distances = [rect_distance(rect, c) for c in candidates]
    idx = int(np.argmin(distances))
    return idx, distances[idx]
