#!/usr/bin/env python3
"""Generate a synthetic original.pdf + scan.pdf pair for pipeline testing.

The "scan" is the original page rendered to an image with a yellow highlight,
a red underline and a margin note (plus a drawn line pointing to a sentence).
It is intentionally simple — enough to exercise alignment, segmentation,
margin-note detection and sentence association end to end.
"""

from __future__ import annotations

import os
import sys

import cv2
try:
    import pymupdf as fitz
except ImportError:  # pragma: no cover
    import fitz  # type: ignore
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
OUT_DIR = os.path.join(HERE, "fixtures")

DPI = 200
SCALE = DPI / 72.0

ESSAY_LINES = [
    "On the Extraction of Marginalia",
    "",
    "The practice of reading with a pencil is ancient, but it has only",
    "recently become amenable to computational analysis. The quick brown",
    "fox jumps over the lazy dog near the river bank at dawn.",
    "",
    "A second consideration is the alignment between a physical copy and",
    "its digital surrogate. When pages are scanned carefully, the printed",
    "text can be matched to the PDF text layer with high confidence.",
    "",
    "Finally, the margin itself carries meaning. A note in the margin is",
    "an index of attention, pointing back to the sentence that provoked it.",
]


def build_original(path: str) -> None:
    doc = fitz.open()
    page = doc.new_page(width=612, height=792)  # US Letter
    margin = 72
    y = margin
    for line in ESSAY_LINES:
        if line:
            page.insert_text((margin, y), line, fontsize=12, fontname="helv")
        y += 22
    doc.save(path)
    doc.close()


def find_rect(page, needle: str):
    hits = page.search_for(needle)
    return hits[0] if hits else None


