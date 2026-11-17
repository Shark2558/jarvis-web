Version v13.1.2 · 17 Nov 2026, 21:41 IST · Release R13.1 · Status: Current · Owner: 🛠 Mark XXIII

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

## 8. Fix (review B-1)

Fixer B (Fable 5.2) worked through `REVIEW-B-1.md` (2 HIGH, 5 MEDIUM, 10 LOW) on `r13-1-b`, nine commits
`fe4d6a1` … `f6f5af0` and this note. Each fix began with a failing test, seen red on the code or the files
as they were. **Sections 2 to 5 above describe the first build; where this section differs, this section
is right.** The honest exception to "test first": the four unit tests of `carry.py` were written after it
(the Node check that drove it, `b_poke.mjs`, was red first).

### The release now (17 Nov 2026)

| File | Bytes | SHA-256 (first 16) |
|---|---|---|
| `body.glb` | 1,108,524 | `6d89b11d44014ea2` |
| `garments.glb` | 1,511,948 | `ce678bf349b7d470` |
| the folder in all | **2,650,340** | budget 3,670,016 (3.5 MB): 72 % |

- Two builds in a row are byte-identical. The opt-in rebuild from the clone gives the committed files.
- The heaviest dressed figure is 30,940 triangles (limit 32,000).
- **The measure table, on the body that is drawn:**

| Rule | Limit | Measured |
|---|---|---|
| height on its own slider, measured on the DRAWN mesh (150, 161, 172, 178, 195) | 0.5 | **under 0.001** (was 1.03 to 1.68 short) |
| the rig against the drawn mesh (19 cases) | 0.1 | 0.000; every shared rig point within **0.016 mm** of its drawn twin |
| a measurement changed alone, on its own slider (the rig) | 0.5 | **0.488** (chest 76 reads 76.49) |
| every other measurement in any case | 3.5 | **3.215** (height 150: chest reads 99.22) |
| the written file against the float build | 0.2 | **0.001** |

### HIGH

| # | Finding | What was done |
|---|---|---|
| 1 | The drawn figure was 1.0–1.7 cm shorter than typed; the rig and AVT-03 measured a body that is never drawn | The head's softening moved into `pose.Head`. The solve, the rig and the drawing now use ONE body, the drawn one (`Measurer.drawn`). A new Node case measures the drawn regions themselves, and AVT-03 reads the drawn height. The new control `unsoftened_rig` (the old behaviour, kept as data in the manifest's `controls`) turns it red: "the rig reads 173.37 cm but the drawn figure is 172.00 cm tall". |
| 2 | The governor timed the gap between inputs and retired 3D on a fast laptop | `createGovernor()` is a pure, exported unit. It judges a frame's COST (the wait for its turn plus the drawing); a window is at least 2 s and 8 judged frames, slow when its median is over 45 ms. Replays in Node: 3 Hz key taps, a 60 ms drag and a 60 fps spin never step; 60 ms frames step down at 4.1 s and retire at 8.3 s. The control `input_cadence` retires the fast laptop (red). Two Chromium tests: 12 s of taps and 11 s of slow drag keep the shadows on (red on the old engine); a page whose draw calls burn 4 ms is stepped down, then retired with `slow`. No new `GL_FAIL` word was needed. |

### MEDIUM

| # | Finding | What was done |
|---|---|---|
| 3 | The GLB reader read malformed files | One `span()` check before a byte is read; finite scales, offsets and UVs; each view's own stride; whole triangles; plain, unique mesh and morph names; a map without a prototype; `join()` refuses a name two files share. 31 broken copies of `garments.glb` are each refused with `GlbRefused`. |
| 4 | A shirt over a wrap ignored `tucked: false` in silence | `show()` answers `forced: {top: 'tucked'}` (top level and each figure) and names `tuck` in that slot's `approx`. See "Needs I1" below for Part D. An untucked shape over a wrap is NOT built (see "Left"). |
| 5 | The figure swallowed the chat's scrolling | The wheel is the figure's only while a pointer is pressed on the canvas or the canvas has the focus, and only while the zoom can still move. `touch-action` is `pan-y` until the canvas is focused, `none` while it is. A Chromium test with the stage in a scrolling column proves both ways, with a real touch swipe. |
| 6 | Poke-through was never checked | See "The layers" below: a check, a real fix, and two documented limits. |
| 7 | CI never ran the script's shape code (44 %) | A small committed source (`tests/fixtures/r13_1/b_source.bin.xz`, 262,000 bytes, SHA-pinned, CC0) and `build.build_files()`. Without the clone the script's coverage is **98 %**; every function but the 13 that read the clone's own files runs in the fixture build. CI itself still needs scipy: "Needs I1" below. |

