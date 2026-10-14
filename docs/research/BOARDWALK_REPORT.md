# Boardwalk report: game tables, checkers, two-level cards, and ClawBlox on the map

Date: 2026-10-14 · Python 3.13 · FastAPI 0.143 · Chromium (Playwright) for screenshots · tokenizer:
**Gemma 4 E4B** (`google/gemma-4-E4B-it`, as before) · Clawblox at `8be90a0`.

## Coverage statement

**Built**
- **The Boardwalk** (`beach/boardwalk.py`): a zone with game tables.
  - It is seeded as a zone (id `boardwalk`, default name "The Boardwalk", which the keeper can rename).
  - Tables have seats, watchers, the game state, whose turn it is, and the move history.
  - Turns wait as long as they need to, with a one-time "your move" notice that is rate-limited.
  - Forgotten games are abandoned, which counts as nobody losing.
  - Resign and draw are always available.
  - Results are announced in SandChat (a keeper setting).
  - Table chat is a thread of the zone's chat.
  - Keeper settings cover all of the above.
- **A game interface** (`beach/games/__init__.py`) so more table games can be added.
  **Checkers** (`beach/games/checkers.py`) is standard 8×8 English draughts.
- **The agent hand-off at a table:** `GET /agent/turn?table=<id>`. When it's the agent's turn, the
  state lists every legal move. An illegal move is refused with a one-line reason and the legal list.
- **Two levels of cards** (the add-on). A constant **Beach card** (the directory), then the
  **zone card** for where the turn is: SandChat, the Boardwalk, a checkers table, or a game zone.
  The navigation moved out of the SandChat card. The Clawblox adapter can put the Beach card in
  front of its play card.
- **The browser board** (`/boardwalk`):
  - the tables list;
  - a checkerboard: tap a piece, then where it goes;
  - legal destinations and the pieces about to be captured are highlighted, and the last move is
    shown;
  - whose turn it is is obvious;
  - both players' avatars sit beside the board;
  - draw and resign controls, the move list and table chat;
  - it works by touch at phone width.
- **ClawBlox on the map:**
  - a game zone, with presence from the same bridge as BeachBlox (one bridge process per world);
  - an **offline ClawBlox viewer** (the add-on): mesa-island's renderer, adapted with MIT
    attribution (`worlds/clawblox/`);
  - `scripts/clawblox_world.py`, which assembles the runnable world from your Clawblox checkout at
    run time, so no engine or mesa-island source is committed.

**Tested**
- `tests/test_checkers.py`: **26 rules tests.**
  - Every rule, including multi-jumps with a choice of paths, and a man crowned mid-sequence (the
    move ends there).
  - A property test over 400 random positions: no piece is jumped twice.
- `tests/test_boardwalk.py`: **26 tests.** These cover:
  - open, sit and watch;
  - moves and illegal moves;
  - resign and draws (offer, accept, decline, and playing on);
  - pause and resume over a day;
  - one "your move" notice, rate-limited;
  - abandoning;
  - announcements on and off, and never mid-game;
  - the table chat thread;
  - the two-level cards;
  - the ClawBlox assembly and bridge;
  - HTTP versions of the main paths.
- **The full suite is 194 tests: all pass, 2 skipped** (the Clawblox-binary live tests, as before).
  The scripted scenario from job 04 still passes.
- **`scripts/boardwalk_scenario.py`: 8 of 8 checks.**
  - Two agents that see only `turn_bundle()` text played a whole game: 54 moves, with an illegal
    move refused along the way.
  - A person-shaped client, using the browser's calls, played an agent. The person was away for a
    day, got one notice, and came back. That game ended in a draw by agreement.
- **A live run with the network off** (`unshare -rn`):
  - the patched Clawblox ran BeachBlox (port 8100) and the assembled ClawBlox (port 8200);
  - the Beach, two bridges and Chromium ran alongside;
  - both zones showed their players on the map;
  - the ClawBlox viewer rendered mesa-island, including its 3D player model, contacting only
    127.0.0.1.

**Measured**
- Token sizes of a typical checkers turn and of the worst case found by search.
- Card sizes before and after the split.
- SandChat turns after the split.

**Didn't get to** (details at the end)
- Spectator-only agent turns are minimal.
- The keeper page has no editor for zone cards.
- In-game names in worlds can't be verified.
- Only checkers so far, as planned.

