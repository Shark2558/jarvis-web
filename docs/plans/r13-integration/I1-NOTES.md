Version v13.0.3 · 16 Nov 2026 · Release R13 · Status: Current · Owner: 🛠 Mark XXI

# R13 — I1 notes (the integration of the four parts)

Written by the R13 I1 integrator on `r13-i1` (cut from `r13-i0` @ `3bf2cb1`). Merged with `--no-ff`
in order: A `9e4401d`, B `b8ee053`, C `eb87a75`, D `0107326` (no conflicts), then R6.2's date-bomb
fix `678f7326` cherry-picked (`InMemorySessionStore(now=)`). `main` is not merged here (the Workshop
merges it after R6.2). Sources: the four `INTEGRATION-<X>.md` §6 lists, `I0-NOTES.md` §6, the plan's
I1 steps, the Workshop's seven binding decisions (Mark XXI) and the owner's decision of 16 Nov.

States: done (commit), declined (reason), left (for the integrated reviews or the Workshop).

## Items (open = still to do on this branch)

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
| 18 | Door `thumb` and `drop` (guard 130 to 145) | D §6 | open |
| 19 | Camera strip CSS move; `d_dom.js` exits when its parent dies | D §6 | open |
| 20 | Fake-server noon stated day (A13) and D tests expecting noon | A §6 | open |
| 21 | A14 `wardrobe_max_pieces` 600 to 500 after checking the plan | A §6 | open |
| 22 | A15 C69 retention row and plan data model | A §6 | open |
| 23 | A6 `plan_counts` from C into `PilotCounts` | A §6 | open |
| 24 | C9 "Outfit plans" Privacy row decision | C §6 | open |
| 25 | C10 runbook key-change note | C §6 | open |
| 26 | C11 guide: C69-C71 built, C63 wording, camera and wardrobe-photos privacy rows | C §6 | open |
| 27 | D10 and D6 texts | D §6 | open |
| 28 | Persona p13.0 and its 21 pins | plan I1 | open |
| 29 | Owner decision 16 Nov: declined calendar events keep their outfit plans, recorded in the plan | owner | open |
| 30 | Workshop 4 overflow sentence confirmed | Workshop 4 | open |
| 31 | `evals/r13/e2e.py` and `needles.py` | plan I1 | open |
| 32 | Flip `STUBS_PASS`, empty `planned`, update the gate test | plan I1 | open |
| 33 | D's browser tests on the wired app | D §6 | open |
| 34 | Version pins | plan I1 | open |
| 35 | D10 core `tell()` skip | D §6 | declined: core stays untouched; the shared `took()` rule (item 13) covers the need |
| 36 | A16 and C12 integrated re-reviews | A/C §6 | left for the reviews |
