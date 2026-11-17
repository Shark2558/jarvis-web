Version v13.1.2 · 18 Nov 2026, 03:20 IST · Release R13.1 · Status: Current · Owner: 🛠 Mark XXIII

# R13.1 — I1 notes (the four parts joined)

Written by the R13.1 I1 integrator on `r13-1-i1`, cut from `r13-1-i0` @ `eb8b7e4`. Merged with
`--no-ff` in this order: A `4dd58f6` (`dad08f8`), C `3660d24` (`8c63019`), B `eb7ea8d`
(`f42253e`), then D `de5a9b4` (`33b5fb1`) once its fixer finished, all with no conflicts. `main` is
not merged here.

Sources: the four `INTEGRATION-<X>.md` files ("Needs I1", A §8 and §11, B §6 and §8, C §6 and
§10.4, D §6), the four `REVIEW-<X>-1.md` reviews' notes for I1, `I0-NOTES.md` §5, and the plan's
I1 steps (`docs/plans/r13-1-try-on.md` v13.1.3: "Tests and evals", "Exit check").

States: **done** (commit), **declined** (the reason), **left** (for the integrated reviews, the
Workshop or a later release, with the reason). "Red first" means the test was run and failed for
the stated reason before the change; "a pin" means a test of behaviour the joined parts already
had, green when first run.

## Items

1. **I0's three stub pins** (INTEGRATION-A 8.1, B 6.1, C 6.1). Done `ef63076`. With no keyring,
   `tryon` reads A's `OFF_NO_KEY` and `seeme` C's "off: …" words; no part says "not built yet";
   the wired app's `GET /v1/tryon` is 503 `off` in A's words, `GET /v1/seeme` 503
   `not_configured`, both 401 signed out. B's engine keeps the engine contract and `mount()`
   with no host throws "The 3D view needs a place on the page.".
2. **A's contract changes against B, C and D** (INTEGRATION-A 11.3). Checked:
   - `rgb: null` → B draws it mid-grey and names `colour` in `approx` (`console-tryon-cloth.js`
     `rgbOf`, `GREY`); D: at D's merge.
   - `LookSlot.refs` → C does not read A's look: it finds a piece's front crop in R13's own photo
     records (`pair.front_of`, INTEGRATION-C §4.10). Both read the same `view` field, and a
     joined test pins that A's `refs` front and C's pick are the same crop. Done `20e6db4`.
   - The new codes (`refused`, `left_out`, `changed`, `not_whole`, `too_large`, `internal`) are
     D's to branch on: at D's merge.
3. **A's look route takes `?pieces=` with `&plan=`** (INTEGRATION-D §5). A pin `20e6db4`:
   readiness is read in that plan's context, so its own pieces are Ready; the same pieces with
   no plan read "Draft: reserved for your plan" (why D sends the plan along).
4. **The end date, one source** (INTEGRATION-C 10.4 b, review C-1 finding 6). Done `7b7c2c5`:
   `tryon_model_retires` is removed from `Settings` (the model's own `RETIRES_ON` is the one
   date; a second could only disagree), with its unused `_DAY` pattern; `config.py` is 789 lines.
5. **`tryon_cache` defaults to true** (INTEGRATION-C 6.2 and 10.4 d, review C-1). Done `7b7c2c5`,
   red first: fail toward disclosure. The deploy passes `JARVIS_TRYON_CACHE` explicitly and sets
   false only after its PATCH worked, so the deploy is unchanged. C's cache test now builds its
   world with the cache proved off.
6. **The deploy's role** (INTEGRATION-C §7 (a), (b)). Done `7b7c2c5`, red first: an existing
   `jarvisTryOn` is set back to `aiplatform.endpoints.predict` only (a note if that fails; the
   role is still used, never the broader fallback); the comment says what the role allows:
   prompt requests to any Agent Platform model, with the cap and the `jarvis-tryon` budget alert
   as the brakes. (c), whether the cache PATCH covers the `us` endpoint, can't be checked here.
7. **The fake server's consent version** (INTEGRATION-C 10.4 a). Done `c9d4c44`, red first:
   "c2-0123456789ab", the shape of C's "c2-" + 12 hex.
