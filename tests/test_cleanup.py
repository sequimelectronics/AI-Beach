"""Job 08 (closing open items): the session in the viewer link's fragment, the join key, Beach
names in the viewer and adapter, the keeper's card editor, several sign-in links per person, the
world+bridge launcher, Gather Bell retries, and opt-outs that catch plain names.

Against a temporary data directory with a fake clock. The real-world part of the join key (a
patched Clawblox refusing a direct join) is shown by scripts/join_key_live.py.
"""

from __future__ import annotations

import copy
import http.server
import json
import os
import random
import shutil
import signal
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time
import unittest
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from beach import front_door  # noqa: E402
from beach.core import BOARDWALK, SANDCHAT, Beach, BeachError  # noqa: E402
from beach.identity import names_in  # noqa: E402

try:
    from fastapi.testclient import TestClient
    HAVE_FASTAPI = True
except ImportError:  # pragma: no cover
    HAVE_FASTAPI = False

FIX = ROOT / "tests" / "fixtures" / "beach"


class FakeClock:
    def __init__(self, t: float = 1_800_000_000.0):
        self.t = t

    def __call__(self) -> float:
        return self.t

    def advance(self, s: float) -> None:
        self.t += s


class Case(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="cleanup-")
        self.clock = FakeClock()
        self.beach = Beach(self.dir, clock=self.clock, rng=random.Random(8))
        self.beach.ensure_admin()
        self.sandy, self.sandy_tok = self.beach.add_participant("Sandy", "agent")
        self.coral, self.coral_tok = self.beach.add_participant("Coral", "person")

    def tearDown(self):
        self.beach.db.close()
        shutil.rmtree(self.dir, ignore_errors=True)


# 1 ----------------------------------------------------------------------- the viewer link

class ViewerLinkTests(unittest.TestCase):
    def test_session_rides_after_the_hash(self):
        link = front_door.viewer_link("http://192.168.1.20:8100/?x=1#old", "spec", "sess-9", "Sandcastle Sam")
        address, _, fragment = link.partition("#")
        self.assertEqual(address, "http://192.168.1.20:8100/?spectator_token=spec")
        self.assertEqual(fragment, "session=sess-9&player=Sandcastle+Sam")
        self.assertNotIn("sess-9", address)

    def test_the_patch_reads_the_fragment_and_clears_it(self):
        patch = (ROOT / "patches" / "clawblox-viewer-session.patch").read_text()
        self.assertIn("window.location.hash", patch)
        self.assertIn("history.replaceState", patch)
        added = [ln for ln in patch.splitlines() if ln.startswith("+") and "location.search" in ln
                 and "get('session')" in ln]
        self.assertEqual(added, [])   # no longer read from the query string


# 2 ----------------------------------------------------------------------- the join key

class JoinKeyTests(Case):
    def setUp(self):
        super().setUp()
        self.beach.add_zone("beachblox", "BeachBlox", "game", viewer_url="http://127.0.0.1:8100/")
        self.beach.set_world_url("beachblox", "http://127.0.0.1:8100")

    def test_the_beach_joins_with_the_worlds_key(self):
        b = self.beach
        b.set_join_key("beachblox", "k3y")
        seen = []
        agent = str(uuid.uuid4())
        r = b.play(self.sandy.id, "beachblox",
                   joiner=lambda url, name, key: seen.append((url, name, key)) or {"session": "s1", "agent_id": agent})
        self.assertEqual(seen, [("http://127.0.0.1:8100", "Sandy", "k3y")])
        self.assertEqual(r["agent_id"], agent)
        self.assertEqual(b.door("beachblox")["grants"][0]["claims"][0]["joined_as"], "Sandy")
        info = b.world_info("beachblox", self.sandy.id)
        self.assertTrue(info["join_key_required"])
        self.assertEqual(len(info["steps"]), 1)          # only through the Beach
        b.set_join_key("beachblox", None)                # a world started without a key
        self.assertFalse(b.world_info("beachblox", self.sandy.id)["join_key_required"])

    def test_join_world_sends_the_key_header(self):
        got = {}

        class H(http.server.BaseHTTPRequestHandler):
            def do_POST(self):
                got["key"] = self.headers.get("X-Join-Key")
                got["path"] = self.path
                body = json.dumps({"session": "s", "agent_id": str(uuid.uuid4())}).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *a):
                pass
        srv = http.server.HTTPServer(("127.0.0.1", 0), H)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        try:
            r = front_door.join_world(f"http://127.0.0.1:{srv.server_port}", "Sandcastle Sam", "k3y")
            self.assertEqual(got["key"], "k3y")
            self.assertEqual(got["path"], "/join?name=Sandcastle+Sam")
            self.assertEqual(r["session"], "s")
            with self.assertRaises(ValueError):
                front_door.join_world("http://192.168.1.5:8100", "Sandy", "k3y")   # never off this machine
        finally:
            srv.shutdown()
            srv.server_close()


