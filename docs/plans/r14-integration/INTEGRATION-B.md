Version v14.0.2 · 14 Nov 2026, 17:38 IST · Release R14 · Status: Current · Owner: 🛠 Mark XIX

# R14 Part B — Self-health: integration notes for I1

Built by builder B for the Workshop (🛠 Mark XIX) on branch `r14-b`, from `origin/r14-i0` @
`9eb9d8b`, test first throughout (each module's tests were written and seen failing before it).
Plan: `docs/plans/r14-hardening.md` v14.0.2 (D5–D7, D13 item 7, review A6–A8). Nothing here spends
money, calls Google or a model, or adds a console control, a Scheduler job, a secret or a kind.
v14.0.2 is the fixer's pass over the three fresh-context reviews (silent-failure BLOCK on H1,
code APPROVE, Python WARN): every finding is in section 8 with its outcome and its test.

## 1. What Part B built

| Deliverable | Where | What it does |
|---|---|---|
| Job ledger and once-only claims | `selfwatch/ledger.py` | Failed or timed-out runs in a row per job and sweep, fed by the tick observer; `ok` ends a streak, a skip never counts nor ends one; each streak told once; a job never reports its own streak. After a restart the stored streak is joined (failures seen before the load add to it; only an `ok` seen here ends it), and the ledger is never written before the stored copy was read. `Told`: create-only claims `selfwatch_told/{uid}_{sha256(kind|cause)[:24]}` written **before** the send, reserved in memory before the await; given back (`release`) when the send reached nobody; in memory when the store is down; swept after 30 days |
| Fixed texts and the teller | `selfwatch/texts.py` | Every alert a fixed template (job names, a time, the version, the spike's ₹ only), ≤ 300 characters. `Teller.tell -> Said(sent, settled)`: claim, then send with `SENDING` set, then read the `Delivery` as Home's `watchdog.took` does for its idle alert: told when a channel took it, held, or dropped by the owner's own choice (`SETTLED`). Anything else gives the claim back and answers `settled=False`; retried at most every 30 minutes, 6 times, then the claim stands. No notifier or no owner: nothing claimed, not settled. A failed send is logged as a class name and never raised |
| Errors handler (`log_handler`) | `selfwatch/errors.py` | A `logging.Handler` (level ERROR) counting by local hour and logger name (≤ 50 names, the rest "other"); never its own package (`jarvis.selfwatch*`); never `QUIET_LOGGERS` while `SENDING`; never fails out loud (`emit` catches all, `handleError` off; the stdlib `flush`/`close` untouched). Counts written batched by the 5-minute job to `selfwatch_errors/{yyyymmdd}`, kept 14 days |
| The two clocks | `selfwatch/clocks.py` | The tick says the 5-minute clock is stopped (unseen 20 minutes); the 5-minute clock says no tick ran by 05:00 local; each once per outage, and the stopped clock's next run says it is back (`selfwatch_ok`). A clock never seen is judged from `first_seen` (decision 7). An event whose alert reached nobody is undone (`undo`) and raised again. `selfwatch/clocks` kept by a transaction that keeps each clock's later stamp and the earlier baseline |
| Brief not made | `selfwatch/brief_check.py` | Today's brief absent or failed at its time + `selfwatch_brief_grace_min`; read through `BriefService.today()` at most about twice a day (once for its time, once at time + grace); once a day per owner |
| Spend spike | `selfwatch/spend.py` | One month-total snapshot a day per owner (`Billing.month(uid).inr_total`) in `selfwatch/spend`; a day = its snapshot minus the day before (the 1st: its own; after a missed snapshot the difference spread over the gap); spike when > factor × the up-to-14-day average and ≥ the floor, after 7 days of history. `snapshot -> Snapshot(spikes, failed)`: each owner guarded on its own, his day done only once kept and its spike said; a failure is tried at the next tick the same day |
| New version live | `selfwatch/deploys.py` | `K_REVISION` and the version against `selfwatch/deploy`; first run only remembers; a revision seen before (restart, or the old one during a deploy) is never told; says the version. A new revision is remembered (`remember`) only after its alert is settled |
| The watch and its jobs | `selfwatch/jobs.py` | `Watch` (state + `observe`), `selfwatch_clock` (10 s budget: stamp, morning-clock check, streaks, brief, error counts, errors, version) and `selfwatch_daily` (25 s: stamp, 5-minute-clock check, streaks, each owner's spend snapshot until done, once a day the sweeps). Each step stands alone with a fair share of the time left; a failed or cut step counts under `failed`; the ledger is written in a reserved slice, in a `finally`. What an alert settles is committed only when it is settled |
| Status, privacy row | `selfwatch/status.py` | `Status.view()` for the route; `ToldPrivacy` row `selfwatch_told` (Settings and safety; count of claims; 30 days; no export, no delete) |
| Vitals item `clocks` | `selfwatch/vitals.py` | ok "are running", amber "one has stopped" (also a clock never seen once it should have run), red "have stopped" with "Clocks stopped since 16 Nov, 02:10.", unknown "not seen yet". Quiet (`VITALS_QUIET`) |
| The join | `selfwatch/part.py` | `build(ctx)`: the two jobs, `tick_observer`, `log_handler`, `status` (a private service key), the Vitals reader, the privacy row; `ready` "on"; `selfwatch_enabled` off → `HardeningPart("selfwatch", ready="off")`; the brief, billing and notifier read late |
| Route | `api/selfwatch.py` | `GET /v1/selfwatch` (owner-only, `no-store`): `{part, ready, clocks{tick, watchdog, tick_outage, watchdog_outage}, jobs[{name, runs, since, told}], errors_today, unrecorded{errors, outcomes}, alerts{waiting, given_up}, deploy{revision, version, at}, version}`; off → `{part, ready}`; a failing view → `unavailable: true`, never the cause's text |
| Held kind drop (D13 item 7) | `notify/store.py`, `home/heartbeat.py` | `NotifyStore.held_drop(uid, kinds)` (one transaction); the laptop-back path drops a held `home_offline_idle` before the morning summary (`DROP_WHEN_BACK`), never the armed `home_offline`; a failing drop never stops `home_online`. The store is reached through the notifier's own `store` (`NotifyService.store`), so no wiring file changed; `HeartbeatHandler(..., held=)` takes one explicitly too |
| Eval | `evals/r14/selfwatch.py` | `BUILT = True`: 13 cases on the real watch, `run_jobs`, policy and storm; 5 negative controls, each failing exactly its own case |
| Fakes | `tests/r14_fakes_b.py` | `RingCounter` (real policy + real storm, answering a `Delivery` as `NotifyService` does: a cap is a `drop` with the storm's reason; `dead` channels roll the storm slot back; `took()` lists what a channel took), `BrokenDocs`, `FakeBrief`, `FakeBilling`, `FlakyJob`, `build_world` |

## 2. What it keeps (prefix `jarvis_`; all named in card C67 by I0)

| Document | Holds | Kept | Writes |
|---|---|---|---|
| `selfwatch/jobs` | streaks `{name: {runs, since, told_at}}`, `last_alert`, `recovered` | overwritten | only when changed |
| `selfwatch/clocks` | `tick`, `watchdog`, `tick_outage` (day), `watchdog_outage` (stamp), `first_seen` (the baseline) | overwritten | each run of either clock (twice when an alert reached nobody and its event is undone) |
| `selfwatch/deploy` | `revision`, `version`, `at`, the last 10 revisions seen | overwritten | once per process at most |
| `selfwatch/spend` | `{owners: {uid: {"YYYY-MM-DD": ₹}}}`, 16 days per owner, ≤ 20 owners | overwritten | once a day per owner |
| `selfwatch_errors/{yyyymmdd}` | `{hours: {"HH": n}, loggers: {name: n}, other}` | 14 days | when there are new errors |
| `selfwatch_told/{uid}_{hash}` | `{uid, kind, at}` (the cause is hashed, never kept) | 30 days | one per alert |

About 310 reads and 300 writes a day (the clocks transaction every 5 minutes dominates): ₹0
inside Firestore's free quota, as the plan says. While an alert waits to be tried again (at most
about 2.5 hours, decision 11), the check that raises it reads again each run (a clock event
also writes its undo, a new revision re-reads `selfwatch/deploy`, a missed brief re-reads
`BriefService.today`): a few dozen reads at most, only while delivery is failing.

## 3. Decisions taken in Part B (safe defaults)

1. **Errors piling up are held while a job streak told in the last 6 hours still runs**
   (`ERRORS_HELD`, v14.0.2; before: for the whole streak). During an outage every failing job
   logs an error, so `errors_piling` would be a second ring about the same incident: the hours
   that piled up meanwhile are that incident's (`errors.Piles` covers them) and are never said
   again. Any other hour over the limit (after the jobs recover, or 6 hours after the job alert
   while one job keeps failing) is owed and said, even with no new error. This is what keeps
   "a whole-Firestore outage → at most 1 ring" true without letting one long-failing job mask
   every other error storm.
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
7. **The clocks' baseline (v14.0.2, silent review M3).** The clocks document keeps
   `first_seen`, the first time either clock was seen (the earliest wins, across processes).
   A clock never seen is judged from it, never in a fresh install's first hour (`FRESH`):
   - the morning clock, never seen, is due at the first 05:00 local at least an hour after
     `first_seen` (installed at 14:00: by 05:00 the next day; installed at 04:30: by 05:00 the
     day after, since that morning's ticks were inside its first hour; installed at 03:00: by
     05:00 that day, after the 04:00 and 04:30 ticks);
   - the 5-minute clock, never seen, is stopped once `first_seen` is more than an hour old
     (said by the tick, "has not run at all since …").
   So a clock that never starts after a deploy (a missing or mis-set Scheduler job) is said
   once, and the Vitals item turns amber instead of "ok, hasn't run yet". With no clock seen at
   all nothing can be said (nothing runs the checks); the Vitals item says "not seen yet".
8. **With the store down**, claims and clock stamps live in memory, so an outage is still said
   once from this process.
9. **The errors handler never counts its own package** (`jarvis.selfwatch*`), whether sending or
   not, and logs its own trouble at WARNING.
10. The status service is a private key `services["status"]` (not in `SERVICE_OWNER`; `check_part`
    allows it); the route reads it per request.
11. **What counts as told, and the retries (v14.0.2, silent review H1).** An alert is told when
    a channel took it (Telegram or a push), when it was held for the morning summary, or when
    it was dropped by the owner's own choice (`switched_off`, `feed_only`; the same set as
    `home.watchdog.OWNER_SETTLED`, pinned by a test). A storm cap, no channel, a send that
    raised or was cancelled reached nobody: the claim is given back and nothing is committed.
    It is tried again at most every 30 minutes (`RETRY_EVERY`, the storm's own `SELF_GAP`, so
    a capped kind is admitted again by then) and 6 times in all (`MAX_TRIES`); then the claim
    stands and it is logged "given up". Every retry passes the storm again, so none rings past
    the self-health cap (a test runs five kinds for three hours: each said once, never more
    than 3 in any hour). The status route counts the waiting and the given-up alerts.
12. **No notifier yet, or no owner, is "not settled"**: nothing is claimed, the state stays
    uncommitted and the next run tries again (the notifier is read late; once it exists the
    alert goes out). "No notifier" is logged once per process.
13. **Spend after a missed snapshot (v14.0.2, silent review M2)**: the difference is spread
    evenly over the days since the last snapshot (or since the 1st when the month began again).
    Spreading can only lower a day's figure, so it never makes a false spike; a spike after a
    missed morning is still seen (and says the per-day figure).
14. **Time shares (v14.0.2, silent review M4)**: each step gets what is left of 85 % of the
    job's time (`ticks.time_left()`, else its budget), split over the steps still to run; the
    ledger write has 10 % kept for it, in a `finally`. The 5-minute job's order is now load,
    the 5-minute stamp, the job streaks, the brief, the error counts, the version.

## 4. Checks (this worktree, 14 Nov 2026, after the review follow-ups)

| Check | Result |
|---|---|
| Own tests, 3.12: `tests/test_r14_b_*.py` (9 files, new: `test_r14_b_retries.py`) | **183 passed** (113 at v14.0.1) |
| Own tests, 3.11 | **183 passed** |
| Existing tests of my files: `test_home_webhook`, `test_notify_service`, `test_notify_hardening`, `test_notify_policy`, `test_r3_wiring`, `test_webpush_service`, `test_r6_fix_push` | **449 passed** (with B's own) |
| Coverage of `jarvis.selfwatch` + `api/selfwatch` (own tests) | **99 %** (1,231 statements, 13 missed) |
| Seam set (`test_r14_seams`, `test_r14_wiring`, `test_claude_guard`, `test_arch_coverage`, `test_telegram_tool_guard`) | 265 passed, 13 failed: the 4 pins of section 5.1 (expected: Part B is built) and the 9 `test_claude_guard` rm cases (section 5.3: this worktree's path, not this diff) |
| Section 5.1 diffs re-checked on a throw-away export under `/tmp` | `test_r14_seams` + `test_r14_wiring`: 89 passed; the one failure needs `.git` (`test_the_real_repository_is_r14_and_its_plan_comes_first`) |
| `ruff check` / `ruff format --check` (src tests evals scripts) | clean (1,678 files) |
| `mypy src` | 9 errors: exactly the baseline (`core/window.py`, `llm/anthropic_provider.py`, `memory/redis_store.py`) |
| `evals/r14/run.py --mock --part selfwatch` | **13/13**, exit 0; control failed the suite: True, each of the 5 controls failing exactly its own case (streak counting off → `three_failures_one_alert`; aggregation off → `outage_rings_once`; the outcome ignored → `skip_never_counts`; the delivery ignored → `undelivered_said_later`; the baseline off → `clock_never_started`) |
| `evals/r14/run.py --mock` (all parts) | 26/26, exit 0 |
| `scripts/arch_coverage.py` | OK: 65 packages and modules, 90 console modules, 2 Scheduler jobs, 30 services, 102 collections |
| `scripts/check_doc_versions.py` | all 28 documents pass |
| Functions ≤ 50 lines, modules ≤ 400 | largest function 33 lines (`Watch.__init__`); largest module `jobs.py` 361 lines |

## 5. Needs I1

Every diff below was applied to a throw-away export of `r14-b` under `/tmp` (never this
worktree) and run: the six files pass (153 passed; the one failure there was
`test_the_real_repository_is_r14_and_its_plan_comes_first`, which needs `.git`). v14.0.2
re-checked section 5.1 on an export of the new head (89 passed, the same `.git` one failing):
the review follow-ups need **nothing new from I1**. The route's two new keys (`unrecorded`,
`alerts`) do not touch diff (a), which compares `part` and `ready` only.

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
their retention; the held idle alert dropped when the laptop is back (D13 item 7). From
v14.0.2 also: an alert no channel took is tried again (every 30 minutes, 6 times) and never
counted as told; a clock that never starts after a deploy is said once (never in the first
hour); errors are held for 6 hours after a job alert, not for its whole streak.

## 6. Blocked actions

The GateGuard hook blocked nothing. Once, the session's own permission check refused a
temporary edit I tried to make to other parts' test files in this worktree (to check the
section 5 diffs): I stopped, restored nothing (nothing had changed) and checked the diffs on a
throw-away export under `/tmp` instead. v14.0.2 (the fixer): nothing was blocked; the section 5.1
diffs were re-checked the same way, on an export under `/tmp`, never in this worktree.

## 7. Not verified here (only live can)

- `K_REVISION` on the live service and what the first R14 deploy stores (S5 not fetched).
- The real clocks: Cloud Scheduler's tick (`0,30 4-11`, the brief's time zone) and watchdog
  (`*/5`), and that the tick's first run is before 05:00 local every day.
