---
page: pg_card_c66
written_by: Workshop · Mark XXIV
written_on: 2026-11-24
sources:
  "deploy/backup_setup.sh": "354cd02d8afbcc3f"
  "evals/r14/backup.py": "163e8845efbe7c01"
  "src/jarvis/api/backup.py": "d9e1d0f24f8d2498"
  "src/jarvis/backup/__init__.py": "dbe6facab3a59646"
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
  "src/jarvis/core/guardrails.py": "bf48636f731d056c"
  "src/jarvis/storage/firestore_admin.py": "342edf56ae911283"
  "src/jarvis/storage/firestore_walk.py": "82b45e93c972759f"
  "src/jarvis/telegram/service.py": "abea8743a90bb292"
---
## In plain words
Everything JARVIS remembers for you lives in one Google database. Once you run a one-time set-up, Google copies that whole database every day and keeps each copy for {{fact:src/jarvis/backup/status.py:RETENTION_DAYS}} days, and the live database is protected against being deleted (`deploy/backup_setup.sh`). A backup you have never restored is only a hope, so once a month JARVIS also rehearses a real recovery: it restores the newest copy into a separate throw-away database, checks that it matches, then deletes it (`src/jarvis/backup/drill.py`). It can never write to your live data while it does this (`src/jarvis/backup/readonly.py`).

## Example (made up)
On the 1st at 05:00 the drill starts for Suresh. It restores last night's copy, which holds 18,402 documents, into the throw-away database. Over the next three morning ticks it counts every collection (18,402, a match), opens yesterday's sealed test value with today's key, opens his vault through its normal path, and compares 20 documents from each collection with the live ones. All pass, the copy is deleted, and Suresh gets "Backup drill passed". Vitals shows the copies cost about ₹4 this month.

## How it works
Every morning `BackupCanaryJob` writes a test value: a hash of a fresh random number, the number itself sealed with the keyring, and the key's fingerprint, so a restored copy can prove it opens with today's key (`src/jarvis/backup/canary.py`).
The same job reads Google's list of copies through `BackupStatusService` and raises a backup problem once a day if the newest copy is older than {{fact:settings.backup_max_age_h}} hours, the schedule is gone or the key changed.
`BackupDrillJob` moves the drill one step each morning, from the drill day or after you approve the "test my backup" card, at most {{fact:settings.backup_drill_manual_per_month}} extra times a month and never through Approve all (`Drill`).
The drill restores the newest finished copy only if the restore would cost at most ₹{{fact:settings.backup_drill_max_inr}}, into a database whose name `drill_target` checks before every Google call (`src/jarvis/backup/drill_start.py`).
The verifier counts every collection against Google's own count, checks the test value, opens each owner's vault and compares up to {{fact:src/jarvis/backup/walk_checks.py:SAMPLES_PER_COLLECTION}} documents a collection; comparing too few is a failure, never a pass (`src/jarvis/backup/verify.py`).
It reads the live side only through `read_only`, a view with no way to write, and the copy through `src/jarvis/storage/firestore_walk.py`, which has no writer at all.
Whatever the result, `cleanup` deletes the throw-away copy, and `DrillLog` records the outcome for Vitals.

## What it costs
Nothing until you run the one-time set-up (`deploy/backup_setup.sh`). After that Google charges for storing the daily copies and for the monthly restore; Vitals shows the month's cost in rupees, worked out from Google's prices at the live exchange rate (`monthly_inr`). A drill never starts if its restore would cost more than ₹{{fact:settings.backup_drill_max_inr}} (`src/jarvis/backup/drill_start.py`).

## When it fails
Before the set-up Vitals says "not set up", with no alert and no Google call (`BackupStatusService`). A slow restore or check simply carries on at the next morning tick (`Drill`). A drill cut off after its restore began ends "interrupted", never a second restore. Any failure is stored with a reason and the copy is still deleted (`cleanup`). An alert that reached nobody is tried again later the same day (`src/jarvis/backup/status.py`). The copies live in the same project as the key, so the drill proves recovery from a bad write or delete, not from losing the whole project.
