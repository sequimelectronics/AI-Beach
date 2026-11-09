# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Becky Northaven and the AI-Beach contributors
"""Go, 9x9: captures, the two forbidden moves, passing and area scoring."""

import random
import unittest

from beach.games import GAMES, IllegalMove


class GoTests(unittest.TestCase):
    def setUp(self):
        self.g = GAMES["go"]
        self.s = self.g.new({})

    def go(self, *moves):
        info = None
        for m in moves:
            self.s, info = self.g.play(self.s, m)
        return info

    def stone(self, name):
        return self.s["board"][(int(name[1]) - 1) * 9 + "ABCDEFGHJ".index(name[0])]

    def test_black_first_and_every_way_of_naming_a_point(self):
        self.assertEqual(self.g.to_move(self.s), 0)
        self.go("e5", "play D4", "F6.")
        self.assertEqual((self.stone("E5"), self.stone("D4"), self.stone("F6")), ("x", "o", "x"))
        self.assertEqual(self.g.to_move(self.s), 1)

    def test_corners_and_the_missing_i(self):
        self.go("A1", "J9")
        self.assertEqual((self.stone("A1"), self.stone("J9")), ("x", "o"))
        for bad in ("I5", "K1", "A0", "A10", "", "somewhere"):
            with self.assertRaises(IllegalMove, msg=bad):
                self.g.play(self.s, bad)
        with self.assertRaises(IllegalMove) as e:
            self.g.play(self.s, "I5")
        self.assertIn("no I column", e.exception.reason)
        with self.assertRaises(IllegalMove):
            self.g.play(self.s, "A1")                                 # occupied

    def test_a_capture_takes_the_stones_off(self):
        info = self.go("B1", "A1", "E5", "pass", "A2")                # a White stone in the corner, surrounded
        self.assertEqual(self.stone("A1"), ".")
        self.assertEqual(self.s["captures"], [1, 0])
        self.assertIn("capturing 1", info["text"])

    def test_a_group_is_captured_together(self):
        self.go("B1", "A1", "B2", "A2")                               # two White stones up the edge, one liberty left
        self.assertEqual(self.s["board"].count("o"), 2)
        self.go("A3")
        self.assertEqual(self.s["board"].count("o"), 0)
        self.assertEqual(self.s["captures"], [2, 0])

    def test_a_move_with_no_liberties_is_refused(self):
        self.go("B1", "E5", "A2", "E6", "E7")                         # White to move; A1 is walled in
        with self.assertRaises(IllegalMove) as e:
            self.g.play(self.s, "A1")
        self.assertIn("no empty point", e.exception.reason)
        self.assertNotIn("A1", self.g.legal_moves(self.s))

    def test_unless_the_move_captures_first(self):
        self.go("A3", "A2", "B2", "B1", "C1", "E5")                   # White's A2 and B1 each have only A1 left
        self.assertIn("A1", self.g.legal_moves(self.s))
        self.go("A1")
        self.assertEqual(self.stone("A1"), "x")
        self.assertEqual((self.stone("A2"), self.stone("B1")), (".", "."))
        self.assertEqual(self.s["captures"], [2, 0])

    def test_ko_cant_recreate_the_board(self):
        # x . at C3 side and the classic shape: White takes, Black may not retake at once.
        self.go("C4", "D4", "B3", "E3", "C2", "D2", "pass", "C3")     # White's C3 is in atari, at D3
        self.go("D3")                                                 # Black captures C3
        self.assertEqual(self.stone("C3"), ".")
        with self.assertRaises(IllegalMove) as e:
            self.g.play(self.s, "C3")                                 # White retaking would recreate the board
        self.assertIn("repeat", e.exception.reason)
        self.assertNotIn("C3", self.g.legal_moves(self.s))
        self.go("J9", "J1")                                           # a move elsewhere each changes the board
        self.go("C3")                                                 # so now the retake is fine
        self.assertEqual(self.stone("C3"), "o")

    def test_two_passes_end_it_and_area_is_counted(self):
        self.go("E1", "F1", "E2", "F2", "E3", "F3", "E4", "F4", "E5", "F5", "E6", "F6", "E7", "F7", "E8", "F8", "E9", "F9")
        self.go("pass")
        self.assertIn("if you pass too", self.g.text(self.s, 1))
        self.assertIsNone(self.g.outcome(self.s))
        self.go("pass")
        over = self.g.outcome(self.s)
        self.assertEqual(over["score"]["black"], 45)                  # columns A-E: 5 x 9
        self.assertEqual(over["score"]["white"], 36 + 6.5)            # columns F-J: 4 x 9, plus komi
        self.assertEqual(over["winner"], 0)
        self.assertIn("Black wins by 2.5", over["reason"])
        self.assertIsNone(self.g.to_move(self.s))
        self.assertEqual(self.g.legal_moves(self.s), [])

    def test_a_region_touching_both_colors_is_nobodys(self):
        self.go("A1", "J9", "pass", "pass")
        t = self.g.outcome(self.s)["score"]
        self.assertEqual((t["black"], t["white"]), (1, 1 + 6.5))
        self.assertEqual(self.g.outcome(self.s)["winner"], 1)

    def test_a_pass_clears_only_with_a_stone(self):
        self.go("pass", "E5", "pass")
        self.assertIsNone(self.g.outcome(self.s))

    def test_the_text_helps_a_small_model(self):
        self.go("B1", "A1")
        text = self.g.text(self.s, 0)
        self.assertIn("A B C D E F G H J", text)
        self.assertIn(" 1  o x", text)
        self.assertIn("You are Black (x).", text)
        self.assertIn("you can capture 1 stone by playing A2", text)
        self.s, _ = self.g.play(self.s, "E5")
        self.assertIn("your stones at A1 have one liberty left, at A2", self.g.text(self.s, 1))

    def test_the_view_and_card(self):
        self.go("E5")
        v = self.g.view(self.s, 0)
        self.assertEqual((v["kind"], v["size"], v["last"], v["ply"]), ("go", 9, "E5", 1))
        self.assertEqual(v["out"], [])                                  # the page reads it for games with no draw offers
        self.assertLess(len(self.g.card(7)), 1400)
        self.assertIn("/tables/7/move", self.g.card(7))

    def test_random_games_always_finish_and_stay_legal(self):
        for seed in range(6):
            rng = random.Random(seed)
            s = self.g.new({})
            for _ in range(400):
                if self.g.outcome(s):
                    break
                legal = self.g.legal_moves(s)
                self.assertTrue(legal)
                points = [m for m in legal if m != "pass"]
                s, _ = self.g.play(s, rng.choice(points) if points and rng.random() < 0.97 else "pass")
            self.assertTrue(self.g.outcome(s), seed)
            self.assertEqual(len(s["board"]), 81)


if __name__ == "__main__":
    unittest.main()
