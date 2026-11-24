---
page: pg_card_c35
written_by: Workshop · Mark XXIV
written_on: 2026-11-24
sources:
  "src/jarvis/places/__init__.py": "dececf6ca654af2f"
  "src/jarvis/places/google_maps.py": "e501dc1330ddf0e6"
  "src/jarvis/places/service.py": "8ddf6f3c199455c1"
  "src/jarvis/places/store.py": "ca051c3236c69a6b"
  "src/jarvis/places/tools.py": "1f078ded21c4ca3e"
---
## In plain words
Ask JARVIS for a place ("a pharmacy open near Koramangala") or a route ("how long to work by bike right now?") and it asks Google Maps, then shows the answer as a card under the reply with an Open in Google Maps link. It knows your saved Home and Work, which you type once in Integrations, and sends them to Google only when you ask for a route. Maps runs inside Google's free monthly allowance and stops before it runs out.

## Example (made up)
At 8:50 am you ask "how long to work on the two-wheeler?". JARVIS swaps "work" for the Work address you saved, asks Google for a two-wheeler route with live traffic, and answers "about 34 minutes, 11.2 km" with a card that opens the route in Google Maps. Later you ask for "a good dosa place near Indiranagar"; it shows five places, each with its own Open in Google Maps link.

## How it works
`maps_tools` gives the brain a place search and a route, both read-only through the tool gateway (`src/jarvis/places/tools.py`).
`search_text` asks Google's place search for up to {{fact:src/jarvis/places/google_maps.py:PAGE_SIZE}} places, biased to India, with basic fields only (name, address, map link), and drops any field that does not check out (`src/jarvis/places/google_maps.py`).
`compute_route` asks for a car, two-wheeler or walking route, with live traffic for the first two, and reads back only the time and distance.
"Home" and "work" turn into your saved addresses from `MapsPlaces`, which keeps them encrypted with the deployment's token key in `maps_places` (`src/jarvis/places/store.py`). A place search refuses "home" or "work" outright, so your addresses never go with a search (`src/jarvis/places/tools.py`).
If the turn had read other people's words first, a route that would send Home or Work asks you before it goes (`maps_tools`).
Both tools refuse a phone number, an e-mail address or an account number in their words, using the web search's private-query guard (`src/jarvis/places/tools.py`).
Before each call the free allowance ledger (C44) reserves the exact kind of call Google bills, and you get at most {{fact:src/jarvis/places/tools.py:MAX_MAPS_PER_HOUR}} Maps calls an hour (`MapsService`).
You see the result as a card with the Google Maps attribution and its link, built by `place_link` and `directions_link`; the brain sees names, addresses, times and distances, never the links or coordinates. Nothing from Google is stored (`src/jarvis/places/tools.py`).

## What it costs
No rupees: the free allowance ledger stops Maps before Google's free monthly allowance runs out, so it never becomes a bill (`MapsService`). Its only stored data is your encrypted Home and Work (`maps_places`).

## When it fails
At the month's stop JARVIS says Maps is paused for the month instead of searching (`src/jarvis/places/tools.py`). If Home or Work is not set, it asks you for the address and sends nothing. A damaged or unreadable Home and Work record fails closed: "home" can't be resolved and nothing goes to Google (`PlacesUnreadable`). A route Google can't find or answer clearly is said plainly, and without the server's Google key the Maps tools are not offered at all (`src/jarvis/places/service.py`).
