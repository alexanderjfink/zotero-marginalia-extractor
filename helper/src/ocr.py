"""Handwriting transcription backends.

Tesseract is always available when the binary is installed. Ollama is optional
and used for a local vision-language model when configured; if the call fails
we fall back to Tesseract so the pipeline never hard-fails on OCR.
"""

from __future__ import annotations

import base64
import json
import os
import re
import urllib.error
import urllib.request
from typing import Optional

import cv2
import numpy as np

from .models import Config
from .util import Rect

try:
    import pytesseract
except ImportError:  # pragma: no cover
    pytesseract = None  # type: ignore


DEFAULT_PROMPT = (
    "Transcribe the handwritten text in this image exactly as written. "
    "Preserve the author's spelling, punctuation and line breaks. "
    "If a word is illegible, write [illegible]. "
    "Output only the transcription, with no commentary or formatting."
)
OLLAMA_PROMPT = DEFAULT_PROMPT  # backwards compatibility


def _llm_key(cfg: Config) -> str:
    if cfg.llm_api_key:
        return cfg.llm_api_key
    env_name = cfg.llm_api_key_env or "MARGINALIA_LLM_API_KEY"
    return os.environ.get(env_name, "")


def _effective_url(cfg: Config, backend: str) -> str:
    if cfg.llm_url:
        return cfg.llm_url.rstrip("/")
    if backend == "ollama":
        return (cfg.ollama_url or "http://127.0.0.1:11434").rstrip("/")
    if backend == "openai":
        return "http://127.0.0.1:8000/v1"
    if backend == "anthropic":
        return "https://api.anthropic.com"
    return ""


def _effective_model(cfg: Config, backend: str) -> str:
    if cfg.llm_model:
        return cfg.llm_model
    if backend == "ollama":
        return cfg.ollama_model or "qwen2.5vl"
    return ""


def _prompt(cfg: Config) -> str:
    return cfg.llm_prompt or DEFAULT_PROMPT


def _png_base64(crop_rgb: np.ndarray) -> Optional[tuple[bytes, str]]:
    ok, buffer = cv2.imencode(".png", cv2.cvtColor(crop_rgb, cv2.COLOR_RGB2BGR))
    if not ok:
        return None
    raw = buffer.tobytes()
    return raw, base64.b64encode(raw).decode("ascii")


def _post_json(url: str, payload: dict, headers: dict, timeout: float) -> Optional[dict]:
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json", **headers},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError):
        return None


def _list_models(base: str, headers: dict, backend: str) -> list[str]:
    if backend == "ollama":
        endpoint = base + "/api/tags"
    elif backend == "anthropic":
        endpoint = base + ("/models" if base.endswith("/v1") else "/v1/models")
    else:
        endpoint = base + "/models"
    request = urllib.request.Request(endpoint, headers=headers, method="GET")
    try:
        with urllib.request.urlopen(request, timeout=6) as response:
            body = json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError):
        return []
    if backend == "ollama":
        return [model.get("name", "") for model in body.get("models", [])]
    return [model.get("id", "") for model in body.get("data", [])]


def crop(rgb: np.ndarray, rect: Rect, pad: int = 6) -> np.ndarray:
    h, w = rgb.shape[:2]
    x0 = max(0, int(rect[0]) - pad)
    y0 = max(0, int(rect[1]) - pad)
    x1 = min(w, int(rect[2]) + pad)
    y1 = min(h, int(rect[3]) + pad)
    return rgb[y0:y1, x0:x1].copy()


