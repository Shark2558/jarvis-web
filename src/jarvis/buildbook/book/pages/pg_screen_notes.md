---
page: pg_screen_notes
written_by: Workshop · Mark XXIV
written_on: 2026-11-24
sources:
  "src/jarvis/api/notes.py": "267fb7b9484f51ea"
  "src/jarvis/api/static/console-notes-memo.js": "611c96f51b3ebd97"
  "src/jarvis/api/static/console-notes.js": "92a47b642b64b6a6"
  "src/jarvis/api/static/console.html": "d26e202e4e9aa526"
---
## In plain words
Notes is your notebook inside JARVIS. It holds three kinds of thing: notes you type, voice memos you record and read through before saving, and links to web pages with a line on why you kept them. A search box finds any of them by their words, and the All, Notes, Memos and Links buttons narrow the list. Everything is stored encrypted, and JARVIS reads your notes when you ask it about them in a conversation (`src/jarvis/api/notes.py`).

## Example (made up)
After a call at 18:05 you press Record memo in Notes and speak for a minute about the plumber's quote. The words appear in a box marked "Transcript (edit before saving)"; you fix "tap" that was heard as "top" and press Save memo. On Thursday you press Save link for a recipe page, add "for Sunday lunch" as why you saved it, and press Fetch page text so the recipe stays readable even if the page goes. A week later you type "plumber" in the search box and the memo is the first match.

## How it works
The panel loads one page of your notes from `GET /v1/notes` when it opens, and the search box and the kind buttons ask again with your words (`src/jarvis/api/static/console-notes.js`). "Add note" and "Save link" open a small form that saves through `POST /v1/notes` (`src/jarvis/api/notes.py:add_note`). Record memo comes from `src/jarvis/api/static/console-notes-memo.js`: it records in pieces, turns each piece into words, puts them in an editable box, and keeps nothing until you press Save memo. Audio stays only in the page's memory and is dropped once it has been turned into words (`src/jarvis/api/static/console-notes-memo.js`). Opening a note lets you edit its text, title and tags, saved by `PATCH /v1/notes/{note_id}`. Fetch page text first asks "Fetch page text?", because it uses a web search credit, then stores the page's words with the link (`POST /v1/notes/{note_id}/fetch`). Delete moves a note to Recently deleted with an Undo (`DELETE /v1/notes/{note_id}`). "Export and import" saves all your notes as one file from `GET /v1/notes/export`, or adds a file made that way through `POST /v1/notes/import`, skipping anything that looks like an ID, card number or password (`src/jarvis/api/notes.py:import_notes`).

## What it costs
Typing, saving, searching and exporting notes costs nothing (`src/jarvis/api/notes.py`). Fetch page text uses one web search credit from the month's free allowance, and the panel asks before it does (`src/jarvis/api/notes.py:fetch_note`). A voice memo uses the same speech-to-words service as the microphone, or the browser's own when cloud voice is off (`src/jarvis/api/static/console-notes-memo.js`).

## When it fails
If you save something that looks like an ID, card number or password, the panel says JARVIS doesn't keep that, and nothing is stored. Without an encryption key on the server, it says "Notes are not available on this server (no encryption key)." If the microphone is off or blocked, Record memo explains how to switch it on, or suggests typing the note. If fetching a page fails, it says "Couldn't fetch the page." with the reason. An import file that is too big or not a notes export is refused before anything is added.
