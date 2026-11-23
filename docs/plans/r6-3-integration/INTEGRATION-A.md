Version v6.3.1 · 23 Nov 2026, 19:10 IST · Release R6.3 · Status: Current · Owner: 🛠 Mark XXIV

# R6.3 — Part A's integration notes: the fact pack and the generator

Part A of R6.3 (`docs/plans/r6-3-book-content.md` v6.3.3: D2, D2a, D2b, D3, D10's G3–G8), built on
`r6-3-a` from `r6-3-i0` @ `d25dbcc` by the Workshop (🛠 Mark XXIV). Briefs: `BRIEF-COMMON.md`,
`BRIEF-A.md`. A first builder was stopped by a server restart after three commits (the scrubber's
kinds and phrases, the counter, and a `wip` of the pack and the pages index); this builder checked
that `wip` against the brief, fixed it and finished the part.

## 1. The plan (written before the code)

Already on the branch: `gen/scrub.py` (G8, M8; `tests/test_r63_scrub_kinds.py` green, its `xfail`
marks removed), `gen/loc.py` (D2a, G6), and the `wip`: `gen/facts.py` with its helpers
`facts_code.py`, `facts_guide.py`, `facts_routes.py`, `facts_values.py`, `gen/pages_index.py`,
`gen/plans.py` (G4) and their tests. Order of the rest, each test written before its code:

1. Fix the `wip`: the release day in the book's own form ("23 Nov 2026", D asks for it), and the
   tour's 30 keys all or none (a fixture repository gives none, so D's "some but not all is a
   `GenError`" never stops R6's fixture builds). Tests: `test_r63_a_facts_units.py`.
2. G7, `gen/costs.py`: GitHub Actions on a public repository Unverified; Firestore's daily free
   reads, writes and deletes. Test: `test_r63_a_book.py`.
3. G3, `gen/code.py`: the book's integrations name every one of the coverage checker's 31
   services. Test: `test_r63_a_book.py`.
4. D2b and G5, `gen/inventory.py` (new): Android, the home kit's images, the bridge's pins, the dev
   tools, one SPDX spelling a licence, the run-time / build-and-maintenance split. Test:
   `test_r63_a_inventory.py`.
5. The eval `evals/r6_3/facts.py`: the plan's `facts` cases and every control of BRIEF-A §4.
6. Verify once at the end (the owner's rule of 23 Nov): A's tests and the seam tests, `--check` on
   the real repository, ruff and mypy on A's files, the eval; then this file.

## 2. What was built

| File | Lines | What |
|---|---|---|
| `gen/facts.py` | 213 | `build(repo, scrub, *, modules=MODULES, services_table=None) -> FactPack` (release and pages left to the join); `all_or_none` (the tour's 30 keys); `limitations` (all, G4) |
| `gen/facts_code.py` | 198 | every `src/jarvis` module parsed once; literal module constants (H5), top-level symbols, `Settings` with defaults and bounds, collections |
| `gen/facts_routes.py` | 331 | M9: every `APIRouter(...)` / `FastAPI(...)` by AST, whatever its name, prefixes resolved through constants and imports, `add_api_route` in loops, the writer's `ROUTES` table |
| `gen/facts_guide.py` | 209 | the guide's cards, "Where in the code" through `gen/refs.resolve`, scrubbed; the 22 panels and the show; §11's roadmap rows |
| `gen/facts_values.py` | 278 | the tour's 30 keys from their plan sources; hosting facts `verified=False` |
| `gen/pages_index.py` | 198 | D3: 8 chapters, 18 modules, 73 cards under their modules, 23 screens, 31 services |
| `gen/loc.py` | 311 | D2a, G6 (the first builder's commit) |
| `gen/inventory.py` | 293 | new: D2b's rows, `spdx`, `USE`, and R6's Stack moved here from `libs.py` |
| `gen/scrub.py` | 392 | G8's kinds, M8's phrases (first builder), and a four-part version is not an IPv4 address |
| `gen/code.py` | 376 | G3: one row for each checker service the plain rows don't stand for; `inventory_names` (cached), `slug`, `service_owners`, `services_named` |
| `gen/libs.py` | 376 | G5: every licence spelled once; Stack re-exported from `inventory` (was 475) |
| `gen/costs.py` | 236 | G7: Firestore's daily reads, writes, deletes; GitHub Actions Unverified |
| `gen/plans.py` | 280 | G4: `limitations(read, cap=None)` gives every one |
| `evals/r6_3/facts.py` | 400 | the `facts` suite, `BUILT = True` |
| tests | | `test_r63_a_{book,facts_real,facts_units,inventory,loc,pages,scrub}.py`, `tests/r63_fakes_a.py`; `test_r63_scrub_kinds.py` green with no `xfail` |

**The pack on this branch** (measured with `facts.build` and the join at `75385c4`): `facts.json`
**1,004,429 bytes** (95.8 % of the 1 MiB cap: index 487,651, values 223,370, pages 128,318,
limitations 56,570, routes 44,177, cards 30,344, settings 14,364, loc 9,620, screens 5,876);
1,760 values (1,563 constants in 510 files, 154 settings' defaults of 179 settings, the 30 tour
keys, A's 7 counts, 6 hosting facts, all `verified=False`); index: 2,842 paths, 6,897 symbols, 120
collections, 508 routes; 18 modules, 73 cards, 23 screens, 31 services, 310 limitations, 81 line
counts; **153 pages**. The tour keys read: R6.3, v6.3.0, 23 Nov 2026 (the commit's IST day), "The
Build Book: written by AI, short tour and full book", 73, 18, 11, "129 thousand", 8, Claude Sonnet
5.5, 30, 26, 31, 5, 12, 20, 10, 180, 6, 2, 5, 5, "112", 6, ₹9, ₹300, 67, 95.24, "R6.3.1, the Build
Book's pictures and storage", "R6.4, the Book's new look". `book.json` 211,741 bytes (I0: 204,818):
23 integration rows naming all 31 services, 23 inventory rows in the Stack.

## 3. The checks (once, at the end, behind `/tmp/jarvis-heavy.lock`)

| Check | Result |
|---|---|
| `tests/test_r63_a_*.py`, `test_r63_scrub_kinds.py` | 118 tests (book 6, facts_real 9, facts_units 21, inventory 16, loc 13, pages 7, scrub 32, scrub_kinds 14), all passed in the run below |
| `tests/test_r63_*.py tests/test_book_*.py` (Python 3.11) | **1,117 passed, 5 skipped, 2 failed**: both pins this part moves (§5.1, §5.2) |
| `evals/r6_3/run.py --mock --part facts` | 14/14 cases; the control failed the suite, each of the 7 controls turning its own case red (checked one by one: two processes differ; `ipv4`; "cards in no module: C69"; verify refuses 138 places; 3 app routes missing; "no C74 page"; "cards in no module: C69-C73") |
| `python -m jarvis.buildbook.gen --check` (this checkout) | two builds byte-identical: book.json 211,741, facts.json 1,004,429, source.zip 10,111,819 bytes, 36.4 s |
| `--check` on the fixture | the eval's `check_twice_identical` (`write.check` on A's fixture, and facts.json across two hash seeds) |
| `ruff check`, `ruff format --check` (A's 23 Python files) | clean |
| `mypy src` | the one baseline error only (`memory/redis_store.py:67`) |
| `scripts/arch_coverage.py`, `scripts/check_doc_versions.py` | OK (66, 108, 2, 31, 120); 31 documents |
| sizes | every A module ≤ 400 lines, every function ≤ 50 |

## 4. Deviations, and what the brief or plan got wrong

- **The tour's keys are all or none** (`facts.all_or_none`). I0's `FIXTURE_FACTS` carries some
  tour keys, and part D refuses a pack with some but not all (D's decision 2), so every R6 test
  that builds a fixture's book would fail at I1. With all or none a fixture builds no tour, and a
  key whose source this repository loses drops the tour, never the book (CI's
  `test_row380_every_tour_key_is_known` fails).
- **153 pages, not 152:** the plan's sum counts 22 screens; the 22 panels and the show are 23.
- **facts.json is 1.00 MB, not ≈ 0.6 MB** (the index alone is 488 KB, the plan said 383 KB): see §5.4.
- **`loc.python_code` is "129 thousand"** (plan 124,475): on `47ee8fc` the counter gives 126,078
  (the plan counted a string alone inside brackets as docstring); I0 added code since.
- **1,563 constants in 510 files** (plan 1,461 in 506 on `47ee8fc`).
- **`release.date` is "23 Nov 2026"** (`show.human_date` of the commit's IST day), D's form.
- **`sos.emergency` is the string "112"**, the code's own literal; D's `PLAN_VALUES` has the integer.
  Both fill "112".
- **D2b's rows are in book.json's Stack, not its Libraries.** `sections.Library.kind` is a closed
  Literal (python, vendored, model, font) and show scene 9 says "N Python libraries and M vendored
  pieces" by kind, so Android libraries or Docker images there would make its words false. The
  Stack's rows (role, name, version, source) carry them with R6's rows unchanged; the licences and
  the uses are in `inventory.items` and its eval case, not in book.json (§5.6).
- **G3: 23 rows naming the 31, not 31 rows.** The 15 rows in plain words (`buildbook/plain.py`,
  R6's pins) each stand for several of the checker's names ("Google sign-in, Gmail and
  Calendar"); one row is added for each name none stands for (8).
- **G8 was too wide:** the four-part version `4.12.0.88` (opencv, a bridge row) read as an IPv4
  address, so `--check` refused the book. A private, shared or link-local address is always
  found; a global one in a version's place stays.
- **Files beyond the brief's list, all A's own:** `gen/facts_{code,guide,routes,values}.py`
  (`facts.py` split for the 400-line rule); R6's Stack code moved from `libs.py` into
  `inventory.py` (libs.py was 475 lines before R6.3).
- **Licences not stated:** the home kit's images, the Android build plugins, the dev extra and
  three bridge pins state no licence in their own files, so they read "not stated" (nothing typed).
- **Not run red first:** the tests after the restart were written before their code but, by the
  owner's rule of 23 Nov (no repeated runs), run once at the end with the seam tests (fast unit
  files were run once while fixing). No self-review agents (the same rule).

## 5. Needs I1 (exact diffs)

**5.1 I0's stub pin moves** (`tests/test_r63_gen_joins.py`): A's pack is no longer empty.

```diff
-def test_the_stubs_give_an_empty_pack_no_pages_and_no_tour(fx: Repo) -> None:
+def test_a_fixture_s_pack_has_no_tour_keys_and_its_eight_chapters(fx: Repo) -> None:
     built = write.build(fx, OPTS)
     pack = load_facts(built.facts)
-    assert pack.values == {} and pack.pages == () and pack.release == built.release.ref()
+    assert not set(FACT_TOUR_KEYS) & set(pack.values) and pack.release == built.release.ref()
+    assert [p.id for p in pack.pages] == [f"pg_chapter_{c}" for c, _ in CHAPTERS]
     assert load_book(built.book).tour is None
```
(with `FACT_TOUR_KEYS, CHAPTERS` imported from `jarvis.buildbook.facts_model`).

**5.2 R6's scrub pin moves with G8** (`tests/test_book_gen_scrub.py:180`):

```diff
-        "Ports 8080 and 8098; 127.0.0.1 and 192.168.1.10; 512 MiB, 1 GiB, 15 MB.",
+        "Ports 8080 and 8098; 127.0.0.1; 512 MiB, 1 GiB, 15 MB.",  # R6.3 G8: 192.168.1.10 is found
```

**5.3 `FIXTURE_FACTS` against what `facts.build` computes for `fixture_repo`** (B builds on
`FIXTURE_FACTS` and needs no change). Only in I0's: `cards.count`, `modules.count`,
`release.label` (tour keys: all or none), `hosting.region` (no `deploy/cloudrun.sh`), the route
`GET /v1/demo` and the collection `demo_notes` (no file declares them). Only in A's: the symbol
`src/jarvis/config.py:Settings`, A's counts (`routes.count`, `settings.count`,
`collections.count`, `screens.count`, `constants.count`, `limitations.count`,
`limitations.shown`), the fixture plan's limitation, four line counts, all 8 chapters and
`pg_service_firestore`; `pg_chapter_example` has no refs or sources (its cards C05… aren't in the
fixture); `pg_module_demo`'s refs are sorted. To make them equal, add to `FIXTURE_FILES`
`deploy/cloudrun.sh` (`REGION="${REGION:-asia-south1}"`), a router (`router =
APIRouter(prefix="/v1/demo")` with `@router.get("")`) and `COLLECTION = "demo_notes"`, drop the
three tour keys from `FIXTURE_FACTS` and take its pages from `pages_index.build`.

**5.4 facts.json's headroom.** 1,004,429 bytes is 95.8 % of `FACTS_JSON_CAP_BYTES` (1 MiB); B's,
C's and D's files add paths, symbols and constants at I1, and a release that grows past the cap
gets NO book (`GenError`; best effort writes the error). Measure after the merge, and choose one:

```diff
 # src/jarvis/buildbook/facts_model.py
-FACTS_JSON_CAP_BYTES = 1 * MIB
+FACTS_JSON_CAP_BYTES = 2 * MIB
```
(the plan's and BRIEF-COMMON's size guard say 1 MiB), or `canonical_facts` dumping with
`exclude_defaults=True` (about 28 KB of `"verified":true`; it changes the bytes' form, so pin it).

**5.5 Part D (its 5.5).** Run `tests/test_r63_d_*.py`, D's browser file and `--part tour` on A's
real pack, then `--check` with a tour. A's forms: `release.date` "23 Nov 2026" (the commit's IST
day), `loc.python_code` "129 thousand" (no "about"), `seeme.inr_a_picture` "₹9",
`seeme.month_cap_inr` "₹300", the roadmap rows above, `sos.emergency` "112" as a string. R6's
`book_gen_fakes.fixture_repo` builds: it gets no tour key (all or none), so D's decision 2 never
trips there.

**5.6 If the owner wants the inventory's licences in book.json** (optional), in
`buildbook/sections.py`:

```diff
 class StackItem(Frozen):
     role: str = Field(max_length=40)
     name: str = Field(max_length=80)
     version: str = Field(default="", max_length=40)
     source: str = Field(max_length=160)
+    licence: str = Field(default="", max_length=80)  # R6.3 D2b: the inventory's rows
```
with `inventory.stack` passing `licence=i.licence`, left out of the bytes when "" (47ee8fc's book
must still round-trip, as `Book.tour` is), and the reader's Stack row showing it.

**5.7 Book content changes A makes by design** (G3, G5, G7): 8 more integration rows, 23 more
Stack rows, licences spelled once, Firestore's and GitHub's free-tier words. The look is
unchanged, but the Book panel's Integrations, Stack, Libraries and Costs sections hold more rows
than `47ee8fc`'s: C's and the exit check's "screenshots with the writer off unchanged" should
compare the look, not these sections' row counts.

**5.8 I0's list, item 2:** `test_r63_scrub_kinds.py` has no `xfail` left; the phrase rule is in,
so the `needles` suite's phrase stand-ins should now be caught.

## 6. What could not be verified here

- GitHub Actions on a public repository (marked Unverified, as Phase A says) and Firestore's free
  numbers (taken from the guide's §6.5 row): not checked live.
- The licences the home kit's images, the build plugins and the dev tools carry (their files
  don't say).
- Part D's tests on A's real pack (D's branch isn't merged here), and the Python 3.11 whole suite
  (CI's, by the owner's rule).

## Change log

| Version | Date | Release | What changed | By |
|---|---|---|---|---|
| v6.3.1 | 23 Nov 2026, 19:10 IST | R6.3 | First edition: part A's plan (written before the rest of its code), what was built, the pack on this branch, the checks with their numbers, the deviations and what the brief or plan got wrong, "Needs I1" with exact diffs, what could not be verified | 🛠 Mark XXIV |
