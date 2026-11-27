---
page: pg_card_c39
written_by: Workshop · Mark XXV
written_on: 2026-11-27
sources:
  "deploy/home/README.txt": "ccd584edeaae8de0"
  "deploy/home/bridge-requirements.txt": "d3cc937b4d00f431"
  "deploy/home/bridge.Dockerfile": "069ad0453fef216c"
  "deploy/home/docker-compose.yml": "725207386158f89f"
  "deploy/home/frigate/README.txt": "fe9736516a619a9d"
  "deploy/home/frigate/config.yml": "1f68e068fe75298f"
  "deploy/home/homeassistant/configuration.yaml": "953add6ef76bbe0a"
  "deploy/home/models/.gitignore": "8d9a294fd35f1cee"
  "deploy/home/models/LICENSE-sface-Apache-2.0.txt": "cfc7749b96f63bd3"
  "deploy/home/models/LICENSE-yunet-MIT.txt": "c83b8120c50ccbd4"
  "deploy/home/models/MODELS.txt": "e21a3fc25d92d0b7"
  "deploy/home/mosquitto/acl": "39c602bca80a945f"
  "deploy/home/mosquitto/mosquitto.conf": "82979e5f4e46fbe0"
  "deploy/home/setup-windows.ps1": "fa2e742ac802bca3"
  "deploy/home/setup-wsl.sh": "63978a0f3d2aa59c"
  "deploy/home/start-home.ps1": "b7b542257f3142ce"
  "deploy/home/stop-home.ps1": "80a7e2e8e35e8e7f"
  "deploy/home/wslconfig.example": "ea540076246a7986"
  "src/jarvis/homebridge/__init__.py": "29a51394d2701ecf"
  "src/jarvis/homebridge/__main__.py": "92219666087fb984"
  "src/jarvis/homebridge/app.py": "48d9256170d79ab2"
  "src/jarvis/homebridge/arm.py": "5933796343a6086f"
  "src/jarvis/homebridge/auth.py": "ecdfd9a0f24456ab"
  "src/jarvis/homebridge/camera.py": "a72e388114843dc7"
  "src/jarvis/homebridge/cloud.py": "01e2ce596f173c01"
  "src/jarvis/homebridge/config.py": "f245a473eec10e08"
  "src/jarvis/homebridge/decoder.py": "cda8f3cd13aacc84"
  "src/jarvis/homebridge/detections.py": "3538da65b39ab9a3"
  "src/jarvis/homebridge/devices.py": "3d7760fac1bc28b2"
  "src/jarvis/homebridge/face_db.py": "543c9a151c7f23cb"
  "src/jarvis/homebridge/face_engine.py": "69e0f1992e047153"
  "src/jarvis/homebridge/face_folder.py": "11f319f3e3033134"
  "src/jarvis/homebridge/face_groups.py": "5902d7c92d9667e3"
  "src/jarvis/homebridge/face_index.py": "55bad938c50bcf32"
  "src/jarvis/homebridge/face_store.py": "f8fb5b0e9b069ec9"
  "src/jarvis/homebridge/face_types.py": "76ee8ec27074bd16"
  "src/jarvis/homebridge/faces.py": "f99eab9f65f75c44"
  "src/jarvis/homebridge/frigate.py": "e1936febcd13a1c7"
  "src/jarvis/homebridge/ha.py": "f48cc3dc0360614c"
  "src/jarvis/homebridge/heartbeat.py": "c27532d28254a9bb"
  "src/jarvis/homebridge/jpeg.py": "fc09ec2d9bba4bae"
  "src/jarvis/homebridge/local_page.py": "60fb8e8c185bd3b0"
  "src/jarvis/homebridge/mqtt.py": "4dd0da9d478150aa"
  "src/jarvis/homebridge/packages_log.py": "ac0de9d66a4b891b"
  "src/jarvis/homebridge/plugins.py": "17f93a9898b95a02"
  "src/jarvis/homebridge/registry.py": "c042dd57435a3c35"
  "src/jarvis/homebridge/retention.py": "6becb660967f4007"
  "src/jarvis/homebridge/snapshot.py": "b06800e3ca0fe965"
  "src/jarvis/homebridge/state.py": "390012b807f1fff3"
  "src/jarvis/homebridge/static/faces.css": "3121aa2d96336c65"
  "src/jarvis/homebridge/static/faces.html": "d4c0c6e890f25048"
  "src/jarvis/homebridge/static/faces.js": "576e95bf28e14d71"
