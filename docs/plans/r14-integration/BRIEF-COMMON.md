Version v14.0.1 · 14 Nov 2026, 15:45 IST · Release R14 · Status: Current · Owner: 🛠 Mark XVIII

# R14 — the common builder brief (Parts A–D)

Read this, then the plan `docs/plans/r14-hardening.md` (v14.0.2, Status Ready: the decisions D0–D18,
your part's row in "Part split", its tests and evals), `docs/plans/r14-integration/I0-NOTES.md` (what
I0 built and what only CI or the owner's step can prove), `PLAN-REVIEW-1.md` (why the plan says what
it says), then `CLAUDE.md` and `.claude/rules/ecc/common/*.md`. You build ONE part, in parallel with
the others, on your own branch from `r14-i0`. Everything you may touch is in your part's row;
everything else is someone else's. When in doubt, don't edit: write it in your `INTEGRATION-<PART>.md`
for I1.

## 1. Your branch, your commits

- Worktrees and branches `r14-a` (A · backups and the drill), `r14-b` (B · self-health), `r14-c`
  (C · cost and the skill register), `r14-d` (D · No-AI pass 2, rows 101/102, the leftovers), each
  from `origin/r14-i0`, e.g. `git worktree add /home/claude/wt/r14-a -b r14-a origin/r14-i0`.
  Push after every commit: `git -c push.negotiate=true push -u origin r14-a` (the first time), then
  `git -c push.negotiate=true push`. Never rebase, never force-push, never `rm -rf` outside `/tmp`,
  `/home/claude/wt/` or `.claude/worktrees/`, never `git stash` while a background run uses the
  tree, never edit lint, format, type-check or coverage-floor files to make an error go away. Never
  touch `main` or another part's branch.
- **The hook.** `.claude/settings.json` runs `.claude/hooks/guard.py` before every Bash, Edit, Write
  and MultiEdit call (plan D18). It blocks only clearly dangerous actions (a force push or a push to
  `main`, a hard reset onto a remote ref, deleting `main`, `rm -rf` outside the places above, `.env*`
  and key files, a private key block, checks switched off in `[tool.ruff]` / `[tool.mypy]` /
  `ruff.toml` / `mypy.ini` / `setup.cfg`, a lower `scripts/coverage_floor.txt`). **A blocked action
  means stop and report it in your INTEGRATION file and to the Workshop; never work around it**
  (no other spelling of the same command, no editing the hook). Every command in this brief passes it.
- Conventional commit messages (`feat(r14): …`, `fix(r14): …`, `test(r14): …`), each ending with
  exactly these trailers:

  ```
  Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
  Claude-Session: https://claude.ai/code/session_01KbmAktj4yLvk2uM2MrtjEW
  JARVIS-Version: v14.0.0
  JARVIS-Mark: XVIII
  ```
- The repository is PUBLIC: no personal data (names, e-mail addresses, phone numbers, account
  numbers, home addresses, real mail or calendar content), no keys, no project ids, no chat links
  other than the trailer, no local paths, in code, tests, fixtures or docs. Fixtures use made-up
  people, `example.com` addresses and obviously fake numbers.

## 2. The rule: never edit a wiring file

I0 built every join. A part plugs in through **one function**, `build(ctx: HardeningContext) ->
HardeningPart` (`jarvis.hardening.ports`), in its part module (`backup/part.py` for A,
`selfwatch/part.py` for B, `skills/part.py` for C, `offline/r14_part.py` for D), and its own route
file. You never edit:

- `src/jarvis/api/app.py` (726 lines, guard ≤ 735: it may not grow past it), `api/r14_wiring.py`,
  `api/tick_wiring.py`, `api/r14_status.py`, `api/personal.py`, `api/selfcheck_wiring.py`,
  `api/home.py`, `api/brief.py`, `api/r7_wiring.py`, `api/r11_wiring.py`, `tools/setup.py`
- `src/jarvis/tools/gateway.py` (760 lines, guard 760: it may not grow by a line), `console.html`
  (782 lines, guard ≤ 782), any `console*.js` but your row's (each ≤ 800), `console-alerts.js`
  (I0 added the eleven rows), `console-vitals.js`, `console-privacy.js` (R14 adds no console
  control: Vitals items and the Privacy row are server-sent)
