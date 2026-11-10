"""End-to-end pipeline: original PDF + scanned PDF -> annotation JSON.

v2 adds page mapping (offset / fingerprint matching / two-page spreads),
progress + cancellation, a per-page sentence model for review re-targeting,
and per-page review images.
"""

from __future__ import annotations

import os
import time
from typing import Any, Optional

import cv2
import numpy as np

from . import lines as lines_mod
from . import ocr as ocr_mod
from . import pagematch
from . import pdf_pages
from . import perspective
from . import segment as seg
from . import textmatch as tm
from .pagecache import PageTextCache
from .align import align_pair
from .fingerprint import hamming, layout_hash
from .models import (
    Annotation,
    Config,
    HELPER_VERSION,
    PROTOCOL_VERSION,
)
from .progress import Progress
from .util import Rect, ensure_dir, normalize_text, rect_center


def process(
    pdf_path: str,
    scan_path: str,
    cfg: Config,
    progress: Optional[Progress] = None,
) -> dict[str, Any]:
    progress = progress or Progress(cfg.progress_path, cfg.cancel_path)
    orig = pdf_pages.open_document(pdf_path)
    scan = pdf_pages.open_document(scan_path)
    text_cache = PageTextCache(cfg)
    _log(cfg, f"start pdf={pdf_path} scan={scan_path}")

    units, warnings = build_page_mapping(orig, scan, cfg, progress, text_cache)
    _log(cfg, f"mapping units={len(units)} warnings={len(warnings)}")
    total = len(units)
    pages: list[dict[str, Any]] = []
    status = "ok"

    for index, unit in enumerate(units):
        if progress.cancelled():
            status = "cancelled"
            break
        progress.write("running", index, total, f"page {unit['label']}", unit["scan_index"])
        page_result = process_unit(orig, scan, unit, cfg, index, text_cache)
        pages.append(page_result)
        _log(
            cfg,
            f"page {unit['label']} pdf={unit['pdf_index']} "
            f"annotations={page_result.get('annotation_count', 0)}",
        )
        progress.write("running", index + 1, total, f"page {unit['label']}", unit["scan_index"])

    if cfg.merge_cross_page:
        merge_cross_page_highlights(pages)

    result = {
        "protocol_version": PROTOCOL_VERSION,
        "helper_version": HELPER_VERSION,
        "status": status,
        "source_pdf": os.path.basename(pdf_path),
        "scan_pdf": os.path.basename(scan_path),
        "page_count_scanned": pdf_pages.page_count(scan),
        "page_count_original": pdf_pages.page_count(orig),
        "page_mapping": units,
        "warnings": warnings,
        "pages": pages,
    }
    _log(cfg, f"done status={status} pages={len(pages)}")
    progress.write("done" if status == "ok" else status, len(pages), total, status)
    return result


def _log(cfg: Config, message: str) -> None:
    if not cfg.log_path:
        return
    try:
        with open(cfg.log_path, "a", encoding="utf-8") as handle:
            handle.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} {message}\n")
    except OSError:
        pass


def map_only(pdf_path: str, scan_path: str, cfg: Config) -> dict[str, Any]:
    """Return just the scan→PDF page mapping (for the preview dialog)."""
    orig = pdf_pages.open_document(pdf_path)
    scan = pdf_pages.open_document(scan_path)
    _log(cfg, f"map-only pdf={pdf_path} scan={scan_path}")
    text_cache = PageTextCache(cfg)
    units, warnings = build_page_mapping(orig, scan, cfg, None, text_cache)
    _log(cfg, f"map-only units={len(units)} warnings={len(warnings)}")
    pdf_pages_info = [
        {"index": index, "label": _page_label(orig, index)}
        for index in range(pdf_pages.page_count(orig))
    ]
    return {
        "protocol_version": PROTOCOL_VERSION,
        "helper_version": HELPER_VERSION,
        "status": "ok",
        "source_pdf": os.path.basename(pdf_path),
        "scan_pdf": os.path.basename(scan_path),
        "page_mapping": units,
        "warnings": warnings,
        "pdf_pages": pdf_pages_info,
    }


