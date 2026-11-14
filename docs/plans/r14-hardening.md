Version v14.0.1 · 14 Nov 2026, 13:40 IST · Release R14 · Status: Draft · Owner: 🛠 Mark XVIII

# Release R14 — Free hardening (`v14.0.0`)

**Phase:** 7 (evals, hardening, cost), pulled forward by the owner (build order of 14 Nov: free and
pending items first). **Type:** free to build; backups add a small Google charge that starts only when
the owner runs his one-time step (about ₹5 a month at 100 MB of data). No new paid service, no new
secret, no new Cloud Scheduler job. **Branches:** I0 `r14-i0` (from `main` @ `5db4f05`, R7 live,
v7.0.0) → parts `r14-a` … `r14-d` → integration `r14-i1` → PR `v14.0.0 · R14 Free hardening · Mark
XVIII`. Every commit carries `JARVIS-Version: v14.0.0` and `JARVIS-Mark: XVIII`. Read on `5db4f05`.

## Summary for the owner (plain words)

1. **Your data gets a safety copy, and we prove it works.** Today JARVIS keeps no copy of its
   database: one bad mistake would lose your vault, notes, health and sleep log and settings. After
   your one-time step, Google makes a copy every day and keeps each for 7 days. Once a month JARVIS
   opens the newest copy in a separate, throw-away database, checks that nothing is missing and that
   it can still unlock one of your locked documents, then deletes the throw-away copy. It can never
   write to your real database while it does this. Cost: about ₹5 a month at today's likely size,
   at most about ₹40 if your data ever fills Google's free 1 GB. JARVIS shows the real figure.
2. **JARVIS watches itself and tells you when something is wrong**: a background job failing again
   and again, its clock stopping, the morning brief not made, errors piling up, a day's AI spend far
   above normal, a new version going live, a missed or broken backup. Same alert rules as today
   (quiet hours, caps, switches in the Alerts card).
3. **Cheaper replies.** Each reply sends JARVIS's whole rule book and all ~120 tool descriptions to
   Claude. R14 sends only the tools a message needs (any others on request), stops old tool results
   from riding along in every later reply, and lets Claude reuse more of what it has already read.
   Estimate: about 40 % less per reply (from about ₹4.7 to about ₹2.7 on the middle Claude model).
   JARVIS will measure the real numbers and show where the money goes.
4. **A skill register.** Every tool is filed under one of JARVIS's 11 skills, with its risk, its
   permission row and its Telegram rule. A check stops any new tool that isn't filed. New groupings
   of existing tools are a data change, not a code change.
5. **More works with the AI off**: groceries, vault expiry, "where did I put…", home status, parcels,
   inbox summary, recently deleted, time and date, memory search, backups, "what can you do".
6. **Your car and home services (rows 101, 102).** The car's maker offers no way in for other apps,
   so the car stays "not possible yet"; its papers already live in the vault with reminders, and
   R14 adds a car-service reminder. For a plumber or electrician JARVIS writes the request and opens
   the booking site or drafts a message to the person you pick; it never books or pays.
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
   `test_r7_seams.py:650`), `tools/gateway.py` 760 = guard (`:242`, `:649`), `console.html` 782 =
   guard (`:246`, `test_r7_seams.py:606`); `console.js` 761, `core/brain.py` 704, `config.py` 656,
   `vault/service.py` **876** (over 800, pre-existing).
2. **Clocks.** Region `asia-south1` (`deploy/cloudrun.sh:48`), `--max-instances 1` (`:548`). Two
   Scheduler jobs (`:647–697`): the brief tick `0,30 4-11 * * *` and the watchdog `*/5 * * * *`
   (created whatever Home is set to). The tick runs its sweeps, then `run_jobs`
   (`api/brief.py:129–160`). A failed or timed-out job is **logged and reported "failed" in the
   answer only** (`ticks.py:68–95`); in the watchdog an advisory job's failure becomes "degraded"
   and a log line (`home/watchdog.py:81–83`, `:236–241`). Nobody is told.
3. **Home off.** The 5-minute route then runs **only the helpers' clock** (`api/home.py:148–172`).
   The systems check (`api/selfcheck_wiring.py:180–192`) and R7's `mobile_clock`
   (`api/r7_wiring.py:179–181`) join the watchdog only when it exists, so with Home off they run in
   the morning window only. R5.1 D4 ("around the clock") holds only with Home on.
4. **Self-health today.** Probes: brain, google, telegram, home, docs, redis, web
   (`health/probes.py:130–254`); Vitals: AI spend, voice allowances, Google SKUs, keys
   (`api/selfcheck_wiring.py:68–103`). Nothing watches the clocks, job streaks, error volume, the
   brief's outcome (`brief/service.py:491–497` marks a failed brief and tells no one), revisions,
   backups or the database's size.
5. **Alerts.** 43 kinds (`alerts.py:22–83`; pinned `test_r3_seams.py:165`, `test_r6_seams.py:142`,
   `test_r11_seams.py:66`, `test_r11_1_seams.py:119`, `test_r7_seams.py:231`).
   `storm.SOFT_URGENT_KINDS` = health_fault, vitals_critical (`notify/storm.py:38`). The held words
   (`notify/held.py:14–40`) and the Alerts card (`console-alerts.js:20`) have no entry for
   `health_fault` or `vitals_critical` (R5.1 leftover).
