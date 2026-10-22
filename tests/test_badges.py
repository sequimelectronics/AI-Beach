# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Becky Northaven and the AI-Beach contributors
"""Badges for the day: earned, shown, chosen, announced on arrival, gone after the reset."""

from __future__ import annotations

import json
import random
import shutil
import sqlite3
import sys
import tempfile
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from beach.agent import state_text  # noqa: E402
from beach.badges import BADGES  # noqa: E402
from beach.core import BOARDWALK, SANDCHAT, Beach, BeachError  # noqa: E402

try:
    from fastapi.testclient import TestClient
    HAVE_FASTAPI = True
except ImportError:  # pragma: no cover
    HAVE_FASTAPI = False


class FakeClock:
    def __init__(self, t: float):
        self.t = t

    def __call__(self) -> float:
        return self.t

    def advance(self, s: float) -> None:
        self.t += s


# 03:30 local time: half an hour before the default 04:00 reset.
BEFORE_RESET = time.mktime((2027, 3, 10, 3, 30, 0, 0, 0, -1))


class BadgeCase(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="badges-")
        self.clock = FakeClock(BEFORE_RESET)
        self.beach = Beach(self.dir, clock=self.clock, rng=random.Random(3))
        self.beach.ensure_admin()
        self.p = {}
        for name, kind in (("Sandy", "agent"), ("Pebble", "agent"), ("Coral", "person"), ("Drift", "person")):
            self.p[name], _ = self.beach.add_participant(name, kind)
        self.b = self.beach.badges

    def tearDown(self):
        self.beach.db.close()
        shutil.rmtree(self.dir, ignore_errors=True)

    def sandchat_lines(self, reader="Drift"):
        return [m["text"] for m in self.beach.read(self.p[reader].id, SANDCHAT)]

    def vouch(self, name, zid="beachblox", agent_id="00000000-0000-4000-8000-0000000000{:02d}"):
        """A game-world join the Beach vouched for (as the front door records it)."""
        p = self.p[name]
        aid = agent_id.format(p.id)
        uid = self.beach.user_id_for(aid)
        self.beach.db.run("INSERT INTO game_grants (agent_id, user_id, zone_id, participant_id, joined_as, granted_at)"
                          " VALUES (?, ?, ?, ?, ?, ?)", (aid, uid, zid, p.id, name, self.clock()))
        return uid


