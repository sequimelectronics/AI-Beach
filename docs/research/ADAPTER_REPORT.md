# Clawblox adapter report: a playable view in about 1.1k tokens per turn

Date: 2026-10-14 · Clawblox commit `8be90a0` (same as job 01) · world: mesa-island (stock, plus a
`max_players = 2` copy for the stress and two-player runs) · tokenizer: **Gemma 4 E4B**
(`google/gemma-4-E4B-it`, repo sha `ee0ef60`, not gated, downloaded without credentials).

## Coverage statement

**Built**
- `adapters/clawblox/`, a Python package (standard library only):
  - `look`, `act`, `say`/`hear`, `history`, `map_card`, `full_look`;
  - `turn_bundle()` with the three-piece contract;
  - `PLAY_CARD.md` (373 tokens) and `README.md`.
- `scripts/clawblox_adapter_agent.py`: a scripted agent that sees only the adapter's text. It's also
  the 50-turn measurement session.
- `scripts/clawblox_capture_fixtures.py`: captures the raw observations used as test fixtures.
- `tests/`: 38 unit tests on 8 recorded fixtures, plus 1 integration test against a live headless
  server.
- A "Budget correction" addendum at the top of job 01's Q2 answer. Job 01's measurements are
  unchanged.

**Tested**
- All 38 unit tests pass.
- The integration test passes 12/12 consecutive runs after the Place fix described below. Before
  the fix it failed 6 times in 32 runs, for a reason I traced and fixed rather than retried.
