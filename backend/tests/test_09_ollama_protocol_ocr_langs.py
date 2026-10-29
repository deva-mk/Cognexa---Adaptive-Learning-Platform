"""Ollama client against a real HTTP server speaking the Ollama wire protocol (/api/tags, /api/chat),
and OCR in the Indic language packs when they are installed.

The fake server proves OUR client's protocol handling (request shape, errors, timeouts). It does not prove
the quality of a real model - that needs a real `ollama pull`."""
import json
import subprocess
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest
from PIL import Image, ImageDraw, ImageFont

from app.ai.llm_provider import LLMError, LLMProvider, LLMUnavailable
from app.config import settings


class _Ollama(BaseHTTPRequestHandler):
    models = ["llama3.2:latest"]
    mode = "ok"
    seen: list = []

    def log_message(self, *a):
        pass

    def _send(self, code, obj):
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path == "/api/tags":
            self._send(200, {"models": [{"name": m} for m in self.models]})
        else:
            self._send(404, {})

    def do_POST(self):
        n = int(self.headers.get("Content-Length", 0))
        req = json.loads(self.rfile.read(n) or b"{}")
        type(self).seen.append(req)
        if self.mode == "500":
            return self._send(500, {"error": "boom"})
        if self.mode == "slow":
            time.sleep(2.5)
        if req.get("format") == "json":
            return self._send(200, {"message": {"role": "assistant", "content": '```json\n{"ok": true, "n": 3}\n```'}})
        self._send(200, {"message": {"role": "assistant", "content": f"echo: {req['messages'][-1]['content']} "}})


@pytest.fixture()
def ollama(monkeypatch):
    _Ollama.models, _Ollama.mode, _Ollama.seen = ["llama3.2:latest"], "ok", []
    srv = HTTPServer(("127.0.0.1", 0), _Ollama)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    monkeypatch.setattr(settings, "OLLAMA_BASE_URL", f"http://127.0.0.1:{srv.server_port}")
    monkeypatch.setattr(settings, "OLLAMA_MODEL", "llama3.2")
    yield _Ollama
    srv.shutdown()


def test_status_and_chat_use_the_ollama_wire_protocol(ollama):
    p = LLMProvider()
    st = p.status(force=True)
    assert st["available"] and st["installed_models"] == ["llama3.2:latest"]
    out = p.chat([{"role": "system", "content": "s"}, {"role": "user", "content": "hello"}])
    assert out == "echo: hello"                       # stripped
    req = ollama.seen[-1]
    assert req["model"] == "llama3.2" and req["stream"] is False and "format" not in req
    assert req["options"]["temperature"] == 0.2 and req["options"]["num_predict"] == 1500


def test_json_mode_sets_format_and_tolerates_code_fences(ollama):
    p = LLMProvider()
    assert p.chat_json([{"role": "user", "content": "x"}]) == {"ok": True, "n": 3}
    assert ollama.seen[-1]["format"] == "json"


def test_model_not_installed_is_reported_with_the_pull_command(ollama):
    ollama.models = ["mistral:latest"]
    p = LLMProvider()
    assert p.available() is False
    with pytest.raises(LLMUnavailable, match="ollama pull llama3.2"):
        p.chat([{"role": "user", "content": "x"}])


def test_server_error_and_timeout_become_llm_error(ollama, monkeypatch):
    p = LLMProvider()
    ollama.mode = "500"
    with pytest.raises(LLMError):
        p.chat([{"role": "user", "content": "x"}])
    ollama.mode = "slow"
    monkeypatch.setattr(settings, "OLLAMA_TIMEOUT_SEC", 1)
    with pytest.raises(LLMError, match="too long"):
        p.chat([{"role": "user", "content": "x"}])


def test_unreachable_ollama_is_unavailable_not_a_crash(monkeypatch):
    monkeypatch.setattr(settings, "OLLAMA_BASE_URL", "http://127.0.0.1:1")
    p = LLMProvider()
    assert p.status(force=True)["available"] is False
    with pytest.raises(LLMUnavailable, match="ollama serve"):
        p.chat([{"role": "user", "content": "x"}])


# --------------------------------------------------------------------------- OCR language packs
SAMPLES = {"hin": ("Noto Serif Devanagari", "शिक्षा विद्यार्थी विश्वविद्यालय पुस्तक", 4),
           "kan": ("Noto Serif Kannada", "ಶಿಕ್ಷಣ ವಿದ್ಯಾರ್ಥಿ ಪುಸ್ತಕ ಶಾಲೆ", 4),
           "tam": ("Noto Serif Tamil", "கல்வி கற்றல் மாணவர் பள்ளி", 1),
           "mal": ("Noto Serif Malayalam", "വിദ്യാഭ്യാസം വിദ്യാർത്ഥി പുസ്തകം", 1)}


@pytest.mark.parametrize("code", sorted(SAMPLES))
def test_ocr_reads_indic_scripts_when_the_pack_and_font_exist(code):
    from app.rag.document_parser import ocr_languages
    pytest.importorskip("pytesseract")
    if code not in ocr_languages()["installed"]:
        pytest.skip(f"tesseract language pack '{code}' not installed")
    fam, text, min_words = SAMPLES[code]
    path = subprocess.run(["fc-match", "-f", "%{file}", fam], capture_output=True, text=True).stdout
    if fam.split()[-1].lower() not in path.lower() and "noto" not in path.lower():
        pytest.skip(f"font for {code} not installed")
    im = Image.new("L", (1400, 140), 255)
    ImageDraw.Draw(im).text((20, 30), text, font=ImageFont.truetype(path, 56), fill=0)
    import pytesseract
    got = set(pytesseract.image_to_string(im, lang=code).split())
    assert len(set(text.split()) & got) >= min_words, got
