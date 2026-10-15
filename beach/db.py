"""SQLite storage for the Beach: one file in the data directory, WAL mode.

One connection guarded by a lock: the Beach is a single small process on a
home machine, and this keeps it simple and idle-cheap.
"""

from __future__ import annotations

import sqlite3
import threading
from pathlib import Path

SCHEMA_VERSION = 1

SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);

CREATE TABLE IF NOT EXISTS participants (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL UNIQUE COLLATE NOCASE,
    kind TEXT NOT NULL CHECK (kind IN ('person', 'agent')),
    is_admin INTEGER NOT NULL DEFAULT 0,
    invitable INTEGER NOT NULL DEFAULT 1,
    token_hash TEXT UNIQUE,              -- before job 08 (one link each); moved to sign_ins
    created_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS zones (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    kind TEXT NOT NULL CHECK (kind IN ('chat', 'game')),
    open INTEGER NOT NULL DEFAULT 1,
    viewer_url TEXT,
    sky TEXT NOT NULL DEFAULT 'afternoon',
    sky_set_by INTEGER,
    sky_set_at REAL,
    created_at REAL NOT NULL
);

-- One row per visit: a participant present in a zone from joined_at until left_at.
CREATE TABLE IF NOT EXISTS visits (
    id INTEGER PRIMARY KEY,
    participant_id INTEGER NOT NULL REFERENCES participants(id),
    zone_id TEXT NOT NULL REFERENCES zones(id),
    joined_at REAL NOT NULL,
    left_at REAL,
    last_active REAL NOT NULL,
    optout_all INTEGER NOT NULL DEFAULT 0,
    optout_actions TEXT NOT NULL DEFAULT '[]'   -- per-visit; gone when the visit ends
);
CREATE INDEX IF NOT EXISTS visits_open ON visits (zone_id, left_at);

CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY,
    zone_id TEXT NOT NULL,
    author_id INTEGER,                    -- NULL for the Beach's own notices
    kind TEXT NOT NULL,                   -- say | action | sky | bell | presence
    text TEXT,                            -- NULL once deleted
    created_at REAL NOT NULL,
    deleted INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS messages_zone ON messages (zone_id, id);

-- Who was present when each message was posted. Reading is bounded by this.
CREATE TABLE IF NOT EXISTS witnesses (
    message_id INTEGER NOT NULL,
    participant_id INTEGER NOT NULL,
    PRIMARY KEY (message_id, participant_id)
) WITHOUT ROWID;

CREATE TABLE IF NOT EXISTS audit (
    id INTEGER PRIMARY KEY,
    at REAL NOT NULL,
    admin_id INTEGER NOT NULL,
    what TEXT NOT NULL,                   -- e.g. 'delete_message'
    message_id INTEGER
);

CREATE TABLE IF NOT EXISTS action_templates (
    name TEXT PRIMARY KEY COLLATE NOCASE,
    targeted INTEGER NOT NULL,
    variants TEXT NOT NULL                -- JSON list of strings with {actor} / {target}
);

-- Private notes and events for one participant (never shown to the room).
CREATE TABLE IF NOT EXISTS inbox (
    id INTEGER PRIMARY KEY,
    participant_id INTEGER NOT NULL,
    kind TEXT NOT NULL,                   -- note | event
    text TEXT NOT NULL,
    data TEXT,
    created_at REAL NOT NULL,
    delivered INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS bells (
    id INTEGER PRIMARY KEY,
    zone_id TEXT NOT NULL,
    ringer_id INTEGER NOT NULL,
    rung_at REAL NOT NULL,
    closes_at REAL NOT NULL,
    status TEXT NOT NULL DEFAULT 'open'   -- open | answered | unanswered
);

CREATE TABLE IF NOT EXISTS invites (
    bell_id INTEGER NOT NULL,
    participant_id INTEGER NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',  -- pending | came | declined | lapsed
    responded_at REAL,
    PRIMARY KEY (bell_id, participant_id)
);

-- Notification outbox: a hook call waiting to be made. Never delivered after its bell closes.
CREATE TABLE IF NOT EXISTS outbox (
    id INTEGER PRIMARY KEY,
    bell_id INTEGER NOT NULL,
    participant_id INTEGER NOT NULL,
    payload TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'queued',   -- queued | sent | failed | dropped
    queued_at REAL NOT NULL,
    done_at REAL
);

-- Who is playing in a game zone, as reported by the game's bridge.
CREATE TABLE IF NOT EXISTS zone_players (
    zone_id TEXT NOT NULL,
    name TEXT NOT NULL,                    -- a participant's id as text ("p:7"), or a guest label
    reported_at REAL NOT NULL,
    PRIMARY KEY (zone_id, name)
);

-- Game tables in zones that have them (the Boardwalk). The game's own state is JSON
-- the game module writes; the core never interprets it.
CREATE TABLE IF NOT EXISTS game_tables (
    id INTEGER PRIMARY KEY,
    zone_id TEXT NOT NULL,
    game TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'waiting',   -- waiting | playing | finished | abandoned | closed
    state TEXT NOT NULL,
    result TEXT,                              -- JSON once over: winner seat (or null), reason
    draw_offer INTEGER,                       -- the seat offering a draw, or NULL
    created_by INTEGER NOT NULL,
    created_at REAL NOT NULL,
    started_at REAL,
    last_activity REAL NOT NULL,              -- for abandoning forgotten games
    turn_since REAL,                          -- when the current turn began
    notified_ply INTEGER,                     -- the turn a "your move" notice was sent for
    finished_at REAL
);
CREATE TABLE IF NOT EXISTS table_seats (
    table_id INTEGER NOT NULL,
    seat INTEGER NOT NULL,
    participant_id INTEGER NOT NULL,
    PRIMARY KEY (table_id, seat)
);
CREATE TABLE IF NOT EXISTS table_watchers (
    table_id INTEGER NOT NULL,
    participant_id INTEGER NOT NULL,
    PRIMARY KEY (table_id, participant_id)
);
CREATE TABLE IF NOT EXISTS table_moves (
    table_id INTEGER NOT NULL,
    ply INTEGER NOT NULL,
    seat INTEGER NOT NULL,
    participant_id INTEGER NOT NULL,
    move TEXT NOT NULL,
    info TEXT,                                -- JSON from the game (captures, crowning)
    at REAL NOT NULL,
    PRIMARY KEY (table_id, ply)
);
-- When each participant last got a "your move" notice (rate limit).
CREATE TABLE IF NOT EXISTS turn_notices (
    participant_id INTEGER PRIMARY KEY,
    at REAL NOT NULL
);

-- Sign-in links: a participant may have several (a tablet and a phone), each revocable on its
-- own. Only a hash of each token is stored.
CREATE TABLE IF NOT EXISTS sign_ins (
    id INTEGER PRIMARY KEY,
    participant_id INTEGER NOT NULL REFERENCES participants(id),
    token_hash TEXT NOT NULL UNIQUE,
    label TEXT NOT NULL,
    created_at REAL NOT NULL,
    last_used_at REAL,
    revoked_at REAL
);
CREATE INDEX IF NOT EXISTS sign_ins_participant ON sign_ins (participant_id);

-- Renames (one name everywhere; the old name is shown as "(was ...)" for a while).
CREATE TABLE IF NOT EXISTS name_history (
    id INTEGER PRIMARY KEY,
    participant_id INTEGER NOT NULL,
    old_name TEXT NOT NULL,
    new_name TEXT NOT NULL,
    at REAL NOT NULL,
    by_admin INTEGER NOT NULL DEFAULT 0
);

-- The front door to game worlds: a participant's claim "this world join is me". A claim only
-- counts in the world if the join's name there equals the claimant's Beach name, so nobody
-- can claim (or block) a join made under someone else's name.
CREATE TABLE IF NOT EXISTS game_grants (
    agent_id TEXT NOT NULL,
    user_id INTEGER NOT NULL,              -- the world's player UserId, derived from agent_id
    zone_id TEXT NOT NULL,
    participant_id INTEGER NOT NULL,
    joined_as TEXT NOT NULL,
    granted_at REAL NOT NULL,
    PRIMARY KEY (agent_id, participant_id)
);

-- Watching a game world (core.watch_world): a spectator spot at the edge of the world. A
-- watcher has no character there; their name shows at the spot, and the world announces them.
-- A watch lasts while it is refreshed (the page does that while it is open).
CREATE TABLE IF NOT EXISTS world_watchers (
    zone_id TEXT NOT NULL,
    participant_id INTEGER NOT NULL REFERENCES participants(id),
    since REAL NOT NULL,
    seen_at REAL NOT NULL,
    PRIMARY KEY (zone_id, participant_id)
);

-- Each participant's look (avatar.py). No row = the default look for their id.
CREATE TABLE IF NOT EXISTS avatars (
    participant_id INTEGER PRIMARY KEY REFERENCES participants(id),
    record TEXT NOT NULL,                 -- JSON: preset, theme, hair, eyes, skin, accessory
    set_at REAL NOT NULL,
    set_by_admin INTEGER NOT NULL DEFAULT 0
);

-- Badges for the day (badges.py): what each participant earned TODAY, and nothing older. Rows
-- from before the keeper's daily reset are deleted: there are no counts and no history.
CREATE TABLE IF NOT EXISTS badges (
    participant_id INTEGER NOT NULL REFERENCES participants(id),
    badge TEXT NOT NULL,
    day TEXT NOT NULL,                    -- the Beach day it was earned (see badges.day())
    earned_at REAL NOT NULL,
    PRIMARY KEY (participant_id, badge)
);
-- Which badge a participant chose to wear ("none" for none). No row: badges.SHOWN_FIRST decides.
CREATE TABLE IF NOT EXISTS badge_worn (
    participant_id INTEGER PRIMARY KEY REFERENCES participants(id),
    badge TEXT NOT NULL
);
"""


class Database:
    def __init__(self, path: Path | str):
        self.path = str(path)
        self.lock = threading.RLock()
        self.conn = sqlite3.connect(self.path, check_same_thread=False, isolation_level=None)
        self.conn.row_factory = sqlite3.Row
        with self.lock:
            self.conn.execute("PRAGMA journal_mode=WAL")
            self.conn.execute("PRAGMA synchronous=NORMAL")
            self.conn.execute("PRAGMA foreign_keys=ON")
            # Deleted content is overwritten with zeros rather than left in free pages.
            self.conn.execute("PRAGMA secure_delete=ON")
            self.conn.executescript(SCHEMA)
            self.conn.execute("INSERT OR IGNORE INTO meta VALUES ('schema_version', ?)", (str(SCHEMA_VERSION),))

    def q(self, sql: str, args: tuple = ()) -> list[sqlite3.Row]:
        with self.lock:
            return self.conn.execute(sql, args).fetchall()

    def one(self, sql: str, args: tuple = ()) -> sqlite3.Row | None:
        with self.lock:
            return self.conn.execute(sql, args).fetchone()

    def run(self, sql: str, args: tuple = ()) -> int:
        with self.lock:
            cur = self.conn.execute(sql, args)
            return cur.lastrowid

    def run_count(self, sql: str, args: tuple = ()) -> int:
        """Like run(), for an UPDATE or DELETE: how many rows it changed."""
        with self.lock:
            return self.conn.execute(sql, args).rowcount

    def checkpoint(self) -> None:
        """Fold the write-ahead log into the main file and empty it (used after deletes)."""
        with self.lock:
            self.conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")

    def tx(self):
        """Context manager for a transaction (BEGIN IMMEDIATE ... COMMIT)."""
        return _Tx(self)

    def close(self) -> None:
        with self.lock:
            self.conn.close()


class _Tx:
    def __init__(self, db: Database):
        self.db = db

    def __enter__(self):
        self.db.lock.acquire()
        self.db.conn.execute("BEGIN IMMEDIATE")
        return self.db

    def __exit__(self, exc_type, exc, tb):
        try:
            if exc_type is None:
                self.db.conn.execute("COMMIT")
            else:
                self.db.conn.execute("ROLLBACK")
        finally:
            self.db.lock.release()
        return False
