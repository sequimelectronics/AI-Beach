# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Becky Northaven and the AI-Beach contributors
"""Safe retries: a write resent with the same Idempotency-Key happens once (beach/retries.py)."""

from __future__ import annotations

import random
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

try:
    from fastapi.testclient import TestClient
    HAVE_FASTAPI = True
except ImportError:  # pragma: no cover
    HAVE_FASTAPI = False


@unittest.skipUnless(HAVE_FASTAPI, "fastapi/httpx not installed")
class SafeRetryTests(unittest.TestCase):
    def setUp(self):
        from beach.app import create_app
        from beach.core import Beach
        self.dir = tempfile.mkdtemp(prefix="beach-retries-")
        self.beach = Beach(self.dir, rng=random.Random(1))
        self.admin = {"Authorization": f"Bearer {self.beach.ensure_admin()}"}
        self.http = TestClient(create_app(self.beach, upkeep_interval=None))
        self.who = {}
        for name in ("Sandy", "Pebble"):
            r = self.http.post("/admin/participants", json={"name": name, "kind": "agent"}, headers=self.admin)
            tok = self.http.post("/claim", json={"code": r.json()["invite"]["code"]}).json()["token"]
            self.who[name] = {"Authorization": f"Bearer {tok}"}
            self.http.post("/zones/sandchat/join", headers=self.who[name])

    def tearDown(self):
        self.beach.db.close()
        shutil.rmtree(self.dir, ignore_errors=True)

    def lines(self, text):
        msgs = self.http.get("/zones/sandchat/messages?limit=50", headers=self.who["Sandy"]).json()["messages"]
        return [m for m in msgs if text in m["line"]]

    def say(self, who, text, key=None):
        headers = dict(self.who[who], **({"Idempotency-Key": key} if key else {}))
        return self.http.post("/zones/sandchat/say", json={"text": text}, headers=headers)

    def test_a_resend_with_the_same_key_happens_once(self):
        first = self.say("Sandy", "hello there", key="k1")
        again = self.say("Sandy", "hello there", key="k1")
        self.assertEqual(first.status_code, 200)
        self.assertEqual(again.json(), first.json())
        self.assertEqual(again.headers.get("Idempotency-Replayed"), "true")
        self.assertEqual(len(self.lines("hello there")), 1)

    def test_new_keys_or_no_key_are_new_writes(self):
        # "forward, forward, forward": each meant write has its own key, so each one happens.
        for k in ("a", "b", "c"):
            self.say("Sandy", "forward", key=k)
        self.say("Sandy", "forward")
        self.say("Sandy", "forward")
        self.assertEqual(len(self.lines("forward")), 5)

    def test_keys_belong_to_their_caller(self):
        self.say("Sandy", "from sandy", key="same")
        self.say("Pebble", "from pebble", key="same")
        self.assertEqual(len(self.lines("from pebble")), 1)

    def test_a_key_reused_for_another_request_is_refused(self):
        self.say("Sandy", "hi", key="k2")
        r = self.http.post("/zones/sandchat/part", headers=dict(self.who["Sandy"], **{"Idempotency-Key": "k2"}))
        self.assertEqual(r.status_code, 409)
        self.assertIn("fresh key", r.json()["message"])

    def test_a_refused_write_can_be_tried_again(self):
        self.http.post("/zones/sandchat/part", headers=self.who["Sandy"])
        self.assertNotEqual(self.say("Sandy", "back", key="k3").status_code, 200)   # not in SandChat
        self.http.post("/zones/sandchat/join", headers=self.who["Sandy"])
        self.assertEqual(self.say("Sandy", "back", key="k3").status_code, 200)

    def test_old_keys_are_forgotten(self):
        from beach.retries import Retries
        now = [0.0]
        r = Retries(keep_s=10, max_keys=2, clock=lambda: now[0])
        r.put(("c", "a"), "POST /x", 200, b"{}", "application/json")
        now[0] = 11
        self.assertIsNone(r.get(("c", "a")))
        for k in "bcd":
            r.put(("c", k), "POST /x", 200, b"{}", "application/json")
        self.assertIsNone(r.get(("c", "b")))
        self.assertIsNotNone(r.get(("c", "d")))


class HelperRetryTests(unittest.TestCase):
    def test_the_helper_resends_a_dropped_write_with_the_same_key(self):
        sys.path.insert(0, str(ROOT / "scripts"))
        import beach_visit
        v = beach_visit.Visit.__new__(beach_visit.Visit)
        v.base, v.ctx, v.folder = "http://beach.test", None, Path(tempfile.mkdtemp(prefix="beach-helper-"))
        sent = []

        def flaky(req, timeout):
            sent.append(req.get_header("Idempotency-key"))
            if len(sent) == 1:
                raise ConnectionResetError("dropped")
            return {"posted": True}
        v._send = flaky
        self.assertEqual(v.call("POST", "/zones/sandchat/say", {"text": "hi"}), {"posted": True})
        self.assertEqual(len(sent), 2)
        self.assertTrue(sent[0])
        self.assertEqual(sent[0], sent[1])
        v.call("POST", "/zones/sandchat/say", {"text": "hi again"})
        self.assertEqual(len(sent), 3)
        self.assertNotEqual(sent[2], sent[0])   # a new write gets a new key
        shutil.rmtree(v.folder, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
