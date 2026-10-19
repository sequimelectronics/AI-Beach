# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Becky Northaven and the AI-Beach contributors
"""Integration test against a running headless Clawblox server.

Skipped unless one of these is set:
  CLAWBLOX_URL                   a server you already started (mesa-island, max_players >= 1 free)
  CLAWBLOX_BIN + CLAWBLOX_WORLD  the built `clawblox` binary and a mesa-island folder; the test
                                 copies the world to a temp dir, starts it on a free port, stops it

Clawblox itself is never part of this repo; build it from source elsewhere.
"""

from __future__ import annotations

import math
import json
import os
import re
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


class _LiveBeachWorld:
    """Starts worlds/beach from this repo on a temp copy, behind a Beach (its front door), for
    Sandy and Pebble. AFK_TIMEOUT, when set, replaces the world's idle limit in the copy only."""

    AFK_TIMEOUT: int | None = None
    LIFEGUARD_AFTER: int | None = None   # replaces the lifeguard's wait, in the copy only

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
        if cls.AFK_TIMEOUT is not None:
            toml = world / "world.toml"
            text = toml.read_text(encoding="utf-8")
            toml.write_text(re.sub(r"(?m)^afk_timeout = \d+$", f"afk_timeout = {cls.AFK_TIMEOUT}", text), encoding="utf-8")
        if cls.LIFEGUARD_AFTER is not None:
            lua = world / "main.lua"
            text = lua.read_text(encoding="utf-8")
            lua.write_text(text.replace("lifeguard = { after = 120 }", f"lifeguard = {{ after = {cls.LIFEGUARD_AFTER} }}"),
                           encoding="utf-8")
        # The Beach, in this process: Sandy and Pebble, and the BeachBlox zone with its bridge token.
        cls.beach = Beach(Path(cls.tmp) / "data", rng=random.Random(1))
        cls.beach.ensure_admin()
        # Each test plays its own pair: one character per participant, so a second test reconnecting
        # the same name would retire the first test's character mid-run (seen 10-18 under load).
        cls.tokens = {n: cls.beach.add_participant(n, "agent")[1] for n in ("Sandy", "Pebble", "Coral", "Shell", "Kelp")}
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



@unittest.skipUnless(BIN, "CLAWBLOX_BIN not set (the beach world itself is in this repo)")
class LiveBeachTest(_LiveBeachWorld, unittest.TestCase):
    """A short round on the beach world. The world names characters by their Beach names, which
    only a Beach can give: run alone, every character keeps the "..." placeholder (job 13 fixed
    this test, which until then expected a name the world can't know)."""

    def test_beach_round(self):
        a = self.adapter("Sandy")
        b = self.adapter("Pebble")
        b.look()  # adapters join lazily: bring Pebble onto the beach first (the door admits them)
        self.assertIn("castle plots", a.map_card())
        self.assertEqual(a.rules.world, "beach")
        self.assertIn("Pebble", a.look())  # named, by the Beach's door, even if Pebble is behind Sandy
        # From the Plaza north-west to the Ball Court (along the north shore, goals at its east and west
        # ends), and kick the soccer ball east from just west of it (the court's middle is -24, 33).
        self.assertIn("arrived", a.act("MoveTo", {"position": [-12, 0, 16]}))
        self.assertIn("arrived", a.act("MoveTo", {"position": [-26.2, 0, 33]}))
        res = a.act("Kick", {"direction": [1, 0, 0], "power": 0.5})
        self.assertTrue(res.startswith("Kicked the soccer ball E"), res)
        # Round the dune's east end to the Sandcastles: build two blocks in plot 2 and see the castle.
        for stop in ([-2, 0, 16], [-2, 0, -13], [-28, 0, -23]):   # one lane east of Pebble, who stands at -6,-6
            a.act("MoveTo", {"position": stop})
        for y in (0.55, 1.55):
            self.assertTrue(a.act("Mold", {"shape": "block"}).startswith("Molded"))
            res = a.act("Place", {"position": [-32, y, -23]})
            self.assertTrue(res.startswith("Placed"), res)
        time.sleep(1.0)
        self.assertRegex(a.look(), r"sandcastle in plot 2 .*: 2 pieces, 2 high")
        # Pebble comes over too, and they talk (both at the Sandcastles).
        for stop in ([-6, 0, -13], [-26, 0, -20]):
            b.act("MoveTo", {"position": stop})
        b.hear()
        a.say("hello Pebble")
        self.assertIn("Sandy: hello Pebble", b.hear())
        bundle = a.turn_bundle()
        self.assertLess(bundle["total_tokens"], 8000)

    def test_regions_shout_and_the_dune(self):
        # 10-18, the island. Speech stays in the speaker's region; a shout carries everywhere. The dune
        # is a ridge of 1.4 ledges, each a running jump high (needs patches/clawblox-region-speech.patch).
        a = self.adapter("Coral")
        b = self.adapter("Shell")
        b.look()   # Shell stays at the Plaza (the spawn points are there)
        card = a.map_card()
        for words in ("the Ball Court", "the Sandcastles", "the Lighthouse", "the Pier", "dune", "island"):
            self.assertIn(words, card)
        for stop in ([-12, 0, 16], [-24, 0, 28]):
            self.assertIn("arrived", a.act("MoveTo", {"position": stop}))
        self.assertIn("in the Ball Court", a.look())
        b.hear()
        a.say("only the court can hear this")
        time.sleep(0.5)
        self.assertNotIn("only the court", b.hear())
        self.assertTrue(a.say("can anyone hear me?", shout=True).startswith("shouted"))
        self.assertIn("Coral shouts: can anyone hear me?", b.hear())
        # South through the dune's gap, then up DuneMiddle from the castle side: two running jumps.
        for stop in ([-23.5, 0, 16], [-23.5, 0, -8], [-31, 0, -8]):
            a.act("MoveTo", {"position": stop})
        res = a.act("MoveTo", {"position": [-31, 1.4, 0.5], "jump": True})   # the lower strip
        self.assertIn("on DuneMiddle", res)
        res = a.act("MoveTo", {"position": [-31, 2.8, 4], "jump": True})     # the top
        self.assertIn("on DuneMiddleTop", res)
        self.assertIn("between regions", a.look())



