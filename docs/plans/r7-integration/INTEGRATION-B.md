Version v7.0.3 · 13 Nov 2026, 23:40 IST · Release R7 · Status: Current · Owner: 🛠 Mark XVII

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
  {installed, why}}}`; `GET /v1/vision/results?days=1..365&limit=1..200&offset=0` → `{sealed, keep_days, results, total, more, unreadable}` (a day that does not open is counted in `unreadable`, never hides the others);
  `POST /v1/vision/results` (one Result, ≤ 64 KB) → 201 `{kept}` or 422 `dropped` (never
  repaired), 409 `not_sealed` / `day_full` ("That day's results are full, Sir": 100 results, or a sealed day over 900,000 characters, Firestore's 1 MiB being the wall), a result over 20,000 characters is a 422 "too big", 413, 429 (30 a minute); `DELETE
  /v1/vision/results/{vr_<12 hex>}`. Off in settings: 404 `vision_off`. No token key: nothing
  is kept, and the part says so (looking still works).

## 3. Contract files

- `src/jarvis/vision/results.py`: **unchanged**.
- The port core of `console-vision.js`: **changed in v7.0.2 by two contract lines** (the Workshop's
  decisions on the reviews), now SHA-256 `f26e439a…0860` (I0's was `9e5ae773…82c6`), pinned by
  `tests/test_r7_b_console.py::test_the_port_core_is_the_agreed_one_byte_for_byte`. Part B's tasks
  are appended below the marker `// ==== R7 Part B`.
  1. **`register` is sealed.** After the five built-in tasks (`sealRegistry()` as the last line of
     Part B's block) `JarvisVision.register(...)` returns `false`. Later releases add an engine
     task by editing the engine, never from a use case: a use case that could register a task
     could hand it a live frame (`run(id, video)`), which is exactly what D13 forbids.
  2. **`stream(task, opts, onResult)` reports.** `opts.onError(error)` (new, optional) is called
     once when the task cannot load or run, and the stream stops; a frame that is not there yet
     (`There is no picture to look at.`) is skipped, and only 20 in a row end the look (and say so).
     Before, any error ended the look silently.
- New facts later parts build against: the release folder `r7-1` (`jarvis.vision.assets.RELEASE`);
  `jarvis.vision.assets.TASK_FILES`; the two routes above; `window.JarvisCamera` and
  `jarvis:camera`; `JarvisMobile.parts.panel` = `{choose(tab), tab(), result()}` (Part A's
  `do=look` can call `choose('look')` after opening the panel; nothing starts the camera).
- **The use-case rule (D13) for R8–R10**: `tests/r7_fakes_b.py` `use_case_problems(source)` (the
  guard itself is `tests/r7_jsguard.py`) and `use_case_modules()` (every console script that calls
  `JarvisVision.use(`). **It fails closed**: a small lexer cuts the source into tokens, and the
  guard refuses text it cannot read (an unterminated string, template or comment; a non-ASCII
  character or a backslash outside a string), any computed member access `a[k]` whose key is not
  one plain string or number literal, and every banned name wherever it appears: the plan's list
  (`drawImage`, `getImageData`, `toBlob`, `createImageBitmap`, `captureStream`, `fetch`,
  `XMLHttpRequest`, `sendBeacon`, `WebSocket`, `JarvisConsole.api`, `JarvisChat`, `import(`,
  `localStorage`, `sessionStorage`, `indexedDB`, `caches`) and the ways around it (the global
  object: `window`, `self`, `top`, `parent`, `frames`, `opener`, `globalThis`, `this[`, `Reflect`,
  `Proxy`; dynamic code: `eval`, `Function`, `constructor`, `__proto__`, a string to `setTimeout`;
  other routes to pixels or bytes: `Image`, `Audio`, `Request`, `Worker`, `SharedWorker`,
  `VideoFrame`, `MediaStreamTrackProcessor`, `OffscreenCanvas`, `ImageCapture`, `BroadcastChannel`,
  `MessageChannel`, `WebTransport`, `toDataURL`, `readPixels`, `texImage2D`, `srcObject`,
  `getUserMedia`, `innerHTML`, `defaultView`, …). **A use case's whole API is the bare global
  `JarvisVision.use(...)`**: `JarvisVision` may only be followed by `.use`; `register`, `run`,
  `stream` and every `JarvisCamera` member (`start`, `stop`, `frame`, `photo`, `lock`, `unlock`,
  `live`, `locked`, `onChange`, `facing`, `useFacing`, `phrases`) are refused as member names (a
  use case must not name its own method `start` or `stop`); the only static `import` allowed is
  `import { use } from './console-vision.js'`; `export` is refused. Each of the security review's
  bypasses is a test case, and a known-good sample passes. R7 has no use-case module; the test runs
  on every one that appears.

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
   `python scripts/vision_assets.py fetch --models --object-licence "<its name>"` fetches
   `efficientdet_lite0.tflite`. The name must be a recognised permissive one (`Apache-2.0`, `MIT`,
   `BSD-2-Clause`, `BSD-3-Clause`); anything else is refused; without the option only pose comes,
   and a later run keeps the object model's licence line.
3. `python scripts/vision_assets.py check` must print `r7-1: OK`; commit the model files,
   `MANIFEST.json` and `LICENSE-mediapipe-models.txt`. No restart is needed: since I1 the route's
   `vision_files` is checked again whenever the release folder changes on disk (Needs I1, item 12,
   done), so `GET /v1/vision` says the models are installed as soon as they are deployed.
   The models are pinned on first fetch (trust on first use): check each one's SHA-256 against the
   hash the vendor published before committing (the licence file says so too). From then on every fetch must match the
   pinned sums. (Their sizes, about 5.5 MB and 4.4 MB, are *unverified* here.)
4. Then acceptance 5 can be run on the phone (pose's speed for the coach stays R8's).

## 6. Checks run here (Python 3.12)

| Check | Result |
|---|---|
| Part B's unit tests (`tests/test_r7_b_*.py`: assets, store, part, api, console, dom, package) | 243 passed |
| Guard tests (R7 seams, R7 Telegram hook, R11.1 seams, arch coverage, Telegram tool guard, console assets linked) | 481 pass; the one I0 stub pin fails by design (Needs I1, item 1) |
| Coverage of `jarvis.vision` and `jarvis.api.vision` | 94 % at v7.0.1; not re-measured (no coverage plug-in in this venv); the new store paths each have a test |
| `evals/r7/run.py --mock --part vision` | 12/12; each of seven controls fails exactly its case (`upload_in_look` → `no_picture_leaves`, `lock_check_removed` → `locked_means_off`, `schema_checks_off` → `schema_drops`, `cap_off` → `day_limits`, `sweep_off` → `sweep_keeps_days`, `tool_unfenced` → `tool_fences`, `seal_off` → `kept_sealed`) |
| `evals/r7/run.py --mock` (all parts) | not re-run at v7.0.2 (I1 runs it); the vision part alone is 12/12 |
| Browser: `tests/browser/test_r7_b_camera.py` (fake camera) | 13 passed (adds a tap elsewhere refused, and a live run contacting this origin only) (text reads "125" and "500" off a drawn label; code reads a drawn QR; visual gate 1440×900 and 390×844, Night and Day, on four states) |
| Browser: the whole `test_ui_audit.py` and `test_dock_fit.py` | 152 passed, 1 failed once (`test_dock_fit.py ... [1366]`, a CSP error in the test's own `wait_for_function`) and passed alone on a rerun |
| Wheel | `pip wheel --no-deps` into `/tmp/r7b-wheel`: all 17 vision files present (10 files, `MANIFEST.json`, 6 licences) |
| `ruff check` / `ruff format --check` (src tests evals scripts) | clean |
| `mypy src`, and on Part B's files | the 9 old errors only (none in Part B's files; the 5 in `evals/r7/vision.py` are fixed) |
| `scripts/arch_coverage.py`, `scripts/check_doc_versions.py`, `python -m jarvis.buildbook.gen --check` | OK (91 collections); 27 documents; the book "R7", two builds byte-identical |
| Sizes | `console-camera.js` 237, `console-vision.js` 362, `console-camera-panel.js` 451 lines (≤ 800); `console-camera.css` 31 lines (≤ 150) |

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
11. **`pyproject.toml` package-data (v7.0.2)**: Part B added `"static/vendor/vision/*.txt"` and
    `"static/vendor/vision/*/*"` to the `"jarvis.api"` list right after `"static/vendor/ort/*.txt"`
    (a non-editable install shipped none of the 17 vision files). Part A adds two globs at the same
    lines: keep both sets (duplicates are harmless). `tests/test_r7_b_package.py` pins it.
12. **`api/console.py` `vision_files` is `lru_cache`d for the process** (I0's file; Part B did not
    touch it). Two effects: models pinned later need a server restart (section 5), and a file
    swapped on disk after the first call is served unchecked (the plan says each file is checked
    before it is served). Fix: key the cache on each file's `(st_mtime_ns, st_size)` and hash again
    only when that changes (a few lines, no new dependency), then drop the restart line.
13. **EXIF in the one door** (`console-r111-files.js` `shrink`, R11.1's file, used by I0's
    `console-r7-send.js` `prepared()` for Ask, Vault and Attach): a JPEG that is already small
    enough (`scale === 1 && file.size <= most`, not WebP) is returned *as it is*, with its EXIF and
    any location, so Part A's share tray sends such originals unchanged (Ask is stripped on the
    server, Vault and Attach are not). Part B's panel no longer relies on it (it sends the picture
    redrawn on its canvas). Exact fix for I1: in `shrink`, change the early-return test to
    `scale === 1 && file.size <= most && !/\.webp$/i.test(file.name) && !/\.jpe?g$/i.test(file.name)`
    so every JPEG is redrawn (a PNG carries no camera metadata).
