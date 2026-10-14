"""Rules tests for checkers (beach/games/checkers.py): standard 8x8 English draughts.

Standard library only. Positions are built with Checkers.from_pieces({"c3": "b", ...}):
b/w = Black/White men, B/W = kings. Black (seat 0) moves up the board.
"""

from __future__ import annotations

import random
import re
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from beach.games import GAMES, IllegalMove  # noqa: E402
from beach.games.checkers import Checkers, parse_sq  # noqa: E402

G = Checkers()
P = Checkers.from_pieces


def board_of(state) -> dict:
    return G.view(state, None)["board"]


class OpeningTests(unittest.TestCase):
    def test_registered(self):
        self.assertIs(type(GAMES["checkers"]), Checkers)
        self.assertEqual(G.seats, 2)

    def test_start_position(self):
        s = G.new({})
        b = board_of(s)
        self.assertEqual(sum(1 for p in b.values() if p == "b"), 12)
        self.assertEqual(sum(1 for p in b.values() if p == "w"), 12)
        self.assertEqual(b["a1"], "b")
        self.assertEqual(b["h8"], "w")
        self.assertNotIn("a2", b)           # pieces only on dark squares
        self.assertEqual(G.to_move(s), 0)   # Black first

    def test_black_opening_moves(self):
        self.assertEqual(G.legal_moves(G.new({})),
                         ["a3-b4", "c3-b4", "c3-d4", "e3-d4", "e3-f4", "g3-f4", "g3-h4"])

    def test_white_cannot_move_first(self):
        with self.assertRaises(IllegalMove) as cm:
            G.play(G.new({}), "b6-a5")
        self.assertIn("no piece on b6", cm.exception.reason)


class MovementTests(unittest.TestCase):
    def test_men_move_forward_only(self):
        s = P({"d4": "b", "e7": "w"})
        self.assertEqual(G.legal_moves(s), ["d4-c5", "d4-e5"])
        s = P({"d4": "b", "e7": "w"}, turn=1)
        self.assertEqual(G.legal_moves(s), ["e7-d6", "e7-f6"])

    def test_kings_move_both_ways(self):
        s = P({"d4": "B", "a7": "w"})
        self.assertEqual(sorted(G.legal_moves(s)), ["d4-c3", "d4-c5", "d4-e3", "d4-e5"])

    def test_blocked_by_own_pieces_and_edges(self):
        s = P({"a3": "b", "b4": "b", "h8": "w"})
        self.assertEqual(G.legal_moves(s), ["b4-a5", "b4-c5"])  # a3's only square is taken

    def test_man_crowned_on_far_row(self):
        s = P({"c7": "b", "a1": "w"})
        s2, info = G.play(s, "c7-d8")
        self.assertTrue(info["crowned"])
        self.assertEqual(board_of(s2)["d8"], "B")
        s = P({"d2": "w", "h8": "b"}, turn=1)
        s2, info = G.play(s, "d2-c1")
        self.assertEqual(board_of(s2)["c1"], "W")