def merge_cross_page_highlights(pages: list[dict]) -> None:
    """Join a highlight that runs off the bottom of one page onto the next.

    Zotero represents this with ``annotationPosition.nextPageRects``. We only
    merge colour highlights (not margin notes) of the same colour and type that
    touch the bottom of page *i* and the top of page *i+1*.
    """
    by_index = {p.get("pdf_index"): p for p in pages if p.get("pdf_index") is not None}
    for page in pages:
        index = page.get("pdf_index")
        if index is None:
            continue
        following = by_index.get(index + 1)
        if not following:
            continue
        height = page.get("height_pts") or 0
        next_height = following.get("height_pts") or 0
        if not height or not next_height:
            continue
        bottom_band = height * 0.06
        top_band = next_height * 0.06

        for annotation in page.get("annotations", []):
            if annotation.get("source") != "highlight":
                continue
            rects = annotation.get("rects") or []
            if not rects or min(rect[1] for rect in rects) > bottom_band:
                continue
            for other in list(following.get("annotations", [])):
                if other.get("source") != "highlight":
                    continue
                if other.get("color") != annotation.get("color"):
                    continue
                if other.get("type") != annotation.get("type"):
                    continue
                other_rects = other.get("rects") or []
                if not other_rects:
                    continue
                if max(rect[3] for rect in other_rects) < next_height - top_band:
                    continue
                annotation["next_page_index"] = index + 1
                annotation["next_page_rects"] = other_rects
                following["annotations"].remove(other)
                following["annotation_count"] = len(following["annotations"])
                break


# ── Page mapping ─────────────────────────────────────────────────────────────

def build_page_mapping(orig, scan, cfg: Config, progress: Optional[Progress] = None,
                       text_cache: Optional[PageTextCache] = None) -> tuple[list[dict], list[str]]:
    n_pdf = pdf_pages.page_count(orig)
    n_scan = pdf_pages.page_count(scan)
    pdf_tokens = {
        index: pagematch.pdf_page_tokens(orig, index, text_cache)
        for index in range(n_pdf)
    }
    pdf_hashes = {
        index: layout_hash(pdf_pages.render_small_gray(orig, index, width=240))
        for index in range(n_pdf)
    }
    pdf_hashes = {index: value for index, value in pdf_hashes.items() if value is not None}

    units: list[dict] = []
    warnings: list[str] = []

    for scan_index in range(n_scan):
        if progress is not None:
            if progress.cancelled():
                warnings.append("cancelled during page matching")
                break
            progress.write(
                "running",
                scan_index,
                n_scan,
                f"matching scan page {scan_index + 1}/{n_scan}",
                scan_index,
            )
        width, height = pdf_pages.page_size_pts(scan, scan_index)
        subrects: list[Optional[tuple[float, float, float, float]]] = [None]
        if cfg.split_spreads and width > height * 1.15:
            small = pdf_pages.render_small_gray(scan, scan_index, width=600)
            gutter = small.shape[1] // 2
            detected = _detect_gutter(small)
            # Only trust the detected gutter when it is near the geometric
            # centre; asymmetric text margins bias the whitespace-band centre.
            if detected is not None and abs(detected - gutter) <= small.shape[1] * 0.06:
                gutter = detected
            gutter_pts = gutter / float(small.shape[1]) * width
            subrects = [(0.0, 0.0, gutter_pts, height), (gutter_pts, 0.0, width, height)]

        for sub_index, subrect in enumerate(subrects):
            label = str(scan_index + 1)
            if len(subrects) > 1:
                label += "ab"[sub_index]

            index_candidate = scan_index + cfg.page_offset
            index_valid = 0 <= index_candidate < n_pdf
            pdf_index: Optional[int] = None
            distance: Optional[float] = None
            method = "unmatched"

            if cfg.match_pages:
                scan_tokens = pagematch.scan_page_tokens(scan, scan_index, cfg, subrect)
                if scan_tokens:
                    pdf_index, score, method = pagematch.best_text_match(
                        scan_tokens, pdf_tokens, index_candidate if index_valid else None
                    )
                    distance = score
                if pdf_index is None:
                    # Text unavailable or inconclusive: fall back to layout hash.
                    small = pdf_pages.render_small_gray(scan, scan_index, width=300)
                    if subrect is not None:
                        x0 = int(subrect[0] / width * small.shape[1])
                        x1 = int(subrect[2] / width * small.shape[1])
                        small = small[:, x0:x1]
                    scan_hash = layout_hash(small)
                    pdf_index, distance, method = _choose_pdf_page(
                        scan_hash, scan_index, cfg.page_offset, pdf_hashes, n_pdf, True
                    )
            elif index_valid:
                pdf_index, method = index_candidate, "index"

            override = (cfg.map_overrides or {}).get(label)
            if override is not None:
                try:
                    override_index = int(override)
                    if 0 <= override_index < n_pdf:
                        pdf_index = override_index
                        distance = None
                        method = "manual"
                except (TypeError, ValueError):
                    pass

            units.append(
                {
                    "scan_index": scan_index,
                    "scan_rect": subrect,
                    "pdf_index": pdf_index,
                    "label": label,
                    "match_distance": distance,
                    "match_method": method,
                }
            )
            if pdf_index is None:
                warnings.append(f"Scan page {label} did not match any PDF page")

    return units, warnings


