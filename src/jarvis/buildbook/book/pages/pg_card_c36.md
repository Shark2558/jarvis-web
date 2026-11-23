---
page: pg_card_c36
written_by: Workshop · Mark XXIV
written_on: 2026-11-24
sources:
  "src/jarvis/api/media.py": "aa4e42876e43952e"
  "src/jarvis/api/static/console-media.js": "9470b3411b87efe1"
  "src/jarvis/integrations/youtube.py": "c96d11458be8fab1"
  "src/jarvis/media/__init__.py": "d22af73dcf2b98a4"
  "src/jarvis/media/service.py": "b536d789f9f47be8"
  "src/jarvis/media/tools.py": "fc968d3eb85733db"
  "src/jarvis/media/youtube.py": "47d17a4bac4f408e"
---
## In plain words
Ask JARVIS for a video or a song and it searches YouTube, then shows the results as cards under its reply. With your permission it lists your own playlists too, "Liked videos" first. A video starts only when you press Play, in the Media panel's privacy-enhanced player, never unasked. YouTube searching runs inside Google's free daily quota and pauses before it runs out.

## Example (made up)
On Sunday morning you ask "play some old Hindi film songs". JARVIS searches YouTube for music and shows five songs with their lengths, each with a Play button. You press Play on the third; the Media panel opens and the song starts. Later you ask "what's in my Workout playlist?" and it lists the first twenty videos, with a next page if you want more.

## How it works
`youtube_tools` give the brain a search, a list of your playlists and one playlist's videos, all read-only through the tool gateway (`src/jarvis/media/tools.py`).
A search uses JARVIS's own server key: embeddable videos only, moderate safe search, region India, music narrowed to the music category, at most {{fact:src/jarvis/media/tools.py:SEARCH_RESULTS}} results, plus one more call for the durations (`search_hits`, `details`).
Your playlists need your Google link and the YouTube grant; "Liked videos" comes first, and a playlist shows {{fact:src/jarvis/media/tools.py:PLAYLIST_PAGE}} videos a page (`playlists`, `playlist_videos`).
Every call is first reserved from the free allowance ledger (C44), given back if it never reached Google, and the day is closed when Google says the quota is gone (`YouTubeService`).
`YouTubeOwn` reads your own channel and uploads the same careful way, each call sent once and counted (`src/jarvis/integrations/youtube.py`).
Titles and channel names are other people's words, so the brain sees them fenced, and any write later in that turn becomes a card (`src/jarvis/media/tools.py`).
`src/jarvis/api/static/console-media.js` draws the cards; Play is the only way a video starts, in a privacy-enhanced YouTube player made at your click and removed when you stop.
The Vitals line reads the day's YouTube count and the month's Maps count from `GET /v1/quota`, and Integrations saves your Maps Home and Work through `PUT /v1/maps/places` (`src/jarvis/api/media.py`).

## What it costs
No rupees: the free allowance ledger stops YouTube before Google's free daily quota runs out (`YouTubeService`). It keeps no data of its own; the counts live in the ledger (C44).

## When it fails
At the day's stop JARVIS says YouTube searches are paused for today instead of searching (`src/jarvis/media/tools.py`). Without the YouTube grant your playlists answer with how to grant it, and nothing is sent to Google (`YouTubeNotGranted`). When the durations can't be had, the videos come without them, since the search is already paid (`details`). Without the server's Google key the YouTube tools are not offered (`build_media`).
