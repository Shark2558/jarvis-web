---
page: pg_card_c71
written_by: Workshop · Mark XXIV
written_on: 2026-11-24
sources:
  "evals/r13/e2e.py": "4674cf168867869c"
  "evals/r13/needles.py": "cf4fcee3b562a0fa"
  "evals/r13/phone.py": "63e0c70756acc8cf"
  "evals/r13/styling.py": "e389d9c1cbc715f6"
  "src/jarvis/api/outfits.py": "82d01c0c1a75d43f"
  "src/jarvis/api/static/console-helpers-wardrobe.js": "acd25c1703c9f832"
  "src/jarvis/api/static/console-r7-send.js": "545d6c2abaf1e8c6"
  "src/jarvis/api/static/console-vision-r13.js": "257e08f6dbb85e66"
  "src/jarvis/api/static/console-wardrobe-pieces.js": "fc67587233a37088"
  "src/jarvis/api/static/console-wardrobe-scan.js": "abc7558a46e7675d"
  "src/jarvis/api/static/console-wardrobe-words.js": "ad99400085c24604"
  "src/jarvis/api/static/console-wardrobe.css": "59a615346858721a"
  "src/jarvis/offline/phrases_r13.py": "2fbd4988328c6be8"
  "src/jarvis/wardrobe/phone/__init__.py": "b03509c8e734bdae"
  "src/jarvis/wardrobe/phone/part.py": "214e041cf53d80bd"
  "src/jarvis/wardrobe/phone/privacy.py": "bdd9e279aeb6d7b8"
  "src/jarvis/wardrobe/styling/__init__.py": "0c7e42c16ad32f78"
  "src/jarvis/wardrobe/styling/actions.py": "4cd977b6364b3f89"
  "src/jarvis/wardrobe/styling/answers.py": "7a20f123cb05ae74"
  "src/jarvis/wardrobe/styling/calendar.py": "31a1c7498bd0995c"
  "src/jarvis/wardrobe/styling/cards.py": "45ea0d2b75d0cbd9"
  "src/jarvis/wardrobe/styling/data.py": "2e2b422cfd39ee1d"
  "src/jarvis/wardrobe/styling/engine.py": "da45a027ccc76538"
  "src/jarvis/wardrobe/styling/jobs.py": "3536abb06b2bd217"
  "src/jarvis/wardrobe/styling/look.py": "49d14273ff8e7f5b"
  "src/jarvis/wardrobe/styling/outlook.py": "ba7798e4d73256fc"
  "src/jarvis/wardrobe/styling/part.py": "2384375983e34cc4"
  "src/jarvis/wardrobe/styling/plans.py": "f2d89b8ae3afc926"
  "src/jarvis/wardrobe/styling/prefs.py": "4c954007ab01e1ec"
  "src/jarvis/wardrobe/styling/rank.py": "474d652195b37cde"
  "src/jarvis/wardrobe/styling/ready.py": "c2364da92205f632"
  "src/jarvis/wardrobe/styling/refresh.py": "f413a4c6f5eeb28a"
  "src/jarvis/wardrobe/styling/reserve.py": "b8b920b5ed9fdf3c"
  "src/jarvis/wardrobe/styling/rules.json": "199e4a9cb35cc85b"
  "src/jarvis/wardrobe/styling/rules.py": "01f21c7fe6cac0f9"
  "src/jarvis/wardrobe/styling/sealed.py": "b340b0d7da28ed6f"
  "src/jarvis/wardrobe/styling/service.py": "e3294ed9ed9a3a1d"
  "src/jarvis/wardrobe/styling/texts.py": "ad24bebcca710c9b"
  "src/jarvis/wardrobe/styling/tools.py": "531e69d3dd1a55c2"
  "src/jarvis/wardrobe/styling/tryon_card.py": "b05959a7b3ba30a3"
  "src/jarvis/wardrobe/styling/views.py": "22cc96d004b3decf"
  "src/jarvis/wardrobe/styling/wear.py": "ddebc234a16df155"
  "src/jarvis/wardrobe/styling/wearlog.py": "ae4741e0a06242f7"
