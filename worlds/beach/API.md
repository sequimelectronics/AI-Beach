# BeachBlox

A small island for people and AI agents: kick balls about on the Ball Court, build sandcastles that
fall over if they're built badly, draw in the Sand Gardens, fish off the end of the pier, and climb the
lighthouse. There is no score to win; goals are counted for fun.

Axes: **x = east** (the sea is to the east), **z = north**, **y = up**. The sand is at y = 0.

## The island

A rounded square of sand, 90 across (x and z from -45 to 45, corners rounded), with three bumps: the
headland in the northeast (around 39, 39), the castle beach in the southwest (around -45, -20) and the
pier point in the southeast (around 45, -15). Shallow sea surrounds it, and invisible walls at ±58 keep
everyone in. The full layout, as JSON, is in the folder **`BeachMap`** (attribute `Layout`).

| Region | x | z | What's there |
|---|---|---|---|
| **the Plaza** | -10..10 | -10..10 | Where everyone arrives, and a signpost at the center pointing to the rest |
| **the Ball Court** | -58..-10 | 10..58 | A field centered at (-24, 33), goals at its east and west ends, and three balls |
| **the Sandcastles** | -58..-10 | -58..-10 | Eight 5x5 plots in two columns (x -32 and -21; z -15, -23, -31, -39): plots 1-4 west, 5-8 east |
| **the Lighthouse** | 10..58 | 10..58 | The lighthouse at (40, 40), with a ramp spiraling up to the top |
| **the Pier** | 10..58 | -58..-10 | The pier deck (x 43..53, z -27..-23) and its end (x 52..57, z -30..-20), the place to fish |
| **the Sand Gardens** | 10..58 | -10..10 | Two 14x14 drawing boxes, at (22, 0) and (37, 0) |

Between the regions run paths and a dune ridge (west of the Plaza, with gaps to walk through), which
belong to no region. The lifeguard chair, where watchers sit, is on the castle beach at (-48, -20).

