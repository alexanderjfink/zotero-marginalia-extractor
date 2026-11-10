#!/usr/bin/env python3
"""Marginalia Extractor — local processing helper (v2).

Usage:
    python3 marginalia_helper.py \
        --pdf "/path/to/library.pdf" \
        --scan "/path/to/scan.pdf" \
        --output "/tmp/marginalia.json" \
        [--config /tmp/config.json] \
        [--dpi 200] [--mark-mode both] \
        [--ocr-backend tesseract|ollama|none] \
        [--page-offset 0] [--no-match-pages] [--split-spreads] \
        [--progress /tmp/progress.json] [--cancel /tmp/cancel] \
        [--review-dir /tmp/review]

Protocol on stdout (one line each):
    PROGRESS <done> <total>
    DONE <output-path>
Errors go to stderr with a non-zero exit code.

Diagnostics:
    python3 marginalia_helper.py --check
prints a JSON dependency report and exits.
"""

from __future__ import annotations

import argparse
import importlib
import json
import os
import shutil
import sys
import traceback

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from src.models import Config, HELPER_VERSION, PROTOCOL_VERSION, default_color_rules  # noqa: E402
from src import pipeline  # noqa: E402
from src.progress import Progress  # noqa: E402


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description="Extract marginalia from a scanned PDF into annotations.")
    parser.add_argument("--pdf", help="Original PDF already in Zotero")
    parser.add_argument("--scan", help="Scanned PDF of the same pages")
    parser.add_argument("--output", help="Where to write the annotation JSON")
    parser.add_argument("--config", help="Path to a JSON config file (written by the plugin)")
    parser.add_argument("--dpi", type=int)
    parser.add_argument("--mark-mode", choices=["highlight", "underline", "both"])
    parser.add_argument("--ocr-backend", choices=["tesseract", "ollama", "openai", "anthropic", "none"])
    parser.add_argument("--ocr-lang")
    parser.add_argument("--ollama-url")
    parser.add_argument("--ollama-model")
    parser.add_argument("--llm-url")
    parser.add_argument("--llm-model")
    parser.add_argument("--llm-api-key")
    parser.add_argument("--llm-api-key-env")
    parser.add_argument("--llm-prompt")
    parser.add_argument("--llm-timeout", type=int)
    parser.add_argument("--llm-max-tokens", type=int)
    parser.add_argument("--llm-temperature", type=float)
    parser.add_argument("--page-offset", type=int)
    parser.add_argument("--no-match-pages", action="store_true")
    parser.add_argument("--split-spreads", action="store_true")
    parser.add_argument("--no-perspective", action="store_true")
    parser.add_argument("--perspective-min-area", type=float)
    parser.add_argument("--no-merge-cross-page", action="store_true")
    parser.add_argument("--no-white-balance", action="store_true")
    parser.add_argument("--no-shadows", action="store_true")
    parser.add_argument("--no-deskew", action="store_true")
    parser.add_argument("--no-dark-underlines", action="store_true")
    parser.add_argument("--dark-underline-color")
    parser.add_argument("--no-ocr-pdf", action="store_true")
    parser.add_argument("--color-space", choices=["hsv", "lab"])
    parser.add_argument("--max-candidates", type=int)
    parser.add_argument("--debug-dir")
    parser.add_argument("--review-dir")
    parser.add_argument("--progress")
    parser.add_argument("--cancel")
    parser.add_argument("--page-limit", type=int, help="Only process the first N pages (debugging)")
    parser.add_argument("--map-only", action="store_true", help="Only compute the scan→PDF page mapping")
    parser.add_argument("--log", help="Write a run log to this path")
    parser.add_argument("--check", action="store_true", help="Print dependency diagnostics and exit")
    return parser.parse_args(argv)


