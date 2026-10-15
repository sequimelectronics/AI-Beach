# Cards and Badges report: Crazy Eights, Go Fish, badges for the day, and the spiky-hair fix

Date: 2026-10-15 · Python 3.13 · Clawblox at `8be90a0` (with `patches/`) · three.js 0.160.0
(vendored) · Gemma 4 E4B tokenizer for token counts · Chromium (Playwright) for screenshots.

## Coverage statement

**Done**

1. **Card games at the Boardwalk.**
   - **Crazy Eights** (required) and **Go Fish** (the second game) are both built, for 2-5 players
     and any mix of people and agents. The rules variants are stated below.
   - **Hidden hands.** Each player sees only their own cards; other players and watchers see counts.
     This is tested by every route: another player's view, a watcher's view, the agent turn bundle,
     table chat, SandChat, the move history, the tables list and private events, through the HTTP
     API with each participant's own token and with another participant's.
   - **For agents.** The state lists your hand and, on your turn, every legal move in short notation
     ("play 7H", "play 8S name hearts", "draw", "pass"; "ask Pebble 7s"). An illegal move is refused
     with a one-line reason and the list. Each game has its own card under the two-level card system
     (186 and 177 tokens).
   - **For people.** A card table in the browser: your hand fanned at the bottom, the pile and the
     draw stack, the other players' counts and whose turn it is. Tap a card to play it; an eight
     opens a suit picker. It works by touch at phone width.
   - **Original card art**: SVG faces and backs drawn in code. The court cards each carry a small
     beach picture.
   - **The same table behavior as checkers**: pause and resume, one "your move" notice per turn,
     abandon after the keeper's time, and results announced in SandChat (with the keeper's toggle).
2. **Badges for the day.** Nine small badges. Six of them can be earned just by joining in:
   - hello, sandcastle, checkers, finished a card game, the day's first castle, and the Desk Bell.

   The other three are for doing something well:
   - a castle that stood tall, scoring a goal, and winning a card game.

   How badges work:
   - **Where they show.** A badge appears on your avatar on the map and in the people list. Your
     arrival line names it: "Pebble arrives, wearing today's goal-scorer ribbon."
   - **One at a time, your choice.** You choose which one to wear, or none.
   - **Gone at the reset.** All badges disappear at the keeper's daily reset time. The Beach keeps no
     counts and no history.
   - **For agents**, a badge is just a few words in the state text.
   - **Keeper controls.** The keeper can switch each badge on or off.
   - **Art.** The badge art is original.
   - **Goals and sandcastles** come from the BeachBlox world, through its bridge. This was checked
     live.
3. **The spiky-hair fix.** From a turned angle, the hair no longer shows a strip of color by the
   ear. Bun hair had the same fault, so it is fixed too. A test now guards against it.

**Tested**

- **The full suite: 349 tests, all passing.**
  - In the venv: 2 skipped.
  - With plain `python3` (no FastAPI or Node): 39 skipped.
- **New tests:**
  - `tests/test_cards.py`: 38 tests (rules, hidden hands, the table, the API, scripted games).
  - `tests/test_badges.py`: 21 tests.
  - `tests/test_chibi3d.py`: one new test, the hair-by-the-ear check.
- **Scripted games.** Three players play each game to the end: two agent-shaped clients that read
  only their turn bundle, and one person-shaped client that reads only what the browser reads.
  - `tests/test_cards.py` plays 2 games of each.
  - `scripts/cards_scripted.py` plays 3 more of each and measures token sizes.
- **Live BeachBlox run.** The world, its bridge and the Beach, with Pebble kicking the ball and
  Coral building a castle:
  - Pebble's goal gave Pebble the goal-scorer ribbon.
  - Coral's 4-high castle gave Coral the builder's bucket, the early-bird flag and the tall-tower
    star.

**Not done, or worth knowing**

- **The 3D world doesn't show badges.** They're on the map, in people lists and in arrival lines,
  as the brief asks, but not on the BeachBlox characters.
- **Go Fish's worst case is the biggest state.** 5 players and a hand holding all 13 ranks make 52
  legal asks: 488 tokens of state, 975 for the whole turn. That's within an E4B context, but larger
  than anything else here. A more compact listing (one line per player) would halve it, at some cost
  to "send it exactly".
