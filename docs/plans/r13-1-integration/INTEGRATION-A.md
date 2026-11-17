Version v13.1.2 · 17 Nov 2026, 21:50 IST · Release R13.1 · Status: Current · Owner: 🛠 Mark XXIII

# R13.1 Part A: Try-on data (AVT-03, AVT-04, AVT-05, AVT-09, AVT-11, AVT-14, OPS-05)

This is builder A's report for I1. Branch `r13-1-a`, cut from `r13-1-i0` @ `eb8b7e4`. It is built
against these documents (review A-1's fixes, and what changed for C, D and I1, are in section 11):

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
 "texture_view": "front", "photo": "wh_00000000a001", "views": ["front", "back"],
 "refs": [{"view": "front", "photo": "wh_00000000a001"}, {"view": "back", "photo": "wh_00000000a002"}],
 "missing": [],
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
  - A reply card's covered slot (`slot:` with no id) reads, when the card carries `&plan=`, the
    piece that plan holds there: its readiness is real, and `&private=1` names it. It stays
    covered whatever that piece is now. With no plan its readiness is `looks.UNCHECKED`, "Not
    checked here" (review A-1 F6).
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
- **Reference cards (AVT-04).** `refs` names each kept crop, `[{"view", "photo"}]`, in the order
  front, back, detail; empty on a covered slot. It is built from the same map as `views`, so the
  two never disagree. D's front and back cards and C's front crop come from it.
- **Colour.** `rgb` is `model.rgb_of(colour)`. A drawn piece with no colour has `rgb: null`: B
  draws it mid-grey, and D says "no colour set" for a slot with a `template`, not `private`, whose
  `rgb` is null (section 8.3, chosen at review A-1).
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

Every route can also answer `401`, `429 rate_limited` "Too many requests; wait a minute.", and
`500 internal` "Something went wrong inside JARVIS. Try again later." (a bug: logged at ERROR with
where it happened, never its message). Off, unreadable and storage trouble are 503 on every route
(review A-1 F5). Every route with a body answers a body over 16 KB with `413 too_large` "That
request is too big." before reading it (F8).

| Route | Status · code |
|---|---|
| `GET /v1/tryon` | 503 `off` (the part's Off words) · 503 `unreadable` ("Your try-on data can't be opened on this server. Nothing was changed; ...") · 503 `unavailable` |
| `PUT /v1/tryon/body` | 422 `out_of_range` (`model.range_words`) · 422 `not_whole` ("Type each measurement in whole centimetres, for example 172.": "172", 172.0, 172.5, true) · 422 `nothing_typed` · 422 `bad_request` · 422 `full` · 413 · 503 `off` / `unavailable` |
| `POST /body/use?at=<draft.at>` | 404 `no_draft` · 409 `changed` (the draft isn't the one he saw: "Your new measurements changed on another screen: check them, then press Use again.") · 422 `bad_request` (an `at` that isn't a time with its zone) · 503. Without `at`, the draft is used as before (F7). |
| `DELETE /body/draft` | 404 `no_draft` · 503 |
| `GET /v1/tryon/look` | 404 `gone` ("That plan isn't there any more.", or an `alt` that isn't there) · 422 `bad_day` · 422 `not_a_piece` · 422 `bad_request` (`alt` not 0–2, a value over 1,000 characters) · 503 `off` (R13's own words when styling is off) / `unavailable` |
| `PUT /v1/tryon/assets/{piece}` | 404 `not_in` · 422 `wrong_shape` (a private piece, another slot's shape, both a shape and card only, a type with no template) · 422 `bad_request` · 413 · 503 `off` / `unavailable` |
| `POST /v1/tryon/confirm` | 409 `draft` ("The navy jacket is in the laundry: it can't be confirmed for this event.") · 409 `left_out` ("This plan can't leave out its watch yet: put the watch back on the figure to use this look for it.") · 409 `refused` (`outfit_plan`'s own refusal, R13's words) · 404 `gone` · 404 `unavailable` (no gateway or tool) · 422 `not_a_look` · 422 `bad_request` · 422 `no_conversation` · 422 `tool_error` (the gateway's error, in R13's words) · 413 · 503 `off` / `unavailable` |
| `GET/POST /v1/tryon/saved` | 409 `too_many` ("You keep at most 10 comparisons: delete one first.") · 422 `not_a_look` · 422 `bad_request` · 413 (POST) · 503 |
| `GET/DELETE /v1/tryon/saved/{id}` | 404 `gone` ("That comparison isn't there any more.") · 503 `off` / `unavailable` |

**"Use this look" when it passes the fresh check** answers R13's `ToolReply` (200):

- `status` `executed`;
- `needs_approval` with `approval_id` and `session_id` (the card waits in his conversation);
- or `denied`.

**The race (D20), and any refusal by `outfit_plan` itself** ("That plan changed meanwhile: try
again.", ...) is `409 refused` with R13's words as `detail` ("The navy jacket is in the laundry:
it can't be locked into this plan."), never a 200 (review A-1 F1). The fake server answers it the
same way for a confirm of `r131_fake_server.RACE_PLAN`, or when its state's `refuse` is set.

**A look that leaves out a removable slot the plan's look holds** (D7's Remove: outer, belt,
watch, socks) is `409 left_out`, before any call: R13's plans can't keep a slot empty (section
11, F2). The console sends every slot it shows (a covered slot has no id and is never asked for).

### 7.6 For C

`ports.looks_service(ctx).look(uid, plan)` is the same `TryonLook`, read fresh.

- It raises `looks.NoLook` (the plan is gone) or `looks.StylingOff` (R13 off or not ready; its
  words).
- A slot C may send is one with `private: false`, a `template` in `model.GARMENTS`, and `"front"`
  in `views`.
- The FRONT crop's photo id is the `refs` entry whose `view` is `front` (the slot's `photo` is the
  texture's crop, which may be `detail`).

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

**Done at review A-1 (`d1deaf2`), as named pairs `RefCard {view, photo}`, not the 2-tuples below.**

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

**Done at review A-1 (`c604823`): choice (a), `rgb: null`.**

The brief says `rgb` is `model.rgb_of` with "no colour set" when there is none; A serves
`NO_COLOUR_RGB`. D can say "no colour set" only by keeping a copy of (128, 128, 128), which the one
source rule forbids. I1 can choose either of these:

- (a) A serves `rgb: null` for a drawn piece with no colour. BRIEF-B already draws null as
  mid-grey, and D shows "no colour set" for a drawn slot whose `rgb` is null. This is one line in
  `looks.slot_of`, `rgb=rgb_of(p.colour) if p.colour else None`, and the same in the fake server.
- (b) A field `no_colour: bool` on `LookSlot`.

I left it as the brief says (a) would change what B and D build against.

### 8.4 The `tryon_figure` export and I1's `needles` suite

**Decided at review A-1 (`fc19a86`): the export keeps his numbers (the first choice below); the
needles rule is in section 11.**

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

## 11. Fix (review A-1)

The fixer of review A-1 (`REVIEW-A-1.md` v13.1.1, made at `08d4ed0`) worked on `r13-1-a` from
`1bc62fc`. Each finding was done test first: a failing test, seen red for its own reason, then the
fix, a commit, a push. The Workshop agreed the reviewer's recommendations on sections 8.2–8.4.

### 11.1 Each finding

| Finding | Outcome | Commits |
|---|---|---|
| F1 HIGH | **Fixed.** An EXECUTED result with `refused` is `409 refused`, R13's words as `detail`; `denied` stays R13's `ToolReply`. The fake server can send it (`RACE_PLAN`, or its state's `refuse`), and `test_r131_a_contract.py` pins the console-facing reply on both A's real race and the fake. The AVT-09 named test and the eval's race case pin `409 {"error": "refused", "detail": LOCK_REFUSED}`. | `2d5e992`, `5623f96` |
| F2 MEDIUM | **Fixed by the review's option (b), not (a)**: section 11.2. A look that leaves out a removable slot the plan's fresh look holds is `409 left_out`, before any call. | `0aa0ad7` |
| F3 MEDIUM | **Fixed.** `store.storage_trouble` and `store.where`. Storage trouble stays a warning and 503; anything else is `log.error` with `route`, `error` and `at` ("wardrobe/tryon/looks.py:327:build"), answered `500 internal`; never `str(exc)` or `exc_info`. `part._read` degrades on storage trouble only. | `8ee9cae` |
| F4 MEDIUM | **Fixed.** `test_avt14_looks_a_piece_made_private_is_never_another_slots_option` (red under the review's mutation, run as a scratch plugin outside the tree); the colour needle is `json.dumps(rgb_of("maroon"))`, "[110, 30, 40]"; the eval's AVT-14 case reads a top made private, and a control "options keep private pieces" turns it red. | `c53a26f` |
| F5 LOW | **Fixed.** 503 on the five rows; `down=` and the `down` parameter are gone. | `708be16` |
| F6 LOW | **Fixed.** A card's covered slot reads its plan's piece fresh (still covered); with no plan, "Not checked here". | `2224cb6` |
| F7 LOW | **Fixed**, with `at` optional (11.4). | `e41f4f4` |
| F8 LOW | **Fixed.** 16 KB cap, `413 too_large`, before any parse; `not_whole` for "172", 172.0, 172.5, true. `StrictInt` on `BodyIn` is left to I1 (A no longer depends on it). | `e904839` |
| F9 LOW | **A's half fixed**: count and export tidied against R13's view when it can be read; the row deletable whenever the document is on disk. I0's words are for I1 (11.4). | `4f5e6d7` |
| F10 LOW | **The words fixed** (no cause named). `Body` reading `extra="ignore"` is I0's (11.4). | `5d3c6f5` |
| F11 LOW | **Fixed.** A tenth control (`saved.look_view` answers Ready, never re-checked) turns the AVT-11 case red. | `b82dafc` |
| F12 LOW | **Not fixed here**: I1 with C (11.4). | none |
| 8.2 `refs` | **Done**, as `RefCard {view, photo}`, front, back, detail; empty when covered. | `d1deaf2` |
| 8.3 no colour | **Done**: `rgb: null`. | `c604823` |
| 8.4 export | **Kept** his numbers; A's needles guard states the rule (11.4, item 7). | `fc19a86` |
| Found while fixing | The needles guard flaked about once in a dozen runs: "93" (his waist) inside the random audit hash "...2b93d7...". Random hex is now masked before the numeric search, and each `args_hash` is checked to be a digest. | `8ee9cae` |
| Sizes | The eval (427) and the route tests (409) back under 400: `PlanCalls` in A's fakes replaces three copies of a call counter; the body tests move to `test_r131_a_bodies.py`. | `824cbb8` |

### 11.2 F2: why the refusal, not "release the removed slot"

The review's option (a) was to drop the removed slots' picks inside R13's `lock`. That cannot keep a
slot empty. R13's engine fills every slot of the dress code again on each read, both required
slots and optional ones that have a fitting piece. Probed on the fakes (the meeting plan,
business formal):

- a watch, outer layer, belt or socks pick dropped from the stored plan comes back in the plan's
  look as the same piece;
- R13's own `release` of the watch re-picks the same watch.

So after (a) the stored picks would lack the watch, but "Today and tomorrow", the figure by
`?plan=` and `outfit_plans` would still show it. That test would pass while the behaviour was
still wrong. A plan can't hold "no watch" without an R13 plan field and an engine change, and
R13's packages are not Part A's (BRIEF-COMMON section 3).

So A does (b): the confirm reads the plan's look as it is now, and refuses in words, before any
call, a look that leaves out a removable slot that look holds:

- "This plan can't leave out its watch yet: put the watch back on the figure to use this look for
  it." (the slot is named in R13's slot words);
- a covered slot (a private piece: no id to send) is never asked for;
- nor is a slot the plan's look doesn't hold now.

The screen therefore never says "used" while the plan keeps a watch. Remove still works on the
figure, in compare and in saved comparisons. The durable fix is 11.4, item 1.

### 11.3 Contract changes for I1 to check against B, C and D (I0's files, the smallest change)

- `wardrobe/tryon/http_figure.py` (+8): `class RefCard(_M): view: View; photo: PhotoId`, and
  `LookSlot.refs: tuple[RefCard, ...] = Field(default=(), max_length=3)`.
- `wardrobe/tryon/http.py` (+11 −7):
  - it re-exports `RefCard`;
  - it adds the aliases `_A = "/v1/tryon/assets/{piece}"` and `_B = (413, 422)`;
  - row errors: `PUT /body` +413; `POST /body/use` +409 +422; `PUT /assets/{piece}` +413 +503;
    `POST /confirm` +413 +503; `POST /saved` +413 +503; `GET/DELETE /saved/{id}` +503. Every
    `tryon` row now lists 503.
- `tests/r131_fake_server.py` (+21 −2):
  - `RACE_PLAN`, `FakeTryon.refuse` and `_race`: the confirm answers `409 refused`;
  - `look_slot` serves `refs` (in A's order) and `rgb: null` for no colour;
  - `use` honours `?at=` (`409 changed`).
- Unchanged: `ConfirmIn`, `BodyIn`, `LookSlot.rgb` (already optional).
- New refusal codes (the contract doesn't list codes): `refused`, `left_out` (confirm, 409),
  `changed` (body/use, 409), `not_whole` (body, 422), `too_large` (413), `internal` (500).

What each part needs:

- **D** must:
  - branch on those codes and show `detail`, and report success only on a 200;
  - send `?at=<draft.at>` with "Use these measurements";
  - draw AVT-04's cards from `refs`;
  - say "no colour set" for a drawn slot whose `rgb` is null;
  - send every slot it shows on "Use this look".
- **B**: nothing (null `rgb` is already mid-grey).
- **C**: take the front crop from `refs`.

### 11.4 For I1 (not done here, with reasons)

1. **F2's durable Remove** needs R13's packages, not A's. The smallest change:
   - `Plan.omit: tuple[str, ...]` (at most 4 slots; R13's sealed records ignore unknown fields,
     so a rollback still opens them);
   - `Ask.omit`, filled from it in `service.ask`, and `engine._slots` skips those slots;
   - `lock` with `pieces` takes `omit` (only `REMOVABLE_SLOTS`) in the same `s.change`, and
     `reserve.with_pick` clears a slot from `omit` when he picks one again;
   - `plan_schema` gains `omit`.

   Then `ConfirmIn.removed` replaces A's `left_out`, and R13's styling tests and evals must stay
   green.
2. **F7**: once D sends `?at=`, make it required (one line in `api/tryon._seen`).
3. **F8**: `BodyIn`'s fields may become `StrictInt` (optional now).
4. **F9** (I0's `kept.SPECS`): `tryon_all`'s unit is "documents", and its words gain "The month's
   Try-on spend (numbers only) stays 13 months for your monthly limit." (D16).
5. **F10** (I0's `model.Body`): read stored bodies with `extra="ignore"`, and keep `forbid` on
   `BodyIn`.
6. **F12**, with C:
   - C's picture write checks his YES again in the same transaction (it is gone after OPS-05)
     and drops the picture when it is gone;
   - the OPS-05 test gains a press that finishes after the erase.
7. **The `needles` suite** (`evals/r13_1/needles.py`, I1's stub):
   - his measurements are allowed only in `tryon_figure`'s export payload: the single export's
     `data` and `export_all`'s `categories.tryon_figure`;
   - they are allowed nowhere else: no other category, not `unavailable`, not the export's audit
     line, no log;
   - its positive control is the needle planted in another category's export, found;
   - `tests/test_r131_a_needles.py::outside_the_figure` is that rule, and I1 may reuse it;
   - a log record's `at` (`store.where`) is a code location: check it by its shape, not by
     numbers (a line number may equal one of his).
8. **Unchanged:** the two wiring pins of 8.1.
9. **I0's `fake_routes`** is 126 lines long (it was over 50 before A's +5). It is listed here and
   not refactored, because it is I0's file.
10. **The reviews of the fix:** this session could not start another agent, so the fix was not
    reviewed in a fresh context. I1 should run `security-reviewer` on F1 and F2 (the confirm
    path), and `code-reviewer` and `python-reviewer` on the fix.

### 11.5 The checks (code at `824cbb8`; one at a time, the heavier behind the shared lock)

| Check | Result |
|---|---|
| A's tests, `tests/test_r131_a_*.py` (13 files), Python 3.12 | **184 passed** |
| the same, Python 3.11 | **184 passed** |
| coverage of A's 11 modules (3.12) | **98.1 %** (1,119 statements, 21 missed); each 95–100 % (`looks.py` 95 %, `api/tryon.py` 99 %) |
| `evals/r13_1/run.py --mock --part looks`, 3.11 and 3.12 | **9/9 passed; the negative control failed the suite.** Each of the 10 controls turned its own case red for its own reason (each failure list printed and read). |
| the areas A touches (43 files: every `test_r131_*`, `test_r13_c_*`, `test_r13_a_routes`, every `test_privacy_*`, `test_r13_seams`, `test_r13_wiring`), 3.11 and 3.12 | **1,080 passed, 2 failed**: the two I0 pins of 8.1, as before |
| `ruff check` and `ruff format --check`, the 20 Python files changed since `1bc62fc` | clean |
| `mypy src/jarvis/wardrobe/tryon src/jarvis/api/tryon.py` | the baseline error only (`memory/redis_store.py:67`) |
| `scripts/arch_coverage.py` · `scripts/check_doc_versions.py` | OK, 115 collections · 30 documents OK |
| static checks: no real clock, no `$`, every function ≤ 50 lines, A's modules ≤ 400 | clean (largest: the eval at 391, `looks.py` at 380) |

### 11.6 Not test first (each commit says so)

- **Written with the code they pin** (their unit tests were red first):
  - the fake server's `refs` pin;
  - the `left_out` route pin.
- **Guards**, where the code already held:
  - F4's options test, red under a scratch mutation;
  - the needles allowance, with its positive control.
- **Controls:** the eval's new controls; a control's red is its test.
- **No assertion changed:** the `PlanCalls` and size refactor.

### 11.7 What could not be verified here

- D's console and how it handles the new codes;
- a browser;
- C's branch;
- real Firestore errors: they are classified by their module (`google.`), and tested only with a
  stand-in class;
- R13's engine with an `omit` field (11.4, item 1, not built).

## Change log

| Version | Date | Release | What changed | By |
|---|---|---|---|---|
| v13.1.0 | 17 Nov 2026, 19:40 IST | R13.1 | The plan section, before any code | 🛠 Mark XXIII |
| v13.1.1 | 17 Nov 2026, 20:05 IST | R13.1 | Current, at the end of Part A. It records: what was built (files with line counts, the second builder's eight commits); BRIEF-A item by item; the rows' named tests; the eval's 9 cases and 8 controls; the checks with their numbers; what C and D get (the pilot's look, the look's rules, readiness words, refusals per route, the race's reply); Needs I1 (the two wiring pins, a `refs` field for AVT-04, "no colour set", the export against the needles suite, the fresh-context reviews, the fake server's differences); deviations; known limits | 🛠 Mark XXIII |
| v13.1.2 | 17 Nov 2026, 21:50 IST | R13.1 | Section 11, the fix of review A-1: each finding's outcome and commits (F1 409 refused, and the fake server sends it; F2 a 409 left_out, with why not option (a); F3 bugs logged where they happened and answered 500; F4 AVT-14 pinned; F5 503 everywhere; F6 a card's covered slot readiness; F7 Use bound to the draft seen; F8 the 16 KB cap and whole centimetres; F9 A's half; F10 the words; F11 the AVT-11 control; F12 for I1), sections 8.2 to 8.4 done, the contract changes for I1 to check against B, C and D, what is left for I1, the checks with their numbers. Section 7's contract lines brought up to date (refs, rgb null, the refusals table, the race reply, C's front crop) | 🛠 Mark XXIII (fix A-1) |
