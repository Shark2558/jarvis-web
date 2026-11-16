Version v13.0.2 · 16 Nov 2026, 11:50 IST · Release R13 · Status: Current · Owner: 🛠 Mark XXI

# R13 Part A: Catalog and the ledger (INV-01 to INV-17, OPS-03, OPS-06)

Builder A's report for I1. Branch `r13-a`, cut from `r13-i0` @ `3bf2cb1`. I built against
`BRIEF-COMMON.md`, `I0-NOTES.md`, the plan `r13-wardrobe.md` v13.0.2 (Part A, D2, D4, D7, D9,
D16, D17, plan review H3 and H4, the M items) and the repository's rules. I edited no wiring
file and no shared file. Everything A owns is in `src/jarvis/wardrobe/catalog/`,
`src/jarvis/api/wardrobe.py`, `tests/test_r13_a_*.py`, `tests/r13_fakes_a.py` and
`evals/r13/catalog.py`.

v13.0.2 adds the fixes of the fresh-context review `REVIEW-A-1.md` (verdict WARNING: 4 high,
8 medium, 9 low). Every finding that is A's own is fixed test first, one commit each, with the
review's deviation 6 (§9). What is not A's to change is under "Needs I1" (§6).

## 1. What A offers the other parts

- **`store`**: `catalog.store.CatalogStore`, the one `WardrobeStore`. It seals the index
  `wardrobe/{uid}` and the log pages `wardrobe_log/{uid}_{piece}_{page}` (200 events a page)
  under the `wardrobe` key. Each AAD names the owner, and for a log page also the piece and the
  page. It passes I0's `tests/test_r13_fold_conformance.py`: `r13_fakes_a.conformance_store`
  runs all 21 rig cases on it, and the two cases that walk every factory include it.
  - `transact(uid, fn)` follows the contract. It takes three keyword arguments that are A's own
    and leave the Protocol unchanged:
    - `index=` changes the index's other records (places, pairs, labels) in the same commit;
    - `needed=` asks B's writer for entries without an event (the sweep);
    - `as_stored=` keeps already-settled events exactly (the restore).
  - `events(uid, piece, *, view=None)` returns the raw log. Pass the view you already hold:
    then N pieces read the index once, not N times.
  - `history`, `correct` and `bind` follow the contract. `correct` refuses the card-only kinds
    (`store.CARD_ONLY`: registered, archived, restored, merged, corrected) in plain words
    (`store.OWN_BUTTON`).
- **`photos`**: `catalog.photos.PhotoVault` (`count`, `delete_all`, plus `save`, `get`, `delete`
  and `prints` for the routes).
- **`bin`**: `catalog.undo.CatalogBin`, the restorer and purger for `wardrobe_item`. An entry
  is `{ref, ev}` (ids only): it restores or purges only while its own `archived` event is still
  the piece's newest applied state-setting event.
- **No other service name** is offered. A's routes reach everything else through `store.desk`
  (`catalog.part.Desk`).
- **Tools**: the eight `wardrobe_*` tools, all agent `wardrobe`, none `spoken_ok`, none
  trusted. `wardrobe_merge` and `wardrobe_retire` use `ask_when` and always become a card.
  `wardrobe_remove` is `undoable`. Every write tool takes piece ids only (`wardrobe_edit`
  requires `piece`).
- **Daily job**: `wardrobe_sweep` (`catalog.jobs`).
- **Data**: `CatalogData` ("catalog") for D's Privacy rows.

## 2. What A built, by use case

