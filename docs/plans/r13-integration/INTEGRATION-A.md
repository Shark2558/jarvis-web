Version v13.0.1 · 15 Nov 2026, 21:30 IST · Release R13 · Status: Current · Owner: 🛠 Mark XXI

# R13 Part A: Catalog and the ledger (INV-01 to INV-17, OPS-03, OPS-06)

Builder A's report for I1. Branch `r13-a`, cut from `r13-i0` @ `3bf2cb1`. I built against
`BRIEF-COMMON.md`, `I0-NOTES.md`, the plan `r13-wardrobe.md` v13.0.2 (Part A, D2, D4, D7, D9,
D16, D17, plan review H3 and H4, the M items) and the repository's rules. I edited no wiring
file and no shared file. Everything A owns is in `src/jarvis/wardrobe/catalog/`,
`src/jarvis/api/wardrobe.py`, `tests/test_r13_a_*.py`, `tests/r13_fakes_a.py` and
`evals/r13/catalog.py`.

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
  - `events(uid, piece)` returns the raw log. `history`, `correct` and `bind` follow the
    contract.
- **`photos`**: `catalog.photos.PhotoVault` (`count`, `delete_all`, plus `save`, `get`, `delete`
  and `prints` for the routes).
- **`bin`**: `catalog.undo.CatalogBin`, the restorer and purger for `wardrobe_item`.
- **No other service name** is offered. A's routes reach everything else through `store.desk`
  (`catalog.part.Desk`).
- **Tools**: the eight `wardrobe_*` tools, all agent `wardrobe`, none `spoken_ok`, none
  trusted. `wardrobe_merge` and `wardrobe_retire` use `ask_when` and always become a card.
  `wardrobe_remove` is `undoable`.
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
| INV-17 | `tools_life.retire` (archive and restore are cards every time; restore reuses the id and asks the condition) | `test_inv17_…` |
| OPS-03 | `fold.py`, the pure, order-independent fold: superseded, duplicate, conflict, held, voided, known; `settle`, the one time rule; `store.py`, one commit, never overwriting what it can't open | I0's conformance (21 on A), `test_as_fold_agrees_with_the_reference_on_500_seeded_histories`, store tests, route scan tests |
| OPS-06 | `backup.py` (sealed line by line, streamed, photos only when ticked, refused in words over 25 MB) and `restore.py` (the check writes nothing, then chunks of 50, idempotent) | `test_ops06_…` (3, one through the real app with a 3 MB file and a 31 MB refusal), 11 more in `test_r13_a_backup.py` |

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
| `wardrobe/catalog/store.py` | 393 | ≤ 400 (the largest) |
| `wardrobe/catalog/tools_write.py` · `edits.py` · `photos.py` · `restore.py` · `routes_files.py` · `tagging.py` | 305 · 268 · 236 · 234 · 249 · 245 | ≤ 400 |
| the other 23 modules under `wardrobe/catalog/` | 2 to 208 | ≤ 400 |
| `api/wardrobe.py` | 289 | ≤ 800 (≤ 400 kept) |
| `tests/test_r13_a_*.py` (9 files) · `tests/r13_fakes_a.py` · `evals/r13/catalog.py` | 149 to 355 · 198 · 356 | ≤ 800 |

