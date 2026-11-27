---
page: pg_module_home
written_by: Workshop · Mark XXIV
written_on: 2026-11-24
sources:
  "evals/r7/vision.py": "6915895e39b87c6e"
  "scripts/vision_assets.py": "fb34eec7a323c768"
  "src/jarvis/api/camera.py": "b1dd8720f99237ef"
  "src/jarvis/api/console.py": "5f89470424a0a10a"
  "src/jarvis/api/home.py": "cd0a9f3557a74808"
  "src/jarvis/api/home_wiring.py": "47912d10ccd3e249"
  "src/jarvis/api/static/console-camera-panel.js": "8e142dadab602be2"
  "src/jarvis/api/static/console-camera.css": "30a4a654f42d34ed"
  "src/jarvis/api/static/console-camera.js": "c917b03cb1ff1deb"
  "src/jarvis/api/static/console-home-panel.js": "bb7fd758c81f6d63"
  "src/jarvis/api/static/console-home.js": "5694fc12065091f8"
  "src/jarvis/api/static/console-r7-send.js": "545d6c2abaf1e8c6"
  "src/jarvis/api/static/console-vision.js": "19bb229445ef34de"
  "src/jarvis/api/vision.py": "dd9f8fd3f32fbec2"
  "src/jarvis/brief/home_overnight.py": "5f5e4b1de238e306"
  "src/jarvis/home/client.py": "3364bbf315a99086"
  "src/jarvis/home/devices.py": "bf96dfa5e5a51a8a"
  "src/jarvis/home/heartbeat.py": "028d88e299dd4f48"
  "src/jarvis/home/kit.py": "48aad7dfbf328ee8"
  "src/jarvis/home/link.py": "165c8f9201511281"
  "src/jarvis/home/signing.py": "4499c07dbb6aa847"
  "src/jarvis/home/store.py": "df4eb9b455c772e0"
  "src/jarvis/home/tools.py": "cfbe1c5b4edaeda8"
  "src/jarvis/home/watchdog.py": "5ed83e7a835b50e2"
  "src/jarvis/home/webhook.py": "2d41ed0e356a9910"
  "src/jarvis/vision/assets.py": "f0807a871257eb2d"
  "src/jarvis/vision/part.py": "092b1fb37d1a192d"
  "src/jarvis/vision/privacy.py": "1fd90827889acb01"
  "src/jarvis/vision/results.py": "3a35718bf243ce23"
  "src/jarvis/vision/store.py": "fbe61ccef010668b"
  "src/jarvis/vision/tools.py": "704bb79eeafabe12"
---
## In plain words
This module connects JARVIS to your home. A small bridge runs on your home laptop beside Home Assistant (your smart devices), Frigate (your cameras) and Mosquitto (the messages between them). The cloud JARVIS talks to the bridge only over a private, signed link, so you arm the burglar alarm, ask who was at the gate yesterday, see your devices and hear when a parcel arrives. Separately, the Camera panel lets your phone's or laptop's camera read text, codes and labels on the device itself, and no picture leaves it unless you choose to send one.

## Example (made up)
Before a weekend away, Rhea taps Arm, then Away, in the Home panel, and within a minute her laptop confirms. On Saturday at 14:12 Frigate sees a person at the back door; the bridge checks the event at home, signs it and sends it, and her phone rings with an urgent alert. It is the gardener, a day early. On Monday her brief's "Home overnight" line reads: 1 burglar alert, 2 parcels. To disarm she taps Disarm and confirms with her fingerprint.

## How it works
You link the laptop with a one-time code of {{fact:src/jarvis/home/link.py:CODE_LEN}} characters that lasts {{fact:src/jarvis/home/link.py:CODE_TTL_S}} seconds; `src/jarvis/home/link.py` checks the bridge's address and makes a signed test call before it stores the link. Every message either way is signed by `src/jarvis/home/signing.py` with a separate key for each direction, and refused when more than {{fact:src/jarvis/home/signing.py:MAX_SKEW_S}} seconds off or replayed. `src/jarvis/home/client.py` reaches only the bridge's fixed routes and gives up after {{fact:src/jarvis/home/client.py:TIMEOUT_S}} seconds. The bridge's events arrive at `src/jarvis/home/webhook.py`, which checks the signature before reading anything, allows a network client {{fact:src/jarvis/home/webhook.py:CLIENT_PER_MINUTE}} requests a minute, and handles a repeated event once. Heartbeats come in through `src/jarvis/home/heartbeat.py`; with none for {{fact:settings.home_offline_after_s}} seconds, `src/jarvis/home/watchdog.py` marks the laptop offline and tells you once. `src/jarvis/home/tools.py` answers "is the house armed?" from the last heartbeat, lists the devices you exposed, and turns a request for a lock or plug that needs a passkey into a card with one. The Home panel, `src/jarvis/api/static/console-home-panel.js`, arms the alarm through `src/jarvis/api/camera.py`; disarming works only in the console, with your passkey or a fresh Google sign-in, and is audited first. `src/jarvis/brief/home_overnight.py` writes the brief's "Home overnight" line from fixed words and counts, never a name or a picture. `src/jarvis/api/home.py` serves the Link button and the home kit, a zip built by `src/jarvis/home/kit.py`. The Camera panel, `src/jarvis/api/static/console-camera-panel.js`, runs one engine in the browser, `src/jarvis/api/static/console-vision.js`, that reads text, codes and picture quality and finds objects and poses. Only `src/jarvis/api/static/console-camera.js` asks for the camera. Keep sends just the result to `POST /v1/vision/results`, sealed and kept {{fact:settings.vision_keep_days}} days (`src/jarvis/vision/store.py`). A picture reaches the server only through `src/jarvis/api/static/console-r7-send.js`, when you press Ask the AI, Add to my vault or Attach, redrawn first to drop camera and location data. The engine's files are served only when their SHA-256 matches the pinned list (`scripts/vision_assets.py`).

## What it costs
Nothing in software: the bridge, Home Assistant, Frigate and Mosquitto run on your own laptop, and the vision engine runs in your browser (`src/jarvis/home/kit.py`, `src/jarvis/api/static/console-vision.js`). Asking the AI about a photo is the one paid step, and only when you press it (`src/jarvis/api/static/console-r7-send.js`).

## When it fails
With the laptop off, home tools say so plainly, the watchdog tells you once, and you hear when it is back (`src/jarvis/home/watchdog.py`). An unsigned or replayed message is refused without a word (`src/jarvis/home/webhook.py`). An arm the laptop doesn't confirm in time sends one alert that it couldn't arm. If the disarm's audit entry can't be written, nothing is switched off (`src/jarvis/api/camera.py`). A vision result outside its task's shape is dropped, and the pose and object tasks say "not installed" until their model files arrive (`src/jarvis/api/vision.py`).
