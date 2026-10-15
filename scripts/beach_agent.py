#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Becky Northaven and the AI-Beach contributors
"""Scripted beach player that sees ONLY the adapter's text output.

Proves the compact beach view is enough to play. Reading only the map card,
look() text, one-line act() results and hear() lines, it must:
  1. kick a ball into a goal and see the goal announced,
  2. retrieve a ball that went into the sea,
  3. build a 3-high castle in a plot that stands,
  4. build one badly and see it fall,
then measure the worst case (next to a finished castle with all balls nearby).

One "turn" = one turn_bundle() (what a host would get) + one tool call.

    python3 scripts/beach_agent.py --base http://127.0.0.1:8100 \
        --tokenizer path/to/gemma-4-E4B-it/tokenizer.json --out beach_run.json
"""

from __future__ import annotations

import argparse
import json
import math
import re
import statistics
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from adapters.clawblox import ClawbloxAdapter, make_counter  # noqa: E402
from adapters.clawblox.compact import compact_view, view_json, view_text  # noqa: E402

NUM = r"(-?[\d.]+)"
ROW = re.compile(rf"^(\S+) (.+?) \({NUM},{NUM},{NUM}\) ([\d.]+) ([NSEW]{{1,2}}|here)(.*)$")
ME = re.compile(rf"^you \({NUM},{NUM},{NUM}\)")
CASTLE = re.compile(r"^sandcastle in plot (\d+) .*?: (\d+) pieces?, (\d+) high(, with a flag)?, "
                    r"(standing|still moving)(?:, has fallen (\d+))?")
PLOTS = re.compile(rf"(\d+) at {NUM},{NUM}")
GOAL_LINE = re.compile(rf"(north|south) goal line z={NUM} between posts x={NUM}\.\.{NUM}")
SHORE = re.compile(rf"east of x={NUM} is shallow water")


def parse_look(text: str) -> dict:
    out = {"me": None, "holding": None, "objects": [], "castles": {}, "players": [], "total": 0}
    for line in text.splitlines():
        m = ME.match(line)
        if m:
            out["me"] = tuple(float(x) for x in m.groups())
            hm = re.search(r"holding (\S+)", line)
            out["holding"] = hm.group(1) if hm else None
            continue
        tm = re.match(r"objects \(nearest \d+ of (\d+)", line)
        if tm:
            out["total"] = int(tm.group(1))
            continue
        cm = CASTLE.match(line)
        if cm:
            out["castles"][int(cm.group(1))] = {
                "pieces": int(cm.group(2)), "height": int(cm.group(3)), "flag": bool(cm.group(4)),
                "standing": cm.group(5) == "standing", "falls": int(cm.group(6) or 0)}
            continue
        rm = ROW.match(line)
        if rm:
            g = rm.groups()
            out["objects"].append({"name": g[0], "kind": g[1], "pos": tuple(map(float, g[2:5])),
                                   "dist": float(g[5]), "dir": g[6], "extra": g[7]})
            continue
        if line.startswith("players: ") and "nobody" not in line:
            for part in line[len("players: "):].split("; "):
                pm = re.match(r"(.+?) ([\d.]+) ([NSEW]{1,2}|here)( \(not in view\))?$", part)
                if pm:
                    out["players"].append({"name": pm.group(1), "dist": float(pm.group(2)),
                                           "in_view": not pm.group(4)})
    return out


