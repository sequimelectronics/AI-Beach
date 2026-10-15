"""Scripted card games through the Beach's HTTP API, with mixed clients, plus token sizes.

Three players at one table: two agent-shaped clients that read ONLY their turn bundle
(GET /agent/turn?table=<id>, the text an agent's model would get) and pick a move from the
"Legal moves" line in it, and one person-shaped client that reads only what the browser reads
(GET /tables/<id>) and taps a move from its "legal" list. Nobody knows the rules; they choose
among the moves they're shown. Each game is played to the end.

Then token sizes with a real tokenizer: each game's card, a typical turn, and the worst case
(the largest hand, with the most legal moves).

    python3 scripts/cards_scripted.py --tokenizer path/to/gemma-4-E4B/tokenizer.json [--out report.json]

Runs in-process (FastAPI's test client); needs the Beach's own requirements only.
"""

from __future__ import annotations

import argparse
import json
import random
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from beach import agent  # noqa: E402
from beach.core import BOARDWALK, Beach  # noqa: E402
from beach.games import GAMES  # noqa: E402
from beach.tokens import make_counter  # noqa: E402

LEGAL = "your move. Legal moves (pick one): "


class AgentClient:
    """Sees only its turn bundle. Picks one of the listed moves (a seeded random choice)."""

    def __init__(self, http, name, headers, rng):
        self.http, self.name, self.h, self.rng = http, name, headers, rng
        self.biggest = 0

    def turn(self, tid) -> dict | None:
        b = self.http.get(f"/agent/turn?table={tid}", headers=self.h).json()
        self.biggest = max(self.biggest, b["total_tokens"])
        line = next((ln for ln in b["state"]["text"].splitlines() if ln.startswith(LEGAL)), None)
        if line is None:
            return None
        moves = line[len(LEGAL):].split(", ")
        r = self.http.post(f"/tables/{tid}/move", json={"move": self.rng.choice(moves)}, headers=self.h)
        assert r.status_code == 200, r.text
        return r.json()


class PersonClient:
    """Sees only what the browser shows: the table view. Taps one of its legal moves."""

    def __init__(self, http, name, headers, rng):
        self.http, self.name, self.h, self.rng = http, name, headers, rng

    def turn(self, tid) -> dict | None:
        v = self.http.get(f"/tables/{tid}", headers=self.h).json()
        if not v["your_turn"]:
            return None
        r = self.http.post(f"/tables/{tid}/move", json={"move": self.rng.choice(v["legal"])}, headers=self.h)
        assert r.status_code == 200, r.text
        return r.json()


def setup(data_dir: str):
    from fastapi.testclient import TestClient
    from beach.app import create_app
    beach = Beach(data_dir, rng=random.Random(1))
    admin = {"Authorization": f"Bearer {beach.ensure_admin()}"}
    http = TestClient(create_app(beach, upkeep_interval=None))
    heads = {}
    for name, kind in (("Sandy", "agent"), ("Pebble", "agent"), ("Coral", "person")):
        tok = http.post("/claim", json={"code": http.post("/admin/participants", json={"name": name, "kind": kind}, headers=admin).json()["invite"]["code"]}).json()["token"]
        heads[name] = {"Authorization": f"Bearer {tok}"}
    return beach, http, heads


def play_game(http, heads, game: str, seed: int = 1, limit: int = 2000) -> dict:
    rng = random.Random(seed)
    clients = [AgentClient(http, "Sandy", heads["Sandy"], rng), PersonClient(http, "Coral", heads["Coral"], rng),
               AgentClient(http, "Pebble", heads["Pebble"], rng)]
    tid = http.post("/zones/boardwalk/tables", json={"game": game, "players": 3}, headers=heads["Sandy"]).json()["id"]
    http.post(f"/tables/{tid}/sit", headers=heads["Coral"])
    http.post(f"/tables/{tid}/sit", headers=heads["Pebble"])
    moves, lines = 0, []
    while moves < limit:
        acted = False
        for c in clients:
            r = c.turn(tid)
            if r:
                moves += 1
                acted = True
                lines.append(f"{c.name}: {r.get('text', r['moved'])}")
                if r["over"]:
                    break
        v = http.get(f"/tables/{tid}", headers=heads["Sandy"]).json()
        if v["status"] != "playing" or not acted:
            break
    return {"table": tid, "game": game, "moves": moves, "status": v["status"], "result": v.get("result_text"),
            "transcript": lines, "agent_bundle_max": max(c.biggest for c in clients if isinstance(c, AgentClient))}


