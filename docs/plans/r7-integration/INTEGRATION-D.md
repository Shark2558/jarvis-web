Version v7.0.2 · 13 Nov 2026, 22:10 IST · Release R7 · Status: Current · Owner: 🛠 Mark XVII

# R7 — Part D · Watch, sleep and SOS: notes for I1

Built on `r7-d` from `r7-i0` @ `9d96320` by the Part D builder in the Workshop (🛠 Mark XVII). The plan is
`docs/plans/r7-mobile.md` v7.0.4 (D17–D20, D25; Part D's rows in "Part split" and "Tests and evals per part";
acceptance checks 8, 9 and 11). No wiring file was edited (BRIEF-COMMON §2). Part D owns no line of
`telegram/service.py` or `telegram/rules.py`.

## 1. What Part D built

| Deliverable | Where | State |
|---|---|---|
| The `health` door's intake: the body checked whole (strict integers, ranges, 35 days, offsets, one writer name per value), refused in fixed words that never echo a value | `watch/models.py`, `watch/door.py` | built |
| One sealed day a night (`watch_days/{uid}_{date}`, purpose `watch`, AAD binds the date), the sync state by kind only (`watch_state/{uid}`), a typed night kept sealed inside its day, the 400-day sweep | `watch/store.py`, `watch/jobs.py` | built |
| Sleep in plain code: last night (longest session ending 00:00–14:00 where he slept, one writer: the watch before the phone; a typed night wins), the week (average, spread of bedtimes), fixed sentences, never advice | `watch/sleep.py`, `watch/words.py`, `watch/service.py` | built |
| Tools `sleep_last_night`, `sleep_week`, `watch_today` (R1), `sleep_note` (R2), `sos_status` (R1, the brain's only SOS tool; counts only) | `watch/tools.py`, `sos/tools.py` | built |
| No-AI phrases: "how did I sleep", "how did I sleep this week", "steps today", "what's my heart rate today", "I slept 11:30 to 6", "sos status", "who are my emergency contacts" | `watch/phrases.py` | built |
| The brief's sleep line in the pinned slot (`BriefData.sleep`, `SleepLine`); never a Helpers line (so never in the e-mailed copy or on Telegram) | `watch/brief.py` | built; wiring is I1's (§4.2) |
| `watch_stale` (5-minute clock: told once per silence: 26 hours without a sync, a phone whose syncs are all refused, or 3 days with no data; v7.0.2) | `watch/jobs.py` | built |
| SOS: sealed contacts book (`sos/{uid}`, purpose `sos`), one-time join words (192 bits, kept only as `keyring.mac("sos", word)`, 24 hours, used once, their own wrong-word counter), the send (each joined chat once, the fixed template and a map pin, honest per-contact results, limits 3/h and 10/day for a real SOS and a separate 3/h, 10/day for tests and "I'm safe"), the log (`sos_log`, no place), the audit line, the owner's `sos_sent` notice (no name) | `sos/models.py`, `sos/message.py`, `sos/store.py`, `sos/service.py` | built |
| The code behind I0's Telegram hook (`ContactHook`: never raises; join, a contact's `/stop` removes them and tells him `sos_contact_left` without a name) | `sos/contacts_hook.py` | built |
| `send_location` (the pin travels in the POST body only, errors name the method only) | `telegram/client.py` | built |
| Routes `/v1/watch` (+ `/sleep`) and `/v1/sos` (+ `/sheet`, `/label`, `/contacts`, `/contacts/{id}`, `/contacts/{id}/link`, `/send`) | `api/watch.py`, `api/sos.py` | built |
| Console: the SOS sheet (2 s hold, 5 s countdown with a full-width Cancel, place asked when it opens, honest results, SMS screen and 112 always), Integrations → Emergency SOS, the voice command `sos.open` (opens only), `JarvisMobile.parts.sos = {open, close, isOpen}` | `console-r7-sos.js`, `console-r7-sos.css` | built |
| Helpers → Watch (today, last night with stages, the week, last synced, a typed night) | `console-helpers-watch.js` | built |
| Privacy rows `watch_days` (passkey delete, export) and `sos` (confirm delete, export) | `watch/privacy.py` | built |
| Eval `evals/r7/body.py` (BUILT): 11 cases, four negative controls, each failing its own case | `evals/r7/body.py` | built |

