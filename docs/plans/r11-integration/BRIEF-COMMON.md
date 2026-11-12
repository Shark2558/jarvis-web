Version v11.0.2 · 11 Nov 2026, 21:44 IST · Release R11 · Status: Current · Owner: 🛠 Mark XIV

# R11 — the common builder brief (Parts A–D)

Read this, then the plan `docs/plans/r11-free-helpers.md` (your part's items and decisions), then
`CLAUDE.md` and `.claude/rules/ecc/common/*.md`. You build ONE part, in parallel with three others,
on your own branch from `r11-i0`. Everything you may touch is listed below; everything else is
someone else's. When in doubt, don't edit: write it in your `INTEGRATION-<PART>.md` for I1.

## 1. Your branch, your commits

- Worktree and branch: `r11-a` (A · Today), `r11-b` (B · Home and outside), `r11-c` (C · Nudges),
  `r11-d` (D · Kitchen), each from `origin/r11-i0`. Push after every commit. Never force-push,
  `rm -rf`, `git stash`, or edit lint / format / type-check configs to make an error go away.
- Every commit message ends with exactly these trailers:

  ```
  JARVIS-Version: v11.0.0
  JARVIS-Mark: XIV
  Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
  Claude-Session: https://claude.ai/code/session_01KbmAkpbuzzBBGe42J3qaAS
  ```
- The repository is private but treated as public: no personal data (names, e-mail addresses,
  phone numbers, real UPI IDs, account numbers, home addresses), no keys, no chat links — in code,
  tests, fixtures or docs. Fixtures use made-up merchants' mail shapes with `example.com`-style
  addresses and obviously fake numbers.

## 2. The rule: never edit a wiring file

I0 built every join. You plug in through **one function**, `build(ctx) -> HelperPart`, in your
`src/jarvis/helpers/<part>/part.py`, and **one router**, `api/helpers_<part>.py`. You never edit:

- `src/jarvis/api/app.py`, `api/r11_wiring.py`, `api/personal.py`, `api/home.py`,
  `api/home_wiring.py`, `api/r4_wiring.py`, `api/r6_wiring.py`, `api/console.py`, `tools/setup.py`
- the I0 core `src/jarvis/helpers/{kinds,ports,gate,clock,brief,sources,privacy}.py`,
  `alerts.py`, `notify/*`, `keyring.py`, `config.py`, `permissions/groups.py`,
  `offline/{mode,rules,no_ai}.py`, `brief/*`, `buildbook/*`
- `console.html`, `console-deck.js`, `console-dock.js`, `console-alerts.js`,
  `console-brief-sections.js`, `console-helpers.js`, `console-helpers.css`
- `pyproject.toml`, `requirements.lock`, `requirements.licences.json`, `Makefile`, `.github/*`,
  `deploy/*`, `docs/architecture/*`, `scripts/arch_coverage.json`, `evals/run_all_mock.py`
- `tests/r11_fakes.py`, `tests/test_r11_{seams,gate,wiring}.py`, `tests/test_evals_r11.py`,
  `evals/r11_helpers/{run,gate}.py`, another part's files

If you need a change there (a new setting, a CSS rule, an alert kind, a dependency), stop and write
it under "Needs I1" in your `INTEGRATION-<PART>.md` with the exact diff you propose.

## 3. What each part owns (and only this)

| Part | Package | Route file | Console tab | Eval part | Tests and fakes |
|---|---|---|---|---|---|
| A · Today (items 1, 7, 10) | `src/jarvis/helpers/today/` | `api/helpers_today.py` | `console-helpers-today.js` | `evals/r11_helpers/today.py` | `tests/test_r11_a_*.py`, `tests/r11_fakes_a.py`, `tests/fixtures/r11/a_*` |
| B · Home and outside (2–6) | `src/jarvis/helpers/house/` | `api/helpers_house.py` | `console-helpers-house.js` | `evals/r11_helpers/house.py` | `tests/test_r11_b_*.py`, `tests/r11_fakes_b.py`, `tests/fixtures/r11/b_*` |
| C · Nudges (8, 9, 11, 12) | `src/jarvis/helpers/nudges/` | `api/helpers_nudges.py` | `console-helpers-nudges.js` | `evals/r11_helpers/nudges.py` | `tests/test_r11_c_*.py`, `tests/r11_fakes_c.py`, `tests/fixtures/r11/c_*` |
| D · Kitchen (13–16) | `src/jarvis/helpers/kitchen/` (+ `data/fdc_subset.json`) | `api/helpers_kitchen.py` | `console-helpers-kitchen.js` | `evals/r11_helpers/kitchen.py` | `tests/test_r11_d_*.py`, `tests/r11_fakes_d.py`, `tests/fixtures/r11/d_*`, `scripts/kitchen_fdc_subset.py` |

Plus your own note: `docs/plans/r11-integration/INTEGRATION-<A|B|C|D>.md` (what you built, how to
check it, what I1 must do, owner checks). **Fakes filenames are unique per part** (`r11_fakes_a.py`
… `r11_fakes_d.py`, fixtures prefixed `a_` … `d_`), so the four branches merge without a clash.
Shared fakes are I0's `tests/r11_fakes.py` (`Clock`, `FakeNotifier` with `policy=True`, `sender`,
`ctx`): import them, don't copy or change them.

