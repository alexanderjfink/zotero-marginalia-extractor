"""Page-corner detection and perspective correction for phone photos.

A phone photo of a page is a quadrilateral inside a background. We find the
largest convex four-point contour, order its corners, and warp it to a
rectangle so the rest of the pipeline sees a fronto-parallel page.
"""

from __future__ import annotations

from typing import Optional

import cv2
import numpy as np


def order_quad(points) -> np.ndarray:
    pts = np.asarray(points, dtype=np.float32).reshape(4, 2)
    total = pts.sum(axis=1)
    diff = np.diff(pts, axis=1).reshape(-1)
    top_left = pts[np.argmin(total)]
    bottom_right = pts[np.argmax(total)]
    top_right = pts[np.argmin(diff)]
    bottom_left = pts[np.argmax(diff)]
    return np.array([top_left, top_right, bottom_right, bottom_left], dtype=np.float32)


def detect_page_quad(gray: np.ndarray, min_area_ratio: float = 0.30) -> Optional[np.ndarray]:
    """Return ordered page corners, or None when no clear quad is found."""
    if gray.size == 0:
        return None
    height, width = gray.shape[:2]
    blurred = cv2.GaussianBlur(gray, (5, 5), 0)
    edges = cv2.Canny(blurred, 50, 150)
    edges = cv2.dilate(edges, np.ones((3, 3), np.uint8), iterations=1)
    contours, _ = cv2.findContours(edges, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

    best = None
    best_area = 0.0
    for contour in contours:
        area = cv2.contourArea(contour)
        if area < min_area_ratio * width * height:
            continue
        perimeter = cv2.arcLength(contour, True)
        approx = cv2.approxPolyDP(contour, 0.02 * perimeter, True)
        if len(approx) != 4 or not cv2.isContourConvex(approx):
            continue
        if area > best_area:
            best_area = area
            best = approx
    if best is None:
        return None
    return order_quad(best)


def is_full_frame(quad: np.ndarray, shape, margin_ratio: float = 0.02) -> bool:
    """True when the quad hugs the image border (a flatbed scan, not a photo)."""
    height, width = shape[:2]
    for x, y in np.asarray(quad).reshape(4, 2):
        if (width * margin_ratio < x < width * (1 - margin_ratio)
                and height * margin_ratio < y < height * (1 - margin_ratio)):
            return False
    return True


def warp_page(rgb: np.ndarray, quad: np.ndarray, width: int, height: int) -> np.ndarray:
    destination = np.array(
        [[0, 0], [width - 1, 0], [width - 1, height - 1], [0, height - 1]],
        dtype=np.float32,
    )
    matrix = cv2.getPerspectiveTransform(np.asarray(quad, dtype=np.float32), destination)
    return cv2.warpPerspective(rgb, matrix, (width, height))


def warp_to_portrait(rgb: np.ndarray, quad: np.ndarray, width: int = 1000) -> np.ndarray:
    height = int(width / 0.7727)  # US Letter aspect; close enough for OCR
    return warp_page(rgb, quad, width, height)


def correct_perspective(rgb: np.ndarray, min_area_ratio: float = 0.30,
                        target_width: Optional[int] = None,
                        target_height: Optional[int] = None) -> np.ndarray:
    """Warp a photographed page, leaving flatbed scans untouched."""
    gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
    quad = detect_page_quad(gray, min_area_ratio)
    if quad is None or is_full_frame(quad, gray.shape):
        return rgb
    width = target_width or rgb.shape[1]
    height = target_height or rgb.shape[0]
    return warp_page(rgb, quad, width, height)