@unittest.skipUnless(BIN, "CLAWBLOX_BIN not set (the beach world itself is in this repo)")
class LiveLighthouseTest(_LiveBeachWorld, unittest.TestCase):
    """The pier and the lighthouse (10-18): onto the deck and out to its end; then up the lighthouse's
    spiral, pad by pad as the map card describes it, to the top, which earns the lighthouse badge."""

    def test_the_pier_then_up_the_lighthouse(self):
        from adapters.clawblox.world import beach_layout
        a = self.adapter("Kelp")
        a.look()
        self.assertIn("lighthouse: a tower", a.map_card())
        self.assertIn("pier: a plank deck", a.map_card())
        a.act("MoveTo", {"position": [30, 0, -25]})
        self.assertIn("on PierDeck", a.act("MoveTo", {"position": [48, 0.3, -25]}))
        self.assertIn("on PierEnd", a.act("MoveTo", {"position": [54.5, 0.3, -25]}))
        self.assertIn("in the Pier", a.look())
        for stop in ([30, 0, -25], [28, 0, 28]):
            a.act("MoveTo", {"position": stop})
        lh = beach_layout(a._observe())["lighthouse"]

        def pad(n, r=None):
            ang = math.radians(lh["first_deg"] + (n - 1) * lh["step_deg"])
            r = r or lh["ramp_r"]
            return [lh["x"] + r * math.cos(ang), n * lh["rise"], lh["z"] + r * math.sin(ang)]
        # Two pads per walk (they overlap, so the straight line between them stays on pads).
        for n in [1] + list(range(3, lh["pads"] + 1, 2)) + [lh["pads"]]:
            res = a.act("MoveTo", {"position": pad(n)})
            # On the spiral (neighboring pads overlap, so either may be named) and at pad n's height.
            self.assertIn("on LighthouseStep", res, f"pad {n}")
            y = float(re.search(r"at \([-\d.]+,([-\d.]+),", res).group(1))
            self.assertGreater(y, n * lh["rise"] + 2.5 - 0.5, f"pad {n}: {res}")
        res = a.act("MoveTo", {"position": pad(lh["pads"] + 1, lh["tower_r"] + 1.2)})
        y = float(re.search(r"at \([-\d.]+,([-\d.]+),", res).group(1))
        self.assertGreater(y, lh["top_y"] + 2.0, res)   # up at the top's level (the landing reaches onto it)
        self.assertIn("on LighthouseTower", a.act("MoveTo", {"position": [lh["x"], lh["top_y"], lh["z"]]}))
        heard = ""
        for _ in range(8):
            heard += a.hear()
            if "reached the top of the lighthouse" in heard:
                break
            time.sleep(1)
        self.assertIn("Kelp reached the top of the lighthouse!", heard)
        pid = self.beach.by_name("Kelp").id
        for _ in range(15):   # the bridge reports the world's events every couple of seconds
            if "lighthouse" in self.beach.badges.today(pid):
                break
            time.sleep(1)
        self.assertIn("lighthouse", self.beach.badges.today(pid))


