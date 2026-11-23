---
page: pg_module_memory
written_by: Workshop · Mark XXIV
written_on: 2026-11-24
sources:
  "src/jarvis/api/belongings.py": "ed3598e69f3f0053"
  "src/jarvis/api/memory.py": "b4f86cb6ed2117cc"
  "src/jarvis/api/notes.py": "267fb7b9484f51ea"
  "src/jarvis/api/static/console-memory.js": "b88a7282d9e272d9"
  "src/jarvis/api/static/console-notes-memo.js": "611c96f51b3ebd97"
  "src/jarvis/api/static/console-notes.js": "92a47b642b64b6a6"
  "src/jarvis/api/static/console-things.js": "03183aa2760ac6a0"
---
## In plain words
This module is JARVIS's notebook about you. Memory holds short facts about the people, places and things you like, and brings the relevant ones into a reply, showing which it used. Notes keep your own notes, voice-memo transcripts and saved web links. Things answers "Where did I keep it?": tell JARVIS the passport is in the blue suitcase and ask months later. All of it is yours to see, correct, export and delete.

## Example (made up)
On a Saturday Divya tells JARVIS, "The spare car key is in the top drawer of the study desk." Things saves it. In March she asks, "Where's the spare car key?" and JARVIS answers, "Top drawer of the study desk, since 14 September." She moves it to the key box by the door and says so; the history keeps both places. In Memory she once added "Tara is allergic to peanuts", so when she asks for a snack list for Tara's birthday party the reply leaves peanuts out and shows that fact under "what I used".

## How it works
The Memory panel, `src/jarvis/api/static/console-memory.js`, loads only when you open it and reads `GET /v1/memory`: your settings, the About you notes and every fact. `add_fact` stores a fact you type, `patch_fact` edits or pins one, and `delete_fact` removes it with the older versions it replaced. Learning from your messages stays off until you switch it on with `put_settings` and confirm the spend; asking without that confirmation gets status 409. Before anything is kept, a filter refuses ID numbers, card numbers and passwords with status 422 "sensitive" (`add_fact`). `export` downloads everything as a JSON file with its history, `import_memory` reads such a file back, and `forget_everything` wipes facts and profile only after you type FORGET, keeping your settings. Notes live in `src/jarvis/api/notes.py`: `add_note` keeps a note, a voice memo or a link, and `list_notes` searches them by code, with no AI call. A voice memo is a transcript, never audio: `src/jarvis/api/static/console-notes-memo.js` sends the recording in short pieces to be turned into words, you correct them, and only Save stores them. `fetch_note` reads the text of a saved link's page only after you confirm it may spend a web credit (`FetchRequest`). Deleting a note puts it in Recently deleted first (`delete_note`), and `export_notes` writes its audit line before it sends anything (`_audit_export`). Things are kept by `src/jarvis/api/belongings.py`: `things_put` adds a thing or moves it, remembering where it was, and `things_history` lists its earlier places. `things_list` finds a thing by name, and changes are limited to {{fact:src/jarvis/api/belongings.py:CHANGES_PER_MINUTE}} a minute (`_limit`). `things_export` works only from the console in your browser, and `things_remove` puts a deleted thing in Recently deleted.

## What it costs
Notes and Things cost nothing: they are your own records, searched by code (`src/jarvis/api/notes.py`, `src/jarvis/api/belongings.py`). Memory costs nothing while learning is off. With learning on, each background run is a small call to the cheapest brain tier, and the panel shows the estimate in rupees before you agree (`put_settings`).

## When it fails
A memory outage gives a reply without its notes, never a failed reply. A brain that may train on what it is sent never sees your memory (`src/jarvis/api/static/console-memory.js`). Without JARVIS's encryption key, Notes and Things stay switched off and say so, so nothing is stored in clear (`_need`). An import over the size cap is refused with status 413 before it is read (`import_memory`), and a full memory answers status 409 "memory_full" (`add_fact`). If the audit line for a notes export can't be written, nothing is sent (`export_notes`).
