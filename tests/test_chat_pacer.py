# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Becky Northaven and the AI-Beach contributors
"""The chat pacer (IRC-style flood control): a quick burst, then one line every few seconds; faster
lines wait their turn and post by themselves, never silently dropped (Becky 10-16, built 10-20)."""

from __future__ import annotations

import random
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from beach.core import SANDCHAT, Beach, BeachError  # noqa: E402
from tests.test_beach_core import FakeClock  # noqa: E402


class ChatPacerTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="beach-pacer-")
        self.clock = FakeClock()
        self.beach = Beach(self.dir, clock=self.clock, rng=random.Random(3))
        self.beach.update_settings({"posts_per_minute": 0})   # the pacer alone, here
        self.sandy, _ = self.beach.add_participant("Sandy", "agent")
        self.coral, _ = self.beach.add_participant("Coral", "person")
        for p in (self.sandy, self.coral):
            self.beach.join(p.id, SANDCHAT)

    def tearDown(self):
        self.beach.db.close()
        shutil.rmtree(self.dir, ignore_errors=True)

    def lines(self, who="Sandy"):
        return [m["text"] for m in self.beach.read(self.coral.id, SANDCHAT, limit=100)
                if m.get("author") == who and m["kind"] in ("say", "action")]

    def test_a_burst_posts_then_lines_wait_their_turn(self):
        answers = [self.beach.post(self.sandy.id, SANDCHAT, f"line {i}") for i in range(1, 9)]
        self.assertTrue(all(a["posted"] for a in answers[:6]))           # a quick burst goes straight out
        self.assertEqual([a.get("queued") for a in answers[6:]], [True, True])
        self.assertEqual(answers[6]["posts_in"], 2)
        self.assertEqual(answers[7]["posts_in"], 4)
        self.assertIn("posts by itself", answers[6]["note"])
        self.assertEqual(len(self.lines()), 6)
        self.clock.advance(2)
        self.beach.tick()
        self.assertEqual(self.lines()[-1], "line 7")
        self.clock.advance(2)
        self.beach.tick()
        self.assertEqual(self.lines()[-2:], ["line 7", "line 8"])          # in order, none lost

    def test_a_normal_pace_never_waits(self):
        for i in range(20):
            self.clock.advance(2)
            self.assertTrue(self.beach.post(self.sandy.id, SANDCHAT, f"steady {i}")["posted"])

    def test_too_many_waiting_is_refused_with_a_retry_after(self):
        for i in range(11):                                               # 6 posted + 5 waiting
            self.beach.post(self.sandy.id, SANDCHAT, f"x{i}")
        with self.assertRaises(BeachError) as e:
            self.beach.post(self.sandy.id, SANDCHAT, "one too many")
        self.assertEqual(e.exception.code, "rate_limited")
        self.assertTrue(e.exception.retry_after > 0)

    def test_leaving_drops_waiting_lines(self):
        for i in range(8):
            self.beach.post(self.sandy.id, SANDCHAT, f"y{i}")
        self.beach.part(self.sandy.id, SANDCHAT)
        self.clock.advance(30)
        self.beach.tick()
        self.assertNotIn("y7", self.lines())

    def test_actions_are_paced_too_and_each_person_has_their_own_pace(self):
        self.beach.update_settings({"action_cooldown_s": 0, "max_actions_in_a_row": 0})
        for i in range(6):
            self.beach.post(self.sandy.id, SANDCHAT, f"/me hops {i}")
        held = self.beach.post(self.sandy.id, SANDCHAT, "/me hops again")
        self.assertTrue(held["queued"])
        self.assertTrue(self.beach.post(self.coral.id, SANDCHAT, "I can still talk")["posted"])
        self.clock.advance(2)
        self.beach.tick()
        self.assertIn("Sandy hops again", self.lines())

    def test_off_when_the_keeper_sets_it_to_zero(self):
        self.beach.update_settings({"chat_pace_s": 0})
        self.assertTrue(all(self.beach.post(self.sandy.id, SANDCHAT, f"z{i}")["posted"] for i in range(12)))


if __name__ == "__main__":
    unittest.main()
