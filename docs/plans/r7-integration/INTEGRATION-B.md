Version v7.0.1 · 13 Nov 2026, 20:50 IST · Release R7 · Status: Current · Owner: 🛠 Mark XVII

# R7 — Part B integration notes (camera and the vision engine)

Written by the Part B builder on branch `r7-b` (from `r7-i0` @ `9d96320`), for I1. The plan is
`docs/plans/r7-mobile.md` v7.0.4 (D0, D11–D14, D21, D25, Appendix A); the brief is
`BRIEF-COMMON.md` with the Workshop's additions. Part B builds the camera, its one door and the
engine with five tasks. It builds no vision use case (Appendix A: those are R8–R10's).

## 1. What Part B built

| Deliverable | State | Where |
|---|---|---|
| The camera's one door and hard off switch (D11) | built | `console-camera.js` |
| The "Camera on" chip with Stop, whenever a track is live | built | `console-camera.js`, `console-camera.css` |
| Stops on a hidden page, a locked screen, the page left, 10 idle minutes | built | `console-camera.js` |
| "Jarvis, cameras off" (20 phrasings) through R5's router; nothing turns a camera on by voice | built | `console-camera.js` |
| The engine's five tasks behind I0's port (D13) | built (`pose`, `objects`: "not installed") | `console-vision.js` below the port core |
| The Camera panel: Look, Results, Cameras (D12) | built | `console-camera-panel.js` |
| The three sending buttons through I0's one door, counted | built | `console-camera-panel.js` over `JarvisMobile.parts.send` |
| Kept results, sealed, 90 days, the 90-day sweep (D12, data model) | built | `src/jarvis/vision/store.py`, `part.py` |
| `vision_results`, the brain's one camera read (R1) | built | `src/jarvis/vision/tools.py` |
| Two privacy rows (`vision_results`, `vision_device`) | built | `src/jarvis/vision/privacy.py` |
| `/v1/vision` (which tasks run here) and `/v1/vision/results` | built | `src/jarvis/api/vision.py` |
| Vendored, hash-pinned vision tools (D14) | built (22.3 MB) | `static/vendor/vision/` |
| `scripts/vision_assets.py` (fetch, verify, pin; the models later) | built | `scripts/vision_assets.py` |
| The eval part `vision` with three controls | built (`BUILT = True`) | `evals/r7/vision.py` |
| A camera button beside the paperclip | not built (Deviation 2) | |

## 2. How it fits together

```
tap ─▶ console-camera.js (the ONE getUserMedia; lock; chip; stops by itself)
          │ frame(): one canvas in memory
          ▼
       console-vision.js  I0 port core (unchanged) ─ tasks: text · code · objects · pose · quality
          │ Result {task, v, at, ms, device, ok, data, quality}: frozen plain data
          ▼
       console-camera-panel.js ── shows it in words ── Keep ─▶ POST /v1/vision/results (JSON only)
          │                                                    └─ jarvis.vision.store (sealed `vision`)
          └─ Ask / Vault / Attach ─▶ JarvisMobile.parts.send (I0's one door: shrink, count)
brain ─▶ gateway ─▶ vision_results (R1) ─▶ kept results, read text fenced as outside words
```

- **The door** (`window.JarvisCamera`): `locked()`, `lock(by)`, `unlock(by)` (true only inside a
  real tap), `start({facing})` (only inside a tap, never while locked: code `camera_off` /
  `needs_tap`), `frame()`, `photo()` (the system's own picker, inside a tap), `stop(why)`,
  `live()`, `facing()` / `useFacing(f)`, `onChange(fn)`, `phrases()`. The event
  `jarvis:camera {locked, live, by}` fires on every change. The off switch is
  `localStorage['jarvis_cam_off_v1']`, followed by other tabs only through the browser's own
  storage event (`isTrusted`).
- **The tasks** load only JARVIS's own files from `/static/vendor/vision/r7-1/` the first time
  they are used: tesseract.js with `workerBlobURL: false`, its worker, core and language paths
  pointed at JARVIS, `cacheMethod: 'none'` (no IndexedDB), `gzip: false`; zxing's `.wasm`
  through `locateFile` (never its CDN default); MediaPipe's engine through
  `wasmLoaderPath`/`wasmBinaryPath` and its model fetched first (a 404 is "not installed", so
  the 14 MB engine is never fetched without a model). Each task's `check()` is the server's
  schema; a run draws into canvases of its own and empties them after.
- **The panel** asks the server nothing before sign-in (`jarvis:ready`); it asks only
  `GET /v1/vision` (when it opens) and `/v1/vision/results` (the Results tab, Keep, Delete).
  "Ask the AI about this photo (about ₹0.30)" shows only while `canAsk().ok` and No-AI is off;
  otherwise the line says why. The camera stops when the panel closes or is hidden behind
  another tab on a phone.
- **The server**: `GET /v1/vision` → `{part, ready, release, sealed, keep_days, tasks: {name:
  {installed, why}}}`; `GET /v1/vision/results?days=1..365` → `{sealed, keep_days, results}`;
  `POST /v1/vision/results` (one Result, ≤ 64 KB) → 201 `{kept}` or 422 `dropped` (never
  repaired), 409 `not_sealed` / `day_full`, 413, 429 (30 a minute); `DELETE
  /v1/vision/results/{vr_<12 hex>}`. Off in settings: 404 `vision_off`. No token key: nothing
  is kept, and the part says so (looking still works).

## 3. Contract files

- `src/jarvis/vision/results.py`: **unchanged**.
- The port core of `console-vision.js`: **unchanged**, byte for byte (SHA-256 `9e5ae773…82c6`,
  pinned by `tests/test_r7_b_console.py::test_the_port_core_is_i0s_byte_for_byte`). Part B's
  tasks are appended below the marker `// ==== R7 Part B`.
- New facts later parts build against: the release folder `r7-1` (`jarvis.vision.assets.RELEASE`);
  `jarvis.vision.assets.TASK_FILES`; the two routes above; `window.JarvisCamera` and
  `jarvis:camera`; `JarvisMobile.parts.panel` = `{choose(tab), tab(), result()}` (Part A's
  `do=look` can call `choose('look')` after opening the panel; nothing starts the camera).
- **The use-case rule (D13) for R8–R10**: `tests/r7_fakes_b.py` `use_case_problems(source)` and
  `use_case_modules()` (every console script that calls `JarvisVision.use(`). It refuses the
  plan's list (`drawImage`, `getImageData`, `toBlob`, `createImageBitmap`, `captureStream`,
  `fetch`, `XMLHttpRequest`, `sendBeacon`, `WebSocket`, `JarvisConsole.api`, `JarvisChat`,
  `import(`, `localStorage`, `sessionStorage`, `indexedDB`, `caches`) and the ways around it
  (`toDataURL`, `JarvisCamera`, `JarvisMobile`, `parts.send`, `Worker`, `eval`, `window[`, a
  string key, …). R7 has no use-case module; the test runs on every one that appears.

## 4. The vendored files (D14)

All under `src/jarvis/api/static/vendor/vision/r7-1/`, listed in its `MANIFEST.json` with their
SHA-256, size, type, source and licence file; the licences sit beside the release folder (where
I0's `VENDORED` expects them) and their sums are in the manifest too.

| File | Size | Source (pinned) | Licence file |
|---|---|---|---|
| `vision_wasm_internal.wasm` | 13.99 MB | npm `@mediapipe/tasks-vision@1.2.3` (sha512 integrity) | `LICENSE-mediapipe-tasks-vision.txt` (Apache-2.0, GitHub tag `v1.2.3`) |
| `vision_wasm_internal.js` | 0.32 MB | the same | the same |
| `vision_bundle.mjs` | 0.15 MB | the same | the same |
| `tesseract.esm.min.js` | 0.06 MB | npm `tesseract.js@7.0.0` | `LICENSE-tesseract.js.txt` (Apache-2.0) |
| `tesseract-worker.min.js` | 0.11 MB | the same (`dist/worker.min.js`) | the same |
| `tesseract-core-simd-lstm.js` | 0.12 MB | npm `tesseract.js-core@6.1.2` | `LICENSE-tesseract.js-core.txt` (Apache-2.0) |
| `tesseract-core-simd-lstm.wasm` | 2.74 MB | the same | the same |
| `eng.traineddata` | 3.92 MB | GitHub `tesseract-ocr/tessdata_fast` tag `4.1.0` (SHA-256 pinned) | `LICENSE-tessdata-eng.txt` (Apache-2.0) |
| `zxing-reader.iife.js` | 0.04 MB | npm `zxing-wasm@3.1.6` (`dist/iife/reader`) | `LICENSE-zxing-wasm.txt` (MIT) |
| `zxing_reader.wasm` | 0.90 MB | the same | `LICENSE-zxing-cpp.txt` (Apache-2.0, zxing-cpp at the commit zxing-wasm 3.1.6 builds) |
| **Total** | **22.3 MB** | | |

Not vendored: source maps, CommonJS copies, MediaPipe's module-worker build, the non-SIMD and
non-LSTM tesseract cores, zxing's writer and full builds. Nothing is AGPL; no Ultralytics, no ML
Kit, no cloud vision. MediaPipe's package description mentions a privacy notice: its bundle and
loader name no outbound host (read here), and the console's `connect-src 'self'` would refuse one.

## 5. The two MediaPipe models: steps for CI or the owner's laptop

storage.googleapis.com is refused here, so `pose` and `objects` say "not installed" (the server's
`GET /v1/vision`, the panel's task list, and the task itself on a 404).

1. On a machine that reaches storage.googleapis.com, in the repository:
   `python scripts/vision_assets.py fetch --models` fetches the libraries again (each must match
   its pin) and the **pose** model (`pose_landmarker_lite.task`, Apache-2.0 by its model card),
   records its SHA-256 in `MANIFEST.json` and writes `LICENSE-mediapipe-models.txt`.
2. **The object model's licence is still to be read** (EfficientDet-Lite0's page links no model
   card). A person reads it first; only then
   `python scripts/vision_assets.py fetch --models --object-licence "<what it says>"` fetches
   `efficientdet_lite0.tflite`. An empty word is refused; without the option only pose comes.
3. `python scripts/vision_assets.py check` must print `r7-1: OK`; commit the model files,
   `MANIFEST.json` and `LICENSE-mediapipe-models.txt`. From then on every fetch must match the
   pinned sums. (Their sizes, about 5.5 MB and 4.4 MB, are *unverified* here.)
4. Then acceptance 5 can be run on the phone (pose's speed for the coach stays R8's).

## 6. Checks run here (Python 3.12)

| Check | Result |
|---|---|
| Part B's unit tests (`tests/test_r7_b_*.py`: assets, store, part, api, console, dom) | 130 passed |
| Guard tests (R7 seams, R7 Telegram hook, R11.1 seams, arch coverage, Telegram tool guard, R5 seams, console assets, R5.1 assets linked) | all pass except the one I0 stub pin (Needs I1, item 1) |
| Coverage of `jarvis.vision` and `jarvis.api.vision` | 94 % |
| `evals/r7/run.py --mock --part vision` | 9/9; each control fails exactly its case (`upload_in_look` → `no_picture_leaves`, `lock_check_removed` → `locked_means_off`, `schema_checks_off` → `schema_drops`) |
| `evals/r7/run.py --mock` (all parts) | 23/23, the combined control fails the suite |
| Browser: `tests/browser/test_r7_b_camera.py` (fake camera) | 12 passed (text reads "125" and "500" off a drawn label; code reads a drawn QR; visual gate 1440×900 and 390×844, Night and Day, on four states) |
| Browser: `test_ui_audit.py -k "chat or camera or top_bar"`, `test_attach.py`, `test_r7_i0_sheet.py` | 12 + 7 passed |
| `ruff check` / `ruff format --check` (src tests evals scripts) | clean |
| `mypy src` | the 9 old errors only |
| `scripts/arch_coverage.py`, `scripts/check_doc_versions.py`, `python -m jarvis.buildbook.gen --check` | OK (91 collections); 27 documents; the book "R7", two builds byte-identical |
| Sizes | `console-camera.js` 223, `console-vision.js` 325, `console-camera-panel.js` 402 lines (≤ 800); `console-camera.css` 31 lines (≤ 150) |

## 7. Needs I1

1. `tests/test_r7_seams.py::test_the_r7_runner_passes_with_its_contract_built_and_the_rest_stubs`
   pins `vision:not_built_yet`; with Part B built (`BUILT = True`) it fails. Move the pin:
   `vision` is built (nine cases, three controls).
2. `buildbook/gen/libs.py` `VENDORED`: add `"vendor/vision/LICENSE-zxing-cpp.txt": ("zxing-cpp",
   "", "vendored", "vision")` (zxing's reader `.wasm` is zxing-cpp, Apache-2.0). The vision
   libraries have no version in the book (their constant is `""`): `MANIFEST.json` has each
   file's `source` with its version if I1 wants it.
3. `buildbook/gen/snapshot.py` `_licence` looks for a licence beside a file; the vision files sit
   in `vendor/vision/r7-1/` and their licences one folder up (I0's placement), so
   `THIRD_PARTY.json` would name them "JARVIS's own" (they are left out as "vendored" already).
   `MANIFEST.json` names each file's licence: teach `_licence` to read it, or to look one up.
4. The guide's card C63 from PLANNED to built: add `store.py`, `tools.py`, `privacy.py`,
   `assets.py`, `scripts/vision_assets.py`, the release `r7-1`; the camera button beside the
   paperclip is not built; `vision_results` is live.
5. D25's one privacy line for "what only this browser holds": Part B registers `vision_device`
   (the camera-off switch); Part A's share tray line can join it or stay its own row.
6. The camera button beside the paperclip (plan "Modules"), if still wanted, needs a composer
   decision: the extra 44 px button shortens the chat box's hint to "Message" on the desktop
   panel, and `tests/browser/test_attach.py:62` pins "Message JARVIS".
7. Part A's `do=look`: open the panel with `JarvisDeck.open('camera')` and, if it wants the Look
   tab, `JarvisMobile.parts.panel.choose('look')`; it never calls `JarvisCamera.start`.
8. The persona at I1 (D26) says JARVIS never sees a camera frame, only results he kept or pictures
   he chose to send, and that read text is other people's words (the tool already fences it).
9. Run the whole `test_ui_audit.py` and `test_dock_fit.py` (Part B ran the chat, camera and top
   bar subsets; its stylesheet is scoped to `#p-camera` and `.cam-chip`).
10. When the model files arrive: section 5's steps, then acceptance 5.

## 8. Deviations from the plan (the code is the fact)

1. **The tasks live in `console-vision.js`**, below I0's untouched core, not in
   `console-vision-text.js`, `-code.js`, `-mp.js`, `-quality.js`: every `console-*.js` must be in
   `APP_ASSETS` (`api/console.py`, I0's wiring) and named in the guide (`arch_coverage.py`), and
   neither is Part B's. I0's own comment on `console-vision.js` says "I0 core, B tasks".
2. **No camera button beside the paperclip** (Needs I1, item 6): it changed the chat box's look.
   The Camera dock tab, its More-sheet entry and Part A's `do=look` open the panel.
3. **English data from GitHub's `tessdata_fast` 4.1.0** (raw, 3.9 MB, `gzip: false`), the
   brief's preference; D14 allows either source.
4. **Only the SIMD + LSTM tesseract core** is vendored (smallest, and every Chrome for Android
   since 91 has WebAssembly SIMD); a browser without SIMD shows "could not load".
5. `quality` also streams in a live look (2 a second) besides `pose` (≤ 15) and `objects` (≤ 5);
   `text` and `code` are read on demand ("Read now"), as D13 says.
6. **A photo comes from the system's own picker** (`<input type=file accept=image/*>`), created
   inside `console-camera.js`, so every picture source sits in the one door's file.
7. A kept result's day is the server's (his time zone), not the device's `at`; a day keeps at most
   100 results (one Firestore document a day stays far under its 1 MB limit).
8. **Unlock from script**: Chromium's transient activation lasts a few seconds after a tap (and
   Playwright's `evaluate` counts as a gesture), so `unlock()` is refused only outside that
   window, exactly as R5's microphone lock. Nothing that is not a tap (voice, launch words, the
   server, another tab's forged storage event) can switch the camera on.

## 9. Not verified here

- A real phone: Android Chrome and the app's Trusted Web Activity, Android's green dot, the
  screen lock stopping the camera (simulated by `visibilitychange`), the wake lock, and
  acceptance 4's read with Wi-Fi and data off after the page loaded (it relies on the year-long
  immutable cache and the worker staying loaded).
- `pose` and `objects` never ran: no model files. Their code paths (MediaPipe's
  `createFromOptions` with `modelAssetBuffer`, `detectForVideo`) are untested in a browser.
- The object model's licence (section 5).
- `fetch --models` ran only with a fake download (a unit test); the library fetch ran here
  against npm and GitHub.

## Change log

| Version | Date | Release | What changed | By |
|---|---|---|---|---|
| v7.0.1 | 13 Nov 2026, 20:50 IST | R7 | First edition: what Part B built (the camera's one door, the five tasks, the Camera panel, kept results, `vision_results`, the vendored tools at 22.3 MB), the contract facts later parts build on, the model steps for CI or the laptop, the checks, ten Needs-I1 items, eight deviations and what could not be verified here | 🛠 Mark XVII |