def worst_cases(beach: Beach, counter) -> dict:
    """Bundles for hand-made worst positions: the biggest hand with the most legal moves."""
    out = {}
    bw = beach.tables
    names = ["Sandy", "Pebble", "Coral", "Drift", "Shell"]
    pids = [beach.add_participant(n + "W", "agent")[0].id for n in names]
    # Crazy Eights, 2 players: one holds 30 cards including all four eights (16 ways to play them).
    tid = bw.open(pids[0], BOARDWALK, "crazy8", options={"players": 2, "seed": 5})["id"]
    bw.sit(pids[1], tid)
    st = json.loads(bw.table(tid)["state"])
    pool = [c for c in st["stock"] + st["hands"][1] if not c.startswith("8")]
    eights = [c for c in st["stock"] + st["hands"][1] + st["hands"][0] + st["pile"] if c.startswith("8")]
    top = next(c for c in pool if c[-1] == "H")
    pool.remove(top)
    hand = sorted(eights + [c for c in pool if c[-1] in "HS" or c[:-1] == top[:-1]][:26],
                  key=lambda c: "SHDC".index(c[-1]))
    rest = [c for c in st["stock"] + st["hands"][0] + st["hands"][1] + st["pile"] if c not in hand and c != top]
    st.update(hands=[hand, rest[:3]], stock=rest[3:], pile=[top], suit="H", turn=0)
    beach.db.run("UPDATE game_tables SET state = ? WHERE id = ?", (json.dumps(st), tid))
    b = agent.table_bundle(beach, pids[0], tid, counter=counter, consume_notes=False)
    out["crazy8"] = {"hand": len(hand), "legal": len(GAMES["crazy8"].legal_moves(st)),
                     "state_tokens": b["state"]["tokens"], "total_tokens": b["total_tokens"]}
    # Go Fish, 5 players: one holds a card of all thirteen ranks; four people to ask: 52 asks.
    tid = bw.open(pids[0], BOARDWALK, "gofish", options={"players": 5, "seed": 5})["id"]
    for p in pids[1:]:
        bw.sit(p, tid)
    st = json.loads(bw.table(tid)["state"])
    from beach.games.cards import RANKS, deck
    d = deck()
    big = [r + s for r, s in zip(RANKS, "SHDCSHDCSHDCS")] + [r + "H" for r in RANKS[:3]]
    rest = [c for c in d if c not in big]
    st.update(hands=[big, rest[:2], rest[2:4], rest[4:6], rest[6:8]], stock=rest[8:],
              books=[[] for _ in range(5)], turn=0)
    beach.db.run("UPDATE game_tables SET state = ? WHERE id = ?", (json.dumps(st), tid))
    b = agent.table_bundle(beach, pids[0], tid, counter=counter, consume_notes=False)
    out["gofish"] = {"hand": len(big), "legal": len(GAMES["gofish"].legal_moves(dict(st, names=[n + "W" for n in names]))),
                     "state_tokens": b["state"]["tokens"], "total_tokens": b["total_tokens"]}
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tokenizer")
    ap.add_argument("--games", type=int, default=3, help="games of each kind")
    ap.add_argument("--out")
    a = ap.parse_args(argv)
    counter = make_counter(a.tokenizer, "Gemma 4 E4B") if a.tokenizer else make_counter()
    d = tempfile.mkdtemp(prefix="cards-scripted-")
    try:
        beach, http, heads = setup(d)
        report = {"token_method": counter.method, "games": [], "cards": {}, "typical": {}, "worst": {}}
        for game in ("crazy8", "gofish"):
            report["cards"][game] = counter(GAMES[game].card(1))
            for i in range(a.games):
                g = play_game(http, heads, game, seed=100 + i)
                report["games"].append({k: v for k, v in g.items() if k != "transcript"})
                print(f"{game} #{i + 1}: {g['moves']} moves, {g['status']}: {g['result']}")
                if i == 0:
                    print("   " + "\n   ".join(g["transcript"][:8]) + "\n   ...\n   " + "\n   ".join(g["transcript"][-3:]))
            # A typical turn: a fresh 3-player table a few moves in, from the agent's side.
            g = play_game(http, heads, game, seed=7, limit=6)
            b = http.get(f"/agent/turn?table={g['table']}", headers=heads["Sandy"]).json()
            report["typical"][game] = {"tools": counter(b["tools"]["text"]), "state": counter(b["state"]["text"]),
                                       "recent": counter(b["recent"]["text"])}
            report["typical"][game]["total"] = sum(report["typical"][game].values())
            report["typical"][game]["example_state"] = b["state"]["text"]
        report["worst"] = worst_cases(beach, counter)
        print(json.dumps({k: v for k, v in report.items() if k != "games"}, indent=1))
        if a.out:
            Path(a.out).write_text(json.dumps(report, indent=1))
        ok = all(g["status"] == "finished" for g in report["games"])
        return 0 if ok else 1
    finally:
        beach.db.close()
        shutil.rmtree(d, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
