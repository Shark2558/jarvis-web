Version v14.0.1 · 14 Nov 2026, 17:05 IST · Release R14 · Status: Current · Owner: 🛠 Mark XIX

# R14 Part A — backups and the restore drill (integration notes for I1)

Built by builder A for the Workshop (🛠 Mark XIX) on branch `r14-a`, from `origin/r14-i0` @
`9eb9d8b`, against the plan `docs/plans/r14-hardening.md` v14.0.2 (D3, D4, D5's backup rows, the
data model, "Part split" A), `BRIEF-COMMON.md`, `I0-NOTES.md` and `PLAN-REVIEW-1.md` (A2–A5, A8).
Every file written is in Part A's row; no wiring file, contract file or other part's file was
edited. Tests were written first and seen failing before each module (`tdd-guide`).

## 1. What Part A built

| Deliverable | Files | What it does |
|---|---|---|
| The read-only view (lock 1) | `backup/readonly.py` | `read_only(docs)`: `get` and `query` only; no `write`, `transaction`, `close` or `__dict__`; not a `Docs`; fixed slots. The verifier holds it for the live side |
| The admin adapter (lock 2) | `storage/firestore_admin.py` | `BackupAdmin` on `FirestoreAdminAsyncClient` (async, lazy import). Every call passes `drill_target` first: the four that name a database (restore's target, get, update, delete) pass that id; the three that name none (list backups, list schedules, poll an operation) pass the drill id against the live one, so it refuses to run at all when the live database is `jarvis-drill`. An operation naming a database must name the drill copy; only this project's backups are restored. Google's `PermissionDenied` / `Forbidden` become a plain `PermissionError` with fixed words; a gone database reads as None |
| The drill-side reader (lock 2) | `storage/firestore_walk.py` | `DrillWalk` + `ReadOnlyDocs` on `jarvis-drill` only: checked when made and again before every call; collection ids, `count()` per collection group, samples, get, query; no writer |
| The canary | `backup/canary.py` | `{prefix}backup_canary/{yyyymmdd}` = SHA-256 of a random 32-byte nonce, the nonce sealed with `backup_probe` (AAD `backup_canary/{day}/v1`), the key's fingerprint (first 16 hex of `mac("backup_probe", "fingerprint/v1")`), the version, the time; once a day, kept 30 days; "the key changed" = the newest earlier canary doesn't open with today's key |
| The status | `backup/status.py` | `BackupStatusService` (the service `backup_status`, `backup.ports.BackupStatus`): `{prefix}backup_status/current` (schedule now, schedule FIRST seen = the set-up has run, the newest READY backup, the newest with its stats filled: size and count, the copies, when each cause was last told); the rupee costs at the live rate; `Teller`: `backup_problem` / `backup_ok` through the notifier, fixed templates, the claim written before the send, once a cause a day, the left-over copy weekly |
| The drill's log (lock 3) | `backup/log.py` | The ONE writer of `{prefix}backup_drill/current` (state) and `{prefix}backup_drills/{yyyymm}` (the month's latest result, 13 months) |
| The checks (locks 1, 3) | `backup/verify.py`, `backup/walk_checks.py`, `backup/vault_probe.py` | D4's four checks, one unit at a time within `ticks.time_left()` (8 s reserve), resumable: the canary (within 26 h before the snapshot, equal to live, opens with the live key); each owner's vault through the vault store's own read path, compared on `rev` / `updated_at` and each item's own `updated_at`, one file opened whole and hashed in memory against the vault's recorded SHA-256 and size; `count()` per collection group (the root ids, the stores' pinned sub-collections, each owner's activity days from the copy's own index) equal to Google's document count exactly; up to 20 samples a collection on their own time field. First failure ends the checks; nothing compared fails; no vault is "skipped", never a pass. Firestore's reserved `__x__` names never enter a hash. They import neither `storage.firestore_docs` nor `backup.log` (an import test) |
| The state machine | `backup/drill.py` | See section 2 |
| The jobs | `backup/jobs.py` | `backup_canary` (budget 30 s) and `backup_drill` (budget 60 s), morning tick only |
| The tools | `backup/tools.py` | `vitals_backups` (R1, agent `vitals`) and `vitals_drill_start` (R2, `ask_when` always, fixed card text), and `BackupDesk` (what the tools and routes share) |
| Vitals | `backup/vitals.py` | `backups`, `backup_drill`, `db_size` (section 3) |
| Privacy | `backup/privacy.py` | The "Backups (Google's copies)" row, section "Settings and safety", delete `none`, no export |
| The join | `backup/part.py` | `build(ctx)` / `build_with(ctx, admin=, walk=, keys=, clock=)` (section 4) |
| The routes | `api/backup.py` | `GET /v1/backup`, `POST /v1/backup/drill` (section 4) |
| The set-up | `deploy/backup_setup.sh` | Section 5 |
| Tests | `tests/test_r14_a_{locks,status,verify,drill,jobs,part,setup}.py`, `tests/r14_fakes_a.py` | 124 passed + 1 strict xfail (I1 #1) on 3.12 and 3.11; Part A's modules at 95 % statement coverage |
| Eval | `evals/r14/backup.py` (`BUILT = True`) | 11 cases, two negative controls (section 6) |

## 2. The drill, one morning tick at a time

`{prefix}backup_drill/current` holds the phase: **idle → restoring → verifying → cleanup → idle**.

- **Due**: on `backup_drill_day` from 05:00 his time (a month whose day was missed runs at the next
  morning tick), or after he approved the `vitals_drill_start` card (at most
  `backup_drill_manual_per_month` a month, counted when he approves; one drill at a time). Any drill
  that starts, or is refused, is the month's drill: no second restore follows it that month.
  Nothing is asked of Google before a schedule has been seen once ("not set up").
- **Start**: the newest READY backup with its stats filled and a document count over 0 (else
  "waiting": A2); refused, with a "failed: over_cap" result and nothing restored, when its restore at
  the LIVE rate (`billing.fx`, else `usd_inr_rate`) costs more than `backup_drill_max_inr`; refused
  ("no_key") without a token key. A `jarvis-drill` that is already there is cleaned up first and
  the restore waits at least 6 minutes after a delete (Google: 5), so it starts at the next tick.
- **Restoring**: polled each tick; done without a database: "failed: restore".
- **Verifying**: section 1; a check that raises 3 ticks in a row ends it ("failed: unknown").
- **The end**: the result is recorded and told as soon as the checks end (passed → `backup_ok`;
  failed → `backup_problem` "drill_failed" with its reason in fixed words; skipped → nothing).
- **Cleanup**: `get_database("jarvis-drill")` decides; delete protection off first; delete; look
  again. It runs WHATEVER the switches say: idle, the job asks once a day whether a copy is there.
  A copy still there after 2 days is told ("copy_left"), then weekly. A run older than 3 days
  fails ("stuck"). Switched off mid-run: "skipped: switched off", no alert.

**Costs** (S2 at ₹95.24; the code uses the live rate): copies 7 × 0.0977 GiB × ₹2.86 ≈ ₹1.95, a
restore 0.0977 GiB × ₹19.05 ≈ ₹1.86, counts and samples ≈ ₹0: **≈ ₹3.8 a month at 100 MB** (the plan's
and card C66's "≈ ₹4.9" is ₹2.0 + ₹1.9 added up wrongly: it is ₹3.9; the owner-facing "about ₹5"
stays a safe round figure); ≈ ₹39 at 1 GiB; a left-over copy ≈ ₹1.4 (100 MB) to ₹14 (1 GiB) a month.

## 3. What he sees

- **Before his one-time step**: Vitals shows only "Backups is not set up" (unknown, quiet: no ring,
  and the brief does not nag), with the step and its cost range; `vitals_backups` says the same;
  the drill card answers "Backups aren't set up yet"; Privacy: "Not set up: no copies are kept";
  no backup alert of any kind (both jobs return "not set up", never a failure).
- **After it**: `backups` ok "Last copy 14 Nov, 08:30; Google keeps each copy 7 days. About ₹3.81 a
  month at this size." (amber "has no copy newer than 36 hours", red "has no daily schedule");
  `backup_drill` unknown "hasn't run yet" → ok "Passed on …: N documents counted, N vault items and N
  documents compared, the copy deleted." / red "failed: <fixed words>" / amber "was skipped: no vault
  to open"; `db_size` the newest backup's size in MB against 1,024 MB (kind storage: Vitals' own
  amber at 80 %, red at 100 %; the only R14 item that rings from Vitals).
