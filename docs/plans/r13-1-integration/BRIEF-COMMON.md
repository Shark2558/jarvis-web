Version v13.1.2 · 17 Nov 2026, 17:55 IST · Release R13.1 · Status: Current · Owner: 🛠 Mark XXIII

# R13.1 — the common builder brief (Parts A–D)

Read this, then your part's own brief (`BRIEF-A.md` … `BRIEF-D.md`, in this folder), then the plan
`docs/plans/r13-1-try-on.md` (v13.1.3, Status Ready: the summary, the 15 rows and their named tests,
D0–D22, the data model, the HTTP contract, your part's row in "Part split", the suites and their
controls, the size guards), `docs/plans/r13-1-integration/I0-NOTES.md` (what I0 built, the stale lines
it found, what it left for I1), `PLAN-REVIEW-1.md` (why the plan says what it says), then
`CLAUDE.md`, `.claude/rules/ecc/common/*.md`, `.claude/rules/ecc/python/*.md` and
`.claude/agents/tdd-guide.md`. You build ONE part, in parallel with the others, on your own branch
from `r13-1-i0`. Everything you may touch is in your part's brief; everything else is someone
else's. When in doubt, don't edit: write it in your `INTEGRATION-<PART>.md` for I1.

**The owner's answers** (17 Nov 2026, ≈ 14:25 IST; in the plan v13.1.3): the model is **Gemini 3.1
Flash Image, processed in the United States** (question 12, the default, confirmed), and a "See it on
me" picture is kept **30 days** unless he presses Keep (question 3: `tryon_keep_days` 30,
`model.PICTURE_KEEP_DAYS`). Every other owner question keeps its safe default.

**The owner's scope** (17 Nov 2026, ≈ 15:33–15:45 IST; in the plan v13.1.3 as D21 and D22), in his
words: "the see it on me is for purchasing new garments, But I need the 3D model to be created and
within Jarvis so that whenever I ask what to wear, jarvis should open up the card, decide and show me
on the 3D model". So: **row 388** (new, R13.1, free): when he asks what to wear (chat or voice, laptop
or phone), JARVIS decides by R13's rules and the try-on card opens by itself under the answer, the
figure dressed in that look (I0 built the server half and the hooks; D builds the card, A the look by
ids, B the figure); and **"See it on me"** (AVT-12) is for a garment he is thinking of BUYING: he gives
its photo (uploaded or shared in; JARVIS never fetches an address), JARVIS pairs it with up to two of
his own pieces, and the garment is never added to his wardrobe (C builds it, D its console). A
garment's photo is untrusted content: its bytes only, no text read from it.

**Agents:** Part B (the 3D figure) is built by ONE builder on **Fable 5.2** (the owner's rule of 15 Nov
2026): its brief is self-contained. Every other part, review and fix is on Opus.

## 1. The loop

plan → test first → implement → review (fresh context) → verify → remember → improve.

1. **Plan** your part in your INTEGRATION file's first section before code (what you build, in
   which order, which tests prove it).
2. **Test first** (skill `tdd-workflow`, `.claude/agents/tdd-guide.md`): write the failing test,
   RUN it and see it fail for the reason you expect, write the least code that passes, refactor.
   Each of your rows' named tests (the plan's first table) is written before its code. 80 %
   coverage for your package at least.
3. **Review** in a fresh context: `code-reviewer` and `python-reviewer` (Python parts), and
   `security-reviewer` where your brief says (A, C and D: yes). Fix CRITICAL and HIGH.
4. **Verify**: the commands of section 6, every one green, numbers written down.
5. **Remember**: your INTEGRATION file says what you built, the checks with their numbers, every
   deviation and why, "Needs I1" with exact diffs, and honestly what you could not verify.

## 2. Your branch, your commits

- Worktrees and branches `r13-1-a` (A · Try-on data), `r13-1-b` (B · the 3D figure), `r13-1-c`
  (C · See it on me), `r13-1-d` (D · Console and phone), each from `origin/r13-1-i0`, e.g.
  `git worktree add .claude/worktrees/r13-1-a -b r13-1-a origin/r13-1-i0`.
