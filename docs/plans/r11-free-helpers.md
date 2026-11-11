Version v11.0.3 · 11 Nov 2026, 21:44 IST · Release R11 · Status: Current · Owner: 🛠 Mark XIV

# Release R11 — Free proactive helpers (+ the kitchen tools that need no camera) (`v11.0.0`)

**Phase:** 4 (proactive agents), with Phase 2 tool reuse and Phase 7 evals. **Type:** free: ₹0 a month,
no new paid service, no new secret, no new Cloud Scheduler job. **Branches:** I0 `r11-i0` (from
`origin/r6-1-i1` @ `4d28928`, R6.1 not merged yet) → parts `r11-a` … `r11-d` → integration `r11-i1` → PR
`v11.0.0 · R11 Free proactive helpers · Mark XIV` (labels `release`, `Mark XIV`). Every commit carries
`JARVIS-Version: v11.0.0` and `JARVIS-Mark: XIV`. Read on `r6-1-i1` @ `4d28928`.

## Goal (plain words)

JARVIS starts looking ahead for you, for free. It reminds you of bills and gets the UPI payment ready for
your PIN (it never pays), keeps the chores rota and the home upkeep list, warns you about weather and
disasters near you, watches for breach notices, nudges you to stand up and drink water within the limits
you set, tells you your top priority and what is pending, notices when a planned walk didn't happen, offers
ideas for free time from your own list, and in the kitchen suggests recipes from what you have, works out
rough nutrition, totals your grocery spend from your e-mailed receipts and blocks cooking and washing-up
time in your calendar. Everything that can be plain code is plain code, so it all works with the AI off;
only new recipe ideas use the brain, metered like any reply.

## The 16 items: skill, layer, phase, part

| # | Item | Core skill | Layers | Phase | Part | Brain? |
|---|---|---|---|---|---|---|
| 1 | Bills, due dates, a UPI payment prepared for his PIN | Finance & Analytics | L5, L6 (gateway R3 card), L8 | 4 | A | no |
| 2 | Chores rota | Task & Productivity | L5, L3 clock, L8 | 4 | B | no |
| 3 | Home maintenance schedule | Task & Productivity | L5, L3 clock, L8 | 4 | B | no |
| 4 | Weather alerts | Research & Intel | L6 (Open-Meteo, SACHET), L8 | 4 | B | no |
| 5 | Disaster alerts (India) | Security Advisor | L6 (NDMA SACHET CAP), L8 urgent | 4 | B | no |
| 6 | E-mail breach monitoring → **breach-notice watching** (D14) | Security Advisor | L6 Gmail, L8 | 4 | B | no |
| 7 | Birthday reminders (Google Contacts) | Communication | L6 People API, L8 | 4 | A | no |
| 8 | Stand-up nudges | Health & Wellbeing (planned 11th skill; Task & Productivity until then) | L3 clock, L8 | 4 | C | no |
| 9 | Hydration reminders | Health & Wellbeing (as 8) | L3 clock, L8, L7 sealed log | 4 | C | no |
| 10 | "Top priority now" and what is pending | Decision Support | L5, L6 Tasks/Calendar | 4 | A | no |
| 11 | A nudge when a planned activity didn't happen | Task & Productivity | L6 Calendar, L3 clock, L8 | 4 | C | no |
| 12 | Free-time suggestions from his own list | Task & Productivity | L6 Calendar, L5 | 4 | C | no (code picks) |
| 13 | Recipes from what he has (veg / non-veg, spicy, oily, cuisine) | Learning (cooking) | L4 router (balanced), L5 | 4 | D | **yes**, metered |
| 14 | Nutrition per dish (D15: USDA FoodData Central, not INDB) | Health & Wellbeing (as 8) | L5, L7 bundled data | 4 | D | no |
| 15 | Grocery spend a month from e-mailed receipts | Finance & Analytics | L6 Gmail (like the parcels reader), L7 sealed | 4 | D | no |
| 16 | Cooking and washing-up calendar blocks | Task & Productivity | L6 Calendar + approval cards | 2/4 | D | no |

Not in this plan: paying anything (JARVIS has no way to move money and keeps none), messages to anyone but
the owner (the chores rota tells only him), the camera kitchen (R8–R10), a stock pantry from receipts, meal
plans for children, any wearable.

## What the code says today (`r6-1-i1` @ `4d28928`)

1. **Clock.** Two Scheduler jobs of the 3 free ones: `jarvis-morning-brief` (`0,30 4-11 * * *`, `api/brief.py`,
   `ticks.run_jobs`, 60 s a job, 150 s a tick) and `jarvis-home-watchdog` (`*/5 * * * *`, 60 s attempt
   deadline, `home/watchdog.py` `WATCHDOG_BUDGET_S = 50`). `deploy/cloudrun.sh` step 8 creates the watchdog
   job **whatever Home is set to**, but with Home off `app.state.home_watchdog` is None and
   `POST /internal/home/watchdog` answers zeros and runs nothing (`api/home.py` l.146). So today nothing runs
   between 11:30 and 04:00 unless Home is on. `Watchdog.extend(job)` adds a job (R5.1 health, R6 book);
   `ADVISORY_JOBS` never 503 it. `home_watchdog.run` passes the linked homes as owners: R6 jobs ignore the list.
2. **Alerts.** `AlertKind` 23 (`alerts.py`), levels in `notify/ports.py` `DEFAULT_URGENCY` (pinned
   `== 23` in `test_r3_seams.py` l.163 and `test_r6_seams.py` l.138), `SignalSource` already has `"nudge"`.
   Policy (`notify/policy.py`): quiet hours 23:00–06:30 hold "important" and drop "info"; default
   `ring_for="urgent"` makes "important" silent unless in `DAYTIME_RING_KINDS`. Storm (`notify/storm.py`):
   soft-urgent gaps for health/vitals. Telegram (`notify/telegram_out.py`): normal kinds 10 an hour / 50 a
   day, urgent 30 / 100; kinds without an R1 toggle obey the policy switch only. Held summary words
   (`notify/held.py`), the Alerts card's kind list (`console-alerts.js` `KINDS`). Alert text is always a fixed
   template (C45); `named_message` only when "names in alerts" is on (D20 of R3, default off).
3. **Brief.** Typed sections (`brief/models.py`): `VitalsSection(lines, state)` is the simplest; a source
   has `section(uid, tz, day)`; `_own_section` bounds each (`EXTRA_TIMEOUT_S`); render `_vitals`; console
   `console-brief-sections.js` `vitals()`. `build_brief_service` in `api/app.py` passes each source.
4. **Tools.** `tools/setup.py` `build_gateway(..., r4=R4Parts)` → `register_r4_tools`. `Tool.ask_when` makes
   any call a card (slice 11 D7a); R3 is never approvable on Telegram (C04); `content_tainted()` and
   `context_trust` exist; `Preview.also` lets a tool obey another row.
5. **Permissions.** 38 rows (`permissions/groups.py`, pinned `len == 38` in `test_r3_seams.py` l.885; maps
   in `test_permissions_policy.py` `RISK_OF`/`TOOL_OF`/`EXPECTED`); sections contiguous; Maps and YouTube last.
