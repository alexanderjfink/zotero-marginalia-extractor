# Real-scan corpus

The `golden/` files are generated from the synthetic fixtures in
`tests/fixtures/`. To test against your own annotated scans:

1. Register a pair (copies by default; `--link` symlinks instead):
   ```bash
   .venv/bin/python tests/add_corpus.py mybook.pdf mybook-scan.pdf --name mybook
   # optional per-case settings:
   .venv/bin/python tests/add_corpus.py mybook.pdf mybook-scan.pdf --name mybook \
       --config '{"page_offset": 12}'
   ```
   This creates `mybook.pdf`, `mybook.scan.pdf` (and optionally `mybook.json`)
   in this folder. `golden_util.py` discovers pairs automatically.
2. Run the pipeline once:
   ```bash
   .venv/bin/python tests/update_golden.py
   ```
   This writes `tests/golden/corpus-mybook.json`.
3. Inspect the golden. If a detection is wrong, fix the pipeline or the scan
   settings first — the golden should describe *correct* behaviour, not merely
   current behaviour.
4. Commit the golden JSON (not the PDFs). `tests/test_golden.py` then guards
   against regressions.

Goldens intentionally ignore pixel geometry and confidence values, so they
survive small OpenCV changes. OCR text is compared exactly, so regenerate the
goldens when you upgrade Tesseract or change its language data.

Useful settings for a real scan:

- `page_offset` if printed page 1 is not PDF page 1,
- `split_spreads` for landscape book spreads,
- `perspective_correct` for phone photos,
- `match_pages` on (default) for partial or reordered scans.
