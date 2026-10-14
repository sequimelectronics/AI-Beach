"""The Boardwalk, scripted end to end through the HTTP door (temporary data dir, fake clock).

Part 1: two agents, Sandy and Pebble, play checkers to the end. Each sees ONLY what
GET /agent/turn?table=<id> returns (tools, state, recent as text). Their "mind" is a tiny
stand-in for a small model: it reads the legal-move list out of the state text and picks
one (most captures first, then a crowning move, else a seeded random choice). It never
computes legality itself. Sandy also tries one illegal move, to show the refusal.

Part 2: Coral, a person-shaped client, plays Drift (an agent) through the same calls the
browser makes (GET /tables/<id>, POST /tables/<id>/move with a move from `legal`). Midway
Coral leaves for a day: the game waits, one "your move" notice goes to the hook, Coral
comes back and finishes. Then a draw by agreement.

    python3 scripts/boardwalk_scenario.py [--tokenizer path/to/tokenizer.json] [--log out.txt]
"""

from __future__ import annotations

import argparse
import random
import re
import shutil
import statistics
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from beach.app import create_app  # noqa: E402
from beach.core import Beach  # noqa: E402
from beach.tokens import make_counter  # noqa: E402


class FakeClock:
    def __init__(self):
        self.t = 1_800_000_000.0

    def __call__(self):
        return self.t


def legal_from(state_text: str) -> list[str]:
    m = re.search(r"Legal moves \(pick one\): (.+)", state_text)
    return [x.strip() for x in m.group(1).split(",")] if m else []


class TextAgent:
    """Stands in for a model: reads the bundle text, answers with one move from the list."""

    def __init__(self, name: str, seed: int):
        self.name = name
        self.rng = random.Random(seed)

    def choose(self, bundle: dict) -> str:
        state = bundle["state"]["text"]
        legal = legal_from(state)
        best = max(m.count("x") for m in legal)
        pool = [m for m in legal if m.count("x") == best]
        crowning = [m for m in pool if m[-1] in "18" and not self._is_king_at(state, m[:2])]
        return self.rng.choice(crowning or pool)

    @staticmethod
    def _is_king_at(state: str, sq: str) -> bool:
        rows = {line[0]: line[2:].split(" ") for line in state.splitlines() if re.match(r"^[1-8] [.bwBW]", line)}
        piece = rows[sq[1]]["abcdefgh".index(sq[0])]
        return piece in "BW"


