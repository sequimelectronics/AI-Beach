# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Becky Northaven and the AI-Beach contributors
"""The Drive-In's local speech-to-text helper: sound in, words out, on the keeper's own computer.

    python -E -P whisper_service.py --model <folder of a faster-whisper model> --beach-origin http://192.168.1.20:8765

It listens on 127.0.0.1 only. The projector (the program, or the Drive-In page's tab projector) sends it RAW sound:
16 kHz mono 16-bit little-endian samples, nothing else. There is no container, no decoder, no ffmpeg, so a page that
tried to send it a crafted media file has nothing to exploit (Pharos, 11-01). It answers with the words heard.

It holds no Beach sign-in and sends nothing anywhere: it only answers whoever asked, and only:
- requests addressed to exactly 127.0.0.1:<port> (the Host header; this stops DNS rebinding);
- browser requests from exactly the Beach's own origin (any other web page is refused: browsers can't fake Origin),
  with that one origin allowed by CORS and by Chrome's Private Network Access check; never "*";
- one request at a time, at most MAX_SECONDS of sound per request and per minute.
The model is a local folder (offline; the Hugging Face hub is switched off before anything loads).
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

os.environ["HF_HUB_OFFLINE"] = "1"          # never reach the internet for a model
os.environ["HF_HUB_DISABLE_TELEMETRY"] = "1"

RATE = 16000
MAX_SECONDS = 30                             # per request
MAX_PER_MINUTE = 90                          # seconds of sound per minute (a show plays 60)
DEFAULT_PORT = 8796

# Whisper-style models invent words over music and quiet: they learned from countless videos that end this way (the
# keeper, 11-02: "it likes to insert 'thanks for watching' and 'no' randomly"). Three guards, cheapest first:
# - a piece the model itself thinks has no speech (and it isn't confident about the words) is dropped;
# - these phrases are dropped when they're a whole piece on their own (said mid-sentence, they stay), and a few
#   short fillers need the model to be quite sure it heard speech;
# - one- or two-word pieces need the model to be fairly sure there was speech.
PHANTOMS = {
    "thanks for watching", "thank you for watching", "thanks for watching and see you next time",
    "thank you so much for watching", "please subscribe", "subscribe", "like and subscribe",
    "please like and subscribe", "see you next time", "see you in the next video",
    "subtitles by the amaraorg community",
}
# Real lines in plenty of stories, but also the model's favorite fillers: kept only when it's quite sure it heard speech.
SUSPECTS = {"thank you", "thanks", "bye", "you", "no", "so", "okay", "oh", "um", "hmm"}
SUSPECT_NO_SPEECH = 0.1
NO_SPEECH_DROP = 0.6        # with avg_logprob below -1.0: Whisper's own "this was silence" rule
SHORT_NO_SPEECH = 0.3       # a one- or two-word piece is kept only below this
MAX_WORDS_HINT = 240        # characters of the keeper's word list (names to spell right)


def phantom_key(text: str) -> str:
    return " ".join("".join(c for c in text.lower() if c.isalnum() or c.isspace()).split())


def keep_segment(text: str, no_speech_prob: float, avg_logprob: float) -> bool:
    """Whether a heard piece is real speech rather than one of the model's inventions over music or quiet."""
    key = phantom_key(text)
    if not key:
        return False
    if no_speech_prob > NO_SPEECH_DROP and avg_logprob < -1.0:
        return False
    if key in PHANTOMS:
        return False
    if key in SUSPECTS and no_speech_prob > SUSPECT_NO_SPEECH:
        return False
    if len(key.split()) <= 2 and no_speech_prob > SHORT_NO_SPEECH:
        return False
    return True


def clean_words(raw: str | None) -> str:
    """The keeper's word list (names like a town or a shop), as plain words for the model to expect. Letters, digits,
    spaces, commas, hyphens and apostrophes only, so it can only ever be a list of words."""
    if not raw:
        return ""
    kept = "".join(c if (c.isalnum() or c in " ,-'") else (" " if c.isspace() else "") for c in raw)
    return " ".join(kept.split())[:MAX_WORDS_HINT]


def cuda_dlls_on_path() -> None:
    """On Windows, ctranslate2 needs cublas64_12.dll and cudnn64_9.dll from the nvidia-cublas-cu12 / nvidia-cudnn-cu12
    packages, but doesn't find their bin folders by itself ("Library cublas64_12.dll is not found"). Put them first on
    PATH (what its loader always searches) and on the DLL search path. A no-op without those packages (CPU only)."""
    if os.name != "nt":
        return
    import importlib.util
    spec = importlib.util.find_spec("nvidia")
    bins = [os.path.join(root, sub, "bin") for root in (spec.submodule_search_locations or []) if spec
            for sub in ("cublas", "cudnn")]
    bins = [d for d in bins if os.path.isdir(d)]
    for d in bins:
        try:
            os.add_dll_directory(d)
        except OSError:
            pass
    if bins:
        os.environ["PATH"] = os.pathsep.join(bins) + os.pathsep + os.environ.get("PATH", "")


