# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Becky Northaven and the AI-Beach contributors
"""Checkers: standard 8x8 English draughts.

- Black (seat 0) moves first, from ranks 1-3 up the board; White (seat 1) from ranks 6-8 down.
- Men move one square diagonally forward; kings one square diagonally either way.
- Captures are compulsory. A capture jumps an adjacent enemy piece to the empty square beyond;
  if the capturing piece can jump again it must, and the whole sequence is one move. When
  there's a choice of captures (or of paths within one), any of them may be chosen.
- A man reaching the far row is crowned and the move ends there, even mid-sequence.
- You lose when you have no legal move (no pieces, or all blocked).
- Draws: by agreement (handled by the table), or after `quiet_limit` moves each in which nobody
  captured and no man (uncrowned piece) moved: only kings shuffling about.

Squares are named a1..h8 (a1 is a dark square, bottom left from Black's side). Notation:
"c3-d4" for a step, "e3xc5xa7" for a capture with every landing square.
"""

from __future__ import annotations

import re

from . import IllegalMove, TableGame

EMPTY = "."
MEN = ("b", "w")      # seat 0, seat 1
KINGS = ("B", "W")
FORWARD = (1, -1)     # rank direction for each seat's men
DIRS = ((1, 1), (-1, 1), (1, -1), (-1, -1))
MOVE_RE = re.compile(r"^[a-h][1-8](?:-[a-h][1-8]|(?:x[a-h][1-8])+)$")


def sq(f: int, r: int) -> str:
    return "abcdefgh"[f] + str(r + 1)


def parse_sq(s: str) -> tuple[int, int]:
    return "abcdefgh".index(s[0]), int(s[1]) - 1


def _seat_of(piece: str) -> int | None:
    if piece in ("b", "B"):
        return 0
    if piece in ("w", "W"):
        return 1
    return None


