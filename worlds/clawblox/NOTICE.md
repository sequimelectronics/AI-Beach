# Third-party notice: the ClawBlox zone

ClawBlox is [Clawblox](https://github.com/nacloos/clawblox)'s own `mesa-island` world (MIT License,
Copyright (c) 2026 nacloos). Its world script (`main.lua`), settings and player model are **not** in
this repository: `scripts/clawblox_world.py` copies them from your own Clawblox checkout at run time.

One file here is derived from Clawblox's `worlds/mesa-island` at commit `8be90a0`:

| File | Derived from | What changed |
|---|---|---|
| `renderer/src/index.js` | `worlds/mesa-island/renderer/src/index.js` | The three.js import points at the vendored copy (`static/vendor/three`) instead of esm.sh, plus an attribution comment. Each player's character is passed to `beach-tint.js` (four lines, marked "AI Beach"). Nothing else. |
| `renderer/package.json` | `worlds/mesa-island/renderer/package.json` | Package name only. |

`renderer/src/beach-tint.js` is ours (not derived): it gives each player's copy of the claw
character's material their Beach colours (the red shell becomes their outfit colour, the gold plates
their trim colour) with a few lines of shader code. The character model itself (`player.glb`) is
Clawblox's, copied at run time from your checkout and never changed or committed.

Clawblox's licence text is in `renderer/LICENSE.clawblox`. The vendored three.js and lucide come from
`worlds/beach/static/vendor/` (licences and sources listed there).
