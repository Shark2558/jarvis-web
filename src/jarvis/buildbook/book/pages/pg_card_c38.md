---
page: pg_card_c38
written_by: Workshop · Mark XXIV
written_on: 2026-11-24
sources:
  "src/jarvis/api/home.py": "cd0a9f3557a74808"
  "src/jarvis/api/home_wiring.py": "47912d10ccd3e249"
  "src/jarvis/api/static/console-home.js": "5694fc12065091f8"
  "src/jarvis/home/__init__.py": "7ffa5da7cc0a71d1"
  "src/jarvis/home/classes.py": "117b2f01b0f8f5b6"
  "src/jarvis/home/client.py": "3364bbf315a99086"
  "src/jarvis/home/devices.py": "bf96dfa5e5a51a8a"
  "src/jarvis/home/heartbeat.py": "028d88e299dd4f48"
  "src/jarvis/home/kit.py": "48aad7dfbf328ee8"
  "src/jarvis/home/link.py": "165c8f9201511281"
  "src/jarvis/home/models.py": "1ed38e8733e48134"
  "src/jarvis/home/parts.py": "b36a459efc6d3aa3"
  "src/jarvis/home/ports.py": "1f9d6ef581933a5d"
  "src/jarvis/home/privacy.py": "22b4bdd8c270d811"
  "src/jarvis/home/signing.py": "4499c07dbb6aa847"
  "src/jarvis/home/store.py": "df4eb9b455c772e0"
  "src/jarvis/home/tools.py": "cfbe1c5b4edaeda8"
  "src/jarvis/home/watchdog.py": "adb8fe67d29e2bc2"
  "src/jarvis/home/webhook.py": "2d41ed0e356a9910"
---
## In plain words
The home link is how the JARVIS server in the cloud and the small bridge on your home laptop learn to trust each other, and keep doing so. You link them once with a short one-time code; after that every message between them is signed, so nobody else can pretend to be either side (`src/jarvis/home/signing.py`). It also notices when the laptop stops answering and tells you, then tells you again when it is back (`src/jarvis/home/watchdog.py`).

## Example (made up)
On Sunday you press Link in Integrations and get the code K7QM-2RXD, valid for ten minutes. On the laptop the setup script asks for it, and a few seconds later the panel shows "Linked". You pick 6 devices to let JARVIS see, the hall light and the front gate among them. On Thursday at 23:10 the laptop goes to sleep while the alarm is armed; six minutes later your phone rings with "your home laptop stopped answering, camera alerts are off until it's back". When it wakes, a "back" note follows.

## How it works
`LinkService` makes a code of {{fact:src/jarvis/home/link.py:CODE_LEN}} characters that lasts {{fact:src/jarvis/home/link.py:CODE_TTL_S}} seconds, is used once, is stored only as a hash, and dies after {{fact:src/jarvis/home/store.py:MAX_CODE_TRIES}} wrong tries (`src/jarvis/home/link.py`). The bridge sends it to `POST /home/link` with its address; JARVIS checks the address, makes a home id and a secret seed, and saves the link only after a signed test call proves the laptop at that address is the one that asked. From the seed `derive_keys` makes two keys, one for each direction, so a captured message can't be bounced back (`src/jarvis/home/signing.py`). Every message carries a time, a fresh random number and a signature; it is refused if more than {{fact:src/jarvis/home/signing.py:MAX_SKEW_S}} seconds old, if its random number was seen in the last {{fact:src/jarvis/home/signing.py:NONCE_TTL_S}} seconds, or if the signature doesn't match (`verify`). `HomeClient` is the only way the cloud calls home: it re-checks the laptop's address on every call, calls only the bridge's fixed routes, waits at most {{fact:src/jarvis/home/client.py:TIMEOUT_S}} seconds and accepts only a reply signed for that very request (`src/jarvis/home/client.py`). `POST /home/webhook` takes the laptop's events and heartbeats with the same checks, each before anything is read, and claims each event once so a repeat does nothing (`src/jarvis/home/webhook.py`). `DeviceService` keeps the devices you chose, at most {{fact:src/jarvis/home/ports.py:MAX_EXPOSED}}, in `home_devices`, each in a class that sets its risk: lights are everyday, plugs ask for a passkey, and locks and gates always do (`src/jarvis/home/classes.py`). The link record in `home` is sealed with the home key (`src/jarvis/home/store.py`). `GET /v1/home/kit` gives you the home kit as a zip whose checksum is shown beside the button (`src/jarvis/home/kit.py`).

## What it costs
Nothing: the link, the signing and the watchdog are JARVIS's own code, and the tunnel and Home Assistant run on your own laptop (`src/jarvis/home/client.py`).

## When it fails
With no heartbeat for {{fact:settings.home_offline_after_s}} seconds, `Watchdog` marks the laptop offline and sends one alert per outage, urgent when the alarm is armed, then "back" when it returns (`src/jarvis/home/watchdog.py`). While it is offline, the home tools say so plainly and never guess (`src/jarvis/home/tools.py`). A replayed, late or unsigned message gets a bare refusal, logged by the check's name only (`src/jarvis/home/webhook.py`). A test call that fails while linking doesn't use up the code or count as a wrong try (`src/jarvis/home/link.py`). A link record that can't be read is never overwritten (`HomeStoreUnavailable`).
