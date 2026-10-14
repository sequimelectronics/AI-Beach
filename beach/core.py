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
from . import identity
from .db import Database

SANDCHAT = "sandchat"
BOARDWALK = "boardwalk"
SKIES = ("dawn", "morning", "midday", "afternoon", "sunset", "night")
NAME_RE = identity.NAME_RE
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
    "rename_cooldown_s": 86400,      # how often a participant may rename themselves (first rename free)
    "rename_hint_s": 86400,          # for this long, agents see "New (was Old)", and Old stays reserved
    "game_guests": False,
    "bell_retries": 2,               # retries for a failed bell notice, only while the bell is open
    "bell_retry_s": 10,              # first retry after this; each later one waits 3x longer            # game worlds admit players the Beach didn't vouch for (as guests)
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
        if "card" not in cols:
            self.db.run("ALTER TABLE zones ADD COLUMN card TEXT")   # a game zone's own card (keeper-set)
        if "world_url" not in cols:   # a game world's address on this machine, from its bridge
            self.db.run("ALTER TABLE zones ADD COLUMN world_url TEXT")
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
        recent = self.now() - self.setting("rename_hint_s")
        for r in self.db.q("SELECT participant_id, old_name FROM name_history WHERE at > ?", (recent,)):
            if r["participant_id"] != pid and identity.skeleton(r["old_name"]) == sk:
                raise BeachError("conflict", f"'{name}' was someone's name until recently; choose another")
        return name

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
        return [{"id": r["id"], "name": r["name"], "kind": r["kind"], "admin": bool(r["is_admin"]),
                 "invitable": bool(r["invitable"]), "has_token": self.is_active(r["id"]),
                 "links": self.db.one("SELECT COUNT(*) AS n FROM sign_ins WHERE participant_id = ?"
                                      " AND revoked_at IS NULL", (r["id"],))["n"],
                 "was": self.was_name(r["id"]), "avatar_v": self.avatar_version(r["id"])}
                for r in self.db.q("SELECT * FROM participants ORDER BY id")]

    def authenticate(self, token: str | None) -> Participant | None:
        if not token:
            return None
        row = self.db.one("SELECT p.*, s.id AS sign_in, s.last_used_at FROM sign_ins s JOIN participants p"
                          " ON p.id = s.participant_id WHERE s.token_hash = ? AND s.revoked_at IS NULL",
                          (_hash(token),))
        if not row:
            return None
        now = self.now()
        if row["last_used_at"] is None or now - row["last_used_at"] > 300:   # don't write on every request
            self.db.run("UPDATE sign_ins SET last_used_at = ? WHERE id = ?", (now, row["sign_in"]))
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
                 "active": r["revoked_at"] is None}
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

    def update_participant(self, pid: int, invitable: bool | None = None) -> Participant:
        self.participant(pid)
        if invitable is not None:
            self.db.run("UPDATE participants SET invitable = ? WHERE id = ?", (int(invitable), pid))
        return self.participant(pid)

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
        self.db.run("INSERT INTO name_history (participant_id, old_name, new_name, at, by_admin) VALUES (?, ?, ?, ?, ?)",
                    (pid, p.name, new, now, int(by_admin)))
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
        row = self.db.one("SELECT old_name, at FROM name_history WHERE participant_id = ? ORDER BY id DESC LIMIT 1",
                          (pid,))
        if row and self.now() - row["at"] < self.setting("rename_hint_s"):
            first = self.db.one("SELECT old_name FROM name_history WHERE participant_id = ? AND at > ?"
                                " ORDER BY id LIMIT 1", (pid, self.now() - self.setting("rename_hint_s")))
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
            return [{"id": p.id, "name": p.name, "kind": p.kind, "v": self.avatar_version(p.id)}
                    for p in self.present(zid)]
        out = []
        for key in self.players_in(zid):
            if key.startswith("p:"):
                p = self.participant(int(key[2:]))
                out.append({"id": p.id, "name": p.name, "kind": p.kind, "v": self.avatar_version(p.id)})
            else:
                out.append({"id": None, "name": key, "kind": "guest", "v": 0})
        return out

    def game_looks(self, zid: str) -> dict:
        """Current name -> colours, for a game that tints characters with their owner's look."""
        return {w["name"]: avatar_mod.hexes(self.avatar_record(w["id"]))
                for w in self.who_in(zid) if w["id"] is not None}

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
        # Several participants may claim the same join; the world honours only the claim whose
        # name matches the name the join used, which only its rightful owner can make.
        self.db.run("INSERT OR REPLACE INTO game_grants VALUES (?, ?, ?, ?, ?, ?)",
                    (str(agent_id), uid, zid, pid, joined_as, self.now()))
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

    def play(self, pid: int, zid: str, joiner=None) -> dict:
        """Join a game world for a participant (a person from the map, or an agent through its
        adapter): the Beach joins under their Beach name, with the world's join key if it has
        one, and vouches for the join. Returns the session, and a viewer link for people."""
        from . import front_door
        z = self.zone(zid)
        if z["kind"] != "game":
            raise BeachError("invalid", "only game zones have worlds to play in")
        if not z["open"]:
            raise BeachError("closed", f"{z['name']} is closed right now")
        if not z["world_url"]:
            raise BeachError("conflict", f"{z['name']} isn't connected to the Beach yet (its bridge isn't running)")
        p = self.participant(pid)
        try:
            j = (joiner or front_door.join_world)(z["world_url"], p.name, z["join_key"])
        except Exception as e:  # the world is down, or refused
            raise BeachError("conflict", f"couldn't reach {z['name']} ({e})") from None
        self.vouch(pid, zid, j["agent_id"], p.name)
        viewer = z["viewer_url"] or z["world_url"] + "/"
        return {"zone": zid, "name": p.name, "session": j["session"], "agent_id": j["agent_id"],
                "viewer": front_door.viewer_link(viewer, z["watch_token"], j["session"], p.name)}

    def world_info(self, zid: str, pid: int) -> dict:
        """For a participant: how to join this world as themselves, and a viewer link."""
        z = self.zone(zid)
        if z["kind"] != "game":
            raise BeachError("invalid", "only game zones have worlds")
        p = self.participant(pid)
        viewer = z["viewer_url"]
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
                 "participant": r["participant_id"]})
        return {"zone": zid, "guests": bool(self.setting("game_guests")),
                "grants": [{"user_id": uid, "claims": claims} for uid, claims in grants.items()]}

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

    def report_players(self, zid: str, players: list) -> int:
        """Called by a game bridge: the full current list of who is playing. Each entry is
        {"user_id": n} for a join the Beach vouched for, or {"guest": "Guest 3"} (or a bare name,
        which counts as a guest: the Beach doesn't take a world's word for who someone is)."""
        if self.zone(zid)["kind"] != "game":
            raise BeachError("invalid", "only game zones report players")
        now = self.now()
        keys = set()
        for e in players:
            if isinstance(e, dict) and e.get("user_id") is not None:
                # A vouched join: the claim whose name matches the name the player joined under.
                g = self.db.one("SELECT g.participant_id FROM game_grants g JOIN participants p"
                                " ON p.id = g.participant_id WHERE g.zone_id = ? AND g.user_id = ?"
                                " AND g.joined_as = ?", (zid, int(e["user_id"]), str(e.get("joined_as", ""))))
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
            name = None
            if author is not None:
                name = db.conn.execute("SELECT name FROM participants WHERE id = ?", (author,)).fetchone()[0]
            mid = db.conn.execute("INSERT INTO messages (zone_id, author_id, kind, text, created_at, action_key,"
                                  " table_id, author_name) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                                  (zid, author, kind, text, now, action_key, table_id, name)).lastrowid
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
        sql = ("SELECT m.id, m.kind, m.text, m.created_at, m.author_id, COALESCE(m.author_name, p.name) AS author,"
               " p.name AS author_now, p.kind AS author_kind"
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
