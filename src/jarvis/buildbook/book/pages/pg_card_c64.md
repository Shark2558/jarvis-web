---
page: pg_card_c64
written_by: Workshop · Mark XXIV
written_on: 2026-11-24
sources:
  "evals/r7/body.py": "b65be7b48b9d80ec"
  "src/jarvis/api/r7_wiring.py": "6550ccbb04997884"
  "src/jarvis/api/static/console-brief-sections.js": "e11e4eafe28cf198"
  "src/jarvis/api/static/console-helpers-watch.js": "66676faabf8cfcc9"
  "src/jarvis/api/watch.py": "a632cfa03931c5d3"
  "src/jarvis/brief/models.py": "18f095d54c93f9da"
  "src/jarvis/brief/service.py": "8ff72b107aa66083"
  "src/jarvis/watch/__init__.py": "026564129d332364"
  "src/jarvis/watch/brief.py": "d0eac5afb394b730"
  "src/jarvis/watch/door.py": "8401690cf589e080"
  "src/jarvis/watch/jobs.py": "ed30d25007a42368"
  "src/jarvis/watch/models.py": "7f7b06101f7df8c5"
  "src/jarvis/watch/part.py": "ec70b306786dfc9a"
  "src/jarvis/watch/phrases.py": "f9011febcff9dd71"
  "src/jarvis/watch/privacy.py": "b9db7a9578f53582"
  "src/jarvis/watch/service.py": "4b55ffd580ad843e"
  "src/jarvis/watch/sleep.py": "5a65de6a5f4a2658"
  "src/jarvis/watch/store.py": "a1f17396425c6739"
  "src/jarvis/watch/tools.py": "6663e17be1faa847"
  "src/jarvis/watch/words.py": "add145980ba0b8fc"
---
## In plain words
If you wear a fitness watch, its steps, heart rate and sleep land in Android's Health Connect. The JARVIS phone app reads them there and sends one short summary for each day, so JARVIS knows how you slept and how much you walked (`src/jarvis/watch/service.py`). Last night's sleep appears as one line in the console's morning brief, and "how did I sleep?" gets an answer by voice or chat, even with the AI switched off (`src/jarvis/watch/phrases.py`). No watch? Typing your own bedtime and waking time works too (`POST /v1/watch/sleep`). The numbers are the watch's or the phone's estimates, never a diagnosis.

## Example (made up)
Rohan's watch records that he slept from 23:40 to 06:30, with 95 minutes of deep sleep, and that he walked 8,412 steps the day before. At 07:00 his phone app sends that day's summary through its signed door. When he opens the brief at 07:30 he sees "Sleep: 6 h 50 min, 23:40 to 06:30 · from your watch". On Sunday he asks "how did I sleep this week" and JARVIS gives him his average night and how much his bedtime wandered, from 23:10 to 01:05.

## How it works
The phone's summary arrives at `health_handler` only after the door's checks, and `parse_health` checks it whole: at most {{fact:src/jarvis/watch/models.py:MAX_DAYS}} recent days, steps up to {{fact:src/jarvis/watch/models.py:MAX_STEPS}}, heart rate between {{fact:src/jarvis/watch/models.py:HEART_LOW}} and {{fact:src/jarvis/watch/models.py:HEART_HIGH}} beats a minute, and at most {{fact:src/jarvis/watch/models.py:MAX_SESSIONS}} sleep sessions a day.
Anything out of range refuses the whole body with fixed words that never echo a value (`IntakeRefused`).
`WatchStore` keeps one sealed record per day in `watch_days`, locked with the keyring's watch key and bound to that day, plus a small `watch_state` record of when the last sync came.
`last_night` picks one night: a night you typed wins, otherwise the longest session that ended that morning from a single writer, the watch before the phone and any other health app after both, so nothing is counted twice (`src/jarvis/watch/sleep.py`).
`week` gives the average over the last {{fact:src/jarvis/watch/service.py:WEEK_DAYS}} nights and the spread of your bedtimes.
`SleepBrief` fills the brief's own sleep slot through `mobile_sleep`, which only the console reads, so the line never goes into the e-mailed copy or onto Telegram (`src/jarvis/watch/brief.py`).
`watch_tools` gives the brain reads for today, last night and the week, plus a note tool for a typed night, each answering with a fixed sentence from `src/jarvis/watch/words.py`.
`watch_phrases` matches whole questions such as "steps today" so they work in No-AI mode too.
`GET /v1/watch` feeds Helpers, Watch in the console (`src/jarvis/api/static/console-helpers-watch.js`), and `POST /v1/watch/sleep` saves a typed night.
`WatchStale` tells you once, quietly, when the phone stops syncing or no watch data has arrived for {{fact:src/jarvis/watch/jobs.py:DATA_STALE_DAYS}} days, and `BodySweep` removes days older than {{fact:settings.watch_keep_days}} days each morning.

## What it costs
Keeping and summarising your days costs nothing: no outside service and no AI is involved, only fixed sentences (`src/jarvis/watch/service.py`). Asking about your sleep in a normal chat is an ordinary AI reply at the usual price, and nothing at all with the AI off, where `watch_phrases` answers.

## When it fails
Without Health Connect or its permission, the Watch tab says so and a typed sleep time still works (`src/jarvis/api/watch.py`). With no token key nothing is stored at all, never in clear (`WatchOff`). A stored day that won't open is replaced only by the phone's own next sync of that day, never by a guess (`src/jarvis/watch/store.py`). When no night can be read, the brief simply shows no sleep line (`SleepBrief`). A silence warning that couldn't be delivered is tried again later, and one owner's failed job never stops another's (`src/jarvis/watch/jobs.py`). Logs hold counts and class names, never a value.
