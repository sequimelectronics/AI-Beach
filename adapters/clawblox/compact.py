"""Turn a parsed observation into the compact view and the one-time map card.

Pure functions; see world.py for parsing. Two encodings of the same compact
view are provided so they can be measured against each other: plain text
(the default the adapter hands out) and compact JSON.
"""

from __future__ import annotations

import json
from collections import defaultdict

from .world import (
    MESA_RULES, Entity, Player, Rules, Snapshot, direction_to, dist3, fmt_vec,
    held_object, r1, resting_on, standing_on,
)

NEAR_COUNT = 8


# --- players ----------------------------------------------------------------

def players_in_radius(snap: Snapshot, names_by_entity: dict[int, str]) -> list[Player]:
    """Every other character within the observation radius, named when known.

    The server lists other players only inside your 105-degree view cone, but
    their characters are in the radius-only entity list as unnamed
    HumanoidRootPart parts. Match the two by position and remember entity id ->
    name (updated in place) so a player behind you is still listed.
    """
    mine = snap.my_entity()
    out: list[Player] = []
    seen_entities = set()
    for p in snap.named_players:
        pos = tuple(p["position"])
        ent = min((e for e in snap.entities if e.is_character and e is not mine),
                  key=lambda e: dist3(e.pos, pos), default=None)
        eid = None
        if ent is not None and dist3(ent.pos, pos) < 0.75:
            eid = ent.id
            names_by_entity[eid] = p.get("name") or names_by_entity.get(eid) or "someone"
            seen_entities.add(eid)
        out.append(Player(name=p.get("name") or "someone", pos=pos, in_view=True, entity_id=eid))
    for e in snap.entities:
        if not e.is_character or e is mine or e.id in seen_entities:
            continue
        out.append(Player(name=names_by_entity.get(e.id, "unknown player"), pos=e.pos,
                          in_view=False, entity_id=e.id))
    out.sort(key=lambda p: dist3(p.pos, snap.me))
    return out


# --- objects ----------------------------------------------------------------

def _object_row(e: Entity, snap: Snapshot, statics: list[Entity]) -> dict:
    on = resting_on(e, statics)
    return {
        "name": e.name,
        "kind": e.kind,
        "pos": [r1(v) for v in e.pos],
        "dist": r1(dist3(e.pos, snap.me)),
        "dir": direction_to(snap.me, e.pos),
        "on": on.name if on else None,
        "on_top": r1(on.top) if on else None,
    }


def summarize_rest(rows: list[dict]) -> str:
    """One line for everything beyond the nearest few.

    Many of a kind are grouped by direction with a distance range; a kind that
    appears once is named with its distance (and what it rests on).
    """
    by_kind: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        by_kind[r["kind"]].append(r)
    parts = []
    for kind in sorted(by_kind, key=lambda k: (-len(by_kind[k]), k)):
        group = by_kind[kind]
        if len(group) == 1:
            r = group[0]
            on = f" on {r['on']}" if r["on"] else ""
            parts.append(f"{r['name']} {kind} {fmt_vec(r['pos'])}{on} {r['dist']:g} {r['dir']}")
            continue
        by_dir: dict[str, list[float]] = defaultdict(list)
        for r in group:
            by_dir[r["dir"]].append(r["dist"])
        spans = []
        for d in sorted(by_dir, key=lambda d: min(by_dir[d])):
            ds = by_dir[d]
            lo, hi = min(ds), max(ds)
            span = f"{lo:.0f}" if round(lo) == round(hi) else f"{lo:.0f}-{hi:.0f}"
            spans.append(f"{len(ds)} {d} {span}")
        parts.append(f"{len(group)} {kind}s ({', '.join(spans)})")
    return "; ".join(parts)


def compact_view(snap: Snapshot, statics: list[Entity], names_by_entity: dict[int, str],
                 rules: Rules = MESA_RULES, near: int = NEAR_COUNT) -> dict:
    """The compact view as a plain dict (encoded as text or JSON below)."""
    held = held_object(snap, rules)
    objs = [e for e in snap.objects if held is None or e.id != held.id]
    rows = sorted((_object_row(e, snap, statics) for e in objs), key=lambda r: r["dist"])
    on = standing_on(snap, statics, rules)
    return {
        "tick": snap.tick,
        "me": [r1(v) for v in snap.me],
        "facing": snap.facing,
        "standing_on": on.name if on else None,
        "holding": held.name if held else None,
        "near": rows[:near],
        "rest": summarize_rest(rows[near:]) if len(rows) > near else "",
        "rest_count": max(0, len(rows) - near),
        "players": [
            {"name": p.name, "dist": r1(dist3(p.pos, snap.me)), "dir": direction_to(snap.me, p.pos),
             "in_view": p.in_view}
            for p in players_in_radius(snap, names_by_entity)
        ],
    }


