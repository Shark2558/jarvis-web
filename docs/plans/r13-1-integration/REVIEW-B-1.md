Version v13.1.1 · 17 Nov 2026, 19:54 IST · Release R13.1 · Status: Current · Owner: 🛠 Mark XXIII (review B-1)

# R13.1 — Part B review 1: the 3D figure and its garments

A review in a fresh context, as security reviewer, code reviewer and Python reviewer
(`.claude/agents/security-reviewer.md`, `code-reviewer.md`, `python-reviewer.md`, `CLAUDE.md`,
`.claude/rules/ecc/common/*`, `.claude/rules/ecc/python/*`). The reviewer did not build Part B.

- **Under review:** branch `r13-1-b` at `35a57c7`, the diff `eb8b7e4..35a57c7`: 32 files, +6,165 lines.
- **Read against:** `BRIEF-COMMON.md`, `BRIEF-B.md`, `INTEGRATION-B.md` (its 11 deviations and known flaws),
  `I0-NOTES.md`, and the plan `docs/plans/r13-1-try-on.md` v13.1.3 (D2, D3, D5–D9).
- **No code was changed.**

## Verdict

**CHANGES REQUESTED (WARNING).** There is no CRITICAL finding. The licence chain, the SHA pinning, the CSP
and the private-layer rule are sound. Each of those has a test, and a control that turns the test red.
Two HIGH findings should be fixed before I1 merges Part B:

1. **The figure on screen is 1.0–1.7 cm shorter than the measurements he typed.** The measure table and
   AVT-03 measure a rig that is never drawn. The rig is taken before the head is softened, so the eval
   does not measure the figure he sees (finding 1).
2. **The performance governor can retire 3D on a fast laptop during normal use.** With render on
   demand, it times the input, not the render. No test drives it (finding 2).

Counts: **0 CRITICAL · 2 HIGH · 5 MEDIUM · 10 LOW.**

## What was run (17 Nov 2026, this workspace)

| Check | Result |
|---|---|
| `pytest tests/test_r131_b_script.py tests/test_r131_b_figure.py` (venv-c, 3.13) | 54 passed, 1 skipped (the rebuild) |
| the same with `JARVIS_ANNY_DIR` set to the pinned clone, with `--cov=mannequin` | 55 passed; the rebuild measures within 0.1 cm and counts the same triangles; coverage **98 %** |
| `tests/test_r131_b_script.py` alone, without the clone (what CI runs) | coverage **44 %** (finding 7) |
| `JARVIS_BROWSER_TESTS=1 pytest -m browser tests/browser/test_r131_b_stage.py` | 16 passed |
| `evals/r13_1/run.py --mock --part figure` | 19/19; the control failed the suite, as it must |
| `tests/test_r131_seams.py`, `test_r13_seams.py`, `test_r51_console_assets_linked.py` | 782 passed, 1 failed: I0's stub pin, correctly listed under "Needs I1" #1 |
| `evals/r7/run.py --mock`, from an export of HEAD at a path without "131" | **68/68**: the builder's explanation of the one failure in the worktree holds |
| `ruff check` and `ruff format --check` on every Python file of the part | clean |
| The licence chain, re-checked by hand against the clone | the commit, all 23 SHA-256 sums, both licence texts byte for byte, and the 46-index waist loop identical to `BASE_MESH_WAIST_VERTICES` |
| Scratch probes (in `/tmp`, not committed) | the GLB reader on malformed files; the governor replayed on frame times; the drawn body's height against the rig's; the watch swap rendered again in Chromium |

## Findings

### HIGH

**1. HIGH: the drawn figure is 1.0–1.7 cm shorter than the measurement, and the eval cannot see it.**

- **Where the heights split:**
  - The measure rig is written from `ctx.P`, the posed body before softening
    (`scripts/mannequin/build.py:108` `ctx.out["_P"] = ctx.P`; `build.py:152-156` `x=base["_P"][ids]`).
  - The Newton solve measures the same unsoftened points (`measure.py:161-162` `of_shape`).
  - The body regions that are drawn come from `pb = fig.body(posed.P)` (`figure.py:261`, written at
    `figure.py:270`). `Figure.body` smooths the head eight times (`figure.py:209-211`), and this lowers the
    crown.
