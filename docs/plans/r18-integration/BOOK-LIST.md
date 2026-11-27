Version v18.0.0 · 27 Nov 2026, 17:20 IST · Release R18 · Status: Current · Owner: 🛠 Mark XXV

# R18 "Calls from your laptop": the Build Book's list after the catalogue

Branch `r18-book`, from `r18-i1` (16fb461); the catalogue at 775927f. For the page writers: what
the Book now catalogues for R18, and every page and narration that needs writing or refreshing.
The lists below are the output of `PYTHONPATH=src python -m jarvis.buildbook.gen pages --list`,
`--check` and `--narration-check` on 775927f (their exit codes: 0, 1 and 1).

## 1. What the catalogue now has

- **Guide v18.0.1** (`docs/architecture/JARVIS-Architecture.md`): cards **C74** Calls: cards,
  approvals, limits and records; **C75** Call engine, hub and live listening; **C76** Call speech
  and the language check; **C77** Call desk on the laptop; **C78** Phone calls on the phone. I0's
  seams are on C74 (`models`, `store`, `settings`, `tools`, `ports`, `config_calls.py`,
  `api/calls_routes.py`), C75 (`protocol`) and C76 (`prices`); the join on C74
  (`api/r18_wiring.py`, `calls/chat_card.py`), C75 (`calls/join.py`) and C76
  (`calls/join_speech.py`). `scripts/arch_coverage.py`: OK (69 packages/modules, 131 console
  modules, 35 outside services, 134 Firestore collections).
- **Module** `calls` "Phone calls" (`src/jarvis/buildbook/gen/modules.py`, last of 19) → page
  `pg_module_calls`, cards' pages `pg_card_c74` … `pg_card_c78`, chapter `module_calls` (its
  narration `src/jarvis/buildbook/book/narration/module_calls.md` is the slot: not written).
- **Services** (code-driven, `scripts/arch_coverage.json`): Microsoft Azure Speech, Sarvam and
  Bhashini by their settings, Hugging Face by its host → `pg_service_microsoft_azure_speech`,
  `pg_service_sarvam`, `pg_service_bhashini`, `pg_service_hugging_face` (31 → 35 services).
- **Chapters' homes** (`src/jarvis/buildbook/book/chapters.py` `HOMES`): `pg_screen_calls` and the
  four service pages are told in `module_calls`. The tour's chapter names
  (`console-book-tour.js` `CHAPTER_NAMES`) have `pg_module_calls` (this staled `pg_screen_show`).
- **Counts**: 8 chapters, 19 modules, 78 cards, 24 screens, 35 services = 164 pages; 27 narrated
  chapters. The tour's "what else" scene lists 12 modules; its roadmap facts are now "R5.2, Voice"
  then "R8, Home cameras" (the guide's built "Phone calls" row is gone).

## 2. The lists

**164 pages: 67 ok, 85 stale, 1 failing, 11 missing.**
`--check`: 203 problems (the same pages, and the narration below).

**Missing (11):**

- modules (1): `pg_module_calls`
- cards (5): `pg_card_c74`, `pg_card_c75`, `pg_card_c76`, `pg_card_c77`, `pg_card_c78`
- screens (1): `pg_screen_calls`
- services (4): `pg_service_bhashini`, `pg_service_hugging_face`, `pg_service_microsoft_azure_speech`, `pg_service_sarvam`

**Failing (1):** `pg_chapter_planned`. Its flowchart's nodes `built` and `left` name
`docs/plans/r6-4-book-look.md`, which is no longer one of its refs: the chapter's refs are the
guide and this release's own plan (`gen/pages_index.py` `CHAPTER_SOURCES["planned"]` and
`plans.plan_paths`), now `docs/plans/r18-calls.md`. The catalogue side is right as it is, so
nothing was changed there: the page writers rewrite the page and its flow
(`src/jarvis/buildbook/book/flows/pg_chapter_planned.json`) and restamp it.

**Stale (85)**, by kind (84 were stale on `r18-i1`; `pg_screen_show` is new here, from
`console-book-tour.js`):

