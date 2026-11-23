---
page: pg_screen_camera
written_by: Workshop · Mark XXIV
written_on: 2026-11-24
sources:
  "src/jarvis/api/static/console-camera-panel.js": "8e142dadab602be2"
  "src/jarvis/api/static/console-camera.js": "c917b03cb1ff1deb"
  "src/jarvis/api/static/console.html": "9f4c0c68f45e46fe"
---
## In plain words
Camera lets JARVIS look through this device's camera, or at a photo you choose, and tell you what it sees: it reads text, reads a QR code or barcode, or checks the light and sharpness. The looking happens on the device itself; a picture leaves it only when you press a button that says so. Results you want to keep are saved as words and numbers, never the picture. This device's camera has its own off switch, and only a tap switches it back on. The home burglar camera is separate and lives in the Home panel (`src/jarvis/api/static/console-camera-panel.js`).

## Example (made up)
At the chemist you want the batch number off a medicine strip. You open Camera, choose "Read text" under "What to look for", and press Start the camera. The panel says "The camera is on. Nothing leaves this device while you look." You hold the strip up, JARVIS reads "Batch B2391, Exp 08/2027", and you press Keep; it says "Kept. You will find it in Results." On the way out you say "Jarvis, cameras off", and the camera stays off until you tap Allow again.

## How it works
The panel has tabs, among them Look, Results and Cameras (`src/jarvis/api/static/console-camera-panel.js`). In Look you pick what to look for, then press Choose a photo or Start the camera, and JARVIS looks on this device and says the result in plain words (`src/jarvis/api/static/console-camera-panel.js`). Only `src/jarvis/api/static/console-camera.js` ever asks the browser for the camera, and only inside a tap; while it is on, a "Camera on" chip with Stop stays on screen. The camera stops when the panel closes, the page is hidden, or nothing has used it for a while (`src/jarvis/api/static/console-camera.js`). Keep saves only the result, never the picture, and Results lists what you kept, each with Delete (`src/jarvis/api/static/console-camera-panel.js`). A picture leaves the device only through a button that says so: "Ask the AI about this photo", "Add to my vault" or "Attach to my message" (`src/jarvis/api/static/console-camera-panel.js`). The Ask button appears only when the brain answering sees pictures and No-AI is off (`src/jarvis/api/static/console-camera-panel.js`). In Cameras you switch this device's camera off or allow it, and pick the front or back camera; "Jarvis, cameras off" switches it off by voice too (`src/jarvis/api/static/console-camera.js`).

## What it costs
Looking costs nothing: it runs on your own device (`src/jarvis/api/static/console-camera-panel.js`). "Ask the AI about this photo" is a paid reply, and its button shows the rough price in rupees before you press it (`src/jarvis/api/static/console-camera-panel.js`).

## When it fails
If the browser blocks the camera, the panel says "The camera wasn't allowed" and how to allow it. If another app is using it, it says "The camera is busy in another app." With no camera at all, it says "No camera was found on this device." A file that is not a picture gets "That is not a picture. Choose a JPEG or PNG photo." If nothing is read, it says so, such as "No text found."
