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
| 23 | A6 `plan_counts` from C into `PilotCounts` | A §6 | left: C keeps no log of what each suggestion named, so there is nothing to count; the pilot's `suggested` and `unavailable_suggested` stay 0 and `evals/r13/e2e.py` case 8 counts them from the live suggestions instead. Workshop to say whether C should log them |
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