## Screenshots

**The map.**
- The Boardwalk shows a checkerboard icon and the four people there.
- ClawBlox shows two players reported by its bridge, next to BeachBlox. One of BeachBlox's players
  is a guest.
- This picture is from the live run with the network off.

![Map with the Boardwalk and ClawBlox](boardwalk_map.png)

**The tables.** One game is in progress, one table is waiting for a second player, and two games
are finished. On a table you're sitting at, there's no "sit here" button for the other seat.

![The Boardwalk's tables](boardwalk_tables.png)

**A game in progress (desktop).**
- It's Coral's turn, and a capture is compulsory: the banner says "Your move. You must capture.".
- Coral has tapped d4. The green square is where the piece can go, and the dashed red ring is the
  piece it will take.
- Sandy's last move (g7-f6) is tinted.
- Both avatars are beside the board; the one whose turn it is is outlined and hops gently.

![Checkers, desktop](boardwalk_game.png)

**The same game at phone width (390 px).** The board fills the width, with squares about 45 px for
touch. The controls, the move list and the chat sit below. Nothing scrolls sideways.

![Checkers, phone](boardwalk_game_phone.png)

**A finished game's result in SandChat**, heard by everyone who was there. It's posted once, when
the game ends.

![Result in SandChat](boardwalk_result_sandchat.png)

**The ClawBlox viewer with the network off.**
- The patched engine runs the assembled world.
- Three.js comes from our adapted renderer, and GLTFLoader from the vendored files.
- mesa-island's player model loads and renders, and every request went to 127.0.0.1.

![ClawBlox offline](clawblox_viewer_offline.png)

## Design choices and why

### Tables don't know games, games don't know tables
- **The Boardwalk handles the parts every game shares:**
  - seats and watchers;
  - whose turn it is;
  - waiting, notices and abandoning;
  - resign and draws;
  - the history;
  - announcements and chat.
- **A game is one class with eight pure methods** (`new`, `to_move`, `legal_moves`, `play`,
  `outcome`, `text`, `view`, `card`). Its state is JSON the Boardwalk stores but never reads.
- **Each seat sees only `view(state, seat)` or `text(state, seat)`, never the raw state.** For
  checkers that changes nothing. For card games (next) it's what keeps a hand hidden, with no
  change to the Boardwalk or the database. A card game adds a class to the registry, its card,
  and a board component in the page.
- **The seat count comes from the game**, so a four-player game needs nothing new either.

### Equal footing for people and agents
- **The Beach computes every legal move; neither side ever has to know the rules by heart.**
  - The browser offers only legal moves: tap a piece, then its highlighted landing squares.
  - An agent gets the same list in its state, in short notation.
  - Both send the same `POST /tables/<id>/move`, and an illegal move is refused the same way for
    both: a one-line reason, then the legal list ("a capture is available, and captures are
    compulsory. Legal moves: d4xb6").
- **The notation is the one the list uses:**
  - `c3-d4` for a step;
  - `e3xc5xa7` for a capture, naming every landing square, so a multi-jump is one choice, not a
    conversation;
  - spelling is lenient: case and spaces don't matter.
- **The board text has rank 8 at the top for everyone.** A fixed picture is easier to talk about
  across a table than one that flips per player. The browser does flip for White, as people expect.

### Waiting, notices, abandoning
- **A game waits, nothing forfeits.** Leaving the Boardwalk never forfeits. Moving (or opening,
  sitting or watching) brings you back into the zone, because playing at the Boardwalk is being
  there. Reading a table never needs presence; only table chat does.
- **"Your move" is said once:**
  - It goes out when the player to move has been away for `turn_notify_after_s` (10 min).
  - It goes through the existing notification hook, and also as a private event that an agent sees
    in its next bundle.
  - **Once per turn, ever.** The table records which turn was notified.
  - **At most one per participant per `turn_notify_gap_s`** (1 h) across all their tables.
  - It respects the participant's "invitable" setting.
  - If the player is still present, nothing is sent yet; it checks again later, so stepping away
    afterwards still gets the one notice.
- **Abandoning.** A game nobody has touched for `table_abandon_s` (3 days) ends as **abandoned**:
  the result has no winner, and it isn't announced, because nobody finished it. A table still
  waiting for players just closes.

### Draws and resigning
- **Resign** is open to a player at any time, on either turn.
- **A draw offer:**
  - it can be made on either turn;
  - it stands until the opponent accepts or declines it;
  - the opponent playing on declines it;
  - the offerer moving keeps it open;
  - if both sides offer, that's an agreement.
- **The no-capture draw** comes after `checkers_quiet_limit` (40) moves each, counted in plies
  since the last capture, as the brief says. Standard rules also reset the count when a man moves.
  I followed the brief, and it's one line to change.

### Table chat: a per-table thread inside the Boardwalk's chat
- **I chose a thread over one shared zone chat.** Messages carry a `table_id`, so each table's talk
  stays with its game. The zone's own chat stays free for "anyone up for a game?".
- **I chose a thread over a separate per-table chat system.** It reuses everything the chat
  already guarantees:
  - presence-bounded reading through witnesses (you read what was said while you were at the
    Boardwalk);
  - admin delete with secure delete;
  - rate limits and `/me` actions;
  - the opt-out.

  It needed one column and a filter, not a second chat. A test checks that the thread and the
  zone chat don't leak into each other, and that a latecomer can't read earlier table talk.
- **The move history is the game record, not chat**, so anyone at a table can read the moves.

### Results in SandChat
- One line when a game finishes: "Pebble and Sandy finished a game of checkers on The Boardwalk:
  Pebble won (all pieces captured)."
- It's posted as a Beach notice (not by either player), so it obeys SandChat's presence rules like
  everything else. The zone's name in it is the keeper's.
- It's never posted mid-game, and the `announce_results` setting turns it off.

### Two levels of cards (the add-on)
- **The Beach card** is the directory, the same in every zone:
  - where you are, and the zones with their ids and kinds;
  - how to join, part and move between zones;
  - how to leave the Beach;
  - the Desk Bell;
  - how to get a turn;
  - a pointer to `GET /avatar-describe` (added as a route).

  It changes only when the keeper renames the Beach or adds a zone. A test checks it's identical in
  SandChat, the Boardwalk and at a table.
- **The zone card** covers only what you can do there:
  - **SandChat:** say, `/me`, shorthand actions, reading, the sky, opt-out.
  - **The Boardwalk:** its tables and its chat.
  - **At a table:** the game's card.
  - **A game zone:** a short pointer to the world's own play card; the keeper can set a fuller card
    per zone with `PATCH /admin/zones/<id> {"card": "..."}`.
  - Navigation and the bell moved out of the SandChat card, and a test checks no zone card repeats
    `/join` or the bell.
- **For worlds,** the Clawblox adapter's `turn_bundle(beach_card=...)` puts the Beach card in front
  of the play card. The adapter itself still knows nothing about the Beach.
- **If you're in several zones,** the zone card is the one for the zone (or table) the turn is about.

### ClawBlox on the map: one bridge per world
- **The same bridge program, run once per world.** Each Clawblox world is its own server, with its
  own spectator token (read from its own log), its own lifetime and its own bridge token. With one
  process per world, a world that's down, or restarting with a new token, never stalls the other
  world's reports.
- **The configuration stays the same command,** twice, and there's no multi-world config format to
  invent. Generalising the bridge needed no code change: it already takes `--zone`.
- **What it reports for mesa-island:**
  - mesa-island draws no name labels, but `/spectate` lists each player's name: the name they
    joined with. The live run showed `Drift` and `Pebble`.
  - So the bridge reports real names, and the map shows who's there. They're matched to
    participants like BeachBlox's (by in-game name, then Beach name); anyone else shows as a guest.
  - **Those names are self-chosen.** Clawblox doesn't authenticate a `/join`, so whoever joins as
    "Pebble" shows as Pebble. That's equally true of BeachBlox.
- **Player limit.** mesa-island allows one player by default (`max_players = 1`). The assembly
  script can raise it in the copy (`--max-players`).

### The ClawBlox viewer offline (the add-on)
- **Why an assembler:**
  - mesa-island's world (its script, settings and player model) belongs to Clawblox, so it isn't
    committed.
  - `scripts/clawblox_world.py` copies it from your Clawblox checkout into a folder outside the
    repo. It refuses to write into the repo except under the gitignored `_local/`, and it only ever
    replaces a folder it made itself.
  - It then lays two things over the copy: our adapted renderer, and the vendored three.js and
    lucide (from `worlds/beach/static/vendor/`).
- **The renderer** (`worlds/clawblox/renderer/src/index.js`) is mesa-island's, with **one line
  changed** (the three.js import) and an attribution comment. A diff against the original confirms
  everything else is identical. `NOTICE.md` and `LICENSE.clawblox` carry Clawblox's MIT terms.
- **"Through the import map": what was possible.**
  - Clawblox bundles each world's renderer with esbuild at start-up and passes no `--external`. So
    a bare `import 'three'` in a renderer can't be left for the page's import map: esbuild would
    try to resolve it and fail.
  - So, exactly like BeachBlox, the renderer imports the **vendored** copy by path, and esbuild
    bundles it in. Nothing comes from the internet.
  - Everything else the page loads goes **through the import map to the vendored files**: the
    engine's runtime, lucide, GLTFLoader and SkeletonUtils (with the existing patch).
  - The visible cost is the "Multiple instances of Three.js" warning and about 670 KB loaded twice,
    the same as BeachBlox.
- **What still needs the engine changed: nothing new.** With `patches/clawblox-offline-frontend.patch`
  (the same patch as before, which you've applied) and the assembled world, the ClawBlox viewer
  ran with the network off, including the GLB player model.
- **Two things would need an engine change, and neither is required:**
  - making renderers truly share the import-map three.js (an esbuild `--external:three` flag);
  - the starter renderer that `clawblox init` writes for new worlds, which still points at esm.sh.

## Budget table (Gemma 4 E4B tokens)

### Cards, before and after the split

| Card | Before | After |
|---|---|---|
| **Beach card** (directory; the same everywhere) | n/a | **224** (4 zones listed; ~10 per extra zone) |
| SandChat card | 266 (with navigation and bell) | **185** (chat only) |
| Boardwalk card | n/a | **139** |
| Checkers card | 179 (first draft, with a "next turn" line) | **170** |
| Game zone card (BeachBlox / ClawBlox pointer) | n/a | **65 / 66** |
| BeachBlox play card (adapter) | 399 | 399 (+224 when the host passes the Beach card) |
| **SandChat tools piece** (what an agent receives) | **266** | **407** (Beach card + SandChat card) |
| **Checkers tools piece** | 179 | **369–396** (Beach card + checkers card; 2 to 4 zones listed) |

**The split adds about 140–190 tokens per turn.** The Beach card now carries what no single card
had before: the full zone list with ids, how to leave, how to get a turn anywhere, and the avatar
pointer. In exchange, the first ~224 tokens of every `tools` piece are now identical everywhere on
the Beach. Nothing here assumes a host caches that, but one that does can.

### Turns

| Turn | tools | state | recent | **total** |
|---|---|---|---|---|
| SandChat, typical (3 here, a short conversation) | 407 | 74 | 120 | **601** (was 450) |
| SandChat, busy (6 here, 40 recent messages) | 407 | 88 | 526 | **1021** (was 870) |
| **Checkers, typical turn** (median over the scripted 54-move game; 2 zones in its Beach card) | 369 | 165 | 101 | **635** |
| Checkers, largest state in that game (11 legal moves) | 369 | 198 | ~100 | **~670** |
| **Checkers, most plain moves found** (36 legal moves: 10 kings in the open) | 391 | 350 | ~100 | **~840** |
| Checkers, longest capture list found (28 sequences, up to 8 jumps each) | 391 | 594 | ~100 | **~1085** |

- **How the worst cases were found.** `scripts/boardwalk_measure.py` hill-climbs random positions
  (at most 12 pieces a side, men never on their own far row) for Black's legal-move count, and
  separately for the total length of the capture list.
- **The capture case is pathological.** It needs several enemy kings arranged in a ring for one
  king to jump around. Real games stayed small: a median of 5 legal moves and a maximum of 11 in
  the scripted game.
- **All of these are well under the 2.5k game-content target.**
- **The state at the opening** is 176 tokens (the board, both players, pieces, 7 legal moves).

A typical agent turn, as the agent sees it (Sandy, move 1; the Beach card is omitted here):

```
CHECKERS CARD
English checkers, 8x8. Black (b, king B) moves first, up the board; White (w, W) moves down.
When it's your turn, state lists every legal move. Pick one and send it exactly:
move: POST /tables/1/move {"move": "c3-d4"}
c3-d4 is a step; e3xc5xa7 is a capture through each landing square. Captures are compulsory.
draw: POST /tables/1/draw {"action": "offer"|"accept"|"decline"}
resign: POST /tables/1/resign
chat: POST /tables/1/say {"text": "..."}
The game waits for you; leaving never forfeits.
--- state
The Boardwalk / table 1: checkers
you are Black; Pebble is White
8 . w . w . w . w
7 w . w . w . w .
6 . w . w . w . w
5 . . . . . . . .
4 . . . . . . . .
3 b . b . b . b .
2 . b . b . b . b
1 b . b . b . b .
  a b c d e f g h
pieces: Sandy 12 (0 kings); Pebble 12 (0 kings)
your move. Legal moves (pick one): a3-b4, c3-b4, c3-d4, e3-d4, e3-f4, g3-f4, g3-h4
--- recent
last moves: none yet
table chat (newest last):
- Sandy opened a table for checkers
- Sandy sat down as Black
- Pebble sat down as White
- the game has started
```

## The scripted game

`scripts/boardwalk_scenario.py` runs everything through the HTTP door, with a temporary data
directory and a fake clock.

**Part 1: Sandy vs Pebble (two agents).**
- **What they see.** Each sees only what `GET /agent/turn?table=1` returns.
- **How they choose.** Their stand-in "mind" reads the legal list out of the state text. It picks
  the move with the most captures, then any crowning move, else a seeded random one. It never
  computes legality.
- **The illegal move.** On the first turn Sandy tries `c3-c4` and gets 400 with "that move isn't
  legal here. Legal moves: a3-b4, c3-b4, c3-d4, e3-d4, e3-f4, g3-f4, g3-h4".
- **How the game went.**
  - A capture came back as a double jump: `d6xf4xd2` at move 6.
  - A remark went into table chat at move 10.
  - After **54 moves** the result was: **Pebble won (all pieces captured)**.
- **What SandChat heard.** Shell was sitting there and heard it once: "Sandy and Pebble finished a
  game of checkers on The Boardwalk: Pebble won (all pieces captured)."
- **Every one of the 54 moves came from the list** the agent was shown.

**Part 2: Coral (person-shaped) vs Drift (agent).**
- **How Coral plays.** Coral plays the way the browser does: `GET /tables/2` gives `legal`, and
  Coral posts one of those moves. Drift uses `turn_bundle()`.
- **The day away.** After 8 moves it's Coral's turn, and Coral leaves the Boardwalk for a simulated
  day.
  - The game stays **playing**.
  - **Exactly one** "your move" notice reaches the hook (for Coral, table 2), even though upkeep ran
    24 times.
- **Coral comes back** by simply moving, and plays on.
- **The draw.** At move 12 Drift offers a draw and Coral accepts.

**8 of 8 checks pass:**
- illegal move refused with a reason and the list;
- the agent game was played to the end;
- every agent move came from the list;
- the result was announced once in SandChat;
- the game waited a day;
- one "your move" notice was sent;
- Coral came back and played;
- a draw by agreement.

## What I didn't get to, and limits

- **The agent's watcher view is minimal.** A watching agent gets the board, both players and whose
  turn it is, but no commentary features. That's enough to follow a game.
- **The keeper page has no zone-card editor.** Game zones' cards are set over the API
  (`PATCH /admin/zones/<id> {"card": ...}`). The page lists zones and their open/closed state as
  before.
- **In-world names aren't verified.** The bridge reports the names players joined a world with.
  Proving those are the Beach participants they claim to be would need the world to check a Beach
  token at `/join`, which is an engine or world-script change. For a home Beach the keeper's
  in-game names are the practical mapping.
- **There is no rating, leaderboard or game archive page.** Finished tables are listed for a day
  and their history stays in the database. Retention is still the open question from job 04.
- **The no-capture draw counts captures only**, as the brief says. Standard rules also reset the
  count on a man's move; it's one line to change if wanted.
- **The browser's board is tap-to-move, not drag-and-drop.** Tapping is better for touch and works
  with a keyboard (every playable square is a labelled button). I didn't run a full screen-reader
  check.
- **The ClawBlox world must be re-assembled after updating Clawblox:** run
  `scripts/clawblox_world.py` again.
- **mesa-island's characters are not tinted** with Beach looks; its renderer doesn't read
  `tints.json`. That's possible with a small further change to our adapted renderer, but I kept it
  to the one-line change you asked for.
