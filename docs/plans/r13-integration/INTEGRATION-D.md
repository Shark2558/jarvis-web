Version v13.0.1 · 15 Nov 2026, 21:55 IST · Release R13 · Status: Current · Owner: 🛠 Mark XXI

# R13 — Part D: Phone and panel (INTEGRATION-D)

Built on branch `r13-d` from `r13-i0` @ `3bf2cb1` by the R13 Part D builder in the Workshop (🛠 Mark
XXI), against `docs/plans/r13-wardrobe.md` v13.0.2 Part D, `BRIEF-COMMON.md` and `I0-NOTES.md`. The
owner's "defaults OK" (15 Nov, 18:38 IST) stands: every safe default below is the plan's. Not reviewed
here: `code-reviewer`, `python-reviewer` and the required `security-reviewer` (the door's use, the scan
module, the redaction views) run in a fresh context, not by this builder.

## 1. What D built, by use case and decision

| Plan item | What is built | Where |
|---|---|---|
| D8 the models | Face and person self-check references recorded (Node 22, the vendored onnxruntime-web 1.30.0, one thread): face, the top five face scores on the ramp over 1 x 3 x 240 x 320 (tolerance 0.002); person, SSD's one detection on a drawn silhouette (class 1, 0.9449, its box; tolerance 0.03), because SSD's own score floor gives no detection on the ramp. `scripts/wardrobe_assets.py manifest` writes MANIFEST.json from the pins without the network and refuses a vendored file that differs. The fp32 fallback is not vendored: `embed`'s int8 self-check passes here | `scripts/wardrobe_assets.py`, `vendor/vision/r13-1/MANIFEST.json` |
| D7-D9 the four tasks | `embed` (uint8 x 1,280, 1,708 base64, `mnv2-int8-1`), `colour` (Lab median of the box's centre, nearest of the 18 names, multicolour for two far clusters, naming the larger), `person` (SSD class 1 >= 0.5), `face` (UltraFace >= 0.7, NMS 0.3), all photo-only, registered before `sealRegistry()`; the I0 core's hash unchanged. One runtime: the wake word's module URL and `env.wasm` (one thread, no proxy, its folder). Each `load()` runs its fixed input and compares with `SELF13` (the manifest's numbers); a mismatch releases the session and is "not installed". `logSeverityLevel: 3` keeps UltraFace's initializer warnings off the phone's console. Sessions are released on `pagehide` | `console-vision.js` Part B (641 lines) |
| OPS-01, D5, D9 the phone checkpoints | Camera -> Wardrobe: Add pieces (a box per piece laid apart; his label offered first; "seen before?" from his fingerprints, centred, compared on the phone, at most 3, bands 0.80 / 0.60, identical copies within 0.03 said; kind chips; the suggested colour; "Make it private?" for a private-by-default kind), To laundry (deposits, ids only; Cancel sends nothing; "and more I couldn't show" a pending deposit with no id; "Not sure which" sends both unverified, so both are held), Back clean (the place; dry or needs pressing), Find (a scan or a typed name in his own list), Read a label (size, fabric with its percentage, care words; each unverified until he confirms; the text itself never leaves). The person and face checks run on THE canvas the crops are cut from; one hit, or a check not installed, and that photo keeps and sends nothing, while a label read or a tapped match still makes its event. Crops <= 512 px, JPEG 0.8, only through `door.wardrobe` / `door.tag`; never for a private piece. Unsent events wait in page memory ("Not sent yet: keep this page open", "Send now"), each with its capture `at` and its `sent` stamped at send. Stop and leaving the tab end the camera and the live label reader. Nothing asked before sign-in or a press | `console-wardrobe-scan.js` (595 lines) |
| D1 Helpers -> Wardrobe | Needs a check, Today and tomorrow, Laundry, Pieces, Labels, Settings, from the frame's builders and existing classes; every change through `POST /v1/wardrobe/tools/{tool}`; C's settings through `PUT /v1/outfits/settings`; the calendar list only on his press (the governed read's own answer is shown); the QR sheet and the sealed backup as downloads; restore checked first (counts, "nothing is changed until you press Restore") then applied with the token | `console-helpers-wardrobe.js` (282), `console-wardrobe-pieces.js` (104) |
| D10 private pieces | Hidden in Helpers until "Show private basics" is tapped (the view's `private_hidden` count says how many); otherwise "A private basic", with his printed label's number when there is one ("A private basic (No. 2)", D10's card form), so two identical vests can be told apart; no photo, fingerprint or AI tag ever offered for one | both modules |
| H2 AI tagging | Only with his setting on, the AI on (`JarvisBrainMode` not "none"), a saved piece that is not private, and a photo whose check ran and found nobody; the rupees and the month's counter are shown before the press; refused when the month would pass its cap | `console-wardrobe-scan.js` `tagBox` (see deviation 1) |
| D1 the look | `console-wardrobe.css` (52 lines, no colour, font, radius or shadow literal) only places things; the chosen step or kind wears the existing `.btn.primary`; the Camera strip gets four columns for its four tabs (deviation 7) | `console-wardrobe.css` |
| D20 the Privacy rows | Section "Wardrobe", four rows over every part's `WardrobeData`, read late from `app.state.r13_parts`: pieces and places (data named "pieces"), laundry, outfits and wear history (every other source), photos and fingerprints (data named "photos"), and the device row (page memory only; nothing to delete). Counts add up; the export is each source's own export under its name; delete (passkey) empties only that row's sources; one failing source hides only its row | `wardrobe/phone/privacy.py` (167) |
| D6, D20 No-AI | Anchored routers installed first: what to wear (day words and the occasion to the tool), where a piece is (the wardrobe's call, then Things'), the move ("I put my watch in the travel bag"), the basket, the clean return, laundry status, the wear's start and done ("done for today", "yesterday"), counts. Never a possessive, R14's not-a-thing words, or bag, glasses, spectacles, keys, wallet, umbrella | `offline/phrases_r13.py` (277) |
| The part | `build(ctx)`: no tool, job or collection; `services["phrases"]` (the routers, in order) and the four rows; ready "ready" | `wardrobe/phone/part.py` (36) |
| The book | The SSD licence row now reads the manifest's words (D8: "the same in `buildbook/gen/libs.py`") | `buildbook/gen/libs.py` |
| The eval | `evals/r13/phone.py` BUILT (below) | `evals/r13/phone.py` |

## 2. Sizes against the guards

| File | Lines | Guard |
|---|---|---|
| `console-vision.js` | 641 | <= 800 (the I0 core's SHA-256 unchanged) |
| `console-wardrobe-scan.js` | 595 | <= 600 |
| `console-helpers-wardrobe.js` | 282 | <= 600 |
| `console-wardrobe-pieces.js` | 104 | <= 600 |
| `console-wardrobe.css` | 52 | <= 200 (new CSS <= 300 in all) |
| `wardrobe/phone/privacy.py` / `part.py` | 167 / 36 | <= 400 |
| `offline/phrases_r13.py` | 277 | <= 400 |
| `console.html` | 782 | byte-identical (not touched) |

Every function is at most 50 lines (none of D's console functions passes 30). No wiring or shared
file was edited.

## 3. Tests and checks (what ran, and the numbers)

| Check | Result |
|---|---|
| D's unit tests: `test_r13_d_assets.py` (the manifest, the script, the engine's references, the real models in Node, INV-06's real half, the book's rows), `test_r13_d_vision.py` (the pure arithmetic in Node, the checks), `test_r13_d_phrases.py` (D20 rows, near misses, every R14 phrase unchanged, the wiring order), `test_r13_d_part.py` (the contract, the four rows), `test_r13_d_scan.py` (25 behavioural scenarios in Node with spies) | see section 3.1 |
| R7's tests D owns: `test_r7_b_console.py`, `test_r7_b_dom.py` (nine tasks, `BASE13`, the wardrobe tasks' own release) | in section 3.1 |
| Seam tests: `test_r13_seams.py`, `test_r13_fold_conformance.py`, `test_telegram_tool_guard.py` | pass (316 with the wiring file's other tests) |
| `test_r13_wiring.py` | 2 expected failures: I0's stub pins say every part is "not built yet" and D is now "ready" (Needs I1, item 1, exact diff) |
| Browser (Python 3.13, Playwright, real Chromium, the console's CSP, one file at a time, behind the lock): `tests/browser/test_r13_d_camera.py` | 10 passed (the four tasks self-check; a drawn face and a drawn figure are found, a laid shirt is neither; one runtime with the wake word; add, save, remember, the same photo offers the piece and his tap keeps its id; a face or a figure keeps and sends nothing; a live label read, an unsent scan and "Send now"; the visual gate x4) |
| Browser: `tests/browser/test_r13_d_helpers.py` | 9 passed (the six sections; private basics only after a tap; a change through the tools route; a piece's history; the calendar's governed answer; the sheet downloads; nothing asked before sign-in; the visual gate x4) |
| Browser: R7's `test_r7_b_camera.py` visual gate (the strip now has four columns) | 4 passed |
| `python evals/r13/run.py --mock --part phone` | 15/15; the control (the person check off) fails exactly `phone:ops01:person_keeps_and_sends_nothing` |
| `python evals/r13/run.py --mock --part contract` | 14/14 with D built; its control fails the suite |
| `ruff check` / `ruff format --check` (D's files, `tests/`) | clean |
| `mypy` on D's Python | no issue (the repository's one baseline error is elsewhere) |
| `scripts/wardrobe_assets.py check`, `scripts/arch_coverage.py`, `scripts/check_doc_versions.py` | OK; arch coverage OK (66 modules, 93 console modules); 29 documents |

### 3.1 Counts

The counted run (Python 3.11, behind the lock): **420 passed, 0 failed**: D's own 155
(`test_r13_d_assets.py` 8, `test_r13_d_vision.py` 11, `test_r13_d_phrases.py` 105,
`test_r13_d_part.py` 6, `test_r13_d_scan.py` 25), R7's two files D owns 171 (`test_r7_b_console.py`
116, `test_r7_b_dom.py` 55) and R14's phrase file 94 (unchanged, run beside R13's routers). The seam
run (`test_r13_seams.py`, `test_r13_wiring.py`, `test_r13_fold_conformance.py`,
`test_telegram_tool_guard.py`): **316 passed, 2 failed**, the two of Needs I1 item 1. Browser: **23
passed** (D's 10 and 9, R7's camera gate 4).

## 4. Screenshots (`/tmp/r13-d-shots/`, for the Workshop)

Camera -> Wardrobe, at 1440x900 and 390x844, Night and Day: `camera-wardrobe-start-*`,
`camera-wardrobe-card-*` (a drawn striped shirt, one card, its kinds and suggested colour),
`camera-wardrobe-laundry-*`. Helpers -> Wardrobe, the same sizes and surfaces:
`helpers-wardrobe-*` and `helpers-wardrobe-pieces-*` (each also as `*-panel.png`, the panel alone):
the review queue with two private copies told apart by label number, tomorrow's plan, the laundry,
the pieces with the private basics shown and a piece's history open. 28 files in all (12 Camera, 16 Helpers).

## 5. Deviations from the plan, and why

1. **The AI tag's rupees** (H2: "the ₹ shown first"): I0's static test
   `test_the_door_is_the_only_caller_of_the_wardrobes_picture_routes` refuses the literal
   `'/v1/wardrobe/tag` in every console file but the door, which also catches the read-only
   `GET /v1/wardrobe/tag/estimate`. Rather than spell the path around the guard, the button shows
   the plan's at-most figure for one photo (₹0.30) and the month's ₹ and cap from the view's
   settings, R7's own precedent (`ASK_COST`: "I0's door gives no cost to read"). Needs I1, item 2.
2. **No thumbnails or one-photo delete in Helpers**: the same test blocks `GET` and `DELETE
   /v1/wardrobe/photos/{id}` outside the door. Pieces says how many photos a piece has; all wardrobe
   photos are deleted from Privacy (passkey). Needs I1, item 2.
3. **No test hook for a detection**: a drawn face fires UltraFace (0.999) and a drawn silhouette fires
   SSD's "person" (0.94), in Node and in Chromium, so the refusal tests use the real models; the
   Node harness fakes the answers for the flow tests. Nothing in the shipped module can be told to
   pass a photo.
4. **The box split** is plain arithmetic in the scan module (the border's colour as the surface, a
   one-cell gap closed so a striped shirt stays one box, parts of at least 1.5 %, at most six, left
   to right): the plan says "a box per piece" and names no detector (R7's `objects` model never
   arrived).
5. **A label's brand is not read** (OCR brand text is unreliable): size, fabric with percentages and
   care words only, from the fixed lists; he types a brand in Helpers.
6. **The bands** stay the plan's (0.80, 0.60, 0.03). INV-06's real half: a drawn striped shirt stays
   candidate 1 rotated 25 degrees, folded and from the back, with centred scores 0.43, 0.53 and
   0.81 (margins 0.37 to 0.78), so "likely" is rarer than the bands suggest; the pilot calibrates.
7. **The Camera strip** has four columns: I0 gave the panel a fourth tab and R7's
   `console-camera.css` lays the strip out in three, so Wardrobe sat alone on a second row.
   Placement only; R7's camera visual gate passes at both sizes. I1 compares with R14's screenshots.
8. **Private copies by number**: in his own console a hidden private piece is "A private basic
   (No. N)" when it has a printed label (D10's own card form), so INV-07's two vests can be told
   apart without showing them.
9. **The person self-check input** is a drawn silhouette, not the ramp (SSD's score floor gives no
   detection on the ramp, so the ramp would prove nothing); its arithmetic lives once, in
   `console-vision.js` `SELFCHECK`, and the Node test runs that very text.

## 6. Needs I1 (exact diffs)

1. **`tests/test_r13_wiring.py`** (I0's; D may not edit it): building D moves two stub pins.
   ```diff
   @@ def test_every_stub_part_builds_through_the_real_modules
   -    assert {p.ready for p in parts.values()} == {"not built yet"}
   +    assert {n: p.ready for n, p in parts.items()} == {
   +        "catalog": "not built yet", "laundry": "not built yet",
   +        "styling": "not built yet", "phone": "ready",  # at I1: each built part's word
   +    }
   @@ def test_the_app_builds_the_four_parts_and_answers_v1_r13
   -            (n, "not built yet") for n in PARTS
   +            (n, "ready" if n == "phone" else "not built yet") for n in PARTS
   ```
   A, B and C move the same pins when they build; at I1 both read each part's own ready word.
2. **`tests/test_r13_seams.py`** (I0's): the door test should hold the picture-SENDING routes only.
   ```diff
   @@ def test_the_door_is_the_only_caller_of_the_wardrobes_picture_routes
   -        for route in ("/v1/wardrobe/photos", "/v1/wardrobe/tag"):
   +        for route in ("/v1/wardrobe/photos?", "/v1/wardrobe/tag?"):  # the sending routes
                assert f"'{route}" not in code, (path.name, route)
   ```
   Then D (a) asks `GET /v1/wardrobe/tag/estimate?piece=` before the tag button and shows the
   brain's own ₹ (the fake server already answers it), and (b) shows a thumbnail through
   `JarvisChat.raw('/v1/wardrobe/photos/' + id)` as a blob URL (the console's CSP `img-src` must
   allow `blob:`; to check) with a Delete per photo. The other way: the door gains `estimate(piece)`
   and `thumb(id)`; that edits `console-r7-send.js` (130, guard <= 130), so the test change is the
   smaller one.
3. **The tool arguments D sends** (A, B and C build in parallel; one side moves at I1):
   - A `wardrobe_add {type, private, colour?}` answering `result.piece`; `wardrobe_edit {query, place}`
     (the No-AI move, D6 and D20 name it, D10's list of `query` tools does not),
     `wardrobe_edit {piece, label_field: size|fabric|care, value: {v, pct?, ok}}`,
     `wardrobe_edit {settings: {ai_tagging}}` (see 5); `wardrobe_count {type | category, ready?}`;
     `wardrobe_find {query}`; `wardrobe_retire {piece, action: archive|restore}`;
     `wardrobe_remove {piece}`.
   - B `laundry_move {step: basket|ready, query}` (No-AI), `{step: washing|drying|ready, pieces,
     load?}`, `{step: basket, unseen, category}` (LND-03's pending deposit); `laundry_status {}`;
     `laundry_review {action: resolve, entry, piece}` or `{..., none: true}`;
     `laundry_send_out {action: receive, batch, pieces}`.
   - C `outfit_suggest {day?: today|tomorrow, occasion?}` (day words: the tool reads his zone, D15);
     `wear_log {action: start|done, query?, plan?, day?: yesterday}`.
   - Scan events (`POST /v1/wardrobe/scan`): `seen`, `deposited`, `returned` (with `place`),
     `needs_prep`; `source: phone`, `via: ph-<random>`, `how: qr|match`, `verified` false only for
     "Not sure which".
4. **`WardrobeData` names**: A names its index source "pieces" and its photo vault "photos"; every
   other source (A's log, B's, C's) is counted in "Laundry, outfits and wear history".
5. **A's own settings** (AI tagging, private display) have no route in `wardrobe/http.py`; D sends
   `wardrobe_edit {settings: {ai_tagging}}`. Either A accepts that, or I1 adds
   `PUT /v1/wardrobe/settings` (a contract change, with `record_change`, D1).
6. **The backup and restore**: D sends the "include photos" tick as `GET /v1/wardrobe/backup?photos=1`
   (the contract names no parameter); Restore sends the token only, so a purged piece is not yet
   offered for ticking (`RestoreCheck.purged`, `RestoreApply.include_purged`).
7. **D's browser tests** run on `tests/r13_fakes_d.py` over I0's fake server (its fixed clock moved to
   09:30, after the seeded registrations, so a phone's corrected `at` lands after them); at I1 they
   move to the wired app (I0-NOTES 6.5).
8. **The persona and the guide** (I1's): `WARDROBE_RULE`, C63's new words and the wardrobe photos'
   row land with the commit that makes saving possible (D9, M14).

## 7. Pins D moved (its own files)

`tests/test_r7_b_console.py`: the engine is sealed after NINE tasks; R7's BASE regex no longer reads
`ORT_BASE`; a task may fetch from `BASE13`; `load: guard(` counts 7 (R7's four and R13's three);
new: the wardrobe tasks load only their own release and the wake word's runtime settings.
`tests/test_r7_b_dom.py`: the engine lists the nine tasks, the four wardrobe ones photo-only. R7's
INTEGRATION-B gets its line from I0 (seam 11).

## 8. What can't be verified here

The models on his phone (speed, memory, a quantized operator: the self-checks report it; Node here
gives 170-270 ms a model); UltraFace and SSD on a real face and a real partial body (only drawn ones
here); a real camera (Chromium's fake device only); the match rates on his clothes (the pilot); the
other parts' real routes and tools (fakes until I1); Web Push and Telegram words (B and C send them).

## Change log

| Version | Date | Release | What changed | By |
|---|---|---|---|---|
| v13.0.1 | 15 Nov 2026, 21:55 IST | R13 | First edition: what D built per use case and decision, the sizes, every check with its numbers, the screenshots, nine deviations with their reasons, eight Needs-I1 items with exact diffs, the R7 pins moved, and what this workspace can't verify | 🛠 Mark XXI |
