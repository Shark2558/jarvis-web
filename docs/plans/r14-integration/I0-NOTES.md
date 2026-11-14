Version v14.0.1 · 14 Nov 2026, 17:00 IST · Release R14 · Status: Current · Owner: 🛠 Mark XVIII

# R14 — I0 notes (the joins for "Free hardening")

Written by the R14 I0 integrator in the Workshop (🛠 Mark XVIII) while building I0 on `r14-i0`. The
plan is `docs/plans/r14-hardening.md` (v14.0.2, Status Ready, with plan review 1 written in and the
owner's two additions D17, D18); the builders' brief is `BRIEF-COMMON.md`, in this folder.

## 1. The base

- `r14-i0` was cut from `main` @ `5db4f05` (R7 live, v7.0.0) and carried the plan v14.0.1
  (`b45e43c`) and review 1 (`7a37d1b`). Nothing was rebased or force-pushed; no part builder has
  started; no pull request is open.
- Step 1 (`d0bdca4`): the plan v14.0.2, Status Ready, and the review's "Addressed in v14.0.2"
  (A1–A8, every B line, the C seams, the D notes; every ₹ figure recomputed at `billing/fx.py`'s
  ₹95.24).
- The owner's scope addition (14 Nov, 13:45 IST, "add them"): coverage measured with a ratchet
  floor (D17) and a GateGuard hook for the coding agents (D18), both built here, tests first.

## 2. Stale lines found at I0 (beyond review 1's B table)

1. Plan D15 and seam 8: cards "C61–C63". The guide's cards already run to C65 (R11.1's C61, R7's
   C62–C65): R14's are **C66–C68** (plan fact 16, D15, seam 8).
2. Seam 1 and the task: "`pyproject.toml`" carries the version. It does not: `[tool.setuptools.dynamic]`
   reads `jarvis.__version__` (R6.1 D4; pinned by `tests/test_about.py`). Only `__init__.py` moved.
3. Seam 4: "`understand/words.py` nouns". The nouns live in the test's `TOOL_NOUNS`
   (`tests/test_r11_1_b_guard.py`); "start" and "open" are already action words, so `words.py`
   needed nothing (plan corrected).
