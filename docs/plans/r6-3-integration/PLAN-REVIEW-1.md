Version v6.3.1 · 23 Nov 2026, 14:55 IST · Release R6.3 · Status: Current · Owner: 🛠 Mark XXIV

# R6.3 plan review 1 (fresh context, 23 Nov 2026)

Plan reviewed: `docs/plans/r6-3-book-content.md` v6.3.1 (Draft), all 1,118 lines, on `r6-3-plan` @
`ad65e99` (the code is `main` @ `47ee8fc`: `git diff --stat 47ee8fc ad65e99` touches only the plan and
`docs/plans/r6-2-book-rebuild/PHASE-A-FINDINGS.md`). Checked against that code, the generator run
on a clean `47ee8fc` checkout, the project's locked dependencies (a scratch venv outside the
repository) and Anthropic's rate-limit page (read today). Reviewer: a fresh-context agent for
🛠 Mark XXIV applying `.claude/agents/code-reviewer.md` and `security-reviewer.md` to a plan.
Read-only apart from this file. "L" numbers are the plan's lines at `ad65e99`.

**Verdict: APPROVE WITH CHANGES.** CRITICAL 0 · HIGH 7 · MEDIUM 9 · LOW 12.

No CRITICAL finding. The seven HIGH findings (H1–H7) must be written into the plan before I0; the
MEDIUM ones should be; the LOW ones are the planner's call. None needs a new owner question; H2 and
H3 change what the owner is told (summary items 4, 5 and 7). The core design holds: one write seam
inside `jarvis.llm` by tier that never falls back, the same scrubbed public pack for both brains, no
tool, holds before every paid call, the typed YES bound to the estimate shown, nothing written by AI
for the tour, and a fixed, timed script whose every number is a fact.

The review file names nobody: where a finding is about the owner's identity it says "the owner's
GitHub handle" or "a place example", never the word itself (this repository is public).

## HIGH

### H1 · A guest can be read the owner-only tour lines: the speak route has no audience for them

**Evidence.** `POST /v1/book/show/speak {line_id}` → `BookService.line_text(uid, session, line_id)`
(`buildbook/service.py:339–345`) checks the guest lock, then calls `self.show.line_text(uid,
line_id)` (`:345`) **without the session's audience**; `ShowScript.line_text(uid, line_id)`
(`buildbook/show_script.py:58–65`) has no audience parameter. Seam 10 (L878–880) only teaches
`show_script.line_text` to hand a `^t\d{2}b\d{2}$` id to D's `tour_line_text` ("stub: None"), and the
size guards freeze `buildbook/service.py` at "397 (no edit, ≤ 400)" (L1014). The owner-only lines
are `t13b03` (the ₹ per picture and the ₹ month cap, L408) and the whole of T16 (`t16b01`, the ₹
scene, L431).

**Failure.** In a guest's show, a request for `t16b01` or `t13b03` returns their text to the speak
path; with the owner's show voice set to the Cloud voice the guest hears them. `GET …/show/script`
filters by audience (D9) and the tour suite's "no ₹ for a guest" case (L993) checks only the served
script, so every planned test passes while the route leaks.

**Change.** Seam 10: `ShowScript.line_text(uid, line_id, audience)` and `tour_line_text(book,
line_id, audience)` returning None for an owner-only beat or scene in a guest session (→ 404
`unknown_line`, the same answer as a made-up id); `service.py:345` passes `session.audience` (a
one-line change, the file stays 397). Add the I0 seam, a D case "a guest's speak of every owner-only
tour id is 404" and its control (the audience argument ignored: the case fails). Remove
`service.py` from "no edit" in the size guards (keep ≤ 400).

### H2 · Spending authority can be granted without a confirmation step (auto-update, the brain, the first caps)

**Evidence.** `PUT /v1/book/writer/pick {brain, caps, auto_update, confirm_cost?}` refuses only "a
cap raised without `confirm_cost: true`" (L776); D7: "Saving the pick spends nothing; raising a cap
above what he last confirmed needs `confirm_cost: true`" (L622–623). Nothing asks for a confirmation
to turn **"update by itself within the release cap"** on (L621, L716–717), to switch the brain from
Gemini (₹0) to Claude, or to save the very first caps (there is no "last confirmed" value yet). The
data model's `confirmed {caps}` (L747) has no stated starting value.

