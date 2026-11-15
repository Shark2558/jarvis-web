Version v13.0.1 · 15 Nov 2026, 19:20 IST · Release R13 · Status: Current · Owner: 🛠 Mark XXI

# R13 — I0 notes (the joins for "Wardrobe & laundry, phone first")

Written by the R13 I0 integrator in the Workshop (🛠 Mark XXI) while building I0 on `r13-i0`. The
plan is `docs/plans/r13-wardrobe.md` (v13.0.2, Status Ready, plan review 1 written in); the builders'
brief is `BRIEF-COMMON.md`, in this folder.

## 1. The base, and the owner's answers

- `r13-i0` was cut from `r13-plan` @ `1e55cb0` (`main` @ `9a8392b`, R14 live as v14.0.2, plus the
  plan and review 1). Nothing was rebased or force-pushed; no part builder has started; no pull
  request is open. The R6.2 mic fix (v6.2.0) merges to `main` first; R13 is brought up to date with
  `main` before its PR (section 7 lists the files both releases touch).
- **The owner answered "defaults OK" to the plan's 14 questions** (15 Nov 2026, 18:38 IST, through
  the Workshop): every safe default in the plan stands (the Wardrobe in Helpers and Camera; the
  private-by-default types; no calendar until he picks one, title on, location off; the 20:00
  reminder; auto-swap off; the rewear rule and the 04:00 close; Holi "okay to stain" only; one
  512-px photo a piece, none for private pieces; a sheet of 24 QR labels; AI tagging off, at most
  ₹30; the 14-day quick check; the sealed 25 MB backup without photos unless ticked; the 80 use
  cases as their own tracker rows; the pilot's pass line).
- A server restart stopped I0 once (18:40 IST) after seams 1–10 were pushed; the uncommitted seams
  11–12 were intact and were re-tested and committed. Nothing was lost.

## 2. Stale lines found at I0 (beyond review 1)

1. **More pins than the plan lists.** The version: besides the four of fact 1,
   `test_r11_seams.py:60` (`startswith("14.")`) and the book's release-label pins
   (`test_r14_seams.py`, `test_r7_seams.py` "the real repository", `test_book_gen_plans.py` twice,
   `test_book_gen_determinism.py`): the book now reads "R13" with this plan first. The kinds:
   R11's Alerts-card order slice and the browser fake's kind list (`tests/browser/test_alerts.py`).
   The keyring: R11's purpose count. The rows: R11.1's Kitchen-to-Maps slice now holds the three
   rows. The bin: R2's `IN_PLACE_KINDS` and `PASSKEY_PURGE_KINDS` equalities. Telegram:
   `test_telegram_personal_reads.py`'s `PERSONAL_PATTERNS`. R5.1's exact `DAYTIME_RING_KINDS`.
2. **The tool names' verbs** (seam 4 says nouns only). Six words of the 18 names are verbs that
   were not action words: count, merge, retire, review, correct, wear. They joined
   `understand/words.py` `ACTION_VERBS` (with "wore", "worn"), so a spoken correction never changes
   them; the nouns (wardrobe, piece, laundry, outfit, plan, plans, label, places, prefs, out) joined
   `TOOL_NOUNS`, and the 18 planned names the guard's list.
3. **The skill register** (seam 13: "group `wardrobe` (`wardrobe_*`, `laundry_*`)"). One group
   would hold 13 tools; the register allows 10 a group (`test_r14_skill_coverage.py`). Three
   groups: `wardrobe` and `laundry` under Task & Productivity, `outfits` under Decision Support.
   Its "pattern matches nothing" check did not consult `planned`: one line in `skills/registry.py`
   lets a pattern wait for a planned tool. R14's "planned names no built tool" test would fail on
   every part branch as soon as a part builds one of the 18: it now exempts them while
   `evals/r13/run.py` `STUBS_PASS` is True (so I1's flip and emptying `planned` go together).
4. **The restore's body cap** (seam 10: one path). The check reads the file too, so
   `BODY_CAPS` holds both `/v1/wardrobe/restore/check` and `/v1/wardrobe/restore`, at the setting's
   ceiling (30 MB) plus 64 KB; A's routes read the body with `read_capped` at
   `wardrobe_backup_max_mb` (25) and answer in plain words between the two.
5. **The book and a second vision release.** With `vendor/vision/r13-1/MANIFEST.json` the newest
   release, the book's licence table read its versions from that manifest only and lost every R7
   vision version (tesseract.js, zxing-wasm, MediaPipe). `buildbook/gen/libs.py` now reads every
   release, the newest first (a test pins R7's versions). R7's licence test requires the book to
   know every `LICENSE-*.txt` beside the releases, so the three new licences got their `VENDORED`
   rows at I0 (the plan gives `libs.py` to D: D owns it from now on).
6. **A tie in the fold.** Two events of one piece at the same `at` (one commit, or two commits at
   one instant) fell back to their random ids. The store records each event after every one before
   it in the piece's log ("arrival breaks a tie"; a conformance case pins it).
7. **The store's signatures** (seam 9 names them only). `Commit(events, extra, records)`:
   `records` are A's index records (a new piece); `extra` are B's own writes as storage ops, never
   written through `tx` (Firestore needs every read before any write: `fn` and the writer read,
   the store writes last). `correct(uid, piece, event_id)` takes the piece (each piece has its own
   log). Every event names a piece: a pending deposit or a blind period is B's review entry plus
   `held` / `blind` events of the plausible pieces. `zone(uid)` is async (it reads the brief store).
8. **`wardrobe/http.py`** was 562 lines: the models sit in `http_views.py` (shared, A) and
   `http_parts.py` (B, C, `GET /v1/r13`), re-exported by `http.py` with `ROUTES` (every module
   ≤ 400). Import them from `jarvis.wardrobe.http`.
9. **The manifest's `licence`** is a description (SSD's reads "MIT (ONNX Model Zoo); weights from
   the TensorFlow Object Detection API (Apache-2.0)", as D8 asks) and `licence_files` names the
   files; R7's manifest used `licence` for a file name. The book shows no version for the models
   (their source is `media.githubusercontent.com`, as zxing-cpp has none).
10. **The door** (`console-r7-send.js`) was not ASCII before I0 (two typographic apostrophes in R7's
    words); the ASCII rule is the scan module's. It is 130 lines (guard ≤ 130).

## 3. What I0 built (seams 1–16)

Tests first: `tests/test_r13_seams.py` (stage by stage), `tests/test_r13_fold_conformance.py` (before
the store it drives), `tests/test_r13_wiring.py`; each was run red, then green.

1. **Version** `13.0.0` (`__init__.py`; lower than 14.0.2 on purpose, D21) and every pin above.
2. **Alert kinds** 52 → 56 (`R13_ALERT_KINDS`: `outfit_ready`, `outfit_changed`, `laundry_overdue`
   important daytime rings, held at night; `wardrobe_review` info) in `alerts.py`,
   `notify/ports.py`, `notify/policy.py`, `notify/held.py`, `console-alerts.js` (+5 lines, 467),
   `webpush/service.py` (all four → `helpers`), `buildbook/plain.py`; `KIND_OWNER` in the ports.
3. **Keyring** 22 → 24 (`wardrobe`, `wardrobe_photos`, last).
4. **Permissions** 49 → 52 (`wardrobe`, `laundry`, `outfits`, R2, one "Wardrobe" section, after
   Pictures; Maps and YouTube last); the save cap 51 → 54 (its own pin: 54 pass, 55 fail);
   `EXPECTED`, `RISK_OF`, `TOOL_OF` for the 18 tools; the words of item 2.
5. **Undo**: `wardrobe_item` (in place, passkey purge, "wardrobe piece"; the console's words); the
   wiring registers A's `bin` service (restore and purge) with the app's bin.
6. **Telegram**: `wardrobe_*`, `laundry_*`, `outfit_*`, `wear_*` behind the personal switch; the
   refusal names the wardrobe; `test_telegram_tool_guard.py` builds the R13 parts (`r13=`).
7. **Guardrails**: `wardrobe_merge`, `wardrobe_retire` in `NO_BULK_TOOLS`.
8. **Settings** (`config.py` 729 → 746): the fourteen of seam 8, with their ranges; "20:00" and
   "04:00" are checked times of day.
9. **The contract** (`src/jarvis/wardrobe/`): `ports.py` (`WardrobePart`, `WardrobeContext` with
   `now()` and `zone(uid)`, `PARTS`, `TOOL_OWNER` and `TOOL_FAMILIES`, `ROUTE_PREFIX`,
   `COLLECTIONS`, `R13_JOB_NAMES`, `JOB_OWNER`, `SERVICE_OWNER` (`store`, `photos`, `bin` A;
   `review_writer` B; `refresh` C; `phrases` D), `KIND_OWNER`, `Mark`, `Commit`, `Committed`,
   `ReviewNeeded`, `HistoryItem`, `PieceChange`, `Refused`, and the Protocols `WardrobeStore`,
   `ReviewWriter`, `ChangeObserver`, `PhotoVault`, `WardrobeData`); `states.py` (10 states, 23
   event kinds, the table, eligibility, pairs and sets); `model.py` (frozen records with short keys,
   ids, the fixed lists from the workbook's sheet "Wardrobe Rules"); `redact.py` (six sinks);
   `http.py` (23 routes' models); the four stub parts; `tests/r13_fakes.py` (fixed IST clocks, the
   24-piece pilot set with pairs, places and a kurta set, a recording review writer and observer, a
   context) and `tests/r13_fakes_store.py` (the in-memory store and the REFERENCE fold);
   `tests/test_r13_fold_conformance.py` (23 cases, every one run on each store it finds: A adds
   `conformance_store` to `tests/r13_fakes_a.py`; an arrival-order control fails it).
10. **Wiring**: `api/r13_wiring.py` (the contract check, `wire_r13` after R14 and before the
    gateway, `join_store`, `register_bin`, `install_r13_phrases` first and in order, the tools,
    the tick and clock jobs, the privacy sources, the data, `BODY_CAPS`, `install_r13_routes`),
    `api/r13_status.py` (`GET /v1/r13`, `limited`, `part_of`), stub routers `api/wardrobe.py`,
    `api/laundry.py`, `api/outfits.py`; `app.py` +5 → **732**; `api/tick_wiring.py` (R13's daily
    jobs last, `outfit_clock` after the other 5-minute jobs); `home/watchdog.py` (`outfit_clock`
    advisory); `tools/setup.py` (`r13=`); `api/personal.py` (R13's privacy slot before home's);
    `offline/mode.py` (`add_phrases(routers, *, first: bool = False)`); `offline/phrases_r14.py`
    (`WITHOUT_AI` + "your wardrobe: where a piece is, laundry, today's outfit");
    `app.state.wardrobe_now` (the real clock unless a test set its own before the start).
11. **The vision contract** (R7's INTEGRATION-B gets its line): `WARDROBE_TASKS` and their schemas
    (`EmbedData` 1,708 base64 characters, 1,280 dims, its model; `ColourData` from 18 colour names
    and multicolour; `FoundData` at most 20 boxes), `parse_result(raw, wardrobe=True)`; `TASKS`
    stays five and the kept-results path refuses the four. `vision/assets.py`: `WARDROBE_RELEASE`
    `r13-1`, `WARDROBE_FILES`, `installed(served, served13)`. The `PANELS` static test.
    **The models** (the Workshop's brief moved them to I0; D owns them from now on):
    `scripts/wardrobe_assets.py` (`check` stdlib only; `fetch` with `onnx==1.23.2` for the cut),
    `vendor/vision/r13-1/` with the three served files and `MANIFEST.json`, the three licence texts
    at pinned commits (ONNX Model Zoo Apache-2.0, UltraFace MIT, TensorFlow models Apache-2.0) and
    `NOTICE-wardrobe-models.txt` (the cut, SSD's two licences, the training-data sentence).
12. **Console**: Helpers → Wardrobe (console-only; `helpers/kinds.py` `TABS` stays five), Camera →
    Wardrobe (`window.JarvisCameraModes`, +13 lines → 481), the door's `wardrobe()` and `tag()`,
    `console-r7.js` loads the scan module and the stylesheet; the four new files are stubs, in
    `APP_ASSETS` and `NOT_IN_PAGE`; `console.html` byte-identical (SHA-256 pinned).
13. **Skill register**: three groups and their words, `no_ai` (7), `planned` (18).
14. **Guide and book**: C69 Wardrobe catalog and the ledger, C70 Laundry, C71 Outfits (PLANNED,
    every collection), the L5 row, C51's purposes, edition v13.0.1; `layers.py` (`wardrobe` → L5);
    `libs.py` (item 2.5). `scripts/arch_coverage.json` needed nothing (no new outside service).
15. **Evals and fakes**: `evals/r13/run.py` (STAGED, `STUBS_PASS = True`), the built `contract`
    part, six stubs, gated in `run_all_mock.py`; `tests/r13_fake_server.py` (23 routes from the
    seeded fake store, each reply validated by its model).
16. `BRIEF-COMMON.md` and this file.

## 4. Decisions taken at I0 (safe defaults)

1. The 8 categories and their types are the workbook's ("Inventory categories and counting"); the
   18 colour names are black, white, grey, charcoal, navy, blue, light blue, green, olive, yellow,
   orange, red, maroon, pink, purple, brown, beige, khaki (plus multicolour).
2. Only an event that changes eligibility becomes a hold when unverified (a step between two
   laundry states does not); `restored` waits in review with Ready to go back to.
3. A second record of the current state with a new place is a place update, not a duplicate.
4. A wear counts when its `wear_done` is applied or superseded, never when it is a duplicate.
5. The fake server's routes take precedence over the parts' own (so D's tests keep running while
   A–C fill their routers); at I1 D's browser tests move to the wired app.
6. Committing the three served model files (13.2 MB) follows D8 ("the cut files are committed")
   and R7's precedent (≈ 23 MB vendored); the fp32 fallback (8.8 MB) is not vendored.

## 5. Sizes after I0

| File | Lines | Guard |
|---|---|---|
| `src/jarvis/api/app.py` | 732 | ≤ 735 |
| `src/jarvis/tools/gateway.py` | 760 | not edited |
| `src/jarvis/core/brain.py` | 713 | ≤ 741, not edited |
| `src/jarvis/api/static/console.html` | 782 | byte-identical |
| `console-camera-panel.js` / `console-r7-send.js` / `console-helpers.js` / `console-alerts.js` | 481 / 130 / 238 / 467 | ≤ 483 / 130 / 238 / 800 |
| `console-wardrobe.css` | 4 | ≤ 200 (new CSS ≤ 300 in all) |
| `src/jarvis/config.py` | 746 | < 800 |
| modules under `src/jarvis/wardrobe/` | ≤ 391 each | ≤ 400 |
| `src/jarvis/api/r13_wiring.py` | 300 | ≤ 400 |

## 6. For I1

1. Flip `evals/r13/run.py` `STUBS_PASS` to False and change
   `test_the_gate_is_staged_until_i1_and_a_stub_fails_once_it_flips` to pin False; empty
   `planned` in `skills/catalogue.json` (the R14 coverage test then bites again).
2. Persona p13.0 with `WARDROBE_RULE` (D21) and its 21 pins.
3. The guide: C69–C71 from PLANNED to built; C63's new words, the camera's privacy row and the
   wardrobe photos' row in the same commit that makes saving possible, pinned (D9, M14).
4. A's real store passes `tests/test_r13_fold_conformance.py` (`r13_fakes_a.conformance_store`);
   the wiring then binds B's writer and C's refresh into it (nothing to change in the wiring).
5. D's browser tests: from `tests/r13_fake_server.py` to the wired app; the existing tabs'
   screenshots against R14's; the full browser suite once.
6. The e2e and needles suites (I1's own), the clock sweep, the pilot (exit check).
7. **The rebase on `main` after R6.2's PR**: both releases touch `src/jarvis/__init__.py`,
   `config.py` (R6.2 +23 lines: 746 + 23 = 769 < 800), `test_about.py`,
   `test_book_gen_determinism.py`, `test_r11_1_seams.py`, `test_r14_seams.py`, `test_r7_seams.py`;
   the version stays R13's (13.0.0, the book "R13").

## 7. The checks (in order, one at a time; 2 CPUs; heavy runs behind the lock shared with R6.2)

| Check | Result |
|---|---|
| The seam tests, every test file I0 touched and the pinned-count tests (Python 3.11), run stage by stage | stage 1: 1,093 then 533 passed after the pins moved; stage 2: 652 passed; stage 3: 789 passed (the guide's cards still to come); stage 4: 1,066 passed; `test_r13_fold_conformance.py` 23 passed six runs in a row (the first runs found the fold's tie, item 2.6) |
| `ruff check` and `ruff format --check` (`src tests evals scripts`) | clean (1,781 files) |
| `mypy src` | 1 error: the baseline's (`memory/redis_store.py:67`) |
| `evals/run_all_mock.py` | **ALL MOCK EVALS: PASS** (the second run); the phase0 smoke fails by design (8 of 12 cases); `r13 (gated)` 19/19, its contract control failing the suite; `r14` 108/108, `r7` 68/68. The first run found the permissions eval's own row table without the three rows (fixed in `41f90cc`) |
| `scripts/check_doc_versions.py`, `scripts/arch_coverage.py` (CI's docs job) | 29 documents pass; arch coverage OK (66 packages and modules, 93 console modules, 2 Scheduler jobs, 30 outside services, 106 collections). The sub-folder docs (`BRIEF-COMMON.md`, `I0-NOTES.md`, R7's `INTEGRATION-B.md`) checked with the same rules: OK. Markdy not run: no diagram changed |
| `scripts/wardrobe_assets.py check` | OK; both cuts reproduced byte for byte from the planner's verified downloads with onnx 1.23.2 (`c32ba47c…`, and the fp32 fallback `d0049881…`, not vendored); the int8 self-check digest re-run on the vendored onnxruntime-web 1.30.0 (Node 22, one thread): `e5b53d7e…`, 152 ms |
| Browser (Python 3.13 with Playwright): `test_alerts`, `test_deleted`, `test_r7_b_camera`, `test_r7_i0_sheet`, `test_r7_i1_joins`, `test_r11_a_today`, `test_r11_i1_paused`, `test_r7_d_body` | 63 passed |
| The book | `test_book_gen_determinism.py` builds the real repository: "R13", this plan first, R7's vision versions kept |
| **Unit suite, Python 3.12, whole** (`pytest -q -x`, last, at `41f90cc` plus these notes) | **16,258 passed, 134 skipped, 0 failed** (14 min 03 s); the 14 warnings are the existing ones (a duplicate OpenAPI id of the phone's door, `forkpty` in the real-evals script) |

What only CI, the parts or the owner can prove: CI's coverage floor on its runners (the new code is
mostly contract and fakes, exercised by the seam, wiring and conformance tests); the models on his
phone (speed, memory, a quantized operator: the self-check reports it); everything the plan's
"What can't be verified from this workspace" lists.

## Change log

| Version | Date | Release | What changed | By |
|---|---|---|---|---|
| v13.0.1 | 15 Nov 2026, 19:20 IST | R13 | First edition: the base and the owner's "defaults OK" (18:38 IST), the stale lines found at I0 (more pins, the tool verbs, three register groups, two restore paths, the book's second vision release, the fold's tie, the store's signatures, the split HTTP contract, the manifest's licence words, the door), what I0 built for each of the 16 seams, the decisions taken, the sizes, the I1 list, and every check with its numbers (the whole 3.12 unit suite last: 16,258 passed, 0 failed) | 🛠 Mark XXI |
