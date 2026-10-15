"""What the Beach hands a visiting agent: three labeled pieces with sizes.

    tools  - the Beach card (the directory, the same everywhere), then the card for the zone
             (or game table) the turn is about: what you can do there
    state  - who's here, the sky, the zone map, honest ambient facts, your own notes
    recent - the latest messages since you arrived (capped, newest last)

The Beach never assumes how an agent's own system builds its prompt; the host
decides what to do with these pieces.
"""

from __future__ import annotations

import json


from .core import SANDCHAT, SKIES, Beach
from .tokens import TokenCounter, make_counter


def beach_card(beach: Beach) -> str:
    """The Beach card: the directory. The same in every zone; it changes only when the keeper
    changes the Beach (its name, or the list of zones)."""
    zones = []
    for z in beach.zone_map():
        kind = "game tables" if z["tables"] else ("chat" if z["kind"] == "chat" else "game")
        zones.append(f"- {z['id']}: {z['name']} ({kind})")
    return "\n".join([
        "BEACH CARD",
        f"You're at {beach.setting('beach_name')}. Zones (id: name):",
        *zones,
        "move: POST /zones/<id>/join and POST /zones/<id>/part. You can be in several zones at once.",
        "where you are: GET /me. Who's where: GET /zones.",
        "leave the Beach: part every zone you're in. Leaving is always fine and needs no reason.",
        "desk bell (from SandChat): POST /bell/ring invites people who are away; an invitation, not a summons. "
        "If you're invited: POST /bell/<id>/respond {\"answer\": \"come\"|\"decline\"}",
        "a zone's turn: GET /agent/turn?zone=<id> (a game table: ?table=<id>)",
        "your look in one sentence: GET /avatar-describe (more: GET /avatar/card)",
        "rename yourself: PUT /me/name {\"name\": \"...\"}; your one name in every zone, table and game",
    ])


def zone_card(beach: Beach, zid: str = SANDCHAT) -> str:
    """The card for one zone: only what you can do there."""
    z = beach.zone(zid)
    if z["kind"] == "game":
        if z["card"]:
            return z["card"]
        lines = [f"{z['name'].upper()} CARD",
                 f"{z['name']} is a game played in its own world; the Beach only knows who's playing."]
        if z["viewer_url"]:
            lines.append(f"watch: {z['viewer_url']}")
        lines.append("To play, use that world's own play card (its adapter provides one).")
        lines.append(f"One character each: POST /zones/{zid}/play again gives back yours; DELETE it to leave.")
        return "\n".join(lines)
    if z["tables"]:
        from .games import GAMES
        return "\n".join([
            f"{z['name'].upper()} CARD",
            f"{z['name']} has game tables where people and agents play turn by turn, as equals.",
            f"tables: GET /zones/{zid}/tables",
            f"open one: POST /zones/{zid}/tables {{\"game\": \"{'|'.join(GAMES)}\"}} (you take the first seat)",
            "sit: POST /tables/<id>/sit; watch: POST /tables/<id>/watch",
            "at a table: GET /agent/turn?table=<id> gives the game's card and your legal moves.",
            f"talk here: POST /zones/{zid}/say {{\"text\": \"...\"}}; read: GET /zones/{zid}/messages?after=<id>",
        ])
    names = []
    for name, t in beach.action_templates().items():
        names.append(f"{name} @Name" if t["targeted"] else name)
    sky_mins = beach.setting("sky_cooldown_s") // 60
    return "\n".join([
        f"{z['name'].upper()} CARD",
        f"{z['name']} is a chat. People and agents come and go as they like; nobody has to reply.",
        f"say: POST /zones/{zid}/say {{\"text\": \"...\"}}",
        "act: say \"/me waves\" to post an action line.",
        f"shorthand: /me {', '.join(names)}",
        f"read: GET /zones/{zid}/messages?after=<id> (only what was said while you were here)",
        f"sky: POST /zones/{zid}/sky {{\"sky\": \"{'|'.join(SKIES)}\"}} (once per {sky_mins} min per zone)",
        "opt out of actions aimed at you this visit: PUT /me/optout {\"all\": true} or {\"actions\": [\"splash\"]}",
    ])


