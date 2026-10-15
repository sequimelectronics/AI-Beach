"""One name, everywhere (job 07): renames, look-alike names, history, and the front door to
game worlds (vouching, the bridge's door sync, presence by join, guests).

Against a temporary data directory with a fake clock. The world side (the BeachDoor Lua script
in a real Clawblox world) is exercised by scripts/identity_scenario.py; here the world's
DataStore is a stand-in SQLite file with Clawblox's table layout, and /spectate is faked.
"""

from __future__ import annotations

import json
import random
import shutil
import sqlite3
import sys
import tempfile
import unittest
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from beach import identity  # noqa: E402
from beach.agent import beach_card, recent_text, state_text, table_bundle  # noqa: E402
from beach.core import BOARDWALK, SANDCHAT, Beach, BeachError  # noqa: E402

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


class Case(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="identity-")
        self.clock = FakeClock()
        self.beach = Beach(self.dir, clock=self.clock, rng=random.Random(4))
        self.beach.ensure_admin()
        self.sandy, _ = self.beach.add_participant("Sandy", "agent")
        self.pebble, _ = self.beach.add_participant("Pebble", "agent")
        self.coral, _ = self.beach.add_participant("Coral", "person")

    def tearDown(self):
        self.beach.db.close()
        shutil.rmtree(self.dir, ignore_errors=True)

    def lines(self, zid, pid, table_id=None):
        return [m["text"] for m in self.beach.read(pid, zid, table_id=table_id)]


class NameRulesTests(Case):
    def test_look_alikes_are_refused(self):
        for bad in ("sandy", "SANDY", "S andy", "S_andy", "San.dy", "Sanndy", "Saandy", "Pebb1e", "PebbIe",
                    "C0ral", "Cora1", "Peb-ble"):
            with self.assertRaises(BeachError, msg=bad) as cm:
                self.beach.add_participant(bad, "agent")
            self.assertEqual(cm.exception.code, "conflict", bad)
        for ok in ("Sandi", "Pebbles", "Carol", "Drift", "Sandcastle Sam"):
            self.beach.add_participant(ok, "agent")

    def test_bad_shapes_are_refused(self):
        for bad in ("", "   ", "1Sandy", "Sandy!", "Sаndy", "x" * 25, "Sandy​"):   # Cyrillic а, zero-width
            with self.assertRaises(BeachError, msg=repr(bad)) as cm:
                self.beach.add_participant(bad, "agent")
            self.assertEqual(cm.exception.code, "invalid", repr(bad))

    def test_skeleton(self):
        self.assertEqual(identity.skeleton("Sandy"), identity.skeleton("5_A-n.n d Y"))
        self.assertNotEqual(identity.skeleton("Sandy"), identity.skeleton("Sandi"))
        self.assertEqual(identity.skeleton("Wave"), identity.skeleton("VVave"))
        self.assertEqual(identity.skeleton("Mira"), identity.skeleton("Rnira"))