`watch.part.build(ctx)` returns `MobilePart("body")` with the five tools, `clock_jobs=(watch_stale,)`,
`daily_jobs=(body_sweep,)`, `privacy=(watch_days, sos)` and the services `door` {`health`, `sos`}, `sos_hook`,
`phrases`, `brief`, plus `watch` (`WatchService`), `sos` (`SosService`) and `sos_contacts` (`SosService.sms_view`:
`async (uid) -> {label, contacts: [{label, phone}]}` for Part C's `hello` reply; renamed from
`sos_sms` in v7.0.2 because Part C reads `sos_contacts`). Its `ready` word is `ready`, `off: no token key` or
`off: no document store`. It reads the Telegram client, the clock (`helpers_now`) and the notifier LATE from the app.

## 2. Where Part D decided what the plan left open (and the deviations)

1. **A typed night is sealed inside its day** (`watch_days/{uid}_{date}`, field `typed`), not kept in clear in
   `watch_state` as the data-model table says. Strictly more private; `watch_state` holds only the last sync,
   which kinds arrive (yes / no) and when he was told the watch went quiet.
2. **A typed night wins** over the watch's and the phone's for that night (he typed it because the device was
   wrong or not worn).
3. **Writer → source** (the Workshop's question from Part E, 13 Nov): `com.noisefit` (`models.WATCH_WRITERS`)
   is "watch" ("from your watch"); Health Connect's own `android` (`models.PHONE_WRITERS`) is "phone" ("from
   your phone"); ANY other writer (another maker's health app, Google Fit) is "app", said neutrally: "from
   another health app" and "these are that app's own estimates" in the tools, the No-AI answers and the Watch
   tab. It is never claimed as the watch's or the phone's. One night keeps one writer: the watch, then the
   phone, then any other app (D17), then the longest session. **The brief's pinned `SleepLine` knows only
   watch / phone / typed**, so an "app" night is written there as "phone" (an app on his phone; the console's
   one brief line would read "from your phone"); a fourth source would be a contract change, I1's to make
   (§4.10). Tests: `test_r7_d_watch_intake.py`, `test_r7_d_sleep.py`, `test_r7_d_watch_tools.py`.
4. **The clock where he slept:** a night's start and end are read in each time's own UTC offset (what the phone
   wrote), and its minutes from the absolute times, so a night across a time-zone change sums right. "Ends
   between 00:00 and 14:00" uses that same local clock (14:00 itself counts).
5. **Two sessions, one night:** "last night" is the longest session, as D18 says (not their sum).
6. **SOS documents inside the plan's collections:** `sos_log/{uid}_budget` (the last day's send times, real and
   tests apart, in one transaction), `sos_log/{uid}_last` (the newest entry, for the card) and
   `sos_join/wrong` and `sos_join/wrong_{0..255}` (the wrong-word counters: 30 an hour per chat, 300 an hour from everyone, then joins wait for the hour; v7.0.2). No
   composite index: every query is one equality on `uid`.
7. **If the limits cannot be read** (the store fails during the budget transaction) a REAL SOS still goes out
   and the log says so, bounded by an in-process counter (the same 3 an hour, 10 a day); a test or "I'm
   safe" is refused. An emergency beats a counter, never an unbounded one (v7.0.2).
8. **A press that passes the limits counts, unless it reached nobody**: a real press with `reached == 0`
   gives its slot back (v7.0.2), so failed presses never lock the owner out of a real one. A refused press
   counts nothing. Privacy "delete SOS" keeps the send times (it never resets the limits).
9. **The owner's notice goes for every press** (sent, partial, failed, nobody joined, refused, unavailable; real,
   test and "I'm safe"), always as `sos_sent`, counts only, so a mis-press or a failure shows on every channel.
10. **`/stop` removes the whole contact** (label and number too: "removes them", D20).
11. **"I'm safe" goes to every joined contact** (the list an SOS uses), shares the tests' budget, carries no place,
    and on the web it is held and counted down like the others (so is "Send a test").
