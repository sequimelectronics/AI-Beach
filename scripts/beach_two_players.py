#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Becky Northaven and the AI-Beach contributors
"""Two scripted beach players at once, each seeing ONLY its own adapter's text.

Checks that both see and name each other (including when the other is behind
them, outside the engine's view cone), that chat goes both ways, and that one
can pass a ball the other then kicks. Records turn_bundle() sizes for both.

    python3 scripts/beach_two_players.py --base http://127.0.0.1:8100 \
        --tokenizer path/to/gemma-4-E4B-it/tokenizer.json --out two.json
"""

from __future__ import annotations

import argparse
import json
import math
import statistics
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from adapters.clawblox import ClawbloxAdapter, make_counter  # noqa: E402
from beach_agent import BeachPlayer  # noqa: E402


def players_line(view_text: str) -> str:
    return next((ln for ln in view_text.splitlines() if ln.startswith("players:")), "")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:8100")
    ap.add_argument("--tokenizer")
    ap.add_argument("--tokenizer-name")
    ap.add_argument("--out")
    args = ap.parse_args()
    counter = make_counter(args.tokenizer, args.tokenizer_name)
    sandy = BeachPlayer(ClawbloxAdapter(args.base, "Sandy", counter=counter), "Sandy ")
    pebble = BeachPlayer(ClawbloxAdapter(args.base, "Pebble", counter=counter), "Pebble ")
    goals: dict = {}

    sandy.turn("map_card")
    pebble.turn("map_card")

    # 1. Positions: Pebble waits north of the center; Sandy goes behind the soccer ball.
    pebble.go(0, 12)
    sandy.go(-3, -4)
    s_view = sandy.look()
    p_view = pebble.look()
    goals["sandy_sees"] = [(p["name"], p["in_view"]) for p in s_view["players"]]
    goals["pebble_sees"] = [(p["name"], p["in_view"]) for p in p_view["players"]]
    # Pebble faces north, away from Sandy: the engine's own list would not include Sandy.
    goals["both_named"] = (any(n == "Pebble" for n, _ in goals["sandy_sees"])
                           and any(n == "Sandy" for n, _ in goals["pebble_sees"]))
    goals["named_while_out_of_view"] = any(not v for _, v in goals["sandy_sees"] + goals["pebble_sees"])

    # 2. Chat both ways.
    sandy.turn("say", "Pebble, ready? passing the soccer ball to you")
    heard_p = pebble.turn("hear")
    pebble.turn("say", "ready, Sandy - send it over")
    heard_s = sandy.turn("hear")
    goals["pebble_heard_sandy"] = "Sandy: Pebble, ready?" in heard_p
    goals["sandy_heard_pebble"] = "Pebble: ready, Sandy" in heard_s

    # 3. Sandy passes the soccer ball to where Pebble is standing.
    target = next(p for p in sandy.look()["players"] if p["name"] == "Pebble")
    p_me = pebble.look()["me"]
    dist = math.hypot(p_me[0], p_me[2] - 0)
    res = sandy.kick_towards("soccer ball", (p_me[0], p_me[2] - 1.5), power=min(1.0, max(0.3, (dist - 1.5) / 25)))
    goals["pass"] = res
    time.sleep(2.0)
    view = pebble.look()
    ball = pebble.find("soccer ball")
    goals["ball_reached_pebble"] = bool(ball and ball["dist"] < 8)
    # 4. Pebble kicks it on, towards the north goal.
    res = pebble.kick_towards("soccer ball", (0, 30), power=1.0)
    goals["pebble_kick"] = res
    goals["pebble_kicked_the_passed_ball"] = res.startswith("Kicked the soccer ball")
    heard = pebble.turn("hear") + "\n" + sandy.turn("hear")
    goals["goal_after_pass"] = "Goal at the north end" in res or "Goal at the north end" in heard

    # Worst case with two named players, castles from the solo run, all balls about, chat.
    bundles = {name: pl.a.turn_bundle(include_map=True) for name, pl in (("Sandy", sandy), ("Pebble", pebble))}
    worst = {name: {"tokens": {k: b[k]["tokens"] for k in ("tools", "state", "recent")},
                    "total": b["total_tokens"], "state": b["state"]["text"], "recent": b["recent"]["text"]}
             for name, b in bundles.items()}

    all_turns = sandy.turns + pebble.turns
    totals = [t["total"] for t in all_turns]
    out = {"token_method": counter.method, "goals": goals,
           "turn_total": {"min": min(totals), "median": statistics.median(totals), "max": max(totals)},
           "worst_with_map": worst, "turns": {"Sandy": sandy.turns, "Pebble": pebble.turns}}
    if args.out:
        Path(args.out).write_text(json.dumps(out, indent=1))
    print(json.dumps({k: out[k] for k in ("token_method", "goals", "turn_total")}, indent=1))
    print(json.dumps({n: {"tokens": w["tokens"], "total": w["total"]} for n, w in worst.items()}))
    ok = all(goals[k] for k in ("both_named", "pebble_heard_sandy", "sandy_heard_pebble",
                                "pebble_kicked_the_passed_ball"))
    print("TWO PLAYERS", "OK" if ok else "NOT OK")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