**Failure.** He ticks "update by itself" in Book settings; at the next deploy `book_write` spends up
to ₹500 for that release (₹1,000 a month) with no ₹ ever shown to him for it. Summary item 5 tells
him "Nothing spends money by itself after a deploy" (L49) with this as the one exception, which is
exactly the case R6.2's pattern exists for (`buildbook/owner.py:80` `CostNotConfirmed`: a switch that
can cost money needs `confirm_cost: true` in the same patch).

**Change.** D7 and the HTTP row: `confirm_cost: true` is required (422 `confirm_needed` otherwise,
nothing saved) for (a) `auto_update` false → true, shown as "up to ₹500 a release and ₹1,000 a month,
by itself after each deploy"; (b) any change of `brain` to a brain whose BALANCED model is paid
(`pricing.is_paid`); (c) the first saved pick, because `confirmed.caps` starts at zero, so every
non-zero cap is a raise. The audit records `cost_confirmed` (already planned). Add writer cases and a
control (auto-update accepted without `confirm_cost`: the case fails); C's ₹ dialog for each.

### H3 · The AI pages do not survive: they are carried forward only on Update, and a release's pages file can never be replaced

**Evidence.** D11: "an update opens the previous release's pages file, carries every unchanged
page's template, refills its facts … and writes only the changed pages" (L702–704). D12: nothing is
called until he taps Update; "If he never updates, the reader shows the last release's AI pages for
unchanged parts" (L714–718). Every seal prunes to three releases (`sealer.py:140–145` `_prune`,
`KEEP = 3` at `model.py:65`), and hotfixes count (L1042). The attach is described once per release
("attaches it to the already-sealed release", L698–700); no step replaces a release's pages file.

**Failure.** (1) Three releases (or two hotfixes and a release) seal without his Update: the last
release that has a pages file is pruned with its chunks, every AI page is gone, and the next Update
finds "an unreadable previous pages file → the update rewrites those pages" (L802): a ≈ ₹1,120
rewrite behind a ₹500 release cap and one tap, while `POST …/first` answers 409 `already_written`
(L777). (2) A first write that stops at its cap (L626–627) or by Stop (L779) is sealed as a partial
pages file; continuing next month or after a raised cap needs a second pages file on the same
release, which D11 does not allow.

**Change.** (a) At each new release seal, `book_write` builds the new release's pages file **free**
(no brain call): every unchanged page carried and refilled, every changed page as the generator's
text marked "changed, waiting for your Update"; only then does `update_ready` show the ₹. (b) The
vault gets attach-or-replace for `pages`: a replace puts the old file's chunk set in `orphans` in the
same index transaction (the R6 prune pattern), so the newest pages file always wins. (c) A rewrite
of more than the release cap's worth of pages, or with no carry source, goes through `POST …/first`
(typed YES), never through a tap. Tests: three seals without Update keep every unchanged AI page;
a capped first write resumed next month replaces its pages file; controls (carry only on Update: the
three-seal case fails; no replace: the resume case fails). Summary item 5 says the carry is free.

### H4 · The parts' file lists and the I0 seams miss existing files that B, A and D must change

**Evidence.** Parts own only their listed files, "never a wiring or shared file" (L911–912), yet:
- **`buildbook/seal.py`** (DocsBookVault): the only index read-modify-write is the private
  `_change(uid, fn, held=)` (`:110–138`), with the Privacy hold check, the pending → chunks → commit
  order and orphans (`:192–223`, `:233–265`). `seal_attach.py` (B, L698–700) can only reach these by
  editing `seal.py` or by copying the index code. `read()` uses `found.file(kind)` (`:299`), which is
  `next(...)` (`model.py:291`): for a release without a pages file it raises `StopIteration` (a
  `RuntimeError` inside a coroutine), not `LookupError`.
- **`buildbook/ports.py`** `BookVault` (`:88–118`) has no attach, replace or optional read.
- **`buildbook/seal_notices.py`, `seal_words.py`, `sealer.py`**: D11's two new notice texts, the
  80 % warning "the sealer's notice says it once a release" (L707) and D12's "The AI pages wait for
  your Update (about ₹300)" (L714) are the sealer's words; `SealNotices.tell` (`seal_notices.py:88`)
  claims "told" per release, so a second `book_sealed` for the same release needs its own claim key.
