Version v6.3.1 · 23 Nov 2026, 17:24 IST · Release R6.3 · Status: Current · Owner: 🛠 Mark XXIV

# R6.3 — Part B brief: the writer (Opus)

Read `BRIEF-COMMON.md` first (the loop, the rules, the seams, the commands). Branch `r6-3-b` from
`origin/r6-3-i0`. **`security-reviewer` is REQUIRED** (money, consent, the free brain's data rule,
the checks, sealing). Plan sections: D1's use, D4–D8, D10, D11, D12, D13, the data model, the HTTP
contract, the `writer` suite and its controls, "Tools: none new".

## 1. Your files (only these)

`src/jarvis/buildbook/writer/{packs,prompts,checks,fill,caps,consent,estimate,run,store,pages,
texts,vault,carry,sweep}.py` (new), `writer/job.py`, `writer/privacy.py` and `writer/part.py`
(replace I0's stubs), `src/jarvis/api/book_writer.py` and `api/book_pages.py` (replace I0's stub
routers), `tests/test_r63_b_*.py`, `tests/r63_fakes_b.py`, `evals/r6_3/writer.py` (I0's stub:
replace it), `docs/plans/r6-3-integration/INTEGRATION-B.md`. Every module ≤ 400 lines, functions
≤ 50. **Not yours:** `writer/model.py`, `writer/http.py`, `writer/ports.py` (the contract),
`llm/write.py`, R6's sealing and Privacy files (BRIEF-COMMON section 3), `api/r6_wiring.py`,
`api/book_writer_wiring.py`.

## 2. Your contracts

