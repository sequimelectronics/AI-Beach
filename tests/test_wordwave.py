# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Becky Northaven and the AI-Beach contributors
"""Word Wave: secret words, a reveal each tide, and winning together."""

import json
import unittest

from beach.games import GAMES, IllegalMove


class WordWaveTests(unittest.TestCase):
    def setUp(self):
        self.g = GAMES["wordwave"]
        self.s = self.g.new({"players": 3})
        self.s["names"] = ["Coral", "Pebble", "Sandy"]

    def go(self, *words):
        for w in words:
            self.s, info = self.g.play(self.s, w)
        return info

    def test_a_word_stays_hidden_until_the_reveal(self):
        info = self.go("say doohicky")
        everything = json.dumps({k: v for k, v in info.items() if k != "private"})
        self.assertNotIn("doohicky", everything)
        self.assertIn("doohicky", info["private"])
        for seat in (1, 2, None):
            self.assertNotIn("doohicky", self.g.text(self.s, seat))
            self.assertNotIn("doohicky", json.dumps(self.g.view(self.s, seat)))
        self.assertIn("doohicky", self.g.text(self.s, 0))              # your own word is yours to see

    def test_the_reveal_shows_every_word_and_the_next_tide_begins(self):
        info = self.go("doohicky", "whatsit", "thingamajig")
        self.assertIn("Tide 1: Coral: doohicky, Pebble: whatsit, Sandy: thingamajig", info["text"])
        self.assertIsNone(self.g.outcome(self.s))
        self.assertEqual(self.g.to_move(self.s), 0)
        self.assertIn("tide 1: Coral: doohicky", self.g.text(self.s, None))

    def test_everyone_saying_the_same_word_wins_together(self):
        info = self.go("whatsit", "Whatsit.", "say whatsits")          # any case, punctuation, a plain plural
        over = self.g.outcome(self.s)
        self.assertTrue(over["together"])
        self.assertIn("the waves met", over["text"])
        self.assertIn("The waves met", info["text"])
        self.assertIsNone(self.g.to_move(self.s))
        self.assertEqual(self.g.legal_moves(self.s), [])
        self.assertEqual(self.g.view(self.s, 0)["tide"], 1)                  # still the tide it was won on

    def test_a_shown_word_cant_be_used_again(self):
        self.go("doohicky", "whatsit", "thingamajig")
        for again in ("doohicky", "WHATSIT", "whatsits"):
            with self.assertRaises(IllegalMove) as e:
                self.g.play(self.s, again)
            self.assertIn("earlier tide", e.exception.reason)

    def test_the_tide_can_go_out(self):
        self.s = self.g.new({"players": 2, "tides": 3})
        self.go("anchor", "buoy", "cove", "dune", "eddy", "foam")
        self.assertIn("the tide went out", self.g.outcome(self.s)["text"])

    def test_one_word_and_not_the_placeholder(self):
        for bad in ("two words", "say <one word of your own>", "say (your own one word)", "12345", "", "x" * 25):
            with self.assertRaises(IllegalMove, msg=bad):
                self.g.play(self.s, bad)
        self.assertEqual(self.s["words"], {})

    def test_the_card_gives_no_word_to_recite(self):
        # The Rule of Doohicky: if every model copied an example word, the table would "win" on the first tide.
        self.assertIn("say (your own one word)", self.g.card(7))
        self.assertLess(len(self.g.card(7)), 1400)

    def test_someone_leaving_mid_tide(self):
        self.go("doohicky", "whatsit")
        self.s, out = self.g.resign(self.s, 2)                          # the last word owed leaves: the tide reveals
        self.assertIsNone(out)
        self.assertEqual(len(self.s["past"]), 1)
        self.assertEqual(self.s["past"][0], {"0": "doohicky", "1": "whatsit"})
        self.s, out = self.g.resign(self.s, 1)                          # one left: there's no one to meet
        self.assertIn("emptied", out["text"])

    def test_someone_leaving_takes_their_word_with_them(self):
        self.go("doohicky")
        self.s, out = self.g.resign(self.s, 0)
        self.assertIsNone(out)
        self.assertEqual(self.s["words"], {})
        self.assertEqual(self.g.to_move(self.s), 1)


if __name__ == "__main__":
    unittest.main()
