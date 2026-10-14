# Third-party notice: the ClawBlox zone

ClawBlox is [Clawblox](https://github.com/nacloos/clawblox)'s own `mesa-island` world (MIT License,
Copyright (c) 2026 nacloos). Its world script (`main.lua`), settings and player model are **not** in
this repository: `scripts/clawblox_world.py` copies them from your own Clawblox checkout at run time.

One file here is derived from Clawblox's `worlds/mesa-island` at commit `8be90a0`:

| File | Derived from | What changed |
|---|---|---|
| `renderer/src/index.js` | `worlds/mesa-island/renderer/src/index.js` | The three.js import points at the vendored copy (`static/vendor/three`) instead of esm.sh, plus an attribution comment. Nothing else. |
| `renderer/package.json` | `worlds/mesa-island/renderer/package.json` | Package name only. |

Clawblox's licence text is in `renderer/LICENSE.clawblox`. The vendored three.js and lucide come from
`worlds/beach/static/vendor/` (licences and sources listed there).