6. **Keyring.** 13 cipher purposes + `webpush_vapid` (pinned set `test_r3_seams.py` l.833).
7. **Google.** `REQUIRED_SCOPES` calendar.events, calendar.readonly, gmail.readonly, gmail.compose; optional
   Grants tasks, contacts (`contacts.readonly`), youtube, photos (`integrations/google.py`). Contacts today
   uses `people:searchContacts` with `READ_MASK = "names,emailAddresses,phoneNumbers"` (`contacts/client.py`);
   `people.connections.list` with `personFields=names,birthdays` needs the same scope (no new Grant).
   Background readers call the connector directly and obey the owner's row by `Policy.decide` (the
   DigiLocker inbox job, `api/personal.py` `_drive_allowed`), audited.
8. **Parcels reader** (`packages/`): fixed sender domains, `authenticated(results, domain)` checks the
   Authentication-Results alignment, pure parsing, no model: the pattern for receipts and breach notices.
9. **No-AI** (`offline/rules.py` `route_no_ai`, `offline/no_ai.py`): fixed patterns → gateway calls; a
   "don't remind me …" would hit `_remind` today, so R11 phrases must run before it. `BrainMode` is the one
   object Brain and the No-AI runner share (`offline/mode.py`).
10. **Privacy** (`privacy/ports.py` `PrivacySource`, `api/personal.py` `privacy_sources`: R6's rows then
    Faces last). **Groceries** (`groceries/`): a Google Tasks list. **Vitals** "bills" are JARVIS's own
    service bills, not household bills (reuse its "amber N days before" idea, not its store).
11. **Limits to respect.** `console.html` 792 lines (< 800); `api/app.py` 743 (guard ≤ 750,
    `test_r6_wiring_seams.py` l.75); dock 20 tabs (pinned in `test_console_assets.py` l.505,
    `test_arch_coverage.py` l.529, browser `test_dock_fit.py`); the guide's coverage check runs in the unit
    suite (`test_the_real_guide_passes`): a new package, console module, collection or API host needs its card.

## External sources (verified 11 Nov 2026 with web search; the sandbox reaches none of them)

| Source | Used for | Terms, limits, key | Fallback |
|---|---|---|---|
| **Open-Meteo** forecast API (`api.open-meteo.com`) | 4: hourly forecast, thresholds, the brief's weather line | Free for non-commercial use, which explicitly includes "personal home automation"; no API key; 600 calls a minute, 5,000 an hour, 10,000 a day, 300,000 a month per IP; data CC BY 4.0 (attribution "Weather data by Open-Meteo.com") | SACHET's IMD warnings still arrive; the brief says "weather unavailable" |
| **IMD API** (`mausam.imd.gov.in`) | not used | Needs IP whitelisting by request (its own request form) | Open-Meteo + IMD's CAP warnings via SACHET |
| **NDMA SACHET** CAP feeds (`sachet.ndma.gov.in/cap_public_website/rss/rss_<state>.xml`, national `rss_india.xml`) | 5 and the official half of 4 | RSS 2.0, channel `copyright` "public domain"; each item links a CAP 1.2 XML (`FetchXMLFile?identifier=`); no key or sign-up seen; no published rate limit (JARVIS polls the one state feed every 10 min, ~144 a day); state and district granularity only; no CORS (server-side only) | the national feed; the panel says "can't reach SACHET since …"; the official SACHET app, SMS and cell broadcast stay the primary channel |
| **Have I Been Pwned** API | not used (D14) | The e-mail search (`breachedaccount`) is an authenticated, paid-subscription API; Pwned Passwords is free but is for passwords | — |
| **HIBP "Notify me"** (and Mozilla Monitor) | 6: he subscribes his own address; JARVIS watches Gmail for their notices | Free; HIBP verifies the address by e-mail. JARVIS sends his address nowhere | none needed; he can also check the sites by hand |
| **XposedOrNot** free API | not used by default (owner decision 4) | No key; 2 a second, 25 an hour, 100 a day; "personal and low-volume use"; the address travels in the URL to a third party; full terms not read | — |
| **Indian Nutrient Databank (INDB)** | **not usable** (D15) | The GitHub repository states no licence (so all rights reserved by default) and says its IFCT data "must be requested from the original source"; IFCT 2017 is ICMR-NIN's, free to read but with no reuse licence | USDA FoodData Central |
| **USDA FoodData Central** (SR Legacy / Foundation, bulk download) | 14: per-ingredient nutrients, a bundled subset | CC0 1.0, public domain, "no permission is needed", citation requested; the API needs a free data.gov key (1,000 an hour) → not used: the bulk file is converted once into the image | nutrition answers "nutrition data not installed" until the subset exists (owner decision 6) |
| **Google People API** `people.connections.list` | 7: birthdays | The existing `contacts.readonly` Grant; `personFields=names,birthdays`; ≤ 1,000 a page (Google's documented page size, *unverified* here: its page refused the fetch) | no Grant → the Today tab says "Grant Contacts in Integrations" |
| **NPCI UPI deep link** `upi://pay?pa=…&pn=…&am=…&cu=INR&tn=…` | 1: the prepared payment | A payer-initiated pay intent (P2P collect requests ended 1 Oct 2025 and are not used); whether every UPI app accepts a pre-filled P2P intent from outside is *unverified* | the card shows the UPI ID and the amount to type by hand |
| **segno** 1.6.6 (PyPI) | 1: the QR as SVG on the server | BSD-3-Clause, pure Python, no dependencies, released 12 Mar 2025 | the link only |

## Data model

Collections (all `{prefix}` = `jarvis_`; the guide's C60 card lists every one before any code names it).
"Sealed" = encrypted by JARVIS with that keyring purpose (AAD `<collection>/{uid}/v1`); without the token
key a sealed feature stays OFF.

| Collection | Part | Holds | Sealed | Kept |
|---|---|---|---|---|
| `helpers_nudge/{uid}` | I0 | per nudge kind: daily cap, snoozed-until, stopped-for-day; rev | no | until deleted |
| `helpers_gate/{uid}_{date}` | I0 | per send: kind, due minute, sent minute, outcome (no text) | no | 15 days (the exit check reads 14) |
| `helpers_clock/status` | I0 | the clock's last run and its job results (one doc per deployment) | no | overwritten |
| `bills/{uid}` | A | bills: id, label ≤ 40, payee name ≤ 40, UPI ID, amount (paise) or "varies", due rule, lead days, last 4 digits at most, paid history ≤ 24 | `bills` | until deleted |
| `bills_told/{uid}_{key}` | A | a reminder claim (bill id + due date + offset hash) | no | 60 days |
| `birthdays_told/{uid}_{key}` | A | a claim: SHA-256 of uid, the contact's resource name and the year; no name, no date | no | 400 days |
| `chores/{uid}` | B | chores, frequency, time, rota members (labels he types, adults only), whose turn | no | until deleted |
| `maintenance/{uid}` | B | upkeep items: label, every N days/months, last done, lead days | no | until deleted |
| `house_told/{uid}_{key}` | B | chore / upkeep / weather / CAP / breach claims (hashes) | no | 30 days |
| `outside/{uid}` | B | his place: district, state, lat/lon rounded to 0.01°, thresholds, breach watch on, SACHET state | `alerts_place` | until deleted |
| `nudges/{uid}` | C | each nudge: on, window, days, every N min, meeting keyword; the free-time list (≤ 50 ideas, each with minutes, indoor/outdoor) | no | until deleted |
| `wellbeing/{uid}_{date}` | C | glasses of water, stand-ups done, planned-activity check-ins (event id hash + done/missed/moved) | `wellbeing` | 30 days |
| `kitchen/{uid}` | D | pantry ≤ 200 items, diet (veg / egg / non-veg), spice 0–3, oil, cuisines, saved recipes ≤ 100 (ingredients with grams), block plan | `kitchen` | until deleted |
| `spend/{uid}_{yyyymm}` | D | grocery orders: merchant, day, amount (paise), message-id hash | `spend` | 13 months |
| `spend_scan/{uid}` | D | last Gmail scan, seen message-id hashes (≤ 500) | no | until deleted |

Keyring purposes added: `bills`, `spend`, `wellbeing`, `alerts_place`, `kitchen` (18 cipher purposes).
Never stored anywhere: a full card, account or consumer number (a run of 5+ digits in a bill field is
refused; receipts are masked before parsing), a contact's birth year, any child's data, a UPI PIN (JARVIS
never sees it), weather or CAP text in alert text, recipe prompts or replies beyond the conversation.

## Decisions (binding)

**D1 · Plain code first; the brain only for recipe ideas.** Reminders, the rota, the upkeep schedule, weather
and disaster alerts, breach notices, nudges, top priority, the free-time pick (D12), nutrition, spend totals
and calendar blocks are deterministic code with fixed templates, so they work in No-AI mode. Only item 13's
new recipes call a model (D15); in No-AI it matches his saved recipes by code and says "The AI is off, Sir:
these are from your saved recipes. New ideas need the AI switched on."

**D2 · One package, four plug-ins, no shared wiring for builders.** Everything R11 lives in
`src/jarvis/helpers/`: I0's core (`ports.py`, `kinds.py`, `gate.py`, `clock.py`, `brief.py`, `sources.py`,
`privacy.py`) and one sub-package per part, `helpers/today` (A), `helpers/house` (B), `helpers/nudges` (C),
`helpers/kitchen` (D). Each part's `part.py` has `build(ctx: HelperContext) -> HelperPart` (I0 stubs return
an empty part). `HelperPart` (frozen): `tools`, `clock_jobs`, `daily_jobs`, `privacy`, `brief`
(contributors), `pending` (sources), `phrases` (No-AI routers), `ready` (a one-line status). `HelperContext`
(frozen): settings, docs, keyring, google, notifier, sender (D4), billing, router-for (tier calls),
brain mode, permissions (live), audit, owners, tz, clock, prefix, `pending_all()` (every part's pending
sources, read late). `api/r11_wiring.py` (I0) builds the four in order A, B, C, D and is the only wiring.
Each part's HTTP routes live in its own `api/helpers_<part>.py` (`today`, `house`, `nudges`, `kitchen`;
I0 stubs with empty routers), mounted by `install_r11_routes`; they read their services from
`app.state.r11_parts[<part>]` per request.

