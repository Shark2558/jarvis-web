Version v14.0.2 · 14 Nov 2026, 18:10 IST · Release R14 · Status: Current · Owner: 🛠 Mark XIX

# R14 Part D · No-AI pass 2, rows 101/102 and the leftovers — integration note for I1

Built by builder D for the Workshop (🛠 Mark XIX) on branch `r14-d`, cut from `origin/r14-i0` @
`9eb9d8b`, following `docs/plans/r14-hardening.md` v14.0.2 (D1, D2, D12, D13, Part split row D),
`BRIEF-COMMON.md`, `I0-NOTES.md` and `PLAN-REVIEW-1.md`. Every change was test first: each test was
run red on the old code (or on I0's stub) before the code went in. Nothing was rebased, stashed or
force-pushed; the hook blocked nothing. v14.0.2 adds the fixes for the three fresh-context reviews
(security, code, Python) and the Workshop's decision on D13 (1): section 6.

## 1. What was built, per deliverable

| Deliverable | Files | Tests (red first) |
|---|---|---|
| **D12 No-AI pass 2**: 13 anchored routers, each a whole-message pattern ending in ONE gateway call or a fixed line, no model: groceries (add with quantities, show, remove), vault expiry, where a thing is / "I kept X in Y", home status and arming (disarm is the fixed line "Disarming is only in the Home panel, Sir.", never a tool, not even `home_disarm`), parcels, the inbox summary, Recently deleted, memory search, the time and the date (from the clock, his zone), backups / the restore drill (a card), a home-service request, "what can you do" (the 11 skills from `skills/ids.py`, a fixed list of what works with the AI off, and "anything that needs writing … needs the AI") | `offline/phrases_r14.py` (383 lines), `offline/r14_part.py` (`ready` = "ready", `services["phrases"]` = the 13 routers, no tool) | `test_r14_d_phrases.py` (94 since v14.0.2; first edition 63: every D12 example, quantities through `parse_items`, the belongings and service arguments through their tools' own checks, disarm, the clock, the 11 skills, generative asks keep `NO_AI_LINE`, longer sentences fall through to pass 1, near misses, odd input; 42 red on I0's stub); `test_r14_d_noai_app.py` (37: the real app with the AI off, every app phrase installed: the routers sit last, in order, none shadowed; every D12 example is a chat turn with **zero provider calls**; since v14.0.2, 43 with a Telegram turn and the real belongings tool) |
| **Row 101** (D1): the car stays "not possible yet"; `STARTERS` gains "Car service" every 180 days (offered, never added) | `helpers/house/upkeep.py` | `test_r11_b_chores.py` pin → `[90, 180, 365, 365, 180]` (red, then green) |
| **Row 102** (D2): `maint_service_request` (R1, house tool, agent `helpers`, row `household` via `maint_*`, Telegram open): a fixed template (the job of 8, his problem ≤ 200, his time ≤ 40, and "Address and phone number: shared only with the provider you choose."), Urban Company's address as **text** in the result; a phone number (also date-shaped, split by words or spelled out), PIN code, e-mail or link (also "bit.ly/x") in his words is refused (a real date or a time is not); words he did not type this turn are fenced as data and the result is not `trusted_output` (v14.0.2); reads nothing of his, books / pays / sends / opens nothing; the result points to `whatsapp_draft` for a person he picks | `helpers/house/service_request.py` (new, 218), `helpers/house/tools.py` (registered beside `maint_starters`), `helpers/sources.py` (`URBAN_COMPANY_NAME`, `URBAN_COMPANY_URL`) | `test_r14_d_service.py` (37), `test_r11_b_part.py` (the house tool set) |
| **D13 (1)**, as the Workshop decided (section 6.1): a re-sign-in asks Google for `auth_time` (`max_age=0` and the `claims` parameter `{"id_token":{"auth_time":{"essential":true}}}`; never `prompt=login`); a present `auth_time` is checked strictly (older than the start or in the future: stale); a missing one is stale only when `reauth_requires_auth_time` is on (default off: the pre-R14 way); the log names the kind, never the token | `api/auth.py` (`REAUTH_CLAIMS`, `requires_auth_time`, `_reauth_at`) | `test_r14_d_auth.py` (15) |
| **D13 (2)** a new show lock keeps the earlier `sessions_valid_after` mark (read in `set`'s own transaction); a lift without a mark keeps it; a mark never moves back; another owner's malformed document never blocks a Resume (lenient, as before R14), this owner's own stays strict | `buildbook/lock.py` | `test_r14_d_lock.py` (7), `test_book_lock.py` (the read count: `set` now reads once) |
| **D13 (3)** a 503 from an unreadable lock covers the console: `lock_unreadable` (R7's app lock) → the app's unlock cover (its unlock reads the lock again), `show_lock_unreadable` (R6's show lock) → the gate's "Can't reach JARVIS" cover with Try again, uncovered only by a 200 from `/auth/me`; any other 503 stays its caller's. **8 lines**, no new look | `api/static/console.js` (761 → 769) | `tests/browser/test_r14_d_console.py` (4; 3 red on the old console) |
| **D13 (4)** `GET /v1/notes/export` is audited FIRST (agent `privacy`, tool `notes_export`, args `{count}`, detail "notes: N", never a note's words); a chain that can't be written refuses (503 `export_unaudited`, nothing sent), and so does no chain at all (tools off: `NO_CHAIN`, as the vault does; v14.0.2) | `api/notes.py` | `test_r14_d_notes.py` (3), `test_kb_api.py` (its app has a chain) |
| **D13 (5)** the re-plan card's first line (the only line Telegram shows, `HEAD_BY_CODE`) names no plan: "Move N sessions of your plan …"; the stored plan's words open line 2 ("Your CCA plan: 60 sessions before …"), which only the console shows | `series/cards.py` | `test_r14_d_replan.py` (3, through `telegram.service._long_card`); `test_r11_1_a_series.py` pins moved |
| **D13 (6)** the UPI cap is one figure: `PAY_CAP_PAISE` *is* `MAX_UPI_AMOUNT_PAISE` (the ceiling = the `Settings` bound), `pay_cap_paise()` reads `bill_pay_cap_inr` (never above the ceiling); `amount_text` (the card check, the prepared payment and the link) refuses past it with the lowered figure | `helpers/today/{models,upi}.py`, `helpers/sources.py` | `test_r14_d_upi.py` (5) |
| **D13 deploy**: the Vitals composite index is no longer created (the one made stays); `backup_status_note` calls only `bash deploy/backup_setup.sh --status`, non-fatal, before "DONE", under `timeout` (`BACKUP_STATUS_TIMEOUT_S`, 60 s) with stdin from `/dev/null` (v14.0.2); no TTL policy | `deploy/cloudrun.sh` | `test_r14_d_deploy.py` (7: the block run under `set -euo pipefail` with a fake script that fails, hangs, or reads a typed "YES") |
| **D13 docstring**: the people cache says there is no TTL policy and why (a float field, billed deletes) | `people/cache.py` | `test_r14_d_deploy.py` |
| **Eval** `evals/r14/noai.py`, `BUILT = True`: 31 D12 examples through a Brain with the AI off (zero provider calls, exactly its tool; a write or the drill on one card), 9 fixed lines / generative asks (no model, no tool), the service request with no contact; **41/41**. Control "R14 phrases off": **all 31 rows fail** | `evals/r14/noai.py`, `evals/r14/noai_fakes.py` (the D12 table, a No-AI Brain on fakes; `tests/r14_fakes_d.py` loads it by path, v14.0.2) | `test_r14_d_eval.py` |

D13 (7) (a held `home_offline_idle` dropped when the laptop is back) is Part B's (`notify/store.py`
and the laptop-back path): not built here.

### Existing tests changed (the tests of the files above, nothing else)

- The Google fakes of the **re-sign-in** flows send `auth_time` (as Google does once Session age
  claims are on and the `claims` parameter asks): `tests/book_app_fakes.py`, `tests/r7_fakes_c.py`,
  `test_camera_api.py`, `test_faces_api.py`, `test_privacy_api.py`, `test_r3_wiring.py`, and
  `test_permissions_api.py` (`_fresh`: `auth_time=None` leaves it out; since v14.0.2 its re-auth
  test pins "missing, setting off → fresh, the old way"; `test_r14_d_auth.py` has the missing
  cases with the setting on and off explicitly).
- `test_kb_api.py` (v14.0.2): its app carries an audit chain, since an export with none is refused.
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
3. **D13 (4)** fails closed on a broken audit chain and, since v14.0.2, on no chain at all (tools
   switched off), as the vault's `_audit` does (security review L1, decided consciously).
7. **D13 (1) is met only partly** (v14.0.2, the Workshop's decision): the plan says a missing
   `auth_time` is never fresh, on the premise that OpenID Connect returns it whenever `max_age` is
   sent. Google's own page (Sign in with Google, security bundle, read by the Workshop on 14 Nov
   2026) says Google puts `auth_time` in the ID token only when the app is published and verified,
   "Session age claims" is switched on (off by default) and the request asks for it with the
   `claims` parameter; `max_age` alone is not documented to produce it. "Missing = stale" would lock
   the owner out of passkey set-up, the passkey reset, the build book, Privacy exports and more. So
   the request now asks for it, a present one is checked strictly, and a missing one is stale only
   when the owner switches `reauth_requires_auth_time` on (section 6.2).
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
5. **`config.py`** (v14.0.2, D13 (1)): the setting `api/auth.py` reads with `getattr` until then.
   After it, `requires_auth_time` becomes `return s.reauth_requires_auth_time is True`
   (`test_r14_d_auth.py::test_the_setting_is_read_strictly` stays as it is):

   ```diff
   @@ class Settings  # --- web sign-in (owner only) ---
        session_cookie_max_age_s: int = 12 * 60 * 60
   +    reauth_requires_auth_time: bool = Field(
   +        default=False,
   +        description="A re-sign-in counts only if Google's ID token carries auth_time (switch "
   +        "on only after Google's Session age claims is on; off: the moment it completed)",
   +    )
   ```
6. **The stale message** (v14.0.2, D13 (1)): it lives in two console files that are not Part D's.
   Plain words that help in both cases (Google did not ask again; Google sent no sign-in time):

   ```diff
   --- src/jarvis/api/static/console-permissions.js
   -    else note('bad', 'Google didn\'t ask you to sign in again, so this didn\'t count. Sign out of Google in this browser, then try again.');
   +    else note('bad', 'Google didn\'t confirm a fresh sign-in, so this didn\'t count. Sign out of Google in this browser, then try again. If it happens every time, Google isn\'t sending the sign-in time: switch on Session age claims in Google Auth Platform, or switch reauth_requires_auth_time off.');
   --- src/jarvis/api/static/console-book.js
   -    ... say('bad', 'Google didn\u2019t ask you to sign in again, so the book did not open. Sign out of Google in this browser, then try again.'); }
   +    ... say('bad', 'Google didn\u2019t confirm a fresh sign-in, so the book did not open. Sign out of Google in this browser, then try again. If it happens every time, Google isn\u2019t sending the sign-in time: switch on Session age claims in Google Auth Platform, or switch reauth_requires_auth_time off.'); }
   ```
   (and the comment on line 10 of `console-permissions.js`: "=stale: Google didn't confirm a fresh
   sign-in"). No test pins either string today. The server's own log line already says "Google did
   not confirm a fresh sign-in" with `reason=auth_time_missing|auth_time_old|auth_time_future`.
7. **No-AI answers of the real tools** (v14.0.2, found while pinning the code review's not-found
   answer): No-AI shows a tool result's `spoken` / `summary` / `message` / `reply` (`offline/no_ai.py`
   `SUMMARY_KEYS`), else the result as compact JSON. `belongings_where` returns `{"found", "note"}`,
   so "where's my passport" with nothing noted reads `{"found": false, "note": "Nothing is noted
   under that name."}` (pinned in `test_r14_d_noai_app.py`; the words are right, the wrapping is
   not). `vault_tools`, `packages/tools.py` and `recall/tools.py` name none of the four keys either,
   so `vault_expiring`, `gmail_track_packages` and `memory_search` most likely read as JSON too
   (not run through their real tools here). The smallest fix for the not-found case, in a file that
   is not Part D's:

   ```diff
   --- src/jarvis/belongings/tools.py (where)
   -            return vouch({"found": False, "note": NOT_NOTED}, True)
   +            return vouch({"found": False, "note": NOT_NOTED, "message": NOT_NOTED}, True)
   ```
   The found case and the other three want a fixed-template `message` line each in their own
   modules (adding `note` to `SUMMARY_KEYS` would hide data for any tool whose result has a `note`
   beside it). The D12 eval and tests run on fakes that return `message`, so they cannot see this.
8. **The fakes moved** (v14.0.2, python review M2): Part D's shared fakes are
   `evals/r14/noai_fakes.py`; `tests/r14_fakes_d.py` is a 48-line loader (by path, like
   `tests/passkey_fakes.py`). Nothing for I1 to change; listed so a merge does not surprise.

## 4. Checks (one at a time, behind the shared `flock`)

| Check | Result |
|---|---|
| Own tests, 3.12: `test_r14_d_*.py` (215 since v14.0.2, v14.0.1: 150) + every existing test of the files touched and of the fakes they share (118 files in all) | **2,508 passed**, 1 skipped (v14.0.2; v14.0.1: 1,535 in 60 files) |
| The same, 3.11 (`/tmp/venv-b`) | **2,508 passed**, 1 skipped |
| Seam set (`test_r14_seams`, `test_r14_wiring`, `test_claude_guard`, `test_arch_coverage`, `test_telegram_tool_guard`) | 266 passed, 12 failed (the same 12 at v14.0.2): the 2 seam pins and the `TELEGRAM_SAFE` line of "Needs I1" (Part D being built), and 9 `test_claude_guard` "rm -rf" cases that fail in ANY checkout under `/home/claude/wt/` or `/tmp/` (the hook allows `rm -rf` there by design and the test resolves `src`, `tests`, … from the checkout); neither `.claude/` nor that test is touched on this branch (`git diff origin/r14-i0 -- .claude tests/test_claude_guard.py` is empty) |
| `ruff check` / `ruff format --check` (src tests evals scripts) | clean (1,671 files) |
| `mypy src` | the 9 baseline errors only (`core/window.py` 1, `llm/anthropic_provider.py` 7, `memory/redis_store.py` 1) |
| `mypy evals/r14/noai.py evals/r14/noai_fakes.py` (strict, v14.0.2) | no issues |
| `bash -n deploy/cloudrun.sh` | OK |
| `evals/r14/run.py --mock --part noai` | **41/41 passed; the control ("R14 phrases off") failed the suite: 31 of 31 rows** |
| R11.1's eval, plan part (the re-plan card moved) | 24/24; its control fails |
| `scripts/arch_coverage.py`, `scripts/check_doc_versions.py` | OK; 28 documents |
| `python -m jarvis.buildbook.gen --check` | R14 @ `6019b88`, two builds byte-identical |
| Browser (Chromium, `/tmp/venv-c`): `test_r14_d_console.py` | 4 passed; again with the optional extras blocked (aiomqtt, paho, cv2, numpy): 4 passed (v14.0.1; `console.js` unchanged since, so not re-run) |
| Browser: the console's existing files `test_r6_i1_console.py`, `test_r7_c_lock.py`, `test_console.py` | 45 passed |
| Coverage of Part D's modules (own tests) | `phrases_r14` 99 %, `r14_part` 100 %, `service_request` 100 %, `notes` 100 %, `sources` 100 %, `lock` 97 %, `upi` 96 %, `upkeep` 94 %, house `tools` 93 %, `auth` 92 %, `cards` 85 % (v14.0.1); v14.0.2 re-measured the changed ones: `phrases_r14` 99 %, `service_request` 100 %, `notes` 100 %, `auth` 90 %, `lock` 90 % (with `test_kb_api`, `test_permissions_api`) |

Sizes: `phrases_r14.py` 383, `service_request.py` 218, house `tools.py` 375, `auth.py` 265,
`console.js` 769 (≤ 800; `console.html` untouched), every function ≤ 50 lines.

## 5. What could not be verified here

- Whether Google sends `auth_time` for this app (v14.0.2: by Google's page, only once the app is
  published and verified and Session age claims is on). It no longer matters by default: a missing
  one counts as before R14; the log line "owner signed in again" says `auth_time=present|missing`
  after each re-sign-in, so the owner can see it before switching the setting on (section 6.2).
- The `claims` parameter's effect at Google (no live sign-in here); the URL it builds is tested.
- The No-AI answers of the real `vault_expiring`, `gmail_track_packages` and `memory_search` (only
  `belongings_where` was run through its real tool: Needs I1 item 7).
- Urban Company's address (`https://www.urbancompany.com/`) was not fetched; it is only shown as text.
- `deploy/cloudrun.sh` was not run end to end (no Google); its new block was run in bash with a fake
  `backup_setup.sh`, and the whole script passes `bash -n` and the deploy tests.
- The console change in a real phone app (only desktop Chromium here); the R7 cover's unlock with
  an unreadable store is R7's own path, already tested there.
- The full unit and browser suites (I1's, per the brief).

## 6. Review follow-ups (v14.0.2)

The three fresh-context reviews of `3474eeb` (security, code, Python; each WARN, no CRITICAL).
Each finding was fixed with a failing test first, or declined with its reason.

### 6.1 The shared HIGH: D13 (1), `auth_time` (security H1, code HIGH)

**Fixed as the Workshop decided** (`71b076e`). `/auth/login?reauth=1` keeps `max_age=0` and adds
`claims={"id_token":{"auth_time":{"essential":true}}}`; an ordinary sign-in sends neither; no
`prompt=login` (not one of Google's documented `prompt` values, so the security review's step 2 is
declined). `auth_time` present: the strict check as before. Missing or not a number: stale only
with `reauth_requires_auth_time` (Needs I1 item 5), else the moment it completed. The warning names
`reason=auth_time_missing`, `auth_time_old` or `auth_time_future`; an accepted re-sign-in logs
`auth_time=present|missing`; neither logs the token, the e-mail or the time. The security review's
go/no-go live check (step 1) and break-glass route (step 5) are not needed: the default can no
longer lock him out. The stale wording (step 4) is Needs I1 item 6 (the strings live in two console
files that are not Part D's). Tests: `test_r14_d_auth.py` (15): the `claims` parameter on a re-sign-in
and not on an ordinary one; missing with the setting off (fresh, the old way) and on (stale); present
and old (stale, either setting, logged as old); present and fresh (ok, either setting); the future
case; the setting read strictly. The 7 Google fakes keep sending `auth_time`.

### 6.2 What the owner may do later (optional, not required)

Nothing is needed for R14: re-sign-ins work as before. If he wants the stricter rule:
1. Have his Google sign-in app published and verified (Google's condition for the claim).
2. In Google Auth Platform → Settings → Advanced Settings, switch on "Session age claims" (off by
   default).
3. Do one re-sign-in (Permissions, "Sign in again") and look for the log line "owner signed in
   again": it must say `auth_time=present`.
4. Only then set `JARVIS_REAUTH_REQUIRES_AUTH_TIME=true` on the service (once I1 has added the
   field). If step 3 says `missing`, leave it off: on, it would refuse every re-sign-in (passkey
   set-up, the passkey reset, the build book, Privacy exports).

### 6.3 Every other finding

| Review · finding | Outcome | Test |
|---|---|---|
| Code M · `PUT` too wide ("I left the house at 9", "I left my job in March") | **Fixed** (`8aac59f`): `left` and `moved` dropped; a person, place, ride or money (`_NOT_A_THING`, the item's last word) is never a thing ("I put the kids in the car") | `test_r14_d_phrases.py::test_near_misses_are_left_alone` (6 new) |
| Code M / Py M3 (b) · `WHERE` takes "the toilet / my bus / the kids / my refund" | **Fixed**: the same `_NOT_A_THING` check, so "my car keys", "my bus pass", "my wife's phone" still route; the not-found answer through the REAL belongings tool is pinned (its fixed words reach him; the JSON wrapping is Needs I1 item 7) | `test_near_misses_are_left_alone` (9 new), `test_a_thing_named_after_a_person_or_a_ride_is_still_a_thing`, `test_r14_d_noai_app.py::test_where_with_nothing_kept_says_so_and_a_place_never_asks` |
| Code M · "book a plumber to call 9876543210" | **Confirmed and fixed**: a refused check is audited with an args HASH and the fixed refusal, never the words (`audit.make_entry` keeps `args_hash`); but with the AI off the owner read "That isn't available right now" (the refusal is not one of No-AI's own lines), so the router now answers `CONTACT_REFUSAL` itself, with no call | `test_r14_d_service.py::test_a_refused_request_leaves_no_number_in_the_audit`, `test_r14_d_phrases.py::test_a_service_ask_with_a_contact_is_refused_with_no_call` |
| Sec M1 · contact check misses date-shaped numbers, bare links, split and spelled numbers | **Fixed** (`101c858`): a date is blanked only when its parts are a real day, month and year; times blanked; 10+ digits in all, 6+ spelled digits, and `name.tld` links refused; "e.g.", "A.C.", "10.30 am", real dates and small numbers kept | `test_contact_details_links_and_bad_input_are_refused` (8 new), `test_a_day_or_a_time_is_not_a_phone_number` (3 new), `test_ordinary_words_and_small_numbers_are_kept` |
| Sec M2 · `problem` / `when` returned unfenced with `trusted_output=True` | **Fixed**: `trusted_output` dropped (the result taints the round); words not in his own message this turn (`taint.owner_text`) are fenced with `wrap_external`; his typed words stay plain (the No-AI reply reads as he wrote it) | `test_the_result_is_never_his_own_data`, `test_words_he_did_not_type_are_fenced_as_data` |
| Py M1 · strict mypy error at `evals/r14/noai.py` | **Fixed** (`fca42b1`): rows unpacked by name | strict `mypy` on the eval: no issues |
| Py M2 · the eval imports `tests/r14_fakes_d` through `sys.path` | **Fixed**: `evals/r14/noai_fakes.py`, loaded by path by both (Needs I1 item 8) | `test_r14_d_eval.py`, every test importing `r14_fakes_d` |
| Py M3 (a) · bare "time" / "date" | **Fixed**: "the time", "current time", "time now", "today's date", "date today" kept; a bare word is a topic | `test_a_bare_time_or_date_word_is_not_a_question` |
| Code L · "book a handyman for 5 pm" read "5 pm" as the problem | **Fixed**: the problem may not start with a time or a weekday ("for 2 leaking taps" still is one) | `test_a_service_time_is_never_read_as_the_problem` |
| Py L3 · locale-dependent day and month words | **Fixed**: fixed English `DAYS` and `MONTHS` | `test_the_day_and_month_words_do_not_depend_on_the_locale` |
| Py L2 · `_one` duplicates `rules._one` | **Fixed**: renamed `_call` | the router tests |
| Sec L1 · notes export with no gateway answers | **Fixed** (`90918e7`): refused, 503 `export_unaudited` with `NO_CHAIN` | `test_r14_d_notes.py::test_without_an_audit_chain_the_export_is_refused` |
| Sec L2 · `--status` call has no `timeout` or `</dev/null` | **Fixed** (`05c174a`) | `test_r14_d_deploy.py::test_a_status_check_that_hangs_is_cut_off`, `::test_a_status_check_never_reads_what_he_types` |
| Sec L3 · no router test on a Telegram turn | **Fixed** (a pin; the gateway's Telegram rules already refused): things, the vault, the inbox and Recently deleted are refused and nothing is read | `test_r14_d_noai_app.py::test_on_a_telegram_turn_the_private_rows_stay_refused` (5) |
| Sec L4 · `memory_search` open on Telegram | **Not Part D's to change** (`TELEGRAM_SAFE` and the Telegram rules are I1's / R1's). For the owner: "what do you remember about …" with the AI off is one call to his saved memory from Telegram, the same reach the model already has there. Whether memory should follow the PERSONAL group (its own switch) is his decision | none |
| Sec L5 · console cover gaps (non-JSON 503, `unsure` does not throw) | **Declined**: not a hole (the server refuses every request; a page script needs XSS first); `console.js` stays at 769 lines | none |
| Py L1 · `lift` reads his own malformed mark strictly | **Declined, pinned** (`54650a2`): a lenient read would drop his own mark, the hole D13 (2) closes; his malformed document fails closed on every read, so a lift with it is not reachable; docstring says so | `test_r14_d_lock.py::test_his_own_malformed_mark_is_never_read_leniently_by_a_lift` |
| Py L4 · `pay_cap_paise()` re-reads cached settings; `max(1, …)` duplicates `ge=1` | **Declined**: cached (`lru_cache`), and the guard is defence in depth | none |
| Code L · "help" alone is taken | **Kept**: a whole-message ask for what he can do, only with the AI off | `test_what_can_you_do_lists_the_eleven_skills_and_what_works_with_the_ai_off` |
| Code L · no Hindi / Hinglish forms | **Declined** for R14: the plan lists none; they fall through to pass 1 and the fixed line (safe) | none |
| Code L · test edits outside the row; "Lekha" | **No change**: the edited fakes are tests of `api/auth.py` (I1 should watch `book_app_fakes.py` and `r7_fakes_c.py` at the merge); "Lekha" is the plan's and the codebase's existing example name (21 files before R14), not a person's data | none |

## Change log

| Version | Date | Release | What changed | By |
|---|---|---|---|---|
| v14.0.2 | 14 Nov 2026, 18:10 IST | R14 | Review follow-ups (section 6): D13 (1) rebuilt as the Workshop decided (the `claims` parameter, a missing `auth_time` stale only by `reauth_requires_auth_time`, kinds in the log) and met only partly, with the reason and the owner's optional step; the routers' `PUT` / `WHERE` / time / service fixes; the contact check and the fenced, untrusted service result; the eval's own fakes module and strict mypy; the notes export with no chain refused; the deploy's status call cut off and fed `/dev/null`; Needs I1 items 5–8 (the `config.py` field, the stale wording, the No-AI JSON answers, the moved fakes); the checks re-run | 🛠 Mark XIX |
| v14.0.1 | 14 Nov 2026, 17:25 IST | R14 | First edition: Part D built test first on `r14-d` (No-AI pass 2's 13 routers, row 101's car-service starter, row 102's `maint_service_request`, D13 (1)–(6) and the deploy and docstring lines), the existing tests moved with their files, the decisions taken differently, Needs I1 (two seam pins, `TELEGRAM_SAFE`, C's catalogue, the persona line), the checks and what could not be verified | 🛠 Mark XIX |
