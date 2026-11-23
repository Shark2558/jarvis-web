Version v6.3.3 · 24 Nov 2026, 01:35 IST · Release R6.3 · Status: Current · Owner: 🛠 Mark XXIV

# R6.3 — I1 notes (the four parts joined)

Written by the R6.3 I1 integrator (the Workshop, 🛠 Mark XXIV) on `r6-3-i1`, cut from `r6-3-i0` @
`b377b29`. Merged with `--no-ff` in this order, all with no conflicts: A `ec911fb` (`4ac0a4b`), B
`456be03` (`d079fd5`), C `40ac76c` (`1f221c3`), D `d529b9a` (`e5d14a9`). `main` is not merged
here.

Sources: the four `INTEGRATION-<X>.md` files ("Needs I1": A §5, C §5, D §5; B's file holds only
its plan, so B's list is its two "I1" notes in the code, `writer/prompts.py` and
`test_r63_b_rows.py`), `I0-NOTES.md` §5, the plan `docs/plans/r6-3-book-content.md` v6.3.3
("Tests and evals", "Exit check") and the Workshop's list for I1.

States: **done** (commit), **declined** (the reason), **left** (for the combined reviews, the
Workshop, the owner or a later release, with the reason). "Red first" means the test was run and
failed for the stated reason before the change; "a pin" means a test of behaviour the joined parts
already had.

## Items

1. **A join bug the merge showed** (not in any part's list). Done `5e020fd`: the generator
   refused the book on the joined branch, because part A's AST route scan (M9) reads a router's
   prefix and a loop's routes table by name, and part B's `api/book_writer.py` and
   `api/book_pages.py` used `http.WRITER_PREFIX`, `http.PAGES_PREFIX` and `http.ROUTES`. Both now
   import the names, as I0's stubs did. Red first: `facts.build` on this checkout raised
   `GenError` at `api/book_pages.py:32`.
2. **facts.json's headroom** (INTEGRATION-A 5.4). Done `419af45`, red first: after the join the
   pack is 1,018,018 bytes, 97.1 % of I0's 1 MiB cap, and an overflow means no book. **Chosen:
   the cap is 2 MiB** (`facts_model.FACTS_JSON_CAP_BYTES`) **with a warning from 80 %**
   (`FACTS_JSON_WARN_BYTES` = 1,677,722 bytes): the generator says "build book warning:
   facts.json is N bytes, over 80 % of its 2 MiB cap" on stderr (sizes only), and `load_facts`
   refuses past 2 MiB. Slimming was not clearly simpler: `exclude_defaults` saves about 28 KB and
   changes the file's form. The plan's and BRIEF-COMMON's "facts.json ≤ 1 MiB" size guard is
   superseded by this item. On the final commit the pack is 1,020,731 bytes (48.7 %).
3. **A's stub pins** (INTEGRATION-A 5.1, 5.2). Done `419af45`: I0's empty-pack pin is now A's
   fixture pack (no tour key, its eight chapters); R6's scrub pin in `test_book_gen_scrub.py`
   drops `192.168.1.10`, which G8 now finds.
4. **`FIXTURE_FACTS` against A's real values** (INTEGRATION-A 5.3). Done `80af7ed`: I0's fixture
   repository now holds the sources of what `FIXTURE_FACTS` names (the demo's route in
   `routes.py`, its collection in `stores.py`, `deploy/cloudrun.sh`'s region), so A computes the
   same route, collection and `hosting.region`; A's comparison test asserts them equal instead of
   pinning the gap. Left by design (said in the test): `FIXTURE_FACTS` keeps three tour keys that
   B's filler tests fill (a mix A never makes: all or none) and its hand-written pages; the `e2e`
   suite runs B on A's own pack instead (item 14).
5. **The tour gets the show** (INTEGRATION-D 5.1). Done `419af45`, red first:
   `gen/write.py` passes `show=` to `tour.build`; the join pin records it; I0's empty-script pin
   is now D's 17 scenes.
6. **B's message type** (B's note in `writer/prompts.py`). Done `934f365`, red first: the import
   guard (`test_r63_static.py`) allows `jarvis.llm.base` for `ChatMessage` ONLY, and a new test
   refuses any other name from it and any `vars()` call in the writer's files; `prompts.py`
   imports `ChatMessage` instead of `vars(write)["base"]`.
7. **mypy** (not in any list). Done `934f365`: the join had 14 new errors from part B. The
   writer's context types its source as `FactSource` (R6's `BookSource` plus `facts()`, in
   `writer/ports.py`; both wirings pass it), five values are typed with their Literal, privacy's
   count is an `int`, `part.py` names `PagesFile` from the model. `mypy src`: the baseline only.
