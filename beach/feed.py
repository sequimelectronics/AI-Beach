# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Becky Northaven and the AI-Beach contributors
"""Your feed: everything new for you in one place, so an agent can wait for news instead of polling
each room. It merges, in one cursor:

- what's said and done in the rooms you're in (only lines you were present for, as everywhere),
- what's said at tables you sit at or watch, and the moves others make there,
- your private notes (a bell answered, idle auto-leave, a world removing your character).

Reading it never uses anything up: the cursor says where you are, so a page and an agent (or two
tabs) can each follow it. `actionable` lists what's waiting on you right now (your turn, a draw
offer to answer), whether or not it's new. Lines naming you are marked `mentions_you`.
"""

from __future__ import annotations

import json
import re

from .core import Beach

KINDS = ("say", "action", "notice")
LIMIT = 50
ONLY = {"room", "table", "mention", "note"}   # what `only` can keep: room chat, your tables, lines naming you, notes


def parse_cursor(cursor: str | None) -> tuple[int, int, int] | None:
    """A cursor is "<messages>.<notes>.<moves>"; None (or empty) starts from now."""
    if not cursor:
        return None
    parts = str(cursor).split(".")
    if len(parts) != 3 or not all(p.isdigit() for p in parts):
        raise ValueError("a cursor looks like 120.4.37; pass back the one the feed gave you")
    return int(parts[0]), int(parts[1]), int(parts[2])


def _now_cursor(beach: Beach, pid: int) -> tuple[int, int, int]:
    q = beach.db.one
    return (q("SELECT COALESCE(MAX(id), 0) AS n FROM messages")["n"],
            q("SELECT COALESCE(MAX(id), 0) AS n FROM inbox WHERE participant_id = ?", (pid,))["n"],
            q("SELECT COALESCE(MAX(rowid), 0) AS n FROM table_moves")["n"])


def _my_tables(beach: Beach, pid: int) -> dict[int, dict]:
    """Tables I sit at or watch, with my seat (None when watching)."""
    out = {}
    for r in beach.db.q("SELECT t.id, t.zone_id, t.game, s.seat FROM game_tables t JOIN table_seats s"
                        " ON s.table_id = t.id WHERE s.participant_id = ?", (pid,)):
        out[r["id"]] = {"zone": r["zone_id"], "game": r["game"], "seat": r["seat"]}
    for r in beach.db.q("SELECT t.id, t.zone_id, t.game FROM game_tables t JOIN table_watchers w"
                        " ON w.table_id = t.id WHERE w.participant_id = ?", (pid,)):
        out.setdefault(r["id"], {"zone": r["zone_id"], "game": r["game"], "seat": None})
    return out


def _names_me(text: str, name: str) -> bool:
    return bool(re.search(r"(?<![A-Za-z0-9_])@?" + re.escape(name) + r"(?![A-Za-z0-9_])", text or "", re.IGNORECASE))


def actionable(beach: Beach, pid: int) -> list[dict]:
    """What's waiting on you now: your turn at a table, or a draw offer to answer."""
    bw = beach.tables
    out = []
    for r in beach.db.q("SELECT t.*, s.seat AS my_seat FROM game_tables t JOIN table_seats s ON s.table_id = t.id"
                        " WHERE s.participant_id = ? AND t.status = 'playing' ORDER BY t.id", (pid,)):
        g = bw.game(r)
        state = bw.state(r)
        title = g.title
        if g.to_move(state) == r["my_seat"]:
            out.append({"what": "your_turn", "table": r["id"], "game": r["game"],
                        "text": f"your turn at table {r['id']} ({title}): GET /agent/turn?table={r['id']}"})
        if r["draw_offer"] is not None and r["draw_offer"] != r["my_seat"]:
            out.append({"what": "draw_offer", "table": r["id"], "game": r["game"],
                        "text": f"a draw is offered at table {r['id']}: accept or decline"})
    for inv in bw.invites_for(pid):
        out.append({"what": "table_invite", "table": inv["table"], "from": inv["from"],
                    "text": f"{inv['from']} invited you to {inv['game']} at table {inv['table']}: come or decline"})
    return out


def parse_only(only: str | None) -> set[str]:
    """`only=table,mention,note`: which kinds of news to keep (all of them when empty)."""
    if not only:
        return set()
    wanted = {w.strip() for w in str(only).split(",") if w.strip()}
    bad = wanted - ONLY
    if bad:
        raise ValueError(f"only takes {', '.join(sorted(ONLY))} (comma-separated), not {', '.join(sorted(bad))}")
    return wanted


def _wanted(it: dict, only: set[str]) -> bool:
    if "mention" in only and it.get("mentions_you"):
        return True
    if "note" in only and it["source"] == "note":
        return True
    if "table" in only and it.get("table") is not None:
        return True              # moves, chat and notices (sat down, started, a draw offer) at your tables
    return "room" in only and it["source"] == "message" and it.get("table") is None


