Version v6.2.1 · 15 Nov 2026, 20:15 IST · Release R6.2 · Status: Current · Owner: 🛠 Mark XXI

# R6.2 Part 1 — "The Build Book: Ask by voice fixed" (integration notes A)

Built for the Workshop (🛠 Mark XXI) on branch `r6-2`, cut from `origin/main` @ `9a8392b`
(`v14.0.2`), after the owner approved Part 1 on 15 Nov 2026 (about 17:00 IST): the microphone fix
plus closing the developer no-passkey shortcut, as one small PR. The plan is the Phase A report
(`docs/plans/r6-2-book-rebuild/PHASE-A-FINDINGS.md` v6.2.1 on branch `r6-2-plan`): its Part 1
design (sections 4.3–4.5), its 20 reproduced cases (4.2), gap G11 and C8 (9.7), with the owner's
Phase B and non-negotiables 1–8. Every behaviour change was test first: the test was written and
seen failing, then the change made. Nothing was rebased, stashed or force-pushed; `main`, the
other worktrees (`r13-plan`, `r6-2-plan`) and the project's own docs were not touched; the hook
blocked nothing.

**Takeover.** The first builder was stopped by a server restart after pushing `f7fe775` (four
commits), with three small fixes uncommitted. A second builder took over in the same worktree:
it read the four commits and the uncommitted diff, finished those fixes test first (`22405bb`:
no "Switch the microphone on" once the questions run out; an empty `K_SERVICE` counts as unset;
a race in the browser helper), added Phase A case 2 as its own test, moved the one version pin
`f7fe775` missed (`cff2c07`: `test_r11_seams`), re-ran every check below and finished this
document. Nothing from the first builder was discarded.

## 1. What changed

### 1.1 Ask by voice (the shared R5 code and the Book; no fork)

| Where | What |
|---|---|
| `static/console-voice-capture.js` (R5, shared) | One table of words for each reason the microphone can't listen: `JarvisAudio.WORDS` / `JarvisAudio.words(code)` (`blocked`, `no_mic`, `busy`, `unsupported`, `failed`, `ended`, and the new `silent`). `blocked` now says how to allow it in Chrome on Windows (site settings, and Windows' own microphone switch) and on Android (Chrome's site settings, and Android's permission for Chrome), and still ends "Then tap the mic again." |
| `static/console-voice-mic.js` (R5, console) | `HELP` is the shared table plus the composer's own two lines (`mic_off`, `cloud_down`); no second copy of the words. `console-voice-wake.js` reads them through `HELP` as before |
| `static/console-book-voice.js` | `record.frames()`: how many 80 ms frames have come (none after 1.5 s: no sound is coming) |
| `static/console-book-talk.js` | One tap listens, a second stops (15 s at most, as before). A status line under the box (`#shHear`, `role="status"`, `aria-live="polite"`): "Listening… tap the mic again to stop." → "Processing…" → "Done. Edit the question if you like, then press Ask." (with "Heard “…”; understood as the words in the box" when the free rules changed it, and, for the owner, "This month's free listening minutes are used up, so this one was charged."). The words land in the box and are never sent by themselves; nothing heard keeps what was typed. Each failure has its own line in the thread (`.sys.error`, as before): the shared words for blocked / no microphone / busy / a part that failed to load / no sound, "too short" for a tap–tap at once, the server's Book wording for every server answer, the calm "Can't reach JARVIS…" for a dropped connection, and "I didn't catch that…" only when the server says nothing. The typed box stays usable after every one. **"Mic off"**: the status line says "The microphone is switched off in this browser…" and "Switch the microphone on" (`#shMicOn`) appears; a tap on the mic while it is off opens nothing and moves the focus there. Only a real tap turns it on: `e.isTrusted` and then `JarvisAudio.unlock('button')` (which also needs the browser's user activation), as in R5 D11; switching on never listens by itself. A lock set elsewhere (another tab, the console) stops a recording and shows the line. Once the session's questions are used up the box goes away, and so does "Switch the microphone on" (nothing is left to ask by voice; the lock itself is untouched). **An old browser** keeps the button, disabled (`aria-describedby="shHear"`), with "This browser can't record audio here. You can still type." |
| `static/book.html` | `<p class="hint" id="shHear" role="status" aria-live="polite" hidden>` under the composer; `<button class="btn lift" id="shMicOn" hidden>` beside "No more questions"; `aria-describedby="shHear"` on `#shMic`. Existing classes only |
| `static/book.css` | One property: `.sh-tfoot` gets `gap:8px` (seen only while both footer buttons show). Nothing else; the Book's look is unchanged |
| `buildbook/hear.py` (new) | `vocabulary(book)`: the book's own public words (a fixed list of 39 stack and service names, then this release's language and vendored stack names and its outside services' labels), cleaned as "Words to recognise" are, unique, at most 60. `BookWords(source)`: that list read once a release (an unreadable book gives the fixed list, asked again next time). `understood(heard, hints)`: the console's R11.1 rules (`understand.rules.apply`), no model call. `words(reason, owner=)`: one plain sentence a reason; the owner alone gets a short pointer to Vitals; `SPEAK_OFF` for narration |
| `buildbook/service.py` | `BookService.words = hear.BookWords(source)` (one line; the module stays at 397 of 400) |
| `voice/service.py` | `transcribe(..., public_hints=())`: words with nothing of the owner's in them go to the recogniser for a guest too, before any turn hint; a refusal while they are on retries with the base list only, as the owner's words already do |
| `api/book_show.py` `show_hear` | Answers `{text, heard, changed, no_speech}` (+ `charged: true` for an owner session when the question was priced). The book's words go to the recogniser for both audiences; the correction uses them, plus the owner's "Words to recognise" for an OWNER session only (R6 D1: for a guest they are never even read). Failures by reason in the Book's own words: `not_configured`, `api_disabled`, `upstream_error`, `timeout` (503), `budget` (the session's 30 spoken questions, 503), `budget_unreadable` (503, G12: was 402), `budget_reached` (402: "This month's free listening minutes are used up and the monthly spending limit is reached…", G13), `voice_busy` (429), `input_rejected` / `bad_audio` (422), `too_large` / `too_long` (413). No Cloud Shell command, no "the browser's voice is used", no rupees, no setting name, and for a guest no "Vitals" |
| `api/book_show.py` `show_speak` | A narration failure says only "Use the browser's voice." (it is true there: the page reads the line itself), never the setup text |