- **`buildbook/privacy.py`** `BookSealedSource` (`:59–118`): "R6's `book_sealed` row counts the pages
  files" (L724–725).
- **`api/book.py`**: the Book panel's 80 % warning "with the sizes" (L706–707) needs a field in an
  existing route.
- **`buildbook/model.py`** `SealedRelease._one_of_each` (`:279–284`, exactly `["book", "source"]`)
  and `file()`; seam 3 names `files` 2–3 but not the validator.
- **G4** (L691): "all of them, the reader pages them" needs `Book.limitations`
  (`model.py:235`, `max_length=MAX_LIMITATIONS`) or a new home, and `console-book-reader.js`; neither
  is in A's list nor a seam.
- **`buildbook/service.py:345`** (H1).

**Failure.** Builders in parallel worktrees either edit shared files (merge conflicts at I1, review
scope lost) or re-implement the sealed index's transaction beside the sealer's, where a missed
`held=` lets an attach in flight bring a pages file back after Privacy → Delete.

**Change.** Add I0 seams with stubs: `seal.py` `attach(uid, rid, kind="pages", data, now)` and
`replace(...)` through `_change(held=rid)` and the pending/orphans path, `read()` raising
`LookupError` for a missing kind; `ports.BookVault` gains them; `seal_words`/`seal_notices` gain the
three texts and a claim key per (release, kind); `privacy.py`'s count and `api/book.py`'s storage
field; `model.py`'s validator. Decide G4's home (a `facts.json` list plus a "+N more" line is enough)
and assign the reader change to C. If M4's separate pages index is taken, most of these shrink to
one new module.

### H5 · Checks (1) and (2) cannot be met by the data D2 and D3 give them

**Evidence, check (2) "numbers come from facts"** (L679–681): outside the made-up example, every
number must be a `{{fact:…}}` the filler knows; years in dates and version strings are the only
exceptions. D2's facts are the 179 settings, `gen/costs.py`, versions and the tour's ≈ 25 named
constants (L527–530). The code has **1,460 numeric module-level UPPER_CASE constants in 505 files**
(an AST count on `47ee8fc`), and the trial's own technical sample page `pg_card_c16` (the router)
cannot state its two-minute laptop window (`llm/fallback.py:65` `BREAKER_S = 120.0`) or the 5 s
No-AI refresh (`llm/router.py:43`). The exceptions also miss C-ids (`C16`), release labels (`R13.1`),
HTTP statuses (403, 429), standard names (SHA-256, AES-256-GCM, UTF-8, IPv4, WebGL2, 3D) and digits
inside backticked references (`r6_wiring.py`, `/v1/…`).

**Evidence, check (1) "every reference exists"** (L676–678) against the fact index of full paths
and `path:symbol` (L530–531): the guide's "Where in the code" cells, which D3 makes each card page's
sources (L553–554), hold **589 backticked references: 201 full paths, 388 short names (122 of them
ambiguous: the same file name in more than one package), 88 directory references in 60 cards, and 61
other tokens** (job names, partial paths such as `brief/service.py`, symbols). Module constants are
not in the index either.

**Failure.** The brain echoes the card's short names and needs ordinary numbers; check (1) refuses
the short names (or, loosened to file names, passes any `service.py`), check (2) refuses the
numbers; each refused page has cost two paid calls (≈ ₹15 at mid) and keeps the generator's text.
The trial then compares the brains on a check that fails good pages.

**Change.** A: (a) the fact pack and index add every top-level UPPER_CASE constant with a literal
value as `path:NAME` = value (AST; ≈ 1,460 entries, ≈ +60 KB, still ≤ 1 MiB); (b) `pages_index`
resolves every guide reference to full paths (the directory named earlier in the same cell first,
then `src/jarvis/`, `src/jarvis/api/static/`), fails the generator on an unresolvable or ambiguous one
(I0 fixes those cells in the guide), and stores each page's `refs` as full paths; directory
references expand to their files for D12; (c) the prompt asks for references only from the pack's
list. B: check (2) exempts backticked references, `C\d{2}`, `R\d+(\.\d+)*`, versions, HTTP statuses
and a fixed list of standard names. Add a precision case (one hand-written good page per trial
sample passes all six checks) with its control (an exemption removed: the case fails).