6. **Keyring.** 21 cipher purposes + `webpush_vapid` (`keyring.py:42–75`; pinned
   `test_r7_seams.py:293`, `test_r11_seams.py:163`, `test_r3_seams.py:849`). Root = Secret Manager
   `jarvis-token-key`, made once, never overwritten (`deploy/cloudrun.sh:202`;
   `tests/test_deploy_vault.py`). A backup is only readable with that key.
7. **Permissions.** 49 rows (pinned `test_r1_seams.py:231`, `test_r2_seams.py:576`,
   `test_r3_seams.py:911`, `test_r11_1_seams.py:139`, `test_r7_seams.py:258`); `vitals_*` R1 →
   `vitals`, R2 → `vitals_change` (`permissions/groups.py:444–461`); `maint_*` → `household`
   (`:512–520`).
8. **Firestore.** One `(default)` Native database in asia-south1 (`deploy/cloudrun.sh:411–419`);
   `jarvis-run` has `roles/datastore.user` and `logging.logWriter` (`:471–473`). `FirestoreDocs`
   takes a `database` (`storage/firestore_docs.py:54`) and is the only SDK importer; setting
   `firestore_database` (`config.py:171`). The pinned SDK (google-cloud-firestore 2.34.1) already
   ships `firestore_admin_v1` with `list_backups`, `restore_database`, `delete_database` and
   `Backup.stats{size_bytes, document_count}`: no new dependency. Sub-collections exist
   (`activity/{uid}/d`, `activity_days/{uid}/days`, `deleted_items/{uid}/items`).
9. **Promises to change.** The guide says "No backups … When you delete something it is gone for
   good" (`docs/architecture/JARVIS-Architecture.md:118–119`) and "Firestore has no backups"
   (`:1685–1686`).
10. **Deploy facts.** The people cache says deploy sets a TTL policy on `expires_at`
    (`people/cache.py:6–7`); deploy sets none. The Vitals composite index is still created
    (`deploy/cloudrun.sh:429–437`, the `jarvis_vitals_providers` index) though R5.1 D2 removed the need. The budget alert is ₹1, "any
    charge" (`:372–394`): once backups cost money it will e-mail every month.
11. **Where tokens go** (measured here on the dev app with Google fakes; the live set is larger):
    the persona is 21,338 characters ≈ 5,300 tokens (`core/prompts.py:563–611`); 112 tool schemas are
    48,471 characters ≈ 12,100 tokens (top 20 % of tools = 39 % of it). **Every** model call sends
    every tool (`core/brain.py:430`, `tools/registry.py:20`). One cache breakpoint, on the system
    block (`llm/anthropic_provider.py:115–126`); the conversation is never cached. The history caps
    (`session_max_turns` 40, `session_max_chars` 48,000; `config.py:175–179`) count only
    `t.content` (`core/window.py:34`, `:37`), but a tool-result turn has `content=""` and the result
    in blocks (`core/rounds.py:120`), up to 12,000 characters each (`tools/gateway.py:106`): **tool
    results are never counted**, so a long tool session re-sends every result on every reply.
    Billing records one USD figure a call (`core/brain.py:432`, `billing/service.py:293`), not the
    token split. Prices (`llm/pricing.py:27–29`): Sonnet 5.5 $2 in, $10 out, $0.10 cache read,
    $2.50 cache write; rate ₹95.24 (`billing/fx.py:33`).
12. **No-AI pass 1** (`offline/rules.py:260–288`): notes add/search, timer, remind, systems check,
    vitals, quota, reminders, to-dos, calendar, people research; since then phrase routers for the
    four helpers, study plans and the watch. Everything else answers `NO_AI_LINE` (`:65`).
13. **Leftover facts.** `_reauth_at` treats a missing `auth_time` as now (`api/auth.py:166–174`);
    `ShowLock.set` writes the new lock without the earlier `sessions_valid_after` mark
    (`buildbook/lock.py:120–124`); `GET /v1/notes/export` writes no audit line (`api/notes.py:170–182`);
    vendor text in `LLMAuthError(str(exc))` / `LLMTransientError(str(exc))`
    (`llm/anthropic_provider.py:155`, `:163`; gemini `:133`, `:137`; openai_compat `:161`, `:165`);
    the Telegram re-plan card's first line is the model's own `series` argument (R11.1 I1-NOTES,
    security L3); the console handles 423 only (`console.js:78`, `:101`), so a 503
    `lock_unreadable` leaves the page on screen; the UPI cap ₹1,00,000 is a constant (R11 D7).
14. **Car papers.** The vault already has `vehicle_rc`, `vehicle_insurance` and `puc` with expiry
    reminders at 180…1 days (`vault/models.py:43–59`, `vault/reminders.py:6`); R11's upkeep list has
    `STARTERS` (`helpers/house/upkeep.py:31`).

## Google's terms (read 14 Nov 2026; the shell can't reach Google)

