---
page: pg_card_c83
written_by: Workshop · Mark XXV
written_on: 2026-11-27
sources:
  "src/jarvis/api/speaker_assets.py": "0e7f9e6e41e69dc3"
  "src/jarvis/api/static/console-voiceprint-math.js": "83f681b57d604b50"
  "src/jarvis/api/static/console-voiceprint-panel.js": "60adde7bfeb9da33"
  "src/jarvis/api/static/console-voiceprint.js": "581978076fad5644"
  "src/jarvis/api/static/vendor/speaker/spk-1/MANIFEST.json": "5e308c06cd676057"
  "tests/test_r52_v5_console.py": "263303cdd8a3e50f"
  "tests/test_r52_v5_never_approves.py": "55843cf2b5201865"
  "tests/test_r52_v5_voiceprint_math.py": "ac10df050e9d96c8"
---
## In plain words
The speaker check lets a device tell your voice from others, so that only you can talk over JARVIS while he speaks, and a TV or another person can't cut him off (`src/jarvis/api/static/console-voiceprint.js`). Your voice print is made, kept and used in that browser alone, encrypted, and never leaves the device (`src/jarvis/api/static/console-voiceprint.js`). It never approves anything: not a tool call, a card, a passkey, an unlock or a Telegram approval (`tests/test_r52_v5_never_approves.py`). It isn't working yet: its model file has not been downloaded and pinned, so the console says "no model" and any voice can interrupt JARVIS, as before (`src/jarvis/api/static/vendor/speaker/spk-1/MANIFEST.json`). Once it is, each device needs a short reading from you to learn your voice (`src/jarvis/api/static/console-voiceprint-panel.js`).

## Example (made up)
Once the model is pinned, Zoya opens Voice, Speaker check on her phone and reads the short passage aloud for 1 minute. The panel says this device now knows her voice; it shows no score and no number. That evening JARVIS is reading her the news when her brother walks in and says "Jarvis, stop". The phone lowers JARVIS's voice for a moment, judges a 1.2-second clip on the device, finds it isn't her, and JARVIS carries on. When Zoya says "stop", he stops.

## How it works
A small speaker-embedding model runs in the browser on the vendored WebAssembly runtime, single-threaded (`src/jarvis/api/static/console-voiceprint.js`). The arithmetic follows WeSpeaker's filterbank, each band's mean removed; a print is the mean direction of several embeddings, and a clip is yours when its embedding is close enough to the print, by a threshold not yet calibrated (`src/jarvis/api/static/console-voiceprint-math.js`). Voice, Speaker check records your reading, or on the laptop uses the voice session's clips, keeping only their embeddings in memory until you choose; it switches the check on or off for this device and forgets the print after a confirm (`src/jarvis/api/static/console-voiceprint-panel.js`). It is for barge-in only: with a print active, a voice that opens the microphone's gate lowers JARVIS's volume and a short check clip is judged on the device first; another voice doesn't stop JARVIS (`src/jarvis/api/static/console-voiceprint.js`). A check that is too slow, no print, the switch off or any failure is a "skip", and barge-in works as before (`src/jarvis/api/static/console-voiceprint.js`). The print is encrypted with AES-GCM under a key this browser makes and cannot export, both kept in this site's own browser storage (`src/jarvis/api/static/console-voiceprint.js`). The model file comes from `GET /static/vendor/speaker/{release}/{name}`, served only when the release's manifest lists it with a matching SHA-256, with no sign-in, since it holds nothing of yours (`speaker_model`). The slot names WeSpeaker's VoxCeleb CAM++ model under a Creative Commons attribution licence, but no file could be taken from a primary source at the build, so the list is empty and every request is refused (`src/jarvis/api/static/vendor/speaker/spk-1/MANIFEST.json`). The tests prove that no decision about an approval takes the owner's voice as an input (`tests/test_r52_v5_never_approves.py`).

## What it costs
₹0: the check runs in your browser and the model file comes from JARVIS itself, so no outside service is involved (`src/jarvis/api/speaker_assets.py`).

## When it fails
No model, which is today: the console says "no model", the Record button is hidden and barge-in is unchanged (`src/jarvis/api/static/console-voiceprint-panel.js`). A browser that can't run it says "unsupported" (`src/jarvis/api/static/console-voiceprint.js`). Too little voice in the reading gives no print, or a weak one you can record again (`src/jarvis/api/static/console-voiceprint.js`). Until it works, someone must download the model, check its SHA-256 and pin it in the slot, as its manifest lists; the threshold then waits for the laptop eval (`src/jarvis/api/static/vendor/speaker/spk-1/MANIFEST.json`).
