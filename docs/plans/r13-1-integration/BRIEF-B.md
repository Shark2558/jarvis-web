Version v13.1.2 · 17 Nov 2026, 17:55 IST · Release R13.1 · Status: Current · Owner: 🛠 Mark XXIII

# R13.1 — Part B brief: the 3D figure and garments (Fable 5.2, one builder)

**This brief is self-contained**: you start with no context, so everything you need is here. Where
it says "the plan", the source is `docs/plans/r13-1-try-on.md` (v13.1.3: D2, D3, D5–D9, "The 3D
figure", the `figure` suite); read it after this brief, but nothing below depends on having read it.
`BRIEF-COMMON.md` in this folder is the rulebook for all four parts; its rules are repeated here
where they bind you.

## 0. What JARVIS is, and what you build

JARVIS is the owner's private personal assistant: a Python 3.11+ FastAPI server (`src/jarvis/`)
with a browser console (`src/jarvis/api/static/console*.js`, plain ES modules, no build step, no
framework, a strict Content Security Policy). Release R13 gave him a wardrobe (every piece has an id
`wi_` + 12 hex, a state such as Ready or In laundry, up to three 512-px photo crops `wh_` + 12 hex).
Release R13.1, "Try-on", adds a **free 3D figure** in Helpers → Wardrobe → "Try it on": a plain grey
mannequin shaped from six measurements he types, dressed in ready-made garment shapes coloured and
textured from his own pieces, that he can turn, zoom, tuck, open, layer, swap and compare. It is
drawn on his phone or laptop; nothing about it leaves the device. **The owner's scope of 17 Nov 2026
(row 388):** when he asks JARVIS "what should I wear?", the answer opens a card with this same figure
under the chat reply by itself, already dressed in the look JARVIS chose (Part D mounts your engine
there through the same contract). "See it on me" (Part C, paid) is now for a garment he is thinking of
buying; it does not touch your engine.

**You (Part B) build the figure: the asset build script, the committed GLB files and their
manifest, the 3D engine module, its GLB reader and its texture module, their tests, the `figure`
eval.** Part A (Opus) builds the server's data (measurements, the look and its readiness), Part D
(Opus) the section's UI and the checklist, Part C (Opus) the paid "See it on me". You never edit
their files or any shared file. You meet them only through the **engine contract** (section 3) and
`tests/r131_fake_server.py` (section 7).

## 1. Your branch, the hook, commits

- Repository: `/home/claude/jarvis-web` (a shallow clone of the public GitHub repo
  `Shark2558/jarvis-web`). Make your worktree and branch from I0's branch:
  `git -C /home/claude/jarvis-web fetch --depth=1 origin '+refs/heads/r13-1-i0:refs/remotes/origin/r13-1-i0'`
  then `git -C /home/claude/jarvis-web worktree add .claude/worktrees/r13-1-b -b r13-1-b origin/r13-1-i0`.
  Work only in `/home/claude/jarvis-web/.claude/worktrees/r13-1-b`.
- **Push after every commit**: the first time `git -c push.negotiate=true push -u origin r13-1-b`,
  then `git -c push.negotiate=true push`. Never rebase, never force-push, never push to `main`, never
  `git stash`, never `rm -rf` outside `/tmp` or `.claude/worktrees/`, never edit lint, format,
  type-check or coverage-floor configuration to make an error go away.
- **The hook.** `.claude/settings.json` runs `.claude/hooks/guard.py` before every Bash, Edit, Write
  and MultiEdit call. **A blocked action means stop and report it** (in INTEGRATION-B.md and to the
  Workshop); never work around it with another spelling.
- Commit messages: conventional (`feat(r13.1): …`, `test(r13.1): …`, `fix(r13.1): …`), a body
  saying what and why, ending with exactly four trailers:

  ```
  Co-Authored-By: <the line the Workshop gives you for Fable 5.2>
  Claude-Session: <the session link the Workshop gives you>
  JARVIS-Version: v13.1.0
  JARVIS-Mark: XXIII
  ```
- **The repository is PUBLIC**: no personal data (names, addresses, his measurements or photos), no
  keys, no project ids, no chat links (the trailer is the only one), no local paths (write
  "a local clone of naver/anny at <commit>", never `/tmp/...`), in code, tests, fixtures, the
  manifest or docs. **Never commit the preview v2 files** (they are local notes, below).

## 2. Your files (only these) and their limits

| File | Limit |
|---|---|
| `scripts/mannequin/` (`core.py`, `pose.py`, `measure.py`, `tops.py`, `bottoms.py`, `outer.py`, `feet.py`, `accessories.py`, `glb.py`, `build.py`, `requirements-dev.txt`, a short `README.md` is NOT wanted: put usage in `build.py`'s docstring) | each module ≤ 400 lines, each function ≤ 50 |
| `src/jarvis/api/static/vendor/mannequin/m1/**` (`body.glb`, `garments.glb` or per-template files, `MANIFEST.json`, `LICENSE-mpfb2-CC0.txt`, `LICENSE-anny-Apache-2.0.txt`, `NOTICE-mannequin.txt`) | ≤ 3.5 MB in all |
| `src/jarvis/api/static/console-tryon-3d.js` (the engine; I0's stub, replace it) | ≤ 600 lines |
| `src/jarvis/api/static/console-tryon-glb.js` (the GLB reader; I0's stub) | ≤ 200 lines |
| `src/jarvis/api/static/console-tryon-cloth.js` (textures; I0's stub) | ≤ 300 lines |
| `tests/test_r131_b_*.py`, `tests/fixtures/r13_1/b_*.mjs`, `tests/browser/test_r131_b_*.py`, `tests/r131_fakes_b.py` (unique names) | — |
| `evals/r13_1/figure.py` (I0's stub, replace it) | — |
| `docs/plans/r13-1-integration/INTEGRATION-B.md` | versioned like this file, with a change log |

**Never edit** anything else, in particular: `console.html`, `console-helpers-wardrobe.js`,
`console-tryon.js` / `-list.js` / `-me.js` / `-photo.js` (Part D's), `api/*.py`,
`wardrobe/**` (Python), `tests/test_r13*_seams.py`, `tests/test_r131_*.py` that are not yours,
`tests/fixtures/r13_1/engine_contract.mjs` and `stage.mjs` (I0's), `tests/r131_fake_server.py`,
`evals/r13_1/run.py`, `buildbook/gen/libs.py` (I0 already lists your two licence files),
`docs/architecture/*`, `pyproject.toml`, `.github/*`, `.claude/*`. A change you need there goes
under "Needs I1" in INTEGRATION-B.md with the exact diff.

## 3. The engine contract (pinned by `tests/fixtures/r13_1/engine_contract.mjs`; read that file)

```
window.JarvisTryOn3D = { supported() -> bool, mount(host, {release, onLost}) -> Stage }   // mount may throw
Stage = { show(figures, opts) -> {drawn, approx, cards}, view(name), spin(on), zoom(step), closer(),
          snapshot({caption: string[]}) -> Promise<Blob>, stats() -> {triangles, figures, fps, dpr, shadows, yaw},
          dispose() }
figures[i] = { body: {weights, typed}, look: {slots: [{slot, piece, template, variant, rgb, pattern, photo, private}]} }
opts = { tucked, open, layers: 'all' | 'no_outer' | 'base', view: 'front' | 'side' | 'back' }
```

- Keep `window.JarvisTryOn3D = …` and also export the same functions from the module; keep loading
  `'./console-tryon-glb.js'` and `'./console-tryon-cloth.js'` (a test pins both, quoted like that).
- `body.weights`: seven morph weights by name, `height`, `shoulders`, `chest`, `waist`, `hips`,
  `inseam`, `waist_down`, computed on the server by `src/jarvis/wardrobe/tryon/model.py`
  `morph_weights`: **each of the six morphs is the solved shape at its range's TOP minus the sample's
  shape** (weight = (v − sample)/(top − sample), negative below the sample: a straight-line
  extrapolation, as preview v2), and **`waist_down` is the solved shape at waist 62 minus the sample**,
  used ALONE for a waist below the sample's 82 (weight (82 − v)/(82 − 62), the `waist` weight then 0).
  Your morph targets must mean exactly that (note: preview v2 calls the second slider `shoulder`;
  JARVIS's name is `shoulders`). `typed`: the measurements he typed; label the figure
  "Estimated from your measurements".
- One or two figures (compare: two figures 0.9 m apart under ONE camera and ONE light set). A slot's
  `template` is one of `shirt`, `tee`, `kurta`, `trousers`, `shorts`, `wrap`, `jacket`, `shoe`,
  `sandal`, `belt`, `watch`, `socks` or null (null, or a model that fails: an image card, reported
  in `cards`); `variant` from `{shirt: [tucked, untucked], tee: [tucked, untucked], kurta: [knee],
  wrap: [ankle], jacket: [open, closed]}`; `rgb` [r, g, b] (0–255) or null (mid-grey); `pattern`
  (a fixed word); `photo`: a crop id `wh_` + 12 hex for the texture, or null.
- **A private slot is `{slot, private: true}` and nothing else** (no piece, template, colour, photo):
  never draw it as itself (section 5, privacy).
- `show` answers `drawn` (slot names drawn), `approx` (slot → which of `template`, `texture`,
  `colour` is approximate; every template is "Approximate") and `cards` (slots shown as an image
  card beside the figure). `view(name)`: camera yaw front 0°, side 90°, back 180° (± 1°), the SAME
  scene state (pieces, tuck, open, layers, weights) in every view. `spin(on)`: "Turn around", a slow
  spin; it stays still when the console's Motion is Off. `zoom(step)` within limits; `closer()`
  frames the upper body. `snapshot({caption})` draws the current figure(s) and, beneath them on the
  SAME canvas, the caption lines Part D passes (fixed words only), and resolves to a PNG Blob (D
  previews it from a `data:` URL or a canvas: `blob:` is not allowed in the console's `img-src`).
- **Mounted in two places, one at a time (row 388):** Part D mounts your Stage either in the "Try it
  on" section or in a card under a chat reply. Only one Stage lives on the page at a time: D calls
  `dispose()` on one before `mount()` of the other, so `dispose()` must free everything (the WebGL
  context with `WEBGL_lose_context`, every listener through the AbortController, every texture and
  buffer), and a second `mount()` after a `dispose()` must work. Row 388's test reads `stats()` and
  the slots of `show`'s answer to check the figure wears exactly the card's pieces: keep `drawn`
  exact.
- **The failure hooks** (`GL_FAIL` in the contract file) that Part D's tests use: with
  `window.__glFail` set, `'no-webgl2'` makes `supported()` false, `'lost'` fires `onLost()` after the
  first show, `'asset'` treats a file as failing its sum, `'timeout'` makes the first render never
  finish. Without the hook, real failures behave the same: no WebGL2 → `supported()` false; a file
  404 or sum mismatch, `webglcontextlost`, a first render over 10 s, the governor retiring 3D →
  `onLost()` (and `mount`/`show` may throw): Part D's checklist then takes over.

## 4. The console you draw in (facts from the code)

- **three.js r187 is vendored alone**: import it ONLY from
  `/static/vendor/three-0.187.0/three.module.min.js` (as `console-3d.js:218` does). **No addon is
  vendored and none may be** (OrbitControls, GLTFLoader, RoomEnvironment import the bare specifier
  `three`, which needs an import map, and the CSP refuses inline scripts). So you write: (i) the GLB
  reader `console-tryon-glb.js` for EXACTLY the subset your build writes (a JSON and a BIN chunk;
  accessors for positions, normals, UVs, indices and morph targets; `KHR_mesh_quantization`'s
  normalised int16 and int8) into `BufferGeometry` with `morphAttributes`; anything else is refused
  (a test proves an unknown accessor type is refused); (ii) turntable controls of your own (drag turns
  the figure, pinch and wheel zoom within limits, arrow keys and +/− for the keyboard, double-tap
  resets; pitch limited to 0.22π–0.56π as preview v2); (iii) lights without RoomEnvironment: preview
  v2's hemisphere (0xFFFFFF/0x3A4658, 0.55), key (0xFFF6EA, 2.3, one 1024 shadow map), fill
  (0xDCE8FF, 0.7), rim (0x9FE2FF, 0.55) and back (0xFFFFFF, 1.25). The body grey (0xC3C9D2) and the
  base layer's grey (0x66748A) are v2's: constants in your engine (not CSS).
- **The console's CSP** (`api/console.py`): `script-src 'self' 'wasm-unsafe-eval'`,
  `connect-src 'self'`, `img-src 'self' data:`, `font-src 'self'`. So: no CDN, no Google Fonts, no
  inline import map; `fetch` only same-origin files (yours: `/static/vendor/mannequin/m1/...`); a
  crop arrives from the picture door as a `data:` URL (`window.JarvisMobile.parts.send.thumb(id)` →
  `data:image/jpeg;base64,…`) and must be decoded with an `Image` (fetching a `data:` URL is refused
  by `connect-src 'self'`); `blob:` URLs can't be shown in an `<img>`.
- **Patterns to reuse from `console-3d.js`** (read lines 1–60 and 160–170): a WebGL2 probe
  (`getContext('webgl2')`), ONE AbortController owning every listener (teardown in `dispose()`,
  the GL context force-released), `webglcontextlost`, and the frame governor (render-on-demand here:
  a change, a drag, the spin; never a continuous loop; device pixel ratio ≤ 1.5; two slow windows
  of ~2 s → shadows off and DPR 1 → 3D retired, `onLost()`). Colours and day/night:
  `window.JarvisFX.tokens()` (accent, accent2, ink …) and `window.JarvisFX.surface()` ('night' or
  'day'); re-palette on the document event `jarvis:theme`. One WebGL context for the stage.
- **The pixel and drawing rules** (tests in `tests/test_r13_seams.py` and `tests/test_r131_seams.py`):
  your two drawing modules (`console-tryon-3d.js`, `console-tryon-cloth.js`) may use canvas APIs on
  their OWN canvases (`drawImage`, `toBlob`, `createImageBitmap`), never `getImageData` or
  `captureStream`; `console-tryon-glb.js` uses none. In all three: no `JarvisVision`,
  `JarvisCamera`, `getUserMedia`, `XMLHttpRequest`, `WebSocket`, `sendBeacon`, `localStorage`,
  `sessionStorage`, `indexedDB`, `innerHTML`, `JarvisChat`, `http://` or `https://`, no door
  sender (`door.person`, `wardrobe`, `tag`, `drop`, `picture`, `myPhoto`, `vault`, `ask`): only the
  door's `thumb(id)`; imports only `./console-tryon-glb.js`, `./console-tryon-cloth.js` and the three
  URL; every string URL starts with `/static/vendor/mannequin/` or is the three URL. **One more trap:
  R7's eval scans the RAW text of every console file, comments included, for `getUserMedia`,
  `getDisplayMedia`, `ImageCapture` and `facingMode`: never write those words, not even in a
  comment.** No `$` money figure anywhere (₹ only, and you show no money at all).

## 5. The assets: built by a pinned script, committed, checked when served (plan D3, D5, D6)

**Sources (local, never committed):**
- Preview v2, the owner's approved prototype: `/home/claude/jarvis-web/.project-notes/scratch-in/
  mannequin-preview-v2/` (`index.html` 544 lines, `build_assets.py` 769, `mq_core.py` 262,
  `measure-table.txt`). Git-excluded on purpose: read it, port it, never copy it into the repo as is.
- A local clone of `naver/anny` at commit `8f35dc2df1c4062fd2fae86734f9705de50c0c2b` (26 Oct 2026)
  is at `/tmp/anny-src/anny` on this machine (its `src/anny/data/mpfb2/` is CC0 1.0; Anny's code
  Apache-2.0). If it is gone, clone `https://github.com/naver/anny` and check out that commit.
- Python with numpy 2.5.3 and scipy 1.18.1: `/tmp/venv-c/bin/python` (3.13). Pin exactly those in
  `scripts/mannequin/requirements-dev.txt`. The script is a dev tool run by hand, never in the
  server's image; the unit suite must not import numpy (CI's test environment may not have it):
  tests that need it `pytest.importorskip("numpy")`.

**What preview v2 does, and the facts measured on it (17 Nov 2026):** the MakeHuman/MPFB2 base mesh
(19,158 vertices, 13,380 on the body), its targets and the standard rig weights read with numpy; a
neutral young male average; six measurement morphs solved by Newton steps (height, shoulder width,
chest, waist, hips, inseam); posed relaxed; eyes filled; the face softened to a mannequin head.
Garments from the CC0 `helper-tights` helper mesh (a face group of `3dobjs/base.obj`), offset and
smoothed: a shirt tucked and untucked (collar stand and leaf, placket, buttons, cuffs), trousers,
belt and buckle, shoes and soles, socks, a watch on the LEFT wrist, and an always-on vest and shorts
base layer. Every mesh carries the same morphs. The build ran in ≈ 3 s and twice gave identical
files: `body.glb` 2,437,524 bytes (SHA-256 `850782a4dfe4cd3f682bd3834b2ce615da60061e163cecba9178e9c30a1ba212`),
`outfit.glb` 1,523,852 bytes (`91e816210b9b46819f6fb8d29df9542121ba6bbc30bbc6ed1f3fc41e2a417e2d`),
float32; triangles dressed and tucked 24,566, base layer only 26,134. Its measure table: each slider
is ONE morph (the shape at the slider's top minus the sample), so below the sample it extrapolates:
**waist 62 comes back 63.9 cm** (1.9 cm off on its own slider); the other five come back within
0.5 cm on their own sliders; the worst cross-effect is chest 99.3 cm at height 150 (+3.3 cm);
tall-and-heavy's worst is chest 108 → 106.2. The sample is height 172, shoulders 44, chest 96,
waist 82, hips 96, inseam 79; the ranges: height 150–195, shoulders 36–54, chest 76–124, waist
62–120, hips 78–126, inseam 66–92 (also in `wardrobe/tryon/model.py`: the one source).
v2's rough spots to fix: the vest neckline, the high collar, a shoulder pinch on the check shirt,
simple shoes, 12-segment sleeves (straight fingers stay).

**What is NOT JARVIS-ready in v2 (do not port):** three.js and its addons from a CDN through an
inline import map, Google Fonts, base64 JSON wrappers around the GLB, sample pieces in the page, a
day/night button of its own, a continuous render loop, OrbitControls and RoomEnvironment, a 2-state
layer toggle that can leave the pelvis uncovered when an outfit has no bottom, no tests for the
build script.

**The script `scripts/mannequin/`:** v2's `mq_core.py` and `build_assets.py` split into modules of
≤ 400 lines (`core.py`, `pose.py`, `measure.py`, `tops.py`, `bottoms.py`, `outer.py`, `feet.py`,
`accessories.py`, `glb.py`, `build.py`), each function ≤ 50 lines. Input: the Anny clone path (an
argument). It reads ONLY `3dobjs/base.obj`, `mesh_metadata/basemesh_vertex_groups.json`,
`rigs/standard/rig.default.json`, `rigs/standard/weights.default.json` and the `macrodetails/`,
`torso/measure-*` and `legs/measure-*` targets it names, **refuses any whose SHA-256 differs from its
table**, and **never reads the `smplx` folder** (non-commercial; Anny's own "anny" topology is not
used either: the raw MakeHuman base is). `scripts/mannequin/measure.py` carries the 46-index waist
loop copied from Anny's `anthropometry.py`, so it carries the **Apache-2.0 header and the NOTICE
line** (the indices live in the script, never in a GLB).

**Output** `src/jarvis/api/static/vendor/mannequin/m1/`: `body.glb`, `garments.glb` (or one file a
template, see the budget), `MANIFEST.json` = `{"files": {name: {"sha256", "bytes", "type":
"application/octet-stream", "source": "naver/anny@8f35dc2…", "licence", "changes"}}, …}` plus the
build's facts: `sliders`, `ranges`, `sample`, `sole` (v2's 0.016 m), the templates and their
variants, triangle counts, and the measure table. (The server serves a file ONLY when `files` lists
it with a matching `sha256` and a data `type`; JSON is `application/json`; JavaScript never. A
mismatch is a 404.) `LICENSE-mpfb2-CC0.txt` (the clone's `src/anny/data/mpfb2/LICENSE.md`, as is),
`LICENSE-anny-Apache-2.0.txt` (the clone's `LICENSE`), `NOTICE-mannequin.txt` ("Body and garment
base: MakeHuman/MPFB2 assets (CC0 1.0) as shipped in NAVER's Anny at <commit>; the waist measurement
loop from Anny's anthropometry.py (Apache-2.0, NAVER Corp.); shaped, posed, cut and quantised by
JARVIS"). Apache-2.0 §4(b): the `changes` field says what was modified.

**First steps, in this order:**
1. Port the script with tests on a SYNTHETIC mesh (a tiny made-up mesh in `tests/r131_fakes_b.py`:
   the GLB writer, the Newton solve, the loft and ring helpers, the SHA table refusal, "never reads
   smplx").
2. **The private zone** (D6): the pelvis and seat faces are REMOVED from the body core at build time,
   the base shorts are always drawn (inside the trousers' ease, so they never poke through), and the
   base vest is drawn whenever no top is drawn. A test walks EVERY combination of layer state ×
   slot set (with or without a bottom, a top, an outer) × variant × view and proves the zone is
   covered (Node, from your GLBs).
3. **The waist below the sample (H3):** add ONE corrective morph, `waist_down` (the solved shape at
   waist 62 minus the sample), seven morph targets in all. Measured on the rebuilt v2: each
   measurement changed alone comes back within **0.48 cm** at both ends of its range and at mid
   points; when several change together, or at a height extreme, another can drift up to **3.33 cm**
   (height 150 → chest 99.3, not touched by this fix) — the figure is labelled "estimated".
4. **Quantisation within the budget:** positions and morph deltas as normalised int16 with a
   per-accessor scale (padded to 8 bytes a vertex), normals int8 (padded to 4), UVs float32, uint16
   indices: v2's set ≈ 2.1 MB, the new templates ≈ 0.8–1.3 MB, `waist_down` ≈ 0.26 MB: ≈ 3.2–3.7 MB
   against **3.5 MB in all** (a test). Over 3.5 MB, drop IN THIS ORDER and say so in INTEGRATION-B:
   the morph normals of the small parts (buttons, buckle, watch, soles, socks), then those of the
   garments, then split the garments into one file a template fetched only for the look's templates
   (the first load, body + base, ≤ 1.6 MB). Quantisation keeps every measurement within 0.2 cm of the
   float build.
5. **Then the templates** (one approximate shape per garment kind, each with every morph): `tee`
   (also polo and top, tucked/untucked), `kurta` (to the knee, always untucked: "A kurta is worn
   out"), `shorts`, `wrap` (mundu, dhoti; ankle length), `jacket` with an OPEN and a CLOSED variant
   (blazer, jacket, coat (longer), hoodie, sweater, rainwear, festive layer), `sneaker` (a white
   sole: the `shoe` template), `sandal` (sandal, slipper); and v2's rough spots (vest neckline, high
   collar, shoulder pinch, 24-segment sleeves, a shaped shoe toe). **AVT-07 fixes the blazer's
   shape:** its sleeve ends at least 1 cm above the shirt cuff, its collar sits under the shirt
   collar, the watch case stays outside the sleeve.
6. Triangles: a dressed figure ≤ 32,000; two figures (compare) ≤ 64,000.

**Reproducible:** a test skipped without the environment variable `JARVIS_ANNY_DIR` rebuilds into a
temporary folder and compares the measurements within 0.1 cm and the triangle counts exactly (byte
equality is not required: another BLAS can change float bits).

**Drawing rules (D5, D6):** order base layer → main (top, bottom) → outer → socks → shoes → belt →
watch. Layers `all`, `no_outer`, `base` (base layer only). Tucked/untucked for `shirt` and `tee`
(the belt shows ONLY when tucked); open/closed for `jacket` (closed hides the shirt's placket
region, keeps the same piece). Colour: `rgb` (null → mid-grey). Texture (`console-tryon-cloth.js`):
the crop id in `photo` → `thumb(id)` → `data:` URL → an `Image` → the centre 40 % square
mirror-tiled 2 × 2 into its own 512 px canvas; the tile size in metres is an assumption per template
(shirt 0.22 m, trousers 0.25 m, jacket 0.25 m: "texture scale approximate"); a crop that can't be
read → colour only. Nothing leaves the device, nothing is stored. Shoes on both feet; the belt at the
trouser top; the watch on the LEFT wrist (strap from its colour; a steel case).

## 6. Your rows (the owner's acceptance checks, word for word) and their named tests

| Row · ID | His acceptance check | Your test (what must hold) |
|---|---|---|
| 353 · AVT-02 | The owner can rotate the model and inspect a distinct front, side and back view. | **`test_avt02_the_basic_figure_turns_to_distinct_front_side_and_back_views`**: with only typed measurements, the Front, Side and Back views give three different camera yaws (0°, 90°, 180° ± 1°), drag turns it, the figure is labelled "Estimated from your measurements" |
| 357 · AVT-06 | Swapping a watch changes the correct wrist accessory or its linked thumbnail. | **`test_avt06_swapping_the_watch_changes_the_left_wrist_and_its_thumbnail`**: swapping watch W1 for W2 changes the strap colour on the left wrist (and D's slot thumbnail to W2's photo); shoes and belt likewise in their own places |
| 358 · AVT-07 | A blazer covers the shirt sleeves and torso where appropriate without hiding the shirt collar or watch by mistake. | **`test_avt07_a_blazer_covers_the_shirt_but_not_its_collar_or_the_watch`** (geometric, Node): with shirt + blazer + watch, the blazer shell contains the shirt's torso and sleeve vertices from shoulder to 1 cm above the cuff; every shirt-collar vertex and every watch-case vertex lies outside the blazer shell |
| 359 · AVT-08 | Changing the viewpoint from front to back preserves outfit and avatar identity. | **`test_avt08_front_to_back_keeps_the_same_pieces_layers_and_figure`**: after Front → Back the engine reports the same slot → piece ids, the same tuck/open/layers state and the same measurement weights; a photo-only piece stays a labelled card beside the 3D view |
| 361 · AVT-10 | Toggling jacket open to closed updates shirt visibility and leaves the same jacket selected. | **`test_avt10_closing_the_jacket_hides_the_shirt_front_and_keeps_the_same_jacket`**: open → closed hides the shirt placket region, keeps the jacket's piece id; tucked ↔ untucked likewise for a shirt (belt shown only when tucked); a kurta offers no tuck |
| 362 · AVT-11 | A formal and festive look can be compared without losing either item list or its availability state. | **`test_avt11_a_formal_and_a_festive_look_compare_with_both_lists_and_their_readiness`** (your half: two figures, one camera and one light set, each with its own slots; D adds the item lists and readiness words, A the saved comparison) |
| 365 · AVT-14 | Sharing a look displays the dressed avatar and only the approved item details. | **`test_avt14_a_shared_look_shows_the_dressed_figure_and_only_approved_details`**: `snapshot({caption})` makes a PNG of the dressed figure plus the caption lines D passes; a private slot draws only the covered base layer (no label, colour or id of the private piece anywhere in the PNG's inputs); in every layer state the private zone is covered |
| halves | AVT-03 (172 → 178 cm changes the figure's height to 178 ± 0.5 cm), AVT-05 (the template and the texture from the crop, "Approximate"), AVT-09 (the swap redraws the outer layer), AVT-15 (the failure signals of section 3) | `test_avt03_shape_*`, `test_avt05_template_*`, `test_avt09_redraw_*`, `test_avt15_signals_*` |

Node tests: `tests/fixtures/r13_1/b_*.mjs`, run from a Python test with `shutil.which("node")`
(raise, don't skip, when Node is missing; see `tests/test_r13_d_scan.py` for the pattern). Browser
tests: `tests/browser/test_r131_b_*.py` with `pytestmark = pytest.mark.browser`, against the bare
stage page of `tests/r131_fake_server.py` (`serve(token)` → url; open `url + "/r131/stage"` or
`/r131/stage?mod=b_<name>.mjs` for your own module under `tests/fixtures/r13_1/`; the default
`stage.mjs` mounts the engine and leaves `window.__r131 = {engine, stage, shown, error}`). The 3D
browser tests run only where Chromium has WebGL2 (skip ONLY on "no-webgl2", as
`tests/browser/test_book_show.py` `_need_3d` does; a failing engine fails the test); the fallback
tests force `__glFail`. Pin the page clock.

## 7. Your eval (`evals/r13_1/figure.py`) and its controls

Expose `PART = "figure"`, `BUILT`, `async def cases() -> list[dict]` (each `{"id": "figure:<case>",
"passed", "failures"}`) and `async def control() -> dict` (`{"name", "suite_failed",
"failed_cases"}`: your cases re-run with the controls applied). Cases (Node and Python): the
manifest's sums, licences and the 3.5 MB budget; the measure table (12 slider ends and 4 mid points:
each measurement changed alone within **0.5 cm**; every case's other measurements within **3.5 cm**;
quantised within 0.2 cm of float); the private zone covered in every layer state × slot set ×
variant × view; AVT-07's geometry; tucked/untucked and open/closed where the table says; triangles
≤ 32,000 a figure; the GLB reader refuses an unknown accessor type; each of your rows' named cases.
**Controls that must turn it red:** two morphs swapped (the measure table fails); `waist_down`
dropped (waist 62 reads 63.9 and fails); the base shorts dropped in "All" (the privacy walk fails);
the blazer sleeve lengthened 2 cm (AVT-07 fails). **Your rows' own controls:** AVT-02 Side returns
Front's yaw; AVT-08 Back resets the tuck state; AVT-10 the closed variant is the open variant (and
AVT-07's above). Set `BUILT = True` only when every control really fails its case. The runner is
`PYTHONPATH=$PWD/src /tmp/venv-b/bin/python evals/r13_1/run.py --mock --part figure`.

## 8. Test commands (2 CPUs, about 7 GB, other agents share the machine)

Run your own tests and the seam tests; NEVER the whole suite. Anything heavier than a few files
runs behind the shared lock `flock /tmp/jarvis-heavy.lock …` (it waits while another agent's heavy
run goes). CI runs plain `pytest` from the repository root, which is NOT on `sys.path`: never
`from tests.x import …`; import your fakes bare (`from r131_fakes_b import …`).

```
PYTHONPATH=$PWD/src /tmp/venv-b/bin/python -m pytest -q -p no:cacheprovider tests/test_r131_b_*.py
flock /tmp/jarvis-heavy.lock /tmp/venv-b/bin/python -m pytest -q -p no:cacheprovider tests/test_r131_seams.py tests/test_r13_seams.py tests/test_r51_console_assets_linked.py
/tmp/venv-12/bin/ruff check scripts/mannequin tests/test_r131_b_*.py evals/r13_1/figure.py && /tmp/venv-12/bin/ruff format --check <the same>
/tmp/venv-c/bin/python scripts/mannequin/build.py <the anny clone> <a temporary output folder>
JARVIS_BROWSER_TESTS=1 flock /tmp/jarvis-heavy.lock /tmp/venv-c/bin/python -m pytest -q -m browser tests/browser/test_r131_b_*.py
PYTHONPATH=$PWD/src /tmp/venv-b/bin/python evals/r13_1/run.py --mock --part figure
PYTHONPATH=$PWD/src /tmp/venv-b/bin/python evals/r7/run.py --mock     # the camera-words rule (section 4)
```

`/tmp/venv-b` is Python 3.11 (the project's), `/tmp/venv-12` 3.12 (ruff), `/tmp/venv-c` 3.13 with
Playwright, Chromium, numpy and scipy. Node 22 is on the PATH. Python code: type annotations on
every function, PEP 8, ruff clean, line length 100, no `print` in library code (the build script's
`main` may print its summary). Every test takes a fixed clock if it needs time at all.

## 9. Done means

Every file of section 2 works: the build reproduces, the manifest's sums match, the size and
triangle budgets hold, the engine fits the contract and draws the pilot look in the stage page, every
named test of section 6 passes, `figure` is BUILT with each control failing it, the seam tests
(`tests/test_r131_seams.py`, `tests/test_r13_seams.py`, `tests/test_r51_console_assets_linked.py`)
and R7's eval stay green, ruff is clean. Then `docs/plans/r13-1-integration/INTEGRATION-B.md`
(first line `Version v13.1.1 · <day> <Mon> 2026, <hh:mm> IST · Release R13.1 · Status: Current ·
Owner: 🛠 Mark XXIII`, a "## Change log" table at the end): what you built, the build's sums, sizes
and triangle counts, the measure table you got, what you dropped for the budget (and why), every
deviation from this brief with its reason, "Needs I1" with exact diffs (e.g. anything Part D must
know about timings or the stage), and honestly what you could not verify here (his phone's GPU,
how close the figure looks to him). Push it.

## Change log

| Version | Date | Release | What changed | By |
|---|---|---|---|---|
| v13.1.1 | 17 Nov 2026, 16:40 IST | R13.1 | First edition, written at I0 for the Fable 5.2 builder, self-contained: JARVIS and the part in two paragraphs, the branch, hook and trailers, the files and their limits, the engine contract with the morph weights' meaning and the failure hooks, the console's facts (three r187 only, the CSP, the patterns of `console-3d.js`, the pixel and drawing rules, R7's camera-words trap), the assets (the sources, preview v2's measured facts and what not to port, the script, the output and manifest, the six first steps with the private zone, `waist_down`, the budget's drop order, the templates and AVT-07's shape), the rows with his acceptance checks, the `figure` eval with its controls, the commands, done | 🛠 Mark XXIII |
| v13.1.2 | 17 Nov 2026, 17:55 IST | R13.1 | The owner's scope of 17 Nov 2026 (plan v13.1.3, D21): the figure also opens under a chat reply (row 388), mounted by Part D through the same contract, one Stage at a time: `dispose()` frees everything and a second `mount()` works; See it on me is for a garment to buy and does not touch the engine | 🛠 Mark XXIII |