| Fact | Source |
|---|---|
| Up to one daily and one weekly backup schedule per database; retention up to 14 weeks; the daily time can't be chosen; a backup is a consistent point-in-time copy in the database's own location; it holds data and index settings, not TTL policies | S1 |
| A restore writes to a **new** database whose id must be unused; deleting the source keeps its backups; a deleted backup can't be recovered | S1 |
| Backup storage $0.000041096 per GiB-hour (≈ $0.030 per GiB-month, ₹2.86); restore $0.20 per GiB (₹19.05); one table for all locations | S2 |
| Named databases get **no** free quota; reads $0.03 per 100,000 | S2 |
| `datastore.restoreAdmin` = backups get/list/restoreDatabase, databases create/list, operations get/list; `datastore.user` has no backup or database-admin permission; `databases.delete` is only in `datastore.owner` | S3 |
| Per-database IAM conditions: `resource.name=="projects/P/databases/D"`; `--delete-protection` on a database; an id is reusable 5 minutes after a delete; 100 databases a project | S4 |
| Cloud Run sets `K_REVISION` in the container | S5 |
| Claude caching: prefix order tools → system → messages; changing tools invalidates all; 5-minute write 1.25×, 1-hour write 2×, read 0.05× on Sonnet/Opus 5.5; up to 4 breakpoints; 512-token minimum | S6 |

## Decisions (binding)

**D0 · Scope and order.** Four parts: A backups and the drill (headline), B self-health, C cost and
the skill register, D No-AI pass 2, rows 101/102 and the security leftovers. Everything plain code;
the only model calls are the ones replies already make. No new Scheduler job: backups are Firestore's
own schedule; R14's jobs ride the existing tick and watchdog.

**D1 · Connected car (row 101): not possible yet** (decided 14 Nov). Tata's iRA has no API for other
apps, and CERT-In flagged iRA app flaws on 4 Nov; unofficial access is declined. The vault already
covers RC, insurance and PUC with reminders (fact 14). Missing piece only: a service-due reminder:
`helpers/house/upkeep.py` `STARTERS` gains "Car service" every 6 months (offered, never added).
Kilometre-based service needs the car's data: not possible yet.

**D2 · Home services (row 102): prepare, never book.** Urban Company has no public API (decided 14
Nov). New tool `maint_service_request` (R1, row `household` via `maint_*`, skill Task & Productivity,
Telegram open): input job (plumber, electrician, carpenter, AC, cleaning, appliance, pest, other),
problem ≤ 200 characters, preferred time; output a fixed-template request text (no address, no
phone) and the link `https://www.urbancompany.com/` for him to open by tap. To message a provider he
picks, the brain uses the existing `whatsapp_draft` (a draft; he sends). No booking, no payment, no
auto-open; the R3 rule stands for anything that would.

**D3 · Backups: Firestore's daily schedule, kept 7 days.** Chosen over managed export (reads billed
per document, a Cloud Storage bucket with no free tier in Mumbai, more IAM) and PITR (≈ 5× the
storage rate, a 7-day window, recovery by clone). The owner's one-time script (D4) runs
`gcloud firestore backups schedules create --database='(default)' --recurrence=daily
--retention=7d`, turns **delete protection** on for `(default)` and grants jarvis-run what the drill
needs. Not in the copy, said plainly: the laptop's camera pictures and face library, Secret Manager
(its versions are kept by Google; the deploy never destroys them, fact 6), his Google account data.
**Privacy change:** a deleted item leaves the live database at once and the backups within 7 days;
the guide (fact 9), the Privacy panel's delete wording and persona p14.0 say so.

**D4 · The restore drill: monthly, automatic, and unable to touch the live database.**
- *IAM (owner's step):* jarvis-run gets `roles/datastore.restoreAdmin` (restore into a new database;
  it can create databases but never delete or overwrite one), `roles/datastore.owner` **only** with
  the condition `resource.name=="projects/P/databases/jarvis-drill"` (so it can delete the drill
  copy and nothing else), and `roles/datastore.backupSchedulesViewer`. `(default)` has delete
  protection on.
- *Canary (daily, morning tick, job `backup_canary`):* `{prefix}backup_canary/{yyyymmdd}` = SHA-256
  of a random 32-byte nonce, the nonce sealed with the new keyring purpose `backup_probe` (AAD
  `backup_canary/{date}/v1`), a key fingerprint (`keyring.mac("backup_probe", "fingerprint/v1")`,
  first 16 hex), version, time. Kept 30 days.
- *Drill (job `backup_drill`, morning tick; state machine in `{prefix}backup_drill/current`):*
  due on day `backup_drill_day` (1) at the first tick after 05:00, or after he approves the
  `vitals_drill_start` card. **start**: newest READY backup; refuse when its size × ₹19.05/GiB >
  `backup_drill_max_inr` (₹100); if a `jarvis-drill` database exists, clean up first; restore into
  the fixed id `jarvis-drill`. **restoring**: poll the operation each tick. **verifying** (resumable
  per collection, bounded by `ticks.time_left()`): (1) every document in `jarvis-drill` counted,
  sub-collections included; total must equal the backup's `stats.document_count` exactly; (2) the
  newest canary dated within 26 h before `snapshot_time` is present, its hash equals the live
  canary's, its sealed nonce opens with the live keyring and the fingerprints match; (3) one sealed
  vault item from `jarvis-drill` opens through the vault store's own read path, its plaintext only
  hashed in memory and compared with the live item when both carry the same `update_time`; (4) up
  to 20 documents per collection compared with live: same `update_time` → identical content hash.
  **cleanup**: delete `jarvis-drill`, wait until gone, store the result. A failure anywhere stores
  "failed" with a reason code and still cleans up; a drill copy older than 2 days raises
  `backup_problem`.
