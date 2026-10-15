"""Crazy Eights, 2-5 players, with the common rules (as in most rule books):

- One standard 52-card deck. 2 players get 7 cards each; 3-5 players get 5 each. The rest is the
  stock, face down; its top card is turned up to start the pile. If that card is an eight it goes
  to the bottom of the stock and the next one is turned up.
- On your turn, play one card that matches the top card's suit or rank. Eights are wild: play one
  on anything and name the suit the next player must follow.
- If you can't play, draw one card. If it can be played you may play it straight away; if not
  (or if you'd rather keep it) you pass. You can't draw while you have a card you could play.
- When the stock runs out, the pile (all but its top card) is shuffled to make a new stock. If
  there's nothing left to draw either, a player who can't play passes. If every player passes in a
  row like that, the game is blocked: whoever holds the fewest cards wins (ties share it).
- The first player to empty their hand wins.

Moves: "play 7H", "play 8S name hearts", "draw", "pass".
"""

from __future__ import annotations

import json

from . import IllegalMove
from .cards import (SUIT_BY_NAME, SUIT_NAMES, CardGame, deck, new_seed, parse_card,
                    players_option, rank, shuffled, sort_hand, suit)

class CrazyEights(CardGame):
    id = "crazy8"
    title = "crazy eights"

    # ------------------------------------------------------------- state

    def new(self, options: dict | None = None) -> dict:
        options = options or {}
        n = players_option(options, 2, 5)
        seed = new_seed(options)
        stock = shuffled(deck(), seed, 0)
        per = 7 if n == 2 else 5
        hands = [[] for _ in range(n)]
        for _ in range(per):
            for s in range(n):
                hands[s].append(stock.pop())
        while rank(stock[-1]) == "8":
            stock.insert(0, stock.pop())
        top = stock.pop()
        return {"players": n, "hands": [sort_hand(h) for h in hands], "stock": stock, "pile": [top],
                "suit": suit(top), "turn": 0, "drawn": None, "ply": 0, "seed": seed, "shuffles": 0,
                "out": [], "passes": 0, "over": None, "names": []}

    def drop(self, state: dict, seat: int) -> dict:
        state["stock"] = state["hands"][seat] + state["stock"]     # under the stock
        state["hands"][seat] = []
        return state

    # ------------------------------------------------------------- rules

    def _plays(self, state: dict, cards: list[str]) -> list[str]:
        top = state["pile"][-1]
        out = []
        for c in cards:
            if rank(c) == "8":
                out.extend(f"play {c} name {SUIT_NAMES[s]}" for s in SUIT_NAMES)
            elif suit(c) == state["suit"] or rank(c) == rank(top):
                out.append(f"play {c}")
        return out

    def _can_draw(self, state: dict) -> bool:
        return bool(state["stock"]) or len(state["pile"]) > 1

    def legal_moves(self, state: dict) -> list[str]:
        if state.get("over"):
            return []
        if state.get("drawn"):
            return self._plays(state, [state["drawn"]]) + ["pass"]
        plays = self._plays(state, state["hands"][state["turn"]])
        if plays:
            return plays
        return ["draw"] if self._can_draw(state) else ["pass"]

    def _canonical(self, move: str) -> str:
        """Forgiving reading: "play 7h", "Play 10 d", "play 8s hearts", "play 8S name Hearts"."""
        m = " ".join((move or "").strip().lower().split())
        words = m.split()
        if len(words) < 2 or words[0] != "play":
            return m
        rest = words[1:]
        card = parse_card(rest[0])
        if card is None and len(rest) > 1:
            card, rest = parse_card(rest[0] + rest[1]), rest[1:]
        if card is None:
            return m
        rest = [w for w in rest[1:] if w not in ("name", "naming", "call", "calling", "suit", "to")]
        if not rest:
            return f"play {card}"
        named = SUIT_BY_NAME.get(rest[0]) or (rest[0].upper() if rest[0].upper() in SUIT_NAMES else None)
        return f"play {card} name {SUIT_NAMES[named]}" if named and len(rest) == 1 else m

    def _why_not(self, state: dict, move: str, legal: list[str]) -> str:
        hand = state["hands"][state["turn"]]
        if move == "draw":
            return ("you've already drawn: play that card or pass" if state.get("drawn")
                    else "you have a card you can play, so you can't draw")
        if move == "pass":
            return "you can only pass after drawing, or when there's nothing left to draw"
        if not move.startswith("play "):
            return 'write a move like "play 7H", "play 8S name hearts" or "draw"'
        card = move.split()[1]
        if card not in hand:
            return f"{card} isn't in your hand"
        if state.get("drawn") and card != state["drawn"]:
            return f"after drawing you can only play the card you drew ({state['drawn']}) or pass"
        if rank(card) == "8" and " name " not in move:
            return f"an eight is wild: name the next suit, e.g. play {card} name hearts"
        top = state["pile"][-1]
        return f"{card} doesn't match the suit ({SUIT_NAMES[state['suit']]}) or the rank of {top}"

    def play(self, state: dict, move: str) -> tuple[dict, dict]:
        if state.get("over"):
            raise IllegalMove("the game is over")
        legal = self.legal_moves(state)
        move = self._canonical(move)
        if move not in legal:
            raise IllegalMove(self._why_not(state, move, legal))
        s = json.loads(json.dumps(state))
        seat = s["turn"]
        who = self.name(s, seat)
        hand = s["hands"][seat]
        info = {"move": move, "seat": seat}
        s["ply"] += 1
        if move == "draw":
            if not s["stock"]:
                top = s["pile"].pop()
                s["shuffles"] += 1
                s["stock"] = shuffled(s["pile"], s["seed"], s["shuffles"])
                s["pile"] = [top]
                info["reshuffled"] = True
            card = s["stock"].pop()
            hand.append(card)
            s["hands"][seat] = sort_hand(hand)
            s["drawn"] = card
            s["passes"] = 0
            info["text"] = f"{who} drew a card" + (" (the pile was shuffled into a new stock)"
                                                   if info.get("reshuffled") else "")
            info["private"] = {"drew": card}
            return s, info
        if move == "pass":
            stuck = not s.get("drawn")
            s["drawn"] = None
            s["passes"] = s["passes"] + 1 if stuck else 0
            info["text"] = f"{who} passed"
            if stuck and s["passes"] >= len(self.active(s)):
                fewest = min(len(s["hands"][q]) for q in self.active(s))
                best = [q for q in self.active(s) if len(s["hands"][q]) == fewest]
                s["over"] = {"winner": best[0] if len(best) == 1 else None, "winners": best,
                             "reason": "blocked: nobody could play or draw; fewest cards wins"}
                return s, info
            s["turn"] = self._after(s, seat)
            return s, info
        parts = move.split()
        card = parts[1]
        hand.remove(card)
        s["pile"].append(card)
        s["suit"] = SUIT_BY_NAME[parts[3]] if len(parts) == 4 else suit(card)
        s["drawn"] = None
        s["passes"] = 0
        info["card"] = card
        info["text"] = f"{who} played {card}" + (f" and named {parts[3]}" if len(parts) == 4 else "")
        if not hand:
            s["over"] = {"winner": seat, "winners": [seat], "reason": "first to empty their hand"}
            return s, info
        if len(hand) == 1:
            info["text"] += " (one card left)"
        s["turn"] = self._after(s, seat)
        return s, info

    # ------------------------------------------------------------- showing it

    def text(self, state: dict, seat: int | None) -> str:
        top = state["pile"][-1]
        follow = f" (suit to follow: {SUIT_NAMES[state['suit']]})" if state["suit"] != suit(top) else ""
        lines = [f"top card: {top}{follow}; stock: {len(state['stock'])}",
                 self._counts_line(state, seat)]
        if seat is not None and seat not in state["out"]:
            lines.append("your hand: " + " ".join(state["hands"][seat]))
            if state.get("drawn") and state["turn"] == seat and not state.get("over"):
                lines.append(f"you drew {state['drawn']}")
        return "\n".join(lines)

    def view(self, state: dict, seat: int | None) -> dict:
        mine = seat is not None and seat < state["players"]
        return {"kind": "cards", "top": state["pile"][-1], "suit": state["suit"],
                "stock": len(state["stock"]), "pile": len(state["pile"]),
                "counts": [len(h) for h in state["hands"]], "out": list(state["out"]),
                "turn": self.to_move(state), "ply": state["ply"],
                "hand": list(state["hands"][seat]) if mine else None,
                "drawn": state.get("drawn") if mine and state["turn"] == seat else None}

    def card(self, table_id: int) -> str:
        t = f"/tables/{table_id}"
        return "\n".join([
            "CRAZY EIGHTS CARD",
            "Play a card matching the top card's suit or rank. Eights are wild: name the next suit.",
            "Can't play? Draw one; play it if it fits, else pass. First to empty their hand wins.",
            "On your turn, state lists every legal move. Pick one and send it exactly:",
            f"move: POST {t}/move {{\"move\": \"play 7H\"}} (or \"play 8S name hearts\", \"draw\", \"pass\")",
            "Cards: rank then suit (A 2-10 J Q K; S H D C). You see only your own hand.",
            f"leave the game: POST {t}/resign (the others play on)",
            f"chat: POST {t}/say {{\"text\": \"...\"}}",
            "The game waits for you; leaving the zone never forfeits.",
        ])
