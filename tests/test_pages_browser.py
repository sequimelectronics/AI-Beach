# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Becky Northaven and the AI-Beach contributors
"""Job 12's page changes in a real browser: the bar with every zone and pins, the picture menu,
the grayed-out target box, Leave table, a game world's page under the bar, My look's labels.

Runs the Beach (in this process, on a free local port) and tests/browser_pages.cjs under Node with
Playwright. Skipped when Node, Playwright or a Chromium isn't available (set PLAYWRIGHT_MODULE to
the playwright package directory, and CHROMIUM to a browser, if they're somewhere unusual).
"""

from __future__ import annotations

import json
import os
import random
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from beach.core import BOARDWALK, SANDCHAT, Beach  # noqa: E402


def _playwright() -> str | None:
    for p in (os.environ.get("PLAYWRIGHT_MODULE"), "/opt/node-tools/node_modules/playwright"):
        if p and (Path(p) / "package.json").exists():
            return p
    return None


def _chromium() -> str:
    for p in (os.environ.get("CHROMIUM"), "/opt/pw-browsers/chromium"):
        if p and Path(p).exists():
            return p
    return ""


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@unittest.skipUnless(shutil.which("node") and _playwright(), "needs node and playwright")
class PagesInABrowser(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            import uvicorn
            from beach.app import create_app
        except ImportError:
            raise unittest.SkipTest("needs fastapi and uvicorn")
        cls.dir = tempfile.mkdtemp(prefix="pages-")
        b = cls.beach = Beach(cls.dir, rng=random.Random(3))
        b.ensure_admin()
        coral, cls.tok = b.add_participant("Coral", "person")
        sandy = b.add_participant("Sandy", "agent")[0]
        b.add_zone("beachblox", "BeachBlox", "game", viewer_url="http://127.0.0.1:9/")
        b.set_world_url("beachblox", "http://127.0.0.1:9")
        b.join(coral.id, SANDCHAT)
        b.join(sandy.id, SANDCHAT)
        tid = b.tables.open(coral.id, BOARDWALK, "crazy8", options={"players": 2})["id"]
        b.tables.sit(sandy.id, tid)
        b.tables.resign(sandy.id, tid)                              # a finished table, Coral at it
        cls.port = _free_port()
        cfg = uvicorn.Config(create_app(b, upkeep_interval=None), host="127.0.0.1", port=cls.port, log_level="error")
        cls.server = uvicorn.Server(cfg)
        cls.thread = threading.Thread(target=cls.server.run, daemon=True)
        cls.thread.start()
        for _ in range(100):
            if cls.server.started:
                break
            time.sleep(0.05)
        r = subprocess.run(["node", str(ROOT / "tests" / "browser_pages.cjs"), _playwright(), _chromium(),
                            f"http://127.0.0.1:{cls.port}", cls.tok],
                           stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=180)
        lines = [ln for ln in r.stdout.splitlines() if ln.startswith("{")]
        cls.seen = json.loads(lines[-1]) if lines else {"fatal": r.stderr[-500:]}
        if "fatal" in cls.seen and "Executable doesn't exist" in cls.seen["fatal"]:
            raise unittest.SkipTest("no Chromium for playwright")

    @classmethod
    def tearDownClass(cls):
        cls.server.should_exit = True
        cls.thread.join(timeout=10)
        cls.beach.db.close()
        shutil.rmtree(cls.dir, ignore_errors=True)

    def test_ran_cleanly(self):
        self.assertNotIn("fatal", self.seen)
        self.assertEqual(self.seen["errors"], [])

    def test_the_bar_lists_every_zone_with_the_right_pins(self):
        bar = {a["text"]: a["pin"] for a in self.seen["bar"]}
        self.assertEqual(bar, {"Map": False, "SandChat": True, "The Boardwalk": True, "BeachBlox": False})
        said = {a["text"]: a["sr"].strip() for a in self.seen["bar"]}           # what a screen reader hears
        self.assertEqual(said["SandChat"], "(you're here)")
        hrefs = {a["text"]: a["href"] for a in self.seen["bar"]}
        self.assertEqual(hrefs["BeachBlox"], "/world?zone=beachblox")        # a game world gets a bar link
        self.assertNotIn("My look", bar)
        self.assertNotIn("Sign out", bar)

    def test_your_picture_opens_my_look_and_sign_out(self):
        self.assertTrue(self.seen["menuHiddenAtFirst"])
        self.assertTrue(self.seen["menuShown"])
        self.assertEqual(self.seen["menu"], ["My look", "Sign out"])

    def test_the_target_box_grays_out(self):
        self.assertTrue(self.seen["targetForWave"])
        self.assertFalse(self.seen["targetForGreet"])
        self.assertEqual([t.strip(" 🔔") for t in self.seen["bell"]], ["Ring the Gather Bell"])

    def test_leave_table_and_leave_the_boardwalk(self):
        self.assertIn("Leave table", self.seen["tableButtons"])
        self.assertIn("Leave The Boardwalk", self.seen["tableButtons"])
        self.assertEqual(self.seen["afterLeaveTable"], "?zone=boardwalk")

    def test_a_world_page_keeps_the_bar(self):
        self.assertEqual(self.seen["worldBar"], 4)                            # Map and the three zones
        self.assertEqual(self.seen["worldButtons"], ["Play", "Watch"])

    def test_my_look_labels(self):
        self.assertEqual(self.seen["lookPairs"], [["Hair style", "Hair color"], ["Clothing theme", "Accessory"]])


if __name__ == "__main__":
    unittest.main()
