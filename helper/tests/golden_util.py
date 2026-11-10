"""Shared helpers for the golden-file tests.

Goldens deliberately ignore pixel geometry and confidence values (which vary
with the exact OpenCV/Tesseract build) and keep the semantic result: page
mapping, annotation type/colour/source/method/text/comment, candidates and
cross-page links.
"""

from __future__ import annotations

import glob
import json
import os
import re
import tempfile

from src import pipeline
from src.models import Config

HERE = os.path.dirname(os.path.abspath(__file__))
FIXTURES = os.path.join(HERE, "fixtures")
GOLDEN_DIR = os.path.join(HERE, "golden")
CORPUS_DIR = os.path.join(HERE, "corpus")

# name -> (original, scan, config overrides)
CASES = {
    "single": ("original.pdf", "scan.pdf", {}),
    "subset": ("multi_original.pdf", "multi_scan_subset.pdf", {}),
    "spread": ("multi_original.pdf", "spread_scan.pdf", {"split_spreads": True}),
    "blue": ("blue_original.pdf", "blue_scan.pdf", {}),
    "photo": ("original.pdf", "photo_scan.pdf", {}),
    "cross": ("cross_original.pdf", "cross_scan.pdf", {}),
    "dark": ("dark_original.pdf", "dark_scan.pdf", {}),
    "imageonly": ("imageonly_original.pdf", "scan.pdf", {}),
}


def _resolve(filename: str) -> str:
    return filename if os.path.isabs(filename) else os.path.join(FIXTURES, filename)


def discover_corpus_cases() -> dict:
    """Find `<name>.pdf` + `<name>.scan.pdf` pairs in tests/corpus.

    An optional `<name>.json` holds config overrides (page_offset, etc.).
    """
    cases: dict = {}
    if not os.path.isdir(CORPUS_DIR):
        return cases
    for scan_path in sorted(glob.glob(os.path.join(CORPUS_DIR, "*.scan.pdf"))):
        base = scan_path[: -len(".scan.pdf")]
        original_path = base + ".pdf"
        if not os.path.isfile(original_path):
            continue
        name = "corpus-" + os.path.basename(base)
        overrides = {}
        config_path = base + ".json"
        if os.path.isfile(config_path):
            try:
                with open(config_path, "r", encoding="utf-8") as handle:
                    overrides = json.load(handle)
            except (OSError, json.JSONDecodeError):
                overrides = {}
        cases[name] = (original_path, scan_path, overrides)
    return cases


CASES.update(discover_corpus_cases())

_WS = re.compile(r"\s+")


def _text(value: str) -> str:
    return _WS.sub(" ", value or "").strip()


def run_case(name: str) -> dict:
    original, scan, overrides = CASES[name]
    review_dir = tempfile.mkdtemp(prefix=f"marg-golden-{name}-")
    data = {
        "ocr_backend": "tesseract",
        "dpi": 200,
        "review_dir": review_dir,
        "match_pages": True,
        "perspective_correct": True,
        "merge_cross_page": True,
    }
    data.update(overrides)
    cfg = Config.from_dict(data)
    result = pipeline.process(
        _resolve(original),
        _resolve(scan),
        cfg,
    )
    return normalize(result)


def normalize(result: dict) -> dict:
    mapping = []
    for unit in result.get("page_mapping", []):
        mapping.append(
            {
                "scan_index": unit.get("scan_index"),
                "pdf_index": unit.get("pdf_index"),
                "label": unit.get("label"),
                "match_method": unit.get("match_method"),
            }
        )

    pages = []
    for page in result.get("pages", []):
        if page.get("error"):
            pages.append(
                {
                    "pdf_index": page.get("pdf_index"),
                    "scan_label": page.get("scan_label"),
                    "error": page.get("error"),
                }
            )
            continue
        annotations = []
        for ann in page.get("annotations", []):
            annotations.append(
                {
                    "page_index": ann.get("page_index"),
                    "type": ann.get("type"),
                    "color": ann.get("color"),
                    "source": ann.get("source"),
                    "method": ann.get("association_method") or "",
                    "text": _text(ann.get("text")),
                    "comment": _text(ann.get("comment")),
                    "candidates": sorted(
                        _text(c.get("text")) for c in ann.get("candidates", [])
                    ),
                    "next_page_index": ann.get("next_page_index"),
                }
            )
        annotations.sort(key=lambda a: (a["page_index"], a["type"], a["color"], a["text"], a["comment"]))
        pages.append(
            {
                "pdf_index": page.get("pdf_index"),
                "scan_label": page.get("scan_label"),
                "match_method": page.get("match_method"),
                "annotations": annotations,
            }
        )

    return {
        "page_mapping": mapping,
        "pages": pages,
        "warnings": sorted(result.get("warnings", [])),
    }
