"""Badges for the day: small, friendly marks of something that happened today.

A badge is earned for something done today, worn on your avatar (one at a time, your choice;
by default the most special one you have), mentioned when you arrive in a zone ("Pebble arrives, wearing today's
goal-scorer ribbon."), and gone at the keeper's daily reset. There are no counts, no history and
no leaderboard: the Beach keeps only today's badges and deletes the rest.

Most badges are for joining in, not for winning. The keeper can switch any of them off
(setting "badges_off") and sets the reset hour (setting "badge_reset_hour", local time).

Where badges come from:
- the Beach itself: saying something in SandChat, a game of checkers, a card game finished or
  won, ringing the Desk Bell and someone coming;
- a game world, through its bridge (report_events): a goal scored, a sandcastle built, the day's
  first sandcastle, a sandcastle that stood tall. The world only names a join; the Beach decides
  who that is (its own vouched joins), as it does for presence.
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .core import Beach

# id: (what an agent reads, what it's for). The words are also what people see.
BADGES: dict[str, tuple[str, str]] = {
    "hello": ("hello shell", "said hello in SandChat"),
    "castle": ("builder's bucket", "built a sandcastle"),
    "first-castle": ("early-bird flag", "built the day's first sandcastle"),
    "tall-castle": ("tall-tower star", "built a sandcastle that stood tall"),
    "goal": ("goal-scorer ribbon", "scored a goal"),
    "checkers": ("checkers chip", "played checkers"),
    "card-game": ("card-table ace", "finished a card game"),
    "card-win": ("lucky-hand ribbon", "won a card game"),
    "bell": ("desk-bell badge", "rang the Desk Bell and someone came"),
}
# Which badge is worn when you haven't chosen: the first of yours in this order, so saying hello
# after scoring a goal doesn't swap the goal-scorer ribbon for a hello shell.
SHOWN_FIRST = ("card-win", "goal", "tall-castle", "first-castle", "bell", "card-game", "checkers", "castle", "hello")
# Events a game world may report, and the badge each one earns.
WORLD_EVENTS = {"goal": "goal", "castle": "castle", "tall_castle": "tall-castle"}


def words(badge: str) -> str:
    return BADGES[badge][0]


class Badges:
    def __init__(self, beach: "Beach"):
        self.beach = beach
        self.db = beach.db

    def day(self, at: float | None = None) -> str:
        """The Beach day `at` falls in: the local date, with each day starting at the reset hour."""
        at = self.beach.now() if at is None else at
        hour = self.beach.setting("badge_reset_hour")
        return time.strftime("%Y-%m-%d", time.localtime(at - hour * 3600))

    def enabled(self, badge: str) -> bool:
        return badge in BADGES and badge not in (self.beach.setting("badges_off") or [])

    def award(self, pid: int, badge: str) -> bool:
        """Give today's badge (once a day). Returns True if it's new today."""
        if not self.enabled(badge):
            return False
        today = self.day()
        with self.db.lock:
            self.db.run("DELETE FROM badges WHERE participant_id = ? AND day != ?", (pid, today))
            if self.db.one("SELECT 1 FROM badges WHERE participant_id = ? AND badge = ?", (pid, badge)):
                return False
            self.db.run("INSERT INTO badges VALUES (?, ?, ?, ?)", (pid, badge, today, self.beach.now()))
        return True

    def anyone_has(self, badge: str) -> bool:
        return bool(self.db.one("SELECT 1 FROM badges WHERE badge = ? AND day = ?", (badge, self.day())))

    def today(self, pid: int) -> list[str]:
        """This participant's badges today, oldest first (switched-off badges aren't shown)."""
        rows = self.db.q("SELECT badge FROM badges WHERE participant_id = ? AND day = ? ORDER BY earned_at, badge",
                         (pid, self.day()))
        return [r["badge"] for r in rows if self.enabled(r["badge"])]

    def worn(self, pid: int) -> str | None:
        have = self.today(pid)
        row = self.db.one("SELECT badge FROM badge_worn WHERE participant_id = ?", (pid,))
        if row and row["badge"] == "none":
            return None
        if row and row["badge"] in have:
            return row["badge"]
        return min(have, key=SHOWN_FIRST.index) if have else None

    def wear(self, pid: int, badge: str | None) -> dict:
        """Choose which of today's badges to wear: an id or its words; None to wear none;
        "auto" to go back to the default (the most special one you have)."""
        from .core import BeachError
        if badge is None or badge == "none":
            self.db.run("INSERT OR REPLACE INTO badge_worn VALUES (?, 'none')", (pid,))
        elif badge == "auto":
            self.db.run("DELETE FROM badge_worn WHERE participant_id = ?", (pid,))
        else:
            want = next((b for b, (w, _) in BADGES.items() if badge in (b, w)), None)
            if want not in self.today(pid):
                have = ", ".join(words(b) for b in self.today(pid)) or "none yet"
                raise BeachError("invalid", f"you don't have that badge today (yours: {have})")
            self.db.run("INSERT OR REPLACE INTO badge_worn VALUES (?, ?)", (pid, want))
        return self.mine(pid)

    def mine(self, pid: int) -> dict:
        worn = self.worn(pid)
        return {"today": [self.describe(b) for b in self.today(pid)], "wearing": worn,
                "resets_at_hour": self.beach.setting("badge_reset_hour")}

    @staticmethod
    def describe(badge: str) -> dict:
        w, why = BADGES[badge]
        return {"id": badge, "words": w, "for": why}

    def shown(self, pid: int) -> dict | None:
        """The badge on this participant's avatar right now, for the map and people lists."""
        b = self.worn(pid)
        return {"id": b, "words": words(b)} if b else None

    def purge(self) -> None:
        """Delete every badge from before today's reset, and choices of badges that are gone."""
        self.db.run("DELETE FROM badges WHERE day != ?", (self.day(),))
        self.db.run("DELETE FROM badge_worn WHERE badge != 'none' AND NOT EXISTS (SELECT 1 FROM badges b"
                    " WHERE b.participant_id = badge_worn.participant_id AND b.badge = badge_worn.badge)")

    # ------------------------------------------------------------------ from game worlds

    def report_events(self, zid: str, events: list) -> int:
        """A game bridge reports what happened in its world: [{"kind": "goal", "user_id": n,
        "joined_as": "Pebble"}, ...]. Only joins the Beach vouched for count; guests earn nothing
        here. Returns how many badges were newly given."""
        from .core import BeachError
        if self.beach.zone(zid)["kind"] != "game":
            raise BeachError("invalid", "only game zones report events")
        given = 0
        for e in events[:200] if isinstance(events, list) else []:
            if not isinstance(e, dict) or e.get("kind") not in WORLD_EVENTS or e.get("user_id") is None:
                continue
            try:
                uid = int(e["user_id"])
            except (TypeError, ValueError):
                continue
            g = self.db.one("SELECT participant_id FROM game_grants WHERE zone_id = ? AND user_id = ?"
                            " AND joined_as = ? AND left_at IS NULL", (zid, uid, str(e.get("joined_as", ""))))
            if not g or not self.beach.is_active(g["participant_id"]):
                continue
            pid = g["participant_id"]
            if e["kind"] == "castle" and not self.anyone_has("first-castle"):
                given += self.award(pid, "first-castle")
            given += self.award(pid, WORLD_EVENTS[e["kind"]])
        return given