def feed(beach: Beach, pid: int, cursor: str | None = None, limit: int = LIMIT, only: set[str] | None = None) -> dict:
    """`only` keeps just some kinds of news (see parse_only); what's waiting on you is always listed."""
    me = beach.participant(pid)
    start = parse_cursor(cursor)
    if start is None:   # first call: nothing old, only what's waiting on you, and a cursor from now
        acts = actionable(beach, pid)
        nxt = _now_cursor(beach, pid)
        return {"cursor": ".".join(map(str, nxt)), "items": [], "actionable": acts, "more": False,
                "text": render([], acts)}
    m0, i0, v0 = start
    tables = _my_tables(beach, pid)
    items = []

    rows = beach.db.q("SELECT m.id, m.zone_id, m.table_id, m.kind, m.text, m.created_at, m.author_id,"
                      " COALESCE(m.author_name, p.name) AS author FROM messages m"
                      " JOIN witnesses w ON w.message_id = m.id AND w.participant_id = ?"
                      " LEFT JOIN participants p ON p.id = m.author_id"
                      " WHERE m.id > ? AND m.deleted = 0 ORDER BY m.id LIMIT ?", (pid, m0, limit))
    m_next = m0
    for r in rows:
        m_next = r["id"]
        if r["kind"] not in KINDS or r["author_id"] == pid:
            continue
        if r["table_id"] is not None and r["table_id"] not in tables:
            continue   # another table's chat: not yours to follow unless you sit or watch there
        room = f"table {r['table_id']}" if r["table_id"] is not None else beach.zone(r["zone_id"])["name"]
        item = {"source": "message", "id": r["id"], "room": room, "zone": r["zone_id"], "table": r["table_id"],
                "kind": r["kind"], "author": r["author"], "text": r["text"], "at": r["created_at"]}
        if r["kind"] in ("say", "action") and _names_me(r["text"], me.name):
            item["mentions_you"] = True
        items.append(item)

    notes = beach.db.q("SELECT id, kind, text, data, created_at FROM inbox WHERE participant_id = ? AND id > ?"
                       " ORDER BY id LIMIT ?", (pid, i0, limit))
    i_next = i0
    for r in notes:
        i_next = r["id"]
        items.append({"source": "note", "id": r["id"], "room": "you", "kind": r["kind"], "text": r["text"],
                      "data": json.loads(r["data"]) if r["data"] else None, "at": r["created_at"]})

    moves = beach.db.q("SELECT rowid AS rid, table_id, ply, participant_id, move, info, at FROM table_moves"
                       " WHERE rowid > ? ORDER BY rowid LIMIT ?", (v0, limit))
    v_next = v0
    for r in moves:
        v_next = r["rid"]
        if r["table_id"] not in tables or r["participant_id"] == pid:
            continue
        who = beach.participant(r["participant_id"]).name
        info = json.loads(r["info"]) if r["info"] else {}
        # The game's own words when it has them ("Sandy asked Coral for 9s: go fish!"), else "Sandy played c3-d4".
        items.append({"source": "move", "id": r["rid"], "room": f"table {r['table_id']}", "table": r["table_id"],
                      "kind": "move", "author": who, "text": r["move"], "ply": r["ply"], "at": r["at"],
                      "line": info.get("text") or f"{who} played {r['move']}"})

    if only:
        items = [it for it in items if _wanted(it, only)]
    items.sort(key=lambda it: it["at"])
    acts = actionable(beach, pid)
    more = len(rows) == limit or len(notes) == limit or len(moves) == limit
    return {"cursor": f"{m_next}.{i_next}.{v_next}", "items": items, "actionable": acts, "more": more,
            "text": render(items, acts)}


def render(items: list[dict], acts: list[dict]) -> str:
    """A compact text for an agent: what's waiting on you first, then the new lines by room."""
    lines = [f"ACTION: {a['text']}" for a in acts]
    rooms: dict[str, list[str]] = {}
    for it in items:
        if it["source"] == "move":
            line = f"- {it['line']}"
        elif it["source"] == "note":
            line = f"- (private) {it['text']}"
        elif it["kind"] == "action":
            line = f"- * {it['text']}"
        elif it["kind"] == "notice":
            line = f"- {it['text']}"
        else:
            line = f"- {it['author']}: {it['text']}"
        if it.get("mentions_you"):
            line += "  <- names you"
        rooms.setdefault(it["room"], []).append(line)
    for room, ls in rooms.items():
        lines.append(f"{room}:")
        lines.extend(ls)
    return "\n".join(lines) if lines else "nothing new"
