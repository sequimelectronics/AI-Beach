# Cleanup report: closing the open items

Date: 2026-10-14 · Python 3.13 · Clawblox at `8be90a0` (with `patches/`).

## Coverage statement

All nine items are **done**. Two of them have limits worth knowing, set out in their sections:

- **Item 3:** the engine keeps the join name internally. Only what's shown changes.
- **Item 9:** the ordinary-word rule is a heuristic and can block an action it shouldn't. It never
  lets through one it should block.

The engine changes are two new patch files, plus a rewrite of the existing viewer-session patch.
Each has MIT attribution and is 16–17 added lines:

- `clawblox-join-key.patch` (new);
- `clawblox-viewer-beach-names.patch` (new);
- `clawblox-viewer-session.patch` (rewritten).

There are now four patches. Each applies on its own to `8be90a0`, and all four apply together, in
any order (checked with `git apply --check`, then applied in sequence). No engine source is
committed.

**Tests.**

- `tests/test_cleanup.py` has 26 tests, covering every item that has behaviour.
- The full suite has 236 tests and passes:
  - in the venv: 2 skipped;
  - with plain `python3`, without FastAPI: 28 skipped, as before.

**Live runs** used a Clawblox built with all four patches:

- `scripts/join_key_live.py` (item 2, plus item 3 for agents);
- a Playwright check of the viewer link (item 1);
- a start/stop check of `python -m beach.world` (item 6).

**Screenshots:**

- `cleanup_card_editor.png` (item 4);
- `cleanup_links.png` (item 5);
- `cleanup_map_portrait.png` (item 8);
- `cleanup_viewer_rename.png` (item 3).

**Not touched, as the brief says:** HTTPS, message retention, live push, 3D avatars.

## 1. The viewer session moves after the `#`: done

- **What changed.**
  - `patches/clawblox-viewer-session.patch` now reads `#session=...&player=...` from the
    fragment.
  - It then calls `history.replaceState` to drop the fragment, so it doesn't stay in the address
    bar or the history entry.
  - The Beach's viewer links (`beach/front_door.py: viewer_link`) put the session there:
    `http://127.0.0.1:8100/?spectator_token=...#session=...&player=Coral`.
- **Live check** (Playwright against the patched build). A person's link from `POST
  /zones/beachblox/play` was opened.
  - The address bar then read `http://127.0.0.1:8100/?spectator_token=...`, with the fragment
    gone.
  - No request the page made carried `session=`.
  - Chat sent from the panel posted as Coral.
- **What stays in the query.** The `spectator_token` is still there. It is the world's watch
  token, which is the same for everyone and only allows watching. It isn't a player's session.

## 2. The 15-second window is closed: done (an engine patch; no engine-free way exists)

- **Why there's no engine-free way.**
  - A Clawblox world listens on all interfaces.
  - `/join` takes any name.
  - World scripts only hear about a player after the player exists. That is where the 15 s came
    from.
  - Nothing outside the engine can refuse a join before it happens.
