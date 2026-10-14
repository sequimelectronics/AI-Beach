#!/usr/bin/env python3
"""Capture raw beach observations as unit-test fixtures (tests/fixtures/beach/).

Run against a fresh copy of worlds/beach. Uses the adapter only to move things
around; every saved file is the server's raw /observe response.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from adapters.clawblox import ClawbloxAdapter  # noqa: E402

OUT = Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "beach"


def save(name: str, text: str) -> dict:
    doc = json.loads(text)
    (OUT / name).write_text(json.dumps(doc, separators=(",", ":")) + "\n")
    print("saved", name, len(text), "bytes")
    return doc


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:8100")
    args = ap.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)

    a = ClawbloxAdapter(args.base, "Sandy")
    save("spawn.json", a.full_look())

    # A good castle in plot 1 (3 blocks + flag) and a bad one in plot 4 (it falls).
    a.act("MoveTo", {"position": [-6.3, 0, -18]})
    y = 0.0
    for shape, h in (("block", 1), ("block", 1), ("block", 1), ("flag", 1.5)):
        a.act("Mold", {"shape": shape})
        a.act("Place", {"position": [-9.5, y + h / 2 + 0.05, -18]})
        y += h
    a.act("Mold", {"shape": "tower"})
    save("holding_piece.json", a.full_look())
    a.act("Place", {"position": [-7.5, 1.05, -21]})  # a loose tower outside any plot
    time.sleep(2)
    save("castle_near.json", a.full_look())
    a.act("MoveTo", {"position": [-6.3, 0, 18]})
    a.act("Mold", {"shape": "tower"})
    a.act("Place", {"position": [-9.5, 1.05, 18]})
    a.act("Mold", {"shape": "wall"})
    a.act("Place", {"position": [-8.6, 2.55, 18]})
    time.sleep(2.5)
    a.act("MoveTo", {"position": [4, 0, 0]})
    save("castles_far.json", a.full_look())

    # A ball in the sea.
    a.act("MoveTo", {"position": [3.8, 0, -10]})
    print(a.act("Kick", {"direction": [1, 0, 0], "power": 1.0}))
    save("ball_in_sea.json", a.full_look())

    # A second player, behind Sandy (outside the engine's view cone).
    b = ClawbloxAdapter(args.base, "Pebble")
    b.act("MoveTo", {"position": [0, 0, -14]})
    a.act("MoveTo", {"position": [0, 0, -4]})
    a.act("MoveTo", {"position": [0, 0, 2]})  # walking north: Pebble is behind
    save("two_players_behind.json", a.full_look())
    return 0


if __name__ == "__main__":
    sys.exit(main())
