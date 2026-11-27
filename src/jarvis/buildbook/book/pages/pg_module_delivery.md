---
page: pg_module_delivery
written_by: Workshop · Mark XXV
written_on: 2026-11-27
sources:
  ".github/pull_request_template.md": "507326d6a36186c6"
  ".github/workflows/ci.yml": "9a6b5662e765a438"
  "Dockerfile": "2b925ebcbd25ec7c"
  "Makefile": "3c446b64c5b9cb98"
  "deploy/backup_setup.sh": "354cd02d8afbcc3f"
  "deploy/cloudrun.sh": "768853b09894305d"
  "deploy/run-real-evals.sh": "3e7d08fb0a07cf43"
  "docs/github-backfill.tsv": "08260a54febc5a52"
  "evals/r14/backup.py": "163e8845efbe7c01"
  "evals/run_all_mock.py": "71d648c70abd6a51"
  "evals/run_real.py": "ce0ae50e362c19f3"
  "render.yaml": "f4d4dcab2c0f7920"
  "requirements.lock": "9c015550bb6a8ae7"
  "scripts/arch_coverage.py": "16b033ee883f89d6"
  "scripts/check_doc_versions.py": "3bb43ca65ad791d7"
  "scripts/check_pr_title.py": "8a7d9975cdae0f81"
  "scripts/github_backfill.sh": "a988b2892ffcc3aa"
  "scripts/ui_snapshots.py": "f7ee1329fa9806d1"
  "src/jarvis/api/backup.py": "d9e1d0f24f8d2498"
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
  "src/jarvis/config.py": "8c3c0b7f0890ff99"
  "src/jarvis/core/guardrails.py": "bf48636f731d056c"
  "src/jarvis/logging.py": "ce88f3d3fe3403b8"
  "src/jarvis/storage/firestore_admin.py": "342edf56ae911283"
  "src/jarvis/storage/firestore_walk.py": "82b45e93c972759f"
  "src/jarvis/telegram/service.py": "abea8743a90bb292"
  "tests/browser/test_ui_audit.py": "771e9d04da8af53e"
---
## In plain words
This module is how a change becomes the JARVIS you use, safely, and how your data survives a bad day. Every change is tested on GitHub first: the unit tests, test suites called evals that try to trick JARVIS, and a visual check of every console panel on a desktop and a phone screen. Only then is the new version built, started without traffic, checked for health and switched on. Settings live in one place and logs never hold secrets. Once you run a one-time setup, Google copies the whole database every day, and JARVIS proves once a month that a copy really restores.

## Example (made up)
On the 1st of December at 05:00, JARVIS starts its monthly restore drill. It checks that restoring last night's copy will cost under ₹100, then restores it into a throw-away database. Over the next 2 mornings it counts every collection against Google's figure, opens the canary with today's key and opens one vault file from the copy. On the 3rd the Vitals backup line shows that the drill passed, and the throw-away copy is deleted.

## How it works
`.github/workflows/ci.yml` runs on every pull request: the unit tests on both supported Python versions with coverage, lint, a Firestore emulator, the browser tests and the mock evals. `evals/run_all_mock.py` runs every eval suite against a fake brain, with correctness, injection and privacy cases, and each suite has a negative control that must fail; the phone calls' language check runs there scripted, with no network and no paid speech (`evals/run_all_mock.py`). `tests/browser/test_ui_audit.py` is the visual gate: every panel at desktop and phone size, Night and Day, checked for overlaps, contrast and touch targets, with `scripts/ui_snapshots.py` taking the screenshots. `evals/run_real.py` tests the real models, and `deploy/run-real-evals.sh` runs it only after a rupee estimate and your typed YES. A merge to main builds the image from `requirements.lock`, starts it with no traffic, checks its health, then switches traffic (`.github/workflows/ci.yml`). `scripts/arch_coverage.py` checks the architecture guide names every part of the code, and `scripts/check_doc_versions.py` that each plan opens with its version line and ends with a change log; the same job fails on a Build Book page that is missing, failing or older than its code (`.github/workflows/ci.yml`). `src/jarvis/config.py` reads every setting from the environment, keeps secrets typed so they are never printed, and refuses unsafe production settings at start-up. `src/jarvis/logging.py` writes one line per event with the request's trace id, as JSON when `log_json` is on. Backups begin only after `deploy/backup_setup.sh`, which shows its cost lines and waits for YES; then Google copies the database daily and guards it against deletion. Each morning `src/jarvis/backup/canary.py` writes a canary sealed with today's key, so a restored copy proves it opens with the live key. On day {{fact:settings.backup_drill_day}} of each month the drill in `src/jarvis/backup/drill.py` restores the newest copy into a throw-away database, refusing when that would cost more than ₹{{fact:settings.backup_drill_max_inr}}. `src/jarvis/backup/verify.py` checks it a step at a time across mornings, the canary, each vault and the counts, and `src/jarvis/backup/drill_end.py` deletes the copy. A newest copy older than {{fact:settings.backup_max_age_h}} hours turns the backup line red with a reason (`src/jarvis/backup/jobs.py`).

## What it costs
The tests and the deploy run inside GitHub's and Google's free tiers (`.github/workflows/ci.yml`). Backups cost nothing until you run the setup; after that, the daily copies and the monthly drill's restore cost a few rupees a month for a small database, and each drill is capped at ₹{{fact:settings.backup_drill_max_inr}} (`deploy/backup_setup.sh`). Mock evals are free; a real-model run shows its rupee estimate first (`deploy/run-real-evals.sh`).

## When it fails
A new version that isn't healthy never gets traffic, so the current JARVIS keeps running (`.github/workflows/ci.yml`). A failing test, emulator or visual check blocks the merge. A slow restore or check carries on at the next morning tick, and a drill that fails anywhere records a reason and still deletes its copy (`src/jarvis/backup/drill.py`). Before the setup the backup line says "not set up" and no alert rings (`src/jarvis/backup/status.py`).