class BeachPlayer:
    def __init__(self, adapter: ClawbloxAdapter, log_prefix: str = ""):
        self.a = adapter
        self.turns: list[dict] = []
        self.card = ""
        self.view: dict = {}
        self.prefix = log_prefix
        self.heard: list[str] = []

    # one turn = bundle + one tool call
    def turn(self, tool: str, *args) -> str:
        bundle = self.a.turn_bundle()
        state = bundle["state"]["text"]
        if not self.card and "MAP (" in state:
            self.card = state.split("\n\nNOW", 1)[0]
        self.view = parse_look(state.split("NOW\n", 1)[1])
        snap = self.a.last_snapshot
        v = compact_view(snap, self.a.statics, dict(self.a._names_by_entity), self.a.rules)
        c = self.a.counter
        result = getattr(self.a, tool)(*args)
        if tool == "hear":
            self.heard += [x for x in result.splitlines() if x and x != "(no new chat)"]
        if tool == "look":
            self.view = parse_look(result)
        self.turns.append({
            "turn": len(self.turns) + 1, "call": f"{tool} {json.dumps(args)[:100]}",
            "result": result, "tokens": {k: bundle[k]["tokens"] for k in ("tools", "state", "recent")},
            "total": bundle["total_tokens"],
            "view_text_tokens": c(view_text(v)), "view_json_tokens": c(view_json(v)),
            "raw_tokens": c(json.dumps(snap.raw, separators=(",", ":"))),
        })
        print(f"{self.prefix}[{len(self.turns)}] {tool}{args} -> {result}"[:260], flush=True)
        return result

    def look(self) -> dict:
        self.turn("look")
        return self.view

    def find(self, kind: str):
        return next((o for o in self.view["objects"] if o["kind"] == kind), None)

    def go(self, x: float, z: float) -> str:
        return self.turn("act", "MoveTo", {"position": [round(x, 2), 0, round(z, 2)]})

    def line_up(self, ball_kind: str, aim) -> dict | None:
        """Walk to just behind the ball (as seen in look), relative to the aim point."""
        self.look()
        ball = self.find(ball_kind)
        if ball is None:
            return None
        bx, _, bz = ball["pos"]
        dx, dz = aim[0] - bx, aim[1] - bz
        d = math.hypot(dx, dz) or 1.0
        ux, uz = dx / d, dz / d
        me = self.view["me"]
        # If we're on the far side of the ball, go round it first (don't walk through it).
        if (me[0] - bx) * ux + (me[2] - bz) * uz > -1.0:
            side = 1 if (me[0] - bx) * -uz + (me[2] - bz) * ux >= 0 else -1
            self.go(bx - ux * 3.0 - uz * 3.0 * side, bz - uz * 3.0 + ux * 3.0 * side)
        self.go(bx - ux * 2.2, bz - uz * 2.2)
        self.look()
        return self.find(ball_kind)

    def kick_towards(self, ball_kind: str, aim, power: float | None = None) -> str:
        ball = self.line_up(ball_kind, aim)
        if ball is None:
            return "no ball"
        bx, _, bz = ball["pos"]
        dx, dz = aim[0] - bx, aim[1] - bz
        if power is None:
            power = min(1.0, max(0.2, math.hypot(dx, dz) / 25))
        return self.turn("act", "Kick", {"direction": [round(dx, 2), 0, round(dz, 2)], "power": round(power, 2)})

    def settle_and_look(self, seconds: float) -> dict:
        time.sleep(seconds)
        return self.look()


def run(base: str, counter, name: str = "Sandy") -> dict:
    a = ClawbloxAdapter(base, name, counter=counter)
    p = BeachPlayer(a)
    goals: dict = {}

    p.turn("map_card")
    card = p.card or a.map_card()
    plots = {int(m.group(1)): (float(m.group(2)), float(m.group(3)))
             for m in PLOTS.finditer(card.split("castle plots", 1)[1].splitlines()[0])}
    north = next(m for m in GOAL_LINE.finditer(card) if m.group(1) == "north")
    goal_aim = (0.5 * (float(north.group(3)) + float(north.group(4))), float(north.group(2)) + 2)
    shore = float(SHORE.search(card).group(1))

    # 1. Soccer: dribble the soccer ball into the north goal.
    scored = False
    for attempt in range(6):
        res = p.kick_towards("soccer ball", goal_aim, power=1.0)
        if "Goal at the north end" in res:
            scored = True
            break
        time.sleep(1.5)
        heard = p.turn("hear")
        if "Goal at the north end" in heard:
            scored = True
            break
    goals["goal_scored_and_announced"] = scored
    goals["score_line_after"] = next((ln for ln in a.look().splitlines() if ln.startswith("score:")), "")

    # 2. Sea: kick the volleyball into the sea, then retrieve it.
    res = p.kick_towards("volleyball", (shore + 8, p.find("volleyball")["pos"][2] if p.find("volleyball") else 0),
                         power=1.0)
    time.sleep(1.0)
    view = p.look()
    vb = p.find("volleyball")
    went_in = bool(vb and "in the sea" in vb["extra"]) or "in the sea" in res
    goals["ball_went_into_sea"] = went_in
    retrieved = False
    for _ in range(4):
        vb = p.find("volleyball")
        if vb is None:
            break
        p.go(vb["pos"][0] - 2.0, vb["pos"][2])
        p.look()
        vb = p.find("volleyball")
        res = p.turn("act", "Pickup", {"position": list(vb["pos"])})
        if res.startswith("Picked up"):
            p.go(shore - 8, vb["pos"][2])
            me = p.look()["me"]
            res = p.turn("act", "Place", {"position": [round(me[0] - 2.5, 2), 0.6, round(me[2], 2)]})
            time.sleep(1.0)
            p.look()
            vb = p.find("volleyball")
            retrieved = bool(vb and vb["pos"][0] < shore and "in the sea" not in vb["extra"])
            break
    goals["ball_retrieved_from_sea"] = retrieved

    # 3. A good castle: three blocks, then a flag, centered in plot 1.
    px, pz = plots[1]
    p.go(px + 3.2, pz)
    y = 0.0
    for shape, h in (("block", 1.0), ("block", 1.0), ("block", 1.0), ("flag", 1.5)):
        p.turn("act", "Mold", {"shape": shape})
        p.turn("act", "Place", {"position": [px, round(y + h / 2 + 0.05, 2), pz]})
        y += h
    view = p.settle_and_look(3.0)
    good = view["castles"].get(1, {})
    goals["good_castle"] = good
    goals["good_castle_3_high_standing"] = bool(good and good["height"] >= 3 and good["standing"]
                                               and good["falls"] == 0)

    # 4. A bad castle: a wall balanced off-center on a tower, in plot 4.
    bx, bz = plots[4]
    p.go(bx + 3.2, bz)
    p.turn("act", "Mold", {"shape": "tower"})
    p.turn("act", "Place", {"position": [bx, 1.05, bz]})
    p.turn("act", "Mold", {"shape": "wall"})
    p.turn("act", "Place", {"position": [round(bx + 0.9, 2), 2.55, bz]})
    view = p.settle_and_look(2.0)
    heard = p.turn("hear")
    bad = view["castles"].get(4, {})
    goals["bad_castle"] = bad
    goals["bad_castle_fell"] = bool(bad.get("falls")) or "plot 4 fell down" in heard
    goals["fall_announced"] = "plot 4 fell down" in heard or any("plot 4 fell down" in h for h in p.heard)
    goals["good_castle_still_standing"] = bool(view["castles"].get(1, {}).get("standing"))

    # Worst case: bring all three balls next to the finished castle and stand there.
    for kind in ("soccer ball", "volleyball", "beach ball"):
        p.look()
        b = p.find(kind)
        if b is None:
            continue
        p.go(b["pos"][0] + 2.0, b["pos"][2])
        p.look()
        b = p.find(kind)
        if b and p.turn("act", "Pickup", {"position": list(b["pos"])}).startswith("Picked up"):
            p.go(px + 3.5, pz + 1.5)
            me = p.look()["me"]
            i = ("soccer ball", "volleyball", "beach ball").index(kind)
            radius = {"soccer ball": 0.6, "volleyball": 0.55, "beach ball": 0.9}[kind]
            p.turn("act", "Place", {"position": [round(me[0] + 2.0, 2), radius + 0.1,
                                                 round(me[2] - 2.5 + 2.5 * i, 2)]})
    p.go(px + 3.0, pz)
    p.turn("say", "the castle in plot 1 is three high with a flag")
    worst = a.turn_bundle(include_map=True)
    snap = a.last_snapshot
    v = compact_view(snap, a.statics, dict(a._names_by_entity), a.rules)
    worst_info = {"tokens": {k: worst[k]["tokens"] for k in ("tools", "state", "recent")},
                  "total": worst["total_tokens"], "state_text": worst["state"]["text"],
                  "recent_text": worst["recent"]["text"]}
    # Castle line vs listing its pieces one by one (same snapshot).
    c1 = [c for c in v["castles"] if c["plot"] == 1]
    from adapters.clawblox.compact import castle_text, _object_row
    pieces = [e for e in snap.objects if e.attrs.get("InPlot") == 1]
    rows = []
    for e in pieces:
        r = _object_row(e, snap, a.statics)
        rows.append(f"{r['name']} {r['kind']} ({','.join(f'{x:g}' for x in r['pos'])}) {r['dist']:g} {r['dir']} in plot 1")
    castle_vs_pieces = {
        "castle_line": castle_text(c1[0]) if c1 else "",
        "castle_line_tokens": counter(castle_text(c1[0])) if c1 else 0,
        "pieces": len(pieces),
        "pieces_text_tokens": counter("\n".join(rows)),
        "pieces_text": "\n".join(rows),
    }
    return {"goals": goals, "turns": p.turns, "worst_case": worst_info, "castle_vs_pieces": castle_vs_pieces}


