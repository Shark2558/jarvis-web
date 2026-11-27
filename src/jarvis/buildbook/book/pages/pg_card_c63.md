---
page: pg_card_c63
written_by: Workshop · Mark XXIV
written_on: 2026-11-24
sources:
  "evals/r7/vision.py": "6915895e39b87c6e"
  "scripts/vision_assets.py": "fb34eec7a323c768"
  "src/jarvis/api/console.py": "c31a243b1ec2b6f6"
  "src/jarvis/api/static/console-camera-panel.js": "8e142dadab602be2"
  "src/jarvis/api/static/console-camera.css": "30a4a654f42d34ed"
  "src/jarvis/api/static/console-camera.js": "c917b03cb1ff1deb"
  "src/jarvis/api/static/console-r7-send.js": "545d6c2abaf1e8c6"
  "src/jarvis/api/static/console-vision.js": "19bb229445ef34de"
  "src/jarvis/api/vision.py": "dd9f8fd3f32fbec2"
  "src/jarvis/vision/__init__.py": "275237f6b0c8e5a3"
  "src/jarvis/vision/assets.py": "f0807a871257eb2d"
  "src/jarvis/vision/part.py": "092b1fb37d1a192d"
  "src/jarvis/vision/privacy.py": "1fd90827889acb01"
  "src/jarvis/vision/results.py": "3a35718bf243ce23"
  "src/jarvis/vision/store.py": "fbe61ccef010668b"
  "src/jarvis/vision/tools.py": "704bb79eeafabe12"
---
## In plain words
The Camera panel lets JARVIS look at a photo or the live picture on your phone or laptop, right there on the device: read text, scan a QR code or barcode, check if a picture is sharp, and, once their files are installed, spot objects or a body's pose (`src/jarvis/api/static/console-vision.js`). The picture itself never leaves the device unless you press a button that sends it, and JARVIS never keeps a frame (`src/jarvis/api/static/console-camera.js`). Only the results you choose to keep, words and numbers, are stored, sealed (`src/jarvis/vision/store.py`).

## Example (made up)
At the chemist's you point your phone at a medicine strip and tap Look, then Text. The words "Paracetamol 500 mg, Exp 08/2027" appear in a second, read on the phone itself. You press Keep, and only that line is saved. At home you scan the QR code on a gas bill and keep its link. Later you ask JARVIS "what did my camera read this week?" and it lists both, marked as text other people wrote. You say "Jarvis, cameras off", and the phone's camera stays locked until you tap to allow it.

## How it works
`src/jarvis/api/static/console-camera.js` is the only file that asks for a camera: it starts only on your tap, never while the camera-off switch is on, and stops when the page is hidden or nothing used a frame for a while. `src/jarvis/api/static/console-vision.js` is the engine's one port: each task works on the frame and returns only plain results, and the parts built on it never see a picture. `src/jarvis/api/static/console-camera-panel.js` draws Look, Results and Cameras. The engine's files come from JARVIS itself through `console_vision`, which serves only what the release's manifest lists with a matching SHA-256, and `scripts/vision_assets.py` fetches and pins them (`src/jarvis/api/console.py`). `installed` reports pose and objects as "not installed" until their model files arrive, while text, code and quality work (`src/jarvis/vision/assets.py`). Keep sends only the result to `POST /v1/vision/results`, where `parse_result` checks it against its task's schema, numbers in range, labels from a fixed list and text of at most {{fact:src/jarvis/vision/results.py:TEXT_MAX}} characters, and drops anything else (`src/jarvis/vision/results.py`). `VisionStore` keeps results in `vision_results`, sealed with the vision key, at most {{fact:src/jarvis/vision/store.py:PER_DAY_MAX}} a day, for {{fact:settings.vision_keep_days}} days (`src/jarvis/vision/store.py`). The brain's one tool, `results_tool`, reads only kept results and fences any read text as outside content, so a later write in that round becomes a card (`src/jarvis/vision/tools.py`). A picture reaches the server only through `src/jarvis/api/static/console-r7-send.js`, when you press Ask the AI, Add to my vault or Attach; it is redrawn on the device first, so no camera or location data travels, and counted per day.

## What it costs
Nothing: every task runs in your browser, with no cloud vision service (`src/jarvis/api/static/console-vision.js`). Only "Ask the AI about this photo" costs a brain call, and it is offered only when the brain answering can see pictures (`src/jarvis/api/static/console-r7-send.js`).

## When it fails
A result outside its task's schema is dropped, and nothing is repaired (`parse_result`). A vision file whose bytes don't match its recorded sum is never served (`src/jarvis/api/console.py`). Without the token key nothing is kept, never in clear (`VisionOff`), and a day that can't be opened is never overwritten (`VisionUnavailable`). A picture the browser can't read is refused in plain words (`src/jarvis/api/static/console-r7-send.js`). The camera stops by itself when you leave the page (`src/jarvis/api/static/console-camera.js`).
