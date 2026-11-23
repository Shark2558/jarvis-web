---
page: pg_service_google_maps_platform
written_by: Workshop · Mark XXIV
written_on: 2026-11-24
sources:
  "src/jarvis/config.py": "0f90cbe2c5f58fde"
  "src/jarvis/integrations/google_key.py": "5bb317b3fa34a038"
  "src/jarvis/media/service.py": "b536d789f9f47be8"
  "src/jarvis/places/google_maps.py": "e501dc1330ddf0e6"
---
## In plain words
Google Maps Platform is the paid-for-business side of Google Maps. JARVIS uses two parts of it: place search ("a pharmacy open near the station") and routes ("how long to the airport by car right now?"), by car, two-wheeler or on foot. Answers show as cards under the reply. JARVIS uses its own server key for this, not your Google account. What goes to Google is the search words, or the start and end of a route; your saved Home and Work go to Google only inside a route you ask for. JARVIS counts its own use and stops well before Google's free monthly allowance would turn into a bill.

## Example (made up)
At 17:40 you ask: "How long to the airport by car if I leave now?" JARVIS sends Google your saved Home and the airport, by car with live traffic. Google answers 52 minutes and 31 km, and the card shows both. The month's route counter moves from 140 to 141.

## How it works
`build_media` builds Maps and YouTube together, with one key client and one shared counter of the free allowances, only when `google_api_key` is set (`src/jarvis/media/service.py`). `GoogleKeyClient` sends the key only in a request header, never in an address, and only to Google's places, routes and YouTube addresses over HTTPS (`_allowed`). It follows no redirect, gives each call {{fact:src/jarvis/integrations/google_key.py:DEADLINE_S}} seconds in all and refuses an answer past {{fact:src/jarvis/integrations/google_key.py:MAX_RESPONSE_BYTES}} bytes (`src/jarvis/integrations/google_key.py`). `search_text` asks for at most {{fact:src/jarvis/places/google_maps.py:PAGE_SIZE}} places with only the name, address, map point, map link and whether the place is open for business: no ratings, hours or phone numbers, which Google charges more for (`src/jarvis/places/google_maps.py`). `compute_route` asks only for the time and the distance, with live traffic for car and two-wheeler. Every field Google sends back is checked, and a place without a valid id is dropped (`_place`). Your Home and Work are kept sealed with the server's token key (`build_media`). The counter uses Google's price list for your billing account, `maps_pricing` ({{fact:settings.maps_pricing}} by default, the one with the lower free caps), so a wrong guess only stops Maps early. Each error gets JARVIS's own words, and an answer from Google, even an error, counts against the allowance (`_error`).

## What it costs
Nothing in rupees: JARVIS stops each kind of call before Google's free monthly allowance runs out, so nothing becomes paid. The Vitals board shows each counter (`quota_view`). If other projects share your Google billing account, Google counts their use too, and the deploy script warns about that.

## When it fails
With no key, the Maps tools are not there. At the stop, JARVIS says Maps is used up for the month. An unreadable counter stops the call rather than risking paid use. A refused key, a switched-off service, a busy or slow Google each give one plain sentence, such as "Google refused JARVIS's API key" (`KeyAPIError`). No route found is said plainly.