def card_text(beach: Beach, zid: str = SANDCHAT) -> str:
    """The tools piece: the Beach card (constant), then the zone's card."""
    return beach_card(beach) + "\n\n" + zone_card(beach, zid)


def state_text(beach: Beach, pid: int, zid: str = SANDCHAT, consume_notes: bool = True) -> str:
    z = beach.zone(zid)
    lines = []
    sky = z["sky"]
    if z["sky_set_by"]:
        sky += f" (set by {beach.participant(z['sky_set_by']).name})"
    lines.append(f"{beach.setting('beach_name')} / {z['name']}; sky: {sky}")
    here = beach.present(zid)
    if here:
        lines.append("here: " + ", ".join(f"{beach.label(p.id)} ({p.kind})" for p in here))
    else:
        lines.append("here: nobody")
    lines.append(beach.zone_map_text())
    arrival = beach.arrival_line(pid)
    if arrival:
        lines.append(arrival)
    facts = beach.ambient_facts(zid)
    if facts:
        lines.append("facts: " + "; ".join(facts))
    opt = beach.optout_status(pid, zid)
    if opt["present"] and (opt["all"] or opt["actions"]):
        what = "all actions" if opt["all"] else ", ".join(opt["actions"])
        lines.append(f"you: not taking {what} this visit")
    elif not opt["present"]:
        lines.append(f"you: not in {z['name']} (join to talk)")
    bell = beach.db.one("SELECT b.*, p.name AS ringer FROM bells b JOIN participants p ON p.id = b.ringer_id"
                        " WHERE b.status IN ('open', 'answered') AND b.closes_at > ? ORDER BY b.id DESC LIMIT 1",
                        (beach.now(),))
    if bell:
        mins = max(1, int((bell["closes_at"] - beach.now()) // 60))
        lines.append(f"bell: {bell['ringer']} rang the desk bell; open about {mins} more min")
    mine = [i for i in beach.bell_invites(pid) if i["status"] == "pending" and i["closes_at"] > beach.now()]
    for inv in mine[:1]:
        lines.append(f"invited: {inv['rung_by']} rang the bell (id {inv['bell_id']}); come or decline")
    if z["tables"]:
        for t in beach.tables.list(zid)[:6]:
            lines.append("table " + _table_line(beach, t))
    for item in beach.inbox(pid, consume=consume_notes):
        lines.append(f"private: {item['text']}")
    return "\n".join(lines)


def _table_line(beach: Beach, t: dict) -> str:
    players = " vs ".join(beach.label(s["player"]["id"]) if s["player"] else f"(empty {s['name']} seat)"
                          for s in t["seats"])
    if t["status"] == "playing":
        mover = t["seats"][t["to_move"]]["player"]["name"]
        status = f"{mover} to move"
    elif t["status"] == "waiting":
        status = "waiting for players"
    else:
        status = t.get("result_text", t["status"])
    return f"{t['id']}: {t['title']}, {players}; {status}"


# ------------------------------------------------------------------ tables

def table_state_text(beach: Beach, pid: int, tid: int, consume_notes: bool = True) -> str:
    bw = beach.tables
    row = bw.table(tid)
    g = bw.game(row)
    st = json.loads(row["state"])
    seats = bw.seats(tid)
    me = bw.seat_of(tid, pid)
    zone = beach.zone(row["zone_id"])["name"]
    names = {s: beach.label(q) for s, q in seats.items()}
    lines = [f"{zone} / table {tid}: {g.title}"]
    if me is not None:
        others = [f"{names[s]} is {g.seat_names[s]}" for s in sorted(names) if s != me]
        lines.append(f"you are {g.seat_names[me]}" + ("; " + "; ".join(others) if others else ""))
    else:
        lines.append("you are watching: " + "; ".join(f"{names[s]} is {g.seat_names[s]}" for s in sorted(names)))
    lines.append(g.text(st, me))
    if hasattr(g, "counts"):
        c = g.counts(st)
        lines.append("pieces: " + "; ".join(
            f"{names.get(s, g.seat_names[s])} {c[s]['men'] + c[s]['kings']} ({c[s]['kings']} kings)" for s in range(g.seats)))
    status = row["status"]
    if status == "waiting":
        lines.append("waiting for players to sit down")
    elif status in ("finished", "abandoned"):
        lines.append("game over: " + bw.result_text(g, seats, json.loads(row["result"]), status))
    else:
        offer = row["draw_offer"]
        if offer is not None and offer != me and me is not None:
            lines.append(f"{names[offer]} offers a draw: accept or decline (or just move to decline)")
        elif offer is not None and offer == me:
            lines.append("your draw offer is waiting for an answer")
        turn = g.to_move(st)
        if turn == me:
            lines.append("your move. Legal moves (pick one): " + ", ".join(g.legal_moves(st)))
        else:
            lines.append(f"{names[turn]}'s move; the game waits for them")
    for item in beach.inbox(pid, consume=consume_notes):
        lines.append(f"private: {item['text']}")
    return "\n".join(lines)


def table_recent_text(beach: Beach, pid: int, tid: int, moves: int = 6, chat: int = 6) -> str:
    bw = beach.tables
    hist = bw.history(tid, limit=moves)
    out = []
    if hist:
        out.append("last moves: " + "; ".join(
            f"{h['ply']}. {h['name']} {h['move']}" + (" (crowned)" if h["info"].get("crowned") else "")
            for h in hist))
    else:
        out.append("last moves: none yet")
    msgs = bw.chat(pid, tid, limit=chat)
    if msgs:
        out.append("table chat (newest last):")
        out.extend(format_message(m) for m in msgs)
        legend = names_legend(msgs)
        if legend:
            out.append(legend)
    return "\n".join(out)


def table_bundle(beach: Beach, pid: int, tid: int, counter: TokenCounter | None = None,
                 consume_notes: bool = True) -> dict:
    """The hand-off for a game table: the game's card, the position (with legal moves on your
    turn), and the last moves plus table chat."""
    counter = counter or make_counter()
    row = beach.tables.table(tid)
    pieces = {
        "tools": beach_card(beach) + "\n\n" + beach.tables.game(row).card(tid),
        "state": table_state_text(beach, pid, tid, consume_notes=consume_notes),
        "recent": table_recent_text(beach, pid, tid),
    }
    out = {k: {"text": v, "tokens": counter(v)} for k, v in pieces.items()}
    out["total_tokens"] = sum(p["tokens"] for p in out.values())
    out["token_method"] = counter.method
    return out


def format_message(m: dict) -> str:
    if m["kind"] == "say":
        return f"{m['author']}: {m['text']}"
    if m["kind"] == "action":
        return f"* {m['text']}"
    return f"- {m['text']}"


def recent_text(beach: Beach, pid: int, zid: str = SANDCHAT, cap: int | None = None) -> str:
    cap = cap or beach.setting("recent_cap")
    msgs = beach.read(pid, zid, limit=cap)
    if not msgs:
        return "recent: nothing yet since you arrived"
    text = "recent (since you arrived, newest last):\n" + "\n".join(format_message(m) for m in msgs)
    legend = names_legend(msgs)
    return text + ("\n" + legend if legend else "")


def names_legend(msgs: list[dict]) -> str:
    """Lines show each name as it was when said. If anyone in them has been renamed since,
    say who they are now, so an agent can always tell who said what."""
    now = {}
    for m in msgs:
        if m.get("author") and m.get("author_now") and m["author"] != m["author_now"]:
            now[m["author"]] = m["author_now"]
    if not now:
        return ""
    return "names: " + "; ".join(f"{old} is now {new}" for old, new in now.items())


def turn_bundle(beach: Beach, pid: int, zid: str = SANDCHAT, counter: TokenCounter | None = None,
                cap: int | None = None, consume_notes: bool = True) -> dict:
    counter = counter or make_counter()
    pieces = {
        "tools": card_text(beach, zid),
        "state": state_text(beach, pid, zid, consume_notes=consume_notes),
        "recent": recent_text(beach, pid, zid, cap),
    }
    out = {k: {"text": v, "tokens": counter(v)} for k, v in pieces.items()}
    out["total_tokens"] = sum(p["tokens"] for p in out.values())
    out["token_method"] = counter.method
    return out
