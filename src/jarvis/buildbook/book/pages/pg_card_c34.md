---
page: pg_card_c34
written_by: Workshop · Mark XXIV
written_on: 2026-11-24
sources:
  "src/jarvis/api/drive.py": "aab977fe9441f939"
  "src/jarvis/api/static/console-drive.js": "ba574f359e1d5e2b"
  "src/jarvis/drive/__init__.py": "a2a1bc6bf78f6da2"
  "src/jarvis/drive/client.py": "766e2385d779a833"
  "src/jarvis/drive/guard.py": "89a1025585b08521"
  "src/jarvis/drive/kinds.py": "64732723fb4aeeed"
  "src/jarvis/drive/live.py": "9b9a306d821512a1"
  "src/jarvis/drive/ports.py": "7417de94901166bc"
  "src/jarvis/drive/roots.py": "81117f718c69555f"
  "src/jarvis/drive/service.py": "dc7c305c68c1aca4"
  "src/jarvis/drive/token.py": "9e3f8f673ac390aa"
  "src/jarvis/drive/tools.py": "a381ec7f15714801"
---
## In plain words
JARVIS reads Google Drive files, but only in folders you deliberately hand it. It has its own Google account; you share a folder with that account from Drive, then switch the folder on in Integrations. JARVIS reads as itself and only reads, never as you and never writing, so the rest of your Drive stays out of its reach. Switching a folder off stops access at once.

## Example (made up)
You keep your flat's rental papers in a Drive folder called "Flat 2026". In Integrations you copy JARVIS's address, share the folder with it in Drive, and switch "Flat 2026" on. That evening you ask "when does my rent agreement end?". JARVIS searches inside that folder, reads the first part of the agreement PDF and answers "on 31 March". Asked about a file in another folder, it says the file is not in your chosen folders.

## How it works
The whole feature runs only when the `drive` setting is on; it is {{fact:settings.drive}} by default (`drive_configured`).
`MetadataTokens` gets a read-only Drive token for JARVIS's own cloud account from the server it runs on, never your Google link, and never logs it (`src/jarvis/drive/token.py`).
Switching a folder on asks Drive about that folder now: it must be a folder, not in the trash, and yours, judged against your verified address by `owned_by`; it is stored in `drive_roots`, at most {{fact:src/jarvis/drive/ports.py:MAX_ROOTS}} folders (`RootsStore`).
`drive_tools` give the brain four read-only tools: the chosen folders, one folder's contents, a search, and a read of one part of a file.
Before every call `RootChecks` re-checks each chosen folder (cached {{fact:src/jarvis/drive/live.py:ROOT_CHECK_TTL_S}} seconds), and a folder that fails is off for every tool, though kept.
`ParentsGuard` then walks each file's parent folders, at most {{fact:src/jarvis/drive/guard.py:MAX_DEPTH}} levels and {{fact:src/jarvis/drive/guard.py:MAX_LOOKUPS}} look-ups, and refuses anything not inside a chosen folder (`src/jarvis/drive/guard.py`).
A search keeps only hits inside the folders, at most {{fact:src/jarvis/drive/service.py:SEARCH_LIMIT}}, and a read returns one part of about {{fact:src/jarvis/drive/service.py:PART_CHARS}} characters; Docs become text, Sheets their first sheet, and PDFs or Word files up to {{fact:src/jarvis/drive/ports.py:MAX_FILE_BYTES}} bytes go through the app's sandboxed extractor (`DriveService`).
Extracted text is kept in memory for {{fact:src/jarvis/drive/service.py:TEXT_CACHE_S}} seconds only; nothing from Drive is stored (`src/jarvis/drive/service.py`).
Everything Drive returns, file names included, is fenced as outside content, so any write later in that turn becomes a card (`src/jarvis/drive/tools.py`).
`src/jarvis/api/static/console-drive.js` shows JARVIS's address, your folders with their switches (`GET /v1/drive`), and asks before switching one on (`PUT /v1/drive/roots/{folder_id}`).

## What it costs
Nothing in rupees: JARVIS reads with its own cloud account's token (`MetadataTokens`). It keeps only your list of chosen folders (`drive_roots`).

## When it fails
A file outside your chosen folders is refused as "not in your chosen folders" before anything is read (`NotInRoots`). A folder that is no longer yours, was trashed or can't be read shows "switched on, but JARVIS can't currently read it" (`RootChecks`). Any other Drive error fails the call and nothing is read (`src/jarvis/drive/guard.py`). If the list of chosen folders can't be read, JARVIS reads nothing from Drive (`RootsUnreadable`). With the Drive setting off, there are no Drive tools and Integrations says Drive is not set up (`build_drive_service`).
