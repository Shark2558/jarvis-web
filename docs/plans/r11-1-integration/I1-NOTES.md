Version v11.1.4 · 12 Nov 2026, 19:45 IST · Release R11.1 · Status: Current · Owner: 🛠 Mark XV

# R11.1 I1 — integration notes (Mark XV)

Branch `r11-1-i1`, from `r11-1-i0` @ `1d49a1c`. What the integrator joined, every conflict and how it
was resolved, every cross-part issue found, each merge gate and "Needs I1" item with the test that
proves it, the over-caution numbers, the Cloud Run instance check, what is left, and (section 10)
the integrated reviews with their fixes and the residuals for the release notes. The parts' own
notes are `INTEGRATION-A.md` … `INTEGRATION-D.md` beside this file; the plan is
`docs/plans/r11-1-observations.md`.

## 1. Merges

| # | Merged | At | Conflicts | Resolution |
|---|---|---|---|---|
| 1 | `origin/main` | `665fce0` | none | test only (`tests/browser/test_dock_fit.py`, Mark XIV's `bf75cf2`) |
| 2 | `origin/r11-1-a` | `a5f2020` | none | — |
| 3 | `origin/r11-1-b` | `06db8c1` | none | — |
| 4 | `origin/r11-1-c` | `1de44b6` | none | — |
| 5 | `origin/r11-1-d` | `7bdaf96` | none | — |

No file was changed by more than one part, and no part touched the files I0 changed after the
builders forked (`buildbook/gen/layers.py`, two book tests, `tests/test_trust_flag.py`). Every join
was semantic, not textual; the ones that were real defects are in section 3.

## 2. Gates and "Needs I1" items

Every item was written test first (the test seen failing, then the change). Test files added by I1:
`tests/test_r11_1_i1_bounds.py`, `_pictures.py`, `_persona.py`, `_plan.py`, `_telegram.py`,
`_photos.py`, `_signing.py`, `_overcaution.py`, and `tests/browser/test_r11_1_i1_console.py`.

| Item | Done | What, and the proving test |
|---|---|---|
| **GATE A 3.12** Telegram private reads | done | `gmail_inbox_summary` and `picture_*` join `PRIVATE_PATTERNS`; `photos_import_*` (faces found, people recognised) joins `HOME_PATTERNS` beside `faces_*`. The guard test builds the four R11.1 parts as the app does and classifies every one of their reads (`test_telegram_tool_guard.py::test_every_r111_part_read_is_registered_and_classified`, `…private_reads_on_the_inbox_summary_answers_but_the_home_ones_still_wait`). **Decided differently from the orchestrator's list:** `series_*` is not a pattern: patterns deny every risk, so it would also refuse the R2 check-in answer ("session done") on Telegram, where the check-in alert arrives; `series_list` is counts, times and his own typed plan name (like `calendar_list_events`) and stays in `TELEGRAM_SAFE`. The R3 seam pin of `HOME_PATTERNS` follows. |
| **GATE A 3.4** the brief's inbox | done | `InboxSection` gains `groups`, `withheld`, `exact`, `failed`, `listed`; `BriefService(reads=BackgroundReads(...), mail_max_reads=...)`, built over the gateway in `api/app.py`. Tests on the REAL `BriefService`: "Never" and "Ask first" on the mail row mean no Gmail GET at all; an allowed read brings the groups, the withheld count and "about 2 unread" to the rendered brief, no code in it; the app's brief reads through the governed path (`test_brief_service.py::test_r111_*`); the brief API's pinned shape (`test_brief_api.py`). `evals/brief` GATE: PASS. |
| A 3.5 "Primary" / "the last day" | done | the summariser's line and the console's empty / "about N" lines (`brief/summarize.py`, `console-brief.js`). |
| A 3.1 `finish.EMPTY` vs `FILLER` | done | the alias is gone; the seam test asserts `EMPTY` and no `FILLER` attribute. |
| A 3.1b / C 3.2 clock-job lists | done | `test_r11_wiring.py` counts the R11.1 jobs on the helpers' clock (`series_checkin`, `photos_import`, `face_groups_poll`) and checks every job ran. |
| A 3.2 No-AI phrase slot | done | `r11_1_wiring.fix_phrases` / `install_fix_phrases`, called at the end of `wire_r11` whether the helpers are on or off, after the helpers' own phrases (`test_r11_1_i1_plan.py`, both helper settings, order). A's own route test pinned the gap ("not in the phrasebook at start") and now pins it closed. |
| A 3.3 brief contributor | done | `r11_1_wiring.fix_brief` feeds the parts' `services["brief"]` into `r11_wiring.helpers_brief` (`test_r11_1_i1_plan.py::test_the_brief_s_helpers_lines_carry_the_plan_s_open_check_ins`). |
| A 3.6 persona sentences / persona `p11.1` | done | ONE version `p11.1` (the 19 pinned assertions follow, D's sed list); `PLANS_RULE` with A's three sentences beside D's `PICTURES_RULE`, in every wit level before the tools rule; change notes updated (`test_r11_1_i1_persona.py`). **Changed wording:** A's `series: {name}` became `series (the plan's name)`: the persona may hold no brace (a placeholder could be injected; `test_voice_persona.py` pins it). |
| A 3.7 Recently deleted vs a 60-event Undo | done | the panel (`/v1/deleted`) lists up to `PANEL_LISTED` = 100 (a batch's maximum); the model's `deleted_list` stays at `MAX_LISTED` = 50 so its result stays inside the gateway's budget (`test_r11_1_i1_plan.py`, store and route). |
| A 3.8 Approve all's plain reply | done | Approve all says a plan card's own sentence (`finish.said_by_code`) when no model can narrate, never "Done, Sir: Add 60 events" (`test_r11_1_i1_plan.py::test_approve_all_without_a_narrator_says_the_batch_s_own_count`). |
| A 3.9 the R11 bug: a card under a non-session scope | done | the only such card was the kitchen's "Ask to add to my calendar" (`<uid>:helpers_kitchen`); it now waits in a new conversation of his own and the answer carries its `session_id`; proposed, then decided through the Brain (`test_r11_1_i1_plan.py::test_the_kitchen_s_calendar_card_waits_in_a_real_conversation_and_can_be_approved`, `test_r11_d_routes.py`). |
| A 3.10 Telegram's first line | done | the batch, its undo and the re-plan card show their code-written first line and "Open JARVIS to see the full list and approve it.", no button; a first line too long, or another tool, keeps the plain line (`test_r11_1_i1_telegram.py`). |
| A 3.13 / orchestrator 4 `work_output_tokens` ≤ 32,000 | done | `config.py` and the pinned range (`test_r11_1_i1_bounds.py`, `test_r11_1_seams.py`). |
| **GATE B 3.2** `feature_wiring` | done | `DocumentService(..., policy=policy_from(s), sessions=app.state.store)`; the per-request assignment in `api/documents.py` is gone (`test_r11_1_i1_pictures.py::test_the_document_service_has_his_limits_and_the_conversations_from_the_start`, `…no_route_sets_the_document_policy_any_more`). |
| B 3.3 the two attachment bounds | done | `ChatRequest.attachments` and `attach_max_files` both 10 (`test_r11_1_i1_bounds.py`). |
| B 3.1 dependency pins | done | see section 5. |
| B 3.5 the tool-word test | done | `test_r11_1_b_guard.py::test_every_gateway_tool_verb_is_an_action_word` builds the merged app and passes: every word of A's, C's and D's tool names was already classified. |
| **GATE D-A** `web_search` hook | done | `web_tools(web, pictures)`: `query_stop` first in the run, `query_preview` as the look-up; unwired it fails closed. D's web test now uses the real hook; the older web Rig gets a guard whose port says "no picture", as the app's does. |
| **GATE D-B** one guard for the app | done | `app_guard(...)` built in `_build_tool_gateway`, through `build_gateway(pictures=)` to `register_r4_tools` (`PeopleDeps.pictures`) and `web_tools`. Real-app test: on a picture turn the main brain's `research_person` and `web_search` with a face's name are refused on both tool rounds and again after a restart, and the vendor received nothing; without a picture the same search goes out (`test_r11_1_i1_pictures.py`). |
| **GATE D-C** the port over B's `turn_pictures` | done | `DocumentTurns` passes the app's conversation store (read late) and maps B's `unreadable` and any fault to "unknown" (a picture turn). Real-app test: attach a PNG -> send -> `POST /v1/picture/research` is "done"; after a restart (a new app on the same stores) `turn_pictures` returns the picture and the research is "done" again. **Found here: section 3.1.** |
| D 4.D the "Look up" card | done | `PeopleOfferCard` in `reply_cards.AnyCard`, the dispatch line in `console-media.js`, the `type: ignore` gone; D's "until the kind is registered" test now takes the kind out itself. Unit test on the response union, browser test under a real reply (`test_r11_1_i1_console.py::test_the_look_up_card_shows_under_the_reply_and_researches_only_on_his_press`). |
| D 4.6 `console.html` comment | done | "profile cards, each with its own link"; 795 lines, pinned (`test_r11_1_seams.py`). |
| D 4.5 the kit's container names | checked | C renamed nothing; `test_r11_1_d_vitals_home.py` passes on the merged tree. |
| C 3.1 OpenCV / NumPy | done | the `homebridge` extra pins `opencv-python-headless==5.0.0.93` and `numpy==2.5.4` (a test keeps them equal to `deploy/home/bridge-requirements.txt`'s hash-locked pins); CI installs the extra on Python 3.12 (NumPy 2.5 needs 3.12); `home/kit.py` lists `cv2` and `numpy` as safe (tested against the bridge lock). **Decided differently:** they are not in `requirements.licences.json`: that table must match `requirements.lock` exactly (the build book refuses extra rows) and they are not in the cloud image; their licences are in the bridge lock's comments and the kit README's third-party note (C's). |
| C 3.2 seven outside tests | done | `test_r3_seams.py` (routes, plugins: now also pinned by module), `test_r4_seams.py` (9 -> 11), `test_r3_wiring.py`, `test_home_api.py` (0.2.0), `test_r11_wiring.py` (two). |
| C 3.3 `ImportLimits` in `wire_photos` | done | `test_r11_1_i1_photos.py::test_the_photos_service_has_his_import_limits_from_the_first_call`. |
| C 3.3 console-home "-Update" | done | `test_r11_1_i1_photos.py::test_the_old_kit_note_names_the_update_step`. |
| C 3.4 `photos_import_batch` description | done | "The least a step reads when its time allows (a step reads up to 50)". |
| C 3.4 Privacy "pending" | done | `privacy.service.Deleted.pending`: a source's own fixed words when a delete left rows ("Pending: it finishes when your home laptop is back on."), "" otherwise or on any fault; the dashboard shows "Face groups: Pending: ..." instead of "Try again in a moment" (`test_r11_1_i1_photos.py`, the API shape, the browser test in `test_r11_1_c_photos.py`). |
| C 3.4 `home/signing.py` | owned | reviewed: additive (`BODY_HASH_HEADER`, `body_hash`, `verify_declared`), `request_message` builds the same bytes. Golden headers computed with the R3 module come out byte for byte; `verify_declared` refuses a wrong or malformed hash, a stale time, a seen nonce and another target, and never remembers the nonce (`test_r11_1_i1_signing.py`). |
| Orchestrator 10 / B 3.4 / C / D the eval in the release gate | done | `("r11_1 (gated)", …)` in `evals/run_all_mock.py`; the seam test asserts it. |
| Orchestrator 6 the stub-stage seam test | done | retired; `test_every_part_is_built_and_the_runner_passes_with_every_control_failing` reads the runner's report: no stub, every case passed, each part's control failed some of its cases. |
| Orchestrator 11 the console rule | done | Parts A and B asked the server before sign-in (A: the page becoming visible again reloaded with `loadedAt` 0; B: an attach or a conversation switch fetched hints). Both now ask `JarvisConsole.ready()` first; a browser test each, red on the old modules (`test_r11_1_i1_console.py::test_before_sign_in_the_block_asks_the_server_nothing[...]`); C and D have their own. |
| Orchestrator 21 over-caution | done | section 4. |
| Orchestrator 22 the reply-text residual | documented | section 6. |
| The guide | done | `JARVIS-Architecture.md` edition v11.1.2: C61 as built; C04, C05, C07, C08, C12, C13, C18, C19, C21, C37, C38, C39, C52, C53, C55; the intro, the "how checked" bullet, the change log; `arch_coverage.py`, `check_doc_versions.py`, `markdy_export.py --check` pass. README: an R11.1 section (modules and routes). |

## 3. Cross-part issues found and fixed at the join

1. **A picture turn read as "no picture" from its second tool round on (B x D, GATE C).** The
   Brain stores each round's tool results as a `Role.USER` turn (blocks only, no words), and B's
   `_latest_owner_turn` took the latest user turn. So on round 2 of a picture turn
   `turn_pictures` answered "no" (not "unreadable") while the brain still had the picture in its
   window, the turn guard opened, and after any reply that used a tool `POST /v1/picture/research`
   said "There is no picture with your last message". Measured before the fix: rounds
   `[(1 picture), (0, not unreadable)]`. Fix in `documents/pictures.py`: a user turn whose blocks
   are all tool results is never "his latest message"
   (`test_r11_1_i1_pictures.py::test_a_picture_turn_stays_a_picture_turn_on_every_tool_round`; the
   real-app test proves both tool rounds refused).
2. **Picture research said "no picture" when B said it could not read them.** It now says "I
   couldn't read the picture with your last message just now, Sir." (`PICTURES_UNREADABLE`,
   status `unreadable`), as B's contract asks.
3. **Older web tests and the fail-closed default.** Unwired, `web_search` counts every Brain turn
   as a picture turn (D's design). Two older tests built `web_tools(web)` inside a Brain turn and
   searched an untyped capitalised name; they now pass a guard whose port says "no picture", as
   the app does for a turn without one (D anticipated exactly this).
4. **D's test fakes of `turn_pictures`** took three positional arguments; the port now passes
   `sessions=`, so the fakes take `**_kw` (no assertion changed).
5. **`app.py` budget.** I0's seam pinned `app.py ≤ 730` for the builders; I1's two joins made it
   731 (guard 750): the pin now says 735.
6. **The chat box's hint was cut (B x the R6.1 dock).** Part B's limits (`GET /v1/input`, after
   sign-in) make `console-attach.js` redraw, and its redraw wrote "Message JARVIS" back over the
   dock's fitted "Message"; with B's new folder button the box is narrower, so the full hint no
   longer fitted (`test_dock_fit.py` at 1280, 1024, 900 and 320 px). The dock now refits the hint
   on every `jarvis:attach` and leaves an attached file's own hint alone.
7. **Photos off answered `GET /v1/facegroups/import` with 503 (C).** The browser logs any non-2xx
   load as a console error, so every panel test that opened Connectors failed its no-error check
   (`test_dock_fit.py` three tests). The read now answers the state (`status: "off"`, 200), as
   `/groups` does; the step and stop actions still answer 503; the import line stays hidden.
8. **The "Used N memories" chip was 24 px on a phone (a pre-existing gap Part B's visual gate
   exposed).** The browser tests share one server; once an earlier test saved a memory, B's real
   reply carried the chip. The Undo chip beside it is 44 px on phones; the memory chip now is too
   (`test_r11_1_i1_console.py::test_on_a_phone_the_reply_s_memory_chip_is_a_44_px_target_like_the_undo_chip`).
   B's phone gate had passed in isolation for exactly that reason.
9. **A locator.** `test_r51a_ui.py`'s GitHub confirm locator matched C's new "Confirm stopping the
   import" group too; it now names its own group.

## 4. Over-caution (orchestrator item 21)

On a picture turn the turn guard refused ordinary web queries. Measured with `check_query` on 35
ordinary queries and 26 person-name queries (every person made up), the owner having typed only
"what is this?" and the picture showing nothing relevant:

| | Before | After |
|---|---|---|
| Ordinary queries refused | **23 / 35** ("monsoon weather forecast", "weather in Mumbai today", "flights to Delhi tomorrow", "cricket score", "gold rate today", "Onam festival dishes", …) | **5 / 35** ("Taj Mahal opening hours", "Mumbai Pune expressway traffic", "Google Pixel 9 review", "Thrissur Pooram 2026", "Mount Everest height") |
| Person-name queries let through | **0 / 26** | **0 / 26** |

The tuning (`picture/turnguard.py`, `picture/words.py`): a capitalised word counts as a name only
inside a run of two or more capitalised words that could be a name (not a small word, not an
ordinary search word from `QUERY_WORDS`, not the query's sentence-case opener) with a word he did not
type and the picture does not show; a lone capitalised word ("weather in Mumbai") goes ahead, as
the opening capital always did. A bare name is what is left once the ordinary search words are set
aside: two words or more ("rajesh examplekar contact number" is refused, "monsoon weather
forecast" is a topic), or the whole one-word query ("Kohli"). `QUERY_WORDS` leaves out on purpose
words that are plausible given names or surnames (price, best, gold, rain, rose, …).

The 5 left are two capitalised words in a row: exactly a name's shape, so plain code cannot tell
them from "Firstname Lastname"; each goes ahead as soon as the picture shows it or he types it
(pinned). Known gap kept from D's design: a single capitalised surname ("news about Examplewala")
goes ahead, as "Examplewala news" already did at the opening. D's tests, its eval (24/24) and its
five controls are unchanged. Both sets are pinned in `tests/test_r11_1_i1_overcaution.py`.

## 5. Dependencies

- `pyproject.toml`: `openpyxl==3.1.5`, `et-xmlfile==2.0.0`, `xlrd==2.0.2`, `lxml==6.1.3` (exact, as
  Part B asked: xlrd's visibility list is read directly); the `homebridge` extra adds
  `opencv-python-headless==5.0.0.93`, `numpy==2.5.4`.
- `requirements.lock`: pip-tools is not installed in the shared environments and nothing was
  installed, so the lock was NOT regenerated with `make lock`. It was extended exactly the way R11
  added `segno` (commit `0e2aec7`): one block per new package in pip-compile's own format and sort
  order, with the sha256 of every distribution PyPI's JSON API lists for that version (wheel and
  sdist), and `# via` lines; lxml's block gains `jarvis (pyproject.toml)`. As a check of the method,
  the 176 hashes PyPI lists for lxml 6.1.3 are exactly the lock's. The installed versions in all
  three test environments match the pins. A later `make lock` (pip-compile keeps existing pins)
  should produce the same entries; it was not run.
- `requirements.licences.json`: three rows (`openpyxl` MIT, `et-xmlfile` MIT, `xlrd` BSD), read
  from the installed dists' metadata as `--licences` does; written with the table's own JSON
  format. The build book's `--check` reads it against the lock.
- CI: `pip install -e ".[dev,homebridge]"` on the 3.12 leg only.
- Owner decisions recorded by Part C, accepted here: the LGPL-2.1 FFmpeg inside the OpenCV wheel
  (dynamically loaded, unmodified, on the owner's laptop only, installed by pip); the two model
  files downloaded at setup and kept only with their pinned SHA-256.

## 6. Residual (for the release notes)

The main brain's REPLY TEXT on a picture turn still rests on the persona rule (`PICTURES_RULE`):
code stops a name taken from a face reaching `research_person`, `web_search`, a card or picture
research, but not the words of the answer itself. Only a live check proves it (INTEGRATION-D owner
check 3). Not guarded by the turn guard either: `youtube_search` and `maps_search` queries (no part
asked for it; a face's name is far less likely there, and it is the same hook if the reviews want
it).

## 7. Cloud Run with one instance

Verified: `deploy/cloudrun.sh` deploys with `--min-instances 0 --max-instances 1` (the hand deploy
and first set-up), and says why ("rate limiting and the per-conversation write queue are per
process"); the CI deploy (`gcloud run deploy --image … --no-traffic --tag candidate`) sets no
scaling flag, so each new revision keeps the service's maximum of one. The limit is per revision:
during a deploy the candidate (reached only by its health check on the tag URL) and the serving
revision run side by side for a few minutes.

Moot today (one process), and to fix before the limit is raised:
- the sessions' per-conversation write queue (`Brain._serialised`) and the home `NonceCache`
  (replay protection) — both named in `cloudrun.sh` already;
- every rate limiter is in process: the plan routes' 30 a minute, the helpers', the `/v1/input`
  hints and estimate limits, picture research's 4 looks a minute, `web_search`'s per-message and
  hourly caps (`WebService._recent`) and picture search's per-message presses;
- picture research's last report per conversation (in memory, 10 minutes): on another instance
  the "Look up" offer of a printed name becomes a refusal (the safe direction, but a lost offer);
- Part C's naming of a face group across instances (`PhotosService` per-owner lock; consent-safe,
  at worst one person with no pictures; INTEGRATION-C 3.4 proposes a transaction claim, R12);
- the No-AI phrasebook is per process (installed at start: no race, each instance has its own).

Already safe across instances (no change needed): A's check-in claim in `series_told`
(transaction before the alert), C's photo import (transaction claim and lease), D's GitHub
six-hour mark (transaction before the read), B's `turn_pictures` (read from the stored
conversation), approvals (`approvals/{id}`, single use).

## 8. Checks

Run from the worktree, one at a time, the heavy ones behind the builders' shared lock. The unit
suites run with `PYTHONPATH` pointing at the worktree's `src`: a few tests run an eval in a
subprocess, which otherwise imports the main checkout's `jarvis` (INTEGRATION-A 3.11); CI's plain
`pytest` has no such second checkout.

| Check | Last line |
|---|---|
| `pytest -q -p no:cacheprovider` (Python 3.12), first run | `2 failed, 13385 passed, 118 skipped`: the web eval held five ordinary guard cases (it built `web_search` unwired, so fail-closed) and an R3 seam pinned the `homebridge` extra; both fixed at their cause (the eval wires the app's port; the seam pins the new extra), the affected files then `93 passed` |
| `pytest -q -p no:cacheprovider` (Python 3.11), after the fix | `13388 passed, 117 skipped in 710.19s` |
| `ruff check src tests evals scripts` / `ruff format --check …` | `All checks passed!` / `1497 files already formatted` |
| `mypy src` | `Found 9 errors in 3 files (checked 667 source files)`: the 9 older ones only (`llm/anthropic_provider.py` 7, `core/window.py` 1, `memory/redis_store.py` 1) |
| `evals/run_all_mock.py` | `ALL MOCK EVALS: PASS` (phase0 smoke `GATE: FAIL` by design, never gated); `r11_1: 73/73 passed; negative control failed the suite: True` |
| `scripts/arch_coverage.py` | `arch coverage: OK - 56 packages/modules, 79 console modules, 2 Scheduler jobs, 30 outside services, 90 Firestore collections` |
| `scripts/check_doc_versions.py` | `All 26 documents have their version line and change log.` |
| `scripts/markdy_export.py --check` | `14 diagram(s) checked, 0 problem(s)` |
| `scripts/check_pr_title.py "v11.1.0 · R11.1 Your observations, fixed · Mark XV"` | `PR title OK` |
| `python -m jarvis.buildbook.gen --check` | `two builds are byte-identical` |
| the full browser suite (`JARVIS_BROWSER_TESTS=1 python -m pytest -q tests/browser -m browser`) | `10 failed, 1179 passed in 5007.44s (1:23:27)`: four causes, all joins, all fixed (section 3, items 6 to 9) |
| the affected browser set after the fixes (memory, attach, console, deleted, dock fit, home link, R5.1 dock and UI, UI audit, voice pace, the five R11.1 files) | `390 passed in 1329.79s (0:22:09)` |
| `pytest -q -p no:cacheprovider` (Python 3.12), final, on the head | `1 failed, 13386 passed, 118 skipped`: `test_evals_r11.py::test_the_gate_part_passes_and_its_control_fails_it` (R11's helpers eval: all 55 cases pass, one part's control did not fail its part). Re-run: it failed once more in a run of its file, then passed in 8 runs of the file, 6 runs of the test alone and 18 standalone runs of the eval. Open (section 9). |
| `scripts/ui_snapshots.py --out <a scratch folder>` | `200 shots, 0 page errors, 0 failures` |

Size guards: `core/brain.py` 704 (< 800), `api/app.py` 731 (≤ 750), `tools/gateway.py` 760 (not
grown), `console.html` 795 (< 800). Every module this release changed is ≤ 800 lines;
`vault/service.py` (876) is R2's and unchanged.

## 9. Open, or decided differently

- `series_*` not a Telegram pattern; OpenCV / NumPy not in the cloud licence table; A's persona
  sentence without a brace (all in section 2, with the reason).
- The brief's "Never" on the mail row says "Your inbox could not be read just now"; a "paused by
  your Permissions" wording needs a section state of its own (`brief/models.SectionState`):
  INTEGRATION-A 3.4 left it out of the gate, and so did I1. **Since v11.1.4: done (section 10,
  code M4).**
- `requirements.lock` hand-extended (section 5), not regenerated. **Since v11.1.4: checked with
  the Makefile's pip-compile, byte-identical but for the header (section 10, code M1).**
- The single-surname and two-word proper-name cases of the over-caution check (section 4).
  **Since v11.1.4: the guard is strict on a picture that may show a person (section 10).**
- **A flaky R11 eval control** (`evals/r11_helpers`, R11's code, unchanged by R11.1): in 2 of about
  30 runs under pytest one part's negative control did not make its part fail (every case passed);
  never in 26 standalone runs. The two single-case controls (`today`: taint check off, `house`:
  district filter off) are the likely ones; the failing report was not captured. It makes the
  suite fail, never pass wrongly. For the R11 owner (Mark XIV) or the integrated reviews.
  **Since v11.1.4: the root cause (needles over clock stamps and ids) is fixed; 30 of 30 runs
  pass (section 10, code H1).**

## 10. Integrated reviews and fixes (v11.1.4)

The two fresh-context reviews of `bbe056d` (`/tmp/r111-logs/review-i1-security.md`: 0 critical,
2 HIGH, 3 MEDIUM, 4 LOW; `/tmp/r111-logs/review-i1-code.md`: 0 critical, 1 HIGH, 4 MEDIUM, 7 LOW)
were accepted by the Workshop and fixed on this branch, each behaviour change test first (the
test seen red on the old code, then the fix).

| Finding | Fix | Test (red on the old code) | Commit |
|---|---|---|---|
| Security H2: `photos_import` (faces found, people recognised by name) open on Telegram with the home switch off | `HOME_PATTERNS` names `photos_import` beside `photos_import_*` | `test_telegram_tool_guard.py`: the linked gateway now carries every R4 family (Photos included); `…every_face_home_or_photo_tool_of_the_built_registry_waits_for_the_home_switch` reads EVERY tool of the built registry, any risk, whose name says face, home, photo or camera (only R3 D8's four stay open); the ten R4 reads, always answered on Telegram, are now classified | `492c5d2` |
| Code H1: the R11 eval flaked (substring needles over clock stamps, ids, ciphertext, log floats) | `needles.py`: a lookaround year regex and `own_case_only` against the unplanted day's findings; `today.py`: `<svg` / `data:image/svg`, the same regex over message plus extras | `test_evals_r11.py`: `.198810+00:00`, `a1988b`, ciphertext and a log record's own clock injected; the baseline case; 30 loops of the gate test: **30 of 30 passed** | `c3d0804` |
| Security H1, M2, M3; code M3: the picture turn guard (other scripts, links, `_`, a lone name beside a search word, a lower-case name beside a thing word, a name split across two queries; YouTube and Maps unguarded) | **Strict** mode whenever the picture may show a person (only his words, the picture's words and free words go out); **light** mode only when picture research of this message's only picture saw nobody (the report carries the message key); a mark-aware tokeniser; a link's parts tested on their own; no single-word escape beside a person word; the same guard on `youtube_search`, `maps_search`, `maps_route` and `research_person`'s context (runs and look-ups); one refusal sentence that says what he can do | `test_r11_1_i1_overcaution.py` (the 55 probes of both reports plus other scripts, links and `_`: 120 red on the old guard), `test_r11_1_i1_turnguard.py` (which mode, the port's key, every outward tool, Ask first, the run alone), `test_r11_1_i1_pictures.py` (real app: both tool rounds and a restart, Maps and YouTube on a recording Google; light only after research saw nobody, strict again after a restart) | `c25b9fb`, `c265976` |
| Security M1: the brief's Deliveries read Gmail on Never / Ask first | `DeliveriesBrief` goes through `BackgroundReads.allowed` and `reading` (as `gmail_track_packages`); the app hands the brief one governed path | `test_r11_1_i1_brief.py`: Never and Ask first, the clock job and Refresh: zero Gmail requests; Allow reads and leaves its audit line; the app wires both sections to the same path | `055c00a` |
| Code M4: a paused mail row said "could not be read" | `SectionState` `paused` (not retried); the brief and the console say "Paused by your Permissions: set 'Search and read email' to Allow there to see your inbox / deliveries here." | the same file; the earlier gate test and the R11.1 eval case now pin `paused` | `055c00a` |
| Code M2, security L2: a new conversation per kitchen press, left behind on 409 | one kitchen conversation per owner per local day; the one a press made is deleted when no card could be made | `test_r11_1_i1_plan.py`: approve through the Brain runs the calendar tool through the gateway with the approval's token (audited "confirmed", both events reach Google); a second press reuses the conversation and the card; Never leaves no conversation | `d18b1b8` |
| Code M1: the lock's `et-xmlfile` via block | `# via` / `jarvis (pyproject.toml)` / `openpyxl`, as pip-compile writes it (checked with pip-tools 7.6.2 in a scratch venv: byte-identical apart from the header's output path) | `test_deploy_config.py::test_every_runtime_dependency_of_pyproject_is_via_the_project_in_the_lock` | `9de523f` |
| Code L1: one full phrasebook dropped every R11.1 No-AI phrase | installed one at a time; a phrase that does not fit is `log.error`'d with its name, what is left and why | `test_r11_1_i1_plan.py` (one refused phrase keeps the rest; a nearly full book) | `5189a37` |
| Code L2, L3, L7: the doubled doc comment, the `late` timer, the literal `·` and `…` | each comment above its code; the timer cleared in `finally`; written as the escapes `\u00b7` and `\u2026` (text identical, checked with node) | browser suite only: there is no JS harness for `console-r111-files.js` (the node DOM stub is the People panel's) | `d4cd80b` |
| Code L4: `numpy==2.5.4` needs Python 3.12, `requires-python` is 3.11 | the home kit runs Python 3.12 (`bridge.Dockerfile`, `docker-compose.yml`: `python:3.12-slim`, which `setup-wsl.sh` pulls); both face engine pins carry `python_version >= "3.12"`: all four pins on the kit's Python, the MQTT pair on 3.11 | `test_deploy_home.py` (the extra still equals the bridge lock; a new test reads the kit's Python and requires-python's floor) | `df9de5f` |
| Code L5: long functions | `build_gateway`, `web_tools`, `PrivacyService.delete`, and `maps_tools` / `youtube_tools` (which this fix had grown) split under 50 lines; `tools/gateway.py` untouched (760) | the suites | `3af2900` |
| Code L6: the duck-typed `unreadable` mark | made explicit and small: `documents.pictures.pictures_unreadable` reads it through `TurnPictures` (any other list is not marked, as before) | the existing GATE C tests | `c25b9fb` |
| Security L1: the rupee estimate under a raised answer cap | above the default cap the line adds "(up to about ₹N if it writes its whole answer length)"; the cap is unchanged | `test_r11_1_b_estimate.py` (raised and default) | `475f296` |
| Security L3, L4 | residuals, below | — | — |

**The guard, measured** (the owner typed "what is this?", the picture shows nothing relevant):

| | Before (`c3d0804`) | After, strict (may show a person) | After, light (known: nobody) |
|---|---|---|---|
| Person-name queries let through (26) | 0 | 0 | 0 |
| The extended probes let through (55) | 36 | **0** | 4 (named below) |
| Ordinary queries refused (35) | 5 | **30** (they go ahead in his words or the picture's) | 5 |

The controls still fail: D's eval `turn_guard_off` and `guard_off` break exactly their own cases;
the R11.1 eval says `r11_1: 73/73 passed; negative control failed the suite: True`.

**Decided differently from the Workshop's design, and why.** The design was followed. Three of
D's assertions asked an UNTYPED thing query to go ahead on a picture that may show a person
("biryani recipe" twice, the eval's "paint for a plain wall" on a face): strict mode refuses that by
design, and no plain-code rule can tell "biryani" or "paint" from "kohli" or "lekha" without a
dictionary. They now go ahead on a picture known to show nobody, or in his own words, with the
strict refusal asserted beside them; every other D test and the D eval are unchanged and pass. The
strict list's free words add D's generic thing words and "price", "best" (each could be a surname
alone, so the light check leaves them out, but in strict mode a name needs a word that is not free).

**Residuals for the release notes.**
- A follow-up turn with no picture is unguarded by design: a name a model put in an earlier answer
  could be searched on the next turn (it would show in the card or the query he sees).
- The reply TEXT on a picture turn still rests on the persona rule (`PICTURES_RULE`); code guards the
  tools, cards and picture research, not the words of the answer.
- The name guard's known limits after this change: in strict mode it can only refuse, never name, and
  it holds 30 of 35 ordinary queries until he types the words (accepted); light mode (a picture
  researched and seen without a person, so no face to take a name from) still lets through a
  lower-case name beside a thing word ("narendra modi car", "lekha examplekar phone (number)") and
  one name beside an ordinary search word that is not a person's ("Lekha weather", "Kohli
  weather": the first half of a split); a message with two pictures, or a picture nobody
  researched, is always strict. Searches in his OWN data (`gmail_search`, `contacts_search`,
  `drive_search`, the calendar's query) are not outward searches and are not behind the guard.
- The Telegram re-plan card's first line shows the plan's own words (`series/cards.py` `replan_card`:
  the model's `series` argument) in the owner's own chat, with no button (security L3).
- The brief's inbox copy (`inbox_delivery`) is a write he switches on himself, not a read, and is not
  behind the mail row.
- The whole-tree `ruff check .` / `ruff format --check .` findings are in `.claude/` (agent tooling)
  and two integration notes' code blocks, none touched here; the project scope is clean.

**Checks on the head** (`PYTHONPATH` at the worktree's `src`, one at a time):

| Check | Last line |
|---|---|
| `pytest -q -p no:cacheprovider` (Python 3.12) | `1 failed, 13585 passed, 118 skipped, 11 warnings in 652.62s (0:10:52)`: `test_notify_hardening.py::test_every_third_party_top_level_import_in_src_is_in_pyproject` read the homebridge extra with a one-line regex that the new markers broke; fixed at its cause (`d5e2da4`, read as TOML); the file and its neighbours then `174 passed` on 3.12 and on 3.11. Re-run on the head: `13586 passed, 118 skipped, 11 warnings in 686.51s (0:11:26)` (on `d5e2da4`; the warnings are `test_real_evals_script.py`'s forkpty notes, as before) |
| `pytest -q -p no:cacheprovider` (Python 3.11) | `1 failed, 13586 passed, 117 skipped in 672.52s (0:11:12)`: the same test, the same fix. Re-run on the head: `13587 passed, 117 skipped in 670.51s (0:11:10)` (on `d5e2da4`) |
| the gate test, 30 times in a loop | `passed=30 failed=0` |
| `ruff check src tests evals scripts` / `ruff format --check src tests evals scripts` | `All checks passed!` / `1500 files already formatted` (the whole tree adds only `.claude/` tooling and two notes' code blocks, untouched here) |
| `mypy src` | `Found 9 errors in 3 files (checked 668 source files)`: the 9 older ones only |
| `evals/run_all_mock.py` | `ALL MOCK EVALS: PASS` (phase0 smoke `GATE: FAIL` by design); `r11_helpers: 55/55 passed; negative control failed the suite: True`; `r11_1: 73/73 passed; negative control failed the suite: True`; D's `look: 24 cases` with its five controls |
| `scripts/check_doc_versions.py` | `All 26 documents have their version line and change log.` |
| `scripts/arch_coverage.py` | `arch coverage: OK - 56 packages/modules, 79 console modules, 2 Scheduler jobs, 30 outside services, 90 Firestore collections` |
| `scripts/markdy_export.py --check` | `14 diagram(s) checked, 0 problem(s)` |
| `python -m jarvis.buildbook.gen --check` | `two builds are byte-identical` |
| `pip-compile` (the Makefile's command, scratch venv) | the lock byte-identical apart from the header's output path |
| the full browser suite | `1190 passed in 4905.47s (1:21:45)`, behind the shared lock: nothing failed, nothing to re-run |
| `scripts/ui_snapshots.py --out /tmp/r111-logs/i1-fix-shots` | `200 shots, 0 page errors, 0 failures`; the DOM checks (`checks.json`, 108 shots) hold exactly I1's findings: none new, none gone |

Size guards: `core/brain.py` 704, `api/app.py` 732 (pin 735), `tools/gateway.py` 760 (unchanged),
`console.html` 795; no new `innerHTML`, no non-ASCII line added to the console, no CSS or HTML
change; nothing new is asked of the server before sign-in.

## Change log

| Version | Date | Release | What changed | By |
|---|---|---|---|---|
| v11.1.1 | 12 Nov 2026, 11:20 IST | R11.1 | First edition: the five merges | 🛠 Mark XV |
| v11.1.2 | 12 Nov 2026, 12:40 IST | R11.1 | Every gate and "Needs I1" item with its test, the cross-part defects found at the join, the over-caution numbers, the dependencies and how the lock was extended, the residual, the Cloud Run instance check, what was decided differently | 🛠 Mark XV |
| v11.1.3 | 12 Nov 2026, 15:30 IST | R11.1 | The full runs: unit 3.12 and 3.11, ruff, mypy, the mock evals, the doc, guide, diagram, title and book checks, the full browser suite and the four joins it found (the chat box's hint, Photos off answering 503, the memory chip on a phone, a locator), the affected set again, the screenshots; the flaky R11 eval control | 🛠 Mark XV |
| v11.1.4 | 12 Nov 2026, 19:45 IST | R11.1 | The integrated reviews and their fixes (section 10): Telegram's home switch over the real photo import, the R11 eval's flake at its cause, the picture turn guard's strict and light modes with YouTube, Maps and a research's context behind it, the brief's deliveries behind the mail row and a paused row said so, one kitchen conversation a day, the lock's via block, the No-AI phrases one by one, the kit's Python for the face engine pins, the long functions, the estimate under a raised cap, three console joins; the measured guard, the eval loop, every check on the head, and the residuals for the release notes | 🛠 Mark XV |
