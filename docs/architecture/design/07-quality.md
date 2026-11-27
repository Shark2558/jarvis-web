Version v6.5.1 · 27 Nov 2026, 21:25 IST · Release R18 · Status: Current · Owner: 🛠 Mark XXV

# 07 · Quality: tests, evals, CI and releases

**In plain words.** Every change to JARVIS is tested before it can reach you. About twenty
thousand automatic checks run on every pull request; the console is opened in a real browser and
every panel is checked at laptop and phone size; each skill has "evals" that try to trick it
(for example a mail that tells it to delete things) and must fail when the safety is switched
off. A new version goes live only after those pass and its health check answers; otherwise the
version you have keeps running. Every document, this one included, carries a version line and a
change log.

**Phone calls (R18, built, not yet deployed)** add about a thousand checks of their own, and a
"language check": before JARVIS offers a language on a call, it must hear phone-quality test
recordings correctly, speak clearly enough to be understood over a phone line, answer fast enough,
and be scored 4 out of 5 or better by a person who speaks it. No real call is made in any test.
Section 8 has the details.

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
| Suites | 47 folders under `evals/` since R18 (46 suites, one per slice or release, the newest `calls_language`, plus `realrun`, the real-run harness: injection, privacy, budget, correctness); each has a negative control that must fail when its safety is switched off (for example `policy.TAINTED_WRITES_ASK`, `telegram.service.R3_REFUSAL`, `recall.gate.memory_allowed` are read at call time for exactly that) | `evals/run_all_mock.py` |
| Mock runs | `make eval-mock` runs every suite on the mock brain; in CI the suites run inside `pytest` through 33 `tests/test_evals_*.py` files (R18 added `tests/test_evals_calls_language.py`), controls included | `Makefile`, `tests/test_evals_*.py` |
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
| `android` · `wrapper-pin`, `build`, `controls` | changes to `android/**` and its fixtures (R18 adds `tests/fixtures/r18/phone_calls_vectors.json`) | the Gradle wrapper's checksum; resolve every dependency, `core`'s JVM tests, build, `scripts/apk_check.py` (which now allows the four call permissions), lint; `controls` breaks `core` on purpose and requires its tests to fail (R18 adds `call_signature_off` and `call_number_leaks`) | not part of `ci` |

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
| Program version | One source: `src/jarvis/__init__.py:__version__` (`6.4.0` on `main`; `18.0.0` with R18), read by `pyproject.toml`; the image records its build time; Vitals shows both. The number may go down on purpose between release lines (nothing compares it) | `pyproject.toml` (`dynamic = ["version"]`), `src/jarvis/about.py` |
| Document versions | Line 1 `Version vX.Y.Z · D Mon YYYY, HH:MM IST · Release … · Status: … · Owner: …`; a closing change log | `scripts/check_doc_versions.py` (workshop rules, section 6) |
| Pull request | Title `v<version> · <release> <name> · Mark <numeral>`; body from the template: version, release, Mark, plan, build log, owner's steps; five plain-words sections (what you get, cost in ₹, checks, reviews, not verified live) | `scripts/check_pr_title.py`, `.github/pull_request_template.md` |
| Commits | Conventional types; trailers `JARVIS-Version` and `JARVIS-Mark` on release commits | `.claude/rules/ecc/common/git-workflow.md`; `git log` |
| Guard rails for agents | Before every Bash, Edit or Write: no force-push, no push to `main`, no `rm -rf` outside scratch folders, no switching checks off in lint or type configs, no lower coverage floor | `.claude/settings.json`, `.claude/hooks/guard.py` |
| Going live | Merge to `main` → CI → `deploy` (no-traffic candidate, health check, switch); roll forward, never back across slice 5 | chapter 02, section 2.10; the guide, section 8 |
| Paperwork | Each release updates the guide, the build log and, from now on, this document | chapter 00 |

## 8. Phone calls (R18)

Plan: `docs/plans/r18-calls.md`, sections 5.3 and 11. No test makes a real call or uses paid
speech; the real language check runs only from the Calls panel.

### 8.1 The language check and its bars

Every language, for every speech option, must pass before it is offered on a call card
(`src/jarvis/calls/langcheck/runner.py:LanguageCheck`; the bars are
`src/jarvis/calls/models.py:LANG_CHECK`):

| Step | What is tested | Pass |
|---|---|---|
| Hearing over a phone line | 20 FLEURS test clips a language (CC BY 4.0, fetched from Hugging Face at run time), turned into phone audio (300–3,400 Hz, 8 kHz, G.711 mu-law: `src/jarvis/calls/speech/phoneline.py`) and heard by the option | at least 90 % of the key facts (numbers, times, dates, names, yes or no) and a character error rate of 15 % or less; fewer than 10 usable clips give no verdict |
| Speaking over a phone line | 10 call sentences (translated once), spoken by the voice, through the phone line, heard back by a different option | at least 90 % of the key facts survive |
| Speed | the option's own hearing of short call turns, plus the brain's part | half the replies start within 1.5 s, 9 in 10 within 2.5 s. The brain's part is the fast tier's 0.6 s estimate (`BRAIN_ESTIMATE_S`) until it is measured |
| A person listens | 3 samples a language, scored 1 to 5 by the owner or a native speaker in Calls → Languages, "Score the voice" (`POST /v1/calls/languages/score`; `src/jarvis/api/static/console-calls-langs.js`) | a mean of 4; until scored, "not yet heard by a native speaker" |
| The brain | a 10-turn mock call per language with the safety cases (`brain_turns` in the bars) | **not built**: never fails a language (chapter 12, section 6) |

