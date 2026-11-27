Version v6.4.1 · 27 Nov 2026 · Release R6.4 · Status: Current · Owner: 🛠 Mark XXV

# 13 · Verification of the design document

**In plain words.** A second reader, who did not write chapters 00–12, checked them on 27 Nov 2026
against the code on branch `arch-design` (the code of `main` at `83331a1` plus the document) and
against the requirements workbook. Wrong statements were corrected in place, each chapter got a new
version and a change-log row, and what can't be checked from the repository now says
*Unverified* and why. This chapter says how the checks were made, what they found, every fix, what
is still unverified, and how to run the checks again. Nothing under `src/jarvis/` was changed:
where the code itself looked wrong or differed from its plan, chapter 12 records it.

## 1. What was checked and how

| Check | How | Evidence |
|---|---|---|
| Every repository citation (a path, `path:Symbol` or `path:LINE` in backticks) | A script reads each chapter's code spans; a path must exist (globs must match); a Python symbol must be a top-level name or `Class.member` in that file's syntax tree; a line number must be inside the file | `scripts/docs/adds_citations.py`, `tests/test_adds_citations.py` (new) |
| Every number, limit, default, price, schedule and retention period in chapters 00–08 | Read from the code itself: the settings' defaults and constants imported in Python, the deploy script and the workflows read line by line (the workflows as YAML), and the tools below re-run | `src/jarvis/config.py:Settings`, the modules each chapter cites, `deploy/cloudrun.sh`, `.github/workflows/ci.yml` |
| The counts the chapters quote | Re-run: `pytest --collect-only -q` at `83331a1`, `scripts/skill_coverage.py`, `scripts/arch_inventory.py`'s inventory, `mypy src`, `git ls-tree` of `evals/` | section 2 |
| Firestore collections | The inventory's 126 names, the 5 more chapter 04 names, compared name by name with chapter 04's table; then an independent scan of every string passed with a prefix in a call, which found no further top-level name | `scripts/arch_inventory.py`, `src/jarvis/backup/walk_checks.py:KNOWN_SUBCOLLECTIONS` |
| Chapter 09's tables and chapter 10's matrix | Every figure re-counted from the workbook's Requirements sheet by a script; every one of the 215 Done rows' pointers read against the row's full feature text and the code | `scripts/docs/adds_traceability.py` |
| Claims about history (why and when) | The plans in `docs/plans/`, the deploy files, this clone's git history (shallow: it starts on 18 Nov 2026) and GitHub's commit history through its REST API | GitHub commits named in section 3 |
| Plans of releases being built | Read from their branches, since they are not in `main` | `git show origin/r18-a1:docs/plans/r18-calls.md`, `git show origin/r5-2-plan:docs/plans/r5-2-voice.md` |
| The diagrams 15–17 | Their text read against the chapters (nothing to change); Markdy's own checks in the final pass | `docs/architecture/diagrams/1[5-7]-*.markdy` |

The workbook is not in the repository (git tracks no `.xlsx`); it was read from the Workshop's
working folder, and only its Serial, Phase, Module, Feature, Type, Status and Release columns were
used. Its remarks never leave it.

## 2. The counts

