"""PDF rendering and native text extraction via PyMuPDF.

All rectangles produced here are in PDF *points* with a top-left origin (the
convention PyMuPDF uses). Conversion to Zotero's bottom-left PDF space happens
later in the pipeline via :func:`util.image_rect_to_pdf_rect` for image-space
rects, or :func:`pdf_rect_to_zotero` for point-space rects.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from typing import Optional

import numpy as np

try:
    import pymupdf as fitz  # PyMuPDF >= 1.24 preferred name
except ImportError:  # pragma: no cover
    try:
        import fitz  # type: ignore
    except ImportError as exc:
        raise ImportError(
            "PyMuPDF is required. Install with: pip install PyMuPDF"
        ) from exc


from .util import normalize_text

PointRect = tuple[float, float, float, float]
_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+(?=[\"'(\[A-Z0-9])")


@dataclass
class Word:
    text: str
    rect: PointRect  # x0, y0, x1, y1 in PDF points, top-left origin
    block: int
    line: int
    offset: int  # character offset in the page text stream


@dataclass
class PageText:
    width: float
    height: float
    words: list[Word] = field(default_factory=list)
    lines: list[list[Word]] = field(default_factory=list)
    sentences: list["Sentence"] = field(default_factory=list)
    full_text: str = ""
    # Bounding box of all printed text (the "text block"), top-left origin.
    text_bbox: Optional[PointRect] = None


@dataclass
class Sentence:
    text: str
    rects: list[PointRect]  # one rect per visual line
    start: int
    end: int


def open_document(path: str):
    return fitz.open(path)


def page_count(doc) -> int:
    return doc.page_count


def render_gray(doc, page_index: int, dpi: int) -> np.ndarray:
    """Render a page to a grayscale numpy array (uint8)."""
    page = doc.load_page(page_index)
    zoom = dpi / 72.0
    matrix = fitz.Matrix(zoom, zoom)
    pix = page.get_pixmap(matrix=matrix, colorspace=fitz.csGRAY, alpha=False)
    arr = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width)
    return arr.copy()


def render_rgb(doc, page_index: int, dpi: int) -> np.ndarray:
    """Render a page to an RGB numpy array (uint8)."""
    page = doc.load_page(page_index)
    zoom = dpi / 72.0
    matrix = fitz.Matrix(zoom, zoom)
    pix = page.get_pixmap(matrix=matrix, colorspace=fitz.csRGB, alpha=False)
    arr = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, 3)
    return arr.copy()


def render_small_gray(doc, page_index: int, width: int = 240) -> np.ndarray:
    """Render a page small and grayscale, for hashing / gutter detection."""
    page = doc.load_page(page_index)
    zoom = width / float(page.rect.width or 1.0)
    pix = page.get_pixmap(
        matrix=fitz.Matrix(zoom, zoom), colorspace=fitz.csGRAY, alpha=False
    )
    return np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width).copy()


def page_size_pts(doc, page_index: int) -> tuple[float, float]:
    page = doc.load_page(page_index)
    rect = page.rect
    return float(rect.width), float(rect.height)


def _reading_order(raw: list, page_width: float) -> list:
    """Order words for reading: two columns, with full-width headers/footers.

    PyMuPDF's word stream is top-to-bottom, which interleaves the columns of a
    journal page. When a clear vertical gutter exists we read the left column
    fully, then the right one, keeping full-width lines (headers, footers,
    full-width headings) in their vertical position.
    """
    items = [item for item in raw if (item[4] or "").strip()]
    if not items:
        return []

    width = max(1, int(page_width))
    coverage = np.zeros(width + 2, dtype=np.int32)
    for item in items:
        start = max(0, int(item[0]))
        end = min(width + 1, int(item[2]))
        coverage[start : end + 1] += 1

    lo, hi = int(width * 0.30), int(width * 0.70)
    gaps: list[tuple[int, int]] = []
    run_start = None
    for x in range(lo, hi + 1):
        if coverage[x] == 0:
            if run_start is None:
                run_start = x
        else:
            if run_start is not None:
                gaps.append((run_start, x - 1))
                run_start = None
    if run_start is not None:
        gaps.append((run_start, hi))

    split = None
    if gaps:
        gap = max(gaps, key=lambda g: g[1] - g[0])
        if (gap[1] - gap[0]) >= max(8, int(width * 0.02)):
            split = (gap[0] + gap[1]) / 2.0

    def key(item):
        return (round(item[1], 1), item[0])

    if split is None:
        return sorted(items, key=key)

    spanning: list = []
    left: list = []
    right: list = []
    bridge = width * 0.55
    for item in items:
        span = item[2] - item[0]
        crosses = item[0] < split < item[2]
        if crosses or span >= bridge:
            spanning.append(item)
        elif (item[0] + item[2]) / 2.0 < split:
            left.append(item)
        else:
            right.append(item)

    column_words = left + right
    if not column_words:
        return sorted(spanning, key=key)

    column_top = min(item[1] for item in column_words)
    column_bottom = max(item[3] for item in column_words)

    top = [item for item in spanning if item[3] <= column_top + 2]
    bottom = [item for item in spanning if item[1] >= column_bottom - 2]
    middle = [item for item in spanning if item not in top and item not in bottom]

    # A full-width line inside the column region is rare; attach it to the
    # column it overlaps most so it does not jump to the page edge.
    for item in middle:
        left_overlap = max(0.0, min(item[2], split) - item[0])
        (left if left_overlap >= (item[2] - item[0]) / 2.0 else right).append(item)

    return (
        sorted(top, key=key)
        + sorted(left, key=key)
        + sorted(right, key=key)
        + sorted(bottom, key=key)
    )


def _build_page_text(width: float, height: float, raw: list) -> PageText:
    ordered = _reading_order(raw, width)

    words: list[Word] = []
    cursor = 0
    for item in ordered:
        x0, y0, x1, y1, text, block, line = (
            item[0], item[1], item[2], item[3], item[4], item[5], item[6],
        )
        clean = (text or "").strip()
        if not clean:
            continue
        if words:
            cursor += 1  # the space that joins this word to the previous one
        words.append(
            Word(
                text=clean,
                rect=(float(x0), float(y0), float(x1), float(y1)),
                block=int(block),
                line=int(line),
                offset=cursor,
            )
        )
        cursor += len(clean)

    full_text = " ".join(w.text for w in words)

    line_map: dict[tuple[int, int], list[Word]] = {}
    for word in words:
        line_map.setdefault((word.block, word.line), []).append(word)
    lines = [
        sorted(ws, key=lambda x: x.rect[0])
        for _key, ws in sorted(
            line_map.items(),
            key=lambda kv: min(w.offset for w in kv[1]),
        )
    ]

    text_bbox: Optional[PointRect] = None
    if words:
        text_bbox = (
            min(x.rect[0] for x in words),
            min(x.rect[1] for x in words),
            max(x.rect[2] for x in words),
            max(x.rect[3] for x in words),
        )

    sentences: list[Sentence] = []
    if full_text:
        starts = [0]
        for match in _SENTENCE_SPLIT.finditer(full_text):
            starts.append(match.end())
        starts.append(len(full_text))
        starts = sorted(set(starts))
        for i in range(len(starts) - 1):
            start, end = starts[i], starts[i + 1]
            segment = full_text[start:end]
            if not segment.strip():
                continue
            sentences.append(
                Sentence(
                    text=normalize_text(segment),
                    rects=_sentence_rects(words, start, end),
                    start=start,
                    end=end,
                )
            )
        if not sentences and lines:
            for line in lines:
                segment_text = " ".join(w.text for w in line)
                sentences.append(
                    Sentence(
                        text=segment_text,
                        rects=[_line_rect(line)],
                        start=line[0].offset,
                        end=line[-1].offset + len(line[-1].text),
                    )
                )

    return PageText(
        width=width,
        height=height,
        words=words,
        lines=lines,
        sentences=sentences,
        full_text=full_text,
        text_bbox=text_bbox,
    )


def extract_page_text(doc, page_index: int) -> PageText:
    """Extract words, lines and sentences with point-space bounding boxes."""
    page = doc.load_page(page_index)
    width, height = float(page.rect.width), float(page.rect.height)
    raw = [
        (item[0], item[1], item[2], item[3], item[4], item[5], item[6])
        for item in page.get_text("words")
    ]
    return _build_page_text(width, height, raw)


def extract_page_text_ocr(doc, page_index: int, dpi: int = 200, lang: str = "eng") -> PageText:
    """Build a page text model by OCRing a page that has no text layer."""
    from . import ocr as ocr_mod

    page = doc.load_page(page_index)
    width, height = float(page.rect.width), float(page.rect.height)
    image = render_rgb(doc, page_index, dpi)
    scale = dpi / 72.0
    data = ocr_mod.ocr_tesseract_data(image, lang)
    raw = [
        (
            word["rect"][0] / scale,
            word["rect"][1] / scale,
            word["rect"][2] / scale,
            word["rect"][3] / scale,
            word["text"],
            word["block"],
            word["line"],
        )
        for word in data
    ]
    return _build_page_text(width, height, raw)


def _line_rect(line: list[Word]) -> PointRect:
    return (
        min(w.rect[0] for w in line),
        min(w.rect[1] for w in line),
        max(w.rect[2] for w in line),
        max(w.rect[3] for w in line),
    )


def _sentence_rects(words: list[Word], start: int, end: int) -> list[PointRect]:
    """Merge the word boxes intersecting [start, end) into per-line rects."""
    hits = [w for w in words if w.offset < end and (w.offset + len(w.text)) > start]
    if not hits:
        return []
    by_line: dict[tuple[int, int], list[Word]] = {}
    for w in hits:
        by_line.setdefault((w.block, w.line), []).append(w)
    rects: list[PointRect] = []
    for _key, line_words in sorted(by_line.items(), key=lambda kv: (kv[0][0], kv[0][1])):
        rects.append(_line_rect(line_words))
    return rects


def pdf_rect_to_zotero(rect: PointRect, page_height_pts: float) -> list[float]:
    """Convert a top-left PDF point rect to Zotero's bottom-left convention."""
    x0, y0, x1, y1 = rect
    return [
        round(min(x0, x1), 3),
        round(page_height_pts - max(y0, y1), 3),
        round(max(x0, x1), 3),
        round(page_height_pts - min(y0, y1), 3),
    ]