4. Seam 7: "`ticks.py` an observer hook (`observe(fn)`)". A module-wide registry would leak between
   the many apps the tests build; the observer is passed to `run_jobs` (`observer=`, `clock=`) by its
   three callers, from `app.state.tick_observer` (plan wording kept as "an observer passed to
   `run_jobs`").
5. Seam 7: "`api/selfcheck_wiring.py` the Vitals sources slot". The slot is a field of
   `vitals/own.py` `OwnSources` (`r14`, read late) that `selfcheck_wiring.py` fills; R14's ids also
   needed their fixed words in `vitals/words.py` (every automatic item has an "If this …" line and
   a fix; `test_r51b_vitals_own.py` pins it).
6. D7: "replaces the Home-off branch (`api/home.py:160–172`)". The function is `_helpers_clock_only`
   (now `_clock_only`); the three `watchdog.extend` sites were `selfcheck_wiring.py:191`,
   `r11_wiring.py:279` and `r7_wiring.py:181` (R6's book jobs stay on the watchdog only: they are
   not 5-minute advisory clocks of the plan's list).
7. Review B's own lines, every one re-read on `5db4f05`: all right as the review says (pricing
   `:30`; four error classes in three providers and the router's `str(exc)[:200]`; the two UPI
   constants; the float `expires_at`; the pins of the version, the kinds, the keyring and the tick
   list; the STARTERS pin).

## 3. What I0 built (seams 1–12)

Tests first: `tests/test_r14_seams.py`, `tests/test_r14_wiring.py`, `tests/test_claude_guard.py` and
`tests/test_coverage_floor.py` were written before the code and failed before it (no module; 40 of
the hook's cases; the missing floor and CI steps).

1. **Version** `14.0.0` (`src/jarvis/__init__.py`); the book reads "R14" with
   `docs/plans/r14-hardening.md` first. Pins moved: `test_about.py`, `test_r7_seams.py` (the version
   and "the real repository": now R14, R7's plan still listed), `test_r11_1_seams.py`,
   `test_r11_seams.py`.
2. **Alert kinds** 43 → 52 (`R14_ALERT_KINDS`): `job_failing`, `clock_stopped`, `brief_missed`,
   `errors_piling`, `spend_spike`, `deploy_changed`, `backup_problem` important daytime rings;
   `selfwatch_ok`, `backup_ok` info. In `alerts.py`, `notify/ports.py`, `notify/policy.py`,
   `notify/held.py` (+ the missing `health_fault`, `vitals_critical`), `console-alerts.js` (+11
   rows), `webpush/service.py` (all nine → `vitals`), `buildbook/plain.py`. `notify/storm.py`
   gained `SELF_KINDS` (one per kind and subject per 30 minutes, `MAX_SELF_PER_HOUR` 3, with its
   rollback), apart from `SOFT_URGENT_KINDS`, which is unchanged. Pins moved: R3, R6, R11, R11.1,
   R7 seams, R5.1's exact `DAYTIME_RING_KINDS`, R11's Alerts-card order.
3. **Keyring** `backup_probe` (22). Pins moved: R3, R11, R7 (the last three now `[-4:-1]`).
4. **Permissions**: no new row (49; the save cap 51 stays). `EXPECTED` gained `vitals_backups`,
   `vitals_drill_start`, `maint_service_request`, `skills_open` (no row); the `vitals` hint names the
   backups, `vitals_change` the drill (a card, about ₹2, at most 2 a month); a test pins the four as
   open on Telegram; `TOOL_NOUNS` and `R7_PARTS_TOOLS` gained the nouns and the planned tools.
5. **Settings** (`config.py` 656 → 719): the twenty of seam 5 with their ranges; `cloud_run_revision`
   reads Cloud Run's own `K_REVISION`; `Settings` refuses `firestore_database = "jarvis-drill"`
   (D4 lock 5).
6. **The contract and the stubs**: `jarvis.hardening.ports` (`HardeningPart`, `HardeningContext`,
   `PARTS`, `TOOL_FAMILIES`, `ROUTE_PREFIX`, `STATUS_ROUTE`, `R14_STATUS_ROUTE`, `COLLECTIONS`,
   `R14_JOB_NAMES`, `JOB_OWNER`, `SERVICE_OWNER`, `VITALS_IDS`, `VITALS_OWNER`, `VITALS_QUIET`,
   `KIND_OWNER`); `backup/ports.py` (`DRILL_DB`, `drill_target`, `ReadOnlyDocs`, `BackupInfo` with
   `stats_ready`, `BackupAdmin`, `DrillWalk`, `DatabaseInfo`, `BackupFacts`, `NOT_SET_UP`,
   `BackupStatus`); `selfwatch/ports.py` (the outcome, `SENDING`, `QUIET_LOGGERS`, `B_KINDS`);
   `skills/ids.py` (the 11 ids, labels, `SkillSummary`), `skills/ports.py` (`OfferContext`,
   `ToolOffer`, `LedgerCall`, `TokenLedger`, `BrainSlots`), `skills/offer.py` (`offer_all`);
   `billing/ledger.py` (`NoLedger`); `offline/phrases_r14.py` (empty), `offline/r14_part.py`; stub
   parts `backup/part.py`, `selfwatch/part.py`, `skills/part.py`; routes `GET /v1/r14`
   (`api/r14_status.py`), `GET /v1/backup`, `POST /v1/backup/drill` (501 `not_built`),
   `GET /v1/selfwatch`, `GET /v1/skills`, `GET /v1/costs/ledger`, all owner-only and `no-store`;
   `deploy/backup_setup.sh` with `--status` (read only, always exit 0; a test runs it against a fake
   `gcloud` and greps its function) and the set-up (the cost lines, then YES or nothing changes).
7. **Wiring**: `api/r14_wiring.py` (`wire_r14` after R11 and before the gateway, `build_parts` /
   `check_part` with tools, jobs, services and Vitals ids per owner, `install_services`: Part B's
   observer to `app.state.tick_observer`, its errors handler installed once and replaced, never
   stacked, Part D's phrases one at a time; `r14_tools`, `r14_tick_jobs`, `r14_clock_jobs`,
   `R14Vitals`, `r14_privacy_sources`, `backup_status`, `bind_brain`, `install_r14_routes`).
   `api/tick_wiring.py` took `_tick_jobs` out of `app.py` (735 → 726) with R14's daily jobs last,
   and holds the one 5-minute clock (D7): `add_clock_job` (the systems check, the helpers' and R7's
   clocks register there instead of on the watchdog), `ForOwners` (each runs for the brief's owners,
   read late), `install_clocks` (R14's clock jobs first: `Watchdog.prepend`; the rest after the
   laptop check), `finish_wiring` (the last lifespan step). `api/home.py`'s Home-off route runs
   `app.state.clock_jobs` (advisory: "degraded", never a 503). `ticks.run_jobs` hands the observer
   `ok` / `failed` / `timed_out` / `skipped` with the clock and seconds (the tick answer unchanged);
   `api/brief.py` reports its sweeps; the watchdog passes its outcomes too; `ADVISORY_JOBS` +=
   `selfwatch_clock`. `core/brain.py` (704 → 710): `self.slots = BrainSlots()` and its two uses (the
   offered tools; `LedgerCall` after billing). `tools/setup.py` `r14=`; `api/personal.py` the privacy
   slot; `vitals/own.py` the `r14` source, `own_item`, R14's ids in `LABELS` (four quiet, `db_size`
   alerts); `vitals/words.py` their fixed words. The test-side registry
   (`test_telegram_tool_guard.py` `linked_gateway`) builds the R14 parts through the real wiring
   (`r14=`).
8. **Guide and book**: the guide v14.0.1 (cards C66 Backups and restore drill, C67 Self-health
   watch, C68 Skill register and the turn's tools, PLANNED, every planned collection named; the L5
   and L7 rows; the edition line; the change log); the layer map (`backup` L7, `skills` L5,
   `selfwatch` and `hardening` X).
9. **Evals and fakes**: `evals/r14/run.py` (R7's shape), stubs `backup`, `selfwatch`, `offer`,
   `noai`, `needles`, and I0's built `contract` (every part builds through the real wiring and owns
   only its own; five stray parts are refused; its control takes the check away and the five
   refusals fail); gated in `evals/run_all_mock.py`; `tests/r14_fakes.py` (`RecordingJob`,
   `Outcomes`, `FakeBackupStatus`, `ready_backup`, `facts`, `fake_spec`).
10. **Console**: only the Alerts card's eleven rows (`console-alerts.js` 450 → 462). No Vitals or
    Privacy change (both server-sent); the CSP is unchanged; `console.html` stays 782.
11. `BRIEF-COMMON.md` (with the hook's rule: a blocked action means stop and report) and this file.
12. **Coverage and the hook** (D17, D18): `pytest-cov>=7` in the dev extra; CI's 3.12 step with
    `--cov=jarvis --cov-report=term-missing:skip-covered --cov-report=json:coverage.json` and
    `scripts/coverage_floor.py` (the total to the job summary; fails only below
    `scripts/coverage_floor.txt`); the 3.11 step is plain `pytest -q`; coverage files ignored.
    `.claude/settings.json` + `.claude/hooks/guard.py` and the CLAUDE.md line.

The persona and `PERSONA_VERSION` "p7.0" are untouched (p14.0 is I1's; a test holds it).

## 4. Decisions taken at I0 (safe defaults, for the owner)

The plan's section "Decisions taken at I0" lists nine (the cache within a reply; no new console
controls; the booking address as text; the custom delete role; self-health's own cap; no backup
alerts before the set-up; 2 manual drills, never with Approve all; cards C66–C68; the start-up
lock). Added while building:

10. The tick observer is passed to `run_jobs`, not registered module-wide (no state shared between
    apps).
11. R6's book jobs stay on the watchdog only; the shared 5-minute clock carries the four jobs the
    plan names.
12. With Home on, the systems check now runs for the brief's owners, not only the owners who linked
    a laptop (the same person today: one owner).
13. The set-up script's stub prints its cost lines in "Rs" (plain ASCII in Cloud Shell); Part A may
    keep or change the wording, never the YES gate or `--status`'s read-only rule.
14. The coverage floor starts at the total measured here, rounded down; the hook is a guard against
    the mistakes CLAUDE.md names, not a security boundary.

## 5. For the owner

Nothing blocks the parts, and nothing here needs him before the PR. His one-time backup step comes
after the R14 PR is merged and deployed (plan "The owner's one-time steps"). Until then: no backups,
no cost, Vitals says "Backups: not set up", and nothing alerts about backups.

## 6. The checks (in order, one at a time; 2 CPUs)

Being run; the results follow in v14.0.2 of this file.

## Change log

| Version | Date | Release | What changed | By |
|---|---|---|---|---|
| v14.0.1 | 14 Nov 2026, 17:00 IST | R14 | First edition: the base, the stale lines found at I0 (cards C66–C68, the version file, the nouns, the observer, the Vitals slot, the clock sites), what I0 built for each of the 12 seams, the decisions taken, the owner's position | 🛠 Mark XVIII |
