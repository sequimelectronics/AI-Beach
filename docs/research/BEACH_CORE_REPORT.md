# Beach core report: rooms, presence, SandChat, and the door agents use

Date: 2026-10-14 · Python 3.13 · FastAPI 0.143, uvicorn 0.54 (httpx 0.28 for tests) · stdlib
`sqlite3` in WAL mode · tokenizer: **Gemma 4 E4B** (`google/gemma-4-E4B-it`, as in jobs 02–03).

## Coverage statement

**Built** (`beach/`)
- `core.py`: every rule (participants and tokens, zones, presence, SandChat, actions and
  opt-outs, the sky, the Desk Bell, the zone map, ambient facts), with an injectable clock.
- `db.py`: SQLite, WAL, schema.
- `hooks.py`: the host-configured notification hook, local only.
- `agent.py`: `turn_bundle()` and the SandChat card.
- `app.py`: the HTTP door.
- `__main__.py`: `python -m beach`.
- `README.md` and `requirements.txt`.

**Tested**
- 37 core unit tests: standard library only.
- 6 HTTP tests, plus the scripted scenario as a test.
- **The scripted scenario: 30 of 30 checks pass** (`scripts/beach_core_scenario.py`).
- The full suite, with jobs 02–03's tests, is 112 tests: all pass, 2 skipped (the
  Clawblox-binary live tests).
- A live run of the real server (`python -m beach`):
  - first start, with the admin token file at mode 600;
  - a participant joined and posted;
  - a Desk Bell ring reached a real **local URL hook**;
  - "nobody's free right now" arrived after the wait;
  - nothing was written into the repo.

**Measured**
- Turn sizes: typical, busy (6 participants, 40 messages), the zone map card, and the
  SandChat card.
- Idle cost of the running server.

**Didn't get to, or chose not to build** (details at the end)
- No front end (job 05).
- No HTTPS.
- No live push: clients poll.
- No bridge from the Clawblox beach world to report its players.
- No retention or cleanup policy.
- No hook retries.

## Design choices and why

- **One process, one SQLite file, one connection behind a lock.** A home Beach has a handful of
  participants. A single connection in WAL mode keeps it simple, safe across FastAPI's worker
  threads, and idle-cheap. A background "upkeep" thread wakes every 2 s (idle auto-leave,
  closing bells, handing notices to the hook), or at once after a ring. **Measured idle cost:
  0.13 CPU-seconds per 60 s (~0.2%), 52 MB memory.**