### H6 · The owner's GitHub handle is in 46 Android paths: the fact index and the scrubbed packs disagree

**Evidence.** `git ls-files` on `47ee8fc`: 46 tracked paths (all under `android/`) contain the
owner's GitHub handle, which is one of the four hashed words in `buildbook/gen/redact.json`
(checked by hash), and every Kotlin file's `package` line carries it. `Scrubber.clean` turns
`android/app/src/main/java/io/github/<handle>/jarvis/health/Await.kt` into
`android/app/src/main/java/io/github/[removed]/jarvis/health/Await.kt` (run on `47ee8fc`). D2's
index holds "every tracked path" (L530) and calls `facts.json` public (L563), but does not say
whether `facts.json` passes `Scrubber.verify`; D4 scrubs every pack (L571); D10 (1) compares the
page's paths with the index (L676–678). Cards C62, C64 and C65 cite these files.

**Failure.** Either `Scrubber.verify` runs on `facts.json` and raises `ScrubLeak` on the first
build (`--best-effort`: the release has no book), or it does not and the handle sits in `facts.json`
while every Android page's references come back as `[removed]` paths that check (1) refuses, twice,
for every Android card, module and screen page, on every release.

**Change.** D2: the index stores each path in its scrubbed form (`Scrubber.clean(path)`, a stable
placeholder) and `facts.json` passes `Scrubber.verify` like `book.json`; packs and check (1) use the
same form; the reader's code chips show it. Add a needle for the handle in a path (the pack, the
page, `facts.json`) with its positive control, and a test that every Android page's references
resolve.

### H7 · One page in one call does not fit the call window it gets; a cut call is billed and produces nothing

**Evidence.** D5: each call is `write_text(…, max_tokens=4000, timeout_s=min(40, left − 3))`
started while `time_left() ≥ 35 s` (L585–587), inside `book_write`'s 45 s budget (the tick's
`MAX_BUDGET_S = 60`, `ticks.py:32`; the watchdog's 50 s for all its jobs, `home/watchdog.py:61`,
shared with `selfwatch_clock`, the laptop check, `health_check`, `helpers_clock`, `mobile_clock`,
`outfit_clock`, `book_seal`, `book_sweep`); the console step is also capped at 45 s (L587–589). The
plan's own estimate is "a Sonnet page ≈ 20–40 s" (L590) for 2,200–3,500 output tokens (D8), so its
slow end is the cut-off. D8 settles a cut stream **at the hold** (₹8.95) "and redrafted once"
(L638–639, L802). The tick's `asyncio.timeout` cancels the job outright (`ticks.py:101–104`).

**Failure.** A 3,500-token page at 75 tokens a second (Unverified for Sonnet 5.5) needs ≈ 47 s
before its first-token wait. It is cut at ≤ 40 s, counted at ₹8.95, redrafted, cut again and
refused: ≈ ₹18 in the ledger and real tokens billed for no page. In the trial, three such pages
use up the ₹60 cap with nothing to compare.

**Change.** (a) The console step (the trial's driver while he watches) gets its own budget of
≈ 150 s (Cloud Run's `--timeout 300`, `cloudrun.sh:624`) with one call at a time and `timeout_s` 120;
the trial runs only on the step and records each call's seconds. (b) The tick job starts a call
only when the trial's p90 seconds + 5 ≤ `time_left()`; otherwise it leaves the run to the step (or
to owner question 5's Cloud Run Job), said so in the run's view. (c) A page whose text ran past the
window is not redrafted from scratch on the tick: it waits for the step. (d) D8 settles a cut call at
`pricing.stream_usage` (exact input from `message_start`, at least the output received) **plus** a
margin, never below what was received, instead of the full hold (the ledger then matches the bill).
Add the cases (a slow fake stream of 50 s: no tick call starts; the step finishes it) and a control
(the p90 gate removed: the slow-stream case fails).

## MEDIUM

(continued in the next edition of this file)

## Change log

| Version | Date | Release | What changed | By |
|---|---|---|---|---|
| v6.3.1 | 23 Nov 2026, 14:55 IST | R6.3 | First findings: verdict APPROVE WITH CHANGES, counts, H1–H7 | 🛠 Mark XXIV (plan review 1) |
