---
page: pg_card_c45
written_by: Workshop · Mark XXIV
written_on: 2026-11-24
sources:
  "src/jarvis/alerts.py": "567a607a4b13ddc2"
  "src/jarvis/telegram/alerts.py": "4dd37fab0cde0151"
---
## In plain words
When any part of JARVIS wants to tell you something while you are away from the console (an approval waiting, your morning brief ready, trouble at home), it knocks on this one door. The words of an alert are always JARVIS's own fixed sentence, never text a model wrote and never someone else's message, so nobody's e-mail or a model's guess ever reaches your phone as an alert. When an alert does not go out, the part that asked is told why instead of crashing.

## Example (made up)
At 7:02 on a Sunday JARVIS finishes your morning brief and asks this door to tell you. The words are its fixed line "Your morning brief is ready in the console." Your Telegram link is paired, the brief switch is on and it is only the third alert this hour, so your phone buzzes once. Later that morning a burst of approval requests uses up the hour's allowance; the eleventh comes back "alert limit reached for now", and the approval simply waits for you in the console.

## How it works
`AlertSink` is the promise every alert sender keeps: one send call with your account, the text, the kind of alert and two options, a silent delivery and one small photo (`src/jarvis/alerts.py`). The kinds are a fixed list in `src/jarvis/alerts.py`, from an approval waiting and offline mode to home, health, helper, phone, self-watch and wardrobe alerts. Every answer is an `AlertResult`: sent or not, a short reason, and a "queued" mark for an alert held to go out later, so the caller knows not to send it again. When nothing is set up to deliver, `NoAlerts` stands in: it sends nothing and gives its reason.
`TelegramAlerts` is the Telegram sender. It first reads your Telegram link, and with none it answers "Telegram isn't paired" (`TelegramAlerts`). It then checks the switch for that kind: only an approval waiting, offline mode, the brief and the vault reminder have one here, plus the test alert, and any other kind is refused as switched off (`src/jarvis/telegram/alerts.py`). Next it takes one from your allowance of {{fact:src/jarvis/telegram/alerts.py:MAX_PER_HOUR}} alerts an hour and {{fact:src/jarvis/telegram/alerts.py:MAX_PER_DAY}} a day (`MAX_PER_HOUR`, `MAX_PER_DAY`). `plain` then turns the text into one clean line without control characters, cut to {{fact:src/jarvis/telegram/alerts.py:MAX_ALERT_CHARS}} characters with an ellipsis. Finally it sends the line and writes an entry to the `audit` trail with the kind and whether it went, never the text. It accepts the silent and photo options and ignores them (`TelegramAlerts`).
Day to day, JARVIS hands its alerts to the alert policy (C46) first, which handles quiet hours and sends through its own Telegram and Web Push senders; `TelegramAlerts` on its own is the plain fallback used when that policy is not set up (`src/jarvis/telegram/alerts.py`).

## What it costs
Nothing: not a single rupee. This door makes no paid call and calls no AI; the only thing kept is the day's alert counter behind the hourly and daily limits (`TelegramAlerts`).

## When it fails
"Can't send" is an answer, never an error: `AlertResult` comes back with sent off and a short reason, and the caller decides whether to try later. If your Telegram settings or the alert counter can't be read, `TelegramAlerts` refuses to send rather than guess, so a broken counter never floods your phone. If Telegram itself does not answer, you get no buzz, the reason is "Telegram couldn't be reached" and the audit records the failure (`TelegramAlerts`). If even the audit write fails, the alert still counts as sent and the server log notes the missing audit line (`src/jarvis/telegram/alerts.py`).
