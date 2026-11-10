"""Connector detection between margin notes and body text.

Supported connectors, in rough priority order:

* straight lines / arrows (probabilistic Hough transform),
* curved strokes (elongated contours, farthest-pair endpoints),
* vertical brackets in the margin (target = the text edge at the bracket's
  vertical centre).

The association step turns each connector into a target point for the note.
"""

from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np

from .util import Rect, point_rect_distance, rect_center


@dataclass
class LineSegment:
    p0: tuple[float, float]
    p1: tuple[float, float]
    length: float


@dataclass
class Connector:
    p0: tuple[float, float]
    p1: tuple[float, float]
    length: float
    kind: str  # line | curve | bracket


@dataclass
class LineTarget:
    point: tuple[float, float]
    connector: Connector
    confidence: float
    note_index: int


_KIND_WEIGHT = {"line": 1.0, "curve": 0.9, "bracket": 0.78}


def detect_line_segments(
    ink: np.ndarray,
    note_rects: list[Rect] | None = None,
    min_length: float = 45.0,
    max_gap: float = 10,
) -> list[LineSegment]:
    work = _remove_notes(ink, note_rects)
    work = cv2.morphologyEx(work, cv2.MORPH_OPEN, np.ones((2, 2), np.uint8))
    lines = cv2.HoughLinesP(
        work,
        rho=1,
        theta=np.pi / 360,
        threshold=25,
        minLineLength=int(min_length),
        maxLineGap=max_gap,
    )
    segments: list[LineSegment] = []
    if lines is None:
        return segments
    for raw in np.asarray(lines).reshape(-1, 4):
        x0, y0, x1, y1 = (float(v) for v in raw)
        length = float(np.hypot(x1 - x0, y1 - y0))
        if length >= min_length:
            segments.append(LineSegment((x0, y0), (x1, y1), length))
    return segments


def detect_connector_candidates(
    ink: np.ndarray,
    note_rects: list[Rect] | None = None,
    text_bbox: Rect | None = None,
) -> list[Connector]:
    connectors = [
        Connector(seg.p0, seg.p1, seg.length, "line")
        for seg in detect_line_segments(ink, note_rects)
    ]

    work = _remove_notes(ink, note_rects)
    contours, _ = cv2.findContours(work, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    for contour in contours:
        x, y, w, h = cv2.boundingRect(contour)
        area = cv2.contourArea(contour)
        if area < 40 or (w < 8 and h < 8):
            continue

        # Vertical bracket in the margin: point at the text edge, at the
        # bracket's vertical centre.
        if h >= 3 * max(1, w) and h >= 30 and text_bbox is not None:
            center_x = x + w / 2.0
            if center_x < text_bbox[0]:
                target_x = text_bbox[0]
            elif center_x > text_bbox[2]:
                target_x = text_bbox[2]
            else:
                target_x = center_x
            connectors.append(
                Connector(
                    (center_x, float(y)),
                    (target_x, float(y + h / 2.0)),
                    float(h),
                    "bracket",
                )
            )
            continue

        aspect = max(w, h) / max(1, min(w, h))
        is_open_stroke = area < 0.12 * w * h and max(w, h) > 30
        if aspect < 3 and not is_open_stroke:
            continue

        points = contour.reshape(-1, 2).astype(np.float32)
        hull = cv2.convexHull(points).reshape(-1, 2).astype(np.float32)
        if len(hull) < 2:
            continue
        best_distance = 0.0
        best_pair = None
        for i in range(len(hull)):
            for j in range(i + 1, len(hull)):
                distance = float(np.linalg.norm(hull[i] - hull[j]))
                if distance > best_distance:
                    best_distance = distance
                    best_pair = (hull[i], hull[j])
        if best_pair and best_distance >= 25:
            connectors.append(
                Connector(
                    (float(best_pair[0][0]), float(best_pair[0][1])),
                    (float(best_pair[1][0]), float(best_pair[1][1])),
                    best_distance,
                    "curve",
                )
            )
    return connectors


def _remove_notes(ink: np.ndarray, note_rects: list[Rect] | None) -> np.ndarray:
    work = ink.copy()
    if note_rects:
        for x0, y0, x1, y1 in note_rects:
            cv2.rectangle(
                work,
                (int(x0) - 2, int(y0) - 2),
                (int(x1) + 2, int(y1) + 2),
                0,
                thickness=-1,
            )
    return work


def associate_notes_to_points(
    note_rects: list[Rect],
    connectors: list[Connector],
    text_bbox: Rect | None,
    image_width: float,
) -> dict[int, LineTarget]:
    """For each note, pick the connector whose far end points into the text."""
    targets: dict[int, LineTarget] = {}
    if not connectors:
        return targets

    for index, note in enumerate(note_rects):
        _cx, _cy = rect_center(note)
        note_diag = max(30.0, float(np.hypot(note[2] - note[0], note[3] - note[1])))
        attach_radius = note_diag * 1.5 + 25.0

        best: LineTarget | None = None
        for connector in connectors:
            d0 = point_rect_distance(connector.p0, note)
            d1 = point_rect_distance(connector.p1, note)
            if d0 <= d1:
                far, near_d, far_d = connector.p1, d0, d1
            else:
                far, near_d, far_d = connector.p0, d1, d0
            if near_d > attach_radius:
                continue
            if far_d < note_diag:
                continue

            if text_bbox is not None:
                to_text = point_rect_distance(far, text_bbox)
                reach = max(0.0, 1.0 - to_text / (image_width * 0.5))
            else:
                reach = 0.5
            strength = min(1.0, connector.length / (note_diag * 4.0))
            confidence = float(
                np.clip(
                    _KIND_WEIGHT.get(connector.kind, 0.8)
                    * (0.4 * strength + 0.6 * reach),
                    0.0,
                    1.0,
                )
            )
            candidate = LineTarget(
                point=far, connector=connector, confidence=confidence, note_index=index
            )
            if best is None or candidate.confidence > best.confidence:
                best = candidate

        if best is not None:
            targets[index] = best
    return targets