# 3 ----------------------------------------------------------------------- names in the world

class AdapterNameTests(unittest.TestCase):
    def setUp(self):
        from adapters.clawblox.adapter import ClawbloxAdapter
        from adapters.clawblox.tokens import approx_counter
        self.Adapter, self.counter = ClawbloxAdapter, approx_counter
        raw = json.loads((FIX / "spawn.json").read_text())
        raw["player"]["attributes"]["BeachDoor"] = "ok"
        other = {"id": "11111111-2222-4333-8444-555555555555", "name": "Sandy", "position": raw["player"]["position"],
                 "distance": 2.0, "health": 100, "attributes": {"BeachDoor": "ok", "BeachName": "Sandcastle Sam"}}
        raw["other_players"] = [other]
        self.raw = raw
        self.calls = []

    def transport(self, chat=None):
        test = self

        class T:
            def request(self, method, path, body=None, session=None):
                test.calls.append((method, path, session))
                if path == "/observe":
                    return 200, json.dumps(test.raw)
                if path.startswith("/chat/messages"):
                    return 200, json.dumps(chat or {"messages": []})
                if path.startswith("/join"):
                    return 200, json.dumps({"session": "direct", "agent_id": "x"})
                return 404, "no"
        return T()

    def test_join_through_the_beach_never_joins_directly(self):
        got = []
        a = self.Adapter(transport=self.transport(), name="Pebble", sleep=lambda s: None, counter=self.counter(),
                         join_via=lambda name: got.append(name) or {"session": "from-beach",
                                                                  "agent_id": str(uuid.uuid4())})
        a.join()
        self.assertEqual(got, ["Pebble"])
        self.assertEqual(a.session, "from-beach")
        self.assertFalse([c for c in self.calls if c[1].startswith("/join")])
        self.assertTrue(all(c[2] == "from-beach" for c in self.calls))

    def test_others_and_chat_show_current_beach_names(self):
        chat = {"messages": [{"id": "1", "agent_id": "11111111-2222-4333-8444-555555555555", "agent_name": "Sandy",
                              "content": "hello", "created_at": "2026-10-14T00:00:00Z"}]}
        a = self.Adapter(transport=self.transport(chat), name="Pebble", sleep=lambda s: None,
                         counter=self.counter(), session="s")
        view = a.look()
        self.assertIn("Sandcastle Sam", view)
        self.assertNotIn("Sandy", view)
        heard = a.hear()
        self.assertIn("Sandcastle Sam: hello", heard)

    def test_chat_from_a_speaker_out_of_view_shows_their_label(self):
        # Out of the view cone a speaker isn't in other_players; the beach world tags each
        # character with its player's UserId (low 53 bits of the agent id) next to its label.
        from adapters.clawblox.adapter import user_id_of
        from beach.bridge import user_id_for
        aid = "11111111-2222-4333-8444-555555555555"
        self.assertEqual(user_id_of(aid), user_id_for(aid))
        self.raw["other_players"] = []
        hrp = dict(next(e for e in self.raw["world"]["entities"] if e["name"] == "HumanoidRootPart"))
        hrp.update(id=9001, position=[30.0, 2.55, 30.0],
                   attributes={"PlayerName": "Sandcastle Sam", "PlayerUserId": float(user_id_of(aid))})
        self.raw["world"]["entities"].append(hrp)
        chat = {"messages": [{"id": "1", "agent_id": aid, "agent_name": "Sandy", "content": "over here",
                              "created_at": "2026-10-14T00:00:00Z"}]}
        a = self.Adapter(transport=self.transport(chat), name="Pebble", sleep=lambda s: None,
                         counter=self.counter(), session="s")
        a.look()
        self.assertIn("Sandcastle Sam: over here", a.hear())
        main = (ROOT / "worlds" / "beach" / "main.lua").read_text()
        self.assertIn('SetAttribute("PlayerUserId", player.UserId)', main)

    def test_the_viewer_patch_uses_beach_names(self):
        patch = (ROOT / "patches" / "clawblox-viewer-beach-names.patch").read_text()
        self.assertIn("BeachName", patch)
        self.assertIn("chatDisplayName(msg)", patch)
        self.assertIn("playerDisplayName(player)", patch)
        self.assertIn("chatDisplayName(entry, '')", patch)   # the "heard by" line too