### The layers (finding 6)

- **The check** (`tests/fixtures/r13_1/b_poke.mjs`, `b_seen.mjs`): a small depth buffer in Node counts what an
  eye would see of a layer that must stay covered (the base shorts, a tucked tail, the socks under a trouser
  leg): 5 looks × 15 shapes (the sample, both ends of the six sliders, two mixed bodies), 135 checks.
- **What it found on the first build:** far more than the specks at inseam 66. At the sample the tucked
  shirt's tail stood out across the seat (a belt hid it) and the base shorts showed at the crotch. At the
  slider ends a level view saw up to 304 cm² of the base shorts (hips 78, a wrap) and 84 cm² (inseam 66).
- **Why:** each garment was made afresh at each solved shape, and a morph is one straight line used with a
  negative weight at the low end of every slider. A state (tuck, open) was one more line added on top.
- **The fix:** garments are made once, at the sample, and CARRIED by the body (`scripts/mannequin/carry.py`).
  A state gets its own answer to each morph as a product target (`tuck*hips`), which costs 0.30 MB. The
  tucked tail, the base shorts' edges and the wrap's ease were corrected at the sample.
- **Now:** a level view sees at most **0.56 cm²** of any covered layer; from above (a real line of sight
  into a waistband) at most 19.4 cm². The control `thin_trousers` shows 1,303 cm² (red).
- **Two documented limits**, capped in the fixture so they cannot grow unseen:
  - **Inseam 66 with the other five at the sample:** the BODY's own hip line folds over the shortened thigh
    (the morph is a straight line far below its solved shape). A ledge shows on the trousers and a thin line
    of the base layer along it: 5.6 cm² (was 84). Shots 22 and 23. A fix needs a second inseam morph, as
    `waist_down` is for the waist: a contract change, so it is for the Workshop to decide.
  - **Waist 120:** a waistband gapes a little under the belly: 1.2 cm².

### LOW

| # | Finding | Outcome |
|---|---|---|
| 8 | The label overflowed the host | **Fixed.** Its outer height is counted; the canvas's minimum is 120 px (was 240). |
| 9 | Template names, crops, the crop cache | **Fixed.** `Object.hasOwn`; only `data:image/(jpeg|png|webp);base64`; one read a page. |
| 10 | A missing mesh was drawn as nothing; the dispose test | **Fixed.** `onLost('asset')`; the test asserts `isContextLost()`. |
| 11 | The 10 s clock included the download | **Fixed.** 30 s for the files, then 10 s for the frame. Compression is under "Needs I1". |
| 12 | The rig's licence label | **Fixed** (the label). The rig still ships in `body.glb` (64 KB): **left**, see below. |
| 13 | Other glTF tools misread the files | **Fixed.** `JARVIS_accessor_scale` is used and required; both readers want it. |
| 14 | Deviations not written down | **Written here**, below. |
| 15 | White socks over trainers read as boots | **Fixed.** A crew sock (19 cm) and a dark padded collar on the shoe. Shots 11 and 19. |
| 16 | `createStage` is one long closure | **Partly.** The turntable and the governor are module-level now: 210 lines (was 241). |
| 17 | `figure:facts` always passed | **Fixed.** It passes only within the triangle limit. |

### Left, each with its reason

- **An untucked shirt over a wrap (4).** It needs a second wrap shape. A shirt worn out over a mundu is a
  common way to wear one, so it is worth a later slice; today the engine says plainly that it drew it tucked.
- **The rig in `body.glb` (12).** A separate `measure.glb` changes the release's file list, which the server's
  route and I0's tests read. 64 KB did not justify touching a seam.
- **`createStage` (16).** Its inner functions are each under 40 lines. Splitting the rest means passing the
  renderer's state through a dozen parameters, with no behaviour to gain before I1.
