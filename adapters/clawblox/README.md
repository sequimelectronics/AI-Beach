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

`adapters/clawblox/PLAY_CARD.md` is the action reference: 373 tokens with the Gemma 4 E4B
tokenizer.

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

Measured with the Gemma 4 E4B tokenizer (`google/gemma-4-E4B-it`) over three scripted 50-turn
sessions on mesa-island. Details are in `docs/research/ADAPTER_REPORT.md`.

| Piece | Typical (median) | Worst case seen |
|---|---|---|
| tools | 519 (constant) | 519 |
| state | about 320 (look only) | about 800 (map card + look, first turn or on request) |
| recent | about 280 | about 990 (8 actions + six 500-character chat lines) |
| **total** | **about 1,130** | **about 2,300** (stress case) |

The raw observation for the same turns is about 13.7k–17.2k tokens.

## Tests

```bash
python3 -m unittest discover -s tests          # unit tests on recorded fixtures; no server needed
CLAWBLOX_BIN=/path/to/clawblox CLAWBLOX_WORLD=/path/to/worlds/mesa-island \
  python3 -m unittest tests.test_clawblox_integration   # starts a headless server on a temp copy
```

## Limits

- The world constants in `world.Rules` (reach 6/7, match 1.5, throw cap 10, jump rise, run-up) are
  mesa-island's. Another world needs its own `Rules` and play card.
- MoveTo walks in a straight line; there's no pathfinding around platforms.
- A player who has never been inside your view cone shows as "unknown player" until they are.
