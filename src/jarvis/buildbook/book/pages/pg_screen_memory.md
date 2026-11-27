---
page: pg_screen_memory
written_by: Workshop · Mark XXIV
written_on: 2026-11-24
sources:
  "src/jarvis/api/memory.py": "b4f86cb6ed2117cc"
  "src/jarvis/api/static/console-memory.js": "b88a7282d9e272d9"
  "src/jarvis/api/static/console.html": "d26e202e4e9aa526"
---
## In plain words
Memory is everything JARVIS keeps about you, on one page you control. "About you" holds four short notes you write yourself: You, Preferences, People and Work. "Facts" lists the smaller things JARVIS has been told to remember, each one editable, pinnable and deletable. Two switches decide whether memory is used in replies and whether JARVIS may learn facts from your messages. Export, Import and "Forget everything" sit at the bottom, so your memory stays yours (`src/jarvis/api/static/console.html`).

## Example (made up)
On Sunday you open Memory and fill in Preferences: "Short replies before 9 am. Metric units." You press Save and see "Saved.". Under Facts you type "Meera prefers calls after 6 pm", choose People and press Add. You pin it so it is picked first. Later you filter the facts for "gym", find an old one about a gym you left last year, and delete it after the question "Delete this fact for good?".

## How it works
When the panel opens, it loads your notes, facts, switches and counts from `GET /v1/memory` (`src/jarvis/api/static/console-memory.js`). Each About you note saves on its own Save button through `PUT /v1/memory/profile/{label}` (`src/jarvis/api/memory.py:put_profile`). "Add a fact" sends the text and its category to `POST /v1/memory/facts`, and the pin, edit and bin buttons on a fact use `PATCH /v1/memory/facts/{fact_id}` and `DELETE /v1/memory/facts/{fact_id}`. The two switches save through `PUT /v1/memory/settings` (`src/jarvis/api/memory.py:put_settings`). Switching on "Learn from my messages" first opens a window that says it uses Claude, the paid AI, and that only your own words are sent; nothing changes until you press Switch on (`src/jarvis/api/static/console-memory.js`). Export downloads your memory as a file from `GET /v1/memory/export`. Import reads such a file, shows what is in it and asks "Import this file?" before `POST /v1/memory/import` adds what is new and skips duplicates (`src/jarvis/api/memory.py:import_memory`). "Forget everything" needs you to type FORGET, then `DELETE /v1/memory` deletes every fact and note but keeps your switches (`src/jarvis/api/memory.py:forget_everything`).

## What it costs
Keeping and editing memory costs nothing (`src/jarvis/api/memory.py`). "Use memory in replies" adds a little to each reply's cost, because the notes travel with your message (`src/jarvis/api/static/console.html`). "Learn from my messages" uses Claude, and its confirm window shows the estimated monthly cost in rupees, which counts towards your monthly limit (`src/jarvis/api/static/console-memory.js`).

## When it fails
If you add something that looks like an ID, card or account number, a password or a health detail, the panel says "JARVIS doesn't keep that" and it is not stored. When memory is full, it says "Memory is full. Delete some facts to make room." A file that isn't a memory export is refused with a plain reason before anything is imported. If Forget everything fails, it says "Nothing was deleted." with the reason. With a brain that may learn from what you type, a warning says memory is not used with it.