def _choose_pdf_page(
    scan_hash: Optional[int],
    scan_index: int,
    offset: int,
    pdf_hashes: dict[int, int],
    n_pdf: int,
    match_pages: bool,
) -> tuple[Optional[int], Optional[int], str]:
    index_candidate = scan_index + offset
    index_valid = 0 <= index_candidate < n_pdf

    if scan_hash is None:
        # Blank / degraded scan page: trust the ordered mapping.
        if index_valid:
            return index_candidate, None, "index"
        return None, None, "unmatched"

    if not match_pages:
        if index_valid:
            distance = hamming(scan_hash, pdf_hashes.get(index_candidate, scan_hash))
            return index_candidate, distance, "index"
        return None, None, "unmatched"

    best_index = -1
    best_distance = 1_000_000
    for page_index, pdf_hash in pdf_hashes.items():
        distance = hamming(scan_hash, pdf_hash)
        if distance < best_distance:
            best_distance = distance
            best_index = page_index

    if best_index >= 0 and best_distance <= 55:
        if index_valid and index_candidate in pdf_hashes:
            index_distance = hamming(scan_hash, pdf_hashes[index_candidate])
            # Prefer the ordered page when it is essentially as good.
            if index_distance <= best_distance + 10:
                return index_candidate, index_distance, "index"
        return best_index, best_distance, "fingerprint"

    if index_valid:
        distance = hamming(scan_hash, pdf_hashes.get(index_candidate)) if index_candidate in pdf_hashes else None
        return index_candidate, distance, "index-unverified"
    return None, None, "unmatched"


def _detect_gutter(gray: np.ndarray) -> Optional[int]:
    _, binary = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    projection = (binary > 0).sum(axis=0)
    width = len(projection)
    if width < 20:
        return None
    lo, hi = int(width * 0.25), int(width * 0.75)
    threshold = max(2, int(0.002 * int(projection.sum())))

    runs: list[tuple[int, int]] = []
    start = None
    for x in range(lo, hi):
        if projection[x] <= threshold:
            if start is None:
                start = x
        elif start is not None:
            runs.append((start, x - 1))
            start = None
    if start is not None:
        runs.append((start, hi - 1))
    if not runs:
        return None

    widest = max(runs, key=lambda run: run[1] - run[0])
    if (widest[1] - widest[0]) < max(6, int(width * 0.02)):
        return None
    # Centre of the widest empty band, not its edge.
    return (widest[0] + widest[1]) // 2


# ── Per-unit processing ──────────────────────────────────────────────────────


