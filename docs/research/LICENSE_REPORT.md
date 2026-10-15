# License and chat activity report (job 14)

**Coverage.** Everything in the brief is done except one item. The `LICENSE` file (the full AGPL v3
text) is **not** in this change. The environment's network policy refused `www.gnu.org`, the
brief's required source, so I stopped that item as the brief says. I did not type it or rebuild it
from memory. Everything else is done: SPDX headers on every source file we wrote, the MIT files left as
they are, `docs/LICENSES.md` with every dependency, the art license and credits, the README License
section, `CONTRIBUTING.md`, the SPDX check, the engine patch that makes chat count as activity, and a
live test for it. **Don't merge until `LICENSE` is added** (it's one command; see below), because the
README and `docs/LICENSES.md` point to it.

## 1. The LICENSE file: not done (network blocked)

- Source the brief requires: `https://www.gnu.org/licenses/agpl-3.0.txt`.
- Result, tried twice (once at the start and once before this report): `curl: (56) CONNECT tunnel
  failed, response 403`. The session's proxy reports `www.gnu.org:443 connect_rejected`. It is the
  environment's network policy, not the site.
- SHA-256: none, since nothing was fetched.
- To finish it: allow `www.gnu.org` in the cloud environment's settings (the environment menu in the
  session's title bar → Edit → Network access, add it under Allowed domains). Or, on any computer that
  can reach the site, from the repository's root:

  ```bash
  curl -fsSL -o LICENSE https://www.gnu.org/licenses/agpl-3.0.txt
  sha256sum LICENSE        # record this in the commit message
  head -3 LICENSE          # "GNU AFFERO GENERAL PUBLIC LICENSE" / "Version 3, 19 November 2007"
  ```

  Commit it unchanged: no header and no edits.

The CC BY-SA 4.0 legal code wasn't fetched either, for the same reason. The brief allows its official
name and link instead, so `docs/art/LICENSE` gives the name, the SPDX identifier, and the official
summary and legal-code links.

## 2. SPDX headers and the check

- **Header lines.** Each source file we wrote (Python, JavaScript, Lua, CSS, HTML and shell) starts
  with these two lines, in its own comment style:

  ```text
  SPDX-License-Identifier: AGPL-3.0-only
  Copyright (C) 2026 Becky Northaven and the AI-Beach contributors
  ```

  The comment styles are `#`, `//`, `--`, `/* */` and `<!-- -->`. A shebang or `<!doctype html>`
  stays first.
- **Files covered.** 94 files carry these lines: the 93 that existed, plus the new
  `tests/test_spdx.py`.
- **The check.** `tests/test_spdx.py` lists the repository's files (`git ls-files`, including new ones
  not yet committed; it walks the folders if git isn't there) and checks the first few lines of each.
  - Our files must have both lines.
  - The two renderers derived from Clawblox must have `SPDX-License-Identifier: MIT`, keep their
    `Copyright (c) 2026 nacloos` notice and point to `LICENSE.clawblox`, which must hold the MIT
    permission text.
  - The three art SVGs must say `CC-BY-SA-4.0`.
  - Vendored files must be left alone.
  - All eight patches must keep their MIT attribution.
- **Result:** 7 tests, OK.
- **Negative check:** I removed the two lines from `beach/hooks.py`. The test then failed with
  `beach/hooks.py: needs 'SPDX-License-Identifier: AGPL-3.0-only' and 'Copyright (C) 2026 …'`.
  I put the lines back afterward.
- **Full suite:** 423 tests, OK (3 skipped: the live Clawblox tests, which need `CLAWBLOX_BIN`).

## 3. Files that keep MIT, and why

