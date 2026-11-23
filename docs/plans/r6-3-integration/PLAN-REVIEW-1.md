Version v6.3.1 · 23 Nov 2026, 14:51 IST · Release R6.3 · Status: Current · Owner: 🛠 Mark XXIV

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
MEDIUM ones should be; the LOW ones are the planner's call. None needs a new owner question; H1–H3,
M1, M3 and M8 change what the owner is told (summary items 3, 4, 5, 7 and 8). The core design holds: one write seam
inside `jarvis.llm` by tier that never falls back, the same scrubbed public pack for both brains, no
tool, holds before every paid call, the typed YES bound to the estimate shown, nothing written by AI
for the tour, and a fixed, timed script whose every number is a fact.

The review file names nobody: where a finding is about the owner's identity it says "the owner's
GitHub handle" or "a place example", never the word itself (this repository is public).

## HIGH

### H1 · A guest can have the owner-only tour lines read out: the speak route has no audience for them

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

### M1 · D8's holds are not an upper bound, the 80 % gate cannot see them, and stale holds have no rule

**Evidence.** The hold's input is "the pack cap + the system prompt ≈ 27,000 tokens" with the pack
capped at "24,000 tokens (characters ÷ 4)" (L566, L633–634); the code calls ÷ 4 a "rough English
average; used only when a provider reports no usage" (`llm/pricing.py:62`), and source code with
paths and symbols usually tokenizes denser. A call then settles "at the reported usage" (L638–639),
which can be above its hold. The 80 % gate is `billing.spend.ensure_spend_allowed` "with the hold"
(L637), which reads only the meter's settled month (`billing/spend.py:43–60`): with two calls in
flight neither sees the other's hold, and adding the ledger's `spent_inr` to the meter would count
settled calls twice (they are also `billing.record`ed, L640–642). D8 says "R13.1's pattern" but
leaves out what that pattern needed: holds older than an hour turned into spend at their hold
(`settle_old`), closes retried and kept in `pending` (`close_later`), and the month before read for
an hour after his IST month's end (`wardrobe/seeme/cap.py:13–32`). The Claude provider retries
transient errors itself (`max_retries=s.llm_max_retries`, 2 by default: `llm/factory.py:19`,
`config.py:179`), so a 429 or 529 being retried when the call's own timeout fires looks like a cut
stream and is settled at the hold although nothing was billed.

**Why it matters.** "D8's holds make it exact: no call starts that could pass it" (L609–610) and
"the risk is a run stopping early, never an overspend" (L1029–1030) are not quite true: the trial can
end a few rupees above ₹60 (at most the excess of the calls in flight), and a crash leaves a hold
that blocks its page for ever.

**Change.** (a) The hold's input counts the pack's UTF-8 bytes ÷ 2.5 (or the vendor's own token
count through a `jarvis.llm.write.count_tokens` that is free), the system prompt at the cache-write
price; a settle above its hold stops the run and says so. (b) The 80 % gate is meter used + the
ledger's open holds + this hold ≤ 0.8 × limit, in one place, tested with two calls in flight.
(c) `book_write` runs R13.1's `close_later` and `settle_old` first; the month-boundary read is
copied. (d) `write_text` uses a provider built with `max_retries=0` (inside `jarvis.llm`), so a
429/529 is a clean release, never a cut stream. (e) Summary item 3 says "stops at ₹60" only once (a)
holds; the trial test settles one call above its hold as a control.

### M2 · A brain whose price is unknown would be offered at ₹0

**Evidence.** The registry builds a Claude brain, a Gemini brain and an OpenAI-compatible "Custom"
brain (`llm/brains.py:119–158`). With `gemini_paid_tier` on, Gemini is labelled "Gemini", does not
train on content (`:132`, `:137`) and is still priced at $0 (`llm/pricing.py:32–36`: "If
gemini_paid_tier is enabled, add real prices here before relying on cost metering"); a custom
brain's model is usually not in the price table at all (`cost_usd` meters it at $0 with one warning,
`:94–100`). D1 offers "only brains in the registry" (L517–519) and D7 "Claude or Gemini (free)".

