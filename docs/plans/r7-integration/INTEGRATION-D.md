Version v7.0.1 · 13 Nov 2026, 19:40 IST · Release R7 · Status: Current · Owner: 🛠 Mark XVII

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
| `watch_stale` (5-minute clock: told once per silence of 26 hours, never for a phone that never synced) | `watch/jobs.py` | built |
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
`phrases`, `brief`, plus `watch` (`WatchService`), `sos` (`SosService`) and `sos_sms` (`async (uid) -> {label,
contacts: [{label, phone}]}` for Part C's `hello` reply). Its `ready` word is `ready`, `off: no token key` or
`off: no document store`. It reads the Telegram client, the clock (`helpers_now`) and the notifier LATE from the app.

## 2. Where Part D decided what the plan left open (and the deviations)

1. **A typed night is sealed inside its day** (`watch_days/{uid}_{date}`, field `typed`), not kept in clear in
   `watch_state` as the data-model table says. Strictly more private; `watch_state` holds only the last sync,
   which kinds arrive (yes / no) and when he was told the watch went quiet.
2. **A typed night wins** over the watch's and the phone's for that night (he typed it because the device was
   wrong or not worn).
3. **Writer → source:** `com.noisefit` (`models.WATCH_WRITERS`) is "watch"; every other writer, the phone itself
   and any other app, is "phone", because the brief's line has only those two words (D18). The list can grow.
4. **The clock where he slept:** a night's start and end are read in each time's own UTC offset (what the phone
   wrote), and its minutes from the absolute times, so a night across a time-zone change sums right. "Ends
   between 00:00 and 14:00" uses that same local clock (14:00 itself counts).
5. **Two sessions, one night:** "last night" is the longest session, as D18 says (not their sum).
6. **SOS documents inside the plan's collections:** `sos_log/{uid}_budget` (the last day's send times, real and
   tests apart, in one transaction), `sos_log/{uid}_last` (the newest entry, for the card) and
   `sos_join/wrong` (the wrong-word counter: 30 an hour from anyone, then every join waits for the hour). No
   composite index: every query is one equality on `uid`.
7. **If the limits cannot be read** (the store fails during the budget transaction) a REAL SOS still goes out
   and the log says so; a test or "I'm safe" is refused. An emergency beats a counter.
8. **Every press that passes the limits counts**, delivered or not. A refused press counts nothing.
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
| `pytest tests/test_r7_d_*.py tests/test_telegram_client.py` (Python 3.12) | 174 passed |
| Guard tests (`test_r7_seams.py`, `test_r7_telegram_hook.py`, `test_r11_1_seams.py`, `test_arch_coverage.py`, `test_telegram_tool_guard.py`, every `test_telegram_*`) | all pass except the one I0 pin of §4.1 |
| `ruff check` / `ruff format --check` on every file Part D touched | clean |
| `mypy` on `watch`, `sos`, `api/watch.py`, `api/sos.py`, `telegram/client.py` | clean (only the 9 pre-existing errors elsewhere) |
| `evals/r7/run.py --mock --part body` | 11/11; each of the four controls fails its case |
| Browser `tests/browser/test_r7_d_body.py` | see the final report (run under the shared lock) |
| Sizes | `console-r7-sos.js` 343 lines, `console-helpers-watch.js` 151, `console-r7-sos.css` 38 (≤ 150) |

## 4. Needs I1

1. `tests/test_r7_seams.py::test_the_app_starts_with_four_stub_parts_and_their_status_routes` pins
   `wiring.door_handlers(app) == {}` ("no part has built its handlers yet"). With Part D built it is
   `{"health", "sos"}` (and Part C's `hello`, `inbox`). Move the pin; Part D may not edit that file.
2. **The brief's sleep line (acceptance check 8).** `BriefService` must ask the body part's
   `services["brief"].sleep(uid, tz, day)` and put the `SleepLine` (or None) into `BriefData.sleep`;
   `render_text` stays as it is (the e-mailed copy and Telegram carry no sleep). `console-brief-sections.js` must
   draw `d.sleep` as one line: `Sleep: {h} h {m} min, {start} to {end} · from your watch | from your phone |
   typed by you` (`jarvis.watch.sleep.brief_text` is the server's copy of the words). `lines()` is always empty.
3. **Part C's `hello` reply** should read `app.state.r7_parts["body"].services["sos_sms"](uid)` for the phone's
   SMS screen (`{label, contacts: [{label, phone}]}`); a `SosOff` / `SosUnavailable` there means no contacts.
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

## 5. For Part C and Part E

- **C:** the door hands `health` and `sos` to Part D's handlers exactly as `FakeDoor` does; Part D trusts every
  check of D6 to have run. Both handlers answer JSON only; `sos` answers 200 with the honest view for every
  outcome (refused and failed included), 422 for a bad body, 500 `{error: failed}` only for the unforeseen.
- **E:** the `sos` reply's `results[].status` is one of `sent`, `sent_no_pin`, `failed`, `not_joined`;
  `sent` is true only when at least one contact's message was taken by Telegram; `sms.text` is the message the
  server used (with the map link when a place came). Open the SMS screen and the 112 button whatever it says.
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

## Change log

| Version | Date | Release | What changed | By |
|---|---|---|---|---|
| v7.0.1 | 13 Nov 2026, 19:40 IST | R7 | First edition: what Part D built (watch intake, sealed days, sleep, tools, phrases, the brief slot, watch_stale and the sweep; SOS contacts, join words, the send and its limits, the hook, send_location; the routes, the console sheet, card and Watch tab; privacy rows; the eval), the 15 decisions and deviations, the checks, the nine needs for I1, notes for C and E, what was not verified | 🛠 Mark XVII |