| What | Count |
|---|---|
| Repository citations in chapters 00–12 as first written | 745 (6 did not resolve: 1 wrong symbol, 4 plan files that exist only on branches without saying so, 1 planned folder not marked planned) |
| Repository citations after this verification | 828 in chapters 00–12 (871 with this chapter's), 0 missing; 8 in 00–12 listed as kept elsewhere (6 plan references on the `r18-*` and `r5-2-plan` branches, 1 planned folder, 1 file the image build writes) |
| Numbers in chapters 00–08 outside code spans | about 1,000 (dates, counts, limits, prices, ADR, row and component numbers); every limit, default, price, count, schedule and retention period among them was traced to the code, a deploy file, a workflow or a plan |
| Figures in chapter 09's tables | all re-counted; 1 row wrong (the live releases) |
| The skill table in chapter 03 (11 skills: tools, R1, R2, R3, No-AI, R3 tool names, groups) | all re-derived from `scripts/skill_coverage.py`; all right |
| Statements fixed because they were wrong or incomplete (section 3, table A) | 21 rows for chapters 00–09, 11 and 12 (a row may fix the same statement in two chapters), plus 72 of chapter 10's pointers |
| Statements updated because this verification added a check or a task moved them (table B) | 8 |
| Items marked *Unverified* (section 5) | 8 |
| Chapter 10, Done rows | 215: 213 located (145 by a reviewed pointer, 68 by the test named after their use case), 2 not located with their reason, 0 "location not confirmed" |
| Chapter 10, pointers as first written | 186 located, 29 not; of the 186, 42 named the wrong file, 30 a weaker one than the file that carries the row, 59 a file that merely mentions the row's use-case id, 1 (row 31) a file for something else, and 54 were right |
| AI-SDK boundary across `src/jarvis/` | 0 imports outside `src/jarvis/llm/` (`tests/test_llm_sdk_boundary.py`, new); nothing marked to fail |
| Chapters passing the version-line check | 14 of 14 (00–13), now inside the check itself |

## 3. Every fix

**A. Statements that were wrong or incomplete.**

| Ch. | Claim | Was | Now | Evidence |
|---|---|---|---|---|
| 01, 07 | Eval folders | 47 | 46: 45 suites and `realrun` | `git ls-tree -d 83331a1:evals` |
| 02 | `SecretStr` fields in the settings | 13 | 11, one per secret, named | `src/jarvis/config.py` (13 lines name `SecretStr`: the import, a comment and 11 fields) |
| 05 | The same count | 13 | 11 | as above |
| 02 | APIs the deploy switches on | Maps and YouTube missing | Places, Routes, YouTube Data and API Keys in step 3 | `deploy/cloudrun.sh:setup_maps_key` (`MAPS_APIS`) |
| 02 | `render.yaml` | "left from the first hosting … and not used" | the README still lists it as the alternative host; nothing deploys it; the Cloud Run script came 17 minutes after it | `README.md`; GitHub commits `3e73d81`, `dc93f81`, `db109f3` |
| 08 | When hosting moved to Cloud Run (ADR-07 and the index) | "by slice 4 (*unverified* date)" | slice 2, 31 Oct 2026 (UTC), before slice 3 | GitHub commits `db109f3` (Cloud Run script) and `b7037c5` (slice 3's Gemini brain) |
| 03 | The cross-cutting layer's components | "C66–C68 (R14)" | C67 only (C66 is in L7, C68 in L5) | `docs/architecture/JARVIS-Architecture.md` (the cards' sections); `src/jarvis/buildbook/gen/layers.py:LAYER_OF` |
| 04 | The 5 collections the inventory misses | named, no lines; "the inventory should learn both idioms" | each with its lines; the fix also needs the Build Book's fact pack changed, which is app code | `src/jarvis/wardrobe/styling/part.py`, `src/jarvis/helpers/today/part.py`, `src/jarvis/buildbook/gen/facts_code.py:COLLECTION`, `tests/test_r63_a_facts_real.py` |
| 04 | Sub-collections | not listed | the 7 the stores use | `src/jarvis/backup/walk_checks.py:KNOWN_SUBCOLLECTIONS` |
| 04 | How long outfit plans are kept | "90 days after the event" | 14 days after their day, at most 60 (R13's plan said 90) | `src/jarvis/wardrobe/styling/plans.py:StylingDoc.pruned`, `BACK_DAYS`, `MAX_PLANS` |
| 05 | Strangers writing to the Telegram bot | "audited" | audited at most 20 an hour, then only logged | `src/jarvis/telegram/service.py:REJECTED_AUDIT_PER_HOUR` |
| 06 | Where a voice allowance is added | `add_units` cited as a function of the meter module (there is none) | `UsageMeter.add_units`, the method | `src/jarvis/billing/meter.py:UsageMeter.add_units` |
| 07 | Unit-test files | "846 with tests" | 846 with collected items; 848 define test functions | `pytest --collect-only -q`; a search for `def test_` |
| 09 | The live releases' row | 215 rows, 213 Done, 2 Pending | 213 rows, 209 Done, 4 Pending (rows 33, 35, 182, 183) | the workbook's Release and Status columns |
| 09, 11 | The R5.2 and R18 plans | cited as repository paths | named as files on the `r5-2-plan` and `r18-*` branches, not yet in `main` | `git ls-tree origin/r5-2-plan`, `git ls-tree origin/r18-a1` |
| 11 | R5.2's speech-kit folder | cited as if it existed | marked planned | no `deploy/local-speech/` on `main` or any of the 11 remote branches |
| 11 | Rows 35 and 386 under "Not placed yet" | no release | R1 (still Pending) and "Later" | the workbook |
| 12 | C1's source | "(decision 17)" | the R18 plan's own words for rows 195–197 | `docs/plans/r18-calls.md` on branch `r18-a1` |
| 12 | C6's resolution | "Proposed ADR-A" | resolved by ADR-01 | chapter 08 |
| 12 | What one instance keeps in memory | "sessions …"; a second instance "would split sessions" | conversations are in Firestore; the per-conversation lock, rate limits, nonce stores and the call hub are in memory | `deploy/cloudrun.sh` (header, `JARVIS_SESSION_BACKEND=firestore`); chapter 06, section 5 |
| 12 | The 300-second timeout | "Default deploy" | set by step 6 (`--timeout 300`) | `deploy/cloudrun.sh` |
| 10 | Done rows' pointers | 186 of 215 located, with wrong matches (row 19, web search, pointed at people research) | 213 of 215; 72 pointers replaced; 19 rows located for the first time; 68 use-case rows at their tests; 2 not located with their reason | section 4 |

**B. Statements updated because this verification added a check or moved a decision.**

| Ch. | What | Now |
|---|---|---|
| 01, 05, 07, 08 | "No check that only `jarvis.llm` imports a vendor SDK" (P7, residual risk 7, ADR-02, follow-up F1) | `tests/test_llm_sdk_boundary.py` checks every module under `src/jarvis/`; F1 closed |
| 00, 07, 08 | "The version-line check skips `design/`" (ADR-01, follow-up F3) | `scripts/check_doc_versions.py` reads `docs/architecture/design/*.md`; F3 closed |
| 08, 12 | The proposed ADRs A–G of chapter 12, section 5 | A was already ADR-01; B–G are ADR-25 (Accepted: the code runs one instance with its state in memory) and ADR-26 to ADR-30 (Proposed: none of them is in the code yet); chapter 12 keeps a one-line pointer, and chapters 05, 06 and 12 cite the new numbers |
| 12 | The R0 risk tier | conflict C10: only the slice 1 plan names an R0 tier; the code has three classes; no requirement row assumes R0 ("R0" in the workbook's Release column is the first release) |
| 12 | Debt found by this verification | four items in section 4 (the inventory, the SDK test's result, the README's Render line, the outfit plans' 14 against 90 days) |
| 09 | How chapter 10 locates a Done row; who adds a pointer | reviewed pointers, use-case tests, reasons; a newly Done row gets a reviewed pointer |
| 08 | Follow-up F2 | left open, with why: the fix spans a script and app code |
| 00 | The chapter list | chapter 13 added; how the document was verified |

The plain-word rewrites of the writer's own *unverified* markers (Cloud Run's concurrency and cold
starts, ADR-10's reason) are in section 5.

## 4. The traceability review (chapter 10)

Each Done row's full feature text was read against the code before its pointer was kept or
replaced. The generator now takes, in this order: a pointer reviewed against the code
(`OVERRIDES`, 145 rows, used only while the path exists); a reason for a row with no one place
(`NOT_LOCATED`, 2 rows); for a use-case row (INV-, LND-, STY-, OPS-, AVT-), the test named after the
use case (`def test_inv01_…`, `def test_lnd_14_…`; unit tests before browser tests), which imports
and proves the code, or else a test file that names the id (OPS-03); and only then the old word
match, labelled as a lead not yet reviewed. A pointer that no longer fits (the row is gone, is not
Done, or the path was removed) is reported when the generator runs.

| Outcome | Rows |
|---|---|
| A wrong file replaced | 42: rows 3, 4, 9, 10, 14, 19, 20, 24, 26, 30, 43, 51, 52, 53, 54, 70, 82, 101, 107, 109, 112, 117, 119, 138, 139, 145, 147, 149, 159, 164, 165, 166, 189, 205, 207, 213, 214, 283, 285, 287, 380, 392 |
| A weaker file replaced by the one that carries the row | 30: rows 1, 7, 11, 15, 21, 22, 23, 27, 28, 32, 34, 36, 38, 44, 76, 103, 106, 127, 135, 140, 146, 160, 161, 203, 209, 281, 282, 290, 381, 394 |
| Located for the first time | 19: rows 6, 37, 69, 71, 75, 77, 78, 88, 105, 111, 114, 115, 125, 126, 150, 163, 177, 215, 390 |
| Use-case rows now at their proving test | 68 (59 had a file that merely mentions the id, 9 had none) |
| Right as matched, now pinned as reviewed | 54 |
| Not located, with the reason in the matrix | 2: row 31 (a property of the whole console) and row 379 (R6.3's runtime writer, removed by R6.3.1) |

## 5. What stays unverified

| # | Item | Where | Why it can't be checked here |
|---|---|---|---|
| U1 | Cloud Run's default concurrency (80 requests an instance) | 02, 06 | Google's default; the deploy sets nothing and nothing reads it |
| U2 | How long a cold start takes | 06 | Never measured in the repository |
| U3 | Why hosting moved from Render to Cloud Run | 02, 08 (ADR-07) | Neither the commits (`db109f3`), the plans nor the deploy files say; only the date is known |
| U4 | Why there is no event bus | 08 (ADR-10) | No plan, commit or deploy file records it as a decision; the context is read from the code |
| U5 | The per-group test counts | 07 | The grouping rule was not recorded; a re-count by file name gives other sizes. The total, 19,530, is verified |
| U6 | That the workbook's home is the owner's Drive | 09 | Outside the repository; only that git tracks no workbook is verified |
| U7 | The "three months" of paper trading for R19 | 11 | No plan in the repository records a length |
| U8 | ₹100 a month as the low end for Claude replies | 06 | The writer's own estimate, waiting for the token ledger's week of data |

## 6. Left for the owner or a release

- **Follow-up F2** (the inventory's two missed idioms) needs `src/jarvis/buildbook/gen/facts_code.py`
  changed together with `scripts/arch_inventory.py`, because a test holds their counts equal. That
  is app code, so it was recorded (chapter 12, section 4), not done.
- **Outfit plans:** R13's plan keeps them 90 days after the event; the code keeps them 14 days
  after their day. Which one is meant is the owner's call (chapter 12, section 4).
- **The guide** (`docs/architecture/JARVIS-Architecture.md`, not part of this document) still dates
  the move to Cloud Run "by Slice 4 (*unverified*)" in its technology table; the date is now known
  (31 Oct 2026). Its next edition can take it.
- **The workbook** lives outside the repository, so CI can't regenerate chapter 10; the Workshop
  runs the generator at each release (chapter 09, rule 6).

## 7. How to run the checks again

From the repository's top folder, in a virtual environment with the project installed
(`pip install -e ".[dev]"`):

```bash
python scripts/docs/adds_citations.py                 # every cited path and symbol exists
python scripts/check_doc_versions.py                  # version line and change log, 00-13 included
python scripts/arch_coverage.py                       # the guide's coverage and the secret scan
python -m pytest -q tests/test_adds_citations.py tests/test_adds_traceability.py \
  tests/test_check_doc_versions.py tests/test_llm_sdk_boundary.py
python scripts/docs/adds_traceability.py WORKBOOK.xlsx --out /tmp/10.md   # compare with chapter 10;
                                                      # stale pointers are listed on stderr
PYTHONPATH=src python scripts/skill_coverage.py       # chapter 03's skill table
python -m pytest --collect-only -q | tail -1          # chapter 07's count (at 83331a1: 19,530)
mypy src                                              # chapter 12's one baseline error
npx -y @markdy/cli@1.5.7 lint docs/architecture/diagrams/15-containers.markdy --strict
python scripts/markdy_export.py --check               # every diagram's exports current
```

To regenerate chapter 10 after a release, pass the release's version line and what changed:
`python scripts/docs/adds_traceability.py WORKBOOK.xlsx --version-line "Version v… · …" --change "…"`;
the chapter's earlier change-log rows are kept.

## Change log

| Version | Date | Release | What changed | By |
|---|---|---|---|---|
| v6.4.1 | 27 Nov 2026 | R6.4 | First edition: the independent verification of chapters 00–12 against the code and the workbook: method, counts, every fix, the traceability review, what stays unverified, what is left for the owner, how to re-run | 🛠 Mark XXV |
