# adapters/clawblox

A thin, deterministic adapter between a small language model and a
[Clawblox](https://github.com/nacloos/clawblox) world (built and measured against mesa-island at
Clawblox commit `8be90a0`). It turns Clawblox's raw observations (about 14–17k tokens each) into
compact text. It turns each action into a one-line result and keeps a short rolling history. No
language model runs inside it, and Clawblox is not modified; the adapter only calls the world's own
HTTP endpoints. Python 3.11+, standard library only (`tokenizers` is optional, for exact token
counts).

```python
from adapters.clawblox import ClawbloxAdapter, turn_bundle, make_counter

game = ClawbloxAdapter("http://127.0.0.1:8080", name="Sandy",
                       counter=make_counter("path/to/tokenizer.json"))  # optional; else chars/4
bundle = turn_bundle(game)
game.act("MoveTo", {"position": [12.6, 0, -1.3]})   # -> "MoveTo: arrived at (12.2,2.5,-1.4)"
```

## Tools the game offers the model

| Tool | Returns |
|---|---|
| `look()` | the compact view: you (position, facing, what you stand on, what you hold), the nearest 8 objects (name, kind, position to 0.1, distance, compass direction, what they rest on), one summary line for the rest, and every player within the radius (in view or not) |
| `act(type, data)` | one line. `type` is MoveTo, Jump, Stop, Pickup, Place or Throw. MoveTo waits for arrival or a stop and says why it stopped. `"jump": true` does the run-up and climb. |
| `say(text)` / `hear()` | chat; `hear()` returns new `name: text` lines, deduplicated by message id |
| `history(n=20)` | your last n actions with their results, one line each |
| `map_card()` | a one-time description of the fixed scenery: island, ocean, walls, platforms with heights, landmarks |
| `full_look()` | the raw observation JSON, unchanged. It's there whenever the model wants everything; it costs about 14–17k tokens. |

Each world has its own `Rules` (reach distances, actions, play card) in `world.py`:
`MESA_RULES` for mesa-island and `BEACH_RULES` for AI-Beach's own `worlds/beach`. The adapter
picks one from the first observation; pass `rules=` to fix it. The play cards are the action
references a model gets while playing: `PLAY_CARD.md` (mesa-island, 373 tokens) and
`beach/PLAY_CARD.md` (beach, 400 tokens), both counted with the Gemma 4 E4B tokenizer.

On the beach, `act` also takes **Kick** `{"direction", "power"}` and **Mold** `{"shape"}`.
A castle in a plot is described as one line (`sandcastle in plot 1 ...: 4 pieces, 3 high,
with a flag, standing`). Its pieces are listed only when they're within your reach. World
announcements (goals, falls) arrive in `hear()` and in `recent` as `World: ...` lines.

## The hand-off contract

The game provides **three labeled pieces per turn**, each with its token size. That's all it
provides. How a host uses them is up to the host.

```python
turn_bundle(game) == {
    "tools":  {"text": ..., "tokens": n},   # the play card and the action definitions
    "state":  {"text": ..., "tokens": n},   # the map card (first turn only) and the current look
    "recent": {"text": ..., "tokens": n},   # the last 8 action results and the last 6 chat lines
    "total_tokens": n,
    "token_method": "tokenizer:google/gemma-4-E4B-it" | "approx chars/4",
}
```

Options: `turn_bundle(game, n_actions=8, n_chat=6, include_map=None)`.

### Sizes

Measured with the Gemma 4 E4B tokenizer (`google/gemma-4-E4B-it`).

**mesa-island**: three scripted 50-turn sessions; details in `docs/research/ADAPTER_REPORT.md`.

| Piece | Typical (median) | Worst case seen |
|---|---|---|
| tools | 526 (constant; 519 before job 03 widened the `hear` description) | 526 |
| state | about 320 (look only) | about 800 (map card + look, first turn or on request) |
| recent | about 280 | about 990 (8 actions + six 500-character chat lines) |
| **total** | **about 1,130** | **about 2,300** (stress case) |

The raw observation for the same turns is about 13.7k–17.2k tokens. A job-03 regression run on
mesa-island (after the beach changes) still completed the task: median 1,138, max 1,316.

**beach**: three scripted 62-turn sessions plus a two-player run; details in
`docs/research/BEACH_WORLD_REPORT.md`.

| Piece | Typical (median) | Worst case seen |
|---|---|---|
| tools | 555 (constant) | 555 |
| state | about 190 (look only) | about 580 (map card + look next to a finished castle with all balls) |
| recent | about 300 | about 370 |
| **total** | **about 1,040** | **about 1,480** |

Four castles of 9 pieces each cost 143 tokens as castle lines, against 884 if every piece
were listed.

## Tests

```bash
python3 -m unittest discover -s tests          # unit tests on recorded fixtures; no server needed
CLAWBLOX_BIN=/path/to/clawblox CLAWBLOX_WORLD=/path/to/worlds/mesa-island \
  python3 -m unittest tests.test_clawblox_integration   # starts a headless server on a temp copy
```

## Limits

- Each world needs its own `Rules` and play card (mesa-island and beach exist).
- MoveTo walks in a straight line; there's no pathfinding around platforms.
- On mesa-island, a player who has never been inside your view cone shows as "unknown player".
  The beach labels every character with its player's name, so there everyone is named.
- `turn_bundle()` reads the chat log without using up what `hear()` returns.
