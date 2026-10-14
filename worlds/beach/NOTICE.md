# Third-party notice

This world runs on [Clawblox](https://github.com/nacloos/clawblox) (MIT License,
Copyright (c) 2026 nacloos). The Clawblox engine itself is **not** part of this
repository. Two files here are derived from Clawblox's `worlds/mesa-island` at
commit `8be90a0`:

| File | Derived from | What changed |
|---|---|---|
| `renderer/src/index.js` | `worlds/mesa-island/renderer/src/index.js` | Beach visuals (sand, sea floor, goal posts, plot markers, balls, sand pieces with a flag shape), players drawn as their Beach chibi instead of a GLB model (built from simple shapes by `renderer/src/chibi.js`, which is ours, in each player's Beach look from `static/tints.json`; a name label above each), a banner for world announcements, and three.js imported from the vendored copy instead of esm.sh. Mesa-island's code paths are otherwise kept. |
| `renderer/package.json` | `worlds/mesa-island/renderer/package.json` | Package name only. |

`main.lua` is new; its Pickup / Place / Throw handlers follow the same pattern as
mesa-island's `main.lua`.

Clawblox's licence text is in `renderer/LICENSE.clawblox`. No Clawblox assets
(e.g. `player.glb`) are included.

`static/vendor/` holds unchanged (or bundled) copies of three.js 0.160.0 (MIT) and
lucide 0.468.0 (ISC), each with its licence; see `static/vendor/README.md`.
