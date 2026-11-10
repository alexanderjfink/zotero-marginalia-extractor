"""Scan → PDF page alignment.

The scanner output and the PDF page are two renderings of the same page. We
recover a homography that maps scan pixel coordinates into original-PDF-page
pixel coordinates. ECC (enhanced correlation) is tried first because it is
robust for nearly-identical printed pages; ORB feature matching is the
fallback for pages where ECC struggles.

The returned matrix operates on the *full-resolution* images passed in, even
though alignment runs at a reduced working resolution.
"""

from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np


WORK_WIDTH = 1400
WORK_HEIGHT = 2000


@dataclass
class AlignmentResult:
    matrix: np.ndarray  # 3x3, maps moving(scan) full-res px -> reference(pdf) full-res px
    confidence: float
    method: str  # ecc | orb | identity

    @property
    def ok(self) -> bool:
        return self.confidence >= 0.30


def _scale_matrix(sx: float, sy: float) -> np.ndarray:
    return np.array([[sx, 0.0, 0.0], [0.0, sy, 0.0], [0.0, 0.0, 1.0]], dtype=np.float64)


def _to_work(img: np.ndarray) -> tuple[np.ndarray, float, float]:
    """Resize an image to the fixed working size; return (work, sx, sy).

    sx/sy map full-resolution coordinates to working coordinates.
    """
    h, w = img.shape[:2]
    work = cv2.resize(img, (WORK_WIDTH, WORK_HEIGHT), interpolation=cv2.INTER_AREA)
    return work, WORK_WIDTH / float(w), WORK_HEIGHT / float(h)


def align_pair(ref_gray: np.ndarray, mov_gray: np.ndarray) -> AlignmentResult:
    """Align ``mov_gray`` (scan) onto ``ref_gray`` (rendered PDF page)."""
    ref_work, *_ = _to_work(ref_gray)
    mov_work, a_mx, a_my = _to_work(mov_gray)
    ref_h, ref_w = ref_gray.shape[:2]

    result = _try_ecc(ref_work, mov_work)
    if result is None:
        result = _try_orb(ref_work, mov_work)

    if result is None:
        # Identity still lets same-size / same-DPI scans through.
        return AlignmentResult(np.eye(3), 0.10, "identity")

    h_work, confidence, method = result

    # Work coordinates -> full-resolution coordinates.
    #   A_mov = diag(a_mx, a_my, 1) maps full-mov pixels -> work pixels
    #   B_ref = diag(ref_w/W, ref_h/H, 1) maps work-ref pixels -> full-ref pixels
    # so the full-resolution transform is B_ref @ H_work @ A_mov.
    s_mov = _scale_matrix(a_mx, a_my)  # full mov -> work
    s_ref = _scale_matrix(ref_w / WORK_WIDTH, ref_h / WORK_HEIGHT)  # work -> full ref
    h_full = s_ref @ h_work @ s_mov
    return AlignmentResult(h_full, float(confidence), method)


def _try_ecc(ref: np.ndarray, mov: np.ndarray):
    # Blur slightly to suppress paper texture and handwriting.
    ref_b = cv2.GaussianBlur(ref, (5, 5), 0)
    mov_b = cv2.GaussianBlur(mov, (5, 5), 0)
    warp = np.eye(3, dtype=np.float32)
    criteria = (
        cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_COUNT,
        300,
        1e-6,
    )
    try:
        cc, warp = cv2.findTransformECC(
            ref_b,
            mov_b,
            warp,
            cv2.MOTION_HOMOGRAPHY,
            criteria,
            None,
            5,
        )
    except cv2.error:
        return None
    if not np.isfinite(cc):
        return None
    # ECC correlation is in [-1, 1]; map the useful upper range to [0, 1].
    confidence = max(0.0, min(1.0, (float(cc) - 0.2) / 0.8))
    return warp.astype(np.float64), confidence, "ecc"


def _try_orb(ref: np.ndarray, mov: np.ndarray):
    orb = cv2.ORB_create(nfeatures=4000, fastThreshold=7)
    kp_ref, des_ref = orb.detectAndCompute(ref, None)
    kp_mov, des_mov = orb.detectAndCompute(mov, None)
    if des_ref is None or des_mov is None or len(kp_ref) < 12 or len(kp_mov) < 12:
        return None

    matcher = cv2.BFMatcher(cv2.NORM_HAMMING)
    try:
        raw = matcher.knnMatch(des_mov, des_ref, k=2)
    except cv2.error:
        return None

    good = []
    for pair in raw:
        if len(pair) < 2:
            continue
        m, n = pair
        if m.distance < 0.75 * n.distance:
            good.append(m)
    if len(good) < 10:
        return None

    src = np.float32([kp_mov[m.queryIdx].pt for m in good]).reshape(-1, 1, 2)
    dst = np.float32([kp_ref[m.trainIdx].pt for m in good]).reshape(-1, 1, 2)
    h, mask = cv2.findHomography(src, dst, cv2.RANSAC, 5.0)
    if h is None:
        return None
    inliers = int(mask.sum()) if mask is not None else 0
    confidence = min(1.0, inliers / max(1, len(good)))
    if confidence < 0.25:
        return None
    return h.astype(np.float64), confidence, "orb"


def warp_to_ref(image: np.ndarray, matrix: np.ndarray, ref_shape: tuple[int, int]) -> np.ndarray:
    """Warp ``image`` (full-res scan) into ``ref_shape`` using ``matrix``."""
    return cv2.warpPerspective(image, matrix, (ref_shape[1], ref_shape[0]))
