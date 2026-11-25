---
page: pg_service_web_push
written_by: Workshop · Mark XXIV
written_on: 2026-11-24
sources:
  "src/jarvis/api/home_wiring.py": "47912d10ccd3e249"
  "src/jarvis/config.py": "8c6265f13d09201d"
---
## In plain words
Web Push is the standard way a website sends notifications to your browser, even when its tab is closed. Each browser maker runs its own push service that delivers them. JARVIS uses it to send its alerts to the browsers you allow, as well as to Telegram. Each message is encrypted for that one browser, so the push service carries it without being able to read it. The message is the fixed alert text and a link back to JARVIS, never a picture.

## Example (made up)
On your work laptop's browser you press "Allow notifications" in the console. That evening at 19:20 a document in your vault is a month from expiry; a notification pops up on that laptop and the same alert arrives on Telegram. You click it and the console opens on the vault.

## How it works
`build_push` sets up browser notifications only when `webpush_enabled` is on and JARVIS has its public address, or else an owner e-mail, to name as the sender (`src/jarvis/api/home_wiring.py`). JARVIS signs its pushes with its own VAPID key, made from the server's token key ({{fact:src/jarvis/api/home_wiring.py:VAPID_BYTES}} bytes for that purpose), so there is no extra secret to keep (`build_push`). Your browsers' subscriptions are stored sealed with JARVIS's own key (`build_push`). `wire_notify` puts Web Push and Telegram behind the one alert policy, so quiet hours, storms and the urgent rules are the same on both (`src/jarvis/api/home_wiring.py:wire_notify`). Nothing is pushed to the device while a guest show of the Build Book is running (`wire_notify`). If Web Push fails to set up, `wire_notify` logs it and alerts still go to Telegram; the rest of JARVIS keeps running. The Privacy panel lists the browser subscriptions, with delete (`home_privacy_sources`).

## What it costs
Nothing in rupees: the push services are free and run by the browser makers.

## When it fails
A browser that has gone away is removed from the list, and the other channels are not affected. Without the server's token key, or with `webpush_enabled` off, browser notifications are off and alerts go to Telegram only (`src/jarvis/api/home_wiring.py:build_push`). A browser where you blocked notifications gets none.