# 4 ----------------------------------------------------------------------- the card editor

@unittest.skipUnless(HAVE_FASTAPI, "fastapi/httpx not installed")
class CardEditorTests(Case):
    def test_keeper_edits_and_resets_a_game_zone_card(self):
        from beach.app import create_app
        http = TestClient(create_app(self.beach, upkeep_interval=None))
        admin = {"Authorization": f"Bearer {self.beach.add_participant('Keeper Two', 'person', is_admin=True)[1]}"}
        self.beach.add_zone("beachblox", "BeachBlox", "game", viewer_url="http://127.0.0.1:8100/")
        r = http.get("/zones/beachblox/card", headers=admin).json()
        self.assertFalse(r["custom"])
        self.assertIn("BEACHBLOX CARD", r["text"])
        card = "BEACHBLOX CARD\nKick balls into the goals. Your play card has the moves."
        self.assertEqual(http.patch("/admin/zones/beachblox", json={"card": card}, headers=admin).status_code, 200)
        r = http.get("/zones/beachblox/card", headers=admin).json()
        self.assertTrue(r["custom"])
        self.assertEqual(r["text"], card)
        self.assertIn(card, http.get("/agent/turn?zone=beachblox",
                                     headers={"Authorization": f"Bearer {self.sandy_tok}"}).json()["tools"]["text"])
        http.patch("/admin/zones/beachblox", json={"card": ""}, headers=admin)        # "Use the default"
        self.assertFalse(http.get("/zones/beachblox/card", headers=admin).json()["custom"])
        self.assertEqual(http.patch("/admin/zones/beachblox", json={"card": "x" * 4001}, headers=admin).status_code, 400)
        self.assertEqual(http.patch("/admin/zones/beachblox", json={"card": card},
                                    headers={"Authorization": f"Bearer {self.sandy_tok}"}).status_code, 403)

    def test_the_keeper_page_has_the_editor(self):
        js = (ROOT / "beach" / "web" / "keeper.js").read_text()
        self.assertIn("editCard", js)
        self.assertIn("'Use the default'", js)


# 5 ----------------------------------------------------------------------- several sign-in links

