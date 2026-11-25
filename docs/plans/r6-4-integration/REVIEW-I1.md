Version v6.4.0 · 25 Nov 2026, 16:10 IST · Release R6.4 · Status: Current · Owner: 🛠 Mark XXIV

# R6.4 combined security and code review of I1 (fresh context, 25 Nov 2026)

Reviewed: `r6-4-i1` @ `61b0a41` (I0, A, B, C, C2 and W1-W7 joined) against `main` @ `f5cf529`
(`v6.3.2`), with `git diff origin/main...HEAD` (232 files), the plan `docs/plans/r6-4-book-look.md`
v6.4.1 (D1-D11; rows 381, 390, 392, 393, 394), `I0-NOTES.md`, the approved mockups
(`docs/plans/r6-4-mockups/`) and the builders' hand-over notes. One reviewer for 🛠 Mark XXIV
applying `CLAUDE.md` and `.claude/rules/ecc/common` + `python`, security first. By the owner's rule
of 23 Nov this is the release's only review: the reviewer fixed what it found on `r6-4-review`
(each finding names its commit) and ran the one final check pass.

**Verdict: APPROVE** (after the fixes below). CRITICAL 0 · HIGH 0 · MEDIUM 3 (fixed) · LOW 8 (five
fixed, three declined with their reasons).

## What holds (checked)

- **The routes.** `GET /v1/book/chapters`, `/v1/book/chapters/{chapter_id}` and
  `/v1/book/pages/search` go through the pages routes' one handler (`api/book_pages.py:route`): the
  `book_pages` part, the primary owner (403 `not_primary`), an OWNER book session's `X-Jarvis-Book`
  (none 401, a guest's 403 `owner_only`, a store outage 503), console only after the session (403
  `console_only`), the per-owner limit (chapters share the pages' 60 a minute, search its own 60,
  installed by `install_book_pages`), then the request is read: a chapter id against `CHAPTER_ID`
  (404 `no_chapter`), `q` 2-60 characters once trimmed and folded (422 `bad_query`), `?release=`
  against `RELEASE_ID` (404). Every answer is `book_json` (`no-store`); refusals are the fixed words
  of `writer/texts.py`, never a path, a page's text or an exception. `/search` is registered before
  `/{page_id}`. Search echoes `q` only after normalising it (at most 60 characters).
- **`/book/read`** is served by `console._page` exactly as `/book/show` (no-store, nosniff, DENY,
  no-referrer, the one console CSP with `script-src 'self'`); its 14 assets are literal routes
  (`READ_ASSETS`). The guest lock (`book_lock.ALLOWED`) does not let it through: 423 under a lock
  (tested). The page holds no data.
