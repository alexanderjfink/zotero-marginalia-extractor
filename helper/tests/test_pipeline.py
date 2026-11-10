#!/usr/bin/env python3
"""Regression test for the Marginalia Extractor helper pipeline.

Run with the helper virtualenv:
    .venv/bin/python tests/test_pipeline.py

Builds synthetic fixtures if missing, runs the pipeline in-process and checks
that a yellow highlight, a red underline and a margin note are recovered with
the expected text and association method.
"""

from __future__ import annotations

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

from src import pipeline  # noqa: E402
from src.models import Config  # noqa: E402

FIXTURES = os.path.join(HERE, "fixtures")


def ensure_fixtures() -> tuple[str, str]:
    original = os.path.join(FIXTURES, "original.pdf")
    scan = os.path.join(FIXTURES, "scan.pdf")
    if not (os.path.isfile(original) and os.path.isfile(scan)):
        import make_fixture  # noqa: WPS433
        make_fixture.main()
    return original, scan


def find(annotations, **kwargs):
    for ann in annotations:
        if all(ann.get(k) == v for k, v in kwargs.items()):
            return ann
    return None


def main() -> int:
    original, scan = ensure_fixtures()
    import tempfile
    review_dir = tempfile.mkdtemp(prefix="marg-test-")
    cfg = Config.from_dict({"ocr_backend": "tesseract", "dpi": 200, "review_dir": review_dir})
    result = pipeline.process(original, scan, cfg)
    assert result["pages"], "no pages processed"
    page = result["pages"][0]
    anns = page["annotations"]

    print(f"detected {len(anns)} annotations on page 0 (alignment {page['alignment']})")
    for a in anns:
        print(f"  - {a['type']:9s} {a['color']} src={a['source']} method={a['association_method']} text={a['text'][:40]!r}")

    highlight = find(anns, type="highlight", source="highlight")
    assert highlight is not None, "expected a colour highlight"
    assert "quick brown" in highlight["text"].lower(), highlight["text"]
    assert highlight["color"] == "#ffd400", highlight["color"]

    underline = find(anns, type="underline", source="highlight")
    assert underline is not None, "expected an underline"
    assert underline["text"], "underline should attach to the line above it"
    assert underline["color"] == "#ff6666", underline["color"]

    note = find(anns, source="margin_note")
    assert note is not None, "expected a margin note"
    assert note["comment"].strip(), "margin note should be transcribed"
    assert note["association_method"] in ("line", "vertical", "proximity"), note["association_method"]
    assert note["association_method"] == "line", (
        "fixture has a drawn line, expected line association, got "
        + note["association_method"]
    )
    assert note["candidates"], "margin note should expose re-targeting candidates"
    assert page["model"]["sentences"], "page model should contain sentences"
    assert page["images"].get("scan") and page["images"].get("pdf"), "review images missing"

    test_page_matching()
    test_spread_split()
    test_blue_note()
    test_photo_perspective()
    test_cross_page()
    test_dark_underline()
    test_image_only_pdf()
    test_map_only()
    test_per_color_output()
    test_comment_templates()

    print("\nAll pipeline assertions passed.")
    return 0


def _fixture(name: str) -> str:
    return os.path.join(os.path.dirname(__file__), "fixtures", name)


def test_page_matching() -> None:
    """A scan containing only PDF page 2 must match page index 1."""
    original = _fixture("multi_original.pdf")
    subset = _fixture("multi_scan_subset.pdf")
    if not (os.path.isfile(original) and os.path.isfile(subset)):
        print("  (skipping page matching: fixtures missing)")
        return
    cfg = Config.from_dict({"ocr_backend": "tesseract"})
    result = pipeline.process(original, subset, cfg)
    mapping = result["page_mapping"]
    assert len(mapping) == 1, mapping
    assert mapping[0]["pdf_index"] == 1, f"expected pdf page 1, got {mapping[0]}"
    page = result["pages"][0]
    assert page["pdf_index"] == 1
    assert any("margin note" in a["text"] for a in page["annotations"]), page["annotations"]
    print("  page matching: scan page 1 -> PDF page 2 ✓")


def test_spread_split() -> None:
    original = _fixture("multi_original.pdf")
    spread = _fixture("spread_scan.pdf")
    if not (os.path.isfile(original) and os.path.isfile(spread)):
        print("  (skipping spread split: fixtures missing)")
        return
    cfg = Config.from_dict({"split_spreads": True, "ocr_backend": "tesseract"})
    result = pipeline.process(original, spread, cfg)
    indices = [unit["pdf_index"] for unit in result["page_mapping"]]
    assert indices == [0, 1], indices
    assert len(result["pages"]) == 2
    for page in result["pages"]:
        assert page["alignment"]["confidence"] >= 0.5, page["alignment"]
        assert page["annotation_count"] == 0, page["annotations"]
    print("  spread split: left -> PDF 1, right -> PDF 2 ✓")


def test_blue_note() -> None:
    original = _fixture("blue_original.pdf")
    scan = _fixture("blue_scan.pdf")
    if not (os.path.isfile(original) and os.path.isfile(scan)):
        print("  (skipping blue note: fixtures missing)")
        return
    cfg = Config.from_dict({"ocr_backend": "tesseract"})
    result = pipeline.process(original, scan, cfg)
    page = result["pages"][0]
    note = find(page["annotations"], source="margin_note")
    assert note is not None, "expected a blue margin note"
    assert note["color"] == "#2ea8e5", note["color"]
    assert "NOTE" in note["comment"].upper(), note["comment"]
    print("  blue pan note keeps its colour ✓")


