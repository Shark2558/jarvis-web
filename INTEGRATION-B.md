# R6.1 Part B — D4 versioning rollout (code side)

Branch `r6-1-b` from `r6-1-i0`. Plan: `docs/plans/r6-1-architecture-guide.md` (D4, decisions 2–4).
Every commit carries `JARVIS-Version: v6.1.0` and `JARVIS-Mark: XIII`.

## What was built

| # | What | Files |
|---|---|---|
| 1 | One version source `jarvis.__version__ = "6.1.0"` (pyproject `dynamic = ["version"]`, read by setuptools from that attribute: no second number). `jarvis.about`: `version()` → `v6.1.0`, `build_date()` → `11 Nov 2026` or `unknown`, `fields(zone)` (cached per process). Never the request time, and never raises: a stamp out of range, before 2000, garbage or huge reads `unknown`, a bad zone falls back to India then UTC, and any failure in `fields()` is logged once and shown as `unknown`, so GET /v1/vitals can't 500 on it. | `src/jarvis/__init__.py`, `pyproject.toml`, `src/jarvis/about.py`, `tests/test_about.py` |
| 2 | `GET /v1/vitals` (owner-only, existing route) gains `version` and `build_date`; the Vitals panel shows a read-only `About JARVIS · v6.1.0 · built 11 Nov 2026` line (`#vAbout`, existing `.sfine` class, at the foot of the panel's `.list`). A bad or missing version hides the line; an unknown date reads "build date unknown". | `src/jarvis/vitals/api.py`, `console-vitals.js` (355 lines), `console.html` (+2 lines), `tests/test_vitals_api.py`, `tests/test_vitals_console.py`, `tests/browser/test_vitals_board.py`, `tests/browser/ui_checks.py` (the visual audit's vitals mock carries the two fields) |
| 3 | Build book: `RELEASE_ID` unchanged; `ReleaseRef.version` optional (`^v\d{1,3}\.\d{1,3}\.\d{1,4}$`), read by the generator and the stdlib fallback from the documented checkout's `src/jarvis/__init__.py`. A release without a version dumps exactly as R6 wrote it (wrap serializer drops the key), so sealed R6 books, their canonical bytes, release.json and the R6 routes' answers are unchanged. Sealed rows (`view()`) add `version` when set. Book panel, kept-release rows, reader head and the show's start card read `R6.1 · v6.1.0 · 8308815`. Scene 1's first line and the digest overview say `version v6.1.0, commit <id>`; scene facts (6 tiles) unchanged. `about` mapped to layer X. | `buildbook/model.py`, `gen/{fallback,write,show,chunks,layers}.py`, `console-book.js`, `console-book-show.js`, `tests/test_r61_book_version.py`, `tests/browser/test_book_panel.py`, `tests/browser/test_book_show.py` |
| 4 | `.github/pull_request_template.md` (header lines + the five sections). `scripts/check_pr_title.py` (stdlib, ASCII digits, whole-title match). CI job `pr-title`: pull requests only, Dependabot exempt (actor and PR author), title passed through `env` (never `${{ }}` in shell), read live with `gh api` so "Re-run jobs" checks a renamed PR (the event's copy if that read fails), `contents: read` + `pull-requests: read`, a checkout with `persist-credentials: false` that fetches only the script, no `needs`, and the deploy job's dependency chain never reaches it (tested). Each Mark must be a well-formed Roman numeral and two Marks must rise (`VII–VIII`). | `.github/pull_request_template.md`, `scripts/check_pr_title.py`, `.github/workflows/ci.yml`, `tests/test_check_pr_title.py` |
| 5 | Back-fill test: a bash stand-in `gh` first on PATH (canned JSON, every call logged) that answers only `gh api <path>` for a PR, label or tag and refuses every write flag in every spelling (`-X`/`--method` but GET, `-f`/`-F`/`--field`/`--raw-field`, `--input`); `git`/`curl`/`wget` stand-ins refuse too. Practice mode prints a DRY retitle for exactly the 21 titles, makes only those reads (every logged call is checked), skips an unmerged PR, only retitles an already-headed PR, reports an unreadable one (exit 1, the rest go on); a negative control injects a write that skips `run()` and the test catches it. Script: a malformed row (number, version, or `prerelease` not `true`/`false`, since `-F` reads `@…` as a file) is reported and skipped; the first line names the repository and the mode; with `REPO` from the environment set to another repository, `--apply` needs it repeated (`--apply owner/name`). | `scripts/github_backfill.sh`, `tests/test_github_backfill.py` |
| 6 | Version line + change log on all 22 plans that lacked one; `scripts/check_doc_versions.py` (stdlib) fails when a `docs/plans/*.md` or `docs/architecture/*.md` lacks the first-line version line or the closing `## Change log` table (headings inside fenced code are ignored; a line may come before the table, nothing but table rows after it); run in CI's `test` job only. | `docs/plans/*.md`, `scripts/check_doc_versions.py`, `tests/test_check_doc_versions.py`, `.github/workflows/ci.yml` |

## The build date — what the deploy needs

**Nothing has to be added to the deploy step.** The Dockerfile stamps the build time itself, right
before `pip install .`:

```dockerfile
RUN date -u +%Y-%m-%dT%H:%M:%SZ > src/jarvis/BUILD_DATE
```

`BUILD_DATE` is package data (`"jarvis" = ["BUILD_DATE"]`), git-ignored (so `.gcloudignore`, which
includes `.gitignore`, never uploads a stale local one), and read by `jarvis.about`. Both deploy
paths build this Dockerfile: CI's `docker build` (deploy job) and `deploy/cloudrun.sh`'s
`gcloud run deploy --source .` (Cloud Build), so neither file needed a change. Order of sources:
`JARVIS_BUILD_DATE` env (ISO 8601, for another host or a test) → the stamp → `unknown`.

Why not the plan's "env/build-arg written by CI": a `--build-arg` cannot be passed through
`gcloud run deploy --source`, and a service-level env var set by `cloudrun.sh` would be kept by
CI's later `gcloud run deploy --image` and override a newer image's date. The stamp has neither
problem. **Only caveat:** if the deploy ever turns on a Docker layer cache (buildx `cache-from`,
kaniko cache), the stamp layer could be reused when `src/` is unchanged. Then change the line to
`ARG JARVIS_BUILD_TIME` + `RUN echo "$JARVIS_BUILD_TIME" > src/jarvis/BUILD_DATE` and pass
`--build-arg JARVIS_BUILD_TIME="$(date -u +%Y-%m-%dT%H:%M:%SZ)"` in the deploy job's `docker build`.
The Dockerfile's comment says the same in one sentence.

## Shared files the integrator must merge or touch

- `.github/workflows/ci.yml`: Part B added the `pr-title` job (between `test` and `firestore`) and
  one step in `test` (`python scripts/check_doc_versions.py`, after `ruff check`). Part C adds the
  `docs` job: keep both.
- `src/jarvis/api/app.py` (not edited, per the brief): `FastAPI(..., version="0.0.1")` should read
  `version=jarvis.__version__` (cosmetic: `docs_url=None`, nothing shows it).
- `src/jarvis/api/static/console.html`: one `<p class="sfine" id="vAbout"></p>` (+ comment) inside
  `#p-vitals .list`, after the `#vOffline` line; Part A edits the dock. `tests/browser/ui_checks.py`:
  `ABOUT` + `MOCK_VITALS` lines; Part A may edit the same file.
- **Part D / Part C:** every new `docs/architecture/*.md` (the guide) and any new `docs/plans/*.md`
  must start with the version line and end with the change-log table, or CI's test job fails.
  Sub-folders (`docs/architecture/diagrams/`) are not checked.
- Pinned real-repo tests updated because the I0 plan made R6.1 the newest plan (they already failed
  on `r6-1-i0`): `tests/test_book_gen_plans.py::test_the_real_plans_parse`,
  `tests/test_book_gen_determinism.py::test_the_real_repo_builds_...` (label and version, now derived
  from `plans.release_label` and `jarvis.__version__`).
- After the integration merge, the release id shown is the merge's commit; the version stays v6.1.0.
- A version bump is now one line (`src/jarvis/__init__.py`) plus the tests' one literal
  (`tests/test_about.py::test_the_version_lives_in_one_place`); the label stays pinned in
  `tests/test_book_gen_plans.py`.

## Rolling back past R6.1

R6 code refuses unknown fields (`Release`, `SealedRelease`), so a `release.json` or a sealed
book-index row that R6.1 wrote with `version` will not load on an R6 build, which then has "no
book" for it (security review L5; not tried here). A rollback past R6.1 must either remove the R6.1-written `release.json` / sealed
rows (or rebuild the book with R6 code), or accept "no book" until the next R6.1 deploy. Rows and
books written by R6 open on R6.1 unchanged (the key is dropped when there is no version).

## Plan version lines (back-filled)

Release plans `v<release>.1` (R6 → v6.0.1, R5.1 → v5.1.1); slice plans the map's version (v0.9.0,
v0.5.2 for 5c, v0.7.1 for 7b). Dates are the IST day of each merge (read from GitHub): Slice 11 is
3 Nov (merged 00:51 IST), R1–R3 5 Nov, R4–R5 9 Nov, R5.1 and R6 10 Nov. **Inferred, please
confirm:** Slices 1–4 (`v0.1.0`–`v0.4.0`, 1 Nov) are not in the map and predate PR #1; their owner
is written as 🛠 Mark I. Slice 5b (`v0.5.1`, 🛠 Mark II) shipped inside PR #1 with Slice 5.