- chapters (7): `pg_chapter_what`, `pg_chapter_example`, `pg_chapter_data`, `pg_chapter_answers`, `pg_chapter_setup`, `pg_chapter_technology`, `pg_chapter_costs`
- modules (10): `pg_module_console`, `pg_module_brain`, `pg_module_home`, `pg_module_vitals`, `pg_module_approvals`, `pg_module_android`, `pg_module_helpers`, `pg_module_delivery`, `pg_module_book`, `pg_module_wardrobe`
- cards (19): `pg_card_c01`, `pg_card_c02`, `pg_card_c68`, `pg_card_c39`, `pg_card_c63`, `pg_card_c55`, `pg_card_c67`, `pg_card_c28`, `pg_card_c51`, `pg_card_c62`, `pg_card_c64`, `pg_card_c65`, `pg_card_c11`, `pg_card_c49`, `pg_card_c58`, `pg_card_c59`, `pg_card_c57`, `pg_card_c72`, `pg_card_c73`
- screens (23): `pg_screen_chat`, `pg_screen_brief`, `pg_screen_approvals`, `pg_screen_activity`, `pg_screen_history`, `pg_screen_memory`, `pg_screen_vault`, `pg_screen_things`, `pg_screen_notes`, `pg_screen_privacy`, `pg_screen_home`, `pg_screen_faces`, `pg_screen_voice`, `pg_screen_integrations`, `pg_screen_media`, `pg_screen_vitals`, `pg_screen_connectors`, `pg_screen_people`, `pg_screen_book`, `pg_screen_construct`, `pg_screen_helpers`, `pg_screen_camera`, `pg_screen_show`
- services (26): `pg_service_anthropic`, `pg_service_cloud_run`, `pg_service_cloud_scheduler`, `pg_service_firestore`, `pg_service_frankfurter`, `pg_service_frigate`, `pg_service_gemini`, `pg_service_gmail`, `pg_service_google_calendar`, `pg_service_google_cloud_speech_to_text`, `pg_service_google_cloud_text_to_speech`, `pg_service_google_drive`, `pg_service_google_maps_platform`, `pg_service_google_photos_picker`, `pg_service_google_tasks`, `pg_service_google_sign_in`, `pg_service_home_assistant`, `pg_service_mosquitto`, `pg_service_ollama`, `pg_service_openai_compatible`, `pg_service_redis`, `pg_service_tailscale`, `pg_service_tavily`, `pg_service_telegram`, `pg_service_web_push`, `pg_service_youtube_data_api`

**Narrations** (`--narration-check`): 27 narrations: 26 ok, 0 stale, 0 failing, **1 missing:
`module_calls`**.

## 3. Things in the code that look wrong (not changed here)

1. `tests/test_r63_a_facts_real.py::test_m9_the_route_list_is_the_app_s` fails on `r18-i1` and
   here: the Book's route reader (`src/jarvis/buildbook/gen/facts_routes.py`, `loop_envs`) skips
   the `**CALLS_ASSETS` spread in `src/jarvis/api/console.py`'s `APP_ASSETS`, so the fact pack
   lacks the `/static/` routes of the 11 `console-calls*.js` modules, `console-calls.css` and
   `calls-listen-worklet.js`. Generator code: left for the review.
2. The Privacy panel has no calls row: `src/jarvis/privacy/` names none of `calls`,
   `call_settings`, `call_desk`, `call_lang_check`. A call is deleted only in Calls → Calls or by
   the 30-day retention job; there is no export. (C74 says so.)
3. Docstrings that say `/api/calls/...` where the routes are `/v1/calls/...`:
   `src/jarvis/calls/live.py`, `src/jarvis/calls/langcheck/api.py`, and the header comments of
   `console-calls-live.js` and `console-calls-vitals.js`.
4. `src/jarvis/calls/records.py`'s docstring says the audio is "Opus or compressed 16 kHz mono
   (D8)"; the join keeps 8 kHz WAV (`calls/join.py` `RECORD_RATE`; I1-NOTES 4.4).
5. `src/jarvis/phone/calls.py`'s docstring says the command key comes from the keyring "or, until
   that purpose exists", `CommandSigner.ephemeral()`; the joined phone part always uses the
   ephemeral key (I1-NOTES 2.7).