---
## In plain words
The home bridge is the small JARVIS program on your home laptop, running in Docker beside Home Assistant (your devices), Frigate (your cameras) and Mosquitto (the cameras' messages) (`deploy/home/docker-compose.yml`). It is the only thing at home the internet can reach, and it answers only signed calls from your own JARVIS (`src/jarvis/homebridge/app.py`). It filters camera events at home, keeps faces and photos at home, and serves a private Faces page that opens only on the laptop itself (`src/jarvis/homebridge/local_page.py`).

## Example (made up)
At 02:14, with the alarm armed, a person walks into the driveway zone you drew. Frigate spots them, the bridge sees it is the first time this event entered an alarm zone, and sends one short detection to JARVIS; you opted in, so a 60 KB snapshot goes with it. A cat crossing the same zone a minute later sends nothing. During the day, with the alarm off, nothing about people leaves the laptop at all. On Sunday you drop holiday photos into your photos folder, and by evening the bridge has grouped three unknown faces for you to name or forget.

## How it works
`create_bridge` builds one web app that serves only the fixed bridge routes; a request's size and signature are checked before any handler runs, so a stranger reaches no plugin code and no Home Assistant call (`src/jarvis/homebridge/app.py`). `BridgeAuth` checks each signature with the keys made at linking (`src/jarvis/homebridge/auth.py`). `HeartbeatLoop` reports every {{fact:src/jarvis/homebridge/heartbeat.py:DEFAULT_INTERVAL_S}} seconds how Home Assistant, Frigate, the cameras and faces are doing, and the cloud's signed answer brings back its latest state (`src/jarvis/homebridge/heartbeat.py`). `Detections` lets an event leave home only while armed, for a known label, when it entered an alarm zone you drew, and only the first time (`src/jarvis/homebridge/detections.py`). `Snapshot` lets one small picture leave, only with your opt-in, cleaned of all metadata, at most {{fact:src/jarvis/homebridge/snapshot.py:MAX_LONG_SIDE}} pixels on its long side (`src/jarvis/homebridge/snapshot.py`). `DeviceBridge` checks every device action again against Home Assistant and the device's class (`src/jarvis/homebridge/devices.py`). `Retention` deletes face attempts of strangers after {{fact:src/jarvis/homebridge/retention.py:UNKNOWN_HOURS}} hours and others after {{fact:src/jarvis/homebridge/retention.py:KEPT_DAYS}} days (`src/jarvis/homebridge/retention.py`). `OpenCvEngine` finds faces in your photos with two pinned models, used only if their SHA-256 matches, and decodes each picture in a capped child process (`src/jarvis/homebridge/face_engine.py`). `FolderScanner` reads the photos folder you chose, mounted read-only, so nothing in it is ever changed (`src/jarvis/homebridge/face_folder.py`). Unknown faces seen in at least {{fact:src/jarvis/homebridge/face_types.py:MIN_GROUP_PICS}} pictures form a group, and unnamed groups go after {{fact:src/jarvis/homebridge/face_groups.py:DEFAULT_KEEP_DAYS}} days (`src/jarvis/homebridge/face_groups.py`). `deploy/home/setup-windows.ps1` installs it all, with every port bound to the laptop itself and only the bridge reachable through Tailscale Funnel. At sign-in `deploy/home/start-home.ps1` starts the kit, and the call desk as well when it is installed on the same laptop.

## What it costs
Nothing in software: every part is free and runs on your laptop (`deploy/home/docker-compose.yml`). The laptop's electricity is yours, and its amount is Unverified here.

## When it fails
If a container stops, the heartbeat reports it and the systems check shows it (`src/jarvis/homebridge/heartbeat.py`). The setup refuses the bridge's own Funnel port while it serves something else, so it never takes another part's door (`deploy/home/setup-windows.ps1`). An unsigned or malformed call gets a bare refusal before any handler runs (`src/jarvis/homebridge/app.py`). A snapshot that isn't a small clean JPEG is dropped, and the alert goes out without it (`src/jarvis/homebridge/snapshot.py`). A face model that is missing or not the pinned one is never loaded; the camera keeps working and photos wait (`EngineOff`). A photo that makes the reader fail is tried a few times, then marked unreadable, and never stops the scan (`src/jarvis/homebridge/face_folder.py`).