- *Unable to write live:* the verifier gets `ReadOnlyDocs` (get and query only; no `write`, no
  `transaction`; not a `Docs` subclass). The drill-side reader (`storage/firestore_walk.py`) and the
  admin adapter (`storage/firestore_admin.py`) refuse any database id but the constant
  `DRILL_DB = "jarvis-drill"`, and refuse `(default)` and `settings.firestore_database`, **before**
  any call. The result is written by `backup/log.py`, which the verifier modules never import.
  Tests prove each (part A).

**D5 · Self-health watch (B): what JARVIS will tell you about itself.** One package
`src/jarvis/selfwatch/`, two jobs: `selfwatch_clock` (5 minutes, advisory, rides the watchdog and the
Home-off path) and `selfwatch_daily` (morning tick).

| Signal | Rule | Kind |
|---|---|---|
| A job fails again and again | `selfwatch_fail_streak` (3) failed runs in a row of any tick/watchdog job or sweep (seen through `ticks` observer, I0); once per streak | `job_failing` |
| A clock stops | watchdog not seen for 20 min (checked by the tick), or no tick by 05:00 on a day (checked by the watchdog); once per outage | `clock_stopped` |
| Recovered | the streak or clock ends | `selfwatch_ok` (info) |
| Brief not made | today's brief absent or failed `selfwatch_brief_grace_min` (60) after his brief time; once a day | `brief_missed` |
| Errors pile up | ERROR log records in an hour > `selfwatch_errors_per_hour` (30), counted by a logging handler by logger name only; once a day | `errors_piling` |
| Spend spike | today's AI spend > 3× the 14-day daily average and ≥ ₹50 (daily snapshots of the month total, `billing/meter.py`); once a day | `spend_spike` |
| New version live | `K_REVISION` (S5) or version differs from the stored one; once per revision; says the version | `deploy_changed` |
| Backups | no READY backup newer than `backup_max_age_h` (36), no schedule, drill failed, drill copy left over, canary key changed; once per cause a day | `backup_problem` |
| Drill passed | monthly | `backup_ok` (info) |
| Database size | latest backup's `size_bytes` vs Firestore's free 1 GiB: amber 80 %, red 100 % | Vitals item (existing `vitals_warn`/`vitals_critical`) |

If **both** clocks stop JARVIS cannot speak up (nothing runs); the console shows "Clocks stopped
since …" on the Vitals board when he opens it. Firestore read/write counts need Cloud Monitoring and
a new permission: deferred (D16).

**D6 · Alert kinds 43 → 52** (`R14_ALERT_KINDS`): `job_failing`, `clock_stopped`, `brief_missed`,
`errors_piling`, `spend_spike`, `deploy_changed`, `backup_problem` important daytime rings (held in
quiet hours, in `DAYTIME_RING_KINDS` and the storm's soft caps by kind and subject, as R5.1 D13 did
for `health_fault`); `selfwatch_ok`, `backup_ok` info (feed only). Every one has an Alerts-card
switch and held words; text is a fixed template (no logger name, no vendor text, no amounts except
the spike's ₹ figure). The two missing Alerts-card rows and held words for `health_fault` and
`vitals_critical` are added in the same seam.

**D7 · Self-health runs around the clock with Home off too.** I0 replaces the Home-off branch
(`api/home.py:160–172`) with `app.state.clock_jobs`: every advisory 5-minute job (`health_check`,
`helpers_clock`, `mobile_clock`, `selfwatch_clock`), built once and used by both paths; the watchdog
`extend`s the same list when Home is on. `ADVISORY_JOBS` += `selfwatch_clock`.

**D8 · Measure first: a token ledger.** `billing/ledger.py` (C) records per call, per owner per day
(`{prefix}token_ledger/{uid}_{yyyymmdd}`, 90 days): calls, cold calls, input, cache read, cache write,
output tokens (from the vendor's own `Usage`), and characters by part (persona, tools, history, tool
results, memory, trailer), tools offered, skills opened. Counts only. Vitals line "Where the AI money
goes this month" in ₹ by part. The before/after figures below are estimates until a week of ledger
data replaces them; the guide's §9 "about ₹0.17 a reply" (which assumes every token is read from the
cache) is corrected at I1 with measured numbers.

**D9 · Free cost wins (C), all inside `jarvis.llm` and the brain's slots; model-agnostic.**
- *Offer only the tools a message needs.* `skills/offer.py`: the turn's skills = keyword matches on
  his message (the register's words, English and his common Hinglish) ∪ the skills of tools used in
  the last 3 turns ∪ the previous turn's set when it was under 5 minutes ago (sticky, so the cache
  still hits) ∪ the always-offered core (`skills_open`, `reminder_add`, `calendar_list_events`,
  `memory_search`). Fixed for the whole turn, in registry order, except when the model calls
  `skills_open(skill)` (R1, no side effect, through the gateway): the next round adds that skill.
  `tool_offer = "all"` restores today's behaviour (kill switch). A brain that trains on content
  still gets no tools.
