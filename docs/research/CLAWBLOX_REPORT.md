# Clawblox feasibility report: can a ~4B local model play over plain HTTP?

Date: 2026-10-14 · Clawblox commit `8be90a0caef1fc61ad3f97e51be3bb42c5f6d848` (the requested
commit; it was reachable and was also the tip of `main` at clone time).
Clawblox was cloned and built in a scratch directory outside this repo. None of its source is
committed here. This repo gets only `scripts/clawblox_probe.py`,
`scripts/clawblox_token_count.py` and this report.

## Short answer

**Yes, with a thin adapter in front of it. No, if the model reads raw observations.**

- The HTTP API is enough to play. Join, observe, act and chat work with plain `POST`/`GET` calls
  and no coding-agent tooling. All six mesa-island actions and chat worked from a ~350-line
  standard-library Python client.
- **The raw observation does not fit an 8k budget.** A full mesa-island observation is about
  **23 KB, which is about 13,700 tokens** with the Qwen3-4B or Gemma-3-4B tokenizer. The common
  chars/4 rule says about 5,700, a 2.4× underestimate, because this JSON is mostly numbers.
  Shrinking the radius helps, but only stops overflowing once the agent can barely see. The
  same information in a compact form is about **1,500 tokens** for the whole island.
- Multiplayer and chat work with a one-line config change (`max_players`), with caveats: there's
  no leave endpoint, the chat polling cursor drops messages, and other players are only listed
  when they're inside your view cone.
- The engine itself makes no outbound connections while running. Two things around it do: the
  renderer bundling step at startup (`npx --yes esbuild` downloads esbuild from npm) and the
  browser view (loads Three.js and lucide from `esm.sh`).

## Coverage statement

**Read in full**

| File | Notes |
|---|---|
| `worlds/mesa-island/main.lua` | all 917 lines |
| `worlds/mesa-island/API.md` | all 72 lines (1,460 bytes) |
| `worlds/mesa-island/world.toml` | all |
| `docs/scripting.md` | all 778 lines |
| `docs/worlds.md` | all |
| `docs/world-configuration.md` | all |
| `docs/observations-and-input.md` | all |
| `docs/players-and-characters.md` | all |
| `docs/save-load-resume.md` | all |

**Server-side chat (read the relevant parts in full, not the whole file).** Chat lives in
`src/bin/cli.rs` (6,067 lines). I read every chat-related piece: the request and response
structs, `LocalChatState::push`/`list`, `build_chat_audibility`,
`listener_can_receive_message`, the `local_chat` and `local_chat_messages` handlers,
`local_spectate_chat_messages`, and the chat part of `LocalRuntimeSnapshot`. I didn't read
the rest of `cli.rs`.

**Skimmed or partly read (only to answer a specific question)**
- `src/bin/cli.rs`: route table, `local_join`, `get_session`, `local_input`, `local_observe`,
  `local_snapshot`, the renderer bundling code (`maybe_build_renderer_package`,
  `bundle_renderer_with_esbuild`), and the `Run`/`Login`/`Deploy`/`Docs` CLI definitions.
- `src/game/instance/observation.rs`: the `PlayerObservation`/`WorldEntity` structs,
  `effective_observation_radius`, `get_dynamic_world_info`, and enough of
  `get_other_players` to confirm the field-of-view filter.
- `src/game/manager/players.rs`: the "Instance is full" check only.
- `crates/luau-persist/build.rs` and `Cargo.toml`, for build inputs.
- `frontend_runtime/dist/main.js` and `sdk/three.js`: the chat/join and keyboard handling only.
- `docs/world-interface.md`: first 60 lines.
- A URL grep across `src/`, `crates/`, `frontend_runtime/`, `static/` and `worlds/`, with each hit
  followed up in context.

**Didn't get to:** the paper ("Is this machine playing?", arXiv:2610.07130); `docs/engine-api-reference.md`,
`physics.md`, `checkpoints.md`, `agents.md` and the other docs pages not listed above;
`src/snapshot.rs` (5,060 lines); `src/capture.rs`; the mesa-island renderer source beyond a grep;
the Python package under `python/`. I didn't run Clawblox's own test suite.

**Couldn't run or didn't try**
- I didn't test a human *playing* through the browser. The stock mesa-island renderer has no
  play controls (see Q5), so there was nothing to test beyond spectating and chat.
