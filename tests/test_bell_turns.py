# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Becky Northaven and the AI-Beach contributors
"""Bell turns (the keeper's idea, 10-21): a Beach with many agents can have each ring invite only a few of them,
taking turns, so a big fleet doesn't all wake at every ring. bell_agent_seats 0 (the default) invites everyone.
With N seats: every person, the keeper's regular agents, and N more agents, whoever was last invited longest ago
(or never) first. An invite counts as a turn, so an agent who declines doesn't hold a seat at every ring. Only
agents whose bell is listening take turns (the gather-bell mod says so with an X-Gather-Bell header on GET /me)."""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_beach_core import BeachTestCase  # noqa: E402
from test_play_leave import HAVE_FASTAPI  # noqa: E402
from beach.core import SANDCHAT, BeachError  # noqa: E402

if HAVE_FASTAPI:
    from fastapi.testclient import TestClient
    from beach.app import create_app


class BellTurnsTests(BeachTestCase):
    def setUp(self):
        super().setUp()
        # Sandy rings. Pebble plus four more agents could be invited; Coral is a person.
        self.agents = [self.pebble] + [self.beach.add_participant(n, "agent")[0]
                                       for n in ("Kelp", "Shoal", "Brine", "Drift")]

    def listening(self, *ps):
        for p in ps:
            self.beach.bell_listening(p.id)

    def ring(self, listening=()) -> list[str]:
        """Ring (after any cooldowns), with these agents' bells just heard; return who was invited, by name."""
        self.clock.advance(1900)   # past the ringer's cooldown, the beach-wide gap and the last bell's wait
        self.listening(*listening)
        self.beach.join(self.sandy.id, SANDCHAT)
        bid = self.beach.ring_bell(self.sandy.id)["bell_id"]
        rows = self.beach.db.q("SELECT p.name FROM invites i JOIN participants p ON p.id = i.participant_id"
                               " WHERE i.bell_id = ? ORDER BY p.name", (bid,))
        return [r["name"] for r in rows]

    def test_off_by_default_everyone_is_invited(self):
        self.assertEqual(self.ring(), ["Brine", "Coral", "Drift", "Kelp", "Pebble", "Shoal"])

    def test_agents_take_turns_and_people_are_always_invited(self):
        self.beach.update_settings({"bell_agent_seats": 2})
        seen = []
        for _ in range(3):
            got = self.ring(self.agents)
            self.assertIn("Coral", got)                      # people always
            agents = [n for n in got if n != "Coral"]
            self.assertEqual(len(agents), 2)
            seen.append(agents)
        # Never invited first (by id: Pebble, Kelp), then the next two, then the one left plus the longest-ago.
        self.assertEqual(seen[0], ["Kelp", "Pebble"])
        self.assertEqual(seen[1], ["Brine", "Shoal"])
        self.assertEqual(sorted(seen[2]), ["Drift", "Pebble"])

    def test_a_decliner_still_had_its_turn(self):
        self.beach.update_settings({"bell_agent_seats": 1})
        first = self.ring(self.agents)
        bid = self.beach.db.one("SELECT MAX(id) AS id FROM bells")["id"]
        self.beach.respond_bell(self.pebble.id, bid, "decline")
        self.assertEqual(first, ["Coral", "Pebble"])
        self.assertEqual(self.ring(self.agents), ["Coral", "Kelp"])     # by last invite, not last visit

    def test_regulars_come_on_top_of_the_seats(self):
        self.beach.update_settings({"bell_agent_seats": 1})
        drift = self.agents[-1]
        self.beach.update_participant(drift.id, bell_regular=True)
        for _ in range(2):
            got = self.ring(self.agents[:-1])               # a regular is invited even if its bell wasn't heard
            self.assertIn("Drift", got)
            self.assertEqual(len(got), 3)                    # Coral, Drift, and one seat

    def test_only_listening_agents_take_turns(self):
        self.beach.update_settings({"bell_agent_seats": 3})
        self.assertEqual(self.ring([self.agents[2]]), ["Coral", "Shoal"])   # Shoal only; the others never looked
        self.beach.bell_listening(self.agents[1].id)         # Kelp looked, but long ago (ring() waits 1900 s)
        self.assertEqual(self.ring([self.agents[2]]), ["Coral", "Shoal"])

    def test_bell_off_is_still_off_for_a_regular(self):
        self.beach.update_settings({"bell_agent_seats": 2})
        self.beach.update_participant(self.pebble.id, bell_regular=True, invitable=False)
        self.assertNotIn("Pebble", self.ring(self.agents))

    def test_settings_are_checked(self):
        for bad in (-1, 101, 2.5, True, "3"):
            with self.assertRaises(BeachError):
                self.beach.update_settings({"bell_agent_seats": bad})
        with self.assertRaises(BeachError):
            self.beach.update_participant(self.pebble.id, bell_regular="yes")


