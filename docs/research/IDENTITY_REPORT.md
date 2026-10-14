# Identity report: one name everywhere, and the Beach as the front door to game worlds

Date: 2026-10-14 · Python 3.13 · Clawblox at `8be90a0` (with `patches/`) · tokenizer: **Gemma 4 E4B**
(`google/gemma-4-E4B-it`).

## Coverage statement

**Built**
- **One name, everywhere** (`beach/identity.py`, core, API, pages):
  - the separate "in-game name" is removed: its keeper-page column, its mapping, and its database
    column;
  - renames for participants and for the keeper, posting IRC-style `/nick` lines;
  - the new name is used everywhere at once, including the label above a character in a running
    world;
  - "(was Sandy)" for 24 h, a keeper setting;
  - names in history as they were, with a legend whenever someone shown has since been renamed;
  - a keeper-set rename cooldown;
  - look-alike and impersonation checks;
  - a one-line rename instruction in the Beach card.
- **The Beach as the front door to game worlds, with no engine change:**
  - a world-side `BeachDoor` script (Luau, ours), run by both BeachBlox and ClawBlox;
  - Beach endpoints to vouch for a join, and for the Beach to join on a person's behalf;
  - the bridge carries the Beach's vouches into the world's own DataStore;
  - the adapter joins and vouches for agents;
  - the map's game zones join through the Beach for people;
  - guests are a keeper setting, off by default.
- **One tiny, optional viewer patch** (`patches/clawblox-viewer-session.patch`, MIT attribution).
  It lets the viewer's chat panel use the session the Beach made, so people can chat in a world
  under their own name. It is the only engine change in this job, and the front door works without
  it.
- **Checkers' no-progress draw** now matches standard English draughts: any man's move resets the
  count, as a capture does.

**Tested**
- **`tests/test_identity.py`: 21 tests.** These cover:
  - look-alike and malformed names;
  - `/nick` lines in SandChat, in the zone and at the table;
  - the new name in seats, the map and results;
  - the "(was ...)" window opening and closing;
  - history and its legend;
  - the rename cooldown, and keeper renames;
  - the old name reserved, then freed;
  - the rename line in the Beach card;
  - vouching rules, including a claim under the wrong name;
  - the door data, with renames and revocation;
  - presence by admitted join, and guests;
  - the Beach joining for a person;
  - the bridge writing to a real SQLite DataStore laid out the way Clawblox's is, end to end with
    the Beach's HTTP door.
- **Checkers:** 3 new rules tests: kings shuffling draws; any man move resets the count; a man move
  saves a game about to be drawn.
- **The full suite is 210 tests: all pass, 2 skipped** (the Clawblox-binary live tests, as before).
  Jobs 04 and 06's scripted scenarios still pass (30/30 and 8/8).
- **`scripts/identity_scenario.py` against REAL running worlds: 11 of 11 checks.** The setup was:
  - the Beach;
  - BeachBlox and ClawBlox on Clawblox, built with both patches;
  - both bridges;
  - two agents, joined through the adapter;
  - a person-shaped client, joined by the Beach.
- **Also live, by hand (`door_live` run):**
  - ClawBlox's door admitted Pebble and kicked an impostor "Pebble";
  - a claim under the wrong name was refused.

**Measured**
- **The Beach card is 249 tokens with the rename line** (was 224; 4 zones listed). It's 269 with
  the 6 zones of the live run.
- **A typical SandChat turn is 626 tokens** (was 601).

**Didn't do, or can't close without changing the engine** (details in "What's still open")
- An unvouched join exists in the world for up to 15 s before it's kicked.
- Clawblox's own player list and world chat keep the name someone joined with until they rejoin.
- Names inside past action lines aren't rewritten (by design; the legend covers them).

## The front door: what Clawblox allows, the options, and the choice

What I found in Clawblox (at `8be90a0`):

| Question | Answer |
|---|---|
| What does `/join` take? | Only `?name=`. Nothing else reaches the world script; the engine records the name and returns a `session` and an `agent_id`. |
| Can a world script refuse a player? | Yes: `player:Kick(msg)`. |
| Can a world script reach the network (to ask the Beach)? | **No.** `HttpService` is JSON helpers only. |
| Can a world script run more than `main.lua`? | Yes: `[scripts] tree = "scripts"` runs `scripts/ServerScriptService/*.lua`. |
| Can anything from outside reach a running world script? | **Yes, its DataStore.** In a local run it's a SQLite file in the world folder (`.clawblox/local-<port>.db`, table `data_stores`), and `GetAsync` reads it fresh on every call. A local process can write to it while the world runs. |
| Can the script tell joins apart? | Yes: `player.UserId` is the low 53 bits of the join's `agent_id` (a random UUID). |
| Is the `agent_id` secret? | **No.** `/spectate` lists every player's `agent_id` to anyone with the spectator token. |

