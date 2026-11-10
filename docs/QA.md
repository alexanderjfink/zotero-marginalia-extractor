# Live Zotero QA checklist

The helper pipeline is covered by `helper/tests/test_pipeline.py` on synthetic
fixtures. The plugin itself can only be verified inside a real Zotero install.
Work through this list after installing the `.xpi`; each item is a known
integration point.

## Setup

- [ ] **Preferences pane registers** — Settings → Marginalia Extractor is
  visible, has the icon, and does not throw in the Error Console.
- [ ] **Preferences persist** — change DPI, mark mode, page offset, OCR backend,
  colour mapping; restart Zotero; values are still set.
- [ ] **Helper paths** — set the helper folder and venv Python; "Test" reports
  the script and Python.
- [ ] **Binary mode** — build `helper/dist/marginalia-helper`, point the helper
  folder at `dist`; "Test" reports the binary, extraction uses it, and unchecking
  "Use the single-file binary" falls back to Python.
- [ ] **Colour sampling** — Settings → colour mapping → **Sample from image…**;
  open a PNG/JPG, drag over a highlighter, add the rule; it appears in the
  table and persists.
- [ ] **Tabs and search** — Setup/Pages/Marks/OCR/Review/Advanced switch
  correctly; searching filters the visible sections.
- [ ] **Profiles** — apply Essay/Book spread/Phone photo; save a custom profile;
  delete it; export settings to JSON and import them back.
- [ ] **Inline status** — Run check fills the Tesseract/Ollama/Helper chips and
  populates the language/model datalists.
- [ ] **Per-colour output** — set a colour rule to `underline` and confirm marks
  of that colour become underlines.
- [ ] **LLM presets** — choosing vLLM/LM Studio/llama.cpp/Ollama/OpenAI/
  Anthropic fills backend, URL, and model; Run check lists models when the
  endpoint is up.
- [ ] **LLM failure fallback** — point the backend at a dead URL; extraction
  still produces Tesseract text.
- [ ] **API key handling** — set a key via the env var; the key is not written
  to prefs or the log.
- [ ] **Setup check menu** — Tools → Marginalia Extractor: Check Setup prints a
  JSON report with `protocol_version: 2`, modules true, Tesseract true.
- [ ] **Headless logic harness** — `node tests/js/plugin_logic.test.js` passes.
- [ ] **Binary smoke test** — `dist/marginalia-helper --check` reports protocol
  2, and `dist/marginalia-helper --pdf … --scan … --output …` produces JSON.

## Menus

- [ ] Right-click a PDF attachment → **Extract Marginalia…** and **Remove
  Marginalia Extraction** appear.
- [ ] Right-click a parent item whose child is a PDF → the same items appear.
- [ ] Right-click a non-PDF item → the items are hidden.
- [ ] Tools menu contains Extract, Cancel, and Check Setup.

## Extraction

- [ ] Run on a small PDF + scan: a progress headline shows
  `Marginalia: page N/M`.
- [ ] Tools → Cancel stops the run; no annotations are written; an alert says
  cancelled.
- [ ] A missing helper / wrong Python path produces a readable error.
- [ ] A helper protocol mismatch (edit `PROTOCOL_VERSION` in the helper only)
  is reported instead of silently proceeding.
- [ ] Low-alignment pages appear in the review header warnings.
- [ ] Unmatched scan pages are skipped and listed.
- [ ] A phone photo with visible page corners is perspective-warped before
  alignment (compare the review images).
- [ ] A highlighter stroke running off the bottom of one page onto the next is
  represented as one annotation with `nextPageRects`.
- [ ] An image-only PDF (no text layer) still produces annotations with target
  text when **OCR image-only PDFs** is on.
- [ ] A black-pen underline under text becomes a grey `underline` annotation.
- [ ] A deliberately skewed scan is deskewed; a shadowed page still segments
  highlights correctly.
- [ ] **Preview Page Mapping…** opens, lets you change a scan→PDF row, and the
  subsequent extraction honors the correction.
- [ ] **Batch Extract Selected PDFs…** pairs several selected PDFs with scans
  and reports created/replaced/failed counts.

## Review window

- [ ] The dialog opens with the annotation list, page selector, scan/PDF
  images, and sentence list.
- [ ] `file://` images load; if not, the pane hides them without throwing.
- [ ] Clicking an annotation card selects it and shows its page.
- [ ] The current target box is drawn on both images in the right place.
- [ ] Candidate boxes (orange) are clickable and re-target the note.
- [ ] Selecting a sentence then **Set as target** updates the card text and
  boxes.
- [ ] Page selector lets you target a sentence on a different page.
- [ ] A cross-page row shows a “Next page” strip with the second page's boxes.
- [ ] `j`/`k` and the arrow keys move between rows; `Escape` closes.
- [ ] Search/source/**flagged only** filters narrow the list; bulk select +
  colour/type/delete apply to selected rows; Undo restores the previous state.
- [ ] `d` toggles delete, `c` cycles colour, `t` cycles type, `Enter` edits the
  comment, `Ctrl+Z` undoes, `Ctrl+Enter` applies, `?` shows help.
- [ ] **Add annotation from selected sentence** creates a new card.
- [ ] Delete checkbox strikes the card out.
- [ ] Colour / type / comment edits survive switching cards.
- [ ] Cancel closes with no writes.

## Apply

- [ ] Apply creates annotations under the correct attachment.
- [ ] Page index, page label, rects, colour, type, and comment are correct in
  Zotero's annotation pane.
- [ ] Highlight vs underline changes are accepted by `saveTx`.
- [ ] Annotations carry the `marginalia-extractor` tag (and a run tag).
- [ ] Re-running with "replace previous" removes the old run and does not
  duplicate.
- [ ] Staged apply: if a new annotation fails to save, the previous tagged run
  is still present (old run is deleted only after creation succeeds).
- [ ] **Remove Marginalia Extraction** deletes only tagged annotations, leaving
  hand-made ones alone.
- [ ] Cancelling the review writes nothing.
- [ ] **Run History…** lists runs for the PDF; Restore re-applies one; Delete
  removes it from history.
- [ ] **Export Annotations to Markdown…** writes page/type/colour/text/comment.
- [ ] **Open Last Marginalia Log** opens the helper log file.

## Error console / stability

- [ ] Disable/re-enable the plugin; menus and prefs pane come back without
  duplicates.
- [ ] Restart Zotero with a restored reader tab; the plugin still loads.
- [ ] No uncaught exceptions in Tools → Developer → Error Console during any
  of the above.

Record failures with the Zotero version, OS, and the Error Console text.
