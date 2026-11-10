#!/usr/bin/env bash
# Build the Marginalia Extractor plugin as an installable .xpi file.
# Usage: ./build.sh
#
# The Python helper is NOT bundled into the .xpi. It lives in helper/ and is
# installed separately (see README). This keeps the plugin package small.
set -euo pipefail

PLUGIN_ID="marginalia-extractor@zotero-marginalia-extractor"
OUTPUT="marginalia-extractor.xpi"

echo "Building $OUTPUT ..."

# Remove previous build.
rm -f "$OUTPUT"

# An .xpi is just a zip of the plugin root (without the outer directory).
zip -r "$OUTPUT" \
  manifest.json \
  bootstrap.js \
  content/ \
  icons/

echo "Done: $OUTPUT"
echo ""
echo "To install:"
echo "  1. Open Zotero -> Tools -> Plugins"
echo "  2. Click the gear icon -> Install Plugin From File..."
echo "  3. Select $(pwd)/$OUTPUT"
echo ""
echo "Remember to install the Python helper:"
echo "  cd helper && python3 -m venv .venv && . .venv/bin/activate && pip install -r requirements.txt"
