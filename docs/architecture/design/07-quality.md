Version v6.4.2 · 27 Nov 2026 · Release R6.4 · Status: Current · Owner: 🛠 Mark XXV

# 07 · Quality: tests, evals, CI and releases

**In plain words.** Every change to JARVIS is tested before it can reach you. About twenty
thousand automatic checks run on every pull request; the console is opened in a real browser and
every panel is checked at laptop and phone size; each skill has "evals" that try to trick it
(for example a mail that tells it to delete things) and must fail when the safety is switched
off. A new version goes live only after those pass and its health check answers; otherwise the
version you have keeps running. Every document, this one included, carries a version line and a
change log.

## 1. Tests

Measured on 27 Nov 2026 at `83331a1` (Python 3.13 here; CI uses 3.11 and 3.12):

| Suite | Files | Count | How counted | Runs in |
|---|---|---|---|---|
| Unit and store tests (`tests/`) | 939 Python files (browser tests and fixtures aside), 846 with collected items (848 define test functions) | **19,530** collected items | `pytest --collect-only -q` | CI `test` (3.11 and 3.12) |
| Firestore contract tests | 5 files marked `firestore_emulator` (part of the 19,530) | — | marker search | CI `firestore`, against the official emulator; `JARVIS_REQUIRE_EMULATOR=1` fails rather than skips |
| Browser tests (`tests/browser/`) | 105 test files | **1,207** test functions | static count of `def test_` (not collected here: Playwright is not in this environment) | CI `browser`, 4 shards, headless Chromium (Playwright 1.63) |
| Android `core` | JVM tests against the server's shared phone vectors | — | not counted | `.github/workflows/android.yml` (`build`, `controls`) |
| All test functions, static | — | 12,237 `def test_` (browser included) before parametrisation | `grep` | — |

**Where the unit tests point** (collected items grouped by the package a test file's name names;
files named only for a release are grouped by release). *Unverified:* the rule that put each file
in a group was not recorded, and a re-count by file name alone on 27 Nov 2026 gives different
group sizes (for example `voice` 428, `telegram` 266); the groups add up to the verified total of
19,530, and only that total is a measured figure:

| Group | Items | Group | Items |
|---|---|---|---|
| R11 helpers (cross-part) | 2,395 | `buildbook` | 1,073 |
| R13 wardrobe (cross-part) | 1,503 | `api` | 998 |
| R13.1 try-on (cross-part) | 816 | R14 hardening (cross-part) | 786 |
| R7 mobile (cross-part) | 641 | `tools` (the gateway and its tools) | 609 |
| `whatsapp` | 549 | `permissions` | 503 |
| `voice` | 442 | R6.3 Book (cross-part) | 339 |
| `brief` | 333 | `telegram` | 284 |
| `vault`, `vitals` | 254 each | `drive`, `web`, `recall` | 256, 249, 245 |
| 54 smaller groups (other packages, other releases, deploy and docs scripts) | 5,385 | file names that name no package or release | 1,616 |

**Test rules** (`.claude/rules/ecc/common/testing.md`, `CLAUDE.md`): write the failing test first;
unit, integration and end-to-end tests; 80 % coverage as the target.

## 2. Coverage

CI measures coverage on Python 3.12 only (`pytest --cov=jarvis`) and fails below the committed
floor, **95 %** (`scripts/coverage_floor.txt`), read by `scripts/coverage_floor.py`. The floor is a
ratchet: a whole percentage that only goes up, and the agents' safety hook refuses a lower one
(`.claude/hooks/guard.py`). The total was not re-measured for this document (the full run takes
long); the floor is what CI enforces on every change.

## 3. Evals and the eval gate

| Part | As built | Evidence |
|---|---|---|
| Suites | 46 folders under `evals/` (45 suites, one per slice or release, plus `realrun`, the real-run harness: injection, privacy, budget, correctness); each has a negative control that must fail when its safety is switched off (for example `policy.TAINTED_WRITES_ASK`, `telegram.service.R3_REFUSAL`, `recall.gate.memory_allowed` are read at call time for exactly that) | `evals/run_all_mock.py` |
| Mock runs | `make eval-mock` runs every suite on the mock brain; in CI the suites run inside `pytest` through 32 `tests/test_evals_*.py` files, controls included | `Makefile`, `tests/test_evals_*.py` |
| Phase 0 gate | pass rate ≥ 90 %, p95 turn ≤ 4,000 ms on balanced, mean cost ≤ US$0.01 a turn (≈ ₹0.95); `--mock` on every CI run (plumbing only), for real on `main` when the key is set (`eval-gate`, skipped with a notice otherwise; reports, never blocks the deploy) | `evals/phase0/run.py`, `.github/workflows/ci.yml` |
| Owner's real runs | Cloud Shell, key read from Secret Manager into memory only, ₹ estimate and typed YES, stop at 1.5 times the estimate; `--all` adds memory, voice, brief and the Google tools | `deploy/run-real-evals.sh` |
| The visual gate | Every panel, Night and Day, 1440×900 and 390×844, DOM checks (overlap, fonts, overflow, contrast, 44 px targets) | `tests/browser/test_ui_audit.py` |

