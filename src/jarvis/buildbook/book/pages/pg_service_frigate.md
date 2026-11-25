---
page: pg_service_frigate
written_by: Workshop · Mark XXIV
written_on: 2026-11-24
sources:
  "src/jarvis/api/home_wiring.py": "47912d10ccd3e249"
  "src/jarvis/config.py": "e223e4b9e6e6333b"
---
## In plain words
Frigate is a free camera watcher that runs on your laptop at home. It watches your camera, spots people and parcels, keeps the recordings and the face library, all at home. JARVIS uses it for the burglar alarm (Away or Night), for questions like "who was at the gate yesterday?" and for parcel alerts at the door. The pictures stay on the laptop: the bridge passes on only short event facts, never thumbnails, and a small photo goes to your phone with a burglar alert only if you switch that on. Faces are recognised only for people added with their consent.

## Example (made up)
You arm the alarm as Away at 9:00 and leave. At 11:42 Frigate sees a person at the side door. The bridge checks the event at home and sends JARVIS one signed message; nobody enrolled is recognised, so your phone rings at once with an urgent alert. Back home you ask "who was at the door today?" and JARVIS lists two visits, from Frigate's event list on the laptop.

## How it works
`_wire_home` builds the camera part, with the alarm, the home feed, the history and parcel alerts, and gives its handler the camera events the bridge forwards (`src/jarvis/api/home_wiring.py`). Faces come in only with `faces_enabled` on; with them off nobody is named, and a face lookup that fails counts as "not recognised", so recognition never silences an armed alarm (`_wire_faces`). A photo goes with a burglar alert only when you have switched snapshots on, and if that setting can't be read, no photo is sent (`_Snapshots`). Disarming, and unlinking the laptop while armed, need the Disarm button's proof: your passkey, or a fresh Google sign-in while the passkey rules are not running (`_LivePermissions`). The cloud keeps the home alert feed for `home_feed_days` ({{fact:settings.home_feed_days}} days) and seals it with JARVIS's own key (`src/jarvis/api/home_wiring.py:home_privacy_sources`). If the laptop stops sending heartbeats for `home_offline_after_s` ({{fact:settings.home_offline_after_s}} seconds), the watchdog warns you, because camera alerts can't arrive then (`_laptop_online`). Without `home_enabled` on and the server's token key, the camera part is not built at all (`wire_home`).

## What it costs
Nothing in rupees: Frigate is free, open-source software, and the recordings stay on your laptop's disk. No cloud camera service or monthly fee is involved.

## When it fails
When Frigate stops answering, the bridge's heartbeat says so and the Vitals board names the part: the camera watcher (Frigate) is not answering, so burglar alerts stop arriving until you start the home kit again with its start script. An arm the laptop doesn't confirm in time sends one alert that JARVIS couldn't arm your home. With the laptop off, the watchdog tells you once (`src/jarvis/api/home_wiring.py:_laptop_online`).
