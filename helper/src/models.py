"""Data models shared across the Marginalia Extractor helper.

Everything here is plain dataclasses / dicts so the pipeline can be tested
without a live Zotero instance.
"""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Any, Optional

PROTOCOL_VERSION = 2
HELPER_VERSION = "0.6.0"


# Zotero's fixed annotation palette. The plugin only ever emits these hex
# values so downstream Zotero code can rely on them.
ZOTERO_COLORS: dict[str, str] = {
    "yellow": "#ffd400",
    "red": "#ff6666",
    "green": "#5fb236",
    "blue": "#2ea8e5",
    "purple": "#a28ae5",
    "magenta": "#e56eee",
    "orange": "#f19837",
    "grey": "#aaaaaa",
}

DEFAULT_ZOTERO_COLOR = "yellow"


@dataclass
class ColorRule:
    """A physical pen/highlighter colour and where it should land in Zotero.

    Hue bounds are in OpenCV's 0-179 hue scale. ``sat_min`` / ``val_min`` are
    on the usual 0-255 scale. ``kind`` hints whether this rule describes a
    highlighter (translucent) or a pen (opaque); ``any`` lets the segmenter
    decide.
    """

    name: str
    zotero: str = DEFAULT_ZOTERO_COLOR
    hue_min: int = 0
    hue_max: int = 179
    sat_min: int = 60
    val_min: int = 60
    sat_max: int = 255
    val_max: int = 255
    enabled: bool = True
    kind: str = "any"  # any | highlighter | pen
    output: str = "auto"  # auto | highlight | underline | note

    def zotero_hex(self) -> str:
        return ZOTERO_COLORS.get(self.zotero, ZOTERO_COLORS[DEFAULT_ZOTERO_COLOR])


@dataclass
class Config:
    """Runtime configuration, normally injected by the Zotero plugin."""

    dpi: int = 200
    mark_mode: str = "both"  # highlight | underline | both
    ocr_backend: str = "tesseract"  # tesseract | ollama | openai | anthropic | none
    ollama_url: str = "http://127.0.0.1:11434"
    ollama_model: str = "qwen2.5vl"
    # Unified LLM endpoint (any OpenAI-compatible server, or Anthropic).
    llm_url: str = ""
    llm_model: str = ""
    llm_api_key: str = ""
    llm_api_key_env: str = "MARGINALIA_LLM_API_KEY"
    llm_prompt: str = ""
    llm_timeout: int = 180
    llm_max_tokens: int = 1024
    llm_temperature: float = 0.0
    ocr_lang: str = "eng"
    ocr_line_split: bool = True
    note_fallback_color: str = DEFAULT_ZOTERO_COLOR
    colors: list[ColorRule] = field(default_factory=list)
    # Page mapping.
    page_offset: int = 0
    match_pages: bool = True
    split_spreads: bool = False
    perspective_correct: bool = True
    perspective_min_area: float = 0.30
    merge_cross_page: bool = True
    # Colour handling.
    white_balance: bool = True
    color_space: str = "hsv"  # hsv | lab
    remove_shadows: bool = True
    deskew: bool = True
    # Underlines / OCR.
    detect_dark_underlines: bool = True
    dark_underline_color: str = "grey"
    ocr_pdf_pages: bool = True
    ocr_detect_orientation: bool = True
    # Annotation content / provenance.
    comment_prefix: str = ""
    comment_suffix: str = ""
    append_scan_source: bool = False
    low_confidence: float = 0.35
    # Manual page mapping, keyed by scan label (e.g. "3" or "3a").
    map_overrides: dict = field(default_factory=dict)
    # Runtime.
    log_path: Optional[str] = None
    max_pages: int = 0  # 0 = all
    # Minimum connected-component area (in pixels, at the working resolution)
    # for a coloured region to count as a highlight.
    min_highlight_area: int = 120
    # Minimum area for a handwritten ink blob to count as a margin note.
    min_note_area: int = 60
    # Fraction of the page width treated as each margin.
    margin_fraction: float = 0.18
    # How many alternative sentences to expose for review re-targeting.
    max_candidates: int = 4
    # Write per-page review images (warped scan + PDF render).
    render_review_images: bool = True
    # Debug output directory. When set, alignment / segmentation images are written.
    debug_dir: Optional[str] = None
    # Runtime protocol paths managed by the CLI.
    progress_path: Optional[str] = None
    cancel_path: Optional[str] = None
    review_dir: Optional[str] = None

    @staticmethod
    def from_dict(data: dict[str, Any]) -> "Config":
        cfg = Config()
        for key in (
            "dpi",
            "mark_mode",
            "ocr_backend",
            "ollama_url",
            "ollama_model",
            "llm_url",
            "llm_model",
            "llm_api_key",
            "llm_api_key_env",
            "llm_prompt",
            "llm_timeout",
            "llm_max_tokens",
            "llm_temperature",
            "ocr_lang",
            "ocr_line_split",
            "note_fallback_color",
            "page_offset",
            "match_pages",
            "split_spreads",
            "perspective_correct",
            "perspective_min_area",
            "merge_cross_page",
            "white_balance",
            "color_space",
            "remove_shadows",
            "deskew",
            "detect_dark_underlines",
            "dark_underline_color",
            "ocr_pdf_pages",
            "ocr_detect_orientation",
            "comment_prefix",
            "comment_suffix",
            "append_scan_source",
            "low_confidence",
            "map_overrides",
            "log_path",
            "max_pages",
            "min_highlight_area",
            "min_note_area",
            "margin_fraction",
            "max_candidates",
            "render_review_images",
            "debug_dir",
            "progress_path",
            "cancel_path",
            "review_dir",
        ):
            if key in data and data[key] is not None:
                setattr(cfg, key, data[key])
        cfg.colors = [ColorRule(**c) for c in data.get("colors", [])] or default_color_rules()
        return cfg