## 4. CI jobs

| Workflow · job | Runs on | Checks | Does `deploy` wait for it? |
|---|---|---|---|
| `ci` · `test` (3.11, 3.12) | every pull request and push to `main` | ruff on `src`, `tests`, `evals`; pytest (3.11) or pytest with coverage and the floor (3.12); `evals/phase0/run.py --mock`; `python -m jarvis.buildbook.gen --check` | yes |
| `ci` · `docs-check` | every pull request and push to `main` | `scripts/check_doc_versions.py`; `scripts/arch_coverage.py` (the guide's coverage and the secret scan of `docs/architecture/`); `python -m jarvis.buildbook.gen pages --check` | no (a doc slip never holds a deploy) |
| `ci` · `pr-title` | pull requests (Dependabot's exempt) | `scripts/check_pr_title.py` | no |
| `ci` · `firestore` | every pull request and push to `main` | `pytest -m firestore_emulator` against the emulator | yes |
| `ci` · `browser` (4 shards) | every pull request and push to `main` | `pytest tests/browser -m browser`, each file on one shard (`tests/browser/shard_plan.py`) | yes, all four |
| `ci` · `docs` | pull requests | the diagrams: privacy rule, `lint --strict`, `verify --quality showcase`; `--check` of every export when `docs/architecture`, `tools/markdy` or `scripts/markdy_*` changed | no |
| `ci` · `eval-gate` | `main` | the real Phase 0 eval when the key exists | no |
| `ci` · `deploy` | `main` push or manual run, `AUTODEPLOY=on` | chapter 02, section 2.10 | — |
| `android` · `wrapper-pin`, `build`, `controls` | changes to `android/**` and its fixtures | the Gradle wrapper's checksum; resolve every dependency, `core`'s JVM tests, build, `scripts/apk_check.py`, lint; `controls` breaks `core` on purpose and requires its tests to fail | not part of `ci` |

All third-party actions are pinned by commit SHA; Dependabot proposes updates monthly
(`.github/dependabot.yml`). The default token is read-only; only `deploy` may mint a Google token
(`permissions: id-token: write`).

## 5. Documentation checks

| Check | What it enforces | Scope | Gap |
|---|---|---|---|
| `scripts/check_doc_versions.py` | Line 1 is the version line; the last `##` section is `## Change log` with its five-column table | `docs/plans/*.md`, `docs/architecture/*.md` and, since 27 Nov 2026, `docs/architecture/design/*.md` (no other sub-folder) | — (follow-up F3 closed; `tests/test_check_doc_versions.py` holds every ADD chapter in the check) |
| `scripts/arch_coverage.py` | The guide names every package, console module, Scheduler job, outside service and collection; complete cards and technology rows; the secret scan | the guide; the scan covers every file under `docs/architecture/` | Its collection patterns miss 5 names (chapter 04, section 2); the fix also touches app code (chapter 12, section 4) |
| `tests/test_llm_sdk_boundary.py` | No module outside `src/jarvis/llm/` imports an AI vendor's SDK (chapter 01, P7) | every module under `src/jarvis/` | Literal names only: an import built from a variable is out of its reach |
| `scripts/docs/adds_traceability.py` | Chapter 10 from the requirements workbook; reports a reviewed pointer that no longer fits | the workbook's Requirements sheet; the repository | The workbook is kept outside the repository, so CI cannot run it; the Workshop runs it at each release |
| `scripts/markdy_export.py` | Diagram privacy, lint, showcase verification, exports current | `docs/architecture/diagrams/*.markdy` | `--check` trusts `exports.json` (CI has no browser) |
| `python -m jarvis.buildbook.gen pages --check` | Every indexed Book page written, current (stamped against the code it cites) and passing its checks | `src/jarvis/buildbook/book/pages/` | — |

## 6. The Build Book, generated at build time

The Build Book is JARVIS's own illustrated explanation of how it is built, sealed with each
release. Since R6.3.1 JARVIS makes **no AI call** for it (`docs/plans/r6-3-1-book-at-build.md`).

| Step | As built | Evidence |
|---|---|---|
| Facts | `python -m jarvis.buildbook.gen --out DIR` builds `book.json`, `source.zip` and `release.json` from the repository's text and syntax trees: no model call, no network, never importing the app | `src/jarvis/buildbook/gen/__init__.py` |
| Pages | 153 indexed pages written by the Workshop during development, one Markdown file each in `src/jarvis/buildbook/book/pages/`, plus 46 flowcharts in `book/flows/`; every number comes from the code through `{{fact:…}}` placeholders | `src/jarvis/buildbook/book/AUTHORING.md` |
| Checks before merge | `--check`: byte-identical twice, no personal data or secret shape (the scrubber), every package in a layer, every flow step real; `pages --check`: every page present, current and passing | CI `test` and `docs-check` |
| Build | The deploy job compiles the pages into `pages.json.gz` and `flows.json` beside `book.json`, best effort and before any Google credential exists; a failure writes an error `release.json`, never a failed deploy | `.github/workflows/ci.yml` (`deploy`) |
| Seal | At run time the sealer encrypts each release's book under `book_index` and keeps it (60 MB cap); the book opens with a passkey and a fresh sign-in | `src/jarvis/buildbook/sealer.py`, C57 |

## 7. Release process and versioning

| Element | Rule | Evidence |
|---|---|---|
| Engineering loop | plan → test first → implement → review in a fresh context (code, Python; security for tools, auth, secrets or the gateway) → verify → remember → improve | `CLAUDE.md` |
| Plan | Every non-trivial change has `docs/plans/<slice>.md` before code | `CLAUDE.md`; `docs/plans/` |
| Branch shape | A release's `I0` branch builds the seams (contracts, stubs, wiring); parts A, B, … build on it in parallel; `I1` joins them and runs the integrated reviews; then one pull request to `main` | e.g. `docs/plans/r6-3-1-book-at-build.md` ("Branches"), `docs/plans/r6-4-integration/` |
| Program version | One source: `src/jarvis/__init__.py:__version__` (now `6.4.0`), read by `pyproject.toml`; the image records its build time; Vitals shows both. The number may go down on purpose between release lines (nothing compares it) | `pyproject.toml` (`dynamic = ["version"]`), `src/jarvis/about.py` |
| Document versions | Line 1 `Version vX.Y.Z · D Mon YYYY, HH:MM IST · Release … · Status: … · Owner: …`; a closing change log | `scripts/check_doc_versions.py` (workshop rules, section 6) |
| Pull request | Title `v<version> · <release> <name> · Mark <numeral>`; body from the template: version, release, Mark, plan, build log, owner's steps; five plain-words sections (what you get, cost in ₹, checks, reviews, not verified live) | `scripts/check_pr_title.py`, `.github/pull_request_template.md` |
| Commits | Conventional types; trailers `JARVIS-Version` and `JARVIS-Mark` on release commits | `.claude/rules/ecc/common/git-workflow.md`; `git log` |
| Guard rails for agents | Before every Bash, Edit or Write: no force-push, no push to `main`, no `rm -rf` outside scratch folders, no switching checks off in lint or type configs, no lower coverage floor | `.claude/settings.json`, `.claude/hooks/guard.py` |
| Going live | Merge to `main` → CI → `deploy` (no-traffic candidate, health check, switch); roll forward, never back across slice 5 | chapter 02, section 2.10; the guide, section 8 |
| Paperwork | Each release updates the guide, the build log and, from now on, this document | chapter 00 |

## Change log

| Version | Date | Release | What changed | By |
|---|---|---|---|---|
| v6.4.1 | 27 Nov 2026, 16:45 IST | R6.4 | First edition: test counts measured (19,530 collected unit items, 1,207 browser test functions, 5 emulator files) and grouped; the 95 % coverage floor; evals, controls and the Phase 0 gate; every CI job and what the deploy waits for; the documentation checks and their gaps; the Build Book's build-time generation; the release process and versioning | 🛠 Mark XXV |
| v6.4.2 | 27 Nov 2026 | R6.4 | Verification (chapter 13): the eval folder count corrected to 46; the test-file count's two figures explained; the per-group test counts marked unverified; the version check now covers this document (F3 closed); the SDK boundary test and the traceability generator added to the documentation checks | 🛠 Mark XXV |
