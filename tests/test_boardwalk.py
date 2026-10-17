# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Becky Northaven and the AI-Beach contributors
"""Tests for the Boardwalk (game tables), against a temporary data directory with a fake clock.

Core tests need only the standard library; the HTTP tests need FastAPI + httpx.
"""

from __future__ import annotations

import json
import random
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from beach.agent import beach_card, table_bundle, turn_bundle, zone_card  # noqa: E402
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


class BoardwalkCase(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="boardwalk-")
        self.clock = FakeClock()
        self.beach = Beach(self.dir, clock=self.clock, rng=random.Random(2))
        self.beach.ensure_admin()
        self.sandy, _ = self.beach.add_participant("Sandy", "agent")
        self.pebble, _ = self.beach.add_participant("Pebble", "agent")
        self.coral, _ = self.beach.add_participant("Coral", "person")
        self.drift, _ = self.beach.add_participant("Drift", "person")
        self.bw = self.beach.tables
        self.hook = []
        self.beach.sender = lambda payload: self.hook.append(payload) or True

    def tearDown(self):
        self.beach.db.close()
        shutil.rmtree(self.dir, ignore_errors=True)

    def game(self, black=None, white=None) -> int:
        black, white = black or self.sandy, white or self.pebble
        tid = self.bw.open(black.id, BOARDWALK, "checkers")["id"]
        self.bw.sit(white.id, tid)
        return tid

    def sandchat_notices(self):
        return [r["text"] for r in self.beach.db.q(
            "SELECT text FROM messages WHERE zone_id = ? AND kind = 'notice' ORDER BY id", (SANDCHAT,))]


