Version v7.0.1 · 13 Nov 2026, 16:05 IST · Release R7 · Status: Current · Owner: 🛠 Mark XVI

# R7 — the common builder brief (Parts A–E)

Read this, then the plan `docs/plans/r7-mobile.md` (v7.0.4: the decisions D0–D26, your part's row
in "Part split", its tests and evals), `docs/plans/r7-integration/I0-NOTES.md` (what I0 built and
what only CI or the owner's laptop can prove), `docs/plans/r7-integration/phone-contract.md` (the
phone's signed request, launch words, notification tags), then `CLAUDE.md` and
`.claude/rules/ecc/common/*.md`. You build ONE part, in parallel with the others, on your own branch
from `r7-i0`. Everything you may touch is in your part's row; everything else is someone else's.
When in doubt, don't edit: write it in your `INTEGRATION-<PART>.md` for I1.

## 1. Your branch, your commits

- Branches `r7-a` (A · the app on the web side), `r7-b` (B · camera and the vision engine), `r7-c`
  (C · phone link and security), `r7-d` (D · watch, sleep and SOS), `r7-e` (E · the Android app),
  each from `origin/r7-i0`. With four builders, A is merged into E (the plan's "Part split").
  Push after every commit. Never rebase, never force-push, never `rm -rf`, never edit lint, format
  or type-check configs to make an error go away. Never touch `main` or another part's branch.
- Conventional commit messages (`feat(r7): …`, `fix(r7): …`, `test(r7): …`), each ending with
  exactly the trailers the orchestrator gives you, including `JARVIS-Version: v7.0.0` and
  `JARVIS-Mark: XVI`.
- The repository is public: no personal data (names, e-mail addresses, phone numbers, coordinates
  of a real place he lives at, account numbers, real mail or calendar content), no keys, no
  keystore, no server address (the app's address is `jarvis.host` in the ignored
  `android/local.properties`; CI uses `jarvis.invalid`), no chat links other than the trailer, no
  local paths, in code, tests, fixtures or docs. Fixtures use made-up people, `example.com`
  addresses, obviously fake numbers and pictures you draw in the test.

## 2. The rule: never edit a wiring file

I0 built every join. A server part plugs in through **one function**, `build(ctx: MobileContext) ->
MobilePart` (`jarvis.mobile.ports`), in its module (`api/app_shell.py` for A, `vision/part.py` for
B, `phone/part.py` for C, `watch/part.py` for D), its **route files** and its **console modules**
(loaded by `console-r7.js`; Helpers → Watch by `console-helpers.js`). You never edit:

- `src/jarvis/api/app.py` (735 lines, pinned ≤ 735: it may not grow by a line), `api/r7_wiring.py`,
  `api/r11_wiring.py`, `api/r11_1_wiring.py`, `api/personal.py`, `api/console.py`, `tools/setup.py`
- `src/jarvis/tools/gateway.py` (760 lines, frozen), `console.html` (782 lines, pinned ≤ 782),
  `console.js` (761 lines; every console file ≤ 800), `console-dock.js`, `console-r7.js`,
  `console-r7-send.js` (I0's one picture door), `console-attach.js`, `console-helpers.js`
- `jarvis.mobile` (`ports.py`, `contract.py`), `jarvis.vision.results` and the port core of
  `console-vision.js` (contract files: B owns its folder, but a contract change needs a line in
  INTEGRATION-B.md because another part or a later release builds against it), `jarvis.sos.hook`
  (the hook's contract; D writes the code behind it in `jarvis.sos`)
- `telegram/service.py` (I0 added the one hook; D owns no line of it), `telegram/rules.py`
- the alert kinds, permission rows, key purposes, passkey purposes, settings, brief model and
  layer map: I0 added every one R7 needs (D25; see I0-NOTES.md for where each sits)
- `tests/test_r7_seams.py`, `tests/r7_fakes.py`, `tests/fixtures/r7/phone_vectors.json`,
  `evals/r7/run.py`, `evals/r7/contract.py`

## 3. What each part owns

Exactly the plan's "Part split" row for your letter. In short: **A** `api/app_shell.py` (the
manifest, the icons, the share target and its worker `app-share-sw.js`), `console-r7-links.js`,
`console-r7-share.js`/`.css`, `console-sw.js` (the Talk action, targets with their `?`, the hand-over
to an open window), `webpush/service.py` (`payload_for` targets only), `evals/r7/shell.py`;
**B** `src/jarvis/vision/` (not `results.py` without a line), `api/vision.py`, `console-camera.js`,
`console-vision-*.js` and the tasks in `console-vision.js`, `console-camera-panel.js`,
`console-camera.css`, `static/vendor/vision/**`, `scripts/vision_assets.py`, `evals/r7/vision.py`;
**C** `src/jarvis/phone/`, `api/phone.py` (and the door's and asset links' routes), one method in
`buildbook/lock.py`, `console-r7-phone.js`/`.css`, `console-r7-lock.js`, `evals/r7/phone.py`;
**D** `src/jarvis/watch/`, `src/jarvis/sos/` (not `hook.py`'s contract), `api/watch.py`,
`api/sos.py`, `telegram/client.py` (`send_location`), `console-r7-sos.js`/`.css`,
`console-helpers-watch.js`, `evals/r7/body.py`; **E** `android/**` (except the release bump of
`version.properties`), `.github/workflows/android.yml` from now on, `scripts/apk_check.py`,
`tests/test_r7_e_*.py`, `docs/plans/r7-integration/OWNER-STEPS.md`. Every part: its own
`tests/test_r7_<a|b|c|d|e>_*.py`, `tests/r7_fakes_<a|b|c|d>.py`, `tests/browser/test_r7_<a|b|c|d>_*.py`
and `docs/plans/r7-integration/INTEGRATION-<PART>.md` (INTEGRATION-A.md, INTEGRATION-B.md,
INTEGRATION-C.md, INTEGRATION-D.md, INTEGRATION-E.md).

## 4. The contract

- `MobilePart` has R11.1's part fields: `tools` (names inside your `TOOL_FAMILIES`), `clock_jobs`
  (the helpers' 5-minute clock: D's `watch_stale`), `daily_jobs` (the morning tick: the 400-day and
  90-day sweeps), `privacy` (`PrivacySource`s: every part registers its own Privacy rows; nobody
  edits the privacy files), `services` and `ready`. The wiring reads these services: `phrases`
  (No-AI routers), `brief` (a brief contributor; D's fills `BriefData.sleep`, whose shape is pinned:
  `{minutes, start, end, source: watch | phone | typed}`), `door` ({route: handler}; C owns `hello`
  and `inbox`, D owns `health` and `sos`), `app_lock` (C only) and `sos_hook` (D only). A part that
  breaks its contract is left out ("setup failed") and the others run.
- The door: C builds `/phone/link` and `/phone/v1/<route>` with every check of D6, then hands the
  verified request (`PhoneRequest`) to the handler from `r7_wiring.door_handlers(app)`. D's and C's
  handlers are tested against `tests/r7_fakes.py`'s `FakeDoor`; C's door against `sign_request` and
  the shared vectors; E's `core` against the same vectors byte for byte.
- One picture door: A's share tray and B's camera panel send through
  `window.JarvisMobile.parts.send` (`console-r7-send.js`: `canAsk`, `ask`, `attach`, `vault`,
  `sentToday`, `line`). Neither builds its own Ask, Vault, Attach or counter.
- Voice: B's `camera.off` and D's `sos.open` register through R5's `JarvisVoiceCommands.register`;
  their multi-word phrases are already speech hints (`voice/commands.py` `R7_PHRASES`). Nothing
  starts a turn or turns a camera on by voice.
- The app lock: C's check is an async `(scope) -> bool`; the slot answers 423 `device_locked`
  outside D21's never-locked list (`ports.never_locked`) and console.js already sends
  `device_locked` to `jarvis:device-locked` (C's cover) and `show_locked` to the show.

## 5. House rules that apply to every part

- **Ask nothing before sign-in.** A console module asks the server NOTHING until the console says
  it is signed in (`jarvis:ready`, or `JarvisConsole.ready()`); every part has its own
  `test_before_sign_in_the_block_asks_the_server_nothing` (a network spy on a signed-out page). The
  share tray keeps its `do=shared` items in the browser until sign-in.
- **Free first.** No new paid service, secret or Scheduler job. Any model call is by tier through
  `jarvis.llm`, admitted first and recorded after, shown in ₹, and replaced by plain code in No-AI
  mode, saying so.
- **Every action is a tool through the gateway**, except SOS, which is never a tool (D19). Writes
  ask first as the owner's rows say; R3 is never approvable on Telegram.
- **Outside content is untrusted data**: text read from a picture, a shared file's name, anything an
  SOS contact writes. Fence it, never obey it, never put it in alert text.
- **Private by default**: a camera frame never leaves the device; coordinates travel only in a POST
  body and are never stored, logged or audited; watch values are sealed and never logged; logs carry
  check names, kinds and counts only.
- **The look never changes** (D0): existing tokens and components, textContent only, 44 px targets,
  Night and Day at 1440×900 and 390×844, contrast ≥ 4.5:1; each stylesheet ≤ 150 lines that only
  places things; `tests/browser/test_ui_audit.py` keeps passing.
- Write the failing test first (skill `tdd-workflow`), 80 % coverage for your package; then the
  reviews the plan names for your part (`security-reviewer` on A, B, C, D and E; `code-reviewer` and
  `python-reviewer` on A–D; `silent-failure-hunter` on D).

## 6. Test commands (run before every push)

```
pytest -q -p no:cacheprovider tests/test_r7_*.py <the existing tests of your files>
pytest -q -p no:cacheprovider tests/test_r7_seams.py tests/test_r7_telegram_hook.py \
    tests/test_r11_1_seams.py tests/test_arch_coverage.py tests/test_telegram_tool_guard.py
ruff check src tests evals scripts && ruff format --check src tests evals scripts
mypy src                                                 # the pre-existing errors only
PYTHONPATH=$PWD/src python evals/r7/run.py --mock --part <yours>   # passes; your control fails it
PYTHONPATH=$PWD/src python scripts/arch_coverage.py && python scripts/check_doc_versions.py
JARVIS_BROWSER_TESTS=1 PYTHONPATH=$PWD/src python -m pytest -q tests/browser -m browser -k "r7 or ui_audit or dock_fit"
```

The machine has 2 CPUs and is shared: run your own tests and the guard tests above, one heavy run
at a time; I1 runs the whole suite. Set `BUILT = True` in your eval part only when its control
really fails it. Part E cannot compile here (Google's Maven, Gradle's distributions and Maven
Central are refused): its static checks run in the Python suite, and CI is the build.

## 7. Done means

Your deliverables work on fakes end to end and each has its eval case with a failing control;
everything works or says plainly why not in No-AI mode, signed out, with no linked phone, with no
Health Connect, with no contact and past the monthly limit; your screens pass the visual gate; the
commands above are green; your `INTEGRATION-<PART>.md` (versioned like this file, with a change log)
is written and pushed, and lists honestly what you could not verify live.

## Change log

| Version | Date | Release | What changed | By |
|---|---|---|---|---|
| v7.0.1 | 13 Nov 2026, 16:05 IST | R7 | First edition, written at I0: branches, the files no part edits, each part's files, the contract (`MobilePart`, the door's handlers, the one picture door, voice, the app lock), the house rules with "ask nothing before sign-in", the test commands | 🛠 Mark XVI |
