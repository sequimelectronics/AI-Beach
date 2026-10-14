#!/usr/bin/env python3
"""Scripted agent that plays mesa-island seeing ONLY the adapter's text output.

It is the test that the compact view is still enough to play: it reads the
map card, look() text, one-line act() results and hear() lines - never the raw
observation - and must:

  1. reach the block pile, 2. pick up a block and place it,
  3. climb to the rock, 4. pick up the rock and throw it,
  5. confirm new blocks appeared,
then chat and wander until ~50 turns, recording turn_bundle() sizes each turn.

One "turn" = one turn_bundle() (what the host would hand the model) followed
by one tool call. Usage:

    python3 scripts/clawblox_adapter_agent.py --base http://127.0.0.1:8080 \
        --tokenizer path/to/gemma-4-E4B-it/tokenizer.json --out run.json
"""

from __future__ import annotations

import argparse
import json
import re
import statistics
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from adapters.clawblox import ClawbloxAdapter, make_counter  # noqa: E402
from adapters.clawblox.compact import compact_view, view_json, view_text  # noqa: E402

VEC = r"\((-?[\d.]+),(-?[\d.]+),(-?[\d.]+)\)"
ROW = re.compile(rf"^(\S+) (\w+) {VEC} ([\d.]+) (\w+)(?: on (\S+) \(top ([\d.]+)\))?$")
FAR_ONE = re.compile(rf"(\S+) (\w+) {VEC}(?: on (\S+))? ([\d.]+) (\w+)")
ME = re.compile(rf"^you {VEC}")
PILE = re.compile(r"a pile of (\d+) (\w+)s near (-?[\d.]+),(-?[\d.]+)")


# --- reading the adapter's text -------------------------------------------------

def parse_look(text: str) -> dict:
    lines = text.splitlines()
    i = next(k for k, line in enumerate(lines) if line.startswith("you "))
    m = ME.match(lines[i])
    me = tuple(float(x) for x in m.groups())
    holding = None
    hm = re.search(r"holding (\S+)", lines[i])
    if hm:
        holding = hm.group(1)
    objects, total = [], 0
    for line in lines[i + 1:]:
        tm = re.match(r"objects \(nearest \d+ of (\d+)", line)
        if tm:
            total = int(tm.group(1))
            continue
        rm = ROW.match(line)
        if rm:
            g = rm.groups()
            objects.append({"name": g[0], "kind": g[1], "pos": tuple(map(float, g[2:5])),
                            "dist": float(g[5]), "dir": g[6], "on": g[7],
                            "top": float(g[8]) if g[8] else None})
        if line.startswith("farther: "):
            for fm in FAR_ONE.finditer(line[len("farther: "):]):
                g = fm.groups()
                if g[1] in ("blocks",):
                    continue
                objects.append({"name": g[0], "kind": g[1], "pos": tuple(map(float, g[2:5])),
                                "dist": float(g[6]), "dir": g[7], "on": g[5], "top": None})
    return {"me": me, "holding": holding, "objects": objects, "total": total}


def state_view(bundle: dict) -> str:
    """The look part of the state piece (after 'NOW')."""
    return bundle["state"]["text"].split("NOW\n", 1)[1]


