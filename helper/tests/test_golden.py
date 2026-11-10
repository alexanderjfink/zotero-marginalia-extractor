#!/usr/bin/env python3
"""Compare the current pipeline against committed golden JSON.

    .venv/bin/python tests/test_golden.py

If a golden is missing or intentionally stale, run tests/update_golden.py.
"""

from __future__ import annotations

import difflib
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

from tests import golden_util  # noqa: E402


def main() -> int:
    ok = True
    for name in golden_util.CASES:
        path = os.path.join(golden_util.GOLDEN_DIR, name + ".json")
        if not os.path.isfile(path):
            print(f"FAIL {name}: missing {path} (run tests/update_golden.py)")
            ok = False
            continue
        with open(path, "r", encoding="utf-8") as handle:
            golden = json.load(handle)
        current = golden_util.run_case(name)
        if current == golden:
            print(f"PASS {name}")
            continue
        ok = False
        print(f"FAIL {name}")
        golden_text = json.dumps(golden, indent=2, sort_keys=True).splitlines()
        current_text = json.dumps(current, indent=2, sort_keys=True).splitlines()
        diff = list(
            difflib.unified_diff(
                golden_text, current_text, fromfile="golden", tofile="current", lineterm=""
            )
        )
        print("\n".join(diff[:100]))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
