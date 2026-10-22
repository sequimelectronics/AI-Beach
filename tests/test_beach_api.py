# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Becky Northaven and the AI-Beach contributors
"""HTTP-level tests for the Beach door, plus the scripted three-participant scenario.

Skipped if FastAPI (and httpx, for its TestClient) isn't installed:
    pip install -r beach/requirements.txt
"""

from __future__ import annotations

import random
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

try:
    from fastapi.testclient import TestClient
    HAVE_FASTAPI = True
except ImportError:  # pragma: no cover
    HAVE_FASTAPI = False


@unittest.skipUnless(HAVE_FASTAPI, "fastapi/httpx not installed")
class ApiTests(unittest.TestCase):
    def setUp(self):
        from beach.app import create_app
        from beach.core import Beach
        self.dir = tempfile.mkdtemp(prefix="beach-api-")
        self.beach = Beach(self.dir, rng=random.Random(1))
        self.admin = {"Authorization": f"Bearer {self.beach.ensure_admin()}"}
        self.http = TestClient(create_app(self.beach, upkeep_interval=None))
        r = self.http.post("/admin/participants", json={"name": "Sandy", "kind": "agent"}, headers=self.admin)
        tok = self.http.post("/claim", json={"code": r.json()["invite"]["code"]}).json()["token"]
        self.sandy = {"Authorization": f"Bearer {tok}"}

    def tearDown(self):
        self.beach.db.close()
        shutil.rmtree(self.dir, ignore_errors=True)

    def test_health_is_open_everything_else_needs_a_token(self):
        self.assertEqual(self.http.get("/health").json(), {"ok": True})
        for method, path in (("GET", "/zones"), ("GET", "/me"), ("POST", "/zones/sandchat/join"),
                             ("GET", "/agent/turn"), ("GET", "/admin/settings")):
            self.assertEqual(self.http.request(method, path).status_code, 401, path)
        bad = {"Authorization": "Bearer nope"}
        self.assertEqual(self.http.get("/me", headers=bad).status_code, 401)

    def test_leave_is_another_name_for_part(self):
        # 10-22: the helper and the kit both say "leave"; a guessed /leave got a bare 404.
        self.http.post("/zones/sandchat/join", headers=self.sandy)
        self.assertEqual(self.http.post("/zones/sandchat/leave", headers=self.sandy).status_code, 200)
        here = self.http.get("/zones/sandchat/here", headers=self.sandy).json()["here"]
        self.assertEqual([p["name"] for p in here], [])

    def test_admin_only(self):
        for method, path, body in (("GET", "/admin/participants", None), ("PATCH", "/admin/settings", {}),
                                   ("POST", "/admin/participants", {"name": "Kelp", "kind": "agent"}),
                                   ("DELETE", "/admin/messages/1", None), ("GET", "/admin/audit", None)):
            self.assertEqual(self.http.request(method, path, json=body, headers=self.sandy).status_code, 403, path)

    def test_errors_carry_retry_after(self):
        self.http.post("/zones/sandchat/join", headers=self.sandy)
        self.http.post("/zones/sandchat/sky", json={"sky": "dawn"}, headers=self.sandy)
        r = self.http.post("/zones/sandchat/sky", json={"sky": "night"}, headers=self.sandy)
        self.assertEqual(r.status_code, 429)
        self.assertIn("Retry-After", r.headers)
        self.assertEqual(r.json()["error"], "cooldown")

    def test_settings_validate_the_hook(self):
        r = self.http.patch("/admin/settings", json={"notify_hook": {"url": "http://example.com/x"}}, headers=self.admin)
        self.assertEqual(r.status_code, 400)
        r = self.http.patch("/admin/settings", json={"notify_hook": {"url": "http://127.0.0.1:9/x"},
                                                     "beach_name": "Tide Pool"}, headers=self.admin)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["beach_name"], "Tide Pool")
        r = self.http.patch("/admin/settings", json={"no_such": 1}, headers=self.admin)
        self.assertEqual(r.status_code, 400)

    def test_revoke_token(self):
        pid = self.http.get("/admin/participants", headers=self.admin).json()["participants"][1]["id"]
        self.http.delete(f"/admin/participants/{pid}/token", headers=self.admin)
        self.assertEqual(self.http.get("/me", headers=self.sandy).status_code, 401)
        code = self.http.post(f"/admin/participants/{pid}/token", headers=self.admin).json()["invite"]["code"]
        new = self.http.post("/claim", json={"code": code}).json()["token"]
        self.assertEqual(self.http.get("/me", headers={"Authorization": f"Bearer {new}"}).json()["name"], "Sandy")

    def test_turn_bundle_endpoint(self):
        self.http.post("/zones/sandchat/join", headers=self.sandy)
        self.http.post("/zones/sandchat/say", json={"text": "hello"}, headers=self.sandy)
        b = self.http.get("/agent/turn", headers=self.sandy).json()
        self.assertEqual({k for k in b if k in ("tools", "state", "recent")}, {"tools", "state", "recent"})
        self.assertIn("Sandy: hello", b["recent"]["text"])
        self.assertGreater(b["total_tokens"], 0)


@unittest.skipUnless(HAVE_FASTAPI, "fastapi/httpx not installed")
class ScenarioTest(unittest.TestCase):
    def test_three_participant_scenario(self):
        import beach_core_scenario
        from beach.tokens import make_counter
        res = beach_core_scenario.run(make_counter(None))
        failed = [k for k, v in res["checks"].items() if not v]
        self.assertEqual(failed, [])
        self.assertFalse(res["data_dir_inside_repo"])


if __name__ == "__main__":
    unittest.main()