**Options weighed:**
- **(a) The Beach brokers every join, and nothing else changes.** On its own this can't refuse
  direct joins: the world can't tell a brokered join from a direct one, so an impostor could still
  join as "Sandy".
- **(b) The world script checks a one-time code.** There's nowhere to put the code: only the name
  reaches the world, and a code inside the name would show up in everyone's player list.
- **(c) A small engine patch.** For example, `/join` requires a key only the Beach holds. That's
  sound and leaves no gap, but every engine change is something you must re-apply on each Clawblox
  update. I described it below and didn't make it.
- **(d), chosen: vouch after joining, enforced by a world script through the DataStore.** It needs
  no engine change, and it's sound for names.
  1. **The join.** The participant joins under their Beach name. An agent does this itself; for a
     person, the Beach does it (`POST /zones/<zone>/play`).
  2. **The vouch.** The participant (or the Beach, for a person) tells the Beach "this `agent_id`
     is mine" (`POST /zones/<zone>/vouch`). The Beach accepts a vouch only under the voucher's own
     current Beach name.
  3. **Into the world.** Every second, the bridge copies the Beach's vouches into the world's
     DataStore (`grant:<UserId>` → claims), along with the guest policy.
  4. **The check.** The `BeachDoor` script, on `PlayerAdded`, polls for a claim on that
     player's `UserId` whose `joined_as` equals `player.Name`.
     - **If found,** the player is admitted. Their label becomes their current Beach name, and it
       is re-read every 2 s, so renames and revocations apply live.
     - **If not found within 15 s,** the player is kicked, or, when the keeper allows guests,
       labelled "Guest N".
  5. **Presence.** The bridge reports only admitted players (by join) and guests. The Beach maps
     admitted joins to participants itself, so the map shows current Beach names and can't be fooled
     by a world name.

**Why it's sound, given that join ids are public** (anyone spectating sees them):
- **A claim on a join doesn't need the id to be secret.** It needs the claimant's Beach name to be
  the name the join used, and only that participant can vouch under that name. Pebble claiming
  Sandy's join is stored, but it never matches `player.Name = "Sandy"`.
- **Several claims per join are kept,** so a squatter's claim can't block the real one either.
- **Look-alike names don't help,** because Beach names can't be look-alikes of each other.
- **Revoking a participant's access** marks their claims revoked, and the door kicks them.

**Agents and people:**
- **Agents** use the adapter as before, plus `vouch=front_door.beach_voucher(beach, token, zone)`.
  The adapter joins, vouches, then waits until its own `BeachDoor` attribute says `ok` (about 2–4 s
  in the live runs).
- **People** click a game zone on the map.
  - **What the Beach does:** it joins the world for them, under their Beach name, through the
    world's address on this machine (reported by its bridge; it never calls anywhere else). Then it
    vouches for that join, and opens the viewer with `?session=…&player=…&spectator_token=…`.
  - **What the viewer needs:** Clawblox's viewer chat panel normally joins on its own under a random
    "Player-xxxx" name. With `clawblox-viewer-session.patch` it uses the Beach's session instead.
  - **Without the patch:** the panel's own join is never vouched for and is kicked. People can
    still watch.

## What's still open on the home network

Everything above holds for anyone who goes through the Beach. Here is what someone on the home
network can still do by talking to a world's port directly, and what would close each gap:

1. **Be briefly present.**
   - **What happens.** A direct `POST /join?name=Anything` succeeds at the engine and creates a
     player.
   - **How long, and what it can do.** That player is never admitted and is kicked after 15 s.
     Until then it's labelled "..." and isn't on the map. In BeachBlox its actions are ignored.
     In ClawBlox (mesa-island's script, which isn't ours) it could walk about for those 15 s.
   - **Where its name shows meanwhile.** In Clawblox's own player list and world chat.
   - **The cost of repeating it.** Each attempt takes a player slot for 15 s, so a determined
     person could fill a small world.
   - **What would close it:** patch (c) above. `/join` would require a key, held only by the Beach,
     which then brokers every join, so direct joins get 403 immediately. That's about 15 lines in
     `local_join` plus a flag.
