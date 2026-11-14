Version v14.0.1 · 14 Nov 2026, 16:55 IST · Release R14 · Status: Current · Owner: 🛠 Mark XIX

# R14 Part B — Self-health: integration notes for I1

Built by builder B for the Workshop (🛠 Mark XIX) on branch `r14-b`, from `origin/r14-i0` @
`9eb9d8b`, test first throughout (each module's tests were written and seen failing before it).
Plan: `docs/plans/r14-hardening.md` v14.0.2 (D5–D7, D13 item 7, review A6–A8). Nothing here spends
money, calls Google or a model, or adds a console control, a Scheduler job, a secret or a kind.

## 1. What Part B built

| Deliverable | Where | What it does |
|---|---|---|
| Job ledger and once-only claims | `selfwatch/ledger.py` | Failed or timed-out runs in a row per job and sweep, fed by the tick observer; `ok` ends a streak, a skip never counts nor ends one; each streak told once; a job never reports its own streak. `Told`: create-only claims `selfwatch_told/{uid}_{sha256(kind|cause)[:24]}` written **before** the send; in memory when the store is down; swept after 30 days |
| Fixed texts and the teller | `selfwatch/texts.py` | Every alert a fixed template (job names, a time, the version, the spike's ₹ only), ≤ 300 characters. `Teller.tell`: claim, then send with `SENDING` set; a failed send is logged as a class name and never raised |
| Errors handler (`log_handler`) | `selfwatch/errors.py` | A `logging.Handler` (level ERROR) counting by local hour and logger name (≤ 50 names, the rest "other"); never its own package (`jarvis.selfwatch*`); never `QUIET_LOGGERS` while `SENDING`; never fails out loud (`emit` catches all, `handleError` off; the stdlib `flush`/`close` untouched). Counts written batched by the 5-minute job to `selfwatch_errors/{yyyymmdd}`, kept 14 days |
| The two clocks | `selfwatch/clocks.py` | The tick says the 5-minute clock is stopped (unseen 20 minutes); the 5-minute clock says no tick ran by 05:00 local; each once per outage, and the stopped clock's next run says it is back (`selfwatch_ok`). Nothing without a baseline. `selfwatch/clocks` kept by a transaction that keeps each clock's later stamp |
| Brief not made | `selfwatch/brief_check.py` | Today's brief absent or failed at its time + `selfwatch_brief_grace_min`; read through `BriefService.today()` at most about twice a day (once for its time, once at time + grace); once a day per owner |
| Spend spike | `selfwatch/spend.py` | One month-total snapshot a day per owner (`Billing.month(uid).inr_total`) in `selfwatch/spend`; a day = its snapshot minus the day before (the 1st: its own); spike when > factor × the up-to-14-day average and ≥ the floor, after 7 days of history |
| New version live | `selfwatch/deploys.py` | `K_REVISION` and the version against `selfwatch/deploy`; first run only remembers; a revision seen before (restart, or the old one during a deploy) is never told; says the version |
| The watch and its jobs | `selfwatch/jobs.py` | `Watch` (state + `observe`), `selfwatch_clock` (10 s budget: stamp, morning-clock check, error counts, streaks, errors, brief, version) and `selfwatch_daily` (25 s: stamp, 5-minute-clock check, streaks, once a day the spend snapshot and sweeps). Each step stands alone; a failed step counts under `failed` |
| Status, privacy row | `selfwatch/status.py` | `Status.view()` for the route; `ToldPrivacy` row `selfwatch_told` (Settings and safety; count of claims; 30 days; no export, no delete) |
| Vitals item `clocks` | `selfwatch/vitals.py` | ok "are running", amber "one has stopped", red "have stopped" with "Clocks stopped since 16 Nov, 02:10.", unknown "not seen yet". Quiet (`VITALS_QUIET`) |
| The join | `selfwatch/part.py` | `build(ctx)`: the two jobs, `tick_observer`, `log_handler`, `status` (a private service key), the Vitals reader, the privacy row; `ready` "on"; `selfwatch_enabled` off → `HardeningPart("selfwatch", ready="off")`; the brief, billing and notifier read late |
| Route | `api/selfwatch.py` | `GET /v1/selfwatch` (owner-only, `no-store`): `{part, ready, clocks{tick, watchdog, tick_outage, watchdog_outage}, jobs[{name, runs, since, told}], errors_today, deploy{revision, version, at}, version}`; off → `{part, ready}`; a failing view → `unavailable: true`, never the cause's text |
| Held kind drop (D13 item 7) | `notify/store.py`, `home/heartbeat.py` | `NotifyStore.held_drop(uid, kinds)` (one transaction); the laptop-back path drops a held `home_offline_idle` before the morning summary (`DROP_WHEN_BACK`), never the armed `home_offline`; a failing drop never stops `home_online`. The store is reached through the notifier's own `store` (`NotifyService.store`), so no wiring file changed; `HeartbeatHandler(..., held=)` takes one explicitly too |
| Eval | `evals/r14/selfwatch.py` | `BUILT = True`: 11 cases on the real watch, `run_jobs`, policy and storm; 3 negative controls, each failing its own case |
| Fakes | `tests/r14_fakes_b.py` | `RingCounter` (real policy + real storm), `BrokenDocs`, `FakeBrief`, `FakeBilling`, `FlakyJob`, `build_world` |

## 2. What it keeps (prefix `jarvis_`; all named in card C67 by I0)

| Document | Holds | Kept | Writes |
|---|---|---|---|
| `selfwatch/jobs` | streaks `{name: {runs, since, told_at}}`, `last_alert`, `recovered` | overwritten | only when changed |
| `selfwatch/clocks` | `tick`, `watchdog`, `tick_outage` (day), `watchdog_outage` (stamp) | overwritten | each run of either clock |
| `selfwatch/deploy` | `revision`, `version`, `at`, the last 10 revisions seen | overwritten | once per process at most |
| `selfwatch/spend` | `{owners: {uid: {"YYYY-MM-DD": ₹}}}`, 16 days per owner, ≤ 20 owners | overwritten | once a day per owner |
| `selfwatch_errors/{yyyymmdd}` | `{hours: {"HH": n}, loggers: {name: n}, other}` | 14 days | when there are new errors |
| `selfwatch_told/{uid}_{hash}` | `{uid, kind, at}` (the cause is hashed, never kept) | 30 days | one per alert |

About 310 reads and 300 writes a day (the clocks transaction every 5 minutes dominates): ₹0
inside Firestore's free quota, as the plan says.

## 3. Decisions taken in Part B (safe defaults)

1. **Errors piling up are not said while a told job streak still runs.** During an outage every
   failing job logs an error, so `errors_piling` would be a second ring about the same incident;
   it waits, and is said if errors still pile up after the jobs recover. This is what keeps "a
   whole-Firestore outage → at most 1 ring" true.
2. **`selfwatch_ok` for jobs** is one message once every told streak has ended (info, feed or
   silent), not one per job.
3. **The deploy check's first run is silent** (nothing stored to compare); R14's own first deploy
   says nothing. An old revision answering during a deploy is never told.
4. **Spend: 16 snapshots** (today and 15 days back), so the average really covers 14 whole days
   (the data model said "15 days").
5. **`selfwatch_clock` budget 10 s** (it runs first in the watchdog's 50 s); `selfwatch_daily` 25 s.
6. **A step that fails counts under `failed`**, so the job reports "failed" and its own streak is
   watched by the other job (the plan's "the tick's `selfwatch_daily` watches `selfwatch_clock`");
   both jobs report every streak but their own and share the hourly limit.
7. **Clock checks need a baseline**: a clock never seen (a fresh install) raises nothing.
8. **With the store down**, claims and clock stamps live in memory, so an outage is still said
   once from this process.
9. **The errors handler never counts its own package** (`jarvis.selfwatch*`), whether sending or
   not, and logs its own trouble at WARNING.
10. The status service is a private key `services["status"]` (not in `SERVICE_OWNER`; `check_part`
    allows it); the route reads it per request.

## 4. Checks (this worktree, 14 Nov 2026)

| Check | Result |
|---|---|
| Own tests, 3.12: `tests/test_r14_b_*.py` (8 files) | **113 passed** |
| Own tests, 3.11 | **113 passed** |
| Existing tests of my files: `test_home_webhook`, `test_notify_service`, `test_notify_hardening`, `test_notify_policy`, `test_r3_wiring`, `test_webpush_service`, `test_r6_fix_push` | **276 passed** (with `test_r14_b_held.py`) |
| Coverage of `jarvis.selfwatch` (own tests) | 96–100 % per module (`clocks`, `deploys`, `part`, `status`, `texts`, `api/selfwatch` 100 %) |
| Seam set (`test_r14_seams`, `test_r14_wiring`, `test_claude_guard`, `test_arch_coverage`, `test_telegram_tool_guard`) | 265 passed, 13 failed: the 4 pins of section 5.1 (expected: Part B is built) and 9 `test_claude_guard` rm cases (section 5.3: this worktree's path, not this diff) |
| `test_r14_wiring.py` alone | 13 passed (its handler test fails only after an earlier app installed B's real handler: 5.1 d) |
| `ruff check` / `ruff format --check` (src tests evals scripts) | clean (1,677 files) |
| `mypy src` | 9 errors: exactly the baseline (`core/window.py`, `llm/anthropic_provider.py`, `memory/redis_store.py`) |
| `evals/r14/run.py --mock --part selfwatch` | **11/11**; control (streak counting off + aggregation off + the outcome ignored) failed the suite: True; exit 0 |
| `evals/r14/run.py --mock` (all parts) | 24/24, exit 0 |
| `scripts/arch_coverage.py` | OK: 65 packages and modules, 90 console modules, 2 Scheduler jobs, 30 services, 102 collections |
| `scripts/check_doc_versions.py` | all documents pass |
| Functions ≤ 50 lines, modules ≤ 400 | largest function 30 lines (`Watch.__init__`); largest module `jobs.py` 278 lines |
| Wider sample with B built (vitals board, privacy, wiring files of R1–R11, R7/R11.1/R5.1 seams; 21 files) | 431 passed, 8 failed: every one a pinned tick-job list (5.2) |

## 5. Needs I1

Every diff below was applied to a throw-away export of `r14-b` under `/tmp` (never this
worktree) and run: the six files pass (153 passed; the one failure there was
`test_the_real_repository_is_r14_and_its_plan_comes_first`, which needs `.git`).

### 5.1 I0's pins that move now that Part B is built

a. `tests/test_r14_seams.py`, `test_the_app_starts_with_four_parts_and_their_status_routes`:

```diff
-        assert all(p.ready == "not built yet" for p in parts.values())
+        built = {"selfwatch": "on"}  # R14 B (I1 adds the other parts' words)
+        assert all(p.ready == built.get(n, "not built yet") for n, p in parts.items())
         for name, route in STATUS_ROUTE.items():
             r = await client.get(route)
             assert r.status_code == 200, name
-            assert r.json() == {"part": name, "ready": "not built yet"}
+            word = built.get(name, "not built yet")
+            assert {k: r.json()[k] for k in ("part", "ready")} == {"part": name, "ready": word}
             assert r.headers["cache-control"] == "no-store"
         r = await client.get(R14_STATUS_ROUTE)
-        assert r.json() == {"parts": {n: "not built yet" for n in PARTS}}
+        assert r.json() == {"parts": {n: built.get(n, "not built yet") for n in PARTS}}
```

b. `tests/test_r14_seams.py`, `test_the_parts_privacy_rows_reach_the_dashboard`:

```diff
-        assert wiring.r14_privacy_sources(app) == ()  # no part is built yet
+        assert [s.id for s in wiring.r14_privacy_sources(app)] == ["selfwatch_told"]  # R14 B
```

c. `tests/test_r14_seams.py`, `test_the_r14_runner_passes_and_its_contract_control_fails_it`:

```diff
-    for part in ("backup", "selfwatch", "offer", "noai", "needles"):
+    for part in ("backup", "offer", "noai", "needles"):  # selfwatch is built (R14 B)
         assert f"{part}:not_built_yet" in ids, part
+    assert "selfwatch:three_failures_one_alert" in ids
     control = report["negative_control"]
     assert control["suite_failed"] is True and control["failed_cases"]["contract"]
+    assert control["failed_cases"]["selfwatch"]
```

d. `tests/test_r14_wiring.py`, `test_the_errors_handler_is_installed_once_and_replaced_never_stacked`:
an earlier test's app (with its lifespan) leaves B's real handler on the root logger, so the
test's `before` already holds it and `install_log_handler(None)` then takes it away. The test
alone passes; after any lifespan app it fails.

```diff
     root = logging.getLogger()
+    wiring.install_log_handler(None)  # an earlier app's real errors handler (R14 B) comes off
     before = list(root.handlers)
```

(Alternative, I1's choice: have the lifespan take the handler off at shutdown; a part has no
shutdown hook, and `_CLOSABLES` is `app.py`'s.)

### 5.2 Other releases' tests that pin the tick's job list (R14's daily jobs come last)

```diff
# tests/test_r11_wiring.py (test_the_helpers_start_with_four_empty_parts_and_both_composites)
-        assert names[-4:] == ["helpers_clock", "helpers_daily", "mobile_clock", "mobile_daily"]
+        assert names[-5:-1] == ["helpers_clock", "helpers_daily", "mobile_clock", "mobile_daily"]
+        assert names[-1] == "selfwatch_daily"  # R14 B: the parts' daily jobs come last
# tests/test_r11_wiring.py (test_a_failing_part_is_left_empty_and_the_others_run)
-        assert set(out.json()["jobs"]) == {"health_check", "helpers_clock", "mobile_clock"}
+        jobs = {"selfwatch_clock", "health_check", "helpers_clock", "mobile_clock"}  # R14 B first
+        assert set(out.json()["jobs"]) == jobs
# tests/test_r2_wiring.py (test_without_the_token_key_everything_is_off_with_plain_words)
         "mobile_clock",  # R7's own two (I1 fixer), after R11's
         "mobile_daily",
+        "selfwatch_daily",  # R14 B: the parts' daily jobs come last
     ]
# tests/test_r2_wiring.py (test_tick_jobs_have_unique_names_none_of_the_ticks_own)
-    assert names == [*r2, "vitals_poll", "health_check", "book_seal", "book_sweep", *r11]
+    r14 = ["selfwatch_daily"]  # R14 B
+    assert names == [*r2, "vitals_poll", "health_check", "book_seal", "book_sweep", *r11, *r14]
# tests/test_r4_wiring.py (line 50; three tests use it)
-R11_JOBS = ("helpers_clock", "helpers_daily", "mobile_clock", "mobile_daily")
+R11_JOBS = ("helpers_clock", "helpers_daily", "mobile_clock", "mobile_daily", "selfwatch_daily")
# tests/test_r51_wiring.py (test_without_a_home_the_health_job_rides_the_tick_only)
             "mobile_clock",  # R7's own two, after R11's
             "mobile_daily",
+            "selfwatch_daily",  # R14 B
         ]
```

When Part A lands, its `backup_canary` and `backup_drill` come before `selfwatch_daily` in the
same lists (`r14_tick_jobs` walks the parts in `PARTS` order: backup, selfwatch, skills, noai).
I ran a 21-file sample, not the whole suite: other pins may exist (I1 runs it).

### 5.3 Not a diff: `test_claude_guard.py` in a Workshop worktree

Nine cases (`rm -rf src`, `rm -rf tests`, `rm -rf .git`, …) fail here: the hook rightly allows
`rm -rf` inside the Workshop's worktree folder (`SAFE_ROOTS`), and this worktree lives there, so `src`
resolves inside a safe root. No file the test reads changed on this branch
(`git diff 9eb9d8b -- .claude tests/test_claude_guard.py` is empty). In CI and in a checkout
elsewhere they pass, as at I0.

### 5.4 The guide (plan D15, I1's)

Card C67 "Self-health watch" can now say: the two jobs and when they run (D7); the seven kinds
and their rules (section 1); its own cap (storm `SELF_KINDS`) plus one aggregated `job_failing`
an hour, each streak once; errors held back during a told streak (decision 1); the Vitals item
`clocks`; `GET /v1/selfwatch`; the privacy row `selfwatch_told`; the documents of section 2 and
their retention; the held idle alert dropped when the laptop is back (D13 item 7).

## 6. Blocked actions

The GateGuard hook blocked nothing. Once, the session's own permission check refused a
temporary edit I tried to make to other parts' test files in this worktree (to check the
section 5 diffs): I stopped, restored nothing (nothing had changed) and checked the diffs on a
throw-away export under `/tmp` instead.

## 7. Not verified here (only live can)

- `K_REVISION` on the live service and what the first R14 deploy stores (S5 not fetched).
- The real clocks: Cloud Scheduler's tick (`0,30 4-11`, the brief's time zone) and watchdog
  (`*/5`), and that the tick's first run is before 05:00 local every day.
- Real delivery: Telegram and Web Push for the seven kinds, quiet hours, the held summary.
- Firestore's own transaction retries and read/write counts (the ≈ 310 / 300 a day estimate).
- How many ERROR lines the live service writes in a normal hour (the 30 an hour threshold).
- That a live `jarvis.notify*` / `jarvis.telegram*` record raised during a send is skipped (the
  context flag crosses `await`s and tasks created inside the send; tested in process only).

## Change log

| Version | Date | Release | What changed | By |
|---|---|---|---|---|
| v14.0.1 | 14 Nov 2026, 16:55 IST | R14 | First edition: Part B built (the ledger and claims, the fixed texts, the errors handler, the two clocks, the brief, spend and version checks, the watch and its two jobs, the route, the Vitals item, the privacy row, the held idle drop), what it keeps, the decisions, the checks, the I1 diffs verified on a scratch copy, the hook note, what only live can prove | 🛠 Mark XIX |
