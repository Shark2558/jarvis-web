---
page: pg_card_c46
written_by: Workshop · Mark XXIV
written_on: 2026-11-24
sources:
  "src/jarvis/api/notify.py": "d9e0d5160b289278"
  "src/jarvis/api/static/console-alerts.js": "64aaa00169c0410b"
  "src/jarvis/notify/__init__.py": "5049b7ae5c33b9b6"
  "src/jarvis/notify/held.py": "34791b705596ae81"
  "src/jarvis/notify/models.py": "5670a8b715bd616d"
  "src/jarvis/notify/policy.py": "eadcd8a5a5ae474c"
  "src/jarvis/notify/ports.py": "1395334284106e9a"
  "src/jarvis/notify/privacy.py": "80e53bf2627ef2f1"
  "src/jarvis/notify/quiet.py": "18a4db9f43b67131"
  "src/jarvis/notify/service.py": "49bed4fc6715565a"
  "src/jarvis/notify/sink.py": "ec66dc6e513106c3"
  "src/jarvis/notify/store.py": "77f02227065631cd"
  "src/jarvis/notify/storm.py": "d68a67d678a08784"
  "src/jarvis/notify/telegram_out.py": "b716c4ea72837feb"
  "src/jarvis/notify/terms.py": "6a1117e706e94b6b"
---
## In plain words
Not every alert deserves to wake you. This part decides, for each alert JARVIS wants to send, whether your phone rings, buzzes silently, keeps the alert for one summary in the morning, or only lists it in the console. It follows fixed rules that you tune in the console's alert settings, with no AI involved: smoke or a burglar always rings, a routine notice at night waits until you are up, and a burst of camera alerts becomes one summary instead of a flood of buzzes.

## Example (made up)
Your quiet hours run from 11 pm to 6:30 am. At 1:40 am the nightly backup check fails: an important alert, so it is held. At 2:05 a bill reminder for the broadband is held too. At 2:15 the kitchen smoke sensor fires: a hazard rings straight through quiet hours. At 6:30 one Telegram message arrives: "While you were resting, 2 alerts were held (1 backup problem, 1 bill reminder). Open JARVIS."

## How it works
Every feature calls `PolicyAlerts`, which hands the alert to `NotifyService` and turns the outcome into the plain answer the alerts port promises (`src/jarvis/notify/sink.py`). `NotifyService` reads your settings, falling back to the defaults if they can't be read, and honours the per-kind Telegram switches you set earlier.
`decide` then applies fixed rules in order, first match wins (`src/jarvis/notify/policy.py`): a test rings; a kind you switched off is dropped or kept for the console feed; a hazard or an emergency word rings; an urgent kind such as a burglar rings; a nudge at night is dropped; a VIP rings; in quiet hours an important alert is held and an info one dropped; otherwise important rings and info arrives silently.
Emergency words are known in English, Hindi, Malayalam and Odia, and a doubtful match errs on the side of ringing (`emergency`). Quiet hours follow your time zone and may cross midnight (`in_quiet`, `user_timezone`). By default only urgent alerts ring (`NotifySettings`), but a short list of important ones, such as a laptop gone quiet, a red Vitals line or JARVIS's own health, still ring in waking hours (`src/jarvis/notify/policy.py`).
`Storm` then limits bursts: burglar rings stop at {{fact:src/jarvis/notify/storm.py:MAX_URGENT_IN_WINDOW}} in a short window, {{fact:src/jarvis/notify/storm.py:MAX_INTRUDER_PER_HOUR}} an hour and {{fact:src/jarvis/notify/storm.py:MAX_INTRUDER_PER_DAY}} a day, the rest becoming one summary; nudges stop at {{fact:src/jarvis/notify/storm.py:MAX_NUDGES_PER_HOUR}} an hour, self-health rings at {{fact:src/jarvis/notify/storm.py:MAX_SELF_PER_HOUR}}, and a hazard is never capped.
Telegram and Web Push are tried side by side, normal alerts sharing {{fact:src/jarvis/notify/service.py:PUSH_PER_HOUR}} pushes an hour (`NotifyService`). `TelegramHomeAlerts` gives urgent kinds their own bucket of {{fact:src/jarvis/notify/telegram_out.py:URGENT_PER_HOUR}} an hour and {{fact:src/jarvis/notify/telegram_out.py:URGENT_PER_DAY}} a day.
Held alerts are kept as kind and time only, at most {{fact:src/jarvis/notify/store.py:MAX_HELD}} (`notify_held`), and `summary` sends them as one message when quiet hours end. Each decision writes one `audit` line with kinds and counts, never words.

## What it costs
Nothing: no rupees and no AI call, because `decide` is plain rules (`src/jarvis/notify/policy.py`). It keeps your alert settings with the VIP list encrypted (`notify`), up to {{fact:src/jarvis/notify/store.py:MAX_HELD}} held alerts as kind and time (`notify_held`), and short-lived storm counters (`notify_rate`).

## When it fails
Each channel fails on its own: a failing push never blocks Telegram, and the other way round (`NotifyService`). Unreadable settings fall back to the defaults, so burglar and smoke alerts still ring. A hold that can't be saved rings instead of being lost, and held alerts are removed only after Telegram or a browser took the summary (`src/jarvis/notify/service.py`). A burglar ring that reached nobody gives its storm slot back, so the retry is not swallowed (`Storm`). The feature asking sees a short reason such as "held until quiet hours end" or "grouped into a summary" (`src/jarvis/notify/sink.py`).
