---
page: pg_card_c08
written_by: Workshop · Mark XXIV
written_on: 2026-11-24
sources:
  "src/jarvis/api/faces.py": "8b85cb39cc0a41c4"
  "src/jarvis/api/static/console-faces.js": "05194ce7820b117e"
  "src/jarvis/faces/__init__.py": "8df2125446d1c154"
  "src/jarvis/faces/consent.py": "bd26b27351c13e37"
  "src/jarvis/faces/directory.py": "4394450a7a82a7c4"
  "src/jarvis/faces/greeting.py": "3be9a4370b9e1d42"
  "src/jarvis/faces/models.py": "6535b4b94a211a4a"
  "src/jarvis/faces/ports.py": "79d12b5cbbd94c42"
  "src/jarvis/faces/privacy.py": "4419ca000212f8a6"
  "src/jarvis/faces/service.py": "ff13899d9f805bc8"
  "src/jarvis/faces/store.py": "24d6c004acbcb15e"
  "src/jarvis/faces/tools.py": "1c3c3a3c63b343cd"
  "src/jarvis/homebridge/faces.py": "f99eab9f65f75c44"
---
## In plain words
Faces is the short list of people the camera at home may recognise and greet by name. Nobody is on it until you add them with a fixed consent statement, and a child needs a parent's or guardian's yes (`src/jarvis/faces/consent.py`). Face pictures and the matching itself stay on your laptop at home; the cloud keeps only names, relations and consent records, sealed with JARVIS's own encryption (`src/jarvis/faces/store.py`).

## Example (made up)
Your friend Meera agrees to be recognised, so you add her in Faces, tick the consent statement, and add five photos of her on the laptop's own page. At 18:42 the gate camera sees her, and your console's feed says "Meera arrived at the Gate, 18:42". She leaves and comes back at 19:05; no second greeting, since one per half hour is enough. A delivery rider at the gate is "someone JARVIS didn't recognise", never a guess. When Meera later asks to be removed, you delete her with your passkey, and her name stops being used at once.

## How it works
`FacesService` adds a person only with the consent check, starting as consented; enrolment happens at home, where the laptop reports picture counts that move a person to enrolled (`src/jarvis/faces/service.py`). The registry lives in `faces`, sealed with AES-256-GCM under the faces key, and never holds a picture (`src/jarvis/faces/store.py`). At home, `FaceLibrary` names each entry in the face library by a random id, never a name, and refuses a face whose id has no consent (`src/jarvis/homebridge/faces.py`). The cloud sends the laptop ids only, never names, and the laptop sends back counts only (`FacesPlugin`). `Directory` turns an id into a name only when the person is enrolled, not being deleted, has consent on record and the match scores at least {{fact:src/jarvis/faces/ports.py:RECOGNITION_THRESHOLD}}; anything else is unknown (`src/jarvis/faces/directory.py`). `GreetingLimiter` greets one person at most once in {{fact:src/jarvis/faces/greeting.py:GREETING_GAP_S}} seconds, and a greeting never replaces or lowers an alarm (`src/jarvis/faces/greeting.py`). Off the console, in Telegram, a notification or speech, a child is never named, and an adult only if you switched "Say names in alerts" on (`alert_words`). Consent older than a year brings a gentle question, without stopping anything (`renewal_due`). The brain's only tool lists who is on the registry; it can't add, enrol or delete anyone (`src/jarvis/faces/tools.py`). Deleting a person goes through `POST /v1/faces/{person_id}/delete`, which asks for your passkey or a fresh Google sign-in, from the console only (`src/jarvis/api/faces.py`).

## What it costs
Nothing: matching runs in Frigate on your own laptop, never in a cloud vision service, and the registry is one small record (`src/jarvis/homebridge/faces.py`).

## When it fails
A person not in the registry, a low score, a name typed straight into Frigate or a registry that can't be read all give "someone JARVIS didn't recognise", never a guess (`src/jarvis/faces/directory.py`). A deleted name stops resolving at once; if the laptop is asleep, the removal reaches it with its next heartbeat (`src/jarvis/faces/service.py`). The laptop reports a delete as done only when none of that person's pictures is left, and retries until then (`src/jarvis/homebridge/faces.py`). A registry that can't be decrypted is never overwritten (`FacesUnavailable`).