def test_photo_perspective() -> None:
    original = _fixture("original.pdf")
    scan = _fixture("photo_scan.pdf")
    if not (os.path.isfile(original) and os.path.isfile(scan)):
        print("  (skipping perspective: fixtures missing)")
        return
    import tempfile
    cfg = Config.from_dict({
        "ocr_backend": "tesseract",
        "review_dir": tempfile.mkdtemp(prefix="marg-photo-"),
    })
    result = pipeline.process(original, scan, cfg)
    page = result["pages"][0]
    assert page["alignment"]["confidence"] >= 0.6, page["alignment"]
    assert page["annotation_count"] >= 2, page["annotations"]
    print("  phone-photo perspective corrected and aligned ✓")


def test_cross_page() -> None:
    original = _fixture("cross_original.pdf")
    scan = _fixture("cross_scan.pdf")
    if not (os.path.isfile(original) and os.path.isfile(scan)):
        print("  (skipping cross-page: fixtures missing)")
        return
    import tempfile
    cfg = Config.from_dict({
        "ocr_backend": "tesseract",
        "review_dir": tempfile.mkdtemp(prefix="marg-cross-"),
    })
    result = pipeline.process(original, scan, cfg)
    first = result["pages"][0]
    merged = [a for a in first["annotations"] if a.get("next_page_rects")]
    assert merged, first["annotations"]
    assert merged[0]["next_page_index"] == 1
    second = result["pages"][1]
    assert second["annotation_count"] == 0, second["annotations"]
    print("  cross-page highlight merged into nextPageRects ✓")


def test_dark_underline() -> None:
    original = _fixture("dark_original.pdf")
    scan = _fixture("dark_scan.pdf")
    if not (os.path.isfile(original) and os.path.isfile(scan)):
        print("  (skipping dark underline: fixtures missing)")
        return
    cfg = Config.from_dict({"ocr_backend": "tesseract"})
    result = pipeline.process(original, scan, cfg)
    page = result["pages"][0]
    underline = find(page["annotations"], source="dark_underline")
    assert underline is not None, page["annotations"]
    assert underline["type"] == "underline"
    assert underline["color"] == "#aaaaaa"
    assert "black pen underline" in underline["text"].lower(), underline["text"]
    print("  black-pen underline detected as a grey underline ✓")


def test_image_only_pdf() -> None:
    original = _fixture("imageonly_original.pdf")
    scan = _fixture("scan.pdf")
    if not (os.path.isfile(original) and os.path.isfile(scan)):
        print("  (skipping image-only PDF: fixtures missing)")
        return
    cfg = Config.from_dict({"ocr_backend": "tesseract", "ocr_pdf_pages": True})
    result = pipeline.process(original, scan, cfg)
    page = result["pages"][0]
    highlight = find(page["annotations"], type="highlight", source="highlight")
    assert highlight is not None, page["annotations"]
    assert "quick brown" in highlight["text"].lower(), highlight["text"]
    print("  image-only PDF text model built by OCR ✓")


def test_map_only() -> None:
    original = _fixture("multi_original.pdf")
    scan = _fixture("multi_scan_subset.pdf")
    if not (os.path.isfile(original) and os.path.isfile(scan)):
        print("  (skipping map-only: fixtures missing)")
        return
    cfg = Config.from_dict({"ocr_backend": "tesseract"})
    result = pipeline.map_only(original, scan, cfg)
    assert result["page_mapping"], result
    assert result["page_mapping"][0]["pdf_index"] == 1, result["page_mapping"]
    assert result["pdf_pages"], result
    print("  map-only returns the corrected mapping ✓")


def test_per_color_output() -> None:
    original = _fixture("original.pdf")
    scan = _fixture("scan.pdf")
    if not (os.path.isfile(original) and os.path.isfile(scan)):
        print("  (skipping per-colour output: fixtures missing)")
        return
    cfg = Config.from_dict({"ocr_backend": "tesseract"})
    for rule in cfg.colors:
        if rule.name == "yellow":
            rule.output = "underline"
    result = pipeline.process(original, scan, cfg)
    page = result["pages"][0]
    yellow = [
        a for a in page["annotations"]
        if a["color"] == "#ffd400" and a["source"] == "highlight"
    ]
    assert yellow, page["annotations"]
    assert all(a["type"] == "underline" for a in yellow), yellow
    print("  per-colour output override forces underline ✓")


def test_comment_templates() -> None:
    original = _fixture("original.pdf")
    scan = _fixture("scan.pdf")
    if not (os.path.isfile(original) and os.path.isfile(scan)):
        print("  (skipping comment templates: fixtures missing)")
        return
    cfg = Config.from_dict({
        "ocr_backend": "tesseract",
        "comment_prefix": "[",
        "comment_suffix": "]",
        "append_scan_source": True,
    })
    result = pipeline.process(original, scan, cfg)
    note = find(result["pages"][0]["annotations"], source="margin_note")
    assert note is not None, result["pages"][0]["annotations"]
    assert note["comment"].startswith("["), note["comment"]
    assert "scanned p." in note["comment"], note["comment"]
    print("  comment templates + scan source applied ✓")


if __name__ == "__main__":
    raise SystemExit(main())