- *Count tool results in the history.* `core/window.py` counts block characters; tool results older
  than the last 2 tool rounds are cut to `history_tool_result_chars` (2,000) with "… [shortened]",
  pairs kept well-formed.
- *Cache the conversation too.* `jarvis.llm` gains `cache_hint: CacheHint | None` on
  `complete`/`stream` (`messages=True` marks the last message block); Anthropic adds a second
  breakpoint, the others accept and ignore it. 5-minute TTL stays (1-hour waits for ledger data).
- *Vendor text out of errors:* `LLMAuthError` / `LLMTransientError` carry fixed words; the vendor's
  message stays in the provider's log (as `LLMOutOfCredit` does).
- **Out:** a per-turn fast-tier classifier (it adds 0.3–0.8 s to every spoken reply; `skills_open`
  covers a missed tool for one cheap round); simple replies on the fast tier (owner question 7);
  trimming the persona per skill (safety rules live there; needs a full eval pass); the **streamed
  tool loop** from R5 D15 (a latency feature, not cost or safety; it needs tool-call streaming in all
  five providers and the brain, which is at 704 lines; a voice release).

**D10 · ₹ per reply, before and after** (balanced tier, ₹ per million: in 190.48, out 952.40, cache
read 9.52, cache write 238.10; prefix today ≈ 17,400 tokens, after ≈ 8,300 with ~25 tools; history
3,800; output 250; one tool result 2,000):

| Reply | Today | After R14 |
|---|---|---|
| After a pause over 5 min, no tool | ₹5.10 | ₹2.94 |
| Within 5 min of the last | ₹1.13 | ₹0.54 |
| After a pause, one tool (2 calls) | ₹6.47 | ₹3.81 |
| **Mix at 20 a day** (50 % / 20 % / 30 %) | **₹4.72 → ≈ ₹2,830 a month** | **₹2.72 → ≈ ₹1,630 a month** |

Long tool sessions save more (fact 11: uncounted results can add ≈ 30,000 tokens, ₹5.7, to every
later reply). Gemini, laptop and No-AI stay ₹0.

**D11 · The skill register (row 112).** `src/jarvis/skills/catalogue.json` (data) lists the 11
skills — Task & Productivity, Research & Intel, Code & DevOps, Decision Support, Communication,
Finance & Analytics, Learning, Creative, Security Advisor, Automation Engine, Health & Wellbeing —
each with a one-line "about", its words for the turn offer, and its tool patterns (an exact name
wins over a family). `skills/registry.py` derives each tool's card from the live registry: name,
skill, risk (`Tool.risk`), permission rows (`permissions.groups.groups_for`), Telegram class
(private / personal / home / both / open, from `telegram/rules.py`). **The check:**
`tests/test_r14_skill_coverage.py` builds the fullest registry the fakes allow and fails when a tool
has no skill, two skills, a pattern matches nothing, or a read tool has no Telegram class;
`scripts/skill_coverage.py` prints the table for the guide and the build book. **Uses:** the turn
offer (D9), `skills_open`, "what can you do" in No-AI (D12), `GET /v1/skills`. No UI change.
"Without code changes": regrouping, words and the offer are data; a new *ability* still needs a
reviewed tool (owner question 9 for skills he defines himself). The guide's three cards labelled
"Knowledge Base & Memory" are relabelled "Research & Intel (knowledge and memory)" at I1: the
project's ten skills have no such skill.

**D12 · No-AI pass 2 (D).** `offline/phrases_r14.py`, anchored, conservative, tried with the other
extra routers before pass 1. Each ends in a gateway call or a fixed line:

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
fresh: "Google didn't confirm a fresh sign-in; try again" (`api/auth.py:166–174`); (2) a new show
lock keeps the earlier `sessions_valid_after` mark (`buildbook/lock.py:120–124`); (3) the console
covers the page while a lock re-check answers 503 `lock_unreadable` (console.js, ≤ 10 lines);
(4) `GET /v1/notes/export` is audited (agent `privacy`, count only); (5) the Telegram re-plan card's
first line comes from the stored plan's label, never the model's argument (R11.1 L3); (6) the UPI
cap becomes `bill_pay_cap_inr` (₹1,00,000 default, 1–1,00,000; he can only lower it); (7) a held
overnight `home_offline_idle` is dropped when the laptop is back before the morning summary;
plus vendor text out of errors (D9), the Alerts rows (D6), the Home-off clock (D7). Deploy: stop
creating the unneeded Vitals index; add the TTL policy on `jarvis_people_last.expires_at` (fact 10).

**D14 · Version and persona.** `__version__ = "14.0.0"` at I0; the build book names R14 from it.
Persona p7.0 → **p14.0** at I1: TOOLS_RULE adds "This turn you may hold only some of your tools. If
he asks for something none of them does, call skills_open first; never say you can't before that."
BACKUP line: "Backups are kept 7 days; you tell him when the last one was; a restore drill starts
only from its card."

