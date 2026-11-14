Version v14.0.1 · 14 Nov 2026, 21:30 IST · Release R14 · Status: Current · Owner: 🛠 Mark XIX

# R14 — I1 notes (the four parts joined)

Written by the R14 I1 integrator for the Workshop (🛠 Mark XIX) on `r14-i1`, cut from `origin/r14-i0`
@ `9eb9d8b`. The plan is `docs/plans/r14-hardening.md` (now v14.0.3); the parts' notes are
`INTEGRATION-A.md` … `INTEGRATION-D.md` (v14.0.2). Every behaviour change below was test first: the
test was written, seen failing, then the change made (`tdd-guide`). Nothing was rebased, stashed or
force-pushed; no pull request was opened; `main` and the part branches were not touched; the hook
blocked nothing.

## 1. The merges

All four with `git merge --no-ff`, in the brief's order, pushed after each:

| Part | Branch @ | Merge commit | Conflicts |
|---|---|---|---|
| A backups and the drill | `r14-a` @ `54cb846` | `efff284` | none |
| B self-health | `r14-b` @ `193f034` | `fda39ab` | none |
| C cost and the register | `r14-c` @ `9560c58` | `faba36a` | none |
| D No-AI pass 2, rows 101/102, leftovers | `r14-d` @ `db88223` | `8f8b895` | none |

No textual conflict: every file of a part is in its own row. Outside its row Part D also edits the
Google sign-in fakes of other releases' tests (`tests/book_app_fakes.py`, `tests/r7_fakes_c.py`,
five API tests): each fake now sends `auth_time`, as Google does once Session age claims is on; they
are tests of `api/auth.py`, so the edits follow D13 (1) (checked at the merge, kept).

## 2. Every "Needs I1" item

| Item | Outcome | Commit |
|---|---|---|
| **A #1** Approve all never runs the drill card (security HIGH-1) | Done: `core/guardrails.py` `NO_BULK_TOOLS = {START}` with `START` imported from the leaf `jarvis.backup.names` (no literal, no cycle); `PendingAction.bulk_ok` refuses it; A's strict xfail removed in the same commit (the test failed without the guard) | `cfd6548` |
| **A #2, C D, D #2** `TELEGRAM_SAFE` += `vitals_backups`, `skills_open`, `maint_service_request` | Done; the register's open reads now equal the guard's list with no R14 exemption (`tests/test_r14_skill_coverage.py`) | `95a0daa` |
| **A #3, B 5.1 a–c, C E, D 1** the seam pins | Done, merged into one built state (section 4) | `e3838b2` |
| **A #4, B 5.2** the tick-job lists | Done (section 4) | `e3838b2` |
| **A #5** `vitals_drill_start` in `SAID_BY_CODE` | Done, `START` imported; with the AI off the approved card says its own fixed line (before: "Done, Sir: Start a restore drill…", even off Firestore, where nothing starts) | `95a0daa` |
| **A #6, C A, D #4** persona p14.0 (the release blocker) | Done: C's five passages word for word (`_RULES`, `WEB_RULES`, `DRIVE_RULE`, `TOOLS_RULE` leading with D14's words, `MEDIA_RULES`); `VITALS_RULE` gains D14's backups line and D3's privacy change ("a thing he deletes leaves the live data at once and the backups within 7 days"); `HELPERS_RULE` gains D's service-request line. `PERSONA_VERSION = "p14.0"` with its header note. C's A3 rewrite of `test_tools_not_offered_persona.py`, C's A4 seam test (fails if `tool_offer` defaults to "by_skill" while a bullet about an offered tool lacks `skills_open`), new `tests/test_r14_persona.py`; the 20 version pins in 18 files moved p7.0 → p14.0 (22 lines with the two rewritten) | `9dd87cb` |
| **A #6** card C66, §8, the plan's cost row | Done (section 6) | `84e84eb`, `eac5a2b` |
| **A #7** the hook gap | Done (section 5) | `87afe72` |
| **A #8** the honest limit (restoreAdmin is project-wide) | Done: the plan's Risks and card C66 | `eac5a2b`, `84e84eb` |
| **B 5.1 d** the errors-handler test (order-dependent) | Fixed at the cause, not pinned: the lifespan takes the app's own errors handler off the root logger at shutdown (`r14_wiring.remove_log_handler`, one line in `app.py`); the test passes unchanged in any order. A new test saw the handler left behind first | `e3838b2` |
| **B 5.4** card C67 | Done | `84e84eb` |
| **C B** `_window_for` passes `tool_result_chars` | Done (+3 lines, `brain.py` 710 → 713, guard 741); a Brain test with the setting at 600 saw the old results cut at 2,000 first | `44b639c` |
| **C C** the catalogue as package data | Done; a test fails for any tracked runtime data file under `src/jarvis` the wheel would not carry (it named only the catalogue). The built wheel and sdist both list `jarvis/skills/catalogue.json`; the register loads it from the unpacked wheel (11 skills, 40 groups) | `44b639c` |
| **C F** card C68 and §9 | Done; §9 says what the ledger covers (chat replies only) and that its Claude figures are rewritten after a week of ledger data | `84e84eb` |
| **C G, D's hook note** | The same gap as A #7 | `87afe72` |
| **D #3** `maint_service_request` under Task | Done: it was filed only through `maint_*`; now named in Task's household group; the catalogue's `planned` list is empty (every R14 tool is built; a test pins it, so a rename can't hide there) | `95a0daa` |
| **D #5** `reauth_requires_auth_time` | Done: a typed `Settings` field, default False (`config.py` 722 → 729); `api/auth.py` reads it instead of `getattr` | `36f17c5` |
| **D #6** the stale sign-in wording | Done, text only (`console-permissions.js:404`, its comment on line 10, `console-book.js:370`); a test of both files failed first; the old wording pin in `test_permissions_console.py` moves with the words | `05d5683` |
| **D #7** No-AI answers of the real tools | Done at the cause, wider than D could see (section 3) | `19c4932` |
| **D #8** the moved fakes | Nothing to do (noted) | — |
| **Brief 2.9** the release eval gate | Already gated by I0 (`("r14 (gated)", …, True)`); the whole runner now has A, B, C, D built, each control failing its part (section 7) | — |