14. Part B's guard and fakes moved: `tests/r7_jsguard.py` (new) holds the use-case guard;
    `tests/r7_fakes_b.py` re-exports `use_case_problems`, `D13_APIS`, `AROUND` and
    `CLEAN_USE_CASE`. A use case's module must call the bare global `JarvisVision.use(...)`
    (not `window.JarvisVision`): `window` is a refused name.

## 7a. For R8 (the live driver)

Nothing drives a live task for a use case, on purpose. A use case may not touch `JarvisCamera`
(the guard refuses it) and `JarvisVision.register`, `run` and `stream` are not its API, so R8's
coach cannot start `pose` from its own module. **Who owns the driver: R8's first slice, inside the
engine** (`console-vision.js`, Part B's block or a sibling file in the same `APP_ASSETS` list),
not in the use case. Suggested shape: `JarvisVision.live(taskIds)` (added to the core by editing
it, with a line here) pulls frames from `JarvisCamera` internally on a tap-started look, calls
`stream`, and hands the use case Results only through `use()`. It must call
`stream(..., {onError})` (v7.0.2) and show the error in plain words. `summary(state)` is stored by
`use()` and read by nothing yet: R8 decides who calls it (the panel, to show the coach's tally).
Part B builds no driver now (the Workshop's decision 9).

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
   Playwright's `evaluate` counts as a gesture), so since v7.0.2 `start()` and `unlock()` need
   that activation **and** a real (`isTrusted`) click on the camera's own buttons (inside
   `#p-camera` or the chip) in the last 5 seconds: a script that runs after some other tap has
   nothing to use. Nothing that is not such a tap (voice, launch words, the server, another tab's
   forged storage event) can switch the camera on.

## 8a. Review follow-ups (v7.0.2)

The three fresh-context reviews of `r7-b @ 48dc482`; the Workshop's decisions in order. Commits:
`af777cd` package-data, `5ec34d5` store, `9ef0332` assets script, `8b547d8` camera, panel,
engine and guard, `dc7aba6` eval and Part B tests, `976853a` browser tests.

| Finding | Result |
|---|---|
| python H1 package-data | fixed in `af777cd`: a wheel built in `/tmp/r7b-wheel` lists all 17 vision files (10 files, `MANIFEST.json`, 6 licences); `tests/test_r7_b_package.py` pins the globs |
| python M1, code L3, security LOW-7 (a day over 1 MiB) | fixed in `5ec34d5`: `DayFull` by sealed size (900,000 characters) and `TooBig` for one result over 20,000 characters |
| python M2 atomic writes | fixed in `9ef0332`: everything staged in memory, each file through tmp + `os.replace`, the manifest last |
| python M3 `check` on a missing folder | fixed in `9ef0332` (plain lines, exit 1) |
| python M4 untestable network, tar errors | fixed in `9ef0332`: injectable `fetch`/`opener`, a 180 s total deadline, plain tar errors |
| python M5 eval brittle, mypy | fixed in `dc7aba6`: `vendored_pinned` follows the manifest; the 5 mypy errors gone; three cases (`day_limits`, `sweep_keeps_days`, `tool_fences`) and four controls (`cap_off`, `sweep_off`, `tool_unfenced`, `seal_off`, the last for `kept_sealed`); each fails exactly its case |
| python M6 gather test, Telegram | fixed in `5ec34d5` and `dc7aba6`. "Absent for a learning brain": **declined, not required**: the plan states it only in Part D's row (the watch and SOS tools); for `vision_results` it asks for the Telegram rule and the fenced reads, both done |
| python L1, security LOW-3, code L5 (`vision_files` cache) | **declined as a code change** (I0's `api/console.py`); a restart note in section 5 and Needs I1 item 12 with the fix |
| python L2, code L4, security LOW-7 (one bad day) | fixed in `5ec34d5`: list, delete, export skip an unreadable day (counted, logged); a day with nothing readable at all still fails closed; `keep` never overwrites it |
| python L3 docstrings | fixed (`count`, `export`, `message`); the `_uid` `isinstance` guard stays on purpose (a defence for an untyped caller) |
| security M1 (`register` open) | fixed in `8b547d8`: sealed after the five tasks (contract line, section 3); `register`, `run`, `stream` and the camera's members are in the ban list |
| security M2 (the guard bypassed) | fixed in `8b547d8`: a fail-closed lexer, no new dependency (a JS parser would be a new dev dependency without a clean lock path); every bypass of the review is a case; a known-good sample passes |
| security LOW-1 (any tap) | fixed in `8b547d8` and `976853a`: a trusted click on the camera's own buttons, in a real Chromium too |
| security LOW-2 (chip after `play()`) | fixed: `emit('start')` before `await video.play()`; a stop during `play()` ends the start |
| security LOW-4 (telemetry host) | fixed as tests: the console CSP is `connect-src 'self'`, `worker-src 'self'`; a live run contacts this origin only (browser test) |
| security LOW-5 (trust on first fetch) | fixed in `9ef0332`: a recorded note to check the vendor's hashes, a recognised licence name required |
| security LOW-6 (EXIF) | fixed for Part B (the panel sends its redrawn picture); the door's `shrink` keeps small originals: Needs I1 item 13 with the exact fix |
| security INFO-1, INFO-2 | no change (inside the trust boundary; the camera file never talks to the server) |
| code M1 (camera on after close) | fixed: `stopLive` stops unconditionally, a pending start is dropped and its stream stopped when it arrives |
| code M2 (silent live failure) | fixed: `stream` reports (contract line 2), the panel shows "could not load" or "not installed"; a null frame is skipped |
| code M3 (stale result) | fixed: the newest look wins, a task change cancels, the result box is cleared when a look starts |
| code M4 (raw errors) | fixed: a rejected MediaPipe import is retried; every load says only "not installed" or "could not load"; `NotAllowed`, `NotFound`, `Overconstrained`, `NotReadable`, `Abort` in plain words; only a real fetch failure says "Can't reach JARVIS"; server errors of 500 and up and everything unknown are plain sentences |
| code L1 (teardown) | fixed for the page leaving (`pagehide` ends the OCR worker and both landmarkers, and the next look loads them again); **not** on idle or camera stop: reloading 100 MB each look would cost more than it saves |
| code L2 (focus, stale words) | fixed: focus follows a repaint and a Delete; "The camera was switched off." and an empty stage after a lock, idle stop, hidden page or chip stop |
| code L6 (licence overwrite, tar, `<script>`, wake lock) | fixed in `9ef0332` and `8b547d8`. The hard-coded "about ₹0.30": **declined**: it is the plan's own figure (D12, ₹0.30 a picture) and I0's door exposes no cost to read; it is now one named constant (`ASK_COST`) |
| code contract note for R8 | written (section 7a) |

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
| v7.0.3 | 13 Nov 2026, 23:40 IST | R7 | I1: section 5's restart line dropped, since `vision_files` is now checked again whenever the folder changes (Needs I1 item 12, done at I1) | 🛠 Mark XVII |
| v7.0.2 | 13 Nov 2026, 23:30 IST | R7 | Review follow-ups: package-data for a non-editable install, a day under Firestore's limit, pagination, a bad day blocks nothing, atomic `vision_assets.py`, the engine sealed and `stream` reporting (two contract lines in the port core), the camera stopping unconditionally, newest look wins, plain errors, a real tap on the camera's own buttons, a fail-closed use-case guard, eval with seven controls, section 7a for R8, Needs I1 items 11 to 14 | 🛠 Mark XVII |
| v7.0.1 | 13 Nov 2026, 20:50 IST | R7 | First edition: what Part B built (the camera's one door, the five tasks, the Camera panel, kept results, `vision_results`, the vendored tools at 22.3 MB), the contract facts later parts build on, the model steps for CI or the laptop, the checks, ten Needs-I1 items, eight deviations and what could not be verified here | 🛠 Mark XVII |