6. `call_lines` and `call_line_audio` (`calls/speech/lines.py`, B's `LinesCache`) are in the code
   but nothing in the joined app writes them (I1-NOTES 4.3).
7. The guide's roadmap row "Later" still says "R15–R18 subscription releases", though R18 is now
   "Calls from your laptop": the owner's release plan decides; left as it is.
8. Fixed here, catalogue side: `src/jarvis/buildbook/gen/services.py` read only `class Settings`'
   own fields, so R18's secret settings in `config_calls.py` (`azure_speech_key`,
   `sarvam_api_key`, `bhashini_api_key`) escaped the coverage checker's "unknown secret setting"
   rule; it now follows the `jarvis` base class as `gen/code.py` already did (commit 08487f8,
   red first).

## 4. Checks run

- `scripts/arch_coverage.py`: OK. `scripts/check_doc_versions.py`: OK.
- `tests/test_arch_coverage.py` passes (with the Book's suites: every `test_r63*`, `test_r64*`,
  `test_r631*`, `test_book*`, `test_r6_*`, `test_r62*`, `test_r61*`, `test_arch*`: 2,028 passed,
  1 failed, the m9 test of section 3, item 1).
- The guide's and seams' readers (`test_check_doc_versions`, `test_claude_guard`, the R7, R11,
  R11.1, R13, R13.1, R14 seams and docs tests, every `test_r18_i0*` and `test_r18_i1*`): 3,009
  passed.
- `ruff check` and `ruff format --check` on every Python file changed: clean.

## Appendix: `pages --check`, every problem line

