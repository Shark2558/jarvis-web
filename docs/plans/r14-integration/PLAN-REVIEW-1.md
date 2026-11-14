Version v14.0.1 · 14 Nov 2026, 13:32 IST · Release R14 · Status: Current · Owner: 🛠 Mark XVIII

# R14 plan review 1 (fresh context, 14 Nov 2026)

Plan reviewed: `docs/plans/r14-hardening.md` v14.0.1 (Draft), all 531 lines, on `r14-i0` @ `b45e43c`.
Checked against: the code on the same commit (`main` @ `5db4f05`, R7 live, v7.0.0), and Google's and
Anthropic's current pages, read 14 Nov 2026 through the web tools (the shell can't reach Google).
Reviewer: a fresh-context agent run for 🛠 Mark XVIII, applying `.claude/agents/code-reviewer.md` and
`.claude/agents/security-reviewer.md` to a plan; read-only apart from this file. "L" numbers are the plan's.

**Verdict: NOT ready for I0 as written.** It becomes ready once A1–A8 are written into the plan, the B
lines are corrected and the C seams join the I0 list. None needs the owner first. The design holds:
Firestore's own daily schedule, a throw-away restore that is deleted after it is checked, a canary that
proves the key, self-health on the existing clocks, and a register-driven tool offer behind a kill switch.

What this review could not check:
- Every live Google call, as the plan says (L490–499). Two of them the design depends on: whether a
  `resource.name` condition is honoured for `datastore.databases.delete` (Google documents it only for
  `roles/datastore.user`), and whether a restore keeps each document's `update_time` (no page says).
- Cloud Run's `K_REVISION` page (S5) was not fetched. It is a long-standing part of the container contract.
- The dev-app tool count (112). The fullest registry the fakes build was measured instead (B2).

## A. Blocking

