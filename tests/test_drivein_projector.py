# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Becky Northaven and the AI-Beach contributors
"""The Drive-In's projector and speech-to-text helper (11-01): what can be checked without a sound card or a model.
The capture itself was tested live on Windows (one speaking program captured, transcribed, posted, read back)."""

from __future__ import annotations

import ast
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "drivein"))


def code_of(path: Path) -> str:
    """The code alone, without comments or docstrings (they may NAME what the code must never do)."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        body = getattr(node, "body", None)
        if (isinstance(body, list) and body and isinstance(body[0], ast.Expr)
                and isinstance(body[0].value, ast.Constant) and isinstance(body[0].value.value, str)):
            body[0] = ast.Pass()
    return ast.unparse(tree)


PROJ = ROOT / "drivein" / "projector.py"
SVC = ROOT / "drivein" / "whisper_service.py"

try:
    import numpy  # noqa: F401
    HAVE_NUMPY = True
except ImportError:
    HAVE_NUMPY = False


class ProjectorTests(unittest.TestCase):
    def test_it_can_only_ever_capture_one_program(self):
        # Pharos (11-01): no whole-computer or microphone path at all, so there is nothing to fall back to.
        src, code = PROJ.read_text(encoding="utf-8"), code_of(PROJ)
        self.assertIn('"VAD\\\\Process_Loopback"', src)
        self.assertIn("Params(1, pid, 0)", src)                       # process loopback, include the target's tree
        for forbidden in ("GetDefaultAudioEndpoint", "eCapture", "WaveIn", "sounddevice", "soundcard", "pyaudio",
                          "IMMEndpoint", "Stereo Mix", "os.system"):
            self.assertNotIn(forbidden, code, forbidden)

    def test_calls_and_chat_programs_are_never_offered(self):
        import projector
        for name in ("Discord.exe", "Teams.exe", "ms-teams.exe", "Zoom.exe", "slack.exe", "claude.exe"):
            self.assertIn(name.lower(), projector.DENY)

    def test_the_config_names_one_beach(self):
        import json
        import tempfile
        import projector
        with tempfile.TemporaryDirectory() as d:
            p = Path(d, "projector.json")
            for bad in ("ftp://x", "http://", "http://x/path", ""):
                p.write_text(json.dumps({"beach": bad}))
                with self.assertRaises(SystemExit):
                    projector.load_config(str(p))
            p.write_text(json.dumps({"beach": "http://192.168.1.20:8765"}))
            self.assertEqual(projector.load_config(str(p))["_beach"].hostname, "192.168.1.20")

    @unittest.skipUnless(HAVE_NUMPY, "needs numpy")
    def test_sound_is_cut_at_a_pause(self):
        import numpy as np
        import projector
        rate = projector.RATE
        loud = (np.sin(np.arange(rate * 7) / 3) * 8000).astype("<i2")
        quiet = np.zeros(int(rate * 0.6), dtype="<i2")
        cut = projector.cut_point(np.concatenate([loud, quiet, loud]).tobytes())
        self.assertTrue(7 * rate * 2 <= cut <= 7.6 * rate * 2, cut)       # inside the pause
        self.assertIsNone(projector.cut_point(loud[: rate * 3].tobytes()))  # too short yet
        endless = (np.sin(np.arange(rate * 15) / 3) * 8000).astype("<i2").tobytes()
        self.assertEqual(projector.cut_point(endless), projector.CHUNK_MAX_S * rate * 2)   # no pause: cut at the max


class WhisperServiceTests(unittest.TestCase):
    def test_it_takes_raw_samples_only_and_answers_only_the_beach(self):
        # Pharos: nothing to parse (no container, no decoder); Host and Origin checked; CORS for one origin, never "*".
        src, code = SVC.read_text(encoding="utf-8"), code_of(SVC)
        for forbidden in ("ffmpeg", "decode_audio", "av.open", "wave.open", "'*'"):
            self.assertNotIn(forbidden, code, forbidden)
        for needed in ('ThreadingHTTPServer(("127.0.0.1", a.port)', 'self.headers.get("Host") != svc.host',
                       "origin is not None and origin != svc.origin", "Access-Control-Allow-Private-Network",
                       'os.environ["HF_HUB_OFFLINE"] = "1"', "local_files_only=True"):
            self.assertIn(needed, src, needed)


if __name__ == "__main__":
    unittest.main()