- **The token** is taken from THIS tab's sessionStorage (put there by the panel's Read the full
  book, `toShow(..., '/book/read')`; a guest session always goes to the show), sent only on
  `/v1/book/` paths, forgotten on 401/403/404/410 and on Close (which asks first). localStorage
  holds ids and times only (`jarvis_book_place_v1`: release, page, read_at, chapter, line,
  heard_at, the tour's scene; `jarvis_book_read_v1`: page ids for 3 releases); each part keeps the
  others' fields and never writes over another release's place.
- **No HTML from data.** No `innerHTML`/`insertAdjacentHTML` in any R6.4 module; search snippets
  and marks are text nodes and `<mark>` elements built from checked, sorted, non-overlapping
  [start, end) ranges (`normalSearch`); a hostile title is drawn as text (tested). All new JS is
  ASCII; every module is under its 400-line cap; `console.css` and `console-deck.css` are untouched.
- **Row 392.** `config._is_private_host` no longer counts `*.ts.net` (plain http is refused for a
  Tailscale name, with words that say https); loopback, RFC 1918/ULA, link-local, `.local`,
  `.internal` and single-label names are unchanged; `deploy/cloudrun.sh` refuses
  `http://*.ts.net[...]` before its local-address cases. The offline brain and the home bridge
  already required `https://<machine>.<tailnet>.ts.net`; no other caller of the rule exists.
- **Row 393 and C2/I1.** A model with no known price is counted as "price unknown" (calls, tokens)
  and, for every gate, at the dearest known price (`counted_inr`); a stored `unpriced_inr` that is
  not a finite number >= 0 makes the month unreadable (fail closed); one reply is recorded once
  (`record` prices it or counts it unpriced, never both); the chat, stream, spend and voice gates
  compare `counted_inr`; the console, the Vitals row, the brief and the CLI never show ₹0 for it.
  `UNREPORTED_CALL` (8,000 in, 1,000 out at the dearest price, about ₹4.4 a call today) is an upper
  estimate above JARVIS's own 12,000-character background prompts.
- **The narration** is written at build time and compiled with no AI (`compile_narration` reads
  scripts, facts and stamps only); a failing script is never compiled; every spoken line passes
  the pages' personal-word and secret guard (`explain.private_kinds`, filled), the code-name, path,
  number and cue checks. Sealing inside `pages.json.gz` (an optional field left out when absent) is
  as I0 found: a `v6.3.2` rollback loses only that release's full book (503 `unavailable`).
- **Effects safety (D11).** Pause holds every animation in the player (WAAPI pause, CSS
  play-state); Calm and reduced motion give cross-fades only, Off none; the fastest repeat is the
  typewriter caret at 1 Hz (two iterations); a hidden tab pauses and resumes only if it was
  playing; a slow device drops the ambient layer, then the packets.

## MEDIUM

| Id | Where (at `61b0a41`) | Issue | Fix | Test |
|---|---|---|---|---|
| M-1 | `docs/architecture/JARVIS-Architecture.md:2031` (§11), `:1343` (C57) | The roadmap still listed "R6.4 The Book's new look" as the first PLANNED row, so the short tour's "Next:" (`roadmap.next`) named the release being read, and the What's planned page and script ("phone calls at the top of the list") contradicted the table: an untrue spoken line. C57 said "being built" | Row removed; §11's opening says R6.4 is built and its "Not in R6.4" items wait for the owner (no row); the first row reads "Phone calls"; C57 says built, not yet deployed; guide v6.4.2 (`37c137e`) | `test_r63_seams`: a built release is never a planned row (red, then green) |
| M-2 | `src/jarvis/people/research.py:348-350` | A classifier call that refused (a non-public label) raised before its cost was recorded: a paid call outside the monthly limit, and an unpriced one never counted (I1's note) | The reply's cost is recorded before the refusal (a ₹0 entry judged by billing as before); a classifier that raised records nothing; `pg_card_c21` and the `module_people` script say so (`2cbc607`) | `test_r64_i1_unpriced`: refusing classifier billed once (priced and ₹0), a failing one not |
| M-3 | `evals/r6_3/run.py:54` | The plan's mock eval "narration scripts compile and pass the checks" (section 5) was never written ("evals before ship") | `evals/r6_3/narration.py`: a fixture compiled narrated with facts filled and a typed-number script not; each line check named; this checkout's 26 scripts; its control switches the line checks off (`cefad43`) | the part's own control fails it; `test_r63_seams` pins the four parts |

## LOW

| Id | Where | Issue | Fix / reason |
|---|---|---|---|
| L-1 | `core/brain.py:706`, `billing/service.py:435` | A stream the laptop answered on an unpriced brain was counted "price unknown" at the dearest price, while its stored turn said offline (safe side, but the pages say the laptop costs nothing) | `StreamMeter.offline` reads the request's offline mark (`2cbc607`); `test_a_stream_the_laptop_answered_is_not_price_unknown` |
| L-2 | `static/console-book-read-app.js:107` | The page the reader arrived on was saved as the place left off at, so the Continue card was gone after one more visit (I1's note) | Only a chosen page or the player's Stop is remembered (`eb327f1`); browser test, two more visits keep the card |
| L-3 | `static/console-book-chapter.js:284-288` | Each Play fetched every page of the chapter (27 for Integrations) against the 60-a-minute limit the reader shares | The release's pages are kept for the visit (60 at most); a chapter played again asks for none (`eb327f1`); browser test counts the requests |
| L-4 | 4 R6.4 browser test files | `ruff format --check` failed on them (CI runs `ruff check` only) | Formatted (`eb327f1`); the two left are `main`'s own |
| L-5 | `billing/service.py:461` (`_no_cost`, no reply) | A background call on an unpriced brain that the laptop answered is still counted as one `UNREPORTED_CALL` | Declined for R6.4: the safe side (over, never under); fixing it needs every background caller to pass its reply (recipes, brief, understood-as, eyes, talk, people, learning) |
| L-6 | `static/console-book-fx-chart.js:168` | On a slow device every trace becomes `draw`, so that family can repeat back to back | Declined: D11 puts 60 fps before variety (a phone drops layers first) |
| L-7 | `buildbook/writer/search.py:_score` | A query of one-letter words prefix-matches every word (about 190 ms on 153 pages) | Declined: owner only, 60 a minute, at most 8 words; typical queries take 30-80 ms |
| L-8 | `static/console-book-fx.js` (`show`), `book-read.css:264` (after the fix: `:158`, `:264`) | Found in the screenshots: on a phone the count's readout covered the flowchart's title | While a count is over the chart, a phone's chart layer starts below the readout (`fx-readband`); the camera fits it (`e597c79`); browser test |

Notes (no change): the 26 chapters run 256 minutes at 150 words a minute (4-14 minutes each, as
D5 says; the plan's "2½-3 hours in all" is low; no page states a total). In the player the camera
zooms to the spoken box and crops the rest of a tall chart at the stage's edge, by design (D11
camera). `tests/browser/test_vitals_board.py::test_edit_reuses_the_form_and_keeps_the_id` failed
once under load ("element is not stable") and passed alone; it is not an R6.4 file.

## What was sampled for accuracy

Ten pages against the code: `pg_module_book`, `pg_card_c57`, `pg_screen_book`,
`pg_chapter_costs`, `pg_chapter_planned`, `pg_module_vitals` (the systems check joins a running
run, `health/service.py:55-78`), `pg_card_c12` (wardrobe pieces in `undo/models.py:33-46`),
`pg_card_c16`, `pg_service_openai_compatible` and `pg_service_tailscale` (row 392). Three scripts:
`module_book`, `story_costs`, `story_planned`. Every claim held except `story_planned` and
`pg_chapter_planned`'s "phone calls at the top of the list", which the guide's table made untrue
(M-1, fixed in the guide), and `pg_card_c21`, made more exact with M-2's fix.

## The one final check pass (on `r6-4-review`)

FINAL-PASS

## Screenshots and recording

`/tmp/r64-review-shots/` (the REAL compiled book of this tree served through the routes' own code):
reader laptop and phone, Night and Day; search laptop and phone; the player at a `node` cue (line 6)
and a `count` cue (line 9), laptop and phone, Night and Day; the phone's Play bar; the Vault chapter
recorded for 65 s (Night, laptop): `vault-chapter-night-laptop.mp4` (H.264, 1.7 MB) and
`vault-chapter-15s.gif` (1.6 MB). Each was looked at: no overlap, clipped or faint text and no
off-theme font after L-8 (the camera's crop of a tall chart is by design).

## Change log

| Version | Date | Release | What changed | By |
|---|---|---|---|---|
| v6.4.0 | 25 Nov 2026, 16:10 IST | R6.4 | First edition: the combined security and code review of I1 @ `61b0a41`, its fixes (M-1 to M-3, L-1 to L-4 and L-8), the sample, the final pass and the verdict APPROVE | 🛠 Mark XXIV |