**D3 · The clock: no new Scheduler job.** Two composite jobs built by I0 from the parts' jobs:
`helpers_clock` (every 5 minutes, all day: `bills_due`, `birthdays`, `chores_due`, `maint_due`,
`weather_poll`, `disaster_poll`, `nudges`, `activity_check`) with its own budget `helpers_clock_budget_s`
(20 s of the watchdog's 50), and `helpers_daily` on the morning tick (`breach_watch`, `grocery_spend`,
`helpers_sweep`; 40 s of the tick's 150). With Home on, `helpers_clock` is `extend`ed into the home
watchdog and is advisory (never a 503 for the laptop check). **With Home off, the watchdog route runs
`helpers_clock` alone** (I0 change in `api/home.py`), so the existing job serves both. The composites run
the configured owners (`ctx.owners`), never the watchdog's linked-home list. Each run writes
`helpers_clock/status`. **"On time"** = sent by the first clock run at or after the due minute (≤ 5 minutes
plus Scheduler jitter), never early, never twice (claim documents, created in a transaction before the send;
a claim whose send no channel took is released for the next run). If step 8 never made the watchdog job, the
Helpers panel says "Your 5-minute clock isn't running: reminders come only between 04:00 and 11:30" and
names the re-run.

**D4 · One sender for every helper message.** `helpers.gate.HelperSender.send(uid, kind, text, *, due,
key, named=None)`: refuses a kind that is not R11's; for nudge kinds checks the owner's `helpers_nudge`
state (stopped today, snoozed, per-kind daily cap, the deployment's `nudges_max_per_day`); then
`Notifier.notify(Signal(source="nudge", kind=kind), text, named_message=named)`; counts a send only when a
channel took or held it; records `{kind, due, at, outcome}` in `helpers_gate` (the exit check, D21). Text is
≤ 300 characters of JARVIS's own template; outside words (a CAP headline, a mail subject, a contact's name
when names are off) never go in it. No part calls the notifier directly.

**D5 · Thirteen new alert kinds (23 → 36), and the one policy.**

| Kind | Level | At night (23:00–06:30) | By day ("only urgent things ring", the default) |
|---|---|---|---|
| `disaster_alert` | urgent | rings | rings |
| `bill_due`, `birthday`, `chore_due`, `maintenance_due`, `weather_warning`, `breach_notice` | important, daytime ring | held for the morning summary | rings |
| `nudge_standup`, `nudge_hydrate`, `nudge_activity`, `nudge_free_time`, `nudge_focus` | important, daytime ring, **ephemeral** | **dropped** (a stale nudge is noise; never held) | rings |
| `weather_note` | info | feed only | silent |

Policy additions (I0): `EPHEMERAL_KINDS` (the five nudges: quiet hours → drop `stale_at_night`, never hold);
`DAYTIME_RING_KINDS` += the six important reminder kinds and the five nudges. Storm (I0, in process): a
nudge at most once per kind per 20 minutes and at most 8 an hour per owner in all (a hard ceiling equal to
the highest `nudges_max_per_hour`; the gate holds the configured 4); `disaster_alert` is treated like a
hazard: never capped, only the same warning (its `subject`) again within 30 minutes is a duplicate. It is
NOT a soft-urgent kind, because those use Telegram's normal bucket and fail closed; a disaster warning uses
the urgent bucket (fail open, 30 an hour). Every new kind has the Alerts card's on / feed / off switch (none
is in `NO_SWITCH`); held-summary words for the held ones.

**D6 · Nudges stay inside his limits.** Per-kind daily caps (defaults standup 8, hydrate 8, activity 3,
free_time 2, focus 2), never above `nudges_max_per_day` (16) in all and the D5 hourly cap; each nudge is
off until he switches it on (Nudges tab), plus the Alerts card's switch. **Snooze** 30 min / 1 h / 2 h /
until tomorrow and **stop** (for today, or for good = off) by tap (Helpers → Nudges, the brief's helpers
section) or by voice, chat or Telegram ("snooze the water reminder for an hour", "stop stand-up nudges",
"no more nudges today"), which the brain answers with `nudge_snooze` / `nudge_stop` and No-AI with C's
phrases (D18). I0 implements the state, the gate and the tap routes (`/v1/helpers/gate/{kind}/snooze`,
`/stop`, `/resume`, `PUT /v1/helpers/gate`; `kind` a nudge kind or `all`); C the nudges, the words and
the tab.

