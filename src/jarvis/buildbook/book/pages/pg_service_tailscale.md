---
page: pg_service_tailscale
written_by: Workshop · Mark XXIV
written_on: 2026-11-24
sources:
  "src/jarvis/api/home_wiring.py": "47912d10ccd3e249"
  "src/jarvis/config.py": "e223e4b9e6e6333b"
---
## In plain words
Tailscale is a free service that gives your home laptop a safe public address without touching your home router. Its Funnel feature publishes one door of the laptop on the internet over HTTPS, and the encryption ends on the laptop itself, not at Tailscale. JARVIS uses two such doors: the home bridge (cameras, devices, faces) and, if you set it up, the offline brain (Ollama). What passes through: JARVIS's signed calls to the bridge and the laptop's answers, and, in offline mode, your chat with the laptop's brain. Tailscale carries the traffic but sees only encrypted data.

## Example (made up)
You run the home kit's setup on a Saturday. It turns on Funnel and prints the laptop's new address, which you give JARVIS together with a one-time code. From then on, when you ask "is the porch light on?", JARVIS's server in the cloud calls that address, the call arrives encrypted at your laptop, and the bridge answers in about a second.

## How it works
JARVIS's home client calls the laptop's bridge at its Funnel address, and every call and answer is signed both ways with the link's key (`src/jarvis/api/home_wiring.py:_wire_home`). The bridge's heartbeat comes back the same way every `home_heartbeat_s` ({{fact:settings.home_heartbeat_s}} seconds), which also proves the Funnel door is open (`_wire_home`). With no heartbeat for `home_offline_after_s` ({{fact:settings.home_offline_after_s}} seconds), `_laptop_online` treats the laptop as offline, and the watchdog tells you (`src/jarvis/api/home_wiring.py`). The offline brain uses its own Funnel door; a call there may take up to `local_brain_timeout_s` ({{fact:settings.local_brain_timeout_s}} seconds) because the laptop is slow (`src/jarvis/config.py:Settings`). `_is_private_host` does not count a Tailscale name, one ending in ts.net, as a home-network name: seen from the cloud, such a name reaches Tailscale's public relays, so the spare brain slot needs an https address there and refuses plain http (`src/jarvis/config.py`).

## What it costs
Nothing in rupees: JARVIS uses Tailscale's free personal plan. Unverified: the exact limits of that plan.

## When it fails
If Funnel is off or the laptop is asleep, the cloud gets no answer: the home tools say the laptop is offline and the watchdog tells you once, then again when it is back (`src/jarvis/api/home_wiring.py:_laptop_online`). In offline mode, the Test button says the laptop didn't answer and asks whether it is awake, with Tailscale Funnel on. A Funnel address that later points inside a network is refused.