8. **A decodable fake picture** (INTEGRATION-D §7). Done `c9d4c44`, red first:
   `r131_fake_tryon.PNG` is a drawn 120 × 160 RGB PNG (407 bytes: a plain figure in a navy top);
   every test that compares bytes with it still does.
9. **SciPy in CI** (INTEGRATION-B 8, "Needs I1" 4). Done `9b35767`, red first: the 3.12 leg
   installs `scipy==1.18.1` (the script's own pin) after the homebridge extra. Checked with CI's
   own pins (3.12, numpy 2.5.4, scipy 1.18.1): B's two files 74 passed, 2 skipped, the release
   rebuilt byte for byte; the script's tests take about 11 s; coverage is measured on `jarvis`
   only, so the floor is not moved. 3.11, the browser and docs jobs are untouched.
10. **F8, F9, F10 on I0's files** (INTEGRATION-A 11.4, items 3–5). Done `044d636`, red first:
    `BodyIn`'s fields are `StrictInt`; `model.Body` reads with `extra="ignore"` (a rollback
    opens his figure; `BodyIn` stays strict); "All your try-on data" counts documents and says
    "The month's Try-on spend (numbers only) stays 13 months for your monthly limit.".
11. **One rule for the words a garment is sent in** (INTEGRATION-C 10.4 c). Done `1dcbaec`, red
    first: `llm.tryon.FIXED_WORDS`; C's `pair.PROMPT_WORDS` and the adapter's `WORDS` are that
    one object. `StrictTryOn` stays in C's fakes (it runs the adapter's whole check); I0's
    `ScriptedTryOn` is unchanged so no earlier test moves.
12. **A press in flight during OPS-05, A with C** (review A-1 F12, review C-1 finding 3). A pin
    `20e6db4`: OPS-05 through A's own `tryon_all` row while a press is held at the provider:
    422 `no_photo`; no picture, photo, YES, garment photo or figure left; the spend stays; the
    hold closed at what Google made; the wardrobe's `rev` unchanged. C's own fix closes it three
    ways (a re-check after the call, the check inside the save's transaction, the sweep after
    the delete); removing only the check in the save keeps this test green.
13. **The `e2e` suite** (plan "Tests and evals"). Done `2c5acb7`: BUILT through the real app
    (`evals/r13_1/wired.py`), five cases: "Meeting outfit update", "Layer and rotate", "Private
    items and photos" (OPS-05 through the Privacy service), See it on me's life (30 days, gone by
    `seeme_daily`), and row 388 typed and spoken through the mock brain. Its control (the look
    built from a stale view) fails "Meeting outfit update" for its own reason.
14. **The `needles` suite** (plan; INTEGRATION-A 11.4 item 7, C 6.7). Done `ab89c1d`: 9 classes ×
    13 sinks, a positive control per sink, `planted_all`, and the one request to Google decoded
    (exactly his photo, the garment, the chosen crop; one fixed text part). Allowed: the two
    photos in the request to Google; his measurements in `tryon_figure`'s own export (A 8.4,
    decided at review A-1); a private piece's label in R13's own export of his catalog
    (`wardrobe_pieces`). Its control (the adapter logging its request body) fails exactly the
    two photo needles.
15. **Console-only on the wired app** (I0-NOTES §5 item 2). A pin `6dede8d`: all 12 routes the
    contract marks console-only, the garment photo's three included, answer 403 `console_only`
    to a script holding his token and reach C from his console.
16. **The vitals line before GST** (INTEGRATION-C 6.3). Declined: `Billing.record` adds the
    pre-GST ₹ as every brain's line does; the Try-on panel and the cap show GST. One rule for
    every Vitals line.
17. **A port method for a photo's view** (INTEGRATION-C 6.4). Declined: not needed; C reads R13's
    plain `view` field read-only, and item 2's pin keeps it in step with A.
18. **The device check's counts sent with each upload** (INTEGRATION-C 10.4 f, review C-1
    finding 7). Left for a later release: a contract change across the door, D's photo panel and
    `http.QUERIES`; the server cannot decode a picture, so the check stays the device's (as R13's
    console face check is, card C63).
