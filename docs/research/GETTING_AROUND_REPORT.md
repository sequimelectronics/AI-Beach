# Getting Around report: the bar, leaving, watching a world, and words

Date: 2026-10-15 · Python 3.13 · Clawblox at `8be90a0` (with `patches/`) · Gemma 4 E4B tokenizer
for token counts · Chromium (Playwright) for screenshots and the browser test.

This job fixes what the first live play test found: getting around, watching a world, and wording.

## Coverage statement

**All three sections are done**, in the order of the brief. Each item was tested, and the world
items were also checked live against a real BeachBlox run.

1. **Getting around and leaving.**
   - **The bar.** It lists every zone, game worlds included, with a pin on each zone you're in, on
     every page.
   - **Game worlds.** Each world has its own Beach page: the bar, then Play / Watch / Leave, then
     the world's viewer.
   - **Your picture** opens a menu with **My look** and **Sign out**.
   - **Leaving.** A finished table offers **Leave table**. The Boardwalk pages have **Leave The
     Boardwalk**.
   - **Idle auto-leave says so.** The pin follows, the time is the keeper's setting, and the cards
     say it.
   - **The map fits 1920×1080 at 100% zoom.** Who's where and the badges sit in a column beside it,
     and the phone layout still works.
   - **Map wording.** The "quiet" line counts the Boardwalk. A zone you're in says so and offers
     Leave.
   - **SandChat** grays out the target box for actions with no target.
   - **Renaming away from the default "Beach-keeper"** shows no "(was ...)".
2. **Watching a world.**
   - **Play or Watch.** Watch gives you a visible spot, a lifeguard chair with your name on a board,
     and no body.
     - Arrivals are announced in the world.
     - Agents see who's watching, in a few words.
     - A watcher's viewer chat is read-only.
   - **The idle kick.** Watchers are never idled out. A player the world removes is told, and an
     agent's next action says what happened instead of quietly making a new character.
   - **Ghost bodies.** Fixed at the root, with an engine patch: removed players' bodies now leave
     open viewers. The renderer also guards against it.
   - **The replay-only "Agent messages" button** is hidden in live play.
   - **World facts** count the people actually in the world, playing or watching.
3. **Words.**
   - **American English** everywhere people or agents read, with a test that fails on British
     spellings. Renamed identifiers keep their old names working.
   - **Desk Bell → Gather Bell** wherever it's seen.
   - **My look labels.** "Hair style" sits next to Hair color, and "Clothing theme" next to
     Accessory.
   - **No Boardwalk-wide chat.**
   - **The words the pages share** are gathered in one file.

**Tested.**
- **The full suite: 391 tests, all passing.**
  - In the venv: 2 skipped.
  - With plain `python3` (no FastAPI or Node): 384 run, 66 skipped.
- **New tests:**
  - `tests/test_getting_around.py`: 25 tests.
  - `tests/test_spelling.py`: 3.
  - `tests/test_pages_browser.py`: 7, in a real Chromium; skipped without Node and Playwright.
  - New tests in `tests/test_beach_adapter.py` and `tests/test_identity.py`.
- **Live checks** with `scripts/watch_live.py`:
  - ghost bodies, before and after the patch;
  - the idle limit, against a world whose idle limit was cut to 40 s.

**Not finished, or worth knowing.** Details are in the section at the end:
- **Page text.** Only the shared and new page text moved into `web/words.js`. The older pages still
  carry their own words.
- **The old research reports** keep the name "Desk Bell", because they record what happened then.
- **The hook's event id** stays `"desk_bell"`.
- **Chatting in a world isn't activity** to the engine's idle limit.

## 1. Getting around and leaving

### The bar: every zone, a pin where you are, on every page

`web/common.js` draws the bar from `GET /map`. The bar now lists every zone:
- SandChat;
- the Boardwalk;
- every game world;
- any other chat zone.

They appear in the same order as on the map. Each zone links to its page:
- `/chat?zone=` for a chat;
- `/boardwalk?zone=` for a zone with tables;
- `/world?zone=` for a game world.

