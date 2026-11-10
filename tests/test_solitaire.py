# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Becky Northaven and the AI-Beach contributors
"""Solitaire: Klondike (draw one or three) and FreeCell, at a table for one."""

import json
import random
import unittest

from beach.games import GAMES, IllegalMove


def cards(*codes):
    return [{"c": c, "up": True} for c in codes]


class SolitaireTests(unittest.TestCase):
    def setUp(self):
        self.g = GAMES["solitaire"]

    def test_a_klondike_deal(self):
        s = self.g.new({"seed": 7})
        self.assertEqual([len(c) for c in s["tab"]], [1, 2, 3, 4, 5, 6, 7])
        self.assertTrue(all(c[-1]["up"] and not any(x["up"] for x in c[:-1]) for c in s["tab"]))
        self.assertEqual(len(s["stock"]), 24)
        everything = [x["c"] for c in s["tab"] for x in c] + s["stock"]
        self.assertEqual(len(set(everything)), 52)

    def test_face_down_cards_stay_hidden(self):
        s = self.g.new({"seed": 7})
        hidden = s["tab"][6][0]["c"]
        self.assertNotIn(hidden, json.dumps(self.g.view(s, 0)))
        self.assertNotIn(hidden, self.g.text(s, 0).split("Columns")[1])
        self.assertNotIn(s["stock"][0], json.dumps(self.g.view(s, 0)))

    def test_draw_one_three_and_turn_over(self):
        s = self.g.new({"seed": 7})
        s, _ = self.g.play(s, "draw")
        self.assertEqual((len(s["stock"]), len(s["waste"])), (23, 1))
        three = self.g.new({"seed": 7, "variant": "klondike3"})
        three, _ = self.g.play(three, "draw")
        self.assertEqual(len(three["waste"]), 3)
        self.assertEqual(len(self.g.view(three, 0)["waste"]), 3)
        while s["stock"]:
            s, _ = self.g.play(s, "draw")
        s, info = self.g.play(s, "draw")
        self.assertIn("Turned the waste back over", info["text"])
        self.assertEqual((len(s["stock"]), len(s["waste"])), (24, 0))

    def test_column_moves_turn_up_the_card_beneath(self):
        s = self.g.new({"seed": 1})
        s["tab"] = [[{"c": "2C", "up": False}] + cards("5H"), cards("6S"), [], [], [], [], []]
        s["stock"], s["waste"] = ["9D"], []
        self.assertIn("1>2", self.g.legal_moves(s))
        s, info = self.g.play(s, "column 1 to 2")
        self.assertEqual([x["c"] for x in s["tab"][1]], ["6S", "5H"])
        self.assertEqual(s["tab"][0], [{"c": "2C", "up": True}])    # the card underneath turns face up
        self.assertIn("to column 2", info["text"])

    def test_only_a_king_goes_into_an_empty_klondike_column(self):
        s = self.g.new({"seed": 1})
        s["tab"] = [cards("QH"), [{"c": "3C", "up": False}] + cards("KS"), [], [], [], [], []]
        s["stock"], s["waste"] = ["9D"], []
        legal = self.g.legal_moves(s)
        self.assertNotIn("1>3", legal)
        self.assertIn("2>3", legal)
        self.assertIn("1>2", legal)                                 # the red queen on the black king

    def test_foundations_build_up_by_suit_and_a_win(self):
        s = self.g.new({"seed": 1})
        s["found"] = {"S": 13, "H": 13, "D": 13, "C": 12}
        s["tab"] = [cards("KC"), [], [], [], [], [], []]
        s["stock"], s["waste"] = [], []
        s, info = self.g.play(s, "1>f")
        self.assertEqual(self.g.outcome(s)["winner"], 0)
        self.assertIn("All 52 cards are home", info["text"])

    def test_no_moves_left_ends_the_game(self):
        s = self.g.new({"seed": 1})
        s["tab"] = [cards("5H"), cards("9S"), cards("9C"), cards("8S"), cards("8C"), cards("7S"), cards("4H")]
        s["stock"], s["waste"] = [], ["AD"]
        s, info = self.g.play(s, "w>f")
        self.assertIn("No moves left", info["text"])
        self.assertIsNone(self.g.outcome(s)["winner"])
        self.assertIn("1 of 52", self.g.outcome(s)["reason"])

    def test_freecell_cells_and_runs(self):
        s = self.g.new({"seed": 3, "variant": "freecell"})
        self.assertEqual([len(c) for c in s["tab"]], [7, 7, 7, 7, 6, 6, 6, 6])
        self.assertTrue(all(x["up"] for c in s["tab"] for x in c))
        s["tab"] = [cards("9H", "8S", "7D"), cards("10C"), [], [], [], [], [], []]
        s["cells"] = ["AS", "2S", "3S", None]                       # one free cell, five empty columns
        s["found"] = {"S": 0, "H": 0, "D": 0, "C": 0}
        self.assertIn("1>2", self.g.legal_moves(s))
        s, _ = self.g.play(s, "1>2")
        self.assertEqual([x["c"] for x in s["tab"][1]], ["10C", "9H", "8S", "7D"])
        s, _ = self.g.play(s, "c1>f")
        self.assertEqual(s["found"]["S"], 1)
        s, _ = self.g.play(s, "2>c")
        self.assertEqual(s["cells"].count("7D"), 1)

    def test_a_freecell_run_is_limited_by_the_free_spaces(self):
        s = self.g.new({"seed": 3, "variant": "freecell"})
        s["tab"] = [cards("JD", "10S", "9H", "8S", "7D"), cards("QC"), cards("2C"), cards("3C"), cards("4C"),
                    cards("5C"), cards("6C"), cards("7C")]
        s["cells"] = ["AS", "2S", "3S", None]                       # room for 2: the run of 5 can't go
        self.assertNotIn("1>2", self.g.legal_moves(s))
        s["cells"] = [None, None, None, None]                        # room for 5
        self.assertIn("1>2", self.g.legal_moves(s))

    def test_variant_before_the_first_move_only(self):
        s = self.g.new({"seed": 5})
        self.assertIn("variant freecell", self.g.legal_moves(s))
        s, info = self.g.play(s, "variant freecell")
        self.assertEqual((s["variant"], len(s["tab"])), ("freecell", 8))
        self.assertIn("FreeCell", info["text"])
        s, _ = self.g.play(s, self.g.legal_moves(s)[-1])
        with self.assertRaises(IllegalMove):
            self.g.play(s, "variant klondike")
        self.assertEqual(self.g.rematch_options(s), {"variant": "freecell"})

    def test_bad_moves_say_so(self):
        s = self.g.new({"seed": 5})
        for bad in ("9>1", "w>f", "fly", "c1>2"):
            with self.assertRaises(IllegalMove, msg=bad):
                self.g.play(s, bad)

    def test_random_games_stay_legal_and_end(self):
        for variant in ("klondike", "klondike3", "freecell"):
            for seed in range(3):
                rng = random.Random(seed)
                s = self.g.new({"seed": seed, "variant": variant})
                for _ in range(600):
                    if self.g.outcome(s):
                        break
                    legal = [m for m in self.g.legal_moves(s) if not m.startswith("variant")]
                    s, _ = self.g.play(s, rng.choice(legal))
                    total = sum(len(c) for c in s["tab"]) + len(s["stock"]) + len(s["waste"]) + \
                        sum(1 for c in s["cells"] if c) + sum(s["found"].values())
                    self.assertEqual(total, 52, (variant, seed))

    def test_the_card_and_text(self):
        self.assertLess(len(self.g.card(7)), 1400)
        s = self.g.new({"seed": 5})
        t = self.g.text(s, 0)
        self.assertIn("Klondike, draw one", t)
        self.assertIn("7: ## ## ## ## ## ##", t)


if __name__ == "__main__":
    unittest.main()
