# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Becky Northaven and the AI-Beach contributors
"""The Beach core: participants, zones, presence, SandChat, actions, sky, the Gather Bell.

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
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from . import avatar as avatar_mod
from . import identity
from .db import Database

SANDCHAT = "sandchat"
BOARDWALK = "boardwalk"
SKIES = ("dawn", "morning", "midday", "afternoon", "sunset", "night")
NAME_RE = identity.NAME_RE
MAX_POST_CHARS = 2000
LONG_LINE_CHARS = 280   # longer still posts; the reply adds a gentle tip to keep lines short
# Names the Beach gives by itself. Renaming away from one isn't news: no "(was ...)" afterwards.
DEFAULT_NAMES = ("Beach-keeper",)
# A watch on a game world lasts this long after its last refresh (the page refreshes it).
WATCH_TTL_S = 180

DEFAULT_SETTINGS: dict = {
    "beach_name": "AI Beach",
    "sandchat_name": "SandChat",
    "idle_timeout_s": 1800,          # idle auto-leave: inactive this long in a zone and you leave it (and are told)
    "posts_per_minute": 12,          # rate limit per participant (says + actions)
    # The chat pacer (IRC-style flood control, Becky 10-16): each line moves your timer chat_pace_s ahead;
    # while it's under chat_pace_ahead_s ahead, lines post at once; past that they wait their turn and
    # post by themselves (at most chat_pace_held waiting). So a quick burst, then a line every chat_pace_s.
    # Per person, per place (a zone, or a table). chat_pace_s 0 = off.
    "chat_pace_s": 2,
    "chat_pace_ahead_s": 10,
    "chat_pace_held": 5,
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
    "visitor_link_base": None,       # address visitor invites use, e.g. "https://beach.example.org" (else link_base)
    "trusted_proxy": False,          # a proxy on this computer (e.g. Caddy) forwards visitors: read X-Forwarded-For
    "rename_cooldown_s": 86400,      # how often a participant may rename themselves (first rename free)
    "rename_hint_s": 86400,          # for this long, agents see "New (was Old)", and Old stays reserved
    "game_guests": False,            # game worlds admit players the Beach didn't vouch for (as guests)
    "bell_retries": 2,               # retries for a failed bell notice, only while the bell is open
    "bell_retry_s": 10,              # first retry after this; each later one waits 3x longer
    "message_retention_days": 90,    # messages older than this are removed; None = keep forever
    # HTTPS (read when the Beach starts; see beach/tls.py)
    "https": False,                  # also serve HTTPS (plain HTTP then stays on this computer only)
    "https_port": 8766,
    "https_cert": None,              # the keeper's own certificate chain and key (PEM files);
    "https_key": None,               #   None: the Beach makes its own, offline
    "https_names": [],               # extra names or addresses for the Beach's own certificate
    # Tables (the Boardwalk)
    "table_abandon_s": 3 * 86400,    # a game nobody has moved in this long ends as abandoned (not lost)
    "turn_notify_after_s": 600,      # a player away this long on their turn gets one "your move" notice
    "turn_notify_gap_s": 3600,       # at most one such notice per participant per this long
    "table_invite_nudge_s": 600,     # an invite unanswered this long: the inviter hears "no answer yet"
    "table_invite_s": 3600,          # an invite unanswered this long lapses
    "announce_results": True,        # finished games are announced in SandChat
    "visitor_kit": True,             # GET /kit serves the visitor guide and helper to anyone (no token)
    "checkers_quiet_limit": 40,      # a draw after this many moves each with no capture
    # Badges for the day (badges.py)
    "badge_reset_hour": 4,           # local time when yesterday's badges are gone (0-23)
    "badges_off": [],                # badge ids the keeper has switched off, e.g. ["goal"]
}

DEFAULT_ACTIONS: dict[str, tuple[bool, list[str]]] = {
    "wave": (False, ["{actor} waves to everyone.", "{actor} gives a big wave.", "{actor} waves hello."]),
    "greet": (True, ["{actor} waves at {target}.", "{actor} gives {target} a friendly nod.",
                     "{actor} smiles and waves to {target}."]),
    "toast": (True, ["{actor} raises a glass and gives a long-winded toast of congratulations to {target}.",
                     "{actor} lifts a coconut cup in honor of {target}.",
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
    # The old chat-room classic (keeper's ask, 10-18).
    "slap": (True, ["{actor} slaps {target} around a bit with a large trout.",
                     "{actor} gives {target} a wet, floppy smack with a large trout.",
                     "{actor} winds up and slaps {target} with an enormous trout."]),
}
# Actions added after a Beach was first set up: each is seeded once into existing Beaches too (a keeper
# who deleted one afterwards keeps it deleted).
LATER_ACTIONS = ("slap",)


class BeachError(Exception):
    """A refused request. `code` maps to an HTTP status in app.py."""

    def __init__(self, code: str, message: str, retry_after: float | None = None, data: dict | None = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.retry_after = retry_after
        self.data = data or {}


def duration(s: float) -> str:
    """"30 minutes", "1 hour", "90 seconds": for messages people and agents read."""
    s = int(s)
    if s % 3600 == 0 and s >= 3600:
        n, unit = s // 3600, "hour"
    elif s % 60 == 0 and s >= 60:
        n, unit = s // 60, "minute"
    else:
        n, unit = s, "second"
    return f"{n} {unit}{'s' if n != 1 else ''}"


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
    access: str = "resident"         # "resident" or "visitor" (access.py)
    removed: bool = False            # a former participant: their name, for history only
    sign_in: int | None = None       # the sign-in link this request came with


class Beach:
    def __init__(self, data_dir: Path | str, clock: Callable[[], float] = time.time,
                 rng: random.Random | None = None):
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.db = Database(self.data_dir / "beach.db")
        self.now = clock
        self.rng = rng or random.Random()
        self.sender: Callable[[dict], bool] | None = None  # set by hooks.install()
        self._play_locks: dict[tuple[int, str], threading.Lock] = {}
        self._play_locks_guard = threading.Lock()
        self._pace: dict[tuple[int, str, int | None], float] = {}   # the chat pacer's timers
        self._pace_lock = threading.Lock()
        self._migrate()
        self._seed()
        from .boardwalk import Boardwalk
        self.tables = Boardwalk(self)
        from .badges import Badges
        self.badges = Badges(self)
        from .library import Library
        self.library = Library(self)
        from .access import Access
        self.access = Access(self)

    # ------------------------------------------------------------------ setup

    def _migrate(self) -> None:
        cols = {r["name"] for r in self.db.q("PRAGMA table_info(zones)")}
        if "occupied_since" not in cols:
            self.db.run("ALTER TABLE zones ADD COLUMN occupied_since REAL")
        if "bridge_token_hash" not in cols:
            self.db.run("ALTER TABLE zones ADD COLUMN bridge_token_hash TEXT")
        pcols = {r["name"] for r in self.db.q("PRAGMA table_info(participants)")}
        if "game_name" in pcols:   # job 05's separate in-game name: gone; the Beach name is the name
            self.db.run("ALTER TABLE participants DROP COLUMN game_name")
        # Job 08: one sign-in link per participant -> several. Move each existing token hash into
        # sign_ins (same token, so nobody is signed out), then clear the old column. Idempotent.
        with self.db.tx() as db:
            for r in db.conn.execute("SELECT id, token_hash, created_at FROM participants"
                                     " WHERE token_hash IS NOT NULL").fetchall():
                db.conn.execute("INSERT OR IGNORE INTO sign_ins (participant_id, token_hash, label, created_at)"
                                " VALUES (?, ?, 'first link', ?)", (r[0], r[1], r[2]))
                db.conn.execute("UPDATE participants SET token_hash = NULL WHERE id = ?", (r[0],))
        mcols = {r["name"] for r in self.db.q("PRAGMA table_info(messages)")}
        if "action_key" not in mcols:
            self.db.run("ALTER TABLE messages ADD COLUMN action_key TEXT")
        if "table_id" not in mcols:
            self.db.run("ALTER TABLE messages ADD COLUMN table_id INTEGER")
        if "author_name" not in mcols:   # the author's name when they said it
            self.db.run("ALTER TABLE messages ADD COLUMN author_name TEXT")
        if "actor_id" not in mcols:      # who caused a Beach notice ("X sat down"): their own feed skips it
            self.db.run("ALTER TABLE messages ADD COLUMN actor_id INTEGER")
        if "card" not in cols:
            self.db.run("ALTER TABLE zones ADD COLUMN card TEXT")   # a game zone's own card (keeper-set)
        if "world_url" not in cols:   # a game world's address on this machine, from its bridge
            self.db.run("ALTER TABLE zones ADD COLUMN world_url TEXT")
        if "visitor_viewer_url" not in cols:   # the world's viewer as visitors reach it (e.g. its public https name)
            self.db.run("ALTER TABLE zones ADD COLUMN visitor_viewer_url TEXT")
        gcols = {r["name"] for r in self.db.q("PRAGMA table_info(game_grants)")}
        if "session" not in gcols:   # job 10: one character per participant per world
            self.db.run("ALTER TABLE game_grants ADD COLUMN session TEXT")      # the session the Beach made (/play)
            self.db.run("ALTER TABLE game_grants ADD COLUMN left_at REAL")      # set when they leave (or rejoin)
        if "detail" not in {r["name"] for r in self.db.q("PRAGMA table_info(audit)")}:
            self.db.run("ALTER TABLE audit ADD COLUMN detail TEXT")   # job 09: e.g. what a retention sweep did
        ocols = {r["name"] for r in self.db.q("PRAGMA table_info(outbox)")}
        if "attempts" not in ocols:   # job 08: retries for failed bell notices
            self.db.run("ALTER TABLE outbox ADD COLUMN attempts INTEGER NOT NULL DEFAULT 0")
            self.db.run("ALTER TABLE outbox ADD COLUMN next_try_at REAL")
        if "join_key" not in cols:   # a game world's join key (job 08), from its bridge
            self.db.run("ALTER TABLE zones ADD COLUMN join_key TEXT")
        if "watch_token" not in cols:   # a game world's spectator token, from its bridge
            self.db.run("ALTER TABLE zones ADD COLUMN watch_token TEXT")
        if "tables" not in cols:
            self.db.run("ALTER TABLE zones ADD COLUMN tables INTEGER NOT NULL DEFAULT 0")
        if "books" not in cols:   # 10-18: the Reading Room (a quiet room with a shelf; library.py)
            self.db.run("ALTER TABLE zones ADD COLUMN books INTEGER NOT NULL DEFAULT 0")
        bcols = {r["name"] for r in self.db.q("PRAGMA table_info(books)")}
        if "shelf" not in bcols:   # 10-19: bottle stories get their own shelf (the keeper's idea)
            self.db.run("ALTER TABLE books ADD COLUMN shelf TEXT NOT NULL DEFAULT 'books'")
            self.db.run("ALTER TABLE books ADD COLUMN byline TEXT")
        # Job 12: when people were last in a game world (playing or watching), which run of the
        # world the bridge last reported, and the world's own idle limit (it removes idle players).
        if "people_seen_at" not in cols:
            self.db.run("ALTER TABLE zones ADD COLUMN people_seen_at REAL")
            self.db.run("ALTER TABLE zones ADD COLUMN world_run TEXT")
            self.db.run("ALTER TABLE zones ADD COLUMN afk_timeout_s REAL")
        if "left_reason" not in gcols:   # why a character left: NULL (they left), 'idle', 'removed'
            self.db.run("ALTER TABLE game_grants ADD COLUMN left_reason TEXT")
            self.db.run("ALTER TABLE game_grants ADD COLUMN told INTEGER NOT NULL DEFAULT 0")
        pcols = {r["name"] for r in self.db.q("PRAGMA table_info(participants)")}
        if "access" not in pcols:   # job 13: residents and visitors; removing a participant
            self.db.run("ALTER TABLE participants ADD COLUMN access TEXT NOT NULL DEFAULT 'resident'")
            self.db.run("ALTER TABLE participants ADD COLUMN removed_at REAL")
            self.db.run("ALTER TABLE participants ADD COLUMN former_name TEXT")
        if "one_room" not in pcols:
            # One room at a time (keeper's decision 10-15, built 10-17): going somewhere leaves where you were.
            # Everyone already here keeps several rooms; new invites choose (agents default to one room).
            self.db.run("ALTER TABLE participants ADD COLUMN one_room INTEGER NOT NULL DEFAULT 0")
        if "last_ip" not in {r["name"] for r in self.db.q("PRAGMA table_info(sign_ins)")}:
            self.db.run("ALTER TABLE sign_ins ADD COLUMN last_ip TEXT")   # the address a link was last used from
        if "from_default" not in {r["name"] for r in self.db.q("PRAGMA table_info(name_history)")}:
            # A rename away from a name the Beach gave (the keeper's "Beach-keeper"): no "(was ...)".
            self.db.run("ALTER TABLE name_history ADD COLUMN from_default INTEGER NOT NULL DEFAULT 0")
        if "released_at" not in {r["name"] for r in self.db.q("PRAGMA table_info(name_history)")}:
            # The keeper ended this name's hold early (re-inviting the same person); the row stays as history.
            self.db.run("ALTER TABLE name_history ADD COLUMN released_at REAL")

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
        if not self.db.one("SELECT 1 FROM meta WHERE key = 'readingroom_seeded'"):
            # The Reading Room (10-18): a quiet room with a shelf of residents' books. Its name is the keeper's.
            from .library import READINGROOM
            self.db.run("INSERT OR IGNORE INTO zones (id, name, kind, books, created_at) VALUES (?, ?, 'chat', 1, ?)",
                        (READINGROOM, "The Reading Room", now))
            self.db.run("INSERT INTO meta VALUES ('readingroom_seeded', '1')")
        if not self.db.one("SELECT 1 FROM meta WHERE key = 'actions_seeded'"):
            for name, (targeted, variants) in DEFAULT_ACTIONS.items():
                self.db.run("INSERT OR IGNORE INTO action_templates VALUES (?, ?, ?)",
                            (name, int(targeted), json.dumps(variants)))
            self.db.run("INSERT INTO meta VALUES ('actions_seeded', '1')")
        for name in LATER_ACTIONS:
            key = f"action_seeded:{name}"
            if not self.db.one("SELECT 1 FROM meta WHERE key = ?", (key,)):
                targeted, variants = DEFAULT_ACTIONS[name]
                self.db.run("INSERT OR IGNORE INTO action_templates VALUES (?, ?, ?)",
                            (name, int(targeted), json.dumps(variants)))
                self.db.run("INSERT INTO meta VALUES (?, '1')", (key,))

    def ensure_admin(self, name: str = DEFAULT_NAMES[0]) -> str | None:
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
            if k in ("link_base", "visitor_link_base") and v is not None:
                if not isinstance(v, str) or not re.match(r"^https?://[^\s/?#]+/?$", v.strip()):
                    raise BeachError("invalid", f"{k} is an address like http://192.168.1.20:8765")
                v = v.strip().rstrip("/")
            if k in ("trusted_proxy", "visitor_kit") and not isinstance(v, bool):
                raise BeachError("invalid", f"{k} is true or false")
            if k in ("beach_name", "sandchat_name"):
                v = self._display_name(v)
            if k.endswith("_s") and (not isinstance(v, (int, float)) or isinstance(v, bool) or v < 0):
                raise BeachError("invalid", f"{k} is a number of seconds, 0 or more")
            if k == "message_retention_days" and v is not None and (
                    not isinstance(v, int) or isinstance(v, bool) or v < 1):
                raise BeachError("invalid", "message_retention_days is a whole number of days (1 or more), "
                                            "or null to keep messages forever")
            if k == "https" and not isinstance(v, bool):
                raise BeachError("invalid", "https is true or false")
            if k == "badge_reset_hour" and (not isinstance(v, int) or isinstance(v, bool) or not 0 <= v <= 23):
                raise BeachError("invalid", "badge_reset_hour is an hour of the day, 0 to 23")
            if k == "badges_off":
                from .badges import BADGES
                if not isinstance(v, list) or any(b not in BADGES for b in v):
                    raise BeachError("invalid", f"badges_off is a list of badge ids: {', '.join(BADGES)}")
            if k == "https_port" and (not isinstance(v, int) or isinstance(v, bool) or not 1 <= v <= 65535):
                raise BeachError("invalid", "https_port is a port number")
            if k in ("https_cert", "https_key") and v is not None:
                v = str(v).strip() or None
                if v and not Path(v).expanduser().is_file():
                    raise BeachError("invalid", f"{k}: no such file: {v}")
            if k == "https_names":
                from .tls import check_name
                if not isinstance(v, list):
                    raise BeachError("invalid", "https_names is a list of host names or addresses")
                try:
                    v = [check_name(str(n)) for n in v if str(n).strip()]
                except ValueError as e:
                    raise BeachError("invalid", str(e)) from None
            self.db.run("INSERT OR REPLACE INTO settings VALUES (?, ?)", (k, json.dumps(v)))
            if k == "sandchat_name":
                self.db.run("UPDATE zones SET name = ? WHERE id = ?", (v, SANDCHAT))
        return self.settings()

    # ----------------------------------------------------------- participants

    def _p(self, row) -> Participant:
        keys = row.keys()
        removed = "removed_at" in keys and row["removed_at"] is not None
        return Participant(row["id"], row["former_name"] if removed else row["name"], row["kind"],
                           bool(row["is_admin"]), bool(row["invitable"]),
                           row["access"] if "access" in keys else "resident", removed,
                           row["sign_in"] if "sign_in" in keys else None)

    def check_name(self, name: str, pid: int | None = None) -> str:
        """A name that may be used: the right shape, and not mistakable for anyone else's name
        (or for a name someone gave up within rename_hint_s). Returns it tidied."""
        name = " ".join((name or "").split())
        if not identity.shape_ok(name):
            raise BeachError("invalid", identity.NAME_RULE)
        sk = identity.skeleton(name)
        for r in self.db.q("SELECT id, name FROM participants"):
            if r["id"] != pid and identity.skeleton(r["name"]) == sk:
                same = r["name"].casefold() == name.casefold()
                raise BeachError("conflict", f"there is already a participant called {r['name']}" if same else
                                 f"'{name}' is too easy to mistake for {r['name']}")
        for r in self.held_names():
            if r["participant_id"] != pid and identity.skeleton(r["name"]) == sk:
                raise BeachError("conflict", f"'{name}' was someone's name until recently; choose another")
        return name

    def held_names(self) -> list[dict]:
        """Names given up (by a rename or a removal) within rename_hint_s: nobody else may take them yet,
        so nobody can pose as that person in the history. The keeper can release one early."""
        recent = self.now() - self.setting("rename_hint_s")
        return [{"id": r["id"], "participant_id": r["participant_id"], "name": r["old_name"],
                 "since": r["at"], "until": r["at"] + self.setting("rename_hint_s"),
                 "removed": r["new_name"].endswith("(removed)")}
                for r in self.db.q("SELECT * FROM name_history WHERE at > ? AND from_default = 0"
                                   " AND released_at IS NULL ORDER BY id", (recent,))]

    def release_name(self, admin: Participant, name: str) -> dict:
        """Keeper only: end a held name's hold early (say, re-inviting the same person after removing an
        unclaimed slot). Recorded in the audit log; old messages keep their author, so the former holder
        and the new one stay apart in the history."""
        if not admin.is_admin:
            raise BeachError("forbidden", "only the keeper can release a held name")
        sk = identity.skeleton(" ".join((name or "").split()))
        rows = [r for r in self.held_names() if identity.skeleton(r["name"]) == sk]
        if not rows:
            raise BeachError("not_found", f"'{name}' isn't held")
        now = self.now()
        with self.db.tx() as db:
            for r in rows:
                db.conn.execute("UPDATE name_history SET released_at = ? WHERE id = ?", (now, r["id"]))
            db.conn.execute("INSERT INTO audit (at, admin_id, what, detail) VALUES (?, ?, 'release_name', ?)",
                            (now, admin.id, rows[0]["name"]))
        return {"released": rows[0]["name"]}

    def add_participant(self, name: str, kind: str, invitable: bool = True,
                        is_admin: bool = False) -> tuple[Participant, str]:
        if kind not in ("person", "agent"):
            raise BeachError("invalid", "kind must be 'person' or 'agent'")
        name = self.check_name(name)
        pid = self.db.run("INSERT INTO participants (name, kind, is_admin, invitable, created_at)"
                          " VALUES (?, ?, ?, ?, ?)", (name, kind, int(is_admin), int(invitable), self.now()))
        token = self.new_link(pid, "first link")["token"]
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
        """The keeper's list (former participants aren't on it)."""
        return [{"id": r["id"], "name": r["name"], "kind": r["kind"], "admin": bool(r["is_admin"]),
                 "access": r["access"], "status": self.access.status(r["id"]),
                 "invitable": bool(r["invitable"]), "has_token": self.is_active(r["id"]),
                 "links": self.db.one("SELECT COUNT(*) AS n FROM sign_ins WHERE participant_id = ?"
                                      " AND revoked_at IS NULL", (r["id"],))["n"],
                 "was": self.was_name(r["id"]), "avatar_v": self.avatar_version(r["id"])}
                for r in self.db.q("SELECT * FROM participants WHERE removed_at IS NULL ORDER BY id")]

    def authenticate(self, token: str | None, ip: str | None = None) -> Participant | None:
        if not token:
            return None
        row = self.db.one("SELECT p.*, s.id AS sign_in, s.last_used_at, s.last_ip FROM sign_ins s JOIN participants p"
                          " ON p.id = s.participant_id WHERE s.token_hash = ? AND s.revoked_at IS NULL"
                          " AND p.removed_at IS NULL", (_hash(token),))
        if not row:
            return None
        if row["access"] == "visitor" and not self.access.visit_allows(row["id"]):
            # The visit is over (or not yet on): end it now, rather than at the next upkeep.
            self.access.sweep()
            return None
        now = self.now()
        if row["last_used_at"] is None or now - row["last_used_at"] > 300 or (ip and ip != row["last_ip"]):
            self.db.run("UPDATE sign_ins SET last_used_at = ?, last_ip = COALESCE(?, last_ip) WHERE id = ?",
                        (now, ip, row["sign_in"]))
        return self._p(row)

    def is_active(self, pid: int) -> bool:
        """Has at least one sign-in link that still works."""
        return bool(self.db.one("SELECT 1 FROM sign_ins WHERE participant_id = ? AND revoked_at IS NULL",
                                (pid,)))

    # Sign-in links. A person may have several (a tablet, a phone), each revocable on its own.

    def new_link(self, pid: int, label: str = "link") -> dict:
        """A new sign-in link (token) for a participant; their other links keep working."""
        self.participant(pid)
        label = " ".join(str(label or "link").split())[:40] or "link"
        token = _new_token()
        lid = self.db.run("INSERT INTO sign_ins (participant_id, token_hash, label, created_at) VALUES (?, ?, ?, ?)",
                          (pid, _hash(token), label, self.now()))
        return {"id": lid, "label": label, "token": token}

    def links(self, pid: int) -> list[dict]:
        self.participant(pid)
        return [{"id": r["id"], "label": r["label"], "created_at": r["created_at"], "last_used_at": r["last_used_at"],
                 "last_ip": r["last_ip"], "active": r["revoked_at"] is None}
                for r in self.db.q("SELECT * FROM sign_ins WHERE participant_id = ? ORDER BY id", (pid,))]

    def revoke_link(self, pid: int, lid: int) -> None:
        """Cut off one link (a lost phone). If it was their last, they're signed out everywhere."""
        row = self.db.one("SELECT * FROM sign_ins WHERE id = ? AND participant_id = ?", (lid, pid))
        if not row:
            raise BeachError("not_found", "no such sign-in link")
        self.db.run("UPDATE sign_ins SET revoked_at = COALESCE(revoked_at, ?) WHERE id = ?", (self.now(), lid))
        if not self.is_active(pid):
            self._signed_out(pid)

    def revoke_token(self, pid: int) -> None:
        """Sign a participant out everywhere: every link stops working."""
        self.participant(pid)
        self.db.run("UPDATE sign_ins SET revoked_at = ? WHERE participant_id = ? AND revoked_at IS NULL",
                    (self.now(), pid))
        self._signed_out(pid)

    def _signed_out(self, pid: int) -> None:
        for z in self.db.q("SELECT zone_id FROM visits WHERE participant_id = ? AND left_at IS NULL", (pid,)):
            self.part(pid, z["zone_id"])

    def reissue_token(self, pid: int) -> str:
        """A fresh link after a sign-out (job 04's call; other active links are kept)."""
        return self.new_link(pid, "link")["token"]

    def update_participant(self, pid: int, invitable: bool | None = None, one_room: bool | None = None) -> Participant:
        self.participant(pid)
        if invitable is not None:
            self.db.run("UPDATE participants SET invitable = ? WHERE id = ?", (int(invitable), pid))
        if one_room is not None:
            if not isinstance(one_room, bool):
                raise BeachError("invalid", "one_room is true or false")
            self.db.run("UPDATE participants SET one_room = ? WHERE id = ?", (int(one_room), pid))
        return self.participant(pid)

    def one_room(self, pid: int) -> bool:
        """In one room at a time: going somewhere leaves where they were (a keeper's choice per
        participant; a suggestion for smaller models, which follow one place better than several)."""
        row = self.db.one("SELECT one_room FROM participants WHERE id = ?", (pid,))
        return bool(row and row["one_room"])

    def _leave_other_rooms(self, pid: int, keep: str) -> list[str]:
        """For a one-room participant arriving at `keep`: part every other zone, take their character
        out of any other world and stop watching it. A game they're seated at waits for them (leaving
        never forfeits). Returns the names of the places left."""
        if not self.one_room(pid):
            return []
        left = []
        for zid in self.zones_of(pid):
            if zid != keep:
                self.part(pid, zid)
                left.append(self.zone(zid)["name"])
        for z in self.db.q("SELECT id, name FROM zones WHERE kind = 'game' AND id != ?", (keep,)):
            gone = False
            if self._current_join(pid, z["id"]):
                self.leave_world(pid, z["id"])
                gone = True
            if self.stop_watching(pid, z["id"])["was_watching"]:
                gone = True
            if gone and z["name"] not in left:
                left.append(z["name"])
        return left

    # ------------------------------------------------------------------ names

    def _rename_wait(self, pid: int) -> float:
        row = self.db.one("SELECT at, by_admin FROM name_history WHERE participant_id = ? ORDER BY id DESC LIMIT 1",
                          (pid,))
        if not row or row["by_admin"]:
            return 0
        left = self.setting("rename_cooldown_s") - (self.now() - row["at"])
        return round(left, 1) if left > 0 else 0

    def rename(self, pid: int, new_name: str, by_admin: bool = False) -> dict:
        """Change a participant's name, everywhere, like IRC's /nick. Participants: first rename
        free, then once per rename_cooldown_s; the keeper can rename anyone at any time."""
        p = self.participant(pid)
        if p.access == "visitor" and not by_admin:
            raise BeachError("forbidden", "a visitor's name is the one the keeper gave the visit")
        new = self.check_name(new_name, pid)
        if new == p.name:
            raise BeachError("invalid", f"you're already called {new}")
        if not by_admin:
            wait = self._rename_wait(pid)
            if wait > 0:
                raise BeachError("cooldown", "names can change once per "
                                 f"{max(1, round(self.setting('rename_cooldown_s') / 3600))} h so everyone can keep "
                                 f"track; try again in about {math.ceil(wait / 3600)} h", retry_after=wait)
        now = self.now()
        self.db.run("UPDATE participants SET name = ? WHERE id = ?", (new, pid))
        from_default = p.name in DEFAULT_NAMES and not self.db.one(
            "SELECT 1 FROM name_history WHERE participant_id = ?", (pid,))
        self.db.run("INSERT INTO name_history (participant_id, old_name, new_name, at, by_admin, from_default)"
                    " VALUES (?, ?, ?, ?, ?, ?)", (pid, p.name, new, now, int(by_admin), int(from_default)))
        line = f"{p.name} is now known as {new}"
        zones = {SANDCHAT} | set(self.zones_of(pid))
        for zid in sorted(zones):
            self._post(zid, None, "nick", line)
        for t in self.db.q("SELECT DISTINCT t.id, t.zone_id FROM game_tables t"
                           " LEFT JOIN table_seats s ON s.table_id = t.id AND s.participant_id = ?"
                           " LEFT JOIN table_watchers w ON w.table_id = t.id AND w.participant_id = ?"
                           " WHERE t.status IN ('waiting', 'playing')"
                           " AND (s.participant_id IS NOT NULL OR w.participant_id IS NOT NULL)", (pid, pid)):
            self._post(t["zone_id"], None, "nick", line, table_id=t["id"])
        return {"id": pid, "name": new, "was": p.name, "next_rename_in": self._rename_wait(pid)}

    def was_name(self, pid: int) -> str | None:
        """The name this participant had until recently (within rename_hint_s), else None."""
        row = self.db.one("SELECT old_name, at FROM name_history WHERE participant_id = ? AND from_default = 0"
                          " AND released_at IS NULL ORDER BY id DESC LIMIT 1", (pid,))
        if row and self.now() - row["at"] < self.setting("rename_hint_s"):
            first = self.db.one("SELECT old_name FROM name_history WHERE participant_id = ? AND at > ?"
                                " AND from_default = 0 ORDER BY id LIMIT 1",
                                (pid, self.now() - self.setting("rename_hint_s")))
            return first["old_name"] if first else row["old_name"]
        return None

    def label(self, pid: int) -> str:
        """The name an agent sees: "Sandcastle Sam (was Sandy)" for a while after a rename."""
        p = self.participant(pid)
        was = self.was_name(pid)
        return f"{p.name} (was {was})" if was and was != p.name else p.name

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
        """Who is in a zone, for the map: participants present (chat), or the players a game's
        bridge reported (game). A game player is a participant only if the Beach vouched for
        their join (see vouch()); anyone else is a guest, shown under a guest label."""
        z = self.zone(zid)
        if z["kind"] == "chat":
            return [{"id": p.id, "name": p.name, "kind": p.kind, "v": self.avatar_version(p.id),
                     "badge": self.badges.shown(p.id)}
                    for p in self.present(zid)]
        out = []
        for key in self.players_in(zid):
            if key.startswith("p:"):
                p = self.participant(int(key[2:]))
                out.append({"id": p.id, "name": p.name, "kind": p.kind, "v": self.avatar_version(p.id),
                            "badge": self.badges.shown(p.id)})
            else:
                out.append({"id": None, "name": key, "kind": "guest", "v": 0})
        for p in self.watchers(zid):
            out.append({"id": p.id, "name": p.name, "kind": p.kind, "v": self.avatar_version(p.id),
                        "badge": self.badges.shown(p.id), "watching": True})
        return out

    def game_looks(self, zid: str) -> dict:
        """Current name -> look, for a game that draws each character in its participant's look: the
        colors as '#rrggbb' (hair, eyes, skin, outfit, trim), plus the hairstyle and accessory."""
        return {w["name"]: avatar_mod.game_look(self.avatar_record(w["id"]))
                for w in self.who_in(zid) if w["id"] is not None and not w.get("watching")}

    # ------------------------------------------------------- the front door to game worlds

    @staticmethod
    def user_id_for(agent_id: str) -> int:
        """The UserId a Clawblox world gives the player for a join (low 53 bits of its agent_id)."""
        import uuid
        uid = uuid.UUID(str(agent_id)).int & ((1 << 53) - 1)
        return uid or 1

    def vouch(self, pid: int, zid: str, agent_id: str, joined_as: str) -> dict:
        """A participant tells the Beach "this world join is me". The world admits the join only
        once the Beach has vouched for it, and only if it joined under the participant's Beach name."""
        z = self.zone(zid)
        if z["kind"] != "game":
            raise BeachError("invalid", "only game zones have worlds to join")
        if not z["open"]:
            raise BeachError("closed", f"{z['name']} is closed right now")
        p = self.participant(pid)
        try:
            uid = self.user_id_for(agent_id)
        except (ValueError, TypeError):
            raise BeachError("invalid", "agent_id is the id the world's /join returned") from None
        if joined_as != p.name:
            raise BeachError("invalid", f"join the world as {p.name}, exactly: your Beach name is your name there too")
        # Several participants may claim the same join; the world honors only the claim whose
        # name matches the name the join used, which only its rightful owner can make.
        # One character per participant per world: vouching for a new join retires any older one
        # (the world's door then removes it).
        with self.db.tx() as db:
            db.conn.execute("INSERT OR REPLACE INTO game_grants (agent_id, user_id, zone_id, participant_id,"
                            " joined_as, granted_at) VALUES (?, ?, ?, ?, ?, ?)",
                            (str(agent_id), uid, zid, pid, joined_as, self.now()))
            db.conn.execute("UPDATE game_grants SET left_at = ? WHERE participant_id = ? AND zone_id = ?"
                            " AND agent_id != ? AND left_at IS NULL", (self.now(), pid, zid, str(agent_id)))
        return {"zone": zid, "user_id": uid, "name": p.name}

    def set_watch_token(self, zid: str, token: str) -> None:
        self.db.run("UPDATE zones SET watch_token = ? WHERE id = ?", (token[:200], zid))

    def set_join_key(self, zid: str, key: str | None) -> None:
        self.db.run("UPDATE zones SET join_key = ? WHERE id = ?", ((key or "")[:200] or None, zid))

    def set_world_url(self, zid: str, url: str) -> None:
        from .front_door import local_world_url
        base = local_world_url(url)
        if base:
            self.db.run("UPDATE zones SET world_url = ? WHERE id = ?", (base, zid))

    def _play_lock(self, pid: int, zid: str) -> threading.Lock:
        with self._play_locks_guard:
            return self._play_locks.setdefault((pid, zid), threading.Lock())

    def _current_join(self, pid: int, zid: str):
        """The participant's character in this world, if they haven't left: their latest grant."""
        return self.db.one("SELECT * FROM game_grants WHERE participant_id = ? AND zone_id = ? AND left_at IS NULL"
                           " ORDER BY granted_at DESC LIMIT 1", (pid, zid))

    def play(self, pid: int, zid: str, joiner=None, alive=None, again: bool = False) -> dict:
        """Put a participant in a game world (a person from the map, or an agent through its
        adapter): one character per participant per world. If their character from an earlier
        play is still in the world, its session comes back ("existing": true); otherwise the Beach
        joins under their Beach name, with the world's join key if it has one, and vouches for the
        join. Returns the session, and a viewer link for people.
        `alive(world_url, session)` says whether a session is still in the world (default: ask it)."""
        from . import front_door
        z = self.zone(zid)
        if z["kind"] != "game":
            raise BeachError("invalid", "only game zones have worlds to play in")
        if not z["open"]:
            raise BeachError("closed", f"{z['name']} is closed right now")
        if not z["world_url"]:
            raise BeachError("conflict", f"{z['name']} isn't connected to the Beach yet (its bridge isn't running)")
        p = self.participant(pid)
        viewer = self.viewer_for(z, pid)

        def answer(session, agent_id, existing):
            return {"zone": zid, "name": p.name, "session": session, "agent_id": agent_id, "existing": existing,
                    "viewer": front_door.viewer_link(viewer, z["watch_token"], session, p.name)}
        # One at a time per participant and world, so a double click or two tabs can't both join.
        with self._play_lock(pid, zid):
            g = self._current_join(pid, zid)
            if g and g["session"]:
                if (alive or front_door.session_alive)(z["world_url"], g["session"]):
                    return answer(g["session"], g["agent_id"], True)
                # The world dropped the character (it restarted, or removed it) and the Beach
                # hadn't heard yet.
                self._removed_by_world(pid, zid, reason="removed", note=False)
            # Never a new character in silence: if the world removed your last one, say so first.
            # Asking again (or with again=True) then makes a new one.
            last = self.db.one("SELECT rowid, * FROM game_grants WHERE participant_id = ? AND zone_id = ?"
                               " ORDER BY granted_at DESC LIMIT 1", (pid, zid))
            if last and last["left_reason"] and not last["told"]:
                self.db.run("UPDATE game_grants SET told = 1 WHERE rowid = ?", (last["rowid"],))
                if not again:
                    raise BeachError("conflict", self._removed_text(zid, last["left_reason"]) +
                                     " Play again to come back as a new character.", data={"removed": last["left_reason"]})
            self.stop_watching(pid, zid)
            self._leave_other_rooms(pid, zid)
            if p.access == "visitor":
                self.access.saw(pid, zid)
            try:
                j = (joiner or front_door.join_world)(z["world_url"], p.name, z["join_key"])
            except Exception as e:  # the world is down, or refused
                raise BeachError("conflict", f"couldn't reach {z['name']} ({e})") from None
            self.vouch(pid, zid, j["agent_id"], p.name)     # also retires any older character
            self.db.run("UPDATE game_grants SET session = ? WHERE agent_id = ? AND participant_id = ?",
                        (j["session"], str(j["agent_id"]), pid))
            return answer(j["session"], j["agent_id"], False)

    def leave_world(self, pid: int, zid: str) -> dict:
        """Take a participant's character out of a game world. The Beach stops counting them at
        once; the world's door (BeachDoor) removes the character within a couple of seconds."""
        z = self.zone(zid)
        if z["kind"] != "game":
            raise BeachError("invalid", "only game zones have worlds to leave")
        with self._play_lock(pid, zid), self.db.tx() as db:
            n = db.conn.execute("UPDATE game_grants SET left_at = ? WHERE participant_id = ? AND zone_id = ?"
                                " AND left_at IS NULL", (self.now(), pid, zid)).rowcount
            db.conn.execute("DELETE FROM zone_players WHERE zone_id = ? AND name = ?", (zid, f"p:{pid}"))
        return {"zone": zid, "left": n > 0, "playing": False}

    # Watching: a visible spectator spot at the edge of the world. A watcher has no character
    # there (nothing to bump into, nothing to idle out); their name shows at the spot, the world
    # announces them, and agents in the world see who's watching. Nobody watches unseen.

    def watch_world(self, pid: int, zid: str) -> dict:
        """Start (or keep up) watching a game world. Playing there ends first: Play or Watch."""
        z = self.zone(zid)
        if z["kind"] != "game":
            raise BeachError("invalid", "only game zones have worlds to watch")
        if not z["open"]:
            raise BeachError("closed", f"{z['name']} is closed right now")
        if self._current_join(pid, zid):
            self.leave_world(pid, zid)
        if not self.watching(pid, zid):
            self._leave_other_rooms(pid, zid)   # a watch refreshes every few minutes: tidy only on arrival
        now = self.now()
        self.db.run("INSERT INTO world_watchers VALUES (?, ?, ?, ?) ON CONFLICT (zone_id, participant_id)"
                    " DO UPDATE SET seen_at = excluded.seen_at", (zid, pid, now, now))
        me = self.participant(pid)
        if me.kind == "person":
            self.db.run("UPDATE zones SET people_seen_at = ? WHERE id = ?", (now, zid))
        if me.access == "visitor":
            self.access.saw(pid, zid)
        from . import front_door
        viewer = self.viewer_for(z, pid)
        return {"zone": zid, "watching": True, "playing": False, "lasts_s": WATCH_TTL_S,
                "viewer": front_door.watch_link(viewer, z["watch_token"]) if viewer else None}

    def stop_watching(self, pid: int, zid: str) -> dict:
        n = self.db.run_count("DELETE FROM world_watchers WHERE zone_id = ? AND participant_id = ?", (zid, pid))
        return {"zone": zid, "watching": False, "was_watching": n > 0}

    def watchers(self, zid: str) -> list[Participant]:
        """Who is watching this world now (a watch fades WATCH_TTL_S after its last refresh)."""
        rows = self.db.q("SELECT p.* FROM world_watchers w JOIN participants p ON p.id = w.participant_id"
                         " WHERE w.zone_id = ? AND w.seen_at > ? ORDER BY w.since",
                         (zid, self.now() - WATCH_TTL_S))
        return [self._p(r) for r in rows if self.is_active(r["id"])]

    def watching(self, pid: int, zid: str) -> bool:
        return any(p.id == pid for p in self.watchers(zid))

    def _removed_text(self, zid: str, reason: str) -> str:
        z = self.zone(zid)
        if reason == "idle" and z["afk_timeout_s"]:
            return (f"You were idle {duration(z['afk_timeout_s'])} in {z['name']}, so the world took your "
                    "character out (its idle limit).")
        return f"Your character is no longer in {z['name']} (the world removed it, or restarted)."

    def _removed_by_world(self, pid: int, zid: str, reason: str | None = None, note: bool = True) -> None:
        """The world removed this participant's character (they didn't leave): record why, and
        tell them (a private note; the next Play says it too). Gone between two reports of the
        same run of a world with an idle limit: that limit is why (the Beach removes nobody else
        without its own say: Leave and sign-outs are already recorded)."""
        z = self.zone(zid)
        reason = reason or ("idle" if z["afk_timeout_s"] else "removed")
        n = self.db.run_count("UPDATE game_grants SET left_at = ?, left_reason = ? WHERE participant_id = ?"
                              " AND zone_id = ? AND left_at IS NULL", (self.now(), reason, pid, zid))
        self.db.run("DELETE FROM zone_players WHERE zone_id = ? AND name = ?", (zid, f"p:{pid}"))
        if n and note:
            self._note(pid, self._removed_text(zid, reason) + " Play again any time.", kind="event",
                       data={"event": "world_removed", "zone": zid, "reason": reason})

    def playing(self, pid: int, zid: str) -> bool:
        """Has this participant a character in this world now? (What the map's Play/Leave button
        shows.) Yes if they haven't left and the world's bridge still reports them, or they only
        just joined (the next report may not have them yet). After a world restart their old
        character is gone from the reports, so this turns false and the button says Play again."""
        g = self._current_join(pid, zid)
        if not g:
            return False
        if self.now() - g["granted_at"] < 20:
            return True
        return f"p:{pid}" in self.players_in(zid)

    def viewer_for(self, z, pid: int | None, fallback: bool = True) -> str | None:
        """A world's viewer as this participant reaches it. Visitors come from outside the household, so
        they get the keeper's visitor address for the world when there is one; everyone else gets the
        household one (with `fallback`, the world's own address when no viewer address is set)."""
        if pid is not None and z["visitor_viewer_url"] and self.participant(pid).access == "visitor":
            return z["visitor_viewer_url"]
        if z["viewer_url"] or not fallback:
            return z["viewer_url"]
        return z["world_url"] + "/" if z["world_url"] else None

    def world_info(self, zid: str, pid: int) -> dict:
        """For a participant: how to join this world as themselves, and a viewer link."""
        z = self.zone(zid)
        if z["kind"] != "game":
            raise BeachError("invalid", "only game zones have worlds")
        p = self.participant(pid)
        viewer = self.viewer_for(z, pid, fallback=False)
        base = viewer.split("?")[0].rstrip("/") if viewer else None
        steps = [f"POST /zones/{zid}/play (the Beach joins for you; use the session it returns)"]
        if not z["join_key"]:
            steps.append(f"or: POST {base or '<world>'}/join?name={p.name}, then POST /zones/{zid}/vouch "
                         f"{{\"agent_id\": <from the join>, \"name\": \"{p.name}\"}}")
        return {"zone": zid, "name": p.name, "open": bool(z["open"]), "world": base, "viewer_url": viewer,
                "spectator_token": z["watch_token"], "join_key_required": bool(z["join_key"]), "steps": steps}

    def door(self, zid: str) -> dict:
        """What a world's door needs (for its bridge): who the Beach vouched for, under their
        current names, and whether guests may stay. Revoked participants are listed as revoked."""
        self.zone(zid)
        keep = self.now() - 2 * 86400
        grants: dict[int, list] = {}
        for r in self.db.q("SELECT g.*, p.name, NOT EXISTS (SELECT 1 FROM sign_ins s WHERE s.participant_id = p.id"
                           " AND s.revoked_at IS NULL) AS signed_out FROM game_grants g JOIN participants p"
                           " ON p.id = g.participant_id WHERE g.zone_id = ? AND g.granted_at > ?"
                           " ORDER BY g.granted_at", (zid, keep)):
            grants.setdefault(r["user_id"], []).append(
                {"name": r["name"], "joined_as": r["joined_as"], "revoked": bool(r["signed_out"]),
                 "left": r["left_at"] is not None, "participant": r["participant_id"]})
        return {"zone": zid, "guests": bool(self.setting("game_guests")),
                "grants": [{"user_id": uid, "claims": claims} for uid, claims in grants.items()],
                "watchers": [p.name for p in self.watchers(zid)]}

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
                    viewer_url: str | None = None, card: str | None = None,
                    visitor_viewer_url: str | None = None):
        self.zone(zid)
        if visitor_viewer_url is not None:   # "" clears it (visitors then get the household viewer)
            v = visitor_viewer_url.strip()
            if v and not re.match(r"^https?://[^\s/?#]+(/[^\s?#]*)?$", v):
                raise BeachError("invalid", "visitor_viewer_url is an address like https://world.example.org/")
            self.db.run("UPDATE zones SET visitor_viewer_url = ? WHERE id = ?", (v or None, zid))
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

    def report_players(self, zid: str, players: list, world_up: bool | None = None, run: str | None = None,
                       afk_timeout_s: float | None = None) -> int:
        """Called by a game bridge: the full current list of who is playing. Each entry is
        {"user_id": n} for a join the Beach vouched for, or {"guest": "Guest 3"} (or a bare name,
        which counts as a guest: the Beach doesn't take a world's word for who someone is).

        A bridge that also says the world is up, which run of it this is, and its idle limit lets
        the Beach notice a character the world removed (a participant who was reported last time,
        in the same run, hasn't left, and is gone now): they're told, and their next Play says so."""
        z = self.zone(zid)
        if z["kind"] != "game":
            raise BeachError("invalid", "only game zones report players")
        now = self.now()
        if afk_timeout_s is not None:
            self.db.run("UPDATE zones SET afk_timeout_s = ? WHERE id = ?", (float(afk_timeout_s) or None, zid))
        same_run = bool(world_up) and run is not None and run == z["world_run"]
        before = set(self.players_in(zid)) if same_run else set()
        if world_up and run is not None:
            self.db.run("UPDATE zones SET world_run = ? WHERE id = ?", (str(run)[:100], zid))
        keys = set()
        for e in players:
            if isinstance(e, dict) and e.get("user_id") is not None:
                # A vouched join: the claim whose name matches the name the player joined under.
                # A character its participant has left (or replaced) isn't counted, even while
                # the world's door is still removing it.
                g = self.db.one("SELECT g.participant_id FROM game_grants g JOIN participants p"
                                " ON p.id = g.participant_id WHERE g.zone_id = ? AND g.user_id = ?"
                                " AND g.joined_as = ? AND g.left_at IS NULL",
                                (zid, int(e["user_id"]), str(e.get("joined_as", ""))))
                if g and self.is_active(g["participant_id"]):
                    keys.add(f"p:{g['participant_id']}")
            else:
                label = " ".join(str(e.get("guest") if isinstance(e, dict) else e).split())[:30]
                if not label:
                    continue
                if not label.lower().startswith("guest"):
                    # A guest never wears a participant's name, or anything mistakable for one.
                    sk = identity.skeleton(label)
                    taken = any(identity.skeleton(r["name"]) == sk for r in self.db.q("SELECT name FROM participants"))
                    label = "Guest" if taken else f"Guest {label}"
                n, base = 2, label
                while label in keys:
                    label, n = f"{base} {n}", n + 1
                keys.add(label)
        with self.db.tx() as db:
            db.conn.execute("DELETE FROM zone_players WHERE zone_id = ?", (zid,))
            for k in keys:
                db.conn.execute("INSERT INTO zone_players VALUES (?, ?, ?)", (zid, k, now))
        for k in before - keys:
            pid = int(k[2:]) if k.startswith("p:") else None
            if pid and self._current_join(pid, zid) and self.is_active(pid):
                self._removed_by_world(pid, zid)
        if any(k.startswith("p:") and self.participant(int(k[2:])).kind == "person" for k in keys):
            self.db.run("UPDATE zones SET people_seen_at = ? WHERE id = ?", (now, zid))
        return len(keys)

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
        left = self._leave_other_rooms(pid, zid)
        if not self.present(zid):
            self.db.run("UPDATE zones SET occupied_since = ? WHERE id = ?", (now, zid))
        self.db.run("INSERT INTO visits (participant_id, zone_id, joined_at, last_active) VALUES (?, ?, ?, ?)",
                    (pid, zid, now, now))
        if p.access == "visitor":
            self.access.saw(pid, zid)
        worn = self.badges.worn(pid)
        if worn:
            from .badges import words
            self._post(zid, None, "presence", f"{p.name} arrives, wearing today's {words(worn)}.")
        else:
            self._post(zid, None, "presence", f"{p.name} joined")
        self._answer_open_bells(pid, zid)
        out = {"zone": zid, "already_here": False, "arrival": self.arrival_line(pid)}
        if left:
            out["left"] = left   # one room at a time: where they were before
        return out

    def part(self, pid: int, zid: str, idle: bool = False) -> dict:
        """Leave a zone. Never fails and needs no reason."""
        v = self._visit(pid, zid)
        if not v:
            return {"zone": zid, "was_here": False}
        p = self.participant(pid)
        self._post(zid, None, "presence", f"{p.name} drifted off" if idle else f"{p.name} left")
        self.db.run("UPDATE visits SET left_at = ? WHERE id = ?", (self.now(), v["id"]))
        self.db.run("DELETE FROM held_lines WHERE author_id = ? AND zone_id = ?", (pid, zid))   # unsaid now
        if not self.present(zid):
            self.db.run("UPDATE zones SET occupied_since = NULL WHERE id = ?", (zid,))
        return {"zone": zid, "was_here": True}

    def touch(self, pid: int, zid: str) -> None:
        self.db.run("UPDATE visits SET last_active = ? WHERE participant_id = ? AND zone_id = ? AND left_at IS NULL",
                    (self.now(), pid, zid))

    def sweep_idle(self) -> int:
        """Idle auto-leave: anyone inactive in a zone for idle_timeout_s leaves it, and is told
        (a private note: on their pages, and in an agent's next turn)."""
        limit = self.setting("idle_timeout_s")
        rows = self.db.q("SELECT participant_id, zone_id FROM visits WHERE left_at IS NULL AND last_active < ?",
                         (self.now() - limit,))
        for r in rows:
            self.part(r["participant_id"], r["zone_id"], idle=True)
            self._note(r["participant_id"], f"You were away {duration(limit)} and left {self.zone(r['zone_id'])['name']}.",
                       kind="event", data={"event": "idle_left", "zone": r["zone_id"]})
        return len(rows)

    # ------------------------------------------------------------- messages

    def _post(self, zid: str, author: int | None, kind: str, text: str, action_key: str | None = None,
              table_id: int | None = None, actor: int | None = None) -> int:
        """`actor`: for a Beach notice, who caused it (it stays authorless; their own feed skips it)."""
        now = self.now()
        with self.db.tx() as db:
            name = None
            if author is not None:
                name = db.conn.execute("SELECT name FROM participants WHERE id = ?", (author,)).fetchone()[0]
            mid = db.conn.execute("INSERT INTO messages (zone_id, author_id, kind, text, created_at, action_key,"
                                  " table_id, author_name, actor_id) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                                  (zid, author, kind, text, now, action_key, table_id, name, actor)).lastrowid
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
        if self.zone(zid)["books"] and table_id is None:
            # The Reading Room is quiet: no chat, only its book commands, answered to you alone.
            self._require_present(pid, zid)
            answer = self.library.command(pid, text)
            if answer is None:
                raise BeachError("invalid", f"{self.zone(zid)['name']} is a quiet room, with no chat: "
                                            "/unreadbooks, /readbooks, /allbooks, /open <n> [page <p>]")
            self.touch(pid, zid)
            return {"posted": False, "private": True, "answer": answer}
        p = self.participant(pid)
        self._no_zone_chat(zid, table_id)
        self._require_present(pid, zid)
        self._rate_check(p, zid)
        held = self._pace_or_hold(pid, zid, table_id, "say", text)
        if held:
            return held
        mid = self._post(zid, pid, "say", text, table_id=table_id)
        self.touch(pid, zid)
        if zid == SANDCHAT and table_id is None:
            self.badges.award(pid, "hello")
        out = {"posted": True, "id": mid}
        if len(text) > LONG_LINE_CHARS:   # posted anyway; a gentle nudge, never a cut mid-thought
            out["tip"] = "shorter lines are easier to follow: 1-2 sentences"
        return out

    def _pace_or_hold(self, pid: int, zid: str, table_id: int | None, kind: str, text: str,
                      key: str | None = None) -> dict | None:
        """The chat pacer: None if this line may post now; else it's held to post on its turn (the
        answer says when), or refused when too many already wait. Never dropped silently."""
        step = self.setting("chat_pace_s")
        if not step:
            return None
        ahead = self.setting("chat_pace_ahead_s") or 0
        now = self.now()
        place = (pid, zid, table_id)
        with self._pace_lock:
            t = max(self._pace.get(place, now), now)
            post_at = max(now, t - ahead)
            if post_at <= now:
                self._pace[place] = t + step
                return None
            waiting = self.db.one("SELECT COUNT(*) AS n FROM held_lines WHERE author_id = ? AND zone_id = ?"
                                  " AND table_id IS ?", (pid, zid, table_id))["n"]
            if waiting >= (self.setting("chat_pace_held") or 0):
                raise BeachError("rate_limited", f"slow down so everyone can keep up: {waiting} of your lines are "
                                 "already waiting to post", retry_after=round(post_at - now, 1))
            self._pace[place] = t + step
            self.db.run("INSERT INTO held_lines (author_id, zone_id, table_id, kind, text, action_key, post_at)"
                        " VALUES (?, ?, ?, ?, ?, ?, ?)", (pid, zid, table_id, kind, text, key, post_at))
        wait = int(post_at - now + 0.999)
        return {"posted": False, "queued": True, "posts_in": wait,
                "note": f"chat is paced so everyone can keep up: this posts by itself in about {wait}s"}

    def post_held(self) -> int:
        """Post the paced lines whose turn has come (upkeep calls this). A line whose author has left,
        or whose zone has closed, is dropped."""
        rows = self.db.q("SELECT * FROM held_lines WHERE post_at <= ? ORDER BY post_at, id", (self.now(),))
        posted = 0
        for r in rows:
            self.db.run("DELETE FROM held_lines WHERE id = ?", (r["id"],))
            if not self._visit(r["author_id"], r["zone_id"]) or not self.zone(r["zone_id"])["open"]:
                continue
            self._post(r["zone_id"], r["author_id"], r["kind"], r["text"], action_key=r["action_key"],
                       table_id=r["table_id"])
            self.touch(r["author_id"], r["zone_id"])
            posted += 1
        now = self.now()
        with self._pace_lock:
            for k in [k for k, t in self._pace.items() if t < now]:
                del self._pace[k]
        return posted

    def _no_zone_chat(self, zid: str, table_id: int | None) -> None:
        """A zone with game tables (the Boardwalk) has no zone-wide chat: talk happens at a table.
        One group chat at a time is plenty, for people and for a small model."""
        z = self.zone(zid)
        if z["books"]:
            raise BeachError("invalid", f"{z['name']} is a quiet room, with no chat: "
                                        "/unreadbooks, /readbooks, /allbooks, /open <n> [page <p>]")
        if z["tables"] and table_id is None:
            raise BeachError("invalid", f"{z['name']} has no zone-wide chat: talk at a table "
                                        f"(POST /tables/<id>/say), or in {self.zone(SANDCHAT)['name']}")

    def read(self, pid: int, zid: str, after: int = 0, limit: int | None = None,
             all_visits: bool = False, table_id: int | None = None) -> list[dict]:
        """Messages this participant was present for, oldest first.

        By default only the current visit (from arrival on). With all_visits,
        also earlier visits - but never anything posted while they were away.
        """
        v = self._visit(pid, zid)
        if not v and not all_visits:
            return []
        sql = ("SELECT m.id, m.kind, m.text, m.created_at, m.author_id, COALESCE(m.author_name, p.former_name, p.name)"
               " AS author, COALESCE(p.former_name, p.name) AS author_now, p.kind AS author_kind,"
               " p.removed_at IS NOT NULL AS author_former"
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

    def sweep_retention(self) -> int:
        """Remove messages older than message_retention_days, the way an admin delete removes one
        (the text is gone from the database file and its write-ahead log), and forget who was
        present for them. One audit row says what was removed; the audit trail itself is kept.
        Returns how many messages were removed."""
        days = self.setting("message_retention_days")
        if not days:
            return 0
        cutoff = self.now() - days * 86400
        with self.db.tx() as db:
            row = db.conn.execute("SELECT COUNT(*), MAX(id) FROM messages WHERE created_at < ? AND deleted = 0",
                                  (cutoff,)).fetchone()
            n, last = row[0], row[1]
            db.conn.execute("UPDATE messages SET text = NULL, deleted = 1 WHERE created_at < ? AND deleted = 0",
                            (cutoff,))
            db.conn.execute("DELETE FROM witnesses WHERE message_id IN (SELECT id FROM messages WHERE created_at < ?)",
                            (cutoff,))
            if n:
                db.conn.execute("INSERT INTO audit (at, admin_id, what, message_id, detail) VALUES (?, 0, 'retention', ?, ?)",
                                (self.now(), last, f"removed {n} message{'s' if n != 1 else ''} older than {days} days"))
        if n:
            self.db.checkpoint()
        return n

    def audit(self) -> list[dict]:
        return [dict(r) for r in self.db.q(
            "SELECT a.id, a.at, a.what, a.message_id, a.detail, COALESCE(p.name, 'the Beach') AS admin FROM audit a"
            " LEFT JOIN participants p ON p.id = a.admin_id ORDER BY a.id")]

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
        self._no_zone_chat(zid, table_id)
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
        # Who the action is aimed at: the shorthand's target, or anyone present a free-form /me
        # names (with @, or by their plain name; see identity.names_in).
        targets = [target] if target is not None else []
        if key == "me":
            others = [q for q in self.present(zid) if q.id != p.id]
            targets = identity.names_in(body, others)
        # Targeted-action opt-out: nothing is posted, the sender gets a short private note.
        for t in targets:
            if self._opted_out(t.id, zid, key):
                note = f"{t.name} isn't taking actions right now"
                self._note(pid, note)
                return {"posted": False, "note": note}
        # Flood control: a cooldown per action (a named shorthand, or the same free-form /me text repeated:
        # two different free-form actions are just conversation), and a limit on actions in a row.
        cooldown = self.setting("action_cooldown_s")
        if key == "me":
            last = self.db.one("SELECT created_at FROM messages WHERE author_id = ? AND zone_id = ? AND kind = 'action'"
                               " AND action_key = 'me' AND text = ? ORDER BY id DESC LIMIT 1", (pid, zid, text))
        else:
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
        held = self._pace_or_hold(pid, zid, table_id, "action", text, key)
        if held:
            return dict(held, text=text)
        mid = self._post(zid, pid, "action", text, action_key=key, table_id=table_id)
        self.touch(pid, zid)
        if zid == SANDCHAT and table_id is None:
            self.badges.award(pid, "hello")
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
        """Ring the Gather Bell in SandChat: an invitation, not a summons."""
        p = self.participant(pid)
        if not self.access.may_ring(pid):
            raise BeachError("forbidden", "visitors don't ring the Gather Bell (it reaches the household's devices)"
                                          " unless the keeper allows it for the visit")
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
        self._post(SANDCHAT, pid, "bell", f"{p.name} rang the Gather Bell")
        here = {x.id for x in self.present(SANDCHAT)}
        invitees = [r for r in self.db.q("SELECT * FROM participants p WHERE invitable = 1 AND EXISTS (SELECT 1 FROM sign_ins s"
                                       " WHERE s.participant_id = p.id AND s.revoked_at IS NULL)")
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
            self.badges.award(b["ringer_id"], "bell")

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
                           " ON b.id = o.bell_id WHERE o.status = 'queued' AND (o.next_try_at IS NULL"
                           " OR o.next_try_at <= ?) ORDER BY o.id", (now,)):
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
            attempts = o["attempts"] + 1
            if ok:
                self.db.run("UPDATE outbox SET status = 'sent', attempts = ?, done_at = ? WHERE id = ?",
                            (attempts, self.now(), o["id"]))
                counts["sent"] += 1
                continue
            # Failed: try again a little later, but only if that's still within the bell's life.
            # A late invitation is worse than none.
            retry_at = self.now() + self.setting("bell_retry_s") * 3 ** (attempts - 1)
            if attempts <= self.setting("bell_retries") and retry_at < o["closes_at"]:
                self.db.run("UPDATE outbox SET attempts = ?, next_try_at = ? WHERE id = ?",
                            (attempts, retry_at, o["id"]))
                counts["retrying"] = counts.get("retrying", 0) + 1
            else:
                self.db.run("UPDATE outbox SET status = 'failed', attempts = ?, done_at = ? WHERE id = ?",
                            (attempts, self.now(), o["id"]))
                counts["failed"] += 1
        return counts

    def bell_invites(self, pid: int) -> list[dict]:
        """A participant's own invitations (including their own declines), newest first."""
        now = self.now()
        return [{**dict(r), "open": r["bell_status"] == "open" and r["closes_at"] > now} for r in self.db.q(
            "SELECT i.bell_id, i.status, i.responded_at, b.rung_at, b.closes_at, b.status AS bell_status, b.zone_id AS zone,"
            " p.name AS rung_by, p.access AS rung_by_access FROM invites i"
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
            watching = 0
            if z["kind"] == "chat":
                here = len(self.present(z["id"]))
            else:
                here = len(self.players_in(z["id"]))
                watching = len(self.watchers(z["id"]))
            out.append({"id": z["id"], "name": z["name"], "kind": z["kind"], "open": bool(z["open"]),
                        "here": here, "watching": watching, "viewer_url": z["viewer_url"],
                        "visitor_viewer_url": z["visitor_viewer_url"], "sky": z["sky"],
                        "created_at": z["created_at"], "tables": bool(z["tables"]), "books": bool(z["books"]),
                        "connected": bool(z["world_url"]), "idle_limit_s": z["afk_timeout_s"]})
        return out

    def zone_map_text(self) -> str:
        parts = []
        for z in self.zone_map():
            if not z["open"]:
                parts.append(f"{z['name']}: closed")
            elif z["kind"] == "chat":
                kind = " (game tables)" if z["tables"] else (" (a quiet room with books)" if z["books"] else "")
                parts.append(f"{z['name']}{kind}: {z['here']} here")
            else:
                parts.append(f"{z['name']} (game): {z['here']} playing"
                             + (f", {z['watching']} watching" if z["watching"] else ""))
        return "zones: " + "; ".join(parts)

    def arrival_line(self, pid: int | None = None) -> str:
        """What you notice arriving in SandChat. Mentions zones only, never conversations."""
        others = [x for x in self.present(SANDCHAT) if x.id != pid]
        if others:
            return ""
        busy = [z["name"] for z in self.zone_map() if z["id"] != SANDCHAT and z["open"]
                and any(w["id"] != pid for w in self.who_in(z["id"]))]
        if busy:
            return self.setting("quiet_with_play").format(zones=" and ".join(busy))
        return self.setting("quiet")

    # ------------------------------------------------------- ambient facts

    def ambient_facts(self, zid: str = SANDCHAT) -> list[str]:
        """Honest facts an agent may weigh. Cues, not limits."""
        now = self.now()
        facts = []
        z = self.zone(zid)
        if z["kind"] == "game":   # people in a world: playing or watching there (the bridge reports them)
            people = [w for w in self.who_in(zid) if w["kind"] == "person"]
        else:
            people = [x for x in self.present(zid) if x.kind == "person"]
        if not people:
            last = self.db.one("SELECT MAX(v.left_at) AS t FROM visits v JOIN participants p ON p.id = v.participant_id"
                               " WHERE v.zone_id = ? AND p.kind = 'person'", (zid,))["t"]
            if z["kind"] == "game" and z["people_seen_at"] is not None:
                last = max(last or 0, z["people_seen_at"])
            if last is None:
                facts.append("no people have been here yet")
            else:
                facts.append(f"no people have been here for {int((now - last) // 60)} minutes")
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
        """Periodic upkeep: idle auto-leave, closing bells, handing notices to the hook, and (every
        10 minutes) removing messages past their retention."""
        self.post_held()
        self.sweep_idle()
        self.access.sweep()
        self.deliver_notices()
        self.tables.sweep()
        self.badges.purge()
        if self.now() - getattr(self, "_retention_at", float("-inf")) >= 600:
            self._retention_at = self.now()
            self.sweep_retention()