**Why it matters.** An estimate of ₹0 makes every cap and the 80 % gate a no-op while the vendor
bills him.

**Change.** D1: the writer offers a brain only when its BALANCED model `pricing.is_priced` and
either `pricing.is_paid` or the brain is the free tier (`trains_on_content`); otherwise "price
unknown: not offered". In R6.3 that means `anthropic` and the free `gemini` only. Add a case and a
control (a paid-tier Gemini offered at ₹0: the case fails).

### M3 · The writer can ride the 5-minute clock with Home off; the "few days" time is also mis-added

**Evidence.** `tick_wiring.add_clock_job(app, job)` registers "5-minute advisory jobs … so they also
run with Home off" (`api/tick_wiring.py:8–9`, `:66–71`; the route runs them at `api/home.py:150–178`).
D5 puts `book_write` in `r6_tick_jobs`, which joins the watchdog only when Home is on
(`api/r6_wiring.py:216–218`), so with Home off the writer has the 16 morning ticks only. The plan's
own arithmetic then gives ≈ 6 days, not ≈ 4 (L592–593, L1026–1027): one round of at most 2 calls a
morning tick (the step starts calls only while ≥ 35 s is left of 45 s), 190 calls ÷ 2 ÷ 16 = 5.9 days.

**Change.** Register `book_write` through `add_clock_job` (advisory, after the others) as well as on
the morning tick; the seam list and the pins move accordingly (`ADVISORY_JOBS` still gains it).
Summary item 8, D5, the risks and owner question 5 then say "about half a day, Home on or off",
subject to H7's call window.

### M4 · Sealing the pages into R6's index makes the index unreadable to every older revision

**Evidence.** `BookIndex`, `SealedRelease` and `SealedFile` are `Frozen` with `extra="forbid"`
(`buildbook/sections.py:58–59`); `FileKind = Literal["book", "source"]` (`model.py:83`); `files`
has `max_length=2` (`:277`). `_decode` turns any `ValidationError` into `VaultTampered`
(`seal.py:90–100`): "The sealed build books failed their check, so they stay closed" plus the
index-tampered notice. `Book` also forbids extra keys (`model.py:227`), so `tour` fails an older
`load_book`.

**Why it matters.** A traffic rollback to a pre-R6.3 revision, or the old instance still serving
during a rollout, reads an index holding a `pages` file as tampered: a false security alarm, and the
old sealer cannot seal. The plan tests only backward compatibility ("old books and indexes still
load", L849–850).

**Change.** Keep the pages files in their own sealed index document (`{prefix}book_pages/{uid}`,
purpose `book_index`, its own AAD `book/pages/{uid}/v1`, the same chunk envelope), counted in the
60 MiB total by the writer and dropped by the writer's sweep when their release leaves R6's index;
R6's index and `SealedRelease` stay as they are. This also removes most of H4's `seal.py`,
`model.py` and `privacy.py` edits. If the plan keeps one index, it must say "no rollback below
v6.3.0" in the runbook and test that a v13.1.0-shaped reader is never deployed against it.

### M5 · A run that spans a deploy has no rule

**Evidence.** Packs come from "the release's `source.zip` and `facts.json` … both in the image"
(L563–564); a run records its `release` (L747); the first write takes ≈ 11 hours to ≈ 6 days (D5,
M3); hotfixes are frequent (L1042). Nothing says what a step does when `BookSource.current()` is a
newer release than the run's.

**Why it matters.** The new image holds only the new release's code and facts, so a continuing run
would seal pages describing release N+1 into release N's pages file, or check them against the
wrong index; and the owner's YES was bound to release N's estimate.

**Change.** A run is bound to its release id. When the current release changes, the next step stops
the run ("a new release came"), seals what is written into release N's pages file (with
`skipped`), and the rest joins release N+1's update estimate with its own confirmation (H3's free
carry first). The YES never carries to a new release. Add the case with a control.