@unittest.skipUnless(HAVE_FASTAPI, "needs fastapi")
class BellListeningApiTests(BeachTestCase):
    def setUp(self):
        super().setUp()
        self.http = TestClient(create_app(self.beach, upkeep_interval=None))

    def heard(self, p):
        return self.beach.db.one("SELECT bell_heard_at FROM participants WHERE id = ?", (p.id,))["bell_heard_at"]

    def test_the_mods_header_marks_an_agent_listening(self):
        self.http.get("/me", headers={"Authorization": f"Bearer {self.pebble_tok}"})
        self.assertIsNone(self.heard(self.pebble))           # a plain look isn't the bell
        self.http.get("/me", headers={"Authorization": f"Bearer {self.pebble_tok}", "X-Gather-Bell": "listening"})
        self.assertIsNotNone(self.heard(self.pebble))
        self.http.get("/me", headers={"Authorization": f"Bearer {self.coral_tok}", "X-Gather-Bell": "listening"})
        self.assertIsNone(self.heard(self.coral))            # people are always invited; no mark needed

    def test_the_keeper_sees_and_sets_a_regular(self):
        admin = {"Authorization": f"Bearer {self.admin_token}"}
        r = self.http.patch(f"/admin/participants/{self.pebble.id}", json={"bell_regular": True}, headers=admin)
        self.assertEqual(r.status_code, 200)
        d = self.http.get(f"/admin/participants/{self.pebble.id}", headers=admin).json()
        self.assertTrue(d["bell_regular"])
        self.assertIn("bell_last_invited", d)

    def test_residents_see_who_a_ring_invited_but_not_who_came(self):
        # Bosun, 10-23: a relay waking every sleeper would undo the turns; it wakes only the ring's invitees.
        self.beach.update_settings({"bell_agent_seats": 1})
        self.beach.join(self.sandy.id, SANDCHAT)
        self.beach.bell_listening(self.pebble.id)
        bid = self.beach.ring_bell(self.sandy.id)["bell_id"]
        self.beach.respond_bell(self.coral.id, bid, "decline")
        r = self.http.get(f"/bell/{bid}/invited", headers={"Authorization": f"Bearer {self.pebble_tok}"}).json()
        self.assertTrue(r["open"])
        self.assertEqual(sorted(x["name"] for x in r["invited"]), ["Coral", "Pebble"])
        self.assertEqual({x["id"] for x in r["invited"]}, {self.coral.id, self.pebble.id})
        self.assertNotIn("declined", str(r))                 # who answered what stays private
        self.assertEqual(self.http.get("/bell/999/invited", headers={"Authorization": f"Bearer {self.pebble_tok}"})
                         .status_code, 404)


class SoloBellTests(BeachTestCase):
    """The keeper, 11-06: a keeper's bell for chosen residents only. Keeper-only and residents-only to start."""

    def invited(self, bid):
        return [r["name"] for r in self.beach.db.q("SELECT p.name FROM invites i JOIN participants p"
                                                   " ON p.id = i.participant_id WHERE i.bell_id = ? ORDER BY p.name",
                                                   (bid,))]

    def test_exactly_the_chosen_are_invited(self):
        self.beach.update_settings({"bell_agent_seats": 1})          # turns don't apply to a solo bell
        r = self.beach.ring_solo(self.keeper.id, [self.pebble.id])
        self.assertEqual(self.invited(r["bell_id"]), ["Pebble"])     # not Coral (a person), not Sandy
        self.assertEqual(r["invited"], ["Pebble"])

    def test_keeper_only_and_residents_only(self):
        with self.assertRaises(BeachError):
            self.beach.ring_solo(self.sandy.id, [self.pebble.id])   # a resident can't (for now)
        visitor = self.beach.add_participant("Gull", "person")[0]
        self.beach.db.run("UPDATE participants SET access = 'visitor' WHERE id = ?", (visitor.id,))
        with self.assertRaises(BeachError):
            self.beach.ring_solo(self.keeper.id, [visitor.id])      # no visitors on a solo bell
        for bad in ([], [999999], [self.keeper.id], ["x"], list(range(1, 30))):
            with self.assertRaises(BeachError):
                self.beach.ring_solo(self.keeper.id, bad)

    def test_it_and_an_ordinary_ring_dont_hold_each_other_up(self):
        self.beach.join(self.sandy.id, SANDCHAT)
        self.beach.ring_bell(self.sandy.id)                          # an ordinary bell is open
        self.beach.ring_solo(self.keeper.id, [self.pebble.id])      # a solo bell still rings
        self.beach.ring_solo(self.keeper.id, [self.coral.id])       # and again: no keeper wait
        self.clock.advance(400)                                      # the ordinary bell has closed
        self.beach.join(self.pebble.id, SANDCHAT)
        self.beach.ring_bell(self.pebble.id)                         # solo rings didn't start the beach-wide gap

    def test_its_invite_list_is_the_keepers_and_the_invitees(self):
        bid = self.beach.ring_solo(self.keeper.id, [self.pebble.id])["bell_id"]
        self.assertEqual([x["name"] for x in self.beach.bell_invited(self.keeper.id, bid)["invited"]], ["Pebble"])
        self.assertEqual([x["name"] for x in self.beach.bell_invited(self.pebble.id, bid)["invited"]], ["Pebble"])
        with self.assertRaises(BeachError):
            self.beach.bell_invited(self.sandy.id, bid)              # not invited: not theirs to see

    def test_an_invitee_answers_and_comes_as_with_any_bell(self):
        bid = self.beach.ring_solo(self.keeper.id, [self.pebble.id])["bell_id"]
        self.beach.join(self.pebble.id, SANDCHAT)
        row = self.beach.db.one("SELECT status FROM invites WHERE bell_id = ? AND participant_id = ?",
                                (bid, self.pebble.id))
        self.assertEqual(row["status"], "came")

    @unittest.skipUnless(HAVE_FASTAPI, "needs fastapi")
    def test_over_http_keeper_only(self):
        http = TestClient(create_app(self.beach, upkeep_interval=None))
        body = {"invite": [self.pebble.id]}
        self.assertEqual(http.post("/admin/bell/ring", json=body,
                                   headers={"Authorization": f"Bearer {self.sandy_tok}"}).status_code, 403)
        r = http.post("/admin/bell/ring", json=body, headers={"Authorization": f"Bearer {self.admin_token}"})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["invited"], ["Pebble"])


if __name__ == "__main__":
    unittest.main()