- I didn't test proximity chat (`speech.mode = "proximity"`), AFK timeout behaviour, the Postgres
  datastore, or recording/replay.
- I tested the "fresh machine, offline" startup failure by moving the npx cache aside, not on a
  truly clean machine.
- I didn't run a language model. Everything below is about what the model would receive and have
  to send, not about how well a 4B model plays.

## Build (task 3)

| Item | Value |
|---|---|
| Toolchain | `rustc 1.97.0 (2d8144b78 2026-07-07)`, `cargo 1.97.0`; `rust-toolchain.toml` pins `channel = "stable"` |
| C/C++ | gcc/g++ 13.3.0 (Ubuntu 24.04). `luau-persist/build.rs` compiles a C++17 bridge against Luau VM sources |
| Command | `cargo build --release --locked --bin clawblox` |
| Wall time | **5 min 16 s** clean build, 4 vCPU, 15 GB RAM, empty cargo registry beforehand |
| Result | success, 2 dead-code warnings (unused Kimi-agent helpers) |
| Output | 36 MB binary; `target/` 1.1 GB; `~/.cargo/registry` 351 MB |
| Downloads | 339 crates, **all from crates.io** (Cargo.lock lists no git or other sources; no `~/.cargo/git`). The Luau C++ sources come from the `luau0-src` crate on crates.io; `build.rs` finds them in the cargo registry, nothing fetched separately. |

Running it does download something: see the network section. `clawblox run` bundles the world's
renderer on every start, which on a machine without `esbuild` means `npx --yes esbuild` fetching
from registry.npmjs.org.

Headless run: `clawblox run <world-dir> --port 8080`. There's no browser involved. The server is
ready about 5 s after launch (most of that is the esbuild step) and runs at about 60 ticks/s.
It writes `renderer/dist/`, `renderer/.build.lock` and `.clawblox/local-<port>.db` (SQLite)
**into the world directory**, so I ran copies of the world, never the checkout.

## The client (task 4): `scripts/clawblox_probe.py`

Standard library only. `session` mode does `GET /api.md` → `POST /join` → `GET /observe`. It then
walks to the block pile and runs **Pickup → Place → Pickup → Throw → Jump → MoveTo → Stop**,
climbs the plateau, picks up the rock and throws it, sends a chat message and reads chat back,
then wanders until it has made 50 `/observe` and `/input` calls. Every response's size is logged.
`multi` mode joins two players and tests visibility and chat in both directions.

Results on the stock world (radius 40000, 1 player):

| Action | Result |
|---|---|
| MoveTo | works; returns immediately, so you poll `/observe` to see progress |
| Pickup | `PickupSuccess` (must be within 6 units of you and 1.5 of the target point) |
| Place | `PlaceSuccess` (within 7 units; fails `Occupied` if overlapping) |
| Throw | `ThrowSuccess`; speed is silently clamped to 10 |
| Jump | works; about 6.5 units of rise (y 2.55 → 9.05) |
| Stop | works; the character still drifted about 2 units after Stop |
| Rock pickup + throw | `PickupSuccess`/`ThrowSuccess`; the impact spawned **5 new cubes** (14 → 19 pickup objects) |
| Chat send / read | works (`{"id":"local_1","created_at":...}` / `{"messages":[...]}`) |

The first version of the script couldn't reach the rock, and that's worth knowing: **MoveTo
doesn't climb.** The rock rests on a 2-unit plateau. "MoveTo, then Jump at the wall" leaves the
character stuck at the edge. "Jump first, then MoveTo from about 7 units away" works. A small
model will have to learn that timing from failure messages alone (`PickupFailed:OutOfRange`),
because nothing in the observation says "blocked".

## Observation size (task 5): the most important number

### Method

- **Bytes** are the raw HTTP response bodies.
- **chars/4** is the usual rough token estimate, recorded for every call as asked. **It's
  approximate, and for this payload it's badly wrong.**
- So I also counted real tokens on saved raw observations with the Hugging Face `tokenizers`
  library: **Qwen3-4B** and **Gemma-3-4B** tokenizers, both 4B-class local models
  (`scripts/clawblox_token_count.py`). These counts are exact for those tokenizers but cover the
  JSON text only, not chat-template overhead.
- Across all samples, **real tokens ≈ 2.4 × chars/4**. Coordinates, rotation matrices and
  8-corner bounding boxes break into many small tokens.

### Scripted session, stock world (50 calls, radius 40000)

