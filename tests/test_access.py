# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Becky Northaven and the AI-Beach contributors
"""Job 13: residents and visitors, invites that must be claimed, and the keeper's controls.

Against a temporary data directory with a fake clock, over the HTTP API (FastAPI's test client)
where it matters that old tokens stop working, and a stand-in game world (test_play_leave.py).
"""

from __future__ import annotations

import io
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from beach import agent  # noqa: E402
from beach.access import code_key, new_code  # noqa: E402
from beach.core import BOARDWALK, SANDCHAT, Beach, BeachError  # noqa: E402
from test_play_leave import HAVE_FASTAPI, Case  # noqa: E402

if HAVE_FASTAPI:
    from fastapi.testclient import TestClient
    from beach.app import create_app

HOUR = 3600


class AccessCase(Case):
    def setUp(self):
        super().setUp()
        if not HAVE_FASTAPI:
            self.skipTest("needs fastapi")
        self.http = TestClient(create_app(self.beach, upkeep_interval=None))
        self.admin = {"Authorization": f"Bearer {self.admin_tok}"}

    def h(self, tok):
        return {"Authorization": f"Bearer {tok}"}

    def visitor(self, name="Kelp", start=0, end=3 * HOUR, bell=False, kind="agent"):
        now = self.clock()
        r = self.http.post("/admin/visits", json={"name": name, "kind": kind, "starts_at": now + start,
                                                   "ends_at": now + end, "bell": bell}, headers=self.admin)
        self.assertEqual(r.status_code, 200, r.text)
        return r.json()

    def claim(self, code, label=None):
        return self.http.post("/claim", json={"code": code, **({"label": label} if label else {})})


class CodeTests(unittest.TestCase):
    def test_codes_are_easy_to_type_back(self):
        c = new_code()
        self.assertRegex(c, r"^[A-HJ-NP-Z2-9]{4}(-[A-HJ-NP-Z2-9]{4}){3}$")
        self.assertEqual(code_key(c), code_key(c.lower().replace("-", " ")))


class ResidentInviteTests(AccessCase):
    def test_add_makes_an_invite_not_a_working_link(self):
        r = self.http.post("/admin/participants", json={"name": "Drift", "kind": "person"}, headers=self.admin).json()
        self.assertNotIn("token", r)
        self.assertTrue(r["invite"]["link"].endswith("/#c=" + r["invite"]["code"]))
        listed = {p["name"]: p for p in self.http.get("/admin/participants", headers=self.admin).json()["participants"]}
        self.assertEqual((listed["Drift"]["status"], listed["Drift"]["access"]), ("invited", "resident"))
        got = self.claim(r["invite"]["code"], "tablet").json()
        self.assertEqual(self.http.get("/me", headers=self.h(got["token"])).json()["name"], "Drift")
        d = self.http.get(f"/admin/participants/{r['id']}", headers=self.admin).json()
        self.assertEqual([l["label"] for l in d["links"]], ["tablet"])            # the device's own link
        self.assertEqual(d["status"], "active")

    def test_a_claimed_invite_cant_be_claimed_again(self):
        r = self.http.post("/admin/participants", json={"name": "Drift", "kind": "agent"}, headers=self.admin).json()
        self.assertEqual(self.claim(r["invite"]["code"]).status_code, 200)
        again = self.claim(r["invite"]["code"])
        self.assertEqual(again.status_code, 409)
        self.assertIn("already been used", again.json()["message"])

    def test_an_unclaimed_invite_expires_and_can_be_re_sent(self):
        r = self.http.post("/admin/participants", json={"name": "Drift", "kind": "agent", "expires_in_s": 2 * HOUR},
                           headers=self.admin).json()
        self.clock.advance(2 * HOUR + 1)
        late = self.claim(r["invite"]["code"])
        self.assertEqual(late.status_code, 403)
        self.assertIn("expired", late.json()["message"])
        listed = {p["name"]: p for p in self.http.get("/admin/participants", headers=self.admin).json()["participants"]}
        self.assertEqual(listed["Drift"]["status"], "invite expired")
        again = self.http.post(f"/admin/participants/{r['id']}/token", json={"label": "first device"}, headers=self.admin).json()
        self.assertEqual(self.claim(again["invite"]["code"]).status_code, 200)

    def test_re_sending_withdraws_the_old_code(self):
        r = self.http.post("/admin/participants", json={"name": "Drift", "kind": "agent"}, headers=self.admin).json()
        self.http.post(f"/admin/participants/{r['id']}/token", json={}, headers=self.admin)
        self.assertEqual(self.claim(r["invite"]["code"]).status_code, 404)

    def test_wrong_codes(self):
        self.assertEqual(self.claim("AAAA-BBBB-CCCC-DDDD").status_code, 404)
        self.assertEqual(self.claim("").status_code, 404)

    def test_the_agent_gets_its_instructions_with_the_code(self):
        r = self.http.post("/admin/participants", json={"name": "Drift", "kind": "agent"}, headers=self.admin).json()
        card = r["invite"]["for_agent"]
        self.assertIn(f'POST http://testserver/claim {{"code": "{r["invite"]["code"]}"', card)
        self.assertIn("Authorization: Bearer <token>", card)
        door = self.http.get("/").text
        self.assertIn('POST /claim {"code": "<code>"', door)