def _prepare_for_tesseract(crop_rgb: np.ndarray) -> np.ndarray:
    gray = cv2.cvtColor(crop_rgb, cv2.COLOR_RGB2GRAY)
    # Upscale small crops — Tesseract likes ~30px cap height.
    if gray.shape[0] < 100:
        scale = 100 / max(1, gray.shape[0])
        gray = cv2.resize(gray, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
    gray = cv2.bilateralFilter(gray, 5, 30, 30)
    _, binary = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    return binary


def split_into_lines(crop_rgb: np.ndarray) -> list[np.ndarray]:
    """Slice a note crop into individual text lines using horizontal projection."""
    if crop_rgb.size == 0:
        return [crop_rgb]
    gray = cv2.cvtColor(crop_rgb, cv2.COLOR_RGB2GRAY)
    binary = cv2.adaptiveThreshold(
        gray, 255, cv2.ADAPTIVE_THRESH_MEAN_C, cv2.THRESH_BINARY_INV, 25, 10
    )
    binary = cv2.morphologyEx(binary, cv2.MORPH_OPEN, np.ones((2, 2), np.uint8))
    projection = (binary > 0).sum(axis=1)
    threshold = max(2, int(crop_rgb.shape[1] * 0.015))
    bands: list[tuple[int, int]] = []
    start = None
    for y, count in enumerate(projection):
        if count > threshold:
            if start is None:
                start = y
        elif start is not None:
            bands.append((start, y - 1))
            start = None
    if start is not None:
        bands.append((start, len(projection) - 1))

    # Merge bands separated by only a few pixels, drop slivers.
    merged: list[tuple[int, int]] = []
    for band in bands:
        if merged and band[0] - merged[-1][1] <= 3:
            merged[-1] = (merged[-1][0], band[1])
        else:
            merged.append(band)
    merged = [b for b in merged if b[1] - b[0] >= 4]

    if len(merged) < 2:
        return [crop_rgb]

    crops: list[np.ndarray] = []
    height = crop_rgb.shape[0]
    for y0, y1 in merged:
        pad = 3
        crops.append(crop_rgb[max(0, y0 - pad) : min(height, y1 + pad + 1), :])
    return crops


def ocr_tesseract(crop_rgb: np.ndarray, lang: str = "eng", psm: int = 6) -> str:
    if pytesseract is None:
        return ""
    prepared = _prepare_for_tesseract(crop_rgb)
    try:
        text = pytesseract.image_to_string(prepared, lang=lang, config=f"--psm {psm}")
    except Exception:
        return ""
    return _clean(text)


def _prepare_page(crop_rgb: np.ndarray) -> np.ndarray:
    """Binarise a full page without resizing (keeps OCR coordinates valid)."""
    gray = cv2.cvtColor(crop_rgb, cv2.COLOR_RGB2GRAY)
    _, binary = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    return binary


def ocr_tesseract_data(crop_rgb: np.ndarray, lang: str = "eng") -> list[dict]:
    """OCR a full page and return word boxes (pixels, top-left origin)."""
    if pytesseract is None:
        return []
    prepared = _prepare_page(crop_rgb)
    try:
        data = pytesseract.image_to_data(
            prepared,
            lang=lang,
            config="--psm 3",
            output_type=pytesseract.Output.DICT,
        )
    except Exception:
        return []
    words: list[dict] = []
    count = len(data.get("text", []))
    for index in range(count):
        text = (data["text"][index] or "").strip()
        if not text:
            continue
        x = int(data["left"][index])
        y = int(data["top"][index])
        w = int(data["width"][index])
        h = int(data["height"][index])
        if w <= 0 or h <= 0:
            continue
        words.append(
            {
                "text": text,
                "rect": (x, y, x + w, y + h),
                "block": int(data["block_num"][index]),
                "line": int(data["line_num"][index]),
            }
        )
    return words


def detect_orientation(crop_rgb: np.ndarray) -> int:
    """Return the clockwise rotation Tesseract OSD recommends (0/90/180/270)."""
    if pytesseract is None:
        return 0
    prepared = _prepare_page(crop_rgb)
    try:
        osd = pytesseract.image_to_osd(prepared)
    except Exception:
        return 0
    match = re.search(r"Rotate:\s*(\d+)", osd)
    if not match:
        return 0
    angle = int(match.group(1)) % 360
    return angle if angle in (90, 180, 270) else 0


def rotate_image(image: np.ndarray, angle: int) -> np.ndarray:
    if angle % 360 == 0:
        return image
    height, width = image.shape[:2]
    center = (width / 2.0, height / 2.0)
    matrix = cv2.getRotationMatrix2D(center, angle, 1.0)
    return cv2.warpAffine(
        image, matrix, (width, height),
        flags=cv2.INTER_CUBIC, borderMode=cv2.BORDER_REPLICATE,
    )


def ocr_ollama(crop_rgb: np.ndarray, cfg: Config) -> Optional[str]:
    """Send the crop to an Ollama vision model."""
    encoded = _png_base64(crop_rgb)
    if encoded is None:
        return None
    _raw, image_b64 = encoded
    base = _effective_url(cfg, "ollama")
    payload = {
        "model": _effective_model(cfg, "ollama"),
        "prompt": _prompt(cfg),
        "images": [image_b64],
        "stream": False,
    }
    body = _post_json(base + "/api/generate", payload, {}, cfg.llm_timeout)
    if not body:
        return None
    return _clean(body.get("response", ""))


def ocr_openai(crop_rgb: np.ndarray, cfg: Config) -> Optional[str]:
    """OpenAI-compatible vision endpoint (vLLM, LM Studio, llama.cpp, OpenRouter…)."""
    encoded = _png_base64(crop_rgb)
    if encoded is None:
        return None
    raw, _b64 = encoded
    data_url = "data:image/png;base64," + base64.b64encode(raw).decode("ascii")
    base = _effective_url(cfg, "openai")
    headers = {}
    key = _llm_key(cfg)
    if key:
        headers["Authorization"] = "Bearer " + key
    model = _effective_model(cfg, "openai")
    if not model:
        models = _list_models(base, headers, "openai")
        model = models[0] if models else ""
    payload = {
        "model": model,
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": _prompt(cfg)},
                    {"type": "image_url", "image_url": {"url": data_url}},
                ],
            }
        ],
        "max_tokens": cfg.llm_max_tokens,
        "temperature": cfg.llm_temperature,
        "stream": False,
    }
    body = _post_json(base + "/chat/completions", payload, headers, cfg.llm_timeout)
    if not body:
        return None
    choices = body.get("choices") or []
    if not choices:
        return None
    choice = choices[0]
    message = choice.get("message") or {}
    content = message.get("content")
    if isinstance(content, list):
        parts = []
        for block in content:
            if isinstance(block, dict):
                if block.get("type") == "text" and block.get("text"):
                    parts.append(block["text"])
            elif isinstance(block, str):
                parts.append(block)
        content = " ".join(parts)
    if not content:
        content = choice.get("text") or ""
    return _clean(content)