**D7 · Bills and the prepared UPI payment (A).** Bills he enters in the Today tab or by chat: label, payee
name, UPI ID (`^[A-Za-z0-9._-]{2,256}@[A-Za-z][A-Za-z0-9]{1,63}$`), amount in ₹ (or "varies"), due rule
(day of month / one date / every N months), reminder lead days (default 3, 1 and the day), optional last 4
digits. **"Pay"** asks the gateway for `bill_pay_prepare` (R3, row `bill_pay`): the card, written by code,
reads "Get a UPI payment ready: ₹1,240.00 to BESCOM (bescom@okaxis), note 'Electricity Nov'. You confirm
it and enter your PIN in your UPI app. JARVIS never pays." Approve (console only, passkey when in force, no
"don't ask again") → the result is the `upi://pay` link (`pa`, `pn` ≤ 40, `am` with 2 decimals ≤
₹1,00,000, `cu=INR`, `tn` ≤ 50 from the label) and a segno SVG QR, shown once in the card and the bill row,
never stored. He pays in his UPI app; "I paid" (`bill_paid`, R2) records the date. The payee always comes
from his own saved bill; **setting or changing a UPI ID is `bill_payee_set` (R3)** and is refused outright
while `content_tainted()` ("Type the UPI ID yourself in the Today tab, Sir"). Reminders `bill_due` at his
time (default 09:00) on each lead day, once overdue on D+1; brief line "Electricity ₹1,240 due tomorrow".

**D8 · Birthdays (A).** Read live once a day from Google Contacts (`people.connections.list`,
`personFields=names,birthdays`, ≤ 2 pages of 1,000) by the `birthdays` job: the month and day only; the
year is dropped on read and never stored, logged or shown; nothing about the contact is stored but the
claim hash. Alert `birthday` at his time (default 08:30): message "A birthday today in your contacts: open
JARVIS to see whose." and `named` "Today is {name}'s birthday." (used only when "names in alerts" is on).
Brief line lists names (the brief is his own console). No Grant → a plain note, no error.

