Version v13.1.4 · 18 Nov 2026, 10:50 IST · Release R13.1 · Status: Current · Owner: 🛠 Mark XXIII

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
   red first: fail toward disclosure. C's cache test now builds its world with the cache proved
   off. Corrected by the integrated security review (finding 1): the deploy then started from
   false, so a run whose role step failed claimed the cache off with no PATCH sent; since
   `690b84d2` it starts from true and says false only after the PATCH AND a read-back.
6. **The deploy's role** (INTEGRATION-C §7 (a), (b)). Done `7b7c2c5`, red first: an existing
   `jarvisTryOn` is set back to `aiplatform.endpoints.predict` only (a note if that fails; the
   role is still used, never the broader fallback); the comment says what the role allows:
   prompt requests to any Agent Platform model, with the cap and the `jarvis-tryon` budget alert
   as the brakes. (c), whether the cache PATCH covers the `us` endpoint, can't be checked here.
   Superseded by the integrated security review L5: a role that can't be set back is no longer
   used, nor kept bound, and the `roles/aiplatform.user` fallback is gone (`690b84d2`, `51e07b73`).
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
    Reversed by the integrated security review (finding 7): done `d3f7a8d4`.
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
    guard, an `arch_coverage.json` entry and the guide. L12's split was done at the integrated
    fixes (`b04e353b`: `console-tryon-form.js`, its own 150-line guard; `console-tryon.js` 534).
40. **`keep_days` in the console** (D §6 item 4). Left: it needs `keep_days` in `SeeMeView`
    (C's contract) and a 1–30 control; the server setting exists and the owner answered 30 days.

## Fix (integrated reviews)

The fixes of `REVIEW-I1-CODE.md` and `REVIEW-I1-SECURITY.md` (both at `b11205d`), on
`r13-1-i1` from `b11205d` to the head named in "Full checks". Each commit's diff was read against
its finding; "red first" as above. Every finding of both reviews:

**Code review (0 critical, 1 high, 5 medium, 8 low).**

| Finding | State | Commits |
|---|---|---|
| H1 · the card read for today with the default code | done, red first on the wired app: `cardQuery(card)` sends the card's slots (covered as `slot:`), its plan, else its day and code; swap, undo and refresh pass the look's own; every test builds the query through the console's own rule; both fakes refuse a no-plan `pieces=` with no day | `d1258052`, pins `c677e1e0`, `7d331c90` |
| M1 · lock by slot unchecked | done, red first: the slot's pick is checked as a named piece (ready, held by no other plan); `transfer` checks the moved piece too | `c34c7a69` |
| M2 · the day look takes a worn plan | done, red first: A's `for_day` uses R13's `planned`; R13's `PlanView.worn` (one field) and the console's `first()` skip a worn plan | `26983d96`, `a795a544` |
| M3 · no checklist when the figure can't be read | done, red first: the figure is read in its own try; off or signed out says A's words, any other failure draws the checklist with its own why | `94079bd5` |
| M4 · a billed picture not saved | done, red first: `not_saved` settles at the billed ₹, says "It may still be charged", audits the real ₹; its retry says the same (`REPEATED`) and never calls Google again; `seeme/books.py` keeps `make.py` under its guard | `b68b5543` |
| M5 · the rules twice | done (no behaviour change; a static pin red first): `styling/ready.py` holds the readiness rule and its words; `PRIVATE_SLOTS` and `covered` live once in `styling.look` | `3c18a1b0` |
| L1 · `settled_inr` unused | done: the press settles with it, else the hold | `b68b5543` |
| L2 · standard logging in `tryon_card.py` | done, with a static pin for every wardrobe module | `e5775b5c` |
| L3 · card viewers never let go | done, red first: a card whose row left the page is disposed, its observer disconnected | `2a238d28` |
| L4 · a shared garment picture lost | done, red first: the hand-over loads See it on me first; if it can't, the tray keeps the picture | `905dacf2` |
| L5 · silent console fallbacks | done, red first: the three reads say their failure and keep nothing | `06f4bc7d` |
| L6 · weak and brittle pins | the weak one done (each console route's own status and code; the browser twin pins 403 `console_only`); the exact-source pins in `test_r131_i1_console.py` left, as the review allows: the browser tests carry the behaviour | `245a1728` |
| L7 · two NumPy pins | done: the script's pin is the bridge's 2.5.4, pinned one against the other. This departs from the plan's D3 text ("numpy==2.5.3"); the release was rebuilt byte for byte with 2.5.4 (item 9) | `86469b6c` |
| L8 · "131" needles match paths and clocks | done: R7's capture leaves out the code's own location beside the clock's fields (planted in all four, the record's own fields still searched); A's measurements needle masks the moments the code writes. The fixed 12-hex needle the review proposed was not needed for these. The suites are still run from a path without "131" (R7's runner has other path-bound needles) | `44afa149`, `47ee60f2` |

