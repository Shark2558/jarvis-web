Version v11.1.2 · 12 Nov 2026, 06:35 IST · Release R11.1 · Status: Current · Owner: 🛠 Mark XV

# R11.1 — the common builder brief (Parts A–D)

Read this, then the plan `docs/plans/r11-1-observations.md` (the root causes, your part's decisions
and tests), then `CLAUDE.md` and `.claude/rules/ecc/common/*.md`. You build ONE part, in parallel with
three others, on your own branch from `r11-1-i0`. Everything you may touch is listed below; everything
else is someone else's. When in doubt, don't edit: write it in your `INTEGRATION-<PART>.md` for I1.

## 1. Your branch, your commits

- Worktree and branch: `r11-1-a` (A · Brain and calendar), `r11-1-b` (B · Voice and files), `r11-1-c`
  (C · Photos, faces and the home kit), `r11-1-d` (D · People, pictures and Vitals), each from
  `origin/r11-1-i0`. Push after every commit. Never force-push, `rm -rf`, `git stash`, or edit lint /
  format / type-check configs to make an error go away. Never touch `main`, `r11-i1`, `r6-1-i1` or
  another part's branch.
- Conventional commit messages (`feat(r11.1): …`, `fix(r11.1): …`, `test(r11.1): …`), each ending with
  exactly these trailers:

  ```
  Co-Authored-By: Claude Fable 5.2 <noreply@anthropic.com>
  Claude-Session: https://claude.ai/code/session_01KbmAkq4n2V1kcJhjQYHFDP
  JARVIS-Version: v11.1.0
  JARVIS-Mark: XV
  ```
- The repository is public: no personal data (names, e-mail addresses, phone numbers, account numbers,
  home addresses, real calendar or mail content), no keys, no chat links other than the trailer, no
  local paths, in code, tests, fixtures or docs. Fixtures use made-up people, `example.com` addresses,
  obviously fake numbers and pictures you generate in the test (never a photo of a real person).

## 2. The rule: never edit a wiring file

I0 built every join. You plug in through **one function**, `build(ctx: FixContext) -> FixPart`
(`jarvis.fixes.ports`), in your package's `part.py`, **one route file** `api/fix_<part>.py`, and **one
console module** `console-r111-<part>.js` with its stylesheet. You never edit:

- `src/jarvis/api/app.py` (725 lines, guard 750), `api/r11_1_wiring.py`, `api/r11_wiring.py`,
  `api/personal.py`, `api/home.py`, `api/home_wiring.py`, `api/r4_wiring.py`, `api/r6_wiring.py`,
  `api/console.py`, `tools/setup.py`
- `src/jarvis/tools/gateway.py` (760 lines, guard 760: **it may not grow by a line**), `tools/base.py`,
  `tools/budget.py`, `tools/policy.py`, `tools/taint.py`, `tools/background.py`
- `src/jarvis/fixes/ports.py`, `alerts.py`, `notify/*`, `keyring.py`, `config.py`,
  `permissions/groups.py`, `core/models.py`, `core/brain_types.py`, `llm/*`, `offline/*`, `helpers/*`,
  `buildbook/*`, `billing/*`
- `people/gate.py` — **nobody** edits it, and no test of it is weakened (plan D17)
- `console.html` (795 lines, guard < 800), `console-r111.js`, `console-deck.js`, `console-dock.js`,
  `console-alerts.js`, `console-helpers*.js`, `console.css`, `console-deck.css`
- `pyproject.toml`, `requirements.lock`, `requirements.licences.json`, `Makefile`, `.github/*`,
  `docs/architecture/*`, `scripts/*`, `evals/run_all_mock.py`, `evals/r11_1/run.py`
- `tests/test_r11_1_seams.py`, any `tests/test_r*_seams.py`, `tests/browser/ui_checks.py`, another
  part's files

If you need a change there (a new setting, an alert kind, a permission row, a dependency, a line in
`console.html`, a persona sentence that is not yours), stop and write it under "Needs I1" in your
`INTEGRATION-<PART>.md` with the exact diff you propose. Part C alone edits `deploy/*`; Part D alone
edits `core/prompts.py`.

## 3. What each part owns (and only this)

The full list is the plan's "Part split" table; in short:

