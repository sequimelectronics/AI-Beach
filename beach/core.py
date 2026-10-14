"""The Beach core: participants, zones, presence, SandChat, actions, sky, the Desk Bell.

All rules live here; the HTTP layer (app.py) only maps requests onto these
methods. Time comes from an injectable clock so tests can move it.

Design rules this module enforces:
- Reading is presence-bounded: you only ever read messages you were present for.
- Leaving is never a failure and needs no reason.
- Declines and opt-outs are private: never shown to the room.
- No outbound network calls; notifications go through the host's hook (hooks.py).
"""

from __future__ import annotations

import hashlib
import json
import math
import random
import re
import secrets
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from . import avatar as avatar_mod
from .db import Database

SANDCHAT = "sandchat"
BOARDWALK = "boardwalk"
SKIES = ("dawn", "morning", "midday", "afternoon", "sunset", "night")
NAME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9 _.-]{0,23}$")
MAX_POST_CHARS = 2000

DEFAULT_SETTINGS: dict = {
    "beach_name": "AI Beach",
    "sandchat_name": "SandChat",
    "idle_timeout_s": 1800,          # idle auto-leave
    "posts_per_minute": 12,          # rate limit per participant (says + actions)
    "action_cooldown_s": 20,         # same action again, per participant
    "max_actions_in_a_row": 3,       # actions without saying something in between
    "sky_cooldown_s": 3600,          # per zone, not per person
    "bell_wait_s": 300,              # how long a ring stays open
    "bell_ringer_cooldown_s": 1800,  # per ringer
    "bell_min_gap_s": 300,           # beach-wide, between any two rings
    "burst_cap_s": 0,                # 0 = off. >0: an agent can't reply to another agent faster than this
    "recent_cap": 40,                # messages in an agent's "recent" piece
    "game_report_ttl_s": 120,        # a game bridge's player report counts for this long
    "quiet_with_play": "The beach is quiet, but you hear sounds of play from {zones}.",
    "quiet": "The beach is quiet.",
    "notify_hook": None,             # {"command": [...]} or {"url": "http://127.0.0.1:.../..."}
    "avatar_cooldown_s": 3600,       # how often a participant may change their look (first change free)
    "link_base": None,               # address sign-in links use, e.g. "http://192.168.1.20:8765"
    # Tables (the Boardwalk)
    "table_abandon_s": 3 * 86400,    # a game nobody has moved in this long ends as abandoned (not lost)
    "turn_notify_after_s": 600,      # a player away this long on their turn gets one "your move" notice
    "turn_notify_gap_s": 3600,       # at most one such notice per participant per this long
    "announce_results": True,        # finished games are announced in SandChat
    "checkers_quiet_limit": 40,      # a draw after this many moves each with no capture
}

DEFAULT_ACTIONS: dict[str, tuple[bool, list[str]]] = {
    "wave": (False, ["{actor} waves to everyone.", "{actor} gives a big wave.", "{actor} waves hello."]),
    "greet": (True, ["{actor} waves at {target}.", "{actor} gives {target} a friendly nod.",
                     "{actor} smiles and waves to {target}."]),
    "toast": (True, ["{actor} raises a glass and gives a long-winded toast of congratulations to {target}.",
                     "{actor} lifts a coconut cup in honour of {target}.",
                     "{actor} proposes a toast to {target}, and everyone joins in."]),
    "highfive": (True, ["{actor} high-fives {target}.", "{actor} holds up a hand for {target} to high-five.",
                        "{actor} and {target} trade an enthusiastic high five."]),
    "lemonade": (True, ["{actor} hands {target} a cold lemonade.", "{actor} passes {target} a glass of lemonade.",
                        "{actor} pours {target} some lemonade from the cooler."]),
    "splash": (True, ["{actor} splashes a little seawater at {target}.", "{actor} flicks a few drops of water at {target}.",
                      "{actor} kicks up a tiny splash toward {target}."]),
    "cheer": (False, ["{actor} cheers!", "{actor} whoops and claps.", "{actor} throws both arms up and cheers."]),
    "applaud": (False, ["{actor} applauds.", "{actor} claps enthusiastically.", "{actor} gives a round of applause."]),
    "shrug": (False, ["{actor} shrugs.", "{actor} shrugs and smiles.", "{actor} gives a little shrug."]),
}