### 1.2 The developer no-passkey shortcut (G11) and the Cloud Run guard

| Where | What |
|---|---|
| `api/book_show_access.py` | `console()` is a Google sign-in only; the `"token-mode dev, no passkey"` branch and `409 guest_needs_google` are gone. In token mode, dev or not, every `POST /v1/book/open` is `403 google_needed` ("The build book opens only with Google sign-in and your passkey, so it stays shut in token mode. To try it on this computer, run JARVIS with JARVIS_AUTH_MODE=google."), audited as a refusal (`book_open` refused, how `google_needed`), and no session is made. Google mode is unchanged: passkeys in force → a fresh Google sign-in → the audience-bound proof |
| `config.py` | `cloud_run_service` reads Cloud Run's own `K_SERVICE`. With it set, `require_prod_invariants` (called by `create_app` and `jarvis chat`) refuses to start on `JARVIS_ENV=dev` or `JARVIS_AUTH_MODE=token`; the message names settings only, never a value; an empty value counts as unset. `deploy/cloudrun.sh:520` sets `JARVIS_ENV=prod` and `JARVIS_AUTH_MODE=google`, so the live service starts as before |

### 1.3 The version

`jarvis.__version__` = `6.2.0`. The five pinned version tests move with it (`test_about`,
`test_r14_seams`, `test_r7_seams`, `test_r11_1_seams`, and `test_r11_seams`, whose `14.` prefix
`f7fe775` missed: now `6.2.`), and so do the three that pin the real
repository's release label, which the generator reads from the version (`test_r14_seams`,
`test_r7_seams`, `test_book_gen_determinism`: now `R6.2`). The persona is unchanged (no version
in it).

## 2. The 20 cases of Phase A 4.2, as tests

All in `tests/browser/test_r62_book_mic.py` (headless Chromium launched with
`--use-fake-ui-for-media-stream --use-fake-device-for-media-stream`: Chromium's own fake
microphone and the real capture worklet), against the Contract stubbed by `book_mocks.FakeBook`;
the server's words come from `jarvis.buildbook.hear` itself.

