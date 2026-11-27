---
page: pg_screen_things
written_by: Workshop · Mark XXIV
written_on: 2026-11-24
sources:
  "src/jarvis/api/belongings.py": "ed3598e69f3f0053"
  "src/jarvis/api/static/console-things.js": "03183aa2760ac6a0"
  "src/jarvis/api/static/console.html": "6bf7eb0ad6bc821c"
---
## In plain words
Things answers the question "Where did I keep it?". You note what you put away and where, and when you need it again you type a word in the search box and JARVIS shows the place and when you noted it. When something moves, you say so and JARVIS remembers the old place too, so History shows where it has been. Everything here is kept encrypted (`src/jarvis/api/belongings.py`).

## Example (made up)
Before a trip in May you put the spare car key in the red tin on the kitchen shelf. In Things you type "spare car key" under What, "red tin, kitchen shelf" under Where, and press Save. In August you can't find it, so you type "car" in the search box and the row shows "red tin, kitchen shelf · updated 12 May". You move it to the hall drawer, press "Moved…", type the new place, and the panel says "Moved. It was in red tin, kitchen shelf."

## How it works
The panel loads your list from `GET /v1/things` when it opens, and the search box sends your words as you type (`src/jarvis/api/static/console-things.js`). The What and Where boxes save through `POST /v1/things`, which adds a new thing or moves one you already noted (`src/jarvis/api/belongings.py:things_put`). Each row shows the place, who it is for, when it was updated, and whether it was said by voice or came from someone else's words (`src/jarvis/api/static/console-things.js`). "Moved…" opens a box for the new place and saves it with `PATCH /v1/things/{thing_id}` (`src/jarvis/api/belongings.py:things_edit`). History shows the earlier places from `GET /v1/things/{thing_id}/history`. Delete first asks "Forget where this is kept?" with Keep it and Forget, then sends the row to Recently deleted with an Undo (`DELETE /v1/things/{thing_id}`). A thing JARVIS noted from a chat or by voice shows up here too, since the list reloads after a reply (`src/jarvis/api/static/console-things.js`).

## What it costs
Things uses no AI and no outside service, so it costs nothing (`src/jarvis/api/belongings.py`). Each change and search is a few reads and writes in JARVIS's own database.

## When it fails
If the list fails to load, the panel says "Couldn't load your things. Please try again." If a save fails, it says "Couldn't save that. Please try again." with the server's reason when there is one, such as a missing name or place. Without an encryption key on the server the list says it is not available. Changes are limited to {{fact:src/jarvis/api/belongings.py:CHANGES_PER_MINUTE}} a minute (`_limit`). If an undo fails, it says "Couldn't undo that. Try Recently deleted."
