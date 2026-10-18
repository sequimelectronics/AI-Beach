# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Becky Northaven and the AI-Beach contributors
"""Turn a parsed observation into the compact view and the one-time map card.

Pure functions; see world.py for parsing. Two encodings of the same compact
view are provided so they can be measured against each other: plain text
(the default the adapter hands out) and compact JSON.
"""

from __future__ import annotations

import json
from collections import defaultdict

from .world import (
    MESA_RULES, Entity, Player, Rules, Snapshot, beach_layout, direction_to, dist3, fmt_vec, watchers,
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
        p = dict(p, name=display_name(p))
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
        # Worlds that label characters (the beach sets PlayerName) are always named.
        label = e.attrs.get("PlayerName")
        if isinstance(label, str) and label:
            names_by_entity[e.id] = label
        out.append(Player(name=names_by_entity.get(e.id, "unknown player"), pos=e.pos,
                          in_view=False, entity_id=e.id))
    out.sort(key=lambda p: dist3(p.pos, snap.me))
    return out


def display_name(player: dict) -> str | None:
    """A player's name as their world shows it: a host-given name (a Beach's "BeachName",
    current across renames) when present, else the name they joined with."""
    named = (player.get("attributes") or {}).get("BeachName")
    return named if isinstance(named, str) and named else player.get("name")


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


def _plural(kind: str) -> str:
    return kind if kind.endswith("s") else kind + "s"


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
        parts.append(f"{len(group)} {_plural(kind)} ({', '.join(spans)})")
    return "; ".join(parts)


def castles_from(snap: Snapshot, layout: dict | None) -> list[dict]:
    """One entry per plot that has pieces in it, from the world's plot folders."""
    plots = {p["id"]: p for p in (layout or {}).get("plots", [])}
    out = []
    for f in snap.folders.values():
        a = f.attrs
        if "Plot" not in a or not a.get("Pieces"):
            continue
        pid = int(a["Plot"])
        p = plots.get(pid)
        pos = (p["x"], 0.0, p["z"]) if p else None
        out.append({
            "plot": pid,
            "pos": [r1(v) for v in pos] if pos else None,
            "dist": r1(dist3(pos, snap.me)) if pos else None,
            "dir": direction_to(snap.me, pos) if pos else None,
            "pieces": int(a.get("Pieces", 0)),
            "height": int(a.get("Height", 0)),
            "flag": bool(a.get("HasFlag")),
            "standing": bool(a.get("Settled", True)),
            "falls": int(a.get("Falls", 0)),
        })
    out.sort(key=lambda c: c["plot"])
    return out


def compact_view(snap: Snapshot, statics: list[Entity], names_by_entity: dict[int, str],
                 rules: Rules = MESA_RULES, near: int = NEAR_COUNT) -> dict:
    """The compact view as a plain dict (encoded as text or JSON below).

    Pieces of a castle standing in a plot are described once, as the castle;
    they are listed one by one only when they are within your reach.
    """
    held = held_object(snap, rules)
    layout = beach_layout(snap)
    shore = (layout or {}).get("shore_x")
    objs = []
    for e in snap.objects:
        if held is not None and e.id == held.id:
            continue
        in_plot = e.attrs.get("InPlot")
        if in_plot is not None and dist3(e.pos, snap.me) > rules.pickup_reach:
            continue  # part of a castle, described below
        objs.append(e)
    rows = []
    for e in objs:
        r = _object_row(e, snap, statics)
        land = on_land(layout, e.pos)
        r["sea"] = (not land and e.pos[1] < 1.5) if land is not None else (shore is not None and e.pos[0] > shore)
        plot = e.attrs.get("InPlot")
        r["plot"] = int(plot) if isinstance(plot, (int, float)) else None
        rows.append(r)
    rows.sort(key=lambda r: r["dist"])
    on = standing_on(snap, statics, rules)
    score = snap.folders.get("Score")
    spot, watching = watchers(snap)
    return {
        "tick": snap.tick,
        "me": [r1(v) for v in snap.me],
        "facing": snap.facing,
        "region": region_at(layout, snap.me),
        "standing_on": on.name if on else None,
        "holding": held.name if held else None,
        "near": rows[:near],
        "rest": summarize_rest(rows[near:]) if len(rows) > near else "",
        "rest_count": max(0, len(rows) - near),
        "castles": castles_from(snap, layout),
        "score": ({k.lower(): int(v) for k, v in score.attrs.items()} if score else None),
        "players": [
            {"name": p.name, "dist": r1(dist3(p.pos, snap.me)), "dir": direction_to(snap.me, p.pos),
             "in_view": p.in_view}
            for p in players_in_radius(snap, names_by_entity)
        ],
        "watching": {"spot": spot, "names": watching} if watching else None,
    }


def on_land(layout: dict | None, pos) -> bool | None:
    """Is this point on the island's sand (the world's on_land)? None when the world isn't an island."""
    island = (layout or {}).get("island")
    if not island:
        return None
    x, z = pos[0], pos[2]
    half, r = island["half"], island["corner_r"]
    if abs(x) <= half and abs(z) <= half:
        dx, dz = max(abs(x) - (half - r), 0), max(abs(z) - (half - r), 0)
        if dx * dx + dz * dz <= r * r:
            return True
    return any((x - b["x"]) ** 2 + (z - b["z"]) ** 2 <= b["r"] ** 2 for b in island.get("bumps") or [])


def region_at(layout: dict | None, pos) -> str | None:
    """The named region a point is in: "" between regions, None when the world has none."""
    regions = (layout or {}).get("regions") or []
    if not regions:
        return None
    for r in regions:
        if min(r["x"]) <= pos[0] <= max(r["x"]) and min(r["z"]) <= pos[2] <= max(r["z"]):
            return r["name"]
    return ""


def castle_text(c: dict) -> str:
    where = f" {fmt_vec(c['pos'])} {c['dist']:g} {c['dir']}" if c["pos"] else ""
    bits = [f"{c['pieces']} piece{'s' if c['pieces'] != 1 else ''}", f"{c['height']} high"]
    if c["flag"]:
        bits.append("with a flag")
    bits.append("standing" if c["standing"] else "still moving")
    if c["falls"]:
        bits.append(f"has fallen {c['falls']} time{'s' if c['falls'] != 1 else ''}")
    return f"sandcastle in plot {c['plot']}{where}: {', '.join(bits)}"


def view_text(v: dict) -> str:
    me = f"you {fmt_vec(v['me'])}"
    if v.get("region"):
        me += f" in {v['region']}"
    elif v.get("region") == "":
        me += " between regions (only shouts carry here)"
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
            if r.get("sea"):
                on += " in the sea"
            if r.get("plot") is not None:
                on += f" in plot {r['plot']}"
            lines.append(f"{r['name']} {r['kind']} {fmt_vec(r['pos'])} {r['dist']:g} {r['dir']}{on}")
    else:
        lines.append("objects: none in range")
    if v["rest"]:
        lines.append(f"farther: {v['rest']}")
    for c in v.get("castles") or []:
        lines.append(castle_text(c))
    if v.get("score"):
        lines.append("score: " + ", ".join(f"{k} {n}" for k, n in sorted(v["score"].items())))
    if v["players"]:
        ps = []
        for p in v["players"]:
            seen = "" if p["in_view"] else " (not in view)"
            ps.append(f"{p['name']} {p['dist']:g} {p['dir']}{seen}")
        lines.append("players: " + "; ".join(ps))
    else:
        lines.append("players: nobody else nearby")
    if v.get("watching"):
        lines.append(f"watching from {v['watching']['spot']}: {', '.join(v['watching']['names'])}")
    return "\n".join(lines)


def view_json(v: dict) -> str:
    """Same information as view_text, as compact JSON (for measurement)."""
    doc = {
        "me": v["me"], "facing": v["facing"], "on": v["standing_on"], "holding": v["holding"],
        "near": [[r["name"], r["kind"], r["pos"], r["dist"], r["dir"]] + ([r["on"]] if r["on"] else [])
                 for r in v["near"]],
        "farther": v["rest"],
        "castles": [[c["plot"], c["pos"], c["dist"], c["dir"], c["pieces"], c["height"], c["flag"],
                     c["standing"], c["falls"]] for c in v.get("castles") or []],
        "score": v.get("score"),
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
        lines.append(f"platforms (name: center x,z; size x*z; top y). Ledges up to ~{rules.jump_rise - 0.5:g} high can be jumped:")
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


def beach_map_card_text(snap: Snapshot, layout: dict, rules: Rules) -> str:
    """Map card for worlds that publish their layout (the beach)."""
    sand = layout["sand"]
    walls = layout.get("walls", {})
    center = layout.get("center") or layout.get("centre")   # older worlds say "centre"  # spelling: kept
    lines = ["MAP (beach; x = east, z = north, y = up; distances in studs)"]
    island = layout.get("island")
    if island:
        bumps = "; ".join(f"{b['name']} round {b['x']:g},{b['z']:g} r{b['r']:g}" for b in island.get("bumps") or [])
        lines.append(f"island: flat sand y={sand['top_y']:g}, a rounded square x and z -{island['half']:g}..{island['half']:g} "
                     f"(corners rounded, radius {island['corner_r']:g})" + (f", plus {bumps}" if bumps else ""))
        wx = walls.get("x", ["?", "?"])
        lines.append(f"sea: all around the island, shallow; balls that go in drift back after a few seconds. "
                     f"Invisible walls at x and z {wx[0]:g} and {wx[1]:g}")
    else:
        lines.append(f"sand: flat, y={sand['top_y']:g}, x {sand['x'][0]:g}..{sand['x'][1]:g}, "
                     f"z {sand['z'][0]:g}..{sand['z'][1]:g}")
        wz = walls.get("z", [-32, 32])
        lines.append(f"sea: east of x={layout['shore_x']:g} is shallow water; balls that go in drift back "
                     f"to the sand after a few seconds. Invisible walls at x={walls.get('x', ['?', '?'])[0]}"
                     f" and x={walls.get('x', ['?', '?'])[1]}, z={wz[0]:g} and z={wz[1]:g}")
    regions = layout.get("regions") or []
    if regions:
        lines.append("regions (you see moving things only nearby; talk is heard in your own region, "
                     "and between regions only a shout carries): " + "; ".join(
                         f"{r['name']} x {r['x'][0]:g}..{r['x'][1]:g}, z {r['z'][0]:g}..{r['z'][1]:g}"
                         for r in regions))
    dune = layout.get("dune")
    if dune and dune.get("ledges"):
        parts = []
        for d in dune["ledges"]:
            t = f"x {d['x'][0]:g}..{d['x'][1]:g}, z {d['z'][0]:g}..{d['z'][1]:g}"
            if d.get("top"):
                t += f" (a second ledge on it at x {d['top']['x'][0]:g}..{d['top']['x'][1]:g}, z {d['top']['z'][0]:g}..{d['top']['z'][1]:g})"
            parts.append(t)
        gaps = " and ".join(f"x {g['x'][0]:g}..{g['x'][1]:g}" for g in dune.get("gaps") or [])
        lines.append(f"dune (ledges {dune['ledge']:g} high: climb with a running jump): " + "; ".join(parts)
                     + (f". Walk through it at {gaps}" if gaps else ""))
    goals = layout.get("goals", [])
    if goals:
        g = goals[0]
        def goal_text(x):
            if "line_x" in x:   # goals at the east and west ends (the island's court)
                return f"{x['name']} goal line x={x['line_x']:g} between posts z={x['z'][0]:g}..{x['z'][1]:g}"
            return f"{x['name']} goal line z={x['line_z']:g} between posts x={x['x'][0]:g}..{x['x'][1]:g}"
        lines.append("goals: " + "; ".join(goal_text(x) for x in goals)
                     + f" (bar {g['height']:g} high). A ball over the line between the posts "
                     f"scores; it returns to the court's middle {fmt_vec((center[0], 0, center[1]))}")
    plots = layout.get("plots", [])
    if plots:
        size = plots[0]["half"] * 2
        lines.append(f"castle plots ({size:g}x{size:g}; a castle only counts inside one): " + "; ".join(
            f"{p['id']} at {r1(p['x']):g},{r1(p['z']):g}" for p in plots))
    spawns = layout.get("spawns", [])
    if spawns:
        lines.append("spawn points: " + " ".join(f"{s[0]:g},{s[1]:g}" for s in spawns))
    balls = [e for e in snap.objects if e.attrs.get("IsBall")]
    if balls:
        lines.append("balls now: " + "; ".join(f"{b.kind} {fmt_vec(b.pos)}" for b in balls))
    return "\n".join(lines)
