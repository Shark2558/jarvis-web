---
page: pg_module_vitals
written_by: Workshop · Mark XXIV
written_on: 2026-11-24
sources:
  "evals/r14/selfwatch.py": "1dadce66510eae7e"
  "src/jarvis/__init__.py": "e7c19ff56bddba24"
  "src/jarvis/about.py": "c310b3bdce51c135"
  "src/jarvis/api/r14_status.py": "efb328e795d63aa9"
  "src/jarvis/api/r14_wiring.py": "9a389842728e9471"
  "src/jarvis/api/selfcheck_wiring.py": "fb7336391ffa3727"
  "src/jarvis/api/selfwatch.py": "c1f21790ef9e24a9"
  "src/jarvis/api/static/console-systems-modal.js": "0591870095265d5c"
  "src/jarvis/api/static/console-systems-voice.js": "e8f488a203174612"
  "src/jarvis/api/static/console-systems.js": "b2a348eb9c0bd6eb"
  "src/jarvis/api/static/console-usage.js": "1595a84e680dde87"
  "src/jarvis/api/static/console-vitals.js": "dd7cc4ee3cec2353"
  "src/jarvis/api/tick_wiring.py": "315ae398f136c29a"
  "src/jarvis/api/usage.py": "9f60c602bd371c86"
  "src/jarvis/home/heartbeat.py": "028d88e299dd4f48"
  "src/jarvis/llm/pricing.py": "a2d1278419157236"
  "src/jarvis/notify/store.py": "77f02227065631cd"
  "src/jarvis/notify/storm.py": "d68a67d678a08784"
  "src/jarvis/selfwatch/brief_check.py": "d39aec977aff7b68"
  "src/jarvis/selfwatch/clocks.py": "8b5da7d840924a7d"
  "src/jarvis/selfwatch/deploys.py": "2b1ec5694821fd44"
  "src/jarvis/selfwatch/errors.py": "c88bf9a3ad7a73d2"
  "src/jarvis/selfwatch/jobs.py": "a1b5cdedafe3b4b3"
  "src/jarvis/selfwatch/ledger.py": "0d960660646f4dba"
  "src/jarvis/selfwatch/part.py": "547c5b08fe5427da"
  "src/jarvis/selfwatch/ports.py": "bbdbfd81b0bfeaec"
  "src/jarvis/selfwatch/spend.py": "14b29a5d2dcf77bc"
  "src/jarvis/selfwatch/status.py": "f26a7c8f124ce409"
  "src/jarvis/selfwatch/texts.py": "b1efedd77bdcd51e"
  "src/jarvis/selfwatch/vitals.py": "cc04ee58bf9efd60"
  "src/jarvis/ticks.py": "d10b0a94172bdd16"
---
## In plain words
This module is JARVIS keeping an eye on itself and on everything that has a limit. The Vitals board shows in one place your AI spend this month, the free allowances JARVIS uses, its own keys and connections, and bills you add yourself, each with a status in words. The systems check tests every connection when you ask ("Jarvis, run a systems check") and works with the AI off. A self-health watch notices when a background job keeps failing, a clock stops, your morning brief is missed, errors pile up, AI spending jumps or a new version goes live, and tells you once, in plain words.

## Example (made up)
On a Tuesday Joseph's Vitals board shows the web-search line amber: 760 of 900 credits used. At 02:10 that night the vault-reminder job fails 3 times in a row because a Google service is down. The watch holds its "job failing" alert for quiet hours, and at 07:00 his phone shows it with the job's name. That afternoon he says "Jarvis, run a systems check"; every row comes back OK and JARVIS reads the result aloud.

## How it works
`src/jarvis/api/static/console-vitals.js` draws the board: keys and connections, allowances and quotas, and bills, each with a status in words, never colour alone; the money block above it is `src/jarvis/api/static/console-usage.js`. A reply from a model with no known price is counted there as "price unknown", never as ₹0, and the limit counts it at the `dearest` known price (`price_unknown`). `vitals_sources` feeds the board with no model call: the brains' record of their last call, the Google link, the last systems check, the web vendor's usage, the GitHub token's facts and the home link. The systems check runs one probe per connection and speaks from fixed sentences, so it needs no brain (`src/jarvis/api/static/console-systems.js`), and `shared_health_job` runs it on the background clocks too. `run_jobs` in `src/jarvis/ticks.py` runs each background job in turn with its own time budget, and one that fails or runs out of time never stops the rest. The self-health watch, put together by `build` in `src/jarvis/selfwatch/part.py`, hears every job's outcome and keeps the streaks in `JobLedger`. A streak of {{fact:settings.selfwatch_fail_streak}} failures raises a "job failing" alert that names the job (`job_alerts`). `Clocks` notices when either clock stops, and `BriefCheck` notices a brief more than {{fact:settings.selfwatch_brief_grace_min}} minutes late. `ErrorCounter` counts error lines by their source's name only and speaks up past {{fact:settings.selfwatch_errors_per_hour}} an hour. `SpendWatch` warns when a day's AI spend is over {{fact:settings.selfwatch_spike_factor}} times the recent daily average and at least ₹{{fact:settings.selfwatch_spike_min_inr}}, once it has {{fact:src/jarvis/selfwatch/spend.py:HISTORY_MIN}} days of history. `DeployWatch` says once when a new version goes live. `Storm` keeps floods in check: JARVIS's own health alerts are capped at {{fact:src/jarvis/notify/storm.py:MAX_SELF_PER_HOUR}} an hour, while a hazard or an emergency is never capped (`src/jarvis/notify/storm.py`). Alerts held for quiet hours wait in `src/jarvis/notify/store.py`, at most {{fact:src/jarvis/notify/store.py:MAX_HELD}}, for the morning summary. The About line at the board's foot shows the running version and its build day (`src/jarvis/about.py`).

## What it costs
Nothing: the board, the systems check and the watch are plain code on JARVIS's existing clocks, with no model call, and their reads and writes fit inside the database's free daily allowance (`src/jarvis/selfwatch/part.py`).

## When it fails
A record that can't be read shows "unavailable" and never hides the rest of the board (`src/jarvis/api/static/console-vitals.js`). A watch step that fails is counted while the others still run, and each watch job's own failures are reported by the other one, never by itself; an alert that reached nobody is raised again on the next run (`src/jarvis/selfwatch/jobs.py`). With the database down, the watch keeps its notes in memory, so an outage is still told once (`JobLedger`). A systems check asked for while one is running joins that run instead of starting another, and only when the run already has its fill of listeners is the new request turned away as busy (`LiveHealth`).