- **Measured on the committed files** through the console's own reader. The drawn body's vertical extent,
  barefoot, against the rig's:
  - sample: 170.65 against 172.00;
  - height 178 (weight 6/23): 176.56;
  - height max: 193.32 against 195;
  - height min: 148.97 against 150;
  - every one of the 19 table cases is between −1.03 and −1.68 cm.
- **The rule it breaks:** "each measurement changed alone within 0.5 cm", and AVT-03's half: "172 → 178 cm
  changes the figure's height to 178 ± 0.5 cm".
- **Why the tests pass:** `b_check.mjs:84-100` (`measure`) and `181-185` (`avt03_shape_height_178`) measure
  `A.measure`, the rig, never the drawn regions. So `measure_table`, `avt03` and the manifest's table are
  all green.
- **Fix:**
  - Keep the crown out of the softening. Zero the smoothing weight above eye level, or on the back half
    of the head: the softening is meant for the face. The alternative is to build both the rig and the
    solve from `fig.body(...)`.
  - Add a Node case: for every shape in `SHAPES`, the drawn body regions' vertical extent equals the rig's
    `ends` within 0.1 cm, and every rig point outside the removed zone lies within 1 mm of a drawn body
    vertex.
  - Add a control, "the rig from the unsoftened points", that turns that case red.
  - Rebuild, and update the manifest's table and INTEGRATION-B §3.

**2. HIGH: the governor measures input cadence, so it retires 3D on capable devices. Its steps are
untested.**

- **Where:** `console-tryon-3d.js:247-260` (`govern`) runs on every frame (`:267`). Frames are requested
  only by a change, a drag, a key or the spin (`:273`). So between two on-demand frames, the "gap" is the
  time between two inputs, not the time a frame took.
- **Replayed with the exact logic of `govern`:**
  - an arrow key tapped three times a second: shadows off at 5.7 s, then **`onLost('slow')` at 10.3 s**;
  - a slow mouse drag, one move every 60 ms: shadows off at 5.1 s, **retired at 9.2 s**;
  - a 60 fps spin, or key auto-repeat at 30 ms: no step (correct).
- **The outcome:** Part D's checklist replaces the figure on a fast laptop during normal turning.
  `stats().fps` (`:251`) reports the input rate, not a frame rate.
- **The tests:** no test drives the governor (a grep of the tests for `slow`, `tier`, `govern` and
  `shadows` finds only `dpr <= 1.5`). INTEGRATION-B §7 says so honestly.
- **Fix:**
  - Judge the frame's own cost, not the gap between frames. Record `askedAt` in `invalidate()` and use
    `now - askedAt` (the rAF latency), plus `performance.now()` around `renderer.render()`.
  - Or count gaps only in a continuous run: the spin, or a frame requested from inside the previous frame.
  - Move it into a pure `createGovernor({slowMs, windowMs})` exported for Node. Test it: 3 Hz taps for
    20 s → no step; 60 ms renders for two windows → shadows off and DPR 1; four windows → retired.
  - Add a browser test that slows the render with a test-only hook. A new `GL_FAIL` word is a contract
    change: put it under "Needs I1".

### MEDIUM

**3. MEDIUM: the GLB reader reads some malformed files instead of refusing them.**

- **The contract:** "anything else is refused" (`console-tryon-glb.js:1-2`; plan D2 (i)).
- **The gaps:**
  - `room()` (`:24`) ignores `accessor.byteOffset` and accepts negative offsets. The copy then comes from
    `bin.buffer`, the whole file (`:29, :33, :34`).
  - `extras.scale` and `extras.offset` are never checked to be finite numbers (`:27-30`).
  - `byteStride` is checked only for the positions.
  - An index count that is not a multiple of 3 (2 for lines) is accepted (`:72`).
  - `meshes[m.name]` is a plain object (`:91`). The engine also merges the two files with `Object.assign`
    (`console-tryon-3d.js:94`).
