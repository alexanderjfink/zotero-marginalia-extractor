# Marginalia Extractor

Turn your **analog** reading — colored highlighter strokes and handwritten
margin notes on paper — into real, editable **Zotero annotations**.

You put the PDF of a book or essay in Zotero, print/have a paper copy, read it
with a pen and highlighter, scan the annotated pages, and point the plugin at
the scan. It aligns the scan against the PDF page by page, detects your
highlights and margin notes, transcribes the notes, and creates Zotero
annotations. Margin notes are attached by highlighting the sentence the note
points to.

Vibe coded with deepseek-v4.1-flash (via OpenCode).

---

## How it works

1. **You** scan the annotated pages into a PDF — the whole book, just the
   annotated pages, or two-page spreads.
2. The plugin runs a **local Python helper** (no cloud services):
   - maps each scan page to its PDF page by text content (so partial and
     reordered scans work), with a page offset and spread splitting,
   - corrects page perspective for phone photos, deskews, and flattens gutter
     shadows / lighting gradients,
   - aligns the scan to the PDF page with a homography (ECC, ORB fallback),
   - white-balances the scan, then segments colored highlighter / pen strokes
     by HSV or Lab nearest-colour,
   - removes printed text to isolate handwriting, and detects black/blue pen
     underlines under the text,
   - finds margin notes and the drawn lines, curved strokes or margin brackets
     that point to the sentence they annotate,
   - transcribes notes with **Tesseract** (line by line, orientation-corrected),
     **Ollama**, any **OpenAI-compatible vision endpoint** (vLLM, LM Studio,
     llama.cpp, LocalAI, OpenRouter, OpenAI…), or **Anthropic**,
   - OCRs image-only PDF pages so sentence matching still works when the PDF
     has no text layer,
   - joins highlights that run across a page break into one two-page
     annotation,
   - writes an annotation JSON plus per-page sentence models and review images.
3. The plugin opens a **preview review window** — nothing is written yet. It
   shows the scan and PDF pages with overlays, lists every detected annotation,
   and lets you fix colour/type/comment, re-target a note by clicking any
   sentence, add a missed annotation, or delete a bad one.
4. On **Apply**, the annotations are created and tagged; a later run can replace
   the previous extraction instead of duplicating it.

### Page mapping