class RenameTests(Case):
    def test_nick_line_everywhere_they_are(self):
        b = self.beach
        b.join(self.sandy.id, BOARDWALK)
        b.join(self.pebble.id, BOARDWALK)
        b.join(self.coral.id, SANDCHAT)
        tid = b.tables.open(self.sandy.id, BOARDWALK, "checkers")["id"]
        b.tables.sit(self.pebble.id, tid)
        r = b.rename(self.sandy.id, "Sandcastle Sam")
        self.assertEqual((r["name"], r["was"]), ("Sandcastle Sam", "Sandy"))
        line = "Sandy is now known as Sandcastle Sam"
        self.assertIn(line, self.lines(SANDCHAT, self.coral.id))     # SandChat, though Sandy isn't there
        self.assertIn(line, self.lines(BOARDWALK, self.pebble.id))    # the zone Sandy is in
        self.assertIn(line, self.lines(BOARDWALK, self.pebble.id, tid))  # and the table Sandy sits at
        # Everywhere from now on: people lists, table seats, results, the map.
        self.assertEqual(b.participant(self.sandy.id).name, "Sandcastle Sam")
        self.assertEqual([p.name for p in b.present(BOARDWALK)], ["Sandcastle Sam", "Pebble"])
        view = b.tables.view(self.pebble.id, tid)
        self.assertEqual(view["seats"][0]["player"]["name"], "Sandcastle Sam")
        bw = [z for z in b.zone_map() if z["id"] == BOARDWALK][0]
        self.assertEqual(bw["here"], 2)
        b.tables.resign(self.pebble.id, tid)
        self.assertIn("Sandcastle Sam and Pebble finished a game of checkers on The Boardwalk: Sandcastle Sam won",
                      " ".join(self.lines(SANDCHAT, self.coral.id)))

    def test_was_window_for_agents(self):
        b = self.beach
        b.join(self.sandy.id, SANDCHAT)
        b.join(self.pebble.id, SANDCHAT)
        b.rename(self.sandy.id, "Sandcastle Sam")
        self.assertEqual(b.label(self.sandy.id), "Sandcastle Sam (was Sandy)")
        self.assertIn("here: Sandcastle Sam (was Sandy) (agent), Pebble (agent)", state_text(b, self.pebble.id))
        self.clock.advance(b.setting("rename_hint_s") - 1)
        self.assertEqual(b.label(self.sandy.id), "Sandcastle Sam (was Sandy)")
        self.clock.advance(2)
        self.assertEqual(b.label(self.sandy.id), "Sandcastle Sam")
        self.assertIn("here: Sandcastle Sam (agent)", state_text(b, self.pebble.id))

    def test_was_window_at_a_table(self):
        b = self.beach
        tid = b.tables.open(self.sandy.id, BOARDWALK, "checkers")["id"]
        b.tables.sit(self.pebble.id, tid)
        b.rename(self.sandy.id, "Sandcastle Sam")
        st = table_bundle(b, self.pebble.id, tid)["state"]["text"]
        self.assertIn("you are White; Sandcastle Sam (was Sandy) is Black", st)

    def test_history_shows_names_as_they_were_and_a_legend(self):
        b = self.beach
        b.join(self.sandy.id, SANDCHAT)
        b.join(self.pebble.id, SANDCHAT)
        b.post(self.sandy.id, SANDCHAT, "hello from the old name")
        b.post(self.sandy.id, SANDCHAT, "/me waves")
        b.rename(self.sandy.id, "Sandcastle Sam")
        b.post(self.sandy.id, SANDCHAT, "and the new one")
        text = recent_text(b, self.pebble.id)
        self.assertIn("Sandy: hello from the old name", text)
        self.assertIn("* Sandy waves", text)
        self.assertIn("- Sandy is now known as Sandcastle Sam", text)
        self.assertIn("Sandcastle Sam: and the new one", text)
        self.assertTrue(text.endswith("names: Sandy is now Sandcastle Sam"))
        # Long after the "(was ...)" window, an old line is still explained.
        self.clock.advance(10 * 86400)
        msgs = b.read(self.pebble.id, SANDCHAT, all_visits=True)
        self.assertEqual(msgs[1]["author"], "Sandy")
        self.assertEqual(msgs[1]["author_now"], "Sandcastle Sam")

    def test_cooldown_and_keeper(self):
        b = self.beach
        b.rename(self.sandy.id, "Sandcastle Sam")      # first rename: free
        with self.assertRaises(BeachError) as cm:
            b.rename(self.sandy.id, "Sandbar")
        self.assertEqual(cm.exception.code, "cooldown")
        self.assertAlmostEqual(cm.exception.retry_after, 86400, delta=1)
        b.rename(self.sandy.id, "Sandbar", by_admin=True)   # the keeper can, any time
        b.rename(self.sandy.id, "Sandpiper")               # and a keeper rename starts no cooldown
        with self.assertRaises(BeachError):
            b.rename(self.sandy.id, "Sandal")
        self.clock.advance(86401)
        b.rename(self.sandy.id, "Sandal")
        b.update_settings({"rename_cooldown_s": 60})
        self.clock.advance(61)
        b.rename(self.sandy.id, "Sandy Two")

    def test_rename_validation(self):
        b = self.beach
        for bad in ("Pebble", "pebble", "Pebb1e", "", "!!", "Coral"):
            with self.assertRaises(BeachError, msg=bad):
                b.rename(self.sandy.id, bad)
        with self.assertRaises(BeachError):
            b.rename(self.sandy.id, "Sandy")               # already called that
        b.rename(self.sandy.id, "Sandcastle Sam")
        # The old name is reserved while "(was Sandy)" shows, so nobody else can take it.
        with self.assertRaises(BeachError) as cm:
            b.add_participant("Sandy", "person")
        self.assertIn("until recently", cm.exception.message)
        with self.assertRaises(BeachError):
            b.rename(self.pebble.id, "5andy", by_admin=True)
        self.clock.advance(b.setting("rename_hint_s") + 1)
        b.add_participant("Sandy", "person")               # free again later

    def test_beach_card_has_the_rename_line(self):
        card = beach_card(self.beach)
        self.assertIn('rename yourself: PUT /me/name {"name": "..."}', card)
        from beach.agent import zone_card
        for z in (SANDCHAT, BOARDWALK):
            self.assertNotIn("/me/name", zone_card(self.beach, z))