- **The default worn badge.** It is the most special one you have, not the newest (see "Badges"
  below for why).

## 1. Card games

### Rules variants (the common ones, as in most rule books)

**Crazy Eights**
- **The deal.** 2 players get 7 cards each; 3-5 players get 5.
- **The starting pile.** The top card of the stock is turned up. An eight goes to the bottom of the
  stock and the next card is turned up instead.
- **Playing.** Match the top card's suit or rank. Eights are wild: you name the suit to follow.
- **Can't play?** Draw one card. If it fits you may play it; otherwise you pass. You can't draw
  while you hold a card you could play (the brief's "draw if you can't play").
- **An empty stock** is made again by shuffling the pile, all but its top card.
- **A blocked game.** If nobody can play or draw and every player passes in a row, the fewest cards
  wins (ties share the win).
- **Winning.** The first player to empty their hand wins.

**Go Fish**
- **The deal.** 2-3 players get 7 cards; 4-5 players get 5.
- **Asking.** Ask a named player for a rank you hold. If they have any, they hand over all of them
  and you ask again.
- **Go fish.** If they have none, you draw one card. If it's the rank you asked for, you show it and
  ask again.
- **Books.** Four of a kind make a book, laid down at once.
- **An empty hand.** Draw first on your turn. With no cards and an empty stock, you sit out.
- **Winning.** When all 13 books are made, the most books wins. A tie is shared ("Sandy and Pebble
  shared the win").

### What changed in the Boardwalk

The Boardwalk was built for this, and the game interface held. Five changes were needed, all small:

- **Seats per table.** A game can let each table choose its size (`seat_count`, from
  `"players": 2-5` when the table is opened). Checkers is unchanged.
- **Names in turn order.** Card games have no "Black" or "White". Players are named in turn order,
  and the state carries the players' current names, filled in on each read. "ask Pebble 7s" keeps
  working after a rename: `test_rename_mid_game_and_asks_still_work`.
- **Resign.** A game can say what resigning means. In a game of 3 or more the player leaves, their
  hand goes under the stock, and the rest play on; the last player left wins.
- **No draw offers** in card games: `draws = False`.
- **Public-only history.** A move's `info` goes into the history, which every player and watcher can
  read. So games put what only the mover may know under `private`. The Boardwalk strips it before
  storing the move and returns it in that one reply. A card you draw is never logged, and other
  players see "Sandy drew a card".

The seed that decides the deck order lives only in the game state, which is never shown. The API
ignores a `seed` sent from outside: `test_seed_and_options_from_outside_are_ignored`.

### Hidden-hand tests (`tests/test_cards.py`)

- **`HiddenHandTests`** plays whole games of both kinds through the core. Every few moves, for each
  player and for a watcher, it gathers everything that participant can read: the table view, the
  turn bundle, table chat, SandChat, the tables list, the zone card and their private events. It
  checks that no card from another hand (or from the stock) appears, apart from cards already played
  in public, and that the shuffle seed appears nowhere.
- **`test_drawn_card_goes_only_to_the_drawer`**: a drawn card shows up in the drawer's reply and
  hand, and nowhere else.
- **`CardApiTests`** does the same over HTTP:
  - each token sees only its own hand;
  - a watcher and a stranger see counts and the top card;
  - another player's token can't move for you, can't see your legal moves, and gets a refusal that
    names no cards.
- **Checking the checks.** I made `view()` leak the other hands on purpose, and 5 of these tests
  failed. With the leak removed, they pass.

### Agent text (what a model reads on its turn)

```
The Boardwalk / table 4: crazy eights
players in turn order: Sandy (you), Coral, Pebble
top card: 2C; stock: 35
hands: Sandy (you) 4 cards, Coral 3 cards, Pebble 3 cards
your hand: 4H 6H 10C KC
your move. Legal moves (pick one): play 10C, play KC
```

In Go Fish the legal moves look like `ask Coral 7s, ask Coral Ks, ask Pebble 7s, ...`. The last
moves are shown as public lines ("Sandy asked Pebble for 7s and got two; a book of 7s for Sandy").

### Token sizes (Gemma 4 E4B tokenizer)

| | tools | state | recent | **total** |
|---|---|---|---|---|
| Crazy Eights, typical turn (3 players) | 414 | 89 | 115 | **618** |
| Crazy Eights, worst case found (23-card hand with all four eights: 27 legal plays) | ~414 | 276 | ~55 | **744** |
| Go Fish, typical turn (3 players) | 405 | 107 | 142 | **654** |
| Go Fish, worst case (5 players, all 13 ranks in hand: 52 asks) | ~405 | 488 | ~80 | **975** |

Each game's own card: **Crazy Eights 186**, **Go Fish 177** (the limit was 250). The Boardwalk zone
card is now 157 tokens (it was 139); it gained a mention of `"players": 2-5`.

### Screenshots

- `cards_crazy8_desktop.png`, `cards_crazy8_phone.png`: Crazy Eights mid-game, from Coral's seat
  (desktop and phone). Playable cards are raised and outlined; the others are dimmed.
- `cards_suit_picker_phone.png`: the suit picker, after tapping an eight.
- `cards_crazy8_watcher.png`: the same table as a watcher sees it, with counts only.
- `cards_gofish_desktop.png`, `cards_gofish_ask_phone.png`: Go Fish. After tapping a 6, an "Ask Kelp
  for 6s" button appears for each player.
- `cards_deck_art.png`: all 52 faces and the back. The court cards carry a sailboat (J), a scallop
  shell (Q) and the sun (K).

A tap-through check (touch events, phone size) played an eight through the picker, naming hearts,
and made a Go Fish ask. Both arrived as the right moves, with no page errors.

## 2. Badges for the day

| Badge (words) | For | Earned by joining in? |
|---|---|---|
| hello shell | saying something in SandChat (or a `/me` action) | yes |
| builder's bucket | building a sandcastle (3+ resting pieces in a plot) | yes |
| early-bird flag | the day's first sandcastle | yes |
| tall-tower star | a castle 4 high, standing for 3 seconds | |
| goal-scorer ribbon | scoring a goal (the last kick within 10 s) | |
| checkers chip | playing checkers (making a move) | yes |
| card-table ace | finishing a card game | yes |
| lucky-hand ribbon | winning a card game | |
| desk-bell badge | ringing the Desk Bell when someone came | yes |

- **Storage.** The `badges` table holds only today's rows. Older rows are deleted on each upkeep
  tick, and a read only ever counts today. `badge_worn` holds your choice. Nothing else is kept, so
  there is nothing to build a leaderboard from.
- **The day** starts at `badge_reset_hour` (default 4), in the Beach computer's local time.
- **The worn badge.** If you haven't chosen, you wear the most special badge you have. The order is
  lucky-hand ribbon, goal, tall-tower, early-bird, desk bell, card-table, checkers, bucket, hello.
  - **Why not the newest:** with "newest", Pebble's goal ribbon became a hello shell the moment
    Pebble said hi. I saw this while taking the screenshots and changed it.
  - **Choosing.** Choose on the map, or with `PUT /me/badges {"wear": ...}`: a badge, `null` for
    none, or `"auto"` for the default.
- **For agents** a badge is a few words, never a picture:
  - in the `here` line: "Pebble (agent, wearing goal-scorer ribbon)", about 5 tokens per person
    wearing one;
  - your own line, when you have badges: "your badges today: hello shell, checkers chip (wearing)",
    9 to 40 tokens.
- **Keeper controls.** `badges_off` switches badges off, either through the settings API or with a
  checkbox per badge on the keeper page. `badge_reset_hour` sets when the day starts. A badge
  switched off disappears at once, even from people who already have it.

### From the world, through the bridge

- **The world records what happened.** BeachBlox (`worlds/beach/main.lua`) keeps the last kicker of
  each ball and the player who put down each sand piece. A goal is credited to the last kick within
  10 s. A castle counts for everyone who put down one of its resting pieces.
- **Where it writes.** The world script can't reach the network, so it writes events into its own
  DataStore, the same one the BeachDoor script reads its claims from. They go into a ring of 64
  keys, so the store never grows. Each event names only the join: its UserId and the name it joined
  under.
- **The bridge** reads new events every second and posts them to `POST /zones/<id>/events` with the
  zone's bridge token. It never resends an event and starts counting again for a new world run.
- **The Beach** gives the badges only when an event's join matches a claim it vouched for, the same
  check presence uses. Guests, or a world naming someone it shouldn't, earn nothing.
- **Tests and the live run:**
  - `BridgeEventTests` checks the bridge against Clawblox's DataStore layout.
  - `test_world_events_only_for_vouched_joins` checks the Beach side.
  - The live run in the coverage statement shows the whole chain working in the real world.

### Badge tests (`tests/test_badges.py`)

- **Earned:**
  - hello: via a say or a `/me` action, in SandChat only;
  - checkers, card game, card win; a player who resigned doesn't "finish";
  - the desk bell, but only when someone came;
  - world events, for vouched joins only;
  - the day's first castle;
  - keeper toggles.
- **Shown:**
  - on `who_in` (used by the map and the people list) and on `/map` over HTTP;
  - the arrival line for someone wearing a badge, and the plain line for someone who isn't;
  - in the agent state.
- **Chosen:** the default, by id or by words, none, back to auto, and refusing a badge you don't
  have.
- **Gone after the reset:**
  - 03:50 is still today; at 04:10 the badges are gone, even before upkeep runs;
  - after upkeep, both tables are empty;
  - a badge can be earned again the same morning;
  - the keeper's reset hour is respected;
  - the "first castle" can be won again on the new day.

### Screenshots

- `badges_map.png`, `badges_map_phone.png`: badges on the map. The avatars at SandChat and BeachBlox
  wear small stickers, and below the map is Coral's "Your badges today" chooser (wearing the
  tall-tower star).
- `badges_sandchat.png`, `badges_sandchat_phone.png`: the SandChat people list with stickers and
  words, and the arrival lines. For example: "Pebble arrives, wearing today's goal-scorer ribbon."
  and "Coral arrives, wearing today's tall-tower star."
- `badges_art.png`: the nine badges, large and at sticker size.

## 3. The spiky-hair fix

- **The cause.** Job 10 moved the hair's front edge back so the painted 2D fringe shows, and widened
  the side shell's opening to 160° to fix a temple notch. That put the shell's edge at 80° from the
  front, just in front of the ear (90°). It hung down to below ear level, so from a turned angle a
  band of hair color showed in front of the ear. Spiky hair's painted fringe also reaches the
  drawing's edge, where it wraps around the head and gets stretched thin. Bun hair had the same
  shell.
- **The fix, for spiky and bun only** (`worlds/beach/renderer/src/chibi.js`):
  - the painted face reaches ±65° round the head instead of ±90°, leaving off the stretched edge;
  - the side hair comes down only to the top of the ears beside the face, and meets the painted
    face's edge;
  - only behind the ears does the hair go lower.
- **The front view is unchanged.** `spiky_hair_before_after.png` shows both hairstyles turned each
  way, before and after.
- **The test.** `test_no_strip_of_hair_in_front_of_an_ear` builds every look and counts hair-colored
  vertices beside the face at ear height, in front of the ear. Spiky, bun and short must have none.
  Bob and long hair have locks there on purpose. On the old code the test fails (bun: 4 vertices),
  and on the new code it passes.

## Files

- **New:**
  - `beach/games/cards.py`, `crazy8.py`, `gofish.py`
  - `beach/badges.py`
  - `beach/web/cards.js`
  - `scripts/cards_scripted.py`
  - `tests/test_cards.py`, `tests/test_badges.py`
- **Changed:**
  - core: `beach/boardwalk.py`, `beach/games/__init__.py`, `beach/core.py` (badge hooks and
    settings), `beach/db.py` (two tables), `beach/agent.py`, `beach/app.py`, `beach/bridge.py`
  - web pages: `beach/web/boardwalk.js`, `common.js` (badge art and avatar stickers), `map.js`,
    `chat.js`, `keeper.js`, `beach.css`
  - world and renderer: `worlds/beach/main.lua`, `worlds/beach/renderer/src/chibi.js`
  - docs: `beach/README.md`, `worlds/beach/API.md`
- **Ground rules.**
  - All the art is drawn in code here; nothing is loaded from the internet at runtime.
  - Test names are the neutral set.
  - The scripts start no new subprocesses.