class VisitorTests(AccessCase):
    def test_a_visitor_code_works_once_and_only_in_its_window(self):
        early = self.visitor("Kelp", start=HOUR, end=3 * HOUR)
        r = self.claim(early["invite"]["code"])
        self.assertEqual(r.status_code, 403)
        self.assertIn("hasn't started yet", r.json()["message"])
        self.clock.advance(HOUR)
        ok = self.claim(early["invite"]["code"])
        self.assertEqual(ok.status_code, 200)
        self.assertEqual(ok.json()["access"], "visitor")
        self.assertEqual(self.claim(early["invite"]["code"]).status_code, 409)       # once only
        late = self.visitor("Tide", start=0, end=HOUR)
        self.clock.advance(HOUR + 1)
        self.assertEqual(self.claim(late["invite"]["code"]).status_code, 403)       # after the window

    def test_the_window_ending_kills_every_credential(self):
        v = self.visitor("Kelp", end=2 * HOUR)
        tok = self.claim(v["invite"]["code"]).json()["token"]
        more = self.http.post(f"/admin/participants/{v['id']}/token", json={"label": "second"}, headers=self.admin).json()
        tok2 = self.claim(more["invite"]["code"]).json()["token"]                  # a second device in the visit
        spare = self.http.post(f"/admin/participants/{v['id']}/token", json={"label": "spare"}, headers=self.admin).json()
        self.assertEqual(self.http.post("/zones/sandchat/join", headers=self.h(tok)).status_code, 200)
        self.clock.advance(2 * HOUR)
        for t in (tok, tok2):
            self.assertEqual(self.http.get("/me", headers=self.h(t)).status_code, 401)   # at once, before any upkeep
        self.assertIn(self.claim(spare["invite"]["code"]).status_code, (403, 404))   # an unclaimed code is dead too
        self.assertNotIn(v["id"], [p.id for p in self.beach.present(SANDCHAT)])
        log = self.http.get("/admin/visits", headers=self.admin).json()["visits"][0]
        self.assertEqual((log["state"], log["end_reason"], log["zones"]), ("ended", "window", ["sandchat"]))
        # Even back inside the window, nothing comes back (a clock can't be argued with, but just in case).
        self.clock.advance(-HOUR)
        self.assertEqual(self.http.get("/me", headers=self.h(tok)).status_code, 401)

    def test_end_visit_kills_every_credential_and_removes_the_character(self):
        v = self.visitor("Kelp")
        tok = self.claim(v["invite"]["code"]).json()["token"]
        self.beach.play(v["id"], "beachblox", joiner=self.world.join, alive=self.world.alive)
        self.assertTrue(self.beach.playing(v["id"], "beachblox"))
        tid = self.http.post("/zones/boardwalk/tables", json={"game": "checkers"}, headers=self.h(tok)).json()["id"]
        r = self.http.post(f"/admin/visits/{v['visit']['id']}/end", headers=self.admin).json()
        self.assertEqual((r["state"], r["end_reason"]), ("ended", "keeper"))
        self.assertEqual(self.http.get("/me", headers=self.h(tok)).status_code, 401)
        self.assertEqual(self.http.post("/zones/sandchat/join", headers=self.h(tok)).status_code, 401)
        # The world's door is told the character must go; the Beach stops counting it at once.
        claims = [c for g in self.beach.door("beachblox")["grants"] for c in g["claims"] if c["name"] == "Kelp"]
        self.assertTrue(claims and all(c["left"] and c["revoked"] for c in claims))
        self.assertFalse(self.beach.playing(v["id"], "beachblox"))
        self.assertEqual(self.beach.zones_of(v["id"]), [])
        self.assertEqual(self.beach.tables.table(tid)["status"], "closed")       # their waiting table is given up
        self.assertEqual(sorted(r["zones"]), ["beachblox", "boardwalk"])

    def test_the_log_tells_here_now_apart_from_a_pass_still_open(self):
        # 10-17: "on now" read as "here now" when the visitor had left an hour before. The log keeps
        # where they went ("zones") and says where they are now ("here"), empty once they've left.
        v = self.visitor("Kelp")
        tok = self.claim(v["invite"]["code"]).json()["token"]
        self.http.post("/zones/sandchat/join", headers=self.h(tok))
        log = lambda: self.http.get("/admin/visits", headers=self.admin).json()["visits"][0]
        self.assertEqual((log()["state"], log()["here"]), ("on", ["SandChat"]))
        self.http.post("/zones/sandchat/part", headers=self.h(tok))
        self.assertEqual((log()["state"], log()["here"], log()["zones"]), ("on", [], ["sandchat"]))

    def test_a_visitor_sees_only_what_happens_while_there(self):
        self.beach.join(self.coral.id, SANDCHAT)
        self.beach.post(self.coral.id, SANDCHAT, "before the visit")
        v = self.visitor("Kelp")
        tok = self.claim(v["invite"]["code"]).json()["token"]
        self.http.post("/zones/sandchat/join", headers=self.h(tok))
        self.beach.post(self.coral.id, SANDCHAT, "hello, visitor")
        msgs = self.http.get("/zones/sandchat/messages?all_visits=true", headers=self.h(tok)).json()["messages"]
        texts = [m["text"] for m in msgs if m["kind"] == "say"]
        self.assertEqual(texts, ["hello, visitor"])

    def test_visitors_dont_ring_the_bell_unless_allowed(self):
        v = self.visitor("Kelp")
        tok = self.claim(v["invite"]["code"]).json()["token"]
        self.http.post("/zones/sandchat/join", headers=self.h(tok))
        r = self.http.post("/bell/ring", headers=self.h(tok))
        self.assertEqual(r.status_code, 403)
        self.assertNotIn("Gather Bell", agent.zone_card(self.beach, SANDCHAT, v["id"]))   # it lives on SandChat's card
        loud = self.visitor("Tide", bell=True)
        tok2 = self.claim(loud["invite"]["code"]).json()["token"]
        self.http.post("/zones/sandchat/join", headers=self.h(tok2))
        self.assertEqual(self.http.post("/bell/ring", headers=self.h(tok2)).status_code, 200)
        self.assertIn("Gather Bell", agent.zone_card(self.beach, SANDCHAT, loud["id"]))
        self.assertNotIn("Gather Bell", agent.beach_card(self.beach, loud["id"]))
        self.assertFalse(self.beach.participant(v["id"]).invitable)              # never woken by a ring either

    def test_the_visitor_card_says_when_it_ends(self):
        v = self.visitor("Kelp")
        card = agent.beach_card(self.beach, v["id"])
        self.assertIn("you're a visitor until", card)
        self.assertNotIn("rename yourself", card)
        tok = self.claim(v["invite"]["code"]).json()["token"]
        self.assertEqual(self.http.put("/me/name", json={"name": "Kelpie"}, headers=self.h(tok)).status_code, 403)

    def test_lookalike_names_are_refused_with_a_free_one_suggested(self):
        for name in ("Coral", "coral", "C0ral", "Corall"):
            r = self.http.post("/admin/visits", json={"name": name, "kind": "agent", "ends_at": self.clock() + HOUR},
                               headers=self.admin)
            self.assertEqual(r.status_code, 409, name)
            self.assertEqual(r.json()["suggestion"], name + " 2")                  # close to what the keeper typed
        free = r.json()["suggestion"]
        ok = self.http.post("/admin/visits", json={"name": free, "kind": "agent", "ends_at": self.clock() + HOUR},
                            headers=self.admin)
        self.assertEqual(ok.status_code, 200)
        self.assertEqual(self.http.post("/admin/participants", json={"name": "Sandy", "kind": "agent"},
                                        headers=self.admin).json()["suggestion"], "Sandy 2")

    def test_a_visitor_becomes_a_resident(self):
        v = self.visitor("Kelp", end=HOUR)
        tok = self.claim(v["invite"]["code"]).json()["token"]
        r = self.http.post(f"/admin/participants/{v['id']}/resident", headers=self.admin).json()
        self.assertEqual(r["access"], "resident")
        self.clock.advance(2 * HOUR)
        self.beach.tick()
        self.assertEqual(self.http.get("/me", headers=self.h(tok)).status_code, 200)   # the link lives on
        self.assertEqual(self.http.get("/admin/visits", headers=self.admin).json()["visits"][0]["end_reason"], "resident")

    def test_bad_windows(self):
        now = self.clock()
        for body in ({"ends_at": now - 1}, {"starts_at": now + HOUR, "ends_at": now + 30},
                     {"starts_at": now, "ends_at": now + 15 * 86400}, {"ends_at": "soon"}):
            r = self.http.post("/admin/visits", json={"name": "Kelp", "kind": "agent", **body}, headers=self.admin)
            self.assertEqual(r.status_code, 400, body)


