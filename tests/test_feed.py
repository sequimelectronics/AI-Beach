# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Becky Northaven and the AI-Beach contributors
"""Your feed and the wait call: one cursor over the rooms you're in, your tables and your notes."""

import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.dirname(__file__))

from beach.core import BOARDWALK, SANDCHAT  # noqa: E402
from beach.feed import feed, parse_only  # noqa: E402
from test_play_leave import HAVE_FASTAPI, Case  # noqa: E402

if HAVE_FASTAPI:
    from fastapi.testclient import TestClient
    from beach.app import create_app


class FeedTests(Case):
    def setUp(self):
        super().setUp()
        for p in (self.coral, self.sandy):
            self.beach.join(p.id, SANDCHAT)

    def test_first_call_starts_from_now_and_nothing_is_lost_after(self):
        self.beach.post(self.coral.id, SANDCHAT, "before the agent started listening")
        first = feed(self.beach, self.sandy.id)
        self.assertEqual(first["items"], [])
        self.beach.post(self.coral.id, SANDCHAT, "hello Sandy")
        self.beach.post(self.sandy.id, SANDCHAT, "my own line is not news to me")
        f = feed(self.beach, self.sandy.id, first["cursor"])
        self.assertEqual([(i["author"], i["text"]) for i in f["items"]], [("Coral", "hello Sandy")])
        self.assertTrue(f["items"][0]["mentions_you"])
        self.assertIn("SandChat", f["text"])
        self.assertEqual(feed(self.beach, self.sandy.id, f["cursor"])["items"], [])   # nothing twice

    def test_notices_you_caused_dont_wake_you_but_reach_everyone_else(self):
        # 10-17: opening a table, sitting and inviting each woke the agent who did it. Now only the doer
        # skips them; the one waiting at the table still hears "Sandy sat down" (the keeper's question).
        c0 = feed(self.beach, self.coral.id)["cursor"]
        s0 = feed(self.beach, self.sandy.id)["cursor"]
        tid = self.beach.tables.open(self.coral.id, BOARDWALK, "checkers")["id"]
        self.beach.tables.invite(self.coral.id, tid, "Sandy")
        mine = feed(self.beach, self.coral.id, c0)
        self.assertEqual([i for i in mine["items"] if i["source"] == "message"], [])   # nothing of her own
        self.beach.tables.sit(self.sandy.id, tid)
        coral = [i["text"] for i in feed(self.beach, self.coral.id, mine["cursor"])["items"]]
        self.assertTrue(any(t.startswith("Sandy sat down") for t in coral))   # the waiting player hears it
        self.assertIn("the game has started", coral)
        sandy = [i["text"] for i in feed(self.beach, self.sandy.id, s0)["items"] if i["source"] == "message"]
        self.assertFalse(any(t.startswith("Sandy sat down") for t in sandy))  # the sitter doesn't
        self.beach.tables.move(self.coral.id, tid, "c3-d4")      # before any move, resigning calls it off
        self.beach.tables.resign(self.sandy.id, tid)
        ends = [i["text"] for i in feed(self.beach, self.sandy.id, s0)["items"] if i["source"] == "message"]
        self.assertTrue(any("won" in t for t in ends))           # how a game ended reaches everyone

    def test_only_rooms_you_were_in(self):
        start = feed(self.beach, self.sandy.id)["cursor"]
        self.beach.part(self.sandy.id, SANDCHAT)
        self.beach.post(self.coral.id, SANDCHAT, "said while Sandy was away")
        self.assertEqual(feed(self.beach, self.sandy.id, start)["items"], [])

    def test_tables_moves_turns_and_other_tables(self):
        bw = self.beach.tables
        start = feed(self.beach, self.sandy.id)["cursor"]
        mine = bw.open(self.coral.id, BOARDWALK, "checkers")["id"]
        bw.sit(self.sandy.id, mine)
        other = bw.open(self.coral.id, BOARDWALK, "checkers")["id"]   # Sandy isn't at this one
        bw.say(self.coral.id, other, "chat at a table Sandy isn't at")
        bw.move(self.coral.id, mine, "c3-d4")
        f = feed(self.beach, self.sandy.id, start)
        self.assertIn(("move", "c3-d4"), [(i["kind"], i["text"]) for i in f["items"]])
        self.assertNotIn("chat at a table Sandy isn't at", [i["text"] for i in f["items"]])
        self.assertEqual([a["what"] for a in f["actionable"]], ["your_turn"])
        self.assertIn(f"ACTION: your turn at table {mine}", f["text"])
        # A turn already waiting shows on the very first call, so a fresh listener doesn't miss it.
        self.assertEqual([a["what"] for a in feed(self.beach, self.sandy.id)["actionable"]], ["your_turn"])

    def test_notes_are_in_the_feed_without_using_up_the_inbox(self):
        start = feed(self.beach, self.sandy.id)["cursor"]
        self.beach._note(self.sandy.id, "a private note", kind="event", data={"event": "test"})
        f = feed(self.beach, self.sandy.id, start)
        self.assertEqual([(i["source"], i["text"]) for i in f["items"]], [("note", "a private note")])
        self.assertEqual([e["text"] for e in self.beach.inbox(self.sandy.id)], ["a private note"])

    def test_a_bad_cursor_is_refused(self):
        with self.assertRaises(ValueError):
            feed(self.beach, self.sandy.id, "not-a-cursor")

    def test_only_keeps_your_tables_your_name_and_notes(self):
        # A visitor's report, 10-17: a player wants to sleep through room chat and wake for the game.
        bw = self.beach.tables
        start = feed(self.beach, self.sandy.id)["cursor"]
        tid = bw.open(self.coral.id, BOARDWALK, "checkers")["id"]
        bw.sit(self.sandy.id, tid)
        self.beach.post(self.coral.id, SANDCHAT, "chatter about the tide")
        self.beach.post(self.coral.id, SANDCHAT, "but this one is for Sandy")
        bw.move(self.coral.id, tid, "c3-d4")
        self.beach._note(self.sandy.id, "a private note")
        kept = feed(self.beach, self.sandy.id, start, only=parse_only("table,mention,note"))["items"]
        texts = [i.get("line") or i["text"] for i in kept]
        self.assertNotIn("chatter about the tide", texts)
        self.assertIn("but this one is for Sandy", texts)
        self.assertIn("Coral played c3-d4", texts)
        self.assertIn("a private note", texts)
        everything = feed(self.beach, self.sandy.id, start)["items"]
        self.assertIn("chatter about the tide", [i["text"] for i in everything])
        with self.assertRaises(ValueError):
            parse_only("table,gossip")
        # 10-18: "chat" keeps what people say and do, rooms and tables alike, and passes over game moves.
        bw.say(self.coral.id, tid, "good luck everyone")
        chat = feed(self.beach, self.sandy.id, start, only=parse_only("chat"))["items"]
        said = [i.get("line") or i["text"] for i in chat]
        self.assertIn("chatter about the tide", said)
        self.assertIn("good luck everyone", said)
        self.assertNotIn("Coral played c3-d4", said)
        self.assertNotIn("a private note", said)
        # Room and table talk say they're for everyone there.
        text = feed(self.beach, self.sandy.id, start)["text"]
        self.assertIn("(to everyone here):", text)
        self.assertIn("(to everyone at the table; talk here:", text)

    def test_card_asks_read_naturally(self):
        # First Go Fish, 10-17: the feed said "Sandy played ask Coral 9s".
        bw = self.beach.tables
        start = feed(self.beach, self.sandy.id)["cursor"]
        tid = bw.open(self.coral.id, BOARDWALK, "gofish", options={"players": 2, "seed": 3})["id"]
        bw.sit(self.sandy.id, tid)
        ask = bw.view(self.coral.id, tid)["legal"][0]
        bw.move(self.coral.id, tid, ask)
        f = feed(self.beach, self.sandy.id, start)
        line = [i["line"] for i in f["items"] if i["source"] == "move"][0]
        self.assertTrue(line.startswith("Coral asked Sandy for "), line)
        self.assertNotIn("played ask", f["text"])