**Security review (0 critical, 0 high, 1 medium, 6 low).**

| Finding | State | Commits |
|---|---|---|
| 1 MEDIUM · the cache said off without trying | done, red first: `TRYON_CACHE=true` before the `if`; false only after the PATCH AND a read-back of `disableCache: true`; the only `TRYON_CACHE=false` in the deploy; item 5 corrected | `690b84d2` |
| 2 LOW · "press again" replays a not-billed refusal | done, red first: a release is not kept in `done`, so a 429 then a press with the same id makes the picture (two calls, spent once) | `6366515e` |
| 3 LOW · a retry across month-end | done, red first: the press and `reserve`'s transaction also read the month before for `SETTLE_HOURS` after his month's start; a `done` there answers, a fresh hold there is `busy` (tested at 23:59:50 and 00:00:20 IST) | `dbdf5de7` |
| 4 LOW · a picture of a since-private piece | done, red first: the overview, the picture route and the Privacy export first delete every picture showing a piece now private or gone (`drop_taken`); an unreadable wardrobe leaves it to the morning job | `5ab3e154` |
| 5 LOW · role fallbacks beyond prompt rights | done, red first, fail closed: an existing `jarvisTryOn` that can't be set back is never bound and (`51e07b73`) is taken off `jarvis-run` if an earlier run bound it ("not found" is silent, any other refusal a note); the `roles/aiplatform.user` fallback is gone; See it on me stays off with a note that says how to make the role. The residual risk (prompts to any Agent Platform model, outside JARVIS's cap) is stated in C73 with the budget alert as the outside brake (guide v13.1.5, `88c60a71`). This departs from the plan's seam 13 text ("falls back to `roles/aiplatform.user` with a note"); the plan is not re-versioned for it | `690b84d2`, `51e07b73`, `88c60a71` |
| 6 LOW · the budget's "300" in the account's currency | done: `--budget-amount=300INR`. gcloud's reference says a currency given "must be the currency associated with the billing account", so a USD account refuses it and the deploy's note says to add the alert by hand at the try-on cap in the account's own currency; it never sets $300. No conversion is attempted (a rate in a deploy script would go stale) | `690b84d2` |
| 7 LOW · the audit's risk level and timing | done, red first: `record_change` takes `risk` (REVERSIBLE by default, no caller moves); the press, its "sending" line (after the reserve, before the call, never raising) and the three deletes are IRREVERSIBLE | `d3f7a8d4` |
| Concurred · review C-1 finding 7 | left, as item 18 (a contract change for a later release) | — |

Also at the fixes: `b04e353b` split the section's forms out of `console-tryon.js` (item 39) to make
room for H1, M3 and L3; `0aa45477` and `88c60a71` keep the guide's C72 and C73 in step.

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

## Full checks

