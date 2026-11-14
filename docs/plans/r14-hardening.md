Version v14.0.2 · 14 Nov 2026, 14:30 IST · Release R14 · Status: Ready · Owner: 🛠 Mark XVIII

# Release R14 — Free hardening (`v14.0.0`)

**Phase:** 7 (evals, hardening, cost), pulled forward by the owner (build order of 14 Nov: free and
pending items first). **Type:** free to build; backups add a small Google charge that starts only when
the owner runs his one-time step (about ₹5 a month at 100 MB of data, about ₹40 at 1 GB). No new paid
service, no new secret, no new Cloud Scheduler job. **Branches:** I0 `r14-i0` (from `main` @ `5db4f05`,
R7 live, v7.0.0) → parts `r14-a` … `r14-d` → integration `r14-i1` → PR `v14.0.0 · R14 Free hardening ·
Mark XVIII`. Every commit carries `JARVIS-Version: v14.0.0` and `JARVIS-Mark: XVIII`. Read on `5db4f05`;
v14.0.2 writes in plan review 1 (`r14-integration/PLAN-REVIEW-1.md`: A1–A8, the B lines, the C seams
and the D notes) and is Ready for I0.

## Summary for the owner (plain words)

1. **Your data gets a safety copy, and we prove it works.** Today JARVIS keeps no copy of its
   database: one bad mistake would lose your vault, notes, health and sleep log and settings. After
   your one-time step, Google makes a copy every day and keeps each for 7 days. Once a month JARVIS
   opens the newest copy in a separate, throw-away database, checks that nothing is missing and that
   it can still unlock one of your locked documents, then deletes the throw-away copy. Its code can't
   write to your real database while it does this, and nothing it holds can delete that database.
   Cost: about ₹5 a month at 100 MB, about ₹40 a month if your data ever fills Google's free 1 GB.
   JARVIS shows the real figure after the first copy.
2. **JARVIS watches itself and tells you when something is wrong**: background jobs failing again
   and again (one message an hour at most, naming them all), its clock stopping, the morning brief
   not made, errors piling up, a day's AI spend far above normal, a new version going live, a missed
   or broken backup. Same alert rules as today (quiet hours, caps, switches in the Alerts card), plus
   a cap of their own: at most 3 such messages an hour, so they never crowd out your approvals.
3. **Cheaper replies.** Each reply sends JARVIS's whole rule book and all ~135 tool descriptions to
   Claude. R14 sends only the tools a message needs (any others on request), stops old tool results
   from riding along in every later reply, and lets Claude reuse what it read within the same reply.
   Estimate: about 45 % less per reply (from about ₹5.4 to about ₹3.0 on the middle Claude model).
   JARVIS will measure the real numbers and show where the money goes.
4. **A skill register.** Every tool is filed under one of JARVIS's 11 skills, with its risk, its
   permission row and its Telegram rule. A check stops any new tool that isn't filed. New groupings
   of existing tools are a data change, not a code change.
5. **More works with the AI off**: groceries, vault expiry, "where did I put…", home status, parcels,
   inbox summary, recently deleted, time and date, memory search, backups, "what can you do".
6. **Your car and home services (rows 101, 102).** The car's maker offers no way in for other apps,
   so the car stays "not possible yet"; its papers already live in the vault with reminders, and
   R14 adds a car-service reminder. For a plumber or electrician JARVIS writes the request and gives
   you the booking site's address, or drafts a message to the person you pick; it never books or pays.
7. **Seven small security fixes** left from earlier releases (listed in D13).

## The rows (owner's workbook v2, read 14 Nov 2026 from the Google Sheet)