## 4. The names you must use (`src/jarvis/helpers/kinds.py`)

`wire_r11` refuses a part that uses a name it doesn't own (the part is then switched off):

- **Alert kinds** (`KINDS_OF`): A `bill_due`, `birthday`; B `chore_due`, `maintenance_due`,
  `weather_warning`, `weather_note`, `disaster_alert`, `breach_notice`; C the five `nudge_*`; D none.
  Send only through `ctx.sender.send(uid, kind, text, due=..., named=..., subject=...)`: fixed
  templates, ≤ 300 characters, never outside words (a CAP headline, a mail subject, a contact's name
  when "names in alerts" is off — use `named=` for the named version). Respect `SendResult.retry`.
- **Jobs** (`CLOCK_JOBS` on the 5-minute clock, `DAILY_JOBS` on the morning tick): A `bills_due`,
  `birthdays`; B `chores_due`, `maint_due`, `weather_poll`, `disaster_poll` and daily
  `breach_watch`; C `nudges`, `activity_check`; D daily `grocery_spend`. A job runs for
  `ctx.owners` (ignore the `owners` argument), is idempotent (claim documents in a transaction before
  a send; release a claim whose send has `retry`), and is fast: the whole clock has
  `helpers_clock_budget_s` (20 s) for all four parts; outside fetches only when due, ≤ 8 s each.
- **Tools** (`TOOL_FAMILIES`): A `bill_*`, `focus_*`, `pending_*`, `contacts_birthdays`; B `chore_*`,
  `maint_*`, `weather_*`, `disaster_*`, `breach_*`; C `nudge_*`, `freetime_*`; D `pantry_*`,
  `recipe_*`, `nutrition_*`, `spend_*`, `kitchen_*`, `calendar_kitchen_blocks`. The permission rows
  (plan D16) already match these; the right risk per tool is yours (`bill_pay_prepare` and
  `bill_payee_set` are R3; `calendar_kitchen_blocks` is R2 with `ask_when` always).
- **Privacy ids** (`PRIVACY_IDS`, section "Helpers"): A `helpers_bills` (passkey delete),
  `helpers_birthdays`; B `helpers_house`, `helpers_place`; C `helpers_wellbeing` (passkey);
  D `helpers_kitchen`, `helpers_spend` (passkey).
- **Collections** (`COLLECTIONS`, all `f"{ctx.prefix}<name>/..."`): only these, or the guide's
  coverage check fails (card C60 lists them). Sealed data uses `ctx.keyring.cipher(<purpose>)` with
  AAD `<collection>/{uid}/v1`; purposes `bills` (A), `alerts_place` (B), `wellbeing` (C), `kitchen`
  and `spend` (D). No keyring → that feature says it is off, never stores in clear.
