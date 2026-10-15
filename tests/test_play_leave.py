"""Job 10, item 2: one character per participant per world. Play becomes Leave.

Against a temporary data directory with a fake clock, and stand-ins for the world (join and "is
this session still there?"). The live run against a real world is scripts/play_leave_live.py.
"""

from __future__ import annotations

import random
import shutil
import sys
import tempfile
import threading
import time
import unittest
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from beach import agent  # noqa: E402
from beach.core import Beach, BeachError  # noqa: E402

try:
    from fastapi.testclient import TestClient
    HAVE_FASTAPI = True
except ImportError:  # pragma: no cover
    HAVE_FASTAPI = False


class FakeClock:
    def __init__(self, t: float = 1_800_000_000.0):
        self.t = t

    def __call__(self) -> float:
        return self.t

    def advance(self, s: float) -> None:
        self.t += s


class FakeWorld:
    """Joins, and which sessions are still in the world."""

    def __init__(self):
        self.joins = []
        self.live = set()
        self.slow = 0.0

    def join(self, url, name, key=None):
        if self.slow:
            time.sleep(self.slow)
        j = {"session": f"sess-{len(self.joins) + 1}", "agent_id": str(uuid.uuid4())}
        self.joins.append((name, j))
        self.live.add(j["session"])
        return j

    def alive(self, url, session):
        return session in self.live

    def restart(self):
        self.live.clear()


class Case(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="play-")
        self.clock = FakeClock()
        self.beach = Beach(self.dir, clock=self.clock, rng=random.Random(10))
        self.admin_tok = self.beach.ensure_admin()
        self.coral, self.coral_tok = self.beach.add_participant("Coral", "person")
        self.sandy, self.sandy_tok = self.beach.add_participant("Sandy", "agent")
        self.beach.add_zone("beachblox", "BeachBlox", "game", viewer_url="http://127.0.0.1:8100/")
        self.beach.set_world_url("beachblox", "http://127.0.0.1:8100")
        self.world = FakeWorld()

    def tearDown(self):
        self.beach.db.close()
        shutil.rmtree(self.dir, ignore_errors=True)

    def play(self, who):
        return self.beach.play(who.id, "beachblox", joiner=self.world.join, alive=self.world.alive)

    def report(self, *players):
        """What the world's bridge reports: the players in the world, by the joins they were."""
        from beach.core import Beach as B
        entries = []
        for name, j in self.world.joins:
            if j["session"] in self.world.live and name in players:
                entries.append({"user_id": B.user_id_for(j["agent_id"]), "joined_as": name})
        self.beach.report_players("beachblox", entries)