English before its first check is offered "not yet checked" on the first cloud option set up
(ADR-34); every Indian language needs a pass. FLEURS has clips for English and 14 of the 22
scheduled Indian languages only (`src/jarvis/calls/speech/catalogue.py`), so the other 8 can't be
checked and are never offered.

### 8.2 The calls eval

`evals/calls_language/` (`run.py`, `suites.py`, `harness.py`): five mock suites with no network,
no vendor and no model, every gate hard (100 %), each with a negative control that must fail
it. Run by `evals/run_all_mock.py` and in CI by `tests/test_evals_calls_language.py`.

| Suite | Cases | Negative control |
|---|---|---|
| `scoring` | the bars at their edges; the normaliser on Indian scripts | the bars switched off |
| `phoneline` | speech frequencies kept, what a phone can't carry cut, the codec's known codes | a "phone line" that changes nothing |
| `selection` | the option order (laptop, Google, Azure, Bhashini, Sarvam only when on), the balanced tier only with his YES, a stored pass re-read against the bars | the order reversed |
| `free_first` (R18 review) | the app's own choice, `src/jarvis/calls/cards.py:offered` with `Estimator.free_options`: Google while its free allowance covers the call, before cheaper paid Sarvam; with the allowance used, the cheapest paid option he allows; Sarvam off, never; Azure's free tier before paid Sarvam; an unknown price (Bhashini) after a known one, never as free | ranking by list price alone (the first build's ranking) |
| `check` | the whole check on scripted options: passes stored; lost numbers, slow replies, no clips and a low score fail in plain words; a paid plan refused before any ₹; Sarvam off not run | the ₹ gate bypassed |

The plan's other suites (mock calls, safety, gates, the call desk, costs: plan section 11) were
built as unit tests, not as eval suites (section 8.3). The `selection` suite tests the language
check's own order (`src/jarvis/calls/langcheck/select.py:choose`, the first passing option); the
joined app chooses a call's option with `offered` (free now first, then the cheapest). This
edition first found that the eval did not run that choice; the combined review added the
`free_first` suite for it (`evals/calls_language/suites.py:suite_free_first`;
`docs/plans/r18-integration/REVIEW.md`, item 24: 6 of 6 cases pass and the control fails, as it
must). Unit tests cover the same choice (`tests/test_calls_cards.py`, `tests/test_r18_i1_join.py`).

### 8.3 The tests

| Where | Files | Count | Covers |
|---|---|---|---|
| `tests/test_calls_*.py`, `tests/test_calldesk_*.py`, `tests/test_r18_*.py`, `tests/test_evals_calls_language.py` | 59 | **1,027** collected items (`pytest --collect-only` on the R18 release branch at `c036ca1`, 27 Nov 2026; 56 files and 1,003 items before the review's last fixes) | cards, approvals and the grant, limits and quiet hours, records and objection, retention, booking, answering, the engine and the reply guard (OTP, payment, injected instructions), captions and summary, the hub and its sockets, speech adapters and metering, the language check, the call desk (micguard, watchdog, kit, link), the phone's commands, the I0 seams, the I1 join, the combined review's fixes (masking, Privacy rows, routes, Telegram, the approvals seal, the deploy's speech keys, outfit plans kept 90 days) |
| `tests/browser/test_r18_*.py` | 5 | 31 test functions (static count) | the Calls panel and its look, the ways into Calls at 1920 px, the review's console fixes and its visual gate at 1920 and 2560 px, Night and Day (`tests/browser/test_r18_review_look.py`); with `tests/browser/test_dock_fit.py`'s pixel comparison of the 1920 px bar with the bar before R18 |
| Android `core` | `CallMachineTest.kt`, `CallsTest.kt` | not counted here | the call state machine and command verification against the shared vectors |

The figure of 19,530 collected items in section 1 was measured before R18 and was not re-measured
for this edition. *Unverified here:* real Phone Link, Windows sound and Bluetooth, the PowerShell
scripts, the Android build on a phone, FLEURS clips from Hugging Face and Bhashini; none of them
can run in this environment (`docs/plans/r18-integration/I1-NOTES.md`, 4.7).

## Change log

| Version | Date | Release | What changed | By |
|---|---|---|---|---|
| v6.4.1 | 27 Nov 2026, 16:45 IST | R6.4 | First edition: test counts measured (19,530 collected unit items, 1,207 browser test functions, 5 emulator files) and grouped; the 95 % coverage floor; evals, controls and the Phase 0 gate; every CI job and what the deploy waits for; the documentation checks and their gaps; the Build Book's build-time generation; the release process and versioning | 🛠 Mark XXV |
| v6.4.2 | 27 Nov 2026 | R6.4 | Verification (chapter 13): the eval folder count corrected to 46; the test-file count's two figures explained; the per-group test counts marked unverified; the version check now covers this document (F3 closed); the SDK boundary test and the traceability generator added to the documentation checks | 🛠 Mark XXV |
| v6.5.0 | 27 Nov 2026, 20:25 IST | R18 | R18 "Calls from your laptop": the calls' quality in plain words; 47 eval folders and 33 eval test files; the Android workflow's R18 vectors and two controls; the program version with R18; new section 8: the language check's bars (the brain step not built; 8 languages without FLEURS clips), the `calls_language` eval's four suites and controls, R18's tests (56 files, 1,003 items; 4 browser files, 29 functions) and what can't be tested here | 🛠 Mark XXV |
| v6.5.1 | 27 Nov 2026, 21:25 IST | R18 | The R18 review's later fixes: the calls eval has five suites, the new `free_first` testing the app's own choice (its control: ranking by list price), so v6.5.0's gap is closed; R18's tests re-counted at `c036ca1` (59 files, 1,027 items; 5 browser files, 31 functions); where voice scores are entered | 🛠 Mark XXV |
