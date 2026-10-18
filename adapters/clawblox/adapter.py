# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Becky Northaven and the AI-Beach contributors
"""The adapter: tools a host exposes to a small model, plus turn_bundle().

Deterministic; no language model runs here. It never changes Clawblox; it only
calls the world's own HTTP endpoints (/join, /observe, /input, /chat,
/chat/messages).
"""

from __future__ import annotations

import json
import math
import time
import uuid
from collections import deque
from dataclasses import dataclass
from pathlib import Path

from .compact import beach_map_card_text, compact_view, display_name, map_card_text, view_text
from .tokens import TokenCounter, approx_counter
from .transport import HttpError, HttpTransport, join_path
from .world import (
    MESA_RULES, Entity, Rules, Snapshot, announcements, beach_layout, detect_rules, direction_to,
    dist3, fmt_vec, hdist, held_object, obstacle_ahead, parse_observation, r1, standing_on,
)

ACTIONS = MESA_RULES.actions  # mesa-island's; each world's list lives in its Rules
CHAT_MAX = 500
UPRIGHT = {"yaw": 0, "pitch": 0, "roll": 0}
PACKAGE_DIR = Path(__file__).parent
PLAY_CARD_PATH = PACKAGE_DIR / MESA_RULES.play_card


def action_definitions(rules: Rules = MESA_RULES) -> list[dict]:
    """Tool definitions the host can hand to the model (game-side only)."""
    return [
        {"name": "look", "args": {}, "returns": "compact view of you, nearby objects and players"},
        {"name": "act", "args": {"type": "|".join(rules.actions), "data": "object; see the card"},
         "returns": "one line"},
        {"name": "say", "args": {"text": f"string, 1-{CHAT_MAX} chars",
                                 "shout": "optional true: the whole world hears (else, where it has regions, only yours)"},
         "returns": "one line"},
        {"name": "hear", "args": {}, "returns": "new chat lines 'name: text' (World: = the world)"},
        {"name": "history", "args": {"n": "int, default 20"}, "returns": "your last n actions and results"},
        {"name": "full_look", "args": {}, "returns": "the raw observation JSON (large)"},
    ]


ACTION_DEFINITIONS = action_definitions(MESA_RULES)


def _vec(v) -> tuple | None:
    """A finite [x, y, z] or None."""
    if not isinstance(v, (list, tuple)) or len(v) != 3:
        return None
    try:
        out = tuple(float(x) for x in v)
    except (TypeError, ValueError):
        return None
    return out if all(math.isfinite(x) for x in out) else None


def user_id_of(agent_id: str) -> int | None:
    """The UserId Clawblox gives a join (what world scripts see): the low 53 bits of its agent id."""
    try:
        return (uuid.UUID(agent_id).int & ((1 << 53) - 1)) or 1
    except (ValueError, AttributeError):
        return None


def _num_id(msg_id: str) -> tuple:
    tail = str(msg_id).rsplit("_", 1)[-1]
    return (0, int(tail)) if tail.isdigit() else (1, str(msg_id))


@dataclass
class HistoryEntry:
    action: str
    result: str

    def line(self) -> str:
        return f"{self.action} -> {self.result}"


class DoorRefused(RuntimeError):
    """A world behind a Beach's front door didn't let this join in."""


class CharacterGone(HttpError):
    """The world no longer has this character (it was idle too long, or the world restarted).
    The adapter forgets the session; the next action joins again, and a Beach says what
    happened before it makes a new character."""

    def __init__(self, status: int, body: str):
        super().__init__(status, body)
        self.args = (f"your character is no longer in the world (HTTP {status}: {body[:120]}); "
                     "the next action joins again as a new character",)


