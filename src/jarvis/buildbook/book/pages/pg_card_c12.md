---
page: pg_card_c12
written_by: Workshop · Mark XXIV
written_on: 2026-11-24
sources:
  "src/jarvis/api/deleted.py": "3c811fad450ffdf9"
  "src/jarvis/api/static/console-deleted.js": "e39bd9b80826f35f"
  "src/jarvis/tools/calendar_undo.py": "63f51a0c90832f7b"
  "src/jarvis/tools/tasks_undo.py": "88ba03f6eb1eba25"
  "src/jarvis/tools/undo_delete.py": "3b028e0aa145b1ce"
  "src/jarvis/undo/__init__.py": "46eca38bea973351"
  "src/jarvis/undo/models.py": "dd06284e59553752"
  "src/jarvis/undo/service.py": "0ece40e6327958b6"
  "src/jarvis/undo/store.py": "5fa71945b8ce016e"
  "src/jarvis/undo/tools.py": "5539430e590f183e"
---
## In plain words
Before JARVIS deletes one of your own calendar events, to-dos, notes, things or vault files, it keeps a copy for {{fact:src/jarvis/undo/models.py:RETENTION_DAYS}} days. If you change your mind, you bring it back from Recently deleted under Approvals, or just ask "bring back the dentist appointment". After that time the copy is cleared away. Because of this safety net, deleting your own things is undoable rather than a passkey-only step.

## Example (made up)
On Friday you tell JARVIS "delete Saturday's badminton". It keeps a copy, then removes the event from your calendar. On Saturday morning the game is back on, so you open Recently deleted and press Restore: the event returns as a new event, at the same time and with the same notes. Pressing Restore again just says "already restored".

## How it works
Before an undoable delete, `keep_copy` stores the item's snapshot in Recently deleted, with the conversation and request it came from, and if the copy can't be stored, nothing is deleted (`src/jarvis/tools/undo_delete.py`).
`delete_after_keep` then deletes; if Google's answer is lost, it reads the item again: gone means done, still there means not deleted, and if even that read fails the copy stays, since a spare copy is better than lost data.
`UndoBin` keeps each copy in `deleted_items` per owner, written create-only, with an expiry date (`src/jarvis/undo/service.py`).
A restore is first claimed in a transaction, so two clicks never make two copies, and the restorer for that kind rebuilds it: `CalendarRestorer` for events, `TaskRestorer` for to-dos with their subtasks, and vault documents, notes and things in place (`src/jarvis/undo/service.py`).
A restorer that finds the original still there makes nothing and says so (`StillThere`), and one that finds it removed for good drops the entry (`Gone`).
An event comes back without its guests, so restoring never sends anyone an invitation (`restore_body`).
Your list shows the newest {{fact:src/jarvis/undo/store.py:PANEL_LISTED}} items, and the brain's look-up sees the newest {{fact:src/jarvis/undo/store.py:MAX_LISTED}}, with titles fenced as outside text (`undo_tools`).
"Remove now" deletes a copy at once; for vault documents, notes and things that is final, so it needs your passkey when passkeys are on (`src/jarvis/api/deleted.py`).
The scheduler's tick sweeps away expired copies (`UndoBin`), and `src/jarvis/api/static/console-deleted.js` lists them from `GET /v1/deleted` and restores through `POST /v1/deleted/{undo_id}/restore`.

## What it costs
Nothing: no rupees and no AI. It keeps each copy for {{fact:src/jarvis/undo/models.py:RETENTION_DAYS}} days in `deleted_items`, then the tick removes it (`UndoBin`).

## When it fails
If the copy can't be stored, nothing is deleted (`SnapshotFailed`). A second restore says "already restored" instead of making two copies (`UndoBin`). An expired or unknown item gets a plain message, never an error page, and a restore that fails releases its claim so you can try again (`src/jarvis/undo/service.py`). With Google unlinked, events and to-dos can't be restored until you reconnect (`src/jarvis/api/deleted.py`).
