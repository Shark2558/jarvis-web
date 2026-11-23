Version v6.3.1 · 23 Nov 2026, 17:24 IST · Release R6.3 · Status: Current · Owner: 🛠 Mark XXIV

# R6.3 — the common builder brief (Parts A–D)

Read this, then your part's own brief (`BRIEF-A.md` … `BRIEF-D.md`, in this folder), then the plan
`docs/plans/r6-3-book-content.md` (v6.3.3, Status Ready: the summary, the rows and their named tests,
D0–D14, the data model, the HTTP contract, your part in "Part split", the suites and their controls,
the size guards), `I0-NOTES.md` (what I0 built, the decisions it took, what the plan got wrong and
the fix), `PLAN-REVIEW-1.md` (why the plan says what it says), Phase A
(`docs/plans/r6-2-book-rebuild/PHASE-A-FINDINGS.md`), then `CLAUDE.md`, `.claude/rules/ecc/common/*.md`,
`.claude/rules/ecc/python/*.md` and `.claude/agents/tdd-guide.md`. You build ONE part, in parallel
with the others, on your own branch from `r6-3-i0`. Everything you may touch is in your part's
brief; everything else is someone else's. When in doubt, don't edit: write it in your
`INTEGRATION-<PART>.md` under "Needs I1".

**The owner's answers** (23 Nov 2026, ≈ 15:05 IST, in the plan v6.3.3 "Needs the owner"):
the split YES (R6.3 now, R6.3.1 next); **the Writer trial's hard cap is ₹100**, not the plan's ₹60
(`writer.model.Caps.trial`: at ₹11.84 a worst-case hold, 8 calls fit and the 9th is refused before
it is sent); release updates ask him each release (Update with his typed YES; "update by itself"
off); his private words blocked (`gen/redact.json`, hashes only: M8). Every other question keeps its
default. **Approval stop 2 passed** (his YES on the tour's script, 23 Nov 2026, 14:53 IST): part D
starts with A, B and C, and **the tour's spoken words are fixed: no builder changes them.**

**Agents:** every part, review and fix on Opus.

## 1. The loop

plan → test first → implement → review (fresh context) → verify → remember → improve.

1. **Plan** your part in your INTEGRATION file's first section before code (what you build, in
   which order, which tests prove it).