| Part | New package | Route file (prefix) | Console module | Eval part | Tests and fakes |
|---|---|---|---|---|---|
| A · Brain and calendar (O1, O2, O2b, O12) | `src/jarvis/series/` (+ `tools/calendar_batch.py`, `core/finish.py`) | `api/fix_plan.py` (`/v1/series`) | `console-r111-plan.js` | `evals/r11_1/plan.py` | `tests/test_r11_1_a_*.py`, `tests/r11_1_fakes_a.py`, `tests/fixtures/r11_1/a_*` |
| B · Voice and files (O3, O4) | `src/jarvis/understand/` (+ `documents/*`, `voice/*`) | `api/fix_files.py` (`/v1/input`) | `console-r111-files.js` | `evals/r11_1/files.py` | `tests/test_r11_1_b_*.py`, `tests/r11_1_fakes_b.py`, `tests/fixtures/r11_1/b_*` |
| C · Photos, faces, home kit (O5, O6, O7) | `src/jarvis/facegroups/` (+ `photos/*`, `faces/*`, `homebridge/*`, `deploy/*`) | `api/fix_photos.py` (`/v1/facegroups`) | `console-r111-photos.js` | `evals/r11_1/photos.py` | `tests/test_r11_1_c_*.py`, `tests/r11_1_fakes_c.py`, `tests/fixtures/r11_1/c_*` |
| D · People, pictures, Vitals (O8, O9, O10, O11) | `src/jarvis/picture/` (+ `people/*` except the gate, `vitals/*`, `core/prompts.py`) | `api/fix_look.py` (`/v1/picture`) | `console-r111-look.js` | `evals/r11_1/look.py` | `tests/test_r11_1_d_*.py`, `tests/r11_1_fakes_d.py`, `tests/fixtures/r11_1/d_*` |

Plus your own note: `docs/plans/r11-1-integration/INTEGRATION-<A|B|C|D>.md` (what you built, how to
check it, what I1 must do, what you could not verify, owner checks). **Fakes filenames are unique per
part**, so the four branches merge without a clash. You update the EXISTING tests of the files you own
(`test_photos_picker.py` is C's, `test_documents_*.py` B's, and so on) and nobody else's. Never
`from tests.x import …`: tests import fakes as top-level modules (`from r11_1_fakes_a import …`), as
every other test does; CI runs plain `pytest`.

## 4. The contract (`src/jarvis/fixes/ports.py`)

`api/r11_1_wiring.check_part` leaves out a part that breaks it (the app still starts, your part says
"setup failed"):

- **`FixPart(name, tools, clock_jobs, daily_jobs, privacy, services, ready)`**: `name` is yours
  (`plan`, `files`, `photos`, `look`). Set `ready` to one plain word or phrase ("ready", "off: no
  laptop linked", …); your status route returns it.
- **Tools** only inside your family (`TOOL_FAMILIES`): A `calendar_create_events`,
  `calendar_undo_events`, `series_*`, `gmail_inbox_summary`; B none (reading a file stays the
  `doc_*` tools in `jarvis.documents`, which B owns); C `faces_groups`, `faces_group_*`,
  `photos_import_*`; D `picture_*`. The permission rows already match (plan D7, D17). The right risk
  per tool is yours: a batch and a re-plan are R2 with `ask_when` always (always one card); nothing
  in this release is R3 except what already was.
- **Jobs**: `clock_jobs` ride the helpers' 5-minute clock and `daily_jobs` its morning tick (they run
  only while the helpers are on). A job has a unique `name`, a `budget_s`, runs for the configured
  owners, is idempotent (claim a document in a transaction before a send) and fast (the clock gives
  all helpers 20 s together; an outside call ≤ 8 s). Names: A `series_checkin`; C `photos_import`,
  `face_groups_poll`.
- **`FixContext`**: `s` (settings), `docs`, `audit`, `prefix`, `notifier()` and `state(name)`: a LATE
  read of `app.state.<name>` (None when it isn't there). Read `state("gateway")`, `state("brain")`,
  `state("documents")`, `state("billing")`, `state("brain_mode")`, `state("faces")`, … when you are
  CALLED, never while `build` runs, and treat None as "switched off" in plain words.
- **Telling the owner**: only `ctx.notifier().notify(uid, Signal(source=…, kind=…), text)` with kind
  `series_checkin` (A) or `faces_to_name` (C): fixed templates, ≤ 300 characters, never outside words
  (a file's text, a mail subject, a calendar title someone else wrote, a contact's name).
- **Collections** (`COLLECTIONS`, all `f"{ctx.prefix}<name>/..."`): A `series`, `series_told`;
  C `photo_imports`, `face_groups`. Only these, or the guide's coverage check fails (card C61 lists
  them). Nothing new is sealed; if you find you must seal something, that is a "Needs I1" (a keyring
  purpose).
- **Routes**: under your prefix only, owner-only (`require_auth`; a cookie write needs
  `X-Requested-With: JARVIS`), `no-store`, rate-limited where they change something. A route that
  acts calls the tool **through the gateway** (`state("gateway").execute(...)`, as
  `api/helpers_kitchen.py` does); a route never writes to Google itself.
- **Console**: your module is an ES module loaded by `console-r111.js`. Build with
  `window.JarvisFixes` (`mk`, `api`, `part`) and the console's existing classes; `textContent` only,
  no `innerHTML`, ASCII source, no new colours / fonts / radii / shadows, 44 px targets (plan D0).
  Your stylesheet only places things and stays ≤ 150 lines.
- **Seams I0 left for you to fill**: A `core/finish.py` (`reply_text` still returns the filler:
  replace it, plan D2/D3) and `output_cap` (use it in `Brain._complete` and the stream);
  B `documents/pictures.py` (`with_pictures`, `turn_pictures`) and `ChatRequest.heard` / `Turn.heard`;
  D calls `turn_pictures`, never the document store.