12. **The set-up is not changed while the app is locked:** the SOS routes stay never-locked (D21), so the sheet
    and the send work; but while Part C's `app_lock` check says the session is locked, `PUT /label`,
    `POST/DELETE /contacts…` and `/link` answer 423 `device_locked`, and `GET /v1/sos` names no one. A lock
    that cannot be read counts as locked for the set-up only.
13. **His label** defaults to "the owner of this JARVIS" until he sets it (the card asks).
14. **`sos_status` is named safe on Telegram** in `tests/test_telegram_tool_guard.py`'s `TELEGRAM_SAFE` (Part D
    owns the existing `test_telegram_*`): it says counts and times only, as the plan intends.
15. **Fake coordinates:** fixtures use (−31.415926, −17.320508), the open South Atlantic. The first choice
    shared digits with the Telegram fake's bot token, and the needles scan rightly flagged it.

## 3. Checks run here

| Check | Result |
|---|---|
| `pytest tests/test_r7_d_*.py` / `tests/test_telegram_client.py` (Python 3.12) | 178 passed / 16 passed |
| Coverage of `jarvis.watch` and `jarvis.sos` (by those tests) | 92 % |
| Guard tests (every `test_r7_*`, `test_r11_1_seams.py`, `test_arch_coverage.py`, every `test_telegram_*` with the tool guard, `test_r51_console_assets_linked.py`) | 867 passed, 2 failed: the two I0 pins of §4.1 |
| `ruff check` / `ruff format --check` on every file Part D touched | clean |
| `mypy` on `watch`, `sos`, `api/watch.py`, `api/sos.py`, `telegram/client.py` | clean (only the 9 pre-existing errors elsewhere) |
| `evals/r7/run.py --mock --part body` / the whole runner | 11/11, each of the four controls fails its own case / 25/25, exit 0 |
| Review follow-ups (v7.0.2): Part D's unit tests + `test_telegram_*` | see §7 |
| `scripts/arch_coverage.py`, `scripts/check_doc_versions.py` | OK (95 collections) / 27 documents pass |
| Browser `test_r7_d_body.py` with `test_ui_audit.py`, `test_dock_fit.py`, `test_r7_i0_sheet.py` | 166 passed (the card, the sheet and the Watch tab through the visual gate at both sizes, Night and Day) |
| Sizes | `console-r7-sos.js` 345 lines, `console-helpers-watch.js` 149, `console-r7-sos.css` 37 (≤ 150) |

## 4. Needs I1

