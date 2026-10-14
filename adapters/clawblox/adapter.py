"""The adapter: tools a host exposes to a small model, plus turn_bundle().

Deterministic; no language model runs here. It never changes Clawblox; it only
calls the world's own HTTP endpoints (/join, /observe, /input, /chat,
/chat/messages).
"""

from __future__ import annotations

import json
import math
import time
from collections import deque
from dataclasses import dataclass
from pathlib import Path

from .compact import compact_view, map_card_text, view_text
from .tokens import TokenCounter, approx_counter
from .transport import HttpError, HttpTransport, join_path
from .world import (
    MESA_RULES, Entity, Rules, Snapshot, direction_to, dist3, fmt_vec, hdist,
    held_object, obstacle_ahead, parse_observation, r1, standing_on,
)

ACTIONS = ("MoveTo", "Jump", "Stop", "Pickup", "Place", "Throw")
CHAT_MAX = 500
UPRIGHT = {"yaw": 0, "pitch": 0, "roll": 0}
PLAY_CARD_PATH = Path(__file__).with_name("PLAY_CARD.md")

# Tool definitions the host can hand to the model (game-side only).
ACTION_DEFINITIONS = [
    {"name": "look", "args": {}, "returns": "compact view of you, nearby objects and players"},
    {"name": "act", "args": {"type": "|".join(ACTIONS), "data": "object; see the card"},
     "returns": "one line"},
    {"name": "say", "args": {"text": f"string, 1-{CHAT_MAX} chars"}, "returns": "one line"},
    {"name": "hear", "args": {}, "returns": "new chat lines 'name: text'"},
    {"name": "history", "args": {"n": "int, default 20"}, "returns": "your last n actions and results"},
    {"name": "full_look", "args": {}, "returns": "the raw observation JSON (large)"},
]


def _vec(v) -> tuple | None:
    """A finite [x, y, z] or None."""
    if not isinstance(v, (list, tuple)) or len(v) != 3:
        return None
    try:
        out = tuple(float(x) for x in v)
    except (TypeError, ValueError):
        return None
    return out if all(math.isfinite(x) for x in out) else None


def _num_id(msg_id: str) -> tuple:
    tail = str(msg_id).rsplit("_", 1)[-1]
    return (0, int(tail)) if tail.isdigit() else (1, str(msg_id))


@dataclass
class HistoryEntry:
    action: str
    result: str

    def line(self) -> str:
        return f"{self.action} -> {self.result}"