class AgentVisitEndToEnd(AccessCase):
    def test_a_visit_as_an_agent_through_the_api_only(self):
        # The same visit as scripts/visit_e2e.py, with a fake clock: claim, card, SandChat, hello,
        # a move at a table; the window ends; every call is refused.
        sys.path.insert(0, str(ROOT / "scripts"))
        from visit_e2e import visit
        self.beach.join(self.sandy.id, SANDCHAT)
        r = visit(self.http, self.admin, self.h(self.sandy_tok), self.clock(), 1800, self.clock.advance)
        self.assertEqual([s["status"] for s in r["steps"]], [200] * 7, r["steps"])
        self.assertTrue(r["all_refused"], r["after_the_window"])
        self.assertEqual(set(r["after_the_window"].values()) - {401, 409}, set())
        self.assertIn("Kelp: Hello! Kelp here, visiting.", r["sandchat_seen_by_resident"])
        self.assertEqual((r["visit_log"]["end_reason"], r["visit_log"]["zones"]), ("window", ["sandchat", "boardwalk"]))


class KeeperControlTests(AccessCase):
    def test_kick_signs_out_everywhere_parts_and_removes_characters(self):
        b = self.beach
        tok2 = b.new_link(self.coral.id, "phone")["token"]
        b.join(self.coral.id, SANDCHAT)
        self.play(self.coral)
        r = self.http.post(f"/admin/participants/{self.coral.id}/kick", headers=self.admin).json()
        self.assertTrue(r["kicked"])
        for t in (self.coral_tok, tok2):
            self.assertEqual(self.http.get("/me", headers=self.h(t)).status_code, 401)
        self.assertEqual(b.zones_of(self.coral.id), [])
        self.assertFalse(b.playing(self.coral.id, "beachblox"))
        listed = [p["name"] for p in self.http.get("/admin/participants", headers=self.admin).json()["participants"]]
        self.assertIn("Coral", listed)                                         # still on the list
        back = self.http.post(f"/admin/participants/{self.coral.id}/token", json={}, headers=self.admin).json()
        self.assertEqual(self.claim(back["invite"]["code"]).status_code, 200)   # and can come back

    def test_remove(self):
        b = self.beach
        b.join(self.coral.id, SANDCHAT)
        b.join(self.sandy.id, SANDCHAT)
        b.post(self.coral.id, SANDCHAT, "see you all")
        r = self.http.delete(f"/admin/participants/{self.coral.id}", headers=self.admin).json()
        self.assertTrue(r["removed"])
        self.assertEqual(self.http.get("/me", headers=self.h(self.coral_tok)).status_code, 401)
        listed = [p["name"] for p in self.http.get("/admin/participants", headers=self.admin).json()["participants"]]
        self.assertNotIn("Coral", listed)
        msgs = self.http.get("/zones/sandchat/messages", headers=self.h(self.sandy_tok)).json()
        said = [m for m in msgs["messages"] if m["kind"] == "say"]
        self.assertEqual((said[0]["author"], said[0]["former"]), ("Coral", True))   # history keeps the name
        self.assertIn("Coral is a former participant", msgs["names"])
        # The name stays held for a day, then it's free.
        with self.assertRaises(BeachError):
            b.add_participant("Coral", "person")
        self.clock.advance(b.setting("rename_hint_s") + 1)
        b.add_participant("Coral", "person")                              # a new Coral...
        msgs = self.http.get("/zones/sandchat/messages", headers=self.h(self.sandy_tok)).json()["messages"]
        old = [m for m in msgs if m["kind"] == "say"][0]
        self.assertEqual((old["author"], old["former"]), ("Coral", True))     # ...and the old words are still the former's

    def test_the_keeper_cant_be_kicked_or_removed_from_the_web(self):
        keeper = next(p for p in self.beach.participants() if p["admin"])["id"]
        self.assertEqual(self.http.post(f"/admin/participants/{keeper}/kick", headers=self.admin).status_code, 403)
        self.assertEqual(self.http.delete(f"/admin/participants/{keeper}", headers=self.admin).status_code, 403)

    def test_the_admin_view(self):
        self.http.post("/zones/sandchat/join", headers=self.h(self.coral_tok))
        self.play(self.coral)
        d = self.http.get(f"/admin/participants/{self.coral.id}", headers=self.admin).json()
        self.assertEqual((d["kind"], d["access"], d["status"]), ("person", "resident", "active"))
        self.assertEqual(d["links"][0]["last_ip"], "testclient")                 # where the link was last used from
        self.assertEqual(d["where"]["zones"], [{"zone": "sandchat", "name": "SandChat"}])
        self.assertEqual(d["where"]["worlds"], [{"zone": "beachblox", "name": "BeachBlox", "as": "playing"}])