```
pg_chapter_what: stale: `src/jarvis/__init__.py` changed since the page was stamped
pg_chapter_what: stale: `src/jarvis/api/console.py` changed since the page was stamped
pg_chapter_what: stale: `src/jarvis/api/static/console-book-tour.js` changed since the page was stamped
pg_chapter_what: stale: `src/jarvis/api/static/console-deck.js` changed since the page was stamped
pg_chapter_what: stale: `src/jarvis/api/static/console-dock.js` changed since the page was stamped
pg_chapter_what: stale: `src/jarvis/api/static/console.html` changed since the page was stamped
pg_chapter_what: stale: `src/jarvis/api/static/console.js` changed since the page was stamped
pg_chapter_what: stale: `src/jarvis/buildbook/gen/facts_code.py` changed since the page was stamped
pg_chapter_what: stale: `src/jarvis/buildbook/gen/modules.py` changed since the page was stamped
pg_chapter_what: stale: `src/jarvis/buildbook/gen/services.py` changed since the page was stamped
pg_chapter_example: stale: `src/jarvis/tools/reply_cards.py` changed since the page was stamped
pg_chapter_example: stale: `src/jarvis/tools/setup.py` changed since the page was stamped
pg_chapter_data: stale: `deploy/cloudrun.sh` changed since the page was stamped
pg_chapter_data: stale: `src/jarvis/config.py` changed since the page was stamped
pg_chapter_data: stale: `src/jarvis/keyring.py` changed since the page was stamped
pg_chapter_answers: stale: `src/jarvis/skills/catalogue.json` changed since the page was stamped
pg_chapter_setup: stale: `pyproject.toml` changed since the page was stamped
pg_chapter_setup: stale: `src/jarvis/api/app.py` changed since the page was stamped
pg_chapter_setup: stale: `src/jarvis/api/console.py` changed since the page was stamped
pg_chapter_setup: stale: `src/jarvis/api/static/console-deck.js` changed since the page was stamped
pg_chapter_setup: stale: `src/jarvis/api/static/console-dock.js` changed since the page was stamped
pg_chapter_setup: stale: `src/jarvis/api/static/console.html` changed since the page was stamped
pg_chapter_setup: stale: `src/jarvis/api/static/console.js` changed since the page was stamped
pg_chapter_setup: stale: `src/jarvis/config.py` changed since the page was stamped
pg_chapter_technology: stale: `Dockerfile` changed since the page was stamped
pg_chapter_technology: stale: `deploy/cloudrun.sh` changed since the page was stamped
pg_chapter_technology: stale: `pyproject.toml` changed since the page was stamped
pg_chapter_technology: stale: `requirements.lock` changed since the page was stamped
pg_chapter_costs: stale: `src/jarvis/__init__.py` changed since the page was stamped
pg_chapter_planned: flow: node built: `docs/plans/r6-4-book-look.md` is not one of the page's refs
pg_chapter_planned: flow: node left: `docs/plans/r6-4-book-look.md` is not one of the page's refs
pg_chapter_planned: stale: `docs/architecture/JARVIS-Architecture.md` changed since the page was stamped
pg_chapter_planned: stale: `docs/plans/r18-calls.md` is new to this page
pg_chapter_planned: stale: `docs/plans/r6-4-book-look.md` is no longer one of the page's refs
pg_module_console: stale: `src/jarvis/api/app.py` changed since the page was stamped
pg_module_console: stale: `src/jarvis/api/console.py` changed since the page was stamped
pg_module_console: stale: `src/jarvis/api/static/console-deck.js` changed since the page was stamped
pg_module_console: stale: `src/jarvis/api/static/console-dock.js` changed since the page was stamped
pg_module_console: stale: `src/jarvis/api/static/console.html` changed since the page was stamped
pg_module_console: stale: `src/jarvis/api/static/console.js` changed since the page was stamped
pg_module_brain: stale: `src/jarvis/skills/catalogue.json` changed since the page was stamped
pg_module_home: stale: `src/jarvis/api/console.py` changed since the page was stamped
pg_module_vitals: stale: `src/jarvis/__init__.py` changed since the page was stamped
pg_module_vitals: stale: `src/jarvis/api/tick_wiring.py` changed since the page was stamped
pg_module_approvals: stale: `src/jarvis/keyring.py` changed since the page was stamped
pg_module_approvals: stale: `src/jarvis/tools/reply_cards.py` changed since the page was stamped
pg_module_approvals: stale: `src/jarvis/tools/setup.py` changed since the page was stamped
pg_module_android: stale: `.github/workflows/android.yml` changed since the page was stamped
pg_module_android: stale: `scripts/apk_check.py` changed since the page was stamped
pg_module_android: stale: `src/jarvis/api/r7_wiring.py` changed since the page was stamped
pg_module_android: stale: `src/jarvis/api/static/console-r7-links.js` changed since the page was stamped
pg_module_android: stale: `src/jarvis/api/static/console-r7.js` changed since the page was stamped
pg_module_android: stale: `src/jarvis/mobile/contract.py` changed since the page was stamped
pg_module_android: stale: `src/jarvis/mobile/ports.py` changed since the page was stamped
pg_module_android: stale: `src/jarvis/phone/part.py` changed since the page was stamped
pg_module_helpers: stale: `deploy/cloudrun.sh` changed since the page was stamped
pg_module_delivery: stale: `Dockerfile` changed since the page was stamped
pg_module_delivery: stale: `deploy/cloudrun.sh` changed since the page was stamped
pg_module_delivery: stale: `evals/run_all_mock.py` changed since the page was stamped
pg_module_delivery: stale: `requirements.lock` changed since the page was stamped
pg_module_delivery: stale: `src/jarvis/config.py` changed since the page was stamped
pg_module_book: stale: `src/jarvis/api/static/console-book-tour.js` changed since the page was stamped
pg_module_book: stale: `src/jarvis/buildbook/gen/facts_code.py` changed since the page was stamped
pg_module_book: stale: `src/jarvis/buildbook/gen/modules.py` changed since the page was stamped
pg_module_book: stale: `src/jarvis/buildbook/gen/services.py` changed since the page was stamped
pg_module_wardrobe: stale: `deploy/cloudrun.sh` changed since the page was stamped
pg_module_wardrobe: stale: `src/jarvis/api/static/console-r7.js` changed since the page was stamped
pg_module_wardrobe: stale: `src/jarvis/tools/reply_cards.py` changed since the page was stamped
pg_module_calls: missing
pg_card_c01: stale: `src/jarvis/api/console.py` changed since the page was stamped
pg_card_c01: stale: `src/jarvis/api/static/console-deck.js` changed since the page was stamped
pg_card_c01: stale: `src/jarvis/api/static/console-dock.js` changed since the page was stamped
pg_card_c01: stale: `src/jarvis/api/static/console.html` changed since the page was stamped
pg_card_c01: stale: `src/jarvis/api/static/console.js` changed since the page was stamped
pg_card_c02: stale: `src/jarvis/api/app.py` changed since the page was stamped
pg_card_c02: stale: `src/jarvis/api/calldesk_kit.py` is new to this page
pg_card_c02: stale: `src/jarvis/api/calls_console.py` is new to this page
pg_card_c02: stale: `src/jarvis/api/calls_handlers_cards.py` is new to this page
pg_card_c02: stale: `src/jarvis/api/calls_routes.py` is new to this page
pg_card_c02: stale: `src/jarvis/api/calls_ws.py` is new to this page
pg_card_c02: stale: `src/jarvis/api/console.py` changed since the page was stamped
pg_card_c02: stale: `src/jarvis/api/console_calls_assets.py` is new to this page
pg_card_c02: stale: `src/jarvis/api/r18_wiring.py` is new to this page
pg_card_c02: stale: `src/jarvis/api/r7_wiring.py` changed since the page was stamped
pg_card_c02: stale: and 21 more refs
pg_card_c68: stale: `src/jarvis/skills/catalogue.json` changed since the page was stamped
pg_card_c39: stale: `deploy/home/start-home.ps1` changed since the page was stamped
pg_card_c63: stale: `src/jarvis/api/console.py` changed since the page was stamped
pg_card_c55: stale: `src/jarvis/__init__.py` changed since the page was stamped
pg_card_c67: stale: `src/jarvis/api/tick_wiring.py` changed since the page was stamped
pg_card_c28: stale: `src/jarvis/tools/reply_cards.py` changed since the page was stamped
pg_card_c28: stale: `src/jarvis/tools/setup.py` changed since the page was stamped
pg_card_c51: stale: `src/jarvis/keyring.py` changed since the page was stamped
pg_card_c62: stale: `.github/workflows/android.yml` changed since the page was stamped
pg_card_c62: stale: `android/app/src/main/AndroidManifest.xml` changed since the page was stamped
pg_card_c62: stale: `android/app/src/main/java/io/github/[removed]/jarvis/calls/CallActions.kt` is new to this page
pg_card_c62: stale: `android/app/src/main/java/io/github/[removed]/jarvis/calls/CallDecisionReceiver.kt` is new to this page
pg_card_c62: stale: `android/app/src/main/java/io/github/[removed]/jarvis/calls/CallNotices.kt` is new to this page
pg_card_c62: stale: `android/app/src/main/java/io/github/[removed]/jarvis/calls/CallStateReceiver.kt` is new to this page
pg_card_c62: stale: `android/app/src/main/java/io/github/[removed]/jarvis/calls/CallTapActivity.kt` is new to this page
pg_card_c62: stale: `android/app/src/main/java/io/github/[removed]/jarvis/calls/CallsAccess.kt` is new to this page
pg_card_c62: stale: `android/app/src/main/java/io/github/[removed]/jarvis/calls/CallsLauncherActivity.kt` is new to this page
pg_card_c62: stale: `android/app/src/main/java/io/github/[removed]/jarvis/calls/CallsLink.kt` is new to this page
pg_card_c62: stale: and 25 more refs
pg_card_c64: stale: `src/jarvis/api/r7_wiring.py` changed since the page was stamped
pg_card_c65: stale: `android/app/src/main/AndroidManifest.xml` changed since the page was stamped
pg_card_c65: stale: `android/app/src/main/java/io/github/[removed]/jarvis/calls/CallActions.kt` is new to this page
pg_card_c65: stale: `android/app/src/main/java/io/github/[removed]/jarvis/calls/CallDecisionReceiver.kt` is new to this page
pg_card_c65: stale: `android/app/src/main/java/io/github/[removed]/jarvis/calls/CallNotices.kt` is new to this page
pg_card_c65: stale: `android/app/src/main/java/io/github/[removed]/jarvis/calls/CallStateReceiver.kt` is new to this page
pg_card_c65: stale: `android/app/src/main/java/io/github/[removed]/jarvis/calls/CallTapActivity.kt` is new to this page
pg_card_c65: stale: `android/app/src/main/java/io/github/[removed]/jarvis/calls/CallsAccess.kt` is new to this page
pg_card_c65: stale: `android/app/src/main/java/io/github/[removed]/jarvis/calls/CallsLauncherActivity.kt` is new to this page
pg_card_c65: stale: `android/app/src/main/java/io/github/[removed]/jarvis/calls/CallsLink.kt` is new to this page
pg_card_c65: stale: `android/app/src/main/java/io/github/[removed]/jarvis/calls/CallsSetupActivity.kt` is new to this page
pg_card_c65: stale: and 15 more refs
pg_card_c11: stale: `deploy/cloudrun.sh` changed since the page was stamped
pg_card_c49: stale: `src/jarvis/config.py` changed since the page was stamped
pg_card_c58: stale: `Dockerfile` changed since the page was stamped
pg_card_c58: stale: `deploy/cloudrun.sh` changed since the page was stamped
pg_card_c58: stale: `requirements.lock` changed since the page was stamped
pg_card_c59: stale: `evals/run_all_mock.py` changed since the page was stamped
pg_card_c57: stale: `src/jarvis/api/static/console-book-tour.js` changed since the page was stamped
pg_card_c57: stale: `src/jarvis/buildbook/gen/code.py` changed since the page was stamped
pg_card_c57: stale: `src/jarvis/buildbook/gen/facts_code.py` changed since the page was stamped
pg_card_c57: stale: `src/jarvis/buildbook/gen/layers.py` changed since the page was stamped
pg_card_c57: stale: `src/jarvis/buildbook/gen/modules.py` changed since the page was stamped
pg_card_c57: stale: `src/jarvis/buildbook/gen/services.py` changed since the page was stamped
pg_card_c72: stale: `src/jarvis/api/static/console-r7.js` changed since the page was stamped
pg_card_c72: stale: `src/jarvis/tools/reply_cards.py` changed since the page was stamped
pg_card_c73: stale: `deploy/cloudrun.sh` changed since the page was stamped
pg_card_c74: missing
pg_card_c75: missing
pg_card_c76: missing
pg_card_c77: missing
pg_card_c78: missing
pg_screen_chat: stale: `src/jarvis/api/static/console.html` changed since the page was stamped
pg_screen_brief: stale: `src/jarvis/api/static/console.html` changed since the page was stamped
pg_screen_approvals: stale: `src/jarvis/api/static/console.html` changed since the page was stamped
pg_screen_activity: stale: `src/jarvis/api/static/console.html` changed since the page was stamped
pg_screen_history: stale: `src/jarvis/api/static/console.html` changed since the page was stamped
pg_screen_memory: stale: `src/jarvis/api/static/console.html` changed since the page was stamped
pg_screen_vault: stale: `src/jarvis/api/static/console.html` changed since the page was stamped
pg_screen_things: stale: `src/jarvis/api/static/console.html` changed since the page was stamped
pg_screen_notes: stale: `src/jarvis/api/static/console.html` changed since the page was stamped
pg_screen_privacy: stale: `src/jarvis/api/static/console.html` changed since the page was stamped
pg_screen_home: stale: `src/jarvis/api/static/console.html` changed since the page was stamped
pg_screen_faces: stale: `src/jarvis/api/static/console.html` changed since the page was stamped
pg_screen_voice: stale: `src/jarvis/api/static/console.html` changed since the page was stamped
pg_screen_integrations: stale: `src/jarvis/api/static/console.html` changed since the page was stamped
pg_screen_media: stale: `src/jarvis/api/static/console.html` changed since the page was stamped
pg_screen_vitals: stale: `src/jarvis/api/static/console.html` changed since the page was stamped
pg_screen_connectors: stale: `src/jarvis/api/static/console.html` changed since the page was stamped
pg_screen_people: stale: `src/jarvis/api/static/console.html` changed since the page was stamped
pg_screen_book: stale: `src/jarvis/api/static/console-book-tour.js` changed since the page was stamped
pg_screen_book: stale: `src/jarvis/api/static/console.html` changed since the page was stamped
pg_screen_construct: stale: `src/jarvis/api/static/console.html` changed since the page was stamped
pg_screen_helpers: stale: `src/jarvis/api/static/console.html` changed since the page was stamped
pg_screen_camera: stale: `src/jarvis/api/static/console.html` changed since the page was stamped
pg_screen_calls: missing
pg_screen_show: stale: `src/jarvis/api/static/console-book-tour.js` changed since the page was stamped
pg_service_anthropic: stale: `src/jarvis/config.py` changed since the page was stamped
pg_service_bhashini: missing
pg_service_cloud_run: stale: `src/jarvis/api/app.py` changed since the page was stamped
pg_service_cloud_run: stale: `src/jarvis/api/calldesk_kit.py` is new to this page
pg_service_cloud_run: stale: `src/jarvis/api/calls_routes.py` is new to this page
pg_service_cloud_run: stale: `src/jarvis/config.py` changed since the page was stamped
pg_service_cloud_scheduler: stale: `src/jarvis/api/app.py` changed since the page was stamped
pg_service_cloud_scheduler: stale: `src/jarvis/config.py` changed since the page was stamped
pg_service_firestore: stale: `src/jarvis/api/app.py` changed since the page was stamped
pg_service_firestore: stale: `src/jarvis/api/r18_wiring.py` is new to this page
pg_service_firestore: stale: `src/jarvis/config.py` changed since the page was stamped
pg_service_firestore: stale: `src/jarvis/mobile/ports.py` changed since the page was stamped
pg_service_frankfurter: stale: `src/jarvis/config.py` changed since the page was stamped
pg_service_frigate: stale: `src/jarvis/config.py` changed since the page was stamped
pg_service_gemini: stale: `src/jarvis/config.py` changed since the page was stamped
pg_service_gmail: stale: `src/jarvis/config.py` changed since the page was stamped
pg_service_google_calendar: stale: `src/jarvis/config.py` changed since the page was stamped
pg_service_google_cloud_speech_to_text: stale: `src/jarvis/calls/speech/build.py` is new to this page
pg_service_google_cloud_speech_to_text: stale: `src/jarvis/config.py` changed since the page was stamped
pg_service_google_cloud_text_to_speech: stale: `src/jarvis/calls/speech/build.py` is new to this page
pg_service_google_cloud_text_to_speech: stale: `src/jarvis/config.py` changed since the page was stamped
pg_service_google_drive: stale: `src/jarvis/api/app.py` changed since the page was stamped
pg_service_google_drive: stale: `src/jarvis/config.py` changed since the page was stamped
pg_service_google_drive: stale: `src/jarvis/tools/setup.py` changed since the page was stamped
pg_service_google_maps_platform: stale: `src/jarvis/config.py` changed since the page was stamped
pg_service_google_photos_picker: stale: `src/jarvis/config.py` changed since the page was stamped
pg_service_google_tasks: stale: `src/jarvis/config.py` changed since the page was stamped
pg_service_google_sign_in: stale: `src/jarvis/config.py` changed since the page was stamped
pg_service_home_assistant: stale: `src/jarvis/config.py` changed since the page was stamped
pg_service_hugging_face: missing
pg_service_microsoft_azure_speech: missing
pg_service_mosquitto: stale: `src/jarvis/config.py` changed since the page was stamped
pg_service_ollama: stale: `src/jarvis/config.py` changed since the page was stamped
pg_service_openai_compatible: stale: `src/jarvis/config.py` changed since the page was stamped
pg_service_redis: stale: `src/jarvis/config.py` changed since the page was stamped
pg_service_sarvam: missing
pg_service_tailscale: stale: `src/jarvis/config.py` changed since the page was stamped
pg_service_tavily: stale: `src/jarvis/config.py` changed since the page was stamped
pg_service_telegram: stale: `src/jarvis/config.py` changed since the page was stamped
pg_service_web_push: stale: `src/jarvis/config.py` changed since the page was stamped
pg_service_youtube_data_api: stale: `src/jarvis/config.py` changed since the page was stamped
module_calls: missing
```

## Change log

| Version | Date | Release | What changed | By |
|---|---|---|---|---|
| v18.0.0 | 27 Nov 2026, 17:20 IST | R18 | First edition: the catalogue for R18 (cards C74–C78, the Phone calls module, four services, the chapters' homes), the full lists of missing, failing and stale pages and the missing narration, what looks wrong in the code, the checks run | 🛠 Mark XXV |
