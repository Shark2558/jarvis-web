---
page: pg_card_c26
written_by: Workshop · Mark XXIV
written_on: 2026-11-24
sources:
  "src/jarvis/api/family.py": "f4a89f9e2a51c31d"
  "src/jarvis/api/static/console-family.js": "c00e23354c19ae70"
  "src/jarvis/family/__init__.py": "e3b0c44298fc1c14"
  "src/jarvis/family/models.py": "de41bc0e4446ddd1"
  "src/jarvis/family/service.py": "679b358952d1e649"
  "src/jarvis/family/store.py": "5fb756277421ae80"
  "src/jarvis/family/tools.py": "6415f25133ea6cf6"
---
## In plain words
When family members share their Google calendars with you, JARVIS can read them for you: what each person has on today, and when everyone is free, so planning a dinner or a school pickup doesn't need a round of phone calls (`src/jarvis/family/service.py`). If a calendar is shared with you so that you may edit it, JARVIS can also add an event to it, but only after you approve a card, because the other person sees it at once (`src/jarvis/family/tools.py`). Their event titles are treated as other people's words, never as instructions.

## Example (made up)
Arjun's wife and teenage son share their calendars with him. He adds them in Integrations as "Priya" and "Kabir". On Thursday he asks "when are we all free on Saturday?" JARVIS reads the three calendars and answers "10:00 to 12:30 and after 17:00". He asks it to put "Lunch at Nani's, 13:00" on Priya's calendar; a card shows the exact event, he taps Approve, and it appears on her phone a moment later.

## How it works
You register a member in the console with your own label and the calendar's address through `POST /v1/family`; JARVIS first checks with Google that the calendar really is shared with you and notes your access level (`FamilyService`).
At most {{fact:src/jarvis/family/models.py:MAX_MEMBERS}} members are kept in `family_calendars`, and `FamilyStore` changes them in one transaction so two adds can't both take the last place.
`family_tools` gives the brain read tools for a member's events and for shared free slots under your family read row, and an add-event tool that is irreversible, so it always shows a card and never offers Allow.
The add-event tool only works where Google gave you writer or owner access, re-checked when the card runs, and it can never be approved from Telegram (`src/jarvis/family/tools.py`).
Titles, places and descriptions from these calendars reach the AI fenced as outside text, so an odd title can't trigger a write (`src/jarvis/family/service.py`).
A calendar shared only as free or busy gives busy blocks, with no titles to show (`FamilyService`).
Each change to the member list writes one audit entry with only a hash of the calendar address (`src/jarvis/api/family.py`).
The Integrations card that lists members is `src/jarvis/api/static/console-family.js`.

## What it costs
Nothing. Every read and write is an ordinary Google Calendar call through your own Google link, with no new permission asked of Google (`src/jarvis/family/service.py`).

## When it fails
A calendar not yet shared with you is refused with "Not shared with you yet" and how to ask for it (`POST /v1/family`). With Google disconnected the list says so and nothing is read (`FamilyService`). A full list or a duplicate is refused in plain words (`FamilyFull`). Google's own error text never reaches you; changes are limited to {{fact:src/jarvis/api/family.py:CHANGES_PER_MINUTE}} a minute (`src/jarvis/api/family.py`).
