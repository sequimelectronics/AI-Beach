#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Becky Northaven and the AI-Beach contributors
"""Capture raw Clawblox observations as unit-test fixtures for adapters/clawblox.

Run against a mesa-island copy with max_players >= 2. Writes generated game
data (JSON) into tests/fixtures/clawblox/. Uses the adapter only to move
around; every saved file is the server's raw response.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from adapters.clawblox import ClawbloxAdapter  # noqa: E402
from adapters.clawblox.world import held_object, parse_observation  # noqa: E402

OUT = Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "clawblox"


def save(name: str, text: str) -> dict:
    doc = json.loads(text)
    (OUT / name).write_text(json.dumps(doc, separators=(",", ":")) + "\n")
    print("saved", name, len(text), "bytes")
    return doc


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:8081")
    args = ap.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)

    a = ClawbloxAdapter(args.base, "Coral")
    save("spawn.json", a.full_look())
    a.act("MoveTo", {"position": [12.6, 0, -1.3]})
    save("at_pile.json", a.full_look())
    snap = parse_observation(json.loads(a.full_look()))
    blk = min((e for e in snap.objects if e.kind == "block"),
              key=lambda e: sum((p - q) ** 2 for p, q in zip(e.pos, snap.me)))
    print(a.act("Pickup", {"position": list(blk.pos)}))
    doc = save("holding_block.json", a.full_look())
    assert held_object(parse_observation(doc)) is not None, "expected a held block"
    print(a.act("Place", {"position": [snap.me[0] - 3, 0.6, snap.me[2]]}))

    print(a.act("MoveTo", {"position": [-31.4, 3, 26.9], "jump": True}))
    save("on_plateau.json", a.full_look())
    rock = next(e for e in parse_observation(json.loads(a.full_look())).objects if e.kind == "rock")
    print(a.act("Pickup", {"position": list(rock.pos)}))
    print(a.act("Throw", {"direction": [1, -0.3, 0], "speed": 10}))
    save("after_rock_throw.json", a.full_look())

    # Two players: Drift joins at spawn; Coral walks to spawn and faces Drift,
    # then walks past so Drift is behind Coral (outside the server's view cone).
    b = ClawbloxAdapter(args.base, "Drift")
    b.look()
    print(a.act("MoveTo", {"position": [8, 0, 0]}))
    print(a.act("MoveTo", {"position": [4, 0, 0]}))
    save("two_players_in_view.json", a.full_look())
    print(a.act("MoveTo", {"position": [12, 0, 0]}))
    save("two_players_behind.json", a.full_look())

    # Chat: several messages, some in the same second.
    for i in range(3):
        a.say(f"coral message {i}")
        b.say(f"drift message {i}")
    status, text = a.t.request("GET", "/chat/messages?limit=100", None, a.session)
    save("chat_messages.json", text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