**A1. "Cache the conversation too" can't hit across turns, so the ₹ table is too optimistic (D9 L260–262, D10 L271–283).**
- The per-turn trailer is a system block placed before the messages: `_Prompt(system, self._trailer(session, req) + rec.block)` (`core/brain.py:363`), sent as the second system block (`llm/anthropic_provider.py:115–126`). It holds the time to the minute, the turn number and the recalled notes (`core/prompts.py:648–655`).
- The prefix order is tools → system → messages (S6). Every breakpoint on a message therefore includes a block that changes on every turn, so the conversation cache hits only between the rounds of one turn.
- Two more things move the prefix:
  - The window drops the oldest turn on every reply once it is full (`core/window.py:31–37`). Counting tool results (D9's second bullet) makes it fill sooner.
  - The "older than the last 2 tool rounds" trim moves forward with each new round, so an earlier block changes.
- Fix: choose one of these and write it into D9:
  - (a) Move the per-turn trailer after the history: a final block of the last owner message, marked as JARVIS's context and not his words. This changes the prompt shape, so the persona and voice evals rerun and the safety rules for the memory block are re-checked.
  - (b) Keep the trailer where it is and drop the cross-turn claim.
- Either way, the window drops old turns in chunks (for example down to 70 % of the budget), so its start stays put for several replies. The trim happens once, when a result ages out, so the shortened block then stays the same.
- Rework D10 with D10's own parameters:
  - After a pause: ₹3.12, not ₹2.94. With the hint on, the history is a cache write at 1.25×, not plain input.
  - Within 5 minutes, under (b): about ₹1.04, not ₹0.54.
  - Tool sizes come from B2. The "40 %" stays an estimate until the ledger (D8) measures it.
- Tests: a window that slides keeps its first message for N replies. With (a), a negative control: the trailer moved back → the second turn's cache read is 0 in the mock provider's recorded breakpoints.

**A2. The drill's ₹100 guard and its content checks can pass with nothing checked (D4 L185–196).**
- `Backup.stats` is empty until the backup is fully materialised, even though the state is READY. The SDK's own docstring for `stats` says "This field will be empty till then". A size of 0 passes `size × ₹19.05/GiB > ₹100`, and a count of 0 equals a walk of an empty copy. Fix: no stats, or `document_count == 0`, means "not yet". Wait for the next tick; never start.
- Checks (3) and (4) compare only when both sides "carry the same `update_time`". If a restore stamps a new `update_time` (undocumented), every comparison is skipped and the drill passes without opening a vault item. Fix:
  - Compare on the app's own fields: the vault document's `rev` and `updated_at` (`vault/store.py:4`, `:70–87`), and each collection's own time field.
  - Store how many items were compared.
  - Zero vault items opened, or zero samples compared, is "failed: nothing compared" when the live database has any. An owner with no vault is recorded as "skipped: no vault", never as a pass.
  - Negative control: restored items carry a new `update_time` → the drill must not pass.
- Count with `count()` aggregations per collection group (about one read per 1,000 index entries) rather than reading every document. The drill copy is a named database with no free quota (S2), so a full walk at 1 GiB of about 500,000 documents costs about ₹14 and breaks "≈ ₹40" (see the ₹ table below).

**A3. A drill that fails halfway must clean up whatever the switches say, and the leftover must be costed (D4 L184–198, risks L501–505).**
- Cleanup runs whenever a database `jarvis-drill` exists, even with `backup_drill_enabled` or `backup_checks_enabled` off. Otherwise switching the drill off mid-run leaves a copy that is billed with no free quota.
- `get_database("jarvis-drill")` decides what to do, not the stored state alone. A restore operation that failed may still have left a database behind.
- If the restored database has delete protection on (Google doesn't say what a restore inherits), disable it first. The conditioned grant includes `datastore.databases.update` on `jarvis-drill` only. Test it.
- After a delete, the id can be used again only after 5 minutes (S4). A clean-up then restore in one tick fails, so the state machine waits for the next tick. Write that down.
- State the leftover cost in ₹: about ₹1.4 a month at 100 MB and about ₹14 a month at 1 GiB (stored data with no free quota). "Drill copy left over" should then alert once, and weekly after that, not every day.
- One drill at a time (the fixed id does this). Manual drills: at most `backup_drill_manual_per_month` (2) a month, because each costs a restore. The drill card is `bulk_ok=False`, so Approve all can't start one (`core/approve_all.py:14–15`, `:258`).

**A4. Nothing may spend money before he types YES (D13 L330–331, Part D L409–410, owner step 4 L482).**
- Part D's "non-fatal call to `deploy/backup_setup.sh`" from `deploy/cloudrun.sh` would run the set-up during every deploy. Fix: the deploy calls only `backup_setup.sh --status`, which reads and prints and never creates a schedule, a binding or protection. I0's stub defines both modes, and a test greps that `--status` never runs a `create` / `update` / `add-iam-policy-binding`.
- The cost line can't be "at your size today". Before the first backup there is no `stats`, and Monitoring is deferred (D16). The script shows the range ("about ₹5 a month at 100 MB, about ₹40 at 1 GB"). Vitals shows the real figure from the first backup's `size_bytes`.
- D13's TTL policy on `jarvis_people_last.expires_at` comes out:
  - TTL deletes have no free usage (S2: "TTL deletes … do not include free usage"). The code avoids billed TTL on purpose (`api/brief.py:139`, "no billed TTL").
  - `expires_at` is a float (`people/cache.py:91`), and a TTL policy needs a timestamp field. The policy would do nothing and still put a charge line near the ₹1 budget alert.
  - Fix: correct the docstring at `people/cache.py:6–7` (it already deletes on an expired read and on `clear`). Give that file to Part D.

**A5. The four locks, said honestly, and two more (D4 L175–204, summary L18–19).**
- For deleting `(default)`, the locks are real: the adapter refuses the id before any call; there is no delete permission except on `jarvis-drill`; delete protection is on. The middle one is unverified (see "could not check"), but it fails closed: if Google ignores the condition, the drill copy can't be deleted (A3) and `(default)` is still safe.
- For writing to `(default)`, the IAM lock does nothing. `jarvis-run` holds unconditioned `roles/datastore.user` (`deploy/cloudrun.sh:471–473`), which is `datastore.entities.*` on every database (S3). Delete protection doesn't stop writes or document deletes either. So "It can never write to your real database" rests on code alone.
  - Reword L18–19 as "its code can't write to your real database" and keep the two code locks.
  - The live side of every comparison is wrapped in `ReadOnlyDocs` too, not only the drill side.
  - An import test: `backup/{verify,walk_checks,vault_probe}.py` import neither `storage.firestore_docs` nor `backup.log`.
- Add lock 5: `Settings` refuses `firestore_database == "jarvis-drill"` at start-up. Otherwise, after a real restore into that id, the next drill would delete the live database. The "Restoring for real" runbook names the id to avoid, and says to clear `backup_drill/current` after a real restore (the copy carries the old state).
- Least privilege: grant a custom role `jarvisDrillCleanup` (`datastore.databases.get`, `.getMetadata`, `.update`, `.delete`) with the condition, instead of conditioned `roles/datastore.owner` (`datastore.*`). The script can check the binding with `gcloud projects get-iam-policy … --flatten`. The first drill's clean-up proves the positive case.

**A6. Self-health can storm, starve the approvals bell, and alarm about itself (D5 L210–225, D6 L227–233).**
- Burst:
  - `job_failing` is "once per streak" per job. During a Firestore or Google outage every job of the tick and the watchdog fails together, which means 10 to 15 rings within 15 minutes.
  - All of them are "important", so they share the normal Telegram bucket (10 an hour, 50 a day) with `approval_waiting` and the vault and bill reminders (`notify/telegram_out.py:147–158`).
  - Joining `SOFT_URGENT_KINDS` (D6) puts them in the same 6-an-hour soft window as `health_fault` and `vitals_critical` (`notify/storm.py:38`, `:178–191`).
  - Burglar and hazard rings are unaffected (their own bucket, `NO_CAP_KINDS`). Approvals and the systems check are not.
- Fix:
  - One aggregated `job_failing` an hour per owner ("3 background jobs keep failing: …").
  - The R14 kinds get their own soft table (≤ 3 an hour in all, one per kind and subject per 30 minutes), not `SOFT_URGENT_KINDS`.
  - Eval case: a whole-Firestore outage produces at most 1 ring.
- Starvation is not failure:
  - The watchdog has 50 s in all (`home/watchdog.py:61`). `health_check` alone may take 30 s (`health/tick.py:28`), and `selfwatch_clock` is added last.
  - `run_jobs` reports a job it had no time for as "failed" (`ticks.py:111–114`).
  - The `ticks.observe` callback must carry the reason (failed / timed out / skipped for time), and a skip never counts toward a streak.
  - `selfwatch_clock` runs first on both 5-minute paths.
- No self-reinforcing loop:
  - The once-only claim (`selfwatch_told`) is written before the send.
  - A failed send is not a job failure.
  - A selfwatch job never reports its own streak: the tick reports the clock's job and the clock reports the tick's.
  - The errors handler doesn't count records from `jarvis.notify*` / `jarvis.telegram*` raised while sending a selfwatch alert. The once-a-day cap already bounds the rest.
- "Not set up" is a Vitals line only. `backup_problem` begins only after `backup_setup.sh` has run once (a marker it writes, or a schedule seen once). Otherwise he is nagged every day until he does the optional step (L219 "once per cause a day" against L380 "once").
- Spend spike: a day's spend is today's snapshot minus yesterday's, except on the 1st (the month total resets: `billing/meter.py` `month_of`). No alert before 7 days of history.

**A7. D7's "around the clock with Home off" runs for nobody (D7 L235–238).**
- The Home-off route runs its jobs with no owners: `run_jobs((clock,), (), …)` (`api/home.py:168`). Composites carry their own owners; `HealthTickJob` and the planned `selfwatch_clock` serve only the owners they are passed (`health/tick.py:55–60`).
- With Home on, the watchdog passes `linked_uids()`, the owners who linked a laptop (`home/watchdog.py:235`, `home/store.py:210–212`).
- Fix: `app.state.clock_jobs` always runs with the brief's owner list (`BriefService.owners`, `brief/service.py:688`) on both paths.
- Test: Home off → `health_check` and `selfwatch_clock` run for the signed-in owner at 02:00.

**A8. The four parts collide outside I0 (Part split L386–414).**
- `api/static/console-vitals.js` (371 lines, data-driven items only) is needed by three parts and owned by none:
  - A: "Run a restore drill" (owner step 7, L487)
  - B: "Clocks stopped since …" (L223–224)
  - C: "Where the AI money goes", ₹ by part (D8)
- `console-privacy.js` (D3's delete wording) has no owner either.
- Fix: I0 adds one Vitals hook (a list of server-sent lines, `{id, text, action?}`, where the only action is the drill card) and the Privacy panel's "Backups keep deleted things up to 7 days" line. Parts then send data only. Or drop the button and keep "test my backup" by voice and in chat.
- `backup_problem` / `backup_ok` are raised by A (D4 L197–198) and by B (D5 L219–221). B's "Database size" item reads A's backup stats. Fix: A is the only producer of the backup kinds and the size. I0 adds a read port `backup.ports.BackupStatus`, which B and Vitals consume.
- C's `cache_hint=` must be passed at the brain's call (`core/brain.py:423–431`), but I0 lists only two brain slots. Fix: a third slot at I0, or the router applies `cache_history` itself.
- D2's "open by tap" has no carrier: replies are plain text, and links appear only as typed cards that the server checks and the console checks again (`tools/reply_cards.py:26–31`). Fix: I0 adds a `ServiceLinkCard` kind (https, the one allowed host) and its renderer, or the plan says the link is shown as text.

## B. Stale or wrong code facts (on `b45e43c`)

| Plan line | Says | Is |
|---|---|---|
| 113 | prices `llm/pricing.py:27–29` | Sonnet 5.5 is `:30` (`:29` is Opus 5.5, `:27` the comment) |
| 104–105, 25, 496 | 112 tools, 48,471 characters ≈ 12,100 tokens; "about 12,000 tokens" | The fullest registry the fakes build (`tests/test_telegram_tool_guard.py` `linked_gateway`, which D11's check reuses) has **135 tools**: 54,868 characters of name + description + schema (≈ 13,700 tokens), or 61,515 as sent in JSON (≈ 15,400). The prefix of D10 is ≈ 19,000–20,700, not 17,400, so the saving in ₹ is larger. The top 20 % of tools is 37.7 % of it |
| 245–246 | the guide's "₹0.17 a reply" assumes every token comes from the cache | It is the owner's Phase 0 real-Claude run (`docs/plans/phase2-slice11-full-control.md:11`; guide `:62`, `:1800`), measured on a far smaller persona and tool set. The guide's "about ₹100 a month for Claude" (`:62`) is the same stale figure: I1 rewrites both |
| 121–122, 263–264 | vendor text in `LLMAuthError` / `LLMTransientError` | Also `LLMUnreachable(str(exc))` and `LLMError(str(exc))` (`anthropic_provider.py:161`, `:164`); Gemini `:135`, `:138` (the message carries the vendor's detail, `:127–131`); openai_compat `:163`, `:166`; the router logs `str(exc)[:200]` (`llm/router.py:269`). All four classes get fixed words |
| 125, 328, 407 | the UPI cap is a constant; Part D "`helpers/today/upi.py` (or wherever the cap lives)" | Two constants: `helpers/sources.py:35` `MAX_UPI_AMOUNT_PAISE` and `helpers/today/models.py:47` `PAY_CAP_PAISE`. Name both in Part D. `bill_pay_cap_inr` is a deploy-time setting: "he can only lower it" means the bound, not a console control |
| 99–100, 331 | add the TTL policy on `jarvis_people_last.expires_at` | A4: a float field (`people/cache.py:91`), and TTL is billed |
| 341 | "(D19 runbook)" | The plan has D0–D16. The runbook belongs to Part A (INTEGRATION-A.md, L393) |
| 418–419 | version pins in `test_about.py`, `test_r11_1_seams.py`, `test_r7_seams.py`, `test_r1_seams.py` | Version: `test_about.py:24`, `test_r11_1_seams.py:73`, `test_r7_seams.py:110`. `test_r1_seams.py:291` pins the persona. `p7.0` is pinned in 19 test files (D14, at I1) |
| 421–423 | alert kinds pinned 43 → 52 "in the five tests of fact 5" | Also `test_r51_seams.py:45` (the exact `DAYTIME_RING_KINDS`), `test_r51_int_notify.py:47` (`SOFT_URGENT_KINDS` == the two R5.1 kinds), `test_r7_a_push.py:43` (`webpush/service.py` `TARGETS` must name every kind but `test`) |
| 424 | keyring: "the three pins of fact 6" | Also `test_r7_seams.py:292`, which pins the last three purposes: appending `backup_probe` breaks it |
| 444–445 | move `_tick_jobs` (`:420–432`) into `api/tick_wiring.py` | Right lines. `test_r11_wiring.py:294–295` and `test_r7_seams.py:436` pin the tick list inside `app.py`, so they move with it |
| 276–280 | after a pause ₹2.94; within 5 minutes ₹0.54 | ₹3.12 by D10's own figures (the history is written to the cache, 1.25×); ₹0.54 rests on A1 |
| 461–462 | 14 days "≈ double" | Backups ₹2.0 → ₹4.0; in all ≈ ₹4.9 → ≈ ₹6.9 a month at 100 MB |
| 380 | "≈ ₹40 at 1 GiB" | ₹20.0 backups + ₹19.05 restore = ₹39.1, plus the verify reads: ≈ ₹14 if every document is read, ≈ ₹0 with `count()` (A2) |
| 153 | `STARTERS` gains "Car service" | `tests/test_r11_b_chores.py:152` pins `[90, 180, 365, 365]`: Part D updates it |

**Sampled: 54 file:line claims. 51 are right, 4 of them incomplete (the alert-kind pins, the keyring pins, the vendor-text lines, the UPI cap's location). 3 are wrong (the pricing line, the tool-schema size, the reading of ₹0.17).**

Right as written, among others:
- the version and persona (`__init__.py:3`, `prompts.py:56`);
- the guards (735 = `test_r11_1_seams.py:244` / `test_r7_seams.py:650`; 760 = `:242` / `:649`, also `test_r1_seams.py:649`; 782 = `:246` / `:606`) and the five file sizes;
- the region, `--max-instances 1`, the two Scheduler jobs (the watchdog is made whatever Home is set to);
- the tick and watchdog paths;
- "with Home off, the systems check and the mobile clock run only 04:00–11:30", which is true: they reach only the morning tick through `r4_tick_jobs` / `mobile_tick_jobs` (`api/r4_wiring.py:311`, `api/r7_wiring.py:179–181`);
- the probes, the failed brief, 43 kinds, `SOFT_URGENT_KINDS`, the missing held words and Alerts rows, 21 purposes, 49 rows;
- the Firestore facts: `(default)` Native at `:411–419`, the roles at `:471–473`, `FirestoreDocs(database=)` at `:54` as the only SDK importer, google-cloud-firestore 2.34.1 with `list_backups`, `restore_database`, `delete_database`, `Backup.stats{size_bytes, document_count, index_count}`;
- the guide lines 118–119 and 1685–1686;
- "the people cache says the deploy sets a TTL policy; it doesn't", which is true;
- the Vitals index (R5.1 D2: equality only, `vitals/store.py:2`), the ₹1 budget;
- persona 21,338 characters (wit "film", the default);
- every call sends every tool (`brain.py:430`, `registry.py:20`), one cache breakpoint;
- "old tool results are never counted in the history limit (`core/window.py:34`)", which is true for the character cap: `t.content` only (`:34`, `:37`), a result turn has `content=""` (`core/rounds.py:120`), up to 12,000 characters (`gateway.py:106`). The 40-turn cap does count it;
- billing's one USD figure, ₹95.24 (`fx.py:33`);
- `NO_AI_LINE` (`rules.py:65`), `_reauth_at`, `ShowLock.set`, the unaudited notes export, the 423-only console (`console.js:78`, `:101`), the car papers and the `STARTERS`.

**Size guards and the new wiring.**
- `app.py` frees about 15 lines by moving `_tick_jobs` and needs about 5 (the `wire_r14` and `install_r14_routes` calls, `r14=`, an import): it ends at about 725, within 735.
- `gateway.py` is untouched (760).
- `console.html` stays at 782 if A8's Vitals hook is JS only.
- `console-alerts.js` goes 450 → 461.
- `config.py` goes 656 → about 730 (< 800).
- `brain.py` goes 704 + 3 (within 741, `test_r11_1_a_brain.py:301`).

## C. Missing I0 seams

1. **The alert kinds' other tables.** `webpush/service.py` `TARGETS` (+9: the self-health kinds → `vitals` or `integrations`, the backup kinds → `vitals`), `buildbook/plain.py:155` `ALERT_WORDS` (+9), and the pins of B (`test_r51_seams.py:45`, `test_r51_int_notify.py:47`, `test_r7_a_push.py:43`). Also the R14 kinds' own soft table in `notify/storm.py` (A6).
2. **The keyring pin** `test_r7_seams.py:292`, and the tick-list pins `test_r11_wiring.py:294–295`, `test_r7_seams.py:436`.
3. **Evals in `run_all_mock`.** `evals/run_all_mock.py` gains `("r14 (gated)", […, "evals/r14/run.py", "--mock"], True)` after R7's line (shape pinned like `test_r7_seams.py:868`).
4. **The built registry.** `tests/test_telegram_tool_guard.py` `linked_gateway` gains `r14=r14_tools(…)`, as R7 I0 did (`r7_tools`). Without it, D11's coverage test and the Telegram guards never see an R14 tool.
5. **Privacy.** An `r14_privacy_sources` slot in `api/personal.py`, as every release since R4 has (`token_ledger`: counts, 90 days; `selfwatch_told`: 30 days), or a recorded reason why counts need none. The guide's "Data it keeps" names every collection either way (arch coverage).
6. **The errors handler and the observer.** Where the logging handler is installed (`wire_r14`, once, the root logger), and the `ticks.observe(fn)` signature with the reason (A6). `R14_JOB_NAMES` (`backup_canary`, `backup_drill`, `selfwatch_daily`, `selfwatch_clock`) beside `R4_JOB_NAMES` / `R6_JOB_NAMES`.
7. **The brain's third slot** `cache_hint=` (A8), and `BackupStatus` in `backup/ports.py` (A8).
8. **The console hooks.** The Vitals lines hook and the Privacy line (A8). The CSP stays as it is: say so, since it is pinned by four tests and R14 adds no script and no origin.
9. **Config.** `firestore_database != DRILL_DB` (A5); bounds for `selfwatch_spike_min_inr` (10–1,000) and `tool_offer_sticky_s` (0–3,600); `backup_drill_manual_per_month` 2 (0–4) (A3).
10. **`deploy/backup_setup.sh`.** The stub fixes both modes, `--status` (read only, always exit 0) and the interactive set-up (A4), so A and D can't drift.
11. **The drill card.** `bulk_ok=False` (A3). `vitals_drill_start` sits in the row `vitals_change`, labelled "Add, edit and remove the keys you track"; the hint needs a few words for the drill.
12. **Evals each need their own negative control:**
    - the window counting (counting off → a long tool session exceeds `session_max_chars`);
    - the cache hint (hint off → one breakpoint);
    - the outage storm (aggregation off → more than 1 ring);
    - starvation (reason ignored → `job_failing` on a skip);
    - the vacuous drill (A2).

## D. Notes (not blocking)

**Google's terms, read 14 Nov 2026.**
- Confirmed:
  - S1: one daily and one weekly schedule; 14 weeks; no choice of time; data and index settings, no TTL; a new, unused id; deleting the source keeps its backups.
  - S2: $0.000041096 per GiB-hour for backups; $0.20 per GiB for a restore; reads $0.03 per 100,000; named databases get no free quota; backup data and restores have no free usage.
  - S3: `restoreAdmin` = backups get/list/restoreDatabase, databases list/create/getMetadata, operations list/get; `datastore.user` has no backup permission; `databases.delete` only through `datastore.owner`'s `datastore.*`.
  - S4: `resource.name=="projects/P/databases/D"` (shown for `datastore.user`), `--delete-protection`, 5 minutes, 100 databases.
  - S6: tools → system → messages; a tool change invalidates everything; 1.25× / 2× / 0.05× on Sonnet and Opus 5.5; 4 breakpoints; 512 tokens.
- Not on the pages: "a deleted backup can't be recovered", and what a restored database inherits.
- The pricing page says it lists rates "for each Firestore location" but shows one set (L498 stands).

**The ₹ figures, recomputed with ₹95.24 (`billing/fx.py:33`).**

| Item | Figure |
|---|---|
| Backup storage | $0.000041096 × 730 h = $0.0300 per GiB-month = **₹2.86 per GiB-month** |
| 7 daily copies at 0.1 GiB | 0.7 GiB-month = **₹2.00** |
| Restore | **₹19.05 per GiB**, so ₹1.90 a drill at 0.1 GiB |
| Drill reads (no free quota) | ₹2.86 per 100,000, so about ₹1 for a 35,000-document walk; ≈ ₹0 with `count()` |
| **At 100 MB** | **≈ ₹4.9 a month** ("about ₹5" holds) |
| **At 1 GiB** | **≈ ₹39** with `count()` (₹20.0 + ₹19.05), ≈ ₹53 reading every document |
| 14-day retention at 100 MB | ≈ ₹6.9 |
| The ₹100 cap | a backup of 5.25 GiB |
| A drill copy left over | ₹14.3 per GiB-month (stored data $0.000205479 × 730), so ₹1.4 a month at 100 MB |

Use the live rate (`billing/fx.py`), not a constant ₹19.05, in the cap check.

**Prompt caching inside `jarvis.llm`.**
- Changing the offered tools re-writes the whole prefix at 1.25×. The sticky set and the ledger's cold-call count are the right guards.
- Anthropic now documents mid-conversation tool additions (beta header `inline-tools-2026-09-15`, a `tool_addition` block with `tools` left as first sent) and `defer_loading`. Either could keep the prefix cached when `skills_open` adds a skill. They are vendor features, so they belong only in `anthropic_provider.py` behind the hint, and they are optional: the register-based offer is the model-agnostic core and works on Gemini and the laptop too.
- The lookback is 20 blocks, and a run of tool results counts as one, so long tool turns are fine.

**The tool offer and safety.**
- The offer only narrows what the model sees. Every call, including `skills_open`, still meets the registry, the permission rows, the Telegram classes, the taint rules and R3 tokens in the gateway, so nothing is bypassed. A tool the model names that wasn't offered still meets the same gateway checks as today.
- One untested risk: the window replays `tool_use` blocks naming tools that this turn's offer may not hold (the offer covers 3 turns; the window keeps up to 40). Check each of the five providers with the real-run evals. Fallback: offer every tool named in the window.
- A shortened result keeps its leading "untrusted tool output" line, its `is_error` and its `trusted` flag. Shortening is send-side only, so the taint checks still read the stored rounds. Add a test.

**No-AI pass 2, rows 101/102, the fixes.**
- Confirm before commit holds:
  - `maint_service_request` never books or pays;
  - a provider message is a `whatsapp_draft` he sends;
  - disarm never routes;
  - a manual drill is a card;
  - the monthly drill is covered by his YES in the set-up script, and its cost line must include the drill (₹1.90 at 100 MB).
- No unofficial car access: the CERT-In advisory on Tata's connected-vehicle apps (4 Nov 2026) is confirmed by news reports. Bound "preferred time" (≤ 40 characters).
- D13 item 1 follows OpenID Connect: when `max_age` is sent, `auth_time` must come back, so refusing without it is safe.
- D13 item 7: add a test that an armed `home_offline` is never dropped.
- Extra routers run before the generative check (`offline/rules.py:264`, before `_GENERATIVE` at `:269`), so the R14 phrases must stay anchored, as D12 says.

**Data safety outside the drill.**
- The backups and `jarvis-token-key` live in the same project. The drill proves recovery from a bad write or delete, not from losing the project or the key. Owner question 5 covers a copy outside Google; say this in C61.
- The runbook should say:
  - restoring into `(default)` after deleting it (delete protection off, then 5 minutes) keeps the free quota;
  - items deleted after the snapshot come back.
- Use the admin client's async class, or a thread, so a tick never blocks the event loop.
- Rate-limit `POST /v1/backup/drill` per owner.
- The Vitals index already made stays; deleting it is optional and free.

## E. The owner's questions

Nothing blocks I0, and every question has a safe default, in ₹. Changes:
- Question 1: "about ₹5 a month at 100 MB, about ₹40 at 1 GB"; Vitals shows the real figure after the first copy (A4).
- Question 2: 14 days ≈ ₹7, not double.
- Question 3: add "at most 2 manual drills a month, about ₹2 each at today's likely size".
- Add, with a default: no reminders about backups until you run the one-time step (A6).

## Verdict

**Not ready until A1, A2, A3, A4, A5, A6, A7 and A8 are written in.** The B lines also need correcting and the C seams adding to the I0 list. The owner isn't needed for any of it.

## Change log

| Version | Date | Release | What changed | By |
|---|---|---|---|---|
| v14.0.1 | 14 Nov 2026, 13:32 IST | R14 | First edition: fresh-context review of `r14-hardening.md` v14.0.1 on `b45e43c`. A1–A8 blocking: the cross-turn cache, the drill's vacuous checks and empty stats, the drill's clean-up and leftover cost, spending before YES and the billed TTL, the locks said honestly plus a config lock, the self-health storm and starvation, D7's missing owners, and the split's collisions. B: 54 claims sampled (51 right, 4 of them incomplete; 3 wrong). C: 12 seams. D: Google's terms and the ₹ figures recomputed at ₹95.24. E: the owner's questions | 🛠 Mark XVIII |
