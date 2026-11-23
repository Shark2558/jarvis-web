---
page: pg_screen_home
written_by: Workshop · Mark XXIV
written_on: 2026-11-24
sources:
  "src/jarvis/api/camera.py": "b1dd8720f99237ef"
  "src/jarvis/api/home.py": "cd0a9f3557a74808"
  "src/jarvis/api/static/console-home-panel.js": "bb7fd758c81f6d63"
  "src/jarvis/api/static/console-home.js": "5694fc12065091f8"
  "src/jarvis/api/static/console.html": "9f4c0c68f45e46fe"
---
## In plain words
Home is your burglar alarm and gate camera in one panel. A large line says whether the alarm is Armed, Disarmed or still Arming; Arm (Away) and Arm (Night) switch it on, and Disarm switches it off after checking it is really you. Below are your cameras, a list of what the camera noted today or yesterday, and a search through the camera's history. It works through a laptop at your home; video and faces stay on that laptop (`src/jarvis/api/static/console-home.js`). It is a home helper, not a monitored alarm service, as the panel itself warns (`src/jarvis/api/static/console-home-panel.js`).

## Example (made up)
At 22:40 you press Arm (Night). The panel shows "Arming…" for a few seconds, then "Armed (Night)" once the laptop confirms. At 02:15 a delivery scooter stops at the gate; the feed later says "02:15 · gate · a person · alerted you". In the morning you press Disarm, read "Switch off the burglar alarm?", press its button and use your passkey. The panel says "The alarm is off." You then search the history for Packages yesterday and find the parcel left at 16:30.

## How it works
The panel reads the alarm's state from `GET /v1/home/alarm` and the camera list from `GET /v1/home/cameras` when it opens (`src/jarvis/api/static/console-home-panel.js`). Arm (Away) and Arm (Night) send `POST /v1/home/arm`, and the panel shows Armed only once your laptop confirms it (`src/jarvis/api/camera.py:arm_post`). Disarm first asks "Switch off the burglar alarm?", then proves it is you with your passkey for exactly this home, or a Google sign-in from the last few minutes, through `POST /v1/home/disarm` (`src/jarvis/api/camera.py:disarm_post`). Disarming works only from the console in your browser (`src/jarvis/api/camera.py`). The Today and Yesterday list comes from `GET /v1/home/feed`, and each line says what was seen, where, and whether JARVIS alerted you, sent it quietly or held it until morning (`src/jarvis/api/static/console-home-panel.js`). "Search the camera history" asks `GET /v1/home/history` for packages, people JARVIS recognises or strangers, between two times (`src/jarvis/api/camera.py:history_get`). "Camera and zone names" saves names, zones and how many days recordings stay at home through `PUT /v1/home/cameras`. Linking the laptop itself happens under Integrations, Home: a one-time code from `POST /v1/home/link-code` is typed into the setup script on the laptop (`src/jarvis/api/static/console-home.js`).

## What it costs
Home costs nothing to run: the camera, its detector and the recordings live on your own laptop (`src/jarvis/api/home.py`). The link uses free services, and the panel's own reads and writes are a few database calls (`src/jarvis/api/camera.py`).

## When it fails
If the laptop is off or asleep, the panel says "Your home laptop is off or asleep" and that the camera is blind until it is back. With no camera given an alarm zone, Armed comes with a warning that JARVIS is not protecting anything yet. If your sign-in is too old to disarm, it says "Sign in with Google again to disarm." If Home is not set up on the server, the panel says it is not available. Changes are limited to {{fact:src/jarvis/api/camera.py:CHANGE_PER_MINUTE}} a minute.