def process_unit(orig, scan, unit: dict, cfg: Config, index: int,
                 text_cache: Optional[PageTextCache] = None) -> dict[str, Any]:
    pdf_index = unit["pdf_index"]
    base = {
        "scan_index": unit["scan_index"],
        "scan_label": unit["label"],
        "pdf_index": pdf_index,
        "page_index": pdf_index,
        "match_method": unit.get("match_method"),
        "annotations": [],
        "annotation_count": 0,
    }
    if pdf_index is None:
        base["error"] = "unmatched"
        return base

    scale = cfg.dpi / 72.0
    ref_rgb = pdf_pages.render_rgb(orig, pdf_index, cfg.dpi)
    ref_gray = cv2.cvtColor(ref_rgb, cv2.COLOR_RGB2GRAY)
    ref_h, ref_w = ref_rgb.shape[:2]
    scan_rgb = pdf_pages.render_rgb(scan, unit["scan_index"], cfg.dpi)

    subrect = unit.get("scan_rect")
    if subrect is not None:
        x0 = max(0, int(subrect[0] * scale))
        y0 = max(0, int(subrect[1] * scale))
        x1 = min(scan_rgb.shape[1], int(subrect[2] * scale))
        y1 = min(scan_rgb.shape[0], int(subrect[3] * scale))
        scan_rgb = scan_rgb[y0:y1, x0:x1]
    if cfg.perspective_correct:
        scan_rgb = perspective.correct_perspective(
            scan_rgb, cfg.perspective_min_area, ref_w, ref_h
        )
    if cfg.deskew:
        scan_rgb = seg.deskew(scan_rgb)
    scan_gray = cv2.cvtColor(scan_rgb, cv2.COLOR_RGB2GRAY)

    alignment = align_pair(ref_gray, scan_gray)
    warped = cv2.warpPerspective(scan_rgb, alignment.matrix, (ref_w, ref_h))
    if cfg.white_balance:
        warped = seg.white_balance(warped)
    if cfg.remove_shadows:
        warped = seg.normalize_illumination(warped)

    page_text = (
        text_cache.get(orig, pdf_index) if text_cache is not None
        else pdf_pages.extract_page_text(orig, pdf_index)
    )
    text_bbox_px: Optional[Rect] = None
    if page_text.text_bbox is not None:
        tb = page_text.text_bbox
        text_bbox_px = (tb[0] * scale, tb[1] * scale, tb[2] * scale, tb[3] * scale)

    line_height = _estimate_line_height(page_text, scale)
    annotations = _extract_highlights(
        warped, page_text, cfg, scale, line_height, text_bbox_px, pdf_index
    )
    if cfg.detect_dark_underlines:
        annotations += _extract_dark_underlines(
            warped, page_text, cfg, scale, line_height, text_bbox_px, pdf_index
        )
    annotations += _extract_margin_notes(
        warped, page_text, cfg, scale, text_bbox_px, ref_w, pdf_index, unit["label"]
    )
    annotations = _merge_duplicates(annotations)

    _finalize_sort_keys(annotations, page_text)
    page_label = _page_label(orig, pdf_index)
    for annotation in annotations:
        annotation.page_label = page_label
        annotation.scan_label = unit["label"]

    review_images = _save_review_images(cfg, unit, warped, ref_rgb, bool(annotations))
    _write_debug(cfg.debug_dir, unit["label"], warped, alignment, annotations, scale)

    base.update(
        {
            "page_label": page_label,
            "width_pts": page_text.width,
            "height_pts": page_text.height,
            "dpi": cfg.dpi,
            "alignment": {
                "method": alignment.method,
                "confidence": round(alignment.confidence, 3),
            },
            "images": review_images,
            "model": _page_model(page_text, pdf_index, page_label, cfg.dpi),
            "annotation_count": len(annotations),
            "annotations": [a.to_dict() for a in annotations],
        }
    )
    return base


def _page_model(
    page_text: pdf_pages.PageText, pdf_index: int, page_label: str, dpi: int
) -> dict[str, Any]:
    return {
        "page_index": pdf_index,
        "page_label": page_label,
        "width_pts": page_text.width,
        "height_pts": page_text.height,
        "dpi": dpi,
        "sentences": [
            {
                "text": sentence.text,
                "rects": [list(rect) for rect in sentence.rects],
                "start": sentence.start,
                "end": sentence.end,
            }
            for sentence in page_text.sentences
        ],
    }


# ── Highlights ───────────────────────────────────────────────────────────────


