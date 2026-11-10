#!/usr/bin/env python3
"""Exercise the LLM transcription backends against a local mock server.

Run with the helper virtualenv:
    .venv/bin/python tests/test_llm_backends.py

No network access or model is required; the test starts a tiny HTTP server that
speaks the OpenAI chat-completions, Anthropic Messages, and Ollama generate
protocols.
"""

from __future__ import annotations

import json
import os
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

from src import ocr  # noqa: E402
from src.models import Config  # noqa: E402


class MockHandler(BaseHTTPRequestHandler):
    def log_message(self, *args):  # silence
        pass

    def _send(self, payload: dict):
        body = json.dumps(payload).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path.endswith("/api/tags"):
            self._send({"models": [{"name": "mock-model"}]})
        elif self.path.endswith("/models"):
            self._send({"data": [{"id": "mock-model"}]})
        else:
            self.send_error(404)

    def do_POST(self):
        length = int(self.headers.get("Content-Length", "0"))
        self.rfile.read(length)
        if self.path.endswith("/chat/completions"):
            self._send({"choices": [{"message": {"content": "openai note"}}]})
        elif self.path.endswith("/messages"):
            self._send({"content": [{"type": "text", "text": "anthropic note"}]})
        elif self.path.endswith("/api/generate"):
            self._send({"response": "ollama note"})
        else:
            self.send_error(404)


def main() -> int:
    server = ThreadingHTTPServer(("127.0.0.1", 0), MockHandler)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    crop = np.full((60, 140, 3), 255, dtype=np.uint8)
    crop[20:40, 20:120] = 20

    try:
        openai_cfg = Config.from_dict({
            "ocr_backend": "openai",
            "llm_url": f"http://127.0.0.1:{port}/v1",
            "llm_model": "mock-model",
            "llm_timeout": 10,
        })
        assert ocr.ocr_openai(crop, openai_cfg) == "openai note"
        text, backend = ocr.transcribe(crop, openai_cfg)
        assert text == "openai note" and backend == "openai"
        report = ocr.check_backends(openai_cfg)
        assert report["llm_reachable"], report
        assert "mock-model" in report["llm_models"], report
        print("  OpenAI-compatible endpoint ✓")

        openai_auto = Config.from_dict({
            "ocr_backend": "openai",
            "llm_url": f"http://127.0.0.1:{port}/v1",
            "llm_timeout": 10,
        })
        assert ocr.ocr_openai(crop, openai_auto) == "openai note"
        print("  OpenAI-compatible auto-picks the served model ✓")

        anthropic_cfg = Config.from_dict({
            "ocr_backend": "anthropic",
            "llm_url": f"http://127.0.0.1:{port}",
            "llm_model": "mock-model",
            "llm_timeout": 10,
        })
        assert ocr.ocr_anthropic(crop, anthropic_cfg) == "anthropic note"
        text, backend = ocr.transcribe(crop, anthropic_cfg)
        assert text == "anthropic note" and backend == "anthropic"
        report = ocr.check_backends(anthropic_cfg)
        assert report["llm_reachable"], report
        print("  Anthropic Messages endpoint ✓")

        ollama_cfg = Config.from_dict({
            "ocr_backend": "ollama",
            "llm_url": f"http://127.0.0.1:{port}",
            "llm_model": "mock-model",
            "llm_timeout": 10,
        })
        assert ocr.ocr_ollama(crop, ollama_cfg) == "ollama note"
        text, backend = ocr.transcribe(crop, ollama_cfg)
        assert text == "ollama note" and backend == "ollama"
        report = ocr.check_backends(ollama_cfg)
        assert report["llm_reachable"], report
        assert "mock-model" in report["llm_models"], report
        print("  Ollama endpoint ✓")

        print("\nAll LLM backend assertions passed.")
        return 0
    finally:
        server.shutdown()
        server.server_close()


if __name__ == "__main__":
    raise SystemExit(main())
