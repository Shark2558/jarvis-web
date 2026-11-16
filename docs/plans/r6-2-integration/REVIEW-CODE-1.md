Version v6.2.1 · 15 Nov 2026, 20:37 IST · Release R6.2 · Status: Current · Owner: 🛠 Mark XXI (fresh-context code review 1)

# R6.2 Part 1 "The Build Book: Ask by voice fixed" (v6.2.0): fresh-context code review 1

Scope: `git diff 9a8392b..d237b8c` on branch `r6-2` (29 files, +1,815/-111), worktree
`/home/claude/jarvis-web/.claude/worktrees/r6-2` (read only; clean at `d237b8c`). Read against the builder's
`docs/plans/r6-2-integration/INTEGRATION-A.md`, Phase A sections 4.2-4.5 (`origin/r6-2-plan`), the owner's
Phase B (`/tmp/mark21/book-prompt-full.txt` 206-229), `CLAUDE.md`, `.claude/rules/ecc/common` + `python`, and
the `code-reviewer` / `python-reviewer` role files. Python and JavaScript both reviewed.

**Verdict: APPROVE WITH FIXES.** There is one HIGH: a typed question sent while the microphone is listening
leaves the recording running with its status line cleared, and 15 s later the transcript overwrites what the
owner typed next. I reproduced it in Chromium against this branch's code. The fix is one line plus one test.
There are no CRITICAL or MEDIUM findings and 4 LOW. Everything else the brief asked for checks out (section 2).

## 1. Findings

### HIGH

**H1. A typed question while listening leaves the mic recording with no status, then overwrites the box.**
`src/jarvis/api/static/console-book-talk.js:88` (with `:56`, `:118-122`, `:143`, `:164`).

```js
S.busy = true; $('shQ').value = ''; row('user', text); leftWords(); micState();   // :88 ask()
```

- *Trigger:* tap the mic. It says "Listening…". The owner then types a question and presses Enter (or Ask)
  instead of tapping the mic again.
- *What happens:* `ask()` does not stop the recording. While the ask is in flight, `leftWords()` disables
  `#shMic` (`S.busy`, `:56`), so the mic can't be tapped to stop it. `micState()` (newly called here in R6.2)
  clears and hides `#shHear` (`:121`), so "Listening…" disappears while the microphone stays open. After the
  ask, `aria-pressed` is still `true` and nothing says it is listening. At the 15 s cap, `R.onFull(() =>
  sendRec())` (`:143`) posts the WAV to `/hear`. That spends one of the session's 30 spoken questions and STT
  minutes. `landed()` then writes the transcript over whatever is in the box (`:164`).