class SignOutTests(AccessCase):
    def test_sign_out_revokes_this_devices_link(self):
        phone = self.beach.new_link(self.coral.id, "phone")["token"]
        r = self.http.post("/me/sign-out", headers=self.h(self.coral_tok))
        self.assertEqual(r.status_code, 200)
        self.assertEqual(self.http.get("/me", headers=self.h(self.coral_tok)).status_code, 401)   # really out
        self.assertEqual(self.http.get("/me", headers=self.h(phone)).status_code, 200)           # the phone isn't
        js = (ROOT / "beach" / "web" / "common.js").read_text(encoding="utf-8")
        self.assertIn("await api('POST', '/me/sign-out')", js[js.index("async function signOut"):])


class KeeperDeviceTests(AccessCase):
    """Becky (10-20): keepers do a lot from their phones and tablets, so the keeper can invite another of their
    own devices from the keeper page. A keeper link is the keeper's whole key: the invite lasts an hour at most,
    and it's written to the audit log and told to the keeper, so one they didn't make stands out."""

    def test_a_keeper_device_invite_lasts_an_hour_and_is_recorded(self):
        keeper = next(p for p in self.beach.participants() if p["admin"])["id"]
        r = self.http.post(f"/admin/participants/{keeper}/token", json={"label": "phone", "expires_in_s": 7 * 86400},
                           headers=self.admin)
        self.assertEqual(r.status_code, 200, r.text)
        inv = r.json()["invite"]
        self.assertLessEqual(inv["expires_at"] - self.clock(), 3600)        # an hour, whatever was asked
        audit = self.http.get("/admin/audit", headers=self.admin).json()
        rows = audit.get("audit", audit) if isinstance(audit, dict) else audit
        self.assertTrue(any(a["what"] == "keeper_device_invite" and a["detail"] == "phone" for a in rows), rows)
        events = self.http.get("/me/events", headers=self.admin).json()
        self.assertIn("keeper sign-in invite", json.dumps(events))
        got = self.claim(inv["code"], "phone").json()                       # the phone gets its own keeper link
        self.assertEqual(self.http.get("/me", headers=self.h(got["token"])).json()["admin"], True)
        r = self.http.post(f"/admin/participants/{keeper}/token", json={"label": "tablet"}, headers=self.admin)
        self.clock.advance(3601)
        self.assertNotEqual(self.claim(r.json()["invite"]["code"]).status_code, 200)   # an hour later: no good

    def test_a_resident_invite_offers_the_outside_address_too(self):
        # A browser keeps its sign-in per address, so a phone used away from home must claim at the address that
        # reaches the Beach from outside: the visitor address.
        self.beach.update_settings({"link_base": "http://192.168.1.20:8765", "visitor_link_base": "https://beach.example"})
        r = self.http.post("/admin/participants", json={"name": "Drift", "kind": "person"}, headers=self.admin).json()
        self.assertTrue(r["invite"]["link"].startswith("http://192.168.1.20:8765/#c="))
        self.assertEqual(r["invite"]["link_outside"], "https://beach.example/#c=" + r["invite"]["code"])
        self.beach.update_settings({"visitor_link_base": None})
        r = self.http.post("/admin/participants", json={"name": "Shell", "kind": "person"}, headers=self.admin).json()
        self.assertNotIn("link_outside", r["invite"])