- Real delivery: Telegram and Web Push for the seven kinds, quiet hours, the held summary.
- Firestore's own transaction retries and read/write counts (the ≈ 310 / 300 a day estimate).
- How many ERROR lines the live service writes in a normal hour (the 30 an hour threshold).
- That a live `jarvis.notify*` / `jarvis.telegram*` record raised during a send is skipped (the
  context flag crosses `await`s, tasks created inside the send and `asyncio.to_thread`, pinned
  by a test; a `loop.run_in_executor` call does not copy the context and would be counted).
- The real `NotifyService`'s `Delivery` for the seven kinds when Telegram or push is down, or
  the cap drops one: the teller was tested against a fake that answers as the service's code
  reads (a cap is `drop` with the storm's reason; a ring no channel took rolls back its storm
  slot), not against the live service.
- How the per-step time shares behave on the live watchdog (only `ticks.time_left()` and
  fakes here).

## 8. Review follow-ups (v14.0.2)

The three fresh-context reviews of `r14-b` @ `4382b10`: silent-failure (BLOCK: 1 H, 6 M, 5 L),
code (APPROVE: 2 M, 3 L), Python (WARN: 3 M, 4 L). Overlaps fixed once. Each fix was test
first (the test seen failing, then the fix); tests named below are in `tests/test_r14_b_*.py`.

