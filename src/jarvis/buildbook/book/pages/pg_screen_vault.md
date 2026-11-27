---
page: pg_screen_vault
written_by: Workshop · Mark XXIV
written_on: 2026-11-24
sources:
  "src/jarvis/api/static/console-vault-add.js": "741e210463e7aaeb"
  "src/jarvis/api/static/console-vault.js": "7693be82eb53b3c8"
  "src/jarvis/api/static/console.html": "6bf7eb0ad6bc821c"
  "src/jarvis/api/vault.py": "cc8daba16d847fd1"
  "src/jarvis/api/vault_inbox.py": "26546b663f03b975"
---
## In plain words
Vault is the locked drawer for your important papers: passport, licence, insurance, certificates. You add a PDF or a photo, JARVIS reads the dates from it, and once you confirm them it reminds you before each one expires. The files are kept encrypted. The assistant itself never reads them; it sees only the kind of document, the last few characters of its number and the dates. Opening a file needs a fresh check that it is really you, and works only in this panel (`src/jarvis/api/static/console-vault.js`).

## Example (made up)
In March you photograph your new car insurance and press Add in Vault. You choose "Vehicle insurance", leave "Whose is it?" on you, and press Add to vault. JARVIS shows what it found: expires 14 Mar 2027, number ending 4821. You press Confirm and see "Confirmed. Reminders are on." In February 2027 the brief and a reminder both say the policy is due. You tap the item, press Open front, use your passkey, and the policy downloads so you can send it to the renewal agent.

## How it works
The panel lists your documents by person, with each one's expiry and time left, from `GET /v1/vault` (`src/jarvis/api/static/console-vault.js`). Add opens a small form from `src/jarvis/api/static/console-vault-add.js`; the file goes up raw through `POST /v1/vault/upload`, and JARVIS answers with what it read, which counts for nothing until you press Confirm (`src/jarvis/api/vault.py:upload`). Edit and Confirm save through `PATCH /v1/vault/items/{item_id}`, and the reminder ticks choose how early you hear (`src/jarvis/api/vault.py:item_patch`). Delete asks first and sends the document to Recently deleted, with an Undo (`DELETE /v1/vault/items/{item_id}`). To open a file the panel asks for an unlock with `POST /v1/vault/unlock`: your passkey where you require one, else a recent Google sign-in (`src/jarvis/api/vault.py:unlock`). The unlock lives only in this tab's memory and is forgotten when the panel closes or the tab hides (`src/jarvis/api/static/console-vault.js`). Each open asks for a single-use ticket and then downloads the file, and every unlock, open and export is written to the audit log first (`src/jarvis/api/vault.py:download`). Settings choose how reminders are worded, whether due documents show in the brief, and your family list (`PUT /v1/vault/settings`). "Check DigiLocker now" imports new files from the Drive folder you picked (`POST /v1/vault/inbox/check`).

## What it costs
The vault keeps your files in JARVIS's own database with no outside service, so it costs nothing (`src/jarvis/api/vault.py`). Reading the dates from a file is done by code on the server, not by an AI (`src/jarvis/api/static/console-vault-add.js`). The DigiLocker import uses Google Drive's free access (`src/jarvis/api/vault_inbox.py`).

## When it fails
A file that is not a PDF, JPEG or PNG is refused with "Use a PDF, JPEG or PNG.", and one over the size limit is refused before it is sent (`src/jarvis/api/static/console-vault-add.js`). A file already stored gives "That file is already in your vault." If the unlock fails, the panel says "The vault could not be unlocked."; if your sign-in is too old, it offers "Sign in again". Unlocks are limited to {{fact:src/jarvis/api/vault.py:UNLOCKS_PER_MINUTE}} a minute and uploads to {{fact:src/jarvis/api/vault.py:UPLOADS_PER_MINUTE}} a minute. If a download fails, it says "The download did not work."