def run(tokenizer: str | None = None, log=print) -> dict:
    tmp = tempfile.mkdtemp(prefix="boardwalk-scenario-")
    clock = FakeClock()
    beach = Beach(tmp, clock=clock, rng=random.Random(5))
    hook = []
    beach.sender = lambda payload: hook.append(payload) or True
    from fastapi.testclient import TestClient
    http = TestClient(create_app(beach, upkeep_interval=None))
    admin = {"Authorization": f"Bearer {beach.ensure_admin()}"}
    H = {}
    for name, kind in (("Sandy", "agent"), ("Pebble", "agent"), ("Coral", "person"), ("Drift", "agent"),
                       ("Shell", "person")):
        tok = http.post("/admin/participants", json={"name": name, "kind": kind}, headers=admin).json()["token"]
        H[name] = {"Authorization": f"Bearer {tok}"}
    counter = make_counter(tokenizer, "google/gemma-4-E4B-it" if tokenizer else None)
    checks: dict[str, bool] = {}

    def post(who, path, body=None):
        clock.t += 20   # a little thinking time per call
        return http.post(path, json=body or {}, headers=H[who])

    # Games here take simulated hours; keep idle auto-leave out of the way of the story.
    http.patch("/admin/settings", json={"idle_timeout_s": 7 * 86400}, headers=admin)
    # Shell sits in SandChat, to hear the result.
    post("Shell", "/zones/sandchat/join")

    # ------------------------------------------------------------ part 1: agent vs agent
    log("PART 1: Sandy (agent) vs Pebble (agent), each seeing only turn_bundle() text")
    tid = post("Sandy", "/zones/boardwalk/tables", {"game": "checkers"}).json()["id"]
    post("Pebble", f"/tables/{tid}/sit")
    agents = {"Sandy": TextAgent("Sandy", 1), "Pebble": TextAgent("Pebble", 2)}
    sizes, legal_counts, worst = [], [], None
    first_bundle = None
    turns = 0
    illegal_shown = False
    from_list: list[bool] = []
    while True:
        moved = False
        for name, agent in agents.items():
            bundle = http.get(f"/agent/turn?table={tid}", headers=H[name]).json()
            st = bundle["state"]["text"]
            if "game over" in st:
                continue
            if "your move" not in st:
                continue
            legal = legal_from(st)
            tokens = {k: counter(bundle[k]["text"]) for k in ("tools", "state", "recent")}
            sizes.append(tokens)
            legal_counts.append(len(legal))
            if worst is None or tokens["state"] > worst[0]["state"]:
                worst = (tokens, bundle)
            if first_bundle is None:
                first_bundle = bundle
            if not illegal_shown:
                r = post(name, f"/tables/{tid}/move", {"move": "c3-c4"})
                illegal_shown = True
                log(f"  {name} tries c3-c4 -> {r.status_code}: {r.json()['message']}")
                checks["illegal_move_refused_with_reason_and_list"] = (
                    r.status_code == 400 and r.json()["legal"] == legal and "isn't legal" in r.json()["reason"])
            move = agent.choose(bundle)
            from_list.append(move in legal)
            r = post(name, f"/tables/{tid}/move", {"move": move})
            assert r.status_code == 200, r.text
            turns += 1
            if turns <= 6 or (r.json()["over"]):
                log(f"  {turns:3}. {name}: {move}" + (f"  -> {r.json()['over']}" if r.json()["over"] else ""))
            elif turns == 7:
                log("  ...")
            if turns == 10:
                post(name, f"/tables/{tid}/say", {"text": "Your corner is looking crowded."})
            moved = True
            break
        if not moved:
            break
        if turns > 400:
            raise RuntimeError("game didn't end")
    final_sandy = http.get(f"/agent/turn?table={tid}", headers=H["Sandy"]).json()
    view = http.get(f"/tables/{tid}", headers=H["Sandy"]).json()
    log(f"  result after {turns} moves: {view['result_text']}")
    checks["agent_game_played_to_the_end"] = view["status"] == "finished"
    checks["every_agent_move_came_from_the_list"] = all(from_list) and len(from_list) == turns
    sc = http.get("/zones/sandchat/messages", headers=H["Shell"]).json()["messages"]
    announce = [m["line"] for m in sc if "finished a game of checkers" in m["line"]]
    log(f"  SandChat heard: {announce[0] if announce else '(nothing)'}")
    checks["result_announced_once_in_sandchat"] = len(announce) == 1

    # ------------------------------------------------------------ part 2: person vs agent
    log("\nPART 2: Coral (person, the browser's calls) vs Drift (agent, turn_bundle)")
    tid2 = post("Coral", "/zones/boardwalk/tables", {"game": "checkers"}).json()["id"]
    post("Drift", f"/tables/{tid2}/sit")
    drift = TextAgent("Drift", 3)
    rng = random.Random(9)
    paused = False
    n = 0
    while n < 400:
        v = http.get(f"/tables/{tid2}", headers=H["Coral"]).json()
        if v["status"] != "playing":
            break
        if v["your_turn"]:
            # What the browser does: tap a piece from `legal`, then its landing squares.
            move = rng.choice(v["legal"])
            r = post("Coral", f"/tables/{tid2}/move", {"move": move})
            assert r.status_code == 200, r.text
        else:
            b = http.get(f"/agent/turn?table={tid2}", headers=H["Drift"]).json()
            r = post("Drift", f"/tables/{tid2}/move", {"move": drift.choose(b)})
            assert r.status_code == 200, r.text
        n += 1
        if n == 8 and not paused:
            # Drift has just moved; it's Coral's turn, and Coral steps away for a day.
            paused = True
            post("Coral", "/zones/boardwalk/part")
            for _ in range(24):
                clock.t += 3600
                beach.tick()
            v = http.get(f"/tables/{tid2}", headers=H["Drift"]).json()
            mine = [h for h in hook if h.get("event") == "your_move"]
            log(f"  Coral left on their turn; a day later the game is '{v['status']}', "
                f"{len(mine)} 'your move' notice sent: {mine[0]['invitee'] if mine else '-'} at table {tid2}")
            checks["game_waits_a_day"] = v["status"] == "playing"
            checks["one_your_move_notice"] = len(mine) == 1 and mine[0]["invitee"] == "Coral"
        if n == 12:
            post("Drift", f"/tables/{tid2}/draw", {"action": "offer"})
            v = http.get(f"/tables/{tid2}", headers=H["Coral"]).json()
            r = post("Coral", f"/tables/{tid2}/draw", {"action": "accept"})
            log(f"  Drift offered a draw; Coral accepted: {r.json()['result_text']}")
            checks["coral_came_back_and_played"] = any(h["name"] == "Coral" and h["ply"] > 8
                                                      for h in r.json()["history"])
            checks["draw_by_agreement"] = r.json()["result"] == {"winner": None, "reason": "a draw by agreement"}
            break

    shutil.rmtree(tmp, ignore_errors=True)
    beach.db.close()
    typical = {k: int(statistics.median(s[k] for s in sizes)) for k in ("tools", "state", "recent")}
    return {"checks": checks, "turns": turns, "sizes": sizes, "typical": typical, "worst": worst,
            "legal_counts": legal_counts, "first_bundle": first_bundle, "final_bundle": final_sandy,
            "token_method": counter.method}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tokenizer")
    ap.add_argument("--log", help="also write the transcript and bundles here")
    a = ap.parse_args(argv)
    lines = []

    def log(s=""):
        print(s)
        lines.append(s)

    res = run(a.tokenizer, log)
    t, w = res["typical"], res["worst"][0]
    log(f"\nturn sizes ({res['token_method']}): typical tools {t['tools']} / state {t['state']} / recent "
        f"{t['recent']} = {sum(t.values())}; largest state {w['state']} (total {sum(w.values())}); "
        f"legal moves per turn: median {int(statistics.median(res['legal_counts']))}, max {max(res['legal_counts'])}")
    ok = all(res["checks"].values())
    for k, v in res["checks"].items():
        log(f"  [{'x' if v else ' '}] {k}")
    log(f"{sum(res['checks'].values())} of {len(res['checks'])} checks passed")
    if a.log:
        extra = ["", "FIRST BUNDLE (Sandy, move 1)"] + [f"--- {k}\n{res['first_bundle'][k]['text']}"
                                                         for k in ("tools", "state", "recent")]
        extra += ["", "FINAL BUNDLE (Sandy)"] + [f"--- {k}\n{res['final_bundle'][k]['text']}"
                                                 for k in ("state", "recent")]
        Path(a.log).write_text("\n".join(lines + extra) + "\n")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
