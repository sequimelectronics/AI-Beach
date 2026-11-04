# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Becky Northaven and the AI-Beach contributors
"""The Drive-In's picture describer (drivein/describer.py) and frame helpers (drivein/frames.py)."""

import json
import os
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "drivein"))

import describer  # noqa: E402
from describer import DescriberError  # noqa: E402


class TidyAndScrubTests(unittest.TestCase):
    def test_tidy_makes_one_plain_line(self):
        t = describer.tidy
        self.assertEqual(t("<think>hmm, a man?</think> A man waves."), "A man waves.")
        self.assertEqual(t("<|channel>thought\nlet me see<channel|>A woman sings."), "A woman sings.")
        self.assertEqual(t("long reasoning... <channel|>A dog runs."), "A dog runs.")
        self.assertEqual(t("The image shows a man on a stage."), "A man on a stage.")
        self.assertEqual(t('  **A** "clock"\n with a red hand.  '), 'A "clock" with a red hand.')
        long = "A man walks. " * 40
        self.assertLessEqual(len(t(long)), describer.MAX_LINE)
        self.assertTrue(t(long).endswith("."))

    def test_scrub_takes_out_names_but_not_ordinary_capitals(self):
        s = describer.scrub
        self.assertEqual(s("Michael Jackson stands near a plane."), "someone stands near a plane.")
        self.assertEqual(s("A man talks to Sean Penn."), "A man talks to someone.")
        self.assertEqual(s("The Magician bows."), "The Magician bows.")             # a capitalized lead word
        self.assertEqual(s('A box says "DANGER HIGH VOLTAGE".'), 'A box says "DANGER HIGH VOLTAGE".')
        self.assertEqual(s("A man hangs upside down."), "A man hangs upside down.")
        # Words the show itself supplies (the keeper's word list) stay.
        self.assertEqual(s("Whatsit Doohicky waves.", {"Whatsit", "Doohicky"}), "Whatsit Doohicky waves.")
        self.assertEqual(s("Whatsit Doohicky waves.", {"whatsit doohicky"}), "Whatsit Doohicky waves.")

    def test_the_default_prompts_carry_the_no_names_rule(self):
        # The keeper (11-03): "Don't use anyone's name", not "don't guess": a model that thinks it knows isn't guessing.
        for p in describer.DEFAULT_PROMPTS.values():
            self.assertIn("Don't use anyone's name, even if you recognize them", p)
            self.assertNotIn("guess", p.lower())
            self.assertNotIn("surprising", p.lower())       # it made MiniCPM-V pad with "something unusual"


class _FakeServer(BaseHTTPRequestHandler):
    seen: list = []

    def log_message(self, *a):
        pass

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        _FakeServer.seen.append((self.path, self.headers.get("Authorization"), body))
        out = json.dumps({"choices": [{"message": {"content": "The image shows Michael Jackson on a stage."}}]})
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(out)))
        self.end_headers()
        self.wfile.write(out.encode())


class OpenAIDescriberTests(unittest.TestCase):
    def test_talks_to_any_openai_compatible_server(self):
        srv = HTTPServer(("127.0.0.1", 0), _FakeServer)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        try:
            d = describer.make_describer({"kind": "openai", "url": f"http://127.0.0.1:{srv.server_port}",
                                          "model": "my-vision-model"})
            line = d.describe(b"\xff\xd8fake-jpeg", "long")
        finally:
            srv.shutdown()
        self.assertEqual(line, "Michael Jackson on a stage.")             # tidy() here; scrub() is the caller's
        self.assertEqual(describer.scrub(line), "someone on a stage.")
        path, auth, body = _FakeServer.seen[-1]
        self.assertEqual(path, "/v1/chat/completions")
        self.assertIsNone(auth)
        self.assertEqual(body["model"], "my-vision-model")
        self.assertEqual(body["chat_template_kwargs"], {"enable_thinking": False})
        parts = body["messages"][0]["content"]
        self.assertTrue(parts[0]["image_url"]["url"].startswith("data:image/jpeg;base64,"))
        self.assertEqual(parts[1]["text"], describer.DEFAULT_PROMPTS["long"])

    def test_pictures_stay_on_this_computer_unless_the_keeper_says_otherwise(self):
        with self.assertRaises(DescriberError) as e:
            describer.make_describer({"kind": "openai", "url": "http://192.168.1.50:11434/v1"})
        self.assertIn("leave", str(e.exception))
        d = describer.make_describer({"kind": "openai", "url": "http://192.168.1.50:11434/v1", "remote_ok": True})
        self.assertEqual(d.u.hostname, "192.168.1.50")

    def test_bad_settings_get_plain_answers(self):
        for bad in ({"kind": "magic"}, {"kind": "openai", "url": "ftp://x"},
                    {"kind": "openai", "url": "http://127.0.0.1:1", "prompts": {"medium": "x"}},
                    {"kind": "llama-server", "server": "llama-server.exe", "model": "m.gguf", "mmproj": "p.gguf"},
                    {"kind": "command", "command": "python describe.py"},
                    {"kind": "command", "command": ["python", "describe.py"]}):
            with self.assertRaises(DescriberError, msg=str(bad)):
                describer.make_describer(bad)


