---
page: pg_card_c42
written_by: Workshop · Mark XXIV
written_on: 2026-11-24
sources:
  "src/jarvis/api/static/console-vault-add.js": "741e210463e7aaeb"
  "src/jarvis/api/static/console-vault.js": "7693be82eb53b3c8"
  "src/jarvis/api/vault.py": "cc8daba16d847fd1"
  "src/jarvis/vault/__init__.py": "8347e4218a876d75"
  "src/jarvis/vault/build.py": "1b4cc21bdbaa3c14"
  "src/jarvis/vault/crypto.py": "24f53deab403388d"
  "src/jarvis/vault/fields.py": "bb68493697d6e9ce"
  "src/jarvis/vault/models.py": "ab010acea484a5b4"
  "src/jarvis/vault/ports.py": "ba469b0a1ea15c77"
  "src/jarvis/vault/privacy.py": "26420f88e90a21e8"
  "src/jarvis/vault/reminders.py": "ba35d487efb6ee9f"
  "src/jarvis/vault/service.py": "626f27cabe888600"
  "src/jarvis/vault/store.py": "60f751afb5b9d31b"
  "src/jarvis/vault/tools.py": "f060de961eb36de1"
  "src/jarvis/vault/unlock.py": "87b7bdbf53f078e2"
---
## In plain words
The vault is a locked drawer for your important papers: ID cards, insurance, certificates. Every file is sealed with its own key, and opening one needs a fresh unlock on your console (`src/jarvis/vault/crypto.py`). JARVIS reminds you before a document expires, and the brain only ever sees a document's type, title and dates, never the file or a full number (`src/jarvis/vault/tools.py`).

## Example (made up)
You upload a scan of your passport. JARVIS finds "Date of Expiry 03/04/2027" in the PDF and proposes it; you check it and tap Confirm. In October 2026 a reminder says the passport ends in about 180 days. You ask "what's expiring in my vault?" and hear "Passport, yours, ends in 5 months". To open the scan you unlock with your passkey; the unlock lasts 10 minutes, and the download link works once, for a minute.

## How it works
`VaultService` checks each upload by its first bytes, refuses a file already there by its SHA-256, and makes it an item only once the index entry is written (`src/jarvis/vault/service.py`). `VaultCrypto` cuts a file into chunks and seals each with AES-256-GCM under the file's own key, bound to you, the item, the file and its place, so a chunk moved or cut short won't open; that key is itself wrapped by the vault key (`src/jarvis/vault/crypto.py`). The index is one sealed record in `vault`, and nothing readable is kept in clear (`src/jarvis/vault/store.py`). `propose` reads dates and the last four characters of an ID number from a PDF's text by fixed labels, with no AI, and it is only a proposal until you confirm it (`src/jarvis/vault/fields.py`). `POST /v1/vault/unlock` needs your passkey when passkeys are in force, otherwise a fresh Google sign-in, and lasts {{fact:settings.vault_unlock_minutes}} minutes; it works only from the console, never from a script (`src/jarvis/api/vault.py`). Opening a file takes a single-use ticket that lives {{fact:src/jarvis/vault/unlock.py:TICKET_S}} seconds; only a keyed hash of it is stored in `vault_unlocks` (`src/jarvis/vault/unlock.py`). Every unlock, open and export is written to the audit log before the first byte goes out (`src/jarvis/api/vault.py`). `VaultReminders` checks confirmed items once a day and when the panel opens, sends one alert per step, at most {{fact:src/jarvis/vault/reminders.py:MAX_ALERTS}} a run, from a fixed template, and records them in `vault_alerts` (`src/jarvis/vault/reminders.py`). The brain's `vault_tools` list items and dates and can change dates on a card, but can't read a file or add or delete one (`src/jarvis/vault/tools.py`). `src/jarvis/api/static/console-vault.js` and `src/jarvis/api/static/console-vault-add.js` draw the panel and its upload.

## What it costs
Nothing: sealing, reading dates and reminders are all code on JARVIS's own server, with the files kept in the document store, up to {{fact:settings.vault_max_total_mb}} MB in all (`src/jarvis/vault/service.py`).

## When it fails
Without the token key, or with `vault_enabled` off, the vault stays off (`src/jarvis/vault/build.py`). Reads fail closed: a record that can't be decrypted is refused, never shown in part (`VaultUnavailable`). A used, expired or unknown ticket gets one answer, gone (`TicketGone`). If the audit entry can't be written, nothing is sent (`src/jarvis/api/vault.py`). A delete is soft, through Recently deleted; "remove now" first deletes the index entry that holds the file's wrapped key, then the chunks, so the file can never be opened again (`VaultPurger`). A reminder that fails to send is tried again the next day (`src/jarvis/vault/reminders.py`).