def ocr_anthropic(crop_rgb: np.ndarray, cfg: Config) -> Optional[str]:
    """Anthropic Messages API with an image block."""
    encoded = _png_base64(crop_rgb)
    if encoded is None:
        return None
    _raw, image_b64 = encoded
    base = _effective_url(cfg, "anthropic")
    url = base + ("/messages" if base.endswith("/v1") else "/v1/messages")
    headers = {"anthropic-version": "2023-06-01"}
    key = _llm_key(cfg)
    if key:
        headers["x-api-key"] = key
    model = _effective_model(cfg, "anthropic")
    if not model:
        models = _list_models(base, headers, "anthropic")
        model = models[0] if models else ""
    payload = {
        "model": model,
        "max_tokens": cfg.llm_max_tokens,
        "temperature": cfg.llm_temperature,
        "messages": [
            {
                "role": "user",
                "content": [
                    {
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": "image/png",
                            "data": image_b64,
                        },
                    },
                    {"type": "text", "text": _prompt(cfg)},
                ],
            }
        ],
    }
    body = _post_json(url, payload, headers, cfg.llm_timeout)
    if not body:
        return None
    parts = []
    for block in body.get("content", []):
        if isinstance(block, dict) and block.get("type") == "text":
            parts.append(block.get("text", ""))
    return _clean(" ".join(parts))


