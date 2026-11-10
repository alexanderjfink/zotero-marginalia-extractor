#!/usr/bin/env python3
"""Regenerate the golden JSON files from the current fixtures.

Run after intentionally changing detection behaviour:
    .venv/bin/python tests/update_golden.py
"""

from __future__ import annotations

import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

from tests import golden_util  # noqa: E402


def main() -> int:
    os.makedirs(golden_util.GOLDEN_DIR, exist_ok=True)
    for name in golden_util.CASES:
        result = golden_util.run_case(name)
        path = os.path.join(golden_util.GOLDEN_DIR, name + ".json")
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(result, handle, indent=2, sort_keys=True)
        print("wrote", path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
