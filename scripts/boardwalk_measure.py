"""Token sizes for the Boardwalk report: the cards (Beach card, each zone card), and the
checkers state in its worst case (the most legal moves we could find).

    python3 scripts/boardwalk_measure.py --tokenizer path/to/gemma-4-E4B tokenizer.json
"""

from __future__ import annotations

import argparse
import json
import random
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from beach import agent  # noqa: E402
from beach.core import BOARDWALK, Beach  # noqa: E402
from beach.games.checkers import Checkers  # noqa: E402
from beach.tokens import make_counter  # noqa: E402

DARK = [f"{'abcdefgh'[f]}{r + 1}" for r in range(8) for f in range(8) if (f + r) % 2 == 0]


def search_worst(g: Checkers, seed: int, rounds: int, captures: bool) -> tuple[int, dict]:
    """Hill-climb random legal-looking positions (at most 12 pieces a side) for the most legal moves
    for Black: plain moves (captures=False) or capture sequences (captures=True)."""
    rng = random.Random(seed)

    def crown(pieces):
        # A man can't stand on its own far row: it would already be a king.
        return {q: ("B" if v == "b" and q[1] == "8" else "W" if v == "w" and q[1] == "1" else v)
                for q, v in pieces.items()}

    def score(pieces):
        st = Checkers.from_pieces(pieces)
        moves = g.legal_moves(st)
        if not moves or not any(p in "wW" for p in pieces.values()):
            return -1
        is_cap = "x" in moves[0]
        if is_cap != captures:
            return -1
        return len(moves) if not captures else sum(len(m) for m in moves)

    best, best_s = None, -1
    for _ in range(rounds):
        sqs = rng.sample(DARK, 16)
        pieces = {}
        for i, sq in enumerate(sqs):
            side = "b" if i < 10 else "w"
            row = int(sq[1])
            if side == "b" and row == 8 or side == "w" and row == 1:
                side = side.upper()
            pieces[sq] = side if rng.random() < .5 else side.upper()
        pieces = crown(pieces)
        s = score(pieces)
        for _ in range(300):
            trial = dict(pieces)
            k = rng.choice(list(trial))
            v = trial.pop(k)
            free = [q for q in DARK if q not in trial]
            trial[rng.choice(free)] = v if rng.random() < .8 else rng.choice("bBwW")
            if sum(p in "bB" for p in trial.values()) > 12 or sum(p in "wW" for p in trial.values()) > 12:
                continue
            trial = crown(trial)
            ts = score(trial)
            if ts >= s:
                pieces, s = trial, ts
        if s > best_s:
            best, best_s = pieces, s
    return best_s, best


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tokenizer")
    ap.add_argument("--rounds", type=int, default=60)
    a = ap.parse_args(argv)
    c = make_counter(a.tokenizer, "google/gemma-4-E4B-it" if a.tokenizer else None)
    b = Beach(tempfile.mkdtemp())
    b.ensure_admin()
    b.add_zone("beachblox", "BeachBlox", "game", viewer_url="http://127.0.0.1:8100/")
    b.add_zone("clawblox", "ClawBlox", "game", viewer_url="http://127.0.0.1:8200/")
    s, _ = b.add_participant("Sandy", "agent")
    p, _ = b.add_participant("Pebble", "agent")
    out = {"token_method": c.method}
    out["beach_card"] = c(agent.beach_card(b))
    for z in ("sandchat", "boardwalk", "beachblox", "clawblox"):
        out[f"zone_card:{z}"] = c(agent.zone_card(b, z))
    out["checkers_card"] = c(Checkers().card(12))
    play = (ROOT / "adapters" / "clawblox" / "beach" / "PLAY_CARD.md").read_text()
    out["beachblox_play_card"] = c(play)
    tid = b.tables.open(s.id, BOARDWALK, "checkers")["id"]
    b.tables.sit(p.id, tid)
    out["opening_state"] = c(agent.table_state_text(b, s.id, tid, consume_notes=False))
    g = Checkers()
    for captures in (False, True):
        sc, pieces = search_worst(g, 7, a.rounds, captures)
        st = Checkers.from_pieces(pieces)
        b.db.run("UPDATE game_tables SET state = ? WHERE id = ?", (json.dumps(st), tid))
        text = agent.table_state_text(b, s.id, tid, consume_notes=False)
        key = "worst_captures" if captures else "worst_steps"
        out[key] = {"legal_moves": len(g.legal_moves(st)), "state_tokens": c(text),
                    "tools_plus_state": c(agent.beach_card(b) + "\n\n" + g.card(tid)) + c(text), "text": text}
    print(json.dumps(out, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