- **Alerts** (only after the set-up has been seen): `backup_problem` subjects `stale`,
  `no_schedule`, `key_changed`, `drill_failed`, `copy_left`; `backup_ok` subject `drill`. Fixed
  texts in `status.TEXTS` / `FAILED_TEXT` + `REASON_WORDS`: no name, no amount, no vendor text.

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
  month_inr, drill, drill_at, drill_running, spoken}`; owner-only, `no-store`.
- `POST /v1/backup/drill` `{session_id}` → 202 `{status: "awaiting", approval_id, card, detail}`:
  the same `vitals_drill_start` card through the gateway in his own conversation (`turn_budget`,
  `context_trust(untrusted=False)`); 409 `no_conversation`, 403 `denied` (his row says Never), 429
  past 3 a minute per owner (`app.state.backup_drill_limit`), 422 for a malformed body, 503 tools
  off. It restores nothing: the approved card asks for a drill at the next morning tick.

## 5. `deploy/backup_setup.sh`

- The set-up prints three lines ("about ₹5 a month at 100 MB, about ₹40 at 1 GB…"; "a drill about ₹2
  at 100 MB, never over ₹100…"; "a thing you delete stays in the copies up to 7 days") and changes
  NOTHING unless he types exactly `YES` (`IFS= read`: " YES", "yes", "YES please" stop). Then: the
  daily schedule kept 7 days (only if none), delete protection on `(default)`, and the drill's three
  grants for jarvis-run: `roles/datastore.restoreAdmin` and `roles/datastore.backupSchedulesViewer`
  (`--condition=None`), and the custom role `jarvisDrillCleanup` (`datastore.databases.get`,
  `.getMetadata`, `.update`, `.delete`; created, or its permissions reset to exactly these four)
  bound ONLY with `resource.name=="projects/P/databases/jarvis-drill"`. Never `datastore.owner`.
  The binding is read back (`get-iam-policy --flatten`). The last line is the owner step 5 line:
  "Backups: on, kept 7 days · Delete protection: on · Drill access: on" (any part "could not").
- `--status` (the deploy's only call): reads the schedule, the protection (from `--format=json`,
  so no argument names the verb) and the grants; prints three lines; always exits 0, also when
  gcloud fails or no project is set. Its function names no create, update, delete or binding.

## 6. Eval (`evals/r14/backup.py`, BUILT)

`PYTHONPATH=$PWD/src python evals/r14/run.py --mock --part backup` → **11/11 passed; the control
failed the suite**. Cases: drill passes on fakes (and deletes its copy); a missing document fails
the count; a changed key fails; a restamped copy still compares on the app's own fields; a vault
changed since the snapshot never passes vacuously; no live write; `(default)` / live target refused
before any Google call; empty stats never start; a stale backup alerts once; nothing alerts before
the set-up; cleanup whatever the switches. **Controls**: (1) the writable live store handed to the
verifier → `backup:no_live_write` fails; (2) comparisons keyed on Firestore's `update_time` with
restamped copies → nothing compared, the drill fails → `backup:restamped_copy_still_compares`
fails. The whole R14 runner: 24/24 passed, control failed the suite.

## 7. Needs I1 (files Part A doesn't own; exact diffs, NOT applied or run here)

The Workshop's auto-mode refused even a temporary edit of these files to try the diffs, so they
are written out and reasoned, not run; each is small.

**#1 — the drill card is never part of Approve all** (`src/jarvis/core/guardrails.py`; plan D4,
A3). Today `PendingAction.bulk_ok` is True for an R2 card, so Approve all could run it. Then remove
the `@pytest.mark.xfail(strict=True, …)` decorator from
`tests/test_r14_a_part.py::test_the_drill_card_is_never_part_of_approve_all` (strict: it errors
the moment the guard lands, so it can't be forgotten).

```diff
 MEMORY_TOOL_PREFIX = "memory_"
