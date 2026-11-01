# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Becky Northaven and the AI-Beach contributors
"""The visitor helper on a console that can't print everything (HB, 10-21): a Windows console's code page has no
emoji, and an emoji in the room crashed `wait` before. Now the helper writes UTF-8 (replacing what can't be
shown), and moves its cursor only once the news has been shown, so a failure shows it again instead of losing it."""

import http.server
import json
import os
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HELPER = ROOT / "scripts" / "beach_visit.py"


class _Beach(http.server.BaseHTTPRequestHandler):
    """A stand-in Beach that answers one wait with a line holding an emoji."""

    paths: list = []

    def do_GET(self):
        _Beach.paths.append(self.path)
        body = json.dumps({"cursor": "9.0.0", "more": False, "actionable": [],
                           "items": [{"source": "message", "kind": "say", "author": "Coral", "text": "sunset \U0001F305"}],
                           "text": "SandChat:\n- Coral: sunset \U0001F305"}).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


class _ClaimBeach(http.server.BaseHTTPRequestHandler):
    """A stand-in Beach for claiming: it records what was sent and hands back a token."""

    claimed: list = []

    def _send(self, obj):
        body = json.dumps(obj).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        _ClaimBeach.claimed.append(json.loads(self.rfile.read(int(self.headers["Content-Length"]))))
        self._send({"token": "Tq4fakeTOKENfor_tests-only9", "name": "Whomever"})

    def do_GET(self):
        self._send({"text": "BEACH CARD"})

    def log_message(self, *args):
        pass


class HelperClaimTests(unittest.TestCase):
    def test_claim_asks_for_the_code_unseen_when_it_isnt_given(self):
        # The keeper, 11-01: a person pastes the invite into a prompt, so it never sits in a command line or history.
        import getpass
        import importlib.util
        import io
        from contextlib import redirect_stdout
        from unittest import mock
        server = http.server.HTTPServer(("127.0.0.1", 0), _ClaimBeach)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        spec = importlib.util.spec_from_file_location("beach_visit", HELPER)
        helper = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(helper)
        try:
            with tempfile.TemporaryDirectory() as d, \
                    mock.patch.dict(os.environ, {"NO_PROXY": "*", "no_proxy": "*"}), \
                    mock.patch.object(getpass, "getpass", return_value=" ABCD-EFGH-JKLM-NPQR \n") as asked:
                for k in ("BEACH_BASE", "BEACH_TOKEN", "BEACH_TOKEN_FILE", "BEACH_CA"):
                    os.environ.pop(k, None)
                argv = ["beach_visit.py", "--base", f"http://127.0.0.1:{server.server_port}", "--dir", d,
                        "claim", "--label", "Whomever"]
                out = io.StringIO()
                with mock.patch.object(sys, "argv", argv), redirect_stdout(out):
                    helper.main()
                self.assertEqual(asked.call_count, 1)
                self.assertEqual(_ClaimBeach.claimed[-1], {"code": "ABCD-EFGH-JKLM-NPQR", "label": "Whomever"})
                self.assertEqual(Path(d, "token").read_text(), "Tq4fakeTOKENfor_tests-only9")
                self.assertNotIn("Tq4fakeTOKEN", out.getvalue())          # the token is never printed
                self.assertNotIn("ABCD-EFGH", out.getvalue())             # nor the code
                self.assertIn("claimed as Whomever", out.getvalue())
        finally:
            server.shutdown()


class HelperOutputTests(unittest.TestCase):
    def test_an_emoji_doesnt_crash_wait_on_a_narrow_console(self):
        server = http.server.HTTPServer(("127.0.0.1", 0), _Beach)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        try:
            with tempfile.TemporaryDirectory() as d:
                Path(d, "visit.json").write_text(json.dumps({"base": f"http://127.0.0.1:{server.server_port}"}))
                Path(d, "token").write_text("Tq4fakeTOKENfor_tests-only9")
                Path(d, "cursor").write_text("1.0.0")
                # The pipe gets the platform default (cp1252 on Windows); `python -I` ignores PYTHONIOENCODING anyway.
                env = dict(os.environ, NO_PROXY="*", no_proxy="*")
                for k in ("BEACH_BASE", "BEACH_TOKEN", "BEACH_TOKEN_FILE", "BEACH_CA"):
                    env.pop(k, None)
                out = subprocess.run([sys.executable, "-I", str(HELPER), "--dir", d, "wait"], env=env,
                                     stdin=subprocess.DEVNULL, capture_output=True, timeout=60)
                self.assertEqual(out.returncode, 0, out.stderr.decode("utf-8", "replace"))
                self.assertIn("Coral: sunset", out.stdout.decode("utf-8", "replace"))
                self.assertEqual(Path(d, "cursor").read_text(), "9.0.0")   # moved, once the news was shown
        finally:
            server.shutdown()
            server.server_close()

    def test_a_day_old_saved_place_starts_from_now(self):
        # HB, 10-22: after a day away, the first wait replayed ~30 lines of yesterday's chat.
        server = http.server.HTTPServer(("127.0.0.1", 0), _Beach)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        _Beach.paths.clear()
        try:
            with tempfile.TemporaryDirectory() as d:
                Path(d, "visit.json").write_text(json.dumps({"base": f"http://127.0.0.1:{server.server_port}"}))
                Path(d, "token").write_text("Tq4fakeTOKENfor_tests-only9")
                Path(d, "cursor").write_text("1.0.0")
                old = time.time() - 24 * 3600
                os.utime(Path(d, "cursor"), (old, old))
                env = dict(os.environ, NO_PROXY="*", no_proxy="*")
                for k in ("BEACH_BASE", "BEACH_TOKEN", "BEACH_TOKEN_FILE", "BEACH_CA"):
                    env.pop(k, None)
                out = subprocess.run([sys.executable, "-I", str(HELPER), "--dir", d, "wait"], env=env,
                                     stdin=subprocess.DEVNULL, capture_output=True, timeout=60)
                self.assertEqual(out.returncode, 0, out.stderr.decode("utf-8", "replace"))
                self.assertIn("starting from now", out.stdout.decode("utf-8", "replace"))
                self.assertNotIn("after=", _Beach.paths[0])              # read from now, not from the old place
        finally:
            server.shutdown()
            server.server_close()


if __name__ == "__main__":
    unittest.main()
