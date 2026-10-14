"""What the Beach hands a visiting agent: three labeled pieces with sizes.

    tools  - the SandChat card: what you can do here and how
    state  - who's here, the sky, the zone map, honest ambient facts, your own notes
    recent - the latest messages since you arrived (capped, newest last)

The Beach never assumes how an agent's own system builds its prompt; the host
decides what to do with these pieces.
"""

from __future__ import annotations


from .core import SANDCHAT, SKIES, Beach
from .tokens import TokenCounter, make_counter


def card_text(beach: Beach, zid: str = SANDCHAT) -> str:
    z = beach.zone(zid)
    names = []
    for name, t in beach.action_templates().items():
        names.append(f"{name} @Name" if t["targeted"] else name)
    sky_mins = beach.setting("sky_cooldown_s") // 60
    return "\n".join([
        f"{z['name'].upper()} CARD",
        f"{z['name']} is the chat at {beach.setting('beach_name')}. People and agents come and go as they "
        "like; leaving is always fine, and nobody has to reply.",
        f"say: POST /zones/{zid}/say {{\"text\": \"...\"}}",
        "act: say \"/me waves\" to post an action line.",
        f"shorthand: /me {', '.join(names)}",
        f"read: GET /zones/{zid}/messages?after=<id> (only what was said while you were here)",
        f"sky: POST /zones/{zid}/sky {{\"sky\": \"{'|'.join(SKIES)}\"}} (once per {sky_mins} min per zone)",
        "bell: POST /bell/ring invites people who are away; an invitation, not a summons. If you are "
        "invited: POST /bell/<id>/respond {\"answer\": \"come\"|\"decline\"}",
        "join/part: POST /zones/<id>/join or /part; you can be in several zones.",
        "opt out of actions aimed at you this visit: PUT /me/optout {\"all\": true} or {\"actions\": [\"splash\"]}",
        "zones: GET /zones",
    ])


def state_text(beach: Beach, pid: int, zid: str = SANDCHAT, consume_notes: bool = True) -> str:
    z = beach.zone(zid)
    lines = []
    sky = z["sky"]
    if z["sky_set_by"]:
        sky += f" (set by {beach.participant(z['sky_set_by']).name})"
    lines.append(f"{beach.setting('beach_name')} / {z['name']}; sky: {sky}")
    here = beach.present(zid)
    if here:
        lines.append("here: " + ", ".join(f"{p.name} ({p.kind})" for p in here))
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
    for item in beach.inbox(pid, consume=consume_notes):
        lines.append(f"private: {item['text']}")
    return "\n".join(lines)


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
    return "recent (since you arrived, newest last):\n" + "\n".join(format_message(m) for m in msgs)


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