## Back-fill practice run (real GitHub, reads only, no `--apply`)

`LC_ALL=C.UTF-8 bash scripts/github_backfill.sh` → exit 0; output saved as `backfill-dry.txt` in the
orchestrator's scratchpad. All 21 pull requests were read and are merged; **no row was unreadable.**
21 DRY retitles, 21 DRY Releases (no tag/Release exists yet), 64 DRY POSTs in all. PR #27 already
has its header line (retitle only, its title already matches). Label `release` exists; `hotfix`,
`docs` and every `Mark …` label do not (practice mode prints a create line for a Mark label on each
row that names it, because nothing is created in practice; `--apply` creates each once). The DRY
lines include the PRs' original descriptions (that file stays local). `--apply` must run where
GitHub allows writes (decision 4).

## Tests run (all green)

- Review fixes (3.11 and 3.12): `test_about`, `test_vitals_api`, `test_vitals_console`,
  `test_github_backfill` (+ `test_deploy_config`, shellcheck), `test_check_pr_title`,
  `test_check_doc_versions`, `test_r61_book_version`, `test_book_gen_determinism`,
  `test_book_gen_plans`, `test_book_gen_cli`, `test_console_assets`, `test_book_unlock`,
  `test_deploy_media`; a wheel built from the tree carries Version 6.1.0; ruff + mypy clean.