class CommandDescriberTests(unittest.TestCase):
    def _program(self, body: str) -> str:
        d = tempfile.mkdtemp()
        p = os.path.join(d, "describe.py")
        Path(p).write_text(body, encoding="utf-8")
        self.addCleanup(lambda: __import__("shutil").rmtree(d, ignore_errors=True))
        return p

    def test_your_own_program_gets_the_picture_and_the_detail(self):
        prog = self._program("import sys\ndata = sys.stdin.buffer.read()\n"
                             "print(f'A picture of {len(data)} bytes, {sys.argv[-1]} please.')\n")
        d = describer.make_describer({"kind": "command", "command": [sys.executable, "-I", prog]})
        self.assertEqual(d.describe(b"12345", "long"), "A picture of 5 bytes, long please.")

    def test_a_failing_or_slow_program_says_so(self):
        bad = self._program("import sys\nsys.stderr.write('no model here')\nsys.exit(3)\n")
        with self.assertRaises(DescriberError) as e:
            describer.make_describer({"kind": "command", "command": [sys.executable, "-I", bad]}).describe(b"x")
        self.assertIn("exited 3", str(e.exception))
        slow = self._program("import time\ntime.sleep(5)\n")
        d = describer.make_describer({"kind": "command", "command": [sys.executable, "-I", slow], "timeout_s": 0.5})
        with self.assertRaises(DescriberError):
            d.describe(b"x")


class FrameTests(unittest.TestCase):
    def setUp(self):
        try:
            from PIL import Image
        except ImportError:
            self.skipTest("Pillow not installed")
        self.Image = Image
        import frames
        self.frames = frames

    def test_shrink_and_change(self):
        f, Image = self.frames, self.Image
        big = Image.new("RGB", (1920, 1080), (40, 80, 120))
        j = f.to_jpeg(big)
        self.assertEqual(Image.open(__import__("io").BytesIO(j)).size, (768, 432))
        a = f.thumb(big)
        self.assertTrue(f.changed(None, a))
        self.assertFalse(f.changed(a, f.thumb(big)))
        other = Image.new("RGB", (1920, 1080), (220, 220, 220))
        self.assertTrue(f.changed(a, f.thumb(other)))
        self.assertTrue(f.looks_blank(Image.new("RGB", (640, 360), (0, 0, 0))))
        stripes = Image.new("RGB", (640, 360), (0, 0, 0))
        stripes.paste((255, 255, 255), (0, 0, 320, 360))
        self.assertFalse(f.looks_blank(stripes))