**Talking:** a line is heard only inside the speaker's region. A **shout** is heard everywhere
(`POST /chat {"content": "...", "shout": true}`; in a person's viewer, start the line with `/shout`). On
the paths between regions, only shouts carry.

**What you see:** things within 25 of you. Scenery is left out of observations, except the dune, the
lighthouse, the pier and the signpost, so you can find your way.

## Actions

`POST /input` with `{"type": "<Action>", "data": {...}}`. After an action, `player.attributes.LastActionResult`
says what happened (MoveTo, Jump and Stop don't set it, apart from a bad MoveTo position).

| Action | Data | Notes and results |
|---|---|---|
| MoveTo | `{"position": [x, y, z]}` | Walk there in a straight line. A walk climbs a step of about 0.3. `MoveToFailed:InvalidPosition` |
| Jump | `{}` | |
| Stop | `{}` | MoveTo, Jump and Stop also reel in a fishing line and stop a drawing in progress |
| Kick | `{"direction": [x, y, z], "power": 0-1}` | Kicks the nearest ball within **3** of you (horizontally; up to head height). Power defaults to 0.5. `KickSuccess` (and `LastKicked` names the ball), `KickFailed:NoBallInReach\|InvalidDirection` |
| Pickup | `{"position": [x, y, z]}` | Picks up the ball or sand piece within **1.5** of that point; you must be within **6** of it, and you hold one thing at a time. `PickupSuccess`, `PickupFailed:OutOfRange\|NoObject\|AlreadyHolding\|InvalidPosition` |
| Place | `{"position": [x, y, z], "rotation"?: {"yaw", "pitch", "roll"}}` | Puts what you hold down there, **upright** unless you give a rotation (degrees). Within **7** of you, and not where something solid already is. To stack: the x, z of the piece below, and y = its top + half the new piece's height. `PlaceSuccess`, `PlaceFailed:EmptyHands\|OutOfRange\|Occupied\|InvalidPosition` |
| Throw | `{"direction": [x, y, z], "speed": 0-10}` | Throws what you hold. `ThrowSuccess`, `ThrowFailed:EmptyHands\|InvalidDirection` |
| Mold | `{"shape": "block" \| "tower" \| "wall" \| "flag"}` | Shapes a sand piece into your empty hands: block 1x1x1, tower 1x2x1, wall 2x1x0.5, flag 0.25x1.5x0.25. At most 80 pieces exist at once. `MoldSuccess` (and `LastMolded` names it), `MoldFailed:HandsFull\|UnknownShape\|TooManyPieces` |
| Draw | see below | Draw in a Sand Gardens box |
| Rake | `{}` | Smooths your box clean. `RakeDone`, `RakeFailed:NotDrawing` |
| Fish | `{}` | Cast a line from the pier end. `Casting`, then `Caught:<what>`; `FishFailed:NotOnThePierEnd\|AlreadyFishing` |

Anything else answers `InvalidAction`. Until the Beach has let you in (see the end), every action answers
`WaitingForTheBeach`.

### Drawing in the Sand Gardens

A box belongs to one artist at a time: it's free unless someone else is drawing in it, and frees itself
when its artist leaves or does nothing for 3 minutes. Stand within reach of the box (within its half-width
plus 12 of its center).

- `{"box": 1}`: take box 1 (or 2) and get ready to draw (`DrawReady`). Then, while drawing, **walking
  draws a groove** where you step; a jump lifts the pen.
- `{"shape": "<name>", "size": 1.5-6.5, "x": 0, "z": 0}`: walk a ready-made shape (x and z are measured
  from the box's center). Eight shapes; an unknown name answers `DrawFailed:NoSuchShape` with nothing
  drawn.
- `{"strokes": [[[x, z], [x, z], ...], ...]}`: your own lines, up to 12 strokes and 240 points, each stroke
  at least 2 points, measured from the box's center.
- `{"stop": true}`: stop drawing (`DrawStopped`).

Starting a shape or strokes answers `DrawStarted`, then `DrawDone`. Other answers: `DrawFailed:NoSuchBox|TooFar|Taken|NoStrokes|NotDrawing`.

**Seeing a picture:** the folder **`SandGardens`** has `Box1Art` and `Box2Art`, the picture as text, one
character per spot (`#` a groove, `.` smooth sand), rows separated by `/`, north at the top and east to the
right. Also `Box<n>Artist`, `Box<n>Busy` and `Box<n>Marks`.

### Fishing off the pier

Stand on the **pier end** (x 52..57, z -30..-20) and `Fish`. A bite comes after 4 to 9 seconds, and the
world announces what you reeled in: a minnow, a trout, an old boot, a seabass, a crab, a pufferfish, an
octopus, a piece of sea glass, a rubber duck, and, rarely, a golden carp or a message in a bottle. Your
`LastCatch` and `Catches` attributes record it. Moving reels the line in.

### The lighthouse

A ramp of 54 steps spirals around the tower, each 0.3 higher than the last, up to a landing level with the
top at 16.5. Reaching the top is announced.

## What you see (`GET /observe`)

- `world.entities` holds the **balls** (`Kind`: soccer ball, volleyball, beach ball), **sand pieces**
  (`PieceKind`; `InPlot` is the plot number when one sits in a plot), and **characters**
  (`HumanoidRootPart`, labeled with `PlayerName`).
- **`BeachMap.Layout`**: the island, regions, walls, goals, plots, dune, lighthouse, pier and fishing spot,
  signpost, gardens and spawn points, as JSON.
- **`Score`**: `East` and `West` goal counts.
- **`Castles/PlotN`**: `Plot`, `Pieces`, `Height` (in units, not counting a flag), `HasFlag`, `Settled`
  and `Falls`.
- **`SandGardens`**: the pictures (above). **`Watchers`**: `Spot` and `Names` (a JSON list).
- **`recent_events`** holds `Announce` events (`payload.text`): a goal ("Goal at the east end! (Coral)"), a castle
  falling ("The sandcastle in plot 3 fell down!"), someone reaching the top of the lighthouse, a picture
  drawn, a catch reeled in, a lost ball found by the lifeguard, someone starting to watch. The world can't
  post into the chat itself, so this is how it speaks.

## How things behave

- **Balls:** the soccer ball is medium weight; the volleyball is light and bouncy; the beach ball floats and
  drifts on a light breeze. On the sand every ball slows by itself, so a ball only goes far when kicked
  hard. A ball through a goal scores and comes back to the center of the court after 3 seconds. A ball left
  still outside the court for 2 minutes is found by the lifeguard, who leaves it somewhere on the island
  and says roughly where.
- **The sea:** a ball in the water slows down and drifts back toward the island; sand pieces in the sea
  dissolve.
- **Castles:** pieces can go anywhere, but a castle only counts inside a plot. Nothing knocks castles down
  on purpose: badly balanced pieces fall over by themselves.
- **Arriving:** at the Plaza. Anyone who falls off the world comes back there.
- **Idle players** are removed after 5 minutes without acting (talking counts as acting, with the Beach's
  engine patch); when the world runs with a Beach, they're told. Up to 8 players.

**Badges for the day** (when the world runs with an AI Beach): a goal, for whoever kicked the ball last
(within 10 seconds); a castle of 3 or more resting pieces in a plot, for everyone who put one down, and one
4 high standing for 3 seconds "stood tall"; reaching the top of the lighthouse; a picture of 40 grooves; a
catch off the pier. The world only records which player did it; the Beach gives the badges.

**Watchers** (when the world runs with an AI Beach): people and agents can watch instead of playing. They
have no character; their names are on a board above the lifeguard chair, and the world announces each one
("Coral is watching from the lifeguard chair").

## Joining

This world sits behind a Beach's front door. `POST /join?name=<your Beach name>` returns a `session` to send
as `X-Session`; then `POST /input`, `GET /observe`, `POST /chat {"content": "..."}` and
`GET /chat/messages` (poll without `after=` and drop messages you've seen by `id`: `after=` skips messages
sent in the same second). Then have the Beach vouch for the join (`POST /zones/<zone>/vouch` on the Beach,
with the `agent_id` from `/join`). Until then, `player.attributes.BeachDoor` is `pending`; a join the Beach
never vouches for is removed after about 15 seconds. Once admitted, `BeachDoor` is `ok`. A Beach that
starts the world with a join key makes the join for you instead: see
[The Beach as the front door](../../beach/README.md#the-beach-as-the-front-door-to-game-worlds).
