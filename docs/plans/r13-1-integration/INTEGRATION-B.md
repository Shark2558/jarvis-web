Version v13.1.1 · 17 Nov 2026, 21:40 IST · Release R13.1 · Status: Current · Owner: 🛠 Mark XXIII

# R13.1 — Part B: the 3D figure and its garments (integration notes)

Builder B (Fable 5.2, one builder) wrote these notes on branch `r13-1-b` (from `r13-1-i0` @ `eb8b7e4`).
The brief is `BRIEF-B.md`; the plan is `docs/plans/r13-1-try-on.md` v13.1.3 (D2, D3, D5–D9).

## 1. The plan I followed

1. Port preview v2's script into `scripts/mannequin/` and get a first build.
2. Replace the three console stubs (the engine, its GLB reader, its cloth module) and look at the result.
3. The private zone, `waist_down`, quantisation, then the new templates; fix shapes from screenshots.
4. Tests: the script on synthetic meshes, the files and the engine in Node, the engine in Chromium.
5. The `figure` eval with its seven controls; the seam tests; these notes.

**Honest note on "test first":** steps 1–3 were written before their tests, because nothing could be
judged until a figure was on screen. The tests came beside the code and then drove it: the Node checks
found the jacket covering the shirt's collar, a collar band hanging through the jacket's back, the edge of
the removed zone outside the base shorts at inseam 66, and a NaN reaching a file. Each was fixed in the build.

## 2. What I built

| What | Where |
|---|---|
| The build script, 13 modules | `scripts/mannequin/` (`core`, `pose`, `measure`, `mesh`, `figure`, `tops`, `bottoms`, `outer`, `feet`, `accessories`, `glb`, `build`, `__init__`, `requirements-dev.txt`) |
| The release folder | `src/jarvis/api/static/vendor/mannequin/m1/` (`body.glb`, `garments.glb`, `MANIFEST.json`, two licence texts, the NOTICE) |
| The engine | `console-tryon-3d.js` (366 lines), `console-tryon-glb.js` (139), `console-tryon-cloth.js` (150) |
| Tests | `tests/test_r131_b_script.py` (22), `tests/test_r131_b_figure.py` (33), `tests/browser/test_r131_b_stage.py` (16), `tests/r131_fakes_b.py`, `tests/fixtures/r13_1/b_check.mjs`, `b_looks.mjs`, `b_stage.mjs` |
| The eval | `evals/r13_1/figure.py` (BUILT: 19 cases, 7 controls) |

- **Templates:** all twelve. `shirt` and `tee` are ONE mesh each with a `tuck` state; `jacket` is one mesh,
  closed, with an `open` state. A state is an eighth morph target, so nothing is stored twice.
- **The private zone (D6):** every body face deep under the base shorts or the base vest is removed at build
  time and is in no file. `plan()` puts the base shorts in every plan and the vest whenever no top is drawn.
  A private slot is read only for its `private` flag.
- **The body is six regions** (`bodyCore`, `bodyArms`, `bodyShoulders`, `bodyShins`, `bodyThighs`,
  `bodyFeet`). The engine hides a region a garment covers, so the body cannot poke through it.
- **The engine:** three.js alone; its own reader, turntable (drag, pinch, wheel, arrows, +/−, Home, double
  click or double tap) and v2's lights; draws on demand; DPR ≤ 1.5; the governor; one `AbortController`;
  `dispose()` forces the context loss. Colours of the page come from the console's CSS variables and
  `JarvisFX`; the canvas is transparent, so the console's panel shows through, day and night.

## 3. The build's facts (measured here, 17 Nov 2026)

| File | Bytes | SHA-256 (first 16) |
|---|---|---|
| `body.glb` | 1,109,448 | `da9a9d74ee37c78d` |
| `garments.glb` | 1,193,112 | `1b09f54b2d4cbb48` |
| the folder in all | **2,331,314** | budget 3,670,016 (3.5 MB): 64 % |

- **Triangles:** the heaviest dressed figure 30,868 (limit 32,000); the pilot formal look 29,122; a formal
  and a festive figure together 57,838 (limit 64,000).
- **The build** takes about 4 s. A rebuild from the clone (`JARVIS_ANNY_DIR`) measured the same within
  0.1 cm and counted the same triangles.

**The measure table** (cm, measured on the written file by its measure rig):

| Rule | Limit | Measured |
|---|---|---|
| a measurement changed alone, on its own slider | 0.5 | **0.476** (chest 76 reads 76.48) |
| every other measurement in any case | 3.5 | **3.333** (height 150: chest reads 99.33) |
| the written file against the float build | 0.2 | **0.002** |
| waist 62 (the `waist_down` morph; v2 read 63.9) | 0.5 | 62.006 |

Mixed bodies: tall and heavy (190, 48, 108, 110, 110, 86) reads 189.98, 48.00, 106.16, 108.45, 109.78, 86.43;
short and slim (158, 40, 84, 68, 86, 72) reads 158.01, 40.00, 85.45, 67.84, 86.21, 71.91.

## 4. The checks, with their numbers