| ID | Built in | Named tests |
|---|---|---|
| INV-01 | `search.py` (type, colour, pattern, place, label words; `best` only when one match is ahead), `views.place_words` | `test_inv01_…` |
| INV-02 | `places.baseline`: `seen` events and `baseline_at` in ONE commit; unresolved scans returned as a count; places without a baseline listed | `test_inv02_…` |
| INV-03 | `service.add` (a box is a piece, nothing guessed) | `test_inv03_…` |
| INV-04 | `edits.apply_edit` (a type change keeps the id; a change into a private-by-default type asks first) | `test_inv04_…` (2) |
| INV-05 | `service.intake` (his tapped candidate is a `seen` on that id) | `test_inv05_…` |
| INV-06 | `matching.py`, the reference "seen before?" rule the phone runs (centred cosine, best of views, at most 3, bands, twins); `photos.Prints` (sealed shards of 200, one model) | `test_inv06_…`, `test_two_identical_vests_…`, fingerprint tests |
| INV-07 | `labels.py`: `resolve` (only `jw1:` + 8 characters AND one of HIS assigned labels); the scan route marks a QR event unverified on a piece without one of his labels | `test_inv07_…`, `test_a_qr_read_counts_only_…` |
| INV-08 | `service.piece_id`: a keyed hash of the box's client id, so the same box is the same piece, applied once | `test_inv08_…` |
| INV-09 | locks: what he sets is locked; a suggestion never overwrites a lock and never locks | `test_inv09_…` (2) |
| INV-10 | label fields kept only in parsed form (size, brand, fabric, care); read fields stay unverified until he confirms; raw OCR text is refused | `test_inv10_…` (5) |
| INV-11 | `links.pair`, `counts.Tally` | `test_inv11_…`, edges |
| INV-12 | `links.make_set`, `Tally.set_views` | `test_inv12_…` (2) |
| INV-13 | `service.move` (one of his places, else refused with his places listed); "(last known)" when the piece was not seen within `wardrobe_stale_days` or is not Ready | `test_inv13_…` (2), the move by his words |
| INV-14 | `Tally.of` (owned stays, complete pairs drop, scope covered) | `test_inv14_…` |
| INV-15 | `search.rank` (two belts told apart by place; no match gives Things' turn) | `test_inv15_…` |
| INV-16 | `merge.py` (one active id; `history` reads both logs; pair and label move over; two labelled copies are refused; undone from the bin) | `test_inv16_…` (2), the merge undo, the merge's links |
| INV-17 | `tools_life.retire` (archive and restore are cards every time; restore reuses the id; its condition is a card of its own, "Mark a black belt Ready", refused while the piece is still archived); `correct` never voids a card-only kind; a stale bin entry never un-archives | `test_inv17_…`, `test_m7_…`, `test_h1_…`, `test_h2_…` |
| OPS-03 | `fold.py`, the pure, order-independent fold: superseded, duplicate, conflict, held, voided, known; `settle`, the one time rule; `store.py`, one commit, never overwriting what it can't open | I0's conformance (21 on A), `test_as_fold_agrees_with_the_reference_on_500_seeded_histories`, store tests, route scan tests |
| OPS-06 | `backup.py` (sealed line by line, bound to its own file id and head, streamed, photos only when ticked, refused in words before a byte when the restore would refuse it) and `restore.py` (the check writes nothing; the token covers his purge count; chunks of 50 pieces or about 8 MiB, idempotent; links, photos and fingerprints come back only with the pieces that come back) | `test_ops06_…` (3, one through the real app with a 3 MB file and a 31 MB refusal), 15 more in `test_r13_a_backup.py`, 7 in `test_r13_a_restore.py` |

Also built:

- **AI tagging** (`tagging.py`, D7, H2), checked in this order:
  1. off by default, and a cap of ₹0 means never;
  2. only for a saved piece that is not private, judged from the record;
  3. the month-to-date ₹ is kept in his sealed index, by his zone's month;
  4. a call is refused before it starts if month-to-date plus the estimate would pass the cap;
  5. BrainEyes' refusals come back as 422, 402 or 503.

  Only fixed-list words survive the answer.
- **His own settings**: `tagging.update_settings`.
- **The daily sweep** (`jobs.py`): it closes a forgotten wear from 04:00 his time by the rewear
  rule. Holds are handed to B's writer again.
- **The pilot counts** (`pilot.py`) and **the Privacy data** (`data.py`).
- **The routes**: `api/wardrobe.py`, plus `routes_files.py` registered on the same router.

## 3. Files and sizes

| File | Lines | Limit |
|---|---|---|
| `wardrobe/catalog/tools_write.py` | 358 | ≤ 400 (the largest) |
| `wardrobe/catalog/store.py` · `restore.py` · `tagging.py` · `edits.py` · `photos.py` · `routes_files.py` | 341 · 338 · 278 · 268 · 256 · 249 | ≤ 400 |
| the other 25 modules under `wardrobe/catalog/`, with `work.py` (the commit's working set, split out of `store.py` when H1 took it past 400) and `purges.py` (L2) | 2 to 221 | ≤ 400 |
| `api/wardrobe.py` | 290 | ≤ 800 (≤ 400 kept) |
| `tests/test_r13_a_*.py` (10 files) · `tests/r13_fakes_a.py` · `evals/r13/catalog.py` | 176 to 396 · 204 · 356 | ≤ 800 |

Every function is at most 50 lines (checked with `ast`; the longest are `life_tools` at 46 and
`write_tools` at 42). Nothing under `wardrobe/` reads the real
clock (I0's static test passes).

## 4. The checks (Python 3.11, `/tmp/venv-b`, every run behind `/tmp/heavy.lock`)

v13.0.2, on `r13-a` @ `bb09ca6` (the last fix):

| Check | Result |
|---|---|
| A's tests, `tests/test_r13_a_*.py` | **160 passed** (store 16, catalog 27, lifecycle 18, photos 18, jobs 13, tagging 16, backup 18, restore 7, routes 16, edges 11) |
| `tests/test_r13_fold_conformance.py` | 44 passed (23 memory, 21 on A's store) |
| Coverage of `jarvis.wardrobe.catalog` + `jarvis.api.wardrobe` (A's tests + conformance) | **93 %** (3,099 statements, 217 missed; lowest: `routes_files.py` 67 %, `api/wardrobe.py` 85 %) |
| `test_r13_seams.py`, `test_r13_wiring.py`, conformance, `test_telegram_tool_guard.py` | 364 passed, **3 failed**: the same three I0 pins that expect A to be "not built yet" (§6, items 1–3) |
| `test_r14_skill_coverage.py`, `test_permissions_policy.py`, `test_r11_1_b_guard.py`, `test_telegram_personal_reads.py`, `test_test_imports.py` | 397 passed |
| `evals/r13/run.py --mock --part catalog` | **19/19**; the negative control fails the suite |
| `evals/r13/run.py --mock` (every part) | 37/37, the combined control failing the suite |
| `ruff check` · `ruff format --check` (A's 45 files) | clean |
| `mypy src` | 1 error: the baseline's (`memory/redis_store.py:67`) |
| `scripts/arch_coverage.py` | OK (66 packages/modules, 111 Firestore collections: `wardrobe_restore` is now written, L2) |
| `scripts/check_doc_versions.py` | 29 documents pass; this file and `REVIEW-A-1.md` follow the same rules (sub-folder, §8) |

How each fix was tested (§9): its test was written first and run on a frozen copy of the tree
without the fix (each failed, for the reason the review gives); then each commit's exact tree ran
A's whole test set, the conformance test and the catalog eval with its control, green, before it
was committed and pushed.

Not run here, by the brief's rule: the whole unit suite, the browser suite, `evals/run_all_mock.py`.

## 5. Deviations from the plan, and why

1. **`wardrobe_restore/{uid}` is never written.** The plan says the check keeps a token and its
   counts there for an hour. Here the token is a stateless MAC instead: it covers his id, the
   file's SHA-256, an expiry an hour on, and whether the wardrobe was empty at the check. So the
   check writes nothing at all, which is the literal acceptance test. Carrying "empty" in the
   token was needed: a restore cut after chunk 2 re-ran against a non-empty wardrobe and skipped
   the rest as "purged since" (the test caught it). Review A-1 accepted it and asked that
   "empty" can't be replayed (L2): the token's MAC now also covers his purge count. That count
   is the only thing `wardrobe_restore/{uid}` holds (sealed, `wardrobe` purpose), written in each
   purge's own commit and kept while the wardrobe is, not "a checked restore's token and counts,
   1 hour" as the plan's data model says (§6, item 15).
2. **QR codes are derived, not drawn at random and stored.** His code for label N is a keyed
   hash of (his id, N). So `GET /v1/wardrobe/labels.svg?sheet=N` writes nothing (a GET that
   writes can be triggered cross-site), and nobody can guess his codes. A label enters the sealed
   index only when he assigns it, and `resolve` still counts only his assigned labels. The limit
   is 600 labels (25 sheets of 24).
3. **"Remove" is an `archived` event in place.** It carries `via` "bin" and note "removed". The
   I0 `Piece` has no tombstone field, and the event keeps the change in the ledger.
   - Restoring from the bin adds `restored` (Missing or in review).
   - A purge drops the record, its pairs, sets and label, every log page, its photos and its
     fingerprints, in one commit. A purge does nothing to a piece that is no longer archived.
   - A merge's bin entry is `{ref, merge}`: its undo only drops the link, and purging it keeps
     the tombstone.
   - Accepted by review A-1 only with H2, now done: the entry is `{ref, ev}`, and it restores or
     purges only while that `archived` event is still the piece's newest applied state-setting
     event. A piece brought back with the retire card and archived on purpose since is his to
     keep (INV-17).
4. **The byte guard and the count.** 600 newly registered maximal pieces fit: 864 KB sealed.
   Maximal pieces with a full history (every field the fold sets, at its widest) fit at 500
   (842 KB), and the guard refuses them at 550 and 600 in plain words, never reaching Firestore's
   1 MiB. Both cases are tested.
5. **The vouch rule uses `locked`, with no new field.** A label he types on an untainted turn
   gets `"label"` in `locked`, and only results whose labels are all locked (or empty) vouch.
   A spoken label never vouches. A label or a place name proposed in a round that read other
   people's content is not saved: the piece is, without it, and the result says so.
6. **Resolved by review A-1: D10 wins.** `wardrobe_edit` no longer takes `query`; every write
   tool takes piece ids only, so D10's one allowed place in the needles (`laundry_move`,
   `wear_log`) stands. A move by his words is `wardrobe_find`, then `wardrobe_edit(piece=<id>,
   place=…)`: D's No-AI router does that at I1, and D6's wording is amended (§6, item 11).
7. **The scan route.** It refuses `registered`, `merged`, `corrected`, `archived` and `restored`
   (those are tools and cards). A device `at` without `sent` is taken as a stated time
   (30 days). A stated `day` is 12:00 his time, or now while that noon is still ahead (M5: a
   "today" in the morning is never refused as a time ahead). Review A-1 ruled that A wins; the
   I0 fake server's naive midnight changes at I1 (§6, item 13). A retry by client id is "Already done.",
   and a merged piece is a 409.
8. **Statuses when the part is off follow each row's list.** `GET /v1/wardrobe`, `/tag` and
   `/backup` answer 503. The routes whose list has no 503 answer 422 or 404, or an empty model
   (fingerprints, estimate, pilot, the sheet).
9. **The tools route opens a new conversation for each card.** `ToolCall` has no `session_id`,
   and an approval is decided inside a conversation (R11.1 `fix_plan`'s rule). See §6, item 5.
10. **The rewear rule is still copied in A's sweep, now EQUAL to C's.** Review A-1 rejected the
    copy as it was (C's `reusable` had `festive_layer`, A's did not). `jobs.WORN_AGAIN` now
    equals C's `rules.json` "reusable" (trousers, chinos, jeans, outerwear, the festive layer,
    footwear and accessories), pinned by value in `test_m8_…` (and against C's file once it is
    merged). The one source is I0's `states.py` at I1 (§6, item 7).
11. **The backup file is version 2** (L1). Its head carries the file's random id (`fid`); every
    line's AAD names it, and line 1's also binds the head's SHA-256, so "photos" can't be flipped
    and a line of another of his files does not open. R13 is not released, so no version 1 file
    exists outside tests, and none is read.
12. **`wardrobe_edit` can answer `status: "partial"`** (L8): every part is checked before the
    first commit, so this is only for a step that fails for a reason no check could see (a piece
    removed on his phone meanwhile). It lists what was `saved`, never "refused" after a write.
13. **A place named by his words is refused on a tainted round too** (M4), beside labels and set
    labels: a place's id still works there, and nothing of his reaches a card's arguments.

## 6. Needs I1 (exact diffs)

1. **`tests/test_r13_seams.py`**, `test_the_gate_is_staged_until_i1_and_a_stub_fails_once_it_flips`.
   The test uses `catalog` as its stub, and A is BUILT now:
   ```diff
   -    results, _ = asyncio.run(runner.run_parts(("catalog",), stubs_pass=False))  # type: ignore[attr-defined]
   -    assert [(r["id"], r["passed"]) for r in results] == [("catalog:not_built_yet", False)]
   +    results, _ = asyncio.run(runner.run_parts(("needles",), stubs_pass=False))  # type: ignore[attr-defined]
   +    assert [(r["id"], r["passed"]) for r in results] == [("needles:not_built_yet", False)]
   ```
   At I1, when `needles` is built, the test pins the flip instead.
2. **`tests/test_r13_wiring.py`**, `test_every_stub_part_builds_through_the_real_modules`.
   `_ctx` has `docs=None`, so A reads "Off: no document store on this server.":
   ```diff
   -    assert {p.ready for p in parts.values()} == {"not built yet"}
   +    assert wiring.SETUP_FAILED not in {p.ready for p in parts.values()}
   +    assert parts["catalog"].ready == "Off: no document store on this server."
   ```
3. **`tests/test_r13_wiring.py`**, `test_the_app_builds_the_four_parts_and_answers_v1_r13`.
   The test settings carry no token key, so A reads `OFF_NO_KEY`:
   ```diff
   -        assert [(p["part"], p["ready"]) for p in body["parts"]] == [
   -            (n, "not built yet") for n in PARTS
   -        ]
   +        assert [p["part"] for p in body["parts"]] == list(PARTS)
   +        assert all(p["ready"] != wiring.SETUP_FAILED for p in body["parts"])
   +        assert body["parts"][0]["ready"].startswith("Off: the wardrobe needs")
   ```
4. **The contract has no route for A's own settings**: AI tagging, private display and his
   types. All three are in his sealed index, and `tagging.update_settings` is built. A part can't
   add a route outside `ROUTES` (I0's contract eval would refuse it). Proposed for
   `wardrobe/http_views.py`, `http.py` and `ROUTES`:
   ```diff
   +class WardrobeSettingsIn(_M):
   +    """PUT /v1/wardrobe/settings: his own wardrobe settings (D7, D10)."""
   +
   +    ai_tagging: bool | None = None
   +    show_private: bool | None = None
   +    custom_types: tuple[str, ...] | None = Field(default=None, max_length=30)
   ...
   +    ("PUT", "/v1/wardrobe/settings", "catalog", WardrobeSettingsIn, SettingsView, (*_E, 422)),
   ```
   With it go the fake server row and A's route:
   ```python
   view = await tagging.update_settings(desk.store, uid, **body.model_dump())
   return ok(desk.views._settings(view))
   ```
   The plain settings change is logged with `record_change`.
5. **`ToolCall.session_id: str | None = None`** (in `http_views.py`). With it, a card from the
   panel waits in his open conversation instead of a new one. A's route then uses that session
   when it is his, as `fix_plan._conversation` does.
6. **Pilot, Part C's half.** Build the pilot as `PilotCounts(store, plan_counts=...)`, where C
   offers `plan_counts(uid) -> (suggested, unavailable)` from its plan log. A has no way to read
   C's sealed documents. A's two counts are 0 until then.
7. **The rewear rule in one place** (review A-1 M8). Put the default in I0's contract, beside
   `STATED_CHOICES` (the wear lifecycle is D3 data), not in either part:
   ```diff
   +# The rewear rule's default (D3, owner question 6): worn again, else to the laundry.
   +REWEAR_DEFAULT: frozenset[str] = frozenset({
   +    "trousers", "chinos", "jeans", "blazer", "jacket", "hoodie", "sweater", "coat",
   +    "rainwear", "festive_layer", "belt", "watch", "dress_shoe", "sneaker", "sandal",
   +    "slipper", "boot", "tie", "cap", "scarf", "jewellery", "bag", "eyewear",
   +})
   ```
   - A: `jobs.WORN_AGAIN = REWEAR_DEFAULT` (an import); `test_m8_…` then pins
     `WORN_AGAIN is REWEAR_DEFAULT`.
   - C: `rules.py` reads it, or checks at start that `frozenset(rules["reusable"]) ==
     REWEAR_DEFAULT` (and the part is "setup failed" otherwise). A never imports C's file.
   - Until then A's copy equals C's list (with `festive_layer`), pinned by value.
8. **The card-only kinds in one place** (H1's B half). B already refuses them on `r13-b`
   (`laundry/corrections.CARD_ONLY`, `history.to_correct`), with its own copy of A's
   `store.CARD_ONLY`; both are the same five kinds. Put one `CARD_ONLY` in `wardrobe/states.py`
   beside `STATE_SETTING`, and have A's store and B's two modules import it:
   ```diff
   +# Kinds only a card makes (D16, INV-17): a correction never voids one.
   +CARD_ONLY: frozenset[EventKind] = frozenset(
   +    {"registered", "archived", "restored", "merged", "corrected"}
   +)
   ```
9. **B's review writer** gets `ReviewNeeded("hold", piece, back_to=..., reason="sweep")` every
   morning for every held piece, and `reason="restore"` for a piece a restore brings back held
   (M3: one entry for the hold it is in now, never its old marks). It must add an entry only
   where none is open (D4.4's repair).
10. **C's settings**: the calendar, its fields, the lead, the alerts and auto-swap. The data
    model puts them in A's sealed index, but `Commit` can't write `settings`. Either C keeps
    them in its own document (`wardrobe_plans`), or I1 lets C call `store.rewrite`. This is
    flagged only; it is not A's to change.
11. **For D**:
    - The No-AI "I put my watch in the travel bag" (D6's PUT form) is TWO gateway calls, each on
      its row, with no model and no ₹: `wardrobe_find(query)`, then, when it names a single
      `best`, `wardrobe_edit(piece=<best>, place=…)`; otherwise the sentence asks which. The
      edit takes no `query` any more (deviation 6) and requires `piece`. D6's text says
      `wardrobe_edit(query, place)`: amend it to this.
    - The phone sends `how="match"` when his tap took candidate 1, and `how="tap"` with
      candidate 1's `score` when he took another. The pilot's match rate counts that.
    - The label sheet is `labels.svg?sheet=N`.
    - A label is stuck on with `POST /labels {code, piece}` and freed with `piece: null`.
    - Fingerprints come from `GET /fingerprints?model=`.
12. **The needles eval and M4's spoken rounds.** D10's single allowed place stays
    (`laundry_move`, `wear_log`). On a TAINTED round A now refuses, before any card, a label, a
    set label or a place named by words (M4). On a SPOKEN round every write is a card, so a
    spoken `wardrobe_add` `pieces[].label`, `wardrobe_edit` `label` / `set_label` or
    `wardrobe_places` `label` still sits in a card's stored arguments. Choose one at I1:
    - (a, recommended, private-by-default types at least) refuse them on a spoken turn too, in
      the same check: in `tools_write._own_words`, `if not (content_tainted() or
      spoken_in_context()): return`, with the words "Type its label in Helpers, Wardrobe";
    - (b) add those three fields to the needles' allowed places and to D10's text (Things'
      `put` precedent).
13. **The fake server's stated day** (review A-1 deviation 7: A wins), `tests/r13_fake_server.py`
    `_event`:
    ```diff
    -    at = e.stated_at or (datetime.combine(e.day, datetime.min.time()) if e.day else None)
    +    noon = datetime.combine(e.day, time(12), tzinfo=IST) if e.day else None
    +    at = e.stated_at or (min(noon, now) if noon is not None else None)
    ```
    D's browser tests then expect 12:00 his time, or now while that noon is still ahead.
14. **The size setting** (review A-1 deviation 4). `config.py` lets `wardrobe_max_pieces` go to
    600, but maximal pieces with full histories fit only to 500 (the byte guard refuses 550 and
    600 in plain words, before Firestore's 1 MiB). Recommended:
    ```diff
    -    wardrobe_max_pieces: int = Field(default=400, ge=50, le=600, description="Active pieces")
    +    wardrobe_max_pieces: int = Field(default=400, ge=50, le=500, description="Active pieces")
    ```
    or document that 550 to 600 fit only with sparser records.
15. **The guide's C69 row and the plan's data model**: `wardrobe_restore/{uid}` is "his purge
    count (sealed, `wardrobe`), kept while the wardrobe is: a restore token covers it" (L2), not
    "a checked restore's token and counts, 1 hour".
16. **Reviews**: review A-1 is done and committed (`REVIEW-A-1.md`). The fixes in this version
    want a fresh-context re-review before I1 merges A: `code-reviewer` and `python-reviewer`,
    and `security-reviewer` for the restore token and purge count, the backup head and file id,
    and the tainted-round refusals. I never review my own work.

## 7. Notes for B, C and D

- **B and C** can switch from `tests/r13_fakes_store.py` to A's store through
  `r13_fakes_a.conformance_store(docs, now)`. Their tests should run unchanged: it folds the same.
- A **pending deposit with no piece id** is B's: every A event names a piece (I0-NOTES 2.7).
- **B**: `store.correct` refuses the card-only kinds (`OWN_BUTTON`), as B's own `to_correct`
  does. A restore asks for one `hold` entry per piece held now, with `reason="restore"`.
- **B and C**: reading the logs of many pieces, pass the view you hold:
  `store.events(uid, piece, view=view)`.
- **C's engine** reads `Piece.eligible`, `expected_back` (from the latest `sent_out`), `wear`,
  `wears` and `last_worn` from A's view. `PieceChange.plan` is the wear's plan.
- **D's console** draws `GET /v1/wardrobe` exactly as the fake server does, with three
  differences:
  - pieces are sorted by category, type and id;
  - `next` is the next page's cursor, and the next page continues from that piece's place in
    the same order (H3);
  - `place_words` may end in "(last known)".
- **D's panel**: `wardrobe_edit` may answer `status: "partial"` with `saved` (L8). A restore
  card's condition is its own card ("Mark a black belt Ready", M7). The backup file is version 2
  (the fake server's `JWB1-fake` body is unaffected).

## 8. What I could not verify here

- CI's coverage floor (95) on its runners. My 93 % is for A's package alone.
- Firestore's real transaction limits and sizes. A restore chunk now closes at 50 pieces or
  about 8 MiB (L3): the pieces' sealed pages and photos, the index twice over and, with photos,
  every fingerprint shard at its fullest. The budget is an estimate, tested at a small limit on
  in-memory documents (every commit measured under it), not measured on Firestore.
- The backup's size estimate (L4) prices an event at 600 bytes, between a typical one (about
  400) and the widest (about 800). It is tested never to be under a real file; how early it
  refuses a real wardrobe of years is not known here.
- The models on his phone, the real match rates and his real backup sizes.
- `scripts/check_doc_versions.py` reads only `docs/plans/*.md`. I checked this file against the
  same rules as I0's notes; CI won't see it either.
- A whole-suite run, by the brief's rule.

## 9. Review A-1: the findings and their fixes

`REVIEW-A-1.md` v13.0.1 (16 Nov 2026, 10:01 IST), on `r13-a` @ `b8de963`. Each fix's test failed
first on the tree without it; each commit's exact tree then passed A's tests, the conformance
test and the catalog eval with its control (§4).

| ID | Fix | Test | Commit |
|---|---|---|---|
| H1 | `store.correct` looks the target up and refuses `CARD_ONLY` (registered, archived, restored, merged, corrected) in plain words | `test_h1_correct_refuses_the_card_only_kinds_so_an_archived_belt_stays_archived` | `95b64ae` |
| H2 | the bin entry is `{ref, ev}`; restore and purge act only while `ev` is the newest applied state-setting event (`CatalogBin._ours`, read through the commit's `tx`) | `test_h2_a_stale_bin_entry_never_purges_or_restores_a_piece_he_retired_since` | `2623d36` |
| H3 | paging continues from the cursor's place in the sorted list | `test_h3_paging_continues_from_the_cursor_so_260_pieces_each_show_once` (260 pieces, the real app) | `f4222fd` |
| H4 | the file's shards are opened once; each chunk merges only the entries of the pieces it adds that aren't private, through `Prints.merge_ops` in its own commit | `test_h4_a_restore_never_writes_back_a_private_or_unticked_pieces_fingerprint`, `test_h4_every_chunk_brings_back_its_own_pieces_fingerprints` | `c4a44e7` |
| M1 | the check and the estimate's reservation are one commit; settled to the recorded cost after the call, given back on `CantLook` or any failure; a spent cap refuses at an estimate of 0 | `test_m1_five_tags_at_once_never_pass_the_cap_each_reserved_then_settled`, `test_m1_with_no_price_for_the_brain_a_spent_cap_still_refuses` | `4ef3719` |
| M2 | pairs, sets, labels and places come back only with the pieces this restore adds (all of them into a wardrobe empty at the check); a piece never joins a second pair | `test_m2_a_restore_never_re_adds_a_pair_he_undid_or_a_place_he_removed` | `de5e1a1` |
| M3 | `as_stored`: no per-event asks; one `hold` for a piece held now (`reason="restore"`) | `test_m3_a_restore_asks_only_for_the_hold_each_piece_is_in_now` | `93a5c55` |
| M4 | the tainted half: `wardrobe_add`, `wardrobe_edit` and `wardrobe_places` refuse in `check`, before any card, a label, a set label or a place named by words; ids still work | `test_m4_a_tainted_round_never_puts_his_label_or_a_place_name_in_a_card` (and two existing tests moved to the refusal) | `8520bec` |
| M4 spoken | not A's alone: §6, item 12 | — | — |
| M5 | a stated day is `min(noon, now)` | `test_m5_a_stated_day_of_today_before_noon_is_saved_at_now_never_refused` (09:00 and 00:30 IST, the stored time asserted whole) | `f52d40c` |
| M6 | `events(uid, pid, view=)`; the backup, pilot, export, restore check, sweep and merge history pass the view they hold | `test_m6_each_whole_wardrobe_read_opens_the_index_once_not_once_a_piece` | `6eceb68` |
| M7 | a condition is its own card ("Mark a black belt Ready"); refused before any card while the piece is archived, and again at run time | `test_m7_a_restore_card_never_hides_a_condition_he_did_not_confirm` | `22c6c17` |
| M8 | A's half: `WORN_AGAIN` equals C's `reusable` (adds `festive_layer`); the single source is §6, item 7 | `test_m8_the_rewear_rule_is_exactly_parts_cs_reusable_list` | `65356e6` |
| L1 | the head carries `fid`; AAD `…/v1/{fid}/{n}`, line 1's also `|<SHA-256 of the head>`; file version 2 | `test_l1_the_head_is_bound_to_the_file_and_a_flipped_head_does_not_open`, `test_l1_a_line_from_another_of_his_files_does_not_open` | `89315e9` |
| L2 | the token's MAC covers his purge count (`purges.PurgeCount`, sealed in `wardrobe_restore/{uid}`, bumped in each purge's commit); a non-ASCII token is a plain refusal | `test_l2_a_forged_empty_digit_another_owners_or_an_odd_token_is_refused`, `test_l2_an_empty_check_replayed_after_a_purge_says_check_again` | `47affec` |
| L3 | a chunk closes at 50 pieces or `CHUNK_BYTES` (8 MiB) | `test_l3_a_chunk_closes_by_bytes_as_well_as_by_count` | `26ed8a1` |
| L4 | `Backup.estimate` (the index, every piece's events, and with photos the photo and fingerprint documents); every backup is checked, in words (`TOO_BIG_HISTORY`) | `test_l4_a_backup_the_restore_would_refuse_is_refused_in_words_without_photos_too` | `bb09ca6` |
| L5 | `asyncio.to_thread(parse, …)` in `check` and `apply` | `test_l5_the_file_is_parsed_off_the_event_loop` | `4e8b03f` |
| L6 | the estimate asks `eyes().state(uid)` (no model call) | `test_l6_with_the_ai_off_the_estimate_never_offers_the_button` | `85bd44e` |
| L7 | `places.UnknownPlace(names)`; `tools.failed` fences the names before the model sees them; his panel keeps plain words | `test_l7_his_place_names_reach_the_model_only_inside_a_fence` | `caefd7a` |
| L8 | the place, the label code, the pair and the set are checked before the first commit (`links.pair_refusal`, `links.set_refusal`); a later failure answers `partial` with `saved` | `test_l8_an_edit_a_later_part_refuses_writes_nothing_at_all`, `test_l8_a_step_that_fails_after_a_write_says_what_was_saved` | `5efe1fe` |
| L9 | a code in his index is his whatever today's key draws; merging into a private piece drops the other's photos and fingerprints in the same commit; INV-14 asserts the step between | `test_l9_a_label_already_his_moves_and_frees_after_a_key_change`, `test_l9_merging_into_a_private_piece_drops_the_others_photos_and_fingerprints`, `test_inv14_…` | `f4b3b21` |
| Dev. 6 | `wardrobe_edit` drops `query` (D10 wins) | `test_dev6_a_move_by_his_words_is_a_find_then_an_edit_by_id_never_a_query` | `e078ddd` |

Declined: none. Not A's (listed in §6): M4's spoken rounds (item 12), M8's single source (7), H1's
single source with B (8), the fake server's day (13), the size setting (14).

## Change log

| Version | Date | Release | What changed | By |
|---|---|---|---|---|
| v13.0.2 | 16 Nov 2026, 11:50 IST | R13 | The fixes of review A-1 (`REVIEW-A-1.md`), each test first and one commit each: H1–H4, M1–M7, M8's A half, L1–L9 and deviation 6 (D10 wins: `wardrobe_edit` takes piece ids only); §9's findings table (ID, fix, test, commit); §1, §2, §3 and §4 brought up to date (160 A tests, 93 %, the catalog eval 19/19 with its control failing); §5's deviations 1, 3, 6, 7 and 10 updated and 11–13 added; §6's Needs I1 updated (the rewear rule's and the card-only kinds' single source in `states.py`, M4's spoken rounds, the fake server's day, the size setting, C69's `wardrobe_restore` row, a re-review); §7 and §8 extended | 🛠 Mark XXI |
| v13.0.1 | 15 Nov 2026, 21:30 IST | R13 | First edition, written at the end of Part A: the services A offers (only `store`, `photos`, `bin`; the rest through `store.desk`), the use-case table with its named tests, the files and their sizes, the checks with their numbers (132 A tests, 93 % covered, the catalog eval 19/19 with its controls failing INV-05, INV-08 and OPS-03), ten deviations with their reasons, twelve "Needs I1" items with exact diffs, notes for B, C and D, and what could not be verified here | 🛠 Mark XXI |
