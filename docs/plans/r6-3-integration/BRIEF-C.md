Version v6.3.1 · 23 Nov 2026, 17:24 IST · Release R6.3 · Status: Current · Owner: 🛠 Mark XXIV

# R6.3 — Part C brief: the owner's console (Opus)

Read `BRIEF-COMMON.md` first (the loop, the rules, the seams, the commands). Branch `r6-3-c` from
`origin/r6-3-i0`. **`security-reviewer` for the YES and ₹ dialogs.** Plan sections: D6's and D7's
screens, D11's storage line, D12's Update, D14, the HTTP contract (what you draw), the `console`
suite and its control, "Exit check" 3 (the screenshots).

## 1. Your files (only these)

`src/jarvis/api/static/console-book-writer.js` and `console-book-pages.js` (replace I0's stubs,
each ≤ 400 lines), `console-book-reader.js` (G4's "+N more in the full book" line under the
limitations section only; 257 → ≤ 270), `tests/test_r63_c_*.py`, `tests/browser/test_r63_c_*.py`,
`tests/r63_fakes_c.py`, `evals/r6_3/console.py` (I0's stub: replace it), the screenshots (to the
Workshop, not committed), `docs/plans/r6-3-integration/INTEGRATION-C.md`. **Not yours:**
`console.html`, `console-book.js` (I0's loader), `console-book-show.js`, `console-book-script.js`,
`book.html`, `api/console.py` (the allow-list: an optional placement CSS, D0, would need a line
there and a link from your module; if you need it, propose the exact lines under "Needs I1" and
keep your layout to existing classes meanwhile).

## 2. Your contracts

- **The loader (I0's, `console-book.js`):** your two files load ONCE at the Book panel's first
  open. `window.JarvisBookWriter = Object.freeze({ settings(host, deps) })`: `host` sits under Book
  settings (re-appended on every panel render: keep your own state in your module); `deps = {api,
  booked, ask, say, render, token(), release(), top}` where `top` is a box at the TOP of the panel
  (the 80 % storage line from `GET /v1/book/writer` `storage.warn`, shown whether or not the writer
  is used). `window.JarvisBookPages = Object.freeze({ mount(host, deps) })`: `host` sits under the
  reader of an open OWNER session (`deps.token()` non-empty); `booked(opts)` adds `X-Jarvis-Book`;
  `deps.release()` is the release being read ('' for the current one). `api` is
  `JarvisConsole.api` (it throws an error with `status`, `code`, `body`); `ask(title, lines,
  buttons)` is the panel's `.bdialog`.
- **What you draw is exactly `buildbook/writer/http.py`'s models** (rupees only): the Writer trial
  (`Estimate`: about ₹<mid> (₹low–₹high), the time, the cap ₹100, `sent_to`, the GST note; the YES
  box; progress with "Step while I watch", which calls `POST …/step` while Book settings is open;
  the side-by-side `TrialPages` rows with checks, ₹ and seconds; one `TrialPageView`), the Writer
  (the pick: the brain, the tier never offered, the caps filled from `Pick.caps`; `PUT …/pick` →
  422 `yes_needed` → show its `words` above a YES box → resend the same pick with `typed: "YES"`
  and its `terms_id`; "Keep" sends nothing; lowering saves at once), the first write's YES
  (`POST …/first` with the estimate shown), Update's YES and Stop, and the storage line. A route's
  refusal shows its `detail` under the button; offline "Can't reach JARVIS. Check your connection.";
  a stale estimate (409 `estimate_changed`) asks again.
- **The YES box** is never pre-filled and sends exactly what he typed: the SERVER decides (a "yes"
  must reach it and be refused; your control sends "yes"). No ₹ from the page is trusted (the
  server re-estimates); never a `$`.
- **The Full book (D14):** `GET /v1/book/pages?release=` (`PagesView`: parts → chapters → pages,
  `limitations {shown, total}`) and `GET /v1/book/pages/{id}?release=` (`Page`); parts as `.dsc`
  disclosures, chapters as `.bsec` rows, a page's six sections (`plain` and `example` open, the rest
  closed), its line "Written by <label> (balanced tier, <model>) for <version> on <day>" from
  `PageMeta`, or "Not written by AI yet" (`writer.model.NOT_WRITTEN`) and "Changed in this release:
  waiting for your Update" for `changed`; references as code chips; older kept releases through the
  existing release picker. **Continue where I left off:** `localStorage` key
  `jarvis_book_place_v1` (the only Book key allowed there: `test_book_static.py`), `{release, page}`,
  ids only, owner only; reopening offers "Continue: <page title>" for the same release.
- **The reader's G4 line:** under the limitations section, "+N more in the full book" from
  `GET /v1/book/pages`'s `limitations` (N = total − shown), only in an owner session.
- **Rules of the Book's JS** (`tests/test_book_static.py`, which now lists your files): ASCII,
  ≤ 400 lines, no HTML sink (`textContent` only), no `setTimeout` strings, no inline handlers, no
  `$` in a string literal, no colour/font/radius/shadow literal, no off-site URL, the token never
  in `localStorage`. Existing classes only (BRIEF-COMMON section 5). 44 px targets.

## 3. Your fakes and tests

- `tests/r63_fake_server.py` (I0's): the 13 routes from an in-memory `FakeWriter` in the contract's
  models (every grant 422 `yes_needed` until the typed YES on its terms; "yes" 422 `not_yes`; a
  stale estimate 409; `step` advances; a guest's book token `GUEST_BOOK` 403 on the pages; the
  owner's `OWNER_BOOK` = `book_mocks.TOKEN`); `serve(token)` runs it in a child process; the R6
  routes (status, open, sections, settings) are `tests/browser/book_mocks.FakeBook`'s page routes.
  It does NOT check console-only or the primary owner (the wired app at I1 does).
- Browser tests (Playwright, `-m browser`): the trial, the pick's YES boxes, the first write's YES,
  Update's YES and Stop, the Full book (a written page, a "Not written by AI yet" page, references,
  an older release), continue, 44 px, 360 × 800 and 1280 × 800, day and night; the Book panel's
  screenshots with the writer off unchanged against 47ee8fc.

## 4. Your rows

| Row | Your test (what must hold) |
|---|---|
| 23 Nov · trial (your half) | `test_r63_c_trial_*`: the estimate, what is sent and to whom, the YES box refusing "yes" (the server's word), progress with "Step while I watch", side by side with checks |
| 23 Nov · pick (your half) | `test_r63_c_pick_*`: the caps filled with the defaults; the first save, a raise, a paid brain and "update by itself" each show the server's ₹ words and the YES box; "Keep" sends nothing; lowering saves at once; the first write's second YES |
| 380 · grows (your half) | `test_r63_c_a_new_card_is_listed`: a page the index lists is in the Full book (I1's e2e joins it to A's and B's halves) |

## 5. Your eval (`evals/r6_3/console.py`) and its control

Cases: the plan's `console` row (browser, against the fake server). **Control:** the YES box sending
"yes" (its case must fail: the server refuses, the console says so and nothing starts). Set
`BUILT = True` only when it does.

## Change log

| Version | Date | Release | What changed | By |
|---|---|---|---|---|
| v6.3.1 | 23 Nov 2026, 17:24 IST | R6.3 | First edition, written at I0: Part C's files, contracts (the loader's hosts and deps, what you draw from the HTTP contract, the YES box, the Full book and continue, the reader's G4 line, the Book's JS rules), the fakes and tests, its rows, the `console` eval and its control | 🛠 Mark XXIV |