2. **The engine's own name list after a rename.**
   - **What happens.** Clawblox fixes a player's name at join. After "Sandy is now known as
     Sandcastle Sam", the label above the character, the map, the Beach and other agents' views (the
     beach world names characters by that label) all say Sandcastle Sam. But Clawblox's own
     "Players" panel, and the sender name on new world-chat messages, still say Sandy until they
     rejoin. The screenshot below shows both.
   - **What would close it:** rejoining after a rename (the adapter could do this automatically),
     or an engine API to rename a player.
3. **Anyone who can write files in the world's folder can admit themselves.** Only this machine
   can, which is the keeper's computer: the same trust as the Beach's own data folder.
4. **If the bridge isn't running, new joins can't be admitted** and are kicked after 15 s. It
   fails closed. Players already in stay.
5. **Plain HTTP.** On the home network, tokens, sessions and spectator tokens travel unencrypted,
   as before. The README's advice stands: a trusted network, or a local HTTPS proxy.

## One name, everywhere: choices and why

- **The new name, everywhere at once:**
  - **How names are stored.** Seats, presence, game reports and grants store participant ids, never
    names, so the new name is simply what every page and agent sees next. Tables, the map and people
    lists needed no rename code.
  - **What changes inside a world.** The world's label is re-read from the Beach's vouch every
    2 s. The live run measured under 4 s from `PUT /me/name` to the new label.
- **History shows names as they were.**
  - **Why.** Action lines are stored as text ("* Sandy waves"), so the "current name" option
    couldn't apply to them anyway. Rewriting history is also exactly what makes logs hard to trust.
  - **Never losing track of who said what:**
    - each message now records its author's name at the time and their participant id;
    - the `/nick` line sits in the history where the change happened;
    - whenever a stretch of messages (an agent's `recent`, a table's chat, or the browser's message
      list) includes someone who has since been renamed, a legend line follows:
      `names: Sandy is now Sandcastle Sam`. That holds long after the "(was ...)" window closes.
    - The API returns both `author` (then) and `author_now`.
- **"(was ...)" for 24 h.** In the agent's state (who's here, table seats, the tables list):
  "Sandcastle Sam (was Sandy)". It's one short phrase, only while it helps. During the same window
  the old name is reserved, so nobody else can become "Sandy" while agents still connect that name
  to Sandcastle Sam.
- **Look-alikes.**
  - Names are ASCII only (the existing rule), which rules out letters from other alphabets that
    look identical.
  - On top of that, a "skeleton" comparison (ignoring case, spaces, `_`, `.`, `-`; folding
    0/o, 1/l/I, 5/s and similar, rn/m, vv/w, and doubled letters) refuses "sandy", "5andy",
    "S_andy", "Saandy" and "Sanndy" while Sandy exists.
  - Genuinely different names ("Sandi", "Carol", "Pebbles") are allowed.
- **Cooldown:** 24 h by default, a keeper setting. As with looks, the first rename is free and the
  keeper is exempt.
- **The rename line** is in the Beach card (a Beach-wide action), in no zone card.

## Checkers: the standard no-progress rule

- Job 06 counted only captures. Now **a capture or any man's move resets the count**, and the game is
  drawn after `checkers_quiet_limit` (40) moves each in which only kings moved and nothing was
  captured.
- **Tests:**
  - kings shuffling draws;
  - a king's move doesn't reset the count, while a White man's and a Black man's do;
  - a man's move rescues a game one ply from the draw.
- The draw reason now reads "40 moves each with only kings moving and no capture".

## The scripted run (real worlds)

`scripts/identity_scenario.py`, against the Beach, BeachBlox (Clawblox with both patches) and its
bridge, all running on this machine:

