"""Shared page-text cache with OCR fallback for image-only PDFs.

Extracting text is cheap for text PDFs, but OCRing an image-only PDF page is
expensive. Both page matching and annotation extraction need the same page
model, so cache it by (document path, page index).
"""

from __future__ import annotations

from . import pdf_pages
from .models import Config


class PageTextCache:
    def __init__(self, cfg: Config):
        self.cfg = cfg
        self._cache: dict[tuple[str, int], pdf_pages.PageText] = {}

    def get(self, doc, page_index: int) -> pdf_pages.PageText:
        key = (str(getattr(doc, "name", id(doc))), int(page_index))
        cached = self._cache.get(key)
        if cached is not None:
            return cached

        page_text = pdf_pages.extract_page_text(doc, page_index)
        if (
            not page_text.words
            and self.cfg.ocr_pdf_pages
            and self.cfg.ocr_backend != "none"
        ):
            page_text = pdf_pages.extract_page_text_ocr(
                doc, page_index, self.cfg.dpi, self.cfg.ocr_lang
            )
        self._cache[key] = page_text
        return page_text
