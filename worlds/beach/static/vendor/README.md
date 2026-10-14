# Vendored browser libraries (for the offline viewer)

These are third-party files, copied unchanged (or bundled, as noted) so the BeachBlox viewer never
fetches code from the internet. Clawblox serves this folder at `/static/vendor/`.

| Folder | What | Version | License | Source |
|---|---|---|---|---|
| `three/` | three.js: `build/three.module.min.js`, and from `examples/jsm/`: `loaders/GLTFLoader.js`, `utils/SkeletonUtils.js`, `utils/BufferGeometryUtils.js` | 0.160.0 | MIT (`three/LICENSE`) | npm package `three@0.160.0`, files copied unchanged |
| `lucide/` | lucide icons, as one ES module `lucide.mjs` | 0.468.0 | ISC (`lucide/LICENSE`) | npm package `lucide@0.468.0`, `dist/esm` bundled into one file with esbuild (`export * from "lucide"`, `--bundle --format=esm --minify`) |

The beach renderer (`../../renderer/src/index.js`) imports three.js from here, and Clawblox's bundling
step builds it in. The engine's own page and runtime use these files only with the patch in
`patches/clawblox-offline-frontend.patch` (see `docs/research/BEACH_FRONT_REPORT.md`).
