---
page: pg_card_c11
written_by: Workshop · Mark XXIV
written_on: 2026-11-24
sources:
  "deploy/cloudrun.sh": "291d919ed466219d"
  "src/jarvis/api/brief.py": "384e3c31e281a98b"
  "src/jarvis/api/scheduler_auth.py": "346bb43278c2d8f2"
  "src/jarvis/home/watchdog.py": "adb8fe67d29e2bc2"
  "src/jarvis/ticks.py": "d10b0a94172bdd16"
---
## In plain words
JARVIS sleeps when nobody is talking to it, so something has to wake it at the right times. Alarm clocks in Google Cloud do that: a morning clock and a watchdog clock (`deploy/cloudrun.sh`). The morning clock rings every half hour through the early morning: it makes your morning brief when it is due and then does the daily chores, such as vault reminders, the DigiLocker import and clearing out old data. The watchdog clock rings every few minutes all day: it notices when your home laptop stops answering and runs the helpers' small regular jobs (`src/jarvis/home/watchdog.py`). Only Google's own scheduler is allowed to ring them.

## Example (made up)
At 06:00 the morning clock rings. JARVIS sees Deepa's brief is due at 06:30, so it does nothing for the brief yet, then runs its chores: three vault reminders checked, one DigiLocker file imported, 40 expired passkey challenges swept. At 06:30 it rings again and the brief is made. Meanwhile, at 06:12 the watchdog notices her home laptop has missed three heartbeats, marks it offline and sends one alert.

## How it works
Cloud Scheduler calls `POST /internal/brief/tick` with a token signed by Google, and `require_scheduler` lets it in only after `GoogleOIDCVerifier` checks the signature against Google's published keys, the issuer, the exact address of that route and the scheduler's own service account (`src/jarvis/api/scheduler_auth.py`).
Each clock has its own address in the token, so the brief clock's token never opens the watchdog and the other way round (`src/jarvis/api/scheduler_auth.py`).
The `tick` route first makes the brief if it is due, then runs fixed sweeps of old memory, unsent uploads, Recently deleted, unanswered passkey challenges, Telegram counters and Activity days (`src/jarvis/api/brief.py`).
Then `run_jobs` runs every feature's `TickJob` one after another, each limited to {{fact:src/jarvis/ticks.py:MAX_BUDGET_S}} seconds and all of them to {{fact:src/jarvis/ticks.py:TICK_TOTAL_BUDGET_S}} seconds together, which keeps the run inside the scheduler's own deadline.
Each job's outcome, ok, failed, timed out or skipped, goes to the self-health watch through `report` (`src/jarvis/ticks.py`).
The watchdog clock calls `Watchdog`, which uses the same `run_jobs` for the home jobs (`src/jarvis/home/watchdog.py`).
`OfflineJob` marks the home laptop offline after {{fact:settings.home_offline_after_s}} seconds without a heartbeat and sends one alert per outage, urgent when the alarm is armed.
Other watchdog jobs sweep old home claims and link codes, and the helpers' regular clock rides the same call (`src/jarvis/home/watchdog.py`).

## What it costs
Nothing. Google Cloud Scheduler gives a few jobs free per billing account, and JARVIS uses only the morning clock and the watchdog (`deploy/cloudrun.sh`). The deploy script notes that a further job elsewhere on the same billing account could add a small charge in dollars.

## When it fails
A job that fails, runs out of time or answers in the wrong shape is logged and reported "failed", and the rest still run (`run_jobs`). A job the tick has no time left for is reported as skipped, never silently dropped (`src/jarvis/ticks.py`). If the morning clock is missing, the brief is still made when you open the Brief panel, which asks for it through `POST /v1/brief/generate`. Any caller without the scheduler's valid token gets the same bare status 401 and learns nothing about which check failed; the log names the check but never a token (`src/jarvis/api/scheduler_auth.py`).
