---
page: pg_screen_helpers
written_by: Workshop · Mark XXIV
written_on: 2026-11-24
sources:
  "src/jarvis/api/helpers.py": "099ea755b96838a9"
  "src/jarvis/api/helpers_house.py": "8c3ca8188997f42d"
  "src/jarvis/api/helpers_kitchen.py": "a08b1c2b1fcf5e3c"
  "src/jarvis/api/helpers_nudges.py": "456eb205a715f0b6"
  "src/jarvis/api/helpers_today.py": "706db24ddb5a160b"
  "src/jarvis/api/static/console-helpers-house.js": "8ebbcafaaac2bc67"
  "src/jarvis/api/static/console-helpers-kitchen.js": "613cabb9f35a99c0"
  "src/jarvis/api/static/console-helpers-nudges.js": "357f2dc49663617b"
  "src/jarvis/api/static/console-helpers-today.js": "8443c7b4b68f86fb"
  "src/jarvis/api/static/console-helpers-wardrobe.js": "acd25c1703c9f832"
  "src/jarvis/api/static/console-helpers-watch.js": "66676faabf8cfcc9"
  "src/jarvis/api/static/console-helpers.js": "38c9179fa5cd2d23"
  "src/jarvis/api/static/console.html": "9f4c0c68f45e46fe"
---
## In plain words
Helpers gathers the small daily jobs JARVIS does without being asked, in six tabs. Today shows your top priority, what is pending, bills with a prepared UPI payment, and birthdays. Home keeps the chores rota, home upkeep, weather and disaster alerts for your area, and breach notices. Nudges holds the gentle reminders: stand up, drink water, an activity you chose, free time, focus. Kitchen keeps your pantry, tastes, recipes and grocery spend. Watch shows steps, heart rate and sleep from your watch or phone. Wardrobe plans what to wear and tracks the laundry (`src/jarvis/api/static/console-helpers.js`).

## Example (made up)
At 9:00 the Today tab says the electricity bill of ₹1,240.50 is due on the 25th. You press "Ask to pay this", approve the card with your passkey, and a QR code and "Open in UPI app" appear in the bill's row; you pay in your UPI app with your PIN and press Paid. At 11:30 a stand-up nudge arrives; in Nudges you press Snooze 1 h because you are in a call. In Home you tick "Clean the water filter" as done, and its row turns back to "On schedule".

## How it works
The panel's frame reads `GET /v1/helpers` for which parts are on, the clock line and the nudge limits, then builds the six tabs (`src/jarvis/api/static/console-helpers.js`). Each tab starts with any "paused" line, such as a helper your Permissions stop (`src/jarvis/api/helpers.py:helpers_get`). Today reads `GET /v1/helpers/today`; "Ask to pay this" makes an approval card through `POST /v1/helpers/today/bills/{bill_id}/pay`, and the approved payment shows once as a UPI link and QR (`src/jarvis/api/static/console-helpers-today.js`). JARVIS never pays: you finish it in your own UPI app (`src/jarvis/api/static/console-helpers-today.js`). Home reads `GET /v1/helpers/house`, and chores and upkeep are added and ticked off through their own routes (`src/jarvis/api/helpers_house.py:chore_done`). Its alerts are shown as SACHET's own words, never as JARVIS's (`src/jarvis/api/static/console-helpers-house.js`). Nudges reads `GET /v1/helpers/nudges`; each nudge has a switch, a snooze button and Stop for today, through `POST /v1/helpers/gate/{kind}/snooze` and `POST /v1/helpers/gate/{kind}/stop` (`src/jarvis/api/static/console-helpers-nudges.js`). Kitchen reads `GET /v1/helpers/kitchen`, and cooking times reach your calendar only through an approval card (`src/jarvis/api/helpers_kitchen.py:kitchen_propose`). Watch and Wardrobe draw their own tabs (`src/jarvis/api/static/console-helpers-watch.js`, `src/jarvis/api/static/console-helpers-wardrobe.js`).

## What it costs
The helpers use free sources and JARVIS's own records, so they cost nothing (`src/jarvis/api/helpers.py`). Weather comes from a free service with no key, and the weather setting is {{fact:settings.weather_enabled}} (`src/jarvis/api/helpers_house.py`). New recipe ideas come from the chat, which uses the paid AI; the Kitchen tab itself never calls the AI (`src/jarvis/api/static/console-helpers-kitchen.js`).

## When it fails
If the helpers are off on the server, the panel says "The helpers are off on this server." Nudges never exceed {{fact:settings.nudges_max_per_hour}} an hour or {{fact:settings.nudges_max_per_day}} a day (`src/jarvis/api/helpers.py`). If a change fails, the tab says "That didn't work." with the reason. Changes are limited to {{fact:src/jarvis/api/helpers.py:CHANGES_PER_MINUTE}} a minute. If the server is out of reach (`src/jarvis/api/static/console-helpers.js`), it says "Can't reach JARVIS. Check your connection."
