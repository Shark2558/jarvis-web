---
page: pg_service_tailscale
written_by: Workshop · Mark XXV
written_on: 2026-11-27
sources:
  "src/jarvis/api/home_wiring.py": "47912d10ccd3e249"
  "src/jarvis/config.py": "965b3658da16361e"
  "src/jarvis/config_voice.py": "cc7af41e22be3757"
  "src/jarvis/voice/laptop.py": "c05c622c3b08fee0"
  "src/jarvis/voice/session_api.py": "e4f51093cb23971d"
---
## In plain words
Tailscale is a free service that gives your home laptop a safe public address without touching your home router. Its Funnel feature publishes one door of the laptop on the internet over HTTPS, and the encryption ends on the laptop itself, not at Tailscale. JARVIS uses up to three such doors: the home bridge (cameras, devices, faces) and, if you set them up, the offline brain (Ollama) and the laptop speech kit, whose Funnel port is its own, apart from the offline brain's. What passes through: JARVIS's signed calls to the bridge and the laptop's answers; in offline mode, your chat with the laptop's brain; with the kit, what you say to JARVIS for the laptop to hear, the voice session's recordings, and the words heard. Tailscale carries the traffic but sees only encrypted data.

## Example (made up)
You run the home kit's setup on a Saturday. It turns on Funnel and prints the laptop's new address, which you give JARVIS together with a one-time code. From then on, when you ask "is the porch light on?", JARVIS's server in the cloud calls that address, the call arrives encrypted at your laptop, and the bridge answers in about a second. A week later you start the speech kit too: it opens its own door on Funnel's port 10000, leaves the doors already open as they are, and prints the kit's address and key for JARVIS.

## How it works
JARVIS's home client calls the laptop's bridge at its Funnel address, and every call and answer is signed both ways with the link's key (`src/jarvis/api/home_wiring.py:_wire_home`). The bridge's heartbeat comes back the same way every `home_heartbeat_s` ({{fact:settings.home_heartbeat_s}} seconds), which also proves the Funnel door is open (`_wire_home`). With no heartbeat for `home_offline_after_s` ({{fact:settings.home_offline_after_s}} seconds), `_laptop_online` treats the laptop as offline, and the watchdog tells you (`src/jarvis/api/home_wiring.py`). The offline brain uses its own Funnel door; a call there may take up to `local_brain_timeout_s` ({{fact:settings.local_brain_timeout_s}} seconds) because the laptop is slow (`src/jarvis/config.py:Settings`). `_is_private_host` does not count a Tailscale name, one ending in ts.net, as a home-network name: seen from the cloud, such a name reaches Tailscale's public relays, so the spare brain slot needs an https address there and refuses plain http (`src/jarvis/config.py`). The speech kit's address, `local_speech_url`, must be a Tailscale https name on a Funnel port, with no IP address and no other path, or JARVIS refuses it at start-up (`src/jarvis/config_voice.py:kit_origin`). JARVIS uses the kit only with that address, its key `local_speech_key` and `local_speech_enabled` on; otherwise there is no kit, and your voice uses Google's speech, then the browser's (`src/jarvis/voice/laptop.py:laptop_voice`). `LaptopVoice` trusts the kit's health for `local_speech_health_s` ({{fact:settings.local_speech_health_s}} seconds), a turn waits at most {{fact:src/jarvis/voice/laptop.py:HEALTH_WAIT_S}} seconds for a check, and one listen may take up to `local_speech_timeout_s` ({{fact:settings.local_speech_timeout_s}} seconds) on the laptop (`src/jarvis/voice/laptop.py`). The voice session sends its recordings to the kit through the same door, and only while the kit is set up (`src/jarvis/voice/session_api.py:build_profile_api`). What the console shows about the kit never holds the laptop's Tailscale name or the key (`LaptopStatus`).

## What it costs
Nothing in rupees: JARVIS uses Tailscale's free personal plan. Unverified: the exact limits of that plan.

## When it fails
If Funnel is off or the laptop is asleep, the cloud gets no answer: the home tools say the laptop is offline and the watchdog tells you once, then again when it is back (`src/jarvis/api/home_wiring.py:_laptop_online`). In offline mode, the Test button says the laptop didn't answer and asks whether it is awake, with Tailscale Funnel on. A Funnel address that later points inside a network is refused. If the kit's door is closed or the laptop asleep, a failed call marks the kit down until its health period ends, and meanwhile your voice uses Google's speech, then the browser's, with no error shown (`LaptopVoice`).