class MoveReplyTests(Case):
    def test_the_reply_says_whose_turn_it_is(self):
        bw = self.beach.tables
        tid = bw.open(self.coral.id, BOARDWALK, "checkers")["id"]
        bw.sit(self.sandy.id, tid)
        r = bw.move(self.coral.id, tid, "c3-d4")
        self.assertEqual((r["your_turn"], r["next"]), (False, "Sandy"))

    def test_go_fish_go_again_comes_with_the_legal_moves(self):
        # The reply must agree with the table on every move, and "go again" must actually happen.
        bw = self.beach.tables
        tid = bw.open(self.coral.id, BOARDWALK, "gofish", options={"players": 2, "seed": 5})["id"]
        bw.sit(self.sandy.id, tid)
        seen_again = 0
        for _ in range(300):
            v = bw.view(self.coral.id, tid)
            if v["status"] != "playing":
                break
            mover = self.coral if v["to_move"] == 0 else self.sandy
            r = bw.move(mover.id, tid, bw.view(mover.id, tid)["legal"][0])
            after = bw.view(mover.id, tid)
            self.assertEqual(r["your_turn"], after["status"] == "playing" and after["your_turn"])
            if r["your_turn"]:
                seen_again += 1
                self.assertEqual(r["legal"], after["legal"])
        self.assertEqual(bw.view(self.coral.id, tid)["status"], "finished")
        self.assertGreater(seen_again, 0)

    def test_the_compact_view_is_just_the_position(self):
        from beach.agent import table_bundle
        bw = self.beach.tables
        tid = bw.open(self.coral.id, BOARDWALK, "checkers")["id"]
        bw.sit(self.sandy.id, tid)
        bw.say(self.coral.id, tid, "good luck")
        full = table_bundle(self.beach, self.coral.id, tid)          # Coral opened, so Coral (Black) moves first
        small = table_bundle(self.beach, self.coral.id, tid, compact=True)
        self.assertNotIn("tools", small)
        self.assertIn("your move. Legal moves", small["state"]["text"])
        self.assertNotIn("good luck", small["recent"]["text"])
        self.assertLess(small["total_tokens"], full["total_tokens"] / 2)