class OneCharacterTests(Case):
    def test_playing_again_gives_back_the_same_character(self):
        first = self.play(self.coral)
        again = self.play(self.coral)
        self.assertFalse(first["existing"])
        self.assertTrue(again["existing"])
        self.assertEqual(again["session"], first["session"])
        self.assertEqual(len(self.world.joins), 1)              # joined once
        self.assertIn("#session=" + first["session"], again["viewer"])

    def test_two_requests_at_once_join_once(self):
        # A double click, or two tabs: both requests arrive together.
        self.world.slow = 0.2
        results = []
        threads = [threading.Thread(target=lambda: results.append(self.play(self.coral))) for _ in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(len(self.world.joins), 1)
        self.assertEqual({r["session"] for r in results}, {"sess-1"})

    def test_after_a_world_restart_play_joins_afresh(self):
        first = self.play(self.coral)
        self.world.restart()                                     # the old character is gone
        second = self.play(self.coral)
        self.assertFalse(second["existing"])
        self.assertNotEqual(second["session"], first["session"])
        # Only the new join counts; the old grant is retired, so the world's door would drop it.
        claims = [c for g in self.beach.door("beachblox")["grants"] for c in g["claims"]]
        self.assertEqual(sorted(c["left"] for c in claims), [False, True])

    def test_each_person_has_their_own(self):
        a, b = self.play(self.coral), self.play(self.sandy)
        self.assertNotEqual(a["session"], b["session"])
        self.assertEqual(len(self.world.joins), 2)

    def test_a_second_vouched_join_retires_the_first(self):
        # Without a join key an agent can join by itself and vouch; still one character each.
        a1, a2 = str(uuid.uuid4()), str(uuid.uuid4())
        self.beach.vouch(self.sandy.id, "beachblox", a1, "Sandy")
        self.beach.vouch(self.sandy.id, "beachblox", a2, "Sandy")
        left = {c["left"] for g in self.beach.door("beachblox")["grants"]
                for c in g["claims"] if g["user_id"] == Beach.user_id_for(a1)}
        self.assertEqual(left, {True})


class LeaveTests(Case):
    def test_leave_removes_the_character_and_presence_at_once(self):
        self.play(self.coral)
        self.report("Coral")
        self.assertEqual([w["name"] for w in self.beach.who_in("beachblox")], ["Coral"])
        self.assertTrue(self.beach.playing(self.coral.id, "beachblox"))
        r = self.beach.leave_world(self.coral.id, "beachblox")
        self.assertTrue(r["left"])
        self.assertEqual(self.beach.who_in("beachblox"), [])             # the map agrees at once
        self.assertFalse(self.beach.playing(self.coral.id, "beachblox"))
        # The world's door is told: the claim says "left", and BeachDoor removes the character.
        claims = [c for g in self.beach.door("beachblox")["grants"] for c in g["claims"]]
        self.assertEqual([c["left"] for c in claims], [True])
        # Until the door has done it the bridge may still report them: they aren't counted.
        self.report("Coral")
        self.assertEqual(self.beach.who_in("beachblox"), [])

    def test_play_after_leave_is_a_new_character(self):
        first = self.play(self.coral)
        self.beach.leave_world(self.coral.id, "beachblox")
        second = self.play(self.coral)                                    # even if the old session lingers
        self.assertFalse(second["existing"])
        self.assertNotEqual(second["session"], first["session"])

    def test_leaving_when_not_playing_is_harmless(self):
        self.assertFalse(self.beach.leave_world(self.coral.id, "beachblox")["left"])
        with self.assertRaises(BeachError):
            self.beach.leave_world(self.coral.id, "sandchat")


class ButtonStateTests(Case):
    def test_play_then_leave_then_play(self):
        b = self.beach
        self.assertFalse(b.playing(self.coral.id, "beachblox"))          # Play
        self.play(self.coral)
        self.assertTrue(b.playing(self.coral.id, "beachblox"))           # Leave, at once
        self.clock.advance(30)
        self.report("Coral")
        self.assertTrue(b.playing(self.coral.id, "beachblox"))           # still there, per the bridge
        self.world.restart()
        self.report()                                                     # the restarted world has nobody
        self.assertFalse(b.playing(self.coral.id, "beachblox"))          # Play again
        self.play(self.coral)
        self.assertTrue(b.playing(self.coral.id, "beachblox"))

    def test_the_bridge_going_quiet_means_play(self):
        self.play(self.coral)
        self.report("Coral")
        self.clock.advance(self.beach.setting("game_report_ttl_s") + 30)   # no reports: world or bridge gone
        self.assertFalse(self.beach.playing(self.coral.id, "beachblox"))

    def test_map_page_shows_the_button(self):
        js = (ROOT / "beach" / "web" / "map.js").read_text()
        self.assertIn("text: z.playing ? 'Leave' : 'Play'", js)
        self.assertIn("'DELETE', '/zones/' + encodeURIComponent(z.id) + '/play'", js)


@unittest.skipUnless(HAVE_FASTAPI, "fastapi/httpx not installed")
class HttpTests(Case):
    def test_over_http(self):
        from beach import front_door
        from beach.app import create_app
        orig = (front_door.join_world, front_door.session_alive)
        front_door.join_world, front_door.session_alive = self.world.join, self.world.alive
        try:
            http = TestClient(create_app(self.beach, upkeep_interval=None))
            h = {"Authorization": f"Bearer {self.coral_tok}"}
            self.assertFalse(http.get("/zones/beachblox/play", headers=h).json()["playing"])
            game = [z for z in http.get("/map", headers=h).json()["zones"] if z["id"] == "beachblox"][0]
            self.assertFalse(game["playing"])
            a = http.post("/zones/beachblox/play", headers=h).json()
            b = http.post("/zones/beachblox/play", headers=h).json()
            self.assertEqual(a["session"], b["session"])
            self.assertTrue(b["existing"])
            game = [z for z in http.get("/map", headers=h).json()["zones"] if z["id"] == "beachblox"][0]
            self.assertTrue(game["playing"])
            self.assertTrue(http.delete("/zones/beachblox/play", headers=h).json()["left"])
            self.assertFalse(http.get("/zones/beachblox/play", headers=h).json()["playing"])
        finally:
            front_door.join_world, front_door.session_alive = orig


class SessionAliveTests(unittest.TestCase):
    def test_asks_the_world(self):
        import http.server
        from beach.front_door import session_alive

        class W(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                ok = self.path == "/observe" and self.headers.get("X-Session") == "good"
                self.send_response(200 if ok else 401)
                self.send_header("Content-Length", "2")
                self.end_headers()
                self.wfile.write(b"{}")

            def log_message(self, *a):
                pass
        srv = http.server.HTTPServer(("127.0.0.1", 0), W)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        try:
            url = f"http://127.0.0.1:{srv.server_port}"
            self.assertTrue(session_alive(url, "good"))
            self.assertFalse(session_alive(url, "gone"))
            self.assertFalse(session_alive("http://127.0.0.1:9", "good"))     # world down: not there
            self.assertFalse(session_alive("http://192.168.1.5:8100", "good"))  # never off this machine
        finally:
            srv.shutdown()
            srv.server_close()


class AgentTests(Case):
    def test_card_says_one_character(self):
        card = agent.zone_card(self.beach, "beachblox")
        self.assertIn("One character each", card)
        self.assertIn("DELETE", card)

    def test_adapter_leave_goes_through_the_beach(self):
        from adapters.clawblox.adapter import ClawbloxAdapter
        calls = []
        a = ClawbloxAdapter(transport=object(), name="Sandy", session="s", leave_via=lambda: calls.append("left"))
        a.leave()
        self.assertEqual(calls, ["left"])
        self.assertIsNone(a.session)


if __name__ == "__main__":
    unittest.main()
