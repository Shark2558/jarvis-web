---
page: pg_card_c58
written_by: Workshop · Mark XXIV
written_on: 2026-11-24
sources:
  ".github/pull_request_template.md": "507326d6a36186c6"
  ".github/workflows/ci.yml": "9a6b5662e765a438"
  "Dockerfile": "2b925ebcbd25ec7c"
  "Makefile": "3c446b64c5b9cb98"
  "deploy/cloudrun.sh": "76721925b3aca87c"
  "deploy/run-real-evals.sh": "3e7d08fb0a07cf43"
  "docs/github-backfill.tsv": "08260a54febc5a52"
  "render.yaml": "f4d4dcab2c0f7920"
  "requirements.lock": "9c015550bb6a8ae7"
  "scripts/check_doc_versions.py": "c0b0c0420638b540"
  "scripts/check_pr_title.py": "8a7d9975cdae0f81"
  "scripts/github_backfill.sh": "a988b2892ffcc3aa"
---
## In plain words
This is how a change to JARVIS's code reaches your live assistant safely. Every proposed change is tested by GitHub before it may be merged. Once it is merged, GitHub builds a new copy of JARVIS, starts it beside the old one with no visitors, checks that it is healthy, and only then switches everyone over; if the new copy isn't healthy, the old one keeps running (`.github/workflows/ci.yml`). A set-up script prepares the Google Cloud side once and is safe to run again (`deploy/cloudrun.sh`). Every release also carries a clear version number and title, so you always know what you are running (`scripts/check_pr_title.py`).

## Example (made up)
At 22:05 a builder opens a pull request titled "v9.2.0 · R9.2 Shopping lists · Mark XV". The tests, the browser checks and the document checks all pass, and Akhil merges it at 22:40. The deploy job builds the image, starts it with no traffic and asks its health page twelve times, ten seconds apart; the second answer is "ok", so traffic moves to it at 22:52. Had the health page kept failing, the version from the morning would have kept serving and the run would have ended in red.

## How it works
`.github/workflows/ci.yml` runs on every pull request: the unit tests on both supported Python versions with coverage, the linter, the mock evals, the Build Book check, a Firestore emulator test and the browser tests.
Separate jobs check the pull request's title with `scripts/check_pr_title.py` and every plan's version line and change log with `scripts/check_doc_versions.py`; neither ever holds up a deploy.
The documents job also checks that every page of the Build Book is written, passes its checks and is up to date with the code it describes, and fails the pull request when one is not (`.github/workflows/ci.yml`).
On a merge to main, the deploy job signs in to Google without a stored key, builds the image from the repository's Dockerfile with the exact package versions in `requirements.lock`, and pushes it (`.github/workflows/ci.yml`).
It refuses to deploy if main has moved on since, so re-running an old job never rolls JARVIS back, then rolls the image out with no traffic and checks its health page before switching traffic to it (`.github/workflows/ci.yml`).
`deploy/cloudrun.sh` sets up the cloud project once from Cloud Shell: the services, the secrets, the scheduler clocks, the image clean-up and, if you give them, the laptop speech kit's address and key, and skips whatever already exists.
`deploy/run-real-evals.sh` runs the evals against the real AI on demand, showing the cost in rupees and spending nothing until you type YES, and the Makefile gives short commands for tests, lint and evals.
`scripts/github_backfill.sh` gives older pull requests the same titles, labels and releases from `docs/github-backfill.tsv`; by default it only prints what it would change.
The fill-in template for every pull request is `.github/pull_request_template.md`, and `render.yaml` is the old blueprint from before Cloud Run.

## What it costs
Nothing while it stays inside the free tiers of GitHub Actions and Google's image store, as the deploy script sets them up (`deploy/cloudrun.sh`); the exact free minutes and storage are the vendors' and are Unverified here. Only the newest images are kept and old ones are deleted, which keeps storage small.

## When it fails
A new version that isn't healthy never gets traffic, and the current JARVIS keeps running unchanged (`.github/workflows/ci.yml`). A re-run of an old job stops instead of rolling main back. A wrongly titled pull request fails its title check until it is renamed (`scripts/check_pr_title.py`). In the back-fill, every write GitHub refuses is reported with what to do by hand and never retried; the run carries on and ends with an error (`scripts/github_backfill.sh`).
