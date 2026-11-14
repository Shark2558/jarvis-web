Version v14.0.2 · 15 Nov 2026, 00:50 IST · Release R14 · Status: Current · Owner: 🛠 Mark XIX

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
6. **A browser test race** (`test_notes.py`, two reads of the fake's PATCH log without a wait), seen
   only in the full run on 2 busy CPUs: fixed in the test (section 7).

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
`./src`, `.`, `*`, the worktree's own path, a parent-path spelling are all refused; the integrated
review then found `rm -rf ../*` and the usual wrappers still passed: section 11). Tests first:
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
| 5 | Browser suite, whole (`i1-browser.log`) | **1,367 passed, 2 failed** in 97 min at `1e3ac36`, both load-only (each file re-run alone: 42 passed): `test_notes.py::test_editing_an_outside_note_asks_before_taking_it_as_mine` was a test race (it read the fake's PATCH log straight after the click; the same file's `_posted` helper waits for exactly this): fixed at the cause with a waiting `_patched` helper for both such reads (`test_notes.py` re-run: 15 passed); `test_media.py::test_keyboard_focus_stays_in_the_maps_section[desktop]` (focus on BODY right after Enter on Set Home and Work) could not be reproduced (alone, and 4 times under two busy loops: all passed) and its cause is not proven; `console-media.js` is untouched by R14 (section 10) |
| 5 | New browser tests with the optional libraries blocked | `tests/browser/test_r14_d_console.py` (R14's only new browser file) with PIL, numpy, cv2, aiomqtt, paho, onnxruntime, scipy and pandas refused at import (a meta-path blocker): **4 passed** |
| 6 | Screenshots (`scripts/ui_snapshots.py --out /tmp/r14-logs/i1-shots`) | **260 shots, 0 page errors, 0 failures** (`/tmp/r14-logs/i1-shots`); the layout checks find the same 12 screens with the same findings as `r14-i0`. Pixel diff against a fresh `r14-i0` set (`/tmp/r14-logs/i0-shots`) and a second I1 set as the noise floor: beyond noise only the Privacy panel's lower screens (R14's three server-sent rows, in the existing card style) and three capture-state differences (a sub-pixel shift, a focus glow, a button's transition), looked at side by side: **the look is unchanged** |
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
5. **The `needles` eval (the plan's "Needles (I1)") is built** after the integrated review (M5):
   it is part of the gated R14 runner, and the runner now fails any part still a stub (see
   "Integrated review follow-ups").
6. **The restore-drill card is approved in the console only** (the Workshop's decision on the
   integrated security review's M4): `core.guardrails.CONSOLE_ONLY_TOOLS = {vitals_drill_start}`;
   Telegram never offers it Approve/Decline buttons, however short its words (157 characters, under
   the 240 that get one tap), says plainly that it waits in the console under Approvals, raises the
   usual "approval waiting" alert, and refuses an old or forged button for it
   (`tests/test_r14_i1_telegram_drill.py`).

## 10. What can't be verified here

Every Google call (plan "What can't be verified"; INTEGRATION-A 10, B 7, C 6, D 5); the persona and
voice evals on a real model for p14.0 (D14: real runs, keys); whether Google sends `auth_time` for
this app; **verify live (integrated review LOW-1 / code L2): the `claims` authorize parameter is
always sent on a re-sign-in**: if Google rejected or errored on it, `/auth/login?reauth=1` would
fail, and with it the first passkey's set-up and the 24-hour reset. First step after the deploy:
one `/auth/login?reauth=1` round trip; if it fails, send `claims` only when a new setting is on
(the reviewer's `reauth_sends_claims`, default True); not built here, as nothing can try it; real token counts and ₹ by part (the ledger, after deploy); CI's coverage on its own
runners (here 95.50 %); the hook inside a real Claude Code session (tested by running the script as
the hook does); the cause of the one unreproduced browser flake
(`test_keyboard_focus_stays_in_the_maps_section[desktop]`, pre-R14 code), which CI's own browser job
will show again if it is a real race.

## 11. Integrated review follow-ups

The two integrated reviews of `e8ab86d` (`/tmp/r14-logs/review-r14-i1-security.md`: WARN, 0
critical, 0 high, 5 medium, 6 low; `review-r14-i1-code.md`: approve with 2 medium, 2 low), each
finding with its outcome. Every code change was test first (the test seen failing, then the fix).

| Finding | Outcome | Test (red before) | Commit |
|---|---|---|---|
| Security M1 / code M1: a glob in an rm target (`../*`, `/home/claude/wt/*`, `../r14-?`) read as "a whole worktree named `*`" | Fixed: a glob passes only where the folder above it is below `/tmp` or a scratch folder, with no `..` after it | `tests/test_claude_guard.py` (76 new rows red before; 303 pass) | `a26c9a1` |
| Security M2: `bash -c`, `sh -c`, `eval`, `xargs rm`, `find -delete`, `git clean -fdx`, `pushd`, `( )`, `cd ~`, `cd -P` bypassed the rm rule | Fixed in the hook (each judged; a `cd` it can't follow makes later relative targets unknown, so refused); malformed input still passes; every BRIEF-COMMON and Workshop-brief command still passes. The plan (D18, Risks) and the hook's docstring say plainly it is a guard rail for agents, not a sandbox (`python -c`, scripts, a pipe into `sh`, variables, symlinks are out of its reach); CLAUDE.md unchanged | the same file | `a26c9a1`, `548b33d` |
| Security M3: with the AI off, mail subjects, senders and merchants were stored as the assistant's own words | Fixed at the window, for every brain: a No-AI reply made from tools (`model` = `core.models.NO_AI_MODEL`, `tool_derived`) is sent whole inside an outside-content fence, its content defused, with an id from the turn's id (the same text each time: the cache prefix holds), counted in the window's budget. What is stored and shown stays plain, so a reload shows him no markers. Only No-AI tool replies: fencing every `tool_derived` turn (the model's own replies after tools) would change what every model reads of its own words and needs the real-model evals; not tainting the round either, as before I1 (a No-AI read of his own groceries would make every later write a card) | `tests/test_r14_i1_noai_fence.py` (5 of 7): a hostile subject through the real inbox tool, the Brain, the AI back on; a forged END marker; the cap | `e8b3cd9` |
| Security M4: the drill card got Telegram's one-tap buttons | **Workshop decision: console only.** `core.guardrails.CONSOLE_ONLY_TOOLS = {vitals_drill_start}`: never buttons on Telegram, "Approve it in the console, under Approvals…", the usual alert, an old or forged button refused (section 9, item 6; plan D4; guide C66) | `tests/test_r14_i1_telegram_drill.py` (2 of 5) | `22b6e6c` |
| Security M5: the needles eval was I0's stub reporting `passed: True` | Built to the review's spec (section 7 and the plan's "Needles (I1)" row): one simulated day of the four parts, nine needle classes in five forms, four sinks, the rules, a positive control per sink, the negative control failing exactly the three document cases. Google's backup name is also kept by a running drill's own `backup_drill/current.run` (`backup`, `operation`: it needs them between ticks, cleared when it ends); the eval allows exactly those fields and checks they are cleared. The runner now fails any part still a stub | `tests/test_r14_seams.py` (red on the stub) | `284f3d0` |
| Code M2: his questions about JARVIS itself got only the core tools | Fixed: 21 words in the `vitals` group (no bare "clock" or "health"); the 7 phrasings in the labelled set (129, recall 100 %); a held-out set of 8, written before the words, reported not gated: 2/8 before, 5/8 after | `tests/test_r14_i1_offer_recall.py` (11 red); the eval's recall red at 94.6 % | `2cc6f57` |
| Code L1: C68 said 136 tools | Fixed: 139, 9.7 offered on average, recall on 129, the second held-out set (guide v14.0.3) | — | `7a055d5` |
| Security LOW-1 / code L2: `claims` always sent | Recorded as **verify live** (section 10) | — | — |
| Security LOW-2: the Telegram reads | No change needed; the guard list's comment now says `vitals_backups`' rupee figure is JARVIS's own cost, not his money | — | this commit |
| Security LOW-3: notes written to the model shown with the AI off | Fixed: `offline/said.for_him` drops a note's sentences written to the model ("the owner", "do not say", "tell him", a field name in backticks); his own sentences stay | `tests/test_r14_i1_said.py` (2 of 3) | `7a055d5` |
| Security LOW-4: chat links and `?authuser=` | `?authuser=3/4` taken out of the plan's links. The `Claude-Session` lines in the BRIEF files stay (the standard trailer line the rules allow; the Workshop's call) | — | `7a055d5` |
| Security LOW-5: no per-route limit on the four status reads | Fixed: each 30 a minute per owner (`api/r14_status.read_limited`, per process like the drill route's), a 429 with `no-store` and `Retry-After` | `tests/test_r14_i1_route_limits.py` (4) | `7a055d5` |
| Security LOW-6: detail notes | No change needed (the reviewer: fine); the needles eval keeps the backup name out of logs, alerts and routes, and documents the code-only logger-name rule (50 kept) | the needles eval | `284f3d0` |

## 12. Checks after the follow-ups (logs `/tmp/r14-logs/fix-*.log`)

| Check | Result |
|---|---|
| Unit suite, Python 3.12, whole, with coverage, at `7a055d5` (`fix-unit-312.log`; `d42d64c` after it changed docs and a test comment only) | **15,928 passed, 134 skipped, 0 failed** (25:43) |
| **Coverage** (statements of `jarvis`, 3.12; `scripts/coverage_floor.py`) | **95.50 %** (69,966 of 73,260); pass at the floor 95 |
| Unit suite, Python 3.11, whole, at `d42d64c` (`fix-unit-311.log`) | **15,929 passed, 133 skipped, 0 failed** (15:58) |
| `ruff check` / `ruff format --check` (src tests evals scripts) | clean (1,745 files) |
| `mypy src` (`fix-mypy.log`) | **1 error**, the baseline `memory/redis_store.py:67` (772 files) |
| `evals/run_all_mock.py` on 3.11 (`fix-evals.log`) | **ALL MOCK EVALS: PASS** (42 suites); phase0's smoke fails its same 8 cases by design; `r14 (gated)` **108/108**: backup 14, selfwatch 13, offer 10 (held-out note 5/8), noai 41, needles 21, contract 9; the combined control fails the suite, each part failing its own cases (needles exactly `documents_backup`, `documents_ledger`, `documents_selfwatch`); also 108/108 on 3.12 |
| `scripts/arch_coverage.py` | OK: 65 packages and modules, 90 console modules, 2 Scheduler jobs, 30 outside services, 106 collections |
| `scripts/check_doc_versions.py` | all 28 documents pass (plan v14.0.4, guide v14.0.3, these notes v14.0.2) |
| `scripts/markdy_export.py --check` (on a `/tmp` export of `d42d64c`, after `npm ci`) | 14 diagrams, 0 problems |
| `scripts/check_pr_title.py "v14.0.0 · R14 Free hardening · Mark XVIII–XIX"` | OK |
| `python -m jarvis.buildbook.gen --check`, twice | the book is **R14** (`d42d64c`): book.json 182,037 bytes, source.zip 7,791,652 bytes; each run's two builds byte-identical, and the two runs' outputs identical (`cmp`) |
| Browser files that touch chat, Telegram, No-AI, approvals and the visual gate (`JARVIS_BROWSER_TESTS=1`; `test_ui_audit`, `test_r14_d_console`, `test_console`, `test_telegram`, `test_approve_all`, `test_systems_check`, `test_offline`; `fix-browser.log`) | **189 passed, 1 failed**: `test_approve_all.py::…leaves_the_other[phone]` read the list's count straight after the bar hid; the bar hides once fewer than two cards can be batched, which can be before the list has re-rendered (load only: 9 of 9 alone). Fixed in the test (it waits for the list to settle); re-run: 3 passed five times, once under two busy loops. No console file changed in R14's follow-ups; the whole browser suite is CI's |
| Sizes | `app.py` 727 (≤ 735), `gateway.py` 760 (≤ 760), `brain.py` 713 (≤ 741), `console.html` 782 (≤ 782), largest `console*.js` 769 (≤ 800); `said.py` 323, `core/window.py` 221, `telegram/service.py` 547, the hook 748, `evals/r14/needles*.py` 385 / 350 / 287 |

## Change log

| Version | Date | Release | What changed | By |
|---|---|---|---|---|
| v14.0.1 | 14 Nov 2026, 21:30 IST | R14 | First edition: the four merges (no conflicts), every Needs I1 item with its outcome and commit, the defects found at the join (No-AI's JSON answers of the real tools, the drill card's line, the offer's effect on two pins, the errors handler outliving its app, the window's setting), every pin changed and why, the hook fix, the docs, the checks with their numbers, the sizes, the decisions taken, what can't be verified | 🛠 Mark XIX |
| v14.0.2 | 15 Nov 2026, 00:50 IST | R14 | The integrated review follow-ups (section 11): each finding with its outcome, test and commit (the hook's globs and wrappers, the fenced No-AI turn, the drill card console only, the needles eval built, the Vitals words, the route limits, the notes to the model, the guide's count, the links); LOW-1 as verify live; decisions 5 and 6; the checks after the follow-ups | 🛠 Mark XIX |
