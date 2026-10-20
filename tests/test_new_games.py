# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Becky Northaven and the AI-Beach contributors
"""The three games the keeper chose next (10-19), played through the Boardwalk: Lanterns o'er the Bay
(cooperative), Message in a Bottle (a story game; kept stories go on the Reading Room's bottle shelf)
and Hearts. Each plays a whole game; what's hidden stays hidden."""

from __future__ import annotations

import json
import random
import re
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from beach.agent import table_bundle  # noqa: E402
from beach.core import BOARDWALK, BeachError  # noqa: E402
from beach.games import GAMES  # noqa: E402
from beach.library import READINGROOM  # noqa: E402
from test_cards import CardTableCase  # noqa: E402

NAMES = ("Sandy", "Pebble", "Coral")


class NewGamesTests(CardTableCase):
    def seen_by(self, name, tid) -> str:
        pid = self.p[name].id
        return "\n".join([json.dumps(self.bw.view(pid, tid)), json.dumps(table_bundle(self.beach, pid, tid, consume_notes=False)),
                          json.dumps(self.bw.chat(pid, tid)), json.dumps(self.bw.list(BOARDWALK))])

    def mover(self, tid):
        v = self.bw.view(self.p["Sandy"].id, tid)
        return None if v["status"] != "playing" else NAMES[v["to_move"]]

    def test_examples_use_made_up_names(self):
        # 10-19, the keeper: a small model copies examples as they stand, so an example
        # never names a plausible player, and a copied story placeholder is refused, not written into the story.
        for gid, g in GAMES.items():
            card = g.card(7)
            for name in ("Pebble", "Coral", "Sandy"):
                self.assertNotIn(name, card, gid)
        self.assertIn("ask Whomever 7s", GAMES["gofish"].card(7))
        g = GAMES["bottle"]
        s = g.new({"players": 2, "seed": 1})
        for copied in ("write <a line or two of the story>", "write (your line or two, following the one you were shown)"):
            with self.assertRaises(Exception):
                g.play(s, copied)

    def test_compact_read_lists_the_moves_since_yours(self):
        # 10-19: Go Fish is played from the others' asks; a compact read shows everything since your own move.
        tid = self.table("gofish", seed=70_000_007)
        moved = []
        for _ in range(30):
            v = self.bw.view(self.p["Sandy"].id, tid)
            if v["status"] != "playing":
                break
            who = NAMES[v["to_move"]]
            if who == "Sandy" and len(moved) > 3 and moved[-1] != "Sandy":
                break
            self.bw.move(self.p[who].id, tid, self.bw.view(self.p[who].id, tid)["legal"][0])
            moved.append(who)
        recent = table_bundle(self.beach, self.p["Sandy"].id, tid, consume_notes=False, compact=True)["recent"]["text"]
        self.assertTrue(recent.startswith("moves since your last: "), recent)
        last_mine = max(i for i, w in enumerate(moved) if w == "Sandy")
        others = len(moved) - last_mine - 1
        self.assertEqual(recent.count("; ") + 1, others, recent)

    def test_lanterns_says_when_your_card_is_ready(self):
        # 10-19: a fully known card that's needed next says so (to its holder, who could work it out anyway).
        g = GAMES["lanterns"]
        s = g.new({"players": 2, "seed": 9})
        s["names"] = ["Sandy", "Pebble"]
        s["hands"][1] = [g._slot(c) for c in ("R1", "G2", "R3", "B1", "W5")]
        s, _ = g.play(s, "hint Pebble red")          # Pebble knows cards 1 and 3 are red...
        self.assertNotIn("needed next: play it", g.text(s, 1))
        s, _ = g.play(s, "discard 2")                # (Pebble's turn passes)
        s, _ = g.play(s, "hint Pebble 1")            # ...and now that card 1 is a 1: red needs a 1
        self.assertIn("1: ? (told: red, 1) <- needed next: play it", g.text(s, 1))
        self.assertTrue(g.view(s, 1)["hands"][1][0]["ready"])
        self.assertNotIn("ready", g.view(s, 0)["hands"][1][0])   # only the holder's own view marks it
        self.assertIn("not that it's safe to play", g.card(1))

    def test_an_answered_invite_stops_showing(self):
        tid = self.bw.open(self.p["Sandy"].id, BOARDWALK, "gofish", options={"players": 2})["id"]
        self.bw.invite(self.p["Sandy"].id, tid, "Pebble")
        self.bw.sit(self.p["Pebble"].id, tid)
        state = table_bundle(self.beach, self.p["Pebble"].id, tid, consume_notes=False)["state"]["text"]
        self.assertNotIn("invited you", state)

    def test_registered_and_offered(self):
        for gid in ("lanterns", "bottle", "hearts"):
            self.assertIn(gid, GAMES)
            self.assertLess(len(GAMES[gid].card(1)), 1400)
        self.assertEqual(GAMES["hearts"].min_seats, 3)

    def test_lanterns_a_whole_night_and_your_own_hand_stays_hidden(self):
        tid = self.table("lanterns", seed=40_000_001)
        rng = random.Random(3)
        for _ in range(300):
            who = self.mover(tid)
            if who is None:
                break
            seat = NAMES.index(who)
            v = self.bw.view(self.p[who].id, tid)
            mine = v["position"]["hands"][seat]
            self.assertTrue(all("c" not in x for x in mine), "you never see your own lanterns")
            others = [x for q, h in enumerate(v["position"]["hands"]) if q != seat for x in h]
            self.assertTrue(all("c" in x for x in others), "you see everyone else's")
            text = table_bundle(self.beach, self.p[who].id, tid, consume_notes=False)
            self.assertIn("your hand (you can't see it)", json.dumps(text))
            legal = v["legal"]
            hints = [m for m in legal if m.startswith("hint ")]
            self.bw.move(self.p[who].id, tid, rng.choice(hints) if hints and rng.random() < 0.5 else rng.choice(legal))
        v = self.bw.view(self.p["Sandy"].id, tid)
        self.assertEqual(v["status"], "finished")
        self.assertRegex(v["result_text"], r"(bay glowed with|squalls ended the night with|every lantern) ")

    def test_lanterns_hints_point_and_remember(self):
        g = GAMES["lanterns"]
        s = g.new({"players": 2, "seed": 9})
        s["names"] = ["Sandy", "Pebble"]
        s["hands"][1] = [g._slot(c) for c in ("R1", "G2", "R3", "B1", "W5")]
        s, info = g.play(s, "hint Pebble red")
        self.assertEqual(info["text"], "Sandy told Pebble: cards 1, 3 are red")
        self.assertEqual(g.told(s["hands"][1][1]), "not red")
        self.assertIn("1: ? (told: red)", g.text(s, 1))
        s, info = g.play(s, "play 1")                       # Pebble plays the red 1: lit
        self.assertEqual(info["text"], "Pebble lit the red 1 lantern")
        s, info = g.play(s, "hint Pebble 3")
        self.assertRegex(info["text"], r"^Sandy told Pebble: (card \d is a 3|cards [\d, ]+ are 3s)$")
        with self.assertRaises(Exception):
            g.play(s, "discard 9")          # Pebble holds five cards

    def test_hearts_a_whole_game(self):
        tid = self.table("hearts", seed=50_000_002)
        rng = random.Random(4)
        passed_once = False
        for _ in range(2000):
            who = self.mover(tid)
            if who is None:
                break
            v = self.bw.view(self.p[who].id, tid)
            if v["position"]["phase"] == "pass":
                three = rng.sample(v["position"]["hand"], 3)
                r = self.bw.move(self.p[who].id, tid, "pass " + " ".join(three))
                self.assertEqual(r["private"]["passed"], three)
                for name in NAMES:                         # nobody else ever sees what was passed
                    if name != who and not passed_once:
                        hist = json.dumps(self.bw.history(tid))
                        self.assertFalse(set(three) & set(re.findall(r"\b(?:10|[2-9AJQK])[SHDC]\b", hist)))
                passed_once = True
            else:
                self.bw.move(self.p[who].id, tid, rng.choice(v["legal"]))
        v = self.bw.view(self.p["Sandy"].id, tid)
        self.assertEqual(v["status"], "finished")
        self.assertIn("lowest score", v["result_text"])

    def test_hearts_rules(self):
        g = GAMES["hearts"]
        s = g.new({"players": 4, "seed": 11})
        s["names"] = ["A", "B", "C", "D"]
        with self.assertRaises(Exception):
            g.play(s, "play 2C")                            # it's the pass first
        for q in range(4):
            s, _ = g.play(s, "pass " + " ".join(s["hands"][q][:3]))
        self.assertEqual(s["phase"], "play")
        self.assertIn("2C", s["hands"][s["turn"]])
        self.assertEqual(g.legal_moves(s), ["play 2C"])

    def test_bottle_lines_stay_hidden_then_the_story_is_shelved(self):
        tid = self.table("bottle", seed=60_000_003)
        lines = {}
        for i in range(6):
            who = self.mover(tid)
            v = self.bw.view(self.p[who].id, tid)
            self.assertIn("before", v["position"])         # the line before yours, and only that
            if lines:
                self.assertEqual(v["position"]["before"], list(lines.values())[-1])
            line = f"Line {i} by {who}: the crab hummed a tune number {i}."
            for name in NAMES:                             # earlier lines: hidden from everyone else
                if name != who:
                    seen = self.seen_by(name, tid)
                    for old in list(lines.values())[:-1]:
                        self.assertNotIn(old, seen)
            self.bw.move(self.p[who].id, tid, "write " + line)
            lines[i] = line
            hist = json.dumps(self.bw.history(tid))
            self.assertNotIn(line, hist)                   # never in the move history
        v = self.bw.view(self.p["Coral"].id, tid)
        self.assertEqual(v["position"]["phase"], "vote")
        self.assertEqual([ln["text"] for ln in v["position"]["lines"]], list(lines.values()))   # revealed
        for vote in ("shelve everyone", "shelve residents", "shelve everyone"):
            self.bw.move(self.p[self.mover(tid)].id, tid, vote)
        v = self.bw.view(self.p["Sandy"].id, tid)
        self.assertEqual(v["status"], "finished")
        self.assertIn("goes on the bottle-stories shelf (for residents only)", v["result_text"])
        lib = self.beach.library
        bottles = lib.shelf(self.p["Pebble"].id, "all", "bottles")
        self.assertEqual(len(bottles), 1)
        self.assertEqual(bottles[0]["author"], "Sandy, Pebble and Coral")
        self.assertEqual(bottles[0]["audience"], "residents")
        self.assertEqual(lib.shelf(self.p["Pebble"].id, "all"), [])     # not on the books shelf
        self.beach.join(self.p["Pebble"].id, READINGROOM)
        self.assertIn("Sandy, Pebble and Coral", lib.command(self.p["Pebble"].id, "/bottles"))
        self.assertIn("shelf is empty", lib.command(self.p["Pebble"].id, "/allbooks"))
        page = lib.open(self.p["Pebble"].id, bottles[0]["id"])
        self.assertIn(lines[0], page["text"])

    def test_a_bottle_nobody_wants_to_keep_stays_off_the_shelf(self):
        tid = self.table("bottle", players=("Sandy", "Pebble"), seed=60_000_004)
        for i in range(4):
            who = ("Sandy", "Pebble")[self.bw.view(self.p["Sandy"].id, tid)["to_move"]]
            self.bw.move(self.p[who].id, tid, f"write part {i} of a short tale.")
        for vote in ("shelve everyone", "keep it here"):
            who = ("Sandy", "Pebble")[self.bw.view(self.p["Sandy"].id, tid)["to_move"]]
            self.bw.move(self.p[who].id, tid, vote)
        v = self.bw.view(self.p["Sandy"].id, tid)
        self.assertEqual(v["result_text"], "the table wrote a story of 4 lines together")
        self.assertEqual(self.beach.library.shelf(self.p["Sandy"].id, "all", "bottles"), [])
        with self.assertRaises(BeachError):
            self.beach.library.shelf(self.p["Sandy"].id, "all", "attic")


if __name__ == "__main__":
    unittest.main()
