---
page: pg_card_c40
written_by: Workshop · Mark XXIV
written_on: 2026-11-24
sources:
  "src/jarvis/api/camera.py": "b1dd8720f99237ef"
  "src/jarvis/api/static/console-home-panel.js": "bb7fd758c81f6d63"
  "src/jarvis/brief/home_overnight.py": "5f5e4b1de238e306"
  "src/jarvis/camera/__init__.py": "a284e744dc33eb6b"
  "src/jarvis/camera/alarm.py": "77977c4891eca939"
  "src/jarvis/camera/config.py": "b780bf443cdad19f"
  "src/jarvis/camera/events.py": "50f8de4ccf92f1e8"
  "src/jarvis/camera/feed.py": "f787dd6b5e21bc0b"
  "src/jarvis/camera/guard.py": "a96b3106ad2b4544"
  "src/jarvis/camera/history.py": "15858e153150b5d9"
  "src/jarvis/camera/models.py": "0389e539fb21d0a4"
  "src/jarvis/camera/packages.py": "c56466a7c2c3df72"
  "src/jarvis/camera/ports.py": "73426d36484fb18a"
  "src/jarvis/camera/privacy.py": "223520aec4e11948"
  "src/jarvis/camera/sealed.py": "696e24ccc4c36457"
  "src/jarvis/camera/service.py": "eeebe34a47871cd3"
  "src/jarvis/camera/state.py": "4d52b393ede8ed41"
  "src/jarvis/camera/tools.py": "20e2c528d34db3cf"
---
## In plain words
This is your home security in JARVIS: arm the burglar alarm, Away or Night, and get an urgent alert on your phone when someone walks into a zone you marked (`src/jarvis/camera/alarm.py`). Switching it off needs your passkey or a fresh sign-in, so a spoken word, a chat or a Telegram message never disarms it (`src/jarvis/camera/guard.py`). You can also ask who came to the gate and when, and get one note when a parcel arrives at the door (`src/jarvis/camera/history.py`).

## Example (made up)
At 23:05 you tap Arm, Night. The panel shows "Arming…" until the laptop confirms, then "Armed". At 02:14 a person enters the driveway zone, and within seconds your phone rings with an urgent alert and, as you opted in, a small snapshot. In the morning the brief's "Home overnight" says "1 burglar alert, 1 parcel". At 09:30 you disarm with your fingerprint passkey. Later you ask "who was at the gate yesterday?" and hear "Someone JARVIS didn't recognise at 16:20, and a person JARVIS recognised at 18:42".

## How it works
`Alarm` keeps the arm state in `home_arm` with no personal data, pushes each change to the laptop, and says "armed" only once the laptop confirms it (`src/jarvis/camera/alarm.py`). Disarming runs only with a pass from `DisarmGate`, a passkey check made for this very arm, or a Google sign-in a few minutes old when no passkeys are set up; `audited_disarm` writes the audit line first (`src/jarvis/camera/guard.py`). `CameraEvents` handles what the laptop sends: a detection while armed, in a zone, goes to one alert call before anything else, and one that arrives while disarmed is dropped (`src/jarvis/camera/events.py`). Recognising someone never softens an armed alert, a child is never named in one, and an adult only if you switched names in alerts on (`CameraEvents`). The home feed keeps {{fact:src/jarvis/camera/models.py:FEED_KEEP_DAYS}} days in `home_feed`, sealed with the feed key, holding ids and times only, with names looked up when you view it (`src/jarvis/camera/feed.py`). `History` asks the laptop's camera event list and rebuilds every word from your camera labels, fixed words and the consent registry, so nothing the camera software writes can reach the brain (`src/jarvis/camera/history.py`). `Packages` sends one alert when the doorstep goes from empty to a parcel, and treats another parcel signal within {{fact:src/jarvis/camera/packages.py:FLAP_WINDOW_S}} seconds as the same change (`src/jarvis/camera/packages.py`). `HomeOvernightBrief` adds what happened since {{fact:src/jarvis/brief/home_overnight.py:SINCE_HOUR}} o'clock last evening to your brief, in counts and times only (`src/jarvis/brief/home_overnight.py`). `src/jarvis/api/static/console-home-panel.js` draws the Home panel through `POST /v1/home/arm` and `POST /v1/home/disarm`.

## What it costs
Nothing: the camera software runs on your laptop, and the alarm, feed and history are JARVIS's own code with no AI call (`src/jarvis/camera/events.py`).

## When it fails
An arm the laptop doesn't confirm within {{fact:src/jarvis/camera/models.py:ARM_FAIL_AFTER_S}} seconds sends one alert that JARVIS couldn't arm your home (`ArmPendingJob`). If the audit is down, nothing is disarmed (`audited_disarm`). If the arm record can't be read when a detection arrives, the alert still goes out, since a missed burglar is worse than a false alarm (`src/jarvis/camera/events.py`). An alert no channel took makes the laptop send the event again (`AlertNotSent`). A face lookup that fails counts as "not recognised", never a guess (`src/jarvis/camera/ports.py`).