+# R14 D4 (Part A): each restore drill costs a restore, so he approves each on its own card
+NO_BULK_TOOLS = frozenset({"vitals_drill_start"})
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
restore drill starts…", the monthly limit, "not set up"), also with the AI off.

**#6 — the guide and the persona (D14, D15)**: card C66 from PLANNED to built (its "Where in the
code" is section 1's list; "Cost" ≈ ₹3.9 at 100 MB, not ₹4.9; "Data it keeps" unchanged), §8's
"Backups" paragraph replaced by section 8 below, and persona p14.0's BACKUP line (D14).

**#7 — found, I0's (not Part A's)**: `tests/test_claude_guard.py` fails 9 cases in this worktree
(`rm -rf src`, `rm -rf tests`, `rm -rf .git`, `rm -r -f docs`, …): the test runs the hook with
`cwd` = the checkout, and a relative target inside `/home/claude/wt/<x>/` is under the hook's
allowed `/home/claude/wt/` prefix, so it is NOT blocked. The same is true in a real session: inside
a worktree the hook would let `rm -rf src` through. Unchanged by Part A (no `.claude` file or that
test touched). I1 (or a later I0 fix): refuse the checkout's own top-level `src`, `tests`, `.git`,
`docs`, `evals` even under an allowed prefix, and run the test from a neutral cwd.

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
  vault" | "skipped: switched off" | None), `drill_at`. B raises neither backup kind.
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
size, time and rupees of a restore; the Workshop's I1-side tests of section 7.

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
- **Reviews**: the row asks for `security-reviewer`; this builder may not start agents, so a
  self-review against `.claude/rules/ecc/common/security.md` was done (no secret; inputs validated:
  the route body `extra=forbid` and its session pattern, the backup and operation names, collection
  ids; errors are class names and fixed words; no plaintext, nonce or key stored or logged; rate
  limit on the one write route; owner-only). A fresh-context `security-reviewer` on
  `storage/firestore_{admin,walk}.py`, `backup/{readonly,drill,verify,vault_probe}.py`,
  `api/backup.py` and `deploy/backup_setup.sh` is for I1.

