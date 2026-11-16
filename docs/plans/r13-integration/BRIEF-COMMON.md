Version v13.0.1 · 15 Nov 2026, 19:05 IST · Release R13 · Status: Current · Owner: 🛠 Mark XXI

# R13 — the common builder brief (Parts A–D)

Read this, then the plan `docs/plans/r13-wardrobe.md` (v13.0.2, Status Ready: the decisions D0–D22,
your part's row in "Part split", its acceptance tests, the evals table and the size guards),
`docs/plans/r13-integration/I0-NOTES.md` (what I0 built, the stale lines it found, what it left for
I1), `PLAN-REVIEW-1.md` (why the plan says what it says), then `CLAUDE.md`,
`.claude/rules/ecc/common/*.md` and `.claude/rules/ecc/python/*.md`. You build ONE part, in parallel
with the others, on your own branch from `r13-i0`. Everything you may touch is in your part's row;
everything else is someone else's. When in doubt, don't edit: write it in your
`INTEGRATION-<PART>.md` for I1. The owner answered "defaults OK" to the plan's 14 questions (15 Nov,
18:38 IST): every safe default in the plan stands.

## 1. Your branch, your commits

- Worktrees and branches `r13-a` (A · Catalog and the ledger, with OPS-03 and OPS-06), `r13-b`
  (B · Laundry), `r13-c` (C · Styling, with LND-16 and OPS-04), `r13-d` (D · Phone and panel), each
  from `origin/r13-i0`, e.g. `git worktree add .claude/worktrees/r13-a -b r13-a origin/r13-i0`.
  Push after every commit: `git -c push.negotiate=true push -u origin r13-a` the first time, then
  `git -c push.negotiate=true push`. Never rebase, never force-push, never `rm -rf` outside `/tmp`
  or `.claude/worktrees/`, never `git stash` while a background run uses the tree, never edit lint,
  format, type-check or coverage-floor files to make an error go away. Never touch `main`, another
  part's branch or another agent's worktree (the R6.2 builder works in `.claude/worktrees/r6-2`).
- **The hook.** `.claude/settings.json` runs `.claude/hooks/guard.py` before every Bash, Edit, Write
  and MultiEdit call. **A blocked action means stop and report it in your INTEGRATION file and to
  the Workshop; never work around it** (no other spelling of the same command, no editing the hook).
- Conventional commit messages (`feat(r13): …`, `fix(r13): …`, `test(r13): …`), each ending with
  exactly the trailers the Workshop gives you, with `JARVIS-Version: v13.0.0` and
  `JARVIS-Mark: XXI`.
- The repository is PUBLIC: no personal data (names, e-mail addresses, phone numbers, addresses,
  account numbers, his real wardrobe, calendar or laundry shop), no keys, no project ids, no chat
  links (the trailer is the only one), no local paths, in code, tests, fixtures or docs. Fixtures
  use made-up pieces (`tests/r13_fakes.py` `PILOT`), `example.com` and pictures you draw.

## 2. The rule: never edit a wiring file or a shared file

I0 built every join. A part plugs in through **one function**, `build(ctx: WardrobeContext) ->
WardrobePart` (`jarvis.wardrobe.ports`), in its `part.py` (`wardrobe/catalog/part.py` A,
`wardrobe/laundry/part.py` B, `wardrobe/styling/part.py` C, `wardrobe/phone/part.py` D), its own
route file and its own console modules. You never edit:

- `src/jarvis/api/app.py` (732 lines, guard ≤ 735), `api/r13_wiring.py`, `api/r13_status.py`,
  `api/tick_wiring.py`, `api/personal.py`, `api/console.py`, `tools/setup.py`, `home/watchdog.py`
- `src/jarvis/tools/gateway.py` (760 lines, not edited), `core/brain.py` (713, guard ≤ 741, not
  edited), `console.html` (782 lines, byte-identical to `9a8392b`: pinned by its SHA-256)
