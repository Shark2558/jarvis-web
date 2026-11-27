---
page: pg_chapter_data
written_by: Workshop · Mark XXV
written_on: 2026-11-27
sources:
  "deploy/backup_setup.sh": "354cd02d8afbcc3f"
  "deploy/cloudrun.sh": "567937409974b4a2"
  "evals/r14/backup.py": "163e8845efbe7c01"
  "src/jarvis/api/backup.py": "d9e1d0f24f8d2498"
  "src/jarvis/api/privacy.py": "26b8bb3f25b86ee7"
  "src/jarvis/api/static/console-privacy.js": "7184a1fe77763ae0"
  "src/jarvis/api/static/console-vault-add.js": "741e210463e7aaeb"
  "src/jarvis/api/static/console-vault.js": "7693be82eb53b3c8"
  "src/jarvis/api/vault.py": "cc8daba16d847fd1"
  "src/jarvis/backup/canary.py": "66849eb1efde4ddc"
  "src/jarvis/backup/drill.py": "b0778086df43a200"
  "src/jarvis/backup/drill_deps.py": "6f8f658c1f5b5329"
  "src/jarvis/backup/drill_end.py": "3de173f184aa3e89"
  "src/jarvis/backup/drill_start.py": "d91e6d52b859c8d9"
  "src/jarvis/backup/jobs.py": "9ebc144ace125710"
  "src/jarvis/backup/log.py": "e9b004b120699fff"
  "src/jarvis/backup/names.py": "c75892721db14ee0"
  "src/jarvis/backup/part.py": "acc12e13dbcb26b4"
  "src/jarvis/backup/ports.py": "590c986db119aed4"
  "src/jarvis/backup/privacy.py": "f73bc70901711383"
  "src/jarvis/backup/readonly.py": "df5b6b552f9cb766"
  "src/jarvis/backup/status.py": "83c4eb78c1a66bce"
  "src/jarvis/backup/texts.py": "a32dccabb8c5a3e8"
  "src/jarvis/backup/tools.py": "d2e2a37b31ce1781"
  "src/jarvis/backup/vault_probe.py": "b8638cbb5fa60cd8"
  "src/jarvis/backup/verify.py": "98381e6ba5786d43"
  "src/jarvis/backup/vitals.py": "9e8fb47f5bdbeba9"
  "src/jarvis/backup/walk_checks.py": "abe3dd11074f8f6e"
  "src/jarvis/config.py": "965b3658da16361e"
  "src/jarvis/core/guardrails.py": "bf48636f731d056c"
  "src/jarvis/integrations/vault.py": "b766226c56672432"
  "src/jarvis/keyring.py": "092c625e649b4b88"
  "src/jarvis/storage/approvals.py": "093f10af05d87010"
  "src/jarvis/storage/audit.py": "d268e84d6aa87ab5"
  "src/jarvis/storage/docs.py": "561064f51e6e084f"
  "src/jarvis/storage/firestore_admin.py": "342edf56ae911283"
  "src/jarvis/storage/firestore_docs.py": "7077a22c0b20173d"
  "src/jarvis/storage/firestore_walk.py": "82b45e93c972759f"
  "src/jarvis/storage/sessions.py": "c9a8ec12966d54db"
  "src/jarvis/telegram/service.py": "abea8743a90bb292"
---
## In plain words
This chapter is about where your data lives and how it is kept safe and recoverable. JARVIS runs on Google Cloud Run, keeps its records in Google's Firestore database in the Mumbai region, and keeps its secrets in Secret Manager, never in the code. The most private things, such as the vault, notes, things, the numbers you call and your Google tokens, are sealed again by JARVIS with keys of its own, a separate key for each kind of data. The privacy panel shows what is kept, phone calls and your voice included, with Export and Delete. Once you switch backups on, Google copies the database daily while JARVIS proves each month that a copy restores. The Vault, Privacy, Approvals and Delivery pages give the details.

## Example (made up)
On a Friday Ritu wonders what JARVIS keeps about her family. Privacy lists 14 kinds of data: the vault holds 12 documents, encrypted by JARVIS, and Memory 63 facts. She downloads everything except the vault files as one file for her own records. That night Google copies the whole database, as it has every night since she ran the backup setup in October, and on 1 December the monthly drill proves that a copy restores and opens with today's key.

## How it works
`deploy/cloudrun.sh` sets JARVIS up on Google Cloud Run, sleeping when idle, with Firestore as its database in the same project and every secret stored in Secret Manager. `src/jarvis/config.py` reads every setting from the environment, keeps secrets typed so they never reach a log, and refuses to start in production with unsafe settings, such as a missing API token or a laptop-only mode. Every store speaks one small port, `Docs`, and only `src/jarvis/storage/firestore_docs.py` talks to Firestore, under the `firestore_prefix` name prefix. Conversations, approval cards and the audit chain live in `src/jarvis/storage/sessions.py`, `src/jarvis/storage/approvals.py` and `src/jarvis/storage/audit.py`, the last one append-only. `Keyring` turns the one token key into a separate key for each kind of data, so the key for notes never opens the vault, and `TokenCipher` seals with AES-256-GCM. The vault seals each file under its own key and opens a file only after an unlock in the console that lasts {{fact:settings.vault_unlock_minutes}} minutes (`src/jarvis/api/vault.py`). The privacy panel, `src/jarvis/api/privacy.py`, lists the kinds of data kept, with Export and Delete, and asks for your passkey before anything goes for good. Phone calls have their own four rows there, from `src/jarvis/calls/privacy.py`: the calls, their settings, the call desk's link and the language check's results. Your voice has rows of its own: your voice profile, the voice session's recordings, which stay on your laptop, and the wake-word files trained from them (`src/jarvis/api/privacy.py`). Backups begin with your one-time `deploy/backup_setup.sh`: a daily copy kept {{fact:src/jarvis/backup/status.py:RETENTION_DAYS}} days, and delete protection on the live database. `src/jarvis/backup/canary.py` writes a daily canary sealed with today's key, and the monthly drill in `src/jarvis/backup/drill.py` restores a copy into a throw-away database and checks it (`src/jarvis/backup/verify.py`). The drill reaches Google only through `FirestoreAdmin`, and reads both databases through read-only views (`src/jarvis/backup/readonly.py`).

## What it costs
Keeping your data costs nothing while it stays inside Firestore's free tier, and the keyring and the vault use no outside service (`src/jarvis/keyring.py`). Secret Manager is free for the first few secret versions, with a small monthly charge for each one beyond them. Backups add a few rupees a month for a small database, only after you switch them on (`deploy/backup_setup.sh`).

## When it fails
Without the token key the vault, notes, things and other sealed features stay off, rather than store anything in clear (`Keyring`). A wrong key or a tampered record is refused, never guessed at (`TokenCipher`). A malformed or weak token key stops start-up, while a missing optional key just leaves its feature off (`src/jarvis/config.py`). Data that changed since you looked is refused at delete time with status 409 (`src/jarvis/api/privacy.py`). A drill that fails records a reason and still deletes its copy (`src/jarvis/backup/drill.py`).
