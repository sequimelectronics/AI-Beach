# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Becky Northaven and the AI-Beach contributors
"""The beach world's own files agree with each other: the regions the engine hears by (world.toml) are the
regions the agents' map shows (REGIONS in main.lua), and the long-beach layout hangs together (10-18)."""

import re
import tomllib
import unittest
from pathlib import Path

BEACH = Path(__file__).resolve().parents[1] / "worlds" / "beach"


def lua_regions() -> list[tuple[str, list[float], list[float]]]:
    lua = (BEACH / "main.lua").read_text(encoding="utf-8")
    block = lua[lua.index("local REGIONS = {"):]
    block = block[:block.index("\n}")]
    rows = re.findall(r'name = "([^"]+)", x = \{ (-?[\d.]+), (-?[\d.]+) \}, z = \{ (-?[\d.]+), (-?[\d.]+) \}', block)
    return [(n, [float(x0), float(x1)], [float(z0), float(z1)]) for n, x0, x1, z0, z1 in rows]


class BeachWorldFilesTest(unittest.TestCase):
    def setUp(self):
        self.toml = tomllib.loads((BEACH / "world.toml").read_text(encoding="utf-8"))

    def test_speech_regions_match_the_map(self):
        speech = self.toml["speech"]
        self.assertEqual(speech["mode"], "regions")
        engine = [(r["name"], r["x"], r["z"]) for r in speech["regions"]]
        self.assertEqual(engine, lua_regions())
        self.assertGreaterEqual(len(engine), 2)

    def test_regions_are_apart_and_agents_see_only_nearby(self):
        regions = lua_regions()
        for i, (a, _, az) in enumerate(regions):
            for b, _, bz in regions[i + 1:]:
                gap = max(bz[0] - az[1], az[0] - bz[1])
                self.assertGreater(gap, 0, f"{a} and {b} overlap")
        # Sight is shorter than the beach, so a small model isn't sent the whole beach every turn.
        self.assertLessEqual(self.toml["observation"]["radius"], 40)


if __name__ == "__main__":
    unittest.main()
