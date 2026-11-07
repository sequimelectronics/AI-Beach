# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Becky Northaven and the AI-Beach contributors
"""Message items carry who wrote them by id (11-07, asked by a plugin author after a security review): a listener that
keeps its own log attributes lines by id, never by display name (names change; someone who left the room is no
longer in /here). Room messages, table chat and feed items carry author_id, author_kind and author_access."""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_play_leave import HAVE_FASTAPI  # noqa: E402

if HAVE_FASTAPI:
    import random
    import shutil
    import tempfile
    from fastapi.testclient import TestClient
    from beach.app import create_app
    from beach.core import BOARDWALK, SANDCHAT, Beach


@unittest.skipUnless(HAVE_FASTAPI, "needs fastapi")
class AuthorIdTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="authorids-")
        self.beach = Beach(self.dir, rng=random.Random(3))
        admin = {"Authorization": f"Bearer {self.beach.ensure_admin()}"}
        self.http = TestClient(create_app(self.beach, upkeep_interval=None))
        self.h = {}
        for name, kind in (("Sandy", "agent"), ("Coral", "person")):
            code = self.http.post("/admin/participants", json={"name": name, "kind": kind},
                                  headers=admin).json()["invite"]["code"]
            self.h[name] = {"Authorization": "Bearer " + self.http.post("/claim", json={"code": code}).json()["token"]}
        self.coral = self.beach.by_name("Coral")

    def tearDown(self):
        self.beach.db.close()
        shutil.rmtree(self.dir, ignore_errors=True)

    def check(self, item):
        self.assertEqual(item["author_id"], self.coral.id)
        self.assertEqual(item["author_kind"], "person")
        self.assertEqual(item["author_access"], "resident")

    def test_room_messages_and_feed_carry_the_author_by_id(self):
        for who in ("Sandy", "Coral"):
            self.http.post(f"/zones/{SANDCHAT}/join", headers=self.h[who])
        cur = self.http.get("/me/feed", headers=self.h["Sandy"]).json()["cursor"]
        self.http.post(f"/zones/{SANDCHAT}/say", json={"text": "hello doohicky"}, headers=self.h["Coral"])
        self.http.post(f"/zones/{SANDCHAT}/part", headers=self.h["Coral"])     # gone from /here: the id still says who
        msgs = self.http.get(f"/zones/{SANDCHAT}/messages", headers=self.h["Sandy"]).json()["messages"]
        self.check([m for m in msgs if m["kind"] == "say"][-1])
        feed = self.http.get(f"/me/feed?after={cur}", headers=self.h["Sandy"]).json()["items"]
        self.check([i for i in feed if i.get("kind") == "say"][-1])

    def test_table_chat_carries_the_author_by_id(self):
        tid = self.http.post(f"/zones/{BOARDWALK}/tables", json={"game": "checkers"}, headers=self.h["Coral"]).json()["id"]
        self.http.post(f"/tables/{tid}/sit", headers=self.h["Sandy"])
        self.http.post(f"/tables/{tid}/say", json={"text": "good luck"}, headers=self.h["Coral"])
        chat = self.http.get(f"/tables/{tid}/chat", headers=self.h["Sandy"]).json()["messages"]
        self.check([m for m in chat if m["kind"] == "say"][-1])


if __name__ == "__main__":
    unittest.main()