- **Probed on an edited `garments.glb`:**
  - `byteOffset` past the BIN chunk: **read**, with 3,732 NaN coordinates;
  - a negative accessor or view offset: **read**, positions taken from the JSON chunk's bytes;
  - `scale: ['x', 1, 1]` or `offset: 'abc'`: **read**, as NaN;
  - an index count of 3n−1: **read**;
  - a UV view with `byteStride: 16`: **read**, the stride ignored;
  - a mesh named `__proto__`: **the mesh disappears**;
  - two meshes with one name: one silently overwrites the other;
  - a negative `count`: a `RangeError`, not `GlbRefused`.
- **Why MEDIUM and not higher:** the server serves only files whose SHA-256 matches the committed
  manifest, and JavaScript is memory-safe. A bad file means a blank or broken figure, not a breach.
  But a NaN figure is "drawn": `onLost` is not called and the checklist does not take over.
- **Fix:**
  - One `span()` check: `byteOffset`, `count` and `byteLength` are integers ≥ 0;
    `a.byteOffset + bytes ≤ v.byteLength`; `v.byteOffset + v.byteLength ≤ bin.byteLength`.
  - `byteStride` is absent or exact for each kind.
  - `scale` and `offset` are arrays of 3 finite numbers.
  - `index.length % (mode === TRIANGLES ? 3 : 2) === 0`.
  - `Object.create(null)` maps, and a duplicate name is refused, across the two files too.
  - Add each case to `b_check.mjs`'s refusal check (`:129-151`).

**4. MEDIUM: over a wrap, the shirt is drawn tucked even when `tucked: false` is asked (deviation 9).
D is not told.**

- **Where:** `console-tryon-cloth.js:55` forces `tucked` when the bottom is a `wrap`. Probed: asking for
  `{tucked: false}` gives `state.tucked: true` and a tuck weight of 1.
- **The outcome:**
  - Part D's tuck control does nothing for a shirt over a mundu or dhoti, and the figure says nothing.
  - AVT-10's "tucked ↔ untucked likewise for a shirt" silently does not hold for this pairing.
  - INTEGRATION-B §6 ("Needs I1") does not mention it.
- **Fix, either one:**
  - Build an "untucked over a wrap" state: the shirt's tail over the wrap's waist, a morph like `tuck`.
  - Or answer it explicitly: `show()` reports the forced state, for example `approx[slot]` gains `tuck`,
    or a `forced: {top: 'tucked'}` field. Under "Needs I1", D then shows "Drawn tucked into the mundu"
    and disables the control.
- **Test:** a Node case for the shirt over a wrap with `tucked: false`.

**5. MEDIUM: the figure traps the page's scrolling, which matters most in the chat card (row 388).**

- **Where:** `console-tryon-3d.js:119` sets `touchAction: 'none'` on a canvas that fills the host's
  width and is at least 240 px tall. `:295` prevents every wheel event.
- **The outcome:** when the card opens by itself under a chat reply, a vertical swipe that starts on the
  figure (phone), or a wheel scroll that passes over it (laptop), zooms or tilts the figure instead of
  scrolling the chat.
- **Fix:**
  - Use `touch-action: pan-y`: a horizontal drag turns the figure, a vertical swipe scrolls; the tilt
    stays on the arrow keys.
  - Zoom on the wheel only with Ctrl or Meta held, or while the canvas has focus; otherwise let the page
    scroll.
  - Add a browser test: a wheel over the unfocused canvas scrolls the page.
  - Tell D under "Needs I1".

**6. MEDIUM: a garment poking through another at a legal slider value is known but never checked.**

- **The rule:** BRIEF-B §5 and D6 say the base shorts are "inside the trousers' ease, so they never poke
  through".
- **What is checked:** `b_check.mjs:210-225` checks only that the removed zone's edge lies under the base
  shorts and the tops. Nothing checks that an inner layer (the base shorts, a tucked shirt's tail or the
  socks) stays under the trousers, the shorts or the wrap.