class DoorTests(Case):
    """The Beach side of the front door: vouching, what the bridge gets, presence by join."""

    def setUp(self):
        super().setUp()
        self.beach.add_zone("beachblox", "BeachBlox", "game", viewer_url="http://127.0.0.1:8100/")

    def test_vouch_binds_a_join_to_the_name_it_used(self):
        b = self.beach
        agent = str(uuid.uuid4())
        r = b.vouch(self.sandy.id, "beachblox", agent, "Sandy")
        self.assertEqual(r["user_id"], Beach.user_id_for(agent))
        with self.assertRaises(BeachError) as cm:
            b.vouch(self.sandy.id, "beachblox", agent, "SahndyRULZ")   # not your Beach name
        self.assertIn("join the world as Sandy", cm.exception.message)
        with self.assertRaises(BeachError):
            b.vouch(self.sandy.id, "beachblox", "not-an-id", "Sandy")
        with self.assertRaises(BeachError):
            b.vouch(self.sandy.id, SANDCHAT, agent, "Sandy")           # not a game zone

    def test_door_lists_claims_with_current_names(self):
        b = self.beach
        agent = str(uuid.uuid4())
        b.vouch(self.sandy.id, "beachblox", agent, "Sandy")
        # Pebble claims Sandy's join (Pebble saw its id while spectating): allowed, but harmless,
        # because the world honors only the claim whose name is the one the join used.
        b.vouch(self.pebble.id, "beachblox", agent, "Pebble")
        door = b.door("beachblox")
        self.assertFalse(door["guests"])
        g = door["grants"][0]
        self.assertEqual(g["user_id"], Beach.user_id_for(agent))
        self.assertEqual({(c["name"], c["joined_as"]) for c in g["claims"]}, {("Sandy", "Sandy"), ("Pebble", "Pebble")})
        b.rename(self.sandy.id, "Sandcastle Sam")
        claims = {c["joined_as"]: c for c in b.door("beachblox")["grants"][0]["claims"]}
        self.assertEqual(claims["Sandy"]["name"], "Sandcastle Sam")   # the label follows the rename
        b.revoke_token(self.sandy.id)
        claims = {c["joined_as"]: c for c in b.door("beachblox")["grants"][0]["claims"]}
        self.assertTrue(claims["Sandy"]["revoked"])

    def test_presence_by_join_and_guests(self):
        b = self.beach
        a1, a2 = str(uuid.uuid4()), str(uuid.uuid4())
        b.vouch(self.sandy.id, "beachblox", a1, "Sandy")
        b.vouch(self.pebble.id, "beachblox", a2, "Pebble")
        b.report_players("beachblox", [
            {"user_id": Beach.user_id_for(a1), "joined_as": "Sandy"},
            {"user_id": Beach.user_id_for(a2), "joined_as": "Sandy"},     # wrong name for that join: ignored
            {"guest": "Guest 1"}, "Sandy", "Visitor9"])
        who = {w["name"]: w for w in b.who_in("beachblox")}
        self.assertEqual(who["Sandy"]["id"], self.sandy.id)
        self.assertNotIn("Pebble", who)
        # Guests never wear a participant's name (or a look-alike of one).
        self.assertEqual(sorted(k for k in who if k.startswith("Guest")), ["Guest", "Guest 1", "Guest Visitor9"])
        b.rename(self.sandy.id, "Sandcastle Sam")
        self.assertIn("Sandcastle Sam", [w["name"] for w in b.who_in("beachblox")])
        looks = b.game_looks("beachblox")
        self.assertEqual(list(looks), ["Sandcastle Sam"])

    def test_world_info_and_play_for_people(self):
        b = self.beach
        info = b.world_info("beachblox", self.coral.id)
        self.assertEqual(info["name"], "Coral")
        with self.assertRaises(BeachError):
            b.play(self.coral.id, "beachblox")          # no bridge has connected the world yet
        b.set_world_url("beachblox", "http://192.168.1.5:8100")   # not this machine: ignored
        self.assertIsNone(b.zone("beachblox")["world_url"])
        b.set_world_url("beachblox", "http://127.0.0.1:8100/x")
        b.set_watch_token("beachblox", "spec-tok")
        agent = str(uuid.uuid4())
        joined = []
        r = b.play(self.coral.id, "beachblox", joiner=lambda url, name, key: joined.append((url, name, key)) or
                   {"session": "sess-1", "agent_id": agent})
        self.assertEqual(joined, [("http://127.0.0.1:8100", "Coral", None)])   # under the Beach name
        address, _, fragment = r["viewer"].partition("#")
        self.assertEqual(fragment, "session=sess-1&player=Coral")   # after '#': never sent to a server
        self.assertNotIn("sess-1", address)
        self.assertIn("spectator_token=spec-tok", address)
        self.assertEqual(b.door("beachblox")["grants"][0]["claims"][0]["joined_as"], "Coral")