- **The join** (`part.py`): `build(ctx: WriterContext) -> WriterPart(service, job, privacy=(…),
  ready)`; the job is `book_write` (`model.JOB_NAME`; anything else is "setup failed"). Your
  service is `app.state.book_writer`; your routes read it per request. No keyring: you are not
  built (the wiring's rule). The primary owner only (`ctx.uid`, L11): another owner e-mail is 403
  `not_primary`.
- **Imports (D1, D4; `tests/test_r63_static.py`):** from `jarvis.llm` only `write`, `brains` and
  `router.ModelTier`; nothing from memory, vault, mail, contacts, documents, tools, core,
  integrations or the app, no vendor SDK. **No model id, vendor name or price in a string
  literal** of your files: the brain's name is `spec.label`, its maker `write.maker(spec)`, its
  model `write.model_of(spec)`; `model.GST_NOTE.format(maker=…)`. No real clock: `ctx.clock()`.
- **The call** (D1, D5): `write.write_text(ctx.brains.router_for(brain), tier=BALANCED, …,
  max_tokens=model.MAX_TOKENS, timeout_s=…)`; `tools` never sent. Refuse a page whose `tier` isn't
  BALANCED, whose `model` differs from `model_of(spec)`, that came back empty, or that is not
  `complete` (L10), before the checks. Offer only `write.offered(spec)` brains (M2); a missing one
  "not set up on this server". Record `PageMeta` from the `Written` result.
- **Where it runs (D5, H7, M3):** `book_write` on the morning tick and LAST on the 5-minute clock
  (I0 wired both; Home on or off). Free work every run (the sweep, the free carry, `update_ready`,
  the storage check and its notices); brain calls only inside an approved run, under the lease
  (`book_write_lease/{uid}`, held until the step's deadline + 30 s); on a clock a call starts only
  while `ticks.time_left()` ≥ that brain's p90 seconds + 5 over its last 20 calls
  (`WriterDoc.seconds`), at most 2 at once; with no measured call the clocks start none, so **the
  trial runs on the console step** (`POST …/step`: its own `STEP_BUDGET_S` 150 s, one call at a
  time with `STEP_CALL_TIMEOUT_S` 120, at most one step at once (409 `busy`) and 6 a minute). The
  HTTP table's "≤ 45 s" for `step` is superseded by D5's 150 s (I0-NOTES).
- **Money (D8, M1, H7):** `writer/caps.py`, R13.1's pattern (`wardrobe/seeme/cap.py`): ONE
  transaction reserves each call's hold = `write.worst_usd(spec, BALANCED, bytes_sent / 2.5,
  MAX_TOKENS, system_cap=SYSTEM_TOKENS)` at the day's rate (₹11.84 a first draft at ₹95.24, ≈ ₹13.13
  a redraft); refused with nothing written when spent + held + hold would pass the run's cap or
  the month cap, or the 80 % gate fails (his Vitals month + the ledger's open holds + this hold ≤
  the % line × his limit; no limit → the Book's caps only); `busy` while a hold under 10 minutes
  exists for the page; `close_later` and `settle_old` first; the month before read for an hour after
  his IST month's end. **The trial's cap is ₹100** (`Caps.trial`, his answer): 8 worst-case holds
  fit, the 9th is refused before it is sent. Settle at the reported usage; a cut call at
  `stream_usage` + 10 % of the output (≥ 200 tokens), never above its hold, never below what was
  received; `WriterUnavailable` → released; a settle above its hold stops the run. Every settled
  call → `ctx.billing.record(uid, "book", usd)` (Vitals: "Book writer"). Unreadable ledger or limit
  → refused (fail closed). Estimates (`writer/estimate.py`): bytes ÷ 4 / 3 / 2.5, outputs
  2,200 / 3,000 / 3,500, redrafts 15 / 25 / 30 % with +3,000 tokens each; `write.estimate_usd`;
  "about ₹<`about_inr(mid)`>"; ₹ only.
- **Consent (D6, D7, D12, H2):** exactly `YES` (`model.is_yes`) bound to the `estimate_id` shown
  (409 `estimate_changed`); every grant is his typed YES on the ₹ words shown: the first pick
  (`confirmed` starts at zero), any cap or the % line raised, a paid brain, a training brain (the
  learning note, no ₹), "update by itself" on ("up to ₹500 a release and ₹1,000 a month (your
  caps), by itself after each deploy, with no question asked"). Without it `PUT …/pick` saves
  nothing and answers 422 `yes_needed` `{terms_id: "wt_…", words}` (`http.YesNeeded`); the same
  pick with `typed: "YES"` and that `terms_id` saves; a changed pick → 409 `terms_changed`;
  lowering is instant. The writer's Gemini pick is its own consent, separate from the
  talk-through's `allow_training_brain` (L8). `POST …/first` needs the pick and a second YES on its
  estimate (409 `pick_needed`, `estimate_changed`); `POST …/update` takes his YES on its ₹ (409
  `use_first` past the release cap or with nothing to carry from, H3).
- **Packs (D4, M8, L7):** from the release's `source.zip` and `facts()` only (`ctx.source`),
  never `.claude/**`, `tests/**`, `evals/**`, `.env*` / `*.env` / `*.env.*`, key-shaped files,
  `gen/fake_secrets.txt`, `gen/redact.json`, `*.lock`, binaries or the snapshot's left-out files,
  and nothing from Firestore, the vault, memory, mail, contacts, photos, cameras, Book settings or
  logs; ≤ 96,000 UTF-8 bytes (plan text dropped first, then signatures, never the card); every pack
  through `gen/scrub.default_scrubber().clean` (A adds the new kinds and phrases); fenced with a
  canary; the same pack to every brain.
- **Checks (D10, H5):** in `writer/checks.py`, the six, redraft once with the failures listed,
  then the previous text; the exemptions of check (2) and the precision case; `fill.py` writes the
  values; the `CheckCode`s of `model.py`.
- **Sealing (D11, M4, H3, M5):** `writer/vault.py`: the pages index `book_pages/{uid}` sealed with
  `ctx.keyring.cipher(model.INDEX_PURPOSE)` under `model.aad_pages_index(uid)`, chunks in
  `book_pages/{uid}/book_chunks` with R6's envelope (`seal_index.BookCrypto.seal`, `seal_chunks.BookChunks`);
  attach or replace in ONE transaction (old chunk set → `orphans`); R6's Privacy hold checked in the
  same transaction (`seal_state.lease_path`, `held_of`: `SealHeld`); a pages file whose release
  isn't in R6's index is never served; attach refused past `book_max_total_mb` counting R6's total
  (`ctx.vault.used_bytes`) plus the pages files. The free carry at each new release (no brain
  call), the sweep, runs bound to their release, the 80 % storage line (`http.StorageView`).
- **Notices (D11):** through `ctx.notifier` with R6's kinds (`book_sealed`, `book_seal_failed`),
  your own words, claimed in `WriterDoc.told` per (release, what); never R6's per-release claim.
- **Privacy (D13):** the row "Build book: writer" (`writer/privacy.py`, id `book_writer`): counts
  and MiB, export, delete with his passkey that stops any run; the ledger stays 13 months.
- **Routes** (exactly `http.ROUTES`, the models of `http.py`): console rows
  `book_gate.console_only`; session rows an OWNER book session's `X-Jarvis-Book` (a guest's 403
  `owner_only`); `no-store`; `http.LIMITS`; every refusal `http.Refusal` in plain words; audited
  by field names, ids and ₹ only (`yes_confirmed`), never values or text.
- **Logs** content-free (`test_book_boundaries.py` scans every `writer/*.py` and both route files:
  no `text`, `page`, `pack`, `prompt`, `draft`, `pages`, `reply`, … variable in a log call).

## 3. Your rows and their named tests (each its eval case of the same name)

| Row | Your test (what must hold) |
|---|---|
| 379 | **`test_row379_a_page_is_written_at_balanced_with_an_example_and_every_source_checked`**: the fake Claude brain writes `pg_card_c16` (use the fixture's `pg_card_c01` with `GOOD_DRAFT` until A's real pack: say which in INTEGRATION-B); the sealed page has the six sections, `example` marked "Example (made up)"; every reference in the index; every number outside the example a filled placeholder; meta brain `anthropic`, tier `balanced`, model = the registry's; the same page from a router that answered on FAST, or `offline`, refused and the generator's text stays |
| 23 Nov · trial | **`test_the_trial_spends_nothing_before_yes_and_stops_at_its_cap`**: zero calls before `YES`; "yes", "Yes", "YES!" refused; 5 + 5 pages with the fake brains; with every Claude call settling at its hold the **₹100** cap lets **8** calls through and refuses the **9th** before it is sent; a settle above its hold stops the trial (M1); the side-by-side rows; a guest session 403 on every trial route |
| 23 Nov · pick | **`test_the_first_write_needs_the_pick_and_a_second_yes_on_the_estimate_shown`** |
| 23 Nov · deploy | **`test_nothing_spends_by_itself_after_a_deploy`** (50 `book_write` ticks after a new release id: no call, the free carry, one `update_ready` with its ₹; after Update with YES the changed pages only) and **`test_spending_authority_needs_a_typed_yes`** (H2) |
| 380 · grows (your half) | `test_row380_the_update_estimate_counts_a_new_card` (A builds its page; you count it) |

## 4. Your eval (`evals/r6_3/writer.py`) and its controls

Cases: the plan's `writer` row, through `jarvis.llm` with the fake brains (`tests/r63_fake_brains`),
with the trial's numbers at ₹100. **Controls that must turn it red** (the plan's list): the hold as
read-then-write (two parallel calls pass the cap); the YES check off; auto-update accepted without
its YES; a paid-tier Gemini offered at ₹0; `write_text` built on `complete()` (the no-laptop case);
the carry run only on Update (the three-seal case); no replace in the pages vault (the continue
case); the Privacy hold check off (the delete case); a pages entry written into R6's index (the
rollback-reader case: a copy of 47ee8fc's `BookIndex` model must still open R6's index); the run's
YES carried to a new release (M5); the reference check off; one exemption of check (2) removed (the
precision case); `.claude/**` or `tests/**` in a pack; and each row's own: the tier check off (379),
the cap check off (trial), `first` accepted without the second YES (pick), `book_write` starting an
update without his Update (deploy). Set `BUILT = True` only when every control fails its case.

## 5. Limits

No new tool, permission row, alert kind, Scheduler job, secret, keyring purpose or setting; never a
model call at start-up; never a real model call in a test. INTEGRATION-B.md lists the service's
methods the routes use, the exact notices' words, every deviation, "Needs I1".

## Change log

| Version | Date | Release | What changed | By |
|---|---|---|---|---|
| v6.3.1 | 23 Nov 2026, 17:24 IST | R6.3 | First edition, written at I0: Part B's files, contracts (the join, imports and literals, the call, where it runs, money with the ₹100 trial cap, consent and every grant's YES, packs, checks, sealing in its own index, notices, Privacy, routes, logs), its rows and named tests, the `writer` eval with its controls, limits | 🛠 Mark XXIV |
