Version v13.0.3 · 16 Nov 2026 · Release R13 · Status: Current · Owner: 🛠 Mark XXI

# R13 — I1 notes (the integration of the four parts)

Written by the R13 I1 integrator on `r13-i1` (cut from `r13-i0` @ `3bf2cb1`). Merged with `--no-ff`
in order: A `9e4401d`, B `b8ee053`, C `eb87a75`, D `0107326` (no conflicts), then R6.2's date-bomb
fix `678f7326` cherry-picked (`InMemorySessionStore(now=)`). `main` is not merged here (the Workshop
merges it after R6.2). Sources: the four `INTEGRATION-<X>.md` §6 lists, `I0-NOTES.md` §6, the plan's
I1 steps, the Workshop's seven binding decisions (Mark XXI) and the owner's decision of 16 Nov.

States: done (commit), declined (reason), left (for the integrated reviews or the Workshop).

## Items

| # | Item | Source | State |
|---|---|---|---|
| 1 | Merge A, B, C, D (no conflicts) and cherry-pick R6.2's date-bomb fix | plan I1 | done `d025d11f` `fc7dc510` `8c7c77b8` `85a59e6f` `a1307f28` |
| 2 | Wiring pins say what each built part reports; `check_part`, `join_store`, `join_sweep`, sweep closer | I0 §6 | done `31978f4b` |
| 3 | One rewear rule, C's `rules.json` (Workshop 1) | Workshop 1 | done `ad800664` |
| 4 | One `CARD_ONLY` in `states.py` (Workshop 2) | Workshop 2 | done `1f309552` |
| 5 | Spoken turn's label, set label and place by words refused (Workshop 3) | Workshop 3 | done `d8cc7fb4` |
| 6 | Settings join: `PUT /v1/wardrobe/settings`, no `lead_h`, `chosen`, `tag_estimate_inr`, `ToolCall.session_id` | A/C/D §6 | done `c40f3689` |
| 7 | A panel card waits in his open conversation (`session_id` on call and reply) | D §6 | done `94b5b431` |
| 8 | Backup `photos` flag is a bool | A §6 | done `998f070f` |
| 9 | `WardrobeData.row`; A offers two privacy sources (pieces, photos) | A §6 | done `82a72d4d` |
| 10 | `ReviewEntry` carries reason, count, answers from the resolver's table | B/D §6 | done `7762312d` |
| 11 | Camera rule in the store; a sighting refreshes `place_at`; a correction reopens its hold in one commit | A/B §6 | done `4dd4820c` |
| 12 | Scan route refuses the camera source and the laundry's own kinds | D §6 | done `8b6d923d` |
| 13 | One `took()` rule for self-health, Home idle alert, laundry job | B §6 | done `fe770db3` |
| 14 | Replay D's recorded calls through each part's real schema and the gateway | plan I1 | done `8e4414fd` |
| 15 | Ship `rules.json` in the image and check it at build; `outfit_plan` never in Approve all; gateway logs a failure's class only | I0 §6 | done `3d6b5a7f` |
| 16 | No-AI runner fills a `TakeCall` from the step before | D §6 | done `919964ad` `25b2a22d` |
| 17 | D's two console modules in `APP_ASSETS`; `gateway.py` at 760; phone eval find names one piece | D §6 | done `c68bafa7` |
| 18 | Door `thumb` and `drop` (guard 130 to 145), I0's door test widened to any quote | D §6 | done `e4549593` |
| 19 | Camera strip's four columns moved into `console-camera.css`; `d_dom.js` ends when its parent dies | D §6 | done `e4549593` |
| 20 | Fake server's stated day is noon his time (or now while it is ahead) | A §6 | done `e4549593` |
| 21 | A14 `wardrobe_max_pieces` 50 to 500 (maximal pieces fit only to 500); plan D1 text | A §6 | done `e4549593` |
| 22 | A15 `wardrobe_restore/{uid}` is his purge count (guide C69; the plan's data model unchanged: it already said so) | A §6 | done `baee5527` |
| 23 | A6 `plan_counts` from C into `PilotCounts` | A §6 | left: C keeps no log of what each suggestion named, so there is nothing to count; the pilot's `suggested` and `unavailable_suggested` read null ("not measured in v13.0.0", F10) and `evals/r13/e2e.py` case 8 counts them from the live suggestions instead. Workshop to say whether C should log them |
| 24 | C9 an "Outfit plans" Privacy row of its own (five rows; B's `laundry` stays "Laundry and wear history") | C §6 | done `e4549593` |
| 25 | C10 key-change note (C51's "When it fails" and C71 in the guide; there is no separate runbook file in the repo) | C §6 | done `baee5527` |
| 26 | C11 guide: C69-C71 built, C63's new words, the camera row keeps "Never kept: a camera frame" and points a wardrobe photo to its own row, all pinned in `tests/test_r13_i1_docs.py` | C §6, D9, M14 | done `baee5527` |
| 27 | D10 and D6 texts (the move is `wardrobe_find` then `wardrobe_edit(piece, place)`; `query` only on `laundry_move` and `wear_log`) | D §6, A §6 | done `baee5527` |
| 28 | Persona p13.0 with `WARDROBE_RULE`; the 21 pins move | D21 | done `6848d035` |
| 29 | Owner decision 16 Nov: a declined calendar event still gets its outfit plan, recorded in plan D13 | owner | done `baee5527` |
| 30 | Workshop 4 overflow sentence ("Tomorrow's outfits for 17 more events are ready in Helpers, Wardrobe.") written into plan D19 as built | Workshop 4 | done `baee5527` (the Workshop's own wording could not be re-read here; it equals INTEGRATION-C 5.13) |
| 31 | `evals/r13/e2e.py` (tests 1-5, 7, 8) and `needles.py` (8 classes, 9 sinks) through the wired app, `evals/r13/wired.py`, `tests/test_r13_i1_e2e.py` | plan I1 | done `67a4487e` `8e329bab` |
| 32 | `STUBS_PASS` False, `planned` emptied, the gate test pins the flip; the Telegram guard's R13 tools built with a keyring | plan I1 | done `67a4487e` |
| 33 | D's browser tests onto the wired app | D §6 | left: they still run on the contract fake server, which `test_the_fake_server_answers_every_route_with_its_model` ties to the real routes; the wired app is covered by the replay of D's recorded calls, the e2e and the needles |
| 34 | Version pins (program 13.0.0, persona p13.0, guide and plan v13.0.3, build book ≤ 80-char library names) | plan I1 | done `baee5527` `6848d035` `8e329bab` |
| 35 | D10 core `tell()` skip for photo-only wardrobe tasks | D §6 | declined: the core's hash is a contract (I0) and D's static test already refuses any console module that subscribes to `embed`, `colour`, `person` or `face` |
| 36 | A16 and C12 integrated re-reviews (`code-reviewer`, `python-reviewer`, `security-reviewer`) in a fresh context | A/C §6 | left for the reviews |
| 37 | The brief test's night is built from today (date bomb, found by the clock sweep on main too) | Workshop | done `361c8725` (passes at today's date and under the sweep at 2027-01-02) |
| 38 | `test_r13_a_backup` expects the hold's own word as a restore entry's reason (I1's `f.hold`, item 11) | A §6 | done `e4549593` |


## Fix (the I1 fixer, after the integrated reviews)

Written by the fixer on `r13-fix` (cut from `r13-i1` @ `25a0de8`, pushed to `r13-i1` by fast-forward). The
two integrated reviews are kept beside this file: `REVIEW-I1-SECURITY.md` and `REVIEW-I1-CODE.md`
(scratch paths replaced by placeholders; no personal data). Each fix was test-first: the test was run
and failed for the stated reason before the fix. "Red" is the number of tests that failed before.

| # | Item | Fix | Test (red) | Commit |
|---|---|---|---|---|
| F1 | The owner's real name was a test value in a PUBLIC repo | A made-up name in every test, eval, doc and two source comments (`git grep -i` of the old name: 0 hits); a full-width and a zero-width variant in two tests moved too | the 91 touched files re-run: 2 red before the variants were moved, then green | `35b4bb7b` |
| F2 | Test-order pollution (about 17 tests in `test_r13_a_routes` and `test_r13_i1_settings` under `-k "r13 or doc ..."`) | `jarvis.core.channel._offline` is a mutable holder shared with child tasks; `test_offline_rules` left it `[True]`, so OfflineRules turned every R2 write into a card. An autouse yield fixture in `tests/conftest.py` resets it before and after every test; the four offline test files' fixtures now yield. Production is per task and `Brain` resets it every turn: it cannot cross owners or requests. Two edges stay LOW (a task made inside an offline turn shares that turn's list; a long-lived loop task that calls `mark_offline()` without a reset): neither touches the wardrobe path | `pytest tests/test_offline_rules.py tests/test_r13_a_routes.py`: 15 red | `93d665d7` |
| F3 | The 8 old wiring pins | All 8 pinned job lists that R13 rightly extends, so the pins moved; no rule was broken. `test_r11_wiring` x2 (the tick's tail gains `laundry_daily`; the watchdog's clock gains `outfit_clock`), `test_r2_wiring` x2 (`laundry_daily` without the key; `wardrobe_sweep` too with it), `test_r4_wiring` x3 and `test_r51_wiring` x1 (`laundry_daily`). "Vitals or health switched off leaves no tool, route or job" still holds and is still asserted | the 8 as named: 8 red | `d67b143d` |
| F4 | Phase 0 eval 4/12 | **Declined, not a regression** (coordinator): `--mock` echoes the last user message, so most checks fail by design; `run_all_mock.py` treats phase0 as an ungated smoke. Nothing changed | n/a | n/a |
| F5 | r7 `131 in clear` | A chance match, not a leak. The eval's capture dumped each `LogRecord` whole, with `created`, `msecs`, `relativeCreated`, thread and line number, and a 3-digit needle sits in those floats by chance (more log rows, more chances). The plain documents were scanned too and hold no 131. The capture now drops those six fields and still searches the message and every extra field; the negative controls still fail the suite | `test_r13_i1_evals`: 1 red | `660f5474` |
| F6 | Security M1 and the code review's count findings | A, B and C answer alike when data is on disk but can't be opened (no keyring, a failed setup, a changed key): count and export say "Couldn't check right now", delete erases what is on disk by path with no key, the index last. `wardrobe/kept.py` (`kept_paths`, `erase`, `KeptData`); a part that is off or failed gets a stand-in; A's log pages carry a plain `owner` field; counts are what is kept (archived and merged pieces, closed laundry batches, a kept calendar choice); the pieces row says it erases photos too | `test_r13_i1_privacy_kept`: 6 red of 8 | `ce559d56` |
| F7 | Security M2 | A merge keeps a piece private when either was, and no photo or print stays on it | `test_r13_a_photos`: 1 red | `83cfb4c3` |
| F8 | Security M3, code review LOW (brand, size) and L5, and the HIGH needles plant | A private piece's label or a place by its words is refused before any card (add: at `check`; edit: at `preview`, which reads the piece); brand and size join the spoken-turn refusal. The needles eval: the private label now rides a piece made private afterwards, a call offering one is refused and searched for, a `place_label` class, and a case `planted_all` that asserts every plant got in as meant (the foreign QR was posted as `jw1:...`, which `LABEL_CODE` refused with a 422, so its class passed testing nothing) | `test_r13_i1_private_words` 3 red; `planted_all` red on the old plant | `119d6407` |
| F9 | Code review HIGH: an archived piece keeps a laundry batch open | `laundry_daily` takes pieces that are archived, merged away or gone off their batches first (one transaction); a batch with nothing left out is dropped | `test_r13_b_jobs`: 1 red | `821713a9` |
| F10 | Workshop decision (item 7), code review MEDIUMs: the pilot, e2e 8's control | `suggested` and `unavailable_suggested` are `null` ("not measured in v13.0.0"), never 0; an unreadable pilot is a 503, not zeros; the dead `passes()` is removed. e2e 8 makes one real `laundry_correct` and its control switches the engine's availability check off, so a basket piece is really suggested | `test_r13_a_routes` 2 red; the control now fails with "1 unavailable pieces suggested" | `2eebfc06` |
| F11 | Code review MEDIUMs: the sweep | A closer that raises no longer skips the hold repair (its failure counts in `failed`); `join_sweep` warns, with the styling part's ready word, when C has no rules | 2 red | `0277dfc5` |
| F12 | Security L1 and L3 | An unpriced brain is refused for AI tagging (503; the estimate is not allowed). A spoken turn can't name a shop for `laundry_send_out`. **Behaviour change** (the B test that pinned a spoken shop as a card now pins the refusal; revert there if the Workshop wants it back) | `test_r13_a_tagging` 1, `test_r13_b_checks` 1 red | `3e6e54e9` |
| F13 | Security L4, code review LOW (null switch) | `PUT /v1/outfits/settings` answers through `joined()` so `tag_estimate_inr` is in both replies; the AI tagging row says On or Off and "About x a photo"; `{"ai_tagging": null}` is no change in the audit line | 3 red | `2d03019c` |
| F14 | Code review LOWs: path pollution, an `assert`, the dead `correct` | The r13 suites load by path (no `evals/r13` on `sys.path`; `wired.py` appends instead of inserting); `styling/jobs.py` checks instead of asserting; `CatalogStore.correct` stays (A's tests use it) with a docstring and a guard test that no product code calls it | `test_r13_i1_evals` 1 red | `a8f4fc00` |
| F15 | Security L2 and the docs | The plan (D9, summary 6) and guide (C63) say the console's face check is the console's: the server cannot decode a picture. The pilot's "not measured" and the Privacy rule are in the plan and cards C63 and C69 | `test_r13_i1_docs` 1 red | `36cc87f7` |

Left or declined: the two functions a little over 50 lines (`api/app.py` `_install_core_errors` 53,
`api/personal.py` `privacy_sources` 52; both near the line before R13); a stand-in for B when its setup
fails (B builds without a key and keeps its own `_kept`); C's `wardrobe_told` claims are not in C's
stand-in (hash and time only); an "Ask first" needles world (the refusal is at `check`, so the policy
never matters); the answer to item 23 stays with the Workshop (should C log what it suggests).