class TableTests(BoardwalkCase):
    def test_boardwalk_is_a_zone_with_a_keeper_name(self):
        z = self.beach.zone(BOARDWALK)
        self.assertEqual(z["name"], "The Boardwalk")
        self.assertTrue(z["tables"])
        self.beach.update_zone(BOARDWALK, name="The Pier")
        self.assertIn("- boardwalk: The Pier (game tables)", beach_card(self.beach))
        self.assertIn("boardwalk", [z["id"] for z in self.beach.zone_map()])

    def test_open_sit_and_start(self):
        v = self.bw.open(self.sandy.id, BOARDWALK, "checkers")
        self.assertEqual(v["status"], "waiting")
        self.assertEqual(v["my_seat"], 0)
        self.assertIn(BOARDWALK, self.beach.zones_of(self.sandy.id))   # opening brings you in
        v = self.bw.sit(self.coral.id, v["id"])
        self.assertEqual(v["status"], "playing")
        self.assertEqual(v["my_seat"], 1)
        self.assertEqual([s["player"]["name"] for s in v["seats"]], ["Sandy", "Coral"])
        self.assertFalse(v["your_turn"])
        self.assertTrue(self.bw.view(self.sandy.id, v["id"])["your_turn"])

    def test_any_mix_of_players(self):
        for a, b in ((self.coral, self.sandy), (self.sandy, self.pebble), (self.coral, self.drift)):
            tid = self.game(a, b)
            self.assertEqual(self.bw.table(tid)["status"], "playing")

    def test_seat_rules(self):
        tid = self.bw.open(self.sandy.id, BOARDWALK, "checkers")["id"]
        with self.assertRaises(BeachError):
            self.bw.sit(self.sandy.id, tid)            # not both seats
        with self.assertRaises(BeachError):
            self.bw.sit(self.pebble.id, tid, seat=0)    # taken
        self.bw.sit(self.pebble.id, tid)
        with self.assertRaises(BeachError) as cm:
            self.bw.sit(self.coral.id, tid)
        self.assertIn("watch", cm.exception.message)
        self.bw.watch(self.coral.id, tid)
        self.assertEqual(self.bw.view(self.coral.id, tid)["watchers"], 1)
        with self.assertRaises(BeachError):
            self.bw.move(self.coral.id, tid, "c3-d4")  # watchers can't move

    def test_stand_before_start_closes_an_empty_table(self):
        tid = self.bw.open(self.sandy.id, BOARDWALK, "checkers")["id"]
        self.bw.stand(self.sandy.id, tid)
        self.assertEqual(self.bw.table(tid)["status"], "closed")
        tid = self.game()
        with self.assertRaises(BeachError):
            self.bw.stand(self.sandy.id, tid)

    def test_closed_zone_refuses_new_tables(self):
        self.beach.update_zone(BOARDWALK, open=False)
        with self.assertRaises(BeachError):
            self.bw.open(self.sandy.id, BOARDWALK, "checkers")
        with self.assertRaises(BeachError):
            self.bw.open(self.sandy.id, SANDCHAT, "checkers")   # no tables there
        self.beach.update_zone(BOARDWALK, open=True)
        with self.assertRaises(BeachError):
            self.bw.open(self.sandy.id, BOARDWALK, "chess")

    def test_moves_turns_and_illegal_moves(self):
        tid = self.game()
        with self.assertRaises(BeachError) as cm:
            self.bw.move(self.pebble.id, tid, "b6-a5")
        self.assertIn("Sandy's turn", cm.exception.message)
        with self.assertRaises(BeachError) as cm:
            self.bw.move(self.sandy.id, tid, "c3-c4")
        self.assertEqual(cm.exception.code, "invalid")
        self.assertIn("Legal moves: a3-b4", cm.exception.message)
        self.assertEqual(cm.exception.data["legal"][0], "a3-b4")
        r = self.bw.move(self.sandy.id, tid, "c3-d4")
        self.assertEqual(r["moved"], "c3-d4")
        h = self.bw.history(tid)
        self.assertEqual([(m["ply"], m["name"], m["move"]) for m in h], [(1, "Sandy", "c3-d4")])

    def test_resign(self):
        tid = self.game(self.coral, self.sandy)
        self.bw.move(self.coral.id, tid, "c3-d4")
        v = self.bw.resign(self.sandy.id, tid)
        self.assertEqual(v["status"], "finished")
        self.assertEqual(v["result"], {"winner": 0, "reason": "Sandy resigned"})
        self.assertEqual(self.sandchat_notices(),
                         ["Coral and Sandy finished a game of checkers on The Boardwalk: Coral won (Sandy resigned)."])
        with self.assertRaises(BeachError):
            self.bw.move(self.sandy.id, tid, "b6-a5")

    def test_resigning_before_any_move_calls_it_off(self):
        # Live, 10-15: a table filled at two before the third player sat; resigning it announced a "win".
        tid = self.game(self.coral, self.sandy)
        v = self.bw.resign(self.sandy.id, tid)
        self.assertEqual(v["status"], "closed")
        self.assertIsNone(v["result"]["winner"])
        self.assertEqual(self.sandchat_notices(), [])
        self.assertEqual(self.bw.result_text(self.bw.game(self.bw.table(tid)), self.bw.seats(tid),
                                             v["result"], "closed"), "Sandy called it off before the first move")
        self.assertIn("table closed: Sandy called it off", table_bundle(self.beach, self.coral.id, tid)["state"]["text"])

    def test_a_closed_table_reads_without_crashing(self):
        # Live, 10-17 (server log): GET /agent/turn?table=<a table everyone stood up from> raised KeyError.
        tid = self.bw.open(self.sandy.id, BOARDWALK, "checkers")["id"]
        self.bw.stand(self.sandy.id, tid)
        self.assertEqual(self.bw.table(tid)["status"], "closed")
        self.assertIn("table closed: it never started", table_bundle(self.beach, self.sandy.id, tid)["state"]["text"])

    def test_resign_and_draw_available_on_either_turn(self):
        tid = self.game()
        self.bw.draw(self.pebble.id, tid, "offer")      # not Pebble's turn: still fine
        v = self.bw.draw(self.sandy.id, tid, "accept")
        self.assertEqual(v["result"], {"winner": None, "reason": "a draw by agreement"})
        self.assertTrue(self.sandchat_notices()[-1].endswith(": a draw."))

    def test_draw_offer_decline_and_playing_on(self):
        tid = self.game()
        self.bw.draw(self.sandy.id, tid, "offer")
        with self.assertRaises(BeachError):
            self.bw.draw(self.sandy.id, tid, "accept")   # can't accept your own
        self.bw.draw(self.pebble.id, tid, "decline")
        self.assertIsNone(self.bw.table(tid)["draw_offer"])
        self.bw.draw(self.sandy.id, tid, "offer")
        self.bw.move(self.sandy.id, tid, "c3-d4")        # the offerer moving keeps the offer
        self.assertEqual(self.bw.table(tid)["draw_offer"], 0)
        self.bw.move(self.pebble.id, tid, "f6-e5")       # the other side playing on declines it
        self.assertIsNone(self.bw.table(tid)["draw_offer"])
        with self.assertRaises(BeachError):
            self.bw.draw(self.pebble.id, tid, "accept")

    def test_no_announcement_mid_game_and_setting_off(self):
        tid = self.game()
        self.bw.move(self.sandy.id, tid, "c3-d4")
        self.assertEqual(self.sandchat_notices(), [])
        self.beach.update_settings({"announce_results": False})
        self.bw.resign(self.pebble.id, tid)
        self.assertEqual(self.sandchat_notices(), [])

    def test_leaving_never_forfeits_and_moving_brings_you_back(self):
        tid = self.game()
        self.beach.part(self.sandy.id, BOARDWALK)
        self.beach.part(self.pebble.id, BOARDWALK)
        self.clock.advance(86400)                       # a day later
        self.bw.sweep()
        self.assertEqual(self.bw.table(tid)["status"], "playing")
        self.bw.move(self.sandy.id, tid, "c3-d4")
        self.assertIn(BOARDWALK, self.beach.zones_of(self.sandy.id))

    def test_your_move_notice_once_rate_limited(self):
        tid = self.game()
        self.beach.part(self.sandy.id, BOARDWALK)          # Sandy (to move) steps away
        self.clock.advance(300)
        self.bw.sweep()
        self.assertEqual(self.hook, [])                     # not yet: only after turn_notify_after_s
        self.clock.advance(400)
        self.bw.sweep()
        self.assertEqual(len(self.hook), 1)
        self.assertEqual(self.hook[0]["event"], "your_move")
        self.assertEqual(self.hook[0]["invitee"], "Sandy")
        events = self.beach.inbox(self.sandy.id)
        self.assertIn("your move at The Boardwalk", events[0]["text"])
        for _ in range(5):                                  # never repeated for the same turn
            self.clock.advance(3600)
            self.bw.sweep()
        self.assertEqual(len(self.hook), 1)
        # A second game's turn within the hour: rate-limited per participant.
        tid2 = self.game(self.sandy, self.coral)
        self.beach.part(self.sandy.id, BOARDWALK)
        self.bw.move(self.sandy.id, tid, "c3-d4")           # (this brings Sandy back...)
        self.beach.part(self.sandy.id, BOARDWALK)           # ...and away again
        self.clock.advance(700)
        self.bw.sweep()
        self.assertEqual([h["table"] for h in self.hook], [tid, tid2])  # tid2: last notice > 1 h ago
        # A third game's turn ten minutes later: the per-participant gap holds it back.
        tid3 = self.game(self.sandy, self.drift)
        self.beach.part(self.sandy.id, BOARDWALK)
        self.clock.advance(700)
        self.bw.sweep()
        self.assertEqual([h["table"] for h in self.hook], [tid, tid2])
        self.assertEqual(self.bw.table(tid3)["notified_ply"], 0)   # handled: it won't come later either

    def test_no_notice_while_present(self):
        tid = self.game()
        self.clock.advance(5000)
        self.bw.sweep()
        self.assertEqual(self.hook, [])
        self.beach.part(self.sandy.id, BOARDWALK)           # leaves later: still one notice
        self.bw.sweep()
        self.assertEqual(len(self.hook), 1)
        self.assertEqual(self.bw.table(tid)["status"], "playing")

    def test_abandon_after_keeper_time_is_not_a_loss(self):
        tid = self.game()
        self.bw.move(self.sandy.id, tid, "c3-d4")
        self.clock.advance(3 * 86400 - 10)
        self.beach.tick()
        self.assertEqual(self.bw.table(tid)["status"], "playing")
        self.clock.advance(20)
        self.beach.tick()
        row = self.bw.table(tid)
        self.assertEqual(row["status"], "abandoned")
        self.assertEqual(json.loads(row["result"]), {"winner": None, "reason": "abandoned"})
        self.assertEqual(self.sandchat_notices(), [])        # not announced: nobody finished it
        self.beach.update_settings({"table_abandon_s": 60})
        tid = self.bw.open(self.coral.id, BOARDWALK, "checkers")["id"]
        self.clock.advance(61)
        self.beach.tick()
        self.assertEqual(self.bw.table(tid)["status"], "closed")   # an empty waiting table just closes

    def test_game_to_the_end_announces_the_winner(self):
        tid = self.game(self.pebble, self.sandy)
        # Put a near-finished position on the table and play the winning capture.
        from beach.games.checkers import Checkers
        st = Checkers.from_pieces({"c3": "b", "d4": "w"})
        self.beach.db.run("UPDATE game_tables SET state = ? WHERE id = ?", (json.dumps(st), tid))
        r = self.bw.move(self.pebble.id, tid, "c3xe5")
        self.assertEqual(r["over"], {"winner": 0, "reason": "all pieces captured"})
        self.assertEqual(self.sandchat_notices(), [
            "Pebble and Sandy finished a game of checkers on The Boardwalk: Pebble won (all pieces captured)."])

    def test_table_chat_is_a_thread_of_the_zone_chat(self):
        tid = self.game()
        self.bw.say(self.sandy.id, tid, "good luck!")
        table_lines = [m["text"] for m in self.bw.chat(self.pebble.id, tid)]
        self.assertIn("good luck!", table_lines)
        self.assertNotIn("good luck!", [m["text"] for m in self.beach.read(self.pebble.id, BOARDWALK)])
        # Presence still bounds reading: a latecomer doesn't see what was said before they came.
        self.bw.watch(self.coral.id, tid)
        self.assertNotIn("good luck!", [m["text"] for m in self.bw.chat(self.coral.id, tid)])

    def test_no_boardwalk_wide_chat(self):
        # Chat lives in SandChat, a game world, or at a table: not across the whole Boardwalk.
        tid = self.game()
        for text in ("anyone for a second table?", "/me waves"):
            with self.assertRaises(BeachError) as e:
                self.beach.post(self.pebble.id, BOARDWALK, text)
            self.assertIn("talk at a table", e.exception.message)
        self.bw.say(self.pebble.id, tid, "/me waves")                       # at a table: fine