class RecoveryTests(AccessCase):
    def test_a_fresh_keeper_link_on_this_machine_only(self):
        from beach.__main__ import keeper_link
        b = self.beach
        keeper = next(p for p in b.participants() if p["admin"])["id"]
        b.revoke_token(keeper)                                       # the keeper signed out everywhere
        self.assertEqual(self.http.get("/me", headers=self.admin).status_code, 401)
        out, err = io.StringIO(), io.StringIO()
        data = Path(self.dir)
        self.assertEqual(keeper_link(data, out=out, err=err), 1)     # the saved link doesn't work...
        self.assertIn("keeper-link --new", err.getvalue())
        out = io.StringIO()
        self.assertEqual(keeper_link(data, new=True, out=out, err=err), 0)   # ...so make a fresh one, here
        token = out.getvalue().strip().split("#t=")[1]
        me = self.http.get("/me", headers=self.h(token)).json()
        self.assertTrue(me["admin"])
        self.assertEqual((data / "admin_token").read_text().strip(), token)

    def test_no_way_through_the_web(self):
        app = create_app(self.beach, upkeep_interval=None)
        paths = [getattr(r, "path", "") for r in app.routes]
        self.assertFalse([p for p in paths if "recover" in p or "keeper-link" in p])
        # A non-keeper can't make anyone a link, the keeper included.
        keeper = next(p for p in self.beach.participants() if p["admin"])["id"]
        r = self.http.post(f"/admin/participants/{keeper}/token", json={}, headers=self.h(self.coral_tok))
        self.assertEqual(r.status_code, 403)
        self.assertEqual(self.http.post("/claim", json={"code": "keeper"}).status_code, 404)


