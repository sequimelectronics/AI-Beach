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
                                    stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
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


BEACH_DIR = Path(__file__).resolve().parents[1] / "worlds" / "beach"


@unittest.skipUnless(BIN, "CLAWBLOX_BIN not set (the beach world itself is in this repo)")
class LiveBeachTest(unittest.TestCase):
    """Starts worlds/beach from this repo on a temp copy, behind a Beach (its front door), and plays
    a short round. The world names characters by their Beach names, which only a Beach can give:
    run alone, every character keeps the "..." placeholder (job 13 fixed this test, which until
    then expected a name the world can't know)."""

    @classmethod
    def setUpClass(cls):
        import random
        import threading
        try:
            import uvicorn
            from beach.app import create_app
        except ImportError:
            raise unittest.SkipTest("needs the Beach's requirements (fastapi, uvicorn)")
        from beach.bridge import Bridge, run_loop, spectator_token_from_log
        from beach.core import Beach
        cls.tmp = tempfile.mkdtemp(prefix="beach-it-")
        world = Path(cls.tmp) / "beach"
        shutil.copytree(BEACH_DIR, world, ignore=shutil.ignore_patterns(".clawblox", "dist", ".build.lock"))
        # The Beach, in this process: Sandy and Pebble, and the BeachBlox zone with its bridge token.
        cls.beach = Beach(Path(cls.tmp) / "data", rng=random.Random(1))
        cls.beach.ensure_admin()
        cls.tokens = {n: cls.beach.add_participant(n, "agent")[1] for n in ("Sandy", "Pebble")}
        cls.beach.add_zone("beachblox", "BeachBlox", "game")
        bridge_token = cls.beach.bridge_token("beachblox")
        beach_port = _free_port()
        cls.beach_url = f"http://127.0.0.1:{beach_port}"
        cls.server = uvicorn.Server(uvicorn.Config(create_app(cls.beach, upkeep_interval=None), host="127.0.0.1",
                                                   port=beach_port, log_level="error"))
        threading.Thread(target=cls.server.run, daemon=True).start()
        # The world, logging to a file the bridge reads its spectator token from.
        port = _free_port()
        cls.url = f"http://127.0.0.1:{port}"
        log_path = Path(cls.tmp) / "world.log"
        cls.log = open(log_path, "w")
        cls.proc = subprocess.Popen([BIN, "run", str(world), "--port", str(port)],
                                    stdin=subprocess.DEVNULL, stdout=cls.log, stderr=subprocess.STDOUT)
        for _ in range(240):
            try:
                urllib.request.urlopen(cls.url + "/api.md", timeout=1).read()
                break
            except OSError:
                time.sleep(0.5)
        else:
            cls.tearDownClass()
            raise unittest.SkipTest("beach server did not start")
        # Its bridge, in a thread: the door's claims into the world, presence back to the Beach.
        cls.stop = threading.Event()
        bridge = Bridge(cls.url, cls.beach_url, "beachblox", bridge_token, lambda: spectator_token_from_log(str(log_path)),
                        str(world), log=lambda m: None)
        cls.bridge = threading.Thread(target=run_loop, args=(bridge, 2.0), kwargs={"keep_going": lambda: not cls.stop.is_set()},
                                      daemon=True)
        cls.bridge.start()

    @classmethod
    def tearDownClass(cls):
        if getattr(cls, "stop", None):
            cls.stop.set()
            cls.bridge.join(timeout=10)
        cls.proc.terminate()
        cls.proc.wait(timeout=10)
        cls.log.close()
        cls.server.should_exit = True
        cls.beach.db.close()
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def adapter(self, name):
        from adapters.clawblox.front_door import beach_voucher
        return ClawbloxAdapter(self.url, name, vouch=beach_voucher(self.beach_url, self.tokens[name], "beachblox"))

    def test_beach_round(self):
        a = self.adapter("Sandy")
        b = self.adapter("Pebble")
        b.look()  # adapters join lazily: bring Pebble onto the beach first (the door admits them)
        self.assertIn("castle plots", a.map_card())
        self.assertEqual(a.rules.world, "beach")
        self.assertIn("Pebble", a.look())  # named, by the Beach's door, even if Pebble is behind Sandy
        # Kick the soccer ball from just south of it.
        self.assertIn("arrived", a.act("MoveTo", {"position": [0, 0, -2.2]}))
        res = a.act("Kick", {"direction": [0, 0, 1], "power": 0.5})
        self.assertTrue(res.startswith("Kicked the soccer ball N"), res)
        # Build two blocks in plot 2 and see the castle summary.
        a.act("MoveTo", {"position": [-6.5, 0, -6]})
        for y in (0.55, 1.55):
            self.assertTrue(a.act("Mold", {"shape": "block"}).startswith("Molded"))
            res = a.act("Place", {"position": [-9.5, y, -6]})
            self.assertTrue(res.startswith("Placed"), res)
        time.sleep(1.0)
        self.assertRegex(a.look(), r"sandcastle in plot 2 .*: 2 pieces, 2 high")
        # Chat both ways.
        a.say("hello Pebble")
        self.assertIn("Sandy: hello Pebble", b.hear())
        bundle = a.turn_bundle()
        self.assertLess(bundle["total_tokens"], 8000)


if __name__ == "__main__":
    unittest.main()
