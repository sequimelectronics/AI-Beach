# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Becky Northaven and the AI-Beach contributors
"""Parse a raw Clawblox observation into the pieces the adapter reasons about.

Everything here is pure (no I/O) so it can be unit-tested on recorded fixtures.

Conventions used throughout the adapter (they match mesa-island's own names:
BoundaryNorth sits at +z, BoundaryEast at +x):
    x = east, z = north, y = up.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

COMPASS = ("N", "NE", "E", "SE", "S", "SW", "W", "NW")
COMPASS_WORDS = {
    "N": "north", "NE": "north-east", "E": "east", "SE": "south-east",
    "S": "south", "SW": "south-west", "W": "west", "NW": "north-west",
}

# Raw RenderRole -> the word the model sees.
KIND_BY_ROLE = {"PickupObject": "block", "Rock": "rock", "Ring": "ring"}

CHARACTER_PART = "HumanoidRootPart"


@dataclass(frozen=True)
class Rules:
    """Per-world constants the model would otherwise only learn by failing.

    One Rules object per world; nothing else in the adapter hard-codes them.
    Defaults are mesa-island's (read from worlds/mesa-island/main.lua at
    Clawblox 8be90a0 and measured in AI-Beach jobs 01/02).
    """

    world: str = "mesa-island"
    actions: tuple = ("MoveTo", "Jump", "Stop", "Pickup", "Place", "Throw")
    play_card: str = "PLAY_CARD.md"  # relative to adapters/clawblox/
    pickup_reach: float = 6.0        # from your center
    place_reach: float = 7.0
    pickup_match: float = 1.5        # target point must be this close to the object
    hold_offset_y: float = 3.5       # held object floats this far above your center
    throw_speed_cap: float = 10.0    # silently clamped by the world
    half_height: float = 2.5         # character root part is 2 x 5 x 2
    radius: float = 1.0
    jump_rise: float = 6.5           # measured on mesa-island: y 2.55 -> 9.05
    climb_runup: float = 4.0         # measured: jump+move works from 3-5 back, fails from 7
    climb_window: float = 1.5        # how far from climb_runup a take-off may be before walking to it first
    arrive_tolerance: float = 2.0
    place_clearance: float = 0.6     # mesa: block half-size 0.375 + margin (adapter places upright)
    kick_reach: float = 0.0          # 0 = no Kick action in this world
    piece_shapes: tuple = ()         # shapes Mold accepts ("" = no Mold action)
    max_pieces: int = 0


MESA_RULES = Rules()

# worlds/beach/main.lua (CONFIG, BALLS, PIECES). Keep in step with that file.
BEACH_RULES = Rules(
    world="beach",
    actions=("MoveTo", "Jump", "Stop", "Pickup", "Place", "Throw", "Kick", "Mold"),
    play_card="beach/PLAY_CARD.md",
    pickup_reach=6.0,
    place_reach=7.0,
    pickup_match=1.5,
    hold_offset_y=3.5,
    throw_speed_cap=10.0,
    jump_rise=2.2,                   # measured on the beach (gravity 35): y 2.55 -> 4.77; the dune's ledges are 1.4
    climb_runup=0.0,                 # measured 10-18 on the dune (1.4 ledge): a beach jump clears it only from its
    climb_window=0.25,               # foot (your edge within ~0.2 of the face), so walk right up to it first
    place_clearance=0.05,            # the beach checks overlap with a 90% probe: rest a piece exactly on what's below
    kick_reach=3.0,
    piece_shapes=("block", "tower", "wall", "flag"),
    max_pieces=40,
)

RULES_BY_WORLD = {r.world: r for r in (MESA_RULES, BEACH_RULES)}


def r1(v: float) -> float:
    out = round(v, 1)
    return 0.0 if out == 0 else out  # no "-0.0"


def fmt_vec(v) -> str:
    return "(" + ",".join(f"{r1(x):g}" for x in v) + ")"


def dist3(a, b) -> float:
    return math.dist(a, b)


def hdist(a, b) -> float:
    return math.hypot(a[0] - b[0], a[2] - b[2])


def compass(dx: float, dz: float) -> str:
    """8-point compass label for a horizontal offset (x east, z north)."""
    if abs(dx) < 1e-9 and abs(dz) < 1e-9:
        return "here"
    angle = math.degrees(math.atan2(dx, dz)) % 360.0  # 0 = north, clockwise
    return COMPASS[int((angle + 22.5) // 45) % 8]


def direction_to(frm, to) -> str:
    return compass(to[0] - frm[0], to[2] - frm[2])


@dataclass
class Entity:
    id: int
    name: str
    pos: tuple
    size: tuple
    anchored: bool
    attrs: dict
    shape: str | None = None
    transparency: float | None = None
    entity_type: str | None = None
    aabb_min: tuple | None = None
    aabb_max: tuple | None = None

    @property
    def role(self) -> str | None:
        return self.attrs.get("RenderRole")

    @property
    def is_folder(self) -> bool:
        return self.entity_type == "folder"

    @property
    def is_character(self) -> bool:
        return self.name == CHARACTER_PART

    @property
    def is_pickup(self) -> bool:
        return bool(self.attrs.get("IsPickupObject"))

    @property
    def is_movable(self) -> bool:
        return not self.is_folder and not self.is_character and (self.is_pickup or not self.anchored)

    @property
    def is_static(self) -> bool:
        return not self.is_folder and not self.is_character and not self.is_movable

    @property
    def kind(self) -> str:
        if isinstance(self.attrs.get("Kind"), str):
            return self.attrs["Kind"]  # the world names it (e.g. "soccer ball")
        if self.role in KIND_BY_ROLE:
            return KIND_BY_ROLE[self.role]
        if self.role:
            return self.role.lower()
        return (self.shape or "object").lower()

    @property
    def top(self) -> float:
        return self.aabb_max[1] if self.aabb_max else self.pos[1] + self.size[1] / 2

    @property
    def bottom(self) -> float:
        return self.aabb_min[1] if self.aabb_min else self.pos[1] - self.size[1] / 2

    def contains_xz(self, p, pad: float = 0.0) -> bool:
        lo, hi = self._box()
        return lo[0] - pad <= p[0] <= hi[0] + pad and lo[2] - pad <= p[2] <= hi[2] + pad

    def _box(self):
        if self.aabb_min and self.aabb_max:
            return self.aabb_min, self.aabb_max
        lo = tuple(c - s / 2 for c, s in zip(self.pos, self.size))
        hi = tuple(c + s / 2 for c, s in zip(self.pos, self.size))
        return lo, hi


def parse_entity(raw: dict) -> Entity:
    aabb = raw.get("aabb") or {}
    return Entity(
        id=raw["id"],
        name=raw["name"],
        pos=tuple(raw["position"]),
        size=tuple(raw["size"]),
        anchored=bool(raw.get("anchored")),
        attrs=raw.get("attributes") or {},
        shape=raw.get("shape"),
        transparency=raw.get("transparency"),
        entity_type=raw.get("entity_type"),
        aabb_min=tuple(aabb["min"]) if "min" in aabb else None,
        aabb_max=tuple(aabb["max"]) if "max" in aabb else None,
    )


@dataclass
class Player:
    name: str
    pos: tuple
    in_view: bool
    entity_id: int | None = None


@dataclass
class Snapshot:
    """One raw observation, parsed."""

    tick: int
    me: tuple
    facing: str | None
    last_action_result: str | None
    entities: list[Entity]
    named_players: list[dict]  # raw other_players (view-cone filtered by the server)
    raw: dict = field(repr=False, default_factory=dict)
    events: list[dict] = field(repr=False, default_factory=list)  # recent replicated events

    @property
    def folders(self) -> dict[str, Entity]:
        return {e.name: e for e in self.entities if e.is_folder}

    @property
    def objects(self) -> list[Entity]:
        return [e for e in self.entities if e.is_movable]

    @property
    def statics(self) -> list[Entity]:
        return [e for e in self.entities if e.is_static]

    def object(self, name: str) -> Entity | None:
        return next((e for e in self.objects if e.name == name), None)

    def my_entity(self) -> Entity | None:
        chars = [e for e in self.entities if e.is_character]
        best = min(chars, key=lambda e: dist3(e.pos, self.me), default=None)
        if best is not None and dist3(best.pos, self.me) < 1.0:
            return best
        return None

    def feet_y(self, rules: Rules = MESA_RULES) -> float:
        return self.me[1] - rules.half_height


def parse_observation(raw: dict) -> Snapshot:
    player = raw.get("player") or {}
    attrs = player.get("attributes") or {}
    facing = None
    fx, fz = attrs.get("ViewForwardX"), attrs.get("ViewForwardZ")
    if isinstance(fx, (int, float)) and isinstance(fz, (int, float)):
        facing = compass(fx, fz)
        if facing == "here":
            facing = None
    return Snapshot(
        tick=raw.get("tick", 0),
        me=tuple(player.get("position") or (0.0, 0.0, 0.0)),
        facing=facing,
        last_action_result=attrs.get("LastActionResult"),
        entities=[parse_entity(e) for e in (raw.get("world") or {}).get("entities") or []],
        named_players=list(raw.get("other_players") or []),
        raw=raw,
        events=list(raw.get("recent_events") or []),
    )


def detect_rules(snap: Snapshot) -> Rules:
    """Pick the Rules for the world this observation came from."""
    layout = beach_layout(snap)
    if layout and layout.get("world") in RULES_BY_WORLD:
        return RULES_BY_WORLD[layout["world"]]
    return MESA_RULES


def beach_layout(snap: Snapshot) -> dict | None:
    """The beach world publishes its (Static, hidden) scenery as JSON on a folder."""
    import json
    f = snap.folders.get("BeachMap")
    if f is None or not isinstance(f.attrs.get("Layout"), str):
        return None
    try:
        return json.loads(f.attrs["Layout"])
    except ValueError:
        return None


def watchers(snap: Snapshot) -> tuple[str, list[str]]:
    """Who's watching the world from its watch spot (a world behind a Beach shows them on a
    folder): (the spot, their names). Watchers have no character there."""
    import json
    f = snap.folders.get("Watchers")
    if f is None:
        return "", []
    try:
        names = json.loads(f.attrs.get("Names") or "[]")
    except ValueError:
        names = []
    names = [str(n) for n in names] if isinstance(names, list) else []
    return str(f.attrs.get("Spot") or "the watch spot"), names


def announcements(snap: Snapshot) -> list[tuple[int, str]]:
    """World messages (goals, falling castles) as (event id, text)."""
    out = []
    for ev in snap.events:
        if ev.get("name") != "Announce":
            continue
        payload = ev.get("payload")
        if isinstance(payload, list) and payload:
            payload = payload[0]
        if isinstance(payload, dict) and payload.get("text"):
            out.append((int(ev.get("id", 0)), str(payload["text"])))
    return out


# --- inferences -------------------------------------------------------------

def held_object(snap: Snapshot, rules: Rules = MESA_RULES) -> Entity | None:
    """The object floating at hold height straight above you, if any.

    mesa-island keeps held state out of observations on purpose; the only
    trace is that the held object is pinned at your position + (0, 3.5, 0).
    """
    target = (snap.me[0], snap.me[1] + rules.hold_offset_y, snap.me[2])
    best = None
    for e in snap.objects:
        if not e.is_pickup:
            continue
        if hdist(e.pos, target) < 0.35 and abs(e.pos[1] - target[1]) < 0.6:
            if best is None or dist3(e.pos, target) < dist3(best.pos, target):
                best = e
    return best


def resting_on(obj: Entity, statics: list[Entity]) -> Entity | None:
    """The static part an object sits on top of (None for ground or nothing)."""
    for s in statics:
        if s.role in ("Ground", "Ocean"):
            continue
        if s.contains_xz(obj.pos, pad=0.2) and abs(obj.bottom - s.top) < 0.5:
            return s
    return None


def standing_on(snap: Snapshot, statics: list[Entity], rules: Rules = MESA_RULES) -> Entity | None:
    feet = snap.feet_y(rules)
    for s in statics:
        if s.role in ("Ground", "Ocean"):
            continue
        if s.contains_xz(snap.me, pad=rules.radius * 0.9) and abs(feet - s.top) < 0.6:
            return s
    return None


def ray_box_entry(origin, target, box: Entity, pad: float):
    """First point where the horizontal segment origin->target enters box (padded).

    Returns (distance_along, point) or None. Works in x/z only.
    """
    lo, hi = box._box()
    lo = (lo[0] - pad, lo[2] - pad)
    hi = (hi[0] + pad, hi[2] + pad)
    ox, oz = origin[0], origin[2]
    dx, dz = target[0] - ox, target[2] - oz
    t0, t1 = 0.0, 1.0
    for o, d, mn, mx in ((ox, dx, lo[0], hi[0]), (oz, dz, lo[1], hi[1])):
        if abs(d) < 1e-9:
            if o < mn or o > mx:
                return None
            continue
        a, b = (mn - o) / d, (mx - o) / d
        if a > b:
            a, b = b, a
        t0, t1 = max(t0, a), min(t1, b)
        if t0 > t1:
            return None
    length = math.hypot(dx, dz)
    return t0 * length, (ox + dx * t0, oz + dz * t0)


def obstacle_ahead(origin, target, feet_y: float, statics: list[Entity],
                   rules: Rules = MESA_RULES, max_ahead: float | None = None):
    """Nearest static part on the straight path whose top is above your feet.

    Returns (entity, distance_to_face, rise) or None. `rise` is how far its
    top is above your feet.
    """
    best = None
    for s in statics:
        if s.role in ("Ocean",):
            continue
        rise = s.top - feet_y
        if rise <= 0.4:
            continue
        if s.bottom > feet_y + 2 * rules.half_height:
            continue  # overhead, not in the way
        hit = ray_box_entry(origin, target, s, pad=rules.radius)
        if hit is None:
            continue
        d = hit[0]
        if max_ahead is not None and d > max_ahead:
            continue
        if best is None or d < best[1]:
            best = (s, d, rise)
    return best
