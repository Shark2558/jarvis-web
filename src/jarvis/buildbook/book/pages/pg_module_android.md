---
page: pg_module_android
written_by: Workshop · Mark XXIV
written_on: 2026-11-24
sources:
  ".github/workflows/android.yml": "3a93b9484acbf38a"
  "docs/plans/r7-integration/phone-contract.md": "08cd487a0078ba59"
  "evals/r7/body.py": "b65be7b48b9d80ec"
  "evals/r7/contract.py": "e81b73234d12198d"
  "evals/r7/needles.py": "c4a71d20be0d05a4"
  "evals/r7/phone.py": "cd674bc43b02c44d"
  "evals/r7/shell.py": "be19b9a909195d13"
  "scripts/apk_check.py": "03907e0b64dbb950"
  "scripts/app_icons.py": "66cf88ac19f8dfd8"
  "src/jarvis/api/app_shell.py": "055e85c13c45108e"
  "src/jarvis/api/mobile_status.py": "9e940d6b6f4a7153"
  "src/jarvis/api/phone.py": "3d46a2c2ed03ba6a"
  "src/jarvis/api/r7_wiring.py": "6550ccbb04997884"
  "src/jarvis/api/sos.py": "87a35824ff599c02"
  "src/jarvis/api/static/app-share-sw.js": "43e5b0c467b1cfde"
  "src/jarvis/api/static/console-brief-sections.js": "e11e4eafe28cf198"
  "src/jarvis/api/static/console-helpers-watch.js": "66676faabf8cfcc9"
  "src/jarvis/api/static/console-r7-links.js": "1be5e6c95f2f85c3"
  "src/jarvis/api/static/console-r7-lock.js": "054a4c0131ee84cf"
  "src/jarvis/api/static/console-r7-phone.css": "e27eb2c98c16b43c"
  "src/jarvis/api/static/console-r7-phone.js": "39e038d8237ad7b4"
  "src/jarvis/api/static/console-r7-share.css": "5b933aaf0b8d7034"
  "src/jarvis/api/static/console-r7-share.js": "ab846cef6ffe4167"
  "src/jarvis/api/static/console-r7-sos.css": "b1ea79b88f9b7814"
  "src/jarvis/api/static/console-r7-sos.js": "8abd07b320b0f28a"
  "src/jarvis/api/static/console-r7.js": "696313364fb2e895"
  "src/jarvis/api/static/console-sw.js": "8998e220b800ebcc"
  "src/jarvis/api/watch.py": "a632cfa03931c5d3"
  "src/jarvis/brief/models.py": "18f095d54c93f9da"
  "src/jarvis/brief/service.py": "8ff72b107aa66083"
  "src/jarvis/mobile/contract.py": "4ceca1395460fc25"
  "src/jarvis/mobile/ports.py": "a1518ba7f9584d94"
  "src/jarvis/phone/applock.py": "7e71acd21cdef363"
  "src/jarvis/phone/door.py": "ab8b59add7d96386"
  "src/jarvis/phone/handlers.py": "fd6c504bae8191d1"
  "src/jarvis/phone/part.py": "40b3578d797071f7"
  "src/jarvis/phone/privacy.py": "d01b0b502884a563"
  "src/jarvis/phone/service.py": "df810d687109baa0"
  "src/jarvis/phone/store.py": "855ca94f94e9df14"
  "src/jarvis/sos/contacts_hook.py": "3ec147f791dcaead"
  "src/jarvis/sos/hook.py": "a89c4eb4e96ae8c3"
  "src/jarvis/sos/message.py": "146dbeb753c3cf41"
  "src/jarvis/sos/models.py": "fbe2d31d41c2c6e5"
  "src/jarvis/sos/service.py": "95cb8a85cac86cfe"
  "src/jarvis/sos/store.py": "46305eb20c60b793"
  "src/jarvis/sos/tools.py": "fac564bd827fa5c3"
  "src/jarvis/telegram/client.py": "c5efc78af12cb8f9"
  "src/jarvis/telegram/service.py": "abea8743a90bb292"
  "src/jarvis/watch/brief.py": "d0eac5afb394b730"
  "src/jarvis/watch/door.py": "8401690cf589e080"
  "src/jarvis/watch/jobs.py": "ed30d25007a42368"
  "src/jarvis/watch/models.py": "7f7b06101f7df8c5"
  "src/jarvis/watch/part.py": "ec70b306786dfc9a"
  "src/jarvis/watch/phrases.py": "f9011febcff9dd71"
  "src/jarvis/watch/privacy.py": "b9db7a9578f53582"
  "src/jarvis/watch/service.py": "4b55ffd580ad843e"
  "src/jarvis/watch/sleep.py": "5a65de6a5f4a2658"
  "src/jarvis/watch/store.py": "a1f17396425c6739"
  "src/jarvis/watch/tools.py": "6663e17be1faa847"
  "src/jarvis/watch/words.py": "add145980ba0b8fc"
  "src/jarvis/webpush/service.py": "04b4a4ec7539d603"
  "tests/fixtures/r7/phone_vectors.json": "8609e0c92f7c1280"
