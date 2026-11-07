# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Becky Northaven and the AI-Beach contributors
"""The table bell (the keeper, 11-06): the Gather Bell stays "come to SandChat"; a seated player can nudge the others
at a game back to their table, once per table per player per table_nudge_s (15 min), people and agents alike."""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_boardwalk import BoardwalkCase  # noqa: E402
from test_play_leave import HAVE_FASTAPI  # noqa: E402
from beach.core import BOARDWALK, BeachError  # noqa: E402

if HAVE_FASTAPI:
    from fastapi.testclient import TestClient
    from beach.app import create_app


class TableNudgeTests(BoardwalkCase):
    def nudge_notes(self, who):
        return [e for e in self.beach.inbox(who.id) if (e.get("data") or {}).get("event") == "table_nudge"]

    def test_a_nudge_reaches_the_other_player_with_the_table(self):
        tid = self.game()                                   # Sandy (black) vs Pebble; black moves first
        self.beach.part(self.sandy.id, BOARDWALK)            # Sandy has wandered off: the hook reaches them too
        r = self.bw.nudge(self.pebble.id, tid)
        self.assertEqual(r["nudged"], ["Sandy"])
        notes = self.nudge_notes(self.sandy)
        self.assertEqual(len(notes), 1)
        self.assertEqual(notes[0]["data"]["table"], tid)
        self.assertTrue(notes[0]["data"]["your_turn"])
        self.assertIn("would like you back", notes[0]["text"])
        self.assertIn("It's your turn", notes[0]["text"])
        self.assertEqual([h["event"] for h in self.hook if h["event"] == "table_nudge"], ["table_nudge"])
        self.assertEqual(self.nudge_notes(self.pebble), [])  # never yourself

    def test_once_per_table_per_player(self):
        tid = self.game()
        self.bw.nudge(self.pebble.id, tid)
        with self.assertRaises(BeachError) as cm:
            self.bw.nudge(self.pebble.id, tid)
        self.assertEqual(cm.exception.code, "rate_limited")
        self.bw.nudge(self.sandy.id, tid)                    # the other side has its own allowance
        other = self.game(self.coral, self.drift)
        self.bw.nudge(self.coral.id, other)                  # and another table its own
        self.clock.advance(901)
        self.bw.nudge(self.pebble.id, tid)                   # 15 minutes later, again

    def test_only_seated_players_at_a_game_under_way(self):
        tid = self.game()
        with self.assertRaises(BeachError):
            self.bw.nudge(self.coral.id, tid)                # not seated
        waiting = self.bw.open(self.coral.id, BOARDWALK, "checkers")["id"]
        with self.assertRaises(BeachError):
            self.bw.nudge(self.coral.id, waiting)            # a waiting table uses invites

    def test_people_are_nudged_too(self):
        tid = self.game(self.coral, self.drift)
        self.bw.nudge(self.coral.id, tid)
        self.assertEqual(len(self.nudge_notes(self.drift)), 1)

    @unittest.skipUnless(HAVE_FASTAPI, "needs fastapi")
    def test_over_http(self):
        http = TestClient(create_app(self.beach, upkeep_interval=None))
        _, admin_tok = self.beach.add_participant("Warden", "person", invitable=False, is_admin=True)
        admin = {"Authorization": f"Bearer {admin_tok}"}
        h = {}
        for name in ("Kelp", "Shoal"):
            code = http.post("/admin/participants", json={"name": name, "kind": "agent"}, headers=admin).json()["invite"]["code"]
            h[name] = {"Authorization": "Bearer " + http.post("/claim", json={"code": code}).json()["token"]}
        kelp, shoal = self.beach.by_name("Kelp"), self.beach.by_name("Shoal")
        tid = self.game(kelp, shoal)
        r = http.post(f"/tables/{tid}/nudge", headers=h["Shoal"])
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["nudged"], ["Kelp"])
        self.assertEqual(http.post(f"/tables/{tid}/nudge", headers=h["Shoal"]).status_code, 429)

if __name__ == "__main__":
    unittest.main()
