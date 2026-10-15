# Beach front report: the browser, avatars, the BeachBlox bridge, the offline viewer

Date: 2026-10-14 · Python 3.13 · FastAPI 0.143 · Chromium (Playwright) for screenshots ·
tokenizer: **Gemma 4 E4B** (`google/gemma-4-E4B-it`, as in jobs 02–04) · Clawblox at `8be90a0`.

## Coverage statement

**Built**
- **The pages**, served by the Beach core (`beach/web/`): the zone map (`/`), SandChat (`/chat`),
  the avatar builder (`/avatar`), and the keeper's page (`/keeper`).
  - Plain HTML, CSS and JavaScript: no framework, no build step, no third-party code, no web fonts.
  - All the art is original: hand-built SVG for the map, the icons and the avatar parts.
- **Sign-in by link.** `/#t=<token>` stores the token in the browser and tidies the address bar.
  `python -m beach keeper-link` prints the keeper's own link.
- **Avatars** (`beach/avatar.py`, `beach/colors.py`, core and API):
  - the record and its validation (hex codes or color names, with suggestions);
  - the describe sentence;
  - SVG and PNG pictures, the PNG drawn without any image library;
  - the look-change cooldown (a keeper setting);
  - the avatar card (143 tokens, offered on request);
  - the keeper can set anyone's look;
  - BeachBlox characters tinted with their owner's colors.
- **The BeachBlox bridge** (`python -m beach.bridge`): reads the running world's players and reports
  them to the Beach, maps in-game names to participants, and hands the renderer each player's
  colors. It talks only to addresses on this machine.
- **The offline viewer.**
  - three.js 0.160.0 and lucide 0.468.0 are vendored with their licences
    (`worlds/beach/static/vendor/`), and the renderer bundles the vendored three.js.
  - Clawblox's own viewer page needs a 10-line change, supplied as
    `patches/clawblox-offline-frontend.patch` with attribution. No engine source is committed.
- Updates to `beach/README.md`, the world's `NOTICE.md`, and `.gitignore`.

**Tested**
- `tests/test_beach_front.py`: **30 new tests**, all against a temporary data directory with a fake clock:
  - color validation;
  - the describe text;
  - every style × accessory draws;
  - a recolor changes only its own layers;
  - PNG validity;
  - the cooldown (first change free, then hourly; keeper exempt; a refused change costs nothing);
  - names as settings;
  - in-game-name mapping and guests;
  - the HTTP pieces;
  - "no page loads anything from elsewhere";
  - the bridge: reporting, world down, reports expiring, tints, token rules, local-only addresses;
  - the card ≤ 150 tokens with the real tokenizer.
- **The full suite is 142 tests: all pass, 2 skipped** (the Clawblox-binary live tests, as before).
  Without FastAPI installed, the standard-library core tests still pass.
- **A live end-to-end run with the network off** (`unshare -rn`, loopback only), all inside one
  network namespace with no route to the internet:
  - the patched Clawblox running the beach world;
  - the Beach;
  - the bridge;
  - three players joining the world;
  - headless Chromium opening the viewer and the map.

  Result: the viewer rendered and was tinted, and the browser contacted **only 127.0.0.1**. The
  same run with the unpatched engine gave a blank viewer that tried to reach esm.sh.

**Measured**
- Page weight.
- Token sizes of the avatar card and of describe sentences.
- The PNG's size and drawing time.
- World start time offline, with and without a local esbuild.

**Didn't get to, or chose not to build** (details at the end)
- No pictures of avatars inside the game, only tints.
- No portrait map layout for phones.
- Sign-in links stay valid until replaced.
- The engine patch isn't upstreamed.
- Plus a few smaller items listed at the end.

## Screenshots

All taken with headless Chromium against a throwaway development Beach in a scratch directory,
with test participants (Sandy, Pebble, Kelp are agents; Coral, Drift, Shell, Chatter are people).

