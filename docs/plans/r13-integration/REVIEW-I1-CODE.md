Version v13.0.3 · 16 Nov 2026 · Release R13 · Status: Current · Owner: 🛠 Mark XXI (fresh-context code and Python review, I1)

# R13 I1 code and Python review (r13-i1 @ 25a0de8, main 34924ca)

Reviewer: fresh context, read only. Ran: the offline-marker bisect (pytest, flock, <venv>), the
phase0 mock eval (copied to <scratch copy>, so the repo is untouched), a count script for the pins.
NOT finished (the server restarted and killed the queued runs): the fix-validation run of the
pollution fix, and the live probe of findings H1, M1 and M2. Those three are from reading the code,
marked "static". Everything else below was read in the code.

## Verdict: FIX FIRST (small). No CRITICAL. Two HIGH (one real nightly false alert, one vacuous
eval plant). The rest is MEDIUM or LOW.

## Findings

| Sev | File:line | What goes wrong | Fix | Test that catches it |
|---|---|---|---|---|
| HIGH (static) | laundry/providers.py:79-91, laundry/jobs.py:54-62 | A's `archived` (wardrobe_retire, merge tombstone, bin remove) is allowed from `with_provider` (states.py `_ANY`). `outstanding(batch)` reads only the batch, not the ledger. The piece stays outstanding, `plan_receive` refuses it (state != with_provider), and `corrections` close a batch only on a strike-out. So `laundry_daily` sends "overdue" every day with a fresh claim key (`laundry_overdue_{id}_{day}`), and the batch cannot be closed. Loads are safe: `loads.remaining` filters on state. | `outstanding(batch, view)` counts only pieces whose state is `with_provider` (or in review). Close the batch when none is left. Alternatively an observer closes it on `archived`. | send_out, wardrobe_retire archive, advance past due, run `laundry_daily`: no alert, batch closed. |
| HIGH | evals/r13/needles.py:112-123 | The `foreign_qr` needle is posted as `jw1:QXFORE12`. `LABEL_CODE` is `^[a-z2-7]{8}$` (model.py:38), so `LabelAssign` answers 422 before any code runs. The needle never enters the system and the class passes vacuously. `_week` ignores every `w.send` status, and the per-sink controls only plant a marker in the search text. The `phone` and `ocr_text` needles ride in `note` and end up in sealed docs, which are invisible by construction. | `_week` records each plant's status and the suite asserts it was accepted (200). For the foreign QR use a code that passes the schema but is not his, and assert the refusal word. | New case `needles:planted_all`. Control: turn one plant into a 422 and see it fail. |
| MEDIUM | evals/r13/e2e.py:202-218 | The e2e 8 control only does `unavailable += 1`, so it proves nothing about `_suggested_ok`. `wrong` (state corrections) is always 0 because the run never corrects anything. The pass line is vacuous on its second half. | The control should plant a real bad suggestion: patch the engine's eligibility to include in_laundry, and expect `_suggested_ok` to count it. Add one real `laundry_correct` and assert `state_corrections == 1`. | Control run with the patch. |
| MEDIUM | catalog/pilot.py:21-50, api/wardrobe.py:241-251 | I1 item 23 leaves `suggested` and `unavailable_suggested` at a constant 0. The route returns 0 as if measured, and on any exception or no desk it returns all zeros (a broken pilot reads as perfect). The Workshop wording "not measured in v13.0.0" appears nowhere in code or the panel. `passes()` has no caller (dead). The docstring says "joined at I1; 0 until then", which is now false. | Make both fields `int \| None`, None while unwired, and have the panel say "not measured". Return 503 on failure, not zeros. Delete `passes` or use it. Fix the docstring. | Route test: with no `plan_counts` the reply has null, and a thrown read is not 200 with zeros. |
| MEDIUM (static) | catalog/data.py:34-36, laundry/store.py:273-279, styling/data.py:24-28, privacy.py:75-78 | Privacy counts hide kept data, and `deletable = total > 0` then refuses the delete (sources.py:81). A: `count` is `active()` only, so a wardrobe of archived or merged pieces, or one that only has places, labels and settings, shows 0 and cannot be deleted, while his labels are still sealed there. B: only OPEN loads, batches and entries count; closed ones (kept 90 and 30 days, with his shop label) show 0 and cannot be deleted. C: only plans count, so a kept calendar choice or weather alone shows 0. | Count what is kept: `len(view.pieces)` plus index, every doc that exists. At least make `deletable` true whenever any document exists. | Archive the only piece: the row shows count above 0 and delete works. Close the only batch: same. |
| MEDIUM | catalog/data.py:68 and phone/privacy.py:97-105 | The "Wardrobe pieces and places" delete also removes every photo and fingerprint (data.py docstring), but the row text says nothing of it. | Say it in the row's `what`. | Docs pin. |
| MEDIUM | laundry/jobs.py (with catalog/jobs.py:68-69) | In A's sweep `sweep()` runs `_close_wears` then `_repair_holds`. If C's closer raises (bad rules or a doc that can't be opened), `_repair_holds` is skipped for that owner every day, though the docstring says the rest goes on. | Separate try for the closer, log its class, still run the repair. | Closer that raises: holds still repaired. |
| MEDIUM | api/r13_wiring.py:213-222 | `join_sweep` returns silently when C is off or has no rules. Forgotten wears are then never closed and nothing says so. | `log.warning` with the part's `ready` word. | Wiring test with styling failed. |
| LOW | catalog/tools_write.py:42-48,77-85 | Spoken or tainted refusal covers `label`, `set_label` and `place` by words, but not `brand` and `size`. Both are free text and sit in a card's stored arguments. (Brand is shape-checked by `BRAND_RE`, so low.) | Add both to `_own_words`, or say why not. | Spoken edit with a brand. |
| LOW | catalog/store.py:206-225 | `CatalogStore.correct` has no caller. It would skip B's `reconcile_laundry` and `reconcile_review`. A future caller breaks the seam (loads and batches stay wrong). | Delete it, or route it through B's `plan_correct`. | Grep guard test. |
| LOW | api/wardrobe_settings.py:79-84 | `{"ai_tagging": null}` counts as sent (`model_fields_set`), so the audit says it changed while nothing did. | Drop None values from `sent`. | PUT with null. |
| LOW | styling/jobs.py:126 | `assert cal is not None` in production code (stripped under -O). | `if cal is None: return`. | n/a |
| LOW | tests/test_r13_i1_e2e.py:11-13, evals/r13/wired.py:25-27 | `sys.path.insert(0, evals/r13)` makes the eval's `catalog`, `styling`, `phone`, `contract`, `run` top-level names that win over anything else imported later. wired.py also inserts src and tests at import. | Load by path, as run.py does (`spec_from_file_location`). | n/a |
| LOW | api/app.py `_install_core_errors` 53 lines, api/personal.py `privacy_sources` 52 | Over 50 lines. Both were already near the line before R13 (personal.py +1). | Leave, or split. | n/a |

## The test-order pollution (priority 3): root cause CONFIRMED

Reproduced with two files: `pytest tests/test_offline_rules.py tests/test_r13_a_routes.py` fails
`test_the_view_is_the_owners_and_answers_its_model` with `status='needs_approval'` for `wardrobe_add`.
test_offline_prompt, test_offline_service and test_r1_seams as the first file all pass.

Cause: `jarvis.core.channel._offline` holds a MUTABLE list, `[bool]`. It is shared on purpose with
child tasks. `OfflineRules` (offline/rules.py:47) adds an ASK rule on every R2 write while
`answered_offline()` is true. In test_offline_rules.py the autouse fixture `_fresh` only resets
BEFORE each test (no yield), and the last tests call `channel.mark_offline()`. An async test runs in
a task, but the list it mutates is the one in the main context, so `[True]` is still there when the
next file starts. Nothing resets it until a file with its own reset runs. The panel route
(`api/wardrobe.py:~296`) sets `context_trust(...)`, which does not touch the offline marker, so
every R2 call becomes a card, and `_add` in test_r13_a_routes and test_r13_i1_settings asserts
"executed". The e2e and replay tests survive only because `World.ok` approves cards. The default
order is clean because test_r1_seams (autouse reset) and others run between test_offline_rules and
test_r13_*; `-k "r13 or doc or guide or persona"` drops those.

Test-only or production? Test-only in practice. In production every request runs in its own task,
and `Brain` calls `reset_offline()` at the start of each turn, so the holder never crosses
requests or owners. One small real edge: a task created INSIDE an offline turn shares that turn's
list for its whole life (a fire-and-forget gateway call would ask). Another: `mark_offline()` with
no reset in a long-lived loop task (a scheduler job that calls the fallback brain) sticks to that
task's context. Neither touches the wardrobe path. LOW.

Fix: in `tests/conftest.py` add an autouse fixture that resets before AND after the test:

    @pytest.fixture(autouse=True)
    def _offline_marker_clean():
        channel.reset_offline(); yield; channel.reset_offline()

Also turn `_fresh` in test_offline_rules.py, test_offline_chain.py and test_offline_service.py (and
`_clean_offline_marker` in test_r1_seams.py) into yield fixtures. I wrote the plugin form of this fix
(<scratch>/offfix.py) but its run was killed, so "the fix works" is predicted, not run.
Optional hardening: the e2e `World.ok` hides asks, so add an assertion that a plain wardrobe_add
executes without a card.

## New facts from the coordinator's full run

1. Eight old wiring pins fail (r11 2, r2 2, r4 3, r51 1): not read, not in R13's files. They are the
   "switched off leaves no tool, route or job" style, and R13 adds a part to the same lists, so they
   likely need their pinned counts moved. Not verified.
2. phase0 `--mock` 4/12: reproduced at HEAD (copy in <scratch copy>), but it is NOT caused by R13.
   `MockProvider._reply` returns "Certainly, Sir. You said: <last user text>" and ignores the system
   prompt, so persona p13.0 and WARDROBE_RULE cannot change it. `evals/phase0/run.py`,
   `cases.jsonl` and `mock_provider.py` are identical to main (diffed). run.py itself says "checks
   will mostly fail" under --mock; `run_all_mock.py:58` lists it as a non-gated smoke, and it
   returns 0 under --mock. A cases file that needs "Nightingale", "8848" or "17:15" cannot pass with an
   echo mock, so I could not get 12/12 on main from this harness. I did not run main. Ask how the
   12/12 run was made (a scripted provider or an old report.json; report.json is untracked).
3. r7 `sealed_no_value: ['131 in clear']`: likely a chance match, not a leak. The needle is 3 digits
   searched in the plain fields and log rows (body.py:213-218). The author already excluded blobs for
   this reason (0.3%), but plain fields hold timestamps and hex ids. `Rig()` is r7's own, and R13
   touches none of its files. Not re-run. Fix: match the needle with delimiters, or a longer value
   (131 becomes a distinctive max such as 131.25).

## I1 decisions against the plan
- Spoken turns refuse label, set label and place by words: built in `_own_words`, and A's tests
  cover it. Gap: brand and size (LOW above).
- Pieces cap 500: config le=500, default 400; plan D1 already says 50-500. Fine.
- Declined events still get plans: recorded in plan D13 as the owner's decision. Code reads no
  response status, consistent. Fine.
- Overflow sentence: texts.py:196 and jobs.py `_ready` build "Tomorrow's outfits for N more events
  are ready in Helpers, Wardrobe." Claimed once per day, so a 4th-plus plan found after the line was
  sent is never mentioned (it is in the panel). Acceptable.
- Fifth Privacy row: five rows, `row` attribute on all four data sources, fail-closed on an unknown
  row. Fine, but see the count findings.
- Item 23: see the MEDIUM on the pilot.

## Checked and fine
- One `CARD_ONLY` (states.py:147); B's history, B's corrections and A's `correct` all import it.
- One rewear source: `rules.json` through `Rules.after_wear`; nothing else defines it. The sweep
  closer is bound in `join_sweep` to C's `close_forgotten`; the client id `wclose-{piece}-{day}` makes
  a second close in a day a duplicate.
- A correction that leaves a piece held opens its check in the same commit (`work._asks`, B's
  `_reopen` is the backstop); the sweep repairs with the piece's own hold word.
- `fold` is pure, sorted by (at, recorded, id), marks never written back. Camera rule `admit` now
  applied by the store for every event.
- Settings join: PUT is owner-only, `extra=forbid` (lead_h and auto_swap refused), the audit holds
  field names only, A's three switches and C's four are read from one place each.
- `ToolCall.session_id`: a conversation that is not his is never used (`_conversation`).
- Unknown piece ids in laundry tools are dropped by `holds.known`; no KeyError path from the model.
- Pins: 56 alert kinds, 24 key purposes, 52 permission rows, 18 tools (counted by import); the
  save cap is 54 in permissions/models.py with 52 rows.
- Limits: every new Python function is 50 lines or less (script over the diff; only the two older
  ones above); wardrobe modules at most 393 lines; app.py 732; gateway.py 760; config.py 780; scan
  JS 596. No print, breakpoint or console output in the new code. Mutation limited to wiring
  (`store.bind`, `job.closer`) and the pydantic copies elsewhere.
- Replay test: covers the recorded corpus, D's sentences and the JS literals, with a working control.
  It checks schemas, not values (an enum or a pattern that a refusal covers is not caught).

## Not done
Live probes of H1, M1, M2; the fix-validation run; main's phase0 run; the r7 eval re-run.
