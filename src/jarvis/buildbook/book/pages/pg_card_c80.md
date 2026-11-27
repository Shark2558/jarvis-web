---
page: pg_card_c80
written_by: Workshop · Mark XXV
written_on: 2026-11-27
sources:
  "src/jarvis/api/r52_wiring.py": "db7440401d1030dd"
  "src/jarvis/calldesk/config.py": "216730706a264a3f"
  "src/jarvis/config_voice.py": "cc7af41e22be3757"
  "src/jarvis/localspeech/client.py": "6e6755da76ff1a32"
  "src/jarvis/localspeech/desk.py": "2bd10408f3800e30"
  "src/jarvis/vitals/own.py": "9f8aef630fa0d168"
  "src/jarvis/vitals/words.py": "ea17cbb15bd165ae"
  "src/jarvis/voice/calls_bridge.py": "dee4357bb0a42ba0"
  "src/jarvis/voice/laptop.py": "c05c622c3b08fee0"
  "src/jarvis/voice/routing.py": "96b7f27c1fc3c066"
  "tests/test_r52_i1_join.py": "64548bd43cf6264c"
  "tests/test_r52_v2_calls_bridge.py": "98a03a9a0b8a779c"
  "tests/test_r52_v2_client.py": "5393c7ea06dbfe5f"
  "tests/test_r52_v2_desk.py": "e4cb8680b3b902cb"
  "tests/test_r52_v2_laptop.py": "9bc9b35a6d3f245a"
  "tests/test_r52_v2_service_routing.py": "d899e396ea1be836"
---
## In plain words
This part is how JARVIS uses the speech kit on your laptop. When you speak in the console, the laptop listens first while its kit is healthy, then Google, then the browser, each tried once, so a sleeping laptop never stops you being heard (`src/jarvis/voice/routing.py`). Nothing the laptop hears is metered, so it costs ₹0 and saves Google's free minutes (`src/jarvis/voice/laptop.py`). JARVIS still speaks with Google's voice, because this first kit has no voice of its own (`LaptopVoice`). Nothing changes until you give JARVIS the kit's address and key once, with the deploy script's local speech step (`local_speech_url`, `local_speech_key`). Calls gain a "laptop" option, but the call desk offers only languages the kit both hears and speaks, so with this kit every call still uses cloud speech (`src/jarvis/localspeech/desk.py`).

## Example (made up)
At 7:40 Anil asks JARVIS by voice for the day's plan while his laptop is asleep. JARVIS doesn't wait for it: the kit was found down a minute ago, so Google hears him and the reply comes as usual. At 9:15 the laptop is awake. Once the kit's health is 30 seconds old, JARVIS checks it again in the background, and from his next recording Whisper small on the laptop hears him. Vitals now shows "Laptop speech kit" as ready, heard by the laptop, at ₹0 a minute.

## How it works
The cloud reaches the kit only at your Tailscale https name: `local_speech_url` must have the offline brain's shape, with a Funnel port and no other path, or it is refused at start-up (`src/jarvis/config_voice.py`). Before the first call every address the name resolves to must be public, and every request is resolved again and connected to the address just checked, so the name can't be swapped underneath it (`cloud_kit`). Each request carries the key, `local_speech_key`, a secret of at least {{fact:src/jarvis/config_voice.py:KIT_KEY_MIN_CHARS}} characters; redirects are never followed, and the kit's answers become fixed words, never its own text (`src/jarvis/localspeech/client.py`). `LaptopVoice` trusts the kit's health for {{fact:settings.local_speech_health_s}} seconds: a kit found down is answered at once and checked again in the background, a healthy one is checked within {{fact:src/jarvis/voice/laptop.py:HEALTH_WAIT_S}} seconds, and a failure marks it down for the rest of that time. Your listening follows your voice profile's order: the session's best engine, then Google, then the browser, each once; before a session, the laptop's Whisper small goes first while the kit is healthy (`src/jarvis/voice/routing.py`). Your corrections from the session apply after listening, whichever engine heard you (`corrected`). For calls, `LaptopHearing` and `LaptopCallVoice` give the calls' speech its "laptop" option; the calls' own language check decides whether a call uses it, and any failure lets the next option try (`src/jarvis/voice/calls_bridge.py`). The call desk on the same laptop reaches the kit's gate on the laptop itself (`desk_speech`), and finds the kit's key in its environment or in its own private folder, where its installer copies it (`src/jarvis/calldesk/config.py`). One kit client serves the voice, the calls, the session and the wake word (`src/jarvis/api/r52_wiring.py`). Vitals shows a "Laptop speech kit" line only when the kit is set up, with which engine heard and spoke last (`src/jarvis/vitals/own.py`, `src/jarvis/vitals/words.py`).

## What it costs
₹0: the laptop is free and nothing it serves is gated or metered (`src/jarvis/voice/routing.py`). Every listen it serves is one Google doesn't, so Google's free minutes last longer, and Vitals' line says what the laptop costs a minute (`src/jarvis/vitals/words.py`). Calls price the laptop option at ₹0 too, so nothing is metered there (`src/jarvis/voice/calls_bridge.py`).

## When it fails
With no address, no key or `local_speech_enabled` off, there is no kit client and voice works as before (`laptop_voice`). An address that isn't a Tailscale Funnel https name is refused at start-up (`src/jarvis/config_voice.py`). The laptop off, asleep, slow, refusing the key or answering oddly: Google, then the browser, silently and with the usual messages, and the kit isn't asked again until its health period ends (`src/jarvis/voice/laptop.py`). A profile that can't be read in time gives the default order, remembered for a while, so a broken store never stops listening (`src/jarvis/voice/routing.py`). Vitals shows a kit that is slow, needs updating or isn't answering in amber with "Google's speech is used", and never sends an alert for it (`src/jarvis/vitals/own.py`). The call desk without the kit's key uses cloud speech only (`src/jarvis/calldesk/config.py`).
