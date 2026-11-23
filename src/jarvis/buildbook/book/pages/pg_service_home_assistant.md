---
page: pg_service_home_assistant
written_by: Workshop · Mark XXIV
written_on: 2026-11-24
sources:
  "src/jarvis/api/home_wiring.py": "47912d10ccd3e249"
  "src/jarvis/config.py": "0f90cbe2c5f58fde"
---
## In plain words
Home Assistant is a free program that runs on your laptop at home and talks to your smart devices: lights, plugs and sensors. JARVIS never reaches Home Assistant directly from the internet. It talks to a small bridge on your laptop, and the bridge talks to Home Assistant with its own non-admin user. You choose which devices JARVIS may see; only those, with their states, reach JARVIS, and JARVIS sends back commands such as "switch the hall light off". A smoke, gas, water-leak or similar sensor you chose rings an urgent alert. Home Assistant's own token stays on the laptop.

## Example (made up)
At 23:40 you ask from bed: "Is the kitchen plug still on?" JARVIS asks the laptop bridge, the bridge asks Home Assistant, and two seconds later JARVIS says it is on and offers a card to switch it off. You approve; the plug clicks off. At 3:12 a water sensor under the sink you exposed turns on, and your phone rings with "Water was detected at Kitchen sink. Check your home now."

## How it works
`wire_home` builds the home link, the device list, the camera and faces only when `home_enabled` is on and the server has its token key; without the key all of Home stays off rather than being stored in clear (`src/jarvis/api/home_wiring.py`). The laptop's signed messages arrive at one door, the home webhook, which takes at most `home_webhook_per_min` ({{fact:settings.home_webhook_per_min}}) a minute (`_wire_home`). The bridge sends a heartbeat every `home_heartbeat_s` ({{fact:settings.home_heartbeat_s}} seconds); it says which of the laptop's parts work, and JARVIS's answer carries back what the laptop needs to know, such as the alarm state (`_wire_home`). With no heartbeat for `home_offline_after_s` ({{fact:settings.home_offline_after_s}} seconds) the laptop counts as offline (`_laptop_online`). Then the watchdog tells you, by default `home_offline_alert` {{fact:settings.home_offline_alert}}, not only while the alarm is armed (`src/jarvis/config.py:Settings`). A hazard message from a sensor you exposed goes to its own handler and on to the alert policy, which rings a hazard even in quiet hours unless you switched that alert off (`wire_notify`). If a part fails to build at start-up, it is logged by name and Home stays off while the rest of JARVIS keeps working (`wire_home`). The Privacy panel lists the home records, with export and delete (`home_privacy_sources`).

## What it costs
Nothing in rupees: Home Assistant is free, open-source software and runs on your own laptop. The bridge's messages to JARVIS are small and fit in the free hosting allowance.

## When it fails
With the laptop off, the home tools say so, the watchdog tells you once, and a second alert says "Your home laptop is back online." when it returns. If Home Assistant itself stops answering, the bridge reports it in its heartbeat and device commands fail with a short code, never Home Assistant's own text. A sensor you did not expose is ignored, so nothing rings that you never chose. A server without its token key keeps Home off (`src/jarvis/api/home_wiring.py:wire_home`).