| # | Case | Test |
|---|---|---|
| 1 | Permission granted | `test_one_tap_listens_a_second_stops_and_the_words_land_in_the_box_unsent` (Listening → Processing, held → Done; a real WAV; no `/ask`) |
| 2e | Denied / blocked in Chrome (`NotAllowedError`, what Chrome and Windows' switch give) | `test_a_microphone_that_refuses_says_why[NotAllowedError-blocked]` (Chrome, Windows, Android steps) |
| 2 | Denied with no prompt (headless Chromium says `NotSupportedError`) | `test_a_microphone_that_refuses_says_why[NotSupportedError-failed]` (the shared "didn't start" words) |
| 3 | "Mic off" set | `test_mic_off_is_shown_and_only_a_real_tap_switches_it_on` (no `getUserMedia`; a script `click()` and a synthetic `MouseEvent` both refused; the real tap unlocks; then it listens), `test_mic_off_set_while_listening_stops_and_sends_nothing` and `test_mic_off_offers_no_way_back_once_the_questions_run_out` |
| 4 | No microphone (`NotFoundError`) | `test_a_microphone_that_refuses_says_why[NotFoundError-no_mic]` |
| 4b | Busy in another app (`NotReadableError`) | `test_a_microphone_that_refuses_says_why[NotReadableError-busy]` |
| 5b | Worklet fails to load | `test_a_capture_part_that_fails_to_load_says_so` |
| 6 | Unsupported browser | `test_an_unsupported_browser_keeps_the_button_disabled_with_the_reason` |
| 5c | Audio never starts | `test_a_microphone_that_sends_no_sound_says_so` (the worklet's frames never arrive) |
| 9c | Tap–tap at once | `test_a_tap_tap_at_once_is_too_short_and_says_so` |
| 7 | Voice not set up (503 `not_configured`) | `test_each_server_answer_is_said_and_the_box_still_works[503-not_configured]` |
| 7b | Speech API off (503 `api_disabled`) | `…[503-api_disabled]` |
| — | Speech service errors / too slow | `…[503-upstream_error]`, `…[503-timeout]`, `test_a_server_answer_without_words_gets_the_books_own` |
| — | The limit can't be read (G12) | `…[503-budget_unreadable]` |
| 7c | The session's 30 spoken questions | `…[503-budget]` |
| 8 | Monthly limit (402) | `…[402-budget_reached]` |
| 8b | Google busy (429) | `…[429-voice_busy]` |
| 9 | Nothing heard | `test_nothing_heard_says_so_and_keeps_what_was_typed` |
| 9b | Too short (422 `bad_audio`) | `…[422-bad_audio]`, and `…[422-input_rejected]` |
| — | Network drop | `test_a_dropped_connection_is_said_calmly` |
| — | Heard / understood as; charged (owner) | `test_heard_and_understood_as_when_the_free_rules_changed_the_words`, `test_the_owner_is_told_when_a_spoken_question_was_charged` |
| — | The console reads the same words | `test_the_console_reads_the_same_words_for_a_blocked_microphone` |

Every failure test also checks that the typed box still sends a question (`_typing_still_works`),
that nothing was sent to `/hear` when the microphone never opened, and that the page logged no
error and no CSP violation (`_clean`). The layout case of 4.2 is unchanged (no layout change).

## 3. Tests added and changed

| File | Tests | What |
|---|---|---|
| `tests/test_r62_book_hear.py` (new) | 46 | The hear route through the real app with a fake recogniser: the owner's corrections with his words, a guest never biased (his words never read), unchanged words, nothing heard, charged (owner only, never a guest), each failure in the Book's words for both audiences (8 × 2) with no admin text for a guest, the limit said truthfully, too short, no voice service, the session's spoken questions, narration's words; `VoiceService` public hints (a guest gets them, never his words; a refusal retries with the base list); `vocabulary`, `BookWords` (once a release; an unreadable book), `understood`, `words` for every reason |
| `tests/book_hear_fakes.py` (new) | — | `Ears`: `app.state.voice` for the route, records how it was asked |
| `tests/test_r62_book_open.py` (new) | 5 | Token mode (dev and prod) never opens the book for owner or guest: 403, audited, no session; Google mode still opens with the passkey and a fresh sign-in; the refusal's words |
| `tests/test_r62_cloud_run_guard.py` (new) | 7 | `K_SERVICE` read; dev and token mode refused on Cloud Run; production starts; a laptop keeps dev and token mode (an empty `K_SERVICE` too); `create_app` refuses before building; the message names no value |
| `tests/test_r62_book_mic_static.py` (new) | 5 | One words table in the capture module; the console reads it with no second copy; the Book reads it and never opens the microphone itself; only `micOn` unlocks, behind `e.isTrusted`; the show page's status line and button |
| `tests/browser/test_r62_book_mic.py` (new) | 28 | Section 2 (26 by the first builder; case 2 and the questions-run-out case at the takeover) |
| `tests/test_book_show_api.py` | 1 changed | `test_token_mode_dev_opens_for_the_owner_only` → `test_token_mode_dev_never_opens_the_book` (G11) |
| `tests/test_r6_contract.py` | 1 row | `POST /v1/book/open` wired in token-mode dev: `(403, "google_needed")` (was `(200, None)`) |
| `tests/test_book_guest_voice.py` | 1 changed | The fake takes `public_hints`; the answer's new shape |
| version and label | 8 lines | Section 1.3 (`test_r11_seams` at the takeover) |

Red first: the new unit tests failed on import (`GOOGLE_NEEDED`, `jarvis.buildbook.hear`) and on
behaviour (15 failures before the code: the Cloud Run guard, the static seams, the version, the
token-mode open); the browser tests failed to collect without `hear.py`, and against `main`'s own
JavaScript (a scratch copy of `main` @ `9a8392b` with only the new test file and `hear.py` added) 17
of the 28 fail: every microphone case, "Mic off", the status line, the unsupported browser, no
sound, too short, nothing heard, a server answer without words and the console's shared words.
The 11 that pass there are the 10 server answers (`main`'s page already showed the server's
`detail` as it came; that fix is server-side, and red in `test_r62_book_hear`) and the dropped
connection (already calm on `main`, Phase A 4.2). At the takeover, the two new behaviour tests
were seen failing first against the previous code: the questions-run-out case against
`f7fe775`'s JavaScript, the empty `K_SERVICE` case against its `config.py`; and
`test_r11_seams` against version 6.2.0.

## 4. What was run, and the results

All on this 2-CPU machine, heavy runs behind `flock /tmp/heavy.lock`; `PYTHONPATH=$PWD/src`.

| Run | Result |
|---|---|
| *First builder, before the takeover* | |
| Baseline before any change (3.11): the book, voice, contract, version and seam unit files touched below | 871 passed |
| New unit tests before the code (RED) | 15 failed, 2 collection errors (as expected) |
| R5 voice + R6 book + touched unit files, 75 files (3.11, `/tmp/venv-b`) | 2,442 passed, 8 skipped |
| Touched unit files (3.12, `/tmp/venv-12`) | 458 passed, 1 skipped |
| `tests/browser/test_r62_book_mic.py` (3.13 + Chromium, `/tmp/venv-c`) | 26 passed |
| R6 book browser files | 83 passed |
| *After the takeover, on `cff2c07` (the final code)* | |
| R5 voice + R6 book unit files, every touched unit file and every unit file that reads the changed JavaScript or calls `require_prod_invariants`: 104 files (3.11, `/tmp/venv-b`) | **3,075 passed, 7 skipped** (2 warnings: FastAPI's duplicate operation id in `api/phone.py`, untouched) |
| Touched unit files, 13 (3.12, `/tmp/venv-12`) | **459 passed, 1 skipped** |
| `tests/browser/test_r62_book_mic.py` + the R6 book browser files (`test_book_lock_ui`, `test_book_panel`, `test_book_show`, `test_book_show_hold`, `test_r6_fix_labels`, `test_r6_i1_console`, `test_r6_seams`) (3.13 + Chromium, `/tmp/venv-c`) | **111 passed** (28 + 83) |
| R5 voice browser files: `test_voice`, `test_voice_barge`, `test_voice_commands`, `test_voice_devices`, `test_voice_devices_fixes`, `test_voice_fixes`, `test_voice_fixes_barge`, `test_voice_live`, `test_voice_loop`, `test_voice_micoff`, `test_voice_pace`, `test_voice_robust`, `test_wakeword`, `test_r5_seams` | **397 passed** (30 min 31 s) |
| The new browser tests against `main`'s JavaScript (RED evidence, section 3) | 17 failed, 11 passed (as expected) |
| `ruff check src tests evals`, `ruff format --check src tests evals` (ruff 0.17.5) | clean (1,738 files) |
| `mypy` (strict, the repo's config) on the 7 changed modules (`buildbook/hear.py`, `buildbook/service.py`, `api/book_show.py`, `api/book_show_access.py`, `config.py`, `voice/service.py`, `__init__.py`), 3.11 and 3.12 | clean (no issues in 7 source files, both) |
| `scripts/arch_coverage.py` | OK (65 packages and modules, 90 console modules, 2 Scheduler jobs, 30 outside services, 106 collections) |
| `scripts/check_doc_versions.py` | all 28 top-level documents pass; it reads only `docs/plans/*.md` and `docs/architecture/*.md`, so this file was checked with its `problems()` too: none |
| `python -m jarvis.buildbook.gen --check` (3.11, a throwaway local clone of `cff2c07` plus this file) | OK: "build book R6.2: book.json 182,044 bytes, source.zip 7,831,717 bytes; two builds are byte-identical" |

Not run here (the Workshop runs them): the whole unit suite, the whole browser suite, the evals,
coverage, and the fresh-context `code-reviewer`, `python-reviewer` and `security-reviewer` agents
(neither builder had an agent tool; the first builder self-reviewed its diff, and the second
re-read all of it at the takeover: section 8, item 8).

## 5. Wiring changes

None in `api/app.py`, `api/r6_wiring.py` or `tools/gateway.py`. The joins are:
`BookService.words` (made in its constructor from the source it already has), the new keyword
`VoiceService.transcribe(public_hints=)` (default empty: every other caller unchanged),
`Settings.cloud_run_service` (env `K_SERVICE`), `JarvisAudio.WORDS` / `words` (added to the frozen
object; nothing removed), `JarvisBookVoice.record.frames`, and the two new elements in `book.html`.

### Sizes against their limits

| File | Lines | Limit |
|---|---|---|
| `api/app.py` | 727 (unchanged) | ≤ 735 |
| `tools/gateway.py` | 760 (unchanged) | 760, not edited |
| `core/brain.py` | 713 (unchanged) | ≤ 741 |
| `static/console.html` | 782 (unchanged) | ≤ 782, not touched |
| `static/console-voice-capture.js` | 388 (369) | ≤ 800 |
| `static/console-voice-mic.js` | 667 (671) | ≤ 800 |
| `static/console-book-talk.js` | 305 (241) | ≤ 400 (its header) |
| `static/console-book-voice.js` | 255 (253) | ≤ 400 (its header) |
| `static/book.html` | 117 (116) | small |
| `static/book.css` | 182 (182; one property added) | ≤ 300 |
| `api/book_show.py` | 368 (333) | ≤ 400 (`test_book_boundaries`) |
| `api/book_show_access.py` | 306 (305) | ≤ 400 |
| `buildbook/service.py` | 397 (396) | ≤ 400 |
| `buildbook/hear.py` (new) | 208 | ≤ 400 |
| `config.py` | 752 (729) | — |
| `voice/service.py` | 602 (599) | — |

## 6. Local development (C8): the Book still needs the passkey

Token mode no longer opens the Book anywhere. To try it on a laptop, run JARVIS in Google mode at
`http://localhost` (WebAuthn takes `localhost` as a domain, so a passkey works there):
`JARVIS_AUTH_MODE=google`, `JARVIS_PUBLIC_BASE_URL`
`=http://localhost:8000`, `JARVIS_GOOGLE_CLIENT_ID`, `JARVIS_GOOGLE_CLIENT_SECRET` (a Google OAuth
client whose redirect URI is `http://localhost:8000/auth/callback`), `JARVIS_OWNER_EMAILS`,
`JARVIS_SESSION_SECRET` (32+ characters), with `JARVIS_ENV=dev` and the mock brain as the
browser tests use it. Then register a passkey in Approvals → Permissions and open the Book from
the console. Unverified here (no OAuth client in this sandbox): the steps follow the code
(`config._require_google_auth_config`, `permissions/ceremony.RelyingParty.from_base_url`). The
tests keep their fake Google sign-in and soft passkey (`tests/book_app_fakes.py`), and the browser
tests stub the Book's routes (`book_mocks.FakeBook`), so neither needs the shortcut.

## 7. The live check for the go-live guide (for the Workshop to place)

> **Build Book: Ask by voice (R6.2).** On the laptop, in Chrome: open the Book's show, go to
> Questions, and tap the microphone once. The line under the box says "Listening…". Say "How
> does JARVIS keep my data private?" and tap again: it says "Processing…", then "Done…", and your
> words are in the box, not sent. Press Ask. If instead a sentence says the microphone is
> blocked, follow its Chrome steps; if it says the microphone is switched off, tap "Switch the
> microphone on" and try again. Tell the Workshop the sentence you saw if it is anything else.

## 8. For the reviewers, and open questions

1. **Decision 4 (stop listening at the free minutes) is NOT built.** The brief asked for the
   truth about today's billing: past the free 54 minutes a spoken question is charged until the
   monthly limit (402). So the 402 now says both are used up, and the owner sees "this one was
   charged" on a priced question; a guest is never told about costs. If the owner answers YES to
   decision 4, the Book needs a free-only gate (a change in `billing`/`voice`, its own tests).
2. **Security review wanted** (auth): the G11 refusal (`book_show_access._opening`) and the
   Cloud Run guard (`config._refuse_dev_on_cloud_run`). The guard also closes, on Cloud Run, the
   other token-mode dev shortcuts that remain in the code and are outside this part (`api/phone.py`
   offer, `api/deleted.py` remove-now, `api/faces.py`); locally they are unchanged.
3. `book_gate.console_only` (the owner routes in `api/book.py`) still lets token-mode dev read
   `GET /v1/book` (status) and the Book settings, so the console's Book panel loads and then says
   why the Book won't open. No session can be opened in token mode, so the reader, the old books
   and the code download stay shut. Tell me if those two should refuse too.
4. **The console's wording changed** (text only, no style): its "blocked" help now carries the
   Chrome / Windows / Android steps and is longer when shown. R5's own test of it is green.
5. **The version goes down** (14.0.2 → 6.2.0, the owner's release numbering). Nothing compares
   versions (`selfwatch` tells a new revision or version by inequality; sealed books are ordered
   by time). The book's release label is now `R6.2`; the first plan it reads stays
   `docs/plans/r14-hardening.md` until a top-level `docs/plans/r6-2-*.md` lands (then
   `test_r14_seams` / `test_r7_seams` need that path). Not updated here: the architecture guide
   (v14.0.3: its C57 card's "Where in the code" could add `buildbook/hear.py`; its "Outside
   services" is G2, Part 2) and the project's own release plan and progress docs (not in the repo).
6. The "no sound" check waits 1.5 s for the first frame (Phase A 4.5). Frames are the capture
   pipeline's, not the room's loudness, so a quiet room or a slow Bluetooth headset still sends
   them; only a stalled pipeline trips it.
7. `.sh-tfoot` got `gap:8px` for the two footer buttons; with one button (always, unless "Mic off"
   is set and questions are left) the Book looks exactly as before.
8. **The takeover's read of the whole diff** (fresh eyes, no agent tool; nothing needed a change):
   "charged" is said only above the free allowance (`billing.record_units` prices only what is
   over it, and a meter write that fails says nothing, the safe side); the only Cloud Run deploys
   (`deploy/cloudrun.sh:520`, and CI's `gcloud run deploy --image`, which keeps the service's
   settings) run `prod` with Google sign-in, so the guard can't stop the live service; nothing
   else used the removed token-mode branch of `book_show_access.console()`; `hide()` stops a
   recording, so the 1.5 s no-sound timer can't fire after the panel closes; the book's words are
   read as the show script and the talk read the book (the source parses it once a release);
   no `innerHTML` or inline style in the changed JavaScript and HTML; the Book's two "ASCII
   source" files stay ASCII.
9. **Scope of the Cloud Run guard.** Phase A 9.7 listed two more conditions for Part 2: memory
   sessions on Cloud Run, and token mode without an API token (the token-mode refusal here
   already covers the second). This part does only what the brief and decision 6 ask: `dev` or
   token mode with `K_SERVICE` set. Memory sessions on Cloud Run stay for Part 2.

## Change log

| Version | Date | Release | What changed | By |
|---|---|---|---|---|
| v6.2.1 | 15 Nov 2026, 20:15 IST | R6.2 | First edition: Part 1 built (Ask by voice in the shared R5 code and the Book; the hear route's free corrections and plain words; G11's refusal and the Cloud Run guard; version 6.2.0), the 20 cases as tests, what was run, the wiring, the sizes, local development, the live check, the open questions. Finished at the takeover (the first builder's draft of 18:40 IST, never committed): the three uncommitted fixes finished test first, Phase A case 2 and the questions-run-out case as tests, the missed `test_r11_seams` pin, every run re-done on the final code with its results, the takeover's review and the guard's scope (section 8, items 8 and 9) | 🛠 Mark XXI |
