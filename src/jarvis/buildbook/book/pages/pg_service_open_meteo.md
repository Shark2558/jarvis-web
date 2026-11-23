---
page: pg_service_open_meteo
written_by: Workshop · Mark XXIV
written_on: 2026-11-24
sources:
  "src/jarvis/helpers/sources.py": "4a821b855f40c328"
---
## In plain words
Open-Meteo is a free weather forecast service that needs no account and no key. JARVIS's helpers use it to warn you about the weather where you live: heavy rain within the hour, strong gusts, a very hot or cold feel, a day of heavy rain ahead. The same forecast feeds the morning brief's weather line and keeps free-time ideas indoors when rain is likely. What goes to Open-Meteo is only a map point near your home, rounded to about a kilometre, and your time zone; the name of your district never leaves JARVIS. The panel and the brief credit Open-Meteo by name, as its free licence asks.

## Example (made up)
You set your place in the Helpers panel and leave the rain threshold at its default. At 13:00 the forecast shows about 22 mm of rain in the hour around 15:00. At 13:01 one note arrives: "Heavy rain likely around 15:00 today", with the credit line. No second rain note comes that day.

## How it works
Weather runs only with `weather_enabled` and `helpers_enabled` on, and only for an owner who has set a place, which is kept sealed in `outside`. The helpers' clock asks for a forecast for your place every `weather_poll_minutes` ({{fact:settings.weather_poll_minutes}} minutes), within the clock's run budget of `helpers_clock_budget_s` ({{fact:settings.helpers_clock_budget_s}} seconds). Every request goes to Open-Meteo's forecast address over HTTPS, with no key and no redirects followed, and must finish within {{fact:src/jarvis/helpers/sources.py:OUTSIDE_TIMEOUT_S}} seconds (`src/jarvis/helpers/sources.py`). An answer larger than {{fact:src/jarvis/helpers/sources.py:MAX_WEATHER_BYTES}} bytes is refused, and a value that isn't a plausible number is left out rather than trusted (`MAX_WEATHER_BYTES`). JARVIS looks for the first hour ahead over each of your thresholds and for heavy-rain days, then sends at most one weather warning of each kind a day (`weather_enabled`). The day's summary for the brief and any outage are kept sealed with your place in `outside`. Weather has its own share of each run, separate from the disaster feed, so a slow feed never holds it up (`src/jarvis/helpers/sources.py`).

## What it costs
Nothing in rupees: Open-Meteo is free for personal, non-commercial use and needs no key. JARVIS asks only for your one place, far below Open-Meteo's daily allowance.

## When it fails
If Open-Meteo doesn't answer, is slow or sends something unreadable, no warning goes out and the panel says since when the weather could not be read; JARVIS tries again sooner than usual. Unverified: exactly what Open-Meteo does if its free daily limit is ever passed. With no place set, or with `weather_enabled` off, there is simply no weather.