`GET /map` now gives each zone a `you` field: `"here"` (you're in that chat), `"playing"`,
`"watching"`, or `null`. The bar shows a small red pin on each zone you're in. A screen reader hears
"(you're here)", "(you're playing)" or "(you're watching)". The bar redraws every 10 s, and at once
after any private event, so a pin goes away soon after an idle auto-leave. Closed zones are shown
dimmed. On a phone, your name and picture form the first row, and the zones form a row below it that
you can swipe.

### The picture menu

**Your picture** is now a button that opens a small menu:
- **My look**
- **Sign out**

Both have left the main bar. The menu closes on Escape or on a click outside it.

![The bar with pins and the picture menu open](getting_around_bar_menu.png)

### A game world's Beach page

**What changed.** Opening a world used to leave the Beach entirely. Now the world has its own page,
`/world?zone=<id>`:
- the bar;
- the world's name, with **Play**, **Watch** and **Leave** (or **Stop watching**);
- a line saying where you are: "Your character is in BeachBlox. The world takes out anyone idle for
  5 minutes.";
- the world's own viewer, framed below.

**Before you choose.** The page doesn't frame the viewer until you pick Play or Watch, so nobody is
in a world unseen. The map's Play and Watch buttons open this page.

**Security.** The page's Content-Security-Policy allows framing that one world's viewer origin
(`frame-src`), and nothing else. Every Beach page still refuses to be framed itself.

**Engine patches.** The viewer needed two small engine-side changes, both in
`patches/clawblox-viewer-beach-page.patch`, described in section 2.

![A game world under the Beach bar](world_page_playing.png)

### Leave table, and Leave the Boardwalk

**Leave table.** A finished table now offers **Leave table** next to **Back to the tables**. It calls
`POST /tables/<id>/leave`:
- before the game starts, it stands you up;
- it stops you watching;
- during a game, it refuses with "this game is still on and waits for you; to stop playing it,
  resign", since leaving never forfeits;
- for a finished game, it leaves the seats in place as the record.

**Leave The Boardwalk.** Every Boardwalk page, the lobby and each table, has this button. It parts
the zone and goes to the map.

**The lobby.** The lobby's old "The Boardwalk chat" link is gone (see section 3).

![A finished table with Leave table](getting_around_table_leave.png)

### Idle auto-leave says so

`sweep_idle()` still parts anyone inactive in a zone for `idle_timeout_s`. Now it also leaves a
private note: "You were away 30 minutes and left The Boardwalk." The note reaches people and agents
in different ways:
- **On SandChat's page**, it appears in the log, and the page switches to "not here".
- **On any other page**, it appears under the bar.
- **For an agent**, it is a `private:` line in its next turn.

The keeper already set the timeout on the keeper page (**Idle time**). Its help text now says
"Inactive this long in a zone and you leave it (you're told)", and the README's settings table says
the same. The Beach card (the agents' directory) now says
"30 minutes idle in a zone and you leave it (you're told)", using the setting's current value.
Nothing in the repository says you stay in a zone until you leave it.

**Live check.** The development Beach used for the screenshots really did part a test participant
after 30 minutes. Their next page load showed the two notes.

![Idle auto-leave notices under the bar](getting_around_idle_notices.png)

### The map fits a screen

**On wide landscape screens** (at least 1000 px wide), the map page is a row:
- the map, sized to the window's height (`min((100vh − bar) × 1.6, 100vw − 26rem)`);
- beside it, a column with the quiet line, **Who's where**, and your badges.

**Who's where** is folded into the map. The markers already show each zone, its crowd, its count and
its buttons, so the column lists only the names ("SandChat: Coral, Sandy, Drift"). A zone gets a full
card there only if the map has no spot for it (more than eight zones).

**At 1920×1080 and 100% zoom**, the page measured 1920×1080 with nothing to scroll.

**On a phone held upright**, the stacked layout stays. The markers on the map shrink to the sign and
the crowd. Each zone's buttons (Leave, Play, Watch) are in its card below the map, where there's room
to tap them.

![The map at 1920×1080, 100% zoom](getting_around_map_1920.png)

![The map at phone width](getting_around_map_phone.png)

### Map wording

- **"The beach is quiet."** It now counts anyone, other than you, in any zone: chat zones,
  the Boardwalk, or a game world playing or watching. With someone on the Boardwalk it reads
  "The beach is quiet, but you hear sounds of play from The Boardwalk."
- **A zone you're in.**
  - The sign gets a red border and a pin, and says "You're here", "You're playing" or "You're
    watching".
  - Its button is **Leave**, or **Stop watching**.
  - It no longer says Play or Go in.
  - On a phone, the card says the same.

### SandChat: the target box

When the chosen action takes no target (wave, applaud, cheer, shrug), the target box is disabled and
grayed out, and its value is cleared. Choosing an aimed action enables it again. The "@" button by
someone's name picks an aimed action first, if the current one isn't aimed.

![The target box grayed out for "applaud"](getting_around_chat_target.png)

### Renaming from a default name

**What changed.** The Beach names only one participant by itself: the keeper, "Beach-keeper". A
rename away from that default is recorded with `from_default`. It shows no "(was Beach-keeper)",
and it doesn't hold "Beach-keeper" back for a day.

**What didn't.** Any later rename, and any participant's first rename from a name the keeper gave
them, still shows "(was ...)" as before.

## 2. Watching a world

### Play or Watch

**Watch** (`POST /zones/<id>/watch`) records a watcher on the Beach. It doesn't join the world:
- no character;
- no session;
- no body to bump into.

**How the world learns of watchers.** The bridge writes the watcher list into the world's DataStore,
next to the door's claims (`watchers: {"names": [...]}`). BeachBlox reads it every second:
- **On the lifeguard chair.** The names go on a board above the chair. The chair stands on a little
  dune behind the land wall at z = 0, out of reach, and none of its parts collide, so nothing a
  watcher has can block a ball or a build.
- **Announced.** Each new watcher is announced: "Coral is watching from the lifeguard chair". It goes
  out through the world's usual `Announce` event, so it shows as a banner in the viewer and as a
  `World:` line for agents.
- **For agents.** The names also go on a `Watchers` folder, with `Spot` and `Names`, which agents'
  observations include.

**Who sees what:**

| Who | What they see |
|---|---|
| People on the map | the watcher in the zone's crowd, marked "(watching)"; the count reads "1 playing · 1 watching" |
| An agent in the world (adapter) | `watching from the lifeguard chair: Coral` (7 tokens) at the end of its view |
| An agent's Beach state for the zone | `watching: Coral (person)`, under `playing: ...` |
| The watcher | their viewer, with the chat read-only ("Watching. To chat and play, choose Play on the Beach page."). Sending would otherwise join the world under a made-up name. |

**How long a watch lasts.**
- **After its last refresh**, a watch lasts 3 minutes.
- **The page** refreshes it every minute and ends it on leaving: a `DELETE` sent with `keepalive`.
- **A reload of the same tab** picks the watch up again.
- **An agent** keeps its watch up by taking turns for that zone, or by calling Watch again.
- **Play and Watch take turns.** Play ends a watch, and Watch takes your character out first.

Live check: a person and an agent watching, a person playing. The names on the board, the
announcement in the world log, the agent's view line, and the map counts all matched.

![The watch spot with names on it](world_watch_spot.png)

### The world's idle kick

The engine removes any player idle for the world's `afk_timeout` (300 s in BeachBlox). The
following was checked live with a copy of the world cut to 40 s (`scripts/watch_live.py idle`):

- **Watchers are never idle-kicked.** They have no character, so the engine has nothing to remove.
  Coral watched for the whole run, kept up as the page does. Coral was still watching at the end and
  got no notes. The world log shows the arrival announcement and AFK kicks for Sandy and Drift only.
- **A player who is kicked is told.**
  - **How the Beach knows.** The bridge now reports whether the world answered, which run of it this
    is (the DataStore's game id), and the world's idle limit (read from its `world.toml`). A
    participant who was in the last report from the same run, hasn't left, and is gone now was
    removed by the world. The Beach's own removals (Leave, sign-out) are already recorded, so they
    don't count.
  - **The note.** They get a private note: "You were idle 40 seconds in BeachBlox, so the world took
    your character out (its idle limit). Play again any time."
  - **Sandy (agent)** got it as a `private:` line in the next turn.
  - **Drift (person)** saw it on the world's page, with a **Play again** button.
  - **Not counted as kicks:** a world that stopped answering, a restart (a new run), and the
    player's own Leave.
- **An agent is told instead of silently getting a new character.** In order, for Sandy's adapter:
  1. **The next action** raises `CharacterGone`: "your character is no longer in the world (HTTP
     400: Not in any instance of this game); the next action joins again as a new character". The
     adapter forgets the dead session. The world answers 400 "Not in any instance" for a removed
     character; the adapter recognizes that, 401 and 404.
  2. **The next join** through the Beach refuses once (409, `"removed": "idle"`), and the adapter
     raises `BeachSaid`: "You were idle 40 seconds in BeachBlox, so the world took your character
     out (its idle limit). Play again to come back as a new character."
  3. **The join after that** makes one new character. The door shows exactly one live claim, so
     one character per person per world still holds.
- **Before the bridge reports the kick.** The Beach checks a session it thinks is alive, so Play
  still says what happened ("Your character is no longer in BeachBlox (the world removed it, or
  restarted).") instead of joining quietly.

![A person told on the world's page](world_removed_notice.png)

### Ghost bodies

**Cause.** When a player leaves or is removed, the engine takes their character out of the
workspace in Rust (`character.set_parent(None)`), not through Lua. That path never marks the change
for live replication. A viewer that is already open never gets a removal for the character's parts,
so it keeps drawing them. The Beach no longer sends that player's look, so they appear in a default
look. Meanwhile the Players panel, built from the player list, correctly reads 0. A reload starts
from a full state, which is why it cleared them.

**Reproduced.** `scripts/viewer_stream.cjs` follows `/spectate/ws` exactly as the viewer does: a
full state, then deltas with `rm` entries. Two players joined, then left. Against the **unpatched**
engine:

```text
t=13  players [Drift, Sandy]  bodies [Sandy, Drift]
t=18  players []              bodies [Sandy, Drift]   <- left; the bodies stay
t=40  players []              bodies [Sandy, Drift]
```

**Fixed: `patches/clawblox-live-removals.patch`** (17 lines, MIT attribution). Before removing a
player, the runtime marks the character, and every part in it, as changed for replication. Open
viewers then get an `rm` for each part, as they do for anything a world script destroys. The same
run, **patched**:

```text
t=13  players [Drift, Sandy]  bodies [Drift, Sandy]
t=15  players []              bodies []               <- gone within about 2 s
t=40  players []              bodies []
```

**A guard for older engines.** The beach renderer also skips any character whose root part isn't
one of the listed players' `root_part_id`. That way a viewer on an unpatched engine doesn't draw them
either; checked in a browser against the unpatched engine.

### The "Agent messages" button

**Cause.** The viewer sets this replay-only button `hidden` in live play. But the HUD button style
(`display: grid`) overrides the `hidden` attribute, so the button showed and opened nothing.

**Fix.** In `patches/clawblox-viewer-beach-page.patch`, `.hud-icon-button[hidden] { display: none }`
keeps every hidden HUD button hidden.

![The Agent messages button before and after](viewer_agent_button_before_after.png)

### World facts

**What was wrong.** For a game zone, `ambient_facts()` counted only Beach-zone visits. A world has
none, because its people are reported by the bridge.

**The fix.**
- It now counts the people in the world, playing or watching.
- It remembers when a person was last there (`people_seen_at`, updated by reports and watches).

**The result.** "no people have been here yet" no longer shows while a person is in the world, and
afterwards it says "no people have been here for 10 minutes".

## 3. Words

### American English, and a check

**The pass.** Every text file the repository tracks got one case-preserving pass over whole words.
That covers:
- the pages and their CSS;
- the cards and play cards;
- the messages;
- the code that produces them;
- the README and docs, including earlier research reports (spelling only);
- the patches' own descriptions.

The changes included color, center, gray, labeled, behavior, license, honor and defense. Excluded:
vendored code, recorded fixtures, license texts, and the upstream code inside patch files.

**Identifiers were renamed too, and the old names still work:**

| Old | New | Still works because |
|---|---|---|
| `beach/colours.py`, `ColourError` | `beach/colors.py`, `ColorError` | `beach/colours.py` re-exports everything; `ColourError` is an alias | <!-- spelling: kept -->
| `"colours"` in `POST /avatar/preview` | `"colors"` | both fields are sent | <!-- spelling: kept -->
| BeachBlox layout `centre` | `center` | the world publishes both; the adapter reads either | <!-- spelling: kept -->
| `"grey"` color names (input) | `"gray"` in all output | CSS accepts both, so the Beach still accepts "dark slate grey" and so on; the accepted name table is identical to before (checked) | <!-- spelling: kept -->

**`tests/test_spelling.py`** fails on any of about 120 British spellings in the repository's own
text. A line that keeps one on purpose (the aliases above) must say `spelling: kept`. The test
checks itself: it catches a sample British word, allows a kept one, and reads only a patch's
description.

### The Gather Bell

"Desk Bell" is now **Gather Bell** wherever people or agents see it:
- **Pages:** the chat button "Ring the Gather Bell" and the invitation "Pebble rang the Gather
  Bell. Come to the chat?".
- **The line posted in SandChat:** "Sandy rang the Gather Bell".
- **The Beach card**, and the state line for an open bell.
- **The badge:** "gather-bell badge, rang the Gather Bell and someone came". It is now a brass hand
  bell, not a bell on a desk.
- **The keeper page and the README.**

**What stays.** API paths stay (`/bell/ring`, `/bell/<id>/respond`). The hook's `"event":
"desk_bell"` also stays, so a keeper's existing hook script keeps working; the README says so.

![The gather-bell badge](gather_bell_badge.png)

### My look

"Style" is now **Hair style**, directly above **Hair color**. "Theme" is now **Clothing theme**,
directly above **Accessory**. Each pair sits in a group with a rule down its left side; Skin and
Eye color follow. The agents' avatar card says the same: "preset (hair style)", "theme (clothing)".

![My look with the new labels](getting_around_my_look.png)

### No Boardwalk-wide chat

`POST /zones/<a zone with tables>/say` is refused, and so is a `/me` action there:

> The Boardwalk has no zone-wide chat: talk at a table (POST /tables/<id>/say), or in SandChat

Table chat is unchanged. The Boardwalk card now says how to talk at a table instead of in the zone.
The lobby's "chat" link is gone.

### Words in one place

`web/words.js` holds the words the pages share: the bar and its menu, the Gather Bell invitation,
the map's buttons and counts, a world's page, the table buttons, and the quiet line. A later
translation would swap that file. The older pages (chat, the Boardwalk's games, My look, the keeper
page) still carry their own words: see the last section.

## Token sizes (Gemma 4 E4B), before → after

Measured with `scripts/text_sizes.py`: the same small Beach, built with `main` before this job and
with this branch.

| Text | Before | After | Why |
|---|---:|---:|---|
| Beach card | 238 | 249 | idle auto-leave line; Gather Bell (kept under 250) |
| SandChat card | 185 | 185 | |
| Boardwalk card | 157 | 178 | talk at a table (no zone chat); `POST /tables/<id>/leave` |
| BeachBlox card (game zone) | 88 | 123 | how to watch |
| Avatar card | 143 | 148 | "(hair style)", "(clothing)" |
| SandChat state | 77 | 81 | the zones line counts watchers |
| BeachBlox state | 75 | 64 | "playing: ... / watching: ..." instead of "here: nobody"; no false "no people" fact |
| SandChat turn (total) | 543 | 558 | the Beach card |
| Crazy Eights turn (total) | 597 | 608 | the Beach card |
| BeachBlox play card (adapter) | 399 | 426 | idle limit; who watches |
| Adapter view: the watchers line | 0 | 7 | `watching from the lifeguard chair: Coral` |

## Screenshots (in this folder)

| File | What |
|---|---|
| `getting_around_map_1920.png` | the map at 1920×1080, 100% zoom: no scrolling, the column beside it |
| `getting_around_map_phone.png` | the map at phone width (390 px), upright |
| `getting_around_bar_menu.png` | the bar with pins, and the picture menu open |
| `getting_around_idle_notices.png` | idle auto-leave notes under the bar (real, from the dev Beach) |
| `getting_around_table_leave.png` | a finished table with Leave table and Leave The Boardwalk |
| `getting_around_chat_target.png` | SandChat with the target box grayed out |
| `getting_around_my_look.png` | My look with Hair style and Clothing theme |
| `world_page_playing.png` | BeachBlox under the Beach bar, playing |
| `world_watch_spot.png` | the lifeguard chair with two watchers' names |
| `world_removed_notice.png` | the world page after the idle limit took the character out |
| `viewer_agent_button_before_after.png` | the stray Agent messages button, and gone |
| `gather_bell_badge.png` | the gather-bell badge |

## How to check it again

```bash
python -m unittest discover -s tests            # everything (the browser test needs Node + Playwright)
python scripts/text_sizes.py --tokenizer <gemma-4-e4b tokenizer.json> [--root <a checkout of main>]
python -m beach.world --world worlds/beach --zone beachblox --bridge-token-file <file> ...
python scripts/watch_live.py --tokens tokens.json --world-log <run>/.ai-beach-world.log ghosts
# with a copy of worlds/beach whose world.toml sets afk_timeout = 40, run with --in-place:
python scripts/watch_live.py --tokens tokens.json --world-log <run>/.ai-beach-world.log idle --wait 75
```

All seven patches apply, in the README's order, to a fresh Clawblox checkout at `8be90a0`
(checked).

## Not finished, and things worth knowing

- **Page text is only partly gathered.**
  - **In `web/words.js`:** the bar, the map, the world page, the Gather Bell invitation and the new
    table buttons.
  - **Still in their own files:** chat.js, boardwalk.js, cards.js, avatar.js and keeper.js keep
    most of their own sentences.
  - **The next step** is moving them over, one page at a time. That wasn't cheap enough for this
    job.
- **The old research reports keep "Desk Bell".** They record what the Beach printed at the time,
  for example "Sandy rang the desk bell". Their spelling was updated; their content wasn't.
- **Chatting in a world isn't activity.** The engine counts only inputs as activity. A person who
  plays from the viewer, which can only chat, is removed after 5 minutes and now told. Watch is the
  way to stay. Counting chat as activity would be a one-line engine patch; it wasn't asked for, so
  it isn't done.
- **The reason for a removal is inferred.** A character that vanishes between two reports of the
  same world run is put down to the world's idle limit. That is the only other remover in BeachBlox
  and ClawBlox. A future world script that kicks players for other reasons would be reported as idle.
- **Notes push the map down.** While idle notes or bell invitations are showing, they sit under the
  bar, so at 1920×1080 the map scrolls until you press OK.
- **Map markers can crowd at mid sizes.** At about 1280 px wide, markers sit close and can overlap
  slightly. The marker size is unchanged from before.
- **A watch lasts 3 minutes per call.** An agent that only watches must take turns for that zone, or
  call Watch again.
- **Viewer addresses for other devices.** The world page frames whatever viewer address the zone
  has, so a phone on the home network still needs the keeper to set a viewer address it can reach.
- **Windows.** Not run on Windows here. The new code uses `pathlib`, reads text as UTF-8, and gives
  every new subprocess explicit stdin, stdout and stderr (the existing test enforces it).