class Agent:
    def __init__(self, adapter: ClawbloxAdapter, max_turns: int):
        self.a = adapter
        self.max_turns = max_turns
        self.turns: list[dict] = []
        self.view: dict | None = None
        self.card = ""
        self.log: list[str] = []

    def turn(self, tool: str, *args) -> str:
        """One turn: build the bundle the model would see, then make one tool call."""
        bundle = self.a.turn_bundle()
        if not self.card and "MAP (" in bundle["state"]["text"]:
            self.card = bundle["state"]["text"].split("\n\nNOW", 1)[0]
        self.view = parse_look(state_view(bundle))
        snap = self.a.last_snapshot
        v = compact_view(snap, self.a.statics, dict(self.a._names_by_entity), self.a.rules)
        count = self.a.counter
        result = getattr(self.a, tool)(*args)
        self.turns.append({
            "turn": len(self.turns) + 1,
            "call": f"{tool} {json.dumps(args)[:120]}",
            "result": result if isinstance(result, str) else str(result),
            "tokens": {k: bundle[k]["tokens"] for k in ("tools", "state", "recent")},
            "total": bundle["total_tokens"],
            "view_text_tokens": count(view_text(v)),
            "view_json_tokens": count(view_json(v)),
            "view_text_bytes": len(view_text(v).encode()),
            "view_json_bytes": len(view_json(v).encode()),
            "raw_tokens": count(json.dumps(snap.raw, separators=(",", ":"))) if snap else None,
            "objects_total": self.view["total"],
            "me": self.view["me"],
        })
        self.log.append(f"[{len(self.turns)}] {tool}{args} -> {result}")
        print(self.log[-1][:220], flush=True)
        return result

    # --- helpers built only on text -------------------------------------------

    def nearest(self, kind: str):
        objs = [o for o in self.view["objects"] if o["kind"] == kind]
        return min(objs, key=lambda o: o["dist"], default=None)

    def go(self, pos) -> str:
        res = self.turn("act", "MoveTo", {"position": list(pos)})
        if '"jump": true' in res:
            res = self.turn("act", "MoveTo", {"position": list(pos), "jump": True})
        return res

    def pick(self, kind: str) -> str:
        self.turn("look")
        obj = self.nearest(kind)
        if obj is None:
            return f"no {kind} visible"
        res = self.turn("act", "Pickup", {"position": list(obj["pos"])})
        if "move closer" in res:
            self.go(obj["pos"])
            self.turn("look")
            obj = self.nearest(kind) or obj
            res = self.turn("act", "Pickup", {"position": list(obj["pos"])})
        return res

    def play(self) -> dict:
        goals = {}
        # 1. read the map card, head for the block pile
        self.turn("map_card")
        pm = PILE.search(self.card)
        if pm:
            pile = (float(pm.group(3)), 0.0, float(pm.group(4)))
        else:
            pile = self.nearest("block")["pos"]
        self.pile_spot = (pile[0] - 2, pile[1], pile[2])
        res = self.go(self.pile_spot)
        goals["reached_pile"] = res.startswith("MoveTo") and "arrived" in res
        # 2. pick up and place a block
        res = self.pick("block")
        goals["picked_block"] = res.startswith("Picked up")
        me = self.view["me"]
        for dx, dz in ((-3, 0), (0, 3), (0, -3), (-3, 3)):
            res = self.turn("act", "Place", {"position": [me[0] + dx, 0.6, me[2] + dz]})
            if res.startswith("Placed"):
                break
        goals["placed_block"] = res.startswith("Placed")
        self.turn("look")
        blocks_before = self.view["total"]
        # 3. climb to the rock (position comes from look; it says what it rests on)
        rock = self.nearest("rock")
        res = self.go(rock["pos"])
        goals["climbed_to_rock"] = f" on {rock['on']}" in res if rock["on"] else "arrived" in res
        # 4. pick up the rock and throw it off the plateau, slightly downward
        res = self.pick("rock")
        goals["picked_rock"] = res.startswith("Picked up")
        res = self.turn("act", "Throw", {"direction": [1, -0.3, 0], "speed": 10})
        goals["threw_rock"] = res.startswith("Threw")
        m = re.search(r"(\d+) new blocks? appeared", res)
        goals["new_blocks_reported"] = int(m.group(1)) if m else 0
        self.turn("look")
        goals["objects_before_after"] = [blocks_before, self.view["total"]]
        goals["new_blocks_seen_in_look"] = self.view["total"] > blocks_before
        # 5. chat
        self.turn("say", "hello from the plateau - the rock made new blocks")
        self.turn("hear")
        # worst case: stand next to the block pile after the rock made new blocks
        self.go((pile[0] - 2, pile[1], pile[2]))
        self.turn("look")
        # wander until ~max_turns
        waypoints = [(0, 0, 0), (10, 0, -10), (-10, 0, -5), (5, 0, 10), (pile[0] - 2, 0, pile[2])]
        i = 0
        while len(self.turns) < self.max_turns:
            self.go(waypoints[i % len(waypoints)])
            if len(self.turns) < self.max_turns:
                self.turn("look")
            i += 1
        return goals


def stats(xs):
    return {"min": min(xs), "median": statistics.median(xs), "max": max(xs)}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:8080")
    ap.add_argument("--name", default="Sandy")
    ap.add_argument("--tokenizer", help="tokenizer.json (else chars/4 approx)")
    ap.add_argument("--tokenizer-name", default=None)
    ap.add_argument("--turns", type=int, default=50)
    ap.add_argument("--out")
    ap.add_argument("--stress-chat", action="store_true",
                    help="after the run, add a second player's six 500-char chat lines (needs max_players >= 2)")
    args = ap.parse_args()
    counter = make_counter(args.tokenizer, args.tokenizer_name)
    adapter = ClawbloxAdapter(args.base, args.name, counter=counter)
    agent = Agent(adapter, args.turns)
    goals = agent.play()
    stress = None
    if args.stress_chat:
        # Worst case: at the block pile after the rock made new blocks, with a full
        # action history, six max-length chat lines from another player, and the
        # map card included again.
        agent.go(agent.pile_spot)
        other = ClawbloxAdapter(args.base, "Chatter", counter=counter)
        for i in range(6):
            other.say((f"line {i}: " + "the sandcastle needs a moat and a tower " * 20)[:500])
        b = adapter.turn_bundle(include_map=True)
        stress = {"tokens": {k: b[k]["tokens"] for k in ("tools", "state", "recent")},
                  "total": b["total_tokens"], "state_text": b["state"]["text"],
                  "recent_text": b["recent"]["text"]}
    totals = [t["total"] for t in agent.turns]
    out = {
        "token_method": counter.method,
        "goals": goals,
        "turn_total": stats(totals),
        "pieces": {k: stats([t["tokens"][k] for t in agent.turns]) for k in ("tools", "state", "recent")},
        "view_text_tokens": stats([t["view_text_tokens"] for t in agent.turns]),
        "view_json_tokens": stats([t["view_json_tokens"] for t in agent.turns]),
        "raw_tokens": stats([t["raw_tokens"] for t in agent.turns if t["raw_tokens"]]),
        "stress_worst_case": stress,
        "play_card_tokens": counter(Path(__file__).resolve().parents[1].joinpath(
            "adapters", "clawblox", "PLAY_CARD.md").read_text().strip()),
        "map_card_tokens": counter(adapter.map_card()),
        "turns": agent.turns,
        "transcript": agent.log,
    }
    if args.out:
        Path(args.out).write_text(json.dumps(out, indent=1))
    print(json.dumps({k: out[k] for k in ("token_method", "goals", "turn_total", "pieces",
                                          "view_text_tokens", "view_json_tokens", "raw_tokens",
                                          "play_card_tokens", "map_card_tokens")},
                     indent=1))
    ok = all(goals[k] for k in ("reached_pile", "picked_block", "placed_block", "climbed_to_rock",
                                "picked_rock", "threw_rock", "new_blocks_seen_in_look"))
    print("TASK", "COMPLETED" if ok else "NOT COMPLETED")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