[Clawblox](https://github.com/nacloos/clawblox) is MIT, Copyright (c) 2026 nacloos. These files are
derived from it, so their MIT notice stays exactly as it was and they are not relicensed:

| File | Why |
|---|---|
| `patches/clawblox-*.patch` (8) | Changes to Clawblox's own code, offered under its MIT terms. Each says so at the top. |
| `worlds/beach/renderer/src/index.js` | Derived from mesa-island's renderer. I added only `// SPDX-License-Identifier: MIT` above its existing notice. |
| `worlds/clawblox/renderer/src/index.js` | Adapted from the same file. Same treatment. |
| `worlds/beach/renderer/package.json`, `worlds/clawblox/renderer/package.json` | Derived from mesa-island's. JSON can't hold a comment, so they are listed in `docs/LICENSES.md`. |
| `worlds/beach/renderer/LICENSE.clawblox`, `worlds/clawblox/renderer/LICENSE.clawblox` | Clawblox's own license text, kept beside the derived files. Unchanged. |

**Files that are ours (AGPL), and why.** I went by each world's `NOTICE.md`.
- `worlds/beach/main.lua` is ours. It follows the same handler pattern as mesa-island's, but it
  was written new.
- `chibi.js` and `beach-tint.js` are ours too.
- The vendored three.js (MIT) and lucide (ISC) under `worlds/beach/static/vendor/` are untouched.
  They have their own license files.

## 4. Dependencies (`docs/LICENSES.md`)

Every runtime, test, optional, vendored and build dependency is listed there with its version and
license. The licenses come from each installed package's own metadata.

**Every one I checked is compatible with AGPL-3.0.** These need a decision or a note:

- **certifi and tqdm (MPL-2.0).** They're compatible: MPL-2.0 explicitly allows combination with
  GPL-family code, and their own files stay MPL. certifi is used only by the tests (via httpx).
  tqdm is used only by the optional tokenizer stack.
- **Conditional packages weren't installed here, so I couldn't check their metadata.**
  `exceptiongroup` and `tomli` are only pulled in on Python < 3.11. `colorama` is pulled in through
  click, on Windows only. The table gives their license as each project states it and marks it
  "not checked here".
- **The Gemma tokenizer file is under Google's Gemma terms.** Those terms are not an open-source
  license. The file is not in the repository, and it must never be committed. The Beach works
  without it.
- **Clawblox's Rust crates weren't reviewed.** AI-Beach doesn't ship Clawblox. Whoever distributes a
  Clawblox build is responsible for those crates' licenses.
- **Some art is drawn by code.** The avatars, cards and badges are drawn by our code. The code is
  AGPL, and the pictures it draws are CC BY-SA 4.0. **Confirmed by the keeper (2026-10-15).**
- **Kellan N.'s sketches.** Her earlier permission was for the sketches "to be included and
  released with this repository". **CC BY-SA 4.0 for the sketches confirmed by the keeper
  (2026-10-15).** Under it, others can reuse and adapt the sketches, with credit.

## 5. Art

- **License.** `docs/art/LICENSE` says the art is CC BY-SA 4.0 and gives the official links.
- **Credits.** `docs/art/README.md` keeps its existing sketch credit and adds:
  - a Credits section: the avatars were made jointly by Kellan N. (reference sketches, feedback and
    guidance) and Claude; the map, cards and badges are by Claude;
  - a License section with the credit line to use.
- **Marking.** The three SVGs (`icon.svg`, `map-art.svg`, `map-art-portrait.svg`) carry
  `SPDX-License-Identifier: CC-BY-SA-4.0` in a comment. The PNG sketches, the screenshots and the
  drawn art are listed in `docs/LICENSES.md`.

## 6. Chatting counts as being active

- **The cause.** A Clawblox world removes a player who hasn't acted for its `afk_timeout`. That is
  300 s in BeachBlox, and the limit is unchanged. Only inputs called
  `record_player_activity` (in `queue_input`). The chat handler (`local_chat` in
  `src/bin/cli.rs`) never did. So someone standing still and talking was removed after five
  minutes.
- **The fix: `patches/clawblox-chat-activity.patch`.** It has its MIT attribution and its reason at
  the top, like the others. It does three things:
  - adds `record_activity(state, game_id, agent_id)` in `src/game/manager/players.rs`;
  - adds a wrapper for it in `src/game/mod.rs`;
  - calls it from `local_chat`.
  It doesn't touch the idle limit.
- **The patches apply.** All eight apply to a fresh checkout of Clawblox `8be90a0`, in the table's
  order, and the new one also applies on its own. `beach/README.md` has the new row, the updated apply
  loop, and a line under "Play or Watch, and the world's idle limit".
- **The live test.** `LiveChatIdleTest` in `tests/test_clawblox_integration.py` runs the beach world
  behind a Beach, with the idle limit cut to 6 s in the temporary copy only.
  - Sandy says a line every 1.5 s for 24 s and never moves.
  - Pebble does nothing.
  - Then Sandy's look still shows Sandy in the world, and Pebble's raises `CharacterGone` (removed).

  | Clawblox build | Result |
  |---|---|
  | With the patch | **OK** (with `LiveBeachTest`: 3 tests in 47.8 s, 1 skipped) |
  | Without it (the earlier build) | **Fails:** Sandy is removed too (`CharacterGone: … HTTP 400: Not in any instance of this game`) |

  So the test shows the patch is what keeps a chatting player in the world.
- **A static check.** `ChatActivityPatchTest` in `tests/test_spdx.py` checks that the patch calls
  `record_activity` inside `local_chat` and changes no `afk_timeout` line. It runs everywhere,
  without the engine.

## 7. Smaller fixes along the way

- **Spelling.** "licences" in `worlds/clawblox/NOTICE.md` and `docs/research/BEACH_FRONT_REPORT.md`
  is now "licenses". The spelling check missed the plural, so I added "licences" to its list.
- **`CONTRIBUTING.md` is new.** It covers four things:
  - contributions are AGPL-3.0-only, and art is CC BY-SA 4.0;
  - the header lines and their check;
  - files derived from Clawblox stay MIT;
  - the household rules: no real people's or households' names or details in code, tests, docs or
    history, except the approved credits.

## Not finished

- `LICENSE` (section 1). This is the one blocker before merging.
- Confirming the license for three conditional packages (exceptiongroup, tomli, colorama) from
  installed metadata. They're not installed in this environment.