### M6 · The tour's pictures have no data of their own

**Evidence.** Each picture draws its scene's `facts` as objects `{label, value, n, group, flag}`
grouped by meaning: `purpose` for the keyring (`console-book-scenes-data.js:39`), `home` / `edge`
(`:78`), library groups (`:111`), ₹ bars from `n` (`:141`), checked in `console-book-show.js:72–73`.
D9's tour scene carries `facts [keys]` (fact-pack keys for the placeholders, L652–654) and a
`visual` number; D9 says today's pictures will "draw the tour's own labels" (L668–669). No tour field
holds such objects.

**Change.** D9: each tour scene has `picture: {visual, facts: [{label, value, n, group, flag}]}`,
written in `tour.json` with placeholders and filled at CI, and `tour.py` checks per `visual` that the
groups its module reads are present (a table in D9). Or say plainly that a tour scene shows the
borrowed show scene's own facts unchanged. Either way, a D test per visual with a control.

### M7 · "The 31 outside services" have no single source: the guide's §5.2 has 24 rows

**Evidence.** The tour's `services.count` is "rows of the guide's §5.2 (`arch_coverage.py` keeps it
equal to the code)" (L458) and D2/D3 take "the 31 outside services (the guide §5.2)" (L528, L548–549).
§5.2 of `docs/architecture/JARVIS-Architecture.md` v13.1.5 has **24** data rows. The 31 in
`scripts/arch_coverage.py`'s report (`:256`) are the code's inventory (settings and API hosts),
checked against the items of every card's "Outside services" field (`:197–206`), not against §5.2.

**Change.** D2: the services list is the coverage checker's inventory with its names as the cards
spell them (one shared function, so `arch_coverage.py` and `facts.py` agree); `services.count`,
`pg_service_*` and G3 come from it; a test pins the count to the checker's. Recount the pages
(152 assumes 31).

### M8 · What the free brain may still read about the owner, and the summary's promise

**Evidence.** `redact.json` holds four hashed words (the owner's name and handle among them; checked
by hash). Two place examples used as the owner's home and work in the console's Maps settings
placeholder (`src/jarvis/api/static/console-media.js:297`) and in `evals/maps/cases.jsonl:7` are not
in it, and `Scrubber.clean` leaves them unchanged (run on `47ee8fc`). D4's never-list excludes
`tests/fixtures/**` and `evals/**` fixtures only (L567–570); `tests/test_recall_*.py` and
`tests/test_belongings_text.py` hold an employer-like name and the city as test data, and a card may
cite a test file. Summary item 3: "never anything of yours" (L42–43).

**Why it matters.** The repository is public, so nothing new is published; but these words would go
to a brain that may learn from them, which is what the owner was promised would not happen.

**Change.** D4: no file under `tests/**` or `evals/**` in any pack (cite them by path only); the
Workshop adds hashed words for the owner's locality, workplace and employer to `redact.json` (hashes
only); the needles suite plants each (and the H6 handle path) with a positive control. Summary
item 3: "only JARVIS's public code, with your name, handle and places removed".

### M9 · D2's route scan misses routes

**Evidence.** D2 scans "`@router.<verb>` and `add_api_route` in `src/jarvis/api/*.py`" (L525). On
`47ee8fc`, 21 route decorators use other router names (`session_router`, `public`, `console`,
`auth_router`, `internal_router`, `internal`, `hook_router`, `challenge_router`), 23 routes live
outside `api/` (`vitals/api.py`, `photos/api.py`, `people/routes.py`,
`wardrobe/catalog/routes_files.py`), and 46 routers carry an `APIRouter(prefix=…)` that the path
must include.

**Change.** The scan finds every module-level `APIRouter(...)` in `src/jarvis/**`, every decorator on
it, and its prefix; a test (not the generator) compares the list with the routes of the app built
with mock settings, with a control (one router name dropped: the test fails).

## LOW