2. **Test first** (skill `tdd-workflow`, `.claude/agents/tdd-guide.md`): write the failing test,
   RUN it and see it fail for the reason you expect, write the least code that passes, refactor.
   Each named test of your rows (the plan's first table) is written before its code. 80 %
   coverage for your package at least.
3. **Review** in a fresh context: `code-reviewer` and `python-reviewer` (Python parts), and
   `security-reviewer` where your brief says (B: required; C: the YES and ₹ dialogs). Fix CRITICAL
   and HIGH.
4. **Verify**: the commands of section 6, every one green, numbers written down.
5. **Remember**: your INTEGRATION file says what you built, the checks with their numbers, every
   deviation and why, "Needs I1" with exact diffs, and honestly what you could not verify.

## 2. Your branch, your commits

- Worktrees and branches `r6-3-a` (A · the fact pack and the generator), `r6-3-b` (B · the writer),
  `r6-3-c` (C · the owner's console), `r6-3-d` (D · the short tour), each from `origin/r6-3-i0`, e.g.
  `git worktree add .claude/worktrees/r6-3-a -b r6-3-a origin/r6-3-i0`.
- **Push after every commit**: `git -c push.negotiate=true push -u origin r6-3-a` the first time,
  then `git -c push.negotiate=true push`. Server restarts happen every few hours and stop agents:
  pushed work survives; after a restart check `git status` and commit any good work first. Never
  rebase, never force-push, never push to `main`, never `rm -rf` outside `/tmp` or
  `.claude/worktrees/`, **never `git stash`**, never edit lint, format, type-check or
  coverage-floor files to make an error go away. Never touch another part's branch or worktree.
- **The hook.** `.claude/settings.json` runs `.claude/hooks/guard.py` before every Bash, Edit,
  Write and MultiEdit call (GateGuard). **A blocked action means stop and report it in your
  INTEGRATION file and to the Workshop; never work around it.**
- Conventional commit messages in the repository's style (`feat(r6.3): …`, `fix(r6.3): …`,
  `test(r6.3): …`; a body that says what and why), each ending with exactly these four trailers:

  ```
  Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
  Claude-Session: <the session link the Workshop gives you>
  JARVIS-Version: v6.3.0
  JARVIS-Mark: XXIV
  ```
- The repository is PUBLIC: no personal data (names, e-mail addresses, phone numbers, addresses,
  places, his employer or work), no keys, no project ids, no chat links (the trailer is the only
  one), no local paths, in code, tests, fixtures or docs. **The owner's private words** (M8) live
  only in a file outside the repository and as hashes in `gen/redact.json`: never write, print,
  log or commit one; a test that needs one uses a made-up stand-in (`Zorblaxton`, `Quimbledorf
  Works`). Fixtures use the made-up demo (`tests/r63_fakes.py`) and `example.com`.

## 3. The rule: self-contained modules, never a wiring or shared file

I0 built every join. Each part replaces I0's stubs with its own modules and delivers
`docs/plans/r6-3-integration/INTEGRATION-<X>.md`. You never edit (I0's, or untouched by R6.3):

- `src/jarvis/api/app.py` (732), `tools/gateway.py` (760), `core/brain.py` (713), `config.py`
  (789: no new setting; a tunable is a module constant of your part), `console.html` (782,
  byte-identical, pinned by its SHA-256), `api/console.py` (473: the allow-list), `api/r6_wiring.py`,
  `api/book_writer_wiring.py`, `api/tick_wiring.py`, `home/watchdog.py`, `billing/service.py`
- **R6's sealing and Privacy files, untouched by R6.3 (M4, D11; pinned by 47ee8fc's SHA-256 in
  `tests/test_r63_seams.py` and the eval's `contract`):** `buildbook/seal_index.py`, `seal.py`,
  `ports.py`, `sealer.py`, `seal_notices.py`, `seal_words.py`, `privacy.py`, `api/book.py`; and
  `buildbook/model.py`, `service.py`, `show_script.py`, `release.py`, `keyring.py`
- the contract: `buildbook/writer/{model,http,ports}.py`, `buildbook/facts_model.py`,
  `buildbook/tour_model.py`, `llm/write.py` (and `llm/base.py`, `anthropic_provider.py`,
  `gemini_provider.py`), `buildbook/gen/{modules,refs,services,write,runner,fallback}.py`,
  `buildbook/gen/redact.json`, `scripts/redact_add.py`, `scripts/arch_*.py`
- the console frames: `console-book.js` (the loader), `console-book-show.js`,
  `console-book-script.js` (the show's script reader), `book.html`
- `tests/test_r63_seams.py`, `test_r63_write.py`, `test_r63_types.py`, `test_r63_modules.py`,
  `test_r63_gen_joins.py`, `test_r63_wiring.py`, `test_r63_serve.py`, `test_r63_console_seams.py`,
  `test_r63_static.py`, `test_r63_fakes.py`, `test_r63_fake_server.py`, `test_r63_refs_services.py`,
  `test_r63_redact.py`, `tests/r63_fakes.py`, `r63_fake_brains.py`, `r63_fake_server.py`,
  `tests/fixtures/r6_3/*`, `evals/r6_3/run.py`, `evals/r6_3/contract.py`, `evals/run_all_mock.py`,
  every earlier release's seam test, `docs/architecture/*`, `scripts/arch_coverage.json`,
  `deploy/*`, `.claude/**`, `pyproject.toml`, `.github/workflows/*`, `CLAUDE.md`

The two exceptions: **A** turns `tests/test_r63_scrub_kinds.py` green and removes its `xfail`
marks (nothing else in it); **each part** replaces its own `evals/r6_3/<part>.py` stub. If you need
a change elsewhere, stop and write it under "Needs I1" with the exact diff (the others build
against the contract). A pin in an earlier release's test that your part legitimately moves is
named in your INTEGRATION file with the reason.

## 4. The seams you use (what I0 built; details in I0-NOTES.md)

- **The write call** (`jarvis.llm.write`, D1): `write_text(router, *, tier, system,
  system_dynamic, messages, max_tokens, timeout_s, clock=None) -> Written(text, model, provider,
  tier, usage, cost_usd, seconds, complete, stop_reason)`; `BrainOff` under No-AI;
  `WriterUnavailable(why)` (`cloud_down`, `busy`, `refused`, `no_credit`, `declined`,
  `no_answer`) when nothing arrived (release the hold); a cut stream or our own timeout is a
  `Written` with `complete=False` (settle at its usage, D8); a length stop is not complete; never
  the laptop, never another tier, no retry inside a call (`AnthropicProvider.no_retry()`).
  `estimate_usd(spec, tier, in, out, system_tokens=)`, `worst_usd(spec, tier, in_cap, out_cap,
  system_cap=)` (the hold: `worst_usd(spec, BALANCED, 38_400, 4_000, system_cap=3_000)` = US$0.1243,
  ₹11.84 at ₹95.24), `offered(spec)` (M2), `paid(spec)`, `model_of(spec)`, `maker(spec)`
  ("Anthropic", "Google": the writer's words name no vendor themselves).
- **The writer's data model** (`buildbook/writer/model.py`): collections (`WRITER`, `LEASE`,
  `SPEND`, `DRAFTS`, `TRIAL`, `PAGES_INDEX`, `PAGES_CHUNKS`), `aad_pages_index(uid)` =
  `book/pages/{uid}/v1` under purpose `book_index` (no new keyring purpose), ids (`wc_` 16 hex a
  call, `we_` 12 hex an estimate, **`wt_` 12 hex the terms a YES grants**), the job's budgets
  (`JOB_BUDGET_S` 45, `STEP_BUDGET_S` 150, `STEP_CALL_TIMEOUT_S` 120), `MAX_TOKENS` 4,000,
  `PACK_CAP_BYTES` 96,000, `SYSTEM_TOKENS` 3,000, `TRIAL_PAGES` (the five), `YES`/`is_yes`,
  `about_inr` (L4), `GST_NOTE` (`{maker}`), the page and its six sections (`SECTION_IDS`,
  `DRAFT_SECTIONS` = the five a brain writes, `HEADINGS`, `SECTION_CAPS`, `FACT_PLACEHOLDER`,
  `EXAMPLE_MARK`), `PageMeta` (tier always `balanced`), `Caps` (defaults ₹100 / 1,500 / 500 /
  1,000 / 80 %, `CAP_BOUNDS`), `Confirmed` (all zero at first, H2), `Pick`, `Consent`, `Run`,
  `UpdateReady`, `WriterDoc`, `Lease`, `Hold`, `SpendDoc`, `Draft`, `TrialPage`, `PagesFile`,
  `PagesEntry`, `PagesPart`, `PagesIndex`. **The draft wire format:** five `## <heading>` blocks
  in `DRAFT_SECTIONS` order (`tests/r63_fake_brains.draft`); numbers outside the example as
  `{{fact:<key>}}`.
- **The HTTP contract** (`buildbook/writer/http.py`): the 13 routes (`ROUTES`: method, path, part,
  request, reply, statuses, gate `console` or `session`), the request and reply models, `Refusal`,
  `YesNeeded`, the codes (`ERRORS`), `LIMITS`, `NOT_BUILT`. I0's stubs (`api/book_writer.py`,
  `api/book_pages.py`) answer every row 503 `not_built_yet` after `require_auth` (and
  `console_only` for console rows).
- **The writer's join** (`buildbook/writer/ports.py`): `WriterContext` (docs, keyring, brains,
  billing, R6's source, R6's sealed index read-only, notifier, audit, prefix, `limit_mb`, the
  primary owner's `uid`, owner e-mails, honorific, timezone, the Book clock) and `WriterPart
  (service, job, privacy, ready)`; B's ONE join `buildbook/writer/part.build(ctx)` (I0's stub: a
  `NotBuilt` service, a do-nothing `BookWriteJob`, a zero Privacy row). The wiring
  (`api/book_writer_wiring.py`) puts `service` on `app.state.book_writer`, `book_write` on the
  morning tick after `book_sweep` and LAST on the 5-minute clock (Home on or off), never on the
  home watchdog's R6 loop; it is advisory (`ADVISORY_JOBS`). A broken part is `setup_failed` and
  the rest of the Book runs on. Vitals labels the writer's spend `LABELS["book"]` "Book writer"
  (`billing.record(uid, "book", usd)`).
- **The fact pack** (`buildbook/facts_model.py`, D2, D3): `FactPack` (`release`, `values`
  {key → `FactValue(value, source, verified)`}, `index` {paths, symbols, constants, settings,
  collections, routes}, `routes`, `settings`, `collections`, `modules`, `cards`, `screens`,
  `services`, `loc`, `limitations`, `pages`), `IndexedPage`, `PARTS`, `CHAPTERS`, `PAGE_ID`,
  `FACT_KEY`, `FACT_TOUR_KEYS` (the 30 keys A computes), `TOUR_TIMER_KEYS` (`tour.minutes`, D's),
  `canonical_facts`, `load_facts` (1 MiB). Keys: dotted (`cards.count`), constants as
  `path:NAME` (scrubbed path), settings as `settings.<name>`.
- **The generator's joins** (`gen/write.py`): `facts.build(repo, scrub) -> FactPack` (A),
  `pages_index.build(repo, facts) -> tuple[IndexedPage, ...]` (A), `tour.build(repo, facts) ->
  Tour | None` (D); the join sets the pack's `release` and `pages`, re-validates, scrubs
  (`Scrubber.verify`) and caps it; `_book/facts.json` is written before `release.json`
  (`facts_sha256`); `--check` compares it; `ReleaseSource.facts()` reads it verified.
- **The module map** (`gen/modules.py`): `MODULES` (18; Wardrobe & Try-on last), `check(cards,
  table=)`, `module_of`, `others()` (the 11 not in his highlights), `TOUR_HIGHLIGHTS`,
  `guide_cards(text)`. **One resolver** (`gen/refs.resolve(repo, where) -> [(span, path | None)]`,
  the guide check's own rule) and **one services list** (`gen/services.inventory(repo, table=None)`:
  the coverage checker's 31).
- **The tour's shapes** (`buildbook/tour_model.py`): `TourScript` (`gen/tour.json`, I0: empty),
  `ScriptScene`, `ScriptPicture` (`visual`, `FromShow` or a `TourFact` list), `Tour` {`owner`,
  `guest`: `AudienceTour` (scenes, seconds, words, chars, lines)}, `TOUR_SCENES` (the approved
  scenes: number, id, title, picture, audience), `HIGHLIGHTS`, `OWN_PICTURE_DATA` {12, 13, 14},
  `seconds(words, lines, scenes)` (the timer), `HARD_BAND_S`, `AIMED_S`. `Book.tour: Tour | None`
  (left out of the bytes when None: 47ee8fc's real book round-trips).
- **The show's joins** (`buildbook/show_script.py`, `tour_serve.py`): `tour_serve.tour_lines(book,
  audience, words)` (None → `kind: "show"`) and `tour_line_text(book, line_id, audience)` (an
  owner-only line in a guest session → None → 404 `unknown_line`); a guest's tour script carries
  no `costs`. In the page, `console-book-script.js` (`window.JarvisBookScript`) reads both kinds:
  a tour scene's picture is today's `visual` with its own facts, Questions 12, Closing 13; the
  show asks `window.JarvisBookTour` (D's) for `label`, `seen` and `start`.
- **The console's loader** (`console-book.js`): C's `console-book-writer.js` and
  `console-book-pages.js` load ONCE at the Book panel's first open; `JarvisBookWriter.settings(host,
  deps)` (under Book settings; `deps.top` is a box at the top of the panel for the 80 % storage
  line) and `JarvisBookPages.mount(host, deps)` (under the owner's reader); `deps = {api, booked,
  ask, say, render, token(), release()}`.
- **The fakes**: `tests/r63_fakes.py` (`NOW` = 24 Nov 2026 10:00 IST, `ist`, `FixedClock`, `UID`,
  `RING`, the three-card fixture repo and `FIXTURE_FACTS`, `source_zip`, `FakeBilling`,
  `FakeSource`, `writer_context(...)`), `tests/r63_fake_brains.py` (`ScriptedWriter` steps,
  `claude_like`, `gemini_like`, `paid_gemini`, `custom_brain`, `registry(..., laptop=)`,
  `RecordingLaptop`, `busy`, `down`, `cut`, `length_stop`, `slow`, and the drafts `GOOD_DRAFT`,
  `FAKE_PATH_DRAFT`, `TYPED_NUMBER_DRAFT`, `EMAIL_DRAFT`, `INVENTED_DRAFT`,
  `PLANNED_OUTSIDE_DRAFT`, `UNVERIFIED_DRAFT`), `tests/r63_fake_server.py` (the 13 routes from an
  in-memory state for C; `fake_app`, `serve(token)`), `tests/fixtures/r6_3/book-47ee8fc.json.gz`.
- **The eval runner** `evals/r6_3/run.py` is STAGED (`STUBS_PASS = True` until I1): your part's
  file exposes `PART`, `BUILT`, `async def cases()` and `async def control()`; set `BUILT = True`
  only once its control really fails it. Every row's own control (the plan's "A control for every
  row's own case") is a case of your control run.

## 5. House rules for every part

- **₹ only in owner-facing words** (no `$`, no dollar figure ever leaves the server; the static
  test `test_rupees_only` covers every Book JS). **No real model call** anywhere: not in a test, an
  eval, a fixture or a script (the scripted brains only). No real Google or Anthropic call.
- **Every grant of spending is his typed YES on the ₹ shown** (H2): the first pick, a cap raised,
  a paid or training brain, "update by itself", the trial, the first write, Update. Exactly `YES`
  once trimmed. Nothing spends by itself after a deploy.
- **Private by default.** Ids, counts and ₹ only in logs, the audit, notices and Activity; never page
  text, a pack, a prompt, a reply, a draft or the creator name (the Book's log scan:
  `test_book_boundaries.py` `CONTENT_NAMES` now holds `page`, `pack`, `prompt`, `draft`, `pages`:
  name an id variable `page_id`, a count `count`). Packs from the release's public files only,
  scrubbed, never `.claude/**`, `tests/**`, `evals/**`, `*.env*` or the redact list.
- **Outside content is untrusted data** (code and plans in a pack are fenced; a brain's reply is
  checked before anything is kept).
- **The look does not change**: only existing classes (`.bset`, `.dsc`, `.dbody`, `.bsec`,
  `.blines`, `.bchips`, `.btn`, `.bdialog`, `.minput`, `.snote`, `.tag`); no new CSS file unless C
  asks I1 for one (D0); the Book panel's and the show's screenshots with the writer off unchanged.
- **Clocks: no date bombs.** Every test takes a FIXED clock (`r63_fakes.NOW`, `FixedClock`); no
  real clock under `buildbook/writer/` or in `llm/write.py` (`test_r63_static.py`); his IST month
  is tested at 23:30 and 00:30 IST, 1 Jan 2027 and 29 Feb 2028.
- **Imports: CI runs plain `pytest` from the repository root, which is NOT on `sys.path`:** never
  `from tests.x import …`; import fakes bare (`from r63_fakes import …`); every fake file of yours
  has a UNIQUE name (`tests/r63_fakes_<a|b|c|d>.py`), so the four branches merge without a clash.
  Plain `python` needs `PYTHONPATH=$PWD/src`. Browser tests carry `pytestmark =
  pytest.mark.browser` and run only with `JARVIS_BROWSER_TESTS=1`.
- Functions ≤ 50 lines, Python modules ≤ 400, Book JS ≤ 400 and CSS ≤ 300 (your brief's own
  limits are lower); `ruff check` and `ruff format --check` clean; `mypy src` adds no error.

## 6. Test commands (2 CPUs, about 7 GB; other agents share the machine)

Run your part's tests and the seam tests; NEVER the whole suite (I1 runs it). Anything heavier than
a few files goes behind the shared lock, in the foreground, with a generous timeout:

```
PYTHONPATH=$PWD/src /tmp/venv-b/bin/python -m pytest -q -p no:cacheprovider tests/test_r63_<x>_*.py
flock /tmp/jarvis-heavy.lock env PYTHONPATH=$PWD/src /tmp/venv-b/bin/python -m pytest -q \
    -p no:cacheprovider tests/test_r63_*.py tests/test_book_*.py
/tmp/venv-12/bin/ruff check <your files> && /tmp/venv-12/bin/ruff format --check <your files>
flock /tmp/jarvis-heavy.lock /tmp/venv-12/bin/mypy src       # the one baseline error only
PYTHONPATH=$PWD/src /tmp/venv-b/bin/python evals/r6_3/run.py --mock --part <yours>  # control fails
PYTHONPATH=$PWD/src /tmp/venv-b/bin/python -m jarvis.buildbook.gen --check   # A and D: every module
python3 scripts/arch_coverage.py && python3 scripts/check_doc_versions.py
JARVIS_BROWSER_TESTS=1 flock /tmp/jarvis-heavy.lock /tmp/venv-c/bin/python -m pytest -q -m browser tests/browser/test_r63_<x>_*.py
```

`/tmp/venv-b` is Python 3.11, `/tmp/venv-12` 3.12, `/tmp/venv-c` 3.13 with Playwright and Chromium
(use `python -m pytest`). Node 22 is on the PATH. Browser tests one file at a time, behind the lock.
In a worktree run tests with `PYTHONPATH=$PWD/src` (the venvs' editable install points at the main
checkout).

## 7. Size guards (pinned by `tests/test_r63_seams.py` and `test_r63_console_seams.py`)

`api/app.py` 732, `tools/gateway.py` 760, `core/brain.py` 713, `config.py` 789 (none edited);
`console.html` 782, byte-identical; `api/console.py` ≤ 473; `api/r6_wiring.py` ≤ 300;
`buildbook/model.py` ≤ 420, `service.py` ≤ 400, `tour_model.py` ≤ 200, `llm/write.py` ≤ 160; every
module under `buildbook/writer/` and `facts_model.py` ≤ 400; `console-book.js` ≤ 390,
`console-book-show.js` ≤ 370, `console-book-script.js` ≤ 200, `console-book-tour.js` ≤ 300,
`console-book-writer.js` ≤ 400, `console-book-pages.js` ≤ 400, `console-book-reader.js` ≤ 270,
`book.html` ≤ 130; `facts.json` ≤ 1 MiB; a pages file ≤ 2 MiB gzipped; the keyring 26.

## 8. Done means

Your deliverables work on fakes end to end and each named test of your rows passes; your eval part
is BUILT with its controls failing it (every row's own control too); everything works, or says
plainly why not, with the AI off and with nothing set up; the commands above are green; your
`docs/plans/r6-3-integration/INTEGRATION-<A|B|C|D>.md` (versioned like this file, with its change
log) is written and pushed: what you built, the checks with their numbers, every deviation from the
plan with its reason, "Needs I1" with exact diffs, and honestly what you could not verify here.

## Change log

| Version | Date | Release | What changed | By |
|---|---|---|---|---|
| v6.3.1 | 23 Nov 2026, 17:24 IST | R6.3 | First edition, written at I0: the owner's answers of 23 Nov (split, ₹100 trial cap, updates ask, private words) and approval stop 2 (D starts, words fixed); the loop, branches, the hook and the four trailers, the files no part edits (R6's sealing files pinned), the seams (the write call, the writer's model and HTTP contract, its join, the fact pack, the generator's joins, the module map, one resolver and one services list, the tour's shapes, the show's joins, the console's loader, the fakes, the staged runner), the house rules, the commands behind the lock, the size guards, done | 🛠 Mark XXIV |
