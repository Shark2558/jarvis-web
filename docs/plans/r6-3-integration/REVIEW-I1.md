Version v6.3.3 · 23 Nov 2026, 22:10 IST · Release R6.3 · Status: Current · Owner: 🛠 Mark XXIV

# R6.3 combined review of I1 (fresh context, 23 Nov 2026)

Reviewed: `r6-3-i1` @ `bbb9aa8` (the four parts joined and wired) against `main` @ `47ee8fc`, with
`git diff main...HEAD` (168 files), the plan `docs/plans/r6-3-book-content.md` v6.3.3,
`I1-NOTES.md` and `INTEGRATION-{A,B,C,D}.md`. One reviewer for 🛠 Mark XXIV applying
`.claude/agents/security-reviewer.md`, `code-reviewer.md` and `python-reviewer.md` and the rules in
`.claude/rules/ecc/`, security first. By the owner's rule of 23 Nov this is the only review round:
the reviewer fixes what it finds (section "Fix"). Besides reading, the writer's packs were built on
this checkout's REAL `source.zip` and fact pack (`gen.write.build`, outside the repository).

**Verdict: BLOCK until fixed** (two HIGH), then approve. CRITICAL 0 · HIGH 2 · MEDIUM 6 · LOW 11
(M-5 and L-11 were found while fixing, M-6 in the final check pass; see "Fix"). **After the fixes: APPROVE**: every
CRITICAL, HIGH and MEDIUM fixed, seven LOW fixed, four declined with their reasons.

What holds, checked route by route: every spending grant is his typed `YES` on the server's ₹ words
(trial on its `we_` estimate, ₹100 from `Caps().trial`, never the pick's; the pick's grants on a
`wt_` terms id; the first write and Update on their estimate; "update by itself" by its own YES,
within the release cap); the ledger's hold is read and written in ONE transaction, fails closed
on an unreadable counter, and counts every open hold of a kind (two calls cannot race past a cap);
every writer route is `require_auth` + CSRF + `console_only` + the primary owner + a guest token
refused + `no-store` + a per-owner limit, and the show lock answers 423 to all 13 while a guest
show is live; a guest's tour is `tour.guest` (no T16, no owner-only line, no ₹, `costs` empty) and
`tour_line_text` reads only the session's audience; model output is parsed, checked (refs,
numbers, personal, unverified, invented, planned, shape, canary) and drawn with `textContent` only
(no `innerHTML` in any R6.3 module); no vendor SDK or model id outside `jarvis.llm`; `write_text`
refuses the laptop brain and `judge` refuses a model that is not the registry's BALANCED one; logs
carry type names and counts only.

## HIGH

### H-1 · The writer reads no code in production: `source.zip`'s root folder is never stripped

**Evidence.** R6's snapshot zips every file under one root, `JARVIS-source-<id>/`
(`buildbook/gen/snapshot.py:197`, `_zip(f"JARVIS-source-{repo.id}", entries)`). The writer's
`packs.read_source` (`writer/packs.py:71-84`) keeps the member names as they are, and `readable`
(`packs.py:56-67`) tests `low.startswith((".claude/", "tests/", "evals/"))` on them. Every test and
eval builds its zip WITHOUT the root (`tests/r63_fakes.py:158-163`, `test_r63_b_units.py:318`), so
none saw it. On this checkout's real build: 2,774 members, all `JARVIS-source-bbb9aa8/…`; **0 of
the 3,032 page references are found**, the guide is not found (no card), no plan section is found,
and 46 `.claude/**` and 1,132 `tests/**` members pass the never-read filter.

**Why it matters.** Every page of the trial, the first write and each update would be written from
a pack holding only its title, its facts and its `may_cite` list: no signature, no docstring, no
plan, no card (D4). The owner pays for pages written blind, the checks still pass them, and the
estimate (built from those packs) is about a tenth of the real cost (8.3 KB a pack instead of
75 KB). The D4/M8/L7 never-read guard does nothing: today it is only luck that a pack quotes a
file by its exact page reference.

**Fix.** One helper strips the snapshot's root (`JARVIS-source-<id>/`, only when the member has
it) before anything else; `readable` runs on the stripped path and also refuses a `.claude`
segment anywhere. A test builds the zip with R6's own `snapshot._zip`.

### H-2 · The free carry sees no change between releases (same root)