| Row | Workbook text | Skill (workbook) | R14 outcome |
|---|---|---|---|
| 101 | Connected car (if your car's app allows it) | Automation Engine | Not possible yet (D1); papers in the vault (built R2), car-service reminder (new starter) |
| 102 | Home service booking (plumber, electrician), with your confirmation | Task & Productivity | Prepare and hand over; never book or pay (D2) |
| 109 | JARVIS self-health: uptime, error and cost alerts | Code & DevOps | D5–D7 |
| 110 | Backups and restore drills — "Code backups to your Google Drive exist; a tested restore is pending." | Code & DevOps | D3, D4 (the code is on GitHub; the DATA had no copy) |
| 111 | Cost optimisation | Code & DevOps | D8–D10 |
| 112 | Skill registry: add new skills without code changes | Code & DevOps | D11 (data-driven for groupings; a new ability still needs a reviewed tool) |
| — | No-AI mode, pass 2 (release plan) | cross-cut | D12 |
| — | R5.1–R7 leftovers | cross-cut | D13, rest deferred with reasons |

## What the code says today (`main` @ `5db4f05`)

1. **Version and limits.** `__version__ = "7.0.0"` (`src/jarvis/__init__.py:3`); persona `p7.0`
   (`core/prompts.py:56`). Guards: `api/app.py` 735 = guard (`tests/test_r11_1_seams.py:244`,
   `test_r7_seams.py:650`), `tools/gateway.py` 760 = guard (`:242`, `:649`, also
   `test_r1_seams.py:649`), `console.html` 782 = guard (`:246`, `test_r7_seams.py:606`);
   `console.js` 761, `core/brain.py` 704 (guard 741, `test_r11_1_a_brain.py:301`), `config.py` 656,
   `console-alerts.js` 450, `notify/storm.py` 310, `vault/service.py` **876** (over 800, pre-existing).
2. **Clocks.** Region `asia-south1` (`deploy/cloudrun.sh:48`), `--max-instances 1` (`:548`). Two
   Scheduler jobs (`:647–697`): the brief tick `0,30 4-11 * * *` and the watchdog `*/5 * * * *`
   (created whatever Home is set to). The tick runs its sweeps, then `run_jobs`
   (`api/brief.py:129–160`). A failed or timed-out job is **logged and reported "failed" in the
   answer only** (`ticks.py:68–95`); a job the tick had no time left for is reported "failed" too
   (`ticks.py:111–114`); in the watchdog an advisory job's failure becomes "degraded" and a log line
   (`home/watchdog.py:81–83`, `:236–241`). The watchdog has 50 s in all (`home/watchdog.py:61`);
   `health_check` alone may take 30 s (`health/tick.py:28`). Nobody is told.
3. **Home off.** The 5-minute route then runs **only the helpers' clock**, with no owners:
   `run_jobs((clock,), (), …)` (`api/home.py:148–172`, `:168`). Composites carry their own owners;
   `HealthTickJob` serves only the owners it is passed (`health/tick.py:55–60`). With Home on, the
   watchdog passes `linked_uids()`, the owners who linked a laptop (`home/watchdog.py:235`). The
   systems check (`api/selfcheck_wiring.py:180–192`) and R7's `mobile_clock` (`api/r7_wiring.py:179–181`)
   join the watchdog only when it exists, so with Home off they run in the morning window only
   (through `r4_tick_jobs` / `mobile_tick_jobs`, `api/r4_wiring.py:311`). R5.1 D4 ("around the
   clock") holds only with Home on. The brief's owner list is `BriefService.owners`
   (`brief/service.py:688`).
4. **Self-health today.** Probes: brain, google, telegram, home, docs, redis, web
   (`health/probes.py:130–254`); Vitals: AI spend, voice allowances, Google SKUs, keys
   (`api/selfcheck_wiring.py:68–103`; the board's own items are built from `vitals/own.py`
   `OwnSources`). Nothing watches the clocks, job streaks, error volume, the brief's outcome
   (`brief/service.py:491–497` marks a failed brief and tells no one), revisions, backups or the
   database's size.
5. **Alerts.** 43 kinds (`alerts.py:22–83`; pinned `test_r3_seams.py:165`, `test_r6_seams.py:142`,
   `test_r11_seams.py:66`, `test_r11_1_seams.py:119`, `test_r7_seams.py:231`; the exact
   `DAYTIME_RING_KINDS` in `test_r51_seams.py:45`; `webpush/service.py` `TARGETS` must name every
   kind but `test`, `test_r7_a_push.py:43`; `buildbook/plain.py:155` `ALERT_WORDS`).
   `storm.SOFT_URGENT_KINDS` = health_fault, vitals_critical (`notify/storm.py:38`; pinned
   `test_r51_int_notify.py:47`), 6 an hour in all and one per subject per 30 minutes (`:178–191`).
   Every "important" kind shares Telegram's normal bucket, 10 an hour and 50 a day, with
   `approval_waiting` and the vault and bill reminders (`notify/telegram_out.py:147–158`). The held
   words (`notify/held.py:14–40`) and the Alerts card (`console-alerts.js:20`) have no entry for
   `health_fault` or `vitals_critical` (R5.1 leftover).
6. **Keyring.** 21 cipher purposes + `webpush_vapid` (`keyring.py:42–75`; pinned
   `test_r7_seams.py:292` (the last three), `:293`, `test_r11_seams.py:163`, `test_r3_seams.py:849`).
   Root = Secret Manager `jarvis-token-key`, made once, never overwritten (`deploy/cloudrun.sh:202`;
   `tests/test_deploy_vault.py`). A backup is only readable with that key.
7. **Permissions.** 49 rows (pinned `test_r1_seams.py:231`, `test_r2_seams.py:576`,
   `test_r3_seams.py:911`, `test_r11_1_seams.py:139`, `test_r7_seams.py:258`); `vitals_*` R1 →
   `vitals`, R2 → `vitals_change` ("Add, edit and remove the keys you track",
   `permissions/groups.py:444–461`); `maint_*` → `household` (`:512–520`). The save cap
   (`PermissionsPatch.groups`) is 51.
8. **Firestore.** One `(default)` Native database in asia-south1 (`deploy/cloudrun.sh:411–419`);
   `jarvis-run` has `roles/datastore.user` and `logging.logWriter` (`:471–473`): unconditioned
   `datastore.entities.*` on every database of the project. `FirestoreDocs` takes a `database`
   (`storage/firestore_docs.py:54`) and is the only SDK importer; setting `firestore_database`
   (`config.py:171`). The pinned SDK (google-cloud-firestore 2.34.1) already ships
   `firestore_admin_v1` with `list_backups`, `restore_database`, `delete_database` and
   `Backup.stats{size_bytes, document_count, index_count}`, which "will be empty till" the backup is
   fully materialised (the SDK's docstring), even when its state is READY: no new dependency.
   Sub-collections exist (`activity/{uid}/d`, `activity_days/{uid}/days`, `deleted_items/{uid}/items`).
   The vault's own fields are `rev` and `updated_at` (`vault/store.py:4`, `:70–87`).
9. **Promises to change.** The guide says "No backups … When you delete something it is gone for
   good" (`docs/architecture/JARVIS-Architecture.md:118–119`) and "Firestore has no backups"
   (`:1685–1686`).
10. **Deploy facts.** The people cache's docstring says deploy sets a TTL policy on `expires_at`
    (`people/cache.py:6–7`); deploy sets none, and none is wanted: `expires_at` is a float
    (`people/cache.py:91`), a TTL policy needs a timestamp, and TTL deletes have no free usage (S2);
    the code avoids billed TTL on purpose (`api/brief.py:139`). The cache already deletes on an
    expired read and on `clear`. The Vitals composite index is still created
    (`deploy/cloudrun.sh:429–437`, the `jarvis_vitals_providers` index) though R5.1 D2 removed the
    need. The budget alert is ₹1, "any charge" (`:372–394`): once backups cost money it will e-mail
    every month.
11. **Where tokens go** (measured on the fullest registry the fakes build,
    `tests/test_telegram_tool_guard.py` `linked_gateway`; the live set is about 120–140): the persona
    is 21,338 characters ≈ 5,300 tokens (`core/prompts.py:563–611`); **135 tools**: 54,868 characters
    of name + description + schema (≈ 13,700 tokens), 61,515 as sent in JSON (≈ 15,400 tokens); the
    top 20 % of tools is 37.7 % of it. **Every** model call sends every tool (`core/brain.py:430`,
    `tools/registry.py:20`). One cache breakpoint, on the system block (`llm/anthropic_provider.py:115–126`);
    the per-turn trailer (the time to the minute, the turn number, the recalled notes;
    `core/prompts.py:648–655`) is a second, uncached system block (`core/brain.py:363`), so it sits
    **before** the messages. The history caps (`session_max_turns` 40, `session_max_chars` 48,000;
    `config.py:175–179`) count only `t.content` for characters (`core/window.py:34`, `:37`), but a
    tool-result turn has `content=""` and the result in blocks (`core/rounds.py:120`), up to 12,000
    characters each (`tools/gateway.py:106`): **tool results never count toward the character cap**
    (the 40-turn cap counts them), so a long tool session re-sends every result on every reply.
    Billing records one USD figure a call (`core/brain.py:432`, `billing/service.py:293`), not the
    token split. Prices (`llm/pricing.py:30`): Sonnet 5.5 $2 in, $10 out, $0.10 cache read, $2.50
    cache write; rate ₹95.24 (`billing/fx.py:33`, `DEFAULT_RATE`; the live rate is read daily).
12. **No-AI pass 1** (`offline/rules.py:260–288`): notes add/search, timer, remind, systems check,
    vitals, quota, reminders, to-dos, calendar, people research; since then phrase routers for the
    four helpers, study plans and the watch. Extra routers run before the generative check
    (`:264`, before `_GENERATIVE` at `:269`). Everything else answers `NO_AI_LINE` (`:65`).
13. **Leftover facts.** `_reauth_at` treats a missing `auth_time` as now (`api/auth.py:166–174`);
    `ShowLock.set` writes the new lock without the earlier `sessions_valid_after` mark
    (`buildbook/lock.py:120–124`); `GET /v1/notes/export` writes no audit line (`api/notes.py:170–182`);
    vendor text in all four error classes: `LLMAuthError`, `LLMUnreachable`, `LLMTransientError`,
    `LLMError` built from `str(exc)` (`llm/anthropic_provider.py:155`, `:161`, `:163`, `:164`) or from
    the vendor's own message (gemini `:127–138`, the `msg` of `:133`, `:135`, `:137`, `:138`;
    openai_compat `:161`, `:163`, `:165`, `:166`), and the router logs `str(exc)[:200]`
    (`llm/router.py:269`); the Telegram re-plan card's first line is the model's own `series`
    argument (R11.1 I1-NOTES, security L3); the console handles 423 only (`console.js:78`, `:101`),
    so a 503 `lock_unreadable` leaves the page on screen; the UPI cap ₹1,00,000 is two constants,
    `helpers/sources.py:35` `MAX_UPI_AMOUNT_PAISE` and `helpers/today/models.py:47` `PAY_CAP_PAISE`
    (R11 D7).
14. **Car papers.** The vault already has `vehicle_rc`, `vehicle_insurance` and `puc` with expiry
    reminders at 180…1 days (`vault/models.py:43–59`, `vault/reminders.py:6`); R11's upkeep list has
    `STARTERS` (`helpers/house/upkeep.py:31`), pinned `[90, 180, 365, 365]`
    (`tests/test_r11_b_chores.py:152`).
15. **Cards on a reply.** Replies are plain text; a link reaches the screen only as a typed card the
    server checks and the console checks again (`tools/reply_cards.py:26–31`). The drill card's
    `PendingAction.bulk_ok` decides whether Approve all may run it (`core/approve_all.py:14–15`, `:258`).
16. **The guide's cards** run to C65 (R7: C62–C65; R11.1: C61), so R14's new cards are C66–C68.

## Google's and Anthropic's terms (read 14 Nov 2026; the shell can't reach Google)

| Fact | Source |
|---|---|
| Up to one daily and one weekly backup schedule per database; retention up to 14 weeks; the daily time can't be chosen; a backup is a consistent point-in-time copy in the database's own location; it holds data and index settings, not TTL policies | S1 |
| A restore writes to a **new** database whose id must be unused; deleting the source keeps its backups. Not on the page: whether a deleted backup can be recovered, and what a restored database inherits (delete protection, `update_time`) | S1 |
| Backup storage $0.000041096 per GiB-hour (≈ $0.030 per GiB-month, ₹2.86); restore $0.20 per GiB (₹19.05); stored data $0.000205479 per GiB-hour (₹14.29 per GiB-month); reads $0.03 per 100,000 (₹2.86); a `count()` aggregation is billed about one read per 1,000 index entries; one table for all locations | S2 |
| Named databases get **no** free quota; backup data, restores and TTL deletes have no free usage | S2 |
| `datastore.restoreAdmin` = backups get/list/restoreDatabase, databases list/create/getMetadata, operations list/get; `datastore.user` has no backup or database-admin permission; `databases.delete` is only in `datastore.owner` (`datastore.*`) | S3 |
| Per-database IAM conditions: `resource.name=="projects/P/databases/D"` (shown for `datastore.user`); `--delete-protection` on a database; an id is reusable 5 minutes after a delete; 100 databases a project | S4 |
| Cloud Run sets `K_REVISION` in the container (S5 not fetched; a long-standing part of the contract) | S5 |
| Claude caching: prefix order tools → system → messages; changing tools invalidates all; 5-minute write 1.25×, 1-hour write 2×, read 0.05× on Sonnet/Opus 5.5; up to 4 breakpoints; 512-token minimum; a 20-block lookback (a run of tool results counts as one); mid-conversation tool additions (beta `inline-tools-2026-09-15`) and `defer_loading` exist | S6 |

## Decisions (binding)

**D0 · Scope and order.** Four parts: A backups and the drill (headline), B self-health, C cost and
the skill register, D No-AI pass 2, rows 101/102 and the security leftovers. Everything plain code;
the only model calls are the ones replies already make. No new Scheduler job: backups are Firestore's
own schedule; R14's jobs ride the existing tick and watchdog. **Nothing spends money before he types
YES** in his one-time step (D4, owner step 4); the deploy only reads.

**D1 · Connected car (row 101): not possible yet** (decided 14 Nov). Tata's iRA has no API for other
apps, and CERT-In flagged iRA app flaws on 4 Nov (confirmed by news reports); unofficial access is
declined. The vault already covers RC, insurance and PUC with reminders (fact 14). Missing piece only:
a service-due reminder: `helpers/house/upkeep.py` `STARTERS` gains "Car service" every 6 months
(offered, never added); Part D moves the pin `tests/test_r11_b_chores.py:152` to
`[90, 180, 365, 365, 180]`. Kilometre-based service needs the car's data: not possible yet.

**D2 · Home services (row 102): prepare, never book.** Urban Company has no public API (decided 14
Nov). New tool `maint_service_request` (R1, row `household` via `maint_*`, skill Task & Productivity,
Telegram open), in R11's house tools (`helpers/house/tools.py`, Part D): input job (plumber,
electrician, carpenter, AC, cleaning, appliance, pest, other), problem ≤ 200 characters, preferred
time ≤ 40 characters; output a fixed-template request text (no address, no phone) and the booking
site's address `https://www.urbancompany.com/` **as text** in the result (no new card kind: a tap card
would need a new checked card type and renderer; deferred, D16). To message a provider he picks, the
brain uses the existing `whatsapp_draft` (a draft; he sends). No booking, no payment, no auto-open;
the R3 rule stands for anything that would.

