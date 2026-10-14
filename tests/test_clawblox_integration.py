"""Integration test against a running headless Clawblox server.

Skipped unless one of these is set:
  CLAWBLOX_URL                   a server you already started (mesa-island, max_players >= 1 free)
  CLAWBLOX_BIN + CLAWBLOX_WORLD  the built `clawblox` binary and a mesa-island folder; the test
                                 copies the world to a temp dir, starts it on a free port, stops it

Clawblox itself is never part of this repo; build it from source elsewhere.
"""

from __future__ import annotations

import math
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import unittest
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from adapters.clawblox import ClawbloxAdapter  # noqa: E402

URL = os.environ.get("CLAWBLOX_URL")
BIN = os.environ.get("CLAWBLOX_BIN")
WORLD = os.environ.get("CLAWBLOX_WORLD")


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@unittest.skipUnless(URL or (BIN and WORLD), "no Clawblox server or binary configured")
class LiveAdapterTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.proc = None
        cls.tmp = None
        if URL:
            cls.url = URL
            return
        cls.tmp = tempfile.mkdtemp(prefix="clawblox-it-")
        world = Path(cls.tmp) / "world"
        shutil.copytree(WORLD, world, ignore=shutil.ignore_patterns(".clawblox"))
        port = _free_port()
        cls.url = f"http://127.0.0.1:{port}"
        cls.proc = subprocess.Popen([BIN, "run", str(world), "--port", str(port)],
                                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        for _ in range(120):
            try:
                urllib.request.urlopen(cls.url + "/api.md", timeout=1).read()
                break
            except OSError:
                time.sleep(0.5)
        else:
            cls.tearDownClass()
            raise unittest.SkipTest("Clawblox server did not start")

    @classmethod
    def tearDownClass(cls):
        if cls.proc:
            cls.proc.terminate()
            cls.proc.wait(timeout=10)
        if cls.tmp:
            shutil.rmtree(cls.tmp, ignore_errors=True)

    def test_play_loop(self):
        a = ClawbloxAdapter(self.url, "ItBot")
        card = a.map_card()
        self.assertIn("SmallPlateau", card)
        view = a.look()
        self.assertTrue(view.startswith("you ("), view)

        res = a.act("MoveTo", {"position": [12.6, 0, -1.3]})
        self.assertIn("arrived", res)

        snap = a.last_snapshot
        block = min((e for e in snap.objects if e.kind == "block"),
                    key=lambda e: sum((p - q) ** 2 for p, q in zip(e.pos, snap.me)))
        res = a.act("Pickup", {"position": list(block.pos)})
        self.assertTrue(res.startswith("Picked up"), res)
        self.assertIn("holding", a.look().splitlines()[0])
        # Choose a spot the look shows is clear (loose blocks scatter around the pile).
        snap = a.last_snapshot
        me = snap.me
        spots = [[me[0] + dx, 0.6, me[2] + dz] for dx, dz in ((-3, 0), (0, 3), (0, -3), (-3, 3), (-3, -3))]
        clear = [p for p in spots
                 if all(math.hypot(e.pos[0] - p[0], e.pos[2] - p[2]) > 1.3 for e in snap.objects)]
        res = a.act("Place", {"position": clear[0]})
        self.assertTrue(res.startswith("Placed"), res)

        self.assertEqual(a.say("integration hello"), "said: integration hello")
        self.assertEqual(a.hear(), "(no new chat)")  # own message is not repeated

        b = a.turn_bundle()
        self.assertLess(b["total_tokens"], 8000)
        self.assertEqual(len(a.history().splitlines()), 3)


if __name__ == "__main__":
    unittest.main()