19. **The audit's risk level for a paid press** (INTEGRATION-C 10.4 g). Declined for R13.1:
    `record_change` is shared; the press's audit line already carries `code` and `inr`, the
    spend is in `tryon_spend` and Vitals, and every press sits behind his YES and a ₹ confirm.
20. **The data model's new fields** (INTEGRATION-C 10.4 h): `tryon_spend/{uid}_{YYYY-MM}` gains
    `done_order`, the consent record gains `cache`, and `tryon_spend/{uid}_prefs` holds his
    switch, cap and keep days (C §4.1). Recorded here; the plan is not re-versioned for them.
21. **Serve the figure's files compressed** (INTEGRATION-B 8, "Needs I1" 5). Declined for R13.1:
    the 2.6 MB come once a device and are cached a year (the release is in the URL); nothing in
    the app is compressed today (R7's vision files are served the same way). One app-wide change
    later, with the `.gz` beside each file under the manifest's sums.
22. **The book's licences for B's test source** (INTEGRATION-B 8, "Needs I1" 6). Declined: the
    book lists what ships; `tests/fixtures/r13_1/b_source.bin.xz` is CC0 test data that never
    ships.
23. **A sole and a longer coat** (INTEGRATION-B 8, "Needs I1" 7). Left for a later release: a slot
    carries its template, not its type, so it needs a contract word.
24. **I0's `fake_routes` at 126 lines** (INTEGRATION-A 11.4 item 9). Declined: a test fake, not
    product code.
25. **The fresh-context reviews** (A 8.5 and 11.4 item 10, C §7 and 10.4 i, D §6 item 5). Left for
    the integrated reviews (`code-reviewer`, `python-reviewer`, `security-reviewer`), which the
    Workshop runs on this branch.

26. **D's door lines** (INTEGRATION-D §9, "Needs I1" 1). Done `40f52c0`, red first: the door
    (`console-r7-send.js`, 165 of 165) carries `make` (PictureIn's five fields, each checked
    before a byte is sent), `keep`, `forget` and `garments`, to `/v1/seeme/` only. D's two proposal
    pins now read the applied file.
27. **"Show in 3D" with Try-on off** (D §9 "Needs I1" 2, review D-1 M7). Done `40f52c0`, red
    first: I0's hook (302 of 306) draws it only while D's `state()` is "on" and draws again on
    `jarvis:tryon-state`. D's "before I1" browser test became the joined behaviour (`010d808`).
28. **B's real engine in D's card and section** (Workshop step 3). The product already loads B's
    `console-tryon-3d.js` (D's fake engine was a test route only). Proved on the wired app
    (`9c2f967`, `tests/r131_wired_server.py`: `create_app`, every part, C's real adapter on
    recorded answers, a mock brain that answers "...wear..." with `outfit_suggest`) by
    `tests/browser/test_r131_i1_wired.py` (9 tests, `0463bbb`, `8aa46e2`), with B's engine spied,
    never replaced: row 388 typed and spoken (the figure in exactly the card's pieces, its first
    frame drawn, a private slot covered), one stage between card and section, the section
    dressed in tomorrow's plan, compare, the checklist with no WebGL2, See it on me end to end
    on C's routes, console-only, the six Privacy rows.
29. **B's contract honoured by D** (`forced`, host ≥ 150 px, `onLost` reasons, 30 s for files):
    D's fix did it (D §9); checked on B's real engine above (no `onLost`, a frame drawn).
30. **Use these measurements names the draft he saw** (A 11.4 item 2, review A-1 F7). Done
    `3fe3155`, red first: D sent no `?at=`; it now sends the draft's `at`. Declined: making `at`
    required on the server (every console press sends it; A's tests pin the optional form).
31. **The gate flipped** (I0 §5 item 1). Done `446f63d`, red first: `STUBS_PASS = False`; every
    part of `run.PARTS` is BUILT.
32. **The guide** (I0 §5 item 5, plan D17). Done `cb8e341`, red first: v13.1.3; C72 and C73 built
    and joined, with each part's modules; C63 "Three panels see pixels: Camera, Camera → Wardrobe
    and Try-on's own photo check (…)"; R13's C63 pin and I0's guide pin move with it.
33. **Found at I1: R13's "suggestion" row is no plan.** R13's `/v1/outfits` lists a day with no
    plan as an entry whose id is "suggestion". D's section opened on `?plan=suggestion` (404) every
    evening with no plan today, I0's hook drew Show in 3D on it, and compare offered it. Fixed
    `0463bbb`, `8aa46e2` (red first on the wired app): a saved plan's id only (`op_` + 8 hex); a
    suggestion is read by its day. The contract fakes had saved plans only.
34. **Found at I1: A's 503 "off" read as "can't load right now".** A says Try-on is off with 503
    `{"error": "off"}` (review A-1 F5); D took only a 404 as off, so R13's own Wardrobe browser
    tests failed (5 of 10). Fixed `8c63587`, red first: `err.code === 'off'` is off; any other 503
    stays "for now". `test_console.py`'s by-design console lines gain that 503.
35. **Found at I1: the figure's files did not ship.** R14's packaging guard went red: no
    package-data pattern matched `static/vendor/mannequin/m1/`, so `pip install .` (the deploy)
    would have had no GLBs and every figure would fall back to the checklist. Fixed `b0d14e6`:
    `"static/vendor/mannequin/*/*"`; a wheel built here holds all six files.
36. **Found at I1: B's stage test broke CI's collection.** CI's test job runs plain `pytest` with
    no Playwright; B's browser module imported it at its top. Fixed `62bae78`, red first: it uses
    `pytest.importorskip`; `tests/test_r131_i1_ci.py` refuses a top-level Playwright import.
37. **Found at I1: D's fakes changed I0's shared photo views at import**, so 152 of A's tests
    failed in a full run (none alone). Fixed `6f5e772`, red first: D's views are added in D's server
    process only.
38. **D's tests after the joins.** AVT-15's "engine throws" case loaded the real engine file, which
    is B's now: it serves its own throwing engine (`fee5a4c`). D's See it on me setup posted the
    literal "c2": it sends the version it was shown (`82ae250`).
39. **L6's second edge and L12's split of `console-tryon.js`** (D §9). Left for a later slice:
    the file is at 599 of its 600-line guard (I1's three fixes there kept to existing lines); L6
    holds no WebGL context (a new card already disposes the old card's stage). Moving the
    measurements form, shapes and OPS-05 (about 80 lines) to a module of its own needs a new size
    guard, an `arch_coverage.json` entry and the guide.
40. **`keep_days` in the console** (D §6 item 4). Left: it needs `keep_days` in `SeeMeView`
    (C's contract) and a 1–30 control; the server setting exists and the owner answered 30 days.

## The checks (18 Nov 2026, at `8c63587` / `8aa46e2`; one at a time behind the heavy-run lock)

| Check | Result |
|---|---|
| Unit, Python 3.12 (four parts, `tests/test_*.py`) | 4,251 + 4,705 + 4,665 + 4,957 = **18,578 passed**, 52 skipped, 2 failed: both the worktree's path (below). The packaging guard of item 35 was red in that run and passes since `b0d14e6` |
| Unit, Python 3.11 | 4,252 + 4,705 + 4,665 + 4,957 = **18,579 passed**, 50 skipped, 2 failed: the same two |
| The two "failures" | `test_r13_i1_evals::…r7_capture…` and `test_r7_seams::…r7_runner_passes…` search log rows for the needle `131`, which is in this worktree's own path (`/tmp/r131-i1`; B noted it first). From an export of HEAD at a path without it, both pass (91 passed; the export's one other failure needs a git checkout) |
| R13.1 unit files after the last fixes (3.12) | 1,147 passed, 2 skipped |
| `ruff check` / `ruff format --check` (src, tests, evals, scripts) | clean; 2,057 files formatted |
| `mypy src` | the baseline error only (`memory/redis_store.py:67`) |
| `evals/r13_1/run.py --mock` | **121/121**, no part unbuilt; every built part's control failed it (console 4, contract 10, e2e 1, figure 10, looks 10, needles 2, seeme 12 cases red) |
| `evals/run_all_mock.py` | from the worktree: every suite passes but r7 67/68 (`body:sealed_no_value`, the path's `131`); from the export: **ALL MOCK EVALS: PASS** (r7 68/68, r13 110/110, r14 108/108, r13_1 121/121, 21 gated controls failing their suites), phase0 smoke 4/12 as usual |
| `scripts/check_doc_versions.py` · `scripts/arch_coverage.py` | 30 documents OK · OK (66 packages, 103 console modules, 120 collections) |
| `python -m jarvis.buildbook.gen --check` | two builds byte-identical |
| Browser (Chromium, `-m browser`, one file at a time): R13.1 and R13's Wardrobe | B stage 23, D card 14, D section 18, D See it on me 14, D stage 11, D look 16, I1 wired 9, R13 camera 12, R13 helpers 10: **127 passed** |
| The visual gate `tests/browser/test_ui_audit.py` | **116 passed** (56 night, 60 the rest) |
| A wheel built from the branch | holds the six files of `vendor/mannequin/m1/` |

Not run here: the whole browser suite (the Workshop's, after the integrated reviews); a live
Google picture ("not called": it needs his typed YES; exit check 7); his phone's GPU.

## Screenshots (not committed: drawn data, the wired app, B's real figure)

`/tmp/r131-i1-shots/` (31 PNGs), laptop 1280 × 800 and phone 360 × 800, night and day:
`01-card-real-figure-*` (the card under "What should I wear tomorrow?", dressed by itself),
`02-section-real-figure-*` (Helpers → Wardrobe), `03-compare-*` (tomorrow's meeting beside
today's look), `04-card-checklist-*` and `05-section-checklist-*` (no WebGL2),
`06-seeme-garment-*`, `07-seeme-yes-laptop-night`, `08-seeme-rupee-confirm-*`,
`09-seeme-picture-*` (I1's drawn PNG, decoded), `10-privacy-tryon-rows-*`,
`11-tryon-off-wardrobe-tab-laptop-*` (A's 503 off: R13's tab with no Try-on section). Looked at:
the console's own components and colours throughout, the figure dressed in the look's colours,
no sideways scroll on the phone. Seen, R13's and not R13.1's: R13's suggestion row says "planned
by hand" and its reasons line names piece ids (`11-…`).

## Known limits (recorded, not fixed)

- **"Use this look" refuses a look with a removed watch, belt, outer layer or socks** (409
  `left_out`): R13's engine re-adds a removable slot on every read, so a plan can't keep one
  empty. The durable fix is R13's (`Plan.omit`, INTEGRATION-A 11.4 item 1), a later R13 change.
- **Garment poke-through at inseam 66 and waist 120** (B's two documented limits, capped in its
  layer check): a ledge on the trousers with a thin line of the base layer (5.6 cm²) at inseam 66,
  and a waistband gaping 1.2 cm² under the belly at waist 120.
- **The watch strap's edge looks ragged in close-up.**

## Change log

| Version | Date | Release | What changed | By |
|---|---|---|---|---|
| v13.1.1 | 17 Nov 2026, 23:50 IST | R13.1 | First edition: A, C and B merged; items 1–25 (the stub pins, the contract checked against B and C, the end date and cache settings, the deploy's role, the fakes, SciPy in CI, F8–F10, one fixed-words rule, OPS-05 in flight, the e2e and needles suites, console-only on the wired app, and what was declined or left with reasons); the known limits | 🛠 Mark XXIII (I1) |
| v13.1.2 | 18 Nov 2026, 03:20 IST | R13.1 | D merged; items 26–40 (D's door and hook lines, B's real engine proved on the wired app, `?at=`, the gate flipped, the guide, five integration bugs found and fixed with tests first: the suggestion row, A's 503 off, the figure's files not shipped, CI's browser collection, D's fakes' shared state; what is left with reasons); the checks with their numbers; the screenshots | 🛠 Mark XXIII (I1) |
