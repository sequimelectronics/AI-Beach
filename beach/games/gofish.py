# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Becky Northaven and the AI-Beach contributors
"""Go Fish, 2-5 players, with the common rules:

- One standard 52-card deck. 2-3 players get 7 cards each; 4-5 players get 5 each. The rest is
  the stock ("the pond"), face down.
- On your turn, ask one other player, by name, for a rank you already hold ("ask Pebble 7s").
  If they have any, they hand over all of them and you ask again. If not, they say "go fish" and
  you draw one card: if it's the rank you asked for, you show it and ask again; otherwise the
  turn passes to the next player.
- Four of a rank make a book, laid down at once.
- If your hand is empty on your turn, draw a card first ("draw"), then ask. With an empty hand
  and an empty stock you sit out the rest of the game.
- When all thirteen books are made, whoever has the most books wins (a tie is shared).

Moves: "ask Pebble 7s" (ranks: As 2s .. 10s Js Qs Ks), and "draw" when your hand is empty.
What everyone at a real table would see is public (who asked whom for what, how many changed
hands, a fished card that matched, books); the card you fish otherwise is yours alone.
"""

from __future__ import annotations

import json

from . import IllegalMove
from .cards import (RANKS, CardGame, deck, new_seed, number_word, parse_rank, players_option,
                    plural, rank, shuffled, sort_hand)