class WorldStoreTests(unittest.TestCase):
    """The bridge writes the Beach's claims into the world's DataStore (Clawblox's SQLite layout)."""

    def setUp(self):
        self.dir = Path(tempfile.mkdtemp(prefix="worldstore-"))
        self.db = self.dir / "local-8100.db"
        c = sqlite3.connect(self.db)
        c.execute("""CREATE TABLE data_stores (game_id TEXT NOT NULL, store_name TEXT NOT NULL, key TEXT NOT NULL,
                     value TEXT NOT NULL, created_at TEXT NOT NULL DEFAULT (datetime('now')),
                     updated_at TEXT NOT NULL DEFAULT (datetime('now')), PRIMARY KEY (game_id, store_name, key))""")
        c.commit()
        c.close()

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def test_finds_the_run_and_writes_claims(self):
        from beach.bridge import WorldStore
        ws = WorldStore(self.db)
        self.assertIsNone(ws.game_id())                     # the world hasn't started its door
        c = sqlite3.connect(self.db)
        c.execute("INSERT INTO data_stores (game_id, store_name, key, value, updated_at) VALUES"
                  " ('old-run', 'BeachDoor', 'world', '{}', '2026-01-01 00:00:00'),"
                  " ('this-run', 'BeachDoor', 'world', '{}', '2026-10-14 10:00:00')")
        c.commit()
        c.close()
        self.assertEqual(ws.game_id(), "this-run")
        ws.write("this-run", {"grant:42": {"claims": [{"name": "Sandy", "joined_as": "Sandy", "revoked": False, "left": False}]}})
        ws.write("this-run", {"grant:42": {"claims": [{"name": "Sam", "joined_as": "Sandy", "revoked": False}]}})
        self.assertEqual(ws.read("this-run", "grant:42")["claims"][0]["name"], "Sam")