class LinkTests(Case):
    def test_each_link_works_and_is_revoked_on_its_own(self):
        b = self.beach
        tablet = b.new_link(self.coral.id, "tablet")
        phone = b.new_link(self.coral.id, "phone")
        for tok in (self.coral_tok, tablet["token"], phone["token"]):
            self.assertEqual(b.authenticate(tok).id, self.coral.id)
        b.join(self.coral.id, SANDCHAT)
        b.revoke_link(self.coral.id, phone["id"])                   # the phone was lost
        self.assertIsNone(b.authenticate(phone["token"]))
        self.assertEqual(b.authenticate(tablet["token"]).id, self.coral.id)   # the tablet still works
        self.assertIn(SANDCHAT, b.zones_of(self.coral.id))          # and nobody was signed out
        labels = {l["label"]: l["active"] for l in b.links(self.coral.id)}
        self.assertEqual(labels, {"first link": True, "tablet": True, "phone": False})

    def test_revoking_the_last_link_signs_out_and_all_links_go_at_once(self):
        b = self.beach
        b.join(self.coral.id, SANDCHAT)
        first = b.links(self.coral.id)[0]["id"]
        b.revoke_link(self.coral.id, first)
        self.assertFalse(b.is_active(self.coral.id))
        self.assertEqual(b.zones_of(self.coral.id), [])
        tok = b.new_link(self.coral.id, "tablet")["token"]
        tok2 = b.new_link(self.coral.id, "phone")["token"]
        b.revoke_token(self.coral.id)                               # sign out everywhere
        self.assertIsNone(b.authenticate(tok))
        self.assertIsNone(b.authenticate(tok2))
        with self.assertRaises(BeachError):
            b.revoke_link(self.sandy.id, first)                     # not Sandy's link

    def test_tokens_are_stored_hashed_and_last_use_is_kept(self):
        b = self.beach
        t = b.new_link(self.sandy.id, "laptop")
        b.authenticate(t["token"])
        last = [l for l in b.links(self.sandy.id) if l["label"] == "laptop"][0]["last_used_at"]
        self.assertEqual(last, self.clock.t)
        b.db.checkpoint()
        raw = b"".join(p.read_bytes() for p in Path(self.dir).glob("beach.db*"))
        self.assertNotIn(t["token"].encode(), raw)

    def test_old_data_is_migrated_without_signing_anyone_out(self):
        # A Beach data folder from before job 08: one token hash on the participant row.
        old = Path(tempfile.mkdtemp(prefix="old-beach-"))
        try:
            import hashlib
            token = "old-token-abcdefghijklmnop"
            from beach.db import SCHEMA
            c = sqlite3.connect(old / "beach.db")
            c.executescript(SCHEMA.split("-- Sign-in links")[0] + ";")
            c.execute("INSERT INTO participants (name, kind, is_admin, invitable, token_hash, created_at)"
                      " VALUES ('Drift', 'person', 0, 1, ?, 1.0)", (hashlib.sha256(token.encode()).hexdigest(),))
            c.commit()
            c.close()
            b = Beach(old)
            self.assertEqual(b.authenticate(token).name, "Drift")
            self.assertEqual([l["label"] for l in b.links(b.by_name("Drift").id)], ["first link"])
            self.assertIsNone(b.db.one("SELECT token_hash FROM participants WHERE name = 'Drift'")["token_hash"])
            b.db.close()
            b = Beach(old)                                  # opening again changes nothing
            self.assertEqual(len(b.links(b.by_name("Drift").id)), 1)
            b.db.close()
        finally:
            shutil.rmtree(old, ignore_errors=True)

    @unittest.skipUnless(HAVE_FASTAPI, "fastapi/httpx not installed")
    def test_over_http(self):
        from beach.app import create_app
        http = TestClient(create_app(self.beach, upkeep_interval=None))
        admin_tok = self.beach.add_participant("Keeper Two", "person", is_admin=True)[1]
        admin = {"Authorization": f"Bearer {admin_tok}"}
        r = http.post(f"/admin/participants/{self.coral.id}/token", json={"label": "tablet"}, headers=admin).json()
        tablet = r["token"]
        self.assertEqual(r["link"]["label"], "tablet")
        self.assertEqual(http.get("/me", headers={"Authorization": f"Bearer {self.coral_tok}"}).status_code, 200)
        links = http.get(f"/admin/participants/{self.coral.id}/links", headers=admin).json()["links"]
        self.assertEqual(len(links), 2)
        mine = http.get("/me/links", headers={"Authorization": f"Bearer {tablet}"}).json()["links"]
        first = [l for l in mine if l["label"] == "first link"][0]["id"]
        http.delete(f"/me/links/{first}", headers={"Authorization": f"Bearer {tablet}"})   # sign out the other device
        self.assertEqual(http.get("/me", headers={"Authorization": f"Bearer {self.coral_tok}"}).status_code, 401)
        self.assertEqual(http.get("/me", headers={"Authorization": f"Bearer {tablet}"}).status_code, 200)
        listed = [p for p in http.get("/admin/participants", headers=admin).json()["participants"]
                  if p["name"] == "Coral"][0]
        self.assertEqual((listed["has_token"], listed["links"]), (True, 1))