class EarningTests(BadgeCase):
    def test_saying_hello_in_sandchat(self):
        self.beach.join(self.p["Coral"].id, SANDCHAT)
        self.assertEqual(self.b.today(self.p["Coral"].id), [])
        self.beach.post(self.p["Coral"].id, SANDCHAT, "hi all")
        self.assertEqual(self.b.today(self.p["Coral"].id), ["hello"])
        self.beach.post(self.p["Coral"].id, SANDCHAT, "again")      # once a day; no counts
        self.assertEqual(self.b.today(self.p["Coral"].id), ["hello"])
        self.assertEqual(self.beach.db.one("SELECT COUNT(*) AS n FROM badges")["n"], 1)

    def test_an_action_says_hello_too_but_other_zones_dont(self):
        tid = self.beach.tables.open(self.p["Sandy"].id, BOARDWALK, "checkers")["id"]
        self.beach.tables.say(self.p["Sandy"].id, tid, "hello table")      # table chat isn't SandChat
        self.assertEqual(self.b.today(self.p["Sandy"].id), [])
        self.beach.join(self.p["Sandy"].id, SANDCHAT)
        self.beach.post(self.p["Sandy"].id, SANDCHAT, "/me waves")
        self.assertEqual(self.b.today(self.p["Sandy"].id), ["hello"])

    def test_checkers_and_card_games(self):
        bw = self.beach.tables
        tid = bw.open(self.p["Sandy"].id, BOARDWALK, "checkers")["id"]
        bw.sit(self.p["Pebble"].id, tid)
        bw.move(self.p["Sandy"].id, tid, "c3-d4")
        self.assertEqual(self.b.today(self.p["Sandy"].id), ["checkers"])
        self.assertEqual(self.b.today(self.p["Pebble"].id), [])        # played = made a move
        tid = bw.open(self.p["Sandy"].id, BOARDWALK, "crazy8", options={"players": 3, "seed": 5})["id"]
        bw.sit(self.p["Pebble"].id, tid)
        bw.sit(self.p["Coral"].id, tid)
        bw.resign(self.p["Pebble"].id, tid)                             # left: didn't finish
        names = ["Sandy", "Pebble", "Coral"]
        while bw.view(self.p["Sandy"].id, tid)["status"] == "playing":
            mover = names[bw.view(self.p["Sandy"].id, tid)["to_move"]]
            bw.move(self.p[mover].id, tid, bw.view(self.p[mover].id, tid)["legal"][0])
        v = bw.view(self.p["Sandy"].id, tid)
        winner = names[v["result"]["winner"]]
        loser = ({"Sandy", "Coral"} - {winner}).pop()
        self.assertIn("card-win", self.b.today(self.p[winner].id))
        self.assertIn("card-game", self.b.today(self.p[winner].id))
        self.assertIn("card-game", self.b.today(self.p[loser].id))     # joining in counts
        self.assertNotIn("card-win", self.b.today(self.p[loser].id))
        self.assertEqual(self.b.today(self.p["Pebble"].id), [])

    def test_gather_bell_answered(self):
        self.beach.join(self.p["Coral"].id, SANDCHAT)
        bell = self.beach.ring_bell(self.p["Coral"].id)
        self.assertEqual(self.b.today(self.p["Coral"].id), [])         # ringing alone isn't it
        self.beach.respond_bell(self.p["Drift"].id, bell["bell_id"], "come")
        self.assertEqual(self.b.today(self.p["Coral"].id), ["bell"])

    def test_world_events_only_for_vouched_joins(self):
        self.beach.add_zone("beachblox", "BeachBlox", "game")
        uid = self.vouch("Pebble")
        n = self.b.report_events("beachblox", [
            {"kind": "goal", "user_id": uid, "joined_as": "Pebble"},
            {"kind": "goal", "user_id": uid, "joined_as": "Sandy"},       # the wrong name for that join
            {"kind": "goal", "user_id": 12345, "joined_as": "Coral"},     # nobody the Beach knows
            {"kind": "fireworks", "user_id": uid, "joined_as": "Pebble"},
            "nonsense"])
        self.assertEqual(n, 1)
        self.assertEqual(self.b.today(self.p["Pebble"].id), ["goal"])
        self.assertEqual(self.b.today(self.p["Sandy"].id), [])
        self.assertEqual(self.b.today(self.p["Coral"].id), [])
        with self.assertRaises(BeachError):
            self.b.report_events(SANDCHAT, [])

    def test_first_castle_of_the_day_and_a_tall_one(self):
        self.beach.add_zone("beachblox", "BeachBlox", "game")
        u1, u2 = self.vouch("Pebble"), self.vouch("Coral")
        self.b.report_events("beachblox", [{"kind": "castle", "user_id": u2, "joined_as": "Coral"}])
        self.b.report_events("beachblox", [{"kind": "castle", "user_id": u1, "joined_as": "Pebble"},
                                           {"kind": "tall_castle", "user_id": u1, "joined_as": "Pebble"}])
        self.assertEqual(self.b.today(self.p["Coral"].id), ["castle", "first-castle"])
        self.assertEqual(sorted(self.b.today(self.p["Pebble"].id)), ["castle", "tall-castle"])

    def test_keeper_switches_badges_off(self):
        self.beach.update_settings({"badges_off": ["hello"]})
        self.beach.join(self.p["Coral"].id, SANDCHAT)
        self.beach.post(self.p["Coral"].id, SANDCHAT, "hi")
        self.assertEqual(self.b.today(self.p["Coral"].id), [])
        with self.assertRaises(BeachError):
            self.beach.update_settings({"badges_off": ["medal-of-honor"]})
        with self.assertRaises(BeachError):
            self.beach.update_settings({"badge_reset_hour": 24})
        # Switching one off hides it at once, even if someone already has it.
        self.beach.update_settings({"badges_off": []})
        self.beach.post(self.p["Coral"].id, SANDCHAT, "hi again")
        self.assertEqual(self.b.today(self.p["Coral"].id), ["hello"])
        self.beach.update_settings({"badges_off": ["hello"]})
        self.assertIsNone(self.b.shown(self.p["Coral"].id))

    def test_every_badge_has_short_words(self):
        for b, (w, why) in BADGES.items():
            self.assertLessEqual(len(w.split()), 3, b)
            self.assertTrue(why)


