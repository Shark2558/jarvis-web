---
page: pg_screen_brief
written_by: Workshop · Mark XXIV
written_on: 2026-11-24
sources:
  "src/jarvis/api/brief.py": "384e3c31e281a98b"
  "src/jarvis/api/static/console-brief-sections.js": "e11e4eafe28cf198"
  "src/jarvis/api/static/console-brief.js": "11856702dcd2439c"
  "src/jarvis/api/static/console.html": "9f4c0c68f45e46fe"
---
## In plain words
Brief is your morning page: one look at today before the day starts. It lists today's calendar with its clashes and free gaps, the first thing tomorrow, your unread mail, to-dos due, parcels on the way, the family calendars and how many approvals are waiting. JARVIS makes it at the time you choose, and the Brief button shows a dot until you have looked at it. The facts are written by code, not by an AI; the short AI summary is a separate switch that stays off until you confirm it (`src/jarvis/api/static/console-brief.js`).

## Example (made up)
At 7:00 the brief is ready and the Brief button shows a dot. You open it at 7:20 and read: "Today · 4 events · 1 clash". The 11:00 review clashes with a call at 11:30, and the free chips show 9:00–10:30 and 14:00–16:00. The inbox section says 12 unread, with three from people. Deliveries shows a pair of shoes "Out for delivery". At the bottom, JARVIS says "1 approval waiting for you" with an Open Approvals button. Later a meeting moves, so you tap the round arrow at the top to make the brief again; the top line now reads "2 refreshes left today".

## How it works
When the panel opens, the console asks `GET /v1/brief/today` for today's brief and its settings (`src/jarvis/api/static/console-brief.js`). If the brief is on and none is made yet, opening the panel makes one through `POST /v1/brief/generate` (`src/jarvis/api/brief.py:generate`). The "Make it now" button sends the same request, and the round arrow in the title bar sends it with "force" to make today's brief again (`POST /v1/brief/generate`). While the server is still preparing it, the panel shows "Preparing your brief…" and checks again every few seconds (`src/jarvis/api/static/console-brief.js`). Once you have looked at a ready brief, `POST /v1/brief/seen` records it, and the dot on the Brief button goes (`src/jarvis/api/brief.py:seen`). The Deliveries, Family today, Documents, Home overnight and Inbox by kind sections are drawn by `src/jarvis/api/static/console-brief-sections.js`. The Settings section saves through `PUT /v1/brief/settings`: Morning brief on or off, the time, AI summary, Put it in my Gmail inbox, Deliveries and Family today (`src/jarvis/api/brief.py:put_settings`). Switching on the AI summary or the inbox copy opens a window that says what will happen, and nothing changes until you press its own button (`src/jarvis/api/static/console.html`). On the morning schedule, Cloud Scheduler calls `POST /internal/brief/tick`, which makes the brief when it is due (`src/jarvis/api/brief.py:tick`).

## What it costs
The brief is written from your calendar, mail and lists by code, so it costs nothing in AI (`src/jarvis/api/static/console-brief.js`). The AI summary is the one part that uses the paid Claude brain; the confirm window says "Uses Claude; never the free brain", and it stays off until you press Switch on (`PUT /v1/brief/settings`). Putting the brief in your own Gmail inbox costs nothing.

## When it fails
If making the brief fails, the panel says "Today's brief didn't finish." with the reason and a Try again button. If Google isn't linked, a section says "Connect Google to see your calendar here." with an Open Integrations button. If your Permissions don't allow reading mail, the inbox section says it is paused by your choice. Past today's refresh limit, the panel gives the server's reason, or "Brief limit reached for today." If the server is out of reach, it says "Couldn't check today's brief." with a Retry button.
