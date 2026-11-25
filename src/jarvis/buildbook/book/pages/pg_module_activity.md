---
page: pg_module_activity
written_by: Workshop · Mark XXIV
written_on: 2026-11-24
sources:
  "src/jarvis/api/activity.py": "039fe358ea1af9ad"
  "src/jarvis/api/deleted.py": "3c811fad450ffdf9"
  "src/jarvis/api/static/console-activity.js": "531a9ab9aa75238e"
  "src/jarvis/api/static/console-deleted.js": "e39bd9b80826f35f"
  "src/jarvis/tools/calendar_undo.py": "63f51a0c90832f7b"
  "src/jarvis/tools/tasks_undo.py": "88ba03f6eb1eba25"
  "src/jarvis/tools/undo_delete.py": "3b028e0aa145b1ce"
---
## In plain words
Activity is JARVIS's diary of the day in plain words: what it did for you, what is waiting for your approval, what it blocked and what failed. Recently deleted is its safety net. Before JARVIS deletes one of your own calendar events, to-dos, notes, things, vault files or wardrobe pieces, it keeps a copy first, so a slip of the tongue is one Undo away. Together they mean nothing JARVIS does happens out of sight, and most deletes are not final.

## Example (made up)
At 7:40 one morning Arjun tells JARVIS by voice: "Delete the dentist appointment on Friday." Only Arjun is on that event and he made it, so JARVIS deletes it straight away and keeps a copy. At lunch he opens Activity and sees the row "Deleted the event Dentist, Friday 4:30 pm" with an Undo button beside it. He remembers the dentist moved, not cancelled, so he taps Undo. The event is back on Friday at 4:30 with its reminder, and a new row reads "You restored the event Dentist".

## How it works
The panel's script, `src/jarvis/api/static/console-activity.js`, asks `GET /v1/activity` for today or yesterday and shows each row with its outcome and where it came from: the console, voice or Telegram. `activity` answers only the signed-in owner, and when this server keeps no activity or its store fails it returns an empty list marked "not available" instead of an error. `_verified` reads the last {{fact:src/jarvis/api/activity.py:AUDIT_WINDOW}} entries of the `audit` chain and tells the panel whether they still check out, which it shows as "Log verified". An undoable delete starts in `delete_kept`, and `delete_risk` decides first whether it really is undoable (`src/jarvis/tools/calendar_undo.py`). An event only you are on, that you organise, of the ordinary kind and not repeating qualifies; any other event needs an approval card, because Google e-mails its guests (`delete_risk`). A to-do of your own qualifies too; one assigned from a Google Doc or Chat space doesn't (`src/jarvis/tools/tasks_undo.py`). `keep_copy` stores the copy with the conversation and request it came from, and when no copy is stored nothing is deleted. `delete_after_keep` then deletes; if Google's answer is lost it reads the item again, keeps the copy when the item is gone or the check fails, and drops it when the item is still there. `event_snapshot` keeps an event's title, times, place, reminders and at most {{fact:src/jarvis/tools/calendar_undo.py:MAX_ATTACHMENTS}} attached files, never the guests. `task_snapshot` keeps a to-do's title, notes, due date, list, parent and the neighbour above it, and `descendants` adds every subtask. Undo calls `POST /v1/deleted/{undo_id}/restore`, and `restore` writes an audit line and a "You restored" row in Activity. `CalendarRestorer` first checks the original is really gone, then inserts with an id from `restore_event_id`, so a retried restore finds the first copy rather than making two. "Remove now" (`DELETE /v1/deleted/{undo_id}`) drops a copy at once; for a vault file, note, thing or wardrobe piece `_for_good` asks for your passkey or a fresh Google sign-in first.

## What it costs
Nothing in rupees: both lists live in JARVIS's own document store, and a restore is one ordinary call to your Google Calendar or Google Tasks (`src/jarvis/tools/calendar_undo.py`, `src/jarvis/tools/tasks_undo.py`).

## When it fails
If the copy can't be stored, nothing is deleted (`keep_copy`). An Undo pressed twice says "already restored", and a restore retried after a lost answer finds the event it made before instead of making a second one (`restore_event_id`). An item that was never really deleted is refused with status 409, "still there"; an expired copy answers status 410 (`src/jarvis/api/deleted.py`). When Google isn't linked the restore says so in plain words, and any other failure reads "Couldn't restore it just now. Try again in a moment." (`_restore`). A Meet link comes back as a new link, and the note under the row says so (`restore_note`). If Activity's own store is down, the panel says JARVIS isn't recording here and the full log below still shows (`src/jarvis/api/static/console-activity.js`).
