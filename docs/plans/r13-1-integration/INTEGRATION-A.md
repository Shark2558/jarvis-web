Version v13.1.1 · 17 Nov 2026, 20:05 IST · Release R13.1 · Status: Current · Owner: 🛠 Mark XXIII

# R13.1 Part A: Try-on data (AVT-03, AVT-04, AVT-05, AVT-09, AVT-11, AVT-14, OPS-05)

This is builder A's report for I1. Branch `r13-1-a`, cut from `r13-1-i0` @ `eb8b7e4`. It is built
against these documents:

- `BRIEF-COMMON.md` v13.1.2, `BRIEF-A.md` v13.1.2, `I0-NOTES.md` v13.1.1;
- the plan `r13-1-try-on.md` v13.1.3: D4–D7, D11's no-go list, D14, D16, D20, D21, the data model,
  the HTTP contract's `tryon` rows, the `looks` suite.

Two builders built it in turn. The first wrote the plan below and 11 commits of code, tests and
the eval (`2d73b41` … `5a140a2`); a server restart stopped it. The second took over at `5a140a2`
and did these things:

- ticked BRIEF-A item by item against the code (section 3);
- built what was missing or wrong, each test first (section 2, "Second builder");
- ran the checks (section 6);
- wrote the rest of this file.

## 1. Plan (written before the code)

What A builds, in this order, each test first (red, then green):

1. `wardrobe/tryon/store.py`: the sealed `tryon/{uid}` document (purpose `tryon`, AAD
   `model.aad_tryon`, plain `owner` and `updated_at`, at most 200 KB sealed); an unreadable
   document is never overwritten; no keyring or no storage is `Off`. Tests `test_r131_a_store.py`.
2. `versions.py`: a draft from what he typed (range words), "Use these measurements", "Keep the
   current", five earlier versions, `BodyView.weights` from `model.morph_weights`; typed fields
   stay typed, the rest re-estimated from the height. Tests `test_r131_a_versions.py`
   (`test_avt02_store_*`, the AVT-03 named test through the routes).
3. `options.py`: one slot's readiness from a FRESH view and his plans (Ready, `DRAFT_WORDS`,
   reserved for an event, one shoe missing, a set part without its set, the shared base); the
   ≤ 12 options of a slot. `assets.py`: his figure choice per piece (AVT-05), tidied on read.
