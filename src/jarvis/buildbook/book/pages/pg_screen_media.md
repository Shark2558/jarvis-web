---
page: pg_screen_media
written_by: Workshop · Mark XXIV
written_on: 2026-11-24
sources:
  "src/jarvis/api/static/console-media.js": "9470b3411b87efe1"
  "src/jarvis/api/static/console.html": "9f4c0c68f45e46fe"
---
## In plain words
Media is JARVIS's small video player. When you ask for a song or a video, the reply shows cards from YouTube, each with a Play button. Nothing plays until you press Play; then the video opens in this panel, in YouTube's privacy-enhanced player, with the other results listed underneath so you pick the next one. Stop removes the player again (`src/jarvis/api/static/console.html`).

## Example (made up)
On a Sunday morning you type "Play some old Hindi film songs". The reply shows five video cards from YouTube with their titles, channels and lengths. You press Play on the second one; the Media panel opens and the song starts, with the note "Playing:" and its title. When it ends you tap the fourth title in the list below the player, and that one starts. Later you press Stop and the player is gone.

## How it works
A reply that found videos carries cards, and `src/jarvis/api/static/console-media.js` draws each one under the reply with its title, channel, length and a Play button. Pressing Play is the only way a video starts: it opens the Media panel and only then makes the player there (`src/jarvis/api/static/console-media.js`). The player loads from YouTube's privacy-enhanced address, and it is boxed in so it cannot touch the rest of the console (`src/jarvis/api/static/console-media.js`). The other videos from the same result are listed under the player as buttons, and pressing one plays it (`src/jarvis/api/static/console.html`). Stop removes the player, and closing or hiding the panel stops the video too (`src/jarvis/api/static/console-media.js`). A video YouTube allows only on its own site shows "Can only be played on YouTube" instead of Play (`src/jarvis/api/static/console-media.js`). The same file draws the Maps place and route cards, each with "Open in Google Maps" (`src/jarvis/api/static/console-media.js`).

## What it costs
Playing a video costs nothing (`src/jarvis/api/static/console-media.js`). Finding videos uses YouTube searches from Google's free daily allowance, and JARVIS stops before anything would be charged; the count shows in Vitals (`src/jarvis/api/static/console-media.js`).

## When it fails
If no video was found, the card says "No video found." With no YouTube key on the server, Vitals says "YouTube: not set up" and replies have no video cards. A video that may not be shown elsewhere gets "Can only be played on YouTube" and no Play button (`src/jarvis/api/static/console-media.js`). If the panel is empty, it says "Ask JARVIS for a song or a video, then press Play on its card."