- 3.11: `test_about`, `test_vitals_api`, `test_vitals_console`, all `test_book_*` + `test_r6_*`
  (1,060), `test_r61_book_version`, `test_check_pr_title`, `test_check_doc_versions`,
  `test_github_backfill`, `test_deploy_config`, the vitals/R4/R5.1 wiring tests, the console static
  tests (585), the plan-reading seam/persona tests (699). 3.12: the touched unit files (258).
- Browser (3.13): `test_vitals_board.py` (28), `test_book_panel.py` + `test_book_show.py` (33),
  `test_ui_audit.py -k vitals` (8).
- `python -m jarvis.buildbook.gen --check`: two builds byte-identical (R6.1, v6.1.0).
- `evals/r6_book/run.py --mock`: 168/168, negative control fails the suite.
- ruff check + format clean and mypy clean on every touched file.

## Not verified live

- The stamp in a real Cloud Run image (and the line on the live Vitals panel).
- The `pr-title` job on GitHub: the live `gh api` title read, the Dependabot exemption, a fork PR.
- The template as GitHub renders it; `scripts/github_backfill.sh --apply`.

## Review follow-ups

From `review-b-code.md` (2 MEDIUM, 5 LOW) and `review-b-security.md` (5 LOW, 4 INFO):

| Finding | Done |
|---|---|
| Code M1: `build_date` could raise (OverflowError) and 500 the board | Fixed `1ebb81d`: never raises; tests on env + file stamps, zones, a crashing reader, GET /v1/vitals |
| Code M2: the back-fill stub missed writes without `-X` | Fixed `29ed3b9`: every write flag refused, every call checked, negative control |
| Code L1: literal-version pins | Fixed `6a28418`: derived from `jarvis.__version__` / `plans.release_label`; one literal left |
| Code L2: version in pyproject and `__init__.py` | Fixed `6a28418`: `dynamic` version from `jarvis.__version__`; pin test replaced |
| Code L3: `## ` in fenced code; content after the log | Fixed `a65dd81`. Not verified: the rule text itself (`workshop-rules.md` is a project doc outside this repo); every line in the repo uses `IST` and Status values without `·` |
| Code L4: loose Mark pattern | Fixed `4ab36d6`: well-formed numeral, rising range; the rule's own pattern kept |
| Code L5: the stamp is the layer's date | Documented: Dockerfile comment + the caveat above (CI builds without a layer cache) |
| Sec L1: checkout keeps the token | Fixed `05625c5`: `persist-credentials: false`, sparse checkout of the script; permissions already minimal |
| Sec L2: Dependabot exemption by PR author | Declined: the check judges the title, which Dependabot wrote; by actor alone a human's push or rebase on a Dependabot PR would fail it, and the job guards no code, secret or deploy (read-only token, not in `deploy.needs`) |
| Sec L3: `-F prerelease="$pre"` reads `@…` as a file | Fixed `29ed3b9`: rows validated (`true`/`false`, number, version) before any use |
| Sec L4: `REPO`/`MAP` from the environment | Fixed `29ed3b9`: first line names repo + map + mode; a non-default `REPO` needs `--apply owner/name` |
| Sec L5: R6 can't read R6.1 rows on rollback | Documented in "Rolling back past R6.1" above |
| Sec INFO: cached stamp layer | Same as code L5 (comment added) |
| Sec INFO: `fields()` cached per zone; deploy job order; PR template | No change needed (the reviewer's own conclusion) |
