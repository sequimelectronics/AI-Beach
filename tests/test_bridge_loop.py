# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Becky Northaven and the AI-Beach contributors
"""The bridge's loop (10-19, the keeper: a new arrival took up to 15 s to wear their own look): when the
door's list changes (someone was just let in), the bridge reports at once, which brings back their look,
instead of waiting for the next regular report."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from beach import bridge  # noqa: E402


class FakeBridge:
    def __init__(self, doors):
        self.doors = list(doors)   # the door's signature at each sync
        self.last_door = None
        self.steps = []
        self.tick = 0

    def sync_door(self):
        self.last_door = self.doors[min(self.tick, len(self.doors) - 1)]

    def sync_events(self):
        pass

    def step(self):
        self.steps.append(self.tick)


class BridgeLoopTests(unittest.TestCase):
    def run_ticks(self, b, n, every=10.0):
        clock = {"t": 1000.0}

        def keep_going():
            return b.tick < n

        def sleep(_):
            b.tick += 1
            clock["t"] += 1.0

        with mock.patch.object(bridge.time, "sleep", sleep), \
                mock.patch.object(bridge.time, "monotonic", lambda: clock["t"]):
            bridge.run_loop(b, every, keep_going=keep_going)

    def test_reports_at_once_when_someone_is_let_in(self):
        b = FakeBridge(["nobody", "nobody", "nobody", "Coral", "Coral", "Coral"])
        self.run_ticks(b, 6)
        # The first report (tick 0) and one the moment Coral was let in (tick 3), not ten seconds later.
        self.assertEqual(b.steps, [0, 3])

    def test_otherwise_every_few_seconds_as_before(self):
        b = FakeBridge(["same"])
        self.run_ticks(b, 25)
        self.assertEqual(b.steps, [0, 10, 20])


if __name__ == "__main__":
    unittest.main()
