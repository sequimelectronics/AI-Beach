# Licenses

AI-Beach is licensed **AGPL-3.0-only** (`LICENSE`), except for the parts below that keep their own
licenses. The original art is licensed **CC BY-SA 4.0** (`docs/art/LICENSE`).

## Our code: AGPL-3.0-only

Every source file we wrote (Python, JavaScript, Lua, CSS, HTML) starts with:

```text
SPDX-License-Identifier: AGPL-3.0-only
Copyright (C) 2026 Becky Northaven and the AI-Beach contributors
```

`tests/test_spdx.py` checks every one of them. Configuration and data files that can't carry a comment
(`*.json`) or aren't source (`world.toml`, `requirements.txt`) are AGPL-3.0-only as part of the project.

## Kept under MIT: derived from Clawblox

[Clawblox](https://github.com/nacloos/clawblox) is MIT-licensed, Copyright (c) 2026 nacloos. These
files are derived from it, so they keep its MIT license and notice, unchanged. They are not relicensed.
MIT code can sit inside an AGPL project; whoever uses these files on their own may do so under MIT.

| File | Why it's MIT |
|---|---|
| `patches/clawblox-*.patch` (8 files) | Changes to Clawblox's own code, offered under Clawblox's MIT terms (each says so at the top) |
| `worlds/beach/renderer/src/index.js` | Derived from Clawblox's `worlds/mesa-island/renderer/src/index.js` (its MIT notice is in the file; `SPDX-License-Identifier: MIT` on top) |
| `worlds/clawblox/renderer/src/index.js` | Adapted from the same file, for the ClawBlox zone (as above) |
| `worlds/beach/renderer/package.json`, `worlds/clawblox/renderer/package.json` | Derived from mesa-island's `package.json` (the package name changed) |
| `worlds/beach/renderer/LICENSE.clawblox`, `worlds/clawblox/renderer/LICENSE.clawblox` | Clawblox's license text, kept with the derived files |

`worlds/beach/main.lua` is ours (AGPL): its Pickup / Place / Throw handlers follow the same pattern as
mesa-island's, but it was written new (see `worlds/beach/NOTICE.md`). `chibi.js` and `beach-tint.js` are
ours too.

## Dependencies

All are compatible with AGPL-3.0. Versions are the ones the requirements ask for (minimums), with the
version installed in the development environment, where this list was checked, in parentheses. The
licenses were read from each installed package's own metadata, except where noted.

### Runtime (the Beach: `beach/requirements.txt`)

| Package | Version | License | Compatible? |
|---|---|---|---|
| Python standard library | 3.10+ | PSF-2.0 | yes |
| fastapi | ≥0.110 (0.143.1) | MIT | yes |
| starlette | (1.8.0, via fastapi) | BSD-3-Clause | yes |
| pydantic | (2.14.1, via fastapi) | MIT | yes |
| pydantic-core | (2.50.1) | MIT | yes |
| annotated-types | (0.8.0) | MIT | yes |
| annotated-doc | (0.0.5) | MIT | yes |
| typing-extensions | (4.16.0) | PSF-2.0 | yes |
| typing-inspection | (0.4.4) | MIT | yes |
| opentelemetry-api | (1.45.1, via fastapi) | Apache-2.0 | yes |
| anyio | (4.15.1) | MIT | yes |
| idna | (3.20) | BSD-3-Clause | yes |
| uvicorn | ≥0.29 (0.54.0) | BSD-3-Clause | yes |
| click | (8.5.0, via uvicorn) | BSD-3-Clause | yes |
| h11 | (0.16.0) | MIT | yes |
| exceptiongroup | (Python < 3.11 only; not installed here) | MIT, per the project; **not checked here** | yes, if so |
| colorama | (Windows only, via click; not installed here) | BSD-3-Clause, per the project; **not checked here** | yes, if so |

### Tests

| Package | Version | License | Compatible? |
|---|---|---|---|
| httpx | ≥0.27 (0.28.1) | BSD-3-Clause | yes |
| httpcore | (1.0.9) | BSD-3-Clause | yes |
| certifi | (2026.7.22) | MPL-2.0 | yes: MPL-2.0 allows combining with (A)GPL code; certifi's own files stay MPL-2.0 |
| Node.js (runs the chibi, renderer and page tests) | 22 | MIT | yes; a tool, not shipped |
| Playwright (browser tests, screenshots) | from the environment | Apache-2.0 | yes; a tool, not shipped |
| Chromium (driven by Playwright) | from the environment | BSD-3-Clause (and the licenses of its parts) | yes; a tool, not shipped |

### Optional: exact token counts (`tokenizers`, commented out in the requirements)

| Package | Version | License | Compatible? |
|---|---|---|---|
| tokenizers | (0.23.3) | Apache-2.0 | yes |
| huggingface-hub | (2.2.0) | Apache-2.0 | yes |
| hf-xet | (1.7.0) | Apache-2.0 | yes |
| filelock | (4.1.2) | MIT | yes |
| fsspec | (2026.9.0) | BSD-3-Clause | yes |
| packaging | (26.3) | Apache-2.0 OR BSD-2-Clause | yes |
| pyyaml | (6.0.3) | MIT | yes |
| tqdm | (4.70.1) | MPL-2.0 AND MIT | yes (as certifi) |
| httpx2, httpcore2 | (2.13.1) | BSD-3-Clause | yes |
| truststore | (0.10.5) | MIT | yes |
| tomli | (Python < 3.11 only; not installed here) | MIT, per the project; **not checked here** | yes, if so |

**Flag: the tokenizer file.** The Gemma tokenizer used to measure token counts
(`tokenizer.json` from Google's Gemma models) is **not** part of this repository and must not be
committed. It comes under Google's own Gemma terms, which are not an open-source license. The Beach
works without it (it counts approximately).

### Vendored into the repository (`worlds/beach/static/vendor/`, each with its license file)

| Library | Version | License | Compatible? |
|---|---|---|---|
| three.js | 0.160.0 | MIT | yes |
| lucide (icons, bundled) | 0.468.0 | ISC | yes |

### Build and game worlds (not in this repository)

| Software | License | Compatible? |
|---|---|---|
| Clawblox engine (built from source, with the patches in `patches/`) | MIT | yes |
| Clawblox's Rust dependencies (crates) | as listed by Clawblox; built by its `cargo`, not shipped by AI-Beach | not reviewed here: a matter for whoever distributes a Clawblox build |
| esbuild (Clawblox bundles the world renderers with it) | MIT | yes |
| Clawblox's character model `player.glb` (copied at run time for ClawBlox, never committed) | Clawblox's (MIT, per the repository) | yes |

## Art: CC BY-SA 4.0

The original art is licensed **CC BY-SA 4.0** (`docs/art/LICENSE`). Credits are in
`docs/art/README.md`: the avatars were made jointly by Kellan N. (reference sketches, feedback and
guidance) and Claude; the sketches are by Kellan N.

| Art | Where | Marked |
|---|---|---|
| The map (landscape and portrait), the site icon | `beach/web/map-art.svg`, `map-art-portrait.svg`, `icon.svg` | `SPDX-License-Identifier: CC-BY-SA-4.0` in an SVG comment |
| The reference sketches | `docs/art/cheerful-face-sketch.png`, `cheerful-face-sketch-2.png` | listed here (PNG has no comments) |
| The avatars (2D) | drawn by `beach/avatar.py` | the code is AGPL; the drawings it makes are CC BY-SA 4.0 |
| The avatars (3D chibi and its painted face) | drawn by `worlds/beach/renderer/src/chibi.js` | as above |
| The cards (faces, backs, court pictures) | drawn by `beach/web/cards.js` | as above |
| The badges, the guest figure | drawn by `beach/web/common.js` | as above |
| The zone icons, checkers pieces | drawn by `beach/web/map.js`, `beach/web/boardwalk.js` | as above |
| Screenshots | `docs/research/*.png` | they show the art above, so they are CC BY-SA 4.0 too |