- **L1 · Two lines will say "about about".** `t01b03` "about {{loc.python_code}} lines" with the
  value "about 124 thousand" (L306, L453); `t13b03` "about {{seeme.inr_a_picture}} each" with "about
  ₹9" (L408, L469). Drop "about" from the values or the lines; the facts test checks no doubled word.
- **L2 · Two fact sources are not literals as written.** `tryon.measures` is
  `MEASURES = get_args(Measure)` (`wardrobe/tryon/model.py:32`): read the `Measure` Literal at `:31`.
  `seeme.inr_a_picture` is "TRYON_PRICES typical", but the table has three entries (₹8.83, ₹8.83 and
  ₹7.55 a picture with 18 % GST, `llm/tryon.py:75–80`): name the configured model and location.
- **L3 · The "no model id, vendor name or price literal under `buildbook/`" test fails on today's
  code** (`buildbook/hear.py:47–52`, `plain.py:57–73`, `gen/scrub.py:58–65`, `:93`). Scope it to
  `buildbook/writer/**`, `tour_serve.py`, `gen/tour.py`, `api/book_writer.py`, `api/book_pages.py`.
- **L4 · Rounding differs between places.** The trial is "about ₹40" (L40, L605) but ₹37 in the cost
  table (L814); D11's sample notice says "152 pages, about ₹1,030" (L705) against ₹1,122 mid. Use one
  rule ("about" the mid rounded to ₹10) everywhere.
- **L5 · Line cites.** Sonnet's price is `llm/pricing.py:30`, not `:28` (L809); `C_MODULES` is
  `test_book_boundaries.py:19–37` and `LANE_FORBIDDEN` `:38–51` (L237–238).
- **L6 · Estimate inputs.** A redraft sends the pack, the failed draft and its failures (≈ +3k
  tokens in), counted as a plain call; the 5-minute prompt-cache lifetime against 5-minute ticks
  makes the ≈ ₹100 caching saving unlikely (it is not counted, say so); a changed card also changes
  its module page and any screen or service page citing the same files, so changed pages run above
  the changed-card counts (re-measured here: 9 / 32 / 29 cards for R6.2 / R13 / R13.1 by exact
  files, 11 / 37 / 32 with directory references expanded). The 25 / 40 / 60 pages stand; say what
  they include.
- **L7 · The never-list's `.env*`** does not match `deploy/home/bridge.env.example` (in the zip):
  use name patterns `.env*`, `*.env` and `*.env.*`.
- **L8 · `allow_training_brain`** (`buildbook/owner.py:89`) is the talk-through's switch. Say in D6/D7
  and in Book settings that the writer's Gemini pick is a separate consent, so turning that switch
  off does not read as "no Gemini for the Book".
- **L9 · Units.** `book_max_total_mb` is MiB (`sealer.py:86` `limit_mb * MIB`); the plan's release
  sizes are decimal MB (10.0 MB = 9.54 MiB). Say MiB for the cap and the 80 % line (48 MiB).
- **L10 · `Written` cannot tell a page cut by `max_tokens`.** The provider's stream yields text only
  (`anthropic_provider.py:335–368`); add `complete: bool` (from `StreamUsage.final`) and the stop
  reason where the provider gives it, and refuse an incomplete page before the checks.
- **L11 · Primary owner only.** Say that the writer's job and routes serve
  `identity.primary_user_id` like `BookSealJob` (`sealer.py:259–275`); another owner e-mail gets 403
  `not_primary`.
- **L12 · The contract suite's control depends on B** ("the job's 'no run, no call' guard removed",
  L988), which I0 does not have. Give I0 its own control (the stub job calling the fake brain once:
  the contract case fails).

## What holds (checked against the code, the build and the web)

