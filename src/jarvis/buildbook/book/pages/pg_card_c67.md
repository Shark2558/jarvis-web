---
page: pg_card_c67
written_by: Workshop · Mark XXIV
written_on: 2026-11-24
sources:
  "evals/r14/selfwatch.py": "1dadce66510eae7e"
  "src/jarvis/api/r14_status.py": "efb328e795d63aa9"
  "src/jarvis/api/r14_wiring.py": "9a389842728e9471"
  "src/jarvis/api/selfwatch.py": "c1f21790ef9e24a9"
  "src/jarvis/api/tick_wiring.py": "ab30c19996a2944c"
  "src/jarvis/hardening/__init__.py": "1086f4e41654c4e2"
  "src/jarvis/hardening/ports.py": "3ec5ccd3d6c3c19f"
  "src/jarvis/home/heartbeat.py": "028d88e299dd4f48"
  "src/jarvis/notify/store.py": "77f02227065631cd"
  "src/jarvis/notify/storm.py": "d68a67d678a08784"
  "src/jarvis/selfwatch/__init__.py": "d7c9143cd8d131a5"
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
JARVIS keeps an eye on itself. If its background jobs keep failing, one of its clocks stops, your morning brief is not made, errors pile up, the AI spend jumps far above a normal day, or a new version goes live, it tells you once, in plain fixed sentences. These alerts ring only in waking hours and wait for the morning at night. When the trouble ends, a quiet note says so.

## Example (made up)
On Tuesday the bills helper fails at 6:00, 6:30 and 7:00. After the third failure in a row your phone shows "1 job failing: bills. JARVIS will say when it works again." It keeps failing, but you hear nothing more about it. On Wednesday a fix is deployed; the next morning you get "JARVIS was updated: version 6.3.2 is now live.", and when the bills helper next runs cleanly, a note in your feed says it works again.

## How it works
`Watch` hears the outcome of every scheduled job from the clocks (`src/jarvis/ticks.py`), and `JobLedger` counts each job's failures and time-outs in a row; a job skipped for lack of time never counts (`src/jarvis/selfwatch/ledger.py`).
After `selfwatch_fail_streak` failures in a row ({{fact:settings.selfwatch_fail_streak}}) one alert names every job in a streak, at most once an hour (`job_failing`).
Two jobs do the watching, one on the frequent clock and one on the morning tick, and each reports the other's streak, never its own (`src/jarvis/selfwatch/jobs.py`).
`Clocks` makes the two clocks watch each other, so a clock that stops, or never starts after a deploy, is said once per outage (`src/jarvis/selfwatch/clocks.py`).
`BriefCheck` reports a brief not made `selfwatch_brief_grace_min` minutes ({{fact:settings.selfwatch_brief_grace_min}}) after your brief time.
`ErrorCounter` sits on the server's log and counts error records by hour and logger name only, never a message; more than {{fact:settings.selfwatch_errors_per_hour}} in an hour is said, unless a told job streak already explains them (`src/jarvis/selfwatch/errors.py`).
`SpendWatch` keeps a daily snapshot of the month's AI spend and flags a day over {{fact:settings.selfwatch_spike_factor}} times the average of up to {{fact:src/jarvis/selfwatch/spend.py:HISTORY_DAYS}} days and at least ₹{{fact:settings.selfwatch_spike_min_inr}}, never before {{fact:src/jarvis/selfwatch/spend.py:HISTORY_MIN}} days of history.
`DeployWatch` notices a new revision or version once, and the very first run only remembers what is live (`src/jarvis/selfwatch/deploys.py`).
`Teller` writes a once-only claim in `selfwatch_told` before each send, and gives it back when no channel took the alert, retrying at most {{fact:src/jarvis/selfwatch/texts.py:MAX_TRIES}} times (`src/jarvis/selfwatch/texts.py`).
The alert policy holds these kinds at night and caps them at {{fact:src/jarvis/notify/storm.py:MAX_SELF_PER_HOUR}} an hour (`Storm`), and `GET /v1/selfwatch` shows the clocks, streaks and today's errors.

## What it costs
Nothing: no rupees, no AI call and no outside service, only reads and writes of a few small records in the document store (`src/jarvis/selfwatch/jobs.py`). It keeps names, counts and times only, never a log message (`selfwatch`, `selfwatch_errors`, `selfwatch_told`).

## When it fails
A step that fails or runs out of time is counted and the others still run, and the streaks are written in a slice of time kept for them (`Watch`). The errors counter never logs about itself and leaves out the alert path while an alert is being sent, so it never alarms about itself (`src/jarvis/selfwatch/errors.py`). With the store down, claims and clock stamps live in memory and an outage is still said once (`src/jarvis/selfwatch/ledger.py`). If both clocks stop, nothing can speak up; the Vitals item for the clocks shows "Clocks stopped since" when you look (`clocks_item`).