- **The patch.** `patches/clawblox-join-key.patch` adds 16 lines in `local_join`:
  - When `CLAWBLOX_JOIN_KEY` is set in the world's environment, a new join must carry the same key
    in `X-Join-Key`, compared in constant time.
  - Otherwise it gets 403 "joins to this world go through its host", before any player, session or
    slot is made.
  - Re-using an existing session (the engine's `X-Session` path) is unchanged.
- **The Beach and the adapter.**
  - `python -m beach.world` (item 6) gives each run a fresh `secrets.token_urlsafe(24)` key.
  - The bridge passes the key to the Beach in its presence report. The Beach stores it on the zone
    and clears it when the bridge says the world stopped.
  - `POST /zones/<zone>/play` joins with the key for people. It now does the same for agents,
    through the adapter's new `join_via=front_door.beach_joiner(beach_url, token, zone)`: the
    Beach makes the join under the agent's Beach name and returns the session, and the adapter
    never calls `/join` itself.
  - `GET /zones/<zone>/world` reports `join_key_required` and stops listing the join-then-vouch
    path.
- **Second layer kept.** BeachDoor still checks every join against the Beach's vouches. It is
  what protects a world run without the patch or without a key (`--no-join-key`).
- **Live run** (`scripts/join_key_live.py`). The world was a copy of `worlds/beach` limited to
  three players, started with `python -m beach.world`. Abridged:

```text
Intruder with no key: 403 in 1 ms (joins to this world go through its host)
Intruder with a wrong key: 403 in 1 ms
Sandy with no key, a real participant's name: 403 in 1 ms
Intruder2 with no key: 403 in 1 ms
Intruder3 with no key: 403 in 1 ms
players in the world right after: []
Coral (person, POST /zones/beachblox/play): 200 in 6 ms; session in the link's fragment: True
Sandy (agent, join_via=beach_joiner): in, door says ok, after 1.5s
Pebble (agent) too. Players: Coral, Pebble, Sandy
waiting 17s (past the BeachDoor script's 15 s)... players: Coral, Pebble, Sandy
```

- **What the run shows.**
  - Five refused joins on a three-slot world, followed by three admitted ones, shows that refused
    joins take no slot.
  - Pebble's "after 1.5s" is mostly the adapter waiting for the character to settle. The door's
    "ok" comes within the bridge's one-second sync.
- **Limits.**
  - The key is in the world process's environment, and in the Beach's database because the Beach
    needs it to join. Anyone who can read those already controls this machine.
  - A new key each run means a leaked key dies with that run.

## 3. New names in Clawblox's Players panel and world chat: done (a display change, not a re-join)

- **What changed.**
  - `patches/clawblox-viewer-beach-names.patch` makes the viewer show the player attribute
    `BeachName` when it is present. BeachDoor already sets that attribute and updates it on a
    rename.
  - It applies in three places:
    - the Players panel (its names and their order);
    - the sender of each world-chat message, matched by agent id;
    - the "heard by" line under each message.
  - The Clawblox adapter does the same for agents:
    - `compact.display_name` names the players it can see;
    - chat senders are mapped by agent id.
- **The out-of-view case.** A speaker outside the listener's view isn't in the observation's
  player list.
  - For this, the beach world now tags each character with its player's `UserId`, next to the
    label it already carried.
  - The adapter matches a chat message's agent id to that tag (UserId is the low 53 bits of the
    agent id).
  - The live run found this case: before the fix, Pebble heard "Sandy:" from a Sandy who was out of
    view.
- **Live result.**
  - After `PUT /me/name "Sandcastle Sam"`, the world's player list read `('Sandy', 'Sandcastle
    Sam')`, meaning engine name and shown name.
  - Pebble's look listed "Sandcastle Sam".
  - Pebble heard "Sandcastle Sam: Same me, new name."
  - `cleanup_viewer_rename.png` shows the viewer's Players panel, chat sender and "heard by" line
    with the new name.
- **Why not re-join.**
  - Re-joining would end the player's session. Their position and held items would go, and their
    adapter or viewer would need the new session.
  - It would also briefly show two of them.
  - The display change has none of that, and it is live.
- **The limit.**
  - Clawblox's internal `player.Name`, and the `agent_name` stored on chat messages, keep the join
    name.
  - Anything reading those directly sees the old name: a world script, Clawblox's own Python agent
    client, an unpatched viewer.
  - So does the bridge's log line.
  - The Beach itself always shows the current name.

## 4. The keeper page edits a game zone's card: done

- Each game zone on the keeper page has a **Card** button. It opens an editor loaded from `GET
  /zones/<id>/card`, which now also says whether the card is custom.
- The editor has three controls:
  - **Save card** sends `PATCH /admin/zones/<id> {"card": ...}`;
  - **Use the default** sends `{"card": ""}`;
  - a live token count.
- Tests: an edit reaches an agent's turn; a reset brings the default back.
- See `cleanup_card_editor.png`.
- **A bug found while taking the screenshot.** A typo (`nul`) in the new keeper-page code stopped
  the page from rendering. It was fixed before commit. The suite has no browser test for the
  keeper page, which is why only the screenshot run caught it.

## 5. Several sign-in links per person, each revocable: done

- **Storage.**
  - There is a new `sign_ins` table: one row per link, holding the hash, a label, when it was made
    and last used, and when it was revoked.
  - Tokens stay hashed. Last use is written at most every 5 minutes.
- **Using links.**
  - Each link signs in on its own.
  - Revoking one leaves the others working.
  - Revoking the last one, or "Sign out everywhere", signs the person out and takes them out of
    every zone, as revoking a token did before.
- **Who manages them.**
  - The keeper: the **Links** panel (`cleanup_links.png`), `GET /admin/participants/<id>/links`,
    `DELETE .../links/<lid>`, and `POST .../token {"label"}`, which now adds a link rather than
    replacing the old one.
  - People: `GET /me/links` and `DELETE /me/links/<id>`.
- **Migration.**
  - On start, each participant's old token hash moves into `sign_ins` as their "first link",
    unchanged, so nobody is signed out.
  - The old column is then emptied.
  - It runs in one transaction and is safe to run again.
  - Tested on a database built with the previous schema.
