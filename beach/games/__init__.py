"""Table games for zones with tables (the Boardwalk).

The Boardwalk knows nothing about any particular game. A game is a class with
the interface below, registered in GAMES. The core stores each table's state
as the JSON the game returns, asks the game whose turn it is and what's legal,
and shows each seat only `view(state, seat)` / `text(state, seat)`: never the
raw state. That last rule is what lets card games (hidden hands) come later
without changing the Boardwalk.
"""

from __future__ import annotations


class IllegalMove(ValueError):
    """A refused move. `reason` is one short line for the player."""

    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


class TableGame:
    """What a table game provides. All methods are pure: state in, state out."""

    id = ""            # registry key, e.g. "checkers"
    title = ""         # shown to people, e.g. "checkers"
    seats = 2          # how many players
    seat_names: tuple[str, ...] = ()   # e.g. ("Black", "White")

    def new(self, options: dict) -> dict:
        """A fresh game state (JSON-serialisable). `options` come from keeper settings."""
        raise NotImplementedError

    def to_move(self, state: dict) -> int | None:
        """The seat whose turn it is, or None when the game is over."""
        raise NotImplementedError

    def legal_moves(self, state: dict) -> list[str]:
        """Every legal move for the seat to move, in the game's short notation."""
        raise NotImplementedError

    def play(self, state: dict, move: str) -> tuple[dict, dict]:
        """Apply a move for the seat to move. Returns (new state, info). Raises IllegalMove."""
        raise NotImplementedError

    def outcome(self, state: dict) -> dict | None:
        """None while playing; else {"winner": seat or None, "reason": "..."}."""
        raise NotImplementedError

    def text(self, state: dict, seat: int | None) -> str:
        """The position as compact text for an agent sitting at `seat` (None = watching)."""
        raise NotImplementedError

    def view(self, state: dict, seat: int | None) -> dict:
        """The position as data for the browser, as `seat` may see it."""
        raise NotImplementedError

    def card(self, table_id: int) -> str:
        """The short card telling an agent how to play at this table."""
        raise NotImplementedError


def registry() -> dict[str, TableGame]:
    from .checkers import Checkers
    return {g.id: g for g in (Checkers(),)}


GAMES = registry()