1. Two I0 pins in `tests/test_r7_seams.py` (Part D may not edit it) hold every part as a stub and turn red
   once a part is built: `test_the_app_starts_with_four_stub_parts_and_their_status_routes` pins
   `wiring.door_handlers(app) == {}` (with Part D it is `{"health", "sos"}`, and Part C's `hello`, `inbox`), and
   `test_the_r7_runner_passes_with_its_contract_built_and_the_rest_stubs` expects `body:not_built_yet` and
   `body` in `parts_not_built` (the runner itself passes, 25/25 with Part D's controls failing). Move both.
2. **The brief's sleep line (acceptance check 8).** `BriefService` must ask the body part's
   `services["brief"].sleep(uid, tz, day)` and put the `SleepLine` (or None) into `BriefData.sleep`;
   `render_text` stays as it is (the e-mailed copy and Telegram carry no sleep). `console-brief-sections.js` must
   draw `d.sleep` as one line: `Sleep: {h} h {m} min, {start} to {end} · from your watch | from your phone |
   typed by you` (`jarvis.watch.sleep.brief_text` is the server's copy of the words). `lines()` is always empty.
3. **Part C's `hello` reply** (name fixed in v7.0.2; add the pin to `test_r7_seams.py`: a missing `sos_contacts` must fail loudly, and C could log a warning when it is absent) reads `app.state.r7_parts["body"].services["sos_contacts"](uid)`
   (`SosService.sms_view`) for the phone's offline SMS screen and puts it under `sos`, as phone-contract §4
   says: `{"label": his name for the message, "contacts": [{"label", "phone"}]}`, only the contacts that have
   a number (an SMS needs one). It raises `SosOff` (no token key) or `SosUnavailable` (the store failed):
   C answers `hello` without `sos` then, and the phone keeps the list it had (an empty `sms.numbers` in a `sos` answer means the same: use the cached list).
4. **Part A's `do=sos`** opens the sheet with `window.JarvisMobile.parts.sos.open()`.
5. **The persona at `p7.0`:** JARVIS can never send an SOS and says how he does (the hold, the phone, 112); sleep
   and heart numbers are the watch's or the phone's estimates, never a diagnosis.
6. **The guide:** cards C64 "Watch and sleep" and C65 "Emergency SOS" from PLANNED to built, with §1's files and
   §2.6's documents (`sos_join/wrong`, `sos_log/{uid}_budget`, `sos_log/{uid}_last`); C64 names the typed night
   as sealed inside its day (§2.1).
7. **The real notifier path for `sos_sent`:** Part D tested the notice with a recording notifier; I1 should run
   one send through the real `NotifyService` and check that quiet hours, the storm control and the Telegram cap
   all let it through (I0's `NO_SWITCH` and `NO_CAP_KINDS`).
8. **The needles scan:** the only places a coordinate may appear are the request bodies sent to Telegram
   (`sendMessage`'s map link, `sendLocation`'s pin) and the reply to the owner's own POST (its SMS text); every
   document, log record, audit line, Activity row, alert and address must stay clean (Part D's eval checks
   these for its own paths).
9. **The whole suite:** Part D ran only its own files and the guard tests; nothing else of the suite was run.
10. **Optional, a contract change:** if the brief's line should also say "from another health app", add
    `"app"` to `brief.models.SleepLine.source` and to the console's brief words; Part D's `sleep_line` then
    passes it through instead of writing "phone" (§2.3).

11. **A join notice (wanted later, not built):** the owner sees who joined in Integrations → Emergency SOS
    (the date and the last four digits of the Telegram account; I0's hook gives only ids, so a first name
    would need a hook change). If a notice is wanted, I1 adds an alert kind; Part D adds none.
12. **A phone that never synced and never tried** cannot be told about by Part D (it does not know a phone
    is linked). If wanted, Part C offers a seam with the link time; `watch_stale` then treats it as a silence.
13. **Part E** sends exactly `press_id` as the one new field of the `sos` payload (§5).
14. **`SleepLine` and an unreadable sleep read** (silent L5): the brief shows nothing when the sleep store
    cannot be read; the pinned `SleepLine` has no flag for it (§7, declined). If a note is wanted, it is a
    contract change.

## 5. For Part C and Part E

- **C:** the door hands `health` and `sos` to Part D's handlers exactly as `FakeDoor` does; Part D trusts every
  check of D6 to have run. Both handlers answer JSON only; `sos` answers 200 with the honest view for every
  outcome (refused and failed included), 422 for a bad body, 500 `{error: failed}` only for the unforeseen.
- **E:** the `sos` reply always carries `reached` (how many contacts' messages Telegram really took; a
  message Telegram refused, or that did not answer within 12 seconds, is never counted), `joined` (contacts
  on Telegram), `total`, `outcome` (`sent`, `partial`, `failed`, `none_joined`, `refused`, `unavailable`),
  `results[].status` (`sent`, `sent_no_pin`, `failed`, `not_joined`) and `words` (plain words). `sent` is true
  only when `reached` is at least 1. `sms.text` is the message the server used (with the map link when a
  place came). Open the SMS screen and the 112 button whatever it says. Since v7.0.2: an answer
  with `sms.numbers: []` (store down) means "use your cached `hello` list"; the request may carry
  `press_id` (a string of 16 to 64 of A-Z a-z 0-9 _ -, one per press; a repeat within an hour gets
  the first answer and sends nothing again) and NO other new field; a bad place is dropped and the
  answer says "sent without your location"; only `kind` must be right; a 422 or 500 carries `detail`
  (plain words), `sent: false` and `call` (open SMS and 112 for ANY non-200); the answer also has
  `told` (the owner's other devices were really alerted) and `logged`.
  `health` answers 422 `{error: invalid}` for any value outside the contract and never says which (fix the day
  builder, never the server).

## 6. Not verified here

- Telegram itself (`sendMessage`, `sendLocation`, the join link's Start) was faked (`telegram_fakes.FakeBot`);
  a real bot, a real contact and a real map pin are the owner's acceptance check 9, with a TEST, never a real
  SOS to his family.
- A real phone's geolocation in the console sheet (Chromium's was faked) and the `sms:` / `tel:` links opening
  the phone's own apps.
- Firestore's transactions (the memory twin serialises them; Firestore retries on conflict; the functions are
  written to be retried).
- The real NoiseFit and phone writer names on his phone (only `com.noisefit` is known to be the watch).

## 7. Review follow-ups (v7.0.2)

Three fresh-context reviews of `r7-d` @ `bfcadb4` (silent-failure BLOCK, security WARN, code BLOCK) and the
Workshop's nine decisions. Commits: **A** = `c9ddb2e` (SOS service, store, routes, door), **B** = `ee8a249`
(watch store and jobs, flaky needles), **C** = `6c20a64` (sheet and Watch tab JS and their browser tests),
**D** = the docs commits that carry this section.

**Owner decision (security M1), written here with its safe default.** While the app is locked, `/v1/sos/send`
accepts only kind `real`; "test" and "I'm safe" answer 423 `device_locked` in plain words (a thief holding a
locked phone could otherwise tell the family "I'm safe" and stand down help). The sheet and the answer carry no
contact label (`Contact 1`, `Contact 2`), the sheet has no `label` and no `first` number; the numbers travel only
inside the SMS link of the SOS screen (needed to text the family), never shown as text. A lock that cannot be
read counts as locked. The owner may later choose to relax this (for example to let a test through); the default
stays until he does.

| Finding | Result |
|---|---|
| silent H1 (empty `sms.numbers` hid the SMS link) | fixed in A (`unavailable` answers say "use your cached list") and C (the console keeps the sheet's numbers and uses them whenever an answer's list is empty; browser test) |
| silent M1 (unreadable book looked like "no contacts") | fixed in A (`sheet`: `unreadable`, `warning`) and C (the warning on the sheet, the sheet read again before the press) |
| silent M2 (`told` true for hold/drop) | fixed in A (`told` only for ring or silent to a channel) and C ("I couldn't confirm that your other devices were alerted") |
| silent M3 / security L1 / L3 / code M4 (budget) | fixed in A: a real press that reached nobody gives its slot back; unreadable limits fall back to an in-process 3/hour, 10/day counter; delete never resets the limits; a `gather` test; `press_id` |
| silent M4 / code M2 (no deadline) | fixed in A (log, audit and notice run apart and are waited for 5 s; book and limits 8 s) and C (20 s then "UNKNOWN: it may have gone", SMS and 112) |
| silent M5 (error bodies dropped, "[object Object]") | fixed in A (every error carries `detail` and `words`; the body is read by the route, so FastAPI's own 422 never reaches the console) and C (a message containing "[object" is never shown) |
| silent M6 (a bad place refused the whole SOS) | fixed in A for the web and the door (dropped, "sent without your location"; 422 only without a usable `kind`, with SMS and 112 words); the old test was updated |
| silent M7 (`watch_stale` blind spots) | fixed in B: refused syncs are counted and told, the newest data day is tracked (3 days without data), held notices retry after an hour, a failed `mark_told` never re-notifies, a missing notifier is logged and counted (`no_notifier`). A phone that never tried at all is not knowable here (Needs I1 12) |
| silent L1 (shared chat has no row) | fixed in A: a second row with the first's status; counts stay per chat |
| silent L2 (`store.log` failure) | fixed in A: `logged` in the answer |
| silent L3 (corrupt budget read as empty) | fixed in A: a warning is logged |
| silent L4 (`put` race, one corrupt day blocks every sync) | fixed in B: one transaction; a day that will not open is replaced by the phone's sync (logged) |
| silent L5 (brief: unreadable = no night) | declined: `SleepLine` is a pinned contract with no flag for it; the failure is logged. Needs I1 14 |
| silent L6 (`console-r7.js` swallows a failed module load) | declined: `console-r7.js` is a wiring file (BRIEF-COMMON §2); noted for I1 |
| security M1 (locked phone) | fixed in A and C (the owner decision above) |
| security L2 (RecursionError) | fixed in A: caught in both door parsers (and `parse_health`) |
| security L4, code L1 (join counter) | fixed in A: per chat (256 shared counters, so strangers cannot make unbounded documents) plus a global cap of 300 an hour |
| security L5 (who joined) | fixed in A and C: the card shows the join date and the last four digits of the Telegram account (no new alert kind; Needs I1 11) |
| security L6 (test gaps) | unreadable-limits branch, concurrent presses: fixed in A. A cancelled countdown makes no request: already pinned by the browser test. A negative control for the join counter: declined (the plan names four controls) |
| security I1 (typed writer from a phone) | fixed in B (refused) |
| security I2 | fixed in B (see silent L4) |
| security I3 ("app" night shown as "phone" in the brief) | declined: disclosed deviation 2.3, the pinned `SleepLine` (Needs I1 10) |
| code H1 (flaky needles) | fixed in B: plain fields only for the short needles, `com.noisefit` for the blob; 30 eval runs pass |
| code H2 (`sos_sms` vs `sos_contacts`) | fixed in A: `services["sos_contacts"]`; `sos_sms` removed (nothing else used it) |
| code M1 (sync drops a typed night) | fixed in B (one transaction, yielding-twin tests both orders) |
| code M3 (`delete_all` raised on an unreadable book) | fixed in A |
| code L2 (`stale_told = now` hides the next silence) | fixed in B: it stores the silence it was for |
| code L3 (naive clock; keys on the off path) | fixed in B: aware times; the same keys on every path |
| code L4 (nap beats a night) | declined, commented in `sleep.py`: one writer a night is D17, the phone's day builder keeps one writer |
| code L5 (11 sequential reads) | partly fixed in B: the days of a read are fetched together; `night` and `week` still read their own days |
| code L6 (no tools with no store) | docstring fixed (the part is `off: no document store` and has none) |
| code L7 (hygiene) | fixed in A and B: `Entry.extra` removed, `tzinfo` types, no `assert` as control flow, `SosRefused.code` |
| code L8 a-e and the Watch pickers | fixed in C: blur and hidden tab end a hold, focus returns to the hold button after Cancel, the one-time link leaves the page (after Copy, when the sheet opens or closes, when Integrations closes, after 10 minutes), only the primary button starts a hold, one pointer at a time, the pickers keep their values after Save |

Checks after the follow-ups: Part D's unit files and every `test_telegram_*` (with the guard tests of
BRIEF-COMMON §6) 944 passed and the two I0 pins of §4.1 stay red by design; `evals/r7/run.py --mock --part
body` 11/11 with the negative control failing the suite, 30 runs in a row; browser `test_r7_d_body.py`,
`test_r7_d_follow_ups.py` (16 new), `test_ui_audit.py` and `test_dock_fit.py` 180 passed; `ruff check` and
`ruff format --check` clean; `mypy` on Part D's files shows only the 9 pre-existing errors.

Known limit: a repeated `press_id` is remembered in the server process (an hour, 64 presses). Two server
instances would not share it; the limits (3 an hour, 10 a day) still bound any repeat.

## Change log

| Version | Date | Release | What changed | By |
|---|---|---|---|---|
| v7.0.1 | 13 Nov 2026, 19:40 IST | R7 | First edition: what Part D built (watch intake, sealed days, sleep, tools, phrases, the brief slot, watch_stale and the sweep; SOS contacts, join words, the send and its limits, the hook, send_location; the routes, the console sheet, card and Watch tab; privacy rows; the eval), the 15 decisions and deviations (with how a writer that is neither the watch nor the phone is named), the checks, the ten needs for I1, notes for C and E, what was not verified | 🛠 Mark XVII |
| v7.0.2 | 13 Nov 2026, 22:10 IST | R7 | Review follow-ups: a failed SOS always leaves the SMS screen and 112 (kept numbers, 20 s timeout, plain words on every error, a bad place dropped), honest `told`/`logged`/unreadable sheet, budget (slot given back, in-memory fallback, delete keeps limits, `press_id`), locked = real only with no labels (owner decision), `sos_contacts` seam name, bounded side channels, per-chat join counter, one-transaction day merge, `watch_stale` for refused and empty syncs, sheet and Watch tab fixes; Needs I1 11 to 14 | 🛠 Mark XVII |
