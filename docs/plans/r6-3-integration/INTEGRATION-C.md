Version v6.3.1 · 23 Nov 2026, 17:53 IST · Release R6.3 · Status: Draft · Owner: 🛠 Mark XXIV

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

## Change log

| Version | Date | Release | What changed | By |
|---|---|---|---|---|
| v6.3.1 | 23 Nov 2026, 17:53 IST | R6.3 | First edition: Part C's plan, before the code | 🛠 Mark XXIV |
