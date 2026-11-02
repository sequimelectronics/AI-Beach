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

    def test_tree_parents_and_webview_windows_are_never_captured(self):
        # Pharos (11-01): a voice assistant's window may be WebView2; and capturing a parent captures its whole tree.
        import projector
        for name in ("msedgewebview2.exe", "explorer.exe", "svchost.exe", "audiodg.exe", "cmd.exe", "powershell.exe",
                     "pwsh.exe", "windowsterminal.exe", "conhost.exe", "sihost.exe", "runtimebroker.exe"):
            self.assertIn(name, projector.DENY)

    def test_a_denied_program_anywhere_in_the_tree_refuses_the_pick(self):
        import os
        import projector
        me = os.path.basename(sys.executable).lower()            # this test runs in python(.exe)
        self.assertIn(me, [n.lower() for n in projector.denied_in_tree(os.getpid(), {me})])
        self.assertEqual(projector.denied_in_tree(os.getpid(), {"nothing-like-this.exe"}), [])
        self.assertEqual(projector.denied_in_tree(999_999_999, {me}), [])          # gone: nothing to say
        picked = projector.pick([{"pid": os.getpid(), "name": "harmless.exe", "created": 0, "titles": []}], {me})
        self.assertIsNone(picked)                                                # refused before any question

    def test_picking_the_app_is_the_only_question(self):
        # The keeper, 11-01: "don't ask them to capture the audio, we already picked it". One question, a number.
        import builtins
        from unittest import mock
        import projector
        apps = [{"pid": 999_999_991, "name": "vlc.exe", "created": 0, "titles": ["zombies.mp4"], "playing": False},
                {"pid": 999_999_992, "name": "Discord.exe", "created": 0, "titles": ["a call"], "playing": True}]
        with mock.patch.object(builtins, "input", return_value="1") as asked:
            picked = projector.pick(apps, projector.DENY)
        self.assertEqual(asked.call_count, 1)
        self.assertEqual(picked["name"], "vlc.exe")                     # Discord never listed, so VLC is number 1
        self.assertNotIn("yes/no", PROJ.read_text(encoding="utf-8"))

    def test_the_helpers_messages_are_always_read_and_kept_in_memory_only(self):
        # Pharos (11-01): a stderr pipe nobody reads fills after a few warnings and freezes the helper mid-show.
        src = PROJ.read_text(encoding="utf-8")
        self.assertIn("iter(proc.stderr.readline", src)
        self.assertIn("deque(maxlen=20)", src)
        start = src.index("def start_helper")
        import re
        body = src[start:src.index("def run(", start)]
        self.assertIsNone(re.search(r"(?<![A-Za-z])open\(", body))           # nothing written to a file (Popen is fine)

    def test_local_names_join_the_deny_list_from_the_config(self):
        import json
        import tempfile
        import projector
        with tempfile.TemporaryDirectory() as d:
            p = Path(d, "projector.json")
            p.write_text(json.dumps({"beach": "http://192.168.1.20:8765", "deny_also": ["Our-Voice-App.exe", " "]}))
            deny = projector.load_config(str(p))["_deny"]
            self.assertIn("our-voice-app.exe", deny)
            self.assertTrue(projector.DENY <= deny)

    @unittest.skipUnless(sys.platform == "win32", "Windows only")
    def test_a_reused_process_number_is_refused(self):
        # Pharos: between the list and "yes" the program can close and its number go to another one.
        import os
        import psutil
        import projector
        me = psutil.Process(os.getpid())
        for name, created in ((me.name(), me.create_time() + 5), ("someone-else.exe", me.create_time())):
            with self.assertRaises(RuntimeError) as e:
                projector.ProcessCapture(os.getpid(), name, created)
            self.assertIn("pick again", str(e.exception))

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
