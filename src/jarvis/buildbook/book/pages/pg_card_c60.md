---
page: pg_card_c60
written_by: Workshop · Mark XXIV
written_on: 2026-11-24
sources:
  "scripts/kitchen_fdc_subset.py": "62953434b4fe4ce4"
  "src/jarvis/api/helpers.py": "099ea755b96838a9"
  "src/jarvis/api/helpers_house.py": "8c3ca8188997f42d"
  "src/jarvis/api/helpers_kitchen.py": "a08b1c2b1fcf5e3c"
  "src/jarvis/api/helpers_nudges.py": "456eb205a715f0b6"
  "src/jarvis/api/helpers_today.py": "706db24ddb5a160b"
  "src/jarvis/api/r11_wiring.py": "4cfa5b25282b147c"
  "src/jarvis/api/static/console-helpers-house.js": "8ebbcafaaac2bc67"
  "src/jarvis/api/static/console-helpers-kitchen.js": "613cabb9f35a99c0"
  "src/jarvis/api/static/console-helpers-nudges.js": "357f2dc49663617b"
  "src/jarvis/api/static/console-helpers-today.js": "8443c7b4b68f86fb"
  "src/jarvis/api/static/console-helpers.css": "e022adf2c67b5b6b"
  "src/jarvis/api/static/console-helpers.js": "38c9179fa5cd2d23"
  "src/jarvis/helpers/__init__.py": "5691d27263678b69"
  "src/jarvis/helpers/brief.py": "50156137d9ae6c17"
  "src/jarvis/helpers/clock.py": "4e86225ff4e45a86"
  "src/jarvis/helpers/gate.py": "a59ec5e20df351a1"
  "src/jarvis/helpers/house/__init__.py": "a0da1c1a8020c6dd"
  "src/jarvis/helpers/house/breach.py": "ad5d78e54f943bb1"
  "src/jarvis/helpers/house/brief.py": "140ffed7e07a69f7"
  "src/jarvis/helpers/house/cap.py": "72ebb41fe2657764"
  "src/jarvis/helpers/house/chores.py": "722a784d27ce5886"
  "src/jarvis/helpers/house/feed.py": "ebd0b7fb4327bc26"
  "src/jarvis/helpers/house/fetch.py": "d4acfd6c57ce7819"
  "src/jarvis/helpers/house/guard.py": "bb6d648e009b95b7"
  "src/jarvis/helpers/house/models.py": "3a39b8ecf9a07d9b"
  "src/jarvis/helpers/house/night.py": "887342d6d008a955"
  "src/jarvis/helpers/house/part.py": "88e79158b758e6f2"
  "src/jarvis/helpers/house/phrases.py": "27ebae83c3dba025"
  "src/jarvis/helpers/house/privacy.py": "18b4ebc3438c4baf"
  "src/jarvis/helpers/house/rain.py": "6861411e6cc2a6b7"
  "src/jarvis/helpers/house/sachet.py": "e5a9ec73eae4a8d1"
  "src/jarvis/helpers/house/service.py": "b30d31d71b053cc7"
  "src/jarvis/helpers/house/service_request.py": "94e882c398af35c0"
  "src/jarvis/helpers/house/store.py": "f772cda58c199f2f"
  "src/jarvis/helpers/house/tools.py": "40c51a8de0bdb17c"
  "src/jarvis/helpers/house/upkeep.py": "eccf14456467670c"
  "src/jarvis/helpers/house/weather.py": "0f9b4c568e5e8d91"
  "src/jarvis/helpers/house/words.py": "b47130a75b03a72e"
  "src/jarvis/helpers/house/xmlsafe.py": "c42b5cd391f8c8e3"
  "src/jarvis/helpers/kinds.py": "a02b3028819c911a"
  "src/jarvis/helpers/kitchen/__init__.py": "6c8ec0278ab116a0"
  "src/jarvis/helpers/kitchen/blocks.py": "3113370d19f65142"
  "src/jarvis/helpers/kitchen/brief.py": "3918fb100919c72f"
  "src/jarvis/helpers/kitchen/data/fdc_subset.json": "8425fb005dde139c"
  "src/jarvis/helpers/kitchen/diet.py": "b737b7954210aa9b"
  "src/jarvis/helpers/kitchen/diet_words.py": "6bf2cbd734db0f32"
  "src/jarvis/helpers/kitchen/models.py": "650a3f55e85241a7"
  "src/jarvis/helpers/kitchen/nutrition.py": "a2458bbba89e83b0"
  "src/jarvis/helpers/kitchen/pantry.py": "5d05d50d48e895de"
  "src/jarvis/helpers/kitchen/part.py": "cff6dcc088e305b2"
  "src/jarvis/helpers/kitchen/phrases.py": "1e6cbd0c87e9c5a0"
  "src/jarvis/helpers/kitchen/privacy.py": "264ab50648bfee15"
  "src/jarvis/helpers/kitchen/receipts.py": "84928138ffa34150"
  "src/jarvis/helpers/kitchen/recipes.py": "eba12f014f416aa9"
  "src/jarvis/helpers/kitchen/service.py": "8e81ada6e69b5ad3"
  "src/jarvis/helpers/kitchen/spend.py": "7d33789baccc1983"
  "src/jarvis/helpers/kitchen/store.py": "2615571e20b44ba3"
  "src/jarvis/helpers/kitchen/tools.py": "03eea0f85f50bfea"
  "src/jarvis/helpers/nudges/__init__.py": "f5f7e8f075fd5165"
  "src/jarvis/helpers/nudges/activity.py": "e3c086c51e7130d4"
  "src/jarvis/helpers/nudges/brief.py": "67b71bc345e3bcd4"
  "src/jarvis/helpers/nudges/calendar.py": "b57b3bd4d8959bd9"
  "src/jarvis/helpers/nudges/focus.py": "f58e8cd73a18ed8f"
  "src/jarvis/helpers/nudges/freetime.py": "0557ef5ff643f39c"
  "src/jarvis/helpers/nudges/hydrate.py": "ceef8cbce201134b"
  "src/jarvis/helpers/nudges/ideas.py": "c242a0ac298b79e4"
  "src/jarvis/helpers/nudges/jobs.py": "4477e7fee9dbc4bc"
  "src/jarvis/helpers/nudges/models.py": "c9a1756d0606b429"
  "src/jarvis/helpers/nudges/part.py": "8ac0c6d1e80a6714"
  "src/jarvis/helpers/nudges/phrases.py": "8ff0b3bed5c5094e"
  "src/jarvis/helpers/nudges/privacy.py": "56a30373ba1abd2f"
  "src/jarvis/helpers/nudges/schedule.py": "a1fc85f5ef72bd69"
  "src/jarvis/helpers/nudges/service.py": "5a2ed317f5fa09a2"
  "src/jarvis/helpers/nudges/standup.py": "4bc6e669f9213165"
  "src/jarvis/helpers/nudges/store.py": "b16c7972f066620b"
  "src/jarvis/helpers/nudges/tools.py": "38c5ebfdcdeb4cb4"
  "src/jarvis/helpers/nudges/words.py": "be756dd15c961e49"
  "src/jarvis/helpers/paused.py": "9527fec21b3982dd"
  "src/jarvis/helpers/ports.py": "7af488a33ed280c9"
  "src/jarvis/helpers/privacy.py": "15c7fb23fe3fc1f7"
  "src/jarvis/helpers/sources.py": "4a821b855f40c328"
  "src/jarvis/helpers/today/__init__.py": "1c898246840eede2"
  "src/jarvis/helpers/today/bills.py": "b5428c9b37f01351"
  "src/jarvis/helpers/today/birthdays.py": "d69fe6eb17bd801f"
  "src/jarvis/helpers/today/brief.py": "a0e916cd6fb70740"
  "src/jarvis/helpers/today/focus.py": "bd674181abadc9e9"
  "src/jarvis/helpers/today/jobs.py": "ea342cb562d8cce0"
  "src/jarvis/helpers/today/models.py": "1bb9a71bf8e4641a"
  "src/jarvis/helpers/today/part.py": "59eaa4181d431d3e"
  "src/jarvis/helpers/today/pending.py": "b59a876c2a2a7995"
  "src/jarvis/helpers/today/phrases.py": "d8ae4f271a2ade66"
  "src/jarvis/helpers/today/privacy.py": "cea7522e49b27436"
  "src/jarvis/helpers/today/qr.py": "d81712162d609186"
  "src/jarvis/helpers/today/store.py": "36430395f83ee1db"
  "src/jarvis/helpers/today/text.py": "a89186543bbfa6c5"
  "src/jarvis/helpers/today/tools.py": "bbf40de618e63d3c"
  "src/jarvis/helpers/today/upi.py": "7ec14bb46c86c8b3"
  "src/jarvis/helpers/today/views.py": "5eb30855d5b3e2b6"
  "src/jarvis/tools/background.py": "c4d540d4ab2f2eb3"