- *Reproduced* (headless Chromium, real fake-mic pipeline, a scratch test outside the repo, server on this
  branch's `src`):
  - right after the tap, `#shHear` = "Listening… tap the mic again to stop.";
  - during the ask: `#shHear` hidden and empty, `#shMic` disabled, `JarvisBookVoice.record.active()` = true;
  - after the ask: still hidden and empty, `aria-pressed="true"`, `active()` = true;
  - at the cap: 1 POST to `/v1/book/show/hear`. The draft "my next typed draft" was replaced by the
    transcript, and the line said "Done. Edit the question if you like…".
- *Why nothing catches it:* no guard links `ask()` to `S.recording`. `micState()` clears the line without
  checking for a live recording. No browser test types while listening.
- *Partly pre-existing:* on `main`, `ask()` also left the recording open and the cap also filled the box. But
  R6.2 is the release for this exact flow. Its new `micState()` call hides the only sign that the mic is
  open, and Phase B asks for "the typed box always usable" and a status line that shows Listening.
- *Fix* (a typed question wins; nothing recorded is sent; talk.js goes from 305 to 306 lines, under 400):

```js
async function ask() {
  const text = $('shQ').value.replace(/\s+/g, ' ').trim().slice(0, MAX_Q);
  if (!text || S.busy || S.left === 0) return;
  if (S.recording) stopRec(true); // R6.2: a typed question wins; the recording is dropped, nothing is sent
  S.busy = true; $('shQ').value = ''; row('user', text); leftWords(); micState();
```

  Test first, in `tests/browser/test_r62_book_mic.py`:
  `test_a_typed_question_while_listening_stops_the_microphone`. Tap, `wait_for_function(PRESSED true)`, fill
  and press Enter. Then assert that `aria-pressed` is `"false"`, `window.JarvisBookVoice.record.active()` is
  false, and the `/ask` went out. After a short `wait_for_timeout(500)`, assert
  `fake.to("POST", "/v1/book/show/hear") == []`, then `_clean(c)`. The test fails before the fix, because
  `active()` is still true.

### MEDIUM

None.

### LOW

**L1. A stale route table in the `book_show.py` docstring.** `src/jarvis/api/book_show.py:8-11` still lists
`409 guest_needs_google` for `POST /v1/book/open`, and does not list the new `403 google_needed`. That 409 is
gone, and `book_show_access.py`'s own docstring was updated. *Fix:* in that row, replace
`· 409 guest_needs_google` with `403 google_needed (token mode, R6.2 G11) /` ahead of `console_only`.

**L2. The new guest-lane module is missing from the lane-import guard.** `tests/test_book_boundaries.py:81-94`
(`test_the_lane_imports_nothing_that_reaches_the_owner`) leaves out `buildbook/hear.py`. Yet `hear.py`
processes a guest's spoken question and `BookService` imports it. Its imports pass today
(`jarvis.understand.rules`, `jarvis.voice.settings`, `jarvis.buildbook.*`, `jarvis.logging`), but nothing stops
a later edit from pulling in `jarvis.memory` or `jarvis.core.brain`. *Fix:* add `"hear"` to the parametrize
list. It passes as is.

**L3. Two tests wait a fixed time for audio frames.** `tests/browser/test_r62_book_mic.py:113`
(`_record`: `wait_for_timeout(600)`) and `:148` (`wait_for_timeout(700)`). Test 1 then asserts at least two
frames (`len(body) > 44 + 2 * 1280`, `:164`). On a loaded 2-CPU runner the audio thread can start late. The
new `record.frames()` gives an exact condition. *Fix:* replace both sleeps with
`c.page.wait_for_function("() => window.JarvisBookVoice.record.frames() >= 3")`. The negative waits ("nothing
sent", `:167`, `:324`) are fine as they are.

**L4. Future coupling: the integration notes list one test too few.** `INTEGRATION-A.md` §8 item 5 says that
once a top-level `docs/plans/r6-2-*.md` lands, `test_r14_seams` and `test_r7_seams` need the new path. But
`tests/test_book_gen_plans.py:212` and `:218` also pin the first plan and its label
(`read[0].path == "docs/plans/r14-hardening.md" and read[0].label == "R14"`, `lims[0].release == "R14"`). They
pass today because the label R6.2 has no top-level plan, and they break on the same day as the other two.
Part 2 will very likely add that plan. *Fix (doc only):* add `test_book_gen_plans::test_the_real_plans_parse`
to that sentence.

## 2. The checks asked for

### 2.1 Phase B behaviour and failure cases

Each case below is implemented and has a test that drives the real page. Line numbers are in
`console-book-talk.js`; tests are in `tests/browser/test_r62_book_mic.py` unless named otherwise.

| Phase B | Where | Test (real page) |
|---|---|---|
| One tap starts, a second stops; Listening, Processing, Done | `mic()` :134-147, `sendRec()` :169-183, `HEAR` :31-41 | `test_one_tap_listens…` (HOLD_HEAR holds Processing; a real RIFF WAV; no `/ask`) |
| Transcript to the box, never sent | `landed()` :161-168 | the same test, plus `heard/understood`, `charged` |
| Denied (Chrome, Windows, Android steps) | `refused()` :129-133 → `JarvisAudio.words('blocked')` | `[NotAllowedError-blocked]`, plus the console test of the same words |
| No mic / busy | `reason()` mapping (unchanged) | `[NotFoundError-no_mic]`, `[NotReadableError-busy]` |
| Unsupported | `open()` :65-67, disabled button with the reason | `test_an_unsupported_browser…` (no `AudioWorkletNode`) |
| Network / speech failure | `hearWords()` :156-160 (TypeError → calm line; else the server's `detail`; else "I didn't catch that") | 10 server answers, `…without_words…`, `dropped_connection` |
| Nothing heard | `landed()` :163 (the draft is kept) | `test_nothing_heard…keeps_what_was_typed` |
| 402 | `hear.words('budget_reached')` | `[402-budget_reached]`; server side in `test_r62_book_hear` (8 failures × 2 audiences) |
| "Mic off" and the way back | `micState()`, `micOn()` :118-128 (`isTrusted` and then `unlock('button')`) | a script `click()` and a synthetic `MouseEvent` are both refused; a real tap unlocks and never listens; a lock set while listening; no button once the questions run out |
| Typed box always usable | `S.busy = false; leftWords()` on every path except 401 (the session is gone) | `_typing_still_works` after every failure. **One gap: H1.** |

On swallowed errors: the original bug, `catch (_)`, is gone. `mic()` now catches `(e)` and routes `e.code`
(`:146`). Every code produces a sentence except `'closed'` (a cancel or the close won, which is intended).
Unknown codes get the shared `failed` words, which is the same as R5's `help(e && e.code)`
(`console-voice-mic.js:213`). On the server, the two `except Exception` blocks (`hear.BookWords._read`,
`book_show._owner_words`) log the error's type name and fall back to the fixed words. Nothing fails silently.

Not built, by design: decision 4 (stop at the free minutes) waits for the owner (INTEGRATION-A §8.1). Past the
free 54 minutes a guest's spoken questions are charged quietly until the 402; the owner sees "this one was
charged". That is a truthful wording of today's billing, not a code defect. I have not counted it as a finding.

### 2.2 Shared R5 code, not a fork

- `console-voice-capture.js` only adds the frozen `WORDS` table and `words(code)` (`:283-297`). `reason()`,
  `open()`, the lock and the error codes are byte-for-byte unchanged.
- `console-voice-mic.js` `HELP` is `Object.freeze(Object.assign({}, A.WORDS, {mic_off, cloud_down}))`. Its keys
  are a superset of the old ones (plus `silent`, which the console never raises). Only the `blocked` sentence
  changed, as Phase B asked, and it still ends "tap the mic again". Nothing writes to `HELP`, so freezing it is
  safe. `console-voice-wake.js` reads it as before.
- The Book never calls `getUserMedia` or builds a worklet. Only `micOn` unlocks the mic
  (`test_r62_book_mic_static`).

### 2.3 Test quality

- The browser tests drive Chromium's fake device and the real worklet. Each failure is injected where it really
  happens (`getUserMedia` throws a `DOMException` of that name, `addModule` rejects, `AudioWorkletNode` is
  removed, the worklet port is muted). The expected text comes from the page's own `JarvisAudio.words(code)`
  for the expected code, so a wrong mapping fails the test.
- Server answers are stubbed with `hear.words(...)`. That route's own mapping is tested through the real app in
  `test_r62_book_hear.py`.
- Clocks are fixed (`book_show_fakes.Clock` T0, `billing_fakes.NOW`). Nothing in the changed tests reads the
  wall clock or the branch.
- Fakes are imported bare (`book_hear_fakes`, `book_mocks`, `voice_fakes`).
- The waits are event-based (`wait_for_function`, `wait_for`), except L3.
- The RED evidence is plausible. 17 of 28 failing against `main`'s JavaScript matches exactly what `main` lacks:
  the status line, `#shMicOn`, the shared words, the silent and too-short checks, and the "without words"
  fallback. The 11 that pass there (10 server answers, the dropped connection) were already right on the client.

### 2.4 Version pins and the release label

- `__version__` is `6.2.0`. The five version pins and the three label pins moved (`R6.2`).
- `release_label` comes from `src/jarvis/__init__.py`, not the branch (`gen/plans.py:78`,
  `gen/fallback.py:63`), so main's CI (branch `main`) and PR runs (detached) give the same label.
- A search for `14.0.x`, `"R14"` and `startswith("14` found only fixtures that test other things (deploy-watch
  strings, the kit, the guard). The `test_book_gen_plans` pins pass (see L4 for later).
- Nothing else reads the package version in a way that breaks when it goes down. `selfwatch` compares by
  inequality, the home kit uses `BRIDGE_VERSION 0.2.0`, Android uses its own `version.properties`, and
  `check_doc_versions.py` doesn't read it.

### 2.5 Sizes

| File | Lines | Limit |
|---|---|---|
| `console-book-talk.js` | 305 | 400 |
| `console-book-voice.js` | 255 | 400 |
| `console-voice-capture.js` | 388 | 800 |
| `console-voice-mic.js` | 667 | 800 |
| `book.css` | 182 | 300 |
| `app.py` | 727, unchanged | 735 |
| `book_show.py` | 368 | 400 |
| `buildbook/service.py` | 397 | 400 |
| `hear.py` | 208 | 400 |
| `config.py` | 752 | 800 |

No changed function is over 50 lines. `VoiceService.transcribe` is exactly 50: its docstring grew it from 47,
so watch it. `view` at 52 is unchanged code.

### 2.6 General

- Immutability: `WORDS` and `HELP` are frozen, `Understood` is a frozen dataclass, and `BookWords` holds a
  one-entry memo.
- `textContent` only, with no `innerHTML` or inline style in the changed JS and HTML.
- The Book JS stays ASCII (`\u` escapes).
- There's no dead code, and `GUEST_GOOGLE` and the token-mode branch are fully removed. The only stale
  reference left is L1.
- The look: `.sh-tfoot` gets `gap:8px`. That is harmless, because `gap` applies only between rendered flex
  items and the hidden `#shMicOn` is `display:none` (no `.btn`/`.lift` rule sets `display`). With one button
  the footer looks as before. `#shHear` reuses the console's `.hint`.
- Unverified, not a finding: the two-button footer (only while "Mic off" is set) at a phone width. Phase A's
  layout case covered only desktop viewports. `.btn{flex:1}` plus a 24-character uppercase label probably wraps
  to two lines in 44 px, which is fine, but nothing tests it.

### 2.7 CI compatibility

- `pyproject` `pythonpath = ["src"]`; `tests/` has no `__init__.py`, so pytest's default import mode makes the
  bare imports work.
- The new tests need only base packages plus `.[dev]`. `jarvis.buildbook.hear` pulls in `understand.rules` and
  `voice.settings`, with no numpy, OpenCV or google-auth. The browser job's `.[dev]` + Playwright is enough.
- `test_a_laptop_keeps_dev_and_token_mode` assumes `K_SERVICE` is unset, which is true on GitHub runners.

## 3. What I ran

All on this machine, behind `flock /tmp/heavy.lock`, with `PYTHONPATH=$PWD/src`.

| Run | Result |
|---|---|
| `/tmp/venv-b` (3.11): `test_r62_book_hear`, `test_r62_book_open`, `test_r62_cloud_run_guard`, `test_r62_book_mic_static`, `test_book_guest_voice`, `test_book_show_api`, `test_about`, `test_book_boundaries`, `test_book_gen_plans::test_the_real_plans_parse`, and the R14 and R7 version and label seams | 181 passed |
| `ruff check` and `ruff format --check` on the 22 changed `.py` files; `mypy` on the 5 changed source modules | clean |
| `/tmp/venv-c` + Chromium, `JARVIS_BROWSER_TESTS=1`: 5 of the new browser tests (granted, the real-tap "Mic off", no sound, NotAllowedError, the console's shared words) | 5 passed |
| H1 reproduction (a scratch copy of `tests/` in `/tmp`, server on this branch's `src`; deleted afterwards) | reproduced, as in H1 |

Not run (the Workshop's runs): the whole unit, browser and R5 voice suites, evals and coverage.

## Change log

| Version | Date | Release | What changed | By |
|---|---|---|---|---|
| v6.2.1 | 15 Nov 2026, 20:37 IST | R6.2 | First edition: fresh-context code review 1 of `9a8392b..d237b8c`; 0 CRITICAL, 1 HIGH, 0 MEDIUM, 4 LOW; approve with fixes | 🛠 Mark XXI (code review 1) |