The Workshop's full checks after the integrated fixes, one suite at a time behind the heavy-run
lock (2 CPUs, about 7 GB), each from a fresh export of HEAD at a path without "131" (R7's needle
tests match it), in chunks of a few minutes across three server restarts. The export is a
one-commit scratch git repository of `git archive HEAD` (the build-book tests need `git
rev-parse`) and the unit runs set `PYTHONPATH` to its `src` (the venvs' editable install points at
an older checkout, which a test's own subprocess would otherwise import). Every chunk's log is
kept outside the repository, with the commit in its name.

The suites ran at `39e9a1ab`. GitHub's browser job on draft PR #38 (run 44216933907, `39e9a1a`)
then failed 11 of 1,574, fixed with the owner's approval in two test-only commits (below), so the
new HEAD is `2efd3fd5`. What that delta touches was run again there.

| Check | Result |
|---|---|
| Unit, Python 3.12, with coverage (`39e9a1ab`) | **18,643 passed**, 0 failed, 150 skipped (98 of them `tests/browser`, skipped without `JARVIS_BROWSER_TESTS`), 3 warnings, 19 chunks |
| Coverage of `jarvis` (19 chunks combined) | **95.60 %** (86,691 statements, 3,811 missed); `scripts/coverage_floor.py`: floor 95 %, target 80 %. The delta to `2efd3fd5` touches no file under `src/` |
| Unit, Python 3.11 (`39e9a1ab`) | **18,644 passed**, 0 failed, 149 skipped, 3 warnings (one test runs on 3.11 that 3.12 skips) |
| At `2efd3fd5` | `tests/test_r131_png_pixels.py` 7 passed on 3.12 and on 3.11; every unit file that globs a folder (50 files, the tests that look at `tests/` among them) 2,153 passed, 2 skipped on 3.11; the seams, CI and D static pins 242 passed |
| `ruff check src tests evals scripts` · `ruff format --check` (CI's scope and scripts) | clean · 2,065 files formatted (ruff 0.17.5) |
| `ruff check .` · `ruff format --check .` | 88 errors, all in `.claude/skills/continuous-learning-v2/scripts/` (vendored tooling, the same on `main`) · 14 files: 13 as on `main` (`.claude/` and Python code blocks in older plan docs, which ruff 0.17 formats in Markdown) and `REVIEW-A-1.md:129`, a review quoting an indented excerpt as it stood (left as a quote) |
| `mypy src` | the baseline error only (`memory/redis_store.py:67`), 909 files |
| `evals/run_all_mock.py` | **ALL MOCK EVALS: PASS**: 43 gated suites pass, each control failing its suite (r7 68/68, r13 110/110, r14 108/108, r13_1 121/121); phase0 smoke 4/12, as always with the mock brain |
| `evals/r13_1/run.py --mock` | **121/121**; all seven parts BUILT (`parts_not_built` empty, `stubs_pass` false); every part's control failed its cases: console 4, contract 10, e2e 1, figure 10 controls, looks 10, needles 2 (his photo, the garment's), seeme 12 |
| `scripts/check_doc_versions.py` · `scripts/arch_coverage.py` | 30 documents OK · OK (66 packages and modules, 104 console modules with `console-tryon-form.js`, 2 Scheduler jobs, 31 outside services, 120 collections) |
| `python -m jarvis.buildbook.gen --check`, twice | byte-identical both times, at `39e9a1ab` and at `2efd3fd5` (book.json 198,076 bytes) |
| Clock sweep, 3.11, at 2 Jan 2027 09:00 IST (`39e9a1ab`) | 18,643 passed, **1 failed**, 149 skipped. The one: `test_r11_1_c_bridge_trouble.py::test_a_file_still_being_copied_waits_and_is_read_once_it_settles` (R11.1), the known artefact: the half-copied file's modification time comes from the real clock, so under the moved clock it looks weeks old and is read at once instead of waiting 60 s. It passes without the sweep. No date bomb |
| Browser, the FULL suite (Chromium, `-m browser`, one file a chunk; the UI audit in two halves) | **1,574 passed, 0 failed**: 1,396 in 92 chunks at `39e9a1ab` (files 1–91, R13.1's eight among them: B stage 23, D card 17, D look 16, D section 21, D See it on me 15, D stage 11, I1 card day 4, I1 wired 9), 178 in the last 7 files at `2efd3fd5`. No flake: every file passed on its first run (a chunk cut by a restart was run again whole) |
| The two changed browser files at `2efd3fd5`, with `import PIL` blocked | `test_r131_b_stage.py` 23 passed, `test_r131_d_look.py` 16 passed |

**GitHub's browser job (run 44216933907): 11 failed, 1,563 passed.** Ten of B's stage tests imported
Pillow, which that job never installs (`.[dev]` and Playwright only); here the browser venv sees the
system's Pillow, so they passed (the R7 lesson). And row 388's fit test asked for exactly 100 % of
the reply in view and got 0.99889 (a fraction of a pixel of layout rounding in that Chromium).
Fixed with the owner's approval, test-only:

- `ac0152b8`: `tests/r131_png_pixels.py` reads a PNG with zlib and struct (8-bit RGB or RGBA, not
  interlaced, all five filters, CRCs checked; the alpha dropped as Pillow's `convert("RGB")`), and
  the stage tests use it. `tests/test_r131_png_pixels.py`, red first, covers every filter type and
  two PNGs Chromium itself wrote (`tests/fixtures/r13_1/png/`), read to the values Pillow read. A
  pin keeps every module under `tests/` off Pillow. Proof: with an import blocker for `PIL`, the
  stage file failed exactly CI's ten, and now passes 23 of 23. A scratch cross-check decoded every
  PNG those tests read with both readers: 19 PNGs, 7,683,360 pixels, identical. A scan of `tests/`
  finds no other import of a library CI's jobs don't install.
- `2efd3fd5`: the fit test measures the pixels of the reply and of the figure that are hidden and
  allows at most one (`FIT_SLACK_PX`), never a line of words.

**Row 388's screenshots, re-taken at `2efd3fd5`** into `/tmp/r131-i1-shots/` (not committed):
`01-card-real-figure-*` and `04-card-checklist-*`, laptop 1280 × 800 and phone 360 × 800, night and
day. The scene: tonight's meeting is planned, tomorrow has none, and he asks at 19:00 "What should
I wear tomorrow? Something formal.". Looked at, all eight. The card reads "Your look · business
formal" with no "Draft". B's figure wears the white shirt tucked under the brown belt, the navy
blazer and the grey trousers, its base layer covered and the whole figure in view on both sizes.
The checklist for a device without WebGL2 lists the same pieces, each "Ready", under its why.

Not run here: a live Google picture (it needs his typed YES); his phone's GPU.

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
| v13.1.3 | 18 Nov 2026, 06:20 IST | R13.1 | The integrated reviews' fixes: every finding of both reviews with its commits (all done but code L6's exact-source pins, left as the review allows, and the concurred C-1 finding 7); L5 completed (a role that can't be set back is taken off JARVIS's account) and L6 checked against gcloud's reference; items 5, 6, 19 and 39 brought up to date; the departures from the plan's D3 and seam 13 recorded | 🛠 Mark XXIII (I1 fixes) |
| v13.1.4 | 18 Nov 2026, 10:50 IST | R13.1 | Full checks after the integrated fixes, with their numbers: unit 3.12 18,643 passed and coverage 95.60 %, unit 3.11 18,644, lint and types, the mock evals (r13_1 121/121, every part BUILT and every control failing), the docs, architecture and book checks, the clock sweep (one known modification-time artefact), the full browser suite (1,574 passed); GitHub's browser job's 11 failures fixed test-only (`ac0152b8` pixels without Pillow, `2efd3fd5` a one-pixel fit); row 388's screenshots re-taken | 🛠 Mark XXIII (I1 fixes) |