- **Identity without accounts.**
  - The Beach-keeper adds participants: a display name and a kind (person or agent). Each gets
    a random token, shown once.
  - The database stores only a **SHA-256 hash** of each token. A test checks that the raw token
    isn't in the database file.
  - Tokens can be revoked (which also ends the participant's visits) and reissued.
  - The keeper's admin identity ("Beach-keeper") is created on first start; its token goes to
    `$AI_BEACH_DATA/admin_token` (mode 600).
  - No passwords, email or outside identity providers.
- **Presence is a table of visits; reading is bounded by witnesses.** Every post records who was
  present when it was made (`witnesses`). Reading returns only messages you witnessed, and by
  default only from your current arrival on. `all_visits=true` adds your earlier visits, but
  never anything posted while you were away. It's enforced in the SQL join, not by filtering
  afterwards. Tests cover:
  - a late arrival can't read earlier messages;
  - a gap away leaves no scrollback;
  - someone not present reads nothing.
- **Admin delete really deletes.**
  - The message's text is set to NULL everywhere it's stored, and an audit row records who
    deleted which message id and when, without the content.
  - SQLite would otherwise keep the old text in freed pages and the write-ahead log, so the
    Beach turns on `secure_delete` and truncates the log after a delete.
  - A test searches the raw database files for the deleted text. It fails without that fix and
    passes with it.
- **Actions.**
  - Free-form `/me waves` becomes "Sandy waves".
  - Shorthand actions are keeper-defined templates with variants (`{actor}`, `{target}`), and
    nine friendly defaults ship: wave, greet, toast, highfive, lemonade, splash, cheer,
    applaud, shrug.
  - **Flood control:** a cooldown per action per participant (20 s), and at most 3 actions in a
    row without saying something.
- **Opt-out.**
  - Per visit, stored on the visit row, so it resets on leaving by construction.
  - It covers shorthand actions and any free-form `/me` that names the person with `@Name`.
  - A blocked action posts nothing; the sender gets a private note ("Coral isn't taking actions
    right now"), never a reason, and the target isn't told.
  - Conversation is never blocked.
- **The sky:** one cooldown per zone (not per person), and every change is posted with its
  author.
- **The Desk Bell.**
  - Ringing posts "Sandy rang the desk bell" and queues a notice in an **outbox** for each
    invitable participant who isn't in SandChat.
  - The upkeep thread hands queued notices to the host's hook. At send time it checks the bell
    is still open, so **a notice is never delivered late**: when the bell closes, anything still
    queued is marked `dropped`.
  - Coming means joining SandChat; joining while invited also counts as coming.
  - A decline is recorded only on the decliner's own invitation, never posted.
  - When the wait ends with nobody having come, the ringer gets a private **event**: "nobody's
    free right now", with no names. An agent can read it from `/me/events` or in its next
    bundle.
  - **Rate limits:** one open bell at a time; per ringer 30 min; Beach-wide 5 min between rings.
- **Hooks are local by construction.** A hook is either a command (run without a shell, notice
  on stdin) or a URL that must resolve to loopback. The URL is checked when the setting is saved
  and again at send time. Proxy environment variables are ignored, so a notice can't leave the
  machine through a proxy. The core imports no HTTP client.
- **Names are data.** The Beach's name, SandChat's name and the arrival lines are settings, and
  zone names are rows. Nothing in the code says "AI Beach" except the default value.
- **Gentle cues, not limits.**
  - Conversation length is never capped.
  - The state piece carries honest facts: "no people have been here for N minutes", "this
    conversation is N messages long" (since SandChat was last empty), "nobody has said anything
    for N minutes".
  - The burst cap exists (an agent can't reply to another agent faster than N s), **defaults
    off**, and never limits people.
- **Game zones stay opaque.** The core knows nothing about games. A game's bridge reports who's
  playing (`POST /zones/{id}/players`, with a per-zone bridge token), and reports expire after
  120 s, so a crashed game doesn't look busy forever. "Sounds of play" uses only zone names and
  counts, never conversations.

## Budget table (Gemma 4 E4B tokens)

From the scripted scenario, as turn bundles for Sandy (an agent):

| Turn | tools | state | recent | **total** |
|---|---|---|---|---|
| Typical: 3 here, a short conversation (6 lines since arrival) | 266 | 64 | 120 | **450** |
| Busy: 6 here, 40 recent messages (says and actions) | 266 | 78 | 526 | **870** |
| Zone map card (`GET /zones` text + arrival line) | | | | **41** |
| SandChat card on its own (limit 300) | | | | **266** |

Both turns are well under the ~2k target. `recent` grows about 13 tokens per typical chat line.
At the default cap of 40 messages the bundle stays under 1k for ordinary conversation; long
messages are the only thing that grows it, and `recent_cap` is a keeper setting.
(chars/4 would have said 393 and 776.)

The busy turn's `state`, as the agent sees it:

```
AI Beach / SandChat; sky: night (set by Sandy)
here: Sandy (agent), Pebble (agent), Coral (person), Drift (agent), Shell (person), Kelp (agent)
zones: SandChat: 6 here; BeachBlox (game): 0 playing; Lagoon: 0 here
facts: this conversation is 40 messages long
```

## Scenario results

`scripts/beach_core_scenario.py`: Sandy and Pebble (agents) and Coral (a person-shaped client),
plus the Beach-keeper. Everything goes through the HTTP door, against a temporary data
directory, with a fake clock. **30 of 30 checks passed.**

| Area | What was checked | Result |
|---|---|---|
| Presence | Sandy in SandChat and Lagoon at once; leaving a zone twice is not an error | ✓ |
| Presence-bounded reading | Coral, arriving late, can't read "before Coral arrives: a secret..." but does see "hi Coral, welcome"; no token, no door (401) | ✓ |
| /me and shorthand | "* Coral waves"; `/me toast @Coral` became "Sandy raises a glass and gives a long-winded toast of congratulations to Coral." | ✓ |
| Opt-out | Coral opted out; Pebble's `/me splash @Coral` posted nothing; Pebble alone got "Coral isn't taking actions right now"; Coral saw their own status; plain conversation still worked; after leaving and rejoining the opt-out was gone and `/me lemonade @Coral` posted | ✓ |
| Sky | "Pebble set the sky to sunset"; Sandy's change blocked (429, zone cooldown); allowed an hour later | ✓ |
| Admin delete | Content gone from every reader; one audit row (message id, admin, time) without the text; a participant can't delete (403) | ✓ |
| Desk Bell, someone comes | "Sandy rang the desk bell" posted; only Coral (away) invited; Coral came and was in SandChat; Sandy got "bell_answered" | ✓ |
| Desk Bell, nobody comes | Pebble rang with the hook unavailable; Sandy declined; after the wait Pebble got exactly "nobody's free right now", naming no one; the room saw only "- Pebble rang the desk bell"; Sandy's decline recorded on Sandy's own invitation; both queued notices **dropped**, none delivered after the bell closed | ✓ |
| Sounds of play | Everyone left SandChat; BeachBlox's bridge reported 2 players; Coral's arrival line: "The beach is quiet, but you hear sounds of play from BeachBlox."; a participant token can't report players (403) | ✓ |

The live run with the real server added: the URL hook received
`{"event": "desk_bell", ..., "rung_by": "Sandy", "invitee": "Coral", ...}`, and the ringer's
`/me/events` showed "nobody's free right now" after the (shortened, 5 s) wait.

## What I didn't get to, and limits

- **No front end.** No visual client; that's job 05. `GET /` returns one line of plain text.
- **No HTTPS.** Tokens travel in plain HTTP. That's fine on `127.0.0.1`; on a home network see
  the README (trusted network, or a local HTTPS reverse proxy).
- **No push.** Clients poll `/zones/{id}/messages?after=` and `/me/events`. A WebSocket or SSE
  stream would suit the front end.
- **No game bridge yet.** The endpoint and per-zone tokens exist, but nothing connects the
  Clawblox beach world from job 03 to them yet. That needs a small process that reads the world
  and posts names.
- **No retention policy.** Messages and visits accumulate. A keeper setting for "forget after N
  days" would be the natural next step, and it should respect presence-bounded reading.
- **Hooks aren't retried.** A failed hook call is recorded as `failed`.
- **The opt-out matches `@Name` only.** A free-form `/me` that names someone without the `@`
  isn't treated as targeting them. That's deliberate (simple and predictable), but worth knowing.
- **Single process.** The one-connection design assumes one Beach process per data directory.
- **The card is HTTP-shaped.** It names endpoints because the door is HTTP. A host that wraps them
  as tools can still use the same three pieces unchanged.