**Evidence.** `carry.tree_of` (`writer/carry.py:38-44`) hashes members by their zip names and
looks the guide up by `packs.GUIDE`. Two releases' names differ only in the root
(`JARVIS-source-<old>/p` vs `JARVIS-source-<new>/p`), so `old.files.get(ref)` and
`new.files.get(ref)` are both None for every reference and the cards are `{}` on both sides
(real build: 2,783 files, 0 cards).

**Why it matters.** At each new release every AI page is carried as unchanged, refilled and shown
as current even when the code it explains changed; no page is labelled "Changed in this release:
waiting for your Update", `update_ready` names only new pages, and "update by itself" never
rewrites a changed one (D11, D12, H3).

**Fix.** `tree_of` reads through H-1's helper.

## MEDIUM

### M-1 · The writer's and the pages' routes answer a bare 500 on a store, vault or ledger failure

**Evidence.** Both route wrappers catch `WriterRefused` only (`api/book_writer.py:113-118`,
`api/book_pages.py:46-55`). Raised past them: `CapRefused("unreadable")` from
`ledger.run_spent` in every view (`writer/part.py:83`, `:265`), `BookError`/`VaultTampered` from
the pages vault (`part.py:256`, `job.py:62-66` catches `LookupError` only), `BookUnavailable` from
`source.facts()` (a release whose facts file does not match).

**Why it matters.** The console gets "Internal Server Error" with no `no-store` and no plain words;
the plan's rule is a refusal in words (`unavailable`, 503), and a failure is logged by type.

