"""The Boardwalk: game tables in a zone, for turn-based games people and agents play as equals.

A table has a game (from beach.games), seats, watchers, the game's state, whose turn it is,
and the move history. The rules here are the game-independent ones:

- Anyone can open a table, sit, or watch; doing any of these (or moving) brings you into the
  zone, since playing at the Boardwalk is being at the Boardwalk.
- A game starts when every seat is taken, and waits for whoever's turn it is, for as long as
  it takes. Leaving the zone never forfeits.
- If the player to move is away, they get ONE "your move" notice for that turn (through the
  keeper's notification hook, and in their private events), and at most one per
  turn_notify_gap_s across all their tables. Never repeated.
- A game nobody has touched for table_abandon_s ends as abandoned: nobody wins or loses.
- Resigning is always available to a seated player. In a two-player game the other player wins;
  in a bigger card game the one who resigns leaves and the rest play on. Where the game allows
  draws (checkers), a draw offer stands until the opponent accepts, declines, or plays on
  (playing on declines it).
- Hidden information stays hidden: each seat is shown only `game.view/text(state, seat)`, the
  move history keeps only what the game marks public, and what only the mover may know (the card
  they drew) goes back to the mover alone, in the reply to their move.
- When a game finishes, SandChat may hear the result (announce_results); never mid-game.
- Table chat is a thread in the zone's own chat: the same messages, presence rules, deletes
  and opt-outs as any chat, tagged with the table.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from .games import GAMES, IllegalMove

if TYPE_CHECKING:
    from .core import Beach

LIVE = ("waiting", "playing")


class Boardwalk:
    def __init__(self, beach: "Beach"):
        self.beach = beach
        self.db = beach.db

    # ---------------------------------------------------------------- helpers

    def _err(self, code, msg, **kw):
        from .core import BeachError
        return BeachError(code, msg, **kw)

    def table(self, tid: int):
        row = self.db.one("SELECT * FROM game_tables WHERE id = ?", (tid,))
        if not row:
            raise self._err("not_found", f"no table {tid}")
        return row

    def game(self, row):
        return GAMES[row["game"]]

    def state(self, row) -> dict:
        """The table's game state, with the players' current names filled in (card games use them:
        moves like "ask Pebble 7s" name the player, and names can change between turns)."""
        state = json.loads(row["state"])
        if "names" in state:
            seats = self.seats(row["id"])
            state["names"] = [self._name(seats[s]) if s in seats else ""
                              for s in range(self.game(row).seat_count(state))]
        return state

    def seats(self, tid: int) -> dict[int, int]:
        return {r["seat"]: r["participant_id"]
                for r in self.db.q("SELECT seat, participant_id FROM table_seats WHERE table_id = ?", (tid,))}

    def seat_of(self, tid: int, pid: int) -> int | None:
        r = self.db.one("SELECT seat FROM table_seats WHERE table_id = ? AND participant_id = ?", (tid, pid))
        return r["seat"] if r else None

    def _zone_with_tables(self, zid: str):
        z = self.beach.zone(zid)
        if not z["tables"]:
            raise self._err("invalid", f"{z['name']} has no game tables")
        if not z["open"]:
            raise self._err("closed", f"{z['name']} is closed right now")
        return z

    def _arrive(self, pid: int, zid: str) -> None:
        """Opening, sitting, watching or moving brings you into the zone."""
        if not self.beach._visit(pid, zid):
            self.beach.join(pid, zid)
        else:
            self.beach.touch(pid, zid)

    def _line(self, row, text: str) -> None:
        """A notice in the table's thread (who sat, moves are not posted: the history holds them)."""
        self.beach._post(row["zone_id"], None, "notice", text, table_id=row["id"])

    def _name(self, pid: int) -> str:
        return self.beach.participant(pid).name

    # ---------------------------------------------------------------- tables

    def open(self, pid: int, zid: str, game: str, seat: int | None = 0, options: dict | None = None) -> dict:
        """Open a table. The opener sits at `seat` (default 0, who moves first); seat=None to just open it.
        `options`: {"players": 2-5} for the card games."""
        self._zone_with_tables(zid)
        if game not in GAMES:
            raise self._err("invalid", f"the games here are: {', '.join(GAMES)}")
        g = GAMES[game]
        live = self.db.one("SELECT COUNT(*) AS n FROM game_tables WHERE created_by = ? AND status = 'waiting'",
                           (pid,))["n"]
        if live >= 3:
            raise self._err("rate_limited", "you already have 3 tables waiting for players")
        self._arrive(pid, zid)
        now = self.beach.now()
        state = g.new({**(options or {}), "quiet_limit": self.beach.setting("checkers_quiet_limit")})
        tid = self.db.run("INSERT INTO game_tables (zone_id, game, state, created_by, created_at, last_activity)"
                          " VALUES (?, ?, ?, ?, ?, ?)", (zid, game, json.dumps(state), pid, now, now))
        self._line(self.table(tid), f"{self._name(pid)} opened a table for {g.title}")
        if seat is not None:
            self.sit(pid, tid, seat)
        return self.view(pid, tid)

    def sit(self, pid: int, tid: int, seat: int | None = None) -> dict:
        row = self.table(tid)
        g = self.game(row)
        self._zone_with_tables(row["zone_id"])
        if row["status"] != "waiting":
            raise self._err("conflict", "this game has already started; you can watch it")
        taken = self.seats(tid)
        n = g.seat_count(json.loads(row["state"]))
        if pid in taken.values():
            raise self._err("conflict", "you're already sitting at this table")
        free = [s for s in range(n) if s not in taken]
        if seat is None:
            seat = free[0] if free else None
        if seat is None or seat not in free:
            raise self._err("conflict", "that seat is taken" if free else "all seats are taken; you can watch")
        self._arrive(pid, row["zone_id"])
        now = self.beach.now()
        self.db.run("INSERT INTO table_seats VALUES (?, ?, ?)", (tid, seat, pid))
        self.db.run("DELETE FROM table_watchers WHERE table_id = ? AND participant_id = ?", (tid, pid))
        self.db.run("UPDATE game_tables SET last_activity = ? WHERE id = ?", (now, tid))
        self._line(row, f"{self._name(pid)} sat down " + (f"as {g.seat_names[seat]}" if g.seat_names
                                                          else f"({len(taken) + 1} of {n})"))
        if len(taken) + 1 == n:
            self.db.run("UPDATE game_tables SET status = 'playing', started_at = ?, turn_since = ? WHERE id = ?",
                        (now, now, tid))
            self._line(row, "the game has started")
        return self.view(pid, tid)

    def stand(self, pid: int, tid: int) -> dict:
        """Leave your seat before the game starts. Once it has started: resign instead."""
        row = self.table(tid)
        seat = self.seat_of(tid, pid)
        if seat is None:
            raise self._err("conflict", "you're not sitting at this table")
        if row["status"] != "waiting":
            raise self._err("conflict", "the game has started; to stop playing, resign")
        self.db.run("DELETE FROM table_seats WHERE table_id = ? AND participant_id = ?", (tid, pid))
        self._line(row, f"{self._name(pid)} stood up")
        if not self.seats(tid):
            self.db.run("UPDATE game_tables SET status = 'closed', finished_at = ? WHERE id = ?",
                        (self.beach.now(), tid))
        return self.view(pid, tid)

    def watch(self, pid: int, tid: int, on: bool = True) -> dict:
        row = self.table(tid)
        if on:
            self._zone_with_tables(row["zone_id"])
            self._arrive(pid, row["zone_id"])
            if self.seat_of(tid, pid) is None:
                self.db.run("INSERT OR IGNORE INTO table_watchers VALUES (?, ?)", (tid, pid))
        else:
            self.db.run("DELETE FROM table_watchers WHERE table_id = ? AND participant_id = ?", (tid, pid))
        return self.view(pid, tid)

    # ---------------------------------------------------------------- play

    def _playing_seat(self, pid: int, tid: int):
        row = self.table(tid)
        seat = self.seat_of(tid, pid)
        if seat is None:
            raise self._err("forbidden", "only the players at this table can do that")
        if row["status"] != "playing":
            raise self._err("conflict", "this game isn't being played" if row["status"] == "waiting"
                            else "this game is over")
        return row, seat

    def move(self, pid: int, tid: int, move: str) -> dict:
        row, seat = self._playing_seat(pid, tid)
        g = self.game(row)
        state = self.state(row)
        if g.to_move(state) != seat:
            other = self.seats(tid).get(g.to_move(state))
            raise self._err("conflict", f"it's {self._name(other) if other else 'the other side'}'s turn")
        try:
            new, info = g.play(state, str(move or ""))
        except IllegalMove as e:
            legal = g.legal_moves(state)
            raise self._err("invalid", f"{e.reason}. Legal moves: {', '.join(legal)}",
                            data={"reason": e.reason, "legal": legal}) from None
        private = info.pop("private", None)      # only for the mover: never stored, never shown to others
        self._arrive(pid, row["zone_id"])
        if row["game"] == "checkers":
            self.beach.badges.award(pid, "checkers")
        now = self.beach.now()
        ply = state.get("ply", 0) + 1
        offer = row["draw_offer"]
        if offer is not None and offer != seat:
            offer = None   # playing on declines the other side's offer
        self.db.run("INSERT INTO table_moves VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (tid, ply, seat, pid, info["move"], json.dumps(info), now))
        self.db.run("UPDATE game_tables SET state = ?, draw_offer = ?, last_activity = ?, turn_since = ?,"
                    " notified_ply = NULL WHERE id = ?", (json.dumps(new), offer, now, now, tid))
        out = g.outcome(new)
        if out:
            self._finish(tid, out)
        reply = {"moved": info["move"], "captured": info.get("captured", []),
                 "crowned": info.get("crowned", False), "over": out}
        if info.get("text"):
            reply["text"] = info["text"]
        if private:
            reply["private"] = private
        return reply

    def resign(self, pid: int, tid: int) -> dict:
        row, seat = self._playing_seat(pid, tid)
        g = self.game(row)
        name = self._name(pid)
        new, out = g.resign(self.state(row), seat)
        if out is not None:
            out = dict(out)
            if not out.get("reason"):
                out["reason"] = f"{name} resigned"
            if new.get("over"):
                new["over"] = out
        now = self.beach.now()
        self.db.run("UPDATE game_tables SET state = ?, last_activity = ?, turn_since = ?, notified_ply = NULL"
                    " WHERE id = ?", (json.dumps(new), now, now, tid))
        if out is None:
            self._line(row, f"{name} left the game; the others play on")
        else:
            self._finish(tid, out)
        return self.view(pid, tid)

    def draw(self, pid: int, tid: int, action: str) -> dict:
        row, seat = self._playing_seat(pid, tid)
        g = self.game(row)
        if not g.draws:
            raise self._err("invalid", f"there are no draw offers in {g.title}; you can resign to leave the game")
        offer = row["draw_offer"]
        now = self.beach.now()
        name = self._name(pid)
        if action == "offer":
            if offer == seat:
                raise self._err("conflict", "you've already offered a draw")
            if offer is not None:
                return self.draw(pid, tid, "accept")   # both want it
            self.db.run("UPDATE game_tables SET draw_offer = ?, last_activity = ? WHERE id = ?", (seat, now, tid))
            self._line(row, f"{name} offered a draw")
        elif action in ("accept", "decline"):
            if offer is None or offer == seat:
                raise self._err("conflict", "there's no draw offer from the other side")
            if action == "accept":
                self._finish(tid, {"winner": None, "reason": "a draw by agreement"})
            else:
                self.db.run("UPDATE game_tables SET draw_offer = NULL, last_activity = ? WHERE id = ?", (now, tid))
                self._line(row, f"{name} declined the draw")
        else:
            raise self._err("invalid", "action is offer, accept or decline")
        return self.view(pid, tid)

    def _finish(self, tid: int, outcome: dict, status: str = "finished") -> None:
        row = self.table(tid)
        g = self.game(row)
        now = self.beach.now()
        self.db.run("UPDATE game_tables SET status = ?, result = ?, draw_offer = NULL, finished_at = ?,"
                    " last_activity = ? WHERE id = ?", (status, json.dumps(outcome), now, now, tid))
        seats = self.seats(tid)
        names = [self._name(seats[s]) for s in sorted(seats)]
        verdict = self.result_text(g, seats, outcome, status)
        if status == "finished" and not g.seat_names:      # a card game, played to its end
            out = json.loads(row["state"]).get("out", [])
            for s, q in seats.items():
                if s not in out:
                    self.beach.badges.award(q, "card-game")
            for s in outcome.get("winners") or ([outcome["winner"]] if outcome.get("winner") is not None else []):
                if s in seats:
                    self.beach.badges.award(seats[s], "card-win")
        self._line(row, verdict[0].upper() + verdict[1:])
        if status == "finished" and self.beach.setting("announce_results") and len(names) >= 2:
            from .core import SANDCHAT
            zone = self.beach.zone(row["zone_id"])["name"]
            self.beach._post(SANDCHAT, None, "notice",
                             f"{_and(names)} finished a game of {g.title} on {zone}: {verdict}.")

    def result_text(self, g, seats: dict, outcome: dict, status: str = "finished") -> str:
        if status == "abandoned":
            return "the game was set aside unfinished"
        w = outcome.get("winner")
        reason = outcome.get("reason", "")
        both = outcome.get("winners") or []
        if w is None and len(both) > 1:
            who = _and([self._name(seats[s]) if s in seats else f"seat {s + 1}" for s in both])
            return f"{who} shared the win" + (f" ({reason})" if reason else "")
        if w is None:
            return f"a draw ({reason})" if reason and reason != "a draw by agreement" else "a draw"
        who = self._name(seats[w]) if w in seats else f"seat {w + 1}"
        return f"{who} won" + (f" ({reason})" if reason else "")

    # ---------------------------------------------------------------- upkeep

    def sweep(self) -> None:
        """Abandon forgotten games, and send at most one "your move" notice per waiting turn."""
        now = self.beach.now()
        cutoff = now - self.beach.setting("table_abandon_s")
        for row in self.db.q("SELECT * FROM game_tables WHERE status IN ('waiting', 'playing')"
                             " AND last_activity < ?", (cutoff,)):
            if row["status"] == "playing":
                self._finish(row["id"], {"winner": None, "reason": "abandoned"}, status="abandoned")
            else:
                self.db.run("UPDATE game_tables SET status = 'closed', finished_at = ? WHERE id = ?", (now, row["id"]))
        after = self.beach.setting("turn_notify_after_s")
        gap = self.beach.setting("turn_notify_gap_s")
        for row in self.db.q("SELECT * FROM game_tables WHERE status = 'playing' AND notified_ply IS NULL"
                             " AND turn_since <= ?", (now - after,)):
            g = self.game(row)
            state = self.state(row)
            seat = g.to_move(state)
            pid = self.seats(row["id"]).get(seat)
            if pid is None:
                continue
            p = self.beach.participant(pid)
            if self.beach._visit(pid, row["zone_id"]):
                continue   # they're here; check again later in case they step away
            # From here this turn is handled, whatever happens: never more than one notice per turn.
            self.db.run("UPDATE game_tables SET notified_ply = ? WHERE id = ?", (state.get("ply", 0), row["id"]))
            if not p.invitable:
                continue
            last = self.db.one("SELECT at FROM turn_notices WHERE participant_id = ?", (pid,))
            if last and now - last["at"] < gap:
                continue
            self.db.run("INSERT OR REPLACE INTO turn_notices VALUES (?, ?)", (pid, now))
            zone = self.beach.zone(row["zone_id"])["name"]
            opp = [self._name(q) for s, q in self.seats(row["id"]).items() if s != seat]
            text = f"your move at {zone}: {g.title} with {', '.join(opp)} (table {row['id']})"
            self.beach._note(pid, text, kind="event", data={"event": "your_move", "table": row["id"]})
            if self.beach.sender:
                try:
                    self.beach.sender({"event": "your_move", "beach": self.beach.setting("beach_name"),
                                       "zone": zone, "table": row["id"], "game": g.title, "invitee": p.name,
                                       "invitee_kind": p.kind, "opponents": opp,
                                       "turn": f"/agent/turn?table={row['id']}"})
                except Exception:   # a hook failure never breaks the Beach
                    pass

    # ---------------------------------------------------------------- reading

    def list(self, zid: str) -> list[dict]:
        self.beach.zone(zid)
        rows = self.db.q("SELECT * FROM game_tables WHERE zone_id = ? AND (status IN ('waiting', 'playing')"
                         " OR (status IN ('finished', 'abandoned') AND finished_at > ?))"
                         " ORDER BY CASE status WHEN 'playing' THEN 0 WHEN 'waiting' THEN 1 ELSE 2 END, id DESC",
                         (zid, self.beach.now() - 86400))
        return [self.summary(r) for r in rows]

    def _who(self, pid: int) -> dict:
        p = self.beach.participant(pid)
        return {"id": p.id, "name": p.name, "kind": p.kind, "v": self.beach.avatar_version(p.id)}

    def summary(self, row) -> dict:
        g = self.game(row)
        seats = self.seats(row["id"])
        state = json.loads(row["state"])
        to_move = g.to_move(state) if row["status"] == "playing" else None
        out = {"id": row["id"], "game": row["game"], "title": g.title, "status": row["status"],
               "seats": [{"seat": s, "name": g.seat_label(state, s),
                          "player": self._who(seats[s]) if s in seats else None}
                         for s in range(g.seat_count(state))],
               "to_move": to_move, "draws": g.draws,
               "watchers": self.db.one("SELECT COUNT(*) AS n FROM table_watchers WHERE table_id = ?",
                                       (row["id"],))["n"]}
        if row["result"]:
            out["result"] = json.loads(row["result"])
            out["result_text"] = self.result_text(g, seats, out["result"], row["status"])
        return out

    def history(self, tid: int, limit: int | None = None) -> list[dict]:
        sql = ("SELECT m.*, p.name FROM table_moves m JOIN participants p ON p.id = m.participant_id"
               " WHERE table_id = ? ORDER BY ply DESC")
        rows = self.db.q(sql + (" LIMIT ?" if limit else ""), (tid, limit) if limit else (tid,))
        return [{"ply": r["ply"], "seat": r["seat"], "name": r["name"], "move": r["move"],
                 "info": json.loads(r["info"] or "{}"), "at": r["at"]} for r in reversed(rows)]

    def view(self, pid: int, tid: int) -> dict:
        """Everything the browser shows at a table, as this participant may see it."""
        row = self.table(tid)
        g = self.game(row)
        state = self.state(row)
        seat = self.seat_of(tid, pid)
        out = self.summary(row)
        out.update({"zone": row["zone_id"], "my_seat": seat, "position": g.view(state, seat),
                    "draw_offer": row["draw_offer"], "history": self.history(tid),
                    "your_turn": row["status"] == "playing" and seat is not None and g.to_move(state) == seat,
                    "watching": bool(self.db.one("SELECT 1 FROM table_watchers WHERE table_id = ?"
                                                 " AND participant_id = ?", (tid, pid)))})
        out["legal"] = g.legal_moves(state) if out["your_turn"] else []
        return out

    def say(self, pid: int, tid: int, text: str) -> dict:
        row = self.table(tid)
        self._arrive(pid, row["zone_id"])
        return self.beach.post(pid, row["zone_id"], text, table_id=tid)

    def chat(self, pid: int, tid: int, after: int = 0, limit: int | None = None) -> list[dict]:
        row = self.table(tid)
        return self.beach.read(pid, row["zone_id"], after=after, limit=limit, table_id=tid)


def _and(names: list[str]) -> str:
    """"Sandy", "Sandy and Pebble", "Sandy, Pebble and Coral"."""
    return names[0] if len(names) == 1 else ", ".join(names[:-1]) + " and " + names[-1]
