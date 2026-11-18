Version v13.1.2 · 17 Nov 2026, 17:55 IST · Release R13.1 · Status: Current · Owner: 🛠 Mark XXIII

# R13.1 — Part A brief: Try-on data (Opus)

Read `BRIEF-COMMON.md` first (the loop, the rules, the seams, the commands). Branch `r13-1-a` from
`origin/r13-1-i0`. `security-reviewer` is REQUIRED for your part (OPS-05, the confirm path).

You build the figure's data on the server: his measurements and their versions, the look the figure
draws (with each slot's options and their fresh readiness), each piece's figure choice, saved
comparisons, the fresh check before "Use this look", the Try-on Privacy rows that are yours, and
OPS-05 ("Delete all my try-on data"). Plan sections: D4, D5, D6 (private slots), D7, D11's no-go
list, D14, D16, D20, "Data model", "The HTTP contract" (the `tryon` rows), the `looks` suite.

## 1. Your files (only these)

`src/jarvis/wardrobe/tryon/{part,store,versions,looks,options,assets,saved,confirm,privacy,erase}.py`
(`part.py` replaces I0's stub), `src/jarvis/api/tryon.py` (I0's empty router: fill it),
`tests/test_r131_a_*.py`, `tests/r131_fakes_a.py`, `evals/r13_1/looks.py` (I0's stub: replace it),
`docs/plans/r13-1-integration/INTEGRATION-A.md`. Every module ≤ 400 lines, functions ≤ 50.

## 2. Your contracts

- **The join** (`part.py`): `build(ctx) -> WardrobePart("tryon", privacy=(…three rows…),
  services={"tryon_looks": <a TryonLooks>}, ready=<one plain word>)`. No tool, no job, no `data`
  (the wiring refuses `data` on your part, M4); only the Privacy rows `tryon_figure`, `tryon_all`,
  `tryon_device` (`ports.PRIVACY_OWNER`). With no document store or no keyring: ready says so in
  words ("Off: …"), Try-on is off and never stores anything in clear, and your rows still answer for
  what is on disk (reuse `kept.kept_row` / `kept.DeviceRow`, or your own with the same words).
- **The document** `tryon/{uid}` (`model.TRYON`), sealed with purpose `tryon`, AAD
  `model.aad_tryon(uid)`, a plain `owner` field and `updated_at` (R13 I1's M1 rule: found and
  deleted without the key), at most `model.TRYON_DOC_MAX_KB` (200 KB) sealed. It holds the
  measurements (`current`, one `draft`, ≤ `EARLIER_MAX` (5) `earlier`, each a `model.Body` with its
  `typed` fields and `at`), `assets` {piece → template, texture view, card only}, `saved` ≤ 10
  comparisons (`tc_` ids; slots → piece ids, tuck, open, layers; NEVER a picture), his figure
  preferences. An unreadable document is never overwritten (say so, as R13's styling does).
- **Versions (D4):** six whole-cm measurements in `model.RANGES`, a value outside refused with
  `model.range_words` (422 `Refusal`); one he didn't type is `model.estimated(height)`'s and shown
  "estimated"; every `BodyView` you serve carries `weights = model.morph_weights(values)` (the
  engine contract's `body.weights`: the one rule, never a copy); `PUT /v1/tryon/body` writes the draft, `POST /v1/tryon/body/use` makes it current
  (the old current becomes the first earlier), `DELETE /v1/tryon/body/draft` drops it. Each is
  audited with `api.settings_audit.record_change` (an argument hash, never the numbers). Saved
  selections (plans' piece ids, saved comparisons) NEVER change with a version.
- **The look (D5, D7, D21):** `GET /v1/tryon/look?plan=` or `?day=today|tomorrow&alt=0|1|2` or
  `?pieces=slot:wi_…,…` (row 388: exactly the pieces on a reply's try-on card, each re-read fresh; a
  piece that isn't his any more → 422 in words; a private slot covered) (`&private=1`) →
  `http.TryonLook`. Read the plan and its look from R13's styling service
  (`ports.service_of(ctx, "refresh").styling`: `plans.read(uid)`, `answer(...)`; the wardrobe view
  from `ctx.store()`), each slot a `LookSlot`: template from his choice, else `model.template_of`;
  `variants`; `rgb` (`model.rgb_of`, "no colour set" when none); `pattern`; texture view (`detail`
  if kept, else `front`) and its photo id; views kept and the USEFUL missing ones
  (`model.useful_views`); readiness from a FRESH read of the view and the plans (`model.READY`,
  `DRAFT_WORDS[state]`, `reserved_words(texts.event_words(...))` from R13's `styling.reserve`,
  `ONE_SHOE` for a pair with one side not ready); `approximate` flags; `card_only`; `removable`
  (`REMOVABLE_SLOTS`); ≤ 12 options a slot (every non-private, non-archived, non-merged piece of the
  slot's types, each with its readiness). **A private slot (`PRIVATE_SLOTS`) is covered only:** no
  template, colour, pattern, photo or options; its piece and words only with `private=1`. The tuck
  default from the dress code (`TUCKED_CODES`), open by default. "That plan isn't there any more" as
  a 404 `Refusal`.
- **Assets (AVT-05):** `PUT /v1/tryon/assets/{piece}` → `AssetChoice` saved against the piece id in
  `tryon/{uid}.assets` (a template of the same slot, `model.templates_for`, or card only); a
  merged-away or purged piece's entry is dropped on read (your tidy, inside your own code).
- **The confirm (D7, D20):** `POST /v1/tryon/confirm` `{plan, slots, session_id}`: re-check every
  piece from a FRESH view BEFORE any tool call and refuse a draft as 409 `Refusal` in plain words
  ("The navy jacket is in the laundry: it can't be confirmed for this event"); when all are
  eligible, make ONE call: `api.wardrobe.run_panel_tool(request, uid, "outfit_plan",
  {"action": "lock", "plan": plan, "pieces": [...]}, session_id)` and answer
  `api.wardrobe.panel_reply(run)` (R13's `ToolReply`: the cards, rows and audit are R13's; at most
  one card a press). The early check is for the words; `outfit_plan`'s own check is the guarantee
  (I0 built it: a piece that goes to the laundry between the two is refused, the plan unchanged).
- **Saved comparisons (AVT-11):** `GET/POST /v1/tryon/saved`, `GET/DELETE /v1/tryon/saved/{id}`;
  ≤ 10; re-checked on every GET (each slot's readiness word; `draft` while any piece isn't eligible).
- **`tryon_looks` service** (`ports.TryonLooks`): `look(uid, plan) -> TryonLook` (C sends what this
  says, fresh).
- **Privacy rows (D16)**, words from `kept.SPECS` (`tryon_figure` "Your measurements and your 3D
  figure": count, export, delete with a confirm; `tryon_all` "All your try-on data": passkey,
  OPS-05; `tryon_device`: `kept.DeviceRow`). **OPS-05** is the Privacy delete of `tryon_all`
  through the existing `PrivacyService` (its passkey ceremony bound to the category id and `rev`,
  its IRREVERSIBLE audit line, its words; no new passkey code, no erase route): the row's delete
  calls your `erase_all(uid)`: C's pictures, the garment photos (D22), his photo and his YES through
  `ports.seeme_service(ctx).erase(uid)`, else `kept.erase_seeme(docs, prefix, uid)` (C off or
  failed), then `tryon/{uid}` LAST; the spend counters stay; the wardrobe catalog is untouched (its
  `rev` the same). The backups sentence is `kept.BACKUP_WORDS` (read from R14's `RETENTION_DAYS`).
- **Every route** under `/v1/tryon` (exactly `http.ROUTES` rows of part `tryon`): owner-only (the
  router's `require_auth`), `Cache-Control: no-store`, `r13_status.limited` (30 changes, 60 reads a
  minute), `Refusal` on every refusal. Your measurements never reach a tool result, a log, an alert,
  the audit's text, Google or the R13 wardrobe backup.

## 3. Your rows (his workbook's acceptance checks, word for word) and their named tests

| Row · ID | His acceptance check | Your test (what must hold) |
|---|---|---|
| 354 · AVT-03 | Correcting height updates the avatar and its previews while retaining saved outfit selections. | **`test_avt03_correcting_height_reshapes_the_figure_and_keeps_every_saved_selection`** (yours): 172 → 178 cm changes the figure's height to 178 ± 0.5 cm and every open look and saved comparison redraws; their piece ids per slot are byte-identical before and after; the old version stays in use until "Use these measurements"; an untyped measurement is shown "estimated" (B proves the 178 ± 0.5 cm shape; you prove the versions and the kept ids) |
| 355 · AVT-04 | A kurta has recognisable front and back references and remains linked to its original inventory record. | **`test_avt04_a_kurta_shows_its_front_and_back_references_under_its_own_id`** (yours): a kurta with R13's `front` and `back` crops lists both as reference cards in its look slot, under the same `wi_` id as in the catalog; a kurta with only a front asks for the back view only (a link to Camera → Wardrobe), and stays selectable |
| 356 · AVT-05 | A patterned shirt can use an approximate silhouette while its actual reference image stays visible. | **`test_avt05_a_patterned_shirt_draws_on_an_approximate_shape_beside_its_real_photo`** (yours): a checked shirt gets template `shirt` (saved against its id), its texture from its own crop, the label "Approximate", and its front photo card visible beside the figure; a type with no template shows an image card only |
| 360 · AVT-09 | Swapping a ready jacket changes the avatar and checklist together. A jacket in laundry cannot be confirmed for the event. | **`test_avt09_a_ready_jacket_swaps_figure_and_checklist_together_and_one_in_laundry_stays_a_draft`** (yours): the swap changes the drawn outer layer and the checklist row in one step; a jacket In laundry is offered as "Draft: in the laundry", "Use this look" is refused by the server's fresh check (no `outfit_plan` call is made); a jacket that goes to the laundry between that check and the call is refused by `outfit_plan` itself (D20), the plan unchanged; one press makes at most one card; undo returns to the last still-eligible pick (D proves the swap and undo in the browser) |
| 350 · OPS-05 | Deleting an avatar removes it from the viewer and disables dependent previews while retaining the item catalog. | **`test_ops05_deleting_the_figure_empties_the_viewer_disables_previews_and_keeps_the_catalog`** (yours): after the Privacy delete of `tryon_all` ("Delete all my try-on data", his passkey) the viewer says "No figure yet", saved comparisons and pictures are gone, "See it on me" asks for a photo again, and `GET /v1/wardrobe` returns the same pieces and `rev` as before |
| 353 · AVT-02 (your half) | The owner can rotate the model and inspect a distinct front, side and back view. | `test_avt02_store_*`: the measurements behind the figure are kept, versioned and estimated where not typed (B owns the named test) |
| 362 · AVT-11 (your half) | A formal and festive look can be compared without losing either item list or its availability state. | `test_avt11_saved_*`: a saved comparison keeps both looks' piece ids, re-checked on opening, "Draft" while a piece changed state (B owns the named test, D the lists) |
| 365 · AVT-14 (your half) | Sharing a look displays the dressed avatar and only the approved item details. | `test_avt14_looks_*`: no private piece's id, colour, photo or label in any look, option or caption field you serve (B owns the named test) |

The eval case of the same name for each row you own is in `evals/r13_1/looks.py`.

## 4. Your eval (`evals/r13_1/looks.py`) and its controls

Cases: AVT-03 versions and kept selections; AVT-04 views and the kurta; AVT-05 association; AVT-09
fresh check, drafts, no tool call for a draft, the race (a piece to the laundry between the check
and the call → refused by `outfit_plan`, the plan unchanged), one card at most; AVT-11 saved
comparisons re-checked; AVT-14 private slots covered (no id, colour, photo or label in any look,
option or caption); OPS-05 erase order and the catalog's `rev` unchanged; D20's `lock`/`reserve`
refusals. **Controls that must turn it red:** the private filter off (AVT-14 fails); the fresh check
off (AVT-09's laundry jacket gets past the early refusal); `lock` without D20's eligibility check
(monkeypatch `styling.actions.unready` to answer None: the race case writes the jacket). **Each
row's own control (M8):** AVT-03 a new version rewrites a saved comparison's piece ids; AVT-04 the
look drops the `back` view of the kurta; AVT-05 the template choice kept in page memory, not
`tryon/{uid}.assets`; AVT-09 `lock` without D20's check; OPS-05 erase also deletes the wardrobe's
photos (the catalog's `rev` changes). Set `BUILT = True` only when every control fails its case.

## 5. Limits

No new tool, permission row, alert kind, job, secret or collection; never `data`; never a wiring or
shared file (BRIEF-COMMON section 3). A ₹ figure is not yours to show. Fixed clocks (`r131_fakes.NOW`);
fakes in `tests/r131_fakes_a.py` (bare imports). INTEGRATION-A.md lists what C and D need from you
(the exact `TryonLook` you serve for the pilot, the readiness words), every deviation, "Needs I1".

## Change log

| Version | Date | Release | What changed | By |
|---|---|---|---|---|
| v13.1.1 | 17 Nov 2026, 15:55 IST | R13.1 | First edition, written at I0: Part A's files, contracts (the join, the sealed document, versions, the look and its fresh readiness, assets, the confirm through `run_panel_tool`, saved comparisons, the `tryon_looks` service, the Privacy rows and OPS-05's order, the routes), its rows with his acceptance checks and the named tests, the `looks` eval with its controls and each row's own, limits | 🛠 Mark XXIII |
| v13.1.2 | 17 Nov 2026, 17:55 IST | R13.1 | The owner's scope of 17 Nov 2026 (plan v13.1.3): the look by `?pieces=` for row 388's card (D21); OPS-05's erase includes C's garment photos (D22) | 🛠 Mark XXIII |