| Claim (plan) | Result |
|---|---|
| The generator on a clean `47ee8fc`: `book.json` 198,076 B, `source.zip` 9,807,662 B, 97 files left out, 2,670 files, 27.3 MB raw (fact 2) | Right, rebuilt here (`python -m jarvis.buildbook.gen --out <tmp> --best-effort`); on `ad65e99` the two plan files add 5,474 B to `book.json` and 71,676 B to the zip |
| The zip holds `.claude/**` 46, `tests/fixtures/**` 106, `docs/` 135, `android/` 82, `evals/` 156 (fact 17) | Right |
| Version and label pins: the six exact, the prefix, the three `v13.1.0`, the label pins, `test_book_gen_plans.py:212`, `:218` (fact 1) | Right, line for line |
| Sizes: `config.py` 789 (≤ 790 at `test_r131_seams.py:110`, `:905`), `app.py` 732, `gateway.py` 760, `brain.py` 713, `api/console.py` 469, `buildbook/model.py` 412, `service.py` 397, `r6_wiring.py` 263, `console.html` 782 and its hash pins, `console-book-show.js` 390, `console-book.js` 384, `book.html` 117, the Book JS ≤ 400 / CSS ≤ 300 rule (facts 4, 12, 13, 15) | Right |
| `KEEP = 3`, the 15 MiB and 2 MiB caps, `MAX_LIMITATIONS = 80`, `FileKind`, two files a release, `KINDS`, `checked_files`, `BookCrypto` (facts 4, 16) | Right (`model.py:65–70`, `:83`, `:277`; `seal_index.py:43–44`, `:59–108`, `:147`) |
| The clocks: `JOB_BUDGET_S = 45`, `MAX_BUDGET_S = 60`, `TICK_TOTAL_BUDGET_S = 150`, `0,30 4-11` with 180 s, `*/5` with 60 s, `WATCHDOG_BUDGET_S = 50`, `ADVISORY_JOBS`, `R6_JOB_NAMES` and its pins (fact 5) | Right; but see M3 for the clock that runs with Home off |
| Cloud Run 1 CPU / 512 MiB / 300 s / 0–1 instances; `JARVIS_LLM_TIMEOUT_S=20` handed to the Claude client; the optional brain secrets; `asia-south1` (fact 6) | Right (`cloudrun.sh:48`, `:158`, `:162`, `:600`, `:614`, `:620–624`; `llm/factory.py:13–21`) |
| The router: `_DEGRADE_TO`, `allow_degrade`, the laptop still asked on an unreachable cloud, an open breaker or no credit; `stream` hands over before its first text (fact 7) | Right (`llm/router.py:73–77`, `:192–264`, `:272–336`): a write seam that streams from `router.provider` with `resolve(tier)` does avoid both |
| The brain registry, Gemini "(free)" with `trains_on_content`, the tier models (fact 8) | Right (`llm/brains.py:28–158`, `config.py:133–144`); see M2 for the other two brains |
| Prices and rate (fact 9) | Right (`llm/pricing.py:28–39`; `billing/fx.py:33–34`; `gen/costs.py:28`); Anthropic's page lists Sonnet 5.5 at $2 / $10 |
| Every ₹ figure in "Cost (₹)" and D8 | Recomputed: trial ₹25.2 / ₹36.9 / ₹51.4; first write ₹765.8 / ₹1,121.9 / ₹1,561.9; a release ₹126 / ₹295 / ₹617; a hotfix ₹5 / ₹15 / ₹31; Opus ×2, Haiku ÷20; the hold $0.094 = ₹8.95; the trial cap lets 6 holds through and refuses the 7th; ≈ 6 and ≈ 11 pages short at high; GST ₹1,324; caching ≈ ₹0.54 a call; voice 93.75 tours free, ≈ ₹27.4 a tour |
| Money: `LABELS`, `ensure_allowed`, `record(uid, brain_id, usd)`, `ensure_spend_allowed`, R13.1's cap with holds and its typed YES, `CostNotConfirmed` (fact 10) | Right (`billing/service.py:59`, `:222`, `:333`; `billing/spend.py:43`; `wardrobe/seeme/cap.py`; `consent.py:96`; `owner.py:80`) |
| The tour facts on `47ee8fc` (the table under the script) | Right: 30, 26, 5, 12, 20, 10, 180, 360 s → 6, 2 and 5, 5, "112", 6 measures, ₹300, 67 pins, 95.24, 179 settings; the seven highlights map to seven of the 18 modules, so 11 "else" |
| The script's size: owner 54 lines ≈ 1,762 words ≈ 796 s; guest 53 lines ≈ 1,700 words ≈ 768 s; every line ≤ 400 characters, ASCII, no typed digit outside a placeholder, quotes or "3D" | Recounted from L300–438 with the facts filled: 54 / 1,761 / ≈ 794 s and 53 / 1,698 / ≈ 766 s (the dates filled differently); no line over 400; no stray digit; ASCII |
| The running example still holds (fact 19); the show player's scene split and limits (fact 12) | Right (`tools/google_calendar.py:557`, `:610`; `tools/taint.py:82`; `tools/calendar_undo.py:244`; `activity/words.py:74`; `offline/rules.py:133`; `test_book_static.py:30–33`, `:55–58`; `console-book-show.js:67–99`) |
| 22 console panels; the Book panel `#p-book`; the reader and Book scripts at `console.html:775–776` | Right |
| Anthropic's rate limits for Sonnet 5.5 (2,000,000 input tokens a minute at the first tier) leave room for two calls at once | Right (A2): concurrency is not the constraint; time is (H7) |