**Fix.** Both wrappers also catch `BookError` and `CapRefused` and answer `unavailable` (503, the
writer's words), logging the error's type only.

### M-2 · A call that breaks with a non-LLM error after it started is released at ₹0

**Evidence.** `write_text` treats only `TimeoutError` and `base.LLMError` as a cut call
(`llm/write.py:99-104`); any other exception from a provider's stream (a parse error mid-stream)
escapes, and `Runner.call` then releases the hold (`writer/run.py:250-254`).

**Why it matters.** The call left and may be billed, but the ledger records nothing: the run's,
the month's and the % caps can be passed by spend they never saw (D8, H7).

**Fix.** Any `Exception` after text or usage arrived is a cut call (settled at its usage plus the
margin, never above its hold); before anything arrived it is `WriterUnavailable("no_answer")`.

### M-3 · A pick with seven grant lines loses the seventh, and the YES still grants it

**Evidence.** `consent.grants` returns `tuple(words[:6])` (`writer/consent.py:83`). A pick that
switches to a paid brain (1 line), raises the four rupee caps (4 lines) and the % line (1) and
turns "update by itself" on (1) has 7 lines: the AUTO line is cut, while `terms_id` binds
`auto=True`, so his YES grants "update by itself" without its words shown. The console cannot send
a trial raise today (6 lines at most), but the server's H2 guarantee must not rest on the console.

**Fix.** The cap raises are one sentence ("This raises the first full write's cap from ₹… to ₹…,
the release cap …"), so the most lines a pick can have is five; no truncation.

### M-4 · Building the packs blocks the server for minutes (shown by H-1's fix)

**Evidence.** With the code really read, a pack takes about 1.2 s (153 pages: 183 s, mean 75 KB):
`packs._mentioned` compiles and runs one regex per known name over the cited text (0.39 s a
call, three calls a page), `plan_sections` one regex per mark per plan section, and the scrubber
cleans the same plan and code blocks again for every page that quotes them. `Estimates.size`
(`writer/estimate.py:169-176`) builds every page's pack inside `GET …/estimate?run=first`, an
async route, so the event loop stops for minutes; each step builds its page's pack on the loop
too.

**Fix.** `_mentioned` reads the text's identifiers once (a set; the regex only for a name that is
not an identifier), `plan_sections` one combined pattern, the scrubbed block text cached per
release in the runner; the estimate's sizes are built in a worker thread
(`asyncio.to_thread`), so the loop never waits on them.

### M-5 · R6's browser tests are red on the joined branch (found while fixing L-6)

**Evidence.** Since I0 the Book panel asks `GET /v1/book/writer` at its first open and
`GET /v1/book/pages` once an owner session is open (`console-book.js`'s `more()`, C's modules).
R6's page-route mock `tests/browser/book_mocks.FakeBook._route` answers neither and falls through
to 404, and R6's files fail their "no console error" check: `test_book_panel.py` 5 of 13 red here
(the browser's "Failed to load resource: 404 … /v1/book/writer"). Its other users
(`test_book_lock_ui.py`, `test_book_show*.py`, `test_r62_book_listen.py`) share the mock. I1 ran
C's and D's browser files only.

**Why it matters.** CI's browser job runs every file on the pull request: it would be red.

**Fix.** The mock answers both as a server whose writer is off (`{"on": false}`, a pages index
with no parts), so both modules draw nothing; C's files still send those routes on to C's fake
server (`r63_fakes_c.route_c`, registered after the mock).

### M-6 · The Markdy guard is red on the joined branch (found in the final check pass)

**Evidence.** `tests/test_markdy_export.py::test_nothing_the_app_ships_mentions_markdy` reads every
text file under `src/` for "markdy"; part A's generator names the dev tool's lock file
(`buildbook/gen/inventory.py:13, :41` as the constant `MARKDY`, `gen/pages_index.py:60`) to list
its packages' licences in the book. I1 did not run the whole suite.

**Why it matters.** CI's unit job would be red; the guard's purpose (the console and the book never
LOAD Markdy: esm.sh would break the CSP) is not at stake: the generator reads the lock file as data.

**Fix.** The guard takes out only that exact path, only under `buildbook/gen/`, before its check
(every other mention, and "esm.sh", still fails it); the constant is `DEV_TOOL_LOCK`.

## LOW

| Id | Evidence | Why it matters | Fix |
|---|---|---|---|
| L-1 | `api/book_pages.py:46-49` skips `console_only`; R6's sections apply it (`api/book.py:160-161`, G11) | a bearer script holding an owner book token reads the full book; G11: the book opens in the console only | `console_only` after `owner_session` (an unsigned bearer stays 401, as the contract and the `e2e` suite expect) |
| L-2 | `writer/part.py:97-103`: `_start`'s transaction sets the run without looking again | two YES requests at once (a double tap) both start; the second replaces the first's run (same ledger key, so no cap passed) | the transaction refuses `running` when a run is active |
| L-3 | `writer/part.py:168`: `free.run` raises out of `tick` | a vault blip or a full store in the free work stops an approved run's clock step for that tick | the free work's failure is logged by type and the step goes on |
| L-4 | `console-book-writer.js:76-79`, `:283`, `:302` (I1 item 24) | the trial's rows say "Chapter example", "Card C16" (page ids), not the page's title | `TrialRow.title` (default "", so older fakes still read) from the fact pack; the console shows it, the id's words only as a fallback |
| L-5 | `console-book-writer.js:109-110` adds its own "may learn" line after the server's `TRAINS_WORDS` (`estimate.Estimates.sent_to`) (I1 item 24) | two near-duplicate Gemini lines in the YES box | the console's line goes: the server's words are the ones shown |
| L-6 | `console-book-reader.js:74, 86, 93, 104, 117, 134, 142` (R6) | "1 plans", "1 parts", "1 flows", "1 libraries" … in the Book panel's section counts | one `count(n, word)` that pluralises |
| L-7 | `writer/texts.py:112` "({count} pages, …)", `:94-96` "{left} page(s)" | "1 pages" in the sealed notice | the count words built by one helper |
| L-8 | `writer/caps.py:247-259`: a stale hold settles into the ledger, not into billing | after a crash mid-call the % line (Vitals month + open holds) misses that one call | **declined**: the run and month caps count it (`runs[kind]`); writing a maybe-unbilled call into Vitals would overstate his bill; at most one call (₹11.84 worst case) a crash |
| L-9 | `writer/privacy.py:82-95` does not wait for a step in flight | a draft or trial page that step keeps can land after Privacy → Delete | **declined**: the writer's document (the grants) is gone, so the step's next page reads no run and nothing more is spent; what landed is ids and sealed blobs, swept at 30 days (`drop_old`) |
| L-10 | `api/r6_wiring.py:128` `wire_book` is 51 lines with the writer's one line | over the 50-line rule by one | **declined**: R6's function (its body 38 lines, the signature 11); splitting it moves R6's wiring order for no behaviour |
| L-11 | `api/book_writer.py:57-61`: with the writer off (no keyring, `setup_failed`) `GET /v1/book/writer` is 503 | the browser logs one "Failed to load resource" line at each Book panel open | **declined** for R6.3: no behaviour or data at stake; R6's own status route answers a plain 200 `{available: false}` for this, and the writer's view could do the same in R6.4 |

Seen and not findings: `judge`'s tier check compares the tier the writer asked for (the model
check is the one that refuses a resolved fallback); the trial's estimate prices the paid brain
only (the training brain is free); a pages index of an older release uses the current release's
page list (pages of that release that are no longer in it are not shown).

## Fix

Each fix had its test first (red for the reason the finding names, then green); only the files a
fix touched were run with it. New tests: `tests/test_r63_review_i1.py` (one or more a finding),
`tests/browser/test_book_panel.py::test_the_section_counts_say_1_plan_never_1_plans`, and the
trial's browser cases in `tests/browser/test_r63_c_trial.py`.

| Finding | Commit | What changed |
|---|---|---|
| H-1, H-2 | `b8d36b1` | `packs.member_name` takes R6's snapshot root off in `read_source` and `carry.tree_of`; `readable` refuses a `.claude` folder at any depth. On this checkout's real build: 2,855 of the 3,032 page references found (the rest are folders, vendored or binary files a pack never reads), the guide and its 73 cards found, 0 `.claude/**` and 0 `tests/**` members readable |
| M-4 | `720be3a` | `_mentioned` reads the text's word runs once, `plan_sections` one pattern, each release's scrubbed blocks cached in the runner, the estimate's and the step's packs built in a worker thread: 153 packs 183 s → 30 s, never on the event loop (the first write's estimate still takes about 30 s once a release; cached after) |
| M-1 | `311383f` | `book_writer.answered()` (both routers): `BookError` and `CapRefused` → 503 `unavailable` in words, `no-store`, logged by type |
| M-2 | `671e9e4` | `write_text`: any exception after text or usage arrived is a cut call; before anything, `WriterUnavailable("no_answer")` |
| M-3 | `9a65e10` | the cap raises are one sentence (`texts.RAISE_WORDS` + `RAISE_ONE`, `texts.listed`); `grants` never cuts (five lines at most) |
| L-1, L-2, L-3, L-7 | `860bd9b` | pages: `console_only` after the book session; `_start` refuses `running` inside its transaction; the free work's failure logged (`free_failed`) and the clock step still runs; `texts.pages_words` ("1 page") in the sealed notice and the run's words |
| L-4, L-5 | `400e4d0` | `TrialRow.title` (a seam addition, default "") filled from the fact pack and shown by the console (the id's words only as a fallback); the console's own "may learn" line removed from the trial's YES box |
| L-6 | `6b5fdff` | the reader's `count(n, one, many)` for every section summary |
| M-6 | `2110585`, `650e897` | the guard skips only `tools/markdy/package-lock.json` under `buildbook/gen/`; `inventory.MARKDY` renamed `DEV_TOOL_LOCK` (the guard lowercases what it reads; `2110585`'s own check was misread as green, `650e897` completes it) |
| M-5 | `eae6683` | `book_mocks.FakeBook` answers `GET /v1/book/writer` and `GET /v1/book/pages` as a server whose writer is off |
| L-8, L-9, L-10, L-11 | — | declined, the reasons in the table above |

Seam note (for `INTEGRATION-B.md`/`-C.md` readers): `writer/http.TrialRow` has one new optional
field, `title`; I0's fake server leaves it "", C's fake fills it.

## Change log

| Version | Date | Release | What changed | By |
|---|---|---|---|---|
| v6.3.3 | 23 Nov 2026, 22:10 IST | R6.3 | M-6 (the Markdy guard, found in the final check pass) and its fix; MEDIUM 6 | 🛠 Mark XXIV |
| v6.3.2 | 23 Nov 2026, 20:51 IST | R6.3 | The fixes: H-1, H-2, M-1 to M-5 and L-1 to L-7 fixed with their commits; M-5 and L-11 added (found while fixing); L-8 to L-11 declined; verdict after the fixes APPROVE | 🛠 Mark XXIV |
| v6.3.1 | 23 Nov 2026, 20:36 IST | R6.3 | First edition: the combined security, code and Python review of I1 @ `bbb9aa8`, block until the two HIGH are fixed | 🛠 Mark XXIV |