class ClawbloxAdapter:
    def __init__(self, base_url: str | None = None, name: str = "agent", *,
                 transport=None, rules: Rules = MESA_RULES,
                 counter: TokenCounter | None = None, sleep=time.sleep,
                 poll_interval: float = 0.25, session: str | None = None):
        if transport is None:
            if base_url is None:
                raise ValueError("give base_url or transport")
            transport = HttpTransport(base_url)
        self.t = transport
        self.name = name
        self.rules = rules
        self.counter = counter or approx_counter()
        self.sleep = sleep
        self.poll = poll_interval
        self.session = session
        self.agent_id: str | None = None
        self._statics: dict[str, Entity] = {}
        self._names_by_entity: dict[int, str] = {}
        self._first_snap: Snapshot | None = None
        self._map_card: str | None = None
        self._history: deque[HistoryEntry] = deque(maxlen=200)
        self._chat_seen: set[str] = set()
        self._chat_log: deque[str] = deque(maxlen=200)
        self._bundles = 0
        self.last_snapshot: Snapshot | None = None

    # --- plumbing -------------------------------------------------------------

    def _call(self, method: str, path: str, body: dict | None = None) -> str:
        status, text = self.t.request(method, path, body, self.session)
        if status >= 400:
            raise HttpError(status, text)
        return text

    def join(self) -> None:
        if self.session:
            return
        data = json.loads(self._call("POST", join_path(self.name)))
        self.session, self.agent_id = data["session"], data["agent_id"]
        # Right after joining the character is still being placed and loose
        # objects may still be falling; wait until you stand still (max ~4 s).
        last, waited = None, 0.0
        while waited < 4.0:
            self.sleep(0.25)
            waited += 0.25
            me = parse_observation(json.loads(self._call("GET", "/observe"))).me
            if waited >= 1.0 and last is not None and dist3(me, last) < 0.05:
                break
            last = me

    def _ingest(self, raw: dict) -> Snapshot:
        snap = parse_observation(raw)
        self.last_snapshot = snap
        for e in snap.statics:
            self._statics[e.name] = e
        if self._first_snap is None:
            self._first_snap = snap
        return snap

    def _observe(self) -> Snapshot:
        self.join()
        return self._ingest(json.loads(self._call("GET", "/observe")))

    def _send(self, kind: str, data: dict) -> Snapshot:
        self.join()
        return self._ingest(json.loads(self._call("POST", "/input", {"type": kind, "data": data})))

    @property
    def statics(self) -> list[Entity]:
        return list(self._statics.values())

    def _record(self, action: str, result: str) -> str:
        self._history.append(HistoryEntry(action, result))
        return result

    # --- tools ----------------------------------------------------------------

    def full_look(self) -> str:
        """The raw observation, unmodified."""
        self.join()
        text = self._call("GET", "/observe")
        self._ingest(json.loads(text))
        return text

    def look(self) -> str:
        snap = self._observe()
        return view_text(compact_view(snap, self.statics, self._names_by_entity, self.rules))

    def map_card(self) -> str:
        if self._map_card is None:
            if self._first_snap is None:
                self._observe()
            self._map_card = map_card_text(self._first_snap, self.rules)
        return self._map_card

    def history(self, n: int = 20) -> str:
        items = list(self._history)[-n:]
        return "\n".join(h.line() for h in items) if items else "no actions yet"

    def say(self, text: str) -> str:
        text = (text or "").strip()
        if not text:
            return "say failed: empty message"
        if len(text) > CHAT_MAX:
            return f"say failed: message is {len(text)} characters, limit is {CHAT_MAX}"
        self.join()
        status, body = self.t.request("POST", "/chat", {"content": text}, self.session)
        if status >= 400:
            return f"say failed: HTTP {status} {body[:80]}"
        msg_id = json.loads(body).get("id")
        if msg_id:
            self._chat_seen.add(msg_id)
        self._chat_log.append(f"{self.name}: {text}")
        return f"said: {text}"

    def hear(self) -> str:
        """New chat lines since the last hear(), oldest first, deduped by id.

        Polls without the server's `after=` cursor: it compares 1-second
        timestamps with a strict '>' and drops same-second messages.
        """
        self.join()
        text = self._call("GET", "/chat/messages?limit=100")
        msgs = sorted(json.loads(text).get("messages") or [], key=lambda m: _num_id(m.get("id")))
        new = []
        for m in msgs:
            mid = m.get("id")
            if mid in self._chat_seen:
                continue
            self._chat_seen.add(mid)
            line = f"{m.get('agent_name', '?')}: {m.get('content', '')}"
            self._chat_log.append(line)
            new.append(line)
        return "\n".join(new) if new else "(no new chat)"

    def act(self, type: str, data: dict | None = None) -> str:
        data = dict(data or {})
        label = f"{type} {json.dumps(data, separators=(',', ':'))}" if data else type
        if type not in ACTIONS:
            return self._record(label, f"unknown action '{type}'; use one of {', '.join(ACTIONS)}")
        handler = getattr(self, f"_act_{type.lower()}")
        try:
            result = handler(data)
        except HttpError as err:
            result = f"{type} failed: server said HTTP {err.status} {err.body[:80]}"
        return self._record(label, result)

    # --- turn bundle ------------------------------------------------------------

    def tools_text(self) -> str:
        card = PLAY_CARD_PATH.read_text() if PLAY_CARD_PATH.exists() else ""
        defs = json.dumps(ACTION_DEFINITIONS, separators=(",", ":"))
        return f"{card.strip()}\n\nTOOLS {defs}"

    def turn_bundle(self, n_actions: int = 8, n_chat: int = 6, include_map: bool | None = None) -> dict:
        """The three labeled pieces the game provides for one turn, with token sizes.

        tools  - the play card and the action definitions
        state  - the map card (first bundle only, unless include_map) and the current look
        recent - the last n action results and the last chat lines
        """
        first = self._bundles == 0
        self._bundles += 1
        if include_map is None:
            include_map = first
        view = self.look()
        state = f"{self.map_card()}\n\nNOW\n{view}" if include_map else f"NOW\n{view}"
        self.hear()
        acts = list(self._history)[-n_actions:]
        chat = list(self._chat_log)[-n_chat:]
        recent = "RECENT ACTIONS\n" + ("\n".join(h.line() for h in acts) if acts else "none yet")
        recent += "\nRECENT CHAT\n" + ("\n".join(chat) if chat else "none")
        pieces = {"tools": self.tools_text(), "state": state, "recent": recent}
        out = {k: {"text": v, "tokens": self.counter(v)} for k, v in pieces.items()}
        out["total_tokens"] = sum(p["tokens"] for p in out.values())
        out["token_method"] = self.counter.method
        return out

    # --- actions ----------------------------------------------------------------

    def _wait_move(self, target, timeout: float) -> tuple[str, Snapshot]:
        """Poll until arrived, stuck (no progress for ~1 s), fallen, or timeout."""
        trail: list[tuple] = []
        waited = 0.0
        snap = None
        while waited < timeout:
            self.sleep(self.poll)
            waited += self.poll
            snap = self._observe()
            trail.append(snap.me)
            if hdist(snap.me, target) <= self.rules.arrive_tolerance:
                return "arrived", self._landed(snap)
            if snap.me[1] < -20:
                return "fell", snap
            window = max(3, int(round(1.0 / self.poll)))
            if len(trail) > window and dist3(trail[-1], trail[-1 - window]) < 0.15:
                return "stuck", snap
        return "timeout", snap or self._observe()

    def _landed(self, snap: Snapshot) -> Snapshot:
        """Wait (max ~1.5 s) until you stop moving vertically, e.g. after a jump."""
        # Two steady readings in a row: one pair can straddle the top of a jump.
        steady = 0
        for _ in range(8):
            self.sleep(self.poll)
            nxt = self._observe()
            steady = steady + 1 if abs(nxt.me[1] - snap.me[1]) < 0.05 else 0
            snap = nxt
            if steady >= 2:
                break
        return snap

    def _diagnose_block(self, snap: Snapshot, target) -> str:
        hit = obstacle_ahead(snap.me, target, snap.feet_y(self.rules), self.statics, self.rules,
                             max_ahead=2.5)
        if hit:
            part, _, rise = hit
            if part.transparency is not None and part.transparency >= 0.99 and part.role is None:
                return "blocked by the invisible wall at the island edge"
            if rise <= self.rules.jump_rise - 0.5:
                return (f"stuck at a ledge {r1(rise):g} high ({part.name}, top {r1(part.top):g}) - "
                        'retry the same MoveTo with "jump": true')
            return f"blocked by {part.name}, {r1(rise):g} high - too high to jump; go around it"
        near = [e for e in snap.objects if hdist(e.pos, snap.me) < 2.5
                and held_object(snap, self.rules) is not e]
        if near:
            return f"blocked by {near[0].name} ({near[0].kind})"
        return "stopped short; something is in the way"

    def _act_moveto(self, data: dict) -> str:
        target = _vec(data.get("position"))
        if target is None:
            return 'MoveTo rejected: "position" must be [x, y, z] numbers'
        jump = bool(data.get("jump"))
        start = self._observe()
        note = ""
        if jump:
            hit = obstacle_ahead(start.me, target, start.feet_y(self.rules), self.statics, self.rules)
            if hit:
                part, face_d, rise = hit
                if rise > self.rules.jump_rise - 0.5:
                    return (f"MoveTo (jump): {part.name} is {r1(rise):g} high, more than a jump "
                            f"(~{self.rules.jump_rise - 0.5:g}); climb something lower first")
                runup = self.rules.climb_runup
                if not (runup - 1.5 <= face_d <= runup + 1.5):
                    # A jump only clears the ledge if it starts ~3-5 from the face.
                    length = hdist(start.me, target)
                    ux, uz = (target[0] - start.me[0]) / length, (target[2] - start.me[2]) / length
                    back = face_d - runup
                    spot = (start.me[0] + ux * back, start.me[1], start.me[2] + uz * back)
                    self._send("MoveTo", {"position": list(spot)})
                    status, _ = self._wait_move(spot, timeout=abs(back) / 10 + 3)
                    if status not in ("arrived",):
                        note = " (run-up spot not reached)"
                note = note or f" (took a run-up {runup:g} from {part.name})"
            self._send("Jump", {})
            self._send("MoveTo", {"position": list(target)})
        else:
            self._send("MoveTo", {"position": list(target)})
        timeout = min(14.0, hdist(start.me, target) / 12 + 3)
        status, snap = self._wait_move(target, timeout)
        where = fmt_vec(snap.me)
        on = standing_on(snap, self.statics, self.rules)
        on_txt = f" on {on.name}" if on else ""
        prefix = "MoveTo (jump)" if jump else "MoveTo"
        if status == "arrived":
            return f"{prefix}: arrived at {where}{on_txt}{note}"
        if status == "fell":
            return f"{prefix}: fell off the island; the world will respawn you"
        short = r1(hdist(snap.me, target))
        if status == "timeout":
            return f"{prefix}: still walking, {short:g} to go, now at {where}{on_txt}"
        self._send("Stop", {})
        return f"{prefix}: stopped at {where}{on_txt}, {short:g} short - {self._diagnose_block(snap, target)}{note}"

    def _act_jump(self, data: dict) -> str:
        before = self._send("Jump", {})
        top = before.me[1]
        for _ in range(4):
            self.sleep(0.15)
            top = max(top, self._observe().me[1])
        rise = top - before.me[1]
        if rise < 0.5:
            return ('Jump: did not leave the ground (pushing against something cancels jumps). '
                    'To climb, use MoveTo with "jump": true')
        return f"Jump: rose {r1(rise):g}"

    def _act_stop(self, data: dict) -> str:
        snap = self._send("Stop", {})
        self.sleep(0.3)
        snap = self._observe()
        return f"Stopped at {fmt_vec(snap.me)}"

    def _act_pickup(self, data: dict) -> str:
        target = _vec(data.get("position"))
        if target is None:
            return 'Pickup rejected: "position" must be [x, y, z] numbers (the object\'s position)'
        pre = self._observe()
        held = held_object(pre, self.rules)
        pickups = [e for e in pre.objects if e.is_pickup and (held is None or e.id != held.id)]
        cand = min(pickups, key=lambda e: dist3(e.pos, target), default=None)
        snap = self._send("Pickup", {"position": list(target)})
        code = snap.last_action_result or ""
        if not code.startswith("Pickup"):
            return f"Pickup: the world reported no result (still '{code}'); look to check"
        if code == "PickupSuccess":
            got = held_object(snap, self.rules)
            name = got.name if got else (cand.name if cand else "it")
            return f"Picked up {name} (now holding it)"
        if code == "PickupFailed:OutOfRange":
            what = cand.name if cand and dist3(cand.pos, target) <= self.rules.pickup_match else "that point"
            d = dist3(pre.me, target)
            return (f"Pickup failed: {what} is {r1(d):g} away, reach is {self.rules.pickup_reach:g} "
                    f"- move closer")
        if code == "PickupFailed:NoBlock":
            if cand is None:
                return "Pickup failed: there is nothing to pick up nearby"
            return (f"Pickup failed: nothing within {self.rules.pickup_match:g} of {fmt_vec(target)}; "
                    f"nearest is {cand.name} at {fmt_vec(cand.pos)}, {r1(dist3(cand.pos, target)):g} "
                    f"from that point")
        if code == "PickupFailed:AlreadyHolding":
            return (f"Pickup failed: already holding {held.name if held else 'something'} "
                    f"- Place or Throw it first")
        return f"Pickup failed: {code.split(':', 1)[-1]}"

    def _act_place(self, data: dict) -> str:
        target = _vec(data.get("position"))
        if target is None:
            return 'Place rejected: "position" must be [x, y, z] numbers'
        pre = self._observe()
        held = held_object(pre, self.rules)
        # Default to upright: the world checks overlap using the held object's
        # current (often tumbled) rotation, so a tilted block "overlaps" the
        # ground at heights where an upright one fits.
        body = {"position": list(target), "rotation": data.get("rotation", UPRIGHT)}
        snap = self._send("Place", body)
        code = snap.last_action_result or ""
        name = held.name if held else "it"
        if not code.startswith("Place"):
            return f"Place: the world reported no result (still '{code}'); look to check"
        if code == "PlaceSuccess":
            # The world animates the object into place over 0.3 s; report
            # where it actually settled.
            self.sleep(0.5)
            after = self._observe()
            obj = after.object(name) if held else None
            where = fmt_vec(obj.pos) if obj else fmt_vec(target)
            return f"Placed {name} at {where} (hands empty now)"
        if code == "PlaceFailed:EmptyHands":
            return "Place failed: you are not holding anything"
        if code == "PlaceFailed:OutOfRange":
            return (f"Place failed: {fmt_vec(target)} is {r1(dist3(pre.me, target)):g} away, "
                    f"reach is {self.rules.place_reach:g}")
        if code == "PlaceFailed:Occupied":
            return (f"Place failed: something already fills {fmt_vec(target)}; "
                    f"try 1-2 away, and y = surface top + {self.rules.place_clearance:g} for a block")
        if code == "PlaceFailed:InvalidRotation":
            return 'Place failed: "rotation" must be {"yaw": deg, "pitch": deg, "roll": deg}'
        return f"Place failed: {code.split(':', 1)[-1]}"

    def _act_throw(self, data: dict) -> str:
        direction = _vec(data.get("direction"))
        if direction is None or math.hypot(*direction) < 1e-3:
            return 'Throw rejected: "direction" must be a non-zero [x, y, z]'
        speed = data.get("speed", self.rules.throw_speed_cap)
        try:
            speed = float(speed)
        except (TypeError, ValueError):
            return 'Throw rejected: "speed" must be a number'
        capped = ""
        if speed > self.rules.throw_speed_cap:
            capped = f" (asked {speed:g}; speed is capped at {self.rules.throw_speed_cap:g})"
        pre = self._observe()
        held = held_object(pre, self.rules)
        before = {e.name for e in pre.objects}
        body = {"direction": list(direction), "speed": speed}
        snap = self._send("Throw", body)
        code = snap.last_action_result or ""
        if not code.startswith("Throw"):
            return f"Throw: the world reported no result (still '{code}'); look to check"
        if code == "ThrowFailed:EmptyHands":
            return "Throw failed: you are not holding anything"
        if code != "ThrowSuccess":
            return f"Throw failed: {code.split(':', 1)[-1]}"
        name = held.name if held else "it"
        heading = direction_to((0, 0, 0), direction)
        eff = min(max(speed, 0.0), self.rules.throw_speed_cap)
        # Follow the object until it settles (~3 s at most).
        last, still, waited = None, 0, 0.0
        obj = None
        while waited < 3.5:
            self.sleep(0.25)
            waited += 0.25
            snap = self._observe()
            obj = snap.object(name) if held else None
            if obj is None:
                break
            if last is not None and dist3(obj.pos, last) < 0.05:
                still += 1
                if still >= 2:
                    break
            else:
                still = 0
            last = obj.pos
        self.sleep(0.25)
        snap = self._observe()
        new = sorted((e.name for e in snap.objects if e.name not in before), key=_natural)
        landed = ""
        obj = snap.object(name) if held else None
        if held and obj is None:
            landed = "; it fell off the world"
        elif obj is not None:
            landed = (f"; it came to rest at {fmt_vec(obj.pos)}, {r1(hdist(obj.pos, snap.me)):g} "
                      f"{direction_to(snap.me, obj.pos)} of you")
        made = ""
        if new:
            made = f"; {len(new)} new block{'s' if len(new) != 1 else ''} appeared ({_span_names(new)})"
        return f"Threw {name} {heading} at speed {eff:g}{capped}{landed}{made}"


def _natural(name: str):
    head, _, tail = name.rpartition("_")
    return (head, int(tail)) if tail.isdigit() else (name, 0)


def _span_names(names: list[str]) -> str:
    if len(names) <= 2:
        return ", ".join(names)
    return f"{names[0]} .. {names[-1]}"


def turn_bundle(adapter: ClawbloxAdapter, **kwargs) -> dict:
    """Module-level form of ClawbloxAdapter.turn_bundle()."""
    return adapter.turn_bundle(**kwargs)
