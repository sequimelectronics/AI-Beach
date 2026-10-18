# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Becky Northaven and the AI-Beach contributors
"""One room at a time (keeper's decision 10-15, built 10-17): for a participant the keeper marks so,
going somewhere leaves where they were, a seated game waits, and their cards say so. Everyone else
can be in several places at once, as before."""

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.dirname(__file__))

from beach.agent import beach_card  # noqa: E402
from beach.core import BOARDWALK, SANDCHAT, BeachError  # noqa: E402
from test_play_leave import HAVE_FASTAPI, Case  # noqa: E402

if HAVE_FASTAPI:
    from fastapi.testclient import TestClient
    from beach.app import create_app


class OneRoomTests(Case):
    def test_already_here_means_several_rooms(self):
        # Migrated or added the old way: nothing changes for anyone already at the Beach.
        self.assertFalse(self.beach.one_room(self.sandy.id))
        self.beach.join(self.sandy.id, SANDCHAT)
        self.beach.join(self.sandy.id, BOARDWALK)
        self.assertEqual(sorted(self.beach.zones_of(self.sandy.id)), [BOARDWALK, SANDCHAT])
        self.assertIn("several at once is fine", beach_card(self.beach, self.sandy.id))

    def test_going_somewhere_leaves_where_you_were(self):
        self.beach.update_participant(self.sandy.id, one_room=True)
        self.beach.join(self.sandy.id, SANDCHAT)
        r = self.beach.join(self.sandy.id, BOARDWALK)
        self.assertEqual(self.beach.zones_of(self.sandy.id), [BOARDWALK])
        self.assertEqual(r["left"], ["SandChat"])
        self.assertEqual(self.beach.join(self.sandy.id, BOARDWALK)["already_here"], True)   # no-op, no tidy

    def test_a_seated_game_waits_and_answering_an_invite_moves_you(self):
        bw = self.beach.tables
        self.beach.update_participant(self.sandy.id, one_room=True)
        self.beach.join(self.sandy.id, SANDCHAT)
        tid = bw.open(self.coral.id, BOARDWALK, "checkers")["id"]
        bw.invite(self.coral.id, tid, "Sandy")                  # a private note reaches them anywhere
        bw.respond(self.sandy.id, tid, "come")                  # answering moves them to the table
        self.assertEqual(self.beach.zones_of(self.sandy.id), [BOARDWALK])
        bw.move(self.coral.id, tid, "c3-d4")
        self.beach.join(self.sandy.id, SANDCHAT)                # off to chat mid-game
        self.assertEqual(self.beach.zones_of(self.sandy.id), [SANDCHAT])
        self.assertEqual(bw.table(tid)["status"], "playing")    # the game waits; leaving never forfeits
        bw.move(self.sandy.id, tid, bw.view(self.sandy.id, tid)["legal"][0])   # and moving brings them back
        self.assertEqual(self.beach.zones_of(self.sandy.id), [BOARDWALK])

    def test_a_world_counts_as_a_room(self):
        self.beach.update_participant(self.sandy.id, one_room=True)
        self.beach.join(self.sandy.id, SANDCHAT)
        self.play(self.sandy)
        self.assertEqual(self.beach.zones_of(self.sandy.id), [])
        self.assertTrue(self.beach._current_join(self.sandy.id, "beachblox"))
        self.beach.join(self.sandy.id, SANDCHAT)                # back to chat: the character leaves the world
        self.assertFalse(self.beach._current_join(self.sandy.id, "beachblox"))
        self.beach.watch_world(self.sandy.id, "beachblox")
        self.assertEqual(self.beach.zones_of(self.sandy.id), [])
        self.beach.watch_world(self.sandy.id, "beachblox")      # a watch refresh tidies nothing more
        self.beach.join(self.sandy.id, BOARDWALK)
        self.assertFalse(self.beach.watching(self.sandy.id, "beachblox"))

    def test_the_card_says_so(self):
        self.beach.update_participant(self.sandy.id, one_room=True)
        card = beach_card(self.beach, self.sandy.id)
        self.assertIn("one room at a time", card)
        self.assertIn("a game you're seated at waits for you", card)
        self.assertIn("Talk where you are", card)
        self.assertNotIn("several at once", card)
        with self.assertRaises(BeachError):
            self.beach.update_participant(self.sandy.id, one_room="yes")


@unittest.skipUnless(HAVE_FASTAPI, "needs fastapi")
class OneRoomKeeperTests(Case):
    def setUp(self):
        super().setUp()
        self.http = TestClient(create_app(self.beach, upkeep_interval=None))
        self.admin = {"Authorization": f"Bearer {self.admin_tok}"}

    def test_new_invites_default_by_kind_and_the_keeper_can_change_it(self):
        now = self.beach.now()
        agent = self.http.post("/admin/visits", json={"name": "Kelp", "kind": "agent", "starts_at": now,
                                                      "ends_at": now + 3600}, headers=self.admin).json()
        person = self.http.post("/admin/participants", json={"name": "Drift", "kind": "person"}, headers=self.admin).json()
        chosen = self.http.post("/admin/participants", json={"name": "Tide", "kind": "agent", "one_room": False},
                                headers=self.admin).json()
        ids = {n: self.beach.by_name(n).id for n in ("Kelp", "Drift", "Tide")}
        self.assertTrue(agent and person and chosen)
        self.assertEqual({n: self.beach.one_room(i) for n, i in ids.items()}, {"Kelp": True, "Drift": False, "Tide": False})
        r = self.http.patch(f"/admin/participants/{ids['Drift']}", json={"one_room": True}, headers=self.admin)
        self.assertEqual(r.json()["one_room"], True)
        self.assertEqual(self.http.get(f"/admin/participants/{ids['Drift']}", headers=self.admin).json()["one_room"], True)
        self.assertEqual(self.http.patch(f"/admin/participants/{ids['Drift']}", json={"one_room": "yes"},
                                         headers=self.admin).status_code, 400)


if __name__ == "__main__":
    unittest.main()