class VisitorAddressTests(AccessCase):
    """Visitors come from outside: their invites use the visitor address; residents keep the household one."""

    def settings(self, **kw):
        r = self.http.patch("/admin/settings", json=kw, headers=self.admin)
        self.assertEqual(r.status_code, 200, r.text)

    def test_visitor_invites_use_the_visitor_address_and_residents_dont(self):
        self.settings(link_base="http://192.168.1.20:8765", visitor_link_base="https://beach.example.org/")
        v = self.visitor()
        self.assertTrue(v["invite"]["link"].startswith("https://beach.example.org/#c="), v["invite"]["link"])
        self.assertIn("https://beach.example.org", v["invite"]["for_agent"])
        r = self.http.post("/admin/participants", json={"name": "Drift", "kind": "agent"}, headers=self.admin).json()
        self.assertTrue(r["invite"]["link"].startswith("http://192.168.1.20:8765/#c="), r["invite"]["link"])
        self.assertNotIn("beach.example.org", r["invite"]["for_agent"])

    def test_without_a_visitor_address_visitors_fall_back_to_the_household_one(self):
        self.settings(link_base="http://192.168.1.20:8765")
        self.assertTrue(self.visitor()["invite"]["link"].startswith("http://192.168.1.20:8765/#c="))

    def test_bad_values_are_refused(self):
        for bad in ({"visitor_link_base": "beach.example.org"}, {"trusted_proxy": "yes"}):
            self.assertEqual(self.http.patch("/admin/settings", json=bad, headers=self.admin).status_code, 400, bad)

    def last_ip(self, code, headers, client):
        http = TestClient(create_app(self.beach, upkeep_interval=None), client=client)
        tok = http.post("/claim", json={"code": code}, headers=headers).json()["token"]
        http.get("/me", headers={**headers, **self.h(tok)})
        return self.beach.db.one("SELECT last_ip FROM sign_ins ORDER BY id DESC LIMIT 1")["last_ip"]

    def test_visitors_get_the_worlds_visitor_viewer_and_residents_keep_the_household_one(self):
        r = self.http.patch("/admin/zones/beachblox", json={"visitor_viewer_url": "https://blox.example.org/"},
                            headers=self.admin)
        self.assertEqual(r.json()["visitor_viewer_url"], "https://blox.example.org/")
        tok = self.claim(self.visitor()["invite"]["code"]).json()["token"]
        vpid = self.http.get("/me", headers=self.h(tok)).json()["id"]
        self.assertEqual(self.beach.world_info("beachblox", vpid)["world"], "https://blox.example.org")
        self.assertEqual(self.beach.world_info("beachblox", self.sandy.id)["world"], "http://127.0.0.1:8100")
        link = self.beach.play(vpid, "beachblox", joiner=self.world.join, alive=self.world.alive)["viewer"]
        self.assertTrue(link.startswith("https://blox.example.org/"), link)
        self.assertTrue(self.play(self.sandy)["viewer"].startswith("http://127.0.0.1:8100/"))
        self.assertIn("watch: https://blox.example.org/", agent.zone_card(self.beach, "beachblox", vpid))
        self.assertIn("watch: http://127.0.0.1:8100/", agent.zone_card(self.beach, "beachblox", self.sandy.id))
        csp = self.http.get("/world?zone=beachblox").headers["content-security-policy"]
        self.assertIn("frame-src http://127.0.0.1:8100 https://blox.example.org", csp)

    def test_a_bad_visitor_viewer_is_refused_and_empty_clears_it(self):
        bad = self.http.patch("/admin/zones/beachblox", json={"visitor_viewer_url": "blox.example.org"}, headers=self.admin)
        self.assertEqual(bad.status_code, 400)
        self.http.patch("/admin/zones/beachblox", json={"visitor_viewer_url": "https://blox.example.org/"}, headers=self.admin)
        cleared = self.http.patch("/admin/zones/beachblox", json={"visitor_viewer_url": ""}, headers=self.admin)
        self.assertIsNone(cleared.json()["visitor_viewer_url"])

    def test_the_proxy_header_is_read_only_when_trusted_and_only_from_this_computer(self):
        fwd = {"X-Forwarded-For": "203.0.113.9, 10.0.0.1"}
        local, remote = ("127.0.0.1", 50000), ("192.168.1.30", 50000)
        self.assertEqual(self.last_ip(self.visitor("Kelp")["invite"]["code"], fwd, local), "127.0.0.1")   # off
        self.settings(trusted_proxy=True)
        self.assertEqual(self.last_ip(self.visitor("Wrack")["invite"]["code"], fwd, local), "203.0.113.9")
        self.assertEqual(self.last_ip(self.visitor("Tide")["invite"]["code"], fwd, remote), "192.168.1.30")

    def test_a_resident_coming_through_the_visitors_door_gets_the_outside_viewer(self):
        # The keeper, 10-24: her phone on cellular got the household address and couldn't watch.
        self.http.patch("/admin/zones/beachblox", json={"visitor_viewer_url": "https://blox.example.org/"},
                        headers=self.admin)
        fwd = {"X-Forwarded-For": "203.0.113.9"}
        sandy = self.h(self.sandy_tok)

        def world(client, headers):
            http = TestClient(create_app(self.beach, upkeep_interval=None), client=client)
            return http.get("/zones/beachblox/world", headers={**headers, **sandy}).json()["world"]

        local, lan = ("127.0.0.1", 50000), ("192.168.1.30", 50000)
        self.assertEqual(world(local, fwd), "http://127.0.0.1:8100")      # proxy not trusted: household
        self.settings(trusted_proxy=True)
        self.assertEqual(world(local, fwd), "https://blox.example.org")   # through the door: outside
        self.assertEqual(world(local, {}), "http://127.0.0.1:8100")       # on this computer, no proxy header
        self.assertEqual(world(lan, fwd), "http://127.0.0.1:8100")        # a LAN machine can't claim the door
        self.assertEqual(self.beach.world_info("beachblox", self.sandy.id)["world"], "http://127.0.0.1:8100")

    def test_on_a_real_server_only_the_keepers_setting_decides_about_the_proxy(self):
        # 10-24: the test client passed, but the live Beach still handed residents the household address. uvicorn
        # believed X-Forwarded-For from 127.0.0.1 by itself and rewrote the client before the Beach saw it, so
        # trusted_proxy never had a say. The Beach's servers run with SERVER_OPTS (proxy_headers off); check it
        # over a real socket, the way Caddy talks to it.
        import socket
        import threading
        import time
        import urllib.request

        import uvicorn

        from beach.__main__ import SERVER_OPTS
        self.assertIs(SERVER_OPTS["proxy_headers"], False)
        self.http.patch("/admin/zones/beachblox", json={"visitor_viewer_url": "https://blox.example.org/"},
                        headers=self.admin)
        s = socket.socket()
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
        s.close()
        server = uvicorn.Server(uvicorn.Config(create_app(self.beach, upkeep_interval=None), host="127.0.0.1",
                                               port=port, **SERVER_OPTS))
        threading.Thread(target=server.run, daemon=True).start()
        self.addCleanup(setattr, server, "should_exit", True)
        for _ in range(100):
            if server.started:
                break
            time.sleep(0.05)
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

        def world(headers):
            req = urllib.request.Request(f"http://127.0.0.1:{port}/zones/beachblox/world",
                                         headers={**headers, **self.h(self.sandy_tok)})
            return json.load(opener.open(req, timeout=10))["world"]

        fwd = {"X-Forwarded-For": "203.0.113.9"}
        self.assertEqual(world(fwd), "http://127.0.0.1:8100")             # setting off: the header means nothing
        self.assertEqual(self.beach.db.one("SELECT last_ip FROM sign_ins WHERE participant_id = ? ORDER BY "
                                           "last_used_at DESC LIMIT 1", (self.sandy.id,))["last_ip"], "127.0.0.1")
        self.settings(trusted_proxy=True)
        self.assertEqual(world(fwd), "https://blox.example.org")          # through the door: outside
        self.assertEqual(world({}), "http://127.0.0.1:8100")


if __name__ == "__main__":
    unittest.main()