Every function is at most 50 lines (checked with `ast`). Nothing under `wardrobe/` reads the real
clock (I0's static test passes).

## 4. The checks (Python 3.11, `/tmp/venv-b`, heavy runs behind `/tmp/heavy.lock`)

| Check | Result |
|---|---|
| A's tests, `tests/test_r13_a_*.py` | **132 passed** (store 15, catalog 25, lifecycle 15, photos 17, jobs 12, tagging 13, backup 14, routes 13, edges 8) |
| `tests/test_r13_fold_conformance.py` | 44 passed (23 memory, 21 on A's store) |
| Coverage of `jarvis.wardrobe.catalog` + `jarvis.api.wardrobe` (A's tests + conformance) | **93 %** (2,832 statements, 207 missed; lowest: `routes_files.py` 66 %, `merge.py` 87 %) |
| `test_r13_seams.py`, `test_r13_wiring.py`, conformance, `test_telegram_tool_guard.py` | 362 passed, **3 failed**: the three I0 pins that expect A to be "not built yet" (§6, items 1–3) |
| `test_r14_skill_coverage.py`, `test_permissions_policy.py`, `test_r11_1_b_guard.py`, `test_telegram_personal_reads.py` | 395 passed |
| `evals/r13/run.py --mock --part catalog` | **19/19**; the controls fail exactly `catalog:INV-05` (candidates off), `catalog:INV-08` and `catalog:OPS-03` (the dedup off) |
| `evals/r13/run.py --mock` (every part) | 37/37, the combined control failing the suite |
| `ruff check` · `ruff format --check` (my 43 files) | clean |
| `mypy src` | 1 error: the baseline's (`memory/redis_store.py:67`) |
| `scripts/arch_coverage.py` | OK (66 packages/modules, 110 Firestore collections) |
| `scripts/check_doc_versions.py` | this file follows the rules (it lives in a sub-folder, like I0's notes; see §8) |

Not run here, by the brief's rule: the whole unit suite, the browser suite, `evals/run_all_mock.py`.

## 5. Deviations from the plan, and why

1. **`wardrobe_restore/{uid}` is never written.** The plan says the check keeps a token and its
   counts there for an hour. Here the token is a stateless MAC instead: it covers his id, the
   file's SHA-256, an expiry an hour on, and whether the wardrobe was empty at the check. So the
   check writes nothing at all, which is the literal acceptance test. Carrying "empty" in the
   token was needed: a restore cut after chunk 2 re-ran against a non-empty wardrobe and skipped
   the rest as "purged since" (the test caught it). The collection stays named in C69. I1 may
   keep it as planned-unused or drop it.
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
4. **The byte guard and the count.** 600 newly registered maximal pieces fit: 864 KB sealed.
   Maximal pieces with a full history (every field the fold sets, at its widest) fit at 500
   (842 KB), and the guard refuses them at 550 and 600 in plain words, never reaching Firestore's
   1 MiB. Both cases are tested.
5. **The vouch rule uses `locked`, with no new field.** A label he types on an untainted turn
   gets `"label"` in `locked`, and only results whose labels are all locked (or empty) vouch.
   A spoken label never vouches. A label or a place name proposed in a round that read other
   people's content is not saved: the piece is, without it, and the result says so.
6. **`wardrobe_edit` takes `query` only for a move** (`query` + `place`), as D6 and D20 say.
   D10 and `ports.QUERY_TOOLS` name only `laundry_move` and `wear_log`. If such a call becomes a
   card, his words sit in its stored arguments: see §6, item 11.
7. **The scan route.** It refuses `registered`, `merged`, `corrected`, `archived` and `restored`
   (those are tools and cards). A device `at` without `sent` is taken as a stated time
   (30 days). A stated `day` is 12:00 his time; the I0 fake server uses midnight, so D's
   browser tests will see a different time at I1. A retry by client id is "Already done.",
   and a merged piece is a 409.
8. **Statuses when the part is off follow each row's list.** `GET /v1/wardrobe`, `/tag` and
   `/backup` answer 503. The routes whose list has no 503 answer 422 or 404, or an empty model
   (fingerprints, estimate, pilot, the sheet).
9. **The tools route opens a new conversation for each card.** `ToolCall` has no `session_id`,
   and an approval is decided inside a conversation (R11.1 `fix_plan`'s rule). See §6, item 5.
10. **The rewear rule is copied in A's sweep.** It is `jobs.WORN_AGAIN`: trousers, chinos and
    jeans, outerwear, footwear and accessories are worn again; everything else goes to the
    laundry. C's `rules.json` owns the rule. See §6, item 7.

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
7. **The rewear rule in one place.** A's sweep should import C's rule from `rules.json` in place
   of `jobs.WORN_AGAIN`, which uses the same defaults.
8. **B's review writer** gets `ReviewNeeded("hold", piece, back_to=..., reason="sweep")` every
   morning for every held piece. It must add an entry only where none is open (D4.4's repair).
9. **C's settings**: the calendar, its fields, the lead, the alerts and auto-swap. The data
   model puts them in A's sealed index, but `Commit` can't write `settings`. Either C keeps them
   in its own document (`wardrobe_plans`), or I1 lets C call `store.rewrite`. This is flagged
   only; it is not A's to change.
10. **For D**:
    - The phone sends `how="match"` when his tap took candidate 1, and `how="tap"` with
      candidate 1's `score` when he took another. The pilot's match rate counts that.
    - The label sheet is `labels.svg?sheet=N`.
    - A label is stuck on with `POST /labels {code, piece}` and freed with `piece: null`.
    - Fingerprints come from `GET /fingerprints?model=`.
    - For the No-AI "I put my watch in the travel bag", prefer `wardrobe_find`, then
      `wardrobe_edit(piece=id, place=…)`. That keeps his words out of a card's stored arguments.
11. **The needles eval**: either allow `wardrobe_edit`'s `(query, place)` card arguments as a
    second allowed place beside D10's, or have D's router resolve the piece first (item 10).
12. **Reviews**: `security-reviewer` is required for photos, the backup seal and the restore,
    and the tag call. `code-reviewer` and `python-reviewer` too. None was run by me: I never
    review my own work. They should run in a fresh context on `r13-a`.

## 7. Notes for B, C and D

- **B and C** can switch from `tests/r13_fakes_store.py` to A's store through
  `r13_fakes_a.conformance_store(docs, now)`. Their tests should run unchanged: it folds the same.
- A **pending deposit with no piece id** is B's: every A event names a piece (I0-NOTES 2.7).
- **C's engine** reads `Piece.eligible`, `expected_back` (from the latest `sent_out`), `wear`,
  `wears` and `last_worn` from A's view. `PieceChange.plan` is the wear's plan.
- **D's console** draws `GET /v1/wardrobe` exactly as the fake server does, with three
  differences:
  - pieces are sorted by category, type and id;
  - `next` is the next page's cursor;
  - `place_words` may end in "(last known)".

## 8. What I could not verify here

- CI's coverage floor (95) on its runners. My 93 % is for A's package alone.
- Firestore's real transaction limits and sizes. A chunk of 50 pieces with full histories is
  estimated well under 10 MiB, not measured.
- The models on his phone, the real match rates and his real backup sizes.
- `scripts/check_doc_versions.py` reads only `docs/plans/*.md`. I checked this file against the
  same rules as I0's notes; CI won't see it either.
- A whole-suite run, by the brief's rule.

## Change log

| Version | Date | Release | What changed | By |
|---|---|---|---|---|
| v13.0.1 | 15 Nov 2026, 21:30 IST | R13 | First edition, written at the end of Part A: the services A offers (only `store`, `photos`, `bin`; the rest through `store.desk`), the use-case table with its named tests, the files and their sizes, the checks with their numbers (132 A tests, 93 % covered, the catalog eval 19/19 with its controls failing INV-05, INV-08 and OPS-03), ten deviations with their reasons, twelve "Needs I1" items with exact diffs, notes for B, C and D, and what could not be verified here | 🛠 Mark XXI |