---
## In plain words
Helpers are small, free jobs that look ahead for you, in the tabs of the Helpers panel. Today: your bills with reminders before each due date, birthdays from Google Contacts and your top priority. Home: the chores rota, home upkeep, the weather for your place and official disaster warnings for your district. Nudges: stand up, drink water, a walk you missed, an idea for free time. Kitchen: recipe ideas from your pantry that keep to your diet, rough nutrition and your grocery spend from e-mailed receipts. Nearly all of it is plain code, so it keeps working with the AI off; only new recipe ideas ask an AI (`src/jarvis/helpers/kitchen/recipes.py`).

## Example (made up)
Vikram adds his electricity bill: about ₹2,350, due on the 12th. JARVIS reminds him at 09:00 on the 9th, the 11th and the 12th. On the 12th he taps Pay; a card shows the payee and the amount, he approves it with his passkey, and a UPI link and QR code appear once, for his own UPI app, where he types his PIN. At 02:10 that night an official heavy-rain warning for his district rings his phone despite quiet hours. At 16:00 the next day, with no rain expected, a nudge suggests a short walk.

## How it works
Every helper message goes through `HelperSender`, which refuses any kind that isn't a helper's, holds a nudge to your snoozes and caps, at most {{fact:settings.nudges_max_per_day}} a day and {{fact:settings.nudges_max_per_hour}} an hour, and then hands it to the one alert policy for quiet hours.
The jobs ride the existing clocks: `Composite` runs the regular ones on the watchdog call within {{fact:settings.helpers_clock_budget_s}} seconds, and the daily Gmail scans on the morning tick (`src/jarvis/helpers/clock.py`).
`reminders_due` works out which bill reminders are owed today, and Pay only builds a UPI link from your saved bill after you approve its card, up to ₹{{fact:settings.bill_pay_cap_inr}}; the link is shown once, never kept, and JARVIS never pays (`src/jarvis/helpers/today/upi.py`).
A job that reads your Google data, such as birthdays, breach notices, the calendar, to-dos or receipts, asks the tool gateway first through `BackgroundReads`, reads only on Allow and leaves one audit line.
When a permission row stops a helper you switched on, `PauseCheck` shows one fixed line naming the row.
`WeatherJob` reads Open-Meteo about every {{fact:settings.weather_poll_minutes}} minutes for your rounded location, and `DisasterJob` reads NDMA SACHET's official warnings every {{fact:settings.disaster_poll_minutes}} minutes, keeping only those for your district.
At night `CapTeller` lets at most {{fact:src/jarvis/helpers/house/night.py:MAX_NIGHT_RINGS}} different disaster warnings ring and folds the rest into one morning summary.
A recipe idea is one AI call to a brain that doesn't learn from what it is told, after a check of your monthly limit; then the code check `allows` has the last word, so meat is never shown to a vegetarian kitchen (`src/jarvis/helpers/kitchen/diet.py`).
`src/jarvis/helpers/kitchen/nutrition.py:describe` gives rough nutrition from a bundled copy of USDA FoodData Central, labelled as US reference values.
Each helper's data is sealed with its own key and has a Privacy row to list, export and delete it (`src/jarvis/helpers/privacy.py`).

## What it costs
Nearly all of it costs nothing: Open-Meteo and SACHET are free with no key, the nutrition data is bundled, and the rest is plain code on JARVIS's own server (`src/jarvis/helpers/sources.py`). The one exception is a new recipe idea: a single AI call of at most {{fact:src/jarvis/helpers/kitchen/recipes.py:MAX_TOKENS}} tokens, counted against your monthly limit (`src/jarvis/helpers/kitchen/recipes.py`).

## When it fails
With the helpers off, or a part whose setup fails, that part is empty and the rest still run (`src/jarvis/api/r11_wiring.py`). If your nudge settings can't be read, no nudge goes (`HelperSender`). A warning no channel took is tried again on the next run (`CapTeller`). A stale clock shows in the panel (`src/jarvis/helpers/clock.py`). A feed that is down shows since when, and weather and alerts stay off without the token key (`WeatherJob`). Nutrition says "not installed" if its data file is missing (`src/jarvis/helpers/kitchen/nutrition.py`). With no private brain, recipe ideas fall back to your saved recipes that fit (`src/jarvis/helpers/kitchen/recipes.py`).