- **Push after every commit**: `git -c push.negotiate=true push -u origin r13-1-a` the first time,
  then `git -c push.negotiate=true push`. Never rebase, never force-push, never push to `main`,
  never `rm -rf` outside `/tmp` or `.claude/worktrees/`, **never `git stash`** (a background run
  may be using the tree), never edit lint, format, type-check or coverage-floor files to make an
  error go away. Never touch another part's branch or another agent's worktree.
- **The hook.** `.claude/settings.json` runs `.claude/hooks/guard.py` before every Bash, Edit,
  Write and MultiEdit call (GateGuard). **A blocked action means stop and report it in your
  INTEGRATION file and to the Workshop; never work around it** (no other spelling of the same
  command, no editing the hook).
- Conventional commit messages in the repository's style (`feat(r13.1): …`, `fix(r13.1): …`,
  `test(r13.1): …`; a body that says what and why), each ending with exactly these four trailers:

  ```
  Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
  Claude-Session: <the session link the Workshop gives you>
  JARVIS-Version: v13.1.0
  JARVIS-Mark: XXIII
  ```

  (Part B on Fable 5.2 uses the Co-Authored-By line the Workshop gives it.)
- The repository is PUBLIC: no personal data (names, e-mail addresses, phone numbers, addresses,
  his real wardrobe, measurements or photos), no keys, no project ids, no chat links (the trailer is
  the only one), no local paths, in code, tests, fixtures or docs. Fixtures use made-up pieces
  (`tests/r131_fakes.py`), made-up measurements, `example.com` and pictures you draw.

## 3. The rule: self-contained modules, never a wiring or shared file

I0 built every join. A Python part plugs in through ONE function, `build(ctx: WardrobeContext) ->
WardrobePart` (`jarvis.wardrobe.ports`), in its `part.py` (`wardrobe/tryon/part.py` A,
`wardrobe/seeme/part.py` C), its own route file (`api/tryon.py` A, `api/seeme.py` C: I0's empty
stub routers, yours to fill) and its own modules. B and D replace I0's console stubs. Each builder
delivers self-contained modules plus `docs/plans/r13-1-integration/INTEGRATION-<X>.md`. You never
edit:

- `src/jarvis/api/app.py` (732 lines, not edited), `api/r13_wiring.py`, `api/tryon_wiring.py`,
  `api/tryon_assets.py`, `api/r13_status.py`, `api/console.py`, `api/wardrobe.py`,
  `api/personal.py`, `api/tick_wiring.py`, `tools/setup.py`
- `src/jarvis/tools/gateway.py` (760, not edited), `core/brain.py` (713, not edited),
  `console.html` (782 lines, byte-identical: pinned by its SHA-256), `console-helpers.js` (238,
  not edited)