- The scripted agent **completed the task in 3 out of 3 final runs** (two on the stock world, one on
  the two-player copy). An earlier run failed, which exposed two adapter bugs (see "What the
  scripted agent found"). Both are fixed.

**Measured**
- Per-turn token sizes of each bundle piece over three ~50-turn sessions.
- A stress worst case.
- Text versus compact JSON for the same information.
- Raw observation size alongside, for comparison.

**Didn't get to, or couldn't do**
- **No language model was run.** The scripted agent proves the information is sufficient, not that
  a 4B model will use it well.
- No pathfinding: MoveTo walks in a straight line.
- Players who have never been in your view cone show as "unknown player".
- I didn't test on another world; the constants and play card are mesa-island's.
- I didn't measure wall-clock latency per tool call beyond noting that it blocks (see Limits).
- I didn't port the adapter to other hosts' tool formats; by design it describes only what the
  game provides.

## What was built

```
adapters/clawblox/
  world.py      parse a raw observation; geometry; held-state, platform and ledge inference; Rules
  compact.py    compact view (text and JSON encodings), rest-summary, players-in-radius, map card
  adapter.py    ClawbloxAdapter: the tools, one-line action results, rolling history, turn_bundle()
  transport.py  urllib HTTP; tokens.py token counting (exact with `tokenizers`, else chars/4)
  PLAY_CARD.md  the action reference the model gets while playing (373 tokens)
  README.md     the hand-off contract and sizes
```

How the adapter deals with each problem job 01 found:

| Job 01 found | What the adapter does |
|---|---|
| Raw observation about 14k tokens | Static scenery goes into a one-time map card. The view shows the nearest 8 movable objects (name, kind, position to 0.1, distance, compass direction, what they rest on) plus one summary line, e.g. `farther: 10 blocks (1 N 8, 1 W 14, 1 S 14, 1 NE 20, 6 NW 38-77); Ring_1 ring (40,0.3,-42) 49.6 SE; Rock_1 rock (-17.3,1.1,33.3) 45.3 NW`. |
| `/input` returns a second full observation | `act()` returns one line, e.g. `Pickup failed: Rock_1 is 41 away, reach is 6 - move closer`. |
| Held state is hidden | Inferred from the object pinned at your position + (0, 3.5, 0); shown as `holding Block_4`. |
| Sticky `LastActionResult` | Read only for Pickup/Place/Throw (which set it in the same tick), and only when its prefix matches the action. MoveTo, Jump and Stop are judged from positions. A mismatch is reported as "the world reported no result". |
| MoveTo has no arrival or blocked signal | MoveTo polls until arrived, stopped (no progress for ~1 s), fell, or timed out. When stopped it says why: `stuck at a ledge 2 high (SmallPlateau, top 2) - retry the same MoveTo with "jump": true`, or "invisible wall", or "too high to jump". |
| `other_players` depends on facing | Every character within the radius is listed. Names are learned from the server's in-view list and remembered by entity id, so a player behind you shows as `Bob 11.7 W (not in view)`. |
| Chat `after=` drops same-second messages | `hear()` polls without `after`, dedupes by message id and orders by the numeric id. A test covers six messages sent in the same second. |

## Budget table (Gemma 4 E4B tokens)

Three scripted sessions of about 50 turns each (spawn → block pile → pickup/place → climb → rock
throw → chat → back to the pile → wander). One turn is one `turn_bundle()` plus one tool call.
Defaults: last 8 actions, last 6 chat lines.

| Run | turns | tools | state min / median / max | recent min / median / max | **turn total min / median / max** |
|---|---|---|---|---|---|
| A1 (stock world) | 50 | 519 | 289 / 324 / 777 | 11 / 284 / 423 | **825 / 1,129 / 1,307** |
| A2 (stock world) | 50 | 519 | 288 / 323 / 767 | 11 / 283 / 419 | **834 / 1,131 / 1,297** |
| B (2-player copy) | 51 | 519 | 289 / 323 / 771 | 11 / 283 / 478 | **835 / 1,133 / 1,313** |

- The max `state` is always turn 1, where the map card (447–481 tokens) rides along with the look.
- **Worst case requested** (standing next to the block pile after the rock made new blocks): the
  highest such turn was 1,258 (A1), 1,256 (A2) and 1,308 (B) tokens.
- **Stress case** (run B, at the pile after the rock throw, with a second player in range, a full
  8-action history, six maximum-length 500-character chat lines, and the map card included again):
  **2,301 tokens** (tools 519 + state 796 + recent 986).
- **Target check:** every measured turn is **under 8k**. Typical turns are about 1.1k, well under
  the 2.5–3k target, and the stress case lands just under it. There's headroom for larger
  `n_actions` or `n_chat` if a host wants them.
- For comparison, the raw observation on the same turns was 13,697–17,199 tokens. The `look` view
  replaces it at about 320, roughly 50× smaller.

Counting method: `tokenizers` 0.23.3 with `google/gemma-4-E4B-it`'s `tokenizer.json`, no special
tokens added, text only (no chat-template overhead). Gemma 3 4B and Qwen3-4B gave the same counts
within ±1 token on the compact text. **chars/4 underestimates this text about 2.3×**
(e.g. 303 real tokens vs 131), because it's mostly numbers. That's why the adapter reports real
counts when a tokenizer is available and labels the fallback as approximate.

## Text vs compact JSON

Both encodings carry the same information. `view_text` and `view_json` in `compact.py` are built
from one dict, and a test checks they name the same objects.

| Sample | text tokens | JSON tokens | text bytes | JSON bytes |
|---|---|---|---|---|
| spawn | 303 | 315 | 524 | 559 |
| at block pile | 303 | 313 | 529 | 562 |
| holding a block | 305 | 315 | 533 | 567 |
| on the plateau | 278 | 293 | 494 | 526 |
| after the rock throw | 294 | 314 | 531 | 563 |
| two players, one behind | 319 | 336 | 543 | 596 |
| session medians (A1 / A2 / B) | 322 / 318.5 / 320 | 334 / 329.5 / 333 | 540 / 538.5 / 539 | 574 / 571.5 / 576 |

**Text wins**: about 4–6% fewer tokens and bytes in every sample. It also reads as one object per
line with a small header (`name kind pos dist dir`), which is easier for a small model than nested
arrays. The adapter hands out text; the JSON encoder stays for measurement only.

## The scripted agent: is anything important lost?

`scripts/clawblox_adapter_agent.py` parses only the adapter's text with regular expressions: the map
card, the look view, act results and hear lines. It never reads a raw observation. It has to:
1. reach the block pile;
2. pick up and place a block;
3. climb to the rock;
4. pick it up and throw it;
5. confirm new blocks appeared.

| Run | pile | pick block | place | climb (result says "on SmallPlateau") | pick rock | throw | new blocks reported | objects in look before → after |
|---|---|---|---|---|---|---|---|---|
| A1 | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | 4 | 14 → 19 |
| A2 | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | 5 | 14 → 19 |
| B | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | 4 | 14 → 21 |

An excerpt from run A2, exactly as the agent saw it:

```
act MoveTo [-31.4,3,26.9]   -> MoveTo: stopped at (-26.8,2.5,22.9), 6.1 short - stuck at a ledge 2 high (SmallPlateau, top 2) - retry the same MoveTo with "jump": true
act MoveTo ... "jump": true -> MoveTo (jump): arrived at (-31,4.5,26.8) on SmallPlateau (took a run-up 4 from SmallPlateau)
look                        -> you (-31,4.5,26.8) facing W, on SmallPlateau, hands empty
                               Rock_1 rock (-35.9,2.8,28.7) 5.6 W
act Pickup [-35.9,2.8,28.7] -> Picked up Rock_1 (now holding it)
act Throw [1,-0.3,0] 10     -> Threw Rock_1 E at speed 10; it came to rest at (-14.9,1.1,27.3), 16.1 E of you; 5 new blocks appeared (ImpactBlock_13 .. ImpactBlock_17)
```

(The rock had moved from its start at (-31.4,3,26.9): landing on the plateau shoves it, because
characters push loose objects. The agent picked up the rock using the position from its
latest look, not the map card.)

### What the scripted agent found (fixed, then re-measured)

The first full runs did **not** complete. Each failure pointed at something the adapter got wrong:

1. **Place failed as "occupied" on open ground.** This cascaded: still holding the block, the agent
   couldn't pick up the rock.
   - Measured: a held block placed at y=0.4 or 0.5 was rejected; at 0.6 it worked, *usually*.
   - The integration test still failed 6 runs in 32 at y=0.6. The cause: the world checks
     overlap using the held block's **current, tumbled rotation**. A cube tilted on two axes
     reaches about 0.65 below its centre and clips the ground.
   - Fix: the adapter places **upright by default** (`rotation` 0/0/0 unless the model passes
     one). Since then: 12/12 integration runs and 3/3 agent runs.
   - The play card says y = 0.6.
2. **Place reported success before the block landed.** The world animates placement over 0.3 s,
   so an immediate Pickup missed. Place now waits and reports where the object actually settled.
3. **"Arrived" while still in mid-air.** After a climbing jump, two position readings taken either
   side of the jump's peak look steady. MoveTo now waits for two steady readings in a row, so the
   result reliably says `on SmallPlateau`.

Nothing in the *view* had to change. The information was enough, but the action results needed to
be truthful.

### New physics findings (they change job 01's advice)

- **Run-up distance: 3–5 units, not "about 7".** Jump-then-MoveTo onto SmallPlateau succeeded 3/3
  from 3, 4 and 5 units before the ledge face, and **0/3 from 7**. The play card and adapter use 4.
- **A jump while a MoveTo is blocked against a wall doesn't leave the ground** (y stayed 2.5). Stop
  first, or start the jump from a run-up.
- **Two separate model calls can't climb.** Job 01's climb needed Jump and MoveTo within about 0.1 s
  of each other. A real model takes seconds between tool calls, so "Jump, then MoveTo" as two turns
  would never work. The adapter therefore does the run-up, Jump and MoveTo itself when MoveTo gets
  `"jump": true`, and the result tells the model when to use it.
- Walking down off a platform with a plain MoveTo works (3/3).

## Hand-off contract (as built)

`turn_bundle()` returns `tools`, `state` and `recent`, each `{"text", "tokens"}`, plus
`total_tokens` and `token_method`.
- `tools` is the play card and the action definitions.
- `state` is the map card (first bundle only, or `include_map=True`) plus the current look.
- `recent` is the last `n_actions` results and the last `n_chat` chat lines.

Nothing in the repo describes or assumes how a host assembles these. See
`adapters/clawblox/README.md`.

## Limits and risks

- **Calls block.**
  - MoveTo waits until arrival or a stop: up to about 14 s on a long walk.
  - Throw follows the object for up to about 3.5 s, so it can report where it landed and whether
    new blocks appeared.
  - That suits a slow model, but a host shouldn't call these with a short timeout.
- **Straight-line MoveTo.** In run B the agent ended up west of the plateau after the throw; the
  plateau was in the way back, and the suggested `"jump": true` carried it over. Pathfinding
  around obstacles isn't implemented.
- **"unknown player".** A player who has never been inside your view cone can't be named from
  observations alone. (Chat audibility includes distances per speaker and could be used to match
  them; I didn't build that.)
- **hear() reads the latest 100 messages.** That's the server's cap per request. More than 100
  messages between two hears would drop the oldest.
- **mesa-island constants.** `world.Rules` (reach 6/7, match 1.5, hold offset 3.5, throw cap 10, jump
  rise 6.5, run-up 4, place clearance 0.6) and `PLAY_CARD.md` are specific to mesa-island.
- **`full_look()` is the raw observation (about 14–17k tokens).** It's offered, as asked; whether
  to call it is the host's and the model's decision.

## Reproducing

```bash
# Clawblox at 8be90a0, built outside this repo (see CLAWBLOX_REPORT.md); run a copy of mesa-island:
clawblox run /tmp/mesa --port 8080
python3 scripts/clawblox_adapter_agent.py --base http://127.0.0.1:8080 \
  --tokenizer gemma-4-E4B-it/tokenizer.json --tokenizer-name google/gemma-4-E4B-it --out run.json
# stress case (needs max_players >= 2 in the world copy):
python3 scripts/clawblox_adapter_agent.py --base http://127.0.0.1:8082 --stress-chat ...
python3 -m unittest discover -s tests
```