# 6 ----------------------------------------------------------------------- the world launcher

FAKE_CLAWBLOX = r'''
import http.server, json, os, sys, threading, time
port = int(sys.argv[sys.argv.index("--port") + 1])
out = os.environ["FAKE_OUT"]
open(out + ".key", "w").write(os.environ.get("CLAWBLOX_JOIN_KEY", ""))
open(out + ".dir", "w").write(sys.argv[2])
print("Spectator frontend: http://localhost:%d/?spectator_token=spec-123" % port, flush=True)
class H(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        body = b"# api" if self.path.startswith("/api.md") else json.dumps({"players": []}).encode()
        self.send_response(200); self.send_header("Content-Length", str(len(body))); self.end_headers()
        self.wfile.write(body)
    def log_message(self, *a): pass
http.server.HTTPServer(("127.0.0.1", port), H).serve_forever()
'''


def _answers(port: int) -> bool:
    """Is anything listening and answering on this local port?"""
    import urllib.request
    try:
        urllib.request.build_opener(urllib.request.ProxyHandler({})).open(
            f"http://127.0.0.1:{port}/api.md", timeout=2).read()
        return True
    except OSError:
        return False


class FakeBeach:
    """A stand-in Beach that records the bridge's reports."""

    def __init__(self):
        reports = self.reports = []

        class H(http.server.BaseHTTPRequestHandler):
            def _reply(self, obj):
                body = json.dumps(obj).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_GET(self):
                self._reply({"guests": False, "grants": []})

            def do_POST(self):
                n = int(self.headers.get("Content-Length") or 0)
                reports.append(json.loads(self.rfile.read(n) or b"{}"))
                self._reply({"playing": 0, "names": "", "looks": {}})

            def log_message(self, *a):
                pass
        self.srv = http.server.HTTPServer(("127.0.0.1", 0), H)
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        self.url = f"http://127.0.0.1:{self.srv.server_port}"

    def close(self):
        self.srv.shutdown()
        self.srv.server_close()