class BundleTests(BoardwalkCase):
    def test_table_bundle_lists_legal_moves_on_your_turn(self):
        tid = self.game()
        b = table_bundle(self.beach, self.sandy.id, tid)
        self.assertTrue(b["tools"]["text"].startswith("BEACH CARD"))
        self.assertIn("CHECKERS CARD", b["tools"]["text"])
        st = b["state"]["text"]
        self.assertIn("you are Black; Pebble is White", st)
        self.assertIn("your move. Legal moves (pick one): a3-b4, c3-b4, c3-d4, e3-d4, e3-f4, g3-f4, g3-h4", st)
        b2 = table_bundle(self.beach, self.pebble.id, tid)
        self.assertIn("Sandy's move; the game waits for them", b2["state"]["text"])
        self.assertNotIn("Legal moves", b2["state"]["text"])

    def test_zone_turn_lists_tables(self):
        tid = self.game()
        b = turn_bundle(self.beach, self.coral.id, BOARDWALK)
        self.assertIn("THE BOARDWALK CARD", b["tools"]["text"])
        self.assertIn(f"table {tid}: checkers, Sandy vs Pebble; Sandy to move", b["state"]["text"])

    def test_beach_card_is_the_same_everywhere(self):
        tid = self.game()
        cards = [turn_bundle(self.beach, self.sandy.id, z)["tools"]["text"].split("\n\n")[0]
                 for z in (SANDCHAT, BOARDWALK)]
        cards.append(table_bundle(self.beach, self.sandy.id, tid)["tools"]["text"].split("\n\n")[0])
        self.assertEqual(len(set(cards)), 1)
        self.assertEqual(cards[0], beach_card(self.beach))
        for z in (SANDCHAT, BOARDWALK):
            self.assertNotIn("/join", zone_card(self.beach, z))


