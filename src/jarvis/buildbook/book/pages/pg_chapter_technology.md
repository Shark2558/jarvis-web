---
page: pg_chapter_technology
written_by: Workshop · Mark XXIV
written_on: 2026-11-24
sources:
  ".github/pull_request_template.md": "507326d6a36186c6"
  ".github/workflows/ci.yml": "9a6b5662e765a438"
  "Dockerfile": "ec8c53957aaefd1a"
  "Makefile": "3c446b64c5b9cb98"
  "android/gradle/libs.versions.toml": "eb0839fef229e7ee"
  "deploy/cloudrun.sh": "8fd20146ba1568b4"
  "deploy/home/bridge-requirements.txt": "d3cc937b4d00f431"
  "deploy/home/docker-compose.yml": "725207386158f89f"
  "deploy/run-real-evals.sh": "3e7d08fb0a07cf43"
  "docs/github-backfill.tsv": "08260a54febc5a52"
  "pyproject.toml": "bc1af1b3158d2ba0"
  "render.yaml": "f4d4dcab2c0f7920"
  "requirements.lock": "1bcd25a6a274b932"
  "scripts/check_doc_versions.py": "d5acf001aa9fe82d"
  "scripts/check_pr_title.py": "8a7d9975cdae0f81"
  "scripts/github_backfill.sh": "a988b2892ffcc3aa"
  "tools/markdy/package-lock.json": "f3ac43f6e9ddd521"
---
## In plain words
This chapter lists what JARVIS is built from, so you know which pieces of other people's work it stands on and where each one runs. The server is written in Python with the FastAPI web framework, packed into one container on Google Cloud Run, with its memory in Firestore. The console is plain browser code with no build step. Your home laptop runs a small kit of its own for the cameras, and the Android app is built with Google's Android tools. GitHub tests every change before it ships, and every package is pinned to an exact, checked version.

## Example (made up)
A security notice comes out on a Monday for the PDF reader that JARVIS uses. The inventory shows where it lives: listed in pyproject.toml, pinned with its exact hash in requirements.lock, and used only inside the cloud server. The fix is a one-line change to the version, a refreshed lock, and a pull request titled "v6.3.5 · R6.3.4 PDF reader update · Mark XXV". GitHub runs the tests on Python 3.11 and 3.12, the merge builds a new image, and it gets traffic only after it answers its health check, about 9 minutes after the merge.

## How it works
`pyproject.toml` names the server's building blocks: FastAPI and Uvicorn for the web server, Pydantic for checking data, httpx for calls out, Google's Firestore client for storage, cryptography and webauthn for keys and passkeys, and readers for PDF, Word, Excel and slides. Every package is pinned with its exact hash in `requirements.lock`, so the image build refuses any file that differs from the reviewed one. The Dockerfile beside it builds one slim Python container that runs as an ordinary user, stamps its own build day and checks its own health, and CI builds it on every merge (`.github/workflows/ci.yml`). `deploy/cloudrun.sh` sets Google Cloud up once from Cloud Shell, and is safe to run again: Cloud Run for the server, Firestore for memory, Secret Manager for keys, Cloud Scheduler for the morning clock, and the speech services. `render.yaml` is the older Render blueprint, kept from before the move to Google. `.github/workflows/ci.yml` runs the tests, lint, a Firestore emulator, the browser tests, the document checks and the eval gate, and a merge to main builds and rolls out the new image. Pull requests start from `.github/pull_request_template.md`; `scripts/check_pr_title.py` checks that each title names its version, release and Mark, and `scripts/check_doc_versions.py` checks that every plan opens with a version line and ends with a change log. `scripts/github_backfill.sh` gave the earlier pull requests the same titles, labels and Releases from `docs/github-backfill.tsv`. The home kit is `deploy/home/docker-compose.yml`: Mosquitto for messages, Frigate for the cameras, Home Assistant and the JARVIS bridge, every port bound to the laptop itself, with the bridge's packages hash-pinned in `deploy/home/bridge-requirements.txt`. The Android app's tools and libraries are pinned once in `android/gradle/libs.versions.toml`. `deploy/run-real-evals.sh` tests JARVIS against the real Claude models and spends nothing until you type YES. `tools/markdy/package-lock.json` pins the diagram tools behind the architecture guide's pictures, and the Makefile holds the everyday commands such as test, lint and serve.

## What it costs
The building blocks are free, open-source software. The hosting is set up to stay inside Google's and GitHub's free tiers: one Cloud Run instance that sleeps when idle, Firestore in the free tier, and GitHub Actions for the checks (`deploy/cloudrun.sh`, `.github/workflows/ci.yml`). Only the real-model test run spends money, and only after you type YES (`deploy/run-real-evals.sh`).

## When it fails
A new version that isn't healthy never gets traffic, so the running JARVIS keeps going (`.github/workflows/ci.yml`). A package whose hash doesn't match the lock stops the image build before anything ships (`requirements.lock`). A wrongly titled pull request fails its title check until it is renamed, and that check never holds up a deploy (`scripts/check_pr_title.py`). The back-fill reports every write GitHub refuses with what to do by hand, then carries on (`scripts/github_backfill.sh`).