def default_color_rules() -> list[ColorRule]:
    """Sensible defaults for the five Zotero highlighter colours.

    Hue values are on OpenCV's 0-179 scale. Yellow highlighter sits around
    25-35; pink/red wraps around 0; green ~40-85; blue ~90-130; purple
    ~130-165. These are starting points the user can tune in Preferences.
    """
    return [
        ColorRule("yellow", "yellow", hue_min=20, hue_max=38, sat_min=70),
        ColorRule("red", "red", hue_min=0, hue_max=8, sat_min=70),
        ColorRule("pink", "red", hue_min=165, hue_max=179, sat_min=60),
        ColorRule("green", "green", hue_min=40, hue_max=85, sat_min=60),
        ColorRule("blue", "blue", hue_min=90, hue_max=130, sat_min=60),
        ColorRule("purple", "purple", hue_min=130, hue_max=165, sat_min=50),
        # Dark pens used for margin notes. These describe "coloured ink".
        ColorRule("blue-pen", "blue", hue_min=100, hue_max=130, sat_min=80, val_max=180, kind="pen"),
        ColorRule("red-pen", "red", hue_min=0, hue_max=8, sat_min=80, val_max=180, kind="pen"),
    ]


@dataclass
class Annotation:
    """A single annotation to create in Zotero.

    ``rects`` are PDF user-space coordinates with a bottom-left origin, which
    is exactly what Zotero stores in ``annotationPosition``.
    """

    id: str
    page_index: int
    type: str  # highlight | underline | note
    color: str  # Zotero hex colour
    rects: list[list[float]]
    text: str = ""
    comment: str = ""
    source: str = "highlight"  # highlight | margin_note
    association_method: str = ""  # line | vertical | proximity | manual
    confidence: float = 0.0
    page_label: str = ""
    sort_index: str = ""
    scan_label: str = ""
    # Alternative sentence targets, for the review pane's re-targeting UI.
    candidates: list[dict[str, Any]] = field(default_factory=list)
    # A highlight/underline that continues onto the next PDF page.
    next_page_index: Optional[int] = None
    next_page_rects: list[list[float]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
