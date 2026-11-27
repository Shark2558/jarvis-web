---
page: pg_screen_people
written_by: Workshop · Mark XXIV
written_on: 2026-11-24
sources:
  "src/jarvis/api/static/console-people.js": "90b76851b4821be7"
  "src/jarvis/api/static/console.html": "6bf7eb0ad6bc821c"
  "src/jarvis/people/routes.py": "1a14f337e5c1b049"
---
## In plain words
People looks up public figures and work contacts from public sources, before a meeting for instance. You type a name, and a role or organisation if the name is common, and JARVIS returns a short dossier: a summary and a card for each public profile it found, each with its own link. It never gathers a private person's home, movements or accounts, and never identifies anyone from a face; the server refuses such requests. Nothing is saved. The same panel holds the Brain mode switch, AI or No-AI (`src/jarvis/api/static/console-people.js`).

## Example (made up)
Tomorrow at 10:00 you meet Dr Farida Rahman, head of a hospital's IT. In People you type her name and "City General Hospital" under "Role or organisation (optional)", and press Research. The panel says "Searching public sources...", then shows a three-line summary and cards for her LinkedIn page and a conference talk. You press "Open next" twice; each opens one profile in a new tab and its card says "Opened". You press Speak to hear the summary while you get ready.

## How it works
Research sends the name and the optional role to `POST /v1/people/research` (`src/jarvis/api/static/console-people.js`). The route answers with the dossier: the public profiles, short findings with their sites, a summary when the AI is on, and a note when several people share the name (`src/jarvis/people/routes.py:research`). A request that reads as private, or a person who is not a public figure or professional, is refused with a plain message, shown as it is (`src/jarvis/people/routes.py:research`). Each profile is a card with its own real link, and "Open next" presses the next unopened one, one tab per press (`src/jarvis/api/static/console-people.js`). Speak reads the dossier's spoken line aloud in your JARVIS voice (`src/jarvis/api/static/console-people.js`). The last dossier of this session comes back from `GET /v1/people/last` when the console starts again (`src/jarvis/people/routes.py:last`). The Brain mode row and the top-bar pill read and set the mode through `GET /v1/settings/brain-mode` and `POST /v1/settings/brain-mode`; switching AI back on asks you first (`src/jarvis/people/routes.py:set_mode`). A "Look up" button under a chat reply opens this panel and researches the name only when you press it (`src/jarvis/api/static/console-people.js`).

## What it costs
A search uses web search credits from the month's allowance, and the summary is written by the paid AI, so its cost counts towards your monthly limit (`src/jarvis/people/routes.py:research`). In No-AI mode the dossier is links only and nothing paid is used (`src/jarvis/api/static/console-people.js`).

## When it fails
With no name, the panel says "Give me a name to research, Sir." If several people share the name, it asks you to add a role or organisation. A refused request shows the server's reason. If the server has no people research, it says "People research is not set up on this server." (`src/jarvis/people/routes.py`). If the brain mode fails to load, the pill says to press it and try again.
