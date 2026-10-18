# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Becky Northaven and the AI-Beach contributors
"""Releasing a held name (from Pharos's invite, 10-17): removing a participant holds their name for a day so
nobody can pose as them; the keeper, and only the keeper, can end the hold early when it's the same person
coming back. Released holds are audited; old messages keep their former author."""

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.dirname(__file__))

from beach.core import SANDCHAT, BeachError  # noqa: E402
from test_play_leave import HAVE_FASTAPI, Case  # noqa: E402

if HAVE_FASTAPI:
    from fastapi.testclient import TestClient
    from beach.app import create_app


class ReleaseTests(Case):
    def keeper(self):
        return self.beach.participant(self.beach.db.one("SELECT id FROM participants WHERE is_admin = 1")["id"])

    def test_a_removed_name_is_held_until_the_keeper_releases_it(self):
        self.beach.join(self.sandy.id, SANDCHAT)
        self.beach.post(self.sandy.id, SANDCHAT, "hello from the first Sandy")
        self.beach.access.remove(self.sandy.id)
        self.assertEqual([h["name"] for h in self.beach.held_names()], ["Sandy"])
        with self.assertRaises(BeachError):
            self.beach.add_participant("Sandy", "agent")                    # held: nobody may take it
        with self.assertRaises(BeachError):
            self.beach.release_name(self.coral, "Sandy")                    # not the keeper
        r = self.beach.release_name(self.keeper(), "sandy")                 # any case
        self.assertEqual(r, {"released": "Sandy"})
        self.assertEqual(self.beach.held_names(), [])
        new, _ = self.beach.add_participant("Sandy", "agent")               # the same person, re-invited
        self.assertNotEqual(new.id, self.sandy.id)
        old = self.beach.db.one("SELECT author_id FROM messages WHERE text = 'hello from the first Sandy'")
        self.assertEqual(old["author_id"], self.sandy.id)                   # history keeps the former author
        audit = self.beach.db.one("SELECT what, detail FROM audit WHERE what = 'release_name'")
        self.assertEqual((audit["what"], audit["detail"]), ("release_name", "Sandy"))

    def test_only_held_names_can_be_released(self):
        with self.assertRaises(BeachError):
            self.beach.release_name(self.keeper(), "Nobody")


@unittest.skipUnless(HAVE_FASTAPI, "needs fastapi")
class ReleaseApiTests(Case):
    def test_keeper_only_over_http(self):
        http = TestClient(create_app(self.beach, upkeep_interval=None))
        admin = {"Authorization": f"Bearer {self.admin_tok}"}
        self.beach.access.remove(self.sandy.id)
        self.assertEqual([h["name"] for h in http.get("/admin/held-names", headers=admin).json()["held"]], ["Sandy"])
        coral = {"Authorization": f"Bearer {self.coral_tok}"}
        self.assertEqual(http.post("/admin/held-names/release", json={"name": "Sandy"}, headers=coral).status_code, 403)
        self.assertEqual(http.post("/admin/held-names/release", json={"name": "Sandy"}, headers=admin).json(),
                         {"released": "Sandy"})


if __name__ == "__main__":
    unittest.main()
