---
page: pg_screen_connectors
written_by: Workshop · Mark XXIV
written_on: 2026-11-24
sources:
  "src/jarvis/api/static/console-connectors.js": "ff3bd4922c9d1c14"
  "src/jarvis/api/static/console.html": "9f4c0c68f45e46fe"
  "src/jarvis/photos/api.py": "8ac985d0fd795e2a"
---
## In plain words
Connectors links three more services, each read-only. GitHub: you paste a token here, never in chat, and JARVIS reads your profile, repositories and recent activity. YouTube: your own channel and uploads, through your Google link. Google Photos: you choose photos in Google's own picker, they go to your home laptop to find faces, and JARVIS keeps ids, never pictures. Naming anyone found in them needs their consent, in Faces (`src/jarvis/api/static/console-connectors.js`).

## Example (made up)
You want JARVIS to tell you what changed in your hobby projects this week. In Connectors you paste a GitHub token into "GitHub token" and press Connect GitHub; the card says "Connected as" your login. Later you press Choose photos under Google Photos, pick 40 holiday photos in the new tab, then press Import chosen photos. The panel says "Reading your photos. It carries on by itself from here." Faces later shows two Unnamed groups for you to name or forget.

## How it works
When the panel opens, it reads the state of all three from `GET /v1/connectors` (`src/jarvis/api/static/console-connectors.js`). Connect GitHub sends the token once to `PUT /v1/connectors/github`, which checks it with GitHub, stores it encrypted and never sends it back (`src/jarvis/photos/api.py:github_connect`). The token box is cleared at once, so a failed save never leaves it on screen (`src/jarvis/api/static/console-connectors.js`). Disconnect first asks you to confirm that JARVIS forgets the token, then calls `DELETE /v1/connectors/github` (`src/jarvis/photos/api.py:github_disconnect`). The YouTube card only shows whether your channel is reachable through the Google link, and points to Integrations when a Grant is missing (`src/jarvis/api/static/console-connectors.js`). Choose photos asks `POST /v1/connectors/photos/start` for a Google picker link and opens it in a new tab (`src/jarvis/photos/api.py:photos_start`). Import chosen photos runs `POST /v1/connectors/photos/import`, which hands the picked photos to your home laptop in small steps, in the background (`src/jarvis/photos/api.py:photos_import`). Pictures never pass through these routes (`src/jarvis/photos/api.py`).

## What it costs
Connectors costs nothing: GitHub's and Google's read access are free, and face finding runs on your own laptop (`src/jarvis/photos/api.py`). Up to {{fact:settings.photos_max_picked}} photos are read per pick (`src/jarvis/photos/api.py:photos_import`).

## When it fails
A wrong or expired GitHub token is refused with a plain reason, and the card says "Needs reconnecting: paste a new token." if GitHub stops accepting it. Without Google sign-in or a Grant, the YouTube and Photos cards say "Sign in with Google first." or "Press Grant for this in Integrations." If the home laptop is asleep, the import says it carries on when the laptop is back (`src/jarvis/api/static/console-connectors.js`). If Google's picker session ends, it asks you to press Choose photos and pick again. Changes are limited to {{fact:src/jarvis/photos/api.py:CHANGES_PER_MINUTE}} a minute.
