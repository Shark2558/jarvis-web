---
page: pg_card_c27
written_by: Workshop · Mark XXIV
written_on: 2026-11-24
sources:
  "src/jarvis/brief/deliveries.py": "efe59bc1f029c5aa"
  "src/jarvis/packages/__init__.py": "e3b0c44298fc1c14"
  "src/jarvis/packages/carriers.py": "f7a2932d3c2da87e"
  "src/jarvis/packages/parse.py": "563d439d09f141ab"
  "src/jarvis/packages/tools.py": "fced61d69225f979"
---
## In plain words
Ask "where are my parcels?" and JARVIS looks through your order and shipping e-mails from known shops and couriers, and tells you what is ordered, shipped, out for delivery or delivered, with the expected date when the mail gives one (`src/jarvis/packages/tools.py`). It works it out with plain rules, no AI and no paid service, and keeps nothing: every answer is read fresh from Gmail. Parcels on the way also appear in your morning brief (`DeliveriesBrief`).

## Example (made up)
Ritu ordered a kettle and a phone cover last week. At 08:15 she asks JARVIS where her parcels are. It finds four mails from the last 14 days: the kettle "Shipped" by a courier with tracking number EK123456789IN, expected Friday; the phone cover "Out for delivery" today. A fifth mail claiming to be from a shop failed Gmail's sender check, so it was ignored.

## How it works
`gmail_query` searches Gmail only for mail from known shop and courier domains, or with shipping words in the subject, over the last {{fact:src/jarvis/packages/tools.py:DEFAULT_DAYS}} days by default and never more than {{fact:src/jarvis/packages/tools.py:MAX_DAYS}}.
A sender counts as known only when Gmail's own check says the mail really came from that domain; a From line alone proves nothing (`authenticated`).
`parse_mail` reads each mail with fixed rules: the status from a ladder of words, ordered, shipped, out for delivery, delivered, plus cancelled, returned or refunded, read from the subject first and then the start of the body (`detect_status`).
`find_tracking_number` takes a number only right after a tracking word, only in the exact format of the courier the mail names, and India Post numbers only when their check digit is right, so phone numbers, OTPs and amounts are never taken (`src/jarvis/packages/carriers.py`).
`detect_expected` reads "arriving" or "delivery by" dates against the mail's own date, and `build_packages` groups the mails of one parcel so the newest status wins.
No tracking link from inside an e-mail is ever used (`link_for`).
The subject reaches the AI fenced as outside content and the tool never vouches for it; on voice or Telegram the subject is masked or left out (`src/jarvis/packages/tools.py`).
The brief shows at most {{fact:src/jarvis/brief/deliveries.py:MAX_SHOWN}} parcels, asking your "Search and read email" row first (`src/jarvis/brief/deliveries.py`).

## What it costs
Nothing. It is a few Gmail reads through your own Google link and plain rules on the text, with no AI call and no tracking service (`src/jarvis/packages/parse.py`).

## When it fails
The courier number formats were written from public knowledge and are Unverified against real mail, so a miss means no tracking number shown, never a wrong one (`src/jarvis/packages/carriers.py`). Mail from unknown or unproven senders is ignored (`authenticated`). With your mail row on Ask first or Never, the brief says the section is paused by your Permissions instead of reading (`src/jarvis/brief/deliveries.py`). One failure in the parcel section never stops the rest of the brief.