## 12. Checks (run in the worktree, 14 Nov 2026)

| Check | Result |
|---|---|
| `pytest tests/test_r14_a_*.py`, Python 3.12 and 3.11 | 124 passed, 1 xfailed (strict, I1 #1) on each |
| Coverage of Part A's modules (its own tests) | 95 % (1,384 statements) |
| Seam set (`test_r14_seams`, `test_r14_wiring`, `test_claude_guard`, `test_arch_coverage`, `test_telegram_tool_guard`) | 265 passed, 13 failed: 3 seam pins of an unbuilt Part A (I1 #3), 1 Telegram list (I1 #2), 9 hook cases that fail in any worktree (I1 #7) |
| Other existing tests that list the tick jobs | `test_r2_wiring` (2), `test_r4_wiring` (3), `test_r11_wiring` (1), `test_r51_wiring` (1) fail on the two new job names (I1 #4); the other tool / privacy / wiring suites pass |
| `ruff check` and `ruff format --check` (src tests evals scripts) | clean |
| `mypy src` | the 9 baseline errors only |
| `evals/r14/run.py --mock --part backup` | 11/11, control failed the suite |
| `scripts/arch_coverage.py`, `scripts/check_doc_versions.py` | OK (103 collections), all documents versioned |

## Change log

| Version | Date | Release | What changed | By |
|---|---|---|---|---|
| v14.0.1 | 14 Nov 2026, 17:05 IST | R14 | First edition: Part A built (the locks, the canary, the status, the log, the checks, the drill's state machine, the jobs, the tools, Vitals, Privacy, the join, the routes, the set-up script, the eval with its two controls), what he sees, the costs (₹3.9, not ₹4.9, at 100 MB), Needs I1 with exact diffs, the runbook text, what could not be verified, risks and the checks | 🛠 Mark XIX |