- `core/brain.py` (710 lines, guard 741: its two slots are I0's), `ticks.py`, `home/watchdog.py`
- the contract and ports: `hardening/ports.py`, `backup/ports.py`, `selfwatch/ports.py`,
  `skills/ids.py`, `skills/ports.py` (a contract change needs a line in your INTEGRATION file: the
  other parts build against it)
- the alert kinds and every table that names one (`alerts.py`, `notify/ports.py`,
  `notify/policy.py`, `notify/storm.py`, `notify/held.py`, `webpush/service.py`,
  `buildbook/plain.py`), the key purposes (`keyring.py`), the permission rows
  (`permissions/groups.py`), the settings (`config.py`), the layer map
  (`buildbook/gen/layers.py`): I0 added every one R14 needs (I0-NOTES section 3 says where)
- `tests/test_r14_seams.py`, `tests/test_r14_wiring.py`, `tests/r14_fakes.py`,
  `tests/test_claude_guard.py`, `tests/test_coverage_floor.py`, `evals/r14/run.py`,
  `evals/r14/contract.py`, `evals/run_all_mock.py`, `.claude/**`, `pyproject.toml`,
  `.github/workflows/*`, `scripts/coverage_floor.*`, `docs/architecture/*`, `CLAUDE.md`

If you need a change there, stop and write it under "Needs I1" in your INTEGRATION file with the
exact diff you propose.

## 3. What each part owns

Exactly the plan's "Part split" row for your letter. In short: **A** `backup/*` (not `__init__.py`,
`ports.py`), `storage/firestore_admin.py`, `storage/firestore_walk.py`, `api/backup.py`,
`deploy/backup_setup.sh` (fill the set-up; `--status` stays read only and exit 0),
`evals/r14/backup.py`; **B** `selfwatch/*` (not `__init__.py`, `ports.py`), `api/selfwatch.py`,
`notify/store.py`, the laptop-back path that sends `home_online`, `evals/r14/selfwatch.py`; **C**
`skills/*` (not `__init__.py`, `ids.py`, `ports.py`), `billing/ledger.py`, `core/window.py`,
`llm/*`, `api/skills.py`, `scripts/skill_coverage.py`, `tests/test_r14_skill_coverage.py`,
`evals/r14/offer.py`; **D** `offline/r14_part.py`, `offline/phrases_r14.py`,
`helpers/house/{upkeep,service_request,tools}.py`, `helpers/sources.py`,
`helpers/today/{models,upi}.py`, `people/cache.py` (the docstring), `api/auth.py`,
`buildbook/lock.py`, `api/notes.py`, `series/cards.py`, `api/static/console.js` (≤ 10 lines),
`deploy/cloudrun.sh`, `tests/test_r11_b_chores.py` (the STARTERS pin), `evals/r14/noai.py`. Every
part: its own `tests/test_r14_<a|b|c|d>_*.py`, `tests/r14_fakes_<a|b|c|d>.py` (unique names, so the
four branches merge without a clash) and `docs/plans/r14-integration/INTEGRATION-<A|B|C|D>.md`. You
update the EXISTING tests of the files you own and nobody else's.

## 4. The contract (`src/jarvis/hardening/ports.py`)

- `HardeningPart`: `tools` (names inside your `TOOL_FAMILIES`: A `vitals_backups`,
  `vitals_drill_start`; C `skills_open`; B and D none, D's `maint_service_request` is one of R11's
  house tools), `clock_jobs` (5 minutes, first on both paths, for the brief's owners: only B's
  `selfwatch_clock`), `daily_jobs` (the morning tick: A's `backup_canary`, `backup_drill`; B's
  `selfwatch_daily`), `privacy` (`PrivacySource`s), `vitals` (`async (uid, now, tz) -> [OwnItem]`
  made with `vitals.own.own_item`, only under your `VITALS_IDS`: A `backups`, `backup_drill`,
  `db_size`; B `clocks`; C `ai_parts`), `services`, `ready`. A part that breaks the contract is left
  out ("setup failed") and the others run.