| Finding | Outcome | Test(s) |
|---|---|---|
| Silent **H1** (with code M1, M2): any non-raising `notify` counted as sent; the claim and every caller's state committed | **Fixed.** `Teller` reads the `Delivery` (decision 11); not reached → claim given back, `Said.settled=False`, bounded retries; every caller commits only when settled: `report_jobs` (mark_told, `last_alert`), the clocks (`undo`), the version (`remember`), the brief (`settle`), the spend (`settle`), the errors (`Piles.settle`); waiting and given-up alerts in the status | texts: `test_a_send_the_cap_dropped_gives_its_claim_back_and_is_tried_again_later`, `test_retries_never_ring_past_the_self_health_cap`, `test_a_ring_no_channel_took_is_tried_a_bounded_number_of_times`, `test_a_held_alert_and_one_he_switched_off_are_settled`, `test_a_cancelled_send_gives_its_claim_back`, `test_one_owner_reached_and_one_not_tries_only_the_other_again`, `test_no_notifier_claims_nothing_is_not_sent_and_is_logged_once`, `test_settled_drops_are_the_ones_home_settles_too`; retries: all 13 H1 cases (jobs, clocks, brief, version, spend, errors); part: `test_the_status_shows_alerts_waiting_to_be_tried_again_and_given_up`; eval `undelivered_said_later` + control |
| Code **M1** (a capped alert keeps its claim) | **Fixed** with H1 | `test_a_capped_job_alert_is_deferred_not_lost` |
| Code **M2** (`report_jobs` marks told when nothing was sent) | **Fixed** with H1 (also no notifier, no owner) | `test_a_streak_seen_before_the_notifier_exists_is_said_once_it_does`, `test_no_owner_is_nobody_told` |
| Silent **M1**: `errors_piling` dropped, not deferred; a long told streak masks every error storm | **Fixed** (decision 1): owed days said until settled; the incident's own hot hours covered; held 6 h, not the whole streak | errors: `test_a_pile_seen_during_a_told_incident_is_never_owed_and_others_are`, `test_the_piles_remember_a_week_at_most`; retries: `test_errors_piling_that_reached_nobody_is_said_later_with_no_new_errors`, `test_a_job_told_hours_ago_no_longer_hides_other_errors`, `test_an_incidents_own_errors_are_not_said_again_after_it_ends` |
| Silent **M2**: the spend snapshot skipped for the day after a transient failure, blinding the next day | **Fixed**: an owner's day done only once kept and said; a failure fails the step and is tried at the next tick; a missed day spread over the gap (decision 13); billing not there yet waits without failing | retries: `test_an_unreadable_spend_fails_the_step_and_is_taken_later_that_day`, `test_without_billing_yet_the_spend_waits_and_never_fails`; spend: `test_a_missed_snapshot_spreads_the_spend_over_its_days` |
| Silent **M3** (with code L1): a clock never seen is never reported; Vitals "ok" | **Fixed** (decision 7, the baseline) | clocks: `test_a_morning_clock_never_seen_is_missing_at_its_first_five_oclock_an_hour_on`, `test_a_five_minute_clock_never_seen_is_stopped_an_hour_after_the_first_tick`, `test_the_tick_says_a_never_seen_five_minute_clock_once_and_back`, `test_a_fresh_install_says_nothing_in_its_first_hour`, `test_a_morning_clock_that_never_starts_after_a_deploy_is_said`, `test_the_first_seen_is_kept_and_the_earliest_wins`; part: the two amber Vitals tests and `test_clocks_with_only_a_first_seen_are_red_not_a_crash`; eval `clock_never_started` + control |
| Silent **M4**: the flush skipped on a timeout; later steps starve | **Fixed** (decision 14) | jobs: `test_a_hung_step_starves_neither_the_others_nor_the_ledger`, `test_the_ledger_is_kept_even_when_the_job_is_cut_from_outside`, `test_the_brief_is_checked_before_the_errors_are_written`, `test_a_step_with_no_time_left_is_cut_and_counted` |
| Silent **M5**: on load, this process's outcomes drop stored progress | **Fixed**: failures seen before the load join the stored streak; only an `ok` seen here ends it; never written over an unread stored copy | ledger: `test_failures_seen_before_the_load_join_the_stored_streak`, `test_a_streak_that_ended_here_and_began_again_is_this_processs_own`, `test_skips_before_the_load_never_hide_the_stored_streak`, `test_the_ledger_is_never_written_over_a_stored_one_it_could_not_read` |
| Silent **M6**: memory-only outages and claims may be told again after a restart | **Accepted as designed** (the reviewer: a duplicate, never lost); the H1 fix keeps the memory state consistent (a claim given back in memory is overwritten in the store by the next claim made here) | ledger: `test_a_claim_whose_delete_failed_is_still_released_in_this_process` |
| Python **M1** (code L2): naive stored datetimes break the job step and the sweep | **Fixed**: `ledger._when` refuses a naive time | ledger: `test_a_naive_stored_time_reads_as_unknown_never_as_a_time`, `test_a_naive_claim_time_is_swept_not_a_crash` |
| Python **M2**: the `dirty` race in `flush` | **Fixed**: the document taken and `dirty` cleared before the await, set back on failure | ledger: `test_a_change_made_while_the_ledger_is_written_stays_to_write`, `test_a_write_that_fails_keeps_the_ledger_to_write` |
| Python **M3**: one owner's failed write loses another's spike; corrupt keys; `_done` before the write | **Fixed**: each owner guarded on its own; keys validated with `date.fromisoformat`; done only after the write and the alert | retries: `test_one_owners_failed_write_never_loses_anothers_spike`; spend: `test_a_damaged_stored_day_is_left_out_never_a_crash` |
| Silent **L1**: `ErrorCounter.broken` never read | **Fixed**: `unrecorded` count (`broken` a read-only property, python L3); new ones fail the step once; shown in the status | errors: `test_a_broken_record_never_raises_and_never_logs`; retries: `test_records_the_handler_could_not_count_fail_the_step_once`; part: `test_the_status_shows_what_the_handler_and_the_observer_could_not_count` |
| Silent **L2**: `Watch.observe` swallows silently | **Fixed**: counted, logged once by the next run, shown in the status | jobs: `test_the_jobs_answer_counts_and_the_observer_never_raises`, `test_an_observer_that_failed_is_logged_once_by_the_next_run` |
| Silent **L3**: no brief service, no log | **Fixed**: logged once | `test_no_brief_service_is_logged_once_never_silent` |
| Silent **L4**: a corrupt clocks document reads as a fresh baseline, no log | **Fixed**: an unreadable stored field is logged (a count) | clocks: `test_a_damaged_stored_field_is_logged` |
| Silent **L5** a: the all-clear cleared before its send | **Fixed** with H1 (`recovered` / `clear_recovered` after the send) | `test_the_all_clear_that_reached_nobody_is_said_later` |
| Silent **L5** b: several owners, a later failure loses an earlier spike | **Fixed** with python M3 | `test_one_owners_failed_write_never_loses_anothers_spike` |
| Silent **L5** c: a brief whose grace crosses midnight is never reported | **Declined**: it cannot happen. A brief time is 04:00–11:30 (`brief.models.parse_brief_time`) and the grace at most 240 minutes (`Settings.selfwatch_brief_grace_min`), so the latest deadline is 15:30 the same day | — |
| Code **L3**: `SENDING` across threads and tasks | **Pinned** (no code change needed): tasks and `asyncio.to_thread` started by the send copy the context; `run_in_executor` would not (section 7) | texts: `test_what_a_send_logs_from_a_task_or_a_thread_is_left_out_too` |
| Python **L1**: an observer stamp during `Clocks.update` overwritten | **Fixed**: `mine = merged(result, mine)` | clocks: `test_a_stamp_seen_during_the_update_is_kept` |
| Python **L2**: `startswith(OWN)` matches a lookalike; the `BaseException` re-queue | **Fixed**: exact name or below a dot (also the quiet loggers); the double count on a cancel after a commit is commented (acceptable for counts) | errors: `test_only_its_own_package_is_left_out_never_a_lookalike` |
| Python **L3**: typing | **Fixed**: `part.late` typed; the route checks a runtime `StatusView` Protocol instead of a `type: ignore`; `broken` read-only. **Declined**: the unused `me` / `owners` parameters are the `Step` signature (the reviewer agreed) | the route tests; `mypy src` baseline only |
| Python **L4**: two claims at once with the store down both made | **Fixed**: reserved in memory before the await (taken back if cancelled) | ledger: `test_two_claims_at_once_with_the_store_down_make_one`, `test_a_claim_cancelled_mid_transaction_is_not_kept` |

## Change log

| Version | Date | Release | What changed | By |
|---|---|---|---|---|
| v14.0.2 | 14 Nov 2026, 17:38 IST | R14 | Review follow-ups (section 8): every CRITICAL/HIGH/MEDIUM fixed and the cheap lows; one low declined (cannot happen), one medium accepted as designed. The teller reads the `Delivery` and retries (decision 11, 12); callers commit only what was said; the clocks' baseline `first_seen` (decision 7); errors held 6 h with covered hours (decision 1); spend per owner and spread over a gap (decision 13); per-step time shares and the ledger written in a `finally` (decision 14); the route's `unrecorded` and `alerts`; eval 13 cases and 5 controls; checks re-run; nothing new for I1 | 🛠 Mark XIX |
| v14.0.1 | 14 Nov 2026, 16:55 IST | R14 | First edition: Part B built (the ledger and claims, the fixed texts, the errors handler, the two clocks, the brief, spend and version checks, the watch and its two jobs, the route, the Vitals item, the privacy row, the held idle drop), what it keeps, the decisions, the checks, the I1 diffs verified on a scratch copy, the hook note, what only live can prove | 🛠 Mark XIX |