| Response | n | bytes min / median / max | chars/4 min / median / max | entities |
|---|---|---|---|---|
| `GET /observe` | 25 | 22,903 / 23,060 / 26,893 | 5,726 / 5,765 / 6,724 | 36 / 36 / 41 |
| `POST /input` | 25 | 22,918 / 23,089 / 26,882 | 5,730 / 5,773 / 6,721 | 36 / 36 / 41 |

`POST /input` returns a full observation, so every action costs as much as an observe. The max
rows come from after the rock throw, when 5 extra cubes are in view.

Real-tokenizer counts on saved observations:

| Sample | bytes | chars/4 | **Qwen3-4B** | Gemma-3-4B | entities | compact form (Qwen3) |
|---|---|---|---|---|---|---|
| Stock, at spawn | 22,854 | 5,714 | **13,671** | 13,732 | 36 | 1,500 |
| Stock, at block pile | 23,037 | 5,760 | **13,851** | 13,906 | 36 | 1,502 |
| `API.md` | 1,460 | 365 | **424** | 455 | – | – |
| One block entity | 742 | 186 | **447** | – | 1 | about 40 |

One small cube costs about 450 tokens, because each entity carries a 3×3 rotation matrix, an
AABB, an OBB with 8 corners, an RGB colour, material, shape and attributes. The fixed part of the
observation (tick, player, attributes, with no entities) is only 164 tokens. Entities are the
whole cost.

### Shrinking the radius

I tested the world radius (`[observation] radius` in `world.toml`) at 50/25/15/8, plus the
per-player `ObservationRadius` attribute at 15 (set from `main.lua` in `setupPlayer`; an agent
can't set it itself). The engine clamps the attribute to the world radius, so it can only shrink.

Scripted-session distribution (chars/4, 50 calls each):

| Radius | bytes min / median / max | chars/4 min / median / max | entities min / median / max |
|---|---|---|---|
| 40000 (stock) | 22,903 / 23,060 / 26,893 | 5,726 / 5,765 / 6,724 | 36 / 36 / 41 |
| 50 | 7,947 / 19,529 / 23,362 | 1,987 / 4,883 / 5,841 | 13 / 29 / 35 |
| 25 | 11,131 / 11,883 / 13,265 | 2,783 / 2,971 / 3,317 | 16 / 17 / 19 |
| 15 | 2,806 / 6,306 / 12,161 | 702 / 1,577 / 3,041 | 4 / 9 / 17 |
| 15 (player attribute) | 2,646 / 7,234 / 11,181 | 662 / 1,809 / 2,796 | 4 / 10 / 15 |
| 8 | 1,066 / 2,231 / 2,251 | 267 / 558 / 563 | 1 / 3 / 3 |

Single observations with the real tokenizer:

| Radius | at spawn: entities / **Qwen3 tokens** | at block pile: entities / **Qwen3 tokens** |
|---|---|---|
| 40000 | 36 / **13,671** | 36 / **13,851** |
| 50 | 31 / **11,936** | 28 / **11,096** |
| 25 | 19 / **7,840** | 18 / **7,705** |
| 15 | 8 / **3,278** | 17 / **7,350** |
| 8 | 3 / **1,176** | 15 / **6,685** |

Notes:
- **Size depends on what's near you, not just the radius.** Standing next to the 12-block pile at
  radius 8 still costs about 6,700 tokens. Radius doesn't cap size; a pile of loose objects
  defeats any radius.
- The ocean (600×600) and the ground slab under you intersect every radius, so the minimum
  observation always has about 3 entities, about 1,200 tokens.
- None of mesa-island's terrain is tagged `Static`, so the 21 mesas, ground lobes, ocean and
  **four invisible boundary walls** are all sent every time. Removing them (tag `Static` and
  describe the map in API.md) still leaves about 6,700 tokens for the 15 movable things.

### Q2 answer: does it fit in about 8k?

**No, not the raw observation.** At stock radius one observation (about 13.7k tokens) is bigger
than the whole budget. At radius 25 it's about 7.8k, which still leaves nothing for
instructions (API.md alone is 424 tokens), conversation, or the model's reply. At radius 15
it's 3.3k when nothing is nearby but 7.4k at the block pile, which is exactly where the
interesting play happens. Only radius 8 away from objects (about 1.2k) fits comfortably.

**What the agent loses at a radius that fits (8–15):**
- From spawn it can't see the block pile (15 units away, right at the edge), the rock
  (about 41 away), the ring (about 59 away), the climbable mesas, or the boundary walls.
- At radius 8 the scripted session never found a block, so Pickup, Place and Throw were never
  attempted.
- The agent would be exploring blind, because API.md doesn't describe the map either.

**What actually fits** is the same data, compacted: name, position rounded to 0.1, size and role
per entity. That's 1,500 tokens for the entire island at full radius, about 9× smaller, with
nothing lost that the game logic uses. Rotation, AABB, OBB corners and colour are derived or
rendering data. A thin adapter between the model and Clawblox could also:
- return a one-line action result instead of a second full observation from `/input`;
- drop static geometry after the first turn;
- sort entities by distance and cap the count.

That adapter is maybe 100 lines and needs no change to Clawblox. Clawblox also has a built-in
"narrow action result" mode (`state_observation = false` + `action_feedback = true`), but it
turns off `/observe` entirely, so it isn't usable for a text-only model.

## Multiplayer (task 6)

A copy of mesa-island with `max_players = 4`. Nothing else changed.

- Two clients (`Alice`, `Bob`) joined. Each saw the other in `other_players` (by name and
  id), and Alice's entity list had 37 entries (36 plus Bob's `HumanoidRootPart`).