class GoFish(CardGame):
    id = "gofish"
    title = "go fish"

    # ------------------------------------------------------------- state

    def new(self, options: dict | None = None) -> dict:
        options = options or {}
        n = players_option(options, 2, 5)
        seed = new_seed(options)
        stock = shuffled(deck(), seed, 0)
        per = 7 if n <= 3 else 5
        hands = [[] for _ in range(n)]
        for _ in range(per):
            for s in range(n):
                hands[s].append(stock.pop())
        s = {"players": n, "hands": [sort_hand(h) for h in hands], "stock": stock,
             "books": [[] for _ in range(n)], "turn": 0, "ply": 0, "seed": seed, "shuffles": 0,
             "out": [], "over": None, "names": []}
        for seat in range(n):
            self._lay_books(s, seat)
        return s

    def drop(self, state: dict, seat: int) -> dict:
        state["shuffles"] += 1
        state["stock"] = shuffled(state["stock"] + state["hands"][seat], state["seed"], state["shuffles"])
        state["hands"][seat] = []
        return state

    # ------------------------------------------------------------- rules

    @staticmethod
    def _lay_books(s: dict, seat: int) -> list[str]:
        made = []
        hand = s["hands"][seat]
        for r in RANKS:
            if sum(1 for c in hand if rank(c) == r) == 4:
                hand[:] = [c for c in hand if rank(c) != r]
                s["books"][seat].append(r)
                made.append(r)
        return made

    def _can_act(self, s: dict, seat: int) -> bool:
        return bool(s["hands"][seat]) or bool(s["stock"])

    def _next_turn(self, state: dict, seat: int) -> int | None:
        return self._after(state, seat, lambda q: self._can_act(state, q))

    def _targets(self, s: dict, seat: int) -> list[int]:
        return [q for q in self.active(s) if q != seat and s["hands"][q]]

    def legal_moves(self, state: dict) -> list[str]:
        if state.get("over"):
            return []
        seat = state["turn"]
        hand = state["hands"][seat]
        targets = self._targets(state, seat)
        if not hand or not targets:
            return ["draw"] if state["stock"] else []
        ranks = [r for r in RANKS if any(rank(c) == r for c in hand)]
        return [f"ask {self.name(state, q)} {plural(r)}" for q in targets for r in ranks]

    def _parse(self, state: dict, move: str):
        """'ask pebble 7s', 'Ask Pebble for sevens'... -> (seat, rank) or a reason it isn't one."""
        words = " ".join((move or "").split())
        if words.lower() == "draw":
            return "draw", None
        if not words.lower().startswith("ask "):
            return None, 'write a move like "ask Pebble 7s" (or "draw" when your hand is empty)'
        body = words[4:]
        if body.lower().endswith(" for"):
            body = body[:-4]
        head, _, last = body.rpartition(" ")
        if head.lower().endswith(" for"):
            head = head[:-4]
        r = parse_rank(last)
        if not head or r is None:
            return None, 'name a player and a rank, like "ask Pebble 7s"'
        seats = [q for q in range(state["players"]) if self.name(state, q).lower() == head.strip().lower()]
        if not seats:
            return None, f"nobody here is called {head.strip()}"
        return (seats[0], r), None

    def play(self, state: dict, move: str) -> tuple[dict, dict]:
        if state.get("over"):
            raise IllegalMove("the game is over")
        legal = self.legal_moves(state)
        parsed, why = self._parse(state, move)
        seat = state["turn"]
        if parsed is None:
            raise IllegalMove(why)
        if parsed == "draw":
            if "draw" not in legal:
                raise IllegalMove("you can only draw when your hand is empty (or nobody has cards to ask for)")
            canon = "draw"
        else:
            q, r = parsed
            canon = f"ask {self.name(state, q)} {plural(r)}"
            if canon not in legal:
                if q == seat:
                    raise IllegalMove("you can't ask yourself")
                if q in state["out"]:
                    raise IllegalMove(f"{self.name(state, q)} has left the game")
                if not state["hands"][q]:
                    raise IllegalMove(f"{self.name(state, q)} has no cards")
                if not any(rank(c) == r for c in state["hands"][seat]):
                    raise IllegalMove(f"you can only ask for a rank you hold, and you have no {plural(r)}")
                raise IllegalMove("that ask isn't legal right now")
        s = json.loads(json.dumps(state))
        s["ply"] += 1
        me = self.name(s, seat)
        info = {"move": canon, "seat": seat}
        again = False
        if canon == "draw":
            card = s["stock"].pop()
            s["hands"][seat] = sort_hand(s["hands"][seat] + [card])
            info["text"] = f"{me} drew a card"
            info["private"] = {"drew": card}
            again = True
        else:
            q, r = parsed
            them = self.name(s, q)
            got = [c for c in s["hands"][q] if rank(c) == r]
            if got:
                s["hands"][q] = [c for c in s["hands"][q] if rank(c) != r]
                s["hands"][seat] = sort_hand(s["hands"][seat] + got)
                info["text"] = f"{me} asked {them} for {plural(r)} and got {number_word(len(got))}"
                info["got"] = len(got)
                again = True
            elif s["stock"]:
                card = s["stock"].pop()
                s["hands"][seat] = sort_hand(s["hands"][seat] + [card])
                if rank(card) == r:
                    a_n = "an" if r in ("A", "8") else "a"
                    info["text"] = f"{me} asked {them} for {plural(r)}: go fish! {me} fished {a_n} {r} and goes again"
                    info["fished"] = r
                    again = True
                else:
                    info["text"] = f"{me} asked {them} for {plural(r)}: go fish!"
                    info["private"] = {"drew": card}
            else:
                info["text"] = f"{me} asked {them} for {plural(r)}: go fish! (the stock is empty)"
        made = self._lay_books(s, seat)
        if made:
            info["books"] = made
            info["text"] += "; " + " and ".join(f"a book of {plural(b)}" for b in made) + " for " + me
        if sum(len(b) for b in s["books"]) == len(RANKS):
            s["over"] = self._result(s)
            return s, info
        if again and self._can_act(s, seat):
            s["turn"] = seat
            # Who moves next, in words: a first visitor read "X asked them for 4s and got one" as their own
            # turn starting (10-17). A catch means the asker goes again.
            if "goes again" not in info["text"]:
                info["text"] += f" ({me} goes again)"
        else:
            nxt = self._next_turn(s, seat)
            if nxt is None:             # nobody can act: only possible after players left
                s["over"] = self._result(s)
                return s, info
            s["turn"] = nxt
        return s, info

    def _result(self, s: dict) -> dict:
        playing = self.active(s)
        most = max(len(s["books"][q]) for q in playing)
        best = [q for q in playing if len(s["books"][q]) == most]
        word = "book" if most == 1 else "books"
        if len(best) == 1:
            return {"winner": best[0], "winners": best, "reason": f"most books: {most}"}
        return {"winner": None, "winners": best, "reason": f"tied on {most} {word}"}

    def resign(self, state: dict, seat: int) -> tuple[dict, dict | None]:
        s, out = super().resign(state, seat)
        if out is None and not any(self._can_act(s, q) for q in self.active(s)):
            s["over"] = self._result(s)
            return s, s["over"]
        return s, out

    # ------------------------------------------------------------- showing it

    def _books_line(self, s: dict) -> str:
        parts = [f"{self.name(s, q)} " + (" ".join(plural(b) for b in s["books"][q]) or "none")
                 for q in range(s["players"])]
        return "books: " + "; ".join(parts)

    def text(self, state: dict, seat: int | None) -> str:
        lines = [f"stock: {len(state['stock'])}", self._counts_line(state, seat), self._books_line(state)]
        if seat is not None and seat not in state["out"]:
            lines.append("your hand: " + (" ".join(state["hands"][seat]) or "empty"))
        return "\n".join(lines)

    def view(self, state: dict, seat: int | None) -> dict:
        mine = seat is not None and seat < state["players"]
        return {"kind": "cards", "stock": len(state["stock"]),
                "counts": [len(h) for h in state["hands"]], "books": [list(b) for b in state["books"]],
                "out": list(state["out"]), "turn": self.to_move(state), "ply": state["ply"],
                "hand": list(state["hands"][seat]) if mine else None}

    def card(self, table_id: int) -> str:
        t = f"/tables/{table_id}"
        return "\n".join([
            "GO FISH CARD",
            "Ask another player, by name, for a rank you hold. If they have any, you get them all and ask",
            "again; if not, go fish: draw one (ask again if it's that rank). Four of a rank make a book.",
            "Most books when all 13 are made wins. Empty hand on your turn: draw first.",
            "On your turn, state lists every legal ask. Pick one and send it exactly:",
            f"move: POST {t}/move {{\"move\": \"ask Pebble 7s\"}} (or \"draw\")",
            "You see only your own hand.",
            f"leave the game: POST {t}/resign (the others play on)",
            f"chat: POST {t}/say {{\"text\": \"...\"}}",
            "The game waits for you; leaving the zone never forfeits.",
        ])