_BACKENDS = {
    "ollama": ocr_ollama,
    "openai": ocr_openai,
    "anthropic": ocr_anthropic,
}


def transcribe(crop_rgb: np.ndarray, cfg: Config) -> tuple[str, str]:
    """Transcribe a crop, returning (text, backend_actually_used)."""
    if cfg.ocr_backend == "none":
        return "", "none"
    backend_fn = _BACKENDS.get(cfg.ocr_backend)
    if backend_fn is not None:
        text = backend_fn(crop_rgb, cfg)
        if text:
            return text, cfg.ocr_backend

    # Correct orientation for rotated notes before Tesseract.
    if getattr(cfg, "ocr_detect_orientation", True) and min(crop_rgb.shape[:2]) >= 80:
        angle = detect_orientation(crop_rgb)
        if angle:
            crop_rgb = rotate_image(crop_rgb, -angle)

    # Tesseract: transcribe line by line for better handwriting results.
    if cfg.ocr_line_split:
        lines = split_into_lines(crop_rgb)
        pieces = [ocr_tesseract(line, cfg.ocr_lang) for line in lines]
        text = _clean(" ".join(piece for piece in pieces if piece))
    else:
        text = ocr_tesseract(crop_rgb, cfg.ocr_lang)

    if not text:
        # Sparse-text retry helps with short notes / single words.
        text = ocr_tesseract(crop_rgb, cfg.ocr_lang, psm=11)
    return text, "tesseract"


def check_backends(cfg: Config) -> dict:
    """Diagnostics for the preferences panel / --check mode."""
    import shutil

    backend = cfg.ocr_backend
    base = _effective_url(cfg, backend)
    model = _effective_model(cfg, backend)
    result = {
        "tesseract_binary": bool(shutil.which("tesseract")),
        "pytesseract": pytesseract is not None,
        "tesseract_languages": [],
        "backend": backend,
        "llm_url": base,
        "llm_model": model,
        "llm_reachable": False,
        "llm_models": [],
        "llm_model_listed": False,
        "ollama_reachable": False,
        "ollama_model_listed": False,
        "ollama_models": [],
        "messages": [],
    }
    if pytesseract is not None:
        try:
            result["tesseract_languages"] = pytesseract.get_languages(config="")
        except Exception:
            result["tesseract_languages"] = []

    if backend in _BACKENDS and base:
        try:
            headers = {}
            key = _llm_key(cfg)
            if backend == "openai":
                if key:
                    headers["Authorization"] = "Bearer " + key
                endpoint = base + "/models"
            elif backend == "anthropic":
                if key:
                    headers["x-api-key"] = key
                headers["anthropic-version"] = "2023-06-01"
                endpoint = base + ("/models" if base.endswith("/v1") else "/v1/models")
            else:
                endpoint = base + "/api/tags"

            request = urllib.request.Request(endpoint, headers=headers, method="GET")
            with urllib.request.urlopen(request, timeout=6) as response:
                body = json.loads(response.read().decode("utf-8"))

            result["llm_reachable"] = True
            if backend == "ollama":
                names = [m.get("name", "") for m in body.get("models", [])]
                result["ollama_reachable"] = True
                result["ollama_models"] = names
            else:
                names = [m.get("id", "") for m in body.get("data", [])]
            result["llm_models"] = names
            result["llm_model_listed"] = any(
                name == model or name.split(":")[0] == model.split(":")[0]
                for name in names
            )
            if backend == "ollama":
                result["ollama_model_listed"] = result["llm_model_listed"]
        except Exception as exc:  # noqa: BLE001
            result["messages"].append(f"{backend}: {exc}")

    if not result["tesseract_binary"]:
        result["messages"].append("tesseract binary not found on PATH")
    return result


def _clean(text: str) -> str:
    if not text:
        return ""
    lines = [line.strip() for line in text.splitlines()]
    lines = [line for line in lines if line]
    return " ".join(lines).strip()