class PictureLoopTests(unittest.TestCase):
    def setUp(self):
        try:
            from PIL import Image
        except ImportError:
            self.skipTest("Pillow not installed")
        import seeing
        self.seeing, self.Image = seeing, Image
        self.now = [0.0]
        self.picture = self.scene(1)
        self.asked = [False]
        self.sent: list[str] = []
        self.calls: list[str] = []
        self.contexts: list[str] = []
        self.spoken: list[str] = []
        loop_self = self

        class Fake:
            fail = 0

            def describe(self, jpeg, detail, context=""):
                if Fake.fail:
                    Fake.fail -= 1
                    raise describer.DescriberError("no model")
                loop_self.calls.append(detail)
                loop_self.contexts.append(context)
                return "Michael Jackson waves." if detail == "long" else "A man waves."

        self.Fake = Fake
        self.loop = seeing.PictureLoop(grab=lambda: self.picture, describer=Fake(),
                                       send=lambda lines: self.sent.extend(lines) or True,
                                       wants=lambda: self.asked[0], clock=lambda: self.now[0], say=lambda m: None,
                                       heard=lambda: self.spoken)

    def scene(self, n):
        img = self.Image.new("RGB", (640, 360), (20 * n % 255, 40, 90))
        img.paste((255, 255, 255), (0, 0, 64 * n % 640 or 64, 360))
        return img

    def test_pace_change_look_and_the_name_net(self):
        L = self.loop
        self.assertEqual(L.step(), "(seen) someone waves.")             # first look: a long one, name scrubbed
        self.now[0] = 16
        self.assertIsNone(L.step())                                   # due, but the picture hasn't changed
        self.picture = self.scene(2)
        self.assertEqual(L.step(), "(seen) A man waves.")             # changed after 16 s: a short one
        self.now[0] = 20
        self.picture = self.scene(3)
        self.assertIsNone(L.step())                                   # changed, but not due yet
        self.asked[0] = True
        self.now[0] = 21
        self.picture = self.scene(3)
        self.assertEqual(L.step(), "(seen) someone waves.")             # asked: at once, long, even if unchanged
        self.asked[0] = False
        self.now[0] = 52
        self.picture = self.scene(4)
        self.assertEqual(L.step(), "(seen) someone waves.")             # 31 s since the last long: long again
        self.assertEqual(self.calls, ["long", "short", "long", "long"])

    def test_the_story_so_far_and_names_the_show_says(self):
        # The keeper (11-03): "the poor thing would have to have a running narrative"; and the title card's name
        # (said aloud by the show's narrator) was turned into "someone".
        L = self.loop
        self.assertEqual(L.step(), "(seen) someone waves.")         # nobody said the name: still scrubbed
        self.assertEqual(self.contexts[-1], "")                     # nothing before the first picture
        self.spoken.extend(["Tonight, Michael Jackson will vanish.", "I call this the fan."])
        self.now[0] = 31
        self.picture = self.scene(2)
        self.assertEqual(L.step(), "(seen) Michael Jackson waves.")  # the show said it: it stays
        ctx = self.contexts[-1]
        self.assertIn("(seen) someone waves.", ctx)                 # its own last description
        self.assertIn("I call this the fan.", ctx)                  # and what was just said

    def test_context_helpers(self):
        self.assertEqual(describer.names_in(["Tonight, Whatsit Doohicky is making me disappear.",
                                             "The Magic of Whatsit Doohicky", "A man waves."]),
                         {"Whatsit Doohicky"})
        p = describer.with_context("Describe it.", "(seen) A fan.\nAnd now the fan spins.")
        self.assertTrue(p.startswith("Describe it."))
        self.assertIn("for context only", p)
        self.assertIn("And now the fan spins.", p)
        self.assertEqual(describer.with_context("Describe it.", "  "), "Describe it.")
        self.assertLessEqual(len(describer.with_context("x", "y" * 5000)), describer.CONTEXT_MAX + 200)

    def test_blank_pictures_and_a_broken_model(self):
        L = self.loop
        self.picture = self.Image.new("RGB", (640, 360), (0, 0, 0))
        self.assertIsNone(L.step())                                   # a black screen isn't described
        self.picture = None
        self.assertIsNone(L.step())                                   # nothing to grab (minimized)
        self.picture = self.scene(5)
        self.Fake.fail = 5
        for i in range(5):
            self.now[0] += 31
            self.assertIsNone(L.step())
        self.assertTrue(L.stop_event.is_set())                        # gave up; the words go on without it
        self.assertEqual(self.sent, [])


class RunsLikeTheKeepersProjectorTests(unittest.TestCase):
    def test_the_picture_modules_load_under_dash_P(self):
        # The keeper's first picture show (11-03): "no module named describer". The projector runs with -E -P, which
        # keeps its own folder off the import path; the other tests added it themselves and missed this.
        import subprocess
        code = ("import importlib.util, sys\n"
                f"spec = importlib.util.spec_from_file_location('projector', r'{ROOT / 'drivein' / 'projector.py'}')\n"
                "m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)\n"
                "d, f, s = m._picture_modules()\n"
                "print(d.__name__, f.__name__, s.__name__, any('drivein' in p for p in sys.path))\n")
        r = subprocess.run([sys.executable, "-E", "-P", "-c", code], capture_output=True, text=True,
                           cwd=tempfile.gettempdir(), timeout=60)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stdout.strip(), "describer frames seeing False")


class BrowserPicturesTests(unittest.TestCase):
    def test_a_whole_browser_never_gets_pictures(self):
        # Pharos (11-03): a whole browser's window shows whichever tab is on top (an email, a call), not the show's.
        src = (ROOT / "drivein" / "projector.py").read_text(encoding="utf-8")
        start = src.index("def run(cfg")
        body = src[start:src.index("\ndef ", start + 1)]
        self.assertIn('choice["name"].lower() in BROWSERS and cfg.get("vision")', body)
        self.assertLess(body.index("in BROWSERS and cfg.get"), body.index("pics = make_pictures(cfg)"))


if __name__ == "__main__":
    unittest.main()
