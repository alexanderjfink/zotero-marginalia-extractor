#!/usr/bin/env python3
"""Register a real original/scan pair in the test corpus.

    .venv/bin/python tests/add_corpus.py mybook.pdf mybook-scan.pdf --name mybook
    .venv/bin/python tests/add_corpus.py mybook.pdf mybook-scan.pdf --name mybook \
        --config '{"page_offset": 12, "split_spreads": false}'

Then regenerate the goldens:
    .venv/bin/python tests/update_golden.py

Use --link to symlink instead of copying (keeps copyrighted scans out of the
repository on your machine).
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
CORPUS = os.path.join(HERE, "corpus")


def slug(value: str) -> str:
    value = re.sub(r"[^A-Za-z0-9._-]+", "-", value).strip("-")
    return value or "corpus"


def main() -> int:
    parser = argparse.ArgumentParser(description="Add a real scan pair to the golden corpus.")
    parser.add_argument("original", help="PDF already in Zotero")
    parser.add_argument("scan", help="Scanned PDF of the annotated pages")
    parser.add_argument("--name", help="Case name (default: original filename stem)")
    parser.add_argument("--link", action="store_true", help="Symlink instead of copy")
    parser.add_argument("--config", help="JSON config overrides for this case")
    args = parser.parse_args()

    for path in (args.original, args.scan):
        if not os.path.isfile(path):
            print(f"error: not a file: {path}", file=sys.stderr)
            return 2

    os.makedirs(CORPUS, exist_ok=True)
    name = slug(args.name or os.path.splitext(os.path.basename(args.original))[0])
    original_dest = os.path.join(CORPUS, name + ".pdf")
    scan_dest = os.path.join(CORPUS, name + ".scan.pdf")

    for src, dest in ((args.original, original_dest), (args.scan, scan_dest)):
        if os.path.exists(dest):
            os.remove(dest)
        if args.link:
            os.symlink(os.path.abspath(src), dest)
        else:
            shutil.copy2(src, dest)

    if args.config:
        overrides = json.loads(args.config)
        with open(os.path.join(CORPUS, name + ".json"), "w", encoding="utf-8") as handle:
            json.dump(overrides, handle, indent=2)
    elif os.path.isfile(os.path.join(CORPUS, name + ".json")):
        os.remove(os.path.join(CORPUS, name + ".json"))

    print(f"Added corpus case '{name}'.")
    print("  " + original_dest)
    print("  " + scan_dest)
    print("\nNext:")
    print("  .venv/bin/python tests/test_pipeline.py")
    print("  .venv/bin/python tests/update_golden.py")
    print("  .venv/bin/python tests/test_golden.py")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
