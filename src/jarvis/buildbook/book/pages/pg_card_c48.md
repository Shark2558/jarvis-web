---
page: pg_card_c48
written_by: Workshop · Mark XXIV
written_on: 2026-11-24
sources:
  "src/jarvis/activity/__init__.py": "d5653e45f0b5162f"
  "src/jarvis/activity/models.py": "379bcfd100010a5e"
  "src/jarvis/activity/recorder.py": "3bfe29574968cc02"
  "src/jarvis/activity/service.py": "6f85e70d74f6988b"
  "src/jarvis/activity/store.py": "bd7ae9f1fed6160b"
  "src/jarvis/activity/words.py": "f89ec8a5d041f9c7"
  "src/jarvis/api/activity.py": "039fe358ea1af9ad"
  "src/jarvis/api/static/console-activity.js": "531a9ab9aa75238e"
---
## In plain words
Activity is a plain-words diary of what JARVIS did for you today and yesterday: "Looked at your calendar", "Saved a draft to your landlord", "Waiting for your OK: Delete an event". Each row says whether it was done, is waiting, was refused or failed, and where you asked from, the console, your voice or Telegram. Where Recently deleted really holds a copy, the row has an Undo button; anywhere else it says why there is none.

## Example (made up)
At lunch you open Activity. It reads: 9:05 "Looked at your calendar · 3 times" (voice); 9:06 "Add task: renew car insurance" (done); 11:40 "Delete the event Team lunch" (done, with Undo). The lunch is back on, so you press Undo; the row now reads "restored", and the event is back on your calendar.

## How it works
`ActivityRecorder` listens to the tool gateway and, after each call's audit entry, writes one row: the words, the outcome, the channel and, for an undoable delete, a link to its copy in Recently deleted (`src/jarvis/activity/recorder.py`).
`describe` writes the words: a change reads as its own approval-card line, a read as a fixed verb with no search words ("Searched your email"), and a tool's own fixed words win, so a note's text or a vault date never lands here (`src/jarvis/activity/words.py`).
`ActivityStore` keeps the rows per owner and per local day in `activity`, at most {{fact:src/jarvis/activity/store.py:MAX_PER_DAY}} a day, and the scheduler's tick sweeps old days away (`src/jarvis/activity/store.py`).
`ActivityService` builds the view: reads of one tool in one request become one row with a count, a waiting row is hidden once the call finished, and Undo shows only where Recently deleted holds the item (`src/jarvis/activity/service.py`).
Every row without Undo says why, such as "No longer in Recently deleted" or that its days in the bin are over (`undo_note`).
`GET /v1/activity` serves today or yesterday and says whether the audit trail checks out; the Undo button itself calls Recently deleted's own restore (`src/jarvis/api/activity.py`).
`src/jarvis/api/static/console-activity.js` draws the list as plain text.

## What it costs
Nothing: no rupees and no AI call. It keeps a few days of rows, each holding plain words and no message text (`activity`, `activity_days`).

## When it fails
If a row can't be written, the tool call itself still completes, and the audit trail stays the full record (`ActivityRecorder`). With no storage on the server, the panel says nothing is recorded here (`src/jarvis/api/activity.py`). An item no longer in Recently deleted shows no Undo and says so, instead of offering a button that would fail (`ActivityService`).