class ShowingTests(BadgeCase):
    def earn(self, name, *badges):
        for b in badges:
            self.b.award(self.p[name].id, b)
            self.clock.advance(1)

    def test_worn_by_default_the_most_special_and_chosen(self):
        pid = self.p["Pebble"].id
        self.earn("Pebble", "goal", "hello")                  # hello after a goal doesn't replace it
        self.assertEqual(self.b.worn(pid), "goal")
        self.b.wear(pid, "hello shell")                        # by its words...
        self.assertEqual(self.b.worn(pid), "hello")
        self.b.wear(pid, "goal")                               # ...or its id
        self.assertEqual(self.b.worn(pid), "goal")
        self.b.wear(pid, None)
        self.assertIsNone(self.b.worn(pid))
        self.earn("Pebble", "card-win")                        # wearing none stays your choice
        self.assertIsNone(self.b.worn(pid))
        self.b.wear(pid, "auto")
        self.assertEqual(self.b.worn(pid), "card-win")
        with self.assertRaises(BeachError):
            self.b.wear(pid, "bell")                           # not earned today

    def test_arrival_line(self):
        self.earn("Pebble", "goal")
        self.beach.join(self.p["Drift"].id, SANDCHAT)
        self.beach.join(self.p["Pebble"].id, SANDCHAT)
        self.beach.join(self.p["Coral"].id, SANDCHAT)
        lines = self.sandchat_lines()
        self.assertIn("Pebble arrives, wearing today's goal-scorer ribbon.", lines)
        self.assertIn("Coral joined", lines)                   # no badge: the plain line

    def test_shown_on_the_map_and_people_list(self):
        self.earn("Pebble", "goal")
        self.beach.join(self.p["Pebble"].id, SANDCHAT)
        self.beach.join(self.p["Coral"].id, SANDCHAT)
        who = {w["name"]: w["badge"] for w in self.beach.who_in(SANDCHAT)}
        self.assertEqual(who, {"Pebble": {"id": "goal", "words": "goal-scorer ribbon"}, "Coral": None})

    def test_agents_read_a_few_words(self):
        self.earn("Pebble", "goal")
        self.earn("Sandy", "hello", "checkers")
        for n in ("Pebble", "Sandy", "Coral"):
            self.beach.join(self.p[n].id, SANDCHAT)
        text = state_text(self.beach, self.p["Sandy"].id)
        self.assertIn("Pebble (agent, wearing goal-scorer ribbon)", text)
        self.assertIn("Coral (person)", text)
        self.assertIn("your badges today: hello shell, checkers chip (wearing)", text)   # checkers outranks hello
        self.assertNotIn("<svg", text)
        self.assertNotIn("your badges", state_text(self.beach, self.p["Coral"].id))


class ResetTests(BadgeCase):
    def test_gone_after_the_reset_with_nothing_kept(self):
        self.beach.join(self.p["Coral"].id, SANDCHAT)
        self.beach.post(self.p["Coral"].id, SANDCHAT, "hi")
        self.b.wear(self.p["Coral"].id, "hello")
        self.clock.advance(20 * 60)                             # 03:50: still today
        self.beach.tick()
        self.assertEqual(self.b.today(self.p["Coral"].id), ["hello"])
        self.clock.advance(20 * 60)                             # 04:10: a new day
        self.assertEqual(self.b.today(self.p["Coral"].id), [])  # gone at once, even before upkeep
        self.assertIsNone(self.b.shown(self.p["Coral"].id))
        self.beach.tick()
        self.assertEqual(self.beach.db.one("SELECT COUNT(*) AS n FROM badges")["n"], 0)
        self.assertEqual(self.beach.db.one("SELECT COUNT(*) AS n FROM badge_worn")["n"], 0)
        self.beach.join(self.p["Coral"].id, SANDCHAT)            # (40 quiet minutes: upkeep moved Coral on)
        self.beach.post(self.p["Coral"].id, SANDCHAT, "morning")
        self.assertEqual(self.b.today(self.p["Coral"].id), [])    # the hello shell is for a first day only

    def test_the_hello_shell_is_for_a_first_day_only(self):
        # The keeper, 10-20: everyone said hello every day, so the shell meant nothing. Now it's a newcomer's.
        self.clock.advance(24 * 3600)                            # Coral's second day; Brine arrives on it
        newer, _ = self.beach.add_participant("Brine", "agent")
        for p in (self.p["Coral"], newer):
            self.beach.join(p.id, SANDCHAT)
            self.beach.post(p.id, SANDCHAT, "hello")
        self.assertEqual(self.b.today(self.p["Coral"].id), [])
        self.assertEqual(self.b.today(newer.id), ["hello"])

    def test_keeper_sets_the_reset_hour(self):
        self.beach.update_settings({"badge_reset_hour": 6})
        self.b.award(self.p["Coral"].id, "hello")
        self.clock.advance(3600)                                 # 04:30, before a 06:00 reset
        self.assertEqual(self.b.today(self.p["Coral"].id), ["hello"])
        self.clock.advance(2 * 3600)                             # 06:30
        self.assertEqual(self.b.today(self.p["Coral"].id), [])

    def test_first_castle_resets_too(self):
        self.beach.add_zone("beachblox", "BeachBlox", "game")
        u = self.vouch("Coral")
        self.b.report_events("beachblox", [{"kind": "castle", "user_id": u, "joined_as": "Coral"}])
        self.clock.advance(3600)
        self.beach.tick()
        u2 = self.vouch("Pebble")
        self.b.report_events("beachblox", [{"kind": "castle", "user_id": u2, "joined_as": "Pebble"}])
        self.assertIn("first-castle", self.b.today(self.p["Pebble"].id))


