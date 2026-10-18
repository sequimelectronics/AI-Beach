# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Becky Northaven and the AI-Beach contributors
"""The beach world's own files agree with each other: the regions the engine hears by (world.toml) are the
regions the agents' map shows (REGIONS in main.lua), and the long-beach layout hangs together (10-18)."""

import re
import sys
import tomllib
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
BEACH = ROOT / "worlds" / "beach"


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
        for i, (a, ax, az) in enumerate(regions):
            for b, bx, bz in regions[i + 1:]:
                apart_x = bx[0] >= ax[1] or ax[0] >= bx[1]
                apart_z = bz[0] >= az[1] or az[0] >= bz[1]
                self.assertTrue(apart_x or apart_z, f"{a} and {b} overlap")
        # Sight is shorter than the island, so a small model isn't sent the whole island every turn.
        self.assertLessEqual(self.toml["observation"]["radius"], 40)

    def test_the_island_shape_the_agents_are_told(self):
        # The adapter's on_land mirrors the world's: the middle, a rounded corner, the bumps.
        from adapters.clawblox.compact import on_land
        island = {"half": 80, "corner_r": 26, "bumps": [
            {"name": "the headland", "x": 70, "z": 70, "r": 22},
            {"name": "the castle beach", "x": -80, "z": -30, "r": 14}]}
        layout = {"island": island}
        self.assertTrue(on_land(layout, (0, 0, 0)))
        self.assertTrue(on_land(layout, (-79, 0, 0)))            # a straight coast
        self.assertFalse(on_land(layout, (-79, 0, 79)))          # the north-west corner is rounded off
        self.assertTrue(on_land(layout, (79, 0, 79)))            # ...but the headland fills the north-east
        self.assertTrue(on_land(layout, (-90, 0, -30)))          # the castle beach bulges out
        self.assertFalse(on_land(layout, (90, 0, 0)))            # sea
        self.assertIsNone(on_land({}, (0, 0, 0)))                # not an island world
        lua = (BEACH / "main.lua").read_text(encoding="utf-8")
        self.assertIn("half = 80, corner_r = 26", lua)          # the numbers above are the world's


if __name__ == "__main__":
    unittest.main()