- the contract: `wardrobe/ports.py`, `wardrobe/states.py`, `wardrobe/model.py`, `wardrobe/redact.py`,
  `wardrobe/http.py` (with `http_views.py`, `http_parts.py`), `vision/results.py`,
  `vision/assets.py` and the port core of `console-vision.js` (a contract change needs the exact
  diff under "Needs I1" in your INTEGRATION file: the other parts build against it)
- the alert kinds and every table that names one (`alerts.py`, `notify/ports.py`,
  `notify/policy.py`, `notify/held.py`, `webpush/service.py`, `buildbook/plain.py`,
  `console-alerts.js`), the key purposes (`keyring.py`), the permission rows and the save cap
  (`permissions/groups.py`, `permissions/models.py`), the bin's kinds (`undo/models.py`,
  `console-deleted.js`), Telegram's patterns (`telegram/rules.py`), `core/guardrails.py`, the
  settings (`config.py`), `offline/mode.py`, `offline/phrases_r14.py`, the skill register
  (`skills/catalogue.json`, `skills/registry.py`), `understand/words.py`, the guide
  (`docs/architecture/*`) and the layer map (`buildbook/gen/layers.py`): I0 added all R13 needs
- the console frames: `console-helpers.js`, `console-camera-panel.js`, `console-r7.js`,
  `console-r7-send.js` (the ONE picture door: `wardrobe()` and `tag()` are I0's)
- `tests/test_r13_seams.py`, `tests/test_r13_wiring.py`, `tests/test_r13_fold_conformance.py`,
  `tests/r13_fakes.py`, `tests/r13_fakes_store.py`, `tests/r13_fake_server.py`, `evals/r13/run.py`,
  `evals/r13/contract.py`, `evals/run_all_mock.py`, every earlier release's seam test,
  `.claude/**`, `pyproject.toml`, `.github/workflows/*`, `CLAUDE.md`

If you need a change there, stop and write it under "Needs I1" in your INTEGRATION file with the
exact diff you propose. A pin in an earlier release's test that your part legitimately moves is the
one exception: say which, and why, in your INTEGRATION file.

## 3. What each part owns

Exactly the plan's "Part split" row for your letter. In short:

- **A · Catalog and the ledger** (INV-01–17, OPS-03, OPS-06): `wardrobe/catalog/*` (part, store,
  fold, service, search, counts, places, labels, photos, fingerprints, tagging (it calls
  `picture.eyes.BrainEyes.look`), backup, restore, merge, undo, data, pilot, tools, jobs),
  `api/wardrobe.py` (every `ROUTES` row of "catalog", and `POST /v1/wardrobe/tools/{tool}` through
  `gateway.execute`), `tests/test_r13_a_*.py`, `tests/r13_fakes_a.py` (with
  `conformance_store(docs, now)`: the conformance test then runs every case on your store too),
  `evals/r13/catalog.py`, `INTEGRATION-A.md`. `security-reviewer` required (photos, the backup's
  seal and the restore, the tag call). The order rule is yours (D0, D4): the fold, the dedup, the
  time rule, the one commit.
- **B · Laundry** (LND-01–08, LND-10–15, OPS-02): `wardrobe/laundry/*` (part, flows, review,
  writer, holds, loads, providers, blind, history, store, texts, tools, jobs), `api/laundry.py`,
  `tests/test_r13_b_*.py`, `tests/r13_fakes_b.py`, `evals/r13/laundry.py`, `INTEGRATION-B.md`. Your
  `review_writer` service (a `ReviewWriter`) is bound into A's store by the wiring: every
  `ReviewNeeded` gets its entry in A's commit.
- **C · Styling** (STY-01–17, LND-16, OPS-04): `wardrobe/styling/*` (part, rules.json, rules,
  engine, plans, reserve, refresh, calendar, outlook, wear, prefs, texts, tools, jobs),
  `api/outfits.py`, `tests/test_r13_c_*.py`, `tests/r13_fakes_c.py`, `evals/r13/styling.py`,
  `INTEGRATION-C.md`. No R11 file (D14): R11's weather reaches you through `ctx.outside()`, and
  your weather lives in `wardrobe_outlook`. Your `refresh` service (a `ChangeObserver`) is the first
  observer A's store tells.
- **D · Phone and panel** (OPS-01, the UI of every part, the Privacy rows, the No-AI sentences):
  `wardrobe/phone/*` (part, privacy over every part's `WardrobeData`), `offline/phrases_r13.py`
  (your `phrases` service; the wiring installs it FIRST, ahead of R14's `things`),
  `console-helpers-wardrobe.js`, `console-wardrobe-pieces.js`, `console-wardrobe-scan.js` (the
  second named pixel panel), `console-wardrobe.css` (≤ 200 lines) — I0's stubs, yours to replace —,
  the Part B section of `console-vision.js` (the four tasks and the shared ORT settings, before
  `sealRegistry()`; the core's hash unchanged), `tests/test_r7_b_console.py` and
  `tests/test_r7_b_dom.py` (the nine-task pins and `BASE13`, with a line in INTEGRATION-D),
  `static/vendor/vision/r13-1/**`, `scripts/wardrobe_assets.py` and `buildbook/gen/libs.py` from
  now on (I0 pinned the three files, the manifest, the licences and the book's three licence rows:
  you add the face and person self-check references, and the fp32 fallback only if `embed` fails
  its self-check on his phone), `tests/test_r13_d_*.py`, `tests/browser/test_r13_d_*.py`,
  `tests/fixtures/r13/**`, `evals/r13/phone.py`, `INTEGRATION-D.md`. `security-reviewer` required
  (the door, the scan module, the redaction views).

Every part: its own `tests/test_r13_<a|b|c|d>_*.py` and `tests/r13_fakes_<a|b|c|d>.py` (UNIQUE
names, so the four branches merge without a clash). You update the EXISTING tests of the files you
own and nobody else's.

## 4. The seams you use

- **The contract** (`wardrobe/ports.py`): `WardrobePart` (tools only of your `TOOL_OWNER` names,
  `clock_jobs` only C's `outfit_clock`, `daily_jobs` A's `wardrobe_sweep` and B's `laundry_daily`,
  `privacy`, `data`, `observers`, `services` only of your `SERVICE_OWNER` names, `ready`); a part
  that breaks it is left out ("setup failed") and the others run. `WardrobeContext`: `s`, `docs`,
  `keyring`, `audit`, **`now()` (UTC, the only clock)**, **`await zone(uid)`** (his zone), a late
  `state(name)`, `notifier()`, `reads()` (`BackgroundReads`: "Allow" only, one kind-only audit
  line), `outside()` (R11's `OutsideStore`, late), `store()` (A's store, late).
- **The ledger** (D4, H4): `await store.transact(uid, fn)` with `fn(view, tx) -> Commit(events,
  extra, records)`. `fn` reads through `tx` first and NEVER writes: it returns its events and its
  own writes (`extra`, storage ops); `records` are A's only. The store settles each event's time
  (a device's `at + (now − sent)`, refused if ahead or over 24 hours; a stated time at most 30 days
  back, never ahead; a stated day without a time is 12:00 his local time, the caller's to make) and
  `recorded` (arrival breaks a tie), appends, re-folds, asks B's writer for each `ReviewNeeded`'s
  entry, and writes everything in ONE commit (a write that fails rolls it all back); then each
  observer hears each changed piece once (`PieceChange`, with the wear's plan). A `Refused` is plain
  words, nothing written. `Committed` carries the stored events, each one's `Mark`, the entries
  asked for, the changed pieces, the fresh view and `already` ("already done"). `correct(uid,
  piece, event_id)` voids an event. `history(uid, piece)` gives each event with its mark. B and C
  build on `tests/r13_fakes_store.py`'s store, which passes the same conformance test as A's.
- **The states** (`wardrobe/states.py`, D3): the 10 states, `eligible` (Ready only; In use only for
  a later plan that declares the hand-off, C's engine), `allowed`, `target_of`, `wearable_pair`,
  `wearable_set`, `STATED_CHOICES` (`wear_done` lands in In laundry or Ready by the rewear rule).
- **The records** (`wardrobe/model.py`, D2): frozen, short keys (`to_json()`), ids and their
  patterns, `label_code_of` (only `jw1:` + 8 characters, and then only his own labels), the fixed
  lists (8 categories and their types, 18 colours and multicolour, patterns, features, occasions,
  weather, fabrics, care words, `PRIVATE_BY_DEFAULT`). A label field read from a photo is a
  `Verified` value; an unverified one never reaches the model.
- **The views** (`wardrobe/redact.py`, D10): `model_view`, `alert_words`, `card_words` (a card's
  words come from `Tool.preview` through it), `BIN_TITLE`, `log_view`. A private piece is "a
  private basic" everywhere but his own panel.
- **The HTTP contract** (`wardrobe/http.py`, H5): every route's request and reply models and
  `ROUTES`; your route tests assert them exactly; D draws exactly them. `tests/r13_fake_server.py`
  answers every row from the fakes for D's browser tests until I1.
- **The kinds** (D19): C raises `outfit_ready` and `outfit_changed`, B `laundry_overdue` and
  `wardrobe_review` (`KIND_OWNER`), through the notifier, with fixed templates (never his label, a
  title or a private piece); the text says "in Helpers, Wardrobe". Once-only claims in
  `wardrobe_told/{uid}_{key}`, each key starting with your part's name (`TOLD_KEY_PREFIX`).
- **The pixels** (D9, H6): only the Camera panel and Camera → Wardrobe (`console-wardrobe-scan.js`,
  mounted through `window.JarvisCameraModes.register('wardrobe', {mount(host, P), stop()})`) may
  take pixels; the scan module has the camera panel's rules (no `fetch`, XHR, `sendBeacon`,
  WebSocket, `localStorage`, `sessionStorage`, `indexedDB`; `JarvisConsole.api` only to
  `/v1/wardrobe…` and `/v1/laundry…`, never with picture bytes; picture bytes only through
  `door.wardrobe(blob, {piece, view})` and `door.tag(blob, {piece})`; `textContent` only; ASCII).
  `parse_result(raw, wardrobe=True)` checks the four wardrobe tasks' results; they are never kept.
- **Tools** (plan "Tools", D10, D16, D18): every call through the gateway; write tools take piece
  ids (only `laundry_move` and `wear_log` also a `query`); merge and archive are `ask_when` always
  and already in `NO_BULK_TOOLS`; remove is undo-able (`wardrobe_item`, A's `bin` service: the
  wiring registers it); untrusted by default, `may_vouch` per result only when every string is his
  typed label or a fixed-list word; at most 20 pieces a result. The skill register already files
  your tools (`planned` until I1) and the Telegram personal switch already covers them.

## 5. House rules that apply to every part

- **Free first.** ₹0 a month; no new paid service, secret or Scheduler job; the only model call is
  A's optional tagging, admitted first, recorded after, shown in ₹. Nothing orders, pays, calls or
  sends a message.
- **Private by default.** Ids and counts only in logs, the audit and Activity; the bin's fixed
  title; a calendar title is never stored, sent or logged; a private piece never has a photo or a
  fingerprint.
- **Outside content is untrusted data** (calendar titles, label text read off a photo, a QR code).
- **The console's look must not change**: the two new sub-tabs are built only from the existing
  builders and classes; `console-wardrobe.css` only places things (every colour, font, radius or
  shadow a `var(--…)`; a test refuses a literal); the existing tabs' screenshots stay R14's.
- **Test first** (skill `tdd-workflow`), 80 % coverage for your package; then the reviews your row
  names, in a fresh context.
- **Clocks: no date bombs** (the R14 hotfix-2 lesson). Every test takes a FIXED clock
  (`r13_fakes.FixedClock`, `ist(...)`); a sentence with a day in it is asserted WHOLE from that
  clock; nothing under `wardrobe/` or in `offline/phrases_r13.py` calls `datetime.now(`,
  `date.today(`, `time.time(` or `utcnow` (a static test fails it): use `ctx.now()`. Browser tests
  pin the page clock (`page.clock`). Test "tomorrow" at 23:30 and 00:30 IST.
- **Imports**: CI runs plain `pytest` from the repository root, which is NOT on `sys.path`: never
  `from tests.x import`; import fakes bare (`from r13_fakes import …`,
  `tests/test_test_imports.py` guards it). Plain `python` needs `PYTHONPATH=$PWD/src`.
- Functions ≤ 50 lines, modules ≤ 400, files ≤ 800.

## 6. Test commands (2 CPUs, about 7 GB; another agent shares the machine)

Run your part's tests and the seam tests; NEVER the whole suite (I1 runs it). Anything heavier than
a few files goes behind the shared lock, which waits if another agent's heavy run is going:

```
PYTHONPATH=$PWD/src python -m pytest -q -p no:cacheprovider tests/test_r13_<x>_*.py <the existing tests of your files>
PYTHONPATH=$PWD/src flock /tmp/heavy.lock python -m pytest -q -p no:cacheprovider \
    tests/test_r13_seams.py tests/test_r13_wiring.py tests/test_r13_fold_conformance.py tests/test_telegram_tool_guard.py
ruff check <your files> && ruff format --check <your files>
mypy src                                               # the 1 pre-existing error only (memory/redis_store.py)
PYTHONPATH=$PWD/src python evals/r13/run.py --mock --part <yours>   # passes; your control fails it
PYTHONPATH=$PWD/src python scripts/arch_coverage.py && python scripts/check_doc_versions.py
```

`python` is the workspace's Python 3.11 environment (the Workshop names it); set `BUILT = True` in
your eval part only when its control really fails it. Browser tests (D): the environment with
Playwright, one file at a time, behind the lock.

## 7. Size guards (pinned by `tests/test_r13_seams.py`)

`api/app.py` ≤ 735 (732 now); `tools/gateway.py` 760, not edited; `core/brain.py` ≤ 741, not edited;
`console.html` 782, byte-identical; every `console*.js` ≤ 800 (`console-camera-panel.js` ≤ 483,
`console-r7-send.js` ≤ 130, `console-helpers.js` ≤ 238, your new console files ≤ 600 each); new CSS
≤ 300 in all (`console-wardrobe.css` ≤ 200); `config.py` < 800; every module under
`src/jarvis/wardrobe/` ≤ 400 lines.

## 8. Done means

Your deliverables work on fakes end to end and each acceptance test of your use cases is a named
test; your eval part is BUILT with a control that fails it; everything works, or says plainly why
not, with the AI off and with nothing set up; the commands above are green; your
`docs/plans/r13-integration/INTEGRATION-<A|B|C|D>.md` (versioned like this file, with its change
log; it must pass `scripts/check_doc_versions.py`) is written and pushed: what you built, the
checks with their numbers, every deviation from the plan with its reason, "Needs I1" with exact
diffs, and honestly what you could not verify here.

## Change log

| Version | Date | Release | What changed | By |
|---|---|---|---|---|
| v13.0.1 | 15 Nov 2026, 19:05 IST | R13 | First edition, written at I0: branches and the hook, the files no part edits, each part's files, the seams (the contract, the ledger's `transact` and its conformance test, the states, the records, the views, the HTTP contract and its fake server, the kinds, the two pixel panels, the tools), the house rules (fixed clocks, bare fakes imports, the look unchanged), the test commands behind the shared lock, the size guards, the INTEGRATION file | 🛠 Mark XXI |