class Service:
    def __init__(self, model_dir: str, device: str, beach_origin: str, port: int):
        if device == "cuda":
            cuda_dlls_on_path()
        from faster_whisper import WhisperModel
        if not os.path.isdir(model_dir):
            sys.exit(f"no model folder at {model_dir}")
        self.model = WhisperModel(model_dir, device=device,
                                  compute_type="float16" if device == "cuda" else "int8", local_files_only=True)
        self.origin = beach_origin.rstrip("/")
        self.host = f"127.0.0.1:{port}"
        self.busy = threading.Lock()
        self.minute: list[tuple[float, float]] = []

    def transcribe(self, pcm: bytes, words: str = "") -> dict:
        import numpy as np
        audio = np.frombuffer(pcm, dtype="<i2").astype("float32") / 32768.0
        segments, info = self.model.transcribe(audio, language="en", vad_filter=True, beam_size=5,
                                               condition_on_previous_text=False, hotwords=words or None)
        out, dropped = [], 0
        for s in segments:
            text = s.text.strip()
            if keep_segment(text, s.no_speech_prob, s.avg_logprob):
                out.append({"start": round(s.start, 2), "end": round(s.end, 2), "text": text})
            elif text:
                dropped += 1
        return {"segments": out, "dropped": dropped, "seconds": round(len(audio) / RATE, 2)}


def handler_for(svc: Service):
    class Handler(BaseHTTPRequestHandler):
        server_version = "drivein-whisper"
        sys_version = ""

        def log_message(self, *args):   # nothing about what was heard goes in a log
            pass

        def _cors(self) -> None:
            if self.headers.get("Origin") == svc.origin:
                self.send_header("Access-Control-Allow-Origin", svc.origin)
                self.send_header("Vary", "Origin")

        def _answer(self, status: int, body: dict) -> None:
            data = json.dumps(body).encode()
            self.send_response(status)
            self._cors()
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(data)

        def _allowed(self) -> bool:
            if self.headers.get("Host") != svc.host:
                self._answer(421, {"error": "wrong host"})
                return False
            origin = self.headers.get("Origin")
            if origin is not None and origin != svc.origin:   # a browser page that isn't the Beach's
                self._answer(403, {"error": "only the Beach's own page may ask"})
                return False
            return True

        def do_OPTIONS(self):   # the browser's preflight (CORS + Private Network Access), for the Beach's origin only
            if not self._allowed():
                return
            if self.headers.get("Origin") != svc.origin:
                self._answer(403, {"error": "only the Beach's own page may ask"})
                return
            self.send_response(204)
            self._cors()
            self.send_header("Access-Control-Allow-Methods", "POST")
            self.send_header("Access-Control-Allow-Headers", "Content-Type, X-Words")
            if self.headers.get("Access-Control-Request-Private-Network") == "true":
                self.send_header("Access-Control-Allow-Private-Network", "true")
            self.send_header("Access-Control-Max-Age", "600")
            self.end_headers()

        def do_GET(self):
            if self._allowed():
                self._answer(200 if self.path == "/health" else 404, {"ok": True} if self.path == "/health" else {})

        def do_POST(self):
            if not self._allowed():
                return
            if self.path != "/transcribe":
                return self._answer(404, {"error": "not here"})
            if self.headers.get("Content-Type") != "application/octet-stream":
                return self._answer(415, {"error": "send raw 16 kHz mono s16le samples as application/octet-stream"})
            try:
                size = int(self.headers.get("Content-Length", "-1"))
            except ValueError:
                size = -1
            if size <= 0 or size % 2 or size > MAX_SECONDS * RATE * 2:
                return self._answer(413, {"error": f"send 1 sample to {MAX_SECONDS} s of 16 kHz mono s16le"})
            pcm = self.rfile.read(size)
            if len(pcm) != size:
                return self._answer(400, {"error": "short body"})
            now = time.monotonic()
            svc.minute = [(t, s) for t, s in svc.minute if now - t < 60]
            seconds = size / 2 / RATE
            if sum(s for _, s in svc.minute) + seconds > MAX_PER_MINUTE:
                return self._answer(429, {"error": "more sound than a show plays; slow down"})
            if not svc.busy.acquire(blocking=False):
                return self._answer(429, {"error": "one request at a time"})
            try:
                svc.minute.append((now, seconds))
                self._answer(200, svc.transcribe(pcm, clean_words(self.headers.get("X-Words"))))
            finally:
                svc.busy.release()

    return Handler


def main() -> int:
    ap = argparse.ArgumentParser(description="The Drive-In's local speech-to-text helper (127.0.0.1 only)")
    ap.add_argument("--model", required=True, help="a faster-whisper model folder (local; nothing is downloaded)")
    ap.add_argument("--beach-origin", required=True, help="the Beach's own page origin, e.g. http://192.168.1.20:8765")
    ap.add_argument("--port", type=int, default=DEFAULT_PORT)
    ap.add_argument("--device", choices=["cuda", "cpu"], default="cuda")
    a = ap.parse_args()
    svc = Service(a.model, a.device, a.beach_origin, a.port)
    server = ThreadingHTTPServer(("127.0.0.1", a.port), handler_for(svc))
    print(f"Drive-In speech-to-text listening on 127.0.0.1:{a.port} (model {os.path.basename(a.model.rstrip('/\\'))}).",
          flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