## 5. House rules that apply to every part

- **Free first.** No new paid service, no new secret. Any model call is by tier through `jarvis.llm`
  (never a vendor SDK, never a model id), admitted first (`Billing.ensure_allowed`) and recorded
  after (`Billing.record`), shown to the owner in ₹ (never $), and skipped or replaced by plain code
  in No-AI mode (`BrainMode`), saying so honestly.
- **Every action is a tool through the gateway**; writes, sends and deletes ask first as the owner's
  rows say; a batch is one card that lists everything it will do; R3 is never approvable on Telegram.
- **Outside content is untrusted data**: an attached file's text, a zip's file names, mail, web pages,
  a picture's text, calendar entries others wrote. Fence it, never obey it, never put it in alert
  text, and never let it choose a tool's target without a card.
- **Private by default**: pictures and faces stay on the laptop (C) or go only to a seeing,
  non-training brain (B, D); logs carry class names and counts only, never a file name, a heard
  sentence, a title or an address.
- **Size guards**: `core/brain.py` 765 lines now, guard < 800 (A: move logic into `core/finish.py`
  rather than growing it); `tools/gateway.py` frozen at 760; every module ≤ 800 lines, new ones
  ≤ 400; functions ≤ 50 lines; `console.html` untouched.
- Write the failing test first (skill `tdd-workflow`), 80 % coverage for your package; then
  `code-reviewer` + `python-reviewer` in a fresh context, `security-reviewer` for A (the batch tool),
  B (files, zip, pictures) and C (bridge routes, faces), `silent-failure-hunter` for A.

## 6. Test commands (run before every push)

```
/tmp/venv-b/bin/pytest -q -p no:cacheprovider tests/test_r11_1_*.py <the existing tests of your files>
/tmp/venv-b/bin/pytest -q -p no:cacheprovider tests/test_r11_1_seams.py tests/test_r1_seams.py \
    tests/test_r6_wiring_seams.py tests/test_arch_coverage.py tests/test_r51_console_assets_linked.py
/tmp/venv-b/bin/ruff check src tests evals scripts && /tmp/venv-b/bin/ruff format --check src tests evals scripts
/tmp/venv-b/bin/mypy src                                  # the 9 pre-existing errors only
PYTHONPATH=$PWD/src /tmp/venv-b/bin/python evals/r11_1/run.py --mock --part <yours>   # passes; your control fails it
PYTHONPATH=$PWD/src /tmp/venv-b/bin/python scripts/arch_coverage.py && PYTHONPATH=$PWD/src /tmp/venv-b/bin/python scripts/check_doc_versions.py
flock /tmp/r111-logs/heavy.lock env JARVIS_BROWSER_TESTS=1 PYTHONPATH=$PWD/src \
    /tmp/venv-c/bin/python -m pytest -q tests/browser -m browser -k "r11_1 or ui_audit"
```

Run every command from YOUR worktree. `pytest` there already uses your worktree's `src`; a plain
`python` does not (the environments were installed from the main checkout), hence `PYTHONPATH=$PWD/src`.
`/tmp/venv-c` has no `pytest` script: use `python -m pytest`. Any browser run, `mypy src`, and any run
of more than about 500 tests goes behind `flock /tmp/r111-logs/heavy.lock …` so the four builders take
turns on the two CPUs. `openpyxl`, `xlrd`, `opencv-python-headless` and `numpy` are already installed in
all three environments for your tests; I1 adds them to the lock files, you do not. You do not spawn
other agents and you do not review your own part: the orchestrator runs the fresh-context reviews when
you report. Read the plan's **D21** as well: it binds your part.

The machine has 2 CPUs and is shared by four builders: run your own tests and the guard tests above,
not the whole suite (I1 runs it). Wait for an environment's `READY` file (`/tmp/venv-b/READY`,
`/tmp/venv-c/READY`) before using it. Set `BUILT = True` in your eval part only when its control
really fails it. Your browser test goes in `tests/browser/test_r11_1_<a|b|c|d>_*.py` and uses the
visual gate's helpers (`tests/browser/ui_checks.py`, read-only for you).

## 7. Done means

Your observations are fixed on fakes end to end and each has its eval case with a failing control;
everything works or says plainly why not in No-AI mode, with the laptop off, with Google not linked
and past the monthly limit; your screens render in Night and Day at 1440×900 and 390×844 with no JS
errors or CSP violations and the visual gate passes; the commands above are green; your
`INTEGRATION-<PART>.md` (versioned like this file, with a change log) is written and pushed, and it
lists honestly what you could not verify live.

## Change log

| Version | Date | Release | What changed | By |
|---|---|---|---|---|
| v11.1.1 | 12 Nov 2026, 06:17 IST | R11.1 | First edition with the R11.1 I0 seams | 🛠 Mark XV |
| v11.1.2 | 12 Nov 2026, 06:35 IST | R11.1 | Test commands corrected for worktrees (`PYTHONPATH`, `python -m pytest`, the heavy lock); libraries already installed; builders do not review themselves; pointer to the plan's D21 | 🛠 Mark XV |