By default the helper matches scan pages to PDF pages using their **text**
(the PDF text layer vs. OCR/the scan's own text layer). This handles:

- a scan containing only the annotated pages,
- reordered or duplicated pages,
- front matter, via **Page offset**,
- **two-page spreads**, via split-spreads (geometric half split, gutter-aware).

### How a margin note finds its sentence

Association is attempted in this order, and the method used is recorded for
review:

1. **Drawn connector** — a straight line/arrow, a curved stroke, or a margin
   bracket is detected; the far endpoint is matched to the nearest sentence.
2. **Vertical anchor** — with no connector, the sentence at the same vertical
   level is chosen. Small, sparse marks (asterisks, ticks) are labelled
   `marker` in the review so you can spot them.
3. **Proximity** — finally, the nearest sentence.
4. **Manual correction** — the review window shows the nearest sentence
   candidates and the full sentence list for the page; click one to re-target.

### LLM transcription endpoints

The OCR backend can be Tesseract, Ollama, any **OpenAI-compatible** vision
endpoint, or Anthropic. Settings provides presets:

| Preset | Base URL | Notes |
|--------|----------|-------|
| Ollama | `http://127.0.0.1:11434` | Uses `/api/generate`; e.g. `qwen2.5vl` |
| vLLM | `http://127.0.0.1:8000/v1` | OpenAI-compatible; e.g. `Qwen/Qwen2.5-VL-7B-Instruct` |
| LM Studio | `http://127.0.0.1:1234/v1` | OpenAI-compatible local server |
| llama.cpp | `http://127.0.0.1:8080/v1` | `llama-server` with a vision model |
| OpenRouter | `https://openrouter.ai/api/v1` | Remote; set an API key |
| OpenAI | `https://api.openai.com/v1` | Remote; e.g. `gpt-4o-mini` |
| Anthropic | `https://api.anthropic.com` | Messages API; e.g. `claude-3-5-sonnet-latest` |

For remote endpoints, prefer the **Key env var**
(`MARGINALIA_LLM_API_KEY` by default) over storing a key in preferences. If the
endpoint fails or returns nothing, transcription falls back to Tesseract. The
prompt, timeout, max tokens, and temperature are configurable.

---

## Requirements

- Zotero 7, 8, 9 or 10
- Python 3.10+ and the Tesseract binary
- Optional handwriting/vision backend: [Ollama](https://ollama.com), any
  OpenAI-compatible vision server (vLLM, LM Studio, llama.cpp, LocalAI,
  OpenRouter, OpenAI), or Anthropic Claude

### macOS

```bash
brew install tesseract
# optional
brew install --cask ollama && ollama pull qwen2.5vl
```

### Ubuntu / Debian

```bash
sudo apt install tesseract-ocr
```

---

## Install the helper

The Python helper is **not** bundled in the `.xpi` (Zotero installs plugins as
zip archives, so the script must live on disk to be executed). Clone/copy this
repository somewhere permanent, then:

```bash
cd helper
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
```

Note the two paths you will need in the plugin settings:

- **Helper folder** — the absolute path to `.../zotero-marginalia-extractor/helper`
- **Python executable** — the absolute path to `.../helper/.venv/bin/python`

### Zero-setup binary (optional)

To avoid the Python/venv setup on other machines:

```bash
cd helper
./build_binary.sh
```

This produces `helper/dist/marginalia-helper` (PyInstaller, one file). Point the
plugin's **Helper folder** at `helper/dist` and leave the Python path untouched;
the plugin uses the binary automatically when present. Uncheck **Use the
single-file binary** to force Python mode.

---

## Build and install the plugin

```bash
./build.sh
```

That produces `marginalia-extractor.xpi`. In Zotero:

1. **Tools → Plugins**
2. Gear icon → **Install Plugin From File…**
3. Select `marginalia-extractor.xpi` and restart Zotero.

Then open **Settings → Marginalia Extractor** and:

- set the **Helper folder** and **Python executable**,
- press **Test** to confirm the helper is found,
- choose your **Mark type** (both / highlight / underline),
- choose the **OCR backend** (Tesseract or Ollama),
- tune the **colour mapping** table if your highlighters are unusual.

---

## Usage

1. Put the PDF in Zotero and make sure it has a text layer (most do). Image-only
   PDFs need OCR for page matching; the helper falls back to layout matching.
2. Scan your annotated paper copy into a PDF. You can scan the whole document,
   only the annotated pages, or two-page spreads.
3. In Zotero, right-click the PDF attachment (or its parent item) and choose
   **Extract Marginalia…**
4. Pick the scanned PDF.
5. Watch **Tools → Cancel Marginalia Extraction** if you need to stop; the
   progress headline shows the current page.
6. The **review window** opens. Fix colours, types, comments, re-target notes,
   add or delete annotations. Use `j`/`k` or the arrow keys to move between
   rows. Cross-page highlights show a “Next page” strip.
7. Press **Apply changes**. Previously extracted annotations for this PDF are
   replaced (configurable), and the new ones are tagged `marginalia-extractor`.

To undo an extraction, right-click the attachment → **Remove Marginalia
Extraction** (only tagged annotations are removed).

### Other workflows

- **Preview Page Mapping…** — inspect the automatic scan→PDF mapping, change
  any page, then extract with those corrections.
- **Marginalia Run History…** — restore a previous run (re-applies its
  annotations) or delete it from history.
- **Export Annotations to Markdown…** — write the PDF's annotations to a
  Markdown file (page, type, colour, text, comment).
- **Batch Extract Selected PDFs…** — pair several selected PDFs with scans and
  run them sequentially. Batch applies annotations without the review window.
- **Tools → Open Last Marginalia Log** — open the helper run log.

---

## Settings

| Setting | Default | Meaning |
|---------|---------|---------|
| Helper folder / Python | — | Paths to the helper and its venv Python |
| Use binary | on | Prefer `marginalia-helper` when present |
| Render DPI | 200 | PDF/scan render resolution |
| Mark type | both | highlight / underline / both |
| Margin note colour | yellow | Fallback colour for transcribed notes |
| Page offset | 0 | scan page 1 = PDF page (1 + offset) |
| Match pages by text | on | Fingerprint scan pages to PDF pages |
| Split spreads | off | Split landscape scans into two pages |
| Correct perspective | on | Detect page corners for phone photos |
| Join cross-page highlights | on | Two-page annotation at a page break |
| Colour matching | HSV | HSV ranges or Lab nearest-colour |
| White balance | on | Normalise scanner colour cast |
| Deskew | on | Rotate visibly skewed scans |
| Remove shadows | on | Flatten gutter shadows / lighting gradients |
| Dark pen underlines | on | Detect black/blue pen underlines |
| Dark underline colour | grey | Zotero colour for dark underlines |
| OCR image-only PDFs | on | Build a text model for PDFs with no text layer |
| OCR orientation | on | Correct rotated notes before Tesseract |
| White balance | on | Normalise scanner colour cast |
| OCR backend | tesseract | tesseract / ollama / openai / anthropic / none |
| LLM preset | — | Ollama, vLLM, LM Studio, llama.cpp, OpenRouter, OpenAI, Anthropic, Custom |
| Endpoint URL | — | OpenAI-compatible base (`…/v1`) or Anthropic base |
| LLM model | — | e.g. `Qwen2.5-VL`, `llava`, `gpt-4o-mini`, `claude-…` |
| API key / env var | — | optional; prefer `MARGINALIA_LLM_API_KEY` over storing a key |
| LLM prompt | built-in | custom transcription prompt |
| LLM timeout / max tokens / temperature | 180 / 1024 / 0 | request tuning |
| OCR language | eng | Tesseract `-l` value |
| Split note into lines | on | Line segmentation before Tesseract |
| Suggested sentences | 4 | Candidate targets exposed in review |
| Replace previous | on | Re-running replaces the last extraction |
| Profile | Essay | Essay / Book spread / Phone photo, plus saved profiles |
| Per-colour output | auto | auto / highlight / underline / note per colour rule |
| New annotation colour/type | yellow / highlight | Defaults for annotations added in review |
| Comment prefix/suffix | — | Wrapping text for transcribed notes |
| Append scan source | off | Add “— scanned p. N” to notes |
| Flag below confidence | 0.35 | Low-confidence threshold for the review “flagged only” filter |
| Min highlight/note area | 120 / 60 | Detection thresholds |
| Margin fraction | 0.18 | Width treated as each margin |
| Colour mapping | see table | Physical HSV range → Zotero colour |

---

## Colour mapping

Each row maps a physical colour — described by an OpenCV HSV range — to one of
Zotero's annotation colours:

| Field | Meaning |
|-------|---------|
| Name | Label for your reference (e.g. `yellow`, `pink-pen`) |
| Zotero | Target annotation colour (one of Zotero's palette) |
| Hue min/max | Hue range on OpenCV's `0–179` scale |
| Sat min | Minimum saturation (`0–255`) |
| Val min/max | Value/brightness range (`0–255`) |
| Type | `any`, `highlighter`, or `pen` |
| On | Enable/disable the rule |

**Tips**

- Use **Sample from image…** to click a highlighted/ink area in a scan; the
  wizard fills the HSV range and adds the rule.
- Yellow highlighter is usually `H 20–38`; pink/red wraps around `0`/`179`.
- Coloured pens are darker: use a lower `Val max` (e.g. `180`).
- If two rules overlap, the first matching row wins.

---

## Package layout

```
zotero-marginalia-extractor/
├── manifest.json
├── bootstrap.js
├── build.sh
├── docs/
│   └── QA.md                    Live Zotero QA checklist
├── content/
│   ├── marginaliaExtractor.js   Plugin controller (preview-first flow)
│   ├── preferences.xhtml        Settings panel
│   ├── prefs.js                 Settings wiring
│   ├── calibrate.xhtml          Colour sampling wizard
│   ├── calibrate.js             Colour sampling logic
│   ├── review.xhtml             Review window (images + re-targeting)
│   └── review.js                Review window logic
├── icons/
└── helper/                      Local Python helper (installed separately)
    ├── marginalia_helper.py     CLI (+ --check diagnostics)
    ├── build_binary.sh          PyInstaller single-file build
    ├── requirements.txt
    ├── src/
    │   ├── align.py             Homography alignment
    │   ├── pagematch.py         Scan→PDF page text matching
    │   ├── fingerprint.py       Layout-hash fallback
    │   ├── perspective.py       Page-corner detection / warp
    │   ├── segment.py           Colour/ink segmentation, white balance, deskew
    │   ├── lines.py             Line/curve/bracket connectors
    │   ├── ocr.py               Tesseract + Ollama, line splitting, orientation
    │   ├── textmatch.py         Sentence matching + candidates
    │   ├── pdf_pages.py         Rendering, text, reading order, OCR fallback
    │   ├── pagecache.py         Cached page text models
    │   ├── pipeline.py          Orchestration + page models
    │   └── progress.py          Progress/cancel protocol
    └── tests/                   Fixtures, regression, golden, corpus tools
```

The plugin logic has a headless harness under `tests/js/` that runs without
Zotero.

---

## Troubleshooting

- **"The Python helper is not configured"** — set the Helper folder and Python
  executable in Settings.
- **Extraction failed immediately** — run the helper manually to see the real
  error:
  ```bash
  helper/.venv/bin/python helper/marginalia_helper.py \
    --pdf  /path/to/library.pdf \
    --scan /path/to/scan.pdf \
    --output /tmp/out.json
  ```
- **No annotations detected** — increase Render DPI, or widen your colour
  ranges.
- **Wrong pages** — turn on **Match pages by text**; for a book whose printed
  page 1 is not PDF page 1, set **Page offset**. Spreads need **Split spreads**.
- **Wrong sentence for a note** — click the correct sentence in the review
  window and press **Set as target**. The method/confidence is shown on each
  card; low-confidence rows are flagged.
- **Handwriting unreadable** — switch the OCR backend to Ollama, an
  OpenAI-compatible vision endpoint, or Anthropic. Line splitting is on by
  default for Tesseract.
- **LLM endpoint unreachable** — OpenAI-compatible servers need a base URL
  ending in `/v1` (vLLM `:8000/v1`, LM Studio `:1234/v1`, llama.cpp `:8080/v1`);
  Anthropic uses `https://api.anthropic.com`. Run **Check Setup** to see the
  reported URL, models, and error. For remote APIs, set the key through the
  environment variable rather than storing it in preferences.
- **No text in the PDF** — enable **OCR image-only PDFs**; the helper OCRs the
  PDF pages to build a word/sentence model and page fingerprints. Disable it if
  you prefer layout-only matching (faster, less accurate).
- **Skewed or shadowed scans** — **Deskew** and **Remove shadows** are on by
  default; turn them off for clean flatbed scans if they over-correct.
- **Black-pen underlines missed** — check **Detect black/blue pen underlines**
  and the **Dark underline colour** setting.
- **Review images do not load** — some Zotero builds block `file://` images in
  dialogs; the list, editing and re-targeting still work.
- **Run the setup check** — Tools → Marginalia Extractor: Check Setup, or
  `python marginalia_helper.py --check`.

---

## Testing

```bash
# helper pipeline + OCR / vision
cd helper
.venv/bin/python tests/test_pipeline.py   # behavioural regression
.venv/bin/python tests/test_golden.py     # golden JSON comparison
.venv/bin/python tests/update_golden.py   # regenerate after intentional changes
.venv/bin/python tests/add_corpus.py mybook.pdf mybook-scan.pdf --name mybook

# plugin logic (headless, no Zotero needed)
cd ..
node tests/js/plugin_logic.test.js
```

Add real scan pairs with `tests/add_corpus.py`; they are discovered
automatically by the golden harness. See `helper/tests/corpus/README.md`.

---

## Roadmap

Done in 0.5: tabbed preferences with search and profiles/import/export, inline
helper status, per-colour output, discovered Tesseract languages and Ollama
models, page-mapping preview and correction, review filters/bulk edit/undo/
shortcuts, run history, batch extraction, Markdown export, provenance tags,
run logging, helper version checks, and Windows argv handling.

Still ahead:

- A committed corpus of real annotated scans (the harness is ready; add pairs
  with `tests/add_corpus.py` and regenerate goldens)
- Full localization (the UI is English-only; no locale files yet)
- Curved-spine dewarping for thick books (shadow flattening and deskew are done)
- Hand-drawn arrowhead classification (asterisks/ticks are labelled `marker`)
- Parallel page processing for very large books (page-text caching is done)
- Optional per-note “re-OCR with another backend” in the review window
- Binary auto-download/update (version checking is in; download is not)