---
## In plain words
Ask "what should I wear tomorrow?" and JARVIS picks an outfit from the clothes in your wardrobe that are actually clean and ready, for the occasion on your calendar and tomorrow's weather. It explains each choice, offers alternatives, and when a look can't be completed it says what is missing and what to do, such as "press the white shirt" (`src/jarvis/wardrobe/styling/engine.py`). It works by fixed, readable rules, not by AI, so it works with the AI switched off too (`src/jarvis/wardrobe/styling/rules.py`). The evening before an event on your calendar you get a note that tomorrow's outfit is ready.

## Example (made up)
Rahul has a client meeting at 10:00 tomorrow and his calendar title says "Board review". At 20:00 JARVIS tells him tomorrow's outfit is ready: the light blue shirt, charcoal trousers, black belt and black shoes, because the meeting reads as business formal and the belt matches the shoes. Two alternatives swap the shirt. At 22:30 he drops the blue shirt in the basket by mistake; JARVIS marks the plan "needs a new shirt", suggests the white one, and tells him once.

## How it works
`src/jarvis/wardrobe/styling/rules.json` holds the rules as data: slots, dress codes, words that name an occasion, colour pairs and which pieces go to the laundry after one wear; `src/jarvis/wardrobe/styling/rules.py` refuses a file that names an unknown type or code.
`suggest` fills each slot of the dress code: pieces go through fixed exclusions in order (formality, your "never" rules, rain, only ready pieces, whole pairs and sets, pieces another plan holds), and what is left is ranked by `best`.
It returns a main look and up to {{fact:src/jarvis/wardrobe/styling/engine.py:MAX_ALTERNATIVES}} alternatives, each with reasons naming the actual pieces, and a gap with a next action when a slot stays empty (`src/jarvis/wardrobe/styling/rank.py`).
A plan's picks are its reservations, so the same shirt is never picked for two events the same day (`src/jarvis/wardrobe/styling/reserve.py`). A plan is kept {{fact:src/jarvis/wardrobe/styling/plans.py:KEEP_DAYS}} days after its day, up to {{fact:src/jarvis/wardrobe/styling/plans.py:MAX_PLANS}} plans, and invites can make at most {{fact:src/jarvis/wardrobe/styling/plans.py:MAX_CAL_AHEAD}} at once (`src/jarvis/wardrobe/styling/plans.py`).
`Calendar` reads only the one calendar you pick, only start, end and the fields you allow, through the governed background read on Allow only, and never stores a title.
`Outlook` fetches the forecast for your Helpers place at most twice a day and says what a look assumed.
`OutfitClock` runs on the regular clock: it reads your calendar about every {{fact:settings.wardrobe_calendar_refresh_min}} minutes, makes or refreshes plans, and sends the ready note from {{fact:settings.wardrobe_plan_evening}} the evening before.
When a piece picked for a plan goes to the laundry, the refresh in `src/jarvis/wardrobe/styling/refresh.py` marks the plan and finds a substitute; wearing a piece for its own plan is never treated as a change (`src/jarvis/wardrobe/styling/wear.py`).

## What it costs
Nothing. The outfit rules are plain code, the calendar is read at most about hourly through your own Google link, and the weather comes from the free Open-Meteo forecast a couple of times a day (`src/jarvis/wardrobe/styling/jobs.py`).

## When it fails
With no calendar picked, or the calendar row not on Allow, only manual plans work and Settings says why (`Calendar`). With no weather the look says "Weather unknown: I assumed indoors" (`Outlook`). With no complete look you get the gap and a next action (`src/jarvis/wardrobe/styling/rank.py`). A cancelled event leaves a draft and sends no alert. A rules file that fails its check leaves outfits "setup failed" while the rest runs (`src/jarvis/wardrobe/styling/rules.py`). After a key change your plans can't be opened and are never overwritten (`src/jarvis/wardrobe/styling/sealed.py`).
