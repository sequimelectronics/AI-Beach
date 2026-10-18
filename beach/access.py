# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Becky Northaven and the AI-Beach contributors
"""Who can get in: residents and visitors, invites that must be claimed, and the keeper's controls.

- **Residents** are the household's regular members, people or AIs. Each device has its own
  sign-in link, revocable on its own; it lasts until revoked.
- **Visitors** come for an event or a one-time visit. Their access belongs to a **visit** with a
  window (start, end). When the window ends, or the keeper presses End visit, every credential
  the visit made stops working at once, their world characters leave, and they leave every zone.
  Nothing outlives the visit that the visitor's operator could keep, reuse or pass on.
- **Invites.** Nobody gets a working link by being added. The keeper makes an invite: a one-time
  code (or a link carrying it) handed over by any means. The first claim uses it up and becomes
  that device's own sign-in link. A resident's invite expires unclaimed after the keeper's chosen
  time and can be re-sent; a visitor's can be claimed only inside the visit's window. One
  mechanism for both.
- **Kick** signs out every device, parts every zone and removes world characters; the
  participant stays on the list and can come back with a new invite. **Remove** does that and
  takes them off the list: their past messages stay under their name, marked as a former
  participant, and the name stays held for a day.

The Beach keeps no copy of a code or token, only hashes (like every token).
"""

from __future__ import annotations

import hashlib
import json
import secrets
from typing import TYPE_CHECKING

from . import identity

if TYPE_CHECKING:
    from .core import Beach

# Codes are easy to read aloud and type: no 0/O, 1/I/L. Four groups of four: about 80 bits.
CODE_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"
MAX_INVITE_S = 30 * 86400          # an unclaimed resident invite lasts at most 30 days
MAX_VISIT_S = 14 * 86400           # a visit lasts at most two weeks


def new_code() -> str:
    raw = "".join(secrets.choice(CODE_ALPHABET) for _ in range(16))
    return "-".join(raw[i:i + 4] for i in range(0, 16, 4))


def code_key(code: str) -> str:
    """The code as stored (hashed): case, spaces and dashes don't matter when it's typed back."""
    clean = "".join(c for c in str(code or "").upper() if c.isalnum())
    return hashlib.sha256(("invite:" + clean).encode()).hexdigest()