- **Deviations the first notes missed (14):** the hemisphere light is 0.95 (the brief: 0.55) and the fill 0.9
  (0.7), because without the room light of preview v2 the figure's shaded side went black on the night
  surface. The vest's neckline is still ragged (shot 15): a brief item, not done.
- **Shapes still not built:** 24-segment sleeves, a white sneaker sole, a longer coat, a polo collar, jacket
  buttons and pockets. The watch strap's lower edge is slightly ragged against the hand (shot 06).
- **At waist 120 the closed jacket** bunches over the belly (seen in a scratch render, no shot kept).

### Needs I1 (added by this fix)

1. **Part D: a top forced tucked.** When `show()` answers `forced[slot] === 'tucked'`, show "Drawn tucked into
   the mundu" and switch the tuck control off. Row 388's exactness is `drawn` + `hidden` + `cards` + the
   private slots (covered).
2. **Part D: the host.** It needs at least 150 px of height. The figure takes the wheel and vertical swipes
   only once it is pressed or focused; a tap or click gives it the focus.
3. **Part D: `onLost('timeout')`** can now come up to 30 s after `show()` when the files do not arrive.
4. **CI runs none of the script's tests** (they need scipy, which no leg installs). Proposed diff for the
   Python 3.12 leg of `.github/workflows/ci.yml`, after its `pip install -e ".[dev,homebridge]"`:

   ```diff
   +      - run: pip install scipy==1.18.1   # scripts/mannequin's tests (R13.1 B): the build from a small source
   ```
5. **Serve the GLBs compressed** (the route is I0's). With `gzip -9` the two files are about 1.6 MB instead of 2.6.
6. **The book's licences.** `tests/fixtures/r13_1/b_source.bin.xz` is CC0 data derived from the same pinned
   files; list it if the book lists test data.
7. **The sole and the coat** need a word in the contract (a slot carries `template`, not the type).

### The checks after the fix (17 Nov 2026, this workspace)

| Check | Result |
|---|---|
| `tests/test_r131_b_script.py` + `test_r131_b_figure.py`, Python 3.13 with the clone | 76 passed |
| the same, Python 3.11 (no scipy: the script's tests skip) | 44 passed, 2 skipped |
| `tests/test_r131_b_script.py` alone, without the clone, `--cov=mannequin` | 30 passed, 1 skipped; **98 %** |
| `tests/browser/test_r131_b_stage.py` (Chromium, software WebGL2) | 23 passed |
| `evals/r13_1/run.py --mock --part figure` | 28/28; the ten controls failed the suite, as they must |
| `evals/r13_1/run.py --mock` (every part) | 50/50 |
| `tests/test_r131_seams.py`, `test_r13_seams.py`, `test_r51_console_assets_linked.py` | 782 passed, 1 failed: the stub's pin of section 6, item 1 |
| `evals/r7/run.py --mock`, from an export of HEAD at a path without "131" | 68/68 |
| `ruff check` and `ruff format --check` on the part's Python | clean |
| `scripts/arch_coverage.py`, `scripts/check_doc_versions.py` | OK |

**Sizes:** `console-tryon-3d.js` 408 lines (limit 600), `-glb.js` 175 (200), `-cloth.js` 163 (300); every
module of `scripts/mannequin` is under 400 lines (14 modules with `carry.py`).

**Still not verified here:** his phone's GPU (every frame was drawn by Chromium's software renderer, and the
slow device of the governor's test is a made one); how close the figure looks to him; a real crop.

## Change log

| Version | Date | Release | What changed | By |
|---|---|---|---|---|
| v13.1.1 | 17 Nov 2026, 19:25 IST | R13.1 | First edition, at the end of Part B: the plan followed and the honest note on test order, what was built, the build's sums, sizes, triangles and measure table, the checks with their numbers, eleven deviations with reasons, the list for I1 (the stub's pin, what `show()` and `stats()` add), what could not be verified | 🛠 Mark XXIII (builder B) |
| v13.1.2 | 17 Nov 2026, 21:41 IST | R13.1 | Section 8, the fix of review B-1: the release's new sums, size and measure table (now on the drawn body); each of the 2 HIGH, 5 MEDIUM and 10 LOW findings with what was done; the layer check, the carried garments and the two documented limits; what was left and why; seven more items for I1; the checks after the fix | 🛠 Mark XXIII (fixer B) |
