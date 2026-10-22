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
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HELPER = ROOT / "scripts" / "beach_visit.py"


class _Beach(http.server.BaseHTTPRequestHandler):
    """A stand-in Beach that answers one wait with a line holding an emoji."""

    def do_GET(self):
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


class HelperOutputTests(unittest.TestCase):
    def test_an_emoji_doesnt_crash_wait_on_a_narrow_console(self):
        server = http.server.HTTPServer(("127.0.0.1", 0), _Beach)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        try:
            with tempfile.TemporaryDirectory() as d:
                Path(d, "visit.json").write_text(json.dumps({"base": f"http://127.0.0.1:{server.server_port}"}))
                Path(d, "token").write_text("Tq4fakeTOKENfor_tests-only9")
                Path(d, "cursor").write_text("1.0.0")
                env = dict(os.environ, PYTHONIOENCODING="cp1252", NO_PROXY="*", no_proxy="*")
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


if __name__ == "__main__":
    unittest.main()
