Version v14.0.2 · 14 Nov 2026, 17:50 IST · Release R14 · Status: Current · Owner: 🛠 Mark XIX

# R14 Part A — backups and the restore drill (integration notes for I1)

Built by builder A for the Workshop (🛠 Mark XIX) on branch `r14-a`, from `origin/r14-i0` @
`9eb9d8b`, against the plan `docs/plans/r14-hardening.md` v14.0.2 (D3, D4, D5's backup rows, the
data model, "Part split" A), `BRIEF-COMMON.md`, `I0-NOTES.md` and `PLAN-REVIEW-1.md` (A2–A5, A8).
Every file written is in Part A's row; no wiring file, contract file or other part's file was
edited. Tests were written first and seen failing before each module (`tdd-guide`).
v14.0.2: the fixer's follow-ups of the four fresh-context reviews (python, silent-failure, code,
security), each with its test seen failing first: section 13; sections 1 to 12 say the result.

## 1. What Part A built

| Deliverable | Files | What it does |
|---|---|---|
| The read-only view (lock 1) | `backup/readonly.py` | `read_only(docs)`: `get` and `query` only; no `write`, `transaction`, `close` or `__dict__`; not a `Docs`; fixed slots. The verifier holds it for the live side |
| The admin adapter (lock 2) | `storage/firestore_admin.py` | `BackupAdmin` on `FirestoreAdminAsyncClient` (async, lazy import). Every call passes `drill_target` first: the four that name a database (restore's target, get, update, delete) pass that id; the three that name none (list backups, list schedules, poll an operation) pass the drill id against the live one, so it refuses to run at all when the live database is `jarvis-drill`. An operation naming a database must name the drill copy; only this project's backups are restored. Google's `PermissionDenied` / `Forbidden` become a plain `PermissionError` with fixed words; a gone database reads as None. Every call is bounded (`bounded`: 20 s, or what the tick's job has left less 2 s, never under 1 s; `TimeoutError` past it) |
| The drill-side reader (lock 2) | `storage/firestore_walk.py` | `DrillWalk` + `ReadOnlyDocs` on `jarvis-drill` only: checked when made and again before every call; collection ids, `count()` per collection group, samples, get, query; no writer; every call bounded like the admin's, Google's "no permission" a plain `PermissionError` |
| The canary | `backup/canary.py` | `{prefix}backup_canary/{yyyymmdd}` = SHA-256 of a random 32-byte nonce, the nonce sealed with `backup_probe` (AAD `backup_canary/{day}/v1`), the key's fingerprint (first 16 hex of `mac("backup_probe", "fingerprint/v1")`), the version, the time; once a day (his day, the owner's zone), kept 30 days; "the key changed" = the newest earlier canary doesn't open with today's key |
| The status | `backup/status.py` | `BackupStatusService` (the service `backup_status`, `backup.ports.BackupStatus`): `{prefix}backup_status/current` (schedule now, schedule FIRST seen = the set-up has run, the newest READY backup, the newest with its stats filled: size and count, the copies, when each cause was last told and how often a send failed today, when the key changed); written in transactions; a field that can't be read is dropped, the rest kept; the rupee costs at the live rate; `Teller`: `backup_problem` / `backup_ok` through the notifier, fixed templates (`backup/texts.py`), the claim written before the send, once a cause on his day, the left-over copy weekly, each drill's result once; a send that reached nobody gives its claim back (section 3) |
| The drill's log (lock 3) | `backup/log.py` | The ONE writer of `{prefix}backup_drill/current` (state) and `{prefix}backup_drills/{yyyymm}` (his month's latest result, 13 months). The tick's saves are transactions that keep a request he made meanwhile; an unreadable state fails closed (a clean-up, this month's drill had) |
| The checks (locks 1, 3) | `backup/verify.py`, `backup/walk_checks.py`, `backup/vault_probe.py` | D4's four checks, one unit at a time within `ticks.time_left()` (8 s reserve), resumable: the canary (within 26 h before the snapshot, equal to live, opens with the live key); each owner's vault through the vault store's own read path, compared on `rev` / `updated_at` and each item's own `updated_at`, one file opened whole and hashed in memory against the vault's recorded SHA-256 and size; `count()` per collection group (the root ids, the stores' pinned sub-collections, each owner's activity days from the copy's own index) equal to Google's document count exactly; up to 20 samples a collection on their own time field (the canaries left to their own check), at least 3 in all; at the same vault version the copy's items must be live's. First failure ends the checks; nothing (or too little) compared fails; no vault is "skipped", never a pass. Firestore's reserved `__x__` names never enter a hash. They import neither `storage.firestore_docs` nor `backup.log` (an import test) |
| The state machine | `backup/drill.py`, `drill_start.py`, `drill_end.py`, `drill_deps.py` | See section 2 (the start, the end and clean-up, what they share) |
| The jobs | `backup/jobs.py` | `backup_canary` (budget 30 s) and `backup_drill` (budget 60 s), morning tick only |
| The tools | `backup/tools.py`, `backup/names.py` | `vitals_backups` (R1, agent `vitals`) and `vitals_drill_start` (R2, `ask_when` always, fixed card text), and `BackupDesk` (what the tools and routes share). The two names live in `names.py`, a module with no imports, so I1's guard can import `START` (I1 #1) |
| Vitals | `backup/vitals.py` | `backups`, `backup_drill`, `db_size` (section 3) |
| Privacy | `backup/privacy.py` | The "Backups (Google's copies)" row, section "Settings and safety", delete `none`, no export |
| The join | `backup/part.py` | `build(ctx)` / `build_with(ctx, admin=, walk=, keys=, clock=)` (section 4) |
| The routes | `api/backup.py` | `GET /v1/backup`, `POST /v1/backup/drill` (section 4) |
| The set-up | `deploy/backup_setup.sh` | Section 5 |
| Tests | `tests/test_r14_a_{locks,status,verify,drill,jobs,part,setup}.py`, `tests/r14_fakes_a.py` (the world), `tests/r14_fakes_a_sdk.py` (the SDK stand-ins) | 177 passed + 1 strict xfail (I1 #1) on 3.12 and 3.11; Part A's modules at 96 % statement coverage |
| Eval | `evals/r14/backup.py` (`BUILT = True`) | 14 cases, two negative controls (section 6) |

## 2. The drill, one morning tick at a time

`{prefix}backup_drill/current` holds the phase: **idle → restoring → verifying → cleanup → idle**.

- **Due**: on `backup_drill_day` from 05:00 his time (a month whose day was missed runs at the next
  morning tick), or after he approved the `vitals_drill_start` card (at most
  `backup_drill_manual_per_month` a month, counted when he approves; one drill at a time). Any drill
  that starts, or is refused, is the month's drill: no second restore follows it that month.
  Nothing is asked of Google before a schedule has been seen once ("not set up"). A request
  approved before the drill was switched off is dropped (a new approval is needed) and his slot
  comes back.
- **Start** (`drill_start.py`): the newest READY backup with its stats filled and a document count
  over 0 (else "waiting": A2); refused, with a "failed: over_cap" result and nothing restored, when its restore at
  the LIVE rate (`billing.fx`, else `usd_inr_rate`) costs more than `backup_drill_max_inr`; refused
  ("no_key") without a token key. A `jarvis-drill` that is already there is cleaned up first and
  the restore waits at least 6 minutes after a delete (Google: 5), so it starts at the next tick.
  Due but unable to start (no finished backup, or Google refusing: access lost) waits, then after
  2 days is a failed result ("no_backup" / "no_access"), told, the month's drill, and a drill he
  asked for gives his slot back. The INTENT (phase restoring, the month consumed) is saved before
  `restore()`; a refused restore puts the state back, one that fails otherwise ends "failed:
  restore" and the clean-up decides.
- **Restoring**: polled each tick; done without a database: "failed: restore"; no operation saved
  (a tick cut off after the restore began): "failed: interrupted", never a second restore. Google
  refusing any call mid-drill: "failed: no_access".
- **Verifying**: section 1; a check that raises 3 ticks in a row ends it ("failed: unknown").
- **The end**: the result is recorded and told as soon as the checks end (passed → `backup_ok`;
  failed → `backup_problem` "drill_failed" with its reason in fixed words; skipped → nothing).
- **Cleanup** (`drill_end.py`): `get_database("jarvis-drill")` decides; delete protection off
  first; delete; look again. It runs WHATEVER the switches say: idle, the job asks once a day
  whether a copy is there (the day is marked checked only after the look worked; Google refusing
  it is told, "no_access", once a day). A copy still there, or a look that fails, after 2 days is
  told ("copy_left"), then weekly; the clean-up never raises. A run older than 3 days
  fails ("stuck"). Switched off mid-run: "skipped: switched off", no alert.

**Costs** (S2 at ₹95.24; the code uses the live rate): copies 7 × 0.0977 GiB × ₹2.86 ≈ ₹1.95, a
restore 0.0977 GiB × ₹19.05 ≈ ₹1.86, counts and samples ≈ ₹0: **≈ ₹3.8 a month at 100 MB** (₹1.95 +
₹1.86 = ₹3.81; the plan's cost row and card C66's "≈ ₹4.9" are wrong: Needs I1 #6); "about ₹4" where
a round figure is shown (the set-up's line, Vitals' not-set-up note); ≈ ₹39 at 1 GiB ("about ₹40");
a left-over copy ≈ ₹1.4 (100 MB) to ₹14 (1 GiB) a month.

## 3. What he sees

- **Before his one-time step**: Vitals shows only "Backups is not set up" (unknown, quiet: no ring,
  and the brief does not nag), with the step and its cost range ("about ₹4 a month at 100 MB, about
  ₹40 at 1 GB"); `vitals_backups` says the same;
  the drill card answers "Backups aren't set up yet"; Privacy: "Not set up: no copies are kept";
  no backup alert of any kind (both jobs return "not set up", never a failure).
- **After it**: `backups` ok "Last copy 14 Nov, 08:30; Google keeps each copy 7 days. About ₹3.81 a
  month at this size." (amber "has no copy newer than 36 hours", red "has no daily schedule");
  `backup_drill` unknown "hasn't run yet" → ok "Passed on …: N documents counted, N vault items and N
  documents compared, the copy deleted." / amber "is overdue" (that pass is over 40 days old) / red
  "failed: <fixed words>" (a count that didn't match shows both counts) / amber "was skipped: no
  vault to open" / unknown "was skipped: switched off" / amber "can't run: no token key"; a date
  over half a year old carries its year; `db_size` the newest backup's size in MB against 1,024 MB (kind storage: Vitals' own
  amber at 80 %, red at 100 %; the only R14 item that rings from Vitals).
- **Alerts** (only after the set-up has been seen): `backup_problem` subjects `stale`,
  `no_schedule`, `key_changed`, `drill_failed`, `copy_left`, `no_access`; `backup_ok` subject
  `drill`. Fixed texts in `backup/texts.py` (`TEXTS` / `FAILED_TEXT` + `REASON_WORDS`, re-exported
  by `status`): no name, no amount, no vendor text, each at most 300 characters. Once a cause on
  HIS day (UTC midnight is 05:30 in Kolkata, inside the tick); `copy_left` weekly; each drill's
  result once under its own run key (two the same day are two). A send that reached nobody (it
  raised, the storm's cap dropped it, no channel took it) gives its claim back and is tried again
  at a later tick, at most 3 times on his day; where he chose it to go (a kind he switched off,
  the home feed, a hold for the morning summary) counts as told. `key_changed` is kept in the
  status and told daily until a drill passes or 7 days pass (then every copy has the new key).
  The canary job's three steps fail apart: a failing canary or list is counted and the alerts are
  still decided (stale from the stored status).

## 4. The join and the routes

`build(ctx)` (only when `ctx.docs` is set; else `off: no document store`, no tools): tools
`vitals_backups`, `vitals_drill_start`; daily jobs `backup_canary`, `backup_drill`; privacy
`BackupsPrivacy`; one Vitals reader; services `backup_status` (B and Vitals) and `backup` (the desk,
for its routes). The real adapters are made only with `session_backend = firestore` and a
`firestore_project` (production sets `JARVIS_FIRESTORE_PROJECT`); otherwise `ready` = `off: not on
Firestore` and nothing calls Google. `ready` words: `ready`, `ready: no token key, so no canary and
no drill`, `off: not on Firestore`, `off: no document store`. The clock (`helpers_now`), the
notifier and the live rate (`billing.fx`) are read late.

- `GET /v1/backup` → `{part, ready, set_up, schedule, last_copy, copies, size_mb, documents,
  month_inr, drill, drill_at, drill_expected, drill_counted, drill_running, spoken}`; owner-only,
  `no-store`. Off Firestore the drill card says there are no Google backups on this server.
- `POST /v1/backup/drill` `{session_id}` → 202 `{status: "awaiting", approval_id, card, detail}`:
  the same `vitals_drill_start` card through the gateway in his own conversation (`turn_budget`,
  `context_trust(untrusted=False)`); 409 `no_conversation`, 403 `denied` (his row says Never), 429
  past 3 a minute per owner (`app.state.backup_drill_limit`), 422 for a malformed body, 503 tools
  off. It restores nothing: the approved card asks for a drill at the next morning tick.

## 5. `deploy/backup_setup.sh`

- The set-up prints four lines ("about ₹4 a month at 100 MB, about ₹40 at 1 GB…"; "a drill about ₹2
  at 100 MB, never over ₹100…"; "a thing you delete stays in the copies up to 7 days"; "the drill
  uses a throw-away database named jarvis-drill: JARVIS deletes any database by that name") and changes
  NOTHING unless he types exactly `YES` (`IFS= read`: " YES", "yes", "YES please" stop). Then: the
  daily schedule kept 7 days (only if none; one that isn't daily kept 7 days is kept and named:
  "on, but not daily kept 7 days"), delete protection on `(default)`, and the drill's three grants
  for jarvis-run, the clean-up FIRST: the custom role `jarvisDrillCleanup`
  (`datastore.databases.get`, `.getMetadata`, `.update`, `.delete`; created, or its permissions
  reset to exactly these four) bound ONLY with `resource.name=="projects/P/databases/jarvis-drill"`;
  only once it is bound, `roles/datastore.restoreAdmin` and `roles/datastore.backupSchedulesViewer`
  (`--condition=None`), so no restore is granted that couldn't be cleaned up. Never `datastore.owner`.
  The binding is read back (`get-iam-policy --flatten`). The last line is the owner step 5 line:
  "Backups: on, kept 7 days · Delete protection: on · Drill access: on" (any part "could not").
- `--status` (the deploy's only call): reads the schedule (JSON: daily and `retention` 604800 s,
  read with `python3 -I`; without python3 "not confirmed"), the protection (from `--format=json`, so
  no argument names the verb) and the grants; prints three lines, each saying "could not read
  (gcloud error…)" when gcloud itself failed (not "not set up"); always exits 0, also when gcloud
  fails or no project is set. Its function names no create, update, delete or binding.
- Both modes: gcloud never prompts (`CLOUDSDK_CORE_DISABLE_PROMPTS=1`) and never reads his typing
  (stdin `/dev/null`); a project id that isn't one (a leading "-", spaces, capitals) is never
  passed to it ("could not read the project").

## 6. Eval (`evals/r14/backup.py`, BUILT)

`PYTHONPATH=$PWD/src python evals/r14/run.py --mock --part backup` → **14/14 passed; the control
failed the suite**. Cases: drill passes on fakes (and deletes its copy); a missing document fails
the count; a changed key fails; a restamped copy still compares on the app's own fields; a vault
changed since the snapshot never passes vacuously; no live write; `(default)` / live target refused
before any Google call; empty stats never start; a stale backup alerts once; nothing alerts before
the set-up; cleanup whatever the switches; and (v14.0.2) a tick cut off after the restore began
never restores twice; an alert the storm's cap dropped is tried again; lost access to the drill's
copy is told. **Controls**: (1) the writable live store handed to the
verifier → `backup:no_live_write` fails; (2) comparisons keyed on Firestore's `update_time` with
restamped copies → nothing compared, the drill fails → `backup:restamped_copy_still_compares`
fails. The whole R14 runner: 27/27 passed, control failed the suite.

## 7. Needs I1 (files Part A doesn't own; exact diffs, NOT applied or run here)

The Workshop's auto-mode refused even a temporary edit of these files to try the diffs, so they
are written out and reasoned, not run; each is small.

**#1 — the drill card is never part of Approve all** (`src/jarvis/core/guardrails.py`; plan D4,
A3; the security review's HIGH-1, a merge gate). Today `PendingAction.bulk_ok` is True for an R2
card, so Approve all (or an approved spoken or untrusted round) could run it unseen. **Import
`START`, not a literal**: from `jarvis.backup.names` (v14.0.2: a module with no imports of its
own, pinned by `test_the_tool_names_can_be_imported_by_the_guardrails_without_a_cycle`;
importing it from `backup.tools` would be a cycle, as that module imports `core.guardrails`), so
a rename can't silently reopen it. **In the same commit** remove the
`@pytest.mark.xfail(strict=True, …)` decorator from
`tests/test_r14_a_part.py::test_the_drill_card_is_never_part_of_approve_all` (strict: it fails
as XPASS the moment the guard lands, so the two can't drift; the test builds its card from
`START`). `approve_all._one` and the console batch only what `bulk_ok` allows, so this is the one
gate.

```diff
 from pydantic import BaseModel, Field
+
+from jarvis.backup.names import START as DRILL_START  # R14 D4: a leaf module, no import cycle
@@
 MEMORY_TOOL_PREFIX = "memory_"
+# R14 D4 (Part A): each restore drill costs a restore, so he approves each on its own card
+NO_BULK_TOOLS = frozenset({DRILL_START})
@@ class PendingAction(BaseModel):
         if self.irreversible or self.reason is AskReason.DRAFT_RECIPIENT:
             return False
+        if self.tool in NO_BULK_TOOLS:
+            return False
         return not self.tool.startswith(MEMORY_TOOL_PREFIX)
```

**#2 — `vitals_backups` is safe on Telegram** (`tests/test_telegram_tool_guard.py`, `TELEGRAM_SAFE`;
I0 pinned the four R14 tools as open but could not name a tool that didn't exist yet):

```diff
         "research_person",
         "people_open_profiles",
+        # R14 Part A: the backups' own facts (set up or not, the last copy's time, how many,
+        # the size, a rupee estimate, the last drill's result), like vitals_show
+        "vitals_backups",
     }
```

**#3 — I0's seam pins of an unbuilt Part A** (`tests/test_r14_seams.py`):

```diff
@@ async def test_the_app_starts_with_four_parts_and_their_status_routes
-        assert all(p.ready == "not built yet" for p in parts.values())
+        assert parts["backup"].ready == "off: not on Firestore"  # R14 A: dev is MemoryDocs
+        assert all(p.ready == "not built yet" for n, p in parts.items() if n != "backup")
         for name, route in STATUS_ROUTE.items():
             r = await client.get(route)
             assert r.status_code == 200, name
-            assert r.json() == {"part": name, "ready": "not built yet"}
+            assert {"part": name, "ready": parts[name].ready}.items() <= r.json().items()
             assert r.headers["cache-control"] == "no-store"
         r = await client.get(R14_STATUS_ROUTE)
-        assert r.json() == {"parts": {n: "not built yet" for n in PARTS}}
+        assert r.json() == {"parts": {n: parts[n].ready for n in PARTS}}
@@
-        drill = await client.post("/v1/backup/drill", headers={"X-Requested-With": "x"})
-        assert drill.status_code == 501 and drill.json()["error"] == "not_built"
+        drill = await client.post("/v1/backup/drill", json={}, headers={"X-Requested-With": "x"})
+        assert drill.status_code == 409 and drill.json()["error"] == "no_conversation"
@@ async def test_the_parts_privacy_rows_reach_the_dashboard
-        assert wiring.r14_privacy_sources(app) == ()  # no part is built yet
+        assert [s.id for s in wiring.r14_privacy_sources(app)] == ["backups"]  # R14 A
+        assert "backups" in app.state.privacy.registry.ids()
@@ def test_the_r14_runner_passes_and_its_contract_control_fails_it
-    for part in ("backup", "selfwatch", "offer", "noai", "needles"):
+    for part in ("selfwatch", "offer", "noai", "needles"):
         assert f"{part}:not_built_yet" in ids, part
+    assert "backup:drill_passes_on_fakes" in ids  # R14 A: built, with its control
     control = report["negative_control"]
     assert control["suite_failed"] is True and control["failed_cases"]["contract"]
+    assert control["failed_cases"]["backup"]
```

(I1 merges these with Parts B, C and D's own lines: the privacy list then holds every part's rows.)

**#4 — the tick-list pins** gain Part A's two morning jobs, last on the tick (`api/tick_wiring.py`
puts `r14_tick_jobs` last; Part B's `selfwatch_daily` follows them at the merge):

```diff
--- tests/test_r2_wiring.py  (test_without_the_token_key_everything_is_off_with_plain_words)
         "mobile_clock",  # R7's own two (I1 fixer), after R11's
         "mobile_daily",
+        "backup_canary",  # R14 Part A's two, last
+        "backup_drill",
     ]
--- tests/test_r2_wiring.py  (test_tick_jobs_have_unique_names_none_of_the_ticks_own)
     r11 = ["helpers_clock", "helpers_daily", "mobile_clock", "mobile_daily"]  # R11 I0; R7's own
-    assert names == [*r2, "vitals_poll", "health_check", "book_seal", "book_sweep", *r11]
+    r14 = ["backup_canary", "backup_drill"]  # R14 Part A
+    assert names == [*r2, "vitals_poll", "health_check", "book_seal", "book_sweep", *r11, *r14]
--- tests/test_r4_wiring.py
 R11_JOBS = ("helpers_clock", "helpers_daily", "mobile_clock", "mobile_daily")
+R11_JOBS += ("backup_canary", "backup_drill")  # R14 Part A's two, last on the tick
--- tests/test_r11_wiring.py
-        assert names[-4:] == ["helpers_clock", "helpers_daily", "mobile_clock", "mobile_daily"]
+        assert names[-6:-2] == ["helpers_clock", "helpers_daily", "mobile_clock", "mobile_daily"]
+        assert names[-2:] == ["backup_canary", "backup_drill"]  # R14 Part A's two, last
--- tests/test_r51_wiring.py  (test_without_a_home_the_health_job_rides_the_tick_only)
             "mobile_clock",  # R7's own two, after R11's
             "mobile_daily",
+            "backup_canary",  # R14 Part A's two, last
+            "backup_drill",
         ]
```

**#5 — recommended, not required**: `src/jarvis/core/finish.py` `SAID_BY_CODE` gains
`"vitals_drill_start"`, so the reply to his approved card is JARVIS's own fixed line ("Done, Sir: the
restore drill starts…", the monthly limit, "not set up", and since v14.0.2 off Firestore "This
server doesn't keep JARVIS's data in Google's Firestore…"; each under 400 characters), also with
the AI off.

**#6 — the guide, the plan and the persona (D14, D15)**: card C66 from PLANNED to built (its "Where
in the code" is section 1's list; "Cost" **≈ ₹3.8** at 100 MB, not ₹4.9 (nor the ₹3.9 v14.0.1
said); "Data it keeps" unchanged), §8's "Backups" paragraph replaced by section 8 below, and
persona p14.0's BACKUP line (D14). **The plan's own cost row** (`docs/plans/r14-hardening.md`,
"Per item", row "A Backups + drill", the last cell, line 554 at v14.0.2):

```diff
-| ≈ ₹4.9 at 100 MB (backups 7 × 0.1 GiB × ₹2.86 = ₹2.0; a restore ₹1.9; counts ≈ ₹0; samples ≈ ₹0); ≈ ₹39 at 1 GiB (₹20.0 + ₹19.05); a left-over copy ₹1.4 (100 MB) to ₹14 (1 GiB) a month |
+| ≈ ₹3.8 at 100 MB (backups 7 × 0.0977 GiB × ₹2.86 = ₹1.95; a restore ₹1.86; counts ≈ ₹0; samples ≈ ₹0; "about ₹4" where a round figure is shown); ≈ ₹39 at 1 GiB (₹20.0 + ₹19.05); a left-over copy ₹1.4 (100 MB) to ₹14 (1 GiB) a month |
```

**#7 — found, I0's (not Part A's)**: `tests/test_claude_guard.py` fails 9 cases in this worktree
(`rm -rf src`, `rm -rf tests`, `rm -rf .git`, `rm -r -f docs`, …): the test runs the hook with
`cwd` = the checkout, and a relative target inside `/home/claude/wt/<x>/` is under the hook's
allowed `/home/claude/wt/` prefix, so it is NOT blocked. The same is true in a real session: inside
a worktree the hook would let `rm -rf src` through. Unchanged by Part A (no `.claude` file or that
test touched). I1 (or a later I0 fix): refuse the checkout's own top-level `src`, `tests`, `.git`,
`docs`, `evals` even under an allowed prefix, and run the test from a neutral cwd.

**#8 — new in v14.0.2, the plan's honest limits (security review LOW-2)**: a line for
`docs/plans/r14-hardening.md`'s risks: "`roles/datastore.restoreAdmin` is project-wide and
unconditioned: jarvis-run may restore any backup into any NEW database id (a cost, never an
overwrite: a restore can't target a database that exists). jarvis-run already has
`roles/datastore.user` on the live database, so the live database's safety rests on the code locks
(D4's five), not on IAM." No code change: a condition on the restore grant would have to name the
database the restore creates, which nobody here can try against Google.

## 8. The guide's runbook text (for §8 "Operations", D4 "Restoring for real")

> **Backups.** After the owner's one-time step (`bash deploy/backup_setup.sh` in Cloud Shell, which
> shows the cost and waits for YES), Firestore copies the whole database every day and keeps each
> copy 7 days, and the live database has delete protection on. Once a month JARVIS restores the
> newest copy into a throw-away database `jarvis-drill`, checks it, and deletes it (card C66).
> `bash deploy/backup_setup.sh --status` shows what is on; it only reads. A deleted item leaves the
> live database at once and the copies within 7 days. Not in the copies: the laptop's pictures and
> face library, Secret Manager (Google keeps its versions), his Google account data. The copies
> and `jarvis-token-key` share one project: the drill proves recovery from a bad write or delete,
> not from losing the project or the key.
>
> **Restoring for real** (only with the Workshop on the line; nothing here is automatic):
> 1. In Cloud Shell, list the copies: `gcloud firestore backups list --format="table(name,snapshotTime,state)"`.
>    Pick the newest copy from BEFORE the mistake.
> 2. Restore it into a NEW database id, never `jarvis-drill` (the drill deletes that id) and never
>    one in use: `gcloud firestore databases restore --source-backup=<the copy's name>
>    --destination-database=jarvis-restored`. It takes minutes; check with
>    `gcloud firestore operations list --database=jarvis-restored`.
> 3. Either point JARVIS at it (Cloud Run variable `JARVIS_FIRESTORE_DATABASE=jarvis-restored`; JARVIS
>    refuses to start if it is `jarvis-drill`), noting that a named database has no free quota
>    (≈ ₹14 a month per GiB stored); or, to keep the free quota, restore into `(default)` itself:
>    turn its delete protection off (`gcloud firestore databases update --database='(default)'
>    --no-delete-protection`), delete it, wait 5 minutes (an id is reusable only then), restore with
>    `--destination-database='(default)'`, and turn delete protection on again.
> 4. After any real restore, clear the drill's state document (`jarvis_backup_drill/current`): the
>    copy carries the state it had at the snapshot. The next morning tick starts clean.
> 5. Things deleted after the snapshot come back, and things made after it are gone: say so to him,
>    and delete again what he had deleted (the Privacy panel lists them).

## 9. For the other parts

- **Part B** reads the backups only through `ctx.backup_status()` → `BackupFacts`: `set_up` (a
  schedule seen once), `schedule_seen_at`, `newest_at` (newest READY copy), `size_bytes` /
  `document_count` (newest copy with stats), `drill` ("passed" | "failed: <code>" | "skipped: no
  vault" | "skipped: switched off" | None), `drill_at`. B raises neither backup kind. v14.0.2
  adds the reason codes `no_access`, `no_backup`, `interrupted` and `too_few_compared` (a
  "failed: <code>" like the others) and the `backup_problem` subject `no_access`.
- **Part C**: `vitals_backups` and `vitals_drill_start` are Code & DevOps (D11's register; agent
  `vitals`).
- **Part D**: "when was my last backup" → `vitals_backups` (R1; its result's `spoken` is the fixed
  sentence to say); "test my backup" → `vitals_drill_start` (always a card; the approved card's
  result is `{"message": <fixed line>}`). `deploy/cloudrun.sh` should call
  `bash deploy/backup_setup.sh --status || true` (it needs `gcloud config` to name the project, as
  the deploy already does).

## 10. What could not be verified here (the shell can't reach Google)

Every Google call. In particular: the admin API's shapes (backups listed under `locations/-`,
`Backup.stats` reading 0 while empty: Part A treats 0 as "not filled"); the restore operation's name
(assumed under `databases/jarvis-drill/operations/`; a name with no database segment is polled
unchecked, it can't act on a database); that a `count()` over a collection group with no filter
needs no composite index; that `Backup.stats.document_count` counts sub-collection documents and
not "missing" parent documents, which the exact count check assumes (if Google counts otherwise the
first live drill fails closed with `count_mismatch`, and the Workshop sees it); what a restore
inherits (delete protection is turned off if present); whether the conditioned custom role is
honoured for delete (fails closed: "copy_left"); the gcloud flags of the set-up
(`backups schedules create --recurrence=daily --retention=7d`, `databases update
--delete-protection`, `iam roles create/update`, `add-iam-policy-binding --condition`); the real
size, time and rupees of a restore; the Workshop's I1-side tests of section 7. New in v14.0.2:
the JSON gcloud prints for a backup schedule (a daily one assumed to carry a `dailyRecurrence`
key and `"retention": "604800s"`; if it prints otherwise the set-up and `--status` say "on, but
not daily kept 7 days", which fails toward telling the Workshop); `python3` on Cloud Shell's
PATH (without it: the same words); that the admin SDK's async calls stop cleanly when
`asyncio.timeout` cancels them; that a restore whose reply was lost may have begun on Google's
side (assumed: the drill then ends "interrupted" and its clean-up deletes the copy).

## 11. Risks and choices to watch

- **The first month**: the scheduled drill is due from the drill day, so the first one runs the
  first morning after the set-up whose newest copy has its stats (≈ ₹2): it proves the set-up early;
  then monthly.
- **Samples that change without their own time field** (a counter kept in a document with an
  `at` field) would fail "sample_mismatch": `created_at` is deliberately not a time field; watch the
  first live drills.
- **Owners**: the vault probe and the activity days use the tick's owners (the brief's); another
  user's activity days would fail the count closed.
- **Writes to `(default)` rest on code alone** (plan risk): the read-only view on the live side,
  the adapters' id check before any call, the import test, `Settings`' start-up lock, and the
  adapter's own refusal to run with `jarvis-drill` as the live id.
- **Reviews**: four fresh-context reviews (python, silent-failure, code, security) were run by
  the Workshop on v14.0.1; their follow-ups are section 13. A fresh look at the v14.0.2 diff
  (`3d9bd49..` this branch) by the same reviewers is for I1.
- **New in v14.0.2**: "too_few_compared" needs 3 documents compared outside the canaries; a nearly
  empty database fails closed and is told. `key_changed` is told daily for up to 7 days. With no
  channel at all (no Telegram, no push) a lasting cause is tried 3 times a morning, so the home
  feed can list it 3 times. Every tick save is a transaction (one read more a save, ≈ ₹0). The
  no-access alert after the set-up says "run the set-up again" also while the Workshop hasn't
  finished the drill's grants (it is true then too).

## 12. Checks (run in the worktree, 14 Nov 2026, v14.0.2)

| Check | Result |
|---|---|
| `pytest tests/test_r14_a_*.py`, Python 3.12 and 3.11 | 177 passed, 1 xfailed (strict, I1 #1) on each |
| Coverage of Part A's modules (its own tests) | 96 % (1,667 statements) |
| Seam set (`test_r14_seams`, `test_r14_wiring`, `test_claude_guard`, `test_arch_coverage`, `test_telegram_tool_guard`) | 265 passed, 13 failed, the same 13 as v14.0.1: 3 seam pins of an unbuilt Part A (I1 #3), 1 Telegram list (I1 #2), 9 hook cases that fail in any worktree (I1 #7) |
| Other existing tests that list the tick jobs | `test_r2_wiring` (2), `test_r4_wiring` (3), `test_r11_wiring` (1), `test_r51_wiring` (1) fail on the two new job names (I1 #4), unchanged; 57 pass |
| `ruff check` and `ruff format --check` (src tests evals scripts) | clean |
| `mypy src` | the 9 baseline errors only |
| `mypy --strict` on A's tests, fakes and eval (`MYPYPATH=src:tests`) | clean (the 9 src baseline errors only) |
| `evals/r14/run.py --mock --part backup` | 14/14, control failed the suite; the whole runner 27/27, control failed the suite |
| `scripts/arch_coverage.py`, `scripts/check_doc_versions.py` | OK (65 packages/modules, 103 collections), all 28 documents versioned |
| `bash -n deploy/backup_setup.sh` | clean |

## 13. Review follow-ups (v14.0.2)

The four fresh-context reviews of v14.0.1 (`3d9bd49`): python (BLOCK), silent-failure (WARN), code
(WARN), security (WARN). Every HIGH and MEDIUM is fixed but security HIGH-1 (I1's file); the cheap,
safe LOWs are fixed; where reviews overlap the fix is one. Each test below was written first and
seen failing (assertions, not imports) before the fix; files are `tests/test_r14_a_<file>.py`.

| Finding | Outcome | Test |
|---|---|---|
| Python H1: "once a day" on the UTC date (twice a morning) | Fixed: claims on his day (owner's zone) | `status::test_once_a_day_is_his_day_not_utcs`, `part::test_the_part_counts_days_and_months_on_his_clock` |
| Python H2 = code M3: the result keyed by the UTC month | Fixed: his month | `status::test_a_drill_result_is_kept_under_his_month_not_utcs`, `drill::test_a_refusal_at_five_on_the_first_is_his_new_months_result` |
| Python M1 = security M2 (part): a crash between `restore()` and the save restores twice | Fixed: the intent saved first; no operation → "interrupted"; a raising restore → "restore" | `drill::test_a_tick_cut_off_after_the_restore_began_never_restores_twice`, `drill::test_a_restore_that_raises_is_a_failed_restore_and_never_repeats`; eval `cut_off_tick_never_restores_twice` |
| Python M2 = code M1 = silent H3 = security LOW-5: `PermissionError` escaping, read as idle, clean-up unguarded | Fixed: "no_access" (told idle, a failed result mid-drill, a wait at the start); the clean-up never raises and tells "copy_left" | `drill::test_access_taken_away_after_the_set_up_is_told_never_a_job_failure`, `…_lost_while_idle_is_told_once_a_day_and_looked_for_again`, `…_lost_mid_drill_ends_it_and_a_copy_left_is_told`, `drill::test_a_clean_up_whose_look_fails_still_tells_the_copy_left`; eval `lost_access_is_told` |
| Python M3: no per-call deadline | Fixed: `firestore_admin.bounded` on every call of both adapters (20 s or the tick's time left less 2 s, ≥ 1 s); the protection wait 15 s | `locks::test_a_call_gets_its_own_deadline_or_what_the_tick_has_left`, `…_google_admin_call_that_hangs_is_cut_off`, `…_drill_reader_cuts_off_a_hang_and_says_no_permission_plainly` |
| Python M4: `refresh` overwrites a claim made meanwhile | Fixed: a transaction | `status::test_a_refresh_never_erases_a_claim_made_meanwhile` |
| Python M5 = silent L1: `checked_on` saved before the look | Fixed: after it | `drill::test_a_failed_look_for_a_left_over_copy_is_tried_again_the_same_day` |
| Python L1: mypy --strict errors in A's tests and eval | Fixed: clean with `MYPYPATH=src:tests` | the strict run (section 12) |
| Python L2: `tests/r14_fakes_a.py` 420 lines | Fixed: split, 285 + 163 (`r14_fakes_a_sdk.py`) | the whole suite |
| Python L3: naive `datetime.min` sort keys | Fixed (unreachable: a refactor guarded by the newest-backup tests) | `status::test_the_status_keeps_the_newest_ready_backup…`, `drill::test_empty_stats_never_start_a_drill` |
| Python L4: dicts inside frozen models | Fixed statically: `Mapping` types (mypy refuses a mutation). Runtime freezing declined: Pydantic can't serialize a read-only proxy and `model_copy` skips validators | mypy |
| Python L5: `type: ignore` on `Signal`; `_start` at 49 lines | Fixed: `AlertKind`; the start split (every function < 50 lines) | mypy |
| Python L6: canary day UTC, other days local | Fixed: every day key on his day | `status::test_the_canary_day_is_his_day_not_utcs` |
| Silent H1: the Teller ignores `Delivery`; a lost send burns the claim | Fixed: a send that reached nobody gives its claim back, tried again (3 a day); his own choices count as told | `status::test_an_alert_that_reached_nobody_gives_its_claim_back` (3), `…_send_that_keeps_failing_is_tried_three_times_a_day`, `…_where_he_chose_it_to_go_counts_as_told` (4); eval `lost_alert_is_tried_again` |
| Silent H2: one try for canary, list and alerts | Fixed: three apart; stale from the stored status | `jobs::test_a_failing_canary_still_lets_the_alerts_run`, `jobs::test_a_failing_list_still_tells_stale_from_the_stored_status` |
| Silent H4: a drill that never starts is invisible; a manual slot used | Fixed: 2 days, then a failed result ("no_backup" / "no_access"), told, the slot given back | `drill::test_a_restore_refused_waits_then_fails_and_gives_his_slot_back`, `drill::test_a_drill_with_no_finished_backup_fails_after_two_days` |
| Silent M1: "passed" green for ever | Fixed: amber "is overdue" past 40 days; the year past half a year | `part::test_a_pass_older_than_forty_days_is_overdue_and_an_old_one_has_its_year` |
| Silent M2: `key_changed` lost after one dropped alert | Fixed: kept in the status, daily until a drill passes or 7 days | `jobs::test_a_changed_key_is_told_each_day_until_a_drill_passes`, `jobs::test_a_key_change_is_told_until_every_copy_has_the_new_key`, `drill::test_a_passing_drill_settles_a_key_change` |
| Silent M3: a pass on one sample; vault items missing at the same version | Fixed: ≥ 3 compared (canaries left to their own check); the same items at the same version. Opening only one file: declined, plan D4's decision | `verify::test_a_pass_never_rests_on_too_few_compared_documents`, `verify::test_an_item_lost_from_the_copy_at_the_same_version_fails` |
| Silent M4: any schedule read as "on, kept 7 days" | Fixed: daily kept 7 days or "on, but not daily kept 7 days" (his schedule kept) | `setup::test_a_schedule_that_is_not_daily_for_7_days_is_never_called_on`, `setup::test_a_schedule_already_there_is_kept` |
| Silent M5: an unreadable status silences every alert | Fixed: each readable field is kept (set up stays set up). An extra "status unreadable" alert: not added, the salvage keeps the alerts and the error is logged | `status::test_an_unreadable_field_keeps_the_rest_of_the_status` |
| Silent L2: no key, nothing said until the drill day | Fixed: Vitals amber "can't run: no token key". A canary write failure stays a failed count (Part B's streak), by design | `part::test_without_a_key_vitals_says_the_drill_cannot_run` |
| Silent L3: gcloud errors read as "not set up" | Fixed: "could not read (gcloud error…)" per line. Exit 1 on "could not": declined, the set-up is run and read by hand and D3 says the rest go on | `setup::test_status_says_when_gcloud_itself_failed` |
| Silent L4: a failing live rate is silent | Fixed: logged | `part::test_a_live_rate_that_fails_falls_back_to_the_setting_and_says_so` |
| Silent L5: one `drill_failed` claim a day; the off-Firestore card | Fixed: each drill's result once under its run key; the card says there are no Google backups here | `status::test_each_drill_result_is_told_once_even_two_the_same_day`, `part::test_off_firestore_the_drill_card_says_why_not_set_up` |
| Code M2: "switched off" shown as "no vault" | Fixed | `part::test_a_drill_skipped_because_it_was_switched_off_says_so` |
| Code L1: `count_mismatch` without its numbers | Fixed: Vitals and `GET /v1/backup` | `part::test_a_count_mismatch_shows_both_counts` |
| Code L2: ₹3.8 / ₹3.9 | Fixed in A's files: ₹3.8; "about ₹4" in the set-up's line and Vitals' note; the plan's ₹4.9 row is Needs I1 #6 | `part::test_the_set_up_note_says_about_four_rupees_at_100_mb`, `setup::test_nothing_changes_without_a_typed_yes` |
| Code L3: a request approved, then switched off, fires later | Fixed: dropped, the slot given back | `drill::test_a_request_approved_before_the_drill_was_switched_off_needs_a_new_one` |
| Code L4 = security M2 (part): non-transactional tick saves | Fixed: transactions that keep his request | `drill::test_a_request_he_makes_during_a_tick_is_kept` |
| Security HIGH-1: Approve all can run the drill card | Not A's (`core/guardrails.py` is I1's): the strict xfail stays; Needs I1 #1 now imports `START` (from the new leaf `backup/names.py`) and removes the xfail in the same commit | `part::test_the_tool_names_can_be_imported_by_the_guardrails_without_a_cycle`; `part::test_the_drill_card_is_never_part_of_approve_all` (xfail) |
| Security M1: the restore grant before the clean-up grant | Fixed: the clean-up first; no restore granted without it. A start-time `testIamPermissions`: not added (the order closes it at the set-up; a later loss is "no_access") | `setup::test_the_clean_up_grant_comes_before_the_restore_grant`, `setup::test_without_the_clean_up_grant_no_restore_is_granted` |
| Security M2: the intent before `restore()`; `jarvis-drill` reserved | Fixed (above); the name is said in the set-up's lines and the Privacy row | `setup::test_nothing_changes_without_a_typed_yes`, `part::test_the_backups_privacy_row` |
| Security LOW-1: gcloud prompts | Fixed: `CLOUDSDK_CORE_DISABLE_PROMPTS=1`, stdin `/dev/null` | `setup::test_status_never_lets_gcloud_prompt_or_read_what_he_types` |
| Security LOW-2: `restoreAdmin` project-wide | Documented: section 11 and Needs I1 #8 (the plan's honest limits); no code change | none |
| Security LOW-3: the project id positional | Fixed: an id that isn't one is never passed | `setup::test_an_odd_project_id_is_never_passed_to_gcloud` (4) |
| Security LOW-4: an unreadable drill state allows a second drill | Fixed: fails closed | `drill::test_an_unreadable_drill_state_never_starts_a_second_restore` |
| Security LOW-5 (limiter): in memory per process | No change: one owner, and the global middleware also limits (the review says fine) | none |

## Change log

| Version | Date | Release | What changed | By |
|---|---|---|---|---|
| v14.0.1 | 14 Nov 2026, 17:05 IST | R14 | First edition: Part A built (the locks, the canary, the status, the log, the checks, the drill's state machine, the jobs, the tools, Vitals, Privacy, the join, the routes, the set-up script, the eval with its two controls), what he sees, the costs (₹3.9, not ₹4.9, at 100 MB), Needs I1 with exact diffs, the runbook text, what could not be verified, risks and the checks | 🛠 Mark XIX |
| v14.0.2 | 14 Nov 2026, 17:50 IST | R14 | The fixer's follow-ups of the four reviews (section 13): days and months on his clock; a lost alert gives its claim back (3 tries a day), each drill's result once; the canary job's steps apart, the key change kept; transactional status and drill saves, an unreadable status salvaged and an unreadable drill state failing closed; "no_access" told everywhere, a 2-day deadline for a drill that can't start (the slot given back), the intent before the restore ("interrupted", never twice); a deadline on every Google call; ≥ 3 samples and equal vault items; Vitals ages a pass, says switched off, shows both counts, no key; the set-up grants the clean-up first, checks daily/7 days, tells gcloud errors, never prompts, checks the project id, names `jarvis-drill`; ₹3.8 / "about ₹4"; the fakes split, A's tests and eval strict-typed; `backup/names.py` for I1 #1 (import `START`, the xfail removed in the same commit); Needs I1 #6 gains the plan's ₹4.9 row, #8 the honest-limits line; 177 tests, 96 %, eval 14/14 | 🛠 Mark XIX |