**D15 · Guide.** I1 adds cards C61 Backups and restore drill, C62 Self-health watch, C63 Skill
register and the turn's tools (every new collection named), edits "No backups" (fact 9), §8 gains
"Restoring for real" (D19 runbook), §9 the measured cost, the change log and edition line.

**D16 · Deferred, with reasons.**

| Item | Why not now |
|---|---|
| Streamed tool loop (R5 D15) | Latency, not cost or safety; all five providers + brain (D9) |
| Persona split per skill; 1-hour cache; fast tier for simple replies | Need ledger data / safety-eval pass; owner question 7 |
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
| `backup_drill/current` | A | state, backup name, snapshot time, expected count and size, operation, cursors, check results | no | overwritten |
| `backup_drills/{yyyymm}` | A | result: passed, reason code, counts, collections, samples, vault item opened, canary ok, minutes, ₹ estimate | no | 13 months |
| `selfwatch/jobs`, `selfwatch/clocks`, `selfwatch/deploy`, `selfwatch/spend` | B | job streaks; clock stamps; revision and version; daily month-total snapshots (₹) | no | overwritten (spend 15 days) |
| `selfwatch_errors/{yyyymmdd}` | B | per hour: count; per logger name: count (≤ 50 names) | no | 14 days |
| `selfwatch_told/{uid}_{key}` | B | once-only claims (kind + cause + day hash) | no | 30 days |
| `token_ledger/{uid}_{yyyymmdd}` | C | token and character counts by part, offers, skills opened | no | 90 days |

Keyring purposes 21 → **22** (`backup_probe`). Never stored: a vault item's plaintext or hash outside
the drill's memory, a nonce in clear, a key, a log message, a prompt, a reply.

## Per item: layer, skill, failures, security, evals, cost

| Item | Layer · skill | Failure modes and handling | Security and privacy | Tests and eval (negative control) | ₹ a month |
|---|---|---|---|---|---|
| A Backups + drill | L7, cross-cut ops · Code & DevOps | No schedule / no permission → Vitals "not set up" + `backup_problem` once; restore slow → resumes next tick; verify over budget → resumes; delete fails → retried, alert after 2 days; key changed → canary fails, drill "failed: key" | D4's four locks; plaintext only hashed in memory; drill copy deleted the same morning | `evals/r14/backup.py`: passes on fakes; a missing document fails the count; a changed key fails; a live write is refused; a `(default)` target is refused before the call; a stale backup alerts once. **Control:** `ReadOnlyDocs` swapped for the writable store → "no live write" case fails | ≈ ₹5 at 100 MB (backups 7 × 0.1 GiB × ₹2.86 = ₹2.0; restore ₹1.9; drill-copy reads ≈ ₹1); ≈ ₹40 at 1 GiB |
| B Self-health | cross-cut observability, L8 · Code & DevOps | A handler that fails never logs itself; writes batched every 5 min; both clocks dead → console line only | Logger names and counts only; alert text fixed | `evals/r14/selfwatch.py`: 3 failures → one alert, recovery → one info, clock gap, brief missed at time + 60, 31 errors an hour, spike, revision, nothing rings at 02:00. **Control:** streak counting off → "once per streak" fails | ₹0 (≈ 600 reads, 300 writes a day) |
| C Cost + register | L3/L4, L5 · Code & DevOps, Finance & Analytics | Offer misses a tool → `skills_open`; offer crashes → all tools; ledger write fails → logged, reply unaffected | Counts only; vendor text never leaves `jarvis.llm` | `evals/r14/offer.py`: 120 labelled messages, needed tool offered in ≥ 98 %, average ≤ 30 tools; constant tools across rounds; window counts blocks; ledger sums. **Control:** the words table emptied (no sticky, no history) → recall < 98 % | saves ≈ ₹1,200 at 20 replies a day (D10) |
| D No-AI 2, rows 101/102, fixes | L3, L5, L6 · per row | A phrase that doesn't match → pass 1 → fixed line | Disarm never routes; service text has no address or phone; each fix has its own test | `evals/r14/noai.py`: every row of D12 routes with zero provider calls; generative asks keep `NO_AI_LINE`. **Control:** R14 phrases off → their cases fail | ₹0 |
| Needles (I1) | — | — | — | `evals/r14/needles.py`: a planted vault plaintext, nonce, key, exception message, prompt word never reaches any document, log line, audit detail or alert. **Control:** masking off | — |

## Part split (four builders, worktrees, branches `r14-a` … `r14-d` from `r14-i0`; disjoint files)

- **A · Backups and the drill.** `backup/{canary,readonly,drill,verify,walk_checks,vault_probe,log,
  status,tools,jobs}.py` (I0 owns `backup/__init__.py`, `backup/ports.py`),
  `storage/firestore_admin.py`, `storage/firestore_walk.py`, `api/backup.py` (I0 stub; `GET
  /v1/backup`, `POST /v1/backup/drill` → the same card), `deploy/backup_setup.sh` (I0 stub),
  `tests/test_r14_a_*.py`, `tests/r14_fakes_a.py`, `evals/r14/backup.py`, INTEGRATION-A.md (with the
  guide's restore runbook text). Tools `vitals_backups` (R1), `vitals_drill_start` (R2, `ask_when`
  always). `security-reviewer` required.
