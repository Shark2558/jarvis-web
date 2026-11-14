Version v14.0.1 · 14 Nov 2026, 17:25 IST · Release R14 · Status: Current · Owner: 🛠 Mark XIX

# R14 Part D · No-AI pass 2, rows 101/102 and the leftovers — integration note for I1

Built by builder D for the Workshop (🛠 Mark XIX) on branch `r14-d`, cut from `origin/r14-i0` @
`9eb9d8b`, following `docs/plans/r14-hardening.md` v14.0.2 (D1, D2, D12, D13, Part split row D),
`BRIEF-COMMON.md`, `I0-NOTES.md` and `PLAN-REVIEW-1.md`. Every change was test first: each test was
run red on the old code (or on I0's stub) before the code went in. Nothing was rebased, stashed or
force-pushed; the hook blocked nothing.

## 1. What was built, per deliverable

| Deliverable | Files | Tests (red first) |
|---|---|---|
| **D12 No-AI pass 2**: 13 anchored routers, each a whole-message pattern ending in ONE gateway call or a fixed line, no model: groceries (add with quantities, show, remove), vault expiry, where a thing is / "I kept X in Y", home status and arming (disarm is the fixed line "Disarming is only in the Home panel, Sir.", never a tool, not even `home_disarm`), parcels, the inbox summary, Recently deleted, memory search, the time and the date (from the clock, his zone), backups / the restore drill (a card), a home-service request, "what can you do" (the 11 skills from `skills/ids.py`, a fixed list of what works with the AI off, and "anything that needs writing … needs the AI") | `offline/phrases_r14.py` (358 lines), `offline/r14_part.py` (`ready` = "ready", `services["phrases"]` = the 13 routers, no tool) | `test_r14_d_phrases.py` (63: every D12 example, quantities through `parse_items`, the belongings and service arguments through their tools' own checks, disarm, the clock, the 11 skills, generative asks keep `NO_AI_LINE`, longer sentences fall through to pass 1, near misses, odd input; 42 red on I0's stub); `test_r14_d_noai_app.py` (37: the real app with the AI off, every app phrase installed: the routers sit last, in order, none shadowed; every D12 example is a chat turn with **zero provider calls**) |
| **Row 101** (D1): the car stays "not possible yet"; `STARTERS` gains "Car service" every 180 days (offered, never added) | `helpers/house/upkeep.py` | `test_r11_b_chores.py` pin → `[90, 180, 365, 365, 180]` (red, then green) |
| **Row 102** (D2): `maint_service_request` (R1, house tool, agent `helpers`, row `household` via `maint_*`, Telegram open): a fixed template (the job of 8, his problem ≤ 200, his time ≤ 40, and "Address and phone number: shared only with the provider you choose."), Urban Company's address as **text** in the result; a phone number, PIN code, e-mail or link in his words is refused (a date or a time is not); reads nothing of his, books / pays / sends / opens nothing; the result points to `whatsapp_draft` for a person he picks | `helpers/house/service_request.py` (new, 165), `helpers/house/tools.py` (registered beside `maint_starters`), `helpers/sources.py` (`URBAN_COMPANY_NAME`, `URBAN_COMPANY_URL`) | `test_r14_d_service.py` (20), `test_r11_b_part.py` (the house tool set) |
| **D13 (1)** a re-sign-in whose ID token has no (or a non-number) `auth_time` is stale, never "now" | `api/auth.py` `_reauth_at` | `test_r14_d_auth.py` (7) |
| **D13 (2)** a new show lock keeps the earlier `sessions_valid_after` mark (read in `set`'s own transaction); a lift without a mark keeps it; a mark never moves back; another owner's malformed document never blocks a Resume (lenient, as before R14), this owner's own stays strict | `buildbook/lock.py` | `test_r14_d_lock.py` (6), `test_book_lock.py` (the read count: `set` now reads once) |
| **D13 (3)** a 503 from an unreadable lock covers the console: `lock_unreadable` (R7's app lock) → the app's unlock cover (its unlock reads the lock again), `show_lock_unreadable` (R6's show lock) → the gate's "Can't reach JARVIS" cover with Try again, uncovered only by a 200 from `/auth/me`; any other 503 stays its caller's. **8 lines**, no new look | `api/static/console.js` (761 → 769) | `tests/browser/test_r14_d_console.py` (4; 3 red on the old console) |
| **D13 (4)** `GET /v1/notes/export` is audited FIRST (agent `privacy`, tool `notes_export`, args `{count}`, detail "notes: N", never a note's words); a chain that can't be written refuses (503 `export_unaudited`, nothing sent); with no chain at all (tools off) it answers and logs | `api/notes.py` | `test_r14_d_notes.py` (3) |
| **D13 (5)** the re-plan card's first line (the only line Telegram shows, `HEAD_BY_CODE`) names no plan: "Move N sessions of your plan …"; the stored plan's words open line 2 ("Your CCA plan: 60 sessions before …"), which only the console shows | `series/cards.py` | `test_r14_d_replan.py` (3, through `telegram.service._long_card`); `test_r11_1_a_series.py` pins moved |
| **D13 (6)** the UPI cap is one figure: `PAY_CAP_PAISE` *is* `MAX_UPI_AMOUNT_PAISE` (the ceiling = the `Settings` bound), `pay_cap_paise()` reads `bill_pay_cap_inr` (never above the ceiling); `amount_text` (the card check, the prepared payment and the link) refuses past it with the lowered figure | `helpers/today/{models,upi}.py`, `helpers/sources.py` | `test_r14_d_upi.py` (5) |
| **D13 deploy**: the Vitals composite index is no longer created (the one made stays); `backup_status_note` calls only `bash deploy/backup_setup.sh --status`, non-fatal, before "DONE"; no TTL policy | `deploy/cloudrun.sh` | `test_r14_d_deploy.py` (5: the block run under `set -euo pipefail` with a fake script that fails) |
| **D13 docstring**: the people cache says there is no TTL policy and why (a float field, billed deletes) | `people/cache.py` | `test_r14_d_deploy.py` |
| **Eval** `evals/r14/noai.py`, `BUILT = True`: 31 D12 examples through a Brain with the AI off (zero provider calls, exactly its tool; a write or the drill on one card), 9 fixed lines / generative asks (no model, no tool), the service request with no contact; **41/41**. Control "R14 phrases off": **all 31 rows fail** | `evals/r14/noai.py`, `tests/r14_fakes_d.py` (the D12 table, a No-AI Brain on fakes) | `test_r14_d_eval.py` |

D13 (7) (a held `home_offline_idle` dropped when the laptop is back) is Part B's (`notify/store.py`
and the laptop-back path): not built here.

### Existing tests changed (the tests of the files above, nothing else)

- The Google fakes of the **re-sign-in** flows now send `auth_time` (as Google does when `max_age`
  is asked): `tests/book_app_fakes.py`, `tests/r7_fakes_c.py`, `test_camera_api.py`,
  `test_faces_api.py`, `test_privacy_api.py`, `test_r3_wiring.py`, and `test_permissions_api.py`
  (`_fresh`: `auth_time=None` leaves it out; its re-auth test now pins "missing → stale"). Without
  this, 124 tests and 31 errors in 53 files failed on the fix; with it, those 53 files: 1,203 passed.
- `test_book_lock.py` (one read more in `set`), `test_r11_1_a_series.py` (the card's first two
  lines), `test_r11_b_chores.py` (the STARTERS pin), `test_r11_b_part.py` (the house tool set).

## 2. Decided differently from the plan's words, and why

1. **D13 (5).** The plan says the first line should come "from the stored plan's label, never the
   model's argument". The card already read the STORED plan (found by id or normalised name), but
   the stored name is itself the model's `series.name` argument from the batch call, and Telegram
   treats that line as "code alone writes it". So the first line now carries no plan name at all;
   the name moved to line 2 (console only). Any later "label" field would need a model change.
2. **D13 (2)** goes slightly past `set`: `lift` without a mark keeps it (it deleted it), and a mark
   never moves back (`max`), the same hole; `end_sessions` already worked that way.
3. **D13 (4)** fails closed on a broken audit chain (as the vault does for an open), and answers
   with a log line when the app has no chain at all (tools switched off), as `record_change` does.
4. **D13 (6)**: `BillsService` and the today tools have no settings, and their files are not Part
   D's, so `pay_cap_paise()` reads `get_settings()` (the same cached object the app is built from in
   production; a test lowers it through `JARVIS_BILL_PAY_CAP_INR` and clears the cache).
   `amount_text` also takes `cap=` for callers that hold settings. To lower the cap he sets that
   environment variable on the service (the deploy does not set it; the default is ₹1,00,000).
5. **D13 (3)**: both unreadable-lock codes are covered (the plan names `lock_unreadable`; R6's
   `show_lock_unreadable` had the same gap in `api()` / `raw()`).
6. **D12**: one router per row (13), so the wiring's "one at a time" isolates each; the drill
   router sits before the backups one ("test my backup" is a card, never the status).

## 3. Needs I1 (exact diffs; files Part D does not own)

1. `tests/test_r14_seams.py` — Part D is built (`ready` "ready", the eval part `BUILT`):

   ```diff
   @@ test_the_app_starts_with_four_parts_and_their_status_routes
   -        assert all(p.ready == "not built yet" for p in parts.values())
   +        assert parts["noai"].ready == "ready"
   +        assert all(p.ready == "not built yet" for n, p in parts.items() if n != "noai")
   @@
   -        assert r.json() == {"parts": {n: "not built yet" for n in PARTS}}
   +        assert r.json()["parts"]["noai"] == "ready"
   @@ test_the_r14_runner_passes_and_its_contract_control_fails_it
   -    for part in ("backup", "selfwatch", "offer", "noai", "needles"):
   +    for part in ("backup", "selfwatch", "offer", "needles"):
            assert f"{part}:not_built_yet" in ids, part
   +    assert control["failed_cases"]["noai"]  # D's control (R14 phrases off) fails every row
   ```
   (merge with A's, B's and C's lines: once all four are built, every part's word and control.)
2. `tests/test_telegram_tool_guard.py` `TELEGRAM_SAFE` — the new R1 read must pick a side (it is
   open: `test_r14_seams.py::test_the_new_tools_are_open_on_telegram`):

   ```diff
            "maint_starters",
   +        "maint_service_request",  # R14 D2: a prepared request in his words; never books or sends
   ```
3. Part C's register (`skills/catalogue.json`): `maint_service_request` → `task` (Task &
   Productivity, plan D2), so D11's coverage check files it.
4. Persona p14.0 (I1, D14): optionally one TOOLS_RULE clause: "For a plumber or electrician, call
   maint_service_request; you never book or pay; to message a person he picks use whatsapp_draft."

## 4. Checks (one at a time, behind the shared `flock`)

| Check | Result |
|---|---|
| Own tests, 3.12: `test_r14_d_*.py` (150) + every existing test of the files touched (60 files) | **1,535 passed**, 1 skipped |
| The same, 3.11 (`/tmp/venv-b`) | **1,535 passed**, 1 skipped |
| Seam set (`test_r14_seams`, `test_r14_wiring`, `test_claude_guard`, `test_arch_coverage`, `test_telegram_tool_guard`) | 266 passed, 12 failed: the 2 seam pins and the `TELEGRAM_SAFE` line of "Needs I1" (Part D being built), and 9 `test_claude_guard` "rm -rf" cases that fail in ANY checkout under `/home/claude/wt/` or `/tmp/` (the hook allows `rm -rf` there by design and the test resolves `src`, `tests`, … from the checkout); neither `.claude/` nor that test is touched on this branch (`git diff origin/r14-i0 -- .claude tests/test_claude_guard.py` is empty) |
| `ruff check` / `ruff format --check` (src tests evals scripts) | clean (1,671 files) |
| `mypy src` | the 9 baseline errors only |
| `evals/r14/run.py --mock --part noai` | **41/41 passed; the control ("R14 phrases off") failed the suite: 31 of 31 rows** |
| R11.1's eval, plan part (the re-plan card moved) | 24/24; its control fails |
| `scripts/arch_coverage.py`, `scripts/check_doc_versions.py` | OK; 28 documents |
| `python -m jarvis.buildbook.gen --check` | R14 @ `6019b88`, two builds byte-identical |
| Browser (Chromium, `/tmp/venv-c`): `test_r14_d_console.py` | 4 passed; again with the optional extras blocked (aiomqtt, paho, cv2, numpy): 4 passed |
| Browser: the console's existing files `test_r6_i1_console.py`, `test_r7_c_lock.py`, `test_console.py` | 45 passed |
| Coverage of Part D's modules (own tests) | `phrases_r14` 99 %, `r14_part` 100 %, `service_request` 100 %, `notes` 100 %, `sources` 100 %, `lock` 97 %, `upi` 96 %, `upkeep` 94 %, house `tools` 93 %, `auth` 92 %, `cards` 85 % |

Sizes: `phrases_r14.py` 358, `service_request.py` 165, house `tools.py` 375, `console.js` 769 (≤ 800;
`console.html` untouched), every function ≤ 50 lines.

## 5. What could not be verified here

- Whether Google sends `auth_time` on every `max_age=0` re-sign-in (plan "What can't be verified").
  If it ever does not, every re-sign-in reads "stale": passkey set-up and resets wait until it does.
- Urban Company's address (`https://www.urbancompany.com/`) was not fetched; it is only shown as text.
- `deploy/cloudrun.sh` was not run end to end (no Google); its new block was run in bash with a fake
  `backup_setup.sh`, and the whole script passes `bash -n` and the deploy tests.
- The console change in a real phone app (only desktop Chromium here); the R7 cover's unlock with
  an unreadable store is R7's own path, already tested there.
- The full unit and browser suites (I1's, per the brief).

## Change log

| Version | Date | Release | What changed | By |
|---|---|---|---|---|
| v14.0.1 | 14 Nov 2026, 17:25 IST | R14 | First edition: Part D built test first on `r14-d` (No-AI pass 2's 13 routers, row 101's car-service starter, row 102's `maint_service_request`, D13 (1)–(6) and the deploy and docstring lines), the existing tests moved with their files, the decisions taken differently, Needs I1 (two seam pins, `TELEGRAM_SAFE`, C's catalogue, the persona line), the checks and what could not be verified | 🛠 Mark XIX |