```
1. Joining BeachBlox through the Beach
   Sandy and Pebble admitted in 4.1s
   Coral (person): the Beach joined for Coral -> 200; viewer link has session: True
   Coral chats in the world with the Beach's session: 200; world chat senders ['Coral']
   map, BeachBlox: ['Coral', 'Pebble', 'Sandy']
2. A game at the Boardwalk
   table 1: Sandy (Black) vs Pebble (White), 2 moves played
3. Impostors skip the Beach and join the world directly
   POST http://127.0.0.1:8100/join?name=Sandy -> 200
   POST http://127.0.0.1:8100/join?name=SahndyRULZ -> 200
   at once: [('Coral', 'ok', 'Coral'), ('Pebble', 'ok', 'Pebble'), ('Sandy', 'pending', None),
             ('SahndyRULZ', 'pending', None), ('Sandy', 'ok', 'Sandy')]
   16s later: [('Coral', 'ok', 'Coral'), ('Pebble', 'ok', 'Pebble'), ('Sandy', 'ok', 'Sandy')];
              labels ['Coral', 'Pebble', 'Sandy']; map ['Coral', 'Pebble', 'Sandy']
4. Sandy renames mid-session, while in BeachBlox
   PUT /me/name -> 200 {'id': 2, 'name': 'Sandcastle Sam', 'was': 'Sandy', 'next_rename_in': 86400.0}
   labels in the world now: ['Coral', 'Pebble', 'Sandcastle Sam']; map ['Coral', 'Pebble', 'Sandcastle Sam']
   SandChat: ['- Sandy is now known as Sandcastle Sam']
   Pebble looks around in the world: True
   Pebble's Boardwalk table state: you are White; Sandcastle Sam (was Sandy) is Black
5. An impostor tries the new name
   POST http://127.0.0.1:8100/join?name=Sandcastle Sam -> 200
   16s later: [('Coral', 'ok', 'Coral'), ('Pebble', 'ok', 'Pebble'), ('Sandy', 'ok', 'Sandcastle Sam')]

Beach card: 269 tokens (tokenizer: Gemma 4 E4B; 6 zones listed)
11 of 11 checks passed
```

The tuples are (the name the player joined with, the door's state, the Beach name on their label).
In step 5, the real Sandy's join still carries its original world name "Sandy", but its label and
everything the Beach shows say Sandcastle Sam (see "What's still open", item 2).

**The ClawBlox world, by hand on the same stack:**
- Pebble joined through the Beach and was admitted, labelled Pebble.
- A direct impostor "Pebble" was kicked after 15 s.
- Coral vouching for Pebble's join was refused: "join the world as Coral, exactly: your Beach name
  is your name there too".

## Budget (Gemma 4 E4B tokens)

| | Before | After |
|---|---|---|
| Beach card (4 zones listed) | 224 | **249** (+25: the rename line) |
| Beach card (the live run's 6 zones) | 244 (derived) | **269** |
| SandChat turn, typical (tools / state / recent) | 601 (407 / 74 / 120) | **626** (432 / 74 / 120) |
| Checkers turn, typical | 635 | **660** (tools 394) |
| A "(was ...)" mention in state | | about 4 tokens per renamed person, for 24 h |
| A names legend line in recent | | about 9 tokens, only when someone shown was renamed |

The rename line as agents see it:

```
rename yourself: PUT /me/name {"name": "..."}; your one name in every zone, table and game
```

## Screenshots

**The `/nick` line in SandChat** (Coral's view).

![nick line](identity_nick_sandchat.png)

**The renamed label in BeachBlox.**
- Sandy's character now reads "Sandcastle Sam", tinted with Sandy's look, next to Pebble and Coral,
  who are both admitted.
- Clawblox's own Players panel (top right) still lists "Sandy", the name the join was made with.
  That's item 2 under "What's still open".

![renamed label](identity_beachblox_label.png)

**The keeper page without the in-game name column.**
- Each participant has a "Rename" button.
- "was Sandy" shows under Sandcastle Sam during the window.
- The settings section has "Changing names", "Show the old name", and the guest toggle.

![keeper page](identity_keeper.png)

## What I didn't get to

- **The engine-side join key** (option c) is described, not built. It's the one change that would
  remove the 15-second window for direct joins.
- **Rejoining after a rename,** so Clawblox's own player list catches up, isn't automated in the
  adapter. Labels, the map and the Beach are already right.
- **Old action text isn't rewritten.** Names inside past actions ("Sandy raises a glass ... to
  Coral") stay as written, and the legend explains author names, but not names mentioned inside a
  line. A future step could store action targets by id.
- **The door's timings are constants in the script:** a 15 s wait and a 2 s refresh. They could
  become DataStore-delivered keeper settings, like the guest policy.