| Check | Result |
|---|---|
| `tests/test_r131_b_script.py` + `test_r131_b_figure.py`, Python 3.13 with numpy, scipy and the clone | 55 passed |
| the same two files, Python 3.11 (no scipy: the script's tests skip) | 32 passed, 2 skipped |
| `tests/browser/test_r131_b_stage.py` (Chromium, software WebGL2) | 16 passed |
| `evals/r13_1/run.py --mock --part figure` | 19/19; the control failed the suite, as it must |
| `evals/r13_1/run.py --mock` (every part) | 41/41 |
| `tests/test_r131_seams.py`, `test_r13_seams.py`, `test_r51_console_assets_linked.py` | 782 passed, **1 failed** (section 6) |
| `ruff check` and `ruff format --check` on my Python files | clean |
| `scripts/arch_coverage.py`, `scripts/check_doc_versions.py` | OK |
| `evals/r7/run.py --mock` | 67/68 (see below) |

- **R7's one failure is the worktree's name, not this part.** `body:sealed_no_value` searches log rows for
  the needle `131`, and a log record's `pathname` holds this worktree's folder name. The camera-words case
  (`vision:only_the_door_asks`) passes. In a checkout whose path has no `131` it should pass; I could not
  run it from another path here.
- **Controls:** `swap_morphs`, `no_waist_down`, `no_shorts`, `long_sleeve`, `side_is_front`,
  `back_resets_tuck`, `closed_is_open`. A test proves each turns its own case red.

## 5. Deviations from the brief, each with its reason

1. **No normals in the files.** The engine applies the morph weights on the device and computes the normals
   of the shape it made. Shading under a morph is exact instead of blended, and the folder is 2.3 MB
   instead of about 3.5 MB. Nothing had to be dropped for the budget.
2. **Morphs are applied on the CPU**, not through `morphAttributes`: the weights change only when `show()`
   is called, and it saves a morph texture per mesh on a weak phone GPU.
3. **Each accessor carries its own scale** (`extras.scale`, `extras.offset`). The files are the reader's
   subset, not general glTF: another loader would read wrong sizes.
4. **A measure rig is in `body.glb`** (a mesh of lines named `measure`, never drawn): the points and torso
   edges a test needs to measure the file without the source. It holds the waist loop's *positions*, not
   Anny's index list; the NOTICE beside it names the loop's origin.
5. **The engine does not fetch `MANIFEST.json`** (the server never serves it) and does no second SHA check:
   it fetches the release's two named files, which the server checks before serving.
6. **Two extra modules** in `scripts/mannequin/` (`mesh.py`, `figure.py`) and an `__init__.py`, to keep
   every module under 400 lines.
7. **Shapes not built, and why:** 24-segment sleeves (the triangle budget), a white sneaker sole and a
   longer coat (the slot carries the template, not the type), a polo collar, jacket buttons and pockets.
8. **The jacket has no collar band at the back.** Its neck edge is cut round the neck's base, below the
   shirt's collar; the lapels are at the front. A band there either covered the shirt's collar or hung
   through the jacket.
9. **Over a wrap a shirt or tee is always drawn tucked**, whatever `tucked` says: the one wrap shape has no
   room for a top worn out over it.
10. **The shirt cuff ends 1.2 cm above the wrist joint**, so the watch is in view; the jacket's sleeve ends
    1.5 cm above the cuff's end.
11. **Base shorts and garment shorts are longer than v2's** (to mid-thigh and to the knee), so the removed
    zone's edge stays under the shorts at every slider end.

## 6. Needs I1

1. **One pin on I0's stub must move** (`tests/test_r131_seams.py`, which I may not edit). The stub is gone,
   so `mount(null, …)` no longer says "not built yet". Proposed diff:

   ```diff
   -def test_the_engine_stub_fits_the_contract_and_mount_throws_not_built() -> None:
   +def test_the_engine_fits_the_contract_and_mount_without_a_host_throws() -> None:
   ...
   -    assert got["probs"] == [] and got["threw"] == "The 3D view is not built yet."
   +    assert got["probs"] == [] and got["threw"] == "The 3D view needs a place on the page."
   ```

   In Node `E.supported()` is `False` (no document); that test does not assert it.
2. **For Part D, what `show()` answers beyond the contract:**
   - `hidden`: slots that are worn but covered (a belt under an untucked top, the outer layer in "without
     the outer layer", everything in "base layer only"). Row 388's "exactly the card's pieces" is
     `drawn` + `hidden` + `cards`.
   - `figures`: each figure's own answer when two are compared; the top level is the first figure's.
   - `stage.ready`: a promise for the first frame. `show()` answers at once, before the files arrive.
   - `stats()` also gives `state` (`loading`, `ready`, `lost`, `disposed`), `looks`, `zoom`, `closer`, `label`.
   - `onLost(reason)` gets one word: `asset`, `lost`, `timeout` or `slow`.
3. **The image cards are D's to draw.** The engine only names the slots in `cards`.
4. **The host needs a height.** The engine fills the host's width and its height less the label line
   (clamped to 240–1200 px), and adds a canvas and one `<p class="sfine">` ("Estimated from your
   measurements").
5. **`opts.tucked` and `opts.open` win over a slot's `variant`** when they are booleans; left undefined,
   the variant decides.
6. Move the browser test from the fake server to the wired app, as I0's notes say.

## 7. What I could not verify here

- **His phone's GPU.** Every frame here was drawn by Chromium's software renderer. The governor's steps
  were not exercised by a slow device, and no test drives them.
- **How close the figure looks to him**, and whether the garment shapes read right to his eye.
- **A real crop.** The texture path was tested with a drawn striped stand-in through a fake `thumb()`.
- **Known flaws, seen in the screenshots:** at inseam 66 the trousers show a ridge on the thigh and specks
  of the layers beneath; in mixed small bodies the closed jacket's lapel edges go ragged; the kurta has a
  seam line at the waist; the tee's neck edge is slightly uneven; fingers stay straight.

## Change log

| Version | Date | Release | What changed | By |
|---|---|---|---|---|
| v13.1.1 | 17 Nov 2026, 21:40 IST | R13.1 | First edition, at the end of Part B: the plan followed and the honest note on test order, what was built, the build's sums, sizes, triangles and measure table, the checks with their numbers, eleven deviations with reasons, the list for I1 (the stub's pin, what `show()` and `stats()` add), what could not be verified | 🛠 Mark XXIII (builder B) |