## 3. Defects found at the join

1. **No-AI answered with raw JSON (D #7, much wider than one tool).** Run through the REAL tools
   (each family on its own release's fakes), D12's rows for groceries (list, add, remove), the
   vault, things (where and put), parcels, the inbox summary, Recently deleted and memory answered
   him with compact JSON, EXTERNAL CONTENT fence markers and all; `home_arm` read him the model's
   own instruction ("Do not say the home is armed yet"); `home_status` dropped the alarm state
   when the laptop was off. D's tests and eval run on fakes that return `message`, so they could
   not see it. Fixed at the cause, the No-AI renderer, which knew only four generic keys:
   `jarvis.offline.said` holds one fixed-template sayer per tool, reading the tool's own result
   fields and a fence's inner words only (never its markers); a shape it doesn't know, or a sayer
   that raises (logged by class name), falls back to the generic line. The tools' results, and so
   what the model sees and pays for, are unchanged (adding a `message` to each tool, D's
   suggestion, would have doubled those tokens and broken every existing result pin).
   `tests/test_r14_i1_noai_real.py` (9 cases, all red before) and `tests/test_r14_i1_said.py`
   (23, `said.py` at 100 %).
2. **The drill card's approved reply said "Done, Sir: Start a restore drill…"** with the AI off,
   even off Firestore where nothing starts (A #5 fixed it).
3. **C's offer changed what a bare "hello" is offered**: two older tests asserted that every tool
   reaches the model on any message (`test_deleted_api`, `test_documents_api`). Behaviour truly
   changed (D9): their pins now use words that name the group ("undo … restore my meeting", "the
   attached document").
4. **B's errors handler outlived its app** (B 5.1 d): fixed at the cause (section 2).
5. **The Brain ignored `history_tool_result_chars`** until C B was applied (2,000 whatever the
   setting said).

## 4. Pins changed, and why (each only where behaviour truly changed)

| Pin | Why |
|---|---|
| `test_r14_seams`: the parts' ready words on every status route (backup "off: not on Firestore" in the dev app, selfwatch "on", skills and noai "ready"); the drill route 409 `no_conversation` (no longer 501); the privacy rows `backups`, `selfwatch_told`, `token_ledger`; the runner (A–D cases, every control failing its part) | All four parts are built |
| `test_r14_seams`: I0's "persona left alone until I1" → C's A4 seam test; I0's "cards planned" → built cards and "backups exist" | p14.0 and the guide changed at I1 |
| `test_r2_wiring` (2), `test_r4_wiring` `R11_JOBS`, `test_r11_wiring` (2), `test_r51_wiring` | A's `backup_canary`, `backup_drill` and B's `selfwatch_daily` come last on the tick in `PARTS` order; B's `selfwatch_clock` runs first on the shared 5-minute clock |
| 20 `PERSONA_VERSION == "p7.0"` pins (18 files) → `"p14.0"` | The persona changed |
| `test_tools_not_offered_persona.py` rewritten (C A3) | Its point (not offered = not connected) is what p14.0 changes |
| `test_r14_skill_coverage`: no R14 exemption from `TELEGRAM_SAFE` | The three tools are built and named there |
| `test_r14_a_part`: the strict xfail removed | A #1 landed |
| `test_permissions_console`: the stale wording | D #6 changed the words |
| `test_deleted_api`, `test_documents_api`: the message | C's offer (D9) |
| `test_claude_guard`: the blocked table runs from the main checkout's place | The hook now judges a worktree on its own terms (section 5) |

## 5. The hook fix (builder A's finding)

`.claude/hooks/guard.py` allowed `rm -rf` of anything under `/home/claude/wt/` and
`.claude/worktrees/`, so inside a Workshop worktree a relative `rm -rf src` (or `tests`, `.git`,
`docs`) resolved under an allowed root and passed. Now `rm` with recursive and force flags may
remove: anything below `/tmp`; a whole worktree (the innermost `/home/claude/wt/<name>` or
`…/.claude/worktrees/<name>`), but never the one the command stands in; and a scratch folder
(`build`, `dist`, `tmp`, `.tmp`) of the current folder or of a worktree (`build` and `dist`
themselves too; before, only what was below them). Paths are normalised first (`build/../src`,
`./src`, `.`, `*`, the worktree's own path, a parent-path spelling are all refused). Tests first:
the nine rm cases now run from the main checkout's place, a `/home/claude/wt` worktree, a nested
`.claude/worktrees` one and this checkout (ROOT, whatever it is in CI), with more spellings (33
failed before the fix), plus a table of what must still pass (154 cases in the file, all green).
Security self-review (no reviewer agents were started, per the brief): no tracked folder is named
`build`, `dist` or `tmp`; a symlink planted at `build` pointing into the tree and removed with a
trailing slash is outside this hook's model (D18: not a security boundary). Checkouts under `/tmp`
are still wholly scratch, by design. The hook never blocked an edit of itself.

## 6. Docs

- **Plan v14.0.3:** the cost row ≈ ₹4.9 → ≈ ₹3.8 at 100 MB, and every owner-facing round figure
  "about ₹5" → "about ₹4" (as the set-up script prints; 14 days ≈ ₹6, not ₹7); D13 (1) met only
  partly (Google sends `auth_time` only when published, verified, Session age claims on and the
  `claims` parameter asks; the optional setting); D18's rm rule as rebuilt; A #8's honest limit.
- **Guide v14.0.2:** C66, C67, C68 PLANNED → built with the INTEGRATION files' facts; page 1, §6.6
  and §10 no longer say "no backups"; §8 the backups paragraph and "Restoring for real" (A's
  runbook); §9 the backups row and what the ledger measures; the three "Knowledge Base & Memory"
  skill rows relabelled (D11); `offline/said.py` and p14.0 on C68; the edition line, the check note
  and the change log.

## 7. Checks (in the brief's order; logs `/tmp/r14-logs/i1-*.log`)

| # | Check | Result |
|---|---|---|
| 1 | Unit suite, Python 3.12, whole, with coverage, at `eac5a2b` (`i1-unit-312.log`) | 15,743 passed, 134 skipped, **2 failed**, both of the join and fixed in `1e3ac36` (`test_documents_api`: C's offer, as `test_deleted_api`; `test_r14_i1_join`: imported `conftest`, which in a full run is `tests/browser/conftest.py`); the two files re-run green with the browser conftest collected (31 passed) |
| 1 | **Coverage** (statements of `jarvis`, 3.12) | **95.50 %** (69,914 of 73,209; I0 95.33 %); `scripts/coverage_floor.py`: pass at the floor 95 |
| 1 | Unit suite, Python 3.11, whole, at `1e3ac36` (`i1-unit-311.log`) | **15,746 passed, 133 skipped, 0 failed** |
| 2 | `ruff check` / `ruff format --check` (src tests evals scripts) | clean (1,739 files) |
| 2 | `mypy src` (`i1-mypy.log`) | **1 error**, the pre-existing `memory/redis_store.py:67`: the new baseline (C fixed the 8 in `core/window.py` and `llm/anthropic_provider.py`) |
| 3 | `evals/run_all_mock.py` on 3.11 (`i1-evals.log`) | **ALL MOCK EVALS: PASS** (42 suites); phase0's smoke fails by design (the same 8 cases as at I0); `r14 (gated)` **87/87**: backup 14, selfwatch 13, offer 9, noai 41, contract 9, needles 1 (I0's stub); the combined control fails the suite, each of A, B, C, D and the contract failing its own cases |
| 4 | `scripts/arch_coverage.py` | OK: 65 packages and modules, 90 console modules, 2 Scheduler jobs, 30 outside services, 106 collections |
| 4 | `scripts/check_doc_versions.py` | all 28 documents pass |
| 4 | `scripts/markdy_export.py --check` (on an export of `1e3ac36` under `/tmp`, after `npm ci`: `tools/markdy/node_modules` is not git-ignored, so not installed in the worktree) | 14 diagrams, 0 problems |
| 4 | `scripts/check_pr_title.py "v14.0.0 · R14 Free hardening · Mark XVIII–XIX"` | OK |
| 4 | `python -m jarvis.buildbook.gen --check`, twice | the book is **R14** (`1e3ac36`): book.json 181,913 bytes, source.zip 7,747,781 bytes; each run's two builds byte-identical, and the two runs' outputs identical (`cmp`) |
| 5 | Browser suite, whole (`i1-browser.log`) | BROWSER_RESULT |
| 5 | New browser tests with the optional libraries blocked | BLOCKED_RESULT |
| 6 | Screenshots (`scripts/ui_snapshots.py --out /tmp/r14-logs/i1-shots`) | SHOTS_RESULT |
| 7 | Sizes | section 8: every guard holds |
| — | Wheel and sdist (C C) | both list `jarvis/skills/catalogue.json`; the register loads it from the unpacked wheel |

## 8. Sizes

| File | Lines | Guard |
|---|---|---|
| `src/jarvis/api/app.py` | 727 | ≤ 735 |
| `src/jarvis/tools/gateway.py` | 760 | ≤ 760 |
| `src/jarvis/core/brain.py` | 713 | ≤ 741 |
| `src/jarvis/api/static/console.html` | 782 | ≤ 782 |
| every `console*.js` (90) | largest `console.js` 769 | ≤ 800 |
| `src/jarvis/config.py` | 729 | < 800 |
| `src/jarvis/offline/said.py` (new) | 309 | ≤ 400 |

## 9. Decisions taken for the owner (safe defaults)

1. **No-AI words live in the renderer, not in each tool** (section 3): the model's tokens and the
   tools' results stay as they were.
2. **The service-request line sits in `HELPERS_RULE`**, beside "You never pay anyone", not in
   `TOOLS_RULE` (D offered either; `TOOLS_RULE` is about tools not offered, and C's seam test reads
   those bullets).
3. **The errors handler comes off at shutdown** rather than being cleared in a test.
4. **The hook also refuses removing the worktree you stand in** (what the case
   `ls; rm -rf ../jarvis-web` means from inside a checkout), and allows `build`/`dist`/`tmp`
   themselves.
5. **The `needles` eval (the plan's "Needles (I1)") is not built**: the brief's item 9 names A–D;
   it stays I0's passing stub, so the runner reports `needles:not_built_yet`. The Workshop decides
   whether it is a merge gate.

## 10. What can't be verified here

Every Google call (plan "What can't be verified"; INTEGRATION-A 10, B 7, C 6, D 5); the persona and
voice evals on a real model for p14.0 (D14: real runs, keys); whether Google sends `auth_time` for
this app; real token counts and ₹ by part (the ledger, after deploy); CI's coverage on its own
runners (here 95.50 %); the hook inside a real Claude Code session (tested by running the script as
the hook does).

## Change log

| Version | Date | Release | What changed | By |
|---|---|---|---|---|
| v14.0.1 | 14 Nov 2026, 21:30 IST | R14 | First edition: the four merges (no conflicts), every Needs I1 item with its outcome and commit, the defects found at the join (No-AI's JSON answers of the real tools, the drill card's line, the offer's effect on two pins, the errors handler outliving its app, the window's setting), every pin changed and why, the hook fix, the docs, the checks with their numbers, the sizes, the decisions taken, what can't be verified | 🛠 Mark XIX |
