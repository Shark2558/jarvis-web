---
page: pg_card_c23
written_by: Workshop · Mark XXIV
written_on: 2026-11-24
sources:
  "src/jarvis/api/notes.py": "267fb7b9484f51ea"
  "src/jarvis/api/static/console-notes-memo.js": "611c96f51b3ebd97"
  "src/jarvis/api/static/console-notes.js": "92a47b642b64b6a6"
  "src/jarvis/kb/__init__.py": "83ae49288c8bbc30"
  "src/jarvis/kb/fetch.py": "2ff5414a91395922"
  "src/jarvis/kb/models.py": "43c1461d2fa5d480"
  "src/jarvis/kb/privacy.py": "9807e75dba2eb7d7"
  "src/jarvis/kb/search.py": "1395c6278f444625"
  "src/jarvis/kb/service.py": "352c0e4f7d8c5c66"
  "src/jarvis/kb/store.py": "0b84fbfbabf8a3bb"
  "src/jarvis/kb/tools.py": "86e109f097d14503"
---
## In plain words
This is your notebook inside JARVIS: notes you type, voice memos kept as text (never the recording), and web links you want to keep. JARVIS finds them again by plain search code, with no AI call, and seals them with its own encryption before they are stored (`src/jarvis/kb/store.py`). Other people's words in a saved page are always kept apart from yours (`src/jarvis/kb/tools.py`).

## Example (made up)
On Sunday you save a link to a recipe for appam and add "try with coconut milk". On Tuesday you record a 40-second memo about the plumber's quote; only the transcript is kept, after you check it and tap Save. On Friday you ask JARVIS "what did I note about the plumber?" and it finds the memo at once, with a short snippet around "plumber". You click Fetch on the recipe link; its page text is saved under your note, using 1 of your web credits.

## How it works
`NotesService` adds, edits, searches, removes, exports and imports your notes, checking every field and refusing sensitive text such as card or ID numbers (`src/jarvis/kb/service.py`). `NotesStore` keeps them in `kb_shards`, each shard sealed with AES-256-GCM under the notes key and bound to you and its place, while the header in `kb` holds only ids, hashes and counts (`src/jarvis/kb/store.py`). Search is plain code: `rank` scores the words of the title and tags (counted twice), the text, your note on a link and the saved page, lifts a title match and a recent update, and returns at most {{fact:src/jarvis/kb/models.py:MAX_HITS}} hits with short snippets (`src/jarvis/kb/search.py`). `src/jarvis/api/static/console-notes-memo.js` records a memo in pieces through the voice service, shows the words for you to correct, and stores only the text when you tap Save. Saving a link keeps the address and makes no network call; Fetch, your click, gets the page text through the web search provider, at most {{fact:src/jarvis/kb/service.py:FETCH_PER_HOUR}} an hour, and never sends a link that carries an e-mail, phone number or other private part (`src/jarvis/kb/fetch.py`). The brain's notes tools come from `notes_tools`: reading is free, writing is reversible, and a spoken note becomes a card (`src/jarvis/kb/tools.py`). Each note records where its words came from, typed, memo, imported, spoken or outside, and only your own words count as trusted when read back (`vouches`). On a spoken or Telegram turn the result is masked, so a code in a note is never read aloud (`src/jarvis/kb/tools.py`). `src/jarvis/api/notes.py` serves the panel, including `GET /v1/notes/export` and `POST /v1/notes/import`.

## What it costs
Nothing: search is code, and the notes sit in the document store (`src/jarvis/kb/search.py`). Only Fetch uses one credit of the web search allowance per page (`src/jarvis/kb/fetch.py`).

## When it fails
Without the token key, or with `notes_enabled` off, the feature stays off, so notes are never stored in clear (`src/jarvis/kb/service.py`). A record that can't be read or decrypted fails closed and is never overwritten (`src/jarvis/kb/store.py`). Removing a note puts it in Recently deleted first, where it can be restored (`NotesService`). A fetch that fails, or an allowance that has run out, is reported in plain words, never the provider's text (`src/jarvis/kb/fetch.py`). Past {{fact:src/jarvis/kb/models.py:MAX_LIVE}} live notes, a new one is refused (`src/jarvis/kb/models.py`).
