Version v6.3.1 · 23 Nov 2026, 17:24 IST · Release R6.3 · Status: Current · Owner: 🛠 Mark XXIV

# R6.3 — Part D brief: the short tour (Opus)

Read `BRIEF-COMMON.md` first (the loop, the rules, the seams, the commands). Branch `r6-3-d` from
`origin/r6-3-i0`. **Approval stop 2 passed** (the owner's YES on the tour's script, 23 Nov 2026,
14:53 IST): you start with A, B and C, and **every spoken word is fixed: copy the approved script
verbatim; no builder changes a word** (a wording problem goes to the Workshop under "Needs I1").
Plan sections: "The short tour's first script" (T01–T17, the facts table, the size measured), D9,
D13's audiences, the `tour` suite and its controls.

## 1. Your files (only these)

`src/jarvis/buildbook/gen/tour.json` (the approved script; I0's is empty), `gen/tour.py` (replace
I0's stub: fill, audiences, timer, bands), `src/jarvis/buildbook/tour_serve.py` (replace I0's stubs:
`tour_lines`, `tour_line_text`), `src/jarvis/api/static/console-book-tour.js` (replace I0's stub;
≤ 300 lines), `tests/test_r63_d_*.py`, `tests/browser/test_r63_d_*.py`, `tests/r63_fakes_d.py`,
`evals/r6_3/tour.py` (I0's stub: replace it), `docs/plans/r6-3-integration/INTEGRATION-D.md`. **Not
yours:** `buildbook/tour_model.py` (the contract), `show_script.py`, `service.py`, `gen/write.py`,
`console-book-show.js`, `console-book-script.js`, `book.html`, `gen/facts.py` (A computes the
facts you fill from).

## 2. Your contracts

- **The script (`gen/tour.json`, `tour_model.TourScript`):** package data, ASCII with `\u` escapes
  (the file is read with importlib.resources: `gen/tour.py`'s `load_script`), 17 scenes, each
  `{n, id, title, picture: {visual, facts}, chapter, audience, beats: [{id, text, audience, focus}],
  facts: [keys]}`. `(n, id, title, visual, audience)` must equal `tour_model.TOUR_SCENES[n - 1]`
  (I0 pinned the approved scenes: ids `what`, `layers`, `asking`, `approval`, `cancel`, `privacy`,
  `voice`, `approvals`, `memory`, `vault`, `home`, `phone`, `wardrobe`, `else`, `built`, `costs`,
  `planned`, the plan's headings as titles; T16 the owner's); beat ids `tNNbMM` of their scene;
  each beat's text the approved words with `{{key}}` placeholders exactly as the script writes
  them, and `{h}` in t16b01 (filled by `lines.render`'s words when served); `t13b03` audience
  `owner`, `t13b04` audience `guest`, the rest `both`. A title pinned wrong against the approved
  heading: "Needs I1", never a silent change.
- **The picture data (M6):** `picture.facts` is `{"from_show": n}` (T01 1, T02 2, T03 and T05 3, T04
  and T08 5, T06, T09 and T10 4, T07 6, T11 7, T15 9, T16 10, T17 11: the show scene of the same
  subject, copied at CI), or, for T12, T13 and T14 (`tour_model.OWN_PICTURE_DATA`), a list written
  in `tour.json` from that scene's own beat words with values as `{{fact}}` placeholders (T14's
  eleven modules from `gen/modules.others()`). `gen/tour.py` checks per `visual` that the data its
  module reads is there: 4 at least one `purpose` group and one other; 7 `home` and `edge` groups;
  9 at least one `group`; 10 a number `n` on every fact (≤ 10); 1, 2, 3, 5, 6, 8 and 11 a label on
  every fact.
- **`tour.build(repo, facts) -> Tour | None`** (`tour_model.Tour`: `owner` and `guest`, each an
  `AudienceTour` with its own filled scenes, `seconds`, `words`, `chars`, `lines`). Fill every
  `{{key}}` from `facts.values` (`facts_model.FACT_TOUR_KEYS`: A computes them; until A's branch
  joins, build your tests on a hand-made `FactPack` in `tests/r63_fakes_d.py` with the plan's values)
  and `tour.minutes` yourself, whole minutes of that audience's timer (14 owner, 13 guest on the
  plan's counts). An unknown key, a beat over 400 characters once filled, or a digit typed outside
  a placeholder (except inside the running example's quoted words and in "3D") is a `GenError`;
  no doubled word ("about about", L1). A guest's tour leaves out T16 and every owner-only line, and
  has no ₹ anywhere, in its lines AND its picture facts. The timer is `tour_model.seconds(words,
  lines, scenes)`; outside `HARD_BAND_S` (600–900 s) the model refuses; aim `AIMED_S` (780–870 s
  owner, 760–850 s guest).
- **`tour_serve.tour_lines(book, audience, words) -> {"scenes": [...], "seconds": float} | None`**:
  `book.tour.owner` or `.guest`, each scene dumped as JSON with `{h}` and its kin filled by
  `lines.render`; None when the book has no tour (today's 11-scene show). **`tour_line_text(book,
  line_id, audience) -> str | None`**: the text of a `tNNbMM` line only when that line and its scene
  belong to the session's audience (H1): a guest's `t13b03` or `t16b01` is None (404
  `unknown_line` through the real route, I0's join). I0's `show_script.py` gives a guest's tour no
  `costs`.
- **The page (`console-book-tour.js`, `window.JarvisBookTour`):** I0's `console-book-show.js` calls
  three hooks only while it plays a tour: `label(script, n, title)` (the chapters menu's words; for
  the owner, the scene's full-book chapter by name), `seen(script, beat)` (remember the place),
  `start(script, beats)` (the beat index to begin at: "continue where I left off" restarts the
  scene, never the middle of a line; `localStorage` `jarvis_book_place_v1` `{release, scene}`, ids
  only, owner only). The pictures come from `console-book-script.js`'s `picture()`: today's 3D and
  2D modules draw `visual` with the scene's own facts (Questions 12, Closing 13; the timeline's
  scene numbers for a tour are 18 and 19). The Book's JS rules apply (`test_book_static.py` lists
  your file: ASCII, no HTML sink, no `$`, show lines never hard-coded in JS).

## 3. Your rows and their named tests

| Row | Your test (what must hold) |
|---|---|
| 380 · tour | **`test_row380_the_tour_is_ten_to_fifteen_minutes_with_his_seven_highlights`**: the filled tour of this branch times 780–870 s for the owner and 760–850 s for a guest, inside 600–900 s; its highlight ids are exactly `tour_model.HIGHLIGHTS`, in his order; the running example has both lines ("Add a dentist appointment on Friday at 5 pm", "Cancel it") |
| H1 | `test_a_guests_speak_of_an_owner_only_tour_line_is_404`: every owner-only tour id (`t13b03`, `t16b01`) through the real route as a guest; every tour id of the session's audience speaks |
| words | `test_every_spoken_line_is_the_approved_one`: each filled line byte-identical to the plan's approved script once filled (read the plan's tables; no doubled word) |

## 4. Your eval (`evals/r6_3/tour.py`) and its controls

Cases: the plan's `tour` row (both bands; the seven in his order; both running-example lines; no
doubled word and every spoken line as approved; a guest's tour with no ₹, no T16, no owner-only
line; a guest's speak of every owner-only id 404 through the real route; the player runs all 17
scenes, Questions and Closing in 2D, in 3D (WebGL2) and under Motion Off; an older book plays
today's 11 scenes; "What else" lists the 11 other modules from the map; every scene's picture data
has what its `visual` reads, and a guest's picture facts hold no ₹). **Controls that must turn it
red:** T13's owner line left in the guest's tour (the no-₹ case); `tour_line_text` ignoring the
audience (the guest-speak case); a highlight dropped (the seven case, row 380's own); the pace set to
290 words a minute (the band case); T12's picture facts without a `group` (the M6 case). Set
`BUILT = True` only when every control fails its case.

## 5. Limits

₹0: the tour is fixed text, no model writes it; the voice is R6.2's (the browser's by default). No
new setting, route or collection. Browser tests against the show page with `book_mocks.FakeBook`
serving a tour script (and an older book's 11 scenes); 3D only in a Chromium with WebGL2 (the
Book's `_need_3d` rule). INTEGRATION-D.md names the filled tour's measured seconds, words and
characters for both audiences, every deviation, "Needs I1".

## Change log

| Version | Date | Release | What changed | By |
|---|---|---|---|---|
| v6.3.1 | 23 Nov 2026, 17:24 IST | R6.3 | First edition, written at I0 after approval stop 2: Part D's files, contracts (the verbatim script and its pinned scenes, the picture data per visual, the fill per audience and the timer, the serve bound to the audience, the page's three hooks and continue), its rows and named tests, the `tour` eval with its controls, limits | 🛠 Mark XXIV |
