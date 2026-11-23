---
page: pg_card_c43
written_by: Workshop · Mark XXIV
written_on: 2026-11-24
sources:
  "src/jarvis/api/vault_inbox.py": "26546b663f03b975"
  "src/jarvis/vault_inbox/__init__.py": "137f6b0707c84739"
  "src/jarvis/vault_inbox/job.py": "ef1a655de53e9ae0"
  "src/jarvis/vault_inbox/privacy.py": "63cc443683af0832"
  "src/jarvis/vault_inbox/service.py": "28d7d4fda9011c06"
  "src/jarvis/vault_inbox/store.py": "bfcd12486df55c2d"
---
## In plain words
DigiLocker only lets registered organisations use its partner service, so JARVIS uses a simple path instead: you share a document from the DigiLocker app into one Google Drive folder that JARVIS may view, and JARVIS picks new files up and puts them into your vault (`src/jarvis/vault_inbox/service.py`). JARVIS only reads that folder; your copies stay in Drive, and nothing is imported twice (`src/jarvis/vault_inbox/store.py`).

## Example (made up)
You make a Drive folder called "To vault" and pick it in the Vault panel. On Saturday you share your driving licence and your vehicle's insurance from DigiLocker into it, plus a Word file by mistake. At the next scheduler tick JARVIS imports the two PDFs into the vault, ready for you to confirm their dates, and lists the Word file as skipped: "not a PDF, JPEG or PNG". Tapping "Import now" later does nothing new, because both PDFs were already taken.

## How it works
`PUT /v1/vault/inbox` lets you pick the folder; `InboxService` accepts only a folder you own, not one already used for Drive answers or inside one (`src/jarvis/vault_inbox/service.py`). `InboxJob` rides the scheduler tick and runs a check for each owner with a folder; an owner with none costs one storage read and no Drive call (`src/jarvis/vault_inbox/job.py`). A check lists the folder's own files, up to {{fact:src/jarvis/vault_inbox/service.py:LIST_PAGES}} pages of {{fact:src/jarvis/vault_inbox/service.py:LIST_PAGE}}, and takes a file only if it is new or changed, by its checksum or its time and size (`src/jarvis/vault_inbox/service.py`). A PDF, JPEG or PNG within the vault's size limit is downloaded and handed to the vault, at most {{fact:src/jarvis/vault_inbox/service.py:MAX_PER_RUN}} a run, and the rest wait for the next run (`InboxService`). Other files are skipped with a reason and not looked at again until they change (`Seen`). Before each run the folder is checked again: if it is no longer shared, no longer yours, in the bin, or now inside a folder used for Drive answers, imports stop and you are told why (`src/jarvis/vault_inbox/service.py`). `InboxStore` keeps the folder, the last check and what was already seen in `vault_inbox`, never a file's name or anything from inside a file (`src/jarvis/vault_inbox/store.py`). `POST /v1/vault/inbox/check` is "Import now", and each pick, switch-off and check is written to the audit log with the folder id only as a hash (`src/jarvis/api/vault_inbox.py`).

## What it costs
Nothing: reading the folder through Google Drive and sealing the files in the vault involve no AI and no paid service (`src/jarvis/vault_inbox/service.py`).

## When it fails
A file JARVIS skips is listed with its reason in plain words, and it is not tried again until it changes (`src/jarvis/vault_inbox/service.py`). If the stored record can't be read, it fails closed, and the Drive tools then read nothing at all, since the inbox can't be told apart (`InboxUnreadable`). A run stops at its time budget of {{fact:src/jarvis/vault_inbox/service.py:RUN_BUDGET_S}} seconds and carries on next time (`InboxService`). With Drive not set up, or its permission set to "Never", the panel says so and nothing is fetched (`src/jarvis/api/vault_inbox.py`). Google's own error text never appears (`src/jarvis/api/vault_inbox.py`).
