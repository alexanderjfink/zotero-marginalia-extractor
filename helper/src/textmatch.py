"""Map detected scan regions back onto PDF text.

Two jobs:

* For a coloured highlight region, find the printed words it covers and build
  per-line rectangles (Zotero's annotation geometry).
* For a margin note, find the sentence it refers to using, in order: a drawn
  line target point, vertical alignment, then nearest proximity.
"""

from __future__ import annotations

from dataclasses import dataclass

from .pdf_pages import PageText, Sentence, Word, _line_rect
from .util import Rect, rect_center, rect_distance, point_rect_distance, normalize_text


@dataclass
class Target:
    sentence: Sentence
    method: str  # line | vertical | proximity
    confidence: float
    anchor_word: Word | None = None


def image_rect_to_points(rect: Rect, scale: float) -> Rect:
    return (rect[0] / scale, rect[1] / scale, rect[2] / scale, rect[3] / scale)


def words_in_rect(page_text: PageText, rect: Rect, min_overlap: float = 0.15) -> list[Word]:
    hits: list[Word] = []
    for word in page_text.words:
        x0, y0, x1, y1 = word.rect
        ix0 = max(rect[0], x0)
        iy0 = max(rect[1], y0)
        ix1 = min(rect[2], x1)
        iy1 = min(rect[3], y1)
        if ix1 <= ix0 or iy1 <= iy0:
            continue
        inter = (ix1 - ix0) * (iy1 - iy0)
        area = max(1e-6, (x1 - x0) * (y1 - y0))
        if inter / area >= min_overlap or (y0 >= rect[1] and y1 <= rect[3]):
            hits.append(word)
    return hits


def words_to_line_rects(words: list[Word]) -> list[Rect]:
    by_line: dict[tuple[int, int], list[Word]] = {}
    for word in words:
        by_line.setdefault((word.block, word.line), []).append(word)
    rects: list[Rect] = []
    for _key, line_words in sorted(by_line.items(), key=lambda kv: (kv[0][0], kv[0][1])):
        rects.append(_line_rect(line_words))
    return rects


def words_to_text(words: list[Word]) -> str:
    ordered = sorted(words, key=lambda w: w.offset)
    return normalize_text(" ".join(w.text for w in ordered))


def words_for_underline(page_text: PageText, rect: Rect, max_gap: float = 30.0) -> list[Word]:
    """Find the text line sitting just above an underline stroke.

    Underlines are drawn below the baseline, so they do not overlap the word
    boxes we need to annotate. We locate the nearest line above the stroke
    whose horizontal span overlaps it.
    """
    x0, _y0, x1, _y1 = rect
    best_line: list[Word] | None = None
    best_gap = float("inf")
    for line in page_text.lines:
        line_rect = _line_rect(line)
        overlap = min(x1, line_rect[2]) - max(x0, line_rect[0])
        if overlap <= 0:
            continue
        gap = rect[1] - line_rect[3]  # positive when the stroke is below the line
        if gap < -8.0 or gap > max_gap:
            continue
        if gap < best_gap:
            best_gap = gap
            best_line = line
    return best_line or []


def sentence_for_word(page_text: PageText, word: Word) -> Sentence | None:
    for sentence in page_text.sentences:
        if sentence.start <= word.offset < sentence.end:
            return sentence
    # Fallback: nearest sentence by offset.
    if not page_text.sentences:
        return None
    return min(
        page_text.sentences,
        key=lambda s: min(abs(s.start - word.offset), abs(s.end - word.offset)),
    )


def nearest_word(page_text: PageText, point: tuple[float, float]) -> tuple[Word | None, float]:
    if not page_text.words:
        return None, float("inf")
    best = min(page_text.words, key=lambda w: point_rect_distance(point, w.rect))
    return best, point_rect_distance(point, best.rect)


def sentence_for_target_point(page_text: PageText, point: tuple[float, float]) -> Target | None:
    word, distance = nearest_word(page_text, point)
    if word is None:
        return None
    sentence = sentence_for_word(page_text, word)
    if sentence is None:
        return None
    confidence = float(max(0.0, 1.0 - distance / 120.0))
    return Target(sentence=sentence, method="line", confidence=confidence, anchor_word=word)


def sentence_for_vertical(page_text: PageText, note_rect: Rect, band: float = 40.0) -> Target | None:
    """Pick the sentence vertically level with the note, then nearest in x."""
    if not page_text.sentences:
        return None
    _cx, cy = rect_center(note_rect)
    candidates: list[tuple[float, Sentence]] = []
    for sentence in page_text.sentences:
        for rect in sentence.rects:
            y0, y1 = rect[1], rect[3]
            if y1 < cy - band or y0 > cy + band:
                continue
            dx = max(0.0, note_rect[0] - rect[2], rect[0] - note_rect[2])
            dy = max(0.0, cy - y1, y0 - cy)
            candidates.append((dx + dy, sentence))
            break
    if not candidates:
        return None
    score, sentence = min(candidates, key=lambda item: item[0])
    confidence = float(max(0.0, 1.0 - score / 200.0))
    return Target(sentence=sentence, method="vertical", confidence=confidence)


def sentence_candidates(
    page_text: PageText,
    note_rect: Rect,
    limit: int = 4,
) -> list[dict]:
    """Rank sentences near a note, for the review pane's re-targeting list."""
    scored: list[tuple[float, Sentence]] = []
    for sentence in page_text.sentences:
        if not sentence.rects:
            continue
        distance = min(rect_distance(note_rect, rect) for rect in sentence.rects)
        scored.append((distance, sentence))
    scored.sort(key=lambda item: item[0])
    candidates = []
    for distance, sentence in scored[:limit]:
        candidates.append(
            {
                "text": sentence.text,
                "rects": [list(rect) for rect in sentence.rects],
                "start": sentence.start,
                "end": sentence.end,
                "method": "proximity",
                "confidence": round(max(0.0, 1.0 - distance / 300.0), 3),
            }
        )
    return candidates


def sentence_for_proximity(page_text: PageText, note_rect: Rect) -> Target | None:
    if not page_text.sentences:
        return None
    best: Sentence | None = None
    best_distance = float("inf")
    for sentence in page_text.sentences:
        if not sentence.rects:
            continue
        distance = min(rect_distance(note_rect, rect) for rect in sentence.rects)
        if distance < best_distance:
            best_distance = distance
            best = sentence
    if best is None:
        return None
    confidence = float(max(0.0, 1.0 - best_distance / 300.0))
    return Target(sentence=best, method="proximity", confidence=confidence)
