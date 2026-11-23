Version v6.3.2 · 23 Nov 2026, 18:45 IST · Release R6.3 · Status: Current · Owner: 🛠 Mark XXIV

# R6.3 — Part C: the owner's console (integration notes)

Builder C's notes for I1. Part C draws the HTTP contract (`buildbook/writer/http.py`) in the Book
panel: Book settings' Writer trial, the pick and its caps, the rupees and typed-YES dialogs, the
first write, Update and Stop, the 80 % storage line, the Full book in the owner's reader with
"continue where I left off", and the reader's G4 line. Branch `r6-3-c` from `r6-3-i0`.

## 1. Plan (written before the code)

Files: `static/console-book-writer.js`, `static/console-book-pages.js` (I0's stubs replaced,
each ≤ 400 lines), `static/console-book-reader.js` (G4's line only, ≤ 270), `tests/r63_fakes_c.py`
(I0's fake server plus a test-only state route and the writer-off and new-card states),
`tests/test_r63_c_*.py`, `tests/browser/test_r63_c_*.py`, `evals/r6_3/console.py`, this file.

Order, each test written and run red before its code:

1. Static rules of C's JS (`test_r63_c_static.py`): sizes, ASCII, existing classes only, no `$`,
   the YES box never filled by the page, the place key the only `localStorage` key.
2. C's fake server (`test_r63_c_fakes.py`): the writer off, a new card's page, stale estimates.
3. The writer (`test_r63_c_trial.py`, `test_r63_c_pick.py`): the trial's estimate, what is sent and
   to whom, the YES box refusing "yes" by the server's word, "Step while I watch", side by side;
   the pick's caps, every grant's YES with the server's ₹ words, "Keep" sends nothing, lowering
   saves at once, the first write's YES, Update's YES, Stop, the storage line, offline, a stale
   estimate asking again.
4. The Full book (`test_r63_c_pages.py`): parts, chapters, a written page, a "Not written by AI
   yet" page, references as chips, an older release, continue, G4's "+N more", a new card listed.
5. The look (`test_r63_c_look.py`): 44 px targets, 360 × 800 and 1280 × 800, night and day, the
   panel with the writer off laid out exactly as without R6.3's boxes; screenshots on request.
6. The `console` eval and its control (the YES box sending "yes").

## 2. What is built

- **`console-book-writer.js` (400 lines)**, Book settings → "Book writer" (a `.bset` disclosure,
  closed by default), drawn from `GET /v1/book/writer` in rupees only:
  - **The Writer trial:** the estimate first (about ₹<mid> (₹low–high) for 5 sample pages from
    each brain, the ₹100 cap and "each page starts only when its worst case still fits", the
    time, the estimate's `sent_to` lines, a training brain's line, the GST note), then "Start the
    trial" → the YES box → `POST …/trial {typed, estimate_id}`. Progress with "Step while I
    watch" / "Pause watching" and Stop: one `POST …/step` at a time, at most 6 a minute, only
    while Book settings is open, the panel open and the tab visible. Done: both brains' pages side
    by side (`.bevents` rows: the verdict with its checks in words, ₹ and seconds, "Read"), one
    sample page drawn by `JarvisBookPages.page`, "Run another trial", "Delete the trial pages".
  - **The Writer (the pick):** the brain (`.bsel`; a brain not offered is disabled with its note;
    "Balanced tier, always" — the tier is never offered), the four caps filled from `Pick.caps`
    (the defaults ₹1,500 / 500 / 1,000 / 80 %), "Update by itself" (`.bsw`, off). Bounds are
    checked before sending. `PUT …/pick` → 200 saves (lowering); 422 `yes_needed` → the server's
    `words` above the YES box → the same pick resent with `typed` and its `terms_id`; "Keep" (or
    Esc) sends nothing.
  - **The first write's YES and Update's YES** on their own estimates (`GET …/estimate?run=`),
    Stop (`POST …/stop`); a refusal's `detail` under its button; offline "Can't reach JARVIS.
    Check your connection."; 409 `estimate_changed` / `terms_changed` asks again on the new words.
  - **The YES box** (`#bookYesDialog`, a `.bdialog`): never filled, sends exactly what was typed;
    "yes" reaches the server and its `not_yes` words show in the box, nothing starts.
  - **The storage line** at the top of the panel (`deps.top`) when `storage.warn`, whether or not
    the writer is used. Writer off, not built or unreachable: nothing drawn.
- **`console-book-pages.js` (246 lines)**, under the reader of an open OWNER session: "Full book",
  parts as `.dsc` disclosures with their page counts, chapters as `.bsec` rows, each page "Read";
  a page's six sections (plain and example open), "Written by <label> (balanced tier, <model>) for
  <version> on <day>" or "Not written by AI yet", "Changed in this release: waiting for your
  Update", references as `.bchip` code chips; older kept releases through the existing release
  picker (`?release=`). **Continue where I left off:** `jarvis_book_place_v1` `{release, page}`,
  ids only; reopening offers "Continue: <page title>" for the same release. **The key is shared
  with Part D's tour** (`{release, scene}`, `console-book-tour.js` on `r6-3-d` @ `d529b9a`): the
  reader reads it first and keeps every field it does not own exactly as written (D's integer
  scene included); when the key holds the tour's place of ANOTHER release, the reader leaves it
  alone; storage that throws is caught on read and write. A guest's 403, a release without
  pages or offline: nothing drawn.
- **`console-book-reader.js` (259 lines):** G4's "+N more in the full book" under the limitations
  section, from the index's `limitations` (N = total − shown), owner session only.
- **`tests/r63_fakes_c.py`:** I0's fake plus the writer off, stale estimates, a set refusal, C74
  (new card), older kept releases with nothing written, a side by side with a redraft and a
  refusal, a test-only state route. In its child process (the browser's server) the grant words
  carry the rupee sign as part B's real words do (I0's fake says "Rs "; I0's file untouched).

Rows: 23 Nov · trial (C's half): `test_r63_c_trial_*` (6); 23 Nov · pick (C's half):
`test_r63_c_pick_*` (10, the first write's second YES, Update and Stop included); 380 · grows
(C's half): `test_r63_c_a_new_card_is_listed`.

## 3. The checks (on this branch's head, one run each, behind `/tmp/jarvis-heavy.lock`)

| Check | Result |
|---|---|
| `test_r63_c_static.py`, `test_r63_c_fakes.py` (Python 3.11) | 23 passed (16 + 7) |
| Seams and static: `test_r63_seams.py`, `test_r63_console_seams.py`, `test_r63_static.py`, `test_book_static.py` | 104 of 105 passed; **1 failed: I0's stub pin** (section 5, 1) |
| Browser `test_r63_c_trial.py` | 6 passed |
| Browser `test_r63_c_pick.py` | 10 passed |
| Browser `test_r63_c_pages.py` | 10 passed (D's shared place included) |
| Browser `test_r63_c_look.py` (with the pictures) | 18 passed |
| `ruff check`, `ruff format --check` on C's 7 Python files | clean |
| `scripts/check_doc_versions.py` | 31 documents OK |
| Sizes | writer 400 / 400, pages 246 / 400, reader 259 / 270 |

The pictures (not committed; to the Workshop, in the folder `R63C_SHOTS` names): 106 files. Each screen at
`phone` (360 × 800) and `laptop` (1280 × 800), `night` and `day`, the page as seen (`<screen>-<size>-
<surface>.png`) and the part alone (`…-part.png`): `trial-estimate`, `trial-yes`, `trial-progress`,
`trial-side-by-side`, `trial-sample`, `storage-line`, `pick`, `pick-yes`, `first-write-yes`,
`update-yes`, `full-book` (with "Continue: Demo router"), `page-written`, `page-not-written`; and
`writer-off-phone-night.png`, `writer-off-laptop-night.png` (the panel unchanged). A `-part`
picture of a tall box inside the panel's scroller can show the dock over its lower edge: that is
Playwright's element capture, not the layout (the page pictures show it as seen).

## 4. Deviations, and what was not done or not verified here

- **Not test-first everywhere:** the D-merge test was written after the reader already kept
  another part's same-release fields; its new rule (another release's tour place left alone) and
  the look test's last changes were not run red first (the owner's rule of 23 Nov: one run at the
  end).
- **The pick's `PUT` goes through `JarvisChat.raw`** (the console's authenticated fetch), not
  `deps.api`, so the 422 `yes_needed` body (`terms_id`, `words`) is read in one place.
- **The writer-off picture** is compared with the same build with R6.3's three boxes removed
  (layout and pixels identical), not with a picture taken on `47ee8fc`.
- **Not run (the owner's rules of 23 Nov):** `security-reviewer`, `code-reviewer` (no
  self-review agents); a second run of any file; `mypy` (no Python under `src/` changed by C).
- **`evals/r6_3/console.py` is still I0's stub** (`BUILT = False`): not in this session's list.
  See section 5, 2.
- The fake server does not check console-only or the primary owner (I1's wired app does).

## 5. Needs I1

1. **I0's stub pin in `tests/test_r63_console_seams.py`** (C replaced both stubs, as the brief
   asks), exact diff:

   ```diff
   -    assert "settings: () => {}" in _read("console-book-writer.js")  # I0's stub draws nothing
   -    assert "mount: () => {}" in _read("console-book-pages.js")
   +    assert "Object.freeze({ settings })" in _read("console-book-writer.js")
   +    assert "Object.freeze({ mount, page, more })" in _read("console-book-pages.js")
   ```
2. **The `console` eval** (`evals/r6_3/console.py`): build it, or have C build it, before
   `STUBS_PASS` flips to False. Suggested shape (R13.1's `evals/r13_1/console.py`): C's browser
   tests by name as cases where Playwright is present; the control is the YES box sending "yes"
   (the trial's case must fail: the server refuses, the console says so, nothing starts).
3. **I0's fake words:** `tests/r63_fake_server.py` `_words` says "Rs "; part B's words carry the
   rupee sign. If I1 changes I0's fake (`"Rs "` → `"₹"` in `_words`), drop
   `rupee_words` and its one line in `tests/r63_fakes_c.py` `main()`.
4. **The shared place key, D's side:** D's `seen()` keeps the reader's `page` only for the same
   release, so playing the tour replaces the reader's place of an older release. C never drops
   D's fields; I1 may want D to keep the same rule (leave another release's reader place alone).
5. Review the YES and ₹ dialogs with `security-reviewer` on the wired app; test console-only and
   the primary owner on every writer route there; the exit check's pictures against `47ee8fc`.

## Change log

| Version | Date | Release | What changed | By |
|---|---|---|---|---|
| v6.3.1 | 23 Nov 2026, 17:53 IST | R6.3 | First edition: Part C's plan, before the code | 🛠 Mark XXIV |
| v6.3.2 | 23 Nov 2026, 18:45 IST | R6.3 | What is built (the writer, the full book and continue with Part D's shared place merged, G4), the checks with their numbers, the pictures, deviations, Needs I1 (the stub pin's diff, the console eval, I0's fake words, D's side of the place key, the reviews) | 🛠 Mark XXIV |