@unittest.skipUnless(HAVE_FASTAPI, "fastapi/httpx not installed")
class BridgeDoorTests(unittest.TestCase):
    """The bridge end to end with the Beach real (HTTP door), the world faked, the DataStore real."""

    def setUp(self):
        from beach.app import create_app
        self.dir = Path(tempfile.mkdtemp(prefix="bridge-door-"))
        self.clock = FakeClock()
        self.beach = Beach(self.dir / "beach", clock=self.clock, rng=random.Random(1))
        self.admin = {"Authorization": f"Bearer {self.beach.ensure_admin()}"}
        self.http = TestClient(create_app(self.beach, upkeep_interval=None))
        self.beach.add_zone("beachblox", "BeachBlox", "game", viewer_url="http://127.0.0.1:8100/")
        self.bridge_token = self.http.post("/admin/zones/beachblox/bridge-token", headers=self.admin).json()["token"]
        self.tok = {}
        for name in ("Sandy", "Pebble"):
            self.tok[name] = self.http.post("/admin/participants", json={"name": name, "kind": "agent"},
                                            headers=self.admin).json()["token"]
        self.beach.set_avatar(self.beach.by_name("Sandy").id, {"theme": "sunset", "hair": "teal"})
        self.world = self.dir / "world"
        (self.world / ".clawblox").mkdir(parents=True)
        c = sqlite3.connect(self.world / ".clawblox" / "local-8100.db")
        c.execute("""CREATE TABLE data_stores (game_id TEXT NOT NULL, store_name TEXT NOT NULL, key TEXT NOT NULL,
                     value TEXT NOT NULL, created_at TEXT NOT NULL DEFAULT (datetime('now')),
                     updated_at TEXT NOT NULL DEFAULT (datetime('now')), PRIMARY KEY (game_id, store_name, key))""")
        c.execute("INSERT INTO data_stores (game_id, store_name, key, value) VALUES ('run1', 'BeachDoor', 'world', '{}')")
        c.commit()
        c.close()
        self.players = []          # what the fake /spectate returns
        self.up = True

    def tearDown(self):
        self.beach.db.close()
        shutil.rmtree(self.dir, ignore_errors=True)

    def fake_http(self, method, url, headers, body=None):
        import urllib.error
        if url.startswith("http://127.0.0.1:8100"):
            if not self.up:
                raise urllib.error.URLError("refused")
            return {"players": self.players}
        path = url.split("http://127.0.0.1:8765", 1)[1]
        r = self.http.request(method, path, headers=headers, json=body)
        r.raise_for_status()
        return r.json()

    def bridge(self):
        from beach.bridge import Bridge
        return Bridge("http://127.0.0.1:8100", "http://127.0.0.1:8765", "beachblox", self.bridge_token,
                      lambda: "spec-tok", str(self.world), http=self.fake_http, log=lambda m: None)

    def grant(self, agent):
        from beach.bridge import WorldStore
        return WorldStore(self.world / ".clawblox" / "local-8100.db").read("run1", f"grant:{Beach.user_id_for(agent)}")

    def test_vouch_reaches_the_world_and_presence_follows_the_door(self):
        b = self.bridge()
        agent = str(uuid.uuid4())
        r = self.http.post("/zones/beachblox/vouch", json={"agent_id": agent, "name": "Sandy"},
                           headers={"Authorization": f"Bearer {self.tok['Sandy']}"})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(b.sync_door(), 1)
        self.assertEqual(self.grant(agent)["claims"], [{"name": "Sandy", "joined_as": "Sandy", "revoked": False, "left": False}])
        # The world's door admitted Sandy; an impostor "Sandy" is still waiting (then kicked).
        self.players = [{"id": agent, "name": "Sandy", "attributes": {"BeachDoor": "ok", "BeachName": "Sandy"}},
                        {"id": str(uuid.uuid4()), "name": "Sandy", "attributes": {"BeachDoor": "pending"}}]
        res = b.step()
        self.assertEqual(res["playing"], 1)
        z = self.http.get("/map", headers=self.admin).json()["zones"]
        bb = [x for x in z if x["id"] == "beachblox"][0]
        self.assertEqual([w["name"] for w in bb["who"]], ["Sandy"])
        tints = json.loads((self.world / "static" / "tints.json").read_text())["players"]
        self.assertEqual(list(tints), ["Sandy"])
        # A rename reaches the world's door (its label) at the next sync.
        self.http.put("/me/name", json={"name": "Sandcastle Sam"}, headers={"Authorization": f"Bearer {self.tok['Sandy']}"})
        b.sync_door()
        self.assertEqual(self.grant(agent)["claims"][0]["name"], "Sandcastle Sam")
        b.step()
        bb = [x for x in self.http.get("/map", headers=self.admin).json()["zones"] if x["id"] == "beachblox"][0]
        self.assertEqual([w["name"] for w in bb["who"]], ["Sandcastle Sam"])
        # The world also learned the address the Beach may join it at (for people), on this machine.
        self.assertEqual(self.beach.zone("beachblox")["world_url"], "http://127.0.0.1:8100")
        self.assertEqual(self.beach.zone("beachblox")["watch_token"], "spec-tok")

    def test_watchers_reach_the_world_and_a_removed_player_is_told(self):
        # Job 12. The world's idle limit comes from its world.toml.
        from beach.bridge import WorldStore
        (self.world / "world.toml").write_text('name = "Beach"\nafk_timeout = 300\n')
        b = self.bridge()
        ws = WorldStore(self.world / ".clawblox" / "local-8100.db")
        pebble = {"Authorization": f"Bearer {self.tok['Pebble']}"}
        self.http.post("/zones/beachblox/watch", headers=pebble)
        b.sync_door()
        self.assertEqual(ws.read("run1", "watchers"), {"names": ["Pebble"]})     # the chair shows Pebble
        self.http.delete("/zones/beachblox/watch", headers=pebble)
        b.sync_door()
        self.assertEqual(ws.read("run1", "watchers"), {"names": []})
        # Sandy plays, then the world drops Sandy (idle) while it keeps running: Sandy is told.
        agent = str(uuid.uuid4())
        sandy = {"Authorization": f"Bearer {self.tok['Sandy']}"}
        self.http.post("/zones/beachblox/vouch", json={"agent_id": agent, "name": "Sandy"}, headers=sandy)
        self.players = [{"id": agent, "name": "Sandy", "attributes": {"BeachDoor": "ok"}}]
        b.step()
        self.players = []
        b.step()
        ev = self.http.get("/me/events", headers=sandy).json()["events"]
        self.assertEqual([e["data"]["event"] for e in ev], ["world_removed"])
        self.assertIn("idle 5 minutes in BeachBlox", ev[0]["text"])
        # A world that stops answering, or restarts, drops nobody's character with a "you were idle".
        self.http.post("/zones/beachblox/vouch", json={"agent_id": str(uuid.uuid4()), "name": "Sandy"}, headers=sandy)
        self.up = False
        b.step()
        self.assertEqual(self.http.get("/me/events", headers=sandy).json()["events"], [])

    def test_guest_policy_reaches_the_world(self):
        from beach.bridge import WorldStore
        b = self.bridge()
        b.sync_door()
        ws = WorldStore(self.world / ".clawblox" / "local-8100.db")
        self.assertEqual(ws.read("run1", "policy"), {"guests": False})
        self.http.patch("/admin/settings", json={"game_guests": True}, headers=self.admin)
        b.sync_door()
        self.assertEqual(ws.read("run1", "policy"), {"guests": True})

    def test_only_the_bridge_reads_the_door(self):
        r = self.http.get("/zones/beachblox/door", headers={"Authorization": f"Bearer {self.tok['Pebble']}"})
        self.assertEqual(r.status_code, 403)
        r = self.http.get("/zones/beachblox/door", headers={"Authorization": f"Bearer {self.bridge_token}"})
        self.assertEqual(r.status_code, 200)

    def test_world_down_reports_nobody_and_reports_expire(self):
        b = self.bridge()
        agent = str(uuid.uuid4())
        self.beach.vouch(self.beach.by_name("Sandy").id, "beachblox", agent, "Sandy")
        self.players = [{"id": agent, "name": "Sandy", "attributes": {"BeachDoor": "ok"}}]
        b.step()
        self.up = False
        b.step()
        self.assertEqual(self.beach.who_in("beachblox"), [])
        self.up = True
        b.step()
        self.clock.advance(self.beach.setting("game_report_ttl_s") + 1)
        self.assertEqual(self.beach.who_in("beachblox"), [])

    def test_addresses_must_be_local(self):
        from beach.bridge import require_local, spectator_token_from_log
        self.assertEqual(require_local("http://127.0.0.1:8100/", "w"), "http://127.0.0.1:8100")
        for bad in ("http://192.168.1.5:8100", "http://example.com", "file:///etc/passwd"):
            with self.assertRaises(SystemExit):
                require_local(bad, "w")
        log = self.dir / "server.log"
        log.write_text("spectator_token=old\nspectator_token=abc-123_x\n")
        self.assertEqual(spectator_token_from_log(str(log)), "abc-123_x")

    def test_rename_over_http(self):
        h = {"Authorization": f"Bearer {self.tok['Pebble']}"}
        r = self.http.put("/me/name", json={"name": "Pebble Beach"}, headers=h)
        self.assertEqual(r.json()["was"], "Pebble")
        self.assertEqual(self.http.get("/me", headers=h).json()["was"], "Pebble")
        r = self.http.put("/me/name", json={"name": "Pebblet"}, headers=h)
        self.assertEqual(r.status_code, 429)
        r = self.http.put("/me/name", json={"name": "Sandy"}, headers={"Authorization": f"Bearer {self.tok['Sandy']}"})
        self.assertEqual(r.status_code, 400)       # already called that
        r = self.http.patch(f"/admin/participants/{self.beach.by_name('Sandy').id}", json={"name": "Pebb1e"},
                            headers=self.admin)
        self.assertEqual(r.status_code, 409)       # a look-alike of Pebble's old (reserved) name
        r = self.http.patch(f"/admin/participants/{self.beach.by_name('Sandy').id}", json={"name": "SANDY"},
                            headers=self.admin)
        self.assertEqual(r.json()["name"], "SANDY")   # your own name, re-cased: fine
        lst = self.http.get("/admin/participants", headers=self.admin).json()["participants"]
        self.assertNotIn("game_name", lst[0])


if __name__ == "__main__":
    unittest.main()