def _free_port() -> int:
    import socket
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class LauncherTests(unittest.TestCase):
    """Run on Windows and POSIX alike: the stand-in engine is a Python script.

    Every process here gets all three standard handles explicitly (no inherited console or pipe),
    its output goes to a file (no pipe to drain), each test has its own free port, and tearDown ends
    and reaps anything a test started, so nothing carries over to later tests in any order."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="launcher-"))
        self.beach = FakeBeach()
        self.procs = []
        self.logs = []

    def tearDown(self):
        for proc in self.procs:
            if proc.poll() is None:
                proc.kill()
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                pass
        for f in self.logs:
            f.close()
        self.beach.close()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def output(self) -> str:
        return (self.tmp / "launcher.log").read_text(errors="replace")

    def launch(self, port: int) -> subprocess.Popen:
        fake = self.tmp / "fake_clawblox.py"
        fake.write_text(FAKE_CLAWBLOX)
        world = self.tmp / "world"
        world.mkdir(exist_ok=True)
        (world / "world.toml").write_text('name = "W"\n')
        (self.tmp / "bt").write_text("bridge-token")
        env = dict(os.environ, FAKE_OUT=str(self.tmp / "out"), PYTHONPATH=str(ROOT))
        flags = subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0   # for CTRL_BREAK below
        log = open(self.tmp / "launcher.log", "wb")
        self.logs.append(log)
        proc = subprocess.Popen([sys.executable, "-m", "beach.world", "--world", str(world), "--zone", "beachblox",
                                 "--port", str(port), "--bridge-token-file", str(self.tmp / "bt"),
                                 "--beach", self.beach.url, "--clawblox", str(fake),
                                 "--run-dir", str(self.tmp / "run"), "--every", "2"],
                                cwd=str(ROOT), env=env, stdin=subprocess.DEVNULL, stdout=log,
                                stderr=subprocess.STDOUT, creationflags=flags)
        self.procs.append(proc)
        return proc

    def wait_for_report(self):
        end = time.time() + 30
        while time.time() < end and not any(r.get("join_key") for r in self.beach.reports):
            time.sleep(0.2)

    def test_prepare_copies_and_refuses_the_repo(self):
        from beach.world import prepare
        world = self.tmp / "world"
        (world / ".clawblox").mkdir(parents=True)
        (world / "world.toml").write_text('name = "W"\n')
        (world / ".clawblox" / "local-8100.db").write_text("old run")
        run = prepare(world, self.tmp / "run", in_place=False)
        self.assertTrue((run / "world.toml").exists())
        self.assertFalse((run / ".clawblox").exists())          # a fresh run, not the last one's data
        prepare(world, self.tmp / "run", in_place=False)          # its own folder: replaced
        (self.tmp / "mine").mkdir()
        with self.assertRaises(SystemExit):
            prepare(world, self.tmp / "mine", in_place=False)     # someone else's folder
        with self.assertRaises(SystemExit):
            prepare(ROOT / "worlds" / "beach", self.tmp / "x", in_place=True)   # the repo's own world

    def test_starts_both_and_stops_both(self):
        port = _free_port()
        proc = self.launch(port)
        self.wait_for_report()
        key = (self.tmp / "out.key").read_text()
        self.assertGreater(len(key), 20)                         # the world got a fresh join key...
        reports = self.beach.reports
        self.assertEqual([r["join_key"] for r in reports if "join_key" in r][0], key)   # ...and the Beach too
        self.assertEqual(reports[0]["spectator_token"], "spec-123")
        # Ctrl+C (Ctrl+Break is what one process can send another on Windows)
        proc.send_signal(signal.CTRL_BREAK_EVENT if os.name == "nt" else signal.SIGINT)
        proc.wait(timeout=20)
        self.assertEqual(proc.returncode, 0, self.output())
        self.assertEqual(reports[-1], {"players": [], "join_key": None})   # the Beach hears it stopped
        self.assertFalse(_answers(port))                                     # ...and the world is gone

    def test_killing_the_launcher_outright_ends_the_world(self):
        # As if its window were closed: no signal handler, no finally. TerminateProcess on Windows,
        # SIGKILL elsewhere.
        port = _free_port()
        proc = self.launch(port)
        self.wait_for_report()
        self.assertTrue(_answers(port), self.output())
        proc.kill()
        proc.wait(timeout=10)
        end = time.time() + 15
        while time.time() < end and _answers(port):
            time.sleep(0.2)
        self.assertFalse(_answers(port), "the world kept running after its launcher was killed")

    def test_job_object_layout(self):
        # The Windows structure must match JOBOBJECT_EXTENDED_LIMIT_INFORMATION (144 bytes on 64-bit,
        # 112 on 32-bit); the layout can be checked anywhere.
        import ctypes
        from beach.procs import _ExtendedLimits
        self.assertEqual(ctypes.sizeof(_ExtendedLimits), 144 if ctypes.sizeof(ctypes.c_void_p) == 8 else 112)


class SubprocessHandleTests(unittest.TestCase):
    """Every process the code or the tests start gets all three standard handles explicitly.
    On Windows, Popen otherwise duplicates the parent's own handles, and if those are missing or
    invalid (no console, some test runners) it fails with "[WinError 6] The handle is invalid"."""

    def test_no_subprocess_inherits_standard_handles(self):
        import ast
        problems = []
        files = [f for d in ("beach", "adapters", "scripts", "tests") for f in (ROOT / d).rglob("*.py")]
        for f in files:
            tree = ast.parse(f.read_text(), str(f))
            for node in ast.walk(tree):
                if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                        and isinstance(node.func.value, ast.Name) and node.func.value.id == "subprocess"
                        and node.func.attr in ("Popen", "run", "call", "check_call", "check_output")):
                    continue
                names = {k.arg for k in node.keywords}
                if None in names:   # **popen: the callee fills in the defaults (beach/procs.py)
                    continue
                given = {"stdin": bool(names & {"stdin", "input"}),
                         "stdout": bool(names & {"stdout", "capture_output"}),
                         "stderr": bool(names & {"stderr", "capture_output"})}
                missing = [k for k, ok in given.items() if not ok]
                if missing:
                    problems.append(f"{f.relative_to(ROOT)}:{node.lineno} missing {', '.join(missing)}")
        self.assertEqual(problems, [])

    def test_the_launchers_child_gets_explicit_handles(self):
        src = (ROOT / "beach" / "procs.py").read_text()
        self.assertIn('for std in ("stdin", "stdout", "stderr"):', src)


# 7 ----------------------------------------------------------------------- Gather Bell retries

class BellRetryTests(Case):
    def ring(self, sender_results):
        b = self.beach
        b.update_settings({"bell_wait_s": 120, "bell_retry_s": 10, "bell_retries": 2})
        calls = []

        def sender(payload):
            calls.append(self.clock.t)
            return sender_results.pop(0) if sender_results else False
        sender.__bool__ = lambda: True
        b.sender = sender
        b.join(self.sandy.id, SANDCHAT)
        b.ring_bell(self.sandy.id)                 # Coral is away: one notice
        return calls

    def outbox(self):
        return [dict(r) for r in self.beach.db.q("SELECT status, attempts FROM outbox")]

    def test_a_failed_notice_is_retried_and_then_delivered(self):
        calls = self.ring([False, True])
        self.beach.deliver_notices()
        self.assertEqual(self.outbox(), [{"status": "queued", "attempts": 1}])
        self.clock.advance(5)
        self.beach.deliver_notices()               # not yet: backoff is 10 s
        self.assertEqual(len(calls), 1)
        self.clock.advance(6)
        self.beach.deliver_notices()
        self.assertEqual(len(calls), 2)
        self.assertEqual(self.outbox(), [{"status": "sent", "attempts": 2}])

    def test_gives_up_after_the_retries(self):
        calls = self.ring([False, False, False, False])
        for _ in range(10):
            self.beach.deliver_notices()
            self.clock.advance(15)
        self.assertEqual(len(calls), 3)            # the first try and two retries (10 s, then 30 s later)
        self.assertEqual(self.outbox(), [{"status": "failed", "attempts": 3}])

    def test_never_after_the_bell_has_closed(self):
        self.beach.update_settings({"bell_retry_s": 100})
        calls = self.ring([False, True])
        self.beach.update_settings({"bell_retry_s": 100})
        self.beach.deliver_notices()
        # The retry would land at +100 s; the bell closes at +120 s, so it's allowed... then the
        # bell closes before the third try could happen. A retry that would land late isn't queued.
        self.assertEqual(self.outbox()[0]["status"], "queued")
        self.clock.advance(130)
        self.beach.deliver_notices()
        self.assertEqual(len(calls), 1)            # the bell had closed: dropped, never sent late
        self.assertEqual(self.outbox()[0]["status"], "dropped")

    def test_a_retry_that_would_be_late_is_not_scheduled(self):
        self.beach.update_settings({"bell_retry_s": 200})
        calls = self.ring([False, True])
        self.beach.update_settings({"bell_retry_s": 200})
        self.beach.deliver_notices()
        self.assertEqual(self.outbox(), [{"status": "failed", "attempts": 1}])
        self.assertEqual(len(calls), 1)


# 9 ----------------------------------------------------------------------- plain-name opt-outs

class OptOutNameTests(Case):
    def setUp(self):
        super().setUp()
        self.shell, _ = self.beach.add_participant("Shell", "person")
        for p in (self.sandy, self.coral, self.shell):
            self.beach.join(p.id, SANDCHAT)

    def post(self, text):
        return self.beach.post(self.sandy.id, SANDCHAT, text)

    def test_a_plain_name_is_a_target(self):
        self.beach.set_optout(self.coral.id, SANDCHAT, True)
        for text in ("/me splashes Coral", "/me splashes coral", "/me waves at CORAL", "/me hands Coral a towel"):
            r = self.post(text)
            self.assertFalse(r["posted"], text)
            self.clock.advance(30)
        notes = [n["text"] for n in self.beach.inbox(self.sandy.id)]
        self.assertEqual(set(notes), {"Coral isn't taking actions right now"})
        self.assertTrue(self.post("/me waves at everyone")["posted"])

    def test_ordinary_words_are_not_targets(self):
        self.beach.set_optout(self.coral.id, SANDCHAT, True)
        self.beach.set_optout(self.shell.id, SANDCHAT, True)
        for text in ("/me admires the coral reef", "/me picks up a shell", "/me finds some coral",
                     "/me looks at Coralie's sandcastle", "/me collects seashells"):
            self.assertTrue(self.post(text)["posted"], text)
            self.clock.advance(30)
            self.beach.post(self.sandy.id, SANDCHAT, "nice")
        self.assertFalse(self.post("/me hands Shell a shell")["posted"])   # the person, then the word

    def test_only_present_people_and_never_yourself(self):
        self.beach.set_optout(self.coral.id, SANDCHAT, True)
        self.beach.part(self.coral.id, SANDCHAT)
        self.assertTrue(self.post("/me misses Coral")["posted"])   # Coral isn't here: not a target
        self.beach.set_optout(self.sandy.id, SANDCHAT, True)
        self.clock.advance(30)
        self.assertTrue(self.post("/me pats Sandy on the back")["posted"])

    def test_names_in(self):
        class P:
            def __init__(self, name):
                self.name = name
        people = [P("Coral"), P("Shell"), P("Sandcastle Sam")]
        self.assertEqual([p.name for p in names_in("waves at sandcastle sam", people)], ["Sandcastle Sam"])
        self.assertEqual([p.name for p in names_in("toasts @coral", people)], ["Coral"])
        self.assertEqual(names_in("drops the shell in the coral", people), [])
        self.assertEqual([p.name for p in names_in("drops Shell's shell", people)], ["Shell"])


# 8 ----------------------------------------------------------------------- the portrait map

class PortraitMapTests(unittest.TestCase):
    def test_portrait_art_and_spots(self):
        art = (ROOT / "beach" / "web" / "map-art-portrait.svg").read_text()
        self.assertIn('viewBox="0 0 1000 1600"', art)
        js = (ROOT / "beach" / "web" / "map.js").read_text()
        self.assertIn("SLOTS_PORTRAIT", js)
        self.assertIn("(orientation: portrait)", js)
        self.assertIn("map-art-portrait.svg", js)


if __name__ == "__main__":
    unittest.main()