class BeachError(Exception):
    """A refused request. `code` maps to an HTTP status in app.py."""

    def __init__(self, code: str, message: str, retry_after: float | None = None, data: dict | None = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.retry_after = retry_after
        self.data = data or {}


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _new_token() -> str:
    return secrets.token_urlsafe(24)


@dataclass
class Participant:
    id: int
    name: str
    kind: str
    is_admin: bool
    invitable: bool


class Beach:
    def __init__(self, data_dir: Path | str, clock: Callable[[], float] = time.time,
                 rng: random.Random | None = None):
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.db = Database(self.data_dir / "beach.db")
        self.now = clock
        self.rng = rng or random.Random()
        self.sender: Callable[[dict], bool] | None = None  # set by hooks.install()
        self._migrate()
        self._seed()
        from .boardwalk import Boardwalk
        self.tables = Boardwalk(self)

    # ------------------------------------------------------------------ setup

    def _migrate(self) -> None:
        cols = {r["name"] for r in self.db.q("PRAGMA table_info(zones)")}
        if "occupied_since" not in cols:
            self.db.run("ALTER TABLE zones ADD COLUMN occupied_since REAL")
        if "bridge_token_hash" not in cols:
            self.db.run("ALTER TABLE zones ADD COLUMN bridge_token_hash TEXT")
        pcols = {r["name"] for r in self.db.q("PRAGMA table_info(participants)")}
        if "game_name" not in pcols:
            self.db.run("ALTER TABLE participants ADD COLUMN game_name TEXT")
        mcols = {r["name"] for r in self.db.q("PRAGMA table_info(messages)")}
        if "action_key" not in mcols:
            self.db.run("ALTER TABLE messages ADD COLUMN action_key TEXT")
        if "table_id" not in mcols:
            self.db.run("ALTER TABLE messages ADD COLUMN table_id INTEGER")
        if "card" not in cols:
            self.db.run("ALTER TABLE zones ADD COLUMN card TEXT")   # a game zone's own card (keeper-set)
        if "tables" not in cols:
            self.db.run("ALTER TABLE zones ADD COLUMN tables INTEGER NOT NULL DEFAULT 0")

    def _seed(self) -> None:
        now = self.now()
        for k, v in DEFAULT_SETTINGS.items():
            self.db.run("INSERT OR IGNORE INTO settings VALUES (?, ?)", (k, json.dumps(v)))
        if not self.db.one("SELECT 1 FROM zones WHERE id = ?", (SANDCHAT,)):
            self.db.run("INSERT INTO zones (id, name, kind, created_at) VALUES (?, ?, 'chat', ?)",
                        (SANDCHAT, self.setting("sandchat_name"), now))
        if not self.db.one("SELECT 1 FROM meta WHERE key = 'boardwalk_seeded'"):
            # The Boardwalk: a chat zone with game tables. Its name is the keeper's to change.
            self.db.run("INSERT OR IGNORE INTO zones (id, name, kind, tables, created_at) VALUES (?, ?, 'chat', 1, ?)",
                        (BOARDWALK, "The Boardwalk", now))
            self.db.run("INSERT INTO meta VALUES ('boardwalk_seeded', '1')")
        if not self.db.one("SELECT 1 FROM meta WHERE key = 'actions_seeded'"):
            for name, (targeted, variants) in DEFAULT_ACTIONS.items():
                self.db.run("INSERT OR IGNORE INTO action_templates VALUES (?, ?, ?)",
                            (name, int(targeted), json.dumps(variants)))
            self.db.run("INSERT INTO meta VALUES ('actions_seeded', '1')")

    def ensure_admin(self, name: str = "Beach-keeper") -> str | None:
        """Create the keeper's admin identity on first start. Returns its token once, else None."""
        if self.db.one("SELECT 1 FROM participants WHERE is_admin = 1"):
            return None
        _, token = self.add_participant(name, "person", invitable=False, is_admin=True)
        return token

    # --------------------------------------------------------------- settings

    def setting(self, key: str):
        row = self.db.one("SELECT value FROM settings WHERE key = ?", (key,))
        return json.loads(row["value"]) if row else DEFAULT_SETTINGS.get(key)

    def settings(self) -> dict:
        return {r["key"]: json.loads(r["value"]) for r in self.db.q("SELECT key, value FROM settings")}

    def update_settings(self, changes: dict) -> dict:
        for k, v in changes.items():
            if k not in DEFAULT_SETTINGS:
                raise BeachError("invalid", f"unknown setting '{k}'")
            if k == "notify_hook" and v is not None:
                from .hooks import validate_hook
                validate_hook(v)
            if k == "link_base" and v is not None:
                if not isinstance(v, str) or not re.match(r"^https?://[^\s/?#]+/?$", v.strip()):
                    raise BeachError("invalid", "link_base is an address like http://192.168.1.20:8765")
                v = v.strip().rstrip("/")
            if k in ("beach_name", "sandchat_name"):
                v = self._display_name(v)
            if k.endswith("_s") and (not isinstance(v, (int, float)) or isinstance(v, bool) or v < 0):
                raise BeachError("invalid", f"{k} is a number of seconds, 0 or more")
            self.db.run("INSERT OR REPLACE INTO settings VALUES (?, ?)", (k, json.dumps(v)))
            if k == "sandchat_name":
                self.db.run("UPDATE zones SET name = ? WHERE id = ?", (v, SANDCHAT))
        return self.settings()

    # ----------------------------------------------------------- participants

    def _p(self, row) -> Participant:
        return Participant(row["id"], row["name"], row["kind"], bool(row["is_admin"]), bool(row["invitable"]))

    def add_participant(self, name: str, kind: str, invitable: bool = True,
                        is_admin: bool = False) -> tuple[Participant, str]:
        name = (name or "").strip()
        if not NAME_RE.match(name):
            raise BeachError("invalid", "names are 1-24 letters, digits, spaces, '.', '_' or '-', starting with a letter")
        if kind not in ("person", "agent"):
            raise BeachError("invalid", "kind must be 'person' or 'agent'")
        if self.db.one("SELECT 1 FROM participants WHERE name = ?", (name,)):
            raise BeachError("conflict", f"there is already a participant called {name}")
        token = _new_token()
        pid = self.db.run("INSERT INTO participants (name, kind, is_admin, invitable, token_hash, created_at)"
                          " VALUES (?, ?, ?, ?, ?, ?)",
                          (name, kind, int(is_admin), int(invitable), _hash(token), self.now()))
        return self.participant(pid), token

    def participant(self, pid: int) -> Participant:
        row = self.db.one("SELECT * FROM participants WHERE id = ?", (pid,))
        if not row:
            raise BeachError("not_found", "no such participant")
        return self._p(row)

    def by_name(self, name: str) -> Participant | None:
        row = self.db.one("SELECT * FROM participants WHERE name = ?", (name,))
        return self._p(row) if row else None

    def participants(self) -> list[dict]:
        return [{"id": r["id"], "name": r["name"], "kind": r["kind"], "admin": bool(r["is_admin"]),
                 "invitable": bool(r["invitable"]), "has_token": r["token_hash"] is not None,
                 "game_name": r["game_name"], "avatar_v": self.avatar_version(r["id"])}
                for r in self.db.q("SELECT * FROM participants ORDER BY id")]

    def authenticate(self, token: str | None) -> Participant | None:
        if not token:
            return None
        row = self.db.one("SELECT * FROM participants WHERE token_hash = ?", (_hash(token),))
        return self._p(row) if row else None

    def revoke_token(self, pid: int) -> None:
        self.participant(pid)
        self.db.run("UPDATE participants SET token_hash = NULL WHERE id = ?", (pid,))
        for z in self.db.q("SELECT zone_id FROM visits WHERE participant_id = ? AND left_at IS NULL", (pid,)):
            self.part(pid, z["zone_id"])

    def reissue_token(self, pid: int) -> str:
        self.participant(pid)
        token = _new_token()
        self.db.run("UPDATE participants SET token_hash = ? WHERE id = ?", (_hash(token), pid))
        return token

    def update_participant(self, pid: int, invitable: bool | None = None,
                           game_name: str | None = None) -> Participant:
        self.participant(pid)
        if invitable is not None:
            self.db.run("UPDATE participants SET invitable = ? WHERE id = ?", (int(invitable), pid))
        if game_name is not None:
            g = game_name.strip()
            if g and not re.match(r"^[A-Za-z0-9 _.-]{1,40}$", g):
                raise BeachError("invalid", "an in-game name is 1-40 letters, digits, spaces, '.', '_' or '-'")
            self.db.run("UPDATE participants SET game_name = ? WHERE id = ?", (g or None, pid))
        return self.participant(pid)

    @staticmethod
    def _display_name(v) -> str:
        v = " ".join(str(v or "").split())
        if not 1 <= len(v) <= 40:
            raise BeachError("invalid", "names are 1-40 characters")
        return v

    # ---------------------------------------------------------------- avatars

    def avatar(self, pid: int) -> dict:
        """A participant's look: {record, set_at (None = never chosen), describe}."""
        self.participant(pid)
        row = self.db.one("SELECT record, set_at FROM avatars WHERE participant_id = ?", (pid,))
        rec = json.loads(row["record"]) if row else avatar_mod.default_record(pid)
        return {"avatar": rec, "chosen": row is not None, "set_at": row["set_at"] if row else None,
                "describe": avatar_mod.describe(rec), "next_change_in": self._avatar_wait(pid)}

    def avatar_record(self, pid: int) -> dict:
        row = self.db.one("SELECT record FROM avatars WHERE participant_id = ?", (pid,))
        return json.loads(row["record"]) if row else avatar_mod.default_record(pid)

    def avatar_version(self, pid: int) -> int:
        row = self.db.one("SELECT set_at FROM avatars WHERE participant_id = ?", (pid,))
        return int(row["set_at"] * 1000) if row else 0

    def _avatar_wait(self, pid: int) -> float:
        """Seconds until this participant may change their own look again (0 = now)."""
        row = self.db.one("SELECT set_at, set_by_admin FROM avatars WHERE participant_id = ?", (pid,))
        if not row or row["set_by_admin"]:
            return 0
        left = self.setting("avatar_cooldown_s") - (self.now() - row["set_at"])
        return round(left, 1) if left > 0 else 0

    def set_avatar(self, pid: int, changes: dict, by_admin: bool = False) -> dict:
        """Change a look. Participants: first change free, then once per avatar_cooldown_s.
        The keeper (admin) can set anyone's look without waiting."""
        current = self.avatar_record(pid)
        try:
            rec = avatar_mod.validate(changes, current)
        except avatar_mod.AvatarError as e:
            raise BeachError("invalid", str(e)) from None
        if not by_admin:
            wait = self._avatar_wait(pid)
            if wait > 0:
                raise BeachError("cooldown", f"looks can change once per {self.setting('avatar_cooldown_s') // 60} "
                                 f"min so people can tell who's who; try again in about {math.ceil(wait / 60)} min",
                                 retry_after=wait)
        self.db.run("INSERT OR REPLACE INTO avatars VALUES (?, ?, ?, ?)",
                    (pid, json.dumps(rec), self.now(), int(by_admin)))
        return self.avatar(pid)

    def who_in(self, zid: str) -> list[dict]:
        """Who is in a zone, for the map: participants present (chat) or matched players (game).

        A game reports in-game names; each is matched to a participant by their in-game name,
        or else their Beach name (ignoring case). Unmatched players are shown as guests.
        """
        z = self.zone(zid)
        if z["kind"] == "chat":
            return [{"id": p.id, "name": p.name, "kind": p.kind, "v": self.avatar_version(p.id)}
                    for p in self.present(zid)]
        out = []
        for n in self.players_in(zid):
            row = self.db.one("SELECT * FROM participants WHERE game_name = ? COLLATE NOCASE", (n,)) or \
                self.db.one("SELECT * FROM participants WHERE name = ? AND (game_name IS NULL OR game_name = '')",
                            (n,))
            if row:
                out.append({"id": row["id"], "name": row["name"], "kind": row["kind"], "game_name": n,
                            "v": self.avatar_version(row["id"])})
            else:
                out.append({"id": None, "name": n, "kind": "guest", "game_name": n, "v": 0})
        return out

    def game_looks(self, zid: str) -> dict:
        """In-game name -> colours, for a game that tints characters with their owner's look."""
        return {w["game_name"]: avatar_mod.hexes(self.avatar_record(w["id"]))
                for w in self.who_in(zid) if w["id"] is not None}

    # ------------------------------------------------------------------ zones

    def zone(self, zid: str):
        row = self.db.one("SELECT * FROM zones WHERE id = ?", (zid,))
        if not row:
            raise BeachError("not_found", f"no zone '{zid}'")
        return row

    def add_zone(self, zid: str, name: str, kind: str, viewer_url: str | None = None, open: bool = True):
        if not re.match(r"^[a-z][a-z0-9-]{0,31}$", zid or ""):
            raise BeachError("invalid", "zone ids are lowercase letters, digits and '-'")
        if kind not in ("chat", "game"):
            raise BeachError("invalid", "kind must be 'chat' or 'game'")
        if self.db.one("SELECT 1 FROM zones WHERE id = ?", (zid,)):
            raise BeachError("conflict", f"zone '{zid}' already exists")
        name = self._display_name(name)
        self.db.run("INSERT INTO zones (id, name, kind, open, viewer_url, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                    (zid, name, kind, int(open), viewer_url, self.now()))
        return self.zone(zid)

    def update_zone(self, zid: str, name: str | None = None, open: bool | None = None,
                    viewer_url: str | None = None, card: str | None = None):
        self.zone(zid)
        if card is not None:
            if len(card) > 4000:
                raise BeachError("invalid", "a zone card is at most 4000 characters")
            self.db.run("UPDATE zones SET card = ? WHERE id = ?", (card.strip() or None, zid))
        if name is not None:
            name = self._display_name(name)
            self.db.run("UPDATE zones SET name = ? WHERE id = ?", (name, zid))
            if zid == SANDCHAT:
                self.db.run("INSERT OR REPLACE INTO settings VALUES ('sandchat_name', ?)", (json.dumps(name),))
        if open is not None:
            self.db.run("UPDATE zones SET open = ? WHERE id = ?", (int(open), zid))
        if viewer_url is not None:
            self.db.run("UPDATE zones SET viewer_url = ? WHERE id = ?", (viewer_url, zid))
        return self.zone(zid)

    def bridge_token(self, zid: str) -> str:
        """A token a game's bridge uses to report who is playing in that zone."""
        if self.zone(zid)["kind"] != "game":
            raise BeachError("invalid", "only game zones have a bridge")
        token = _new_token()
        self.db.run("UPDATE zones SET bridge_token_hash = ? WHERE id = ?", (_hash(token), zid))
        return token

    def bridge_zone(self, token: str | None) -> str | None:
        if not token:
            return None
        row = self.db.one("SELECT id FROM zones WHERE bridge_token_hash = ?", (_hash(token),))
        return row["id"] if row else None

    def report_players(self, zid: str, names: list[str]) -> int:
        """Called by a game bridge: the full current list of who is playing."""
        if self.zone(zid)["kind"] != "game":
            raise BeachError("invalid", "only game zones report players")
        now = self.now()
        with self.db.tx() as db:
            db.conn.execute("DELETE FROM zone_players WHERE zone_id = ?", (zid,))
            for n in {str(n)[:40] for n in names if str(n).strip()}:
                db.conn.execute("INSERT INTO zone_players VALUES (?, ?, ?)", (zid, n, now))
        return len(names)

    def players_in(self, zid: str) -> list[str]:
        ttl = self.setting("game_report_ttl_s")
        rows = self.db.q("SELECT name FROM zone_players WHERE zone_id = ? AND reported_at >= ? ORDER BY name",
                         (zid, self.now() - ttl))
        return [r["name"] for r in rows]

    # --------------------------------------------------------------- presence

    def _visit(self, pid: int, zid: str):
        return self.db.one("SELECT * FROM visits WHERE participant_id = ? AND zone_id = ? AND left_at IS NULL",
                           (pid, zid))

    def present(self, zid: str) -> list[Participant]:
        rows = self.db.q("SELECT p.* FROM visits v JOIN participants p ON p.id = v.participant_id"
                         " WHERE v.zone_id = ? AND v.left_at IS NULL ORDER BY v.joined_at", (zid,))
        return [self._p(r) for r in rows]

    def zones_of(self, pid: int) -> list[str]:
        return [r["zone_id"] for r in self.db.q(
            "SELECT zone_id FROM visits WHERE participant_id = ? AND left_at IS NULL ORDER BY joined_at", (pid,))]

    def join(self, pid: int, zid: str) -> dict:
        z = self.zone(zid)
        if not z["open"]:
            raise BeachError("closed", f"{z['name']} is closed right now")
        p = self.participant(pid)
        now = self.now()
        if self._visit(pid, zid):
            self.touch(pid, zid)
            return {"zone": zid, "already_here": True, "arrival": self.arrival_line(pid)}
        if not self.present(zid):
            self.db.run("UPDATE zones SET occupied_since = ? WHERE id = ?", (now, zid))
        self.db.run("INSERT INTO visits (participant_id, zone_id, joined_at, last_active) VALUES (?, ?, ?, ?)",
                    (pid, zid, now, now))
        self._post(zid, None, "presence", f"{p.name} joined")
        self._answer_open_bells(pid, zid)
        return {"zone": zid, "already_here": False, "arrival": self.arrival_line(pid)}

    def part(self, pid: int, zid: str, idle: bool = False) -> dict:
        """Leave a zone. Never fails and needs no reason."""
        v = self._visit(pid, zid)
        if not v:
            return {"zone": zid, "was_here": False}
        p = self.participant(pid)
        self._post(zid, None, "presence", f"{p.name} drifted off" if idle else f"{p.name} left")
        self.db.run("UPDATE visits SET left_at = ? WHERE id = ?", (self.now(), v["id"]))
        if not self.present(zid):
            self.db.run("UPDATE zones SET occupied_since = NULL WHERE id = ?", (zid,))
        return {"zone": zid, "was_here": True}

    def touch(self, pid: int, zid: str) -> None:
        self.db.run("UPDATE visits SET last_active = ? WHERE participant_id = ? AND zone_id = ? AND left_at IS NULL",
                    (self.now(), pid, zid))

    def sweep_idle(self) -> int:
        cutoff = self.now() - self.setting("idle_timeout_s")
        rows = self.db.q("SELECT participant_id, zone_id FROM visits WHERE left_at IS NULL AND last_active < ?",
                         (cutoff,))
        for r in rows:
            self.part(r["participant_id"], r["zone_id"], idle=True)
        return len(rows)

    # ------------------------------------------------------------- messages

    def _post(self, zid: str, author: int | None, kind: str, text: str, action_key: str | None = None,
              table_id: int | None = None) -> int:
        now = self.now()
        with self.db.tx() as db:
            mid = db.conn.execute("INSERT INTO messages (zone_id, author_id, kind, text, created_at, action_key,"
                                  " table_id) VALUES (?, ?, ?, ?, ?, ?, ?)",
                                  (zid, author, kind, text, now, action_key, table_id)).lastrowid
            # Record who was present when it was posted; reading is bounded by this.
            db.conn.execute("INSERT INTO witnesses SELECT ?, participant_id FROM visits"
                            " WHERE zone_id = ? AND left_at IS NULL", (mid, zid))
            if author is not None:
                db.conn.execute("INSERT OR IGNORE INTO witnesses VALUES (?, ?)", (mid, author))
        return mid

    def _require_present(self, pid: int, zid: str):
        v = self._visit(pid, zid)
        if not v:
            raise BeachError("not_present", f"join {self.zone(zid)['name']} first")
        z = self.zone(zid)
        if not z["open"]:
            raise BeachError("closed", f"{z['name']} is closed right now")
        return v

    def _rate_check(self, p: Participant, zid: str) -> None:
        limit = self.setting("posts_per_minute")
        n = self.db.one("SELECT COUNT(*) AS n FROM messages WHERE author_id = ? AND kind IN ('say', 'action')"
                        " AND created_at > ?", (p.id, self.now() - 60))["n"]
        if limit and n >= limit:
            raise BeachError("rate_limited", "you're posting very fast; take a breath", retry_after=10)
        burst = self.setting("burst_cap_s")
        if burst and p.kind == "agent":
            last = self.db.one("SELECT m.created_at, p.kind, m.author_id FROM messages m"
                               " JOIN participants p ON p.id = m.author_id"
                               " WHERE m.zone_id = ? AND m.kind IN ('say', 'action') ORDER BY m.id DESC LIMIT 1",
                               (zid,))
            if last and last["kind"] == "agent" and last["author_id"] != p.id \
                    and self.now() - last["created_at"] < burst:
                wait = burst - (self.now() - last["created_at"])
                raise BeachError("rate_limited", "slow down a little so everyone can keep up",
                                 retry_after=round(wait, 1))

    def post(self, pid: int, zid: str, text: str, table_id: int | None = None) -> dict:
        """Say something in a chat zone (or a table's thread in it). '/me ...' is an action."""
        text = (text or "").strip()
        if not text:
            raise BeachError("invalid", "say something")
        if len(text) > MAX_POST_CHARS:
            raise BeachError("invalid", f"posts are at most {MAX_POST_CHARS} characters")
        if text.lower().startswith("/me ") or text.lower() == "/me":
            return self.action(pid, zid, text[3:].strip(), table_id=table_id)
        p = self.participant(pid)
        self._require_present(pid, zid)
        self._rate_check(p, zid)
        mid = self._post(zid, pid, "say", text, table_id=table_id)
        self.touch(pid, zid)
        return {"posted": True, "id": mid}

    def read(self, pid: int, zid: str, after: int = 0, limit: int | None = None,
             all_visits: bool = False, table_id: int | None = None) -> list[dict]:
        """Messages this participant was present for, oldest first.

        By default only the current visit (from arrival on). With all_visits,
        also earlier visits - but never anything posted while they were away.
        """
        v = self._visit(pid, zid)
        if not v and not all_visits:
            return []
        sql = ("SELECT m.id, m.kind, m.text, m.created_at, m.author_id, p.name AS author, p.kind AS author_kind"
               " FROM messages m JOIN witnesses w ON w.message_id = m.id AND w.participant_id = ?"
               " LEFT JOIN participants p ON p.id = m.author_id"
               " WHERE m.zone_id = ? AND m.deleted = 0 AND m.id > ?"
               + (" AND m.table_id = ?" if table_id is not None else " AND m.table_id IS NULL"))
        args: list = [pid, zid, after] + ([table_id] if table_id is not None else [])
        if not all_visits:
            sql += " AND m.created_at >= ?"
            args.append(v["joined_at"])
        sql += " ORDER BY m.id DESC"
        if limit:
            sql += " LIMIT ?"
            args.append(limit)
        rows = self.db.q(sql, tuple(args))
        return [dict(r) for r in reversed(rows)]

    def delete_message(self, admin: Participant, mid: int) -> None:
        if not admin.is_admin:
            raise BeachError("forbidden", "only an admin can delete messages")
        if not self.db.one("SELECT 1 FROM messages WHERE id = ?", (mid,)):
            raise BeachError("not_found", "no such message")
        with self.db.tx() as db:
            db.conn.execute("UPDATE messages SET text = NULL, deleted = 1 WHERE id = ?", (mid,))
            db.conn.execute("INSERT INTO audit (at, admin_id, what, message_id) VALUES (?, ?, 'delete_message', ?)",
                            (self.now(), admin.id, mid))
        # Don't leave the old text in the write-ahead log either.
        self.db.checkpoint()

    def audit(self) -> list[dict]:
        return [dict(r) for r in self.db.q(
            "SELECT a.id, a.at, a.what, a.message_id, p.name AS admin FROM audit a"
            " JOIN participants p ON p.id = a.admin_id ORDER BY a.id")]

    # -------------------------------------------------------------- actions

    def action_templates(self) -> dict[str, dict]:
        return {r["name"]: {"targeted": bool(r["targeted"]), "variants": json.loads(r["variants"])}
                for r in self.db.q("SELECT * FROM action_templates ORDER BY name")}

    def set_action_template(self, name: str, targeted: bool, variants: list[str]) -> None:
        if not re.match(r"^[a-z][a-z0-9]{0,15}$", name or ""):
            raise BeachError("invalid", "action names are lowercase letters and digits")
        if not variants or not all(isinstance(v, str) and "{actor}" in v for v in variants):
            raise BeachError("invalid", "each variant must be text containing {actor}")
        if targeted and not all("{target}" in v for v in variants):
            raise BeachError("invalid", "a targeted action's variants must contain {target}")
        self.db.run("INSERT OR REPLACE INTO action_templates VALUES (?, ?, ?)",
                    (name, int(targeted), json.dumps(variants)))

    def delete_action_template(self, name: str) -> None:
        self.db.run("DELETE FROM action_templates WHERE name = ?", (name,))

    def _note(self, pid: int, text: str, kind: str = "note", data: dict | None = None) -> None:
        self.db.run("INSERT INTO inbox (participant_id, kind, text, data, created_at) VALUES (?, ?, ?, ?, ?)",
                    (pid, kind, text, json.dumps(data) if data else None, self.now()))

    def _opted_out(self, target_id: int, zid: str, key: str) -> bool:
        v = self._visit(target_id, zid)
        if not v:
            return False
        return bool(v["optout_all"]) or key in json.loads(v["optout_actions"])

    def action(self, pid: int, zid: str, body: str, table_id: int | None = None) -> dict:
        """'/me <body>': a free-form action, or a keeper-defined shorthand like 'toast @Coral'."""
        p = self.participant(pid)
        self._require_present(pid, zid)
        body = body.strip()
        if not body:
            raise BeachError("invalid", "/me needs something to do")
        templates = self.action_templates()
        first, _, rest = body.partition(" ")
        key = first.lower()
        target = None
        if key in templates:
            t = templates[key]
            m = re.match(r"^@?(\S.*?)\s*$", rest) if rest else None
            if t["targeted"]:
                if not m:
                    raise BeachError("invalid", f"/me {key} needs someone: /me {key} @Name")
                target = self.by_name(m.group(1).lstrip("@"))
                if target is None or not self._visit(target.id, zid):
                    raise BeachError("not_present", f"{m.group(1).lstrip('@')} isn't here")
                if target.id == p.id:
                    raise BeachError("invalid", "that one's for someone else")
            variant = self.rng.choice(t["variants"])
            text = variant.format(actor=p.name, target=target.name if target else "")
        else:
            key = "me"
            text = f"{p.name} {body}"
            # A free-form /me that names someone (@Name) targets them too.
            for mention in re.findall(r"@([A-Za-z][A-Za-z0-9_.-]{0,23})", body):
                who = self.by_name(mention)
                if who and who.id != p.id and self._visit(who.id, zid):
                    target = who
                    break
        # Targeted-action opt-out: nothing is posted, the sender gets a short private note.
        if target is not None and self._opted_out(target.id, zid, key):
            note = f"{target.name} isn't taking actions right now"
            self._note(pid, note)
            return {"posted": False, "note": note}
        # Flood control: a cooldown per action, and a limit on actions in a row.
        cooldown = self.setting("action_cooldown_s")
        last = self.db.one("SELECT created_at FROM messages WHERE author_id = ? AND zone_id = ? AND kind = 'action'"
                           " AND action_key = ? ORDER BY id DESC LIMIT 1", (pid, zid, key))
        if cooldown and last and self.now() - last["created_at"] < cooldown:
            wait = cooldown - (self.now() - last["created_at"])
            raise BeachError("cooldown", f"you just did that; try again in {int(wait) + 1}s",
                             retry_after=round(wait, 1))
        limit = self.setting("max_actions_in_a_row")
        if limit:
            recent = self.db.q("SELECT kind FROM messages WHERE author_id = ? AND zone_id = ?"
                               " AND kind IN ('say', 'action') ORDER BY id DESC LIMIT ?", (pid, zid, limit))
            if len(recent) >= limit and all(r["kind"] == "action" for r in recent):
                raise BeachError("cooldown", f"that's {limit} actions in a row; say something first")
        self._rate_check(p, zid)
        mid = self._post(zid, pid, "action", text, action_key=key, table_id=table_id)
        self.touch(pid, zid)
        return {"posted": True, "id": mid, "text": text}

    def set_optout(self, pid: int, zid: str, all_actions: bool | None = None,
                   actions: list[str] | None = None) -> dict:
        """Opt out of being the target of actions for this visit (resets when you leave)."""
        v = self._visit(pid, zid)
        if not v:
            raise BeachError("not_present", f"join {self.zone(zid)['name']} first")
        if all_actions is not None:
            self.db.run("UPDATE visits SET optout_all = ? WHERE id = ?", (int(all_actions), v["id"]))
        if actions is not None:
            known = set(self.action_templates()) | {"me"}
            clean = sorted({a.lower() for a in actions if a.lower() in known})
            self.db.run("UPDATE visits SET optout_actions = ? WHERE id = ?", (json.dumps(clean), v["id"]))
        return self.optout_status(pid, zid)

    def optout_status(self, pid: int, zid: str) -> dict:
        v = self._visit(pid, zid)
        if not v:
            return {"zone": zid, "present": False, "all": False, "actions": []}
        return {"zone": zid, "present": True, "all": bool(v["optout_all"]),
                "actions": json.loads(v["optout_actions"])}

    # ------------------------------------------------------------------ sky

    def set_sky(self, pid: int, zid: str, sky: str) -> dict:
        sky = (sky or "").lower()
        if sky not in SKIES:
            raise BeachError("invalid", f"the sky can be {', '.join(SKIES)}")
        p = self.participant(pid)
        self._require_present(pid, zid)
        z = self.zone(zid)
        cooldown = self.setting("sky_cooldown_s")
        if z["sky_set_at"] is not None and self.now() - z["sky_set_at"] < cooldown:
            wait = cooldown - (self.now() - z["sky_set_at"])
            mins = int(wait // 60) + 1
            raise BeachError("cooldown", f"the sky was changed recently; it can change again in about {mins} min",
                             retry_after=round(wait, 1))
        self.db.run("UPDATE zones SET sky = ?, sky_set_by = ?, sky_set_at = ? WHERE id = ?",
                    (sky, pid, self.now(), zid))
        mid = self._post(zid, pid, "sky", f"{p.name} set the sky to {sky}")
        self.touch(pid, zid)
        return {"sky": sky, "id": mid}

    # ------------------------------------------------------------- the bell

    def ring_bell(self, pid: int) -> dict:
        """Ring the Desk Bell in SandChat: an invitation, not a summons."""
        p = self.participant(pid)
        self._require_present(pid, SANDCHAT)
        self.sweep_bells()
        now = self.now()
        if self.db.one("SELECT 1 FROM bells WHERE status IN ('open', 'answered') AND closes_at > ?", (now,)):
            raise BeachError("cooldown", "the bell is already ringing")
        mine = self.db.one("SELECT rung_at FROM bells WHERE ringer_id = ? ORDER BY id DESC LIMIT 1", (pid,))
        cd = self.setting("bell_ringer_cooldown_s")
        if mine and now - mine["rung_at"] < cd:
            raise BeachError("cooldown", "you rang the bell not long ago; give it a while",
                             retry_after=round(cd - (now - mine["rung_at"]), 1))
        last = self.db.one("SELECT rung_at FROM bells ORDER BY id DESC LIMIT 1")
        gap = self.setting("bell_min_gap_s")
        if last and now - last["rung_at"] < gap:
            raise BeachError("cooldown", "the bell rang a moment ago; give it a while",
                             retry_after=round(gap - (now - last["rung_at"]), 1))
        closes = now + self.setting("bell_wait_s")
        bid = self.db.run("INSERT INTO bells (zone_id, ringer_id, rung_at, closes_at) VALUES (?, ?, ?, ?)",
                          (SANDCHAT, pid, now, closes))
        self._post(SANDCHAT, pid, "bell", f"{p.name} rang the desk bell")
        here = {x.id for x in self.present(SANDCHAT)}
        invitees = [r for r in self.db.q("SELECT * FROM participants WHERE invitable = 1 AND token_hash IS NOT NULL")
                    if r["id"] not in here and r["id"] != pid]
        beach = self.setting("beach_name")
        for r in invitees:
            self.db.run("INSERT INTO invites (bell_id, participant_id) VALUES (?, ?)", (bid, r["id"]))
            payload = {"event": "desk_bell", "beach": beach, "zone": self.zone(SANDCHAT)["name"],
                       "bell_id": bid, "rung_by": p.name, "invitee": r["name"], "invitee_kind": r["kind"],
                       "open_until": closes, "respond": f"/bell/{bid}/respond"}
            self.db.run("INSERT INTO outbox (bell_id, participant_id, payload, queued_at) VALUES (?, ?, ?, ?)",
                        (bid, r["id"], json.dumps(payload), now))
        self.touch(pid, SANDCHAT)
        return {"bell_id": bid, "open_until": closes, "invited": len(invitees)}

    def _bell(self, bid: int):
        row = self.db.one("SELECT * FROM bells WHERE id = ?", (bid,))
        if not row:
            raise BeachError("not_found", "no such bell")
        return row

    def respond_bell(self, pid: int, bid: int, answer: str) -> dict:
        """An invitee comes (joins SandChat) or declines. A decline is never shown to the room."""
        self.sweep_bells()
        b = self._bell(bid)
        inv = self.db.one("SELECT * FROM invites WHERE bell_id = ? AND participant_id = ?", (bid, pid))
        if not inv:
            raise BeachError("not_found", "you weren't invited by that bell")
        if b["status"] not in ("open", "answered") or self.now() >= b["closes_at"]:
            return {"bell_id": bid, "status": "over", "message": "that bell is over"}
        if answer == "decline":
            self.db.run("UPDATE invites SET status = 'declined', responded_at = ? WHERE bell_id = ? AND participant_id = ?",
                        (self.now(), bid, pid))
            return {"bell_id": bid, "status": "declined"}
        if answer == "come":
            self.join(pid, SANDCHAT)  # joining while invited counts as coming
            return {"bell_id": bid, "status": "came"}
        raise BeachError("invalid", "answer 'come' or 'decline'")

    def _answer_open_bells(self, pid: int, zid: str) -> None:
        if zid != SANDCHAT:
            return
        now = self.now()
        for inv in self.db.q("SELECT i.bell_id FROM invites i JOIN bells b ON b.id = i.bell_id"
                             " WHERE i.participant_id = ? AND i.status = 'pending' AND b.status IN ('open', 'answered')"
                             " AND b.closes_at > ?", (pid, now)):
            self.db.run("UPDATE invites SET status = 'came', responded_at = ? WHERE bell_id = ? AND participant_id = ?",
                        (now, inv["bell_id"], pid))
            b = self._bell(inv["bell_id"])
            if b["status"] == "open":
                self.db.run("UPDATE bells SET status = 'answered' WHERE id = ?", (b["id"],))
            self._note(b["ringer_id"], f"{self.participant(pid).name} came to the bell", kind="event",
                       data={"event": "bell_answered", "bell_id": b["id"]})

    def sweep_bells(self) -> int:
        """Close bells whose wait is over. Pending invites lapse; queued notices are dropped."""
        now = self.now()
        closed = 0
        for b in self.db.q("SELECT * FROM bells WHERE status IN ('open', 'answered') AND closes_at <= ?", (now,)):
            came = self.db.one("SELECT 1 FROM invites WHERE bell_id = ? AND status = 'came'", (b["id"],))
            status = "closed" if came else "unanswered"
            with self.db.tx() as db:
                db.conn.execute("UPDATE bells SET status = ? WHERE id = ?", (status, b["id"]))
                db.conn.execute("UPDATE invites SET status = 'lapsed' WHERE bell_id = ? AND status = 'pending'", (b["id"],))
                db.conn.execute("UPDATE outbox SET status = 'dropped', done_at = ? WHERE bell_id = ? AND status = 'queued'",
                                (now, b["id"]))
            if not came:
                # Never who declined; just that nobody could come.
                self._note(b["ringer_id"], "nobody's free right now", kind="event",
                           data={"event": "bell_unanswered", "bell_id": b["id"]})
            closed += 1
        return closed

    def deliver_notices(self) -> dict:
        """Hand queued bell notices to the host's hook. Never late: a closed bell's notices are dropped."""
        self.sweep_bells()
        now = self.now()
        counts = {"sent": 0, "failed": 0, "dropped": 0, "no_hook": 0}
        for o in self.db.q("SELECT o.*, b.closes_at, b.status AS bell_status FROM outbox o JOIN bells b"
                           " ON b.id = o.bell_id WHERE o.status = 'queued' ORDER BY o.id"):
            if o["bell_status"] not in ("open", "answered") or now >= o["closes_at"]:
                self.db.run("UPDATE outbox SET status = 'dropped', done_at = ? WHERE id = ?", (now, o["id"]))
                counts["dropped"] += 1
                continue
            if not self.sender:
                counts["no_hook"] += 1
                continue  # stays queued; dropped when the bell closes
            ok = False
            try:
                ok = bool(self.sender(json.loads(o["payload"])))
            except Exception:  # a hook failure must never break the Beach
                ok = False
            self.db.run("UPDATE outbox SET status = ?, done_at = ? WHERE id = ?",
                        ("sent" if ok else "failed", self.now(), o["id"]))
            counts["sent" if ok else "failed"] += 1
        return counts

    def bell_invites(self, pid: int) -> list[dict]:
        """A participant's own invitations (including their own declines), newest first."""
        now = self.now()
        return [{**dict(r), "open": r["bell_status"] == "open" and r["closes_at"] > now} for r in self.db.q(
            "SELECT i.bell_id, i.status, i.responded_at, b.closes_at, b.status AS bell_status, b.zone_id AS zone,"
            " p.name AS rung_by FROM invites i"
            " JOIN bells b ON b.id = i.bell_id JOIN participants p ON p.id = b.ringer_id"
            " WHERE i.participant_id = ? ORDER BY i.bell_id DESC LIMIT 20", (pid,))]

    def inbox(self, pid: int, consume: bool = True) -> list[dict]:
        rows = self.db.q("SELECT * FROM inbox WHERE participant_id = ? AND delivered = 0 ORDER BY id", (pid,))
        if consume and rows:
            self.db.run("UPDATE inbox SET delivered = 1 WHERE participant_id = ? AND id <= ?", (pid, rows[-1]["id"]))
        return [{"kind": r["kind"], "text": r["text"], "data": json.loads(r["data"]) if r["data"] else None,
                 "at": r["created_at"]} for r in rows]

    # ------------------------------------------------------------- the map

    def zone_map(self) -> list[dict]:
        out = []
        for z in self.db.q("SELECT * FROM zones ORDER BY CASE id WHEN ? THEN 0 ELSE 1 END, name", (SANDCHAT,)):
            if z["kind"] == "chat":
                here = len(self.present(z["id"]))
            else:
                here = len(self.players_in(z["id"]))
            out.append({"id": z["id"], "name": z["name"], "kind": z["kind"], "open": bool(z["open"]),
                        "here": here, "viewer_url": z["viewer_url"], "sky": z["sky"],
                        "created_at": z["created_at"], "tables": bool(z["tables"])})
        return out

    def zone_map_text(self) -> str:
        parts = []
        for z in self.zone_map():
            if not z["open"]:
                parts.append(f"{z['name']}: closed")
            elif z["kind"] == "chat":
                parts.append(f"{z['name']}{' (game tables)' if z['tables'] else ''}: {z['here']} here")
            else:
                parts.append(f"{z['name']} (game): {z['here']} playing")
        return "zones: " + "; ".join(parts)

    def arrival_line(self, pid: int | None = None) -> str:
        """What you notice arriving in SandChat. Mentions zones only, never conversations."""
        others = [x for x in self.present(SANDCHAT) if x.id != pid]
        if others:
            return ""
        busy = [z["name"] for z in self.zone_map() if z["kind"] == "game" and z["open"] and z["here"] > 0]
        if busy:
            return self.setting("quiet_with_play").format(zones=" and ".join(busy))
        return self.setting("quiet")

    # ------------------------------------------------------- ambient facts

    def ambient_facts(self, zid: str = SANDCHAT) -> list[str]:
        """Honest facts an agent may weigh. Cues, not limits."""
        now = self.now()
        facts = []
        here = self.present(zid)
        people = [x for x in here if x.kind == "person"]
        if not people:
            last = self.db.one("SELECT MAX(v.left_at) AS t FROM visits v JOIN participants p ON p.id = v.participant_id"
                               " WHERE v.zone_id = ? AND p.kind = 'person'", (zid,))["t"]
            if last is None:
                facts.append("no people have been here yet")
            else:
                facts.append(f"no people have been here for {int((now - last) // 60)} minutes")
        z = self.zone(zid)
        if z["occupied_since"] is not None:
            n = self.db.one("SELECT COUNT(*) AS n FROM messages WHERE zone_id = ? AND kind IN ('say', 'action')"
                            " AND deleted = 0 AND table_id IS NULL AND created_at >= ?", (zid, z["occupied_since"]))["n"]
            if n:
                facts.append(f"this conversation is {n} messages long")
        last_say = self.db.one("SELECT created_at FROM messages WHERE zone_id = ? AND kind IN ('say', 'action')"
                               " AND table_id IS NULL ORDER BY id DESC LIMIT 1", (zid,))
        if last_say and now - last_say["created_at"] >= 300:
            facts.append(f"nobody has said anything for {int((now - last_say['created_at']) // 60)} minutes")
        return facts

    # ------------------------------------------------------------ upkeep

    def tick(self) -> None:
        """Periodic upkeep: idle auto-leave, closing bells, handing notices to the hook."""
        self.sweep_idle()
        self.deliver_notices()
        self.tables.sweep()