**D9 · Top priority and what is pending (A).** Deterministic: `PendingItem(kind, label, due, urgency,
source)` from every part's `pending` sources (`ctx.pending_all()`), Google Tasks due/overdue, approvals
waiting and the next calendar event; ranked overdue → due today → urgency → his pinned item → due date.
`focus_now` (R1) answers "top priority now", `pending_list` (R1) the top 10 grouped by source; the
`nudge_focus` nudge (C's gate rules) says the top one at his chosen times (default off). No model.

**D10 · Chores rota (B).** Chores with daily / weekly-days / every-N-days frequency, a time and a rota of
up to 6 member labels he types (the tab says "adults only: JARVIS keeps no children's data"; no ages are
asked); the turn rotates on "done" or at the period's end. `chore_due` goes to him only: JARVIS never
messages other people.

**D11 · Home maintenance (B).** Items every N days or months with a lead time;
`maintenance_due` at 09:00 on the lead day and the due day; a starter list (water-purifier filter 90 days,
AC service 180 days, fire-extinguisher check 365 days, gas pipe check 365 days) is offered, never added.

**D12 · Weather (B).** Open-Meteo for his place (district centre, rounded to 0.01°, about 1 km), polled
every `weather_poll_minutes` (60; 24 calls a day): thresholds he may change — rain ≥ 15 mm in an hour or
≥ 64.5 mm in a day (IMD's "heavy rain"), apparent temperature ≥ 40 °C, gusts ≥ 50 km/h → `weather_warning`
once per kind per day; the brief line "Weather: 31 °C, rain likely after 15:00 · Open-Meteo". Attribution
"Weather data by Open-Meteo.com (CC BY 4.0)" in the panel and the brief. Weather is OFF until he sets his place.
**Free-time pick (item 12, C)** is code too: an idea from his list that fits the free calendar gap, wasn't
done in the last 3 days, and is indoors when D12 says rain.

**D13 · Disaster alerts (B).** SACHET's state feed every `disaster_poll_minutes` (10); each new
identifier's CAP 1.2 XML fetched once (≤ 256 KB, any `<!DOCTYPE` refused, stdlib `xml.etree` on expat ≥
2.4.1, no new dependency); matched to his district by `areaDesc` or by polygon containment of his rounded
point. **Mapping:** any non-`Met` category, or `Met` with severity `Extreme` → `disaster_alert` (urgent: it
rings at night, owner rule); `Met` `Severe` → `weather_warning`; `Met` `Moderate`/`Minor` → `weather_note`.
`msgType` Update replaces, Cancel tells "lifted" as `weather_note`. Alert text is a fixed template from a
fixed event vocabulary ("Cyclone", "Flood", "Earthquake", "Tsunami", "Landslide", "Heavy rain",
"Thunderstorm", "Heat wave", "Cold wave", else "Disaster" / "Weather"), his own district name and the
`expires` time: "Urgent: Flood warning for Thiruvananthapuram until 18:00 (SACHET). Open JARVIS." The CAP
headline and instructions are shown only in the panel, fenced as outside text. JARVIS is a second
channel; the official alerts stay primary (said in the tab).

**D14 · Breach monitoring is not possible free as asked → breach-notice watching (B).** HIBP's e-mail
search needs a paid key; XposedOrNot's free API would send his address to a third party. Instead he
subscribes at HIBP "Notify me" (and Mozilla Monitor if he likes), both free; `breach_watch` (morning tick)
looks in his Gmail for mail from a fixed sender list (each domain checked by `packages.carriers.authenticated`
alignment; the exact sender addresses are *unverified* until the builder sees a real notice) and sends
`breach_notice`: "A breach notice from Have I Been Pwned arrived. Open it in Gmail and change that password,
Sir." Obeys the `email_read` row; OFF until he says he has subscribed.

**D15 · Kitchen (D).** *Pantry and preferences* by chat or the Kitchen tab. *Recipes*: one call through
`jarvis.llm` (`router.complete(tier=BALANCED, tools=None, max_tokens=700)`) after
`billing.ensure_allowed`, recorded with `billing.record`, prompt = fixed system text + fenced data (pantry
names, diet, spice, oil, cuisines; nothing else about him); the reply must parse as JSON (title, cuisine,
diet, minutes, ingredients `[{name, grams}]`, ≤ 10 steps) or it is dropped. **A code diet check**: a
veg or egg request whose ingredients hit the fixed non-veg word list (English, Hindi, Malayalam, Odia:
chicken, mutton, fish, prawn, egg for veg, beef, pork, kozhi, meen, chingudi, …) is rejected and asked
once more, then refused. A brain that may train on content is not used (the next that doesn't, else "needs
a brain that doesn't learn from what it's told"; owner decision 3). *Nutrition*: INDB can't be used (see
sources); a bundled subset of USDA FoodData Central (`helpers/kitchen/data/fdc_subset.json`, ~150
ingredients with Indian names → FDC ids, per 100 g: kcal, protein, fat, carbohydrate, fibre, sodium; the
source file's SHA-256 recorded) built by `scripts/kitchen_fdc_subset.py`; a dish = Σ grams × per-100 g,
said as "about", raw-ingredient basis, "USDA FoodData Central (public domain)". *Grocery spend*: the
`grocery_spend` job reads Gmail order mail from a fixed merchant list (BigBasket, Blinkit, Zepto, Swiggy
Instamart, JioMart, Amazon Fresh, Flipkart Minutes, DMart Ready, Country Delight, Milkbasket; domains and
DMARC alignment as the parcels reader; *unverified* on real mail), masks every 12–19-digit run before
parsing, keeps merchant, day, amount and a message-id hash; monthly totals in the tab and a brief line on
the 1st. Obeys `email_read`. *Calendar blocks*: `calendar_kitchen_blocks` (R2, `ask_when` always → a card)
proposes recurring events on his primary calendar ("Cooking 19:00–19:45", "Washing-up 20:30–20:45", daily
or on chosen days), created through the existing Calendar client; deletes go to Recently deleted.

**D16 · Six permission rows (38 → 44)**, after Connectors, before Maps:

| Row | Section | Label | Risk | Tools |
|---|---|---|---|---|
| `bills` | Bills | See and keep your bills and due dates | R2 | `bill_*` at R1/R2 |
| `bill_pay` | Bills | Get a bill payment ready for your UPI PIN | R3 | `bill_*` at R3 (`bill_pay_prepare`, `bill_payee_set`) |
| `household` | Home helpers | Chores, home upkeep and your free-time list | R2 | `chore_*`, `maint_*`, `freetime_*` |
| `nudges` | Nudges | Nudges and your top priority | R2 | `nudge_*`, `focus_*`, `pending_*` |
| `outdoor` | Weather and alerts | Weather, disaster alerts and breach notices for your area | R2 | `weather_*`, `disaster_*`, `breach_*` |
| `kitchen` | Kitchen | Pantry, recipes, nutrition and grocery spend | R2 | `pantry_*`, `recipe_*`, `nutrition_*`, `spend_*`, `kitchen_*` |

Birthdays are `contacts_birthdays` (the Contacts row); blocks are `calendar_kitchen_blocks` (the "Add and
change your events" row, always a card). No new passkey purpose: R3 cards already take the passkey.

**D17 · Privacy rows** (each part's `privacy`, section "Helpers"): `helpers_bills` (A, passkey delete),
`helpers_birthdays` (A, the claims only, simple), `helpers_house` (B, chores + upkeep, confirm),
`helpers_place` (B, his place + breach watch, simple), `helpers_wellbeing` (C, passkey), `helpers_nudge`
(I0, caps, snoozes and the send log, confirm), `helpers_kitchen` (D, confirm), `helpers_spend` (D,
passkey). Export = JSON of what is kept; amounts in ₹; the rows say what is never kept.

**D18 · No-AI phrases.** `BrainMode.phrases` (I0): routers `(text, now) -> NoAIRoute | None` added by
`wire_r11`, tried **first** in `route_no_ai` (before `_remind`, so "don't remind me to stand up" never sets
a reminder). Each part's phrases are anchored and conservative (`^…$`-style, its own verbs and nouns) and
end in its own tools through the gateway.

**D19 · Console: one dock tab "Helpers", last.** `#p-helpers` with four sub-tabs, one per part: **Today**
(A: top priority, pending, bills, birthdays), **Home** (B: chores, upkeep, weather and alerts place, breach
watch), **Nudges** (C: each nudge, caps, snooze/stop, water log, free-time list), **Kitchen** (D). I0's shell
`console-helpers.js` builds the strip (`role="tablist"`, arrow keys), exposes `JarvisHelpers.register(tab,
{mount, refresh})` and shared builders (row, toggle, number, time, chip, empty and error states), and loads
`console-helpers-today.js` / `-house.js` / `-nudges.js` / `-kitchen.js` (ES modules, `import()`) and
`console-helpers.css`. Parts use only the shell's builders and the existing tokens and components (`.btn`,
`.pbtn`, `--hud`, `--well`, `--line`, `--ink*`); no new colours, fonts, radii or shadows; `textContent` only;
44 px targets. console.html +6 lines (792 → 798). It is the dock's 21st tab, last, so on a small screen it
folds behind More first (owner decision 2). The visual gate (`tests/browser/ui_checks.py` PANELS) and the
dock-fit test cover `#p-helpers`.

**D20 · Security.** Tool, web, e-mail, contact and CAP content is untrusted data (fenced, `textContent`,
never in alert text, never an instruction); R3 only from his own saved data, never on Telegram, no "don't
ask again"; every outside call through `httpx` with timeouts ≤ 8 s and response caps; background readers
obey his rows (`Policy.decide`) and are audited (agent `helpers`, kind only); logs carry class names and
counts, never amounts, names, places or text.

**D21 · Exit checks made measurable.** The send log (`helpers_gate`) records due vs sent minutes, so the
Nudges tab shows "This fortnight: 42 reminders on time, 0 late, 0 missed; nudges within your limits on 14 of
14 days". The evals simulate 14 days on a fake clock with the 5-minute ticks and jitter.

**D22 · Version and persona.** `__version__` = `11.0.0` at I0. Persona p6.0 → **p11.0** at I1 (the persona
follows the release): adds `HELPERS_RULE` — "You never pay anyone. For a bill you prepare a UPI payment
that he approves and completes with his own PIN. Respect a snoozed or stopped nudge. Alerts come from fixed
templates." I0 leaves the persona as it is.

## Needs the owner (safe defaults until answered; none blocks the build)

1. **"Stand-up nudges"**: a nudge to stand up and move after sitting (default). If you meant your daily
   stand-up *meeting*, the same nudge can also say "Your stand-up starts in 10 minutes" from your calendar
   (built, off by default).
2. **Helpers tab position**: last in the dock (default), or right after Approvals.
3. **Recipes on the free Gemini brain**, which may learn from what it is told: default **no**.
4. **Breach checks through XposedOrNot** (your address goes to them): default **no**; HIBP "Notify me" is free.
5. **Ask ICMR-NIN for IFCT 2017 permission** for Indian food values: default **no**, use USDA FoodData Central.
6. **Let the build fetch the USDA file** (`fdc.nal.usda.gov` is not reachable from the build sandbox): default:
   Part D ships the converter and a test fixture; the orchestrator fetches the file once where allowed; until
   then nutrition says "nutrition data not installed".
7. **Telegram buttons** for Snooze / Stop: default **no** (reply "stop water" in Telegram works).
8. **Names in birthday alerts**: follow Alerts → "names in alerts" (default off).
9. **Nudge windows**: stand-up every 60 min, water every 90 min, 09:30–18:30, Monday to Saturday; each off
   until you switch it on.
10. **Disaster alerts at night**: urgent ones ring (your rule). Also ring IMD "Severe" (orange) at night?
    Default **no** (held for the morning).
11. **Your place for weather and alerts**: none until you type your district (weather and disaster alerts off).
12. **Payment cap**: ₹1,00,000 per prepared payment (default).

## Part split (four parallel builders; worktrees; branches `r11-a` … `r11-d` from `r11-i0`; disjoint files)

- **A · Today: bills, birthdays, top priority.** `helpers/today/{part,models,store,bills,upi,qr,
  birthdays,pending,tools,phrases,privacy,brief}.py`, `api/helpers_today.py`, `console-helpers-today.js`,
  `evals/r11_helpers/today.py`, `tests/r11_fakes_a.py`, `tests/test_r11_a_*.py`. Items 1, 7, 10.
- **B · Home and outside: chores, upkeep, weather, disasters, breach notices.**
  `helpers/house/{part,models,store,chores,upkeep,weather,sachet,cap,breach,tools,phrases,privacy,brief}.py`,
  `api/helpers_house.py`, `console-helpers-house.js`, `evals/r11_helpers/house.py`, fixtures
  `tests/fixtures/r11/{sachet_rss.xml,cap_*.xml,open_meteo_*.json,breach_*.eml}`, `tests/r11_fakes_b.py`,
  `tests/test_r11_b_*.py`. Items 2, 3, 4, 5, 6.
- **C · Nudges.** `helpers/nudges/{part,models,store,standup,hydrate,activity,freetime,focus,tools,
  phrases,privacy,brief}.py`, `api/helpers_nudges.py`, `console-helpers-nudges.js`,
  `evals/r11_helpers/nudges.py`, `tests/r11_fakes_c.py`, `tests/test_r11_c_*.py`. Items 8, 9, 11, 12 (and the
  focus nudge of 10, reading A's pending through `ctx.pending_all()`).
- **D · Kitchen.** `helpers/kitchen/{part,models,store,pantry,recipes,diet,nutrition,receipts,spend,
  blocks,tools,phrases,privacy,brief}.py`, `helpers/kitchen/data/fdc_subset.json`,
  `scripts/kitchen_fdc_subset.py`, `api/helpers_kitchen.py`, `console-helpers-kitchen.js`,
  `evals/r11_helpers/kitchen.py`, `tests/fixtures/r11/{receipt_*.eml,fdc_sample.csv}`, `tests/r11_fakes_d.py`,
  `tests/test_r11_d_*.py`. Items 13, 14, 15, 16.
- **All parts**: test first; functions ≤ 50 lines, modules ≤ 400; only the planned collection names, job
  names, tool-name families and privacy ids; send only through `ctx.sender`; one `INTEGRATION-<PART>.md` in
  `docs/plans/r11-integration/`; `security-reviewer` on A (UPI, payee), B (feeds, XML) and D (receipts,
  prompt); `python-reviewer` and `code-reviewer` on all. The common brief: `docs/plans/r11-integration/BRIEF-COMMON.md`.

## Seams the I0 adds (branch `r11-i0`, tests green)

1. `jarvis.__version__` = `11.0.0` (`tests/test_about.py`).
2. `AlertKind` += the 13 kinds of D5; `DEFAULT_URGENCY`; `DAYTIME_RING_KINDS`; `EPHEMERAL_KINDS` in the
   policy; storm: the nudge hourly cap and `disaster_alert` soft-urgent; held words; `console-alerts.js`
   `KINDS`; pinned counts 23 → 36.
3. Keyring `PURPOSES` += `bills`, `spend`, `wellbeing`, `alerts_place`, `kitchen` (pinned set updated).
4. Permission rows of D16 (38 → 44; `RISK_OF`, `TOOL_OF`, `EXPECTED` and the pinned count updated).
5. `config.py`: `helpers_enabled` (on), `weather_enabled` (on: keyless), `disaster_alerts_enabled` (on),
   `nudges_max_per_day` 16 (1–40), `nudges_max_per_hour` 4 (1–8), `helpers_clock_budget_s` 20 (5–40),
   `weather_poll_minutes` 60 (15–180), `disaster_poll_minutes` 10 (5–60). Each helper is OFF per owner
   until his setup (the parts' own settings, default off).
6. `src/jarvis/helpers/`: `ports.py` (HelperPart, HelperContext, PendingItem, PendingSource,
   BriefContributor, NoAIRouter), `kinds.py` (the R11 kinds, nudge kinds, job names, privacy ids, part
   names), `gate.py` (HelperSender, the nudge state store), `clock.py` (the two composites, the status doc),
   `brief.py` (HelpersBrief), `sources.py` (Open-Meteo and SACHET URLs, attribution), `privacy.py`
   (`helpers_nudge`); stub sub-packages `today`, `house`, `nudges`, `kitchen` with `part.build`.
7. `api/r11_wiring.py` (`wire_r11`, `install_r11_routes`, `r11_tick_jobs`, `r11_privacy_sources`,
   `helpers_brief`, `register_r11_tools`), `api/helpers.py` (`GET /v1/helpers`, `PUT /v1/helpers/gate`,
   `POST /v1/helpers/gate/{kind}/{snooze|stop|resume}`), stub `api/helpers_{today,house,nudges,kitchen}.py`.
   `api/app.py`: `_log_up` moves to `api/startup_log.py` (no behaviour change), then six one-line slots
   (import; `await wire_r11(...)` after `wire_r6`; `*r11_tick_jobs(app)`; `install_r11_routes(app)` after
   `install_r6_routes`; `r11=` to `build_gateway`; `helpers=` to the brief). `tools/setup.py` `r11=`;
   `api/personal.py` `*r11_privacy_sources(app)` before Faces; `api/home.py` the Home-off clock;
   `home/watchdog.py` `ADVISORY_JOBS` += `helpers_clock`.
8. Brief: `HelpersSection(lines, state)`, `BriefData.helpers`, `SectionsStatus.helpers`, `BriefService(helpers=)`,
   render "HELPERS", `console-brief-sections.js` `helpers()`.
9. No-AI: `BrainMode.phrases` + `add_phrases`, `route_no_ai(..., extra=)`, `run_no_ai(..., extra=)`, the runner.
10. Console: dock button, More entry, `#p-helpers`, `console-helpers.js`, `console-helpers.css`, the four
    part stubs, `console-deck.js` `ORDER` + default place, `APP_ASSETS`; the asset, dock-count (20 → 21) and
    C01 tests; `ui_checks.py` PANELS.
11. Guide: card C60 "Helpers (R11)" (package, console modules, every planned collection, Open-Meteo and NDMA
    SACHET), C01/C11/C46/C51 lines, the L5 row, change log; `arch_coverage.json` api hosts; build-book
    `layers.py` `"helpers": "L5"`.
12. `segno==1.6.6` in `pyproject.toml`, `requirements.lock` (hashes) and `requirements.licences.json`.
13. Evals: `evals/r11_helpers/run.py` (R6's runner shape: `PART`, `BUILT`, `cases()`, `control()`), stub
    parts `today`, `house`, `nudges`, `kitchen`, `needles`, and I0's own **built** `gate` part; shared fakes
    `tests/r11_fakes.py`; `tests/test_r11_seams.py`, `tests/test_r11_gate.py`, `tests/test_r11_wiring.py`.
14. `docs/plans/r11-integration/BRIEF-COMMON.md`.

## Tests and evals per part (mock; each control must make its suite fail)

- **gate** (I0): caps per kind and per day; snooze and stop; ephemeral dropped at night; a send no channel
  took is not counted; the log has no text. *Control*: caps off (a 9th water nudge goes out).
- **today** (A): a bill due in 3/1/0 days → three `bill_due` at 09:00, none twice across a restart; the card
  text for `bill_pay_prepare` exactly; approve → link and QR, nothing stored; a UPI ID from a tainted round
  refused; amount > ₹1,00,000 refused; a 16-digit number in a bill field refused; birthdays: year never in
  any stored doc, log or alert, names only when "names in alerts" is on; pending order. *Control*: taint
  check off (an e-mailed UPI ID becomes a payee).
- **house** (B): rota turns; upkeep lead/due; Open-Meteo fixture → one `weather_warning` a kind a day;
  SACHET fixture: a non-Met CAP for his district → `disaster_alert` urgent at 02:00 rings, Met Severe held,
  another district ignored, a `<!DOCTYPE` CAP refused, a 300 KB CAP refused, an injected instruction in a
  CAP headline never reaches alert text or a tool; breach notice from an unaligned sender ignored.
  *Control*: district filter off (an alert for another district rings).
- **nudges** (C): 14 simulated days on the 5-minute clock with jitter: every reminder in the first run at or
  after due, none early, twice or missed; caps held; snooze/stop by tap and by phrase ("don't remind me to
  stand up" stops, sets no reminder); missed activity asked once; free-time pick fits the gap and avoids rain.
  *Control*: claims off (a restart sends twice).
- **kitchen** (D): a veg request answered with chicken is refused by code; No-AI answers from saved recipes
  with the AI-off line and no provider call; the training brain is not used; nutrition sums; receipts:
  totals per month, a planted card number never stored, unknown or unaligned senders ignored; blocks always
  a card. *Control*: diet check off.
- **needles** (I1, `r11_needles`): after a full day of every part on fakes, scan every document, log line,
  audit detail, Activity row, alert text and brief text for planted needles: a full card number, a birth
  year, a UPI ID taken from an e-mail, a CAP instruction, a pantry note, a hydration count in a log.
  *Control*: masking off.
- **Browser**: the Helpers panel and its four tabs at 1440×900 and 390×844, Night and Day (visual gate), the
  dock fits with 21 tabs, Snooze from the tab, no CSP violations or JS errors.

## Acceptance checks

1. The owner's exit checks: nudges stay within the limits he sets (gate + nudges evals; D21 line for 14
   days live); all reminders on time for 2 weeks (D3's definition; the 14-day simulation; D21 live).
2. No-AI covers every plain-code item (a test per part asks it by phrase with the AI off and sees no
   provider call); recipes say so.
3. Every alert follows the policy: a disaster alert rings at 02:00, a bill reminder at 02:00 is held, a
   nudge at 02:00 is dropped; Telegram caps never exceeded (storm + gate).
4. Privacy rows list, export and delete all eight categories; no card/account number, birth year or child
   data is ever stored (needles).
5. Unit 3.11 + 3.12, ruff, mypy (9 pre-existing errors only), mock evals incl. `r11_helpers` (gated), the
   browser suite incl. the visual gate and the dock fit; `console.html` < 800, `api/app.py` ≤ 750, every file
   ≤ 800; `scripts/check_doc_versions.py` and `scripts/arch_coverage.py` pass.

## Cost (₹ a month; no new paid service, secret or Scheduler job)

- **Fixed: ₹0.** Firestore: the clock ≈ 288 runs a day × (≈ 8 reads + ≤ 2 writes) ≈ 2,300 reads and 600
  writes a day, plus a few hundred for the parts: far inside 50,000 reads and 20,000 writes a day; storage
  well under 1 MB. Cloud Run: 288 extra short requests a day when Home was off (~8,600 a month of 2 million
  free; ~1–3 s of CPU each, inside the free CPU time). Open-Meteo 24 calls a day of 10,000; SACHET ~150; Gmail
  2 scans a day; Contacts 1 list a day: all free.
- **Recipes: about ₹0.9 a request** on the balanced tier (~1,200 in + 700 out tokens at ₹190.48 / ₹952.40 per
  million), so 30 a month ≈ ₹27, metered against his monthly limit; ₹0 in No-AI or on an allowed free brain.
- Telegram and Web Push ₹0. segno ₹0.

## Risks

- **No 5-minute clock**: if step 8 failed, reminders only come 04:00–11:30 (the panel says so, D3).
- **Waking the server every 5 minutes with Home off**: free (above), but each run must stay light: one read of
  each owner's settings per job, outside fetches only when due.
- **Alert floods**: SACHET's many IMD nowcasts → district + severity filter, soft-urgent caps, dedup by id;
  nudges capped three ways (gate, storm, Telegram).
- **False reassurance**: JARVIS is not the official warning system; the tab says the SACHET app, SMS and
  cell broadcast come first; a feed outage shows.
- **Payment fraud**: payee only from his own entry, R3 card with passkey, taint refusal, ₹1 lakh cap, no
  stored link or QR, never on Telegram.
- **Diet mistakes** offend: the code check, not the model, has the last word.
- **Children's data**: birth years dropped on read, adults-only rota labels, no ages, no children's meal
  plans.
- **Line budgets**: `console.html` reaches 798 of 799 after I0 — the next release that needs a panel must first
  free lines (for example by building the More sheet's entries from the dock in `console-dock.js`);
  `api/app.py` ~730 after the `_log_up` move.
- ***Unverified* until I1 in the cloud**: Cloud Run's egress to `sachet.ndma.gov.in` and
  `api.open-meteo.com`; HIBP's and merchants' sender addresses; Google's page size for connections.

## I0 — what the seams decided (11 Nov 2026, branch `r11-i0`)

- **Routes**: I0's are `GET /v1/helpers` (`{enabled, parts, clock: {last_run, stale, jobs}, nudges,
  fortnight}`; `{enabled: false, off}` when the helpers are off) and `/v1/helpers/gate…` (not
  `/v1/helpers/nudges…`, which is Part C's router prefix). The clock is "stale" after 12 minutes.
- **Composites**: `helpers_clock` rides the watchdog (Home on: added once; Home off: the watchdog route
  runs it alone, advisory — a job it couldn't finish is "degraded", never a 503) and the morning tick;
  `helpers_daily` holds the parts' daily jobs and I0's `helpers_sweep` (send-log days past 15).
- **The contract is checked** (`r11_wiring.check_part`): a part with another part's name, a tool outside
  its families, an unknown job name or privacy id, or a build that raises is left empty ("setup failed")
  and the other parts still run.
- **Storm**: the nudge ceiling is 8 an hour (D5 as amended above); `disaster_alert` is de-duplicated, not
  soft-urgent.
- **No-AI**: `route_no_ai(text, now, extra)` tries the helpers' routers first; a router that raises is
  skipped. Without them "don't remind me to stand up" asks "When should I remind you?" today.
- **Line budgets after I0**: `api/app.py` 721 (the `_log_up` line moved to `api/startup_log.py`, then the
  six slots); `console.html` 798; `console-deck.js` 594.
- **The build book** names release R11 from this plan; `layers.py` maps `helpers` to L5; the guide's
  edition v11.0.1 adds card C60 (every planned collection listed in advance).
- **segno 1.6.6** is in `pyproject.toml`, the hash-locked `requirements.lock` and the licence table
  (classifier "BSD License"; segno's own LICENSE is BSD-3-Clause).

## I1 — what was merged, what was decided, what is left (11 Nov 2026, branch `r11-i1`)

**In plain words.** The four parts were joined into one branch and checked together. The helpers
now read your Google data only after the same check the chat's tools pass, the kitchen has real
nutrition values (every value, for about 565 foods), and a test lives through a whole day of all
four parts and finds none of the planted private details anywhere it shouldn't be.

**Merged** (in this order, each with `--no-ff`, no conflicts): Part A `r11-a` @ `b0edc43`, Part B
`r11-b` @ `4faba31`, Part C `r11-c` @ `ae4736a`, Part D `r11-d` @ `1be86fb`.

**Decisions taken at I1**

1. **One governed path for background reads** (CLAUDE.md: every tool call passes the gateway).
   `jarvis.tools.background.BackgroundReads.of(gateway)`, reached by the parts as
   `HelperContext.reads` (read late: the gateway is built after the parts). The gateway's own
   policy and the owner's rows, as the gateway reads them (Telegram and offline wrappers
   included), decide the row's tool at R1. **Only "Allow" reads**: "Ask first" now stops a
   background read (before I1, Parts A, B and C read on "Ask first"; Part D already didn't), as do
   "Never", rows that can't be read, no gateway, an unknown or non-read tool. One audit line each
   time (agent `helpers`, the row's tool, no arguments, the job's name and a fixed reason word); a
   refusal once a day. Readers: birthdays (A), the to-dos behind top priority (A; it had no audit
   line), breach notices (B), the nudges' calendar read (C), receipts (D; its counts moved from
   the audit line to the log). Part B's feature jobs (chores, upkeep, weather, SACHET) still ask
   "not Never" through `house/guard.py`: they read no Google data. It is a function of the
   gateway, not a `Gateway` method, because `tools/gateway.py` is at its 760-line guard.
2. **Rain for the free-time pick**: `HelperContext.rain` (read late) gives Part C Part B's
   `services["rain"]` (`house/rain.py`: the sealed weather summary's "rain likely from HH:MM";
   unknown without his place, a keyring, or a summary of today under 3 hours old).
3. **Approvals waiting** are a pending source in `r11_wiring.ApprovalsPending` (D9).
4. **`UpiCard`** (`tools/reply_cards.py`): approving `bill_pay_prepare` in the console spends the
   one-time grant and shows the link and QR once under the approval's reply (the chat and the
   Today tab alike); the tool's result names no link; nothing stores, logs or audits it; Telegram
   draws no such card; `POST /v1/approvals/{id}/approve` answers `no-store`.
5. **Telegram**: every helper read is classified. Private (refused unless private reads are on):
   `bill_list`, `spend_month`, `breach_status` (and `contacts_birthdays`, already). Safe: the
   rest; `focus_now` and `pending_list` drop a bill's amount on a Telegram turn.
6. **Persona p11.0**: `HELPERS_RULE` (D22 with Part C's "don't remind me to ..." → `nudge_stop` and
   Part D's recipe line, plus the nutrition label).
7. **`ticks.time_left()`** (Part B's note 3.5): a job reads its real remaining time; Part B's
   outside slots end 0.5 s before it.
8. **CSS** (`console-helpers.css`): Part A's two rules, Part B's own form grid (`.hp-grid`,
   `.hp-field`, `.hp-form`, replacing the borrowed `.vt-*`), Part D's `label.hp-field` and 44 px
   inputs, and the full-nutrition list; existing tokens only. `console.html` is unchanged (798
   lines); `console.js` gained one line (the UPI card).
9. **D15 amended: nutrition data installed.** The owner's SR Legacy CSV download
   (`FoodData_Central_sr_legacy_food_csv_2018-04.zip`, SHA-256 `b8081729…6fd0`; the three CSVs'
   own SHA-256 recorded too) converted by `scripts/kitchen_fdc_subset.py` into
   `helpers/kitchen/data/fdc_subset.json`: 565 raw foods of an Indian kitchen (Part D's ~110
   named foods with Hindi, Malayalam and Odia names, 29 more, then by FDC food category),
   **every** nutrient the file reports per 100 g (149 nutrients, name and unit once), 748,950
   bytes as plain JSON (no gzip needed), package data. Answers give the six key values; "full
   nutrition for dal" (`detail: full`) and the Kitchen tab's expandable list give every value.
   Every answer says "US reference values (USDA FoodData Central); Indian varieties and home
   recipes can differ." Each food carries its `source`; a source marked `"region": "IN"` in
   another `data/nutrition_*.json` wins over USDA (structure only: no Indian data, no import
   screen). Ten of Part D's descriptions did not match the real file and were fixed (brown rice,
   whole-wheat flour, oats, split pea, sweet potato, apple, papaya, raisins, chicken breast,
   chicken thigh); "millet" (proso) no longer answers to ragi or finger millet.
10. **`r11_needles`** (`evals/r11_helpers/needles.py`, built): a whole day of all four parts in one
    world on fakes, then every document, log line, audit entry, Activity row, alert and brief line
    is scanned: no card number (plain, spaced, dotted, Amex), birth year, e-mailed UPI ID, CAP
    instruction, pantry note, or hydration count in a log. Control "masking off" fails it.
    `evals/run_all_mock.py` now gates `r11_helpers`.
11. **Doc times corrected**: this plan's v11.0.1 and v11.0.2 rows (17:00 and 18:02 IST, from git),
    `BRIEF-COMMON.md` (18:02 IST), `INTEGRATION-C.md` (19:51 IST) and `INTEGRATION-D.md`'s first
    edition (18:52 IST): each said a later time than it was written.

**Left, and why**

- **The shared Gmail list-and-read helper** (Part D's note 3.7) is not built: it would change the
  shipped parcels reader and the brief's Deliveries section for no change in behaviour; a
  separate refactor with its own tests.
- **The "next calendar event" pending source** (D9) is not built (Part A's note); for R12.
- **The brief's parcels section** (R1, `brief/deliveries.py`) reads Gmail with no permission-row
  check of its own. It is older than R11 and outside its files; noted for the owner.
- Everything *unverified* in the parts' notes stays so until the owner's checks after deploy: a
  real UPI app, Cloud Run's reach to Open-Meteo and SACHET, the breach and merchant senders.

**Needs the owner**

1. **"Ask first" on a row now means no background read** (decision 1). With your Contacts row on
   "Ask first", birthday reminders stop; with Email on "Ask first", breach notices and receipts
   stop. Keep it (the default), or say which rows a morning job may read on "Ask first".
2. The parts' owner checks (INTEGRATION-A §4, B §4, C, D §4) after the deploy.

## Change log

| Version | Date | Release | What changed | By |
|---|---|---|---|---|
| v11.0.1 | 11 Nov 2026, 17:00 IST | R11 | First edition: goal, the 16 items mapped, findings from the code, external sources with terms and fallbacks, data model, D1–D22, owner decisions with safe defaults, the A–D split, I0 seams, tests and evals, acceptance, cost, risks | 🛠 Mark XIV |
| v11.0.2 | 11 Nov 2026, 18:02 IST | R11 | After the I0: D5's storm rules (an 8-an-hour nudge ceiling; a disaster warning de-duplicated, never capped, on Telegram's urgent bucket), the gate's tap routes under `/v1/helpers/gate`, D10 and D11 as separate decisions, seam 7's route names, and "I0 — what the seams decided" | 🛠 Mark XIV |
| v11.0.3 | 11 Nov 2026, 21:44 IST | R11 | After the I1: the four parts merged; the background reads' governed path; rain for the free-time pick; approvals in pending; the UPI card; Telegram; persona p11.0; `ticks.time_left()`; the helper CSS; D15 amended (the USDA subset installed with every nutrient, pluggable sources, the honest label); `r11_needles`; the earlier rows' times corrected; what is left and what the owner decides ("I1 — what was merged, what was decided, what is left") | 🛠 Mark XIV |
