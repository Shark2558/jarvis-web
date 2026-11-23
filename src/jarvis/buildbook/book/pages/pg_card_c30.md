---
page: pg_card_c30
written_by: Workshop · Mark XXIV
written_on: 2026-11-24
sources:
  "src/jarvis/tools/addresses.py": "7ebd4b775eca6e2a"
  "src/jarvis/tools/calendar_alerts.py": "9a4b67b7f2509a33"
  "src/jarvis/tools/google_calendar.py": "a296ba2d81650abd"
  "src/jarvis/tools/reminders.py": "71b05fbd96e5a679"
---
## In plain words
JARVIS reads your Google Calendar, finds free time, adds and changes events, and deletes them with an undo. A reminder ("remind me to call the plumber at five") is a small tagged event on your own calendar, and its pop-up appears on your phone through the Google Calendar app. Anything that would e-mail other people, such as inviting guests, always waits in the console for your approval and passkey.

## Example (made up)
At 8:15 am you say "remind me to pay the electricity bill at 6 pm every month". JARVIS shows a card for a monthly reminder at 18:00 with an end date; you approve and it lands on your calendar with a pop-up. At noon you ask "when am I free for an hour tomorrow afternoon?" and get three slots inside your working hours. Then you ask to invite a colleague to Friday's review. The colleague would get an e-mail invitation, so the card waits for your approval and passkey.

## How it works
`calendar_tools` offers list, free slots, create, update and delete, on your primary calendar only and always through the tool gateway (`src/jarvis/tools/google_calendar.py`).
A list returns at most {{fact:src/jarvis/tools/google_calendar.py:MAX_EVENTS}} events, and a query narrows it to the event you named, so a look-up before a change carries nobody else's event (`CalendarAPI`).
`compute_free_slots` finds gaps of the length you want inside your working hours, at most {{fact:src/jarvis/tools/google_calendar.py:MAX_SLOTS}} of them.
`parse_when` reads a time without a zone in your calendar's zone, and every time returned carries its offset.
An event with guests sends them invitations, so creating it is irreversible and needs your passkey, and so does changing an event other people are on (`CalendarAPI`).
Guest addresses must be plain e-mail addresses (`parse_address`), and a card shows a look-alike domain in both its forms so it never passes for the real one (`display_address`).
A delete first reads the event and keeps a copy in Recently deleted, so deleting your own event is undoable; an event with other people, a repeating one or one you don't organise needs your passkey instead (`src/jarvis/tools/google_calendar.py`).
`reminder_tools` adds, lists and changes reminders: each is a short event tagged as JARVIS's own, with an alarm clock in its title, that blocks no time (`src/jarvis/tools/reminders.py`).
`is_reminder` trusts only that private tag, never the title (`src/jarvis/tools/calendar_alerts.py`).
`popup_reminders` sets at most {{fact:src/jarvis/tools/calendar_alerts.py:MAX_ALERTS}} pop-ups per event, none more than {{fact:src/jarvis/tools/calendar_alerts.py:MAX_ALERT_MINUTES}} minutes ahead.
A repeating reminder always has an end date, and one whose pop-up time has already passed is refused (`ReminderAPI`).
Titles read from your calendar reach the brain fenced as outside text, never as instructions (`src/jarvis/tools/google_calendar.py`).

## What it costs
Nothing: no rupees and no AI of its own. It works through your own Google link (C29) and keeps no data of its own, because events live in your Google Calendar (`CalendarAPI`).

## When it fails
A Google error becomes a short plain message, never Google's own text (`CalendarAPI`). If the look-up before a change or delete fails, there is no card and no change (`src/jarvis/tools/google_calendar.py`). A delete that cannot keep its copy first does not delete. A reminder change aimed at an ordinary event is refused in plain words, and a date the calendar cannot hold is refused rather than crashing (`ReminderAPI`). With the Google link expired, the tools answer "Google needs reconnecting" (C29).