def stats(xs):
    return {"min": min(xs), "median": statistics.median(xs), "max": max(xs)}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:8100")
    ap.add_argument("--tokenizer")
    ap.add_argument("--tokenizer-name")
    ap.add_argument("--out")
    args = ap.parse_args()
    counter = make_counter(args.tokenizer, args.tokenizer_name)
    res = run(args.base, counter)
    t = res["turns"]
    res["token_method"] = counter.method
    res["turn_total"] = stats([x["total"] for x in t])
    res["pieces_stats"] = {k: stats([x["tokens"][k] for x in t]) for k in ("tools", "state", "recent")}
    res["view_text_tokens"] = stats([x["view_text_tokens"] for x in t])
    res["view_json_tokens"] = stats([x["view_json_tokens"] for x in t])
    res["raw_tokens"] = stats([x["raw_tokens"] for x in t])
    if args.out:
        Path(args.out).write_text(json.dumps(res, indent=1))
    show = {k: res[k] for k in ("token_method", "goals", "turn_total", "pieces_stats", "view_text_tokens",
                                "view_json_tokens", "raw_tokens")}
    show["worst_case"] = {k: res["worst_case"][k] for k in ("tokens", "total")}
    show["castle_vs_pieces"] = {k: res["castle_vs_pieces"][k] for k in
                                ("castle_line", "castle_line_tokens", "pieces", "pieces_text_tokens")}
    show["turns"] = len(t)
    print(json.dumps(show, indent=1))
    g = res["goals"]
    ok = all(g.get(k) for k in ("goal_scored_and_announced", "ball_went_into_sea", "ball_retrieved_from_sea",
                                "good_castle_3_high_standing", "bad_castle_fell", "good_castle_still_standing"))
    print("TASK", "COMPLETED" if ok else "NOT COMPLETED")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