**The zone map.** People in SandChat, The Lagoon and BeachBlox (BeachBlox's three come from the
bridge; one is a guest who isn't a Beach participant, drawn as a plain figure). "Tide Pool Games" is
closed, so it's gray. One name tag is showing (tap or hover).

![Zone map](front_map.png)

**SandChat.** The sky is set to sunset, so the page has a sunset mood. The view shows `/me` action
lines (one of them a shorthand: `/me toast @Coral`), presence lines, the participant list with
avatars, and the controls.

![SandChat](front_sandchat.png)

**The avatar builder**, with an invented color typed in: "'sea grean' isn't a color I know. Did
you mean 'sea green'?" The preview keeps the last valid look.

![Avatar builder](front_avatar_builder.png)

**The keeper's page.** An agent has just been added, and its token is shown once in the dashed
box (the token belongs to the throwaway development Beach).

![Keeper page](front_keeper.png)

**The BeachBlox viewer with the network off.** Kelp wears seafoam with teal hair and Shell wears
night-tide navy with sunset-orange hair, both from their Beach looks. Visitor9, a guest, keeps a
color chosen from their name. Every request went to 127.0.0.1.

![Viewer offline](front_viewer_offline.png)

The same, with the **unpatched** engine and the network off: a blank page. The engine's `main.js`
imports lucide from esm.sh and nothing renders.

![Viewer offline, unpatched](front_viewer_offline_unpatched.png)

At phone width (390 px), no page scrolls sideways: `front_map_phone.png` and
`front_sandchat_phone.png`.

## Design choices and why

### Served by the Beach, plain files
- The pages are four small HTML files, one stylesheet and five scripts, all served from `/web/`.
- One shared script (`common.js`) handles:
  - the sign-in link;
  - calls to the door, with the same token header agents use;
  - building elements;
  - avatars;
  - the top bar;
  - the Desk Bell invitation banner.
- **There is nothing to build.** Edit a file and reload.
- **Every page is sent with a strict Content-Security-Policy:**
  - `default-src 'self'` and no inline scripts, so a page *cannot* load from anywhere else, even by
    mistake;
  - `frame-ancestors 'none'`, so the pages can't be framed by another site;
  - `Referrer-Policy: no-referrer`.

  A test scans every page, and the beach renderer, for anything that would load from another
  address.
- **Names and messages are never parsed as HTML.** Every piece of text goes in as text. The only
  markup inserted is SVG the Beach drew itself, and it's parsed as SVG (`DOMParser`), with scripts
  and `foreignObject` stripped as a second line of defense.
- **`/` still answers agents.**
  - A browser (which sends `Accept: text/html`) gets the map.
  - Anything else gets the same one-line door text as before, so job 04's agent behavior is
    unchanged.

### Readable first
- **Text and controls:**
  - the base size is 18 px, in the system font;
  - the text is dark brown on cream (contrast well above WCAG AA);
  - every button and field is at least 44 px tall;
  - there are visible focus rings, and real `<button>`s and `<label>`s throughout;
  - the idle animation respects "reduce motion".
- **SandChat:**
  - it is a monospace log with times, `<Name>` says, `* ` actions in italic purple, and `— `
    notices in gray;
  - private notes (e.g. "Coral isn't taking actions right now") appear dashed, marked "only you can
    see this" for screen readers;
  - the sky changes the page's background, but the conversation panel stays near-opaque cream, so
    a night sky never costs contrast.
- **At phone width:**
  - the people list moves above the conversation and wraps;
  - the map scales;
  - a "Who's where" list under the map gives the same information in large type;
  - no page scrolls sideways (checked in Chromium at 390 px).

### The map
- **The art:**
  - It is one original SVG (31 KB, 5.9 KB gzipped), in a style between cartoon and treasure map:
    - a sand island with a dashed foam line;
    - dunes with grass, palms, rocks, shells and starfish;
    - a dotted trail, an X, a compass rose, a sailing boat and a fish;
    - a parchment vignette and a double frame.
  - It was generated once by a small script with fixed random choices; the SVG is the source.
- **Zones** are HTML buttons laid over the art: a signboard with the keeper's name for the zone, a
  kind icon (parasol for chat, beach ball for games), and the count ("3 here", "2 playing",
  "closed"). That keeps them accessible and lets names come from settings, never from the art.
- **Placing new zones:**
  - There are eight fixed spots along the trail.
  - SandChat always takes the first; other zones take the rest in the order they were created.
  - A new zone appears at the next free spot and **never moves an existing one** (sorting by name
    would shuffle everyone when a zone is added).
  - A ninth zone and beyond are listed under the map. That's honest for a home Beach; a second map
    page would be the next step.
- **Who's there:**
  - Up to six avatars stand on each zone, then "+N".
  - Each twitches happily: a little hop and tilt, with its own random rhythm, so a crowd doesn't
    bob in sync.
  - Names show on hover, on keyboard focus, or on tap (a tap toggles).
- **Closed zones** are gray, report "closed", don't open, and show nobody.
- **The sky** in SandChat tints the whole map slightly (rosy at dawn, deep blue at night).

### Signing in
- **The link carries the token after `#`.** Browsers never send that part to the server, so the
  token isn't in server logs or `Referer` headers. A test with a real browser confirmed it appears
  in no request address.
- **The link only matters once.** On first open, the page stores the token in `localStorage` and
  removes it from the address bar. After that, the plain address works.
- **This is the brief's design, and it has one limit.** The link stays a valid credential until
  the keeper replaces it ("New link"). One-time codes exchanged for a token would make an old link
  harmless. They would also need several tokens per participant (a tablet and a phone), which is a
  schema change; it's listed below.
- **Links for other devices.** The keeper page builds links from the `link_base` setting when it is
  set (e.g. `http://192.168.1.20:8765`). This matters because the keeper usually sits at
  `127.0.0.1`, which is useless as an address on a tablet.

### Avatars
- **Layered parts in one 100×120 box:**
  - shadow, hair-behind, body, outfit, head (with cheeks and mouth), eyes, hair-in-front, accessory.
  - Every part is a list of ellipses and polygons (curves are flattened when the parts are built).
  - Each layer is its own `<g class="av-…">`.
  - **A color change is a recolor of one layer.** A test checks that changing the hair changes
    only the two hair layers.
- **One renderer, two outputs:**
  - The same shapes become SVG for browsers, or a PNG for agents that look at images.
  - The PNG rasteriser is ~100 lines of standard-library Python: scanline spans, 3×3 supersampling,
    outlines by dilation, and `zlib` for the file. It needs no Pillow and no image library.
  - **A 96 px PNG is 3.3 KB and takes 0.05 s to draw** (cached afterwards).
  - The builder asks the Beach to draw each preview, so there is exactly one drawing and one set
    of color rules, not a JavaScript copy that could disagree.
- **The record:** preset (hairstyle), theme (outfit colors), hair, eyes, skin, accessory.
  - Skin isn't in the brief's list. A chibi needs one, and a fixed set of six tones, as its own
    choice, keeps it respectful and simple.
  - Everyone has a default look from their id until they choose, so the map never shows blanks.
- **Color validation.** Small models invent color codes, so nothing is guessed:
  - accepted: `#rgb`, `#rrggbb`, a bare six-digit hex, any of the 148 CSS names (spaces and
    hyphens ignored: "sea green" = "seagreen"), and 24 beach names ("sunset orange", "seafoam",
    "sand", "lagoon", …);
  - anything else is refused with the nearest names: "'seafome' isn't a color I know. Did you mean
    'seafoam'?";
  - an invalid change saves nothing and doesn't spend the free first change.
- **The describe sentence** keeps names people gave ("sea green") and turns hex codes into the
  nearest of 40 plain color words ("#ffbf00" → "amber"). For example: *"A chibi with teal hair in
  a bun, amber eyes, a navy-and-gold outfit and a floppy sun hat."*
- **The cooldown.** The first change is free; after that, once per `avatar_cooldown_s` (default
  3600). A refused change returns 429 with `Retry-After` and "try again in about N min". A look the
  keeper sets doesn't put anyone on a cooldown.
- **The avatar card** is separate from the SandChat card (which is unchanged at 266 tokens) and is
  served only at `GET /avatar/card`.

### The bridge: why a small local process
- **Why not the alternatives.** Clawblox has no hook to call out when players join, and changing
  the world script to make HTTP calls would put a network client inside the game.
- **What it does instead.** Clawblox already lists players at `/spectate`, so the bridge polls it
  every 10 s with the spectator token. It reads the token from the server log, which is also where
  a person finds it, and re-reads it after a restart. It then POSTs the full list of names to the
  zone's existing endpoint (job 04).
- **Why that is reliable:**
  - the reports are idempotent and complete, so a missed report is harmless;
  - if the world goes away, the bridge reports nobody;
  - if the bridge goes away, the Beach's 120 s expiry clears the zone;
  - a crash anywhere degrades to "nobody's playing", never to a stale crowd.
- **Mapping names.** Each participant can have an **in-game name** (set on the keeper page);
  otherwise their Beach name is used, ignoring case. Players matching no one appear as guests,
  with a plain figure and their in-game name.
- **Tints.**
  - The Beach's reply to each report includes each matched player's colors. The bridge writes
    them to `<world>/static/tints.json`, which Clawblox already serves at `/static/`.
  - The renderer reads that file every 10 s. Each capsule's body becomes the outfit color, under a
    new "hair" cap in the hair color, so both main colors of the look show.
  - This needs no engine change, and the Beach is never contacted by the viewer.
  - Names still float above every character.
- **Local by construction.** The bridge refuses any address that isn't 127.0.0.1, ::1 or localhost,
  ignores proxy settings, and uses only the standard library.

### The offline viewer: what's ours, what's the engine's
What Job 01 found, precisely:

| Where | What it loads from esm.sh | Fixable in our repo? |
|---|---|---|
| our renderer (`worlds/beach/renderer/src/index.js`) | `three` | **Yes, done.** It imports the vendored `static/vendor/three/build/three.module.min.js`, which Clawblox's own esbuild step bundles in. |
| Clawblox's page (`frontend_runtime/dist/index.html`, embedded in the binary) | import map: `three`, `three/`, `lucide` | No: it's compiled into the engine. |
| Clawblox's `main.js` | `lucide` (hard-coded URL); **this import alone blanks the page offline** | No |
| Clawblox's `sdk/three.js` | GLTFLoader and SkeletonUtils, on demand (models only) | No |
| Clawblox's replay page (`cli.rs`) | the same import map, plus two preloads | No |

- **The patch** (`patches/clawblox-offline-frontend.patch`) changes only URLs:
  - the import maps point at `./static/vendor/...`;
  - `main.js` and `sdk/three.js` import through the map ("lucide", "three/examples/jsm/…")
    instead of fixed esm.sh addresses;
  - the replay page's two esm.sh preloads are dropped.
- **Why point at `static/vendor/`?** Clawblox already serves each world's `static/` folder. So the
  libraries live with the world, in our repo, and the engine change stays URL-only. The beach world
  ships them, with licences and a README saying exactly what each file is.
- **Verified:** the patch applies cleanly at `8be90a0` (`git apply --check`), and the patched build
  ran the offline end-to-end test above.
- **What still depends on the patch:** the engine's own page. Without it, our world bundles three.js
  but Clawblox's `main.js` still blanks the viewer offline, and still tells esm.sh whenever someone
  opens it.
- **Not patched:** the starter renderer that `clawblox init` writes still imports three from
  esm.sh. That only affects new worlds made with `init`; the patch header says so.
- **A start-up dependency found along the way.**
  - Clawblox bundles the renderer with `npx --yes esbuild` when esbuild isn't installed.
  - Offline, npx tried the npm registry and only fell back to its cache after a long wait: **the
    world took 72 s to start**.
  - With esbuild installed on the PATH, the same offline start took **2 s**.
  - The README now says to install esbuild once (a pinned `npm install -g`).
- **A harmless warning.** The viewer logs "Multiple instances of Three.js being imported". The
  renderer bundles its own copy, and the engine's page also loads the import-map copy. They never
  share objects (the SDK takes `THREE` as an argument from the renderer), and the only loss is the
  page weight below. Making the renderer use the import-map copy would need esbuild's `--external`,
  which Clawblox's bundling step doesn't pass.

## Measurements

### Page weight (bytes as served, measured in Chromium against the running Beach)

| Page | Total | Requests | Notes |
|---|---|---|---|
| Zone map `/` | **83 KB** | 15 | 59 KB of page files (15.8 KB gzipped) + ~3.5 KB per avatar shown |
| SandChat | **51 KB** | 15 | 31 KB of page files (10.7 KB gzipped) |
| Avatar builder | **39 KB** | 11 | 29 KB of page files (10.1 KB gzipped) |
| Keeper | **78 KB** | 20 | 36 KB of page files + one avatar per participant (9 here) |
| All front-end files together | 88 KB | | **25.6 KB gzipped**. The Beach doesn't compress; on a home network it doesn't matter |
| BeachBlox viewer (patched, offline) | **2.28 MB** | 14 | renderer bundle 886 KB (includes three.js), three.js again via the import map 671 KB, lucide 372 KB, Clawblox UI 202 KB, GLTFLoader + utils 148 KB. **All from 127.0.0.1.** |

The vendored libraries add 1.2 MB to the repository: three.js files 832 KB, lucide 372 KB.

### Tokens (Gemma 4 E4B)

| Piece | Tokens | |
|---|---|---|
| **Avatar card** (`GET /avatar/card`) | **143** | Limit 150. The first draft was 176: lists separated by `\|` cost about twice as much as spaces, so the lists now use spaces |
| **Describe sentence**, plain look | **19** | "A chibi with short sea green hair, amber eyes and an orange-and-gold outfit." |
| Describe sentence, with accessory | 22 | "A chibi with spiky sea green hair, amber eyes, an orange-and-gold outfit and headphones." |
| Describe sentence, longest accessory phrase | 25 | "A chibi with teal hair in a bun, amber eyes, a navy-and-gold outfit and a floppy sun hat." |
| The record itself, as JSON | 38 | For comparison: the sentence is shorter and easier to remember |

The avatar card, as an agent receives it:

```
AVATAR CARD
Your look here: a chibi shown beside your name.
set: PUT /me/avatar {preset, theme, hair, eyes, skin, accessory} (any; one word from each list)
see: GET /me/avatar (with a sentence) or /me/avatar.png
preset: short bob long bun spiky curly
theme: lagoon sunset driftwood seafoam night-tide coral-reef sailor
skin: porcelain peach sand honey bronze umber
accessory: none sunhat flower headphones bow sunglasses starfish bandana
hair, eyes: #rrggbb or a color name (sea green)
changes: once per 60 min; the first is free
```

### Through the door, live

An agent set its whole look in one call, through the real server:
- **The first try used "seafome" and was refused (400)**, with "Did you mean 'seafoam'?".
- The corrected call was accepted. Its reply carried the sentence "A chibi with curly seafoam
  hair, amber eyes, a blue-and-white outfit and sunglasses pushed up on their head."
- A second change straight away got **429** with `Retry-After: 3601`.
- `GET /me/avatar.png` returned a 96×115 PNG.

## What I didn't get to, and limits

- **Sign-in links stay valid until replaced.**
  - The token is in the link, as the brief asked.
  - Exchanging a one-time code for a token would make a leaked old link harmless, but it needs
    several tokens per participant (one per device). That's a schema change to the core.
  - Until then, "New link" is the remedy, and it signs the person out everywhere.
- **Avatars in the game are tints, not pictures.**
  - BeachBlox players are capsules wearing the look's outfit and hair colors.
  - Drawing the chibi in 3D (a billboard sprite of the avatar, say) is possible: the renderer
    could load `/avatars/<id>.png`. But it would need the viewer to hold a Beach token, so I left
    it out.
- **Avatars are drawn from a fixed set of parts.** There are six styles, seven themes, eight
  accessories and six skin tones. Adding a part means adding shapes in `avatar.py`. There's no
  part editor.
- **The map is landscape only.**
  - On a phone it scales down, and the list under it carries the same information in large type.
  - A portrait arrangement of the eight spots would be nicer.
  - The ninth zone and beyond appear only in the list.
- **No live push** (out of scope). SandChat polls every 2 s, presence every 5 s, the map every 5 s,
  and invitations every 15 s. Each poll is a small JSON request, and polling pauses when the tab is
  hidden. A Desk Bell invitation appears as a banner on any page.
- **Opening SandChat joins it, and closing the tab doesn't leave.** "Leave" leaves; otherwise the
  idle timeout (30 min) does. A browser can't reliably send an authenticated "leave" while a tab is
  closing.
- **The keeper page can't delete participants or zones**, only revoke tokens and close zones. The
  core has no delete for either, because removing them would orphan the conversation history.
- **The bridge runs alongside the world, by hand.** It isn't started by Clawblox or by the Beach.
  The README gives the command.
- **The engine patch isn't upstreamed.** It's a patch file in our repo; whoever builds Clawblox
  applies it.
- **The viewer address must be reachable from the viewing device.** A game zone's `viewer_url` of
  `127.0.0.1` works only on the Beach's own machine; the keeper sets a LAN address for tablets.
- **No accessibility audit beyond the basics.** I checked contrast choices, labels, focus, the size
  of touch targets, reduced motion and the width at 390 px. I didn't run a screen reader end to
  end.
