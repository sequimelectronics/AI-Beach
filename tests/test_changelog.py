# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Becky Northaven and the AI-Beach contributors
"""CHANGELOG.md stays readable: dated sections, newest first, and every entry says what kind of change it is,
so keepers can spot a security update at a glance (the keeper's ask, 11-02)."""

from __future__ import annotations

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
KINDS = ("Security", "Feature", "Fix", "Mod", "Docs")


class ChangelogTests(unittest.TestCase):
    def setUp(self):
        self.text = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")

    def test_every_entry_is_tagged(self):
        body = self.text.split("\n## ", 1)[1]           # past the key at the top
        for line in body.splitlines():
            if line.startswith("- "):
                self.assertRegex(line, r"^- \*\*(%s)\*\*: " % "|".join(KINDS), line)

    def test_dated_sections_newest_first(self):
        dates = re.findall(r"^## (\d{4}-\d{2}-\d{2})", self.text, re.M)
        self.assertTrue(dates)
        self.assertEqual(dates, sorted(dates, reverse=True))

    def test_every_engine_patch_is_in_the_changelog(self):
        # A new patch changes the engine keepers build: it must be announced (and say whether it's security).
        named = {"clawblox-spectate-ws-cap.patch": "patch 12", "clawblox-no-npx-esbuild.patch": "patch 11",
                 "clawblox-http1-and-crate-bumps.patch": "patch 13"}
        for patch, words in named.items():
            self.assertTrue((ROOT / "patches" / patch).exists(), patch)
            self.assertIn(words, self.text, patch)
        self.assertEqual(len(list((ROOT / "patches").glob("clawblox-*.patch"))), 13,
                         "a new engine patch: add it to CHANGELOG.md and to the list in this test")


if __name__ == "__main__":
    unittest.main()