- Services, each from its one owner (`SERVICE_OWNER`): A `backup_status` (`backup.ports.BackupStatus`:
  B and Vitals read the backups only through it, `ctx.backup_status()`); B `tick_observer` (a
  `ticks.TickObserver`: every job's outcome, `ok` / `failed` / `timed_out` / `skipped`, from the tick,
  the watchdog and the Home-off route; a skip never counts) and `log_handler` (a `logging.Handler`,
  installed once on the root logger; skip `QUIET_LOGGERS` while `selfwatch.ports.SENDING` is set);
  C `offer` (`skills.ports.ToolOffer`, the brain's tool slot, only while `tool_offer` is "by_skill")
  and `ledger` (`skills.ports.TokenLedger`, only while `token_ledger_enabled`); D `phrases` (No-AI
  routers, put in one at a time).
- The drill's locks (A): every Google call of `storage/firestore_admin.py` and
  `storage/firestore_walk.py` passes `backup.ports.drill_target(database, live=s.firestore_database)`
  first; the verifier reads both sides through `ReadOnlyDocs`; `backup/{verify,walk_checks,vault_probe}.py`
  import neither `storage.firestore_docs` nor `backup.log`; `Settings` already refuses a live
  database named `jarvis-drill`.
- The alert kinds are I0's (`R14_ALERT_KINDS`): A raises only `backup_problem` and `backup_ok`, B
  the other seven (`hardening.ports.KIND_OWNER`), through the notifier with fixed templates. The
  storm's `SELF_KINDS` table caps them (one per kind and subject per 30 minutes, 3 an hour).
- The brain's two slots (C): `Brain.slots.tools(req, messages, specs)` and
  `Brain.slots.record(LedgerCall)`. No third slot: the history's cache breakpoint is the Anthropic
  provider's own, from `cache_history` (D9).

## 5. House rules that apply to every part

- **Nothing spends money and nothing calls Google** in tests, evals or I0's code: every Google call
  is behind A's adapters and their fakes. The deploy only ever runs `backup_setup.sh --status`.
- **Free first.** No new paid service, secret or Scheduler job. Any model call is by tier through
  `jarvis.llm`, admitted first and recorded after, shown in ₹, replaced by plain code in No-AI mode.
- **Every action is a tool through the gateway.** A restore drill started by hand is an R2 card
  (`bulk_ok=False`); nothing books, pays or sends.
- **Outside content is untrusted data**; alert texts are fixed templates (no logger name, no vendor
  text, no amounts but the spike's ₹).
- **Private by default**: counts and names only in logs, the ledger and the self-health documents;
  a vault item's plaintext is only hashed in the drill's memory.
- **The look never changes**: R14 adds no console control.
- Write the failing test first (skill `tdd-workflow`), 80 % coverage for your package (CI now
  measures it: plan D17); then the reviews your row names.
- **Lessons**: CI runs plain `pytest` from the repository root, which is NOT on `sys.path`:
  never `from tests.x import` (import fakes bare, `from r14_fakes_a import …`; guard
  `tests/test_test_imports.py`). GitHub's runners have 4 CPUs and Python 3.12 there links zlib-ng
  (compare decoded content, never compressed bytes). The browser job installs only `.[dev]` and
  Playwright. The editable install points at this checkout; plain `python` needs
  `PYTHONPATH=$PWD/src`. Functions ≤ 50 lines, modules ≤ 400, files ≤ 800.

## 6. Test commands (run before every push; one heavy run at a time, the machine has 2 CPUs)

```
pytest -q -p no:cacheprovider tests/test_r14_*.py <the existing tests of your files>
pytest -q -p no:cacheprovider tests/test_r14_seams.py tests/test_r14_wiring.py tests/test_claude_guard.py \
    tests/test_arch_coverage.py tests/test_telegram_tool_guard.py
ruff check src tests evals scripts && ruff format --check src tests evals scripts
mypy src                                                 # the 9 pre-existing errors only
PYTHONPATH=$PWD/src python evals/r14/run.py --mock --part <yours>   # passes; your control fails it
PYTHONPATH=$PWD/src python scripts/arch_coverage.py && python scripts/check_doc_versions.py
```

Set `BUILT = True` in your eval part only when its control really fails it. I1 runs the whole
suite, the browser files and the build book.

## 7. Done means

Your deliverables work on fakes end to end and each has its eval case with a failing control;
everything works or says plainly why not with the AI off, before the owner's one-time step and with
nothing set up; the commands above are green; your `INTEGRATION-<PART>.md` (versioned like this file,
with a change log) is written and pushed, and lists honestly what you could not verify live.

## Change log

| Version | Date | Release | What changed | By |
|---|---|---|---|---|
| v14.0.1 | 14 Nov 2026, 15:45 IST | R14 | First edition, written at I0: branches and the hook (a blocked action means stop and report), the files no part edits, each part's files, the contract (`HardeningPart`, the services and their owners, the drill's locks, the kinds, the brain's two slots), the house rules and lessons, the test commands | 🛠 Mark XVIII |
