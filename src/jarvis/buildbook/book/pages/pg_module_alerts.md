---
page: pg_module_alerts
written_by: Workshop · Mark XXIV
written_on: 2026-11-24
sources:
  "src/jarvis/alerts.py": "567a607a4b13ddc2"
  "src/jarvis/api/notify.py": "d9e0d5160b289278"
  "src/jarvis/api/static/console-alerts.js": "64aaa00169c0410b"
  "src/jarvis/api/static/console-sw.js": "8998e220b800ebcc"
  "src/jarvis/telegram/alerts.py": "4dd37fab0cde0151"
---
## In plain words
Alerts are how JARVIS taps you on the shoulder when you aren't looking at the console: a Telegram message, or a notification on your browser or phone. Every feature that wants to tell you something goes through the same door, and the words are always JARVIS's own fixed sentences, never AI text and never someone else's message. You decide what rings: quiet hours for the night, "only urgent things ring", a switch for each kind of alert, and a short VIP list of phone numbers or e-mail addresses whose alerts always get through.

## Example (made up)
Rohan has quiet hours from 23:00 to 06:30. At 1:15 am his home laptop stops answering while the alarm is off. That alert is important but not urgent, so JARVIS holds it, and at 6:30 his morning summary on Telegram mentions it. At 2:05 am the next night the kitchen smoke alarm goes off. A hazard is an emergency, so Telegram and the browser on his phone both ring at once, quiet hours or not. He taps the notification and the console opens straight on the Home panel.

## How it works
Every feature calls the same port, `AlertSink`, with a fixed sentence and a kind of alert from the closed list in `src/jarvis/alerts.py`. The answer is an `AlertResult`: sent, not sent with a short reason, or queued to go out later, so a failed send is never an error for the caller. When Telegram is off or unpaired, `NoAlerts` stands in and says why. The alert policy then decides whether an alert rings, rings silently, waits or is dropped, using fixed rules and the settings you keep with `PUT /v1/notify/settings`: quiet hours, "only urgent things ring", a switch per kind and whether names appear in alerts. `_apply` merges a change into your saved settings, and `put_settings` refuses a switch for a kind that must always ring, such as an SOS. The VIP list takes a phone number or an e-mail address (`add_vip`), and `list_vip` only ever shows a hint made by `_hint`, never the number or address itself. `TelegramAlerts` checks the kind's switch, then a counter of at most {{fact:src/jarvis/telegram/alerts.py:MAX_PER_HOUR}} alerts an hour and {{fact:src/jarvis/telegram/alerts.py:MAX_PER_DAY}} a day. It sends one clean line of at most {{fact:src/jarvis/telegram/alerts.py:MAX_ALERT_CHARS}} characters made by `plain`, and records every send in the `audit` trail. Browser and phone notifications are standard Web Push: the console subscribes a device with `POST /v1/push/subscribe`, using the server's public key from `GET /v1/push/key`. The service worker, `src/jarvis/api/static/console-sw.js`, only shows the notification and handles the tap; it has no fetch handler, so it never serves an old console. A tap opens the panel the alert is about, and its Talk button opens JARVIS with the mic button ready without switching the microphone on (`src/jarvis/api/static/console-sw.js`). `push_test` sends a test through every channel and reports which ones delivered it. Changes are limited to {{fact:src/jarvis/api/notify.py:CHANGES_PER_MINUTE}} a minute per owner (`install_notify`).

## What it costs
Nothing: an alert is a Telegram bot message or a standard Web Push through your browser's own push service, and deciding what rings is fixed rules with no AI call (`src/jarvis/alerts.py`).

## When it fails
Each channel fails alone: a browser that can't be reached never stops the Telegram message, and the caller gets a reason instead of an error (`AlertResult`). If Telegram's settings or its counter can't be read, the alert is not sent rather than risking a flood (`TelegramAlerts`). Over the hourly or daily cap the reason is "alert limit reached for now"; when Telegram itself can't be reached the attempt is recorded as failed (`TelegramAlerts`). A test that no channel delivers says "No channel could deliver it." (`push_test`). On a server where alerts aren't set up, the panel says "Alerts aren't set up on this server yet." (`get_settings`).