def build_scan(original_path: str, path: str) -> dict:
    doc = fitz.open(original_path)
    page = doc.load_page(0)
    pix = page.get_pixmap(matrix=fitz.Matrix(SCALE, SCALE), colorspace=fitz.csRGB, alpha=False)
    img = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, 3).copy()
    img = cv2.cvtColor(img, cv2.COLOR_RGB2BGR)

    def to_px(rect):
        return (
            int(rect.x0 * SCALE),
            int(rect.y0 * SCALE),
            int(rect.x1 * SCALE),
            int(rect.y1 * SCALE),
        )

    report = {}

    # 1. Yellow highlighter over a sentence.
    hl = find_rect(page, "The quick brown fox jumps over the lazy dog")
    if hl:
        x0, y0, x1, y1 = to_px(hl)
        overlay = img.copy()
        cv2.rectangle(overlay, (x0 - 3, y0 - 2), (x1 + 3, y1 + 2), (0, 220, 230), -1)
        img = cv2.addWeighted(overlay, 0.45, img, 0.55, 0)
        report["highlight"] = (x0, y0, x1, y1)

    # 2. Red pen underline under a different sentence.
    ul = find_rect(page, "the printed text can be matched")
    if ul:
        x0, y0, x1, y1 = to_px(ul)
        cv2.line(img, (x0, y1 + 4), (x1, y1 + 4), (0, 0, 210), 3)
        report["underline"] = (x0, y1, x1, y1)

    # 3. Margin note + a drawn line to a target sentence.
    target = find_rect(page, "A note in the margin is")
    if target:
        tx0, ty0, tx1, ty1 = to_px(target)
        note_x = 18
        note_y = ty0 + 10
        cv2.putText(img, "KEY", (note_x, note_y), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (40, 40, 40), 2)
        cv2.putText(img, "IDEA", (note_x, note_y + 26), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (40, 40, 40), 2)
        # Drawn line from the note toward the sentence start.
        cv2.line(img, (note_x + 70, note_y), (tx0 - 6, (ty0 + ty1) // 2), (40, 40, 40), 2)
        report["note"] = (note_x, note_y, note_x + 70, note_y + 26)

    out_path = os.path.join(OUT_DIR, "scan_page.png")
    cv2.imwrite(out_path, img)

    # Save the scan image as a one-page PDF.
    scan_doc = fitz.open()
    scan_page = scan_doc.new_page(width=612, height=792)
    scan_page.insert_image(scan_page.rect, filename=out_path)
    scan_doc.save(path)
    scan_doc.close()
    doc.close()
    return report


def _render_page_bgr(doc, index, dpi=200):
    page = doc.load_page(index)
    scale = dpi / 72.0
    pix = page.get_pixmap(matrix=fitz.Matrix(scale, scale), colorspace=fitz.csRGB, alpha=False)
    arr = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, 3).copy()
    return cv2.cvtColor(arr, cv2.COLOR_RGB2BGR)


def _save_image_pdf(images, path, width=612, height=792):
    doc = fitz.open()
    for i, image in enumerate(images):
        png = os.path.join(OUT_DIR, f"_tmp_{os.path.basename(path)}_{i}.png")
        cv2.imwrite(png, image)
        page = doc.new_page(width=width, height=height)
        page.insert_image(page.rect, filename=png)
    doc.save(path)
    doc.close()


def build_multi():
    original = os.path.join(OUT_DIR, "multi_original.pdf")
    scan = os.path.join(OUT_DIR, "multi_scan.pdf")
    texts = {
        0: ["Chapter One", "", "The first page contains only ordinary prose about rivers",
            "and bridges and the slow work of crossing them."],
        1: ["Chapter Two", "", "The second page introduces the argument about memory and",
            "the way a margin note can preserve a fleeting thought."],
    }
    doc = fitz.open()
    for p in (0, 1):
        page = doc.new_page(width=612, height=792)
        y = 72
        for line in texts[p]:
            if line:
                page.insert_text((72, y), line, fontsize=12, fontname="helv")
            y += 22
    doc.save(original)
    doc.close()

    src = fitz.open(original)
    images = []
    for p in (0, 1):
        img = _render_page_bgr(src, p)
        if p == 1:
            page = src.load_page(p)
            hits = page.search_for("the way a margin note can preserve")
            if hits:
                r = hits[0]
                x0, y0, x1, y1 = [int(v * 200 / 72) for v in (r.x0, r.y0, r.x1, r.y1)]
                overlay = img.copy()
                cv2.rectangle(overlay, (x0 - 3, y0 - 2), (x1 + 3, y1 + 2), (0, 220, 230), -1)
                img = cv2.addWeighted(overlay, 0.45, img, 0.55, 0)
        images.append(img)
    src.close()
    _save_image_pdf(images, scan)

    # Subset: only the second page.
    src = fitz.open(scan)
    subset = fitz.open()
    subset.insert_pdf(src, from_page=1, to_page=1)
    subset.save(os.path.join(OUT_DIR, "multi_scan_subset.pdf"))
    subset.close()
    src.close()
    return original, scan


def build_spread():
    src = fitz.open(os.path.join(OUT_DIR, "multi_original.pdf"))
    images = [_render_page_bgr(src, i) for i in range(2)]
    src.close()
    height = max(img.shape[0] for img in images)
    width = sum(img.shape[1] for img in images)
    spread = np.full((height, width, 3), 255, dtype=np.uint8)
    x = 0
    for img in images:
        spread[: img.shape[0], x : x + img.shape[1]] = img
        x += img.shape[1]
    doc = fitz.open()
    page = doc.new_page(width=1224, height=792)
    png = os.path.join(OUT_DIR, "_spread.png")
    cv2.imwrite(png, spread)
    page.insert_image(page.rect, filename=png)
    doc.save(os.path.join(OUT_DIR, "spread_scan.pdf"))
    doc.close()


def build_blue():
    original = os.path.join(OUT_DIR, "blue_original.pdf")
    scan = os.path.join(OUT_DIR, "blue_scan.pdf")
    doc = fitz.open()
    page = doc.new_page(width=612, height=792)
    y = 72
    for line in ["Coloured margins", "", "A blue pen note in the margin should be detected and keep",
                 "its blue colour rather than being dropped as a highlight."]:
        if line:
            page.insert_text((72, y), line, fontsize=12, fontname="helv")
        y += 22
    doc.save(original)
    doc.close()

    src = fitz.open(original)
    img = _render_page_bgr(src, 0)
    page = src.load_page(0)
    hits = page.search_for("its blue colour")
    if hits:
        r = hits[0]
        tx0, ty0 = int(r.x0 * 200 / 72), int(r.y0 * 200 / 72)
        ty1 = int(r.y1 * 200 / 72)
        nx, ny = 18, ty0
        cv2.putText(img, "NOTE", (nx, ny), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (200, 120, 30), 2)
        cv2.line(img, (nx + 80, ny), (tx0 - 6, (ty0 + ty1) // 2), (200, 120, 30), 2)
    src.close()
    _save_image_pdf([img], scan)


def build_photo():
    """A perspective-distorted 'phone photo' of the annotated scan page."""
    src = fitz.open(os.path.join(OUT_DIR, "scan.pdf"))
    image = _render_page_bgr(src, 0)
    src.close()
    height, width = image.shape[:2]
    background = np.full((int(height * 1.18), int(width * 1.18), 3), 35, np.uint8)
    destination = np.float32([
        [210, 150],
        [width * 1.10, 90],
        [width * 1.13, height * 1.06],
        [150, height * 1.10],
    ])
    source = np.float32([[0, 0], [width, 0], [width, height], [0, height]])
    matrix = cv2.getPerspectiveTransform(source, destination)
    photo = cv2.warpPerspective(image, matrix, (background.shape[1], background.shape[0]))
    mask = cv2.warpPerspective(np.full((height, width), 255, np.uint8), matrix,
                               (background.shape[1], background.shape[0]))
    photo[mask == 0] = background[mask == 0]

    doc = fitz.open()
    page = doc.new_page(width=760, height=1000)
    png = os.path.join(OUT_DIR, "_photo.png")
    cv2.imwrite(png, photo)
    page.insert_image(page.rect, filename=png)
    doc.save(os.path.join(OUT_DIR, "photo_scan.pdf"))
    doc.close()


def build_cross_page():
    """A highlight running from the bottom of page 1 to the top of page 2."""
    original = os.path.join(OUT_DIR, "cross_original.pdf")
    scan = os.path.join(OUT_DIR, "cross_scan.pdf")
    doc = fitz.open()
    p1 = doc.new_page(width=612, height=792)
    for y in (120, 160, 200, 700, 760):
        p1.insert_text((72, y), f"Page one line at {y} with enough words to be found.", fontsize=12, fontname="helv")
    p2 = doc.new_page(width=612, height=792)
    for y in (40, 120, 160, 200, 700):
        p2.insert_text((72, y), f"Page two line at {y} with enough words to be found.", fontsize=12, fontname="helv")
    doc.save(original)
    doc.close()

    src = fitz.open(original)
    out = fitz.open()
    scale = 200 / 72.0
    for i in range(2):
        page = src.load_page(i)
        pix = page.get_pixmap(matrix=fitz.Matrix(scale, scale), colorspace=fitz.csRGB, alpha=False)
        image = np.frombuffer(pix.samples, np.uint8).reshape(pix.height, pix.width, 3).copy()
        image = cv2.cvtColor(image, cv2.COLOR_RGB2BGR)
        needle = "Page one line at 760" if i == 0 else "Page two line at 40"
        hits = page.search_for(needle)
        if hits:
            r = hits[0]
            x0, y0, x1, y1 = [int(v * scale) for v in (r.x0, r.y0, r.x1, r.y1)]
            overlay = image.copy()
            cv2.rectangle(overlay, (x0 - 3, y0 - 2), (x1 + 3, y1 + 2), (0, 220, 230), -1)
            image = cv2.addWeighted(overlay, 0.45, image, 0.55, 0)
        png = os.path.join(OUT_DIR, f"_cross{i}.png")
        cv2.imwrite(png, image)
        page_out = out.new_page(width=612, height=792)
        page_out.insert_image(page_out.rect, filename=png)
    out.save(scan)
    out.close()
    src.close()


def build_dark_underline():
    original = os.path.join(OUT_DIR, "dark_original.pdf")
    scan = os.path.join(OUT_DIR, "dark_scan.pdf")
    doc = fitz.open()
    page = doc.new_page(width=612, height=792)
    y = 72
    for line in [
        "Dark pen underline test",
        "",
        "This sentence has a black pen underline beneath it.",
        "A second sentence follows without any mark at all.",
    ]:
        if line:
            page.insert_text((72, y), line, fontsize=12, fontname="helv")
        y += 22
    doc.save(original)
    doc.close()

    src = fitz.open(original)
    image = _render_page_bgr(src, 0)
    page = src.load_page(0)
    hits = page.search_for("black pen underline beneath")
    if hits:
        r = hits[0]
        x0, y0, x1, y1 = [int(v * 200 / 72) for v in (r.x0, r.y0, r.x1, r.y1)]
        cv2.line(image, (x0, y1 + 4), (x1, y1 + 4), (20, 20, 20), 2)
    src.close()
    _save_image_pdf([image], scan)


def build_image_only():
    """An original PDF with no text layer, to exercise OCR page models."""
    src = fitz.open(os.path.join(OUT_DIR, "original.pdf"))
    image = _render_page_bgr(src, 0)
    src.close()
    _save_image_pdf([image], os.path.join(OUT_DIR, "imageonly_original.pdf"))


def main() -> int:
    os.makedirs(OUT_DIR, exist_ok=True)
    original = os.path.join(OUT_DIR, "original.pdf")
    scan = os.path.join(OUT_DIR, "scan.pdf")
    build_original(original)
    report = build_scan(original, scan)
    build_multi()
    build_spread()
    build_blue()
    build_photo()
    build_cross_page()
    build_dark_underline()
    build_image_only()
    print("fixtures written:")
    print(" ", original)
    print(" ", scan)
    print(" ", os.path.join(OUT_DIR, "multi_original.pdf"))
    print(" ", os.path.join(OUT_DIR, "multi_scan.pdf"))
    print(" ", os.path.join(OUT_DIR, "multi_scan_subset.pdf"))
    print(" ", os.path.join(OUT_DIR, "spread_scan.pdf"))
    print(" ", os.path.join(OUT_DIR, "blue_scan.pdf"))
    print(" ", os.path.join(OUT_DIR, "photo_scan.pdf"))
    print(" ", os.path.join(OUT_DIR, "cross_scan.pdf"))
    print(" ", os.path.join(OUT_DIR, "dark_scan.pdf"))
    print(" ", os.path.join(OUT_DIR, "imageonly_original.pdf"))
    print("  regions:", report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