**D3 · Backups: Firestore's daily schedule, kept 7 days.** Chosen over managed export (reads billed
per document, a Cloud Storage bucket with no free tier in Mumbai, more IAM) and PITR (≈ 5× the
storage rate, a 7-day window, recovery by clone). The owner's one-time script (D4) runs
`gcloud firestore backups schedules create --database='(default)' --recurrence=daily
--retention=7d`, turns **delete protection** on for `(default)` and grants jarvis-run what the drill
needs. Not in the copy, said plainly: the laptop's camera pictures and face library, Secret Manager
(its versions are kept by Google; the deploy never destroys them, fact 6), his Google account data.
The backups and `jarvis-token-key` live in the same project: the drill proves recovery from a bad
write or delete, not from losing the project or the key (owner question 5; card C66 says so).
**Privacy change:** a deleted item leaves the live database at once and the backups within 7 days;
the guide (fact 9), the Privacy panel (a "Backups" row, Part A's privacy source, server-sent: no
console change) and persona p14.0 say so. **Before his step**, Vitals shows "Backups: not set up" and
nothing alerts (D5).

**D4 · The restore drill: monthly, automatic, its code unable to write the live database.**
- *IAM (owner's step):* jarvis-run gets `roles/datastore.restoreAdmin` (restore into a new database;
  it can create databases but never delete or overwrite one), a **custom role `jarvisDrillCleanup`**
  (`datastore.databases.get`, `.getMetadata`, `.update`, `.delete`) **only** with the condition
  `resource.name=="projects/P/databases/jarvis-drill"` (least privilege, instead of a conditioned
  `roles/datastore.owner`, which is `datastore.*`), and `roles/datastore.backupSchedulesViewer`.
  `(default)` has delete protection on. The script checks the binding with
  `gcloud projects get-iam-policy … --flatten`; the first drill's clean-up proves the positive case.
  If Google ignored the condition, it fails closed: the drill copy can't be deleted (A alerts) and
  `(default)` is still safe.
- *Canary (daily, morning tick, job `backup_canary`):* `{prefix}backup_canary/{yyyymmdd}` = SHA-256
  of a random 32-byte nonce, the nonce sealed with the new keyring purpose `backup_probe` (AAD
  `backup_canary/{date}/v1`), a key fingerprint (`keyring.mac("backup_probe", "fingerprint/v1")`,
  first 16 hex), version, time. Kept 30 days.
- *Status (daily, same job):* list the backups and the schedule; store
  `{prefix}backup_status/current` (schedule seen, the first time it was seen, the newest READY
  backup's name, snapshot time, `size_bytes`, `document_count`). Part A is the **only** producer of
  `backup_problem`, `backup_ok` and the database-size Vitals item; Part B and Vitals read it through
  the read port `backup.ports.BackupStatus` (I0).
- *Drill (job `backup_drill`, morning tick; state machine in `{prefix}backup_drill/current`):*
  due on day `backup_drill_day` (1) at the first tick after 05:00, or after he approves the
  `vitals_drill_start` card (`bulk_ok=False`, so Approve all can never start one; at most
  `backup_drill_manual_per_month` (2) manual drills a month; `POST /v1/backup/drill` rate-limited per
  owner). One drill at a time (the fixed id does this).
  - **start**: newest READY backup **whose `stats` are filled and `document_count` > 0**; empty
    stats mean "not yet": wait for the next tick, never start. Refuse when `size_bytes` × the restore
    price at the **live** rate (`billing/fx.py`) > `backup_drill_max_inr` (₹100, a backup of
    5.25 GiB). If a `jarvis-drill` database exists, clean up first, and restore **at the next tick**
    (an id is reusable only 5 minutes after a delete; ticks are 30 minutes apart). Restore into the
    fixed id `jarvis-drill`.
  - **restoring**: poll the operation each tick.
  - **verifying** (resumable per collection, bounded by `ticks.time_left()`): (1) counts by
    `count()` aggregations per collection group (about one read per 1,000 entries, ≈ ₹0) over the
    collection ids `list_collections()` finds at the root plus the known sub-collection ids (Part A
    pins the list against the stores); the total must equal `stats.document_count` exactly (an
    unknown collection fails closed); (2) the newest canary dated within 26 h before `snapshot_time`
    is present, its hash equals the live canary's, its sealed nonce opens with the live keyring and
    the fingerprints match; (3) one sealed vault item from `jarvis-drill` opens through the vault
    store's own read path, its plaintext only hashed in memory and compared with the live item when
    both carry the same **`rev` and `updated_at`** (the app's own fields, never Firestore's
    `update_time`, which a restore may restamp); (4) up to 20 documents per collection compared with
    live on the collection's own time field → identical content hash. The result stores how many
    items were compared. **Zero vault items opened or zero samples compared is "failed: nothing
    compared"** whenever the live database has any; an owner with no vault is "skipped: no vault",
    never a pass.
  - **cleanup**: `get_database("jarvis-drill")` decides, not the stored state alone (a failed
    restore may still leave a database); if the copy has delete protection on (Google doesn't say
    what a restore inherits), disable it first (`.update`, conditioned); delete; wait until gone;
    store the result. Cleanup runs **whenever** a `jarvis-drill` database exists, even with
    `backup_drill_enabled` or `backup_checks_enabled` off. A failure anywhere stores "failed" with a
    reason code and still cleans up. A copy left over costs ≈ ₹1.4 a month at 100 MB, ≈ ₹14 at
    1 GiB (stored data, no free quota): a drill copy older than 2 days raises `backup_problem`
    once, and weekly after that.
- *Unable to write live (the code locks; the IAM lock does nothing for writes, since
  `datastore.user` is unconditioned, and delete protection stops neither writes nor document
  deletes):* (1) the verifier gets `ReadOnlyDocs` (get and query only; no `write`, no
  `transaction`; not a `Docs` subclass) for **both** sides, the drill copy and the live database;
  (2) the drill-side reader (`storage/firestore_walk.py`) and the admin adapter
  (`storage/firestore_admin.py`) refuse any database id but the constant `DRILL_DB =
  "jarvis-drill"`, and refuse `(default)` and `settings.firestore_database`, **before** any call
  (both through `backup.ports.drill_target`, I0); (3) the result is written by `backup/log.py`;
  `backup/{verify,walk_checks,vault_probe}.py` import neither `storage.firestore_docs` nor
  `backup.log` (an import test); (4) for deleting `(default)`: no delete permission but on
  `jarvis-drill`, and delete protection; (5) `Settings` refuses `firestore_database ==
  "jarvis-drill"` at start-up (I0), so a live database restored into that id is never the next
  drill's target. The admin client's async class (or a thread) keeps a tick from blocking the event
  loop. Tests prove each (part A).
- *"Restoring for real"* (Part A's runbook in INTEGRATION-A.md, the guide's §8 at I1): restore into
  a new id, never `jarvis-drill`; after a real restore clear `backup_drill/current` (the copy carries
  the old state); restoring into `(default)` after deleting it (delete protection off, then 5
  minutes) keeps the free quota; items deleted after the snapshot come back.

**D5 · Self-health watch (B): what JARVIS will tell you about itself.** One package
`src/jarvis/selfwatch/`, two jobs: `selfwatch_clock` (5 minutes, advisory, **first** on both 5-minute
paths, D7) and `selfwatch_daily` (morning tick).

| Signal | Rule | Kind |
|---|---|---|
| Jobs fail again and again | `selfwatch_fail_streak` (3) **failed or timed-out** runs in a row of any tick/watchdog job or sweep (seen through the `ticks` observer, I0, which carries the outcome: `ok`, `failed`, `timed_out`, `skipped`; a skip for time never counts); **one aggregated alert an hour per owner** naming every job in a streak ("3 background jobs keep failing: …") | `job_failing` |
| A clock stops | watchdog not seen for 20 min (checked by the tick), or no tick by 05:00 on a day (checked by the watchdog); once per outage | `clock_stopped` |
| Recovered | the streaks or the outage end | `selfwatch_ok` (info) |
| Brief not made | today's brief absent or failed `selfwatch_brief_grace_min` (60) after his brief time; once a day | `brief_missed` |
| Errors pile up | ERROR log records in an hour > `selfwatch_errors_per_hour` (30), counted by a logging handler by logger name only; once a day | `errors_piling` |
| Spend spike | a day's AI spend = today's month-total snapshot minus yesterday's (on the 1st: today's snapshot, the month total resets, `billing/meter.py` `month_of`) > `selfwatch_spike_factor` (3) × the 14-day daily average and ≥ `selfwatch_spike_min_inr` (₹50); no alert before 7 days of history; once a day | `spend_spike` |
| New version live | `K_REVISION` (S5) or version differs from the stored one; once per revision; says the version | `deploy_changed` |
| Backups (Part A) | no READY backup newer than `backup_max_age_h` (36), no schedule, drill failed, drill copy left over, canary key changed; once per cause a day (left-over copy: weekly) | `backup_problem` |
| Drill passed (Part A) | monthly | `backup_ok` (info) |
| Database size (Part A) | latest backup's `size_bytes` vs Firestore's free 1 GiB: amber 80 %, red 100 % | Vitals item (existing `vitals_warn`/`vitals_critical`) |

