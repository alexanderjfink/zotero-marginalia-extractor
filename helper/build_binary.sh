#!/usr/bin/env bash
# Build a single-file helper executable with PyInstaller.
#
# Usage:
#   ./build_binary.sh
#
# Output: dist/marginalia-helper  (or dist/marginalia-helper.exe on Windows)
#
# The binary bundles Python and the helper dependencies, so users can point the
# plugin at this folder and skip the venv setup entirely.
set -euo pipefail

cd "$(dirname "$0")"

if [ ! -d .venv ]; then
  python3 -m venv .venv
fi

.venv/bin/python -m pip install --upgrade pip >/dev/null
.venv/bin/pip install -r requirements.txt pyinstaller >/dev/null

.venv/bin/pyinstaller \
  --onefile \
  --name marginalia-helper \
  --clean \
  --noconfirm \
  marginalia_helper.py

echo
echo "Binary written to: $(pwd)/dist/marginalia-helper"
echo "Point the plugin's Helper folder at: $(pwd)/dist"