@unittest.skipUnless(HAVE_FASTAPI, "needs fastapi")
class WaitApiTests(Case):
    def setUp(self):
        super().setUp()
        self.http = TestClient(create_app(self.beach, upkeep_interval=None))
        self.h = {"Authorization": f"Bearer {self.sandy_tok}"}
        self.http.post("/zones/sandchat/join", headers=self.h)
        self.beach.join(self.coral.id, SANDCHAT)

    def test_slow_answers_are_noted_by_path_only(self):
        # 10-18: a stall left no trace. A slow answer gets one stderr line: method, path, time; never the
        # query string. (SLOW_S lowered so any answer counts; the long wait call is left out.)
        import contextlib
        import io
        import beach.app as app_mod
        old = app_mod.SLOW_S
        app_mod.SLOW_S = -1.0
        err = io.StringIO()
        try:
            with contextlib.redirect_stderr(err):
                self.http.get("/me/feed?after=secret-cursor", headers=self.h)
                self.http.get("/me/wait?timeout=0", headers=self.h)
        finally:
            app_mod.SLOW_S = old
        out = err.getvalue()
        self.assertIn("[slow]", out)
        self.assertIn("GET /me/feed took", out)
        self.assertNotIn("secret-cursor", out)
        self.assertNotIn(self.sandy_tok, out)
        self.assertNotIn("/me/wait", out)

    def test_wait_answers_at_once_when_something_is_new_and_times_out_when_not(self):
        cur = self.http.get("/me/wait", headers=self.h).json()["cursor"]   # first call: at once
        self.beach.post(self.coral.id, SANDCHAT, "news")
        r = self.http.get(f"/me/wait?after={cur}&timeout=5", headers=self.h).json()
        self.assertEqual([i["text"] for i in r["items"]], ["news"])
        quiet = self.http.get(f"/me/wait?after={r['cursor']}&timeout=0", headers=self.h).json()
        self.assertEqual((quiet["items"], quiet["cursor"]), ([], r["cursor"]))

    def test_the_visitor_kit_is_at_the_door_for_anyone_unless_turned_off(self):
        guide = self.http.get("/kit")                                    # no token: open on purpose
        self.assertEqual(guide.status_code, 200)
        self.assertIn("text/markdown", guide.headers["content-type"])
        self.assertIn("Visiting a Beach", guide.text)
        helper = self.http.get("/kit/beach_visit.py")
        self.assertEqual(helper.status_code, 200)
        self.assertEqual(helper.text, (Path(__file__).parent.parent / "scripts" / "beach_visit.py").read_text(encoding="utf-8"))
        self.assertIn("GET /kit", self.http.get("/", headers={"accept": "text/plain"}).text)
        self.beach.update_settings({"visitor_kit": False})
        self.assertEqual(self.http.get("/kit").status_code, 404)
        self.assertEqual(self.http.get("/kit/beach_visit.py").status_code, 404)
        self.assertNotIn("/kit", self.http.get("/", headers={"accept": "text/plain"}).text)
        with self.assertRaises(Exception):
            self.beach.update_settings({"visitor_kit": "yes"})

    def test_feed_and_bad_cursor_over_http(self):
        self.assertEqual(self.http.get("/me/feed?after=x.y", headers=self.h).status_code, 400)
        self.assertEqual(self.http.get("/me/wait?only=gossip", headers=self.h).status_code, 400)
        self.assertIn("cursor", self.http.get("/me/feed", headers=self.h).json())

    def test_wait_with_only_passes_over_chatter_without_waking(self):
        cur = self.http.get("/me/wait", headers=self.h).json()["cursor"]
        self.beach.post(self.coral.id, SANDCHAT, "chatter")
        r = self.http.get(f"/me/wait?after={cur}&timeout=1&only=mention", headers=self.h).json()
        self.assertEqual(r["items"], [])
        self.assertNotEqual(r["cursor"], cur)        # stepped past the chatter, so it's never re-read
        self.beach.post(self.coral.id, SANDCHAT, "Sandy, your turn soon")
        r = self.http.get(f"/me/wait?after={r['cursor']}&timeout=5&only=mention", headers=self.h).json()
        self.assertEqual([i["text"] for i in r["items"]], ["Sandy, your turn soon"])

    def test_compact_turn_over_http(self):
        tid = self.beach.tables.open(self.coral.id, BOARDWALK, "checkers")["id"]
        self.beach.tables.sit(self.sandy.id, tid)
        r = self.http.get(f"/agent/turn?table={tid}&compact=1", headers=self.h).json()
        self.assertEqual(set(r) - {"total_tokens", "token_method"}, {"state", "recent"})


if __name__ == "__main__":
    unittest.main()