class Checkers(TableGame):
    id = "checkers"
    title = "checkers"
    seats = 2
    seat_names = ("Black", "White")

    # ------------------------------------------------------------- state

    def new(self, options: dict | None = None) -> dict:
        board = [EMPTY] * 64
        for r in range(8):
            for f in range(8):
                if (f + r) % 2 == 0:
                    if r <= 2:
                        board[r * 8 + f] = "b"
                    elif r >= 5:
                        board[r * 8 + f] = "w"
        limit = int((options or {}).get("quiet_limit", 40))
        return {"board": "".join(board), "turn": 0, "quiet": 0, "ply": 0, "quiet_limit": limit,
                "over": None}

    @staticmethod
    def from_pieces(pieces: dict[str, str], turn: int = 0, quiet_limit: int = 40) -> dict:
        """A position from {"c3": "b", "d6": "W", ...} (for tests and puzzles)."""
        board = [EMPTY] * 64
        for name, p in pieces.items():
            f, r = parse_sq(name)
            if (f + r) % 2:
                raise ValueError(f"{name} is a light square")
            board[r * 8 + f] = p
        return {"board": "".join(board), "turn": turn, "quiet": 0, "ply": 0, "quiet_limit": quiet_limit,
                "over": None}

    def to_move(self, state: dict) -> int | None:
        return None if state.get("over") else state["turn"]

    def outcome(self, state: dict) -> dict | None:
        return state.get("over")

    # ------------------------------------------------------------- rules

    @staticmethod
    def _at(board: str, f: int, r: int) -> str | None:
        if 0 <= f < 8 and 0 <= r < 8:
            return board[r * 8 + f]
        return None

    def _dirs(self, piece: str) -> tuple:
        if piece in KINGS:
            return DIRS
        fwd = FORWARD[_seat_of(piece)]
        return tuple(d for d in DIRS if d[1] == fwd)

    def _captures_from(self, board: str, f: int, r: int, piece: str, taken: frozenset,
                       path: list[str]) -> list[list[str]]:
        """Every complete capture sequence for `piece` standing on (f, r)."""
        seat = _seat_of(piece)
        found = []
        for df, dr in self._dirs(piece):
            mf, mr, lf, lr = f + df, r + dr, f + 2 * df, r + 2 * dr
            mid, land = self._at(board, mf, mr), self._at(board, lf, lr)
            if mid is None or land is None or land != EMPTY:
                continue
            if _seat_of(mid) not in (1 - seat,) or (mf, mr) in taken:
                continue
            step = path + [sq(lf, lr)]
            crowned = piece in MEN and lr == (7 if seat == 0 else 0)
            if crowned:
                found.append(step)          # crowning ends the move
                continue
            # Move the piece for the rest of the sequence (its old square becomes empty).
            b = list(board)
            b[r * 8 + f] = EMPTY
            b[lr * 8 + lf] = piece
            more = self._captures_from("".join(b), lf, lr, piece, taken | {(mf, mr)}, step)
            found.extend(more or [step])
        return found

    def legal_moves(self, state: dict) -> list[str]:
        if state.get("over"):
            return []
        board, seat = state["board"], state["turn"]
        captures, steps = [], []
        for r in range(8):
            for f in range(8):
                p = board[r * 8 + f]
                if _seat_of(p) != seat:
                    continue
                for path in self._captures_from(board, f, r, p, frozenset(), [sq(f, r)]):
                    captures.append("x".join(path))
                for df, dr in self._dirs(p):
                    if self._at(board, f + df, r + dr) == EMPTY:
                        steps.append(f"{sq(f, r)}-{sq(f + df, r + dr)}")
        moves = captures or steps
        return sorted(set(moves), key=lambda m: (m[1], m[0], m))

    def _why_not(self, state: dict, move: str, legal: list[str]) -> str:
        if not MOVE_RE.match(move):
            return "write a move like c3-d4, or a capture like e3xc5 (every landing square)"
        board, seat = state["board"], state["turn"]
        f, r = parse_sq(move[:2])
        if _seat_of(board[r * 8 + f]) != seat:
            return f"you have no piece on {move[:2]}"
        if any("x" in m for m in legal) and "-" in move:
            return "a capture is available, and captures are compulsory"
        if any(m.startswith(move + "x") for m in legal):
            return "that capture can go on, and it must: give the whole path"
        if "-" in move and not any(m.startswith(move[:2]) for m in legal):
            return f"the piece on {move[:2]} can't move"
        return "that move isn't legal here"

    def play(self, state: dict, move: str) -> tuple[dict, dict]:
        if state.get("over"):
            raise IllegalMove("the game is over")
        move = (move or "").strip().lower().replace(" ", "").replace(":", "x").replace("*", "x")
        legal = self.legal_moves(state)
        if move not in legal:
            raise IllegalMove(self._why_not(state, move, legal))
        seat = state["turn"]
        board = list(state["board"])
        squares = re.split(r"[-x]", move)
        f0, r0 = parse_sq(squares[0])
        piece = board[r0 * 8 + f0]
        board[r0 * 8 + f0] = EMPTY
        captured = []
        if "x" in move:
            for a, b in zip(squares, squares[1:]):
                (fa, ra), (fb, rb) = parse_sq(a), parse_sq(b)
                mf, mr = (fa + fb) // 2, (ra + rb) // 2
                captured.append(sq(mf, mr))
                board[mr * 8 + mf] = EMPTY
        fz, rz = parse_sq(squares[-1])
        crowned = piece in MEN and rz == (7 if seat == 0 else 0)
        board[rz * 8 + fz] = KINGS[seat] if crowned else piece
        new = dict(state, board="".join(board), turn=1 - seat, ply=state["ply"] + 1,
                   # Progress (a capture, or any man moving) resets the no-progress count.
                   quiet=0 if (captured or piece in MEN) else state["quiet"] + 1)
        info = {"move": move, "seat": seat, "captured": captured, "crowned": crowned}
        if not self.legal_moves(new):
            gone = not any(_seat_of(p) == 1 - seat for p in new["board"])
            new["over"] = {"winner": seat, "reason": "all pieces captured" if gone else "no moves left"}
        elif new["quiet"] >= 2 * new["quiet_limit"]:
            new["over"] = {"winner": None, "reason": f"{new['quiet_limit']} moves each with only kings moving and no capture"}
        return new, info

    # ------------------------------------------------------------- showing it

    def counts(self, state: dict) -> list[dict]:
        b = state["board"]
        return [{"men": b.count(MEN[s]), "kings": b.count(KINGS[s])} for s in (0, 1)]

    def text(self, state: dict, seat: int | None) -> str:
        """Rank 8 at the top for everyone (one fixed picture is easier to talk about)."""
        b = state["board"]
        rows = [f"{r + 1} " + " ".join(b[r * 8 + f] for f in range(8)) for r in range(7, -1, -1)]
        return "\n".join(rows + ["  a b c d e f g h"])

    def view(self, state: dict, seat: int | None) -> dict:
        b = state["board"]
        return {"board": {sq(f, r): b[r * 8 + f] for r in range(8) for f in range(8)
                          if b[r * 8 + f] != EMPTY},
                "turn": self.to_move(state), "counts": self.counts(state), "ply": state["ply"],
                "quiet": state["quiet"], "quiet_limit": state["quiet_limit"]}

    def card(self, table_id: int) -> str:
        t = f"/tables/{table_id}"
        return "\n".join([
            "CHECKERS CARD",
            "English checkers, 8x8. Black (b, king B) moves first, up the board; White (w, W) moves down.",
            "When it's your turn, state lists every legal move. Pick one and send it exactly:",
            f"move: POST {t}/move {{\"move\": \"c3-d4\"}}",
            "c3-d4 is a step; e3xc5xa7 is a capture through each landing square. Captures are compulsory.",
            "Men move and capture forward only; kings (reach the far row) move and capture both ways.",
            f"draw: POST {t}/draw {{\"action\": \"offer\"|\"accept\"|\"decline\"}}",
            f"resign: POST {t}/resign",
            f"chat: POST {t}/say {{\"text\": \"...\"}}",
            "The game waits for you; leaving never forfeits.",
        ])