## What this review could not check

A real writer call (no key, no YES): Sonnet 5.5's and Gemini's speed on a 3,000-token page, which H7
turns on; the real tokens of a pack against characters ÷ 4 (M1); Gemini's free quota for
`gemini-3.8-flash`; whether the home watchdog is on in his deployment and how much of its 50 s the
other jobs use; whether Anthropic's invoice to this account adds GST; whether a traffic rollback is
ever used on this service (M4); the owner's lost prompt and the workbook's own acceptance checks for
rows 379 and 380.

## Sources

| # | Source |
|---|---|
| S1 | The plan `docs/plans/r6-3-book-content.md` v6.3.1 and Phase A `docs/plans/r6-2-book-rebuild/PHASE-A-FINDINGS.md` v6.2.1, on `r6-3-plan` @ `ad65e99` |
| S2 | The code at `main` @ `47ee8fc`, every file:line above; the generator run, the AST counts (module constants, route decorators) and the guide's reference count made here with scratch scripts outside the repository |
| S3 | The architecture guide `docs/architecture/JARVIS-Architecture.md` v13.1.5 (cards C01–C73, §5.2) and `scripts/arch_coverage.py` (run: "OK – 66 … 31 outside services, 120 Firestore collections") |
| A1 | Anthropic pricing (Sonnet 5.5 $2 / $10 per million tokens) — https://platform.claude.com/docs/en/about-claude/pricing (as the plan's A1; matches `llm/pricing.py`) |
| A2 | Anthropic rate limits (Start tier: Sonnet 5.5 4,000 requests, 2,000,000 input and 400,000 output tokens a minute; cache reads not counted; not every 429 carries `retry-after`) — https://platform.claude.com/docs/en/api/rate-limits (read 23 Nov 2026) |

## Change log

| Version | Date | Release | What changed | By |
|---|---|---|---|---|
| v6.3.1 | 23 Nov 2026, 14:49 IST | R6.3 | First findings: verdict APPROVE WITH CHANGES, counts, H1–H7 | 🛠 Mark XXIV (plan review 1) |
| v6.3.1 | 23 Nov 2026, 14:51 IST | R6.3 | Complete: MEDIUM M1–M9 (holds and the 80 % gate, unpriced brains, the Home-off clock and the time sum, the index's forward compatibility, runs across a deploy, the tour's picture data, the services source, what the free brain may still read, the route scan); LOW L1–L12; what holds (the generator rebuilt with identical sizes, every pin and size guard, every ₹ figure recomputed, the tour recounted); what could not be checked; sources | 🛠 Mark XXIV (plan review 1) |