- Chat went both ways: Alice and Bob each read `[("Alice","hi Bob, it's Alice"), ("Bob","hi Alice, Bob here")]`.
- Both players spawn on the exact same point, `(0, 5, 0)`; `main.lua` has one spawn position.

Caveats found:
1. **`other_players` is filtered by your view cone (105°), not just the radius**
   (`observation.rs:1313`, `player_can_see_target_in_fov`). The docs don't mention this. In a
   control run (A walks 10 units away, then B joins) **neither player listed the other**. Each
   could only see the other as an unnamed `HumanoidRootPart` in the radius-only entity list.
   Facing follows movement, and there's no turn or look action, so the only way to "look
   around" is to walk.
2. **There's no leave endpoint.** A session lasts until AFK timeout or server restart.
   mesa-island sets `max_players = 1` and `afk_timeout = 0`, so **once one client has joined,
   every other join (including a human opening the browser chat panel, which also calls
   `/join`) gets `400 Instance is full` until restart.** I hit this repeatedly. A re-join that
   sends the old `X-Session` token gets the same player back.
3. **The chat cursor loses messages.** `created_at` has 1-second resolution and the `after=`
   filter is a strict string `>` comparison. Polling with `after=<last created_at>` silently
   **skipped a message sent in the same second** (reproduced: `missed_same_second_message: true`).
   There's no id or sequence cursor. Workaround: poll without `after` and dedupe on `id`
   (`local_N`).
4. **Chat messages are verbose.** Each one carries `heard_by` and an `audibility` entry for every
   player in the instance, about 550 bytes for one message with 2 players, growing with player
   count. An adapter should strip it to `name: text`.
5. Chat isn't part of `/observe`, so an agent has to poll a second endpoint.

### Q3 answer