- the contract: `wardrobe/ports.py`, `wardrobe/tryon/{model,http,http_figure,http_seeme,ports,
  kept}.py`, `llm/tryon.py`, `billing/spend.py`, `billing/service.py`, `keyring.py`,
  `config.py`, R13's `wardrobe/{model,states,redact,http*,kept}.py` and every R13 part's package
  (`wardrobe/catalog`, `laundry`, `styling`, `phone`; the R13 fix in `styling/actions.py` is I0's)
- the console frames: `console-helpers-wardrobe.js` (I0's hook), `console-r7-send.js` (the ONE
  picture door: `person`, `picture`, `myPhoto` are I0's), `console-r111-files.js` (`shrink`),
  `console-privacy.js` (`JarvisPrivacy.remove`), `console-r7.js` (the loader)
- `tests/test_r131_seams.py`, `tests/test_r131_wiring.py`, `tests/test_r131_port.py`,
  `tests/test_r131_lock_fix.py`, `tests/test_r131_panel_tool.py`, `tests/test_r131_spend.py`,
  `tests/test_r131_fakes.py`, `tests/r131_fakes.py`, `tests/r131_fake_tryon.py`,
  `tests/r131_fake_server.py`, `tests/fixtures/r13_1/engine_contract.mjs`,
  `tests/fixtures/r13_1/stage.mjs`, `evals/r13_1/run.py`, `evals/r13_1/contract.py`,
  `evals/run_all_mock.py`, every earlier release's seam test (`tests/test_r13_seams.py` included),
  `docs/architecture/*`, `scripts/arch_coverage.json`, `buildbook/gen/*`, `deploy/*`,
  `.claude/**`, `pyproject.toml`, `.github/workflows/*`, `CLAUDE.md`

If you need a change there, stop and write it under "Needs I1" in your INTEGRATION file with the
exact diff you propose (the other parts build against the contract). A pin in an earlier release's
test that your part legitimately moves is the one exception: say which, and why, in your
INTEGRATION file (C: the eight tick-job pins, section 4).

## 4. The seams you use (what I0 built; details in I0-NOTES.md)

- **The parts' contract** (`wardrobe/ports.py`): `PARTS` = R13's four + `tryon` (A) + `seeme` (C);
  `TOOL_FAMILIES` of both `()` (no new model-callable tool); `ROUTE_PREFIX` `/v1/tryon`,
  `/v1/seeme`; `COLLECTIONS` `tryon` (A) and `tryon_person`, `tryon_consent`, `tryon_picture`,
  `tryon_spend`, `tryon_garment` (C; the last is D22's new-garment photo); `JOB_OWNER["seeme_daily"] = "seeme"` (daily, the morning tick);
  `SERVICE_OWNER["tryon_looks"] = "tryon"`, `["seeme"] = "seeme"`; `PRIVACY_OWNER` (A:
  `tryon_figure`, `tryon_all`, `tryon_device`; C: `tryon_photo`, `tryon_pictures`, `tryon_spend`);
  `NO_DATA_PARTS`: **your Privacy rows ride `WardrobePart.privacy`, never `data`** (the wiring
  refuses a `tryon` or `seeme` part with `data`, M4); `PhotoVault.get(uid, photo)` (R13's
  catalog opens a crop); `WardrobeContext.tryon()` (C's provider, built lazily; None while
  pictures are off). A part that breaks the contract is left out ("setup failed") and the others
  run; a part that offers no Privacy rows gets I0's stand-ins (`wardrobe/tryon/kept.py`).
- **R13.1's own types** (`wardrobe/tryon/model.py`): measurements, ranges, the sample, `Body`,
  `estimated(height)`, `range_words`; the template table (`TEMPLATE_OF`, `VARIANTS`,
  `TEMPLATE_SLOT`, `GARMENTS`, `useful_views`), the palette (`PALETTE`, `rgb_of`), the words
  (`READY`, `DRAFT_WORDS`, `reserved_words`, `COVERED`, `GENERATED`, `CREDENTIALS`, `YES`), ids
  (`tp_` + 12 hex, `tq_` + 16 hex, `tc_` + 8 hex, `tg_` + 12 hex a new garment), D22's
  `NEW_TYPES`, `new_garment_words`, `GARMENT_MAX` 20 and `PAIR_MAX` 2, the collections, the AAD of every sealed
  document, the limits. **The one source**: never keep a copy.
- **The HTTP contract** (`wardrobe/tryon/http.py`, the models in `http_figure.py` and
  `http_seeme.py`): 27 routes (D22 added the garments' four and `pair`), `ROUTES` = (method, path,
  part, request, reply, errors, console only), `QUERIES` (the garment upload's `GarmentIn`);
  `PictureIn` = `{garment, pieces (0–2), confirm_cost, inr_shown, request_id}`, `PictureView.garment`;
  A's look also takes `?pieces=slot:wi_…,…` (row 388's card); every refusal is `Refusal` `{"error": <code>, "detail": <plain words>}` (the console
  branches on `err.code`); your route tests assert the models exactly; D draws exactly them;
  `tests/r131_fake_server.py` answers every row from the fakes until I1.
- **The seams between A and C** (`wardrobe/tryon/ports.py`): `SeeMeErase.erase(uid)` (C's pictures,
  photo and YES), `TryonLooks.look(uid, plan)` (A's look, read fresh), `service_of`,
  `photo_vault`, `seeme_service`, `looks_service`: a service read LATE (at call time, never at
  build time: A is built before C), from its one owner.
- **The provider port** (`llm/tryon.py`): `TryOnProvider.make(ask) -> TryOnResult`, `describe()`,
  `estimate(n)`; `Garment`, `TryOnAsk`, `TryOnUsage`; `TryOnNotBilled` / `TryOnMaybeBilled`;
  `TRYON_PRICES`, `price_of`, `typical_usd`, `worst_usd`, `cost_usd`; `build_tryon` imports
  `jarvis.llm.tryon_gemini` (C's) and calls its `build(s, tokens=, project=)`.
  `tests/r131_fake_tryon.py`'s `ScriptedTryOn(max_garments=1)` chains inside itself.
- **Money** (`billing/spend.py`): `with_tax(inr, pct)` to the paise; `ensure_spend_allowed(billing,
  uid, inr)` (his overall limit, fail closed); the usage label `tryon` ("Try-on").
- **The R13 fix** (D20, I0's): `outfit_plan` `lock` / `reserve` refuse a piece that isn't ready
  ("The charcoal blazer is in the laundry: it can't be locked into this plan."); `lock` with
  `pieces` (one a slot) locks every slot in ONE change, all or nothing; `api.wardrobe.run_panel_tool
  (request, uid, tool, arguments, session_id) -> PanelRun` and `panel_reply(run)`: the panel's ONE
  gateway call (at most one card a press). `outfit_suggest` carries `see_it` while Try-on is on
  ("In the app this look opens on your 3D figure by itself, free. To see a garment you are thinking
  of buying on you, use See it on me in Helpers, Wardrobe; its price is shown before each
  picture.").
- **Row 388's card** (D21, I0's server half): `outfit_suggest` adds ONE `TryOnCard` (kind `tryon`,
  `tools/reply_cards.py`; `{day, plan, code, slots: [{slot, pieces, private}]}`, piece ids only, a
  private slot covered; one a reply; never on Telegram; never in the AI's result) through
  `wardrobe/styling/tryon_card.py` (`show`, `card_of`, and `missing`: row 388's check, which the
  contract eval and its control use). In the console, `console-media.js`'s `cards()` calls
  `window.JarvisTryOnCard.cards(row, list)` (`console-tryon-card.js`, D's, loaded at start by
  `console-r7.js`), which calls `console-tryon.js`'s `inline(el, card)`. The share tray's "See it on
  me (a garment to buy)" calls `window.JarvisTryOnCard.garment(file)` → `console-tryon.js`'s
  `garment(file)` (that press sends nothing).
- **The console** (D's and B's files are I0's stubs): Helpers → Wardrobe mounts `console-tryon.js`
  ONCE (`mount(host, ctx)`), each plan row has "Show in 3D" only (it fires `jarvis:tryon-open`
  `{plan}`; See it on me is not a plan's button any more, D22); a fresh wardrobe load fires
  `jarvis:wardrobe-fresh`. The engine contract is `tests/fixtures/r13_1/engine_contract.mjs`
  (`window.JarvisTryOn3D`; I0's stub's `mount()` throws "The 3D view is not built yet.").
  Loads that tests pin (keep them when you replace a stub): `console-tryon.js` loads
  `'./console-tryon-list.js'`, `'./console-tryon-me.js'`, `'./console-tryon-3d.js'`;
  `console-tryon-me.js` loads `'./console-tryon-photo.js'`; `console-tryon-3d.js` loads
  `'./console-tryon-glb.js'` and `'./console-tryon-cloth.js'`; `console-r7.js` loads
  `/static/console-tryon.css`.
- **The pixel and drawing rules** (`tests/test_r13_seams.py`, `tests/test_r131_seams.py`): THREE
  panels may see pixels: Camera, Camera → Wardrobe and `console-tryon-photo.js` (the scan module's
  rules: no `fetch`, XHR, `sendBeacon`, WebSocket, storage or `innerHTML`; `JarvisConsole.api`
  only to `/v1/seeme…`; picture bytes only through `door.person`; ASCII). The drawing modules
  `console-tryon-3d.js` and `console-tryon-cloth.js` draw only on their own canvases (never the
  vision engine, the camera or the door's senders). Every other module (D's three) uses no pixel
  API at all: the share caption is drawn by B's `snapshot({caption})` (M9). The door is the only
  caller of `/v1/seeme/photo`, `/v1/seeme/pictures` and `/v1/seeme/garments` (its `person()`,
  `garment()`, `picture()`, `garmentPhoto()`, `myPhoto()`).
- **The mannequin's files** are served by `GET /static/vendor/mannequin/{release}/{name}` (I0):
  a file only when its release's `MANIFEST.json` lists it with a matching SHA-256 and a data type
  (never JavaScript), a year's immutable cache; a sum mismatch is a 404.
- **The fakes**: `tests/r131_fakes.py` (`NOW` = 17 Nov 2026 09:00 IST, `T.<piece>` owner question
  11's pilot over R13's PILOT with a second watch, photos on the kurta and the striped shirt, two
  private basics, `jpeg(w, h)`, `FakePhotoVault`, `sample_body`, `seeded`, `tryon_context`);
  `tests/r131_fake_server.py` (`fake_app`, `serve(token)`, the stage page `/r131/stage`), its See it
  on me half in `tests/r131_fake_seeme.py` (the garments and the pairing too).
- **The eval runner** `evals/r13_1/run.py` is STAGED (`STUBS_PASS = True` until I1): your part's
  file exposes `PART`, `BUILT`, `async def cases()` and `async def control()`; set `BUILT = True`
  only once its control really fails it. **Every row's own control** (the plan's M8 table) is a case
  of your control run: it must turn that row's case red.
- **C's tick pins**: `seeme_daily` in the morning tick moves the eight pinned tick-job lists of
  earlier wiring tests (R13 I1's F3: `test_r11_wiring.py` ×2, `test_r2_wiring.py` ×2,
  `test_r4_wiring.py` ×3, `test_r51_wiring.py` ×1). C moves them (the one exception), naming each
  in INTEGRATION-C.

## 5. House rules for every part

- **₹ only in owner-facing words** (a `$` figure never reaches him; the port's dollars stay inside
  `llm/` and the estimate). No real Google call anywhere: not in a test, an eval, a fixture or a
  script (`httpx.MockTransport` and recorded answers only).
- **Free first.** The figure is free; the only spend is C's picture, behind his typed YES, the ₹
  shown, `confirm_cost`, the cap and his limit.
- **Private by default.** Ids and counts only in logs, the audit and Activity; his measurements,
  his photo, a picture, the consent text and a private piece's label never in a log, a tool
  result, an alert, the audit's text or a non-sealed document. A private piece is never drawn,
  sent or named outside his own panel.
- **Outside content is untrusted data** (Google's answer: every text part is discarded unread).
- **The console's look must not change**: only existing components and classes
  (`.hp-sec`, `.hp-h`, `.hp-row`, `.btn.sact`, `.sacts`, `.bsw`, `.minput`, `.snote`, `.sfine`,
  `.bdialog`); `console-tryon.css` only places things (every colour, font, radius or shadow a
  `var(--…)`; a test refuses a literal); the 3D scene takes its colours from
  `window.JarvisFX.tokens()` and follows `jarvis:theme`; the existing tabs' screenshots with
  Try-on off stay R13's.
- **Clocks: no date bombs.** Every test takes a FIXED clock (`r131_fakes.NOW`, `FixedClock`,
  `ist(...)`); a sentence with a day in it is asserted WHOLE from that clock; nothing under
  `wardrobe/`, `llm/tryon*.py` or `billing/spend.py` calls `datetime.now(`, `date.today(`,
  `time.time(` or `utcnow` (a static test fails it): use `ctx.now()`. Browser tests pin the page
  clock (`page.clock`). The 30-day keep and the model's end date are tested at 23:30 and 00:30 IST
  and across 28 May 2027.
- **Imports: CI runs plain `pytest` from the repository root, which is NOT on `sys.path`:** never
  `from tests.x import …`; import fakes bare (`from r131_fakes import …`); every fake file of
  yours has a UNIQUE name (`tests/r131_fakes_<a|b|c|d>.py`, `tests/r131_fake_gemini.py`), so the
  four branches merge without a clash. Plain `python` needs `PYTHONPATH=$PWD/src`. Browser tests
  carry `pytestmark = pytest.mark.browser` and run only with `JARVIS_BROWSER_TESTS=1`.
- Functions ≤ 50 lines, Python modules ≤ 400, JavaScript files ≤ 800 (your brief's own limits are
  lower); `ruff check` and `ruff format --check` clean; `mypy src` adds no error.

## 6. Test commands (2 CPUs, about 7 GB; other agents share the machine)

Run your part's tests and the seam tests; NEVER the whole suite (I1 runs it). **Anything heavier
than a few files goes behind the shared lock**, which waits while another agent's heavy run goes:

```
PYTHONPATH=$PWD/src /tmp/venv-b/bin/python -m pytest -q -p no:cacheprovider tests/test_r131_<x>_*.py
flock /tmp/jarvis-heavy.lock /tmp/venv-b/bin/python -m pytest -q -p no:cacheprovider \
    tests/test_r131_seams.py tests/test_r131_wiring.py tests/test_r13_seams.py tests/test_r13_wiring.py
/tmp/venv-12/bin/ruff check <your files> && /tmp/venv-12/bin/ruff format --check <your files>
flock /tmp/jarvis-heavy.lock /tmp/venv-12/bin/mypy src       # the one baseline error only
PYTHONPATH=$PWD/src /tmp/venv-b/bin/python evals/r13_1/run.py --mock --part <yours>  # passes; control fails it
PYTHONPATH=$PWD/src /tmp/venv-b/bin/python scripts/arch_coverage.py && python3 scripts/check_doc_versions.py
JARVIS_BROWSER_TESTS=1 flock /tmp/jarvis-heavy.lock /tmp/venv-c/bin/python -m pytest -q -m browser tests/browser/test_r131_<x>_*.py
```

`/tmp/venv-b` is Python 3.11, `/tmp/venv-12` 3.12, `/tmp/venv-c` 3.13 with Playwright and Chromium
(use `python -m pytest`; also numpy 2.5.3 and scipy 1.18.1, for Part B's build script). Node 22 is
on the PATH. Browser tests one file at a time, behind the lock.

## 7. Size guards (pinned by `tests/test_r131_seams.py`)

`api/app.py` 732 (not edited); `tools/gateway.py` 760; `core/brain.py` 713; `console.html` 782,
byte-identical; `config.py` ≤ 790; `console-helpers.js` 238; `console-helpers-wardrobe.js` ≤ 306;
`console-r7-send.js` ≤ 165; `console-r111-files.js` ≤ 335; `console-privacy.js` ≤ 268;
`console-tryon.js` ≤ 600, `console-tryon-list.js` ≤ 300, `console-tryon-me.js` ≤ 400,
`console-tryon-photo.js` ≤ 300, `console-tryon-3d.js` ≤ 600, `console-tryon-glb.js` ≤ 200,
`console-tryon-cloth.js` ≤ 300, `console-tryon-card.js` ≤ 150; `console-media.js` ≤ 415,
`console-r7.js` ≤ 95, `console-r7-share.js` ≤ 295, `tools/reply_cards.py` ≤ 400; every `console*.js` ≤ 800; `console-tryon*.css` ≤ 200 in all;
every module under `src/jarvis/wardrobe/` ≤ 400; `api/r13_wiring.py` ≤ 400; `api/console.py` ≤ 475;
`styling/actions.py` ≤ 400; new Python modules ≤ 400; `static/vendor/mannequin/m1/` ≤ 3.5 MB.

## 8. Done means

Your deliverables work on fakes end to end and each named test of your rows passes; your eval part
is BUILT with its controls failing it (every row's own control too); everything works, or says
plainly why not, with the AI off and with nothing set up; the commands above are green; your
`docs/plans/r13-1-integration/INTEGRATION-<A|B|C|D>.md` (versioned like this file, with its change
log) is written and pushed: what you built, the checks with their numbers, every deviation from the
plan with its reason, "Needs I1" with exact diffs, and honestly what you could not verify here.

## Change log

| Version | Date | Release | What changed | By |
|---|---|---|---|---|
| v13.1.1 | 17 Nov 2026, 15:45 IST | R13.1 | First edition, written at I0: the loop, branches, the hook and the four trailers, the files no part edits, the seams (the contract with two new parts, R13.1's types, the HTTP contract, the A–C seams, the provider port, money, the R13 fix and `run_panel_tool`, the console's hook and loads, the three pixel panels and two drawing modules, the mannequin route, the fakes and the fake server, the staged runner, C's tick pins), the house rules (₹ only, no real Google call, fixed clocks, bare and unique fakes, the look unchanged), the commands behind the shared lock, the size guards, done | 🛠 Mark XXIII |
| v13.1.2 | 17 Nov 2026, 17:55 IST | R13.1 | The owner's scope of 17 Nov 2026 (plan v13.1.3, D21 and D22): row 388's card and its hooks; See it on me for a garment he is thinking of buying (`tryon_garment`, 27 routes, the door's `garment()`); the plan rows keep Show in 3D only; the new `see_it` words; the fake server's See it on me half; the new size guards | 🛠 Mark XXIII |