@unittest.skipUnless(HAVE_FASTAPI, "needs fastapi")
class BadgeApiTests(unittest.TestCase):
    def setUp(self):
        from beach.app import create_app
        self.dir = tempfile.mkdtemp(prefix="badges-api-")
        self.beach = Beach(self.dir, clock=FakeClock(BEFORE_RESET), rng=random.Random(1))
        self.admin = {"Authorization": f"Bearer {self.beach.ensure_admin()}"}
        self.http = TestClient(create_app(self.beach, upkeep_interval=None))
        self.h = {}
        for name, kind in (("Sandy", "agent"), ("Coral", "person")):
            tok = self.http.post("/claim", json={"code": self.http.post("/admin/participants", json={"name": name, "kind": kind}, headers=self.admin).json()["invite"]["code"]}).json()["token"]
            self.h[name] = {"Authorization": f"Bearer {tok}"}
        self.beach.add_zone("beachblox", "BeachBlox", "game")
        self.bridge = {"Authorization": f"Bearer {self.beach.bridge_token('beachblox')}"}

    def tearDown(self):
        self.beach.db.close()
        shutil.rmtree(self.dir, ignore_errors=True)

    def test_mine_wear_and_the_list(self):
        self.http.post("/zones/sandchat/join", headers=self.h["Coral"])
        self.http.post("/zones/sandchat/say", json={"text": "hello"}, headers=self.h["Coral"])
        r = self.http.get("/me/badges", headers=self.h["Coral"]).json()
        self.assertEqual((r["wearing"], r["today"][0]["words"]), ("hello", "hello shell"))
        self.assertEqual(self.http.put("/me/badges", json={"wear": None}, headers=self.h["Coral"]).json()["wearing"], None)
        self.assertEqual(self.http.put("/me/badges", json={"wear": "goal"}, headers=self.h["Coral"]).status_code, 400)
        self.assertEqual(len(self.http.get("/badges", headers=self.h["Sandy"]).json()["badges"]), len(BADGES))
        self.assertEqual(self.http.get("/admin/badges", headers=self.h["Sandy"]).status_code, 403)
        self.http.patch("/admin/settings", json={"badges_off": ["goal"]}, headers=self.admin)
        lst = self.http.get("/admin/badges", headers=self.admin).json()["badges"]
        self.assertEqual([b["on"] for b in lst if b["id"] == "goal"], [False])

    def test_map_shows_the_badge(self):
        self.http.post("/zones/sandchat/join", headers=self.h["Coral"])
        self.http.post("/zones/sandchat/say", json={"text": "hello"}, headers=self.h["Coral"])
        zones = self.http.get("/map", headers=self.h["Sandy"]).json()["zones"]
        who = [w for z in zones if z["id"] == "sandchat" for w in z["who"]]
        self.assertEqual(who[0]["badge"], {"id": "hello", "words": "hello shell"})

    def test_events_need_the_bridge_token(self):
        body = {"events": [{"kind": "goal", "user_id": 1, "joined_as": "Coral"}]}
        self.assertEqual(self.http.post("/zones/beachblox/events", json=body, headers=self.h["Coral"]).status_code, 403)
        r = self.http.post("/zones/beachblox/events", json=body, headers=self.bridge)
        self.assertEqual(r.json(), {"zone": "beachblox", "badges_given": 0})
        self.assertEqual(self.http.post("/zones/beachblox/events", json={"events": "x"}, headers=self.bridge).status_code, 400)


