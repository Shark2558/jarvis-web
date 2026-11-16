Version v13.0.2 · 16 Nov 2026, 06:35 IST · Release R13 · Status: Current · Owner: 🛠 Mark XXI

# R13 — Part D: Phone and panel (INTEGRATION-D)

Built on branch `r13-d` from `r13-i0` @ `3bf2cb1` by the R13 Part D builder in the Workshop (🛠 Mark
XXI), against `docs/plans/r13-wardrobe.md` v13.0.2 Part D, `BRIEF-COMMON.md` and `I0-NOTES.md`. The
owner's "defaults OK" (15 Nov, 18:38 IST) stands: every safe default below is the plan's. v13.0.2 is the
fixer's pass on `REVIEW-D-1.md` (the fresh-context security and code review, verdict WARNING: 0
critical, 3 high, 6 medium, 10 low), test first: every fix below has a test that failed before it
(section 3). A second fresh-context review is still to run on this branch.

## 1. What D built, by use case and decision

| Plan item | What is built | Where |
|---|---|---|
| D8 the models | Face and person self-check references recorded (Node 22, the vendored onnxruntime-web 1.30.0, one thread): face, the top five face scores on the ramp over 1 x 3 x 240 x 320 (tolerance 0.002); person, SSD's one detection on a drawn silhouette (class 1, 0.9449, its box; tolerance 0.03), because SSD's own score floor gives no detection on the ramp. `scripts/wardrobe_assets.py manifest` writes MANIFEST.json from the pins without the network and refuses a vendored file that differs. The phone now also compares each model file's SHA-256 with the manifest's (`SUMS13`, L3) before it opens it. The fp32 fallback is not vendored: `embed`'s int8 self-check passes here | `scripts/wardrobe_assets.py`, `vendor/vision/r13-1/MANIFEST.json`, `console-vision.js` |
| D7-D9 the four tasks | `embed` (uint8 x 1,280, 1,708 base64, `mnv2-int8-1`), `colour` (Lab median of the box's centre, nearest of the 18 names, multicolour for two far clusters, naming the larger), `person` (SSD class 1 >= 0.5), `face` (UltraFace >= 0.7, NMS 0.3), all photo-only, registered before `sealRegistry()`; the I0 core's hash unchanged. Their plain arithmetic lives in `console-vision-r13.js` (REVIEW-D-1 split), imported by the R13 section on a wardrobe task's first use: a failed import is "could not load" for those four tasks only, never for R7's five. One runtime: the wake word's module URL and `env.wasm` (one thread, no proxy, its folder). Each `load()` checks the file's bytes, then runs its fixed input and compares with `SELF13`; a mismatch releases the session and is "not installed". Sessions are released on `pagehide` | `console-vision.js` Part B (532), `console-vision-r13.js` (128) |
| OPS-01, D5, D9 the phone checkpoints | Camera -> Wardrobe: Add pieces, To laundry, Back clean, Find, Read a label, as v13.0.1, with the review's fixes: the person and face checks run on the whole photo (they gate the card) AND on the exact crop at Save, Remember and the AI tag, whole and in four overlapping two-thirds so a small face is checked near full size (H2); a box that is the whole photo (no edges, or over 85 %) offers taps and matches only, and the card shows the exact crop before anything is sent (M2); a send keeps his list and refreshes it in the background (H1); a step change ends the camera and the label reader, and a live send or Cancel keeps the view and never offers the same label again (M1); the AI tag says the brain's own rupees or the true range and that a photo is sent (M3, L10); the bands never say "new?" (M5); A's tool shapes (M6); Front, Back or Detail (L7); the fingerprint's own model (L4). Its non-pixel words (his labels, the candidates, a care label's parse) live in `console-wardrobe-words.js`, imported on his first press | `console-wardrobe-scan.js` (596), `console-wardrobe-words.js` (83) |
| D1 Helpers -> Wardrobe | Needs a check, Today and tomorrow, Laundry, Pieces, Labels, Settings, from the frame's builders and existing classes; every change through `POST /v1/wardrobe/tools/{tool}`; the settings through their own routes (C's `PUT /v1/outfits/settings`; A's AI tagging through `PUT /v1/wardrobe/settings`, I1's route, M6), never a tool the model can call; the calendar list only on his press; the QR sheet and the sealed backup as downloads; restore checked first, then applied with the token | `console-helpers-wardrobe.js` (289), `console-wardrobe-pieces.js` (104) |
| D10 private pieces | Hidden in Helpers until "Show private basics" is tapped; otherwise "A private basic", with his printed label's number when there is one; no photo, fingerprint or AI tag ever offered for one | both modules |
| H2 AI tagging | Only with his setting on, the AI on (checked again at the press, L10), a saved piece that is not private, and a photo AND crop whose checks ran and found nobody; the rupees (the view's `tag_estimate_inr` when A sends it, else "about ₹0.01–₹0.51, depending on the brain") and the month's counter are shown before the press; refused when the month would pass its cap | `console-wardrobe-scan.js` `tagBox` |
| D1 the look | `console-wardrobe.css` (54 lines, no colour, font, radius or shadow literal) only places things, now also the card's crop (M2) | `console-wardrobe.css` |
| D20 the Privacy rows | Section "Wardrobe", four rows over every part's `WardrobeData`, read late from `app.state.r13_parts`. A source is placed by its own `row` (the contract's field proposed for I1), else by its name: pieces, photos; laundry and outfits are history. FAIL CLOSED (H3): a source that fits no row lands in none, every server row is then "Couldn't check right now", and nothing is counted, exported or deleted | `wardrobe/phone/privacy.py` (196) |
| D6, D20 No-AI | Anchored routers installed first. The move takes every put form R14 knows (hid, under, behind, near, beside, next to, with, on top of) and "hung" for a wardrobe word (M4), resolves the piece with `wardrobe_find` and edits it by id (`TakeCall`, D10: no `query` reaches `wardrobe_edit`, M6); a count is A's `{type}`. Never a possessive, R14's not-a-thing words (also "wifes"), or bag, glasses, spectacles, keys, wallet, umbrella | `offline/phrases_r13.py` (314) |
| The part | `build(ctx)`: no tool, job or collection; `services["phrases"]` and the four rows; ready "ready" | `wardrobe/phone/part.py` (36) |
| The eval | `evals/r13/phone.py` BUILT, now 16/16 cases (H2's crop case added; the move is two calls) | `evals/r13/phone.py` |

## 2. Sizes against the guards

| File | Lines | Guard |
|---|---|---|
| `console-vision.js` | 532 | <= 800 (the I0 core's SHA-256 unchanged) |
| `console-vision-r13.js` (new) | 128 | <= 800 |
| `console-wardrobe-scan.js` | 596 | <= 600 |
| `console-wardrobe-words.js` (new) | 83 | <= 600 |
| `console-helpers-wardrobe.js` | 289 | <= 600 |
| `console-wardrobe-pieces.js` | 104 | <= 600 |
| `console-wardrobe.css` | 54 | <= 200 (new CSS <= 300 in all) |
| `wardrobe/phone/privacy.py` / `part.py` | 196 / 36 | <= 400 |
| `offline/phrases_r13.py` | 314 | <= 400 |
| `console.html` | 782 | byte-identical (not touched) |

Every function is at most 50 lines. No wiring or shared file was edited.

## 3. Tests and checks (what ran, and the numbers)

Every run behind the shared lock (`flock /tmp/heavy.lock`), `PYTHONPATH=$PWD/src`; Python 3.11 for
the unit tests, Python 3.13 with Playwright for the browser tests (one file at a time). The whole
suites were not run (I1 runs them).

| Check | Result |
|---|---|
| D's unit tests (`test_r13_d_{scan,vision,phrases,part,assets}.py`), with R7's two files D owns | **805 passed**: D's own 540 (`test_r13_d_scan.py` 59, `test_r13_d_vision.py` 13, `test_r13_d_phrases.py` 448 with M4's matrix and L9's Telegram cases, `test_r13_d_part.py` 10, `test_r13_d_assets.py` 10 with the real models in Node), R7's two files D owns 171 (`test_r7_b_console.py` 116, `test_r7_b_dom.py` 55), R14's phrase file 94 (unchanged, run beside R13's routers) |
| Seam and wiring tests (`test_r13_seams.py`, `test_r13_wiring.py`, `test_r13_fold_conformance.py`, `test_telegram_tool_guard.py`) | **318 passed, 2 failed**: the two I0 stub pins of `test_r13_wiring.py` (item 1) |
| Browser, `tests/browser/test_r13_d_camera.py` (the page clock pinned) | **12 passed** (with H2's real-model case, M1 live and the visual gate x4, now with a saved piece's card); R7's `test_r7_b_camera.py` 13 passed on the real app (the split modules load on first use, so its pages never fetch them) |
| Browser, `tests/browser/test_r13_d_helpers.py` (the page clock pinned) | **10 passed** (with the review queue in B's argument names, and the visual gate x4) |
| `python evals/r13/run.py --mock --part phone` | 16/16; the control (the person check off) fails exactly `phone:ops01:person_keeps_and_sends_nothing` |
| `ruff check`, `ruff format --check` (D's Python and tests), `mypy` on D's Python | clean (`mypy`: no issue in 4 source files) |
| `scripts/wardrobe_assets.py check`, `scripts/check_doc_versions.py` | `wardrobe assets: OK`; 29 documents have their version line and change log |

Each fix's test was run first on the code before it and failed (the RED run of each stage), then
passed with the fix; the guard tests (L1, L2) and the waiting-card pin pass on the old code too,
because nothing broke those rules. `a8773b4` carries the words module's half of `1f52333` (that
commit missed one file; the tests had run on the whole tree). `55426f2` only rewraps lines (ruff
E501) and types `PUT_PREPS` (mypy). The two known I0 stub pins in `test_r13_wiring.py` still
fail (Needs I1, item 1). The asset-list tests (`test_r51_console_assets_linked.py`: 544 passed, 4
failed) fail only for the two new modules, allow-listed and linked, until I1 lists them (item 8).

### 3.1 REVIEW-D-1 findings

| ID | Fix | Test (failed before the fix) | Commit |
|---|---|---|---|
| Split | `console-vision.js`'s pure region to `console-vision-r13.js`, the scan module's words to `console-wardrobe-words.js`, each imported on first use (deviation 10); the I0 core's hash unchanged; D's fake server serves both until I1 | `test_the_arithmetic_is_its_own_module_imported_on_a_wardrobe_tasks_first_use`, `..._touches_no_dom_network_storage_or_clock`, `test_the_words_are_their_own_module_imported_on_his_first_press`, `test_words_that_cannot_load_say_so_and_ask_and_send_nothing` | `759f996` |
| H1 | A send keeps his list; a fresh one replaces it only when it has arrived (background refresh) | `test_h1_after_a_live_send_his_next_label_is_read_and_his_names_stay` | `fee2375` |
| H2 | Person and face run again on the exact crop at Save, Remember and Tag, once, whole and in four overlapping two-thirds (a small face near full size); a hit or a missing check keeps and sends nothing | `test_h2_a_face_only_the_crop_shows_keeps_and_sends_nothing` (Save, Remember, Tag), `test_h2_the_crop_is_checked_once_and_a_clean_crop_still_saves`; real UltraFace in Node `test_h2_a_small_face_beside_a_piece_is_missed_by_the_photo_and_found_in_its_crop` (60, 70, 80 px in 1600 x 1200: the photo misses all three, the crop finds all three); real Chromium `test_h2_a_small_face_only_its_crop_shows_keeps_and_sends_nothing` (70 px); eval `phone:ops01:a_face_only_the_crop_shows_keeps_and_sends_nothing` | `fee2375`, `28a1f62` |
| H3 | Privacy rows place a source by its own `row`, else by name (pieces, photos; laundry, outfits = history); anything else lands in no row and every server row is "Couldn't check right now": nothing counted, exported or deleted | `test_a_source_that_fits_no_row_lands_in_none_and_nothing_is_deleted` (catalog, typo, unknown row), `test_each_source_finds_its_row_by_its_own_row_else_its_name` | `5c1b19f` |
| M1 | Another step stops the camera and the label reader; a live send or Cancel clears only the list; ids sent, cancelled or removed are not offered again by that camera | `test_m1_a_step_change_ends_the_camera_and_the_label_reader`, `test_m1_a_live_send_or_cancel_keeps_the_view_and_never_offers_that_label_again` (x2); Chromium `test_m1_a_step_change_ends_the_live_camera` | `097acd6`, `28a1f62` |
| M2 | A box with no edges or over 85 % of the photo: taps and matches only, with words that say how to lay the piece; the card draws the exact crop above Save | `test_m2_a_whole_frame_box_offers_taps_only_and_sends_nothing` (bare, wide), `test_m2_the_card_shows_the_exact_crop_before_anything_is_sent`; the visual gate's saved card | `302cc8f`, `4612e9f` |
| M3 | The view's `tag_estimate_inr` when present, else "about ₹0.01–₹0.51, depending on the brain", 0.51 in the limit check | `test_m3_the_tag_range_is_the_price_tables_cheapest_and_dearest_brain`, `test_m3_the_brains_own_estimate_is_said_and_used_for_the_limit_when_the_view_has_it` | `cf97ac7` |
| M4 | R14's put verbs and places and "hung" ("on top of" before "on"); "wifes" is a person word | `test_m4_r14s_put_verbs_and_places_are_all_inside_r13s`, `test_m4_every_r14_put_form_with_a_wardrobe_word_is_the_wardrobes` (every R14 verb x place x four wardrobe words), the near miss "my wifes shirt is in the laundry" | `a1bbcac` |
| M5 | No candidate is "new?"; candidate 1 at least 0.25 ahead is "maybe"; fewer than 3 prints: no band words, no centring | `test_m5_no_candidate_is_ever_called_new_and_few_prints_say_no_band`, `test_m5_a_single_print_offers_its_piece_with_no_band_words`; real models `test_m5_the_bands_on_inv_06s_real_scores` | `0e61f7c` |
| M6 | A's shapes: `wardrobe_add {pieces: [... client_id]}` -> `ids[0]`, one client id a card; label `{piece, field, read}` + `verify`; `wardrobe_count {type}`; the move `wardrobe_find` then `wardrobe_edit {piece, place}` (`TakeCall`); a refused result is said; `how: tap` with candidate 1's score; Helpers' AI tagging to `PUT /v1/wardrobe/settings` | `test_m6_a_new_piece_is_its_ids_first_and_a_second_press_is_never_a_second_piece`, `test_m6_a_retry_after_a_failure_carries_the_same_client_id`, `test_m6_a_result_that_refused_is_said_and_never_taken_for_done`, `test_m6_a_tap_on_another_candidate_says_tap_with_candidate_ones_score`, `test_m6_helpers_sends_a_settings_change_to_the_settings_route_never_to_a_tool`, the D10 and INV-10 shape tests, `test_m6_the_move_edits_the_piece_wardrobe_find_resolved_and_nothing_on_a_tie` | `a1bbcac`, `c65219d` |
| B's shapes (Workshop) | Helpers' review answers `laundry_review {action: resolve, entry, outcome: these, pieces: [id]}` and `{..., outcome: none}`; the phone's "and more" `laundry_move {step: basket, more, category}` (r13-b @ `b8ee053` `checks.SCHEMAS`); every other D call checked against A (r13-a @ `de5e1a1`), B and C (r13-c @ `eb87a75`) and matching | `test_lnd_03_more_i_couldnt_show_is_a_pending_deposit_with_no_id`; Chromium `test_the_review_queue_answers_in_bs_own_argument_names` | `3136df7` |
| C's cards (Workshop) | D sends no `outfit_plan` or `outfit_prefs` call (so the occasion-key rule needs nothing here); a change that comes back as a card is said as waiting, never taken for done (pinned: it already was) | `test_a_change_that_waits_for_his_ok_or_fails_is_said_and_never_taken_for_done` (needs_approval, denied, error) | `c4b2a52` |
| L1 | The picture routes in any quote, and `JarvisChat`, `.raw(`, `FormData` banned in both scan modules (D's test; I0's at I1) | `test_l1_only_the_door_names_the_picture_routes_in_any_quote` (a guard: nothing broke it before) | `1f52333` |
| L2 | No console module may subscribe to `embed`, `colour`, `person` or `face` (D's test; the core change at I1) | `test_l2_no_console_module_subscribes_to_the_wardrobe_tasks` (a guard) | `1f52333` |
| L3 | The phone compares each model file's SHA-256 with the manifest (`SUMS13`) before opening it | `test_l3_the_phone_compares_each_model_files_bytes_with_the_manifest`; the browser runs load the real files | `1f52333` |
| L4 | A fingerprint carries its embed's own model | `test_l4_remember_sends_the_fingerprints_own_model` | `1f52333` |
| L5 | Page clock pinned, no fixed sleeps, shots only by `R13_D_SHOTS` | D's two browser files | `28a1f62` |
| L6 | Declined here (R7's file): I1 item 9 | – | – |
| L7 | Front, Back or Detail; the default the first side not saved yet (by his list's photo count) | `test_l7_a_photo_is_saved_as_the_side_he_picks_first_the_one_not_saved_yet` (x3) | `1f52333` |
| L8 | The Photos row says its delete is every wardrobe photo and fingerprint at once | `test_the_words_say_what_is_never_kept` | `1f52333` |
| L9 | D20's sentences on Telegram: refused with the personal switch off (nothing runs), reach their tools with it on | `test_l9_a_d20_sentence_on_telegram_follows_the_personal_switch` (each sentence x off, on) | `a1bbcac` |
| L10 | A scan queued during a send goes right after it; the gap comment says two cells; No-AI checked again at the tag's press; the tag button says a photo is sent | `test_l10_a_scan_queued_while_one_is_sent_goes_right_after_it`, `test_l10_the_tag_checks_no_ai_again_at_the_press` | `1f52333`, `cf97ac7` |

### 3.2 Declined, with the reason

- **L6** (the Camera strip's four columns live in D's stylesheet): the rule belongs in R7's
  `console-camera.css`, which is not D's file. Kept as is; I1 moves it (item 9).
- **L2's I1 half** (the core skips `tell()` for the photo-only wardrobe tasks): the core is I0's and
  its hash is a contract; D's static test guards it now (item 10).
- **L1's I1 half** (widening I0's own door test): `tests/test_r13_seams.py` is I0's; D's own test
  file holds the wider rule now (item 2c).

## 4. Screenshots (for the Workshop)

In the Workshop's scratch folder `r13-d-shots-2`, at 1440x900 and 390x844, Night and Day:
Camera -> Wardrobe `camera-wardrobe-start-*`, `camera-wardrobe-card-*` (a new piece's kinds and
suggested colour), `camera-wardrobe-saved-*` (new: a saved piece's card with the exact crop Save
would keep, M2, and Front / Back / Detail, L7), `camera-wardrobe-laundry-*`; Helpers -> Wardrobe
`helpers-wardrobe-*` and `helpers-wardrobe-pieces-*` (each also as `*-panel.png`). 32 files. Every
one passed the visual gate (overlap, clipping, wrap); the look is unchanged but for the fixed
behaviour.

## 5. Deviations from the plan, and why

1. **The AI tag's rupees** (H2: "the ₹ shown first"): the button says the view's own
   `settings.tag_estimate_inr` when A sends it (I1, item 2a), else "about ₹0.01–₹0.51, depending on
   the brain" (`llm/pricing.py`, ≈ 750 tokens in and 120 out, ₹95.24 a dollar), and the limit check
   uses ₹0.51. The door's guard is not narrowed (REVIEW-D-1, item 2).
2. **No thumbnails or one-photo delete in Helpers** until the door's `thumb(id)` and `drop(id)` (I1,
   item 2b); the Photos row says its delete is every wardrobe photo (L8).
3. **No test hook for a detection**: a drawn face fires UltraFace and a drawn silhouette fires SSD's
   "person", in Node and in Chromium, so the refusal tests use the real models; the Node harness
   fakes the answers for the flow tests (including a face only the crop shows, H2).
4. **The box split** is plain arithmetic in the scan module (the border's colour as the surface, gaps
   of up to two cells closed, parts of at least 1.5 %, at most six, left to right). A box over 85 %
   of the photo is not a crop (M2).
5. **A label's brand is not read** (OCR brand text is unreliable): size, fabric with percentages and
   care words only; each field is kept or confirmed whole, as A's `wardrobe_edit` takes it.
6. **The bands** keep the plan's numbers (0.80, 0.60, 0.03) with M5's rules: no candidate is "new?";
   candidate 1 at least 0.25 ahead of candidate 2 is "maybe"; with fewer than 3 saved prints, no band
   words and no centring. On INV-06's real fingerprints the right shirt is "maybe" or "likely" in
   every view; the pilot still calibrates.
7. **The Camera strip** has four columns, set in D's stylesheet (L6, I1 item 9).
8. **Private copies by number**: "A private basic (No. N)" in his own console (D10's card form).
9. **The person self-check input** is a drawn silhouette, not the ramp; its arithmetic now lives in
   `console-vision-r13.js` (`silhouette()`), and the Node test imports that very file.
10. **The two split modules are imported on first use, not statically** (the review suggested a
    static import): the engine and the scan module are loaded at every page start, so a static
    import of a file the server does not serve yet (APP_ASSETS until I1) would stop the whole engine
    and the Camera panel. On first use, a missing file is "could not load" for the wardrobe tasks or
    the Wardrobe mode only.
11. **The move's two steps** (`wardrobe_find`, then `wardrobe_edit` by id) need one runner step at I1
    (item 7): until then the edit runs without its piece and A refuses it, so nothing moves on a
    guess.

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
2. **The picture door and its test** (REVIEW-D-1 item 2: do NOT narrow the door test; v13.0.1's
   proposal is withdrawn).
   - (a) **The ₹ rides in A's view**: `SettingsView` gains `tag_estimate_inr: float | None = None`,
     A's figure from `llm/pricing.py` for the brain that would answer. D already says it (M3).
     ```diff
     @@ class SettingsView(_M):  # wardrobe/http_views.py
          tag_cap_inr: int = Field(default=30, ge=0)
     +    tag_estimate_inr: float | None = Field(default=None, ge=0.0)  # one photo, this brain
     ```
   - (b) **Thumbnails and the one-photo delete through the door** (`console-r7-send.js`, its guard
     130 -> 145 in `test_r13_seams.py`); the CSP's `img-src 'self' data:` needs no `blob:`.
     ```diff
     +const PHOTO = /^wh_[0-9a-f]{12}$/;
     +async function thumb(id) { // a saved crop, back as a data: URL for an <img> in Helpers
     +  const chat = window.JarvisChat;
     +  if (!PHOTO.test(String(id || '')) || !chat || typeof chat.raw !== 'function') throw new Error(NOT_READY);
     +  const r = await chat.raw('/v1/wardrobe/photos/' + id);
     +  if (!r.ok) throw new Error('That photo could not be shown.');
     +  const b = await r.blob();
     +  return new Promise((ok, no) => { const f = new FileReader(); f.onload = () => ok(String(f.result)); f.onerror = no; f.readAsDataURL(b); });
     +}
     +async function drop(id) { // one photo, deleted
     +  const chat = window.JarvisChat;
     +  if (!PHOTO.test(String(id || '')) || !chat || typeof chat.raw !== 'function') throw new Error(NOT_READY);
     +  const r = await chat.raw('/v1/wardrobe/photos/' + id, { method: 'DELETE' });
     +  if (!r.ok) throw new Error('That photo could not be deleted.');
     +}
     -if (M) M.part('send', Object.freeze({ canAsk, ask, attach, vault, wardrobe, tag, sentToday: readCount, line }));
     +if (M) M.part('send', Object.freeze({ canAsk, ask, attach, vault, wardrobe, tag, thumb, drop, sentToday: readCount, line }));
     ```
     D then draws each photo with a Delete in Pieces.
   - (c) **I0's door test widened** (L1; D's own `test_l1_only_the_door_names_the_picture_routes_in_any_quote`
     already holds it):
     ```diff
     @@ def test_the_door_is_the_only_caller_of_the_wardrobes_picture_routes
     -        for route in ("/v1/wardrobe/photos", "/v1/wardrobe/tag"):
     -            assert f"'{route}" not in code, (path.name, route)
     +        assert not re.search(r"""['"`]/v1/wardrobe/(?:photos|tag)\b""", code), path.name
     @@ def test_the_scan_module_keeps_the_camera_panels_rules
     -    for bad in ("fetch(", "XMLHttpRequest", "sendBeacon", "WebSocket", "localStorage"):
     +    for bad in ("fetch(", "XMLHttpRequest", "sendBeacon", "WebSocket", "localStorage", "JarvisChat", ".raw(", "FormData"):
     ```
3. **The tool arguments**: D now sends each owner's shapes, checked against r13-a @ `de5e1a1`,
   r13-b @ `b8ee053` and r13-c @ `eb87a75`. A: `wardrobe_add {pieces: [{type, private, colour?,
   client_id}]}` read as `ids[0]`; a label read `{piece, size | fabric | care, read: true}`, Confirm
   adding `verify: [field]`; `wardrobe_count {type}`; the move `wardrobe_find {query}`, then
   `wardrobe_edit {piece, place}`; `wardrobe_retire {piece, action}`, `wardrobe_remove {piece}`.
   B: `laundry_move {step, pieces | query, load?}` and `{step: basket, more, category}`;
   `laundry_review {action: resolve, entry, outcome: these, pieces}` or `{..., outcome: none}`;
   `laundry_send_out {action: receive, batch, pieces}`; `laundry_status {}`. C: `outfit_suggest
   {day?, occasion?}` (his words, as C's schema keeps it), `wear_log {action, plan | query, day?}`;
   D makes no `outfit_plan` or `outfit_prefs` call. A scan event's `how` is `qr`, `match`
   (candidate 1) or `tap` (another, with candidate 1's score). I1 adds a test that replays the
   calls D's harness records through each part's real tool schema and `check`; C's `lead_h` stays
   in D's settings body until I1's one cross-part commit drops it.
4. **`WardrobeData.row`** (H3: D fails closed now and already reads `row` when a source has one).
   ```diff
   --- a/src/jarvis/wardrobe/ports.py
   +PrivacyRow = Literal["pieces", "history", "photos"]  # D20: the Wardrobe Privacy row of a source
   @@ class WardrobeData(Protocol):
        name: str
   +    row: PrivacyRow
   --- a/src/jarvis/api/r13_wiring.py
   @@ def check_part(name: PartName, part: object) -> WardrobePart:
        if not all(isinstance(d, WardrobeData) for d in part.data):
            raise ValueError(f"part {name} offers data without count, export and delete")
   +    if any(d.row not in get_args(PrivacyRow) for d in part.data):
   +        raise ValueError(f"part {name} offers data with no Privacy row")  # setup failed
   ```
   A exposes two sources: `pieces` (row "pieces": the index and its logs; its delete drops the
   photos too, and the row's words say so) and `photos` (row "photos": photos and fingerprints only;
   the catalog stays usable, e2e 7). B's `laundry` and C's `outfits` are row "history".
5. **`PUT /v1/wardrobe/settings`** (A's settings: AI tagging, the private display): owner-only,
   rate-limited, `record_change`, mirroring C's `PUT /v1/outfits/settings`, calling A's
   `tagging.update_settings`; a contract row in `wardrobe/http.py`
   (`WardrobeSettingsIn {ai_tagging?: bool, show_private?: bool}` -> `SettingsView`). D's Helpers
   already sends `{ai_tagging}` there (D's fake server answers it; the real one says "This switch
   arrives with the next JARVIS update" until then). Never on the model's tool surface.
6. **The backup's photos**: `GET /v1/wardrobe/backup` gains `photos: bool = False` in the contract
   (`?photos=1` parses as true; A's `backup.lines(uid, photos=...)` takes it); the tick's words say the
   file then holds his photos, sealed, and is larger. Restore's purged-piece ticks
   (`RestoreCheck.purged` -> `RestoreApply.include_purged`) can follow in the same change.
7. **The move edits by id (D10)**: `wardrobe_edit {query, place}` leaves D10's exception list and the
   needles eval's allowed places (A drops `query`). D's router already sends `wardrobe_find {query}`
   and then a `TakeCall("wardrobe_edit", {place}, take=(("piece", "best"),))`; the No-AI runner fills
   it (`offline/no_ai.py`; `tests/r13_fakes_d.py run_taking` is the reference and is tested):
   ```diff
   +def _taken(call: NoAICall, results: Sequence[GatewayResult]) -> dict[str, str] | None:
   +    """The call's arguments with any value it takes from the step before (R13 D6, D10); None
   +    when that value is not an id (several pieces fit, or none: nothing moves)."""
   +    args = dict(call.arguments)
   +    prev = results[-1].result if results else None
   +    for arg, key in getattr(call, "take", ()):
   +        value = prev.get(key) if isinstance(prev, dict) else None
   +        if not isinstance(value, str) or not value:
   +            return None
   +        args[arg] = value
   +    return args
   @@ async def run_no_ai(
            for call in route.calls:
   +            args = _taken(call, results)
   +            if args is None:
   +                break  # the step before named no single piece: its own words are the reply
                tool_call = ToolCall(
   -                id=f"noai-{uuid.uuid4().hex[:8]}", name=call.tool, arguments=call.arguments
   +                id=f"noai-{uuid.uuid4().hex[:8]}", name=call.tool, arguments=args
                )
   ```
   D6's wording at I1: "the move resolves the piece first (`wardrobe_find`), then edits it by id".
8. **`APP_ASSETS` for the two new modules** (`api/console.py`), and their loader rows in
   `tests/test_r51_console_assets_linked.py` (`NOT_IN_PAGE`); D's fake server then steps aside by
   itself (`tests/r13_fakes_d.py asset_routes`).
   ```diff
        "console-wardrobe-scan.js": _JS,  # Camera -> Wardrobe, a pixel panel (loaded by console-r7.js)
   +    "console-wardrobe-words.js": _JS,  # its non-pixel words (imported by console-wardrobe-scan.js)
   +    "console-vision-r13.js": _JS,  # the wardrobe tasks' arithmetic (imported by console-vision.js)
   @@ NOT_IN_PAGE = {
   +    "console-vision-r13.js": ("console-vision.js", "import('./console-vision-r13.js')"),
   +    "console-wardrobe-words.js": ("console-wardrobe-scan.js", "import('./console-wardrobe-words.js')"),
   ```
9. **The Camera strip's columns** (L6): move `#p-camera .hp-tabs` (four columns) from
   `console-wardrobe.css` into R7's `console-camera.css` (3 -> 4), and compare the Camera screenshot
   with R14's: only the strip should differ.
10. **The core skips `tell()` for the photo-only wardrobe tasks** (L2): a future use case could list
    `embed` and receive his query fingerprints. D's test refuses any console module that subscribes
    to `embed`, `colour`, `person` or `face` today; the core change is I0's (its hash moves).
11. **D's browser tests** run on `tests/r13_fakes_d.py` over I0's fake server; at I1 they move to the
    wired app (I0-NOTES 6.5). The fake server's naive-midnight stated day changes to noon his time
    (REVIEW-A-1, item 7); D's tests then expect noon.
12. **The persona and the guide** (I1's): `WARDROBE_RULE`, C63's new words and the wardrobe photos'
    row land with the commit that makes saving possible (D9, M14).

## 7. Pins D moved (its own files)

`tests/test_r7_b_console.py`: the engine is sealed after NINE tasks; R7's BASE regex no longer reads
`ORT_BASE`; a task may fetch from `BASE13`; `load: guard(` counts 8 (R7's four, R13's three models,
and the colour task, which now waits for its arithmetic). `tests/test_r7_b_dom.py`: the engine lists
the nine tasks, the four wardrobe ones photo-only.

## 8. What can't be verified here

The models on his phone (speed, memory, a quantized operator: the self-checks report it); UltraFace
and SSD on a real face and a real partial body (only drawn ones here); a real camera (Chromium's fake
device only); the match rates and the bands on his clothes (the pilot); the other parts' real routes
and tools (fakes until I1; D's calls are A's shapes as of `r13-a` @ `95b64ae`); Web Push and Telegram
words (B and C send them; D's Telegram tests use fake tools behind the real Telegram rules).

## Change log

| Version | Date | Release | What changed | By |
|---|---|---|---|---|
| v13.0.2 | 16 Nov 2026, 06:35 IST | R13 | The fixer's pass on REVIEW-D-1: the two splits (`console-vision-r13.js`, `console-wardrobe-words.js`, imported on first use), H1–H3 and M1–M6 fixed test first, the LOWs fixed or declined with reasons, the findings table, Needs I1 rewritten (12 items with exact diffs), fresh screenshots | 🛠 Mark XXI |
| v13.0.1 | 15 Nov 2026, 21:55 IST | R13 | First edition: what D built per use case and decision, the sizes, every check with its numbers, the screenshots, nine deviations with their reasons, eight Needs-I1 items with exact diffs, the R7 pins moved, and what this workspace can't verify | 🛠 Mark XXI |