@unittest.skipUnless(HAVE_FASTAPI, "fastapi/httpx not installed")
class TableApiTests(unittest.TestCase):
    def setUp(self):
        from beach.app import create_app
        self.dir = tempfile.mkdtemp(prefix="boardwalk-api-")
        self.clock = FakeClock()
        self.beach = Beach(self.dir, clock=self.clock, rng=random.Random(1))
        self.admin = {"Authorization": f"Bearer {self.beach.ensure_admin()}"}
        self.http = TestClient(create_app(self.beach, upkeep_interval=None))
        self.h = {}
        for name, kind in (("Sandy", "agent"), ("Coral", "person")):
            tok = self.http.post("/claim", json={"code": self.http.post("/admin/participants", json={"name": name, "kind": kind}, headers=self.admin).json()["invite"]["code"]}).json()["token"]
            self.h[name] = {"Authorization": f"Bearer {tok}"}

    def tearDown(self):
        self.beach.db.close()
        shutil.rmtree(self.dir, ignore_errors=True)

    def test_open_sit_move_illegal_draw_resign(self):
        r = self.http.post("/zones/boardwalk/tables", json={"game": "checkers"}, headers=self.h["Coral"])
        self.assertEqual(r.status_code, 200, r.text)
        tid = r.json()["id"]
        lst = self.http.get("/zones/boardwalk/tables", headers=self.h["Sandy"]).json()
        self.assertEqual(lst["tables"][0]["status"], "waiting")
        self.assertEqual(self.http.post(f"/tables/{tid}/sit", headers=self.h["Sandy"]).json()["status"], "playing")
        bad = self.http.post(f"/tables/{tid}/move", json={"move": "c3-e5"}, headers=self.h["Coral"])
        self.assertEqual(bad.status_code, 400)
        self.assertIn("c3-d4", bad.json()["legal"])
        self.assertIn("reason", bad.json())
        turn = self.http.post(f"/tables/{tid}/move", json={"move": "c3-d4"}, headers=self.h["Sandy"])
        self.assertEqual(turn.status_code, 409)
        ok = self.http.post(f"/tables/{tid}/move", json={"move": "c3-d4"}, headers=self.h["Coral"])
        self.assertEqual(ok.json()["moved"], "c3-d4")
        view = self.http.get(f"/tables/{tid}", headers=self.h["Sandy"]).json()
        self.assertTrue(view["your_turn"])
        self.assertEqual(view["position"]["board"]["d4"], "b")
        self.assertIn("f6-e5", view["legal"])
        bundle = self.http.get(f"/agent/turn?table={tid}", headers=self.h["Sandy"]).json()
        self.assertIn("your move. Legal moves", bundle["state"]["text"])
        self.assertEqual(self.http.post(f"/tables/{tid}/draw", json={"action": "offer"},
                                        headers=self.h["Sandy"]).status_code, 200)
        self.assertEqual(self.http.post(f"/tables/{tid}/draw", json={"action": "decline"},
                                        headers=self.h["Coral"]).json()["draw_offer"], None)
        self.http.post(f"/tables/{tid}/say", json={"text": "nice opening"}, headers=self.h["Sandy"])
        chat = self.http.get(f"/tables/{tid}/chat", headers=self.h["Coral"]).json()["messages"]
        self.assertIn("Sandy: nice opening", [m["line"] for m in chat])
        r = self.http.post(f"/tables/{tid}/resign", headers=self.h["Sandy"]).json()
        self.assertEqual(r["result_text"], "Coral won (Sandy resigned)")
        sc = self.http.post("/zones/sandchat/join", headers=self.h["Coral"])
        self.assertEqual(sc.status_code, 200)

    def test_pause_resume_and_abandon_over_http(self):
        tid = self.http.post("/zones/boardwalk/tables", json={"game": "checkers"}, headers=self.h["Coral"]).json()["id"]
        self.http.post(f"/tables/{tid}/sit", headers=self.h["Sandy"])
        self.http.post("/zones/boardwalk/part", headers=self.h["Coral"])
        self.clock.advance(2 * 86400)
        self.beach.tick()
        self.assertEqual(self.http.get(f"/tables/{tid}", headers=self.h["Sandy"]).json()["status"], "playing")
        self.assertEqual(self.http.post(f"/tables/{tid}/move", json={"move": "a3-b4"},
                                        headers=self.h["Coral"]).status_code, 200)   # resumes a day later
        self.clock.advance(3 * 86400 + 1)
        self.beach.tick()
        v = self.http.get(f"/tables/{tid}", headers=self.h["Coral"]).json()
        self.assertEqual(v["status"], "abandoned")
        self.assertEqual(v["result_text"], "the game was set aside unfinished")

    def test_watchers_and_strangers(self):
        tid = self.http.post("/zones/boardwalk/tables", json={"game": "checkers"}, headers=self.h["Coral"]).json()["id"]
        self.assertEqual(self.http.post(f"/tables/{tid}/watch", headers=self.h["Sandy"]).json()["watching"], True)
        self.assertEqual(self.http.post(f"/tables/{tid}/resign", headers=self.h["Sandy"]).status_code, 403)
        self.assertEqual(self.http.get(f"/tables/{tid}").status_code, 401)
        self.assertEqual(self.http.get("/tables/999", headers=self.h["Sandy"]).status_code, 404)


