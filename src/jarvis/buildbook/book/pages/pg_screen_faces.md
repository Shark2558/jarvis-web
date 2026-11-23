---
page: pg_screen_faces
written_by: Workshop · Mark XXIV
written_on: 2026-11-24
sources:
  "src/jarvis/api/faces.py": "8b85cb39cc0a41c4"
  "src/jarvis/api/static/console-faces.js": "05194ce7820b117e"
  "src/jarvis/api/static/console.html": "9f4c0c68f45e46fe"
---
## In plain words
Faces is the list of people your home camera may recognise by name, and only with their consent. Nobody is on it until you add them. Adding someone asks you to confirm a consent statement: their own agreement, or a parent's or guardian's for a child. Here you keep only names, how you know them and the consent record; the pictures are added on your home laptop and never leave it. Deleting someone removes them from the laptop too (`src/jarvis/api/static/console-faces.js`).

## Example (made up)
Your friend Kiran visits on Sundays and is happy to be greeted. You open Faces, press Add person, type "Kiran", choose friend, tick "VIP (their arrival is always worth a ring)", and tick "I confirm they agreed" under the consent statement. The panel says "Added. Now add their pictures on your home laptop." On the laptop page you add three photos. Next Sunday at 11:05 the feed in Home says Kiran arrived at the gate, and your phone rings with the alert.

## How it works
When the panel opens, it lists the people you added from `GET /v1/faces`, each with their relation, whether they are a VIP, when consent was given and how many pictures the laptop holds (`src/jarvis/api/static/console-faces.js`). Add person opens a form with the consent statement; it is saved through `POST /v1/faces` only with the statement confirmed, and a child needs a parent's or guardian's yes (`src/jarvis/api/faces.py:faces_add`). This route never receives or returns a picture: names, relation and consent records only (`src/jarvis/api/faces.py`). Under the list the panel gives the address of the laptop's own page for adding pictures, which works only on your home laptop and says whether it is online now (`GET /v1/faces/local`). Each row carries a laptop code, because the laptop is told an id, never the name (`src/jarvis/api/static/console-faces.js`). When consent is due for renewal, a "Yes, still OK" button confirms it again through `PATCH /v1/faces/{person_id}` (`src/jarvis/api/faces.py:faces_edit`). Delete asks first and then checks your passkey, or a recent Google sign-in, before `POST /v1/faces/{person_id}/delete` (`src/jarvis/api/faces.py:faces_delete`). If the laptop is asleep, the row says it is deleting on your laptop and the laptop finishes when it is back (`src/jarvis/api/static/console-faces.js`).

## What it costs
Faces costs nothing: matching runs on your own laptop, and the cloud keeps a few small records (`src/jarvis/api/faces.py`).

## When it fails
If the server has no Faces set up, the panel says "Not available on this server." A person added without a confirmed statement is refused, and so is a child without a guardian's yes. If the passkey check is cancelled or fails, nothing is deleted and the panel says the check didn't finish. Deleting works only from the console in your browser (`src/jarvis/api/faces.py:faces_delete`). Changes are limited to {{fact:src/jarvis/api/faces.py:CHANGES_PER_MINUTE}} a minute.