- **Console**: your module calls `window.JarvisHelpers.register('<tab>', {mount(host, H),
  refresh(view)})` and builds with `H.row`, `H.toggle`, `H.section`, `H.empty`, `H.note`, `H.mk`,
  `H.api`; `textContent` only, no `innerHTML`, no new colours / fonts / radii / shadows, 44 px
  targets, ASCII source. Tap actions for nudges use I0's routes `/v1/helpers/gate/{kind}/snooze`,
  `/stop`, `/resume` and `PUT /v1/helpers/gate`.
- **No-AI phrases**: `HelperPart.phrases`, anchored, conservative, ending in your own tools; they run
  before every older pattern (plan D18).
- **Brief and pending**: `HelperPart.brief` contributors give ≤ 3 fixed lines; `HelperPart.pending`
  sources give `PendingItem`s (A reads them all through `ctx.pending_all()`).

## 5. House rules that apply to every part

Model-agnostic (only `jarvis.llm`, by tier; D only, for recipes, through `ctx.brains` and
`ctx.billing`); every action a tool through the gateway; R3 needs his confirmation token and is never
approvable on Telegram; tool, web, e-mail, contact and CAP content is untrusted data (fence it, never
obey it, never put it in alert text); background readers obey his permission rows
(`Policy(await ctx.permissions().rules_for(uid)).decide(...)`, fail closed) and audit a kind-only
line; logs carry class names and counts only. Card / account numbers are never stored (last 4 at
most); a contact's birth year is never read into storage; no children's data. Functions ≤ 50 lines,
modules ≤ 400 (every file ≤ 800). Write the failing test first (`tdd-workflow`), 80 % coverage for
your package, then `code-reviewer` + `python-reviewer` in a fresh context, `security-reviewer` for
A, B and D.

## 6. Test commands (run all before every push)

```
/tmp/venv-12/bin/pytest -q -p no:cacheprovider            # the whole unit suite (3.12)
/tmp/venv-b/bin/pytest -q -p no:cacheprovider tests/test_r11_*  # your tests on 3.11
/tmp/venv-12/bin/ruff check src tests evals scripts && /tmp/venv-12/bin/ruff format --check src tests evals scripts
/tmp/venv-12/bin/mypy src                                  # the 9 pre-existing errors only
/tmp/venv-12/bin/python evals/r11_helpers/run.py --mock --part <yours>   # passes; your control fails it
/tmp/venv-12/bin/python scripts/arch_coverage.py && /tmp/venv-12/bin/python scripts/check_doc_versions.py
JARVIS_BROWSER_TESTS=1 /tmp/venv-c/bin/pytest -q tests/browser -m browser -k "helpers or dock or ui_audit"
```

Set `BUILT = True` in your eval part only when its control really fails it. Your part's browser
test goes in `tests/browser/test_r11_<a|b|c|d>_*.py` and uses the visual gate's helpers
(`tests/browser/ui_checks.py`, read-only for you).

## 7. Done means

Your items work on fakes end to end, in No-AI mode too (except D's new recipe ideas, which say so);
every reminder is sent once, on time (first 5-minute run at or after due), and every nudge inside
the gate's limits; your privacy rows list, export and delete; your tab renders in Night and Day at
1440×900 and 390×844 with no JS errors or CSP violations; the commands above are green; your
`INTEGRATION-<PART>.md` is written and pushed.

## Change log

| Version | Date | Release | What changed | By |
|---|---|---|---|---|
| v11.0.1 | 11 Nov 2026, 18:02 IST | R11 | First edition with the R11 I0 seams | 🛠 Mark XIV |
| v11.0.2 | 11 Nov 2026, 21:44 IST | R11 | I1: the first edition's time corrected (it was written by 18:02 IST, the I0 commit, not 18:40) | 🛠 Mark XIV |