@unittest.skipUnless(BIN, "CLAWBLOX_BIN not set (the beach world itself is in this repo)")
class LiveSandArtTest(_LiveBeachWorld, unittest.TestCase):
    """Sand art (10-18): a shape walked for you leaves a picture agents can read; the box is yours
    (another can't draw in it, and their steps leave nothing); a big enough picture earns the badge;
    Rake clears it."""

    def test_draw_a_heart_and_rake_it(self):
        a = self.adapter("Sandy")
        b = self.adapter("Pebble")
        a.look()
        b.look()
        self.assertIn("sand gardens: box 1 at 22,0", a.map_card())
        for stop in ([16, 0, 0],):
            a.act("MoveTo", {"position": stop})
            b.act("MoveTo", {"position": [16, 0, 4]})
        view = a.look()
        self.assertIn("in the Sand Gardens", view)
        self.assertIn("box 1 at 22,0 (14x14), free, 0 grooves: smooth sand", view)
        res = a.act("Draw", {"box": 1, "shape": "heart", "size": 5})
        self.assertTrue(res.startswith("Drew heart in box 1"), res)
        rows = [line for line in res.splitlines()[2:] if set(line) <= {"#", "."}]
        self.assertEqual(len(rows), 14, res)
        marks = int(re.search(r"(\d+) grooves", res).group(1))
        self.assertGreater(marks, 40, res)
        # Box 1 is Sandy's: Pebble can't draw there, and Pebble walking through leaves nothing.
        self.assertIn("another artist", b.act("Draw", {"box": 1}))
        b.act("MoveTo", {"position": [26, 0, -4]})
        b.act("MoveTo", {"position": [18, 0, 4]})
        self.assertIn(f"{marks} grooves", a.look())
        heard = ""
        for _ in range(6):
            heard += a.hear()
            if "drew a picture in the sand" in heard:
                break
            time.sleep(1)
        self.assertIn("Sandy drew a picture in the sand (box 1).", heard)
        pid = self.beach.by_name("Sandy").id
        for _ in range(15):
            if "sand-art" in self.beach.badges.today(pid):
                break
            time.sleep(1)
        self.assertIn("sand-art", self.beach.badges.today(pid))
        self.assertEqual(a.act("Rake", {}).splitlines()[0], "Raked your box smooth")
        time.sleep(1.5)
        self.assertIn("0 grooves: smooth sand", a.look())


@unittest.skipUnless(BIN, "CLAWBLOX_BIN not set (the beach world itself is in this repo)")
class LiveLifeguardTest(_LiveBeachWorld, unittest.TestCase):
    """The lifeguard (10-18): a ball left outside the Ball Court, untouched and still, is picked up and
    hidden on the island's sand, with a hint. The wait is cut to a few seconds here."""

    LIFEGUARD_AFTER = 4

    def test_a_lost_ball_is_hidden_with_a_hint(self):
        from adapters.clawblox.compact import on_land, region_at
        from adapters.clawblox.world import beach_layout
        a = self.adapter("Sandy")
        a.look()
        for stop in ([-12, 0, 16], [-29, 0, 28]):
            a.act("MoveTo", {"position": stop})
        self.assertTrue(a.act("Pickup", {"position": [-29, 0.55, 30]}).startswith("Picked up"))
        for stop in ([-12, 0, 16], [2, 0, 2]):
            a.act("MoveTo", {"position": stop})
        self.assertTrue(a.act("Place", {"position": [4, 0.55, 2]}).startswith("Placed"))
        a.act("MoveTo", {"position": [-6, 0, -6]})
        heard = ""
        for _ in range(20):
            time.sleep(1)
            heard += a.hear()
            if "The lifeguard found the volleyball" in heard:
                break
        m = re.search(r"The lifeguard found the volleyball and left it somewhere around (the [A-Z][a-z]+)\.", heard)
        self.assertTrue(m, heard)
        self.assertIn(m.group(1), ("the Plaza", "the Sandcastles", "the Lighthouse", "the Pier"))   # never the court
        raw = json.loads(a._call("GET", "/observe"))
        layout = beach_layout(a._observe())
        for e in (raw.get("world") or {}).get("entities") or []:
            if e.get("name") == "Volleyball":   # within sight: on the sand, in the hinted region
                self.assertTrue(on_land(layout, e["position"]))
                self.assertEqual(region_at(layout, e["position"]), m.group(1))


@unittest.skipUnless(BIN, "CLAWBLOX_BIN not set (the beach world itself is in this repo)")
class LiveChatIdleTest(_LiveBeachWorld, unittest.TestCase):
    """Chatting counts as being active (patches/clawblox-chat-activity.patch): with the world's idle
    limit cut to a few seconds, Sandy only talks and stays; Pebble says and does nothing and is
    removed. Needs a Clawblox built with that patch."""

    AFK_TIMEOUT = 6

    def test_chatting_player_stays_silent_player_is_removed(self):
        from adapters.clawblox.adapter import CharacterGone
        sandy = self.adapter("Sandy")
        pebble = self.adapter("Pebble")
        sandy.look()
        pebble.look()
        start = time.monotonic()
        while time.monotonic() - start < 4 * self.AFK_TIMEOUT:   # well past the limit
            self.assertTrue(sandy.say("still here, just talking").startswith("said:"))
            time.sleep(1.5)
        # Sandy never moved or acted, only talked: still in the world.
        self.assertTrue(sandy.look().startswith("you ("))
        # Pebble did nothing at all: the world took their character out.
        with self.assertRaises(CharacterGone):
            pebble.look()


if __name__ == "__main__":
    unittest.main()
