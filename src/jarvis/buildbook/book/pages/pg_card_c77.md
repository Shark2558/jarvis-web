---
page: pg_card_c77
written_by: Workshop · Mark XXV
written_on: 2026-11-27
sources:
  "deploy/calldesk/README.txt": "448576fb7359fcfd"
  "deploy/calldesk/install-calldesk.ps1": "741fdee2f685fc2c"
  "deploy/calldesk/requirements-calldesk.txt": "9b9300f3947589a0"
  "deploy/calldesk/restore-microphone.ps1": "408f2d95d3c53da1"
  "deploy/calldesk/start-calldesk.ps1": "8a1024447ab3babb"
  "deploy/calldesk/stop-calldesk.ps1": "52293f264cbf21dd"
  "src/jarvis/api/calldesk_kit.py": "ecfbe8177c5f2a46"
  "src/jarvis/calldesk/__init__.py": "778dd7bcc574a727"
  "src/jarvis/calldesk/__main__.py": "b52cff184c6aaccd"
  "src/jarvis/calldesk/app.py": "a52cc7b5c3f9d935"
  "src/jarvis/calldesk/audio.py": "44cb3d9825f2c75d"
  "src/jarvis/calldesk/checks.py": "ae85c53300d111ae"
  "src/jarvis/calldesk/client.py": "b5dc3c6ab0189ff7"
  "src/jarvis/calldesk/config.py": "913d060817b22605"
  "src/jarvis/calldesk/credentials.py": "5088a417ab3335a2"
  "src/jarvis/calldesk/dtmf.py": "4dae8072f9b5b6f3"
  "src/jarvis/calldesk/kit.py": "233669d5fe8b487c"
  "src/jarvis/calldesk/link.py": "218b9adbf4e6938e"
  "src/jarvis/calldesk/micguard.py": "74bfb76963d4ce5d"
  "src/jarvis/calldesk/ports.py": "7eb8a266c1d25838"
  "src/jarvis/calldesk/session.py": "02cebfe5ffe361d1"
  "src/jarvis/calldesk/sound.py": "d32b70a565c04a29"
  "src/jarvis/calldesk/speech_local.py": "712882fdfa568bac"
  "src/jarvis/calldesk/vad.py": "e8fe2ef1a59b4a3a"
  "src/jarvis/calldesk/watchdog.py": "1e3d0ee40fe11dc7"
  "src/jarvis/calldesk/win/__init__.py": "8bce92572755d61e"
  "src/jarvis/calldesk/win/coreaudio.py": "30eea5a70e7bd0a8"
  "src/jarvis/calldesk/win/policy.py": "437f17e3e78a6cb0"
  "src/jarvis/calldesk/win/sound.py": "e95e276a93673c3e"
  "src/jarvis/calldesk/win/system.py": "89c7222ce83d9dcf"
  "src/jarvis/calldesk/wsconn.py": "03de617fa79d0676"
  "src/jarvis/calls/hub.py": "eecd1fae04642ee0"
  "src/jarvis/home/signing.py": "4499c07dbb6aa847"
  "tests/test_calldesk_kit.py": "072d5198b720be91"
  "tests/test_calldesk_micguard.py": "affa38e4f83057ac"
  "tests/test_calldesk_session.py": "7ff50c044bcda227"
---
## In plain words
The call desk is a small program on your laptop that carries a call's sound between Windows Phone Link and JARVIS. When you approve a call, your phone dials from your own number and the call's sound comes to the laptop over Bluetooth, like a car kit. For that call only, the desk listens to what the laptop's speaker plays, sends it to JARVIS while the other person speaks, and plays JARVIS's voice into the call through VB-CABLE, a free virtual microphone (`deploy/calldesk/README.txt`). Your own microphone always comes back: at a takeover, at the end, after a crash and at the next start (`MicGuard`). It needs three things from you once: VB-CABLE installed, Phone Link set up for calls, and the desk's kit installed and linked.

## Example (made up)
Rohan installs VB-CABLE, extracts the kit and runs the installer. In Calls, Settings he presses "Link the call desk" and types the code K7M2-Q9XR into the installer, which ends with "ready for calls". Next morning he approves a call to his tailor. The desk makes CABLE Output the laptop's microphone, mutes notification sounds, and sends the tailor's words to JARVIS only while she speaks. When Rohan presses Take over, his own microphone is back at once and JARVIS goes quiet. After the call, everything is as it was.

## How it works
The kit is offered in Calls, Settings, "Download the call desk", only when JARVIS has an https public address, and it is a zip built from the repository when you ask, with its SHA-256 (`src/jarvis/api/calldesk_kit.py`, `CallDeskKit`). The installer sets the desk up in its own Python on your laptop, without administrator rights, and adds Start-menu shortcuts (`deploy/calldesk/install-calldesk.ps1`). Linking takes a code from "Link the call desk": {{fact:src/jarvis/calls/hub.py:CODE_LEN}} characters, good for {{fact:src/jarvis/calls/hub.py:CODE_TTL_S}} seconds and once (`DeskDoorService`). JARVIS answers it with the desk's id and a seed, kept in your own Windows profile folder on the laptop and sealed with the `calls` key in the cloud (`CredentialStore`, `DeskStore`). Every connection of the desk is signed the way the home bridge signs, with the clock within {{fact:src/jarvis/home/signing.py:MAX_SKEW_S}} seconds and a nonce not seen in the last {{fact:src/jarvis/home/signing.py:NONCE_TTL_S}} seconds (`src/jarvis/home/signing.py`). Before every call `Checker` proves the path: VB-CABLE is there, Phone Link is running, no Bluetooth headset is connected to the laptop (Phone Link refuses calls then), and the speaker recording and the cable move sound; its report names no device. Then `MicGuard` writes down your default microphones before changing anything, makes CABLE Output the default in all three roles, reads each switch back and undoes one Windows doesn't confirm. `VoiceDetector` sends the other person's sound only while they speak, judged frame by frame by loudness and zero crossings with no model, and keeps the moment before so the first syllable isn't lost. If they talk over JARVIS, playback stops at once (`DeskSession`). A phone menu's key is played into the call as its tone (`src/jarvis/calldesk/dtmf.py`). Laptop speech is a hook only, shipped off, so every call uses JARVIS's cloud speech (`src/jarvis/calldesk/speech_local.py`).

## What it costs
₹0. VB-CABLE is free, the desk needs no administrator rights (only VB-CABLE's own installer does, once) and downloads no voice models (`deploy/calldesk/README.txt`). The call itself runs on your own phone plan, and the desk talks to no outside service, only to JARVIS (`DeskClient`).

## When it fails
A check that fails puts its plain words on the call card, and nothing is dialled (`Checker`). If the desk can't write down your microphones first, it switches nothing; if that note can't be read later, any role left on the cable goes back to your best microphone (`MicGuard`). A link lost for more than {{fact:src/jarvis/calldesk/session.py:DISCONNECT_GRACE_S}} seconds during a call releases everything on the laptop (`DeskSession`). After {{fact:src/jarvis/calldesk/client.py:NOT_LINKED_AFTER}} refusals in a row the desk treats its link as gone, says so in its log and tries again every {{fact:src/jarvis/calldesk/client.py:NOT_LINKED_RETRY_S}} seconds (`DeskClient`). A crash is caught by the watchdog, which restores your microphone and sounds before restarting the desk (`Supervisor`). The Start menu's "Give me back my microphone" puts it back at any time (`deploy/calldesk/restore-microphone.ps1`).