class CaptureTests(unittest.TestCase):
    def test_captures_are_compulsory(self):
        s = P({"c3": "b", "g3": "b", "d4": "w", "h8": "w"})
        self.assertEqual(G.legal_moves(s), ["c3xe5"])
        with self.assertRaises(IllegalMove) as cm:
            G.play(s, "g3-h4")
        self.assertEqual(cm.exception.reason, "a capture is available, and captures are compulsory")

    def test_capture_removes_the_piece(self):
        s = P({"c3": "b", "d4": "w", "h8": "w"})
        s2, info = G.play(s, "c3xe5")
        self.assertEqual(info["captured"], ["d4"])
        self.assertEqual(board_of(s2), {"e5": "b", "h8": "w"})

    def test_men_do_not_capture_backwards(self):
        s = P({"e5": "b", "d4": "w", "a7": "w"})
        self.assertNotIn("e5xc3", G.legal_moves(s))
        s = P({"e5": "B", "d4": "w", "a7": "w"})
        self.assertEqual(G.legal_moves(s), ["e5xc3"])   # a king does

    def test_multi_jump_must_continue(self):
        s = P({"a1": "b", "b2": "w", "d4": "w", "h8": "w"})
        self.assertEqual(G.legal_moves(s), ["a1xc3xe5"])
        with self.assertRaises(IllegalMove) as cm:
            G.play(s, "a1xc3")
        self.assertIn("must", cm.exception.reason)
        s2, info = G.play(s, "a1xc3xe5")
        self.assertEqual(info["captured"], ["b2", "d4"])
        self.assertEqual(board_of(s2), {"e5": "b", "h8": "w"})

    def test_multi_jump_with_a_choice_of_paths(self):
        s = P({"a1": "b", "b2": "w", "d4": "w", "d6": "w", "f6": "w", "h8": "w"})
        self.assertEqual(G.legal_moves(s), ["a1xc3xe5xc7", "a1xc3xe5xg7"])
        s2, info = G.play(s, "a1xc3xe5xg7")
        self.assertEqual(info["captured"], ["b2", "d4", "f6"])
        self.assertEqual(board_of(s2), {"g7": "b", "d6": "w", "h8": "w"})
        s3, info = G.play(s, "a1xc3xe5xc7")
        self.assertEqual(board_of(s3), {"c7": "b", "f6": "w", "h8": "w"})

    def test_any_capture_may_be_chosen_not_only_the_longest(self):
        # a1 can take two pieces; e3 can take one (d4 either way round, or f4).
        s = P({"a1": "b", "b2": "w", "d4": "w", "e3": "b", "f4": "w", "a7": "w"})
        self.assertEqual(G.legal_moves(s), ["a1xc3xe5", "e3xc5", "e3xg5"])
        G.play(s, "e3xg5")                    # the shorter capture is legal

    def test_crowned_mid_sequence_ends_the_move(self):
        # d6 jumps e7 to f8 and is crowned; as a king it could go on over g7, but the move ends.
        s = P({"d6": "b", "e7": "w", "g7": "w", "a1": "w"})
        self.assertEqual(G.legal_moves(s), ["d6xf8"])
        s2, info = G.play(s, "d6xf8")
        self.assertTrue(info["crowned"])
        self.assertEqual(board_of(s2)["f8"], "B")
        self.assertEqual(board_of(s2)["g7"], "w")   # still there
        with self.assertRaises(IllegalMove):
            G.play(s, "d6xf8xh6")

    def test_a_king_keeps_jumping(self):
        s = P({"f8": "B", "g7": "w", "e5": "w", "a1": "w"})
        # f8 x g7 -> h6, h6 x ... nothing; f8 can't jump e7 (empty); so one capture
        self.assertEqual(G.legal_moves(s), ["f8xh6"])
        s = P({"b2": "B", "c3": "w", "e5": "w", "e3": "w", "a7": "w"})
        self.assertEqual(sorted(G.legal_moves(s)), ["b2xd4xf2", "b2xd4xf6"])

    def test_no_piece_is_jumped_twice_and_landings_are_empty(self):
        rng = random.Random(4)
        squares = [f"{'abcdefgh'[f]}{r + 1}" for r in range(8) for f in range(8) if (f + r) % 2 == 0]
        checked = 0
        for _ in range(400):
            picks = rng.sample(squares, rng.randint(4, 14))
            pieces = {sq: rng.choice("bBwW") for sq in picks}
            s = P(pieces, turn=rng.randint(0, 1))
            for m in G.legal_moves(s):
                if "x" not in m:
                    continue
                path = re.split("x", m)
                jumped = []
                for a, b in zip(path, path[1:]):
                    (fa, ra), (fb, rb) = parse_sq(a), parse_sq(b)
                    jumped.append(((fa + fb) // 2, (ra + rb) // 2))
                self.assertEqual(len(jumped), len(set(jumped)), m)
                s2, info = G.play(s, m)
                self.assertEqual(len(info["captured"]), len(path) - 1)
                checked += 1
        self.assertGreater(checked, 50)


class EndingTests(unittest.TestCase):
    def test_win_by_capturing_everything(self):
        s = P({"c3": "b", "d4": "w"})
        s2, _ = G.play(s, "c3xe5")
        self.assertEqual(G.outcome(s2), {"winner": 0, "reason": "all pieces captured"})
        self.assertIsNone(G.to_move(s2))
        self.assertEqual(G.legal_moves(s2), [])
        with self.assertRaises(IllegalMove):
            G.play(s2, "e5-f6")

    def test_win_by_blocking(self):
        # White's only man on a8... (a8 is light) -> h8 with g7 blocked by Black and f6 guarded.
        s = P({"h8": "w", "g7": "b", "f6": "b", "a1": "b"}, turn=0)
        s2, _ = G.play(s, "a1-b2")
        self.assertEqual(G.outcome(s2), {"winner": 0, "reason": "no moves left"})

    def test_draw_after_quiet_moves(self):
        s = P({"a1": "B", "h8": "W"}, quiet_limit=2)
        for m in ("a1-b2", "h8-g7", "b2-a1", "g7-h8"):
            self.assertIsNone(G.outcome(s))
            s, _ = G.play(s, m)
        self.assertEqual(G.outcome(s), {"winner": None, "reason": "2 moves each with no capture"})

    def test_capture_resets_the_quiet_count(self):
        s = P({"a1": "B", "h8": "W", "c3": "b", "d4": "w"}, quiet_limit=40)
        s, _ = G.play(s, "c3xe5")
        self.assertEqual(s["quiet"], 0)
        s, _ = G.play(s, "h8-g7")
        self.assertEqual(s["quiet"], 1)

    def test_default_quiet_limit_is_forty_each(self):
        self.assertEqual(G.new({})["quiet_limit"], 40)


class NotationTests(unittest.TestCase):
    def test_lenient_spelling(self):
        s = G.new({})
        for m in ("C3-D4", " c3-d4 ", "c3 - d4"):
            s2, info = G.play(s, m)
            self.assertEqual(info["move"], "c3-d4")

    def test_reasons(self):
        s = G.new({})
        cases = {"c3d4": "write a move like", "d4-e5": "no piece on d4", "a1-b2": "can't move",
                 "c3-c4": "isn't legal", "": "write a move like"}
        for move, reason in cases.items():
            with self.assertRaises(IllegalMove, msg=move) as cm:
                G.play(s, move)
            self.assertIn(reason, cm.exception.reason, move)

    def test_text_board(self):
        t = G.text(G.new({}), 0).splitlines()
        self.assertEqual(t[0], "8 . w . w . w . w")
        self.assertEqual(t[7], "1 b . b . b . b .")
        self.assertEqual(t[8], "  a b c d e f g h")

    def test_card_is_short(self):
        self.assertLess(len(G.card(7)) / 4, 250)
        self.assertIn("/tables/7/move", G.card(7))


if __name__ == "__main__":
    unittest.main()