- **Seen:** INTEGRATION-B §7 records "specks of the layers beneath" through the trousers at inseam 66.
  Screenshot 22 shows light-blue specks on both thighs and a ridge, at a value the owner may type.
- **Fix:**
  - Add a Node case using the existing `under()`: for every shape in `SHAPES`, every point of the base
    shorts and of a tucked shirt or tee's tail below the waistband lies under the trousers or shorts
    shell that covers it (and the wrap's).
  - Fix the inseam-66 shape until the case passes.
  - Add a control, "the trousers' ease halved", that turns it red.

**7. MEDIUM: CI never runs the garment code of the build script.**

- **Measured:** without `JARVIS_ANNY_DIR`, the script's tests cover 44 %: `tops.py` 13 %, `outer.py`
  18 %, `bottoms.py` 18 %, `feet.py` 17 %, `figure.py` 23 %, `pose.py` 24 %, `build.py` 26 %. The
  project's floor is 80 % for the part's package.
- **What still protects the files:** the Node checks guard the committed GLBs.
- **What does not:** a change to the script without a rebuild passes CI. A rebuild without the variable
  runs none of the script's shape code under test.
- **Why:** this is the cost of writing the script before its tests (INTEGRATION-B §1).
- **Fix:**
  - Run the rebuild test in CI, from a cached clone at the pinned commit (Needs I1, a workflow change), or
    commit a small CC0 subset of the base mesh and its targets as a SHA-pinned fixture, enough for
    `build.evaluate()`.
  - Until then, say in INTEGRATION-B §4 that 98 % holds only with the clone.

### LOW

**8. LOW: the label overflows the host by its margin.**

- **Where:** `size()` sets the canvas height to `host.clientHeight - label.offsetHeight`
  (`console-tryon-3d.js:164`), but `.sfine` has `margin: 6px 0 0` (`console-deck.css:179`).
- **Seen:** in every screenshot, "Estimated from your measurements" straddles the panel's bottom edge, and
  it is clipped in shot 21. The 240 px minimum overflows any host shorter than about 270 px.
- **Fix:** subtract the label's outer height (`offsetHeight` plus the computed `margin-top`). Clamp to
  the host, or let D's CSS give the host a `min-height`.

**9. LOW: input hardening in `console-tryon-cloth.js`.**

- **Template names:** `TEMPLATES[s.template]` (`:42`) also finds inherited keys. A template of
  `constructor`, `toString` or `__proto__` makes the slot vanish from `drawn`, `cards` and `hidden`
  alike (probed). That breaks the exactness row 388 relies on. Use `Object.hasOwn`; an unknown template
  becomes a card.
- **Crops:** `photoCloth` accepts any `data:image/` (`:96`), `svg+xml` included. Restrict it to
  `data:image/(jpeg|png|webp);base64,`.
- **Performance:** every `show()` asks the door's `thumb()` again and decodes the crop again. Keep one
  canvas per crop id for the page.

**10. LOW: a missing mesh is drawn as nothing, and the dispose test does not prove the context is gone.**

- **Missing mesh:** `rebuild()` skips a part whose mesh is missing (`console-tryon-3d.js:212`
  `if (!mesh) continue;`). For `baseShorts`, `vest` or a body region, that fails open. The files are
  SHA-pinned and `b_check`'s walk checks the meshes exist, but the engine itself should treat it as
  `gone('asset')`.
- **Dispose test:** `test_one_stage_at_a_time_dispose_frees_it_and_a_second_mount_works`
  (`tests/browser/test_r131_b_stage.py:442-469`) checks the DOM, the listeners and a second mount. It does
  not check the contract's "the WebGL context with `WEBGL_lose_context`": keep the canvas and assert
  `isContextLost()`.

**11. LOW: the 10 s first-frame clock includes the first download.**

- **Where:** the timer starts at `show()` (`console-tryon-3d.js:325`), before about **3.05 MB** has
  arrived: the GLBs, 2.30 MB, served uncompressed (no gzip on the route), and three.js, 0.75 MB.
- **The outcome:** on a slow phone link, the first open falls to the checklist. The plan's D8 says "a
  first render".
- **Fix:**
  - Start the 10 s clock when the files are parsed, with a separate, longer download budget.
  - Under "Needs I1": serve the GLBs compressed. With `gzip -9`, `body.glb` goes from 1.11 to 0.69 MB and
    `garments.glb` from 1.19 to 0.74 MB.

**12. LOW: the measure rig's licence label and its weight.**

- **Licence:** `body.glb` carries the rig, whose waist points are in the order of Anny's Apache-2.0 loop.
  Yet its manifest `licence` names only CC0 (`build.py:199-201`). The NOTICE covers it, but the entry
  should say "CC0-1.0 (MPFB2 assets); measure rig: Anny's waist loop order (Apache-2.0); see NOTICE".
- **Weight:** the rig is 64,640 bytes of test-only data that every device downloads. Consider a
  `measure.glb` listed with a type the route never serves. The route serves only data types: tests read
  the file from disk.

**13. LOW: per-accessor `extras.scale` makes general glTF tools misread the files silently
(deviation 3).**

- **Where:** `glb.py:107-108` declares only `KHR_mesh_quantization`, so any other loader opens the files
  at the wrong size.
- **Fix:** add a vendor extension (for example `JARVIS_accessor_scale`) to `extensionsUsed` and
  `extensionsRequired`, so other tools refuse instead. Allow it in the JS reader (`:88`) and the Python
  reader.

**14. LOW: deviations not written down.**

- **The lights:**
  - The hemisphere light is 0.95 (the brief says v2's 0.55) at `console-tryon-3d.js:148`.
  - The fill light is 0.9 (the brief says 0.7) at `:154`.
- **The vest neckline:** BRIEF-B names it as a v2 rough spot to fix. It is still ragged (screenshot 15,
  base layer only), and it is in neither the deviations nor the known flaws.
- **Fix:** add both to INTEGRATION-B §5 and §7, with their reasons.

**15. LOW: white socks over white trainers read as tall boots (the Workshop's note, confirmed in
screenshot 11).**

- **Why:** the sock top is 26 cm above the floor (`socks` reaches y 0.262), and nothing marks where the
  shoe's collar ends and the sock begins.
- **Fix:** a darker ribbed band at the sock top and a darker collar ring on the shoe (both drawn by
  `weave` or the shoe material), or a lower sock with a shoe that has a sole.

**16. LOW: `createStage` is one 241-line closure** (`console-tryon-3d.js:113-353`), against the
≤ 50-line rule.

- **Context:** the house precedent is `console-3d.js`'s `createEngine` (163 lines), and its inner
  functions are small.
- **Fix:** move `controls`, `govern` (with finding 2), `rebuild` and `snapshot` into module-level
  functions over a state object.

**17. LOW: the eval counts a case that always passes.** `figure:facts` (`b_check.mjs:390`) is
`passed: true` by construction, so "19/19" is 18 real cases. Give it a real check, such as worst
triangles ≤ 32,000, or keep it out of `cases`.

## The checks the Workshop asked for

- **The licence chain and SHA pinning: sound.**
  - The anny clone is at `8f35dc2df1c4062fd2fae86734f9705de50c0c2b`.
  - All 23 sums of `core.SOURCES` match the clone.
  - `read_source` refuses anything outside the table, `smplx` or `..`, and a test proves it with a trap
    `smplx` folder.
  - Both licence texts are byte-identical to the clone's and pinned in `build.py:65-74`.
  - The NOTICE has the five required phrases.
  - `measure.py` carries the Apache header and the NOTICE line, and its `WAIST_LOOP` equals Anny's 46
    indices.
  - Nothing comes from `smplx` or Anny's own topology. The only open point is the manifest's label
    (finding 12).
- **The build script:**
  - Every module is ≤ 400 lines and every function ≤ 50 (a test pins both).
  - Every function is typed. `ruff` is clean.
  - NaN is refused at write time.
  - The output is reproducible within 0.1 cm (rerun here).
  - Weak: the rig measures the wrong body (finding 1), and CI coverage is 44 % (finding 7). A nit:
    `solve(f: Any, ...)` could be `Callable[[Arr], Arr]`.
- **The GLB reader:**
  - Sound: the chunk framing, the refusal of the type, attribute, mode, extension, sparse accessor,
    materials and truncation, and index-past-end.
  - Weak: offsets, strides, finiteness, index arity and the name map (finding 3).
  - Memory is bounded by the file; the parsed arrays are about 2.7 MB and cached once a page.
- **The CSP:**
  - Clean: only `/static/vendor/three-0.187.0/three.module.min.js` and the two GLBs are fetched (the
    browser test pins the list), and there is no addon or CDN.
  - The drawing rules and R7's camera words are clean; the seam tests pass.
  - The release name is checked with `^[a-z0-9]{1,12}$` before it is used in a URL.
- **The engine contract:** honoured.
  - `supported`, `mount` (it throws in plain words) and the eight Stage methods are all there.
  - `show` answers `drawn`, `approx` and `cards`, plus `hidden` and `figures`.
  - The four `__glFail` hooks behave as I0 pinned them, and `onLost` fires once.
  - `dispose()` aborts every listener, frees the textures and buffers, forces the context loss, and a
    second `mount()` works (browser-tested; finding 10 for what the test does not pin).
  - The extras are written down for D. One gap: a private slot is in none of `drawn`, `hidden` and
    `cards`. INTEGRATION-B's "drawn + hidden + cards" for row 388 should add "+ the private slots
    (covered)".
- **The private-layer rule: holds, with a regression test and a control.**
  - `plan()` puts `baseShorts` in every plan (`cloth.js:66`) and the vest whenever no top is drawn
    (`:67`).
  - A private slot is read only for its flag (`:41`).
  - The zone's faces are removed at build time (`figure.py:179-180`), so no file contains them.
  - The walk covers 3 × 6 × 4 × 3 × 2 × 3 combinations (`b_check.mjs:187-209`). The rim check proves the
    removed zone's edge is under the shorts and under every top, at every shape. The check that the
    removed zone has an edge catches a build that stopped removing it.
  - The `no_shorts` control turns it red, and `avt14` proves no private label, colour or id reaches the
    plan or the PNG.
  - One honest note: `plan()` does not read `opts.view`, so the walk's "view" dimension is trivially
    true. The real guarantee is the geometry that does not exist.
- **The measurement eval and its controls:**
  - The tolerances (0.5 / 3.5 / 0.2 cm) and the seven controls are as the brief asks. Each control turns
    its own case red and only that (a test checks three of them).
  - But it measures the rig, not the figure (finding 1).
- **The budgets:** 2,331,314 bytes against 3,670,016 (64 %), with nothing dropped. The heaviest dressed
  figure is 30,868 triangles (limit 32,000); two figures 57,838 (limit 64,000).
- **The governor:** untested, and wrong for render on demand (finding 2).
- **Sizes:** 366 / 139 / 150 lines against limits of 600 / 200 / 300. Python is within its limits;
  `createStage` is not (finding 16).
- **The look and the theme:**
  - The canvas is transparent, so the console's panel shows through, day and night (browser-tested).
  - The ring takes `--accent` from `JarvisFX`, and the label is `.sfine`.
  - The fixed greys are the brief's.
  - In the shots it sits well in both themes, apart from the label's overflow (finding 8).

### The 11 deviations

| # | Deviation | Verdict |
|---|---|---|
| 1 | No normals in the files; the device computes them | **Accept.** Exact shading under morphs; saves about 1 MB. |
| 2 | Morphs applied on the CPU, not `morphAttributes` | **Accept.** Weights change only in `show()`; 28,159 vertices are cheap to blend. |
| 3 | Per-accessor `extras.scale` and `extras.offset` | **Accept, with finding 13**: make other loaders refuse instead of misread. |
| 4 | A measure rig in `body.glb` | **Accept only with findings 1 and 12**: it must measure the drawn body, be labelled with Apache-2.0, and ideally not ship to phones. |
| 5 | No `MANIFEST.json` fetch and no client SHA check | **Accept.** The server checks every sum; the release is in the URL; the `asset` path is tested, a 404 included. |
| 6 | Two extra modules and `__init__.py` | **Accept.** They keep every module ≤ 400 lines. |
| 7 | Shapes not built (24-segment sleeves, a white sneaker sole, a longer coat, a polo collar, jacket buttons and pockets) | **Partly accept.** The sleeves are fair (30,868 of 32,000 triangles). The sole and the coat need a word in the contract (the slot carries `template`, not the type): put it under "Needs I1". The vest neckline, a brief item, is missing from this list (finding 14). |
| 8 | No collar band at the jacket's back | **Accept.** AVT-07 needs the shirt's collar on top. |
| 9 | A shirt or tee over a wrap is always tucked | **Flag (finding 4).** It silently overrides his choice, and D is not told. |
| 10 | The cuff ends 1.2 cm above the wrist; the sleeve 1.5 cm above the cuff | **Accept.** AVT-07's geometry passes. A fresh render shows the cuff, then the watch, below the sleeve. |
| 11 | The base shorts and garment shorts are longer than v2's | **Accept.** It keeps the removed zone's edge covered at every slider end. |

### "Not test-first": do the tests now pin the behaviour?

Mostly yes, and better than usual. The Node checks read the committed files through the console's own
reader and plan. The browser tests check real pixels. Seven controls each turn their own case red.

Three places still show the order the work was done in:

- the rig stands in for the figure (finding 1);
- the governor has no test at all (finding 2);
- the script's shape code runs only in an opt-in rebuild (finding 7).

The reader's refusal test covers the kinds of file it was written against, not its bounds (finding 3).

### The screenshots (`/tmp/r131-b-shots/`)

- **06 and 07 (the watch swap):** the two files are byte-identical (12,018 bytes each) and show only a
  jacket sleeve's edge. **They prove nothing.**
- **The swap itself works.** It was rendered again here in Chromium at the test's framing, side and front:
  - the left-wrist strap changes from brown to yellow, and nothing else changes;
  - the steel case sits outside the shirt cuff, and the blazer sleeve ends above the cuff;
  - the browser test's diff box agrees.
  - Replace 06 and 07 in the builder's evidence with a crop at the wrist.
- **Socks (11):** the white socks over white trainers do read as tall boots (finding 15).
- **Also seen:**
  - the ragged vest neckline (15, finding 14);
  - the kurta's seam at the waist and the uneven tee neck (13 and 11; already known flaws);
  - the specks through the trousers at inseam 66 (22, finding 6);
  - the label overflowing the panel (every shot, finding 8).

## Review summary

| Severity | Count | Status |
|---|---|---|
| CRITICAL | 0 | pass |
| HIGH | 2 | warn: findings 1 and 2, fix before I1 merges B |
| MEDIUM | 5 | info: findings 3–7 |
| LOW | 10 | note: findings 8–17 |

Verdict: **WARNING, changes requested.** Two HIGH findings should be fixed before merge. No security
blocker.

## Change log

| Version | Date | Release | What changed | By |
|---|---|---|---|---|
| v13.1.1 | 17 Nov 2026, 19:54 IST | R13.1 | First edition: Part B reviewed fresh at `35a57c7` as security, code and Python reviewer. What was run, with numbers. 17 findings (0 CRITICAL, 2 HIGH, 5 MEDIUM, 10 LOW), each with its evidence and a fix. The Workshop's checks (licences, SHA pins, script, reader, CSP, contract, private layer, eval, budgets, governor, sizes, look). A verdict on each of the 11 deviations. The test-order judgement. The screenshots re-judged, the watch swap rendered again. | 🛠 Mark XXIII (review B-1) |