def _extract_highlights(
    warped: np.ndarray,
    page_text: pdf_pages.PageText,
    cfg: Config,
    scale: float,
    line_height: float,
    text_bbox_px: Optional[Rect],
    page_index: int,
) -> list[Annotation]:
    regions = seg.detect_color_regions(warped, cfg.colors, min_area=max(40, cfg.min_highlight_area // 2))
    if not regions:
        return []

    # Refine each region's colour with Lab nearest-match when requested.
    if cfg.color_space == "lab":
        for region in regions:
            refined = seg.refine_region_rule(warped, region.rect, cfg.colors)
            if refined is not None:
                region.rule = refined

    body: list[seg.ColorRegion] = []
    for region in regions:
        cx, _cy = rect_center(region.rect)
        if text_bbox_px is None or (text_bbox_px[0] - 8 <= cx <= text_bbox_px[2] + 8):
            body.append(region)

    by_rule: dict[str, list[seg.ColorRegion]] = {}
    for region in body:
        by_rule.setdefault(region.rule.name, []).append(region)

    annotations: list[Annotation] = []
    merge_gap = max(12.0, line_height * 1.4)

    for _rule_name, group in by_rule.items():
        rule = group[0].rule
        merged = seg.merge_regions([g.rect for g in group], max_gap=merge_gap)
        kinds = [g.kind for g in group]
        default_kind = "highlighter" if kinds.count("highlighter") >= kinds.count("pen") else "pen"
        for rect in merged:
            ann_type = _resolve_type(cfg.mark_mode, default_kind, rule.output)
            ann = _annotation_for_region(
                page_text, rect, scale, page_index, rule.zotero_hex(), ann_type, "highlight"
            )
            if ann is not None:
                annotations.append(ann)
    return annotations


def _extract_dark_underlines(
    warped: np.ndarray,
    page_text: pdf_pages.PageText,
    cfg: Config,
    scale: float,
    line_height: float,
    text_bbox_px: Optional[Rect],
    page_index: int,
) -> list[Annotation]:
    """Detect black/blue pen underlines under printed text.

    Coloured marks are handled by the colour segmenter; this catches plain dark
    ink. It is deliberately conservative: a stroke must be thin, horizontal,
    and sit just below a text line it horizontally overlaps.
    """
    if not page_text.lines:
        return []
    ink = seg.ink_mask(warped)
    printed = []
    for word in page_text.words:
        x0, y0, x1, y1 = word.rect
        printed.append((x0 * scale, y0 * scale, x1 * scale, y1 * scale))
    ink = seg.mask_out_rects(ink, printed, expand=2)
    colored = _colored_union(warped, cfg)
    colored = cv2.dilate(colored, np.ones((5, 5), np.uint8))
    ink[colored > 0] = 0

    underlines = seg.find_underlines(ink, min_length=int(max(30.0, line_height * 2.5)))
    if not underlines:
        return []

    from .models import ZOTERO_COLORS, DEFAULT_ZOTERO_COLOR

    color = ZOTERO_COLORS.get(cfg.dark_underline_color, ZOTERO_COLORS[DEFAULT_ZOTERO_COLOR])
    hsv = seg.rgb_to_hsv(warped)
    annotations: list[Annotation] = []
    max_gap_pts = (line_height * 1.8) / max(scale, 1e-6)
    for rect in underlines:
        x0 = max(0, int(rect[0]))
        y0 = max(0, int(rect[1]))
        x1 = min(hsv.shape[1], int(rect[2]))
        y1 = min(hsv.shape[0], int(rect[3]))
        if x1 <= x0 or y1 <= y0:
            continue
        # Coloured pen strokes are handled by the colour segmenter; this path
        # is for low-saturation black/grey ink only.
        if float(hsv[y0:y1, x0:x1, 1].mean()) > 60.0:
            continue
        point_rect = tm.image_rect_to_points(rect, scale)
        words = tm.words_for_underline(page_text, point_rect, max_gap=max_gap_pts)
        if not words:
            continue
        # The stroke must cover a meaningful part of the line.
        line_x0 = min(w.rect[0] for w in words)
        line_x1 = max(w.rect[2] for w in words)
        overlap = min(point_rect[2], line_x1) - max(point_rect[0], line_x0)
        if overlap < 0.4 * max(1.0, point_rect[2] - point_rect[0]):
            continue
        rects = _zotero_rects(tm.words_to_line_rects(words), page_text.height)
        if not rects:
            continue
        ann = Annotation(
            id=f"p{page_index}u{int(rect[0])}-{int(rect[1])}",
            page_index=page_index,
            type="underline",
            color=color,
            rects=rects,
            text=normalize_text(tm.words_to_text(words)),
            comment="",
            source="dark_underline",
            association_method="underline",
            confidence=0.6,
        )
        _store_offset(ann, min(w.offset for w in words))
        annotations.append(ann)
    return annotations


def _resolve_type(mark_mode: str, detected_kind: str, rule_output: str = "auto") -> str:
    if rule_output in ("highlight", "underline", "note"):
        return rule_output
    if mark_mode == "highlight":
        return "highlight"
    if mark_mode == "underline":
        return "underline"
    return "highlight" if detected_kind == "highlighter" else "underline"


# Sort keys need the character offset of the anchor word. We stash it on the
# side keyed by object identity so the Annotation dataclass stays serialisable.
_ANCHOR_OFFSETS: dict[int, int] = {}


def _store_offset(ann: Annotation, offset: int) -> None:
    _ANCHOR_OFFSETS[id(ann)] = offset


def _annotation_for_region(
    page_text: pdf_pages.PageText,
    image_rect: Rect,
    scale: float,
    page_index: int,
    color: str,
    ann_type: str,
    source: str,
    comment: str = "",
    association: str = "",
    confidence: float = 0.0,
) -> Optional[Annotation]:
    point_rect = tm.image_rect_to_points(image_rect, scale)
    words = tm.words_in_rect(page_text, point_rect)
    if not words and ann_type == "underline":
        words = tm.words_for_underline(page_text, point_rect)
    if words:
        rects = _zotero_rects(tm.words_to_line_rects(words), page_text.height)
        text = tm.words_to_text(words)
        anchor_offset = min(w.offset for w in words)
    else:
        rects = _zotero_rects([point_rect], page_text.height)
        text = ""
        anchor_offset = 0
    if not rects:
        return None
    ann = Annotation(
        id=f"p{page_index}a{int(image_rect[0])}-{int(image_rect[1])}",
        page_index=page_index,
        type=ann_type,
        color=color,
        rects=rects,
        text=text,
        comment=comment,
        source=source,
        association_method=association,
        confidence=confidence,
    )
    _store_offset(ann, anchor_offset)
    return ann


# ── Margin notes ─────────────────────────────────────────────────────────────


def _extract_margin_notes(
    warped: np.ndarray,
    page_text: pdf_pages.PageText,
    cfg: Config,
    scale: float,
    text_bbox_px: Optional[Rect],
    page_width: float,
    page_index: int,
    scan_label: str = "",
) -> list[Annotation]:
    if not page_text.sentences:
        return []

    ink = seg.ink_mask(warped)
    printed_rects: list[Rect] = []
    for word in page_text.words:
        x0, y0, x1, y1 = word.rect
        printed_rects.append((x0 * scale, y0 * scale, x1 * scale, y1 * scale))
    ink_clean = seg.mask_out_rects(ink, printed_rects, expand=4)

    # Remove coloured highlight strokes inside the text body only; coloured
    # pen notes in the margin must survive.
    colored = _colored_union(warped, cfg)
    if text_bbox_px is not None:
        left = max(0, int(text_bbox_px[0]))
        right = min(colored.shape[1], int(text_bbox_px[2]) + 1)
        body_colored = np.zeros_like(colored)
        body_colored[:, left:right] = colored[:, left:right]
    else:
        body_colored = colored
    ink_clean[body_colored > 0] = 0
    ink_clean = seg.strip_border(ink_clean, margin=6)

    page_height = warped.shape[0]
    margin_blobs = seg.find_margin_blobs(
        ink_clean, text_bbox_px, page_width, cfg.margin_fraction, min_area=cfg.min_note_area
    )
    text_blobs: list[Rect] = []
    for blob in margin_blobs:
        if seg.touches_border(blob, page_width, page_height):
            continue
        if seg.is_line_like(blob):
            continue
        text_blobs.append(blob)

    note_regions = seg.cluster_word_like(text_blobs, max_gap=22.0)
    if not note_regions:
        return []

    connectors = lines_mod.detect_connector_candidates(
        ink_clean, note_rects=note_regions, text_bbox=text_bbox_px
    )
    line_targets = lines_mod.associate_notes_to_points(
        note_regions, connectors, text_bbox_px, page_width
    )

    annotations: list[Annotation] = []
    for idx, note_rect in enumerate(note_regions):
        target = _resolve_target(page_text, note_rect, scale, line_targets.get(idx))
        if target is None:
            continue
        crop = ocr_mod.crop(warped, note_rect)
        comment, _backend = ocr_mod.transcribe(crop, cfg)
        comment = _format_comment(comment, cfg, scan_label)
        color = _note_color(warped, note_rect, cfg)
        rects = _zotero_rects(target.sentence.rects, page_text.height)
        if not rects:
            continue

        method = target.method
        if method == "vertical":
            # A small, sparse mark (asterisk, tick, symbol) beside a line is a
            # marker rather than a multi-word note; the vertical target is
            # still the right sentence, but label it for the review.
            x0 = max(0, int(note_rect[0]))
            y0 = max(0, int(note_rect[1]))
            x1 = min(ink_clean.shape[1], int(note_rect[2]))
            y1 = min(ink_clean.shape[0], int(note_rect[3]))
            width = note_rect[2] - note_rect[0]
            height = note_rect[3] - note_rect[1]
            area = max(1.0, width * height)
            if max(width, height) <= 55 and x1 > x0 and y1 > y0:
                fill = float(np.count_nonzero(ink_clean[y0:y1, x0:x1])) / area
                if fill < 0.35:
                    method = "marker"

        point_rect = tm.image_rect_to_points(note_rect, scale)
        candidates = tm.sentence_candidates(page_text, point_rect, cfg.max_candidates)
        ann = Annotation(
            id=f"p{page_index}n{idx}",
            page_index=page_index,
            type="highlight",
            color=color,
            rects=rects,
            text=normalize_text(target.sentence.text),
            comment=comment,
            source="margin_note",
            association_method=method,
            confidence=target.confidence,
            candidates=candidates,
        )
        _store_offset(ann, max(0, target.sentence.start))
        annotations.append(ann)
    return annotations


def _resolve_target(page_text, note_rect, scale, line_target):
    if line_target is not None:
        point = (line_target.point[0] / scale, line_target.point[1] / scale)
        target = tm.sentence_for_target_point(page_text, point)
        if target is not None:
            target.confidence = (target.confidence + line_target.confidence) / 2.0
            return target
    target = tm.sentence_for_vertical(page_text, tm.image_rect_to_points(note_rect, scale))
    if target is not None and target.confidence >= 0.25:
        return target
    return tm.sentence_for_proximity(page_text, tm.image_rect_to_points(note_rect, scale))


def _note_color(warped: np.ndarray, note_rect: Rect, cfg: Config) -> str:
    hsv = seg.rgb_to_hsv(warped)
    best_color = None
    best_overlap = 0.0
    for rule in cfg.colors:
        if not rule.enabled:
            continue
        mask = seg.color_mask(hsv, rule)
        sub = mask[
            max(0, int(note_rect[1])) : int(note_rect[3]),
            max(0, int(note_rect[0])) : int(note_rect[2]),
        ]
        if sub.size == 0:
            continue
        overlap = float(np.count_nonzero(sub)) / float(sub.size)
        if overlap > best_overlap and overlap > 0.02:
            best_overlap = overlap
            best_color = rule.zotero_hex()
    if best_color:
        return best_color
    from .models import ZOTERO_COLORS, DEFAULT_ZOTERO_COLOR

    return ZOTERO_COLORS.get(cfg.note_fallback_color, ZOTERO_COLORS[DEFAULT_ZOTERO_COLOR])


def _colored_union(warped: np.ndarray, cfg: Config) -> np.ndarray:
    hsv = seg.rgb_to_hsv(warped)
    union = np.zeros(warped.shape[:2], dtype=np.uint8)
    for rule in cfg.colors:
        if not rule.enabled:
            continue
        union = cv2.bitwise_or(union, seg.color_mask(hsv, rule))
    return union


# ── Shared helpers ───────────────────────────────────────────────────────────


def _format_comment(comment: str, cfg: Config, scan_label: str = "") -> str:
    comment = (comment or "").strip()
    if not comment and not cfg.append_scan_source:
        return ""
    text = ""
    if comment:
        text = f"{cfg.comment_prefix}{comment}{cfg.comment_suffix}"
    if cfg.append_scan_source and scan_label:
        source = f"— scanned p. {scan_label}"
        text = f"{text}\n\n{source}" if text else source
    return text.strip()


def _zotero_rects(point_rects: list[Rect], page_height_pts: float) -> list[list[float]]:
    out: list[list[float]] = []
    for rect in point_rects:
        converted = pdf_pages.pdf_rect_to_zotero(rect, page_height_pts)
        if converted[2] > converted[0] and converted[3] > converted[1]:
            out.append(converted)
    return out


def _estimate_line_height(page_text: pdf_pages.PageText, scale: float) -> float:
    heights = []
    for line in page_text.lines:
        ys = [w.rect[1] for w in line] + [w.rect[3] for w in line]
        heights.append(max(ys) - min(ys))
    if not heights:
        return 12.0 * scale
    heights.sort()
    return heights[len(heights) // 2] * scale


def _merge_duplicates(annotations: list[Annotation]) -> list[Annotation]:
    # A coloured underline can leave anti-aliased dark edges that the dark-ink
    # pass picks up; drop the grey duplicate when the same line is already
    # covered by a coloured underline.
    coloured = {
        (a.page_index, a.text)
        for a in annotations
        if a.source == "highlight" and a.type == "underline" and a.text
    }
    annotations = [
        a for a in annotations
        if not (a.source == "dark_underline" and (a.page_index, a.text) in coloured)
    ]

    merged: dict[tuple, Annotation] = {}
    for ann in annotations:
        if ann.source == "margin_note" and ann.text:
            key = (ann.page_index, ann.type, ann.color, ann.text, ann.source)
        elif ann.text:
            key = (ann.page_index, ann.type, ann.color, ann.text, ann.comment, ann.source)
        else:
            key = (ann.page_index, ann.id)
        if key not in merged:
            merged[key] = ann
            continue
        existing = merged[key]
        existing.rects = _dedupe_rects(existing.rects + ann.rects)
        if len(ann.comment or "") > len(existing.comment or ""):
            existing.comment = ann.comment
        if ann.confidence > existing.confidence:
            existing.confidence = ann.confidence
            existing.association_method = ann.association_method
        if ann.candidates and not existing.candidates:
            existing.candidates = ann.candidates
    return list(merged.values())


def _dedupe_rects(rects: list[list[float]]) -> list[list[float]]:
    seen: set[tuple] = set()
    out: list[list[float]] = []
    for rect in rects:
        key = tuple(round(v, 1) for v in rect)
        if key in seen:
            continue
        seen.add(key)
        out.append(rect)
    return out


def _finalize_sort_keys(annotations: list[Annotation], page_text: pdf_pages.PageText) -> None:
    for ann in annotations:
        offset = _ANCHOR_OFFSETS.pop(id(ann), 0)
        top_point_y = max(0.0, page_text.height - max(r[3] for r in ann.rects))
        ann.sort_index = (
            f"{ann.page_index:05d}|{min(999999, offset):06d}|{int(round(top_point_y)):05d}"
        )


def _page_label(doc, index: int) -> str:
    try:
        label = doc.load_page(index).get_label()
        if label:
            return str(label)
    except Exception:
        pass
    return str(index + 1)


def _save_review_images(cfg: Config, unit: dict, warped, ref_rgb, has_annotations: bool) -> dict:
    if not has_annotations or not cfg.render_review_images or not cfg.review_dir:
        return {}
    ensure_dir(cfg.review_dir)
    safe = str(unit["label"]).replace("/", "_")
    scan_path = os.path.join(cfg.review_dir, f"page_{safe}_scan.jpg")
    pdf_path = os.path.join(cfg.review_dir, f"page_{safe}_pdf.jpg")

    def shrink(image):
        height, width = image.shape[:2]
        if width > 900:
            scale = 900.0 / width
            image = cv2.resize(image, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
        return image

    cv2.imwrite(scan_path, cv2.cvtColor(shrink(warped), cv2.COLOR_RGB2BGR), [cv2.IMWRITE_JPEG_QUALITY, 85])
    cv2.imwrite(pdf_path, cv2.cvtColor(shrink(ref_rgb), cv2.COLOR_RGB2BGR), [cv2.IMWRITE_JPEG_QUALITY, 85])
    return {"scan": scan_path, "pdf": pdf_path}


def _write_debug(debug_dir, label: str, warped, alignment, annotations, scale) -> None:
    if not debug_dir:
        return
    vis = cv2.cvtColor(warped, cv2.COLOR_RGB2BGR).copy()
    for ann in annotations:
        color = (0, 0, 255) if ann.source == "margin_note" else (0, 200, 0)
        for x0, y0, x1, y1 in ann.rects:
            p_y0 = warped.shape[0] - y1 * scale
            p_y1 = warped.shape[0] - y0 * scale
            cv2.rectangle(
                vis,
                (int(x0 * scale), int(p_y0)),
                (int(x1 * scale), int(p_y1)),
                color,
                2,
            )
    cv2.putText(
        vis,
        f"page {label} | {alignment.method} {alignment.confidence:.2f}",
        (12, 30),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.9,
        (0, 0, 255),
        2,
    )
    cv2.imwrite(os.path.join(debug_dir, f"page_{label}.jpg"), vis)
