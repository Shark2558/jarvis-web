---
page: pg_service_mosquitto
written_by: Workshop · Mark XXIV
written_on: 2026-11-24
sources:
  "src/jarvis/api/home_wiring.py": "47912d10ccd3e249"
  "src/jarvis/config.py": "8c3c0b7f0890ff99"
---
## In plain words
Mosquitto is a small, free message post office that runs on your laptop at home. It carries the camera's news from Frigate, the camera watcher, to the JARVIS bridge on the same laptop: "a person at the gate", "a parcel appeared". It is the camera's messenger. It lives only inside the home kit's own private network on the laptop: nothing on the internet reaches it, and it refuses anyone without a name and password. Frigate may post camera news; the bridge may only read it. Nothing of yours leaves the laptop through Mosquitto.

## Example (made up)
At 14:05 the alarm is armed. Frigate sees a person at the gate and posts the news to Mosquitto. The bridge, listening, picks it up within a second, checks it at home and sends one signed message to JARVIS. Your phone rings with the alarm alert. Mosquitto itself kept nothing but the message queue on the laptop.

## How it works
The camera's events reach JARVIS through the bridge's signed messages to the home webhook, where `_wire_home` hands each kind to the camera's own handler (`src/jarvis/api/home_wiring.py`). The bridge's heartbeat every `home_heartbeat_s` ({{fact:settings.home_heartbeat_s}} seconds) reports whether its connection to Mosquitto is up, and JARVIS keeps that with the laptop's status (`_wire_home`). With no heartbeat at all for `home_offline_after_s` ({{fact:settings.home_offline_after_s}} seconds), the laptop counts as offline and the watchdog tells you (`_laptop_online`). An armed alarm's alert goes through the one alert policy, which rings an urgent alert even in quiet hours unless you switched it off (`wire_notify`). Without `home_enabled` on and the server's token key, none of the home parts is built (`src/jarvis/api/home_wiring.py:wire_home`).

## What it costs
Nothing in rupees: Mosquitto is free, open-source software that runs in the home kit on your laptop.

## When it fails
When the bridge loses Mosquitto, its heartbeat says so, and the Vitals board names the part: the camera's messenger (MQTT) is not connected, so burglar alerts stop arriving until it is back. The fix it gives is to start the home kit again with its start script on the laptop. The bridge keeps trying to reconnect, with a growing pause, in the meantime. With the whole laptop off, the home tools say so and the watchdog tells you once (`src/jarvis/api/home_wiring.py:_laptop_online`).
