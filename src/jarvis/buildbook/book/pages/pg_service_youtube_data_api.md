---
page: pg_service_youtube_data_api
written_by: Workshop · Mark XXIV
written_on: 2026-11-24
sources:
  "src/jarvis/config.py": "8c6265f13d09201d"
  "src/jarvis/integrations/google_key.py": "5bb317b3fa34a038"
---
## In plain words
The YouTube Data API is YouTube's official way for programs to search videos and read playlists. JARVIS uses it to find videos and music for you and play them in the Media panel ("a ten-minute stretching video", "that new song from the film") and, if you grant it, to read your own YouTube playlists. Searches use JARVIS's own server key, not your account; your playlists are read through your Google link, read-only. What goes to Google is the search words you asked for, and for playlists, the request to list your own. JARVIS counts its daily use and stops before YouTube's free daily allowance runs out.

## Example (made up)
At 6:50 you ask: "Find a short morning yoga video for beginners." JARVIS searches YouTube and shows three cards with titles, channels and lengths. You open the second. The day's search counter moves from 4 to 5, far below the stop.

## How it works
JARVIS builds its key client only when `google_api_key` is set; without it the YouTube and Maps tools are never registered (`src/jarvis/integrations/google_key.py:build_google_key_client`). `GoogleKeyClient` sends the key only in a request header, never in an address, and only to YouTube's own address over HTTPS (`_allowed`). It follows no redirect, gives each call {{fact:src/jarvis/integrations/google_key.py:DEADLINE_S}} seconds in all and refuses an answer past {{fact:src/jarvis/integrations/google_key.py:MAX_RESPONSE_BYTES}} bytes (`src/jarvis/integrations/google_key.py`). YouTube counts every request against its daily quota, even a refused one, so `GoogleKeyClient` treats any answer from Google, error or not, as counted. Only a call that clearly never reached Google gives its count back (`KeyAPIError`). When Google says the day's quota is gone, `_error` marks it so the counter closes that day, while a short burst limit only means "busy, try again in a minute". The key lives in Secret Manager and the server reads it as a secret setting, never printed (`src/jarvis/config.py:Settings`).

## What it costs
Nothing in rupees: JARVIS stops before YouTube's free daily quota is used up, so nothing becomes paid. The Vitals board shows the day's count.

## When it fails
With no key, the YouTube tools are not there. At the daily stop, JARVIS says so until the next day starts at midnight Pacific time, when the quota resets. A refused key, a switched-off service, a busy, slow or unreachable Google each give one plain sentence in JARVIS's words, never Google's (`KeyAPIError`). Without the YouTube permission on your Google link, your playlists stay closed while search still works.