4. `looks.py`: the look for a plan, a day (`alt` 0–2) or a reply card's pieces (row 388), each
   `LookSlot` with its template, colour, texture view, views kept and missing, readiness,
   approximate flags, options; a private slot covered only. Tests `test_r131_a_looks.py`
   (AVT-04, AVT-05, `test_avt14_looks_*`, row 388's `?pieces=`).
5. `confirm.py`: "Use this look": the fresh check before any tool call (409 in words), then ONE
   `outfit_plan` `lock` with `pieces` through `run_panel_tool`. Tests `test_r131_a_confirm.py`
   (AVT-09 with the race).
6. `saved.py`: saved comparisons (≤ 10, re-checked on every read). Tests `test_r131_a_saved.py`
   (`test_avt11_saved_*`).
7. `privacy.py`, `erase.py`: the rows `tryon_figure`, `tryon_all`, `tryon_device`; OPS-05's
   `erase_all` (C's half through its service, else by path; `tryon/{uid}` last; the catalog
   untouched). Tests `test_r131_a_privacy.py` (the OPS-05 named test through `PrivacyService`).
8. `part.py` (the join) and `api/tryon.py` (the 11 routes): owner-only, `no-store`, limited,
   every refusal a `Refusal`. Tests `test_r131_a_routes.py`, `test_r131_a_part.py`.
9. `evals/r13_1/looks.py`: the cases, the three suite controls and each row's own control; BUILT
   only once every control turns its case red.

## 2. What was built

Every file is Part A's own (BRIEF-A section 1). No other file was edited. Line counts are at the
head of this branch.

| File | Lines | What it is |
|---|---|---|
| `src/jarvis/wardrobe/tryon/part.py` | 193 | the join `build(ctx)`: `WardrobePart("tryon", privacy=3 rows, services={"tryon_looks": TryonService}, ready="ready")`, or "Off: …" in words with I0's stand-in rows; `TryonService` (looks, measurements, figure choices, the confirm, saved comparisons, `erase_all`) |
| `src/jarvis/wardrobe/tryon/store.py` | 201 | `TryonStore`: `tryon/{uid}` `{owner, rev, blob, updated_at}`, sealed under `tryon` with AAD `tryon/{uid}/v1`; `Off`, `Unreadable` (never overwritten), `TooBig` (200 KB sealed); `present`, `stamp`, `delete` with no key |
| `src/jarvis/wardrobe/tryon/versions.py` | 137 | D4: a draft, Use (the old current → first earlier, ≤ 5), Keep the current; typed stays typed, the rest `model.estimated(height)`; every `BodyView` carries `model.morph_weights` |
| `src/jarvis/wardrobe/tryon/options.py` | 185 | one FRESH read (`Fresh`); a slot's readiness by R13's rules (state, one shoe, a set part, reserved for another plan's event, the shared base, gone); ≤ 12 options a slot |
| `src/jarvis/wardrobe/tryon/assets.py` | 112 | AVT-05: his figure choice saved against the piece id; the effective template; tidied on read (merged, purged or private pieces dropped) |
| `src/jarvis/wardrobe/tryon/looks.py` | 355 | the `TryonLook` for a plan, a day and `alt`, or a reply card's `?pieces=`; each `LookSlot`; covered slots; gaps said without a private piece |
| `src/jarvis/wardrobe/tryon/confirm.py` | 101 | D7/D20: the fresh check before any tool call ("The navy jacket is in the laundry: it can't be confirmed for this event."), then ONE `outfit_plan` lock of every slot |
| `src/jarvis/wardrobe/tryon/saved.py` | 140 | AVT-11: ≤ 10 saved comparisons (one look or two, piece ids per slot, tuck, open, layers; never a picture), re-checked on every read |
| `src/jarvis/wardrobe/tryon/privacy.py` | 93 | D16: `tryon_figure` (count, export, delete with a confirm), `tryon_all` (OPS-05, passkey), `tryon_device` (`kept.DeviceRow`) |
| `src/jarvis/wardrobe/tryon/erase.py` | 43 | OPS-05 `erase_all`: C's half through `ports.seeme_service`, then by path (`kept.erase_seeme`), then `tryon/{uid}` LAST; the spend and the catalog untouched |
| `src/jarvis/api/tryon.py` | 316 | the 11 `tryon` rows of `http.ROUTES`: owner-only, `no-store`, 60 reads and 30 changes a minute per route, every refusal a `Refusal`; `record_change` with field names only |
| `tests/r131_fakes_a.py` | 245 | `a_world()`: R13's real styling part, store and gateway at `r131_fakes.NOW`, the pilot's photos and their views, Part A built; `FakeSeeMe`; R13's own `GET /v1/wardrobe` over a `CatalogDesk` |
| `tests/test_r131_a_store.py` | 126 | 11 cases: the sealed document |
| `tests/test_r131_a_versions.py` | 112 | 15 cases: `test_avt02_store_*`, a version never touches saved selections |
| `tests/test_r131_a_options.py` | 206 | 24 cases: readiness, options, figure choices |
| `tests/test_r131_a_looks.py` | 315 | 35 cases: looks, row 388, AVT-04/05/06 views, `test_avt14_looks_*` |
| `tests/test_r131_a_confirm.py` | 142 | 10 cases: the fresh check, the race, one lock |
| `tests/test_r131_a_saved.py` | 135 | 11 cases: `test_avt11_saved_*` |
| `tests/test_r131_a_privacy.py` | 190 | 12 cases: the three rows, OPS-05's order, C off or failing |
| `tests/test_r131_a_part.py` | 73 | 4 cases: the join through I0's real wiring |
| `tests/test_r131_a_routes.py` | 315 | 19 cases: the routes |
| `tests/test_r131_a_rows.py` | 261 | 5 cases: the named tests of A's rows |
| `tests/test_r131_a_needles.py` | 96 | 1 case, the guard: his measurements in no log, tool call or audit entry |
| `evals/r13_1/looks.py` | 373 | the `looks` eval: 9 cases, 8 controls, `BUILT = True` |

**Second builder (after `5a140a2`), each test first unless said:**

| Commit | What |
|---|---|
| `8e598ab` | Row 388 seam bug. I0's card sends a slot holding a private piece as `private: true` with no id, for ANY slot (a top he made private too). A refused `top:` with 422, so that look's card could not open. Now an id-less entry of one of R13's slots is that slot covered. Tested on a real `tryon_card.card_of` card. |
| `43e1e93` | AVT-14 edge. With R13's records unreadable, `GET /v1/tryon` listed every kept figure choice unchecked. A choice for a piece made private since would name its id. Now no choice is listed until they can be checked. |
| `ad47565` | OPS-05's named test reads the catalog through R13's own `GET /v1/wardrobe`, as his check says (pieces and `rev` before and after). The OPS-05 control fails it at that check. |
| `54cac25` | The needles guard (written after the code: it passed at once; its positive control, `put_body` logging the height, fails it). |
| `3dee5f4` | The eval's AVT-09 case also checks the draft ("Draft: in the laundry", not eligible). Its AVT-14 case also reads a card's covered top. |
| `f3cbe40` | AVT-09's named test split so every function is ≤ 50 lines (assertions unchanged). |
| `13ae22b` | Flake fix. R13's limiter refills on the real clock, and one run under coverage let a 61st read through. A's two limit tests now freeze the limiter's clock. A scratch control at 50 ms a request failed the old test. |
| `01607e1` | A gateway ERROR on "Use this look" was R13's `ToolReply` at 422, with no `error` code. It is now `Refusal` `tool_error` in R13's own words. |

## 3. BRIEF-A, item by item

| BRIEF-A asks | Where | Proved by |
|---|---|---|
| The join: `build(ctx) -> WardrobePart("tryon", privacy=3 rows, services={"tryon_looks"}, ready=…)`; no tool, job or `data` | `part.py` | `test_r131_a_part.py` (I0's real `check_part` and `build_parts`; C reads the service late) |
| No store or no keyring: "Off: …" in words, nothing in clear, the rows still answer for what is on disk | `part.off_words`, `kept.stand_ins` | `test_off_says_why_in_words_…`, `test_off_with_no_key_the_rows_are_the_stand_ins_and_still_delete_by_path`, `test_off_says_so_in_the_parts_own_words` |
| `tryon/{uid}` sealed (`tryon`, `aad_tryon`), plain `owner` and `updated_at`, ≤ 200 KB sealed; an unreadable one never overwritten | `store.py` | `test_r131_a_store.py` (11) |
| Measurements, one draft, ≤ 5 earlier, `typed`, `at`; `assets`; `saved` ≤ 10 | `store.TryonDoc` | `test_the_document_bounds_its_lists` |
| His figure preferences | not built | see section 9 (the contract has no field or route for them) |
| Six whole-cm values in `model.RANGES`, refused with `range_words` (422 `Refusal`); untyped estimated; `BodyView.weights` | `versions.py`, `api/tryon.py` | `test_avt02_store_*`, `test_every_body_view_carries_the_engines_morph_weights_…`, `test_his_measurements_are_refused_in_words_…` |
| `PUT /body`, `POST /body/use`, `DELETE /body/draft`, each `record_change` (a hash, never the numbers) | `api/tryon.py` `_audit` | `test_his_measurements_are_refused_in_words_and_never_reach_the_audit` (the exact hashes of the field names), `test_r131_a_needles.py` |
| Saved selections never change with a version | `versions.py` | `test_avt03_…` (named), `test_avt03_a_new_version_never_touches_saved_selections_or_figure_choices` |
| The look by `?plan=`, `?day=&alt=`, `?pieces=` (each re-read; not his → 422 in words; a private slot covered), `&private=1` | `looks.py` | `test_r131_a_looks.py`, `test_the_look_route_refuses_in_words` |
| Each `LookSlot`: template (his, else the table's), variants, `rgb`, pattern, texture view (detail, else front) and photo, views kept and USEFUL missing, readiness from a FRESH read, `approximate`, `card_only`, `removable`, ≤ 12 options | `looks.slot_of`, `options.py` | `test_a_plans_look_is_r13s_answer_slot_by_slot`, `test_avt04_views_*`, `test_avt05_assets_*`, `test_a_slot_offers_at_most_twelve_options`, `test_a_slot_shows_its_fresh_readiness_and_options` |
| Readiness words: `READY`, `DRAFT_WORDS[state]`, `reserved_words(…)`, `ONE_SHOE` | `options.readiness` | `test_r131_a_options.py` (state, one shoe, reserved, set, gone) |
| A private slot covered only; its piece and words only with `private=1` | `looks.covered`, `_covered_slot` | `test_avt14_looks_*`, `test_row388_a_private_piece_on_the_card_is_covered_unless_he_asks`, `test_a_private_basic_is_shown_only_when_he_asks` |
| Tuck default from the dress code, open by default | `looks.build` | `test_a_plans_look_is_r13s_answer_slot_by_slot` |
| "That plan isn't there any more" as a 404 `Refusal` | `looks.GONE_PLAN` | `test_the_look_route_refuses_in_words` |
| Assets: `PUT /v1/tryon/assets/{piece}` saved in `tryon/{uid}.assets`; same-slot template or card only; tidied on read | `assets.py` | `test_a_choice_of_the_same_slot_is_saved_against_the_piece_id`, `test_a_merged_away_or_purged_pieces_choice_is_dropped_on_read`, `test_figure_choices_refuse_in_words` |
| The confirm: fresh check BEFORE any tool call, 409 in words; then ONE `run_panel_tool(…, "outfit_plan", {"action": "lock", "plan", "pieces"})`; `panel_reply(run)` | `confirm.py`, `api/tryon.confirm_look` | `test_r131_a_confirm.py`, `test_avt09_…` (named, with the race) |
| Saved comparisons: GET/POST, GET/DELETE by id; ≤ 10; re-checked on every GET | `saved.py` | `test_avt11_saved_*`, `test_saved_comparisons_over_http` |
| `tryon_looks` service: `look(uid, plan) -> TryonLook`, fresh | `TryonService.look` | `test_the_service_is_the_tryon_looks_port_for_c` |
| Privacy rows with `kept.SPECS` words; OPS-05 through `PrivacyService` (passkey, IRREVERSIBLE audit); `erase_all`: C's half, else by path, `tryon/{uid}` LAST; spend kept; catalog untouched; `kept.BACKUP_WORDS` | `privacy.py`, `erase.py` | `test_r131_a_privacy.py`, `test_ops05_…` (named) |
| Every route: exactly the `tryon` rows, owner-only, `no-store`, 30 changes and 60 reads a minute, `Refusal` | `api/tryon.py` | `test_the_router_has_exactly_the_contracts_tryon_rows_…`, `test_without_his_sign_in_every_route_is_refused`, `test_every_answer_is_no_store_and_matches_its_model`, the two limit tests, `test_a_tool_error_on_the_one_call_is_a_refusal_in_r13s_words` |
| His measurements never in a tool result, a log, an alert, the audit's text, Google or the R13 wardrobe backup | everywhere | `test_r131_a_needles.py`. There is no alert or Google call in A. R13's backup (`catalog/backup.py`) streams only the catalog's own records, never `tryon/{uid}`. |
| Rows' named tests, `test_avt02_store_*`, `test_avt11_saved_*`, `test_avt14_looks_*` | tests | section 4 |
| The `looks` eval, BUILT, every control failing its case | `evals/r13_1/looks.py` | section 5 |
| No new tool, permission row, alert kind, job, secret or collection; never `data`; no shared file | — | `git diff --stat eb8b7e4..HEAD` names only A's files; the part test asserts no tool, job or `data` |
| Fixed clocks; bare unique fakes | tests | `r131_fakes.NOW` everywhere; the limiter's clock frozen; `r131_fakes_a.py` |

## 4. His rows and their named tests

| Row · ID | Named test | Proved through |
|---|---|---|
| 354 · AVT-03 | `test_avt03_correcting_height_reshapes_the_figure_and_keeps_every_saved_selection` | the routes: 172 → 178 is a draft, the current stays until Use, the untyped are "estimated" (typed is only `height`), the weights move; the plan's look and the saved comparison are byte-identical before and after. B proves 178 ± 0.5 cm. |
| 355 · AVT-04 | `test_avt04_a_kurta_shows_its_front_and_back_references_under_its_own_id` | `?pieces=`: views `("front", "back")` under the catalog's own `wi_` id; with a front only, `missing == ("back",)` and it stays selectable |
| 356 · AVT-05 | `test_avt05_a_patterned_shirt_draws_on_an_approximate_shape_beside_its_real_photo` | the striped shirt: template `shirt` saved in `tryon/{uid}.assets` (read back by a fresh service), texture from its own `detail` crop, "template" approximate, its front kept; a tie is card only |
| 360 · AVT-09 | `test_avt09_a_ready_jacket_swaps_figure_and_checklist_together_and_one_in_laundry_stays_a_draft` | the swap changes the outer slot's piece, template and words; In laundry → "Draft: in the laundry"; the confirm is 409 in words with NO `outfit_plan` call; the race is refused by `outfit_plan` itself (D20), the plan unchanged, ≤ 1 card; a ready jacket is one lock of every slot |
| 350 · OPS-05 | `test_ops05_deleting_the_figure_empties_the_viewer_disables_previews_and_keeps_the_catalog` | `PrivacyService.delete` of `tryon_all`: 5 documents. The viewer then says `NO_FIGURE` (no versions, choices or saved). C's pictures, garment photo, photo and YES are gone and its erase was called. The spend is kept. `GET /v1/wardrobe` returns the same pieces and `rev`; the crops are untouched. |
| 353 · AVT-02 (A's half) | `test_avt02_store_*` (8) | `test_r131_a_versions.py` |
| 362 · AVT-11 (A's half) | `test_avt11_saved_*` (9) | `test_r131_a_saved.py` |
| 365 · AVT-14 (A's half) | `test_avt14_looks_*` (3) | `test_r131_a_looks.py` (no private id, colour, photo or label anywhere in any look, option or gap) |

## 5. The `looks` eval and its controls

There are 9 cases: AVT-03, AVT-04, AVT-05, AVT-09's fresh check (the draft offered, the 409, no
call), AVT-09's race, AVT-11, AVT-14 (with a card's covered top), OPS-05's order and `rev`, and
D20's `lock`/`reserve`. Each runs on A's real part and routes over R13's real styling, store and
gateway. Each control below turns its own case red, for its own reason:

| Control | Its case | Why it fails |
|---|---|---|
| the private filter off (`looks.covered` → False) | AVT-14 | the vest's and the underwear's ids served; the private slots drawn |
| the fresh check off (`confirm.first_draft` → None) | AVT-09 fresh check | "not refused in words: 200"; an `outfit_plan` call for a draft |
| `lock` without D20 (`styling.actions.unready` → None) | AVT-09 race | `outfit_plan` took the jacket; the plan changed |
| the same | D20 | `lock` and `reserve` took a blazer in the laundry |
| M8 AVT-03: a new version rewrites saved piece ids | AVT-03 | "a saved comparison's piece ids changed with the version" |
| M8 AVT-04: the look drops the `back` view | AVT-04 | the kurta's views `('front',)` |
| M8 AVT-05: the choice kept in page memory only | AVT-05 | not in `tryon/{uid}.assets`; not drawn from its own crop |
| M8 OPS-05: the erase also deletes the wardrobe's photos | OPS-05 | "the wardrobe catalog changed" |

AVT-09's own M8 control is "`lock` without D20's check", which is the race control above. AVT-11's
and AVT-14's sharing controls belong to B and D.

## 6. The checks (head `01607e1`)

These ran one at a time, the heavier ones behind the shared lock.

| Check | Result |
|---|---|
| A's tests `tests/test_r131_a_*.py` (11 files, 147 cases), Python 3.12 | **147 passed** |
| the same, Python 3.11 | **147 passed** |
| coverage of A's 11 modules (3.12) | **97.8 %** (1,000 statements, 22 missed); each module 95–100 % |
| areas A touches (41 files: every `test_r131_*`, `test_r13_seams`, `test_r13_wiring`, every `test_r13_c_*`, `test_r13_a_routes`, every `test_privacy_*`), 3.12 | **1,043 passed, 2 failed**: the two I0 stub pins A moves (section 8.1) |
| the same, 3.11 | **1,043 passed, 2 failed** (the same two) |
| the two pins with the diff of section 8.1 applied (a scratch copy) | 23 passed (the whole file) |
| `evals/r13_1/run.py --mock --part looks`, 3.11 and 3.12 | **9/9 passed; the negative control failed the suite** (each of the 8 for its own reason) |
| `evals/r13_1/run.py --mock` (all parts; stubs pass until I1) | **31/31 passed**; the controls failed the suite |
| `ruff check` and `ruff format --check`, the 24 Python files changed since `eb8b7e4` | clean |
| `mypy src` | the baseline error only (`memory/redis_store.py:67`); A's 11 modules clean |
| `scripts/arch_coverage.py` | OK, 115 Firestore collections. I0 counted 114; the new one is `tryon`, the planned `tryon/{uid}` (`ports.COLLECTIONS`), now named in A's code. A adds no collection. |
| `scripts/check_doc_versions.py` | all 30 documents OK |
| static: no `datetime.now(` / `date.today(` / `time.time(` / `utcnow` in A's files; no `$` in A's words; every function ≤ 50 lines; every module ≤ 400 | clean |

## 7. What C and D get from A

### 7.1 `GET /v1/tryon`

The reply has these fields:

- `part` "tryon"; `ready` "ready" (or the part's "Off: …" words in a 503 `off`);
- `release` "m1"; `files`: the GLB files that pass the mannequin manifest's check, `body.glb`
  first. The list is empty until B's `MANIFEST.json` ships;
- `body` {`current`, `draft`, `earlier` ≤ 5}, each a `BodyView` with `typed` and `weights`;
- `ranges` (six, with `words` such as "The figure can be 150 to 195 cm tall");
- `assets`: his choices for live, non-private pieces. There are none while R13's records can't
  be read;
- `saved` refs (`draft` true when one can't be checked now);
- `words`: "No figure yet: type your measurements." until there is a version, then "Estimated
  from your measurements".

### 7.2 The look A serves for the pilot

This is `GET /v1/tryon/look?plan=` for the pilot's meeting plan tomorrow, `r131_fakes_a` at
`NOW`. Top level: `day` 2026-11-18, `dress_code` business_formal, `tucked` true, `open` true,
`layers` all, `gaps` []. The pilot's plan pieces have no photos, so `texture_view`, `photo` and
`views` are empty and `approximate` is template/colour:

| slot | piece | words | template | variants | rgb | missing | readiness | approximate | removable | options |
|---|---|---|---|---|---|---|---|---|---|---|
| `top` | `wi_000000000002` | a white shirt | shirt | tucked/untucked | 240,240,236 | front/back | Ready | template/colour | no | 5 |
| `bottom` | `wi_000000000005` | charcoal trousers | trousers | - | 64,66,70 | front | Ready | template/colour | no | 4 |
| `shoes` | `wi_000000000010` | a pair of brown dress shoes | shoe | - | 110,75,50 | front | Ready | template/colour | no | 2 |
| `socks` | `wi_00000000000c` | a pair of black socks | socks | - | 28,28,30 | front | Ready | template/colour | yes | 2 |
| `belt` | `wi_0000000000b1` | a brown belt | belt | - | 110,75,50 | front | Ready | template/colour | yes | 2 |
| `watch` | `wi_000000000015` | a grey watch | watch | - | 140,140,144 | front | Ready | template/colour | yes | 2 |
| `outer` | `wi_000000000017` | a charcoal blazer | jacket | open/closed | 64,66,70 | front/back | Ready | template/colour | yes | 2 |
| `base` | none | Base layer (covered) | none | - | null | - | Ready | - | no | 0 |
| `underwear` | none | Base layer (covered) | none | - | null | - | Ready | - | no | 0 |

A piece with photos, the kurta by `?pieces=top:wi_000000000007` (options cut to two):

```json
{"slot": "top", "piece": "wi_000000000007", "words": "a beige kurta", "private": false,
 "template": "kurta", "variants": ["knee"], "rgb": [215, 200, 170], "pattern": null,
 "texture_view": "front", "photo": "wh_00000000a001", "views": ["front", "back"], "missing": [],
 "readiness": "Ready", "eligible": true, "approximate": ["template", "texture"],
 "card_only": false, "removable": false,
 "options": [{"piece": "wi_000000000007", "words": "a beige kurta", "readiness": "Ready",
              "eligible": true, "photo": "wh_00000000a001", "template": "kurta"},
             {"piece": "wi_000000000001", "words": "a light blue shirt", "readiness": "Ready",
              "eligible": true, "photo": null, "template": "shirt"}]}
```

### 7.3 The look's rules (D draws them; C sends from them)

- **Covered.** A slot is covered when it is `base` or `underwear`, or when it holds a private or
  missing piece. It then has `private: true` and `words` "Base layer (covered)", no `piece`, and
  no template, `rgb`, pattern, photo or option.
  - Its `readiness` IS served. These are fixed words (for example "Draft: in the laundry"), never
    the piece's label, colour or id, so his checklist can say a basic isn't ready.
  - With `&private=1` (his "Show private basics"), the covered slot adds its `piece` and R13's
    private words ("a black vest"). It is still never drawn.
- **`?pieces=`.** The format is `slot:wi_…` for each piece; a pair repeats its slot
  (`shoes:wi_a,shoes:wi_b`); a slot the card covers is `slot:` with no id, for ANY of R13's slots
  (I0's card does this for a top he made private). The card's `plan`, `day` and `code` may come
  as `&plan=`, `&day=` and `&code=`. These are refused as 422 `not_a_piece`, with words:
  - a piece that isn't his any more;
  - a piece in another slot's place;
  - two pieces in one slot (unless they are a pair);
  - an unknown slot;
  - a covered slot listed twice or with an id;
  - more than 24 entries.
- **`approximate`.** It holds `template` whenever a shape is drawn; with it, `texture` when a crop
  textures it, else `colour` (an untextured colour). It is empty for an image card only
  (`card_only: true`, `template: null`).
- **The texture crop.** `photo` is the texture crop: his chosen `texture_view` if kept, else
  `detail`, else `front`. It is NOT always the front crop. `views` lists the views kept and
  `missing` the useful ones not kept (front for every garment, back for tops, outerwear and
  traditional; `model.useful_views`).
- **Colour.** `rgb` is `model.rgb_of(colour)`. A piece with no colour gets `model.NO_COLOUR_RGB`
  (128, 128, 128); see section 8.3.
- **Options.** The current pick comes first, then the ready ones, then the drafts; at most 12. A
  pair is offered once, by its first side. Each option has its readiness, its first photo (the
  thumbnail) and his template.
- **Gaps.** These are R13's gaps. One that names a private piece's id becomes "A private basic
  isn't ready: see Helpers, Wardrobe."

### 7.4 Readiness words

| Words | When |
|---|---|
| `Ready` | the piece is eligible now |
| `DRAFT_WORDS` | the piece's state, for example "Draft: in the laundry" (in laundry, washing or drying), "Draft: needs pressing", "Draft: at the laundry shop", "Draft: in use", "Draft: needs a repair", "Draft: needs a quick check", "Draft: archived" |
| `Draft: one shoe missing` | one side of a pair isn't ready |
| `Draft: reserved for {R13's event words}` | for example "Draft: reserved for your 18:00 event": another plan holds the piece against this look's day |
| `Draft: worn only with its set, which isn't ready` | a set part that can't be worn alone |
| `Draft: no longer in your wardrobe` | merged away or purged |
| `Draft: not ready` | any other state (a fallback) |

### 7.5 Refusals (`{"error", "detail"}`, `Cache-Control: no-store`)

Every route can also answer `401`, and `429 rate_limited` "Too many requests; wait a minute.".

| Route | Status · code |
|---|---|
| `GET /v1/tryon` | 503 `off` (the part's Off words) · 503 `unreadable` (the key changed) |
| `PUT /v1/tryon/body` | 422 `out_of_range` (`model.range_words`) · 422 `nothing_typed` · 422 `bad_request` · 422 `full` · 503 `off` / `unavailable` |
| `POST /body/use` · `DELETE /body/draft` | 404 `no_draft` · 503 |
| `GET /v1/tryon/look` | 404 `gone` ("That plan isn't there any more.", or an `alt` that isn't there) · 422 `bad_day` · 422 `not_a_piece` · 422 `bad_request` (`alt` not 0–2, a value over 1,000 characters) · 503 `off` (R13's own words when styling is off) |
| `PUT /v1/tryon/assets/{piece}` | 404 `not_in` · 422 `wrong_shape` (a private piece, another slot's shape, both a shape and card only, a type with no template) · 422 `bad_request` / `off` |
| `POST /v1/tryon/confirm` | 409 `draft` ("The navy jacket is in the laundry: it can't be confirmed for this event.") · 404 `gone` · 422 `not_a_look` · 422 `bad_request` · 404 `unavailable` (no gateway or tool) · 422 `no_conversation` · 422 `tool_error` (the gateway's error, in R13's words) · 422 `off` |
| `GET/POST /v1/tryon/saved` | 409 `too_many` ("You keep at most 10 comparisons: delete one first.") · 422 `not_a_look` · 422 `bad_request` · 503 |
| `GET/DELETE /v1/tryon/saved/{id}` | 404 `gone` ("That comparison isn't there any more.") |

**"Use this look" when it passes the fresh check** answers R13's `ToolReply` (200):

- `status` `executed`;
- `needs_approval` with `approval_id` and `session_id` (the card waits in his conversation);
- or `denied`.

**The race (D20)** is a 200 `executed` whose `result.refused` is true and whose `message` is
R13's words ("The navy jacket is in the laundry: it can't be locked into this plan."). D must show
that message and not report success.

### 7.6 For C

`ports.looks_service(ctx).look(uid, plan)` is the same `TryonLook`, read fresh.

- It raises `looks.NoLook` (the plan is gone) or `looks.StylingOff` (R13 off or not ready; its
  words).
- A slot C may send is one with `private: false`, a `template` in `model.GARMENTS`, and `"front"`
  in `views`.
- The FRONT crop's photo id is in the slot only when `texture_view == "front"`. Section 8.2's
  `refs` gives it always.

## 8. Needs I1

### 8.1 Two I0 stub pins that A's built part moves (`tests/test_r131_wiring.py`)

The two pins say "not built" and "404 stub routers at I0". With A built and no keyring there,
`tryon` is "Off: JARVIS has no token key to seal your measurements." and `GET /v1/tryon` is a 503
`off`. Verified on a scratch copy: 23 passed, and the diff is ruff-clean. The `seeme` line
changes again when C merges (INTEGRATION-C):

```diff
@@ -27,6 +27,7 @@
 from jarvis.storage.docs import MemoryDocs, Set
 from jarvis.wardrobe.ports import NOT_BUILT, PARTS, WardrobeContext, WardrobePart
 from jarvis.wardrobe.tryon import kept
+from jarvis.wardrobe.tryon import part as tryon_part
 
 UID = "owner-r131"
 
@@ -76,7 +77,8 @@
     parts = wiring.build_parts(_ctx(settings, MemoryDocs()))
     assert tuple(parts) == PARTS and PARTS[-2:] == ("tryon", "seeme")
-    assert parts["tryon"].ready == parts["seeme"].ready == NOT_BUILT
+    assert parts["tryon"].ready == tryon_part.OFF_NO_KEY  # A built; no keyring: Off in words
+    assert parts["seeme"].ready == NOT_BUILT
@@ -286,7 +288,9 @@
         assert body["parts"][-1] == {"part": "seeme", "ready": NOT_BUILT}
-        assert (await c.get("/v1/tryon", headers=AUTH)).status_code == 404  # stub routers at I0
+        off = await c.get("/v1/tryon", headers=AUTH)  # A's routes; this app has no keyring
+        assert off.status_code == 503
+        assert off.json() == {"error": "off", "detail": tryon_part.OFF_NO_KEY}
         assert (await c.get("/v1/tryon")).status_code in (401, 404)
```

### 8.2 A contract gap: each kept view's photo id (AVT-04's two reference cards; C's front crop)

`LookSlot` names the views kept (`views`) but carries only ONE photo id: the texture crop. D's
`test_avt04_cards_*` ("both reference cards") can't show a front AND a back card with their ids,
and R13's `PieceView.photos` does not say which photo is which view. C needs the front crop's id
too. I propose this one field (in `wardrobe/tryon/http_figure.py`; A's line and the fake
server's line come with it):

```diff
--- a/src/jarvis/wardrobe/tryon/http_figure.py
+++ b/src/jarvis/wardrobe/tryon/http_figure.py
@@ class LookSlot(_M):
     views: tuple[View, ...] = ()  # the views kept
+    refs: tuple[tuple[View, PhotoId], ...] = ()  # (view, crop): AVT-04's reference cards
     missing: tuple[View, ...] = ()  # a useful view not kept yet (AVT-04)
--- a/src/jarvis/wardrobe/tryon/looks.py
+++ b/src/jarvis/wardrobe/tryon/looks.py
@@ def slot_of(
         views=tuple(v for v in VIEWS if v in kept),
+        refs=tuple((v, kept[v]) for v in VIEWS if v in kept),
--- a/tests/r131_fake_server.py
+++ b/tests/r131_fake_server.py
@@ def look_slot(
         views=views,
+        refs=tuple((VIEW_OF[x], x) for x in p.photos if x in VIEW_OF),
```

A covered slot keeps `refs` empty (a private piece has no photo). Add `refs` to AVT-04's named
test (`kurta.refs == (("front", "wh_…a001"), ("back", "wh_…a002"))`) and to the AVT-04 control.

### 8.3 "no colour set" (D5) has no signal in the contract

The brief says `rgb` is `model.rgb_of` with "no colour set" when there is none; A serves
`NO_COLOUR_RGB`. D can say "no colour set" only by keeping a copy of (128, 128, 128), which the one
source rule forbids. I1 can choose either of these:

- (a) A serves `rgb: null` for a drawn piece with no colour. BRIEF-B already draws null as
  mid-grey, and D shows "no colour set" for a drawn slot whose `rgb` is null. This is one line in
  `looks.slot_of`, `rgb=rgb_of(p.colour) if p.colour else None`, and the same in the fake server.
- (b) A field `no_colour: bool` on `LookSlot`.

I left it as the brief says (a) would change what B and D build against.

### 8.4 The `tryon_figure` export and I1's `needles` suite

D16 gives `tryon_figure` "count, export, delete with a confirm". The export carries his
measurements: his own data, as R13's pieces row carries his labels. It is not passkey-gated (a
"confirm" row), but `GET /v1/tryon` shows the same numbers to the same session.

The plan's `needles` suite lists "his measurements (numbers and words)" with "the Privacy export"
among its sinks. I1 decides:

- either the needles sink skips the owner's own `tryon_figure` export, as it must already skip
  R13's own labels;
- or the export says when and which were typed, never the numbers:

```diff
--- a/src/jarvis/wardrobe/tryon/privacy.py
+++ b/src/jarvis/wardrobe/tryon/privacy.py
@@ def export_of(doc: TryonDoc) -> dict[str, Any]:
-    def body(b: Any) -> Any:
-        return b.model_dump(mode="json") if b is not None else None
+    def body(b: Any) -> Any:  # when and which were typed: never the numbers (I1's needles)
+        return {"at": b.at.isoformat(), "typed": list(b.typed)} if b is not None else None
```

With the second choice, `test_the_figure_row_counts_exports_and_deletes_with_a_confirm` moves
with it.

### 8.5 The fresh-context reviews

BRIEF-A requires `security-reviewer` (OPS-05, the confirm path), and BRIEF-COMMON requires
`code-reviewer` and `python-reviewer`. The first builder's commits say "From A's own review" (in
its own context). This builder's session had no way to start another agent, so no fresh-context
review of Part A was run. I did my own pass instead; it found and fixed the three bugs of
section 2.

**I1 must run all three reviewers on A's files before the PR.** The points to look at:

- the confirm: owner scope, `context_trust(untrusted=False)`, one call, and no `console_only`
  (none is planned for `tryon`);
- `tryon_all`'s passkey row and its erase order;
- that `?private=1` is the owner's alone;
- the sealed document's AAD and 200 KB cap.

### 8.6 The fake server and A differ (D's browser tests move to the wired app at I1)

`tests/r131_fake_server.py` is I0's, and it differs from A in four ways:

- with `private=1`, a covered slot keeps `words` "Base layer (covered)" (A says R13's private
  words);
- `approximate` has no `colour` for an untextured piece;
- an id-less `slot:` entry is refused (A takes it for any of R13's slots);
- options are not ordered current-first.

D's tests of these UI halves should be checked on the wired app.

## 9. Deviations from the plan or the brief, with reasons

- **No "figure preferences" in `tryon/{uid}`.** The data model names them, but the HTTP contract
  has no field or route that reads or writes them. Tuck, open and layers live per look and per
  saved comparison; the view and undo are page memory (D7). A field nothing reads would be dead
  (YAGNI). It is one optional field on `TryonDoc` when a route needs it.
- **The wardrobe view for a look** comes from R13's styling service (`Styling.view`, the same
  store `ctx.store()` returns), so the look and the engine read one view. The figure-choice route
  reads `ctx.store()`.
- **A covered slot's readiness is served** (fixed words only), as section 7.3 explains.
- **An id-less `slot:` is accepted for any of R13's slots, not only `base`/`underwear`.** I0's card
  covers a slot holding a private piece that way (section 2, `8e598ab`).
- **`GET /v1/tryon` lists no figure choice while R13's records can't be read** (AVT-14; the choices
  stay kept).
- **A gateway error on "Use this look" is a `Refusal` `tool_error`, not R13's `ToolReply` at 422.**
  BRIEF-A says "`Refusal` on every refusal". Executed, a card and denied stay R13's `ToolReply`, as
  `panel_reply` makes them.
- **The watch's strap** is drawn from its colour (BRIEF-B's words). The plan's "from its `strap`
  feature" (a material: leather, metal …) is not carried by the contract.
- **Not test-first** (said in each commit):
  - the part's join through I0's real wiring (the first builder);
  - the needles guard (it passed at once; its positive control fails it);
  - the frozen-limiter fix to two existing tests.

## 10. Known limits, and what could not be verified here

- **Browser and console.** The console, the figure and the browser tests are D's and B's. Nothing
  here drew a figure or ran a browser.
- **The figure's files.** `files` stays empty until B's mannequin `MANIFEST.json` is in the tree.
  B proves the 178 ± 0.5 cm shape.
- **Storage.** Only `MemoryDocs` was used. Real Firestore transactions and the sealed size on the
  real keyring's envelope are not measured here (the 200 KB guard is on the sealed string).
- **OPS-05's passkey.** It ran through `PrivacyService.delete` with the fresh sign-in fallback
  (`proof=None`, `fresh_left_s=60`), not a real WebAuthn passkey. The route and the console button
  are D's and I1's.
- **Photo reads.** A look reads each shown piece's photo documents one by one (at most 12 slots ×
  3 views = 36 small reads).
- **Rate limits.** They are R13's in-memory limiter, so they hold per instance.
- **R13's limiter clock.** It refills on the real clock, so any R13 or R13.1 limit test that
  doesn't freeze it can flake under load. I0's notes saw one in `test_voice_api.py`.

## Change log

| Version | Date | Release | What changed | By |
|---|---|---|---|---|
| v13.1.0 | 17 Nov 2026, 19:40 IST | R13.1 | The plan section, before any code | 🛠 Mark XXIII |
| v13.1.1 | 17 Nov 2026, 20:05 IST | R13.1 | Current, at the end of Part A. It records: what was built (files with line counts, the second builder's eight commits); BRIEF-A item by item; the rows' named tests; the eval's 9 cases and 8 controls; the checks with their numbers; what C and D get (the pilot's look, the look's rules, readiness words, refusals per route, the race's reply); Needs I1 (the two wiring pins, a `refs` field for AVT-04, "no colour set", the export against the needles suite, the fresh-context reviews, the fake server's differences); deviations; known limits | 🛠 Mark XXIII |