8. **C's seam pin and I0's fake words** (INTEGRATION-C 5.1, 5.3). Done `2778cde`: the console
   seam pins C's two modules' exports; I0's fake server writes ₹ (never "Rs") in a grant's words,
   as B's real words do, so C's child-process patch `rupee_words` is gone.
9. **The 2D and 3D redraw** (INTEGRATION-D 5.2, the visible bug). Done `e352e63`: both modules
   key a drawn scene by picture AND scene id, so T13–T15 (picture 9 after T12) draw their own
   data, not T12's; D's diff exactly, its `xfail(strict)` removed (D's browser file: the redraw
   case passes at both sizes). Pictures: the list below.
10. **T16 spoken with his honorific** (INTEGRATION-D 5.3). Done `e352e63`:
    `show_script.line_text` passes the script's own words to `tour_line_text`, so the cloud voice
    never reads `{h}` aloud in t16b01; D's `xfail` removed; I0's two fakes of `tour_line_text`
    take the words (`6853928`, one asserts they come).
11. **The shared place key, D's side** (INTEGRATION-C 5.4, D 5.4). Done `e352e63`: the tour's
    `seen()` leaves the reader's place of ANOTHER release exactly as the reader wrote it (C's
    rule from its side), with a browser test. Not run red first (the owner's rule: one run).
12. **D on A's real facts** (INTEGRATION-D 5.5, A 5.5). Done: `--check` on this checkout builds
    the tour from A's real pack (the bands, the digit rule, the pictures' rules and the scrubber
    all hold): owner 795.7 s, 1,761 words; guest 767.8 s, 1,699 words (D measured the same with
    the plan's values). `sos.emergency` is the string "112" and T12 shows it. D's own tests stay
    on `PLAN_VALUES`; the `e2e` suite's `guest_tour` serves the real tour through the real routes.
13. **STUBS_PASS flipped** (I0-NOTES 5.1). Done `fdecd78`: `STUBS_PASS = False`; the seam test
    pins the flip and that all seven parts are BUILT.
14. **The `e2e` suite** (I0-NOTES 5.3). Done `6908165`: through the real app over HTTP, part B's
    writer on part A's own pack of I0's fixture repository (plus the four trial pages its guide
    has no card for): the trial (₹100 cap, "yes" refused, YES, steps, side by side; at the cap it
    stops before a call whose worst case would pass ₹100), the pick's `yes_needed` and YES, the
    first write, a page in the owner's reader written by AI, a new release's `update_ready`
    naming exactly the pages that cite the changed file and Update asking the brain for those
    only, **console-only and the primary owner on every writer route** (I0-NOTES 5.3, C 5.5), and
    a guest's tour built from A's real pack of this checkout. Control: `carry.is_changed` always
    true fails `update_changed_only` for its own reason. On A's pack a small chapter pack settles
    below its hold, so a 9th call can fit (₹92.16 after 9): the cap rule is checked, not B's
    worst-case count of 8 (B's own row test keeps that).
15. **The `needles` suite** (I0-NOTES 5.2, INTEGRATION-A 5.8). Done `2120801`: the creator name,
    his e-mail, a vault text, a memory fact, a mail subject, a secret-shaped string, the canary,
    the handle in a tracked path and a stand-in for each hashed locality, employer and workplace
    (phrases included), against every pack, prompt, page, kept draft, trial page, facts.json, log
    record, audit row, notice and the Privacy export, each page's first draft repeating its whole
    prompt; a positive control per sink. Control: the pack builder reading Book settings turns
    exactly the creator-name case red.
16. **The `console` suite** (INTEGRATION-C 5.2). Done `fdecd78`: C's browser tests by name are its
    cases (they need a Python with Playwright: `JARVIS_BROWSER_PYTHON`, else the suite fails with
    that reason); its control, the YES box sending "yes", is a changed copy of
    `console-book-writer.js` that C's fake server serves only under `R63C_CONTROL` (the file on
    disk untouched): the trial's YES case fails while the estimate's case passes.
17. **I0's stub pins in the tests and the contract eval**. Done `6853928` and `0d92f99`: the writer on `app.state` is B's `WriterService`; no writer or pages route
    says `not_built_yet`, each answers a status its row lists, never cached (the wiring test and
    the contract eval's `routes` case); the 2 MiB cap pin.
18. **The guide** (I0-NOTES 5.4, 5.5). Done `537db63`, v6.3.2: C57's R6.3 sentences from PLANNED
    to built and joined (not yet deployed), its module list filled; §11's rows after the first two
    in the owner's order after R6.3: calls from his laptop, R5.2 (voice), R8 (home cameras), R8.1,
    R9 (kitchen), then later. **Left: R8.1's content** is not in this repository (the row says
    so); the Workshop fills it.
19. **"1 plans"** in the Book panel's section counts. Declined: it is R6's own text
    (`console-book-reader.js:142`, `4621e27`, 10 Nov 2026), shown with R6's one-plan mock book
    (`tests/browser/book_mocks.py`, also R6's), not R6.3's or its fakes'; the real book has 29
    plans. "1 parts", "1 flows", "1 libraries" have the same shape there. For R6.4's look.
20. **The Stack's licence in book.json** (INTEGRATION-A 5.6, optional). Left for the owner: a
    contract change in `sections.py`, not needed for R6.3.
21. **An explicit "Continue: <scene>" offer** (INTEGRATION-D 5.6, optional). Left: it needs a hook
    before Begin in `console-book-show.js`; continue is automatic for the owner today.
22. **The contract eval's control at I1.** Kept I0's (the job replaced by one that calls the brain
    with no run; a stray route). The plan's I1 wording ("the job's no-run guard removed") is part
    B's own `deploy` control in the `writer` suite, which is red in the full run.
23. **The fresh-context reviews** (INTEGRATION-C 5.5; no part ran its own, by the owner's rule of
    23 Nov). Left for the combined reviews (`code-reviewer`, `python-reviewer`,
    `security-reviewer` on the YES and ₹ dialogs).
24. **Seen in the pictures, for the reviews** (not changed: C's and B's words). The trial's rows
    are labelled by page id ("Chapter example", "Card C16"), not the page's title; the trial's YES
    box has two near-duplicate lines on Gemini (free) learning from what it reads.

## The rules bound at I1

- **The tour's approved words never change**: `gen/tour.json` is D's, untouched here;
  `test_r63_d_script` (byte-for-byte against the plan's tables) passes; facts fill placeholders
  only.
- **A guest never gets ₹, owner-only lines or owner data**: D's tests, the `tour` suite and the
  `e2e` suite's `guest_tour` on the real tour (no T16, no owner-only line, no ₹, `costs` empty,
  owner-only ids 404); the `needles` suite for owner data.
- **Nothing spends without his typed YES on the ₹ shown first**: B's rows, the `writer` suite's
  controls, the `e2e` suite (no call before YES; Update only on YES), the `console` suite's
  control.
- **Model-agnostic through `jarvis.llm`**: the import guard (item 6), the write seam unchanged.
- **The console's look**: `console.html`'s hash pinned and unchanged; no CSS changed; the JS
  changed here draws nothing new (the redraw key, the place rule).

## The checks (once each, behind `/tmp/jarvis-heavy.lock`, by the owner's rule of 23 Nov)

| Check | Result |
|---|---|
| Python 3.12: `test_r63_*`, `test_book_*`, `test_r6_*`, `test_r61_*`, `test_r62_*`, every `*_seams.py`, the guide's and the doc checks' tests | 3,284 passed, 5 skipped. The run stopped at its first failure (`-x`, my slip), so it went on from that file instead of starting again: 356 passed + 1 failed, then 2,923 passed, 5 skipped, 4 failed; the five were I0 pins (item 17) and were re-run alone after the fix: 5 passed |
| `evals/r6_3/run.py --mock` (all seven parts, Playwright for `console`) | **140/141**, every built part's control red (facts 14, writer 50, console 44, tour 10, needles 13, e2e 5, contract 5); the one red was the contract's I0 pin, moved (item 17), and the contract part re-run alone: 5/5, its control red |
| Browser `test_r63_d_tour.py` (Chromium, WebGL2) | 13 passed (the redraw case at both sizes, the new place test) |
| C's four browser files | 44 passed, inside the `console` suite's run |
| `python -m jarvis.buildbook.gen --check` | two builds byte-identical: book.json 301,454 bytes (with the tour), facts.json 1,020,731, source.zip 10,305,198, 37.0 s |
| `ruff check` and `ruff format --check` on `src tests evals scripts` | clean (2,159 files) |
| `mypy src` | the one baseline error (`memory/redis_store.py:67`) |
| `scripts/arch_coverage.py`, `scripts/check_doc_versions.py` | OK (66, 108, 2, 31, 122); 31 documents |
| The whole unit suite, the whole browser suite, Python 3.11 | **not run** (the owner's rule: one full check pass after the combined review; CI's 3.11) |

The `e2e` and `needles` suites are new code: their parts were run while they were written
(four and five runs), then once in the full run.

## The pictures (not committed; handed to the Workshop)

The wired app (the real app and the real writer wiring's context on the app's docs, R6 vault and
audit; only the brains are scripted and the source adds A's pack of the fixture repository; a
fresh Google sign-in through the app's own callback; the passkey ceremony is the one stand-in: an
owner session opened by the server for this owner), at `phone` (360 × 800) and `laptop`
(1280 × 800), each with a `-part` crop: `writer-trial-side-by-side-<size>.png`,
`writer-trial-yes-box-<size>.png` (the estimate's ₹ above the YES box, closed with Esc),
`writer-pick-<size>.png`, `full-book-<size>.png`, `full-book-page-written-<size>.png`. The real
tour (A's real pack of this checkout, D's filler) on the wired show page:
`real-tour-<size>-T12.png` … `-T15.png` (2D on the phone, 3D on the laptop). D's run:
`phone-NN-<id>.png` and `laptop-NN-<id>.png` for all 17 scenes (D's plan values).

## Sizes

`console-book-2d.js` 191, `console-book-3d.js` 345, `console-book-tour.js` 104 (≤ 300),
`facts_model.py` 224, `gen/write.py` 263, `api/r6_wiring.py` 293 (≤ 300), `show_script.py` 134,
`writer/part.py` 352, `evals/r6_3/e2e.py` 358, `needles.py` 355, `console.py` 89;
`console.html` 782 and byte-identical; `config.py`, `api/app.py`, `tools/gateway.py`,
`core/brain.py` not edited.

## Final checks (after the combined review, once each)

The combined review `REVIEW-I1.md` v6.3.2 found 2 HIGH, 5 MEDIUM, 11 LOW (+ M-6 below) and fixed
every HIGH and MEDIUM and seven LOW (item 19, "1 plans", is its L-6, now fixed). These are the one
final pass, one suite at a time behind `/tmp/jarvis-heavy.lock`, on `r6-3-i1` @ `650e897`.

| Check | Result |
|---|---|
| Unit, Python 3.12, the WHOLE suite with coverage (eight chunks of `tests/test_*.py` and `tests/browser`, one coverage file appended) | **19,251 passed, 155 skipped, 1 failed**: `test_markdy_export.py::test_nothing_the_app_ships_mentions_markdy`, red on the joined branch (part A's generator names `tools/markdy/package-lock.json`; the whole suite had not run at I1) — review M-6, fixed in `2110585` and `650e897`, that file and A's inventory tests re-run alone: 84 passed. **Coverage 95.59 %**, floor 95 % (`scripts/coverage_floor.py`: OK) |
| `ruff check` and `ruff format --check` on `src tests evals scripts` | clean (2,160 files) |
| `mypy src` | the one baseline error (`memory/redis_store.py:67`) |
| `evals/run_all_mock.py` | every suite PASS but phase0 smoke (fails by design) and `r6_3` (97/98: `console:browser` needs `JARVIS_BROWSER_PYTHON`). `evals/r6_3/run.py --mock` with it: **140/141**, every part's control red; the one red is C's pick case `…_each_ask`, a 30 s wait for the YES dialog in the suite's child process; `test_r63_c_pick.py` run directly: 10 passed |
| `scripts/check_doc_versions.py` | 31 documents OK |
| `scripts/arch_coverage.py` (the guide's coverage) | OK (66, 108, 2, 31, 122) |
| `python -m jarvis.buildbook.gen --check` | two builds byte-identical: book.json 301,454 bytes, facts.json 1,021,081, source.zip 10,326,859, 98 files left out, 35.1 s |
| Browser, the R6.3 files (Chromium; `.[dev]` + Playwright, no Pillow) | `test_r63_c_look`, `_c_pages`, `_c_trial`, `_d_tour`: 47 passed; `test_r63_c_pick`: 10 passed |
| Browser, the files the fixes touched (R6's mock book, `book_mocks.FakeBook`, review M-5) | `test_book_panel` (14, the new plural case included), `test_book_show`, `test_book_show_hold`, `test_book_lock_ui`, `test_r62_book_listen`: 85 passed |
| Python 3.11, the whole browser suite | **not run** (the owner's rule; CI runs both on the pull request) |

The writer's packs on this checkout's REAL build (outside the repository, after H-1 and M-4):
2,855 of the 3,032 page references read, the guide and its 73 cards found, no `.claude/**` or
`tests/**` member readable, 153 packs in 30 s (was 183 s) in a worker thread.

Pictures (not committed), in `/tmp/r63-review-shots/` at `phone` (360 × 800) and `laptop`
(1280 × 800), each with a `-part` crop, on C's fake server: `writer-trial-yes-box-<size>` (one
set of words on who reads what: the server's), `writer-trial-side-by-side-<size>` (each page by
its title), `reader-section-counts-<size>` (R6's mock book: "1 plan", "1 service, 1 alert kind").

## Hotfix 1 (`v6.3.1`, 24 Nov 2026): what the owner's first trial found

R6.3 went live on 23 Nov at 23:41 IST (`58ad64d`). The owner's first Writer trial, between 00:37 and
01:00 IST, found four faults. Each has a test that failed first.

| # | What he saw | Cause | Fix | Test |
|---|---|---|---|---|
| 1 | After a refresh, the Book panel came back without its Book writer (no ₹ estimate) | The deck restores an open panel without firing `jarvis:panel`, and the Book's `ready()` loaded the panel but not the writer and full-book modules | `ready()` loads them too (`console-book.js`) | `test_r63_hotfix1_the_writer_is_there_after_a_refresh_with_the_book_open` |
| 2 | His YES started the trial, and the section still said "Not run yet" | The first step stopped it at the monthly line (JARVIS had used ₹1,404.79 of ₹1,500, past the 80 % line), and the section drew a stopped trial's reason only while it was running | A stopped trial shows how it ended and why, above Start (`console-book-writer.js`) | `test_r63_hotfix1_a_trial_that_stopped_says_why_above_start` |
| 3 | The saved reason said "10 %" | `finish()` read the unpicked pick's floor; the gate used the default 80 % | Both read `run.limit_pct_of()` | `test_a_trial_stopped_at_the_monthly_line_names_the_line_it_used` |
| 4 | With the limit raised to ₹3,000, the trial stopped after one page: "billed above its worst case", ₹11.83 spent, nothing kept | The hold read 2.5 bytes a token; Claude (Sonnet 5.5) counted his full pack denser, so the bill passed the hold | `BYTES_PER_TOKEN_WORST` 2.5 → 1.5 (a full pack's hold ₹11.84 → ₹16.71 at ₹95.24); the estimate one notch denser (mid 3.0 → 2.2 bytes a token), as his bill showed; the trial now fits 5 holds in ₹100, not 8 | `test_a_page_counted_denser_than_the_old_worst_case_is_kept_not_stopped`, the trial-cap and hold pins moved |

The owner approved each fix in chat (00:49, 00:53 and 01:06 IST). The checks ran once: ruff, mypy on
the writer, the R6.3 unit files (522), the version pins, and the Book and trial browser files.

## Change log

| Version | Date | Release | What changed | By |
|---|---|---|---|---|
| v6.3.3 | 24 Nov 2026, 01:35 IST | R6.3 | Hotfix 1 (`v6.3.1`): the four faults from the owner's first trial, their causes, fixes and tests | 🛠 Mark XXIV |
| v6.3.2 | 23 Nov 2026, 22:10 IST | R6.3 | "Final checks": the one pass after the combined review (`REVIEW-I1.md` v6.3.2): the whole unit suite with coverage 95.59 %, the Markdy guard (M-6) fixed, ruff, mypy, the mock evals, the docs checks, the generator's check, the R6.3 and touched browser files, the pictures; item 19 now fixed by the review (L-6) | 🛠 Mark XXIV |
| v6.3.1 | 23 Nov 2026, 20:14 IST | R6.3 | First edition, at the end of I1: the four merges, the join bug, the 2 MiB facts cap with its 80 % warning, A's, B's, C's and D's "Needs I1" (pins, the fixture's sources, the show to the tour, the message type, mypy, ₹ in I0's fake, the redraw fix, the honorific, the place key, D on A's real facts), STUBS_PASS flipped, the console, needles and e2e suites built, I0's stub pins moved, the guide v6.3.2 (C57 built, the roadmap in the owner's order), "1 plans" declined as R6's, the rules bound, the checks once each, the pictures, sizes, what is left | 🛠 Mark XXIV |