def build_config(args) -> Config:
    data = {}
    if args.config:
        with open(args.config, "r", encoding="utf-8") as handle:
            data = json.load(handle)
    if args.dpi is not None:
        data["dpi"] = args.dpi
    if args.mark_mode:
        data["mark_mode"] = args.mark_mode
    if args.ocr_backend:
        data["ocr_backend"] = args.ocr_backend
    if args.ocr_lang:
        data["ocr_lang"] = args.ocr_lang
    if args.ollama_url:
        data["ollama_url"] = args.ollama_url
    if args.ollama_model:
        data["ollama_model"] = args.ollama_model
    if args.llm_url:
        data["llm_url"] = args.llm_url
    if args.llm_model:
        data["llm_model"] = args.llm_model
    if args.llm_api_key:
        data["llm_api_key"] = args.llm_api_key
    if args.llm_api_key_env:
        data["llm_api_key_env"] = args.llm_api_key_env
    if args.llm_prompt:
        data["llm_prompt"] = args.llm_prompt
    if args.llm_timeout is not None:
        data["llm_timeout"] = args.llm_timeout
    if args.llm_max_tokens is not None:
        data["llm_max_tokens"] = args.llm_max_tokens
    if args.llm_temperature is not None:
        data["llm_temperature"] = args.llm_temperature
    if args.page_offset is not None:
        data["page_offset"] = args.page_offset
    if args.no_match_pages:
        data["match_pages"] = False
    if args.split_spreads:
        data["split_spreads"] = True
    if args.no_perspective:
        data["perspective_correct"] = False
    if args.perspective_min_area is not None:
        data["perspective_min_area"] = args.perspective_min_area
    if args.no_merge_cross_page:
        data["merge_cross_page"] = False
    if args.no_white_balance:
        data["white_balance"] = False
    if args.no_shadows:
        data["remove_shadows"] = False
    if args.no_deskew:
        data["deskew"] = False
    if args.no_dark_underlines:
        data["detect_dark_underlines"] = False
    if args.dark_underline_color:
        data["dark_underline_color"] = args.dark_underline_color
    if args.no_ocr_pdf:
        data["ocr_pdf_pages"] = False
    if args.color_space:
        data["color_space"] = args.color_space
    if args.max_candidates is not None:
        data["max_candidates"] = args.max_candidates
    if args.debug_dir:
        data["debug_dir"] = args.debug_dir
    if args.review_dir:
        data["review_dir"] = args.review_dir
    if args.progress:
        data["progress_path"] = args.progress
    if args.cancel:
        data["cancel_path"] = args.cancel
    if args.log:
        data["log_path"] = args.log
    cfg = Config.from_dict(data)
    if not cfg.colors:
        cfg.colors = default_color_rules()
    return cfg


def check_dependencies(cfg: Config) -> dict:
    modules = {}
    for name in ("cv2", "numpy", "PIL", "pytesseract"):
        try:
            importlib.import_module(name)
            modules[name] = True
        except Exception:
            modules[name] = False
    # PyMuPDF: prefer the modern pymupdf module; only touch the deprecated
    # fitz alias when pymupdf is absent.
    try:
        importlib.import_module("pymupdf")
        modules["pymupdf"] = True
    except Exception:
        modules["pymupdf"] = False
        try:
            importlib.import_module("fitz")
            modules["fitz"] = True
        except Exception:
            modules["fitz"] = False

    from src import ocr

    report = {
        "protocol_version": PROTOCOL_VERSION,
        "helper_version": HELPER_VERSION,
        "python": sys.version.split()[0],
        "python_executable": sys.executable,
        "modules": modules,
        "tesseract_binary": bool(shutil.which("tesseract")),
        "ocr": ocr.check_backends(cfg),
    }
    return report


def main(argv=None) -> int:
    args = parse_args(argv)
    cfg = build_config(args)

    if args.check:
        print(json.dumps(check_dependencies(cfg), indent=2))
        return 0

    if not args.pdf or not args.scan or not args.output:
        print("error: --pdf, --scan and --output are required", file=sys.stderr)
        return 2
    for path in (args.pdf, args.scan):
        if not os.path.isfile(path):
            print(f"error: file not found: {path}", file=sys.stderr)
            return 2

    if args.map_only:
        try:
            result = pipeline.map_only(args.pdf, args.scan, cfg)
        except Exception as exc:  # noqa: BLE001
            traceback.print_exc()
            print(f"error: {exc}", file=sys.stderr)
            return 1
        with open(args.output, "w", encoding="utf-8") as handle:
            json.dump(result, handle, indent=2)
        print(f"DONE {args.output}", flush=True)
        return 0

    progress = Progress(args.progress, args.cancel)
    progress.clear_cancel()
    progress.write("starting", 0, 0, "starting")

    try:
        result = pipeline.process(args.pdf, args.scan, cfg, progress)
    except Exception as exc:  # noqa: BLE001
        traceback.print_exc()
        progress.write("error", 0, 0, str(exc))
        print(f"error: {exc}", file=sys.stderr)
        return 1

    if args.page_limit:
        result["pages"] = result["pages"][: args.page_limit]

    with open(args.output, "w", encoding="utf-8") as handle:
        json.dump(result, handle, indent=2)

    if result.get("status") == "cancelled":
        print("CANCELLED", flush=True)
    else:
        print(f"DONE {args.output}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