class ClawbloxAdapter:
    def __init__(self, base_url: str | None = None, name: str = "agent", *,
                 transport=None, rules: Rules | None = None,
                 counter: TokenCounter | None = None, sleep=time.sleep,
                 poll_interval: float = 0.25, session: str | None = None,
                 vouch=None, join_via=None, leave_via=None):
        if transport is None:
            if base_url is None:
                raise ValueError("give base_url or transport")
            transport = HttpTransport(base_url)
        self.t = transport
        self.name = name
        self._rules_fixed = rules is not None
        self.rules = rules or MESA_RULES  # detected from the first observation unless given
        self.counter = counter or approx_counter()
        self.sleep = sleep
        self.poll = poll_interval
        self.session = session
        # vouch(agent_id, name): called right after joining, for worlds behind a front door
        # (e.g. a Beach game zone; see front_door.beach_voucher). None for open worlds.
        self.vouch = vouch
        # join_via(name) -> {"session", "agent_id"}: someone else makes the join for us (a Beach,
        # for a world that only accepts joins carrying its key; see front_door.beach_joiner).
        self.join_via = join_via
        # leave_via(): someone else takes the character out (a Beach; see front_door.beach_leaver).
        self.leave_via = leave_via
        self._names_by_agent: dict[str, str] = {}   # agent id -> name its world shows now
        self._names_by_user: dict[int, str] = {}    # UserId -> its character's label (PlayerName)
        self.agent_id: str | None = None
        self._statics: dict[str, Entity] = {}
        self._names_by_entity: dict[int, str] = {}
        self._first_snap: Snapshot | None = None
        self._map_card: str | None = None
        self._history: deque[HistoryEntry] = deque(maxlen=200)
        self._chat_seen: set[str] = set()
        self._chat_log: list[tuple[str, bool]] = []  # (line, said by me), oldest first
        self._hear_cursor = 0  # hear() returns lines after this index
        self._bundles = 0
        self.last_snapshot: Snapshot | None = None
        self._events_seen: set[int] = set()
        self._world_lines: list[str] = []  # every world announcement seen, oldest first

    # --- plumbing -------------------------------------------------------------

    def _call(self, method: str, path: str, body: dict | None = None) -> str:
        status, text = self.t.request(method, path, body, self.session)
        gone = status in (401, 404) or (status == 400 and "not in any instance" in text.lower())
        if gone and self.session and path.split("?")[0] in ("/observe", "/input", "/chat"):
            # The session no longer names a character here: say so, never act as nobody.
            self.session = None
            self.agent_id = None
            raise CharacterGone(status, text)
        if status >= 400:
            raise HttpError(status, text)
        return text

    def join(self) -> None:
        if self.session:
            return
        if self.join_via:
            data = self.join_via(self.name)
            self.session, self.agent_id = data["session"], data["agent_id"]
            self._wait_for_door()
        else:
            data = json.loads(self._call("POST", join_path(self.name)))
            self.session, self.agent_id = data["session"], data["agent_id"]
            if self.vouch:
                self.vouch(self.agent_id, self.name)
                self._wait_for_door()
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

    def leave(self) -> None:
        """Leave the world (through whoever joined for us; worlds without one keep the character
        until they drop it). Joining again afterwards makes a new character."""
        if self.leave_via and self.session:
            self.leave_via()
        self.session = None
        self.agent_id = None

    def _wait_for_door(self, timeout: float = 20.0) -> None:
        """Wait until the world's door has let us in (its BeachDoor attribute says "ok")."""
        waited = 0.0
        while waited < timeout:
            try:
                raw = json.loads(self._call("GET", "/observe"))
            except HttpError as e:
                raise DoorRefused(f"the world refused this join ({e.status})") from None
            state = ((raw.get("player") or {}).get("attributes") or {}).get("BeachDoor")
            if state in ("ok", "guest"):
                return
            if state == "refused":
                raise DoorRefused("the world's door refused this join")
            self.sleep(0.5)
            waited += 0.5
        raise DoorRefused("the Beach didn't vouch for this join in time")

    def _ingest(self, raw: dict) -> Snapshot:
        snap = parse_observation(raw)
        self.last_snapshot = snap
        for p in snap.named_players:
            name = display_name(p)
            if p.get("id") and name:
                self._names_by_agent[str(p["id"])] = name
        for e in snap.entities:  # labeled characters, in view or not (the beach world tags them)
            label, uid = e.attrs.get("PlayerName"), e.attrs.get("PlayerUserId")
            if isinstance(label, str) and label and label != "..." and isinstance(uid, (int, float)):
                self._names_by_user[int(uid)] = label
        for e in snap.statics:
            self._statics[e.name] = e
        first = self._first_snap is None
        if first:
            self._first_snap = snap
            if not self._rules_fixed:
                self.rules = detect_rules(snap)
        # World announcements (goals, falls) travel as replicated events; older
        # ones from before you arrived are skipped.
        for eid, text in announcements(snap):
            if eid in self._events_seen:
                continue
            self._events_seen.add(eid)
            if not first:
                line = f"World: {text}"
                self._world_lines.append(line)
                self._chat_log.append((line, False))
        return snap

    def _new_world_lines(self, since: int) -> list[str]:
        return [line[len("World: "):] for line in self._world_lines[since:]]

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
            layout = beach_layout(self._first_snap)
            if layout:
                self._map_card = beach_map_card_text(self._first_snap, layout, self.rules)
            else:
                self._map_card = map_card_text(self._first_snap, self.rules)
        return self._map_card

    def history(self, n: int = 20) -> str:
        items = list(self._history)[-n:]
        return "\n".join(h.line() for h in items) if items else "no actions yet"

    def say(self, text: str, shout: bool = False) -> str:
        """Say something. In a world with region speech only your region hears it; a shout
        reaches everyone in the world."""
        text = (text or "").strip()
        if not text:
            return "say failed: empty message"
        if len(text) > CHAT_MAX:
            return f"say failed: message is {len(text)} characters, limit is {CHAT_MAX}"
        self.join()
        body_in = {"content": text, "shout": True} if shout else {"content": text}
        status, body = self.t.request("POST", "/chat", body_in, self.session)
        if status >= 400:
            return f"say failed: HTTP {status} {body[:80]}"
        msg_id = json.loads(body).get("id")
        if msg_id:
            self._chat_seen.add(msg_id)
        self._chat_log.append((f"{self.name}{' shouts' if shout else ''}: {text}", True))
        return f"{'shouted' if shout else 'said'}: {text}"

    def _poll_chat(self) -> None:
        """Fetch chat into the running log, deduped by message id.

        Polls without the server's `after=` cursor: it compares 1-second
        timestamps with a strict '>' and drops same-second messages.
        """
        self.join()
        text = self._call("GET", "/chat/messages?limit=100")
        msgs = sorted(json.loads(text).get("messages") or [], key=lambda m: _num_id(m.get("id")))
        for m in msgs:
            mid = m.get("id")
            if mid in self._chat_seen:
                continue
            self._chat_seen.add(mid)
            # Say who it is as the world names them now (a rename shows at once), else as they joined.
            aid = str(m.get("agent_id", ""))
            who = (self._names_by_agent.get(aid) or self._names_by_user.get(user_id_of(aid))
                   or m.get("agent_name", "?"))
            shouted = " shouts" if m.get("delivery_mode") == "shout" else ""
            self._chat_log.append((f"{who}{shouted}: {m.get('content', '')}", False))

    def hear(self) -> str:
        """Chat lines (and "World:" announcements) since your last hear(), oldest first.

        Your own messages are not repeated back. turn_bundle() reads the same
        log but does not move this cursor.
        """
        self._poll_chat()
        new = [line for line, mine in self._chat_log[self._hear_cursor:] if not mine]
        self._hear_cursor = len(self._chat_log)
        return "\n".join(new) if new else "(no new chat)"

    def act(self, type: str, data: dict | None = None) -> str:
        data = dict(data or {})
        label = f"{type} {json.dumps(data, separators=(',', ':'))}" if data else type
        if self._first_snap is None:
            self._observe()  # learn which world this is before validating
        if type not in self.rules.actions:
            return self._record(label, f"unknown action '{type}'; use one of {', '.join(self.rules.actions)}")
        handler = getattr(self, f"_act_{type.lower()}")
        try:
            result = handler(data)
        except HttpError as err:
            result = f"{type} failed: server said HTTP {err.status} {err.body[:80]}"
        return self._record(label, result)

    # --- turn bundle ------------------------------------------------------------

    def tools_text(self) -> str:
        if self._first_snap is None:
            self._observe()
        path = PACKAGE_DIR / self.rules.play_card
        card = path.read_text() if path.exists() else ""
        defs = json.dumps(action_definitions(self.rules), separators=(",", ":"))
        return f"{card.strip()}\n\nTOOLS {defs}"

    def turn_bundle(self, n_actions: int = 8, n_chat: int = 6, include_map: bool | None = None,
                    beach_card: str | None = None) -> dict:
        """The three labeled pieces the game provides for one turn, with token sizes.

        tools  - the play card and the action definitions (after `beach_card`, if given: when
                 the world is a zone of a Beach, its directory card, from GET /agent/beach-card)
        state  - the map card (first bundle only, unless include_map) and the current look
        recent - the last n action results and the last chat lines
        """
        first = self._bundles == 0
        self._bundles += 1
        if include_map is None:
            include_map = first
        view = self.look()
        state = f"{self.map_card()}\n\nNOW\n{view}" if include_map else f"NOW\n{view}"
        self._poll_chat()
        acts = list(self._history)[-n_actions:]
        chat = [line for line, _ in self._chat_log[-n_chat:]]
        recent = "RECENT ACTIONS\n" + ("\n".join(h.line() for h in acts) if acts else "none yet")
        recent += "\nRECENT CHAT\n" + ("\n".join(chat) if chat else "none")
        tools = self.tools_text()
        if beach_card:
            tools = beach_card.strip() + "\n\n" + tools
        pieces = {"tools": tools, "state": state, "recent": recent}
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
                runup, window = self.rules.climb_runup, self.rules.climb_window
                if not (runup - window <= face_d <= runup + window):
                    # A jump only clears the ledge from the right distance (mesa: ~3-5; beach: ~1).
                    length = hdist(start.me, target)
                    ux, uz = (target[0] - start.me[0]) / length, (target[2] - start.me[2]) / length
                    back = face_d - runup
                    spot = (start.me[0] + ux * back, start.me[1], start.me[2] + uz * back)
                    self._send("MoveTo", {"position": list(spot)})
                    status, _ = self._wait_move(spot, timeout=abs(back) / 10 + 3)
                    if status not in ("arrived",):
                        note = " (run-up spot not reached)"
                    else:
                        # "Arrived" allows arrive_tolerance; a short jump needs the real spot, so let
                        # the walk finish (stop moving, or get within the window) before taking off.
                        prev = None
                        for _ in range(int(1.2 / self.poll) + 1):
                            snap = self._observe()
                            if hdist(snap.me, spot) <= window or (prev and hdist(prev, snap.me) < 0.05):
                                break
                            prev = snap.me
                            self.sleep(self.poll)
                note = note or (f" (took a run-up {runup:g} from {part.name})" if runup >= 0.5
                                else f" (jumped from the foot of {part.name})")
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
        if code in ("PickupFailed:NoBlock", "PickupFailed:NoObject"):
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
                    f"try 1-2 away, with y = the surface's top + half the object's height"
                    f" + {self.rules.place_clearance:g}")
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


    # --- beach actions ----------------------------------------------------------

    def _follow(self, name: str, max_wait: float) -> tuple[Entity | None, Snapshot, bool]:
        """Watch an object until it stops (or max_wait). Returns (obj, snap, still_moving)."""
        last, still, waited = None, 0, 0.0
        snap = self.last_snapshot
        obj = None
        while waited < max_wait:
            self.sleep(self.poll)
            waited += self.poll
            snap = self._observe()
            obj = snap.object(name)
            if obj is None:
                return None, snap, False
            if last is not None and dist3(obj.pos, last) < 0.05:
                still += 1
                if still >= 2:
                    return obj, snap, False
            else:
                still = 0
            last = obj.pos
        return obj, snap, True

    def _act_kick(self, data: dict) -> str:
        direction = _vec(data.get("direction"))
        if direction is None or math.hypot(direction[0], direction[2]) < 1e-3:
            return 'Kick rejected: "direction" must be [x, y, z] with some x or z (y lifts the ball)'
        try:
            power = float(data.get("power", 0.5))
        except (TypeError, ValueError):
            return 'Kick rejected: "power" must be a number from 0 to 1'
        clipped = ""
        if not 0 <= power <= 1:
            clipped = f" (power {power:g} clipped to {min(max(power, 0), 1):g})"
            power = min(max(power, 0.0), 1.0)
        pre = self._observe()
        snap = self._send("Kick", {"direction": list(direction), "power": power})
        code = snap.last_action_result or ""
        if not code.startswith("Kick"):
            return f"Kick: the world reported no result (still '{code}'); look to check"
        if code == "KickFailed:NoBallInReach":
            ballz = [e for e in pre.objects if e.attrs.get("IsBall")]
            near = min(ballz, key=lambda e: hdist(e.pos, pre.me), default=None)
            if near is None:
                return "Kick failed: there is no ball nearby"
            return (f"Kick failed: no ball within {self.rules.kick_reach:g} of you; nearest is the {near.kind} "
                    f"{r1(hdist(near.pos, pre.me)):g} {direction_to(pre.me, near.pos)} at {fmt_vec(near.pos)} "
                    f"- walk up to it first")
        if code != "KickSuccess":
            return f"Kick failed: {code.split(':', 1)[-1]}"
        name = snap.raw.get("player", {}).get("attributes", {}).get("LastKicked")
        ball = pre.object(name) if name else None
        kind = ball.kind if ball else "ball"
        mark = len(self._world_lines)
        heading = direction_to((0, 0, 0), direction)
        obj, snap, moving = self._follow(name, 4.0) if name else (None, snap, False)
        tail = ""
        news = self._new_world_lines(mark)
        scored = any("Goal" in n for n in news)
        if obj is not None and ball is not None and not scored:
            layout = beach_layout(snap) or {}
            shore = layout.get("shore_x")
            where = "is still rolling" if moving else "stopped"
            tail = f"; it {where} {r1(hdist(obj.pos, ball.pos)):g} away at {fmt_vec(obj.pos)}"
            if shore is not None and obj.pos[0] > shore:
                tail += " in the sea (it will drift back)"
        if news:
            tail += "; " + " ".join(news)
            if scored:
                tail += " The ball goes back to the center."
        return f"Kicked the {kind} {heading} (power {power:g}){clipped}{tail}"

    def _act_mold(self, data: dict) -> str:
        shape = str(data.get("shape", "")).lower()
        if shape not in self.rules.piece_shapes:
            return f'Mold rejected: "shape" must be one of {", ".join(self.rules.piece_shapes)}'
        pre = self._observe()
        snap = self._send("Mold", {"shape": shape})
        code = snap.last_action_result or ""
        if not code.startswith("Mold"):
            return f"Mold: the world reported no result (still '{code}'); look to check"
        if code == "MoldSuccess":
            name = snap.raw.get("player", {}).get("attributes", {}).get("LastMolded", "")
            return f"Molded a {shape} piece {name} (now holding it)".replace("  ", " ")
        if code == "MoldFailed:HandsFull":
            held = held_object(pre, self.rules)
            what = held.name if held else "something"
            return f"Mold failed: already holding {what} - Place or Throw it first"
        if code == "MoldFailed:TooManyPieces":
            return (f"Mold failed: the beach already has {self.rules.max_pieces} sand pieces; "
                    f"pick one up and reuse it")
        return f"Mold failed: {code.split(':', 1)[-1]}"


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
