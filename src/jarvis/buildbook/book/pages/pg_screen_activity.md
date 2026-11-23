---
page: pg_screen_activity
written_by: Workshop · Mark XXIV
written_on: 2026-11-24
sources:
  "src/jarvis/api/activity.py": "039fe358ea1af9ad"
  "src/jarvis/api/static/console-activity.js": "531a9ab9aa75238e"
  "src/jarvis/api/static/console.html": "9f4c0c68f45e46fe"
---
## In plain words
Activity is JARVIS's diary of what it did for you, in plain words. Each line says when, what, and how it ended: Done, Waiting for you, Blocked, Failed or Declined. Lines that came from Telegram or your voice carry a small tag. When JARVIS deleted something that is still in Recently deleted, the line has an Undo button. The badge in the title bar says whether the tamper-proof log still checks out (`src/jarvis/api/static/console-activity.js`).

## Example (made up)
On Tuesday evening you wonder whether JARVIS really moved the dentist booking. You open Activity and see, under Today: "09:12 · Voice · Done · Moved Dentist to Thursday 16:00" and "13:40 · Done · Deleted the note Old Wi-Fi password", with an Undo button beside the second. You press Undo, it reads "Undoing…" for a moment, and the line now says Restored. You tap Yesterday to check Monday too, and the badge at the top still reads "Log verified".

## How it works
When the panel opens, it asks `GET /v1/activity` for the day picked with the Today and Yesterday buttons (`src/jarvis/api/static/console-activity.js`). The route `src/jarvis/api/activity.py:activity` answers with your own lines only, each with its time, its words, its outcome and where it came from. It also says whether the audit chain verifies, checking the newest {{fact:src/jarvis/api/activity.py:AUDIT_WINDOW}} entries (`_verified`). The Undo button appears only while the deleted thing is still in Recently deleted, and pressing it restores it there (`src/jarvis/api/static/console-activity.js`); a line whose undo has lapsed shows the server's reason instead. "Show full log" opens the raw tool log beneath, the same list the header badge is checked against (`src/jarvis/api/static/console.html`). The list refreshes by itself after a reply that used tools (`src/jarvis/api/static/console-activity.js`).

## What it costs
Reading Activity costs no AI and no money: it reads JARVIS's own records (`src/jarvis/api/activity.py`). Each refresh is a few database reads inside the free daily allowance, so the panel reloads only when something in it may have changed (`src/jarvis/api/static/console-activity.js`).

## When it fails
If the list fails to load, the panel says "Couldn't load what JARVIS did." with a Retry button. On a server that keeps no activity, it says "JARVIS doesn't record its activity on this server. The full log is below." and shows the raw log. If an undo fails, the line says "Couldn't undo it. Try again in a moment." If the audit chain no longer checks out, the badge reads "Log tampered" instead of "Log verified". If the server is out of reach (`src/jarvis/api/static/console-activity.js`), it says "Can't reach JARVIS. Check your connection."