- **B · Self-health.** `selfwatch/{ledger,clocks,errors,brief_check,spend,deploys,texts,jobs,
  status}.py` (I0 owns `selfwatch/__init__.py`, `ports.py`), `api/selfwatch.py` (I0 stub; `GET
  /v1/selfwatch`), `notify/store.py` (drop a held kind) and the laptop-back path that sends
  `home_online` (D13 item 7), `tests/test_r14_b_*.py`, `evals/r14/selfwatch.py`, INTEGRATION-B.md.
- **C · Cost and the register.** `skills/{catalogue.json,registry.py,offer.py,open_tool.py}` (I0 owns
  `skills/ids.py` and the `offer.py` stub), `billing/ledger.py` (I0 stub), `core/window.py`,
  `llm/{base,router,fallback,anthropic_provider,gemini_provider,openai_compat_provider,
  local_provider,mock_provider}.py`, `api/skills.py` (I0 stub; `GET /v1/skills`, `GET
  /v1/costs/ledger`), `scripts/skill_coverage.py`, `tests/test_r14_c_*.py`,
  `tests/test_r14_skill_coverage.py`, `evals/r14/offer.py`, INTEGRATION-C.md (with the TOOLS_RULE
  text). `security-reviewer` on the `jarvis.llm` change.
- **D · No-AI pass 2, rows 101/102, the leftovers.** `offline/phrases_r14.py`,
  `helpers/house/{upkeep,service_request,tools}.py`, `helpers/today/upi.py` (or wherever the cap
  lives), `api/auth.py`, `buildbook/lock.py`, `api/notes.py`, `series/cards.py`,
  `api/static/console.js` (≤ 10 lines), `deploy/cloudrun.sh` (index out, TTL in, a non-fatal call to
  `deploy/backup_setup.sh`), `tests/test_r14_d_*.py`, `evals/r14/noai.py`, INTEGRATION-D.md.
  `security-reviewer` required.
- **All parts:** test first; functions ≤ 50 lines, modules ≤ 400, files ≤ 800; only the planned
  collections, job names, kinds and tool names; alerts only through the notifier with the fixed
  templates; `docs/plans/r14-integration/BRIEF-COMMON.md`.

## The I0 seam list (branch `r14-i0`; the integrator owns these files)

1. **Version** `14.0.0` (`__init__.py`; pins in `tests/test_about.py`, `test_r11_1_seams.py`,
   `test_r7_seams.py`, `test_r1_seams.py`).
2. **Alert kinds** + 9 (D6): `alerts.py` `R14_ALERT_KINDS`, `notify/ports.py` `DEFAULT_URGENCY`,
   `notify/policy.py` `DAYTIME_RING_KINDS`, `notify/storm.py` soft set, `notify/held.py` words (+
   `health_fault`, `vitals_critical`), `console-alerts.js` `KINDS` (+ 11 rows); pinned 43 → 52 in the
   five tests of fact 5.
3. **Keyring** `backup_probe` (22; the three pins of fact 6).
4. **Permissions:** no new row (49 stays); `tests/test_permissions_policy.py` `EXPECTED` gets
   `vitals_backups` (R1, vitals), `vitals_drill_start` (R2, vitals_change), `maint_service_request`
   (R1, household); `skills_open` has no row (listed); `test_telegram_tool_guard.py` classes them
   open; `understand/words.py` nouns (backups, drill, skills, service, request).
5. **Settings** (`config.py`): `selfwatch_enabled` (on), `selfwatch_fail_streak` 3 (2–10),
   `selfwatch_errors_per_hour` 30 (5–500), `selfwatch_brief_grace_min` 60 (15–240),
   `selfwatch_spike_factor` 3.0 (1.5–10), `selfwatch_spike_min_inr` 50, `cloud_run_revision` (alias
   `K_REVISION`), `backup_checks_enabled` (on in prod), `backup_max_age_h` 36 (25–200),
   `backup_drill_enabled` (on), `backup_drill_day` 1 (1–28), `backup_drill_max_inr` 100 (10–1,000),
   `tool_offer` `by_skill` | `all`, `tool_offer_sticky_s` 300, `history_tool_result_chars` 2,000
   (500–12,000), `cache_history` (on), `token_ledger_enabled` (on), `bill_pay_cap_inr` 1,00,000
   (1–1,00,000). `DRILL_DB` is a constant, never a setting.
6. **Packages and stubs:** `backup/` (`ports.py`: `BackupAdmin`, `DrillWalk`, `ReadOnlyDocs`,
   `DRILL_DB`), `selfwatch/` (`ports.py`), `skills/ids.py` (the 11 ids, labels, `SkillSummary`),
   `skills/offer.py` (`offer_all`), `billing/ledger.py` (no-op), `offline/phrases_r14.py` (empty),
   stub routes `api/backup.py`, `api/selfwatch.py`, `api/skills.py`, `deploy/backup_setup.sh`
   (prints "not built yet").