No self-reinforcing loop: the once-only claim (`selfwatch_told`) is written **before** the send; a
failed send is not a job failure; a selfwatch job never reports its own streak (the tick's
`selfwatch_daily` watches `selfwatch_clock`, the clock watches the tick's); the errors handler skips
records from `jarvis.notify*` / `jarvis.telegram*` raised while a selfwatch alert is being sent (a
context flag); a handler that fails never logs itself; counts are written batched every 5 minutes.
**`backup_problem` begins only after the set-up has run once** (a schedule seen once, stored in
`backup_status/current`); until then "Backups: not set up" is a Vitals line only. If **both** clocks
stop JARVIS cannot speak up (nothing runs); the Vitals board shows "Clocks stopped since …" (an
ordinary Vitals item, server-sent through I0's slot) when he opens it. Firestore read/write counts
need Cloud Monitoring and a new permission: deferred (D16).

**D6 · Alert kinds 43 → 52** (`R14_ALERT_KINDS`): `job_failing`, `clock_stopped`, `brief_missed`,
`errors_piling`, `spend_spike`, `deploy_changed`, `backup_problem` are important daytime rings (held
in quiet hours, in `DAYTIME_RING_KINDS`) with **their own soft table** in `notify/storm.py`
(`SELF_KINDS`: one per kind and subject per 30 minutes, at most 3 an hour in all per owner),
**not** `SOFT_URGENT_KINDS` (which stays the two R5.1 kinds); `selfwatch_ok`, `backup_ok` info (feed
only). Every one has an Alerts-card switch, held words, a Web Push target (`webpush/service.py`
`TARGETS`: self-health → `vitals`, backups → `vitals`) and book words (`buildbook/plain.py`
`ALERT_WORDS`); text is a fixed template (no logger name, no vendor text, no amounts except the
spike's ₹ figure). The two missing Alerts-card rows and held words for `health_fault` and
`vitals_critical` are added in the same seam (Alerts card +11 rows).

**D7 · Self-health runs around the clock with Home off too.** I0 replaces the Home-off branch
(`api/home.py:160–172`) with `app.state.clock_jobs`: every advisory 5-minute job (`selfwatch_clock`
first, then `health_check`, `helpers_clock`, `mobile_clock`), built once, each run **for the brief's
owners** (`BriefService.owners`, read late), used by both paths; with Home on the watchdog runs
`selfwatch_clock` before its own laptop jobs and the rest after them. The three `watchdog.extend`
sites register into the shared list instead. `ADVISORY_JOBS` += `selfwatch_clock`. Test: Home off →
`health_check` and `selfwatch_clock` run for the configured owner at 02:00.

**D8 · Measure first: a token ledger.** `billing/ledger.py` (C) records per call, per owner per day
(`{prefix}token_ledger/{uid}_{yyyymmdd}`, 90 days): calls, cold calls, input, cache read, cache write,
output tokens (from the vendor's own `Usage`), and characters by part (persona, tools, history, tool
results, memory, trailer), tools offered, skills opened. Counts only. Vitals line "Where the AI money
goes this month" in ₹ by part (an ordinary Vitals item through I0's slot). The before/after figures
below are estimates until a week of ledger data replaces them. The guide's §9 "about ₹0.17 a reply"
and "about ₹100 a month for Claude" (`:62`, `:1800`) are the owner's Phase 0 real-Claude run
(`docs/plans/phase2-slice11-full-control.md:11`) on a far smaller persona and tool set: I1 rewrites
both with measured numbers.

**D9 · Free cost wins (C), all inside `jarvis.llm` and the brain's two slots; model-agnostic.**
- *Offer only the tools a message needs.* `skills/offer.py`: the turn's skills = keyword matches on
  his message (the register's words, English and his common Hinglish) ∪ the skills of tools used in
  the last 3 turns ∪ the previous turn's set when it was under `tool_offer_sticky_s` (300 s) ago
  (sticky, so the cache still hits) ∪ the always-offered core (`skills_open`, `reminder_add`,
  `calendar_list_events`, `memory_search`) ∪ every tool a `tool_use` block in the window names (so a
  replayed call never names a tool the provider wasn't offered; checked in the five providers'
  real-run evals). Fixed for the whole turn, in registry order, except when the model calls
  `skills_open(skill)` (R1, no side effect, through the gateway): the next round adds that skill.
  `tool_offer = "all"` restores today's behaviour (kill switch); an offer that raises → all tools. A
  brain that trains on content still gets no tools. The offer only narrows what the model sees:
  every call still meets the registry, the rows, the Telegram classes, the taint rules and R3 tokens.
- *Count tool results in the history.* `core/window.py` counts block characters; tool results from
  **earlier turns** older than the last 2 tool rounds are cut to `history_tool_result_chars` (2,000)
  with "… [shortened]" when the window is built at the start of a turn (never a round of the current
  turn, so the prefix never moves within a turn; a result is shortened once, then stays the same),
  pairs kept well-formed. A shortened result keeps its leading "untrusted tool output" line, its
  `is_error` and its `trusted` flag; shortening is send-side only (the taint checks read the stored
  rounds). The window drops old turns **in chunks** (down to 70 % of the budget), so its start stays
  put for several replies.
- *Cache within the reply* (A1, choice (b)). The per-turn trailer stays a system block before the
  messages (no prompt-shape change, no persona or voice eval rerun), so a breakpoint on a message
  can hit only between the rounds of one turn; the cross-turn claim is dropped. The Anthropic
  provider, built with `cache_history` (on) from the settings, adds a second breakpoint on the last
  message block itself; the other providers have nothing to do; **no brain slot and no `CacheHint`
  in the shared interface**. 5-minute TTL stays (1-hour waits for ledger data). Moving the trailer
  after the history (choice (a), about ₹70 a month more at the mix) is deferred (D16).
- *Vendor text out of errors:* all four classes (`LLMAuthError`, `LLMUnreachable`,
  `LLMTransientError`, `LLMError`) carry fixed words in all three providers; the vendor's message
  stays in the provider's own log (as `LLMOutOfCredit` does); the router logs the class name, not
  `str(exc)`.
- *Optional, Anthropic only:* the mid-conversation tool-addition beta or `defer_loading` could keep
  the prefix cached when `skills_open` adds a skill; they are vendor features, so only inside
  `anthropic_provider.py`, behind `cache_history`, and only if the ledger shows `skills_open` often.
- **Out:** a per-turn fast-tier classifier (it adds 0.3–0.8 s to every spoken reply; `skills_open`
  covers a missed tool for one cheap round); simple replies on the fast tier (owner question 7);
  trimming the persona per skill (safety rules live there; needs a full eval pass); the **streamed
  tool loop** from R5 D15 (a latency feature, not cost or safety; it needs tool-call streaming in all
  five providers and the brain, which is at 704 lines; a voice release).

**D10 · ₹ per reply, before and after** (balanced tier at ₹95.24, ₹ per million: in 190.48, out
952.40, cache read 9.52, cache write 238.10; prefix today ≈ 20,700 tokens (persona 5,300 + 135 tools
15,400), after ≈ 8,200 with ~25 tools; history and trailer 3,800; output 250 a call; a tool round adds
2,250 (the call and a 2,000-token result)):

| Reply | Today | After R14, history hint off | After R14, hint on (default) |
|---|---|---|---|
| After a pause over 5 min, no tool | ₹5.89 | ₹2.91 | ₹3.10 |
| Within 5 min of the last, no tool | ₹1.16 | ₹1.04 | ₹1.22 |
| After a pause, one tool (2 calls) | ₹7.48 | ₹4.38 | ₹3.98 |
| After a pause, two tools (3 calls) | ₹9.49 | ₹6.28 | ₹4.89 |
| **Mix at 20 a day** (50 % / 20 % / 30 % of the first three rows) | **₹5.42 → ≈ ₹3,250 a month** | **₹2.98 → ≈ ₹1,790** | **₹2.99 → ≈ ₹1,790** |

The hint is neutral at the mix and wins on every turn of 2 calls or more (where a long tool session's
cost is); the ledger's cache-write and cold-call counts show whether to keep it. Long tool sessions
save more (fact 11: uncounted results can add ≈ 30,000 tokens, ₹5.7, to every later reply). Saving
≈ ₹1,460 a month at 20 replies a day; "45 %" stays an estimate until the ledger (D8) measures it.
Gemini, laptop and No-AI stay ₹0.

**D11 · The skill register (row 112).** `src/jarvis/skills/catalogue.json` (data) lists the 11
skills — Task & Productivity, Research & Intel, Code & DevOps, Decision Support, Communication,
Finance & Analytics, Learning, Creative, Security Advisor, Automation Engine, Health & Wellbeing —
each with a one-line "about", its words for the turn offer, and its tool patterns (an exact name
wins over a family). The ids and labels are I0's (`skills/ids.py`). `skills/registry.py` derives
each tool's card from the live registry: name, skill, risk (`Tool.risk`), permission rows
(`permissions.groups.groups_for`), Telegram class (private / personal / home / both / open, from
`telegram/rules.py`). **The check:** `tests/test_r14_skill_coverage.py` builds the fullest registry the
fakes allow (`test_telegram_tool_guard.py` `linked_gateway`, which I0 gives `r14=`) and fails when a
tool has no skill, two skills, a pattern matches nothing, or a read tool has no Telegram class;
`scripts/skill_coverage.py` prints the table for the guide and the build book. **Uses:** the turn
offer (D9), `skills_open`, "what can you do" in No-AI (D12), `GET /v1/skills`. No UI change.
"Without code changes": regrouping, words and the offer are data; a new *ability* still needs a
reviewed tool (owner question 9 for skills he defines himself). The guide's three cards labelled
"Knowledge Base & Memory" are relabelled "Research & Intel (knowledge and memory)" at I1: the
project's ten skills have no such skill.

**D12 · No-AI pass 2 (D).** `offline/phrases_r14.py`, anchored, conservative, tried with the other
extra routers before pass 1 (and so before the generative check, fact 12). Each ends in a gateway
call or a fixed line:

| He says (examples) | Tool |
|---|---|
| "add milk and eggs to my grocery list" / "what's on my shopping list" / "remove milk from …" | `grocery_add` / `grocery_list` / `grocery_remove` |
| "what's expiring in my vault" / "which documents expire soon" | `vault_expiring` |
| "where did I put my passport" / "I kept the keys in the drawer" | `belongings_where` / `belongings_put` |
| "is the house armed" / "home status" / "arm the alarm" | `home_status` / `home_arm` (disarm never: "Disarming is only in the Home panel, Sir.") |
| "where's my parcel" | `gmail_track_packages` |
| "check my email" / "any new mail" | `gmail_inbox_summary` (plain code) |
| "what did I delete" | `deleted_list` |
| "what do you remember about Lekha" | `memory_search` |
| "what time is it" / "what's the date" | fixed line from the clock |
| "when was my last backup" / "test my backup" | `vitals_backups` / `vitals_drill_start` (a card) |
| "book a plumber for tomorrow morning" | `maint_service_request` |
| "what can you do (without the AI)" | fixed list from the register: the 11 skills, and what works with the AI off |

The rules' and the gateway's checks apply as for any call (Telegram classes, rows, cards on a
spoken write).

**D13 · Leftovers taken (hardening, small).** (1) Missing `auth_time` on a re-sign-in is **not**
fresh: "Google didn't confirm a fresh sign-in; try again" (`api/auth.py:166–174`; OpenID Connect:
when `max_age` is sent `auth_time` must come back, so refusing without it is safe); (2) a new show
lock keeps the earlier `sessions_valid_after` mark (`buildbook/lock.py:120–124`); (3) the console
covers the page while a lock re-check answers 503 `lock_unreadable` (console.js, ≤ 10 lines);
(4) `GET /v1/notes/export` is audited (agent `privacy`, count only); (5) the Telegram re-plan card's
first line comes from the stored plan's label, never the model's argument (R11.1 L3); (6) the UPI
cap becomes `bill_pay_cap_inr` (₹1,00,000 default, bounds 1–1,00,000: a deploy-time setting he can
only lower, not a console control), read by both constants' users (fact 13); (7) a held overnight
`home_offline_idle` is dropped when the laptop is back before the morning summary (an armed
`home_offline` is never dropped: a test); plus vendor text out of errors (D9), the Alerts rows (D6),
the Home-off clock (D7). Deploy: stop creating the unneeded Vitals index (the one already made stays;
deleting it is optional and free); **no TTL policy** (fact 10): Part D corrects the docstring at
`people/cache.py:6–7` instead. The deploy calls only `deploy/backup_setup.sh --status` (read only,
D4).

**D14 · Version and persona.** `__version__ = "14.0.0"` at I0 (`src/jarvis/__init__.py`,
`pyproject.toml`; pins `test_about.py:24`, `test_r11_1_seams.py:73`, `test_r7_seams.py:110`); the
build book names R14 from it. Persona p7.0 → **p14.0** at I1 (the persona is pinned in 19 test files,
among them `test_r1_seams.py:291`): TOOLS_RULE adds "This turn you may hold only some of your tools.
If he asks for something none of them does, call skills_open first; never say you can't before
that." BACKUP line: "Backups are kept 7 days; you tell him when the last one was; a restore drill
starts only from its card."

**D15 · Guide.** I0 lists cards **C66** Backups and restore drill, **C67** Self-health watch, **C68**
Skill register and the turn's tools as PLANNED (every new collection named); I1 fills them, edits
"No backups" (fact 9), adds "Restoring for real" to §8 (Part A's runbook, D4), the measured cost to
§9 (D8), the change log and edition line.

**D17 · Coverage measured, and ratcheted towards 80 %** (the owner, 14 Nov 2026, 13:45 IST: "add
them"; ₹0; built at I0). Nothing measured coverage before R14 (no pytest-cov, nothing in CI), though
the ECC rules set an 80 % target. `pytest-cov` (MIT; coverage.py Apache-2.0) joins the dev extra with
a lower bound, like the other dev tools (`pytest-cov>=7`; dev tools are not in the lock or the
licence table, which list the image's runtime packages). CI's unit job on Python 3.12 only runs
`pytest -q --cov=jarvis --cov-report=term-missing:skip-covered --cov-report=json:coverage.json`;
`scripts/coverage_floor.py` writes the total to the job summary and fails only when it drops below
the committed floor `scripts/coverage_floor.txt` (a whole percentage that only goes up; the agents'
hook refuses a lower one). The 3.11 job runs plain `pytest -q`, not slowed. **Measured at I0** on
the whole 3.12 suite (14,910 tests, statement coverage of `jarvis`): **95.33 %** (65,954 of 69,187
statements), 15.3 points above the 80 % target, so the floor is **95**: a ratchet that keeps it
there (each part's new package must hold its own 80 %, BRIEF-COMMON). Branch coverage is not
measured (a later choice).

**D18 · A GateGuard hook for the coding agents** (the owner, same message; ₹0; built at I0). CLAUDE.md
already said "No `rm -rf`, force-push, or edits to lint/format configs to make errors disappear", but
nothing enforced it. `.claude/settings.json` runs `.claude/hooks/guard.py` (standard library only,
fast) before every Bash, Edit, Write and MultiEdit call. It reads the hook's JSON and blocks (exit 2,
one line) only clearly dangerous actions: a force push (`--force`, `-f`, `--force-with-lease`,
`--mirror`, a `+refspec`) or a push to `main` / `master` (a refspec, a delete, or a bare push while
that branch is checked out); `git reset --hard` onto a remote ref; deleting `main`; `rm` with
recursive and force flags outside `/tmp/`, `/home/claude/wt/`, `.claude/worktrees/`, `build/` and
`dist/` (never `/`, `~`, `src`, `tests`, `.git`, nor a path it can't read such as `$HOME/x`); writes
to `.env*` and key files, a private key block, a shell redirect into `.env*`; edits that switch a
check off in `[tool.ruff]`, `[tool.mypy]`, `ruff.toml`, `.ruff.toml`, `mypy.ini` or `setup.cfg`'s
lint sections (more ignores or excludes, fewer selected rules, a strictness flag turned off, an
`ignore_errors`, a section removed, a new `ruff.toml` / `mypy.ini`), and a lower
`scripts/coverage_floor.txt`. Everything else passes untouched; unreadable input or an error inside
the hook is allowed with a note, so it can never jam a session; a heredoc's body is data, not a
command. CLAUDE.md and BRIEF-COMMON say a blocked action means stop and report, never work around
it; every command in BRIEF-COMMON passes it (`tests/test_claude_guard.py`: a table of the Workshop's
own commands and the blocked ones). Not a security boundary against a hostile agent (a determined one
could spell a command another way); it stops the mistakes the rule names.

**D16 · Deferred, with reasons.**

| Item | Why not now |
|---|---|
| Streamed tool loop (R5 D15) | Latency, not cost or safety; all five providers + brain (D9) |
| Trailer after the history (A1 choice (a)) | Changes the prompt shape (persona and voice evals, the memory block's safety rules); ≈ ₹70 a month at the mix; the ledger shows how many replies come within 5 minutes |
| Persona split per skill; 1-hour cache; fast tier for simple replies | Need ledger data / safety-eval pass; owner question 7 |
| A "Run a restore drill" button on Vitals; a tap card for the booking site | New console controls and a new checked card type; "test my backup" by voice or chat brings the card, and the site's address is in the text |
| Firestore reads/writes via Cloud Monitoring | New permission and API; size from backup stats suffices |
| A copy outside Google | It would be an unlocked file of conversations; owner question 5 |
| R4: one `KeyedLocks`; one `RateLimiter` style | Refactors; one owner, no risk today |
| R4: `BrainMode.current` "none" if any owner is | Fail-closed by design; one owner |
| R4: refused people target in process only | By design: a refused private name is never stored (R4 I2 F3) |
| R5: phrase-hint dead code; memo `dropped` test | Voice release |
| R11: "next calendar event" source; shared Gmail helper; Approvals refresh from Today | Features or refactors |
| R1: brief inbox copy has no row of its own | His own switch is the consent (R11.1 I1-NOTES) |
| R11.1 L4 (300 ms settle in boot tests); R7 follow-ups | Accepted in their reviews; R7's left items are "not verified live" |
| mypy's 9 baseline errors; `vault/service.py` 876 lines | Cross-part chores; a crypto split during a data-safety release adds risk |
| `ruff format` flags in two R4 INTEGRATION notes | Notes only, not code |

## Data model (prefix `jarvis_`; every collection named in the guide's cards before code uses it)

| Collection | Part | Holds | Sealed | Kept |
|---|---|---|---|---|
| `backup_canary/{yyyymmdd}` | A | nonce hash, sealed nonce, key fingerprint, version, time | nonce: `backup_probe` | 30 days |
| `backup_status/current` | A | schedule seen (and first seen), newest READY backup: name, snapshot time, size, document count | no | overwritten |
| `backup_drill/current` | A | state, backup name, snapshot time, expected count and size, operation, cursors, check results, manual drills this month | no | overwritten |
| `backup_drills/{yyyymm}` | A | result: passed, reason code, counts, collections, samples and items compared, vault item opened, canary ok, minutes, ₹ estimate | no | 13 months |
| `selfwatch/jobs`, `selfwatch/clocks`, `selfwatch/deploy`, `selfwatch/spend` | B | job streaks; clock stamps; revision and version; daily month-total snapshots (₹) | no | overwritten (spend 15 days) |
| `selfwatch_errors/{yyyymmdd}` | B | per hour: count; per logger name: count (≤ 50 names) | no | 14 days |
| `selfwatch_told/{uid}_{key}` | B | once-only claims (kind + cause + day hash) | no | 30 days |
| `token_ledger/{uid}_{yyyymmdd}` | C | token and character counts by part, offers, skills opened | no | 90 days |

Keyring purposes 21 → **22** (`backup_probe`). Never stored: a vault item's plaintext or hash outside
the drill's memory, a nonce in clear, a key, a log message, a prompt, a reply. Privacy rows (through
I0's `r14_privacy_sources` slot): `token_ledger` (counts, 90 days) and `selfwatch_told` (30 days)
are listed with no export or delete (counts only); "Backups" (Google's copies, 7 days) is Part A's.

## Per item: layer, skill, failures, security, evals, cost

| Item | Layer · skill | Failure modes and handling | Security and privacy | Tests and eval (negative control) | ₹ a month |
|---|---|---|---|---|---|
| A Backups + drill | L7, cross-cut ops · Code & DevOps | No schedule / no permission → Vitals "not set up", no alert before the set-up; stats empty → "not yet"; restore slow → resumes next tick; verify over budget → resumes; delete fails → retried, alert after 2 days then weekly; key changed → canary fails, drill "failed: key"; nothing compared → "failed" | D4's five locks; plaintext only hashed in memory; drill copy deleted the same morning | `evals/r14/backup.py`: passes on fakes; a missing document fails the count; a changed key fails; a live write is refused; a `(default)` target is refused before the call; a stale backup alerts once; empty stats never start. **Controls:** `ReadOnlyDocs` swapped for the writable store → "no live write" fails; a comparison keyed on `update_time` with restamped copies → "nothing compared" → the drill must not pass | ≈ ₹4.9 at 100 MB (backups 7 × 0.1 GiB × ₹2.86 = ₹2.0; a restore ₹1.9; counts ≈ ₹0; samples ≈ ₹0); ≈ ₹39 at 1 GiB (₹20.0 + ₹19.05); a left-over copy ₹1.4 (100 MB) to ₹14 (1 GiB) a month |
| B Self-health | cross-cut observability, L8 · Code & DevOps | A handler that fails never logs itself; writes batched every 5 min; both clocks dead → Vitals line only | Logger names and counts only; alert text fixed | `evals/r14/selfwatch.py`: 3 failures → one alert, recovery → one info, clock gap, brief missed at time + 60, 31 errors an hour, spike, revision, nothing rings at 02:00, a whole-Firestore outage → at most 1 ring. **Controls:** streak counting off → "once per streak" fails; aggregation off → more than 1 ring; the outcome ignored → `job_failing` on a skip | ₹0 (≈ 600 reads, 300 writes a day) |
| C Cost + register | L3/L4, L5 · Code & DevOps, Finance & Analytics | Offer misses a tool → `skills_open`; offer crashes → all tools; ledger write fails → logged, reply unaffected | Counts only; vendor text never leaves `jarvis.llm` | `evals/r14/offer.py`: 120 labelled messages, needed tool offered in ≥ 98 %, average ≤ 30 tools; constant tools across rounds; window counts blocks; ledger sums. **Controls:** the words table emptied (no sticky, no history) → recall < 98 %; counting off → a long tool session exceeds `session_max_chars`; the hint off → one breakpoint in the mock's record | saves ≈ ₹1,460 at 20 replies a day (D10) |
| D No-AI 2, rows 101/102, fixes | L3, L5, L6 · per row | A phrase that doesn't match → pass 1 → fixed line | Disarm never routes; service text has no address or phone; each fix has its own test | `evals/r14/noai.py`: every row of D12 routes with zero provider calls; generative asks keep `NO_AI_LINE`. **Control:** R14 phrases off → their cases fail | ₹0 |
| I0 contract | cross-cut | A part that breaks the contract is left out ("setup failed") | — | `evals/r14/contract.py` (built at I0): every part builds, owns only its tools, routes, jobs and services. **Control:** a part offering a tool outside its family → refused → the case fails | — |
| Needles (I1) | — | — | — | `evals/r14/needles.py`: a planted vault plaintext, nonce, key, exception message, prompt word never reaches any document, log line, audit detail or alert. **Control:** masking off | — |

## Part split (four builders, worktrees, branches `r14-a` … `r14-d` from `r14-i0`; disjoint files)

Each part plugs in through `build(ctx: HardeningContext) -> HardeningPart` (`jarvis.hardening.ports`,
I0) in its part module; `api/r14_wiring.py` leaves out a part that breaks the contract.

- **A · Backups and the drill.** `backup/{part,canary,readonly,drill,verify,walk_checks,vault_probe,
  log,status,tools,jobs,vitals,privacy}.py` (I0 owns `backup/__init__.py`, `backup/ports.py`; the
  `part.py` stub is A's to fill), `storage/firestore_admin.py`, `storage/firestore_walk.py`,
  `api/backup.py` (I0 stub; `GET /v1/backup`, `POST /v1/backup/drill` → the same card),
  `deploy/backup_setup.sh` (I0 stub with both modes; A fills the set-up, never `--status`'s
  read-only rule), `tests/test_r14_a_*.py`, `tests/r14_fakes_a.py`, `evals/r14/backup.py`,
  INTEGRATION-A.md (with the guide's restore runbook text). Tools `vitals_backups` (R1),
  `vitals_drill_start` (R2, `ask_when` always, `bulk_ok=False`). The backup kinds, the size item and
  the "Backups" privacy row are A's alone. `security-reviewer` required.
- **B · Self-health.** `selfwatch/{part,ledger,clocks,errors,brief_check,spend,deploys,texts,jobs,
  status,vitals}.py` (I0 owns `selfwatch/__init__.py`, `ports.py`), `api/selfwatch.py` (I0 stub; `GET
  /v1/selfwatch`), `notify/store.py` (drop a held kind) and the laptop-back path that sends
  `home_online` (D13 item 7), `tests/test_r14_b_*.py`, `tests/r14_fakes_b.py`,
  `evals/r14/selfwatch.py`, INTEGRATION-B.md. Reads backups only through `BackupStatus`.
- **C · Cost and the register.** `skills/{part,catalogue.json,registry.py,offer.py,open_tool.py}` (I0
  owns `skills/ids.py`, `skills/ports.py` and the `offer.py` stub), `billing/ledger.py` (I0 stub),
  `core/window.py`, `llm/{base,router,fallback,anthropic_provider,gemini_provider,
  openai_compat_provider,local_provider,mock_provider,factory}.py`, `api/skills.py` (I0 stub; `GET
  /v1/skills`, `GET /v1/costs/ledger`), `scripts/skill_coverage.py`, `tests/test_r14_c_*.py`,
  `tests/r14_fakes_c.py`, `tests/test_r14_skill_coverage.py`, `evals/r14/offer.py`, INTEGRATION-C.md
  (with the TOOLS_RULE text). `security-reviewer` on the `jarvis.llm` change.
- **D · No-AI pass 2, rows 101/102, the leftovers.** `offline/{r14_part,phrases_r14}.py`,
  `helpers/house/{upkeep,service_request,tools}.py`, `helpers/sources.py` and
  `helpers/today/{models,upi}.py` (the two cap constants), `people/cache.py` (the docstring),
  `api/auth.py`, `buildbook/lock.py`, `api/notes.py`, `series/cards.py`, `api/static/console.js`
  (≤ 10 lines), `deploy/cloudrun.sh` (index out, a non-fatal call to `backup_setup.sh --status`),
  `tests/test_r11_b_chores.py` (the STARTERS pin), `tests/test_r14_d_*.py`, `tests/r14_fakes_d.py`,
  `evals/r14/noai.py`, INTEGRATION-D.md. `security-reviewer` required.
- **All parts:** test first; functions ≤ 50 lines, modules ≤ 400, files ≤ 800; only the planned
  collections, job names, kinds and tool names; alerts only through the notifier with the fixed
  templates; `docs/plans/r14-integration/BRIEF-COMMON.md`.

## The I0 seam list (branch `r14-i0`; the integrator owns these files)

1. **Version** `14.0.0` (`__init__.py`, `pyproject.toml`; pins in `tests/test_about.py:24`,
   `test_r11_1_seams.py:73`, `test_r7_seams.py:110`); the build book names "R14" with
   `r14-hardening.md` first.
2. **Alert kinds** + 9 (D6): `alerts.py` `R14_ALERT_KINDS`, `notify/ports.py` `DEFAULT_URGENCY`,
   `notify/policy.py` `DAYTIME_RING_KINDS` (+7), `notify/storm.py` the `SELF_KINDS` soft table (and
   its rollback), `notify/held.py` words (+9, + `health_fault`, `vitals_critical`),
   `console-alerts.js` `KINDS` (+11 rows), `webpush/service.py` `TARGETS` (+9),
   `buildbook/plain.py` `ALERT_WORDS` (+9); pinned 43 → 52 in the five tests of fact 5, the exact
   `DAYTIME_RING_KINDS` (`test_r51_seams.py:45`) and `TARGETS` (`test_r7_a_push.py:43`);
   `SOFT_URGENT_KINDS` (`test_r51_int_notify.py:47`) is unchanged.
3. **Keyring** `backup_probe` (22; the four pins of fact 6).
4. **Permissions:** no new row (49 stays; the save cap 51 stays); `tests/test_permissions_policy.py`
   `EXPECTED` gets `vitals_backups` (R1, vitals), `vitals_drill_start` (R2, vitals_change),
   `maint_service_request` (R1, household), `skills_open` (R1, no row: the risk default applies);
   the `vitals` and `vitals_change` hints name backups and the drill; `test_telegram_tool_guard.py`
   classes them open and its `linked_gateway` gains `r14=`; the nouns (backups, drill, skills,
   service, request) join `TOOL_NOUNS` (`tests/test_r11_1_b_guard.py`; "start" and "open" are
   already action words, so `understand/words.py` needs none).
5. **Settings** (`config.py`): `selfwatch_enabled` (on), `selfwatch_fail_streak` 3 (2–10),
   `selfwatch_errors_per_hour` 30 (5–500), `selfwatch_brief_grace_min` 60 (15–240),
   `selfwatch_spike_factor` 3.0 (1.5–10), `selfwatch_spike_min_inr` 50 (10–1,000),
   `cloud_run_revision` (env `K_REVISION`), `backup_checks_enabled` (on), `backup_max_age_h` 36
   (25–200), `backup_drill_enabled` (on), `backup_drill_day` 1 (1–28), `backup_drill_max_inr` 100
   (10–1,000), `backup_drill_manual_per_month` 2 (0–4), `tool_offer` `by_skill` | `all`,
   `tool_offer_sticky_s` 300 (0–3,600), `history_tool_result_chars` 2,000 (500–12,000),
   `cache_history` (on), `token_ledger_enabled` (on), `bill_pay_cap_inr` 1,00,000 (1–1,00,000).
   `DRILL_DB` is a constant, never a setting; `firestore_database == DRILL_DB` is refused (D4 lock 5).
6. **The contract and the stubs:** `hardening/ports.py` (`HardeningPart`, `HardeningContext`,
   `PARTS`, `TOOL_FAMILIES`, `ROUTE_PREFIX`, `STATUS_ROUTE`, `COLLECTIONS`, `R14_JOB_NAMES` =
   `backup_canary`, `backup_drill`, `selfwatch_daily`, `selfwatch_clock`, `SERVICE_OWNER`);
   `backup/` (`ports.py`: `DRILL_DB`, `drill_target`, `BackupAdmin`, `DrillWalk`, `ReadOnlyDocs`,
   `BackupFacts`, `BackupStatus`; `part.py`), `selfwatch/` (`ports.py`: the job outcome, the
   observer, `SelfwatchFacts`; `part.py`), `skills/` (`ids.py`: the 11 ids, labels, `SkillSummary`;
   `ports.py`: `OfferContext`, `ToolOffer`, `LedgerCall`, `TokenLedger`, `BrainSlots`; `offer.py`
   `offer_all`; `part.py`), `billing/ledger.py` (no-op), `offline/phrases_r14.py` (empty),
   `offline/r14_part.py`; stub routes `api/backup.py`, `api/selfwatch.py`, `api/skills.py` and I0's
   `GET /v1/r14` (each part's ready word); `deploy/backup_setup.sh` with `--status` (read only,
   always exit 0; a test greps that it never runs `create`, `update`, `delete` or
   `add-iam-policy-binding`) and the interactive set-up (prints "not built yet").
7. **Wiring:** `api/r14_wiring.py` (`wire_r14`, `r14_tick_jobs`, `r14_clock_jobs`,
   `install_r14_routes`, `r14_tools`, `r14_vitals`, `r14_privacy_sources`, `install_r14_phrases`, the
   errors handler installed once on the root logger from Part B's `services["log_handler"]`, the
   tick observer from `services["tick_observer"]`); `api/tick_wiring.py` takes `_tick_jobs`
   (`app.py:420–432`) and the D7 clock list, and `finish_wiring(app)` binds the tick jobs, the
   clocks and the brain's slots; `api/app.py` ends ≤ 735 (the tick-list pins
   `test_r11_wiring.py:294–295`, `test_r7_seams.py:436` move to `tick_wiring.py`); `tools/setup.py`
   `r14=`; `vitals/own.py` + `api/selfcheck_wiring.py` one Vitals slot (`OwnSources.r14`: R14's
   items, ordinary Vitals items, so `console-vitals.js` is untouched); `api/personal.py` the
   `r14_privacy_sources` slot; `api/home.py` + `home/watchdog.py` the shared `clock_jobs` (D7, the
   brief's owners, `selfwatch_clock` first); `ticks.py` the outcome (`ok`, `failed`, `timed_out`,
   `skipped`) to an observer passed to `run_jobs` (never raises) and `api/brief.py` reports its sweeps
   to it; `core/brain.py` two slots (`tools=` through `BrainSlots.tools` at `:430`,
   `BrainSlots.record` after `:432`).
8. **Guide and book:** cards C66–C68 listed PLANNED (every collection of the data model), the L5
   row, edition line, change log; `scripts/arch_coverage.json` if needed; build book `layers.py`
   (`backup` → L7, `selfwatch` and `hardening` → cross-cut, `skills` → L5).
9. **Evals and fakes:** `evals/r14/run.py` (R7's runner shape: `PART`, `BUILT`, `cases()`,
   `control()`), stub parts `backup`, `selfwatch`, `offer`, `noai`, `needles`, and I0's built
   `contract`; gated in `evals/run_all_mock.py` as `("r14 (gated)", […, "evals/r14/run.py",
   "--mock"], True)` after R7's line; `tests/r14_fakes.py`; `tests/test_r14_seams.py`,
   `tests/test_r14_wiring.py`.
10. **Console:** only the Alerts card's rows (seam 2). The CSP stays as it is (pinned by four
    tests; R14 adds no script and no origin). `console.html` stays 782.
11. `docs/plans/r14-integration/BRIEF-COMMON.md` and `I0-NOTES.md`.
12. **Coverage and the hook** (D17, D18): `pytest-cov` in the dev extra, CI's 3.12 coverage step and
    floor check (`scripts/coverage_floor.py`, `scripts/coverage_floor.txt`), `.claude/settings.json`,
    `.claude/hooks/guard.py`, the CLAUDE.md line; tests `tests/test_coverage_floor.py`,
    `tests/test_claude_guard.py`. They are tooling outside `src/jarvis`, so the guide needs no card.

## Decisions taken at I0 (v14.0.2; safe defaults, listed for the owner)

1. Cache: the trailer stays before the messages (A1 choice (b)); the history hint is on, applied by
   the Anthropic provider itself; no brain slot for it. Choice (a) is deferred (D16).
2. No new console controls: R14's Vitals lines are ordinary Vitals items sent by the server; the
   drill starts from "test my backup" (voice or chat, a card); the Privacy panel's "Backups" row is
   server-sent. Only the Alerts card gains rows.
3. The booking site's address is text in the request, not a tap card.
4. The drill's delete right is a custom role (`jarvisDrillCleanup`) on `jarvis-drill` only, not a
   conditioned `datastore.owner`.
5. Self-health's own cap: at most 3 messages an hour, one per kind and subject per 30 minutes; one
   aggregated `job_failing` an hour.
6. No backup alerts until the set-up has run once.
7. At most 2 manual drills a month; the drill card is never part of Approve all.
8. The guide's new cards are C66–C68 (C61–C65 are taken).
9. A fifth lock: JARVIS refuses to start with `firestore_database` set to `jarvis-drill`.

## Needs the owner (safe defaults; none blocks the build)

1. **Turn on backups** (about ₹5 a month at 100 MB, about ₹40 at 1 GB): nothing changes until you run
   the one-time step below; until then Vitals says "Backups: not set up", and JARVIS sends no
   reminders about backups.
2. **How long to keep each copy:** 7 days (default). Longer costs more and keeps deleted things
   longer (14 days ≈ ₹7 a month instead of ≈ ₹5 at 100 MB).
3. **Monthly restore drill** on the 1st, automatic, at most ₹100 a drill (default yes), and at most 2
   manual drills a month, about ₹2 each at today's likely size.
4. **Google's "any charge" e-mail** (₹1 budget) will arrive each month once backups cost money.
   Default: leave it; or raise it to ₹100 in Billing → Budgets.
5. **A copy outside Google** (a file on your laptop): default no (it would hold your conversations
   unlocked).
6. **Send only the tools a message needs** (saves ≈ 45 %): default on; "all tools" is one setting.
7. **Simple replies on the cheaper fast model:** default no.
8. **"JARVIS was updated" notice** rings in waking hours: default yes (you'll hear about every
   merge); or feed only.
9. **Skills you define yourself** in the console (row 112's fullest sense): default later.
10. **Car service** every 6 months (default); booking site Urban Company (default), its address
    given as text.
11. **Error alert** at 30 errors an hour; **spend alert** at 3× normal and ₹50 or more, after a week
    of history (defaults).

## The owner's one-time steps (after the R14 PR is merged and deployed)

1. Open https://shell.cloud.google.com and check the project line shows your JARVIS project.
2. Type `cd ~/jarvis-web && git pull` and press Enter (if the folder is missing:
   `git clone https://github.com/Shark2558/jarvis-web && cd jarvis-web`).
3. Type `bash deploy/backup_setup.sh` and press Enter.
4. Read the cost lines it shows ("about ₹5 a month at 100 MB, about ₹40 at 1 GB; a monthly drill
   about ₹2 at 100 MB, never over ₹100"), then type **YES** to go on. Anything else stops it with
   nothing changed.
5. Wait for "Backups: on, kept 7 days · Delete protection: on · Drill access: on". If a line says
   "could not", send that screen to the Workshop; nothing else breaks.
6. Tomorrow, open JARVIS → Vitals: "Backups: last copy today at …" and the real monthly figure.
7. Optional: say or type "test my backup", approve the card; the result shows the next morning.

## What can't be verified from this workspace

Google calls of every kind (the shell can't reach Google): the schedule, a real restore and its
time, `restoreAdmin` creating `jarvis-drill`, the conditioned custom role deleting it (and only it:
Google documents `resource.name` conditions only for `roles/datastore.user`), delete protection
blocking a delete, what a restored database inherits (delete protection, `update_time`), when
`Backup.stats` fills; the real database size (so the real ₹); whether Mumbai prices differ from the
single table (S2); `K_REVISION` on the live service (S5 not fetched); real token counts (here:
characters ÷ 4 on the 135 tools the fakes build; the live set is about 120–140); how often Claude
reuses the cache with changing tool sets; whether Google sends `auth_time` on every `max_age=0`
re-sign-in (D13 item 1 refuses when it doesn't); the Urban Company address; the pricing page itself
(`cloud.google.com/firestore/pricing` was blocked; its `?authuser=3` copy was read).

## Risks

- **`restoreAdmin` can create databases**: a stolen jarvis-run could restore copies and run up
  restore charges. Bounded by the code's single fixed id and ₹100 cap, the manual-drill cap, the ₹1
  budget e-mail, and it can never delete or overwrite `(default)` (delete protection + the
  conditioned custom role).
- **Writes to `(default)` rest on code alone** (`datastore.user` is unconditioned): `ReadOnlyDocs`
  on both sides, the id check before any call, the import test, the start-up lock.
- **Privacy promise changes**: deleted data lives up to 7 days in backups (D3); said everywhere.
- **Key loss** makes every backup useless: the deploy never rotates the key (tested); the canary
  catches a changed key within a day. The key and the backups share a project (D3).
- **A missed tool** after trimming: `skills_open`, the eval's 98 % recall bar, the kill switch.
- **Cache misses** when the offer changes: sticky offer within 5 minutes; the ledger shows it.
- **Alert noise**: aggregation, once per streak/day/revision, held at night, their own soft cap of 3
  an hour, every kind switchable, nothing about backups before the set-up.
- **Line budgets**: `app.py` and `gateway.py` full; I0 frees lines first; no part touches either.
- **2 CPUs here**: targeted tests only; the full suites run in CI (4 CPUs).

## Sources (read 14 Nov 2026)

| # | Source |
|---|---|
| S1 | Firestore, "Back up and restore data" — https://docs.cloud.google.com/firestore/docs/backups |
| S2 | Firestore pricing — https://cloud.google.com/firestore/pricing?authuser=3 |
| S3 | Firestore, "Security for server client libraries" (IAM roles) — https://docs.cloud.google.com/firestore/docs/security/iam |
| S4 | Firestore, "Create and manage databases" — https://docs.cloud.google.com/firestore/docs/manage-databases?authuser=4 |
| S5 | Cloud Run, container runtime contract — https://docs.cloud.google.com/run/docs/container-contract |
| S6 | Claude, "Prompt caching" — https://platform.claude.com/docs/en/build-with-claude/prompt-caching |
| S7 | Owner's workbook rows 101–113, sheet "JARVIS Requirements" (Google Drive) |

## Change log

| Version | Date | Release | What changed | By |
|---|---|---|---|---|
| v14.0.1 | 14 Nov 2026, 13:40 IST | R14 | First edition: summary for the owner, the workbook rows 101/102/109–112 read from his sheet, code facts with file:line, Google's terms, D0–D16 (backups and a drill that can't write live, self-health, the token ledger and free cost wins with ₹ before/after, the skill register, No-AI pass 2, rows 101/102, the leftovers taken and deferred), data model, per-item evals with negative controls, the A–D split, the I0 seam list, owner questions and one-time steps, what can't be verified, risks, sources | 🛠 Mark XVIII |
| v14.0.2 | 14 Nov 2026, 14:30 IST | R14 | The owner's scope addition (14 Nov, 13:45 IST, "add them") written in at I0: D17 coverage measured (95.33 % at I0, floor 95) and ratcheted in CI on 3.12, D18 a GateGuard hook for the coding agents (seam 12); seam 4's nouns corrected (TOOL_NOUNS only). Plan review 1 written in; Status Ready. A1: cache within the reply only (choice (b)), the provider applies the hint, D10 reworked at ₹95.24 (₹5.42 → ₹2.99 a reply, ≈ 45 %). A2: empty stats never start a drill, comparisons on the app's own fields, `count()` aggregations, "nothing compared" fails. A3: clean-up whatever the switches say, `get_database` decides, delete protection off first, the 5-minute wait, the left-over cost and a weekly alert, 2 manual drills, `bulk_ok=False`. A4: the deploy runs only `backup_setup.sh --status`, the cost line is a range, no TTL policy. A5: the locks said honestly, `ReadOnlyDocs` on both sides, an import test, lock 5 in `Settings`, a custom role. A6: one aggregated `job_failing` an hour, R14's own soft table (3 an hour), outcomes with skips, `selfwatch_clock` first, no loops, no backup alert before the set-up, the spike from daily differences after 7 days. A7: the clock jobs run for the brief's owners. A8: Vitals and Privacy server-sent (no console change), A alone produces the backup kinds and size (`BackupStatus`), no third brain slot, the booking address as text. B: 14 lines corrected (prices `:30`; 135 tools; the ₹0.17 reading; all four error classes and the router log; the two UPI constants; the TTL; the runbook; the version, kind, keyring and tick-list pins; 14-day and 1 GiB costs; the STARTERS pin) and one found at I0 (cards C61–C65 are taken: C66–C68). C: the 12 seams joined to the I0 list. D notes taken: the tool-use names in the offer, shortened results keep their flags, the async admin client, the rate limit, the Vitals index stays, the data-safety limit and the runbook lines. Decisions taken at I0 listed | 🛠 Mark XVIII |