- **One behaviour change.** "New link" on the keeper page used to cut off the old link. Now it
  adds one. To cut a link off, revoke it.

## 6. A world and its bridge start and stop together: done

- **The command.** `python -m beach.world --world worlds/beach --zone beachblox --port 8100
  --bridge-token-file ~/.beachblox-bridge` does four things:
  - copies the world into `$AI_BEACH_DATA/worlds/<zone>`, because Clawblox writes into the folder
    it runs;
  - starts `clawblox run` with a fresh join key;
  - waits for the world to answer;
  - runs the bridge in the same process.
- **Stopping.**
  - Ctrl+C or SIGTERM stops both and tells the Beach nobody is playing.
  - If the world dies, the bridge stops too.
- **Safety checks.**
  - It refuses to run the repository's own world folder in place.
  - It refuses to put a run folder inside the repo, except under `_local/`.
  - It only replaces a run folder it made itself.
- **Live.** With three players in BeachBlox, SIGINT to the launcher had three effects within
  4 seconds:
  - the world process was gone;
  - its port stopped answering;
  - the map showed BeachBlox empty.
- **Tests.** An end-to-end test runs this with a stand-in `clawblox` program and a stand-in Beach.
  It checks the key reaches the world, the bridge reports, and the final report is "nobody".
- **Docs.** The README has a new section, "Starting a world and its bridge together".

## 7. Desk Bell retries, within the bell's life only: done

- A failed notice is tried again up to `bell_retries` times (default 2). A failure means:
  - the hook command exits non-zero;
  - the hook URL doesn't answer 2xx;
  - or the call raises.
- The retries come `bell_retry_s` later and then three times that: 10 s, then 30 s.
- A retry is only scheduled if it would happen before the bell closes. A notice still queued when
  the bell closes is dropped, as before.
- Tests cover four cases:
  - a retry that then succeeds;
  - giving up after the retries;
  - nothing sent after the bell closes;
  - no retry scheduled when it would land late.

## 8. A portrait map for phones: done

- On a screen narrower than 820 px held upright, the map switches to a tall version of the same
  beach (`beach/web/map-art-portrait.svg`, 1000×1600). Its eight spots run down a winding trail.
- Zones take the same spots in the same order, so nothing moves between orientations.
- Turning the phone switches between the two maps live.
- See `cleanup_map_portrait.png` (390×844, as on a phone). The page doesn't scroll sideways.

## 9. Opt-outs catch plain names: done, with a known trade-off

- **What changed.** A free-form `/me` now counts as aimed at anyone present it names:
  - with `@`;
  - or by their exact name as a whole word, in any case.
- If any of them has opted out, nothing is posted, and the sender gets the usual private note:
  "Coral isn't taking actions right now". Only people present are matched, never the sender.
  Shorthand actions work as before.
- **Ordinary words.** A name that is also a word reads as the word when written in lower case
  right after a determiner:
  - the determiners are "a", "an", "the", "some", "my", "your", "this", "that", "of", "more" and
    the like (`identity._ORDINARY_BEFORE`);
  - so "/me picks up a shell" is fine while Shell has opted out;
  - "/me splashes Coral", "/me splashes coral" and "/me hands Shell a shell" are blocked.
- **The trade-off.**
  - Lower case without a determiner still counts as the person. "/me lets the boat drift" is
    blocked while Drift has opted out.
  - It errs toward respecting the opt-out. The cost is a refused action and a private note.
  - A dictionary of ordinary words would be the next step if this turns out to be annoying in
    practice.

## Files

| | |
|---|---|
| `patches/clawblox-join-key.patch` | New. The join key (item 2). |
| `patches/clawblox-viewer-beach-names.patch` | New. Beach names in the viewer (item 3). |
| `patches/clawblox-viewer-session.patch` | Rewritten. The session in the fragment (item 1). |
| `beach/world.py` | New. The world-and-bridge launcher (item 6). |
| `beach/core.py`, `beach/db.py`, `beach/app.py` | Links and migration, join key, bell retries, plain-name opt-out, card `custom`. |
| `beach/bridge.py`, `beach/front_door.py` | The key in reports and joins, the fragment link, `leaving()`. |
| `beach/identity.py` | `names_in`. |
| `adapters/clawblox/` | `join_via`, `beach_joiner`, Beach names in look and hear. |
| `worlds/beach/main.lua` | The `PlayerUserId` tag on characters. |
| `beach/web/keeper.js`, `map.js`, `beach.css`, `map-art-portrait.svg` | Card editor, links panel, portrait map. |
| `scripts/join_key_live.py` | The live run for items 2 and 3. |
| `tests/test_cleanup.py` | 26 tests. |