class Access:
    def __init__(self, beach: "Beach"):
        self.beach = beach
        self.db = beach.db

    def _err(self, code: str, msg: str, **kw):
        from .core import BeachError
        return BeachError(code, msg, **kw)

    # ------------------------------------------------------------------ names

    def free_name(self, name: str) -> str | None:
        """A name close to `name` that nobody has or recently had (for a refused name)."""
        base = " ".join((name or "").split())[:21] or "Guest"
        if not identity.shape_ok(base):
            base = "Visitor"
        for n in range(2, 100):
            candidate = f"{base} {n}"
            try:
                return self.beach.check_name(candidate)
            except Exception:
                continue
        return None

    def check_new_name(self, name: str) -> str:
        """check_name, with a free name suggested when it's refused."""
        from .core import BeachError
        try:
            return self.beach.check_name(name)
        except BeachError as e:
            suggestion = self.free_name(name) if e.code == "conflict" else None
            if suggestion:
                raise BeachError(e.code, f"{e.message}; {suggestion} is free", data={"suggestion": suggestion}) from None
            raise

    # ------------------------------------------------------------------ invites

    def _new_invite(self, pid: int, label: str, expires_at: float) -> dict:
        code = new_code()
        label = " ".join(str(label or "first device").split())[:40] or "first device"
        iid = self.db.run("INSERT INTO access_invites (participant_id, code_hash, label, created_at, expires_at)"
                          " VALUES (?, ?, ?, ?, ?)", (pid, code_key(code), label, self.beach.now(), expires_at))
        return {"id": iid, "code": code, "label": label, "expires_at": expires_at}

    def invite_resident(self, name: str, kind: str, expires_in_s: float = 7 * 86400) -> dict:
        """Add a resident as an invite: the slot shows "invited, not claimed" until the code is used."""
        if kind not in ("person", "agent"):
            raise self._err("invalid", "kind must be 'person' or 'agent'")
        expires_in_s = self._duration(expires_in_s, MAX_INVITE_S, "expires_in_s")
        name = self.check_new_name(name)
        pid = self.db.run("INSERT INTO participants (name, kind, is_admin, invitable, created_at, access)"
                          " VALUES (?, ?, 0, 1, ?, 'resident')", (name, kind, self.beach.now()))
        return {"participant": self.beach.participant(pid), "invite": self._new_invite(pid, "first device",
                                                                                         self.beach.now() + expires_in_s)}

    def invite_device(self, pid: int, label: str = "link", expires_in_s: float = 7 * 86400) -> dict:
        """Another device for a resident (or a re-sent invite): a new code; earlier unclaimed codes
        for that participant stop working."""
        p = self.beach.participant(pid)
        if self.removed(pid):
            raise self._err("not_found", "no such participant")
        if p.access == "visitor":
            v = self.visit_of(pid)
            if not v or v["ended_at"]:
                raise self._err("conflict", "that visit is over; make a new visitor invite")
            expires_at = v["ends_at"]
        else:
            expires_at = self.beach.now() + self._duration(expires_in_s, MAX_INVITE_S, "expires_in_s")
        self.db.run("UPDATE access_invites SET revoked_at = ? WHERE participant_id = ? AND claimed_at IS NULL"
                    " AND revoked_at IS NULL", (self.beach.now(), pid))
        return {"participant": p, "invite": self._new_invite(pid, label, expires_at)}

    def invites(self, pid: int) -> list[dict]:
        now = self.beach.now()
        out = []
        for r in self.db.q("SELECT * FROM access_invites WHERE participant_id = ? ORDER BY id", (pid,)):
            state = ("claimed" if r["claimed_at"] else "withdrawn" if r["revoked_at"]
                     else "expired" if r["expires_at"] <= now else "waiting")
            out.append({"id": r["id"], "label": r["label"], "created_at": r["created_at"],
                        "expires_at": r["expires_at"], "claimed_at": r["claimed_at"], "state": state})
        return out

    def claim(self, code: str, label: str | None = None, ip: str | None = None) -> dict:
        """Use up an invite code: it becomes this device's own sign-in link. Once only; a resident's
        before it expires, a visitor's only inside the visit's window."""
        from .core import _hash, _new_token
        now = self.beach.now()
        with self.db.lock:
            r = self.db.one("SELECT * FROM access_invites WHERE code_hash = ?", (code_key(code),))
            if not r or r["revoked_at"] or self.removed(r["participant_id"]):
                raise self._err("not_found", "that code isn't valid; ask the keeper for a new one")
            if r["claimed_at"]:
                raise self._err("conflict", "that code has already been used; ask the keeper for a new one")
            p = self.beach.participant(r["participant_id"])
            if p.access == "visitor":
                v = self.visit_of(p.id)
                if not v or v["ended_at"] or now >= v["ends_at"]:
                    raise self._err("forbidden", "that visit is over")
                if now < v["starts_at"]:
                    raise self._err("forbidden", "that visit hasn't started yet; the code works from "
                                    f"{_clock(v['starts_at'])}", data={"starts_at": v["starts_at"]})
            elif now >= r["expires_at"]:
                raise self._err("forbidden", "that code has expired; ask the keeper to send a new one")
            token = _new_token()
            device = " ".join(str(label or r["label"]).split())[:40] or r["label"]
            sid = self.db.run("INSERT INTO sign_ins (participant_id, token_hash, label, created_at, last_used_at, last_ip)"
                              " VALUES (?, ?, ?, ?, ?, ?)", (p.id, _hash(token), device, now, now, ip))
            self.db.run("UPDATE access_invites SET claimed_at = ?, sign_in_id = ? WHERE id = ?", (now, sid, r["id"]))
            if p.access == "visitor":
                self.db.run("UPDATE access_visits SET first_seen_at = COALESCE(first_seen_at, ?) WHERE participant_id = ?"
                            " AND ended_at IS NULL", (now, p.id))
        out = {"token": token, "id": p.id, "name": p.name, "kind": p.kind, "access": p.access,
               "next": "send 'Authorization: Bearer <token>'; start with GET /agent/beach-card"}
        if p.access == "visitor":
            v = self.visit_of(p.id)
            out["visit"] = {"ends_at": v["ends_at"], "until": _clock(v["ends_at"])}
        return out

    # ------------------------------------------------------------------ visits

    @staticmethod
    def _duration(v, cap: float, what: str) -> float:
        from .core import BeachError
        try:
            v = float(v)
        except (TypeError, ValueError):
            raise BeachError("invalid", f"{what} is a number of seconds") from None
        if not 60 <= v <= cap:
            raise BeachError("invalid", f"{what} is between a minute and {int(cap // 86400)} days")
        return v

    def invite_visitor(self, name: str, kind: str, starts_at: float, ends_at: float, bell: bool = False) -> dict:
        """A visitor and their visit: a one-time code that works only inside [starts_at, ends_at)."""
        if kind not in ("person", "agent"):
            raise self._err("invalid", "kind must be 'person' or 'agent'")
        try:
            starts_at, ends_at = float(starts_at), float(ends_at)
        except (TypeError, ValueError):
            raise self._err("invalid", "starts_at and ends_at are times (seconds since 1970)") from None
        now = self.beach.now()
        if ends_at <= max(starts_at, now):
            raise self._err("invalid", "the visit must end after it starts, and after now")
        if ends_at - starts_at > MAX_VISIT_S:
            raise self._err("invalid", "a visit lasts at most two weeks; residents are for longer")
        name = self.check_new_name(name)
        pid = self.db.run("INSERT INTO participants (name, kind, is_admin, invitable, created_at, access)"
                          " VALUES (?, ?, 0, 0, ?, 'visitor')", (name, kind, now))
        vid = self.db.run("INSERT INTO access_visits (participant_id, name, starts_at, ends_at, bell, made_at)"
                          " VALUES (?, ?, ?, ?, ?, ?)", (pid, name, starts_at, ends_at, int(bool(bell)), now))
        return {"participant": self.beach.participant(pid), "visit": self.visit(vid),
                "invite": self._new_invite(pid, "visit", ends_at)}

    def visit(self, vid: int) -> dict:
        r = self.db.one("SELECT * FROM access_visits WHERE id = ?", (vid,))
        if not r:
            raise self._err("not_found", "no such visit")
        now = self.beach.now()
        state = ("ended" if r["ended_at"] else "waiting" if now < r["starts_at"]
                 else "over" if now >= r["ends_at"] else "on")
        return {"id": r["id"], "participant_id": r["participant_id"], "name": r["name"],
                "starts_at": r["starts_at"], "ends_at": r["ends_at"], "bell": bool(r["bell"]),
                "made_at": r["made_at"], "first_seen_at": r["first_seen_at"], "ended_at": r["ended_at"],
                "end_reason": r["end_reason"], "zones": json.loads(r["zones"]),
                "zone_names": [self._zone_name(z) for z in json.loads(r["zones"])], "state": state,
                # Where they are right now (a zone or a world), apart from the log of where they went:
                # "on" alone read as "here now" to the keeper (10-17), when it meant "the pass is open".
                "here": self._here(r["participant_id"]) if state == "on" else []}

    def _here(self, pid: int) -> list[str]:
        w = self.where(pid)
        return [z["name"] for z in w["zones"]] + [x["name"] for x in w["worlds"]]

    def _zone_name(self, zid: str) -> str:
        z = self.db.one("SELECT name FROM zones WHERE id = ?", (zid,))
        return z["name"] if z else zid

    def visit_of(self, pid: int):
        """The participant's latest visit row (None for a resident who never visited)."""
        return self.db.one("SELECT * FROM access_visits WHERE participant_id = ? ORDER BY id DESC LIMIT 1", (pid,))

    def visits(self) -> list[dict]:
        """The keeper's visit log, newest first: who, when, which zones."""
        return [self.visit(r["id"]) for r in self.db.q("SELECT id FROM access_visits ORDER BY id DESC LIMIT 200")]

    def visit_allows(self, pid: int) -> bool:
        """For a visitor: is their visit on right now? (Residents: always.)"""
        p = self.beach.participant(pid)
        if p.access != "visitor":
            return True
        v = self.visit_of(pid)
        now = self.beach.now()
        return bool(v) and not v["ended_at"] and v["starts_at"] <= now < v["ends_at"]

    def saw(self, pid: int, zid: str) -> None:
        """A visitor went into a zone (or a world): note it in their visit's log."""
        v = self.db.one("SELECT id, zones FROM access_visits WHERE participant_id = ? AND ended_at IS NULL"
                        " ORDER BY id DESC LIMIT 1", (pid,))
        if v:
            zones = json.loads(v["zones"])
            if zid not in zones:
                self.db.run("UPDATE access_visits SET zones = ? WHERE id = ?", (json.dumps(zones + [zid]), v["id"]))

    def may_ring(self, pid: int) -> bool:
        p = self.beach.participant(pid)
        if p.access != "visitor":
            return True
        v = self.visit_of(pid)
        return bool(v and v["bell"])

    def end_visit(self, vid: int, reason: str = "keeper") -> dict:
        """End a visit now: every credential it made stops working, the visitor leaves every zone and
        world, and the log keeps who, when and where."""
        v = self.visit(vid)
        if v["ended_at"] is None:
            self.db.run("UPDATE access_visits SET ended_at = ?, end_reason = ? WHERE id = ? AND ended_at IS NULL",
                        (self.beach.now(), reason, vid))
            self.cut_off(v["participant_id"])
        return self.visit(vid)

    def sweep(self) -> int:
        """Upkeep: end every visit whose window is over."""
        rows = self.db.q("SELECT id FROM access_visits WHERE ended_at IS NULL AND ends_at <= ?", (self.beach.now(),))
        for r in rows:
            self.end_visit(r["id"], "window")
        return len(rows)

    def make_resident(self, pid: int) -> dict:
        """A visitor becomes a resident: the visit ends as converted, their links stay and keep working."""
        p = self.beach.participant(pid)
        if p.access != "visitor":
            raise self._err("conflict", f"{p.name} is already a resident")
        v = self.visit_of(pid)
        if v and not v["ended_at"]:
            self.db.run("UPDATE access_visits SET ended_at = ?, end_reason = 'resident' WHERE id = ?",
                        (self.beach.now(), v["id"]))
        elif v and v["end_reason"] != "resident":
            raise self._err("conflict", "that visit is over; invite them as a resident instead")
        self.db.run("UPDATE participants SET access = 'resident', invitable = 1 WHERE id = ?", (pid,))
        return {"id": pid, "name": p.name, "access": "resident"}

    # ------------------------------------------------------------------ the keeper's controls

    def cut_off(self, pid: int) -> None:
        """Every way in stops working, and the participant is taken out of everything: links and
        unclaimed invites revoked, every zone parted, world characters removed, watching stopped,
        seats at waiting tables given up and live card games left."""
        b = self.beach
        now = b.now()
        self.db.run("UPDATE sign_ins SET revoked_at = ? WHERE participant_id = ? AND revoked_at IS NULL", (now, pid))
        self.db.run("UPDATE access_invites SET revoked_at = ? WHERE participant_id = ? AND claimed_at IS NULL"
                    " AND revoked_at IS NULL", (now, pid))
        for zid in b.zones_of(pid):
            b.part(pid, zid)
        for z in self.db.q("SELECT DISTINCT zone_id FROM game_grants WHERE participant_id = ? AND left_at IS NULL", (pid,)):
            b.leave_world(pid, z["zone_id"])
        self.db.run("DELETE FROM world_watchers WHERE participant_id = ?", (pid,))
        self.db.run("DELETE FROM table_watchers WHERE participant_id = ?", (pid,))
        for t in self.db.q("SELECT t.id, t.status FROM game_tables t JOIN table_seats s ON s.table_id = t.id"
                           " WHERE s.participant_id = ? AND t.status IN ('waiting', 'playing')", (pid,)):
            try:
                if t["status"] == "waiting":
                    b.tables.stand(pid, t["id"])
                else:
                    b.tables.resign(pid, t["id"])
            except Exception:   # a table that can't be left still waits; nothing to undo here
                pass

    def kick(self, pid: int) -> dict:
        p = self.beach.participant(pid)
        if p.is_admin:
            raise self._err("forbidden", "the keeper can't be kicked from here")
        v = self.visit_of(pid) if p.access == "visitor" else None
        if v and not v["ended_at"]:
            self.end_visit(v["id"], "keeper")
        else:
            self.cut_off(pid)
        return {"id": pid, "name": p.name, "kicked": True}

    def removed(self, pid: int) -> bool:
        r = self.db.one("SELECT removed_at FROM participants WHERE id = ?", (pid,))
        return bool(r and r["removed_at"])

    def remove(self, pid: int) -> dict:
        """Take a participant off the list for good. Their messages stay as history under their name,
        marked as a former participant; their name stays held for rename_hint_s (a day)."""
        p = self.beach.participant(pid)
        if p.is_admin:
            raise self._err("forbidden", "the keeper can't be removed")
        self.kick(pid)
        now = self.beach.now()
        with self.db.tx() as db:
            # Every message keeps the name it was said under (older rows may not have it yet).
            db.conn.execute("UPDATE messages SET author_name = ? WHERE author_id = ? AND author_name IS NULL",
                            (p.name, pid))
            db.conn.execute("UPDATE participants SET removed_at = ?, former_name = ?, invitable = 0 WHERE id = ?",
                            (now, p.name, pid))
            # The name is held like a rename's old name: for rename_hint_s, nobody else can take it.
            db.conn.execute("INSERT INTO name_history (participant_id, old_name, new_name, at, by_admin)"
                            " VALUES (?, ?, ?, ?, 1)", (pid, p.name, f"#{pid} (removed)", now))
            # The row keeps an id for history; its name moves out of the way of future names.
            db.conn.execute("UPDATE participants SET name = ? WHERE id = ?", (f"#{pid} {p.name}", pid))
        return {"id": pid, "name": p.name, "removed": True}

    # ------------------------------------------------------------------ the keeper's view

    def where(self, pid: int) -> dict:
        b = self.beach
        worlds = []
        for z in self.db.q("SELECT id, name FROM zones WHERE kind = 'game' ORDER BY name"):
            if b.playing(pid, z["id"]):
                worlds.append({"zone": z["id"], "name": z["name"], "as": "playing"})
            elif b.watching(pid, z["id"]):
                worlds.append({"zone": z["id"], "name": z["name"], "as": "watching"})
        return {"zones": [{"zone": zid, "name": b.zone(zid)["name"]} for zid in b.zones_of(pid)], "worlds": worlds}

    def status(self, pid: int) -> str:
        """For the list: 'active', 'invited' (not claimed yet), 'invite expired', 'signed out',
        'visit waiting', 'visit over'."""
        b = self.beach
        p = b.participant(pid)
        if p.access == "visitor":
            v = self.visit_of(pid)
            if not v or v["ended_at"] or b.now() >= v["ends_at"]:
                return "visit over"
        if b.is_active(pid):
            return "active"
        inv = self.invites(pid)
        if any(i["state"] == "waiting" for i in inv):
            if p.access == "visitor" and b.now() < self.visit_of(pid)["starts_at"]:
                return "visit waiting"
            return "invited"
        if inv and not any(i["state"] == "claimed" for i in inv):
            return "invite expired"
        return "signed out"


def _clock(t: float) -> str:
    import time
    return time.strftime("%Y-%m-%d %H:%M", time.localtime(t))