if __name__ == "__main__":
    unittest.main()


class ClawBloxZoneTests(unittest.TestCase):
    """The ClawBlox zone: the bridge reads mesa-island's players, and the world is assembled offline-ready."""

    def test_bridge_reads_mesa_island_players(self):
        from beach.bridge import door_report, player_names
        # The shape mesa-island's /spectate returned in the live run: names, plus the door's attributes.
        a1, a2 = "687b2927-119e-4a49-8fc3-4f3d259506fb", "11111111-2222-4333-8444-555555555555"
        spect = {"players": [{"id": a1, "name": "Drift", "position": [0, 5, 0], "health": 100,
                              "attributes": {"LastActionResult": "", "BeachDoor": "ok", "BeachName": "Drift"}},
                             {"id": a2, "name": "Pebble", "position": [3, 5, 0], "health": 100,
                              "attributes": {"BeachDoor": "pending"}}]}
        self.assertEqual(player_names(spect), ["Drift", "Pebble"])
        self.assertEqual(door_report(spect), [{"user_id": Beach.user_id_for(a1), "joined_as": "Drift"}])

    def test_assemble_world_from_a_checkout(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location("clawblox_world", ROOT / "scripts" / "clawblox_world.py")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        tmp = Path(tempfile.mkdtemp(prefix="clawblox-assemble-"))
        try:
            mesa = tmp / "clawblox" / "worlds" / "mesa-island"
            (mesa / "renderer" / "src").mkdir(parents=True)
            (mesa / "assets").mkdir()
            (mesa / "world.toml").write_text('name = "Mesa World"\nmax_players = 1\n\n[scripts]\nmain = "main.lua"\n')
            (mesa / "main.lua").write_text("-- mesa")
            (mesa / "assets" / "player.glb").write_bytes(b"glb")
            (mesa / "renderer" / "src" / "index.js").write_text("import * as THREE from 'https://esm.sh/three'")
            out = mod.assemble(tmp / "clawblox", tmp / "world", max_players=4)
            self.assertTrue((out / "main.lua").exists())
            self.assertTrue((out / "assets" / "player.glb").exists())
            self.assertIn("max_players = 4", (out / "world.toml").read_text())
            ours = (out / "renderer" / "src" / "index.js").read_text()
            self.assertFalse([ln for ln in ours.splitlines() if ln.startswith("import") and "esm.sh" in ln])
            self.assertIn("../../static/vendor/three/build/three.module.min.js", ours)
            self.assertTrue((out / "static" / "vendor" / "three" / "build" / "three.module.min.js").exists())
            self.assertTrue((out / "static" / "vendor" / "lucide" / "lucide.mjs").exists())
            self.assertTrue((out / "scripts" / "ServerScriptService" / "BeachDoor.lua").exists())
            self.assertIn('tree = "scripts"', (out / "world.toml").read_text())
            mod.assemble(tmp / "clawblox", tmp / "world")          # its own folder: replaced
            (tmp / "mine").mkdir()
            with self.assertRaises(SystemExit):
                mod.assemble(tmp / "clawblox", tmp / "mine")        # someone else's folder: refused
            with self.assertRaises(SystemExit):
                mod.assemble(tmp / "clawblox", ROOT / "worlds" / "x")  # inside the repo: refused
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_our_renderers_never_import_from_the_internet(self):
        for world in ("beach", "clawblox"):
            src = (ROOT / "worlds" / world / "renderer" / "src" / "index.js").read_text()
            imports = [ln for ln in src.splitlines() if "import" in ln and ("from" in ln or "import(" in ln)]
            self.assertFalse([ln for ln in imports if "http" in ln or "esm.sh" in ln], world)
            self.assertIn("static/vendor/three/build/three.module.min.js", src)