class BridgeEventTests(unittest.TestCase):
    """The bridge passes the world's badge events (rows in its DataStore) to the Beach, once each."""

    def setUp(self):
        self.dir = Path(tempfile.mkdtemp(prefix="bridge-events-"))
        self.db = self.dir / "local-8100.db"
        c = sqlite3.connect(self.db)
        c.execute("""CREATE TABLE data_stores (game_id TEXT NOT NULL, store_name TEXT NOT NULL, key TEXT NOT NULL,
                     value TEXT NOT NULL, created_at TEXT NOT NULL DEFAULT (datetime('now')),
                     updated_at TEXT NOT NULL DEFAULT (datetime('now')), PRIMARY KEY (game_id, store_name, key))""")
        c.execute("INSERT INTO data_stores (game_id, store_name, key, value) VALUES ('run1', 'BeachDoor', 'world', '{}')")
        c.commit()
        c.close()
        self.posted = []

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def world_writes(self, game_id, seq, kind, name="Pebble", uid=77):
        c = sqlite3.connect(self.db)
        c.execute("INSERT OR REPLACE INTO data_stores (game_id, store_name, key, value) VALUES (?, 'BeachDoor', ?, ?)",
                  (game_id, f"event:{seq % 64}", json.dumps({"seq": seq, "kind": kind, "user_id": uid, "joined_as": name})))
        c.commit()
        c.close()

    def bridge(self):
        from beach.bridge import Bridge, WorldStore

        def http(method, url, headers, body=None):
            self.posted.append((method, url, headers.get("Authorization"), body))
            return {}
        return Bridge("http://127.0.0.1:8100", "http://127.0.0.1:8765", "beachblox", "bt", lambda: None,
                      http=http, log=lambda m: None, store=WorldStore(self.db))

    def test_new_events_once_each_in_order(self):
        b = self.bridge()
        self.assertEqual(b.sync_events(), 0)
        self.world_writes("run1", 1, "castle")
        self.world_writes("run1", 2, "goal")
        self.assertEqual(b.sync_events(), 2)
        method, url, auth, body = self.posted[-1]
        self.assertEqual((method, url, auth), ("POST", "http://127.0.0.1:8765/zones/beachblox/events", "Bearer bt"))
        self.assertEqual([e["kind"] for e in body["events"]], ["castle", "goal"])
        self.assertEqual(body["events"][0], {"kind": "castle", "user_id": 77, "joined_as": "Pebble"})
        self.assertEqual(b.sync_events(), 0)                   # nothing new: nothing sent
        self.assertEqual(len(self.posted), 1)
        self.world_writes("run1", 66, "tall_castle")           # the ring wraps: key event:2 again
        self.assertEqual(b.sync_events(), 1)
        self.assertEqual(self.posted[-1][3]["events"][0]["kind"], "tall_castle")

    def test_a_new_world_run_starts_counting_again(self):
        b = self.bridge()
        self.world_writes("run1", 5, "goal")
        b.sync_events()
        c = sqlite3.connect(self.db)
        c.execute("INSERT INTO data_stores (game_id, store_name, key, value, updated_at) VALUES"
                  " ('run2', 'BeachDoor', 'world', '{}', '2999-01-01 00:00:00')")
        c.commit()
        c.close()
        self.world_writes("run2", 1, "castle")
        self.assertEqual(b.sync_events(), 1)
        self.assertEqual(self.posted[-1][3]["events"][0]["kind"], "castle")

    def test_world_scripts_report_goals_and_castles(self):
        lua = (ROOT / "worlds" / "beach" / "main.lua").read_text()
        for kind in ('"goal"', '"castle"', '"tall_castle"'):
            self.assertIn(f"beachEvent({kind}", lua)
        self.assertIn('GetDataStore("BeachDoor")', lua)
        self.assertNotIn("HttpService:", lua.split("beachEvent")[1][:2000])   # never the network


if __name__ == "__main__":
    unittest.main()
