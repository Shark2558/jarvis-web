---
page: pg_module_people
written_by: Workshop · Mark XXIV
written_on: 2026-11-24
sources:
  "src/jarvis/api/faces.py": "8b85cb39cc0a41c4"
  "src/jarvis/api/static/console-faces.js": "05194ce7820b117e"
  "src/jarvis/api/static/console-people.js": "90b76851b4821be7"
  "src/jarvis/homebridge/faces.py": "f99eab9f65f75c44"
  "src/jarvis/people/offer.py": "adad51547ca21512"
  "src/jarvis/people/offer_card.py": "23b0076a0d96c6d9"
  "src/jarvis/picture/turnguard.py": "42e7fe96e76ba0ce"
---
## In plain words
This module handles two careful things about people. Faces is the list of people JARVIS may recognise at your door and greet or name in an alert; nobody is on it until you add them with a consent statement, and their face pictures stay on your home laptop while the cloud keeps only names, relation and consent records. People research gives you a short profile of a public figure, or of someone you are checking for work, from public sources only. In both, JARVIS never turns a face in a picture into a name.

## Example (made up)
Sunil adds his mother to Faces: relation family, and with her agreement he ticks the adult consent statement. On the home laptop's own Faces page he adds 6 photos of her under the code the panel shows. On Tuesday at 10:20 the doorbell camera sees her, the match scores 0.94, and his alert says she has arrived. That evening he sends JARVIS a photo of a conference poster and asks who the speaker is. JARVIS says it doesn't identify people from pictures, but the poster's caption names Prof. Vasanth Iyer, so a "Look up" card appears under the reply. Sunil presses it and the People panel shows a short public profile with links to the speaker's university page.

## How it works
The Faces panel, `src/jarvis/api/static/console-faces.js`, lists the people JARVIS may recognise from `GET /v1/faces`; this API never receives or returns a picture (`src/jarvis/api/faces.py`). Adding someone is `faces_add` with a `NewPerson`: a name, a relation, whether it is a child, and an explicit yes to the fixed consent statement from `_statements`, an adult's own or a parent's or guardian's. `faces_edit` changes the name, relation or VIP mark, or renews the consent (`EditPerson`). `faces_delete` asks for your passkey or a fresh Google sign-in through `_prove`, and only from the console in your browser. At home, `FaceLibrary` keeps the pictures in Frigate's own face library under a code, never a name; the cloud only tells the laptop which codes have consent. It refuses a picture for a code without consent, anything but a JPEG or PNG, and more than {{fact:src/jarvis/homebridge/faces.py:MAX_PER_PERSON}} pictures a person (`FaceRefused`). A recognition counts only for a consented person at a score of at least {{fact:src/jarvis/homebridge/faces.py:RECOGNITION_THRESHOLD}}; anyone else gives no match, so the cloud never hears a guess (`src/jarvis/homebridge/faces.py`). A delete removes the library entry and every saved crop, and reports done only when nothing of that person is left; `FacesPlugin` retries every {{fact:src/jarvis/homebridge/faces.py:RETRY_S}} seconds until then. `faces_local` gives the address of the laptop's own Faces page, where pictures are added and shown. People research is the panel in `src/jarvis/api/static/console-people.js`: a name and an optional role or organisation go in, and a short dossier from public sources comes back, or a plain refusal. Each profile is a card with its own link, and "Open next" opens one tab a press, never all at once (`src/jarvis/api/static/console-people.js`). On a chat turn whose message carried a picture, `TurnGuard` accepts a person's name only when you typed every word of it in that message (`check_name`). A name read from text printed in the picture becomes an `Offer`: `offered` shows a `PeopleOfferCard` with the caption line and one "Look up" button, and nothing is researched until you press it. Anything else is refused in fixed words, and a web search on that turn carries only your words, the picture's words and plain search words (`check_query`).

## What it costs
Faces costs nothing: matching runs in Frigate on your own laptop and the cloud keeps only a small record (`src/jarvis/homebridge/faces.py`). People research uses web-search credits from the search service's free allowance and, with AI on, small checks by the fast brain; the price of those depends on the brain you use.

## When it fails
With the laptop asleep, a delete waits and finishes after it is back, and the panel shows the person as "deleting" until then (`faces_delete`). If Frigate doesn't answer within {{fact:src/jarvis/homebridge/faces.py:FRIGATE_TIMEOUT_S}} seconds, the laptop page says "Frigate didn't answer. Check it is running." (`FaceRefused`). A server without the faces encryption key shows Faces as not available (`_need`), and more than {{fact:src/jarvis/api/faces.py:CHANGES_PER_MINUTE}} changes a minute get a short wait (`_limit`). When the "Look up" card can't be shown with a reply, JARVIS says so and asks you to type the name yourself (`offered`).
