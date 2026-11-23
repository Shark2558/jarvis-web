---
page: pg_card_c47
written_by: Workshop · Mark XXIV
written_on: 2026-11-24
sources:
  "src/jarvis/api/static/console-sw.js": "8998e220b800ebcc"
  "src/jarvis/webpush/__init__.py": "6a7d1f301950b48d"
  "src/jarvis/webpush/ece.py": "558c58d5e81093d4"
  "src/jarvis/webpush/endpoints.py": "f093e1a3089e1073"
  "src/jarvis/webpush/service.py": "04b4a4ec7539d603"
  "src/jarvis/webpush/store.py": "328fec2a3c105f94"
  "src/jarvis/webpush/vapid.py": "73bc1debde0e6e20"
---
## In plain words
Besides Telegram, JARVIS shows its alerts as ordinary browser notifications on the browsers you have allowed, on your laptop or your phone. Each message is locked so that only that browser reads it, carries nothing but JARVIS's fixed alert sentence and never a picture, and a tap opens the console on the panel the alert is about.

## Example (made up)
You allow notifications in Chrome on your phone and name it "Phone in the kitchen". At 4:20 pm a courier leaves a parcel at the gate; the phone shows "A package was left at Front gate, 16:20.", and a tap opens the Home panel. Months later you reset that phone. The next push comes back "410 Gone" from the push service, and JARVIS quietly takes that browser off your list.

## How it works
When you switch notifications on, the browser hands JARVIS a delivery address and two keys, and `PushService` checks them all before keeping anything: the secret must be {{fact:src/jarvis/webpush/ece.py:AUTH_BYTES}} bytes, the key a real point on the curve, and the name is cleaned to at most {{fact:src/jarvis/webpush/service.py:NAME_MAX}} characters (`clean_name`).
`check` treats the address as untrusted: https only, no bare IP address, a host on the list of the browsers' own push services, and every address it resolves to must be public (`src/jarvis/webpush/endpoints.py`).
Your list of browsers is stored encrypted under the `webpush` key, never in plain fields, and it has a fixed size; one browser too many is refused (`PushFull`).
To send, `payload_for` builds the whole message: the alert kind, the fixed text cut to {{fact:src/jarvis/webpush/service.py:MAX_TEXT_CHARS}} characters and the panel to open, at most {{fact:src/jarvis/webpush/service.py:MAX_PAYLOAD_BYTES}} bytes.
`encrypt` then locks it for each browser with that browser's own keys, the standard Web Push encryption (`src/jarvis/webpush/ece.py`). `VapidKey` signs each request so the push service knows it comes from JARVIS; its key is worked out from the keyring each time and never stored (`src/jarvis/webpush/vapid.py`).
`PushService` tries all your browsers at once, each with a {{fact:src/jarvis/webpush/service.py:TIMEOUT_S}}-second limit, and sends a silent alert with low urgency. An undelivered burglar alert expires after {{fact:src/jarvis/webpush/service.py:TTL_INTRUDER_S}} seconds, any other after {{fact:src/jarvis/webpush/service.py:TTL_DEFAULT_S}} seconds (`src/jarvis/webpush/service.py`).
In the browser, the service worker only shows the notification and handles the tap: it caches no pages, accepts only the console's own targets, and adds a Talk button that opens JARVIS with the microphone ready but off (`src/jarvis/api/static/console-sw.js`). Each send writes one `audit` line with the kind and counts, never the text.

## What it costs
Nothing: no rupees and no AI. Messages go straight to the browsers' own push services (`src/jarvis/webpush/endpoints.py`), and the only thing kept is your encrypted list of browsers (`webpush`).

## When it fails
A browser that has gone away (status 404 or 410) is taken off your list (`PushService`). Any other refusal or a timeout counts as "not delivered" for that browser only; your other browsers and Telegram are unaffected. If your list can't be read or unlocked, nothing is sent and the list is never overwritten (`PushUnavailable`). A bad subscription is refused with "That browser subscription isn't valid." (`BadSubscription`). If a message arrives garbled, the worker shows "JARVIS has something for you." instead (`src/jarvis/api/static/console-sw.js`).