7. **Wiring:** `api/r14_wiring.py` (`wire_r14`, `r14_tick_jobs`, `r14_clock_jobs`,
   `install_r14_routes`, `r14_tools`, `r14_vitals_sources`, `install_r14_phrases`); `api/app.py`
   frees lines by moving `_tick_jobs` (`:420–432`) into `api/tick_wiring.py`, then adds the R14
   slots, ending ≤ 735; `tools/setup.py` `r14=`; `api/selfcheck_wiring.py` the Vitals sources slot;
   `api/home.py` + `home/watchdog.py` the shared `clock_jobs` (D7); `ticks.py` an observer hook
   (`observe(fn)`, never raises) and `api/brief.py` reports its sweeps to it; `core/brain.py` two
   slots (`tools=offer(...)` at `:430`, `ledger.record(...)` after `:432`).
8. **Guide and book:** cards C61–C63 listed in advance (every collection of the data model), the L5
   row, edition line, change log; `scripts/arch_coverage.json` if needed; build book `layers.py`
   (`backup` → L7, `selfwatch` → cross-cut, `skills` → L5).
9. **Evals and fakes:** `evals/r14/run.py` (R11's runner shape: `PART`, `BUILT`, `cases()`,
   `control()`), stub parts `backup`, `selfwatch`, `offer`, `noai`, `needles`; `tests/r14_fakes.py`;
   `tests/test_r14_seams.py`, `tests/test_r14_wiring.py`.
10. `docs/plans/r14-integration/BRIEF-COMMON.md`.

## Needs the owner (safe defaults; none blocks the build)

1. **Turn on backups** (₹ about 5 a month now): nothing changes until you run the one-time step
   below; until then Vitals says "Backups: not set up".
2. **How long to keep each copy:** 7 days (default). Longer costs more and keeps deleted things
   longer (14 days ≈ double).
3. **Monthly restore drill** on the 1st, automatic, at most ₹100 a drill (default yes).
4. **Google's "any charge" e-mail** (₹1 budget) will arrive each month once backups cost money.
   Default: leave it; or raise it to ₹100 in Billing → Budgets.
5. **A copy outside Google** (a file on your laptop): default no (it would hold your conversations
   unlocked).
6. **Send only the tools a message needs** (saves ≈ 40 %): default on; "all tools" is one setting.
7. **Simple replies on the cheaper fast model:** default no.
8. **"JARVIS was updated" notice** rings in waking hours: default yes (you'll hear about every
   merge); or feed only.
9. **Skills you define yourself** in the console (row 112's fullest sense): default later.
10. **Car service** every 6 months (default); booking site Urban Company (default).
11. **Error alert** at 30 errors an hour; **spend alert** at 3× normal and ₹50 or more (defaults).

## The owner's one-time steps (after the R14 PR is merged and deployed)

1. Open https://shell.cloud.google.com and check the project line shows your JARVIS project.
2. Type `cd ~/jarvis-web && git pull` and press Enter (if the folder is missing:
   `git clone https://github.com/Shark2558/jarvis-web && cd jarvis-web`).
3. Type `bash deploy/backup_setup.sh` and press Enter.
4. Read the cost line it shows ("about ₹5 a month at your size today"), then type **YES** to go on.
   Anything else stops it with nothing changed.
5. Wait for "Backups: on, kept 7 days · Delete protection: on · Drill access: on". If a line says
   "could not", send that screen to the Workshop; nothing else breaks.
6. Tomorrow, open JARVIS → Vitals: "Backups: last copy today at …".
7. Optional: say "test my backup" or press "Run a restore drill" in Vitals, approve the card; the
   result shows the next morning.

## What can't be verified from this workspace

Google calls of every kind (the shell can't reach Google): the schedule, a real restore and its
time, `restoreAdmin` creating `jarvis-drill`, the conditioned `datastore.owner` deleting it (and
only it), delete protection blocking a delete; the real database size (so the real ₹); whether
Mumbai prices differ from the single table (S2); `K_REVISION` on the live service; real token counts
(here: characters ÷ 4 on 112 tools; the live set is about 120–140); how often Claude reuses the
cache with changing tool sets; whether Google sends `auth_time` on every `max_age=0` re-sign-in
(D13 item 1 refuses when it doesn't); the Urban Company link; the pricing page itself
(`cloud.google.com/firestore/pricing` was blocked; its `?authuser=3` copy was read).

## Risks

- **`restoreAdmin` can create databases**: a stolen jarvis-run could restore copies and run up
  restore charges. Bounded by the code's single fixed id and ₹100 cap, the ₹1 budget e-mail, and it
  can never delete or overwrite `(default)` (delete protection + the conditioned delete).
- **Privacy promise changes**: deleted data lives up to 7 days in backups (D3); said everywhere.
- **Key loss** makes every backup useless: the deploy never rotates the key (tested); the canary
  catches a changed key within a day.
- **A missed tool** after trimming: `skills_open`, the eval's 98 % recall bar, the kill switch.
- **Cache misses** when the offer changes: sticky offer within 5 minutes; the ledger shows it.
- **Alert noise**: once per streak/day/revision, held at night, soft caps, every kind switchable.
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
