"""Match scan pages to PDF pages by text content.

Books use nearly identical layouts on every page, so perceptual/layout hashes
are not discriminative. Text is: the PDF already has a text layer, and scanned
printed pages OCR well. We compare normalized token sets with the Jaccard
index, which tolerates OCR noise and running headers.
"""

from __future__ import annotations

import re
from typing import Optional

from . import ocr as ocr_mod
from . import pdf_pages
from . import perspective
from .models import Config

_WORD = re.compile(r"[A-Za-z0-9']+")
_STOP = {
    "the", "and", "for", "are", "but", "not", "you", "all", "any", "can",
    "had", "her", "was", "one", "our", "out", "has", "him", "his", "how",
    "its", "may", "new", "now", "old", "see", "two", "way", "who", "boy",
    "did", "she", "use", "that", "with", "from", "this", "have", "will",
    "your", "they", "been", "were", "said", "each", "which", "their",
    "there", "would", "about", "these", "other", "into", "than", "them",
    "then", "some", "could", "when", "what", "also", "more", "most",
    "only", "over", "such", "very", "much", "many", "just", "because",
}


def tokens(text: str) -> set[str]:
    if not text:
        return set()
    words = _WORD.findall(text.lower())
    return {word for word in words if len(word) >= 3 and word not in _STOP}


def jaccard(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    union = len(a | b)
    if not union:
        return 0.0
    return len(a & b) / union


def pdf_page_tokens(orig, index: int, text_cache=None) -> set[str]:
    try:
        if text_cache is not None:
            page_text = text_cache.get(orig, index)
        else:
            page_text = pdf_pages.extract_page_text(orig, index)
        return tokens(page_text.full_text)
    except Exception:
        return set()


def scan_page_tokens(scan, index: int, cfg: Config, subrect=None) -> Optional[set[str]]:
    """Tokens for a scan page (or one half of a spread).

    Prefers the scanned PDF's own text layer; falls back to OCR when the scan
    is image-only and an OCR backend is enabled.
    """
    page = scan.load_page(index)
    raw = page.get_text("words")
    if subrect is None and len(raw) >= 6:
        return tokens(" ".join(item[4] for item in raw))

    if cfg.ocr_backend == "none":
        return None
    try:
        image = pdf_pages.render_rgb(scan, index, dpi=150)
    except Exception:
        return None
    if subrect is not None:
        width_pts, _height = pdf_pages.page_size_pts(scan, index)
        scale = 150 / 72.0
        x0 = max(0, int(subrect[0] * scale))
        x1 = min(image.shape[1], int(subrect[2] * scale))
        image = image[:, x0:x1]
    if cfg.perspective_correct:
        image = perspective.correct_perspective(
            image, cfg.perspective_min_area, target_width=900, target_height=1165
        )
    text = ocr_mod.ocr_tesseract(image, cfg.ocr_lang)
    result = tokens(text)
    return result or None


def best_text_match(
    scan_tokens: set[str],
    pdf_token_sets: dict[int, set[str]],
    index_candidate: Optional[int] = None,
) -> tuple[Optional[int], float, str]:
    """Return (pdf_page, score, method)."""
    if not scan_tokens or not pdf_token_sets:
        return None, 0.0, "none"

    scored: list[tuple[float, int]] = []
    for page_index, page_tokens in pdf_token_sets.items():
        if page_tokens:
            scored.append((jaccard(scan_tokens, page_tokens), page_index))
    if not scored:
        return None, 0.0, "none"

    best_score, best_page = max(scored, key=lambda item: item[0])
    if best_score < 0.18:
        return None, best_score, "none"

    if index_candidate is not None and 0 <= index_candidate < len(pdf_token_sets):
        index_score = jaccard(scan_tokens, pdf_token_sets.get(index_candidate, set()))
        if index_score >= best_score - 0.08:
            return index_candidate, index_score, "text-index"
    return best_page, best_score, "text"
