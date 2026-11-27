---
page: pg_service_cloud_scheduler
written_by: Workshop · Mark XXIV
written_on: 2026-11-24
sources:
  "src/jarvis/api/app.py": "a739af3f1d029daa"
  "src/jarvis/config.py": "965b3658da16361e"
---
## In plain words
Cloud Scheduler is Google's alarm clock for internet services. JARVIS's server sleeps when nobody is using it, so something has to wake it on time. Google's clock calls JARVIS at fixed times: through the morning, to make your brief when it is due and to run the daily jobs, and every few minutes all day, to watch your home laptop and run the helpers' reminders and alerts. Each call proves it really comes from Google's clock with a signed token. Nothing of yours goes to Cloud Scheduler: it only knows JARVIS's address and when to call.

## Example (made up)
Your brief time is 07:00. At 07:00 Google's clock calls JARVIS, which finds the brief due, makes it and sends "Your brief is ready" to Telegram. Between calls, at 07:05, the all-day clock runs the watchdog: the laptop answered 40 seconds ago, so all is well, and a bill reminder for that morning goes out.

## How it works
`_mount_scheduler` opens the morning clock's door only when `brief_scheduler_sa` names the clock's own Google service account, `public_base_url` is known and conversations are kept in Firestore through `session_backend`, so a restart never makes a second brief (`src/jarvis/api/app.py`). Each call must carry a token signed by Google for exactly that account and that address, and `_mount_scheduler` sets up the check that reads it. A call without a valid token gets a bare refusal, with nothing read and no reason given (`_install_core_errors`). A `brief_scheduler_sa` that doesn't look like a Google service account is logged as a warning (`_mount_scheduler`). The tick jobs and the one all-day clock are wired at start-up, after every feature (`_lifespan`). The helpers use at most `helpers_clock_budget_s` ({{fact:settings.helpers_clock_budget_s}} seconds) of each all-day run (`src/jarvis/config.py:Settings`). The self-health watch checks that each clock keeps running: a job that fails `selfwatch_fail_streak` ({{fact:settings.selfwatch_fail_streak}}) runs in a row is reported, and a brief not made `selfwatch_brief_grace_min` ({{fact:settings.selfwatch_brief_grace_min}} minutes) after its time is too.

## What it costs
Nothing in rupees: Google gives a small number of Scheduler jobs free per billing account, and JARVIS's jobs fit inside it. If other projects on the same billing account use Scheduler too, an extra job costs a small monthly fee in dollars.

## When it fails
Without the clock, the brief is still made when you open the console (`brief_scheduler_sa`). A job that fails or runs out of time is logged and reported as failed without stopping the others. If a clock stops calling, the self-health watch tells you (`selfwatch_enabled`). Only Google's clock opens these doors; anything else is refused.