**Yes.** Multiplayer and chat need only `max_players` raised, and chat is on by default
(`speech.mode = "global"`; `proximity` with `hearing_radius` exists but I didn't test it). For a
social space you'll also want a non-zero `afk_timeout` (or a leave call), more than one spawn
point, and the chat-cursor workaround.

## Runtime network (task 7)

### Observed

`strace -f -e connect` on the server, plus a run inside a network namespace (`unshare -rn`)
with no external network.

| Phase | Outbound connections |
|---|---|
| `clawblox run` startup, no esbuild installed | **yes**: `npx --yes esbuild` contacted registry.npmjs.org (104.16.x.34:443) and DNS |
| Gameplay: join/observe/input/chat/snapshot, 50+ calls | **none** (0 non-Unix `connect` calls) |
| Startup offline, fresh world (no bundle, empty npx cache) | **fails to start** (`npm error ... getaddrinfo EAI_AGAIN registry.npmjs.org`); the renderer build is fatal |
| Startup offline, bundle already built | starts, warns "renderer rebuild failed; using existing bundle"; **the full scripted session passed offline** |
| Browser view, online | 9 requests to the server, **8 to esm.sh** (three@0.160.0, its loaders, lucide@0.468.0); renders correctly |
| Browser view, offline | **blank dark page**; `esm.sh/lucide` and `three` fail; no 3D view |
| `/observe/image` (vision sidecar) | worked with `CLAWBLOX_CHROME=/opt/pw-browsers/chromium` (first frame 4.0 s, then 0.6 s). It renders the same renderer bundle, which imports `https://esm.sh/three@0.160.0`, and I saw proxied connections during that run, so treat vision as **needing internet too**. I didn't attribute each connection to a process. Without `CLAWBLOX_CHROME`, the engine didn't find the preinstalled Chromium on its own. |

### URLs in the source

| URL | Where | When used |
|---|---|---|
| `https://esm.sh/three@0.160.0`, `.../examples/jsm/loaders/GLTFLoader.js`, `.../utils/SkeletonUtils.js`, `https://esm.sh/lucide@0.468.0` | `src/bin/cli.rs` (embedded frontend HTML, `init` template), `frontend_runtime/dist/*`, `worlds/mesa-island/renderer/src/index.js` | **Runtime, in the viewer's browser** (and in the vision sidecar). Not fetched by the server. |
| registry.npmjs.org (implicit, via `npx --yes esbuild`) | `bundle_renderer_with_esbuild` in `src/bin/cli.rs` | **Every `clawblox run` startup**, unless `esbuild` is on PATH, the world's renderer has an npm `build` script, or npx's cache already has it. Fatal if it fails and no bundle exists. |
| `https://clawblox.com` | `cli.rs` `Login`/`Deploy` defaults | only `clawblox login` / `deploy` (not used) |
| `https://api.github.com/repos/nacloos/clawblox/contents/docs` | `cli.rs` `fetch_docs_from_github` | only `clawblox docs` |
| `https://codeload.github.com/...tar.gz` | `src/world_source.rs` | only when `clawblox run` is given a GitHub folder URL |
| `https://api.kimi.com/coding/v1` | `src/agent.rs` | only the managed coding-agent runner (not used) |
| `DATABASE_URL` (Postgres), `R2_*` (Cloudflare R2 via `rust-s3`) | `src/db/mod.rs`, `src/r2.rs` | env-gated; Postgres only with `--datastore postgres`. I found no R2 use on the `run` path. |
| `http://world:43210`, `https://example.com` | tests / sandbox examples | not contacted |
| crates.io | Cargo.lock | **build time only** |

There's no update check or telemetry on the `run` path that I could find. One thing to note
about exposure: the server binds `0.0.0.0` with permissive CORS (`allow_origin(Any)`), so on a
shared network anyone who can reach the port can join.

## Answers

### 1. Can an agent that isn't a coding assistant play using only the HTTP endpoints?

**Yes.** The whole loop is `GET /api.md`, `POST /join?name=`, `GET /observe`,
`POST /input {"type","data"}`, `POST /chat {"content"}`, `GET /chat/messages`, with an
`X-Session` header. It needs no shell, files or tmux. Each action is one JSON object, which fits
tool-calling well.

What's missing or awkward for a small model:
- **Observation size** (above). This is the blocker, and it's fixable with an adapter.
- **There's no "move finished" or "blocked" signal.** MoveTo returns at once, the engine's
  `MoveToFinished` event isn't exposed, and getting stuck at a ledge looks like "position stopped
  changing". The agent has to poll and compare positions.
- **Held state is deliberately hidden** (`setPlayerBlockState` is a no-op, with the comment
  "keep pickup/held state implicit"). The agent has to infer what it's carrying from
  `LastActionResult` or from a block floating 3.5 units above its head.
- **`LastActionResult` is sticky.** It only changes on Pickup/Place/Throw, so after a MoveTo it
  still reports the old result. Easy to misread.
- **API.md is thin.** It doesn't give ranges (Pickup 6, Place 7, target match 1.5), the Throw
  speed clamp (max 10), failure codes, the map layout, the rock mechanic, or the fact that MoveTo
  can't climb. A small model gets no strategy hints. It's also wrong in places: it advertises
  `/observe/image`, which only works if the host has Chromium and internet.
- **No leave and no turn or look action.** Facing changes only by moving, which matters because
  of the view-cone filter on `other_players`.

### 2. Does an observation fit in about 8k?

**No.** See the observation section: about 13.7k real tokens per raw observation, and no radius
that keeps the game playable brings it under budget with room to spare. A compact re-encoding of
the full island is about 1.5k tokens. **Plan on a thin observation adapter; don't rely on radius.**

### 3. Do multiplayer and chat work with only a config change?

**Yes** (`max_players`). Add `afk_timeout`, multiple spawn points, and the chat-cursor workaround
before a social space depends on it. Watch the view-cone filter on `other_players`.

### 4. What does main.lua implement, and how hard is a new, simpler world?

`main.lua` (917 lines) is plain data plus three mechanics:
- **Terrain (lines 83–197):** a 600×600 semi-transparent "ocean" plane with collision off; an
  island made of 5 overlapping ground slabs; 4 invisible 80-unit boundary walls at ±80; and 11
  anchored "mesas" (the platforms) forming two climbing routes, the tallest a 20-unit spire.
  Gravity is set to 10 (Roblox default is 196.2), which gives slow, floaty jumps.
- **Pickup objects:** 12 small "Slate" cubes dropped in a pile at about (15, 6–11, −1); a heavy
  rock (density 8) on SmallPlateau at (−31.4, 3, 26.9); and a yellow ring at (40, 0.3, −42). The
  ring is just another carryable object. **Nothing scores it or reacts to it**; there are no
  goals in this world.
- **The rock that spawns cubes (`armRockImpact`):** a `Touched` handler on the rock. If the rock
  hits something at speed ≥ 6 and kinetic energy ≥ 3000, it spawns
  `floor(energy / 3000)` new cubes (1–8) in a ring around the impact, with a 1-second arm delay
  and 0.35-second cooldown. In my test a thrown rock spawned 5. The rock is the only way to make
  more blocks.
- **Actions (`AgentInputService.InputReceived`):** MoveTo/Jump/Stop map directly to Humanoid
  calls. Pickup attaches the nearest pickup object within 1.5 units of the target point, if
  you're within 6. The held object is moved to head height every Heartbeat. Place does an overlap
  test and then a 0.3-second eased snap to the target. Throw sets a velocity (speed clamped
  0–10, plus 6 upward).
- **Housekeeping:** respawn below y = −200, destroy fallen blocks, and code to clean up parts
  from earlier layouts.

**A simpler beach world is easy.** Roughly 100–200 lines of Luau and an API.md, reusing this file
as a template:
- Make one flat sand slab and a water plane, and tag them `Static`.
- Make one ball: a `Part` with `Shape = Ball` and some elasticity, plus `IsPickupObject`.
- Make a "sandcastle area": an anchored zone part, with Heartbeat checking which blocks sit
  inside it and writing a `CastleHeight` attribute to a `ServerStorage` folder so it survives
  resume.
- Copy the Pickup/Place/Throw handlers nearly verbatim.

The API is Roblox-like and well documented. The real design work is the API.md and keeping the
entity count low (every loose sandcastle block costs about 450 tokens raw, about 40 compacted).
One more thing: you'd also need a renderer. `clawblox run` refuses to start without a
`renderer/package.json` it can bundle, so you copy mesa-island's (707 lines of Three.js) and
adjust colours.

### 5. What would a human need to join and watch or play in the browser? Does it need the internet?

- **Watch:** open `http://<host>:<port>/?spectator_token=<token printed at startup>`. It works,
  with WASD to fly the spectator camera.
- **Chat:** the same page has a chat panel. Sending the first message silently calls `/join` and
  **takes a player slot** (a character spawns), so with mesa-island's `max_players = 1` it fails
  once an agent is in.
- **Play:** **not possible with the stock mesa-island renderer.** It has no keyboard or mouse
  play bindings; the browser is spectate plus chat. The frontend SDK has the building blocks
  (`ctx.runtime.input`: join, sendInput, `bindKeyboardActions`), so a renderer *could* map keys
  or click-to-move onto MoveTo, Pickup and the rest. That's renderer work for us.
- **Internet at runtime: yes, for the browser.** The page loads Three.js and lucide from
  `esm.sh`. With no internet I got a blank page. To run offline or privately we'd have to vendor
  those modules and rewrite the import map and the renderer's `https://esm.sh/...` import. That's
  doable, but it's a patch to Clawblox's embedded frontend, not a config option.
- Separately, the **server** needs esbuild at startup (an npm download unless installed or
  already bundled).

### 6. Does save/resume work, and is it useful for leaving and coming back?

**Yes, and it works well.**
- **Snapshot:** `GET /snapshot` needs the operator or spectator token. Without it the server
  returns 401. Mid-game snapshot of mesa-island with one player holding a block: 141 KB JSON
  (`schema_version`, `game_id`, `instance`, `sessions`, `chat`).
- **Resume:** I restarted with `clawblox run <world> --resume snap.json` and checked:
  - The player was at the same position, at the same tick.
  - The **held block was still held and followed the player when they moved**. That state lives
    only in a Lua table (`heldBlocksByPlayer`), so the VM snapshot really works.
  - Placing the block afterwards succeeded.
  - Chat history was intact.
  - **The old session token still worked**, so an agent can reconnect without re-joining.
  - A new player could join.
- **Useful for "leave the world, come back later":** yes, at the level of the whole world (pause
  and restore the server). It's not per-player: one snapshot is the entire world with every
  player in it.

Caveats:
- The snapshot contains **every player's session token in plain text**. Anyone with the
  spectator token (it's in the viewer URL) can fetch a snapshot and impersonate players. Treat
  snapshots and spectator links as secrets.
- Snapshots are tied to the binary's schema version. A Clawblox upgrade can make old saves
  unloadable, and per the docs restore "either succeeds exactly or fails".
- DataStore rows live in SQLite next to the world, not in the snapshot.

### 7. Surprises, risks, doubts

1. **chars/4 is the wrong yardstick here.** The approximate count said about 5.8k (fits!).
   Real 4B-model tokenizers say about 13.7k (doesn't). Had I stopped at the requested
   approximation, the main conclusion would have been wrong.
2. **The server needs Node/npm, and the internet, to start**, because the renderer is bundled on
   every start even for headless agent-only use. There's no `--no-renderer` flag. Pre-installing
   `esbuild` or shipping a prebuilt bundle avoids it.
3. **`clawblox run` writes into the world directory** (bundle, lock file, SQLite DB). Don't run it
   against a checked-in world folder you care about keeping clean.
4. **The browser view depends on esm.sh at runtime.** That's a third-party CDN, a privacy leak
   (viewer IPs) and a supply-chain point for a public project.
5. **There's no access control beyond unguessable tokens,** with `0.0.0.0` binding and wildcard
   CORS. `/join` is open to anyone who can reach the port, and with `max_players` low one stray
   join locks everyone out (no leave, `afk_timeout = 0`).
6. **The defaults are aimed at coding agents.** The managed-agent runner defaults to
   `--permission-mode bypassPermissions`. We don't use it, but it shows the intended user is a
   coding agent that can read 23 KB of JSON with tools, not a small model reading it in-context.
   API.md is minimal for the same reason.
7. **Undocumented field-of-view filter on `other_players`.** In a social space, "who's here?"
   shouldn't depend on which way you happen to be facing.
8. **The chat `after` cursor drops same-second messages.** That's a real bug for any polling
   agent.
9. **Small doc and code mismatches:** world.toml uses the legacy key `skill = "API.md"`
   (still accepted as an alias); `vision = true` is the legacy alias of `vision_observation`;
   API.md says the server runs on 8080 while docs examples use 3000; Throw speed is clamped
   to 10 but API.md says nothing.
10. **Doubt about the approach overall:** none that rules it out. The engine is solid: it built
    first time, physics and resume worked, and it's fast (`/observe` about 3 ms, `/input` about
    25–35 ms because it waits a tick). The gap is entirely at the interface: an observation format
    designed for big tool-using agents. A small adapter fixes the token problem; vendoring the
    two CDN modules fixes the offline-browser problem. If we'd rather not maintain patches to the
    embedded frontend, those two adapters are the main ongoing cost of building on Clawblox.

## Reproducing

```bash
# outside this repo
git clone https://github.com/nacloos/clawblox && cd clawblox && git checkout 8be90a0
cargo build --release --locked --bin clawblox
cp -r worlds/mesa-island /tmp/mesa && ./target/release/clawblox run /tmp/mesa --port 8080
# in this repo
python3 scripts/clawblox_probe.py session --base http://127.0.0.1:8080 --out run.json
# multiplayer: set max_players = 4 in a world copy, then
python3 scripts/clawblox_probe.py multi --base http://127.0.0.1:8081 --out multi.json
# real token counts (needs `pip install tokenizers` + tokenizer.json files)
python3 scripts/clawblox_token_count.py --tok qwen3-4b=tokenizer.json obs.json
```

Radius variants: edit `[observation] radius` in a world copy; for the per-player attribute add
`player:SetAttribute("ObservationRadius", 15)` in `setupPlayer` in `main.lua`. Restart the server
between runs, because of the `max_players = 1` and no-leave issue.