---
## In plain words
This module puts JARVIS on your Android phone. The app is the console itself, drawn full screen by Chrome without the address bar, plus a few phone parts: a "Talk to JARVIS" tile, shortcuts, alerts sorted into Urgent, Alerts and Nudges, and JARVIS in the share sheet. It reads your steps, heart rate and sleep from Health Connect, so the brief says how you slept. And it carries an emergency SOS: hold a button, and a fixed message with your location goes to your emergency contacts on Telegram, with your SMS app and the dialler ready too. A passkey lock keeps the app closed when you've been away.

## Example (made up)
Anand links his phone on a Saturday: the laptop shows an 8-character code, he types it in the app, and the phone keeps its own key in its secure chip. On Monday his brief reads "Sleep: 6 h 50 min, 23:40 to 06:30 · from your watch". On Thursday evening his scooter skids in the rain. He taps the SOS tile; after a 10-second countdown his 2 contacts get a Telegram message with a map pin, his SMS app opens filled in, and the console tells him how many it reached.

## How it works
A phone is linked once by `phone_link` with a short code from `link_code`, made on the laptop after your passkey or a fresh sign-in; the phone's key never leaves its secure hardware. Afterwards the phone reaches JARVIS only through `phone_door`, a handful of signed routes that never read a conversation, the vault or mail, approve anything or call a tool (`src/jarvis/phone/handlers.py`). `DoorGate` checks each request in order before reading its body: the route, one header, a flood limit, a linked phone, the time, then the signature and a per-phone rate. A replayed request is refused by `NonceStore`. `AppLock` asks for your passkey after {{fact:settings.app_lock_minutes}} minutes away, only in the installed app, and only once a passkey was added from it. The share sheet hands a photo, PDF or text to the console's share tray, where you choose what happens to it (`src/jarvis/api/static/console-r7-share.js`). Health Connect data arrives as one daily summary through `src/jarvis/watch/door.py`; `src/jarvis/watch/service.py` checks the whole body, keeps it sealed, and words last night's sleep from fixed sentences, so "how did I sleep?" works with the AI off. A night you type yourself, when there is no watch, goes through `watch_sleep`. SOS is never a tool: only your held button and its countdown, or the phone's signed door, reach `sos_send` (`src/jarvis/sos/service.py`). It sends to up to {{fact:settings.sos_max_contacts}} joined contacts, each once, with a message written by code (`src/jarvis/sos/message.py`). A real SOS has its own budget of {{fact:settings.sos_per_hour}} an hour, apart from tests, so tests never block it. The brain's one SOS tool only reads how it is set up (`src/jarvis/sos/tools.py`).

## What it costs
Nothing in JARVIS: the app is built by free CI for a public repository, the phone door and the watch data are plain code, and SOS goes through Telegram's free bot service (`src/jarvis/sos/service.py`). An SOS text message costs your mobile plan's usual charge, and only if you press Send. A question about your sleep is an ordinary reply.

## When it fails
Every failed check at the phone's door gets a bare refusal, logged by the check's name only, so a flood never fills the audit trail (`DoorGate`). If the SOS limits can't be read, a real SOS still goes; a refused or failed send still opens the SMS screen and the emergency number (`src/jarvis/sos/service.py`). Without Health Connect or its permission, the Watch tab says so and a typed sleep time still works (`src/jarvis/watch/service.py`). An app-lock check that fails stays locked (`AppLock`).