def view_text(v: dict) -> str:
    me = f"you {fmt_vec(v['me'])}"
    if v["facing"]:
        me += f" facing {v['facing']}"
    if v["standing_on"]:
        me += f", on {v['standing_on']}"
    me += f", holding {v['holding']}" if v["holding"] else ", hands empty"
    lines = [me]
    total = len(v["near"]) + v["rest_count"]
    if v["near"]:
        lines.append(f"objects (nearest {len(v['near'])} of {total}; name kind pos dist dir):")
        for r in v["near"]:
            on = f" on {r['on']} (top {r['on_top']:g})" if r["on"] else ""
            lines.append(f"{r['name']} {r['kind']} {fmt_vec(r['pos'])} {r['dist']:g} {r['dir']}{on}")
    else:
        lines.append("objects: none in range")
    if v["rest"]:
        lines.append(f"farther: {v['rest']}")
    if v["players"]:
        ps = []
        for p in v["players"]:
            seen = "" if p["in_view"] else " (not in view)"
            ps.append(f"{p['name']} {p['dist']:g} {p['dir']}{seen}")
        lines.append("players: " + "; ".join(ps))
    else:
        lines.append("players: nobody else nearby")
    return "\n".join(lines)


def view_json(v: dict) -> str:
    """Same information as view_text, as compact JSON (for measurement)."""
    doc = {
        "me": v["me"], "facing": v["facing"], "on": v["standing_on"], "holding": v["holding"],
        "near": [[r["name"], r["kind"], r["pos"], r["dist"], r["dir"]] + ([r["on"]] if r["on"] else [])
                 for r in v["near"]],
        "farther": v["rest"],
        "players": [[p["name"], p["dist"], p["dir"], p["in_view"]] for p in v["players"]],
    }
    return json.dumps(doc, separators=(",", ":"))


# --- map card -----------------------------------------------------------------

def _span(lo: float, hi: float) -> str:
    return f"{lo:.0f}..{hi:.0f}"


def map_card_text(snap: Snapshot, rules: Rules = MESA_RULES) -> str:
    """One-time description of the static world, built from a full observation."""
    statics = snap.statics
    ground = [s for s in statics if s.role == "Ground"]
    ocean = [s for s in statics if s.role == "Ocean"]
    walls = [s for s in statics if s.transparency is not None and s.transparency >= 0.99
             and s.role is None]
    platforms = [s for s in statics if s not in ground and s not in ocean and s not in walls]

    lines = ["MAP (fixed scenery; x = east, z = north, y = up; distances in studs)"]
    if ground:
        x0 = min(s._box()[0][0] for s in ground)
        x1 = max(s._box()[1][0] for s in ground)
        z0 = min(s._box()[0][2] for s in ground)
        z1 = max(s._box()[1][2] for s in ground)
        top = max(s.top for s in ground)
        lines.append(f"island: flat ground, top y={top:g}, roughly x {_span(x0, x1)}, z {_span(z0, z1)}")
    if ocean:
        o = ocean[0]
        lines.append(f"ocean all around at y={r1(o.top):g} (you can't swim; you fall through it)")
    if walls:
        # Report each wall's inner face (the line you actually bump into).
        def face(c, half):
            return r1(c - half if c > 0 else c + half)
        xs = sorted({face(w.pos[0], w.size[0] / 2) for w in walls if w.size[0] < w.size[2]})
        zs = sorted({face(w.pos[2], w.size[2] / 2) for w in walls if w.size[2] < w.size[0]})
        edge = []
        if xs:
            edge.append("x=" + "/".join(f"{x:g}" for x in xs))
        if zs:
            edge.append("z=" + "/".join(f"{z:g}" for z in zs))
        lines.append(f"invisible walls at {', '.join(edge)} keep you on the island")
    if platforms:
        lines.append(f"platforms (name: centre x,z; size x*z; top y). Ledges up to ~{rules.jump_rise - 0.5:g} high can be jumped:")
        for p in sorted(platforms, key=lambda s: (s.pos[0], s.pos[2])):
            on = [q for q in platforms if q is not p and q.contains_xz(p.pos) and q.top < p.top]
            under = f" (rises from {on[0].name})" if on else ""
            lines.append(f"{p.name}: {r1(p.pos[0]):g},{r1(p.pos[2]):g}; "
                         f"{r1(p.size[0]):g}*{r1(p.size[2]):g}; top {r1(p.top):g}{under}")
    lines.append(f"you start at {fmt_vec(snap.me)}")

    # Movable landmarks at the start: cluster pickups of the same kind.
    clusters: list[list[Entity]] = []
    for e in sorted(snap.objects, key=lambda e: e.name):
        for c in clusters:
            if c[0].kind == e.kind and any(dist3(e.pos, o.pos) < 4.0 for o in c):
                c.append(e)
                break
        else:
            clusters.append([e])
    things = []
    for c in clusters:
        cx = sum(e.pos[0] for e in c) / len(c)
        cz = sum(e.pos[2] for e in c) / len(c)
        if len(c) > 1:
            things.append(f"a pile of {len(c)} {c[0].kind}s near {r1(cx):g},{r1(cz):g}")
        else:
            on = resting_on(c[0], statics)
            where = f" on {on.name}" if on else ""
            things.append(f"{c[0].name} ({c[0].kind}){where} at {r1(cx):g},{r1(cz):g}")
    if things:
        lines.append("movable things at the start: " + "; ".join(things))
    return "\n".join(lines)
