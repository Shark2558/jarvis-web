Version v5.2.0 · 27 Nov 2026, 19:00 IST · Release R5.2 · Status: Current · Owner: 🛠 Mark XXV

# R5.2 "Your voice": the Build Book's list after the catalogue

Branch `r5-2-book`, from `r5-2-i1` (8c2ea75) with R18's Book work merged (`r18-book`, first at
46436e0, then again at 795091c); the guide at db7650b, the catalogue at b53bdba. For the page
writers: what the Book now catalogues for R5.2, and every page and narration that needs writing or
refreshing. The lists below are the output of `PYTHONPATH=src python -m jarvis.buildbook.gen pages
--list`, `--check` and `--narration-check` on db7650b (exit codes 0, 1 and 1), compared with the
same three commands on `r18-book` at 795091c (exit codes 0, 0 and 0).

## 1. What the catalogue now has

- **Guide v5.2.1** (`docs/architecture/JARVIS-Architecture.md`): cards **C79** Laptop speech kit
  (`src/jarvis/localspeech/`, the kit's side, and `deploy/local-speech/`); **C80** The kit's link
  and engine routing (`localspeech/client.py`, `localspeech/desk.py`, `voice/laptop.py`,
  `voice/routing.py`, `voice/calls_bridge.py`, `config_voice.py`, `api/r52_wiring.py`,
  `calldesk/config.py`, Vitals' `own.py` and `words.py`); **C81** Your voice: profile and voice
  session (`voice/profile*.py`, `voice/session*.py`, `api/voice_profile_routes.py`,
  `console-voice-session.js` and `.css`); **C82** Your own wake word (`localspeech/wakeword/`,
  `localspeech/wakejoin.py`, `voice/wakeword_api.py`, `console-wakeword-own.js`,
  `evals/wakeword/run.py`); **C83** Speaker check (`console-voiceprint.js`,
  `console-voiceprint-math.js`, `console-voiceprint-panel.js`, `api/speaker_assets.py`, the empty
  `static/vendor/speaker/spk-1/MANIFEST.json`). C05, C06, C76 and C77 now say what R5.2 changed in
  them; the collections `voice_profile` and `voice_session` are in C81 and 6.2. The kit's settings
  (`local_speech_*`) name Tailscale in `scripts/arch_coverage.json`. `scripts/arch_coverage.py`: OK
  (71 packages/modules, 136 console modules, 2 Scheduler jobs, 35 outside services, 136 Firestore
  collections). The guide's roadmap row "R5.2 Voice" is gone (built).
- **Module**: R5.2 **extends `voice` "Voice"** (`src/jarvis/buildbook/gen/modules.py`: C05, C06,
  C79–C83), as R13.1's Try-on extended Wardrobe, and because a laptop part sits with its domain
  (C17 the offline brain in `brain`, C39 the home bridge in `home`, C77 the call desk in `calls`).
  So no new module page and no new chapter: the cards' pages are `pg_card_c79` … `pg_card_c83`,
  told in the chapter `module_voice` (its narration `narration/module_voice.md` is the slot to
  retell; it now fails, section 3). The tour's highlights and `CHAPTER_NAMES` are unchanged.
- **Screens**: none new. The voice session and the speaker check are sections of the Voice panel,
  and `pg_screen_voice` already reads `console-voice*.js` (so `console-voice-session.js` and the
  three `console-voiceprint*.js`) and the `/v1/voice/profile` routes; `console-wakeword-own.js` is
  C82's. So `book/chapters.py` `HOMES` is unchanged.
- **Services**: none new (the kit is the owner's own laptop). C79 names Tailscale and Hugging Face
  (the Whisper downloads), both already service pages.
- **Counts**: 8 chapters, 19 modules, 83 cards, 24 screens, 35 services = 169 pages; 27 narrated
  chapters. The tour's roadmap facts are now "R8, Home cameras" then "R8.1" (that row has no title
  in the guide).

## 2. The lists

**169 pages: 78 ok, 85 stale, 1 failing, 5 missing.** `--check`: 209 problems (the pages below and
the narration of section 3).

### 2.1 R18's (stale on `r18-book` too)

**None.** On `r18-book` at 795091c every page and narration passes: 164 pages ok, 27 narrations ok,
0 problems. Every item below comes from R5.2 (its code since `r18-i1`, or this catalogue).

### 2.2 R5.2's own

**Missing (5):** `pg_card_c79`, `pg_card_c80`, `pg_card_c81`, `pg_card_c82`, `pg_card_c83`: the new cards' pages (C79–C83).

**Failing (1):** `pg_chapter_planned`. Its flowchart's nodes `built` and `left` name
`docs/plans/r18-calls.md`, which is no longer one of its refs: the chapter's refs are the guide and
this release's own plan (`gen/pages_index.py` `CHAPTER_SOURCES["planned"]` and `plans.plan_paths`),
now `docs/plans/r5-2-voice.md`. Its text also still names R5.2 as next ("R5.2, the voice build
..."): R5.2 is built and the guide's roadmap now starts at R8. Rewrite the page and its flow
(`src/jarvis/buildbook/book/flows/pg_chapter_planned.json`), then restamp.

**Stale (85)**, by kind, with what changed:

- chapters (6): `pg_chapter_what`, `pg_chapter_example`, `pg_chapter_data`, `pg_chapter_setup`, `pg_chapter_technology`, `pg_chapter_costs`
- modules (10): `pg_module_console`, `pg_module_voice`, `pg_module_home`, `pg_module_vitals`, `pg_module_android`, `pg_module_helpers`, `pg_module_delivery`, `pg_module_book`, `pg_module_wardrobe`, `pg_module_calls`. `pg_module_voice` gains 99 refs (the five cards'
  files); `pg_module_book` is stale only because of this catalogue (`gen/modules.py`).
- cards (17): `pg_card_c01`, `pg_card_c02`, `pg_card_c05`, `pg_card_c06`, `pg_card_c63`, `pg_card_c55`, `pg_card_c56`, `pg_card_c62`, `pg_card_c11`, `pg_card_c49`, `pg_card_c58`, `pg_card_c59`, `pg_card_c57`, `pg_card_c72`, `pg_card_c73`, `pg_card_c74`, `pg_card_c77`. `pg_card_c77` and `pg_module_calls` still say laptop speech
  is "a hook only, shipped off": since R5.2 the desk's hook reaches the kit (C77, C80), though with
  kit 1.0.0 every call still uses cloud speech. `pg_card_c05` gains 16 refs (`src/jarvis/voice/` is
  its folder).
- screens (23): `pg_screen_chat`, `pg_screen_brief`, `pg_screen_approvals`, `pg_screen_activity`, `pg_screen_history`, `pg_screen_memory`, `pg_screen_vault`, `pg_screen_things`, `pg_screen_notes`, `pg_screen_privacy`, `pg_screen_home`, `pg_screen_faces`, `pg_screen_voice`, `pg_screen_integrations`, `pg_screen_media`, `pg_screen_vitals`, `pg_screen_connectors`, `pg_screen_people`, `pg_screen_book`, `pg_screen_construct`, `pg_screen_helpers`, `pg_screen_camera`, `pg_screen_calls`. Every screen cites `console.html` (V4's and V5's script
  tags); `pg_screen_voice` also gains the voice session, the speaker check and the profile routes.
- services (29): `pg_service_anthropic`, `pg_service_bhashini`, `pg_service_cloud_run`, `pg_service_cloud_scheduler`, `pg_service_firestore`, `pg_service_frankfurter`, `pg_service_frigate`, `pg_service_gemini`, `pg_service_gmail`, `pg_service_google_calendar`, `pg_service_google_cloud_speech_to_text`, `pg_service_google_cloud_text_to_speech`, `pg_service_google_drive`, `pg_service_google_maps_platform`, `pg_service_google_photos_picker`, `pg_service_google_tasks`, `pg_service_google_sign_in`, `pg_service_home_assistant`, `pg_service_microsoft_azure_speech`, `pg_service_mosquitto`, `pg_service_ollama`, `pg_service_openai_compatible`, `pg_service_redis`, `pg_service_sarvam`, `pg_service_tailscale`, `pg_service_tavily`, `pg_service_telegram`, `pg_service_web_push`, `pg_service_youtube_data_api`. 28 cite `config.py` (its new base class
  `LocalSpeechConfig`); `pg_service_tailscale` gains `config_voice.py`, `voice/laptop.py` and
  `voice/session_api.py` (the kit's settings name Tailscale).

What changed, by file (pages that cite it): `config.py` 33, `console.html` 27, `deploy/cloudrun.sh`
8 (the kit's address and the twelfth secret), `console-r7.js` 7, `selfcheck_wiring.py` 7,
`api/console.py` 7, `api/app.py` 7, `voice/service.py` 5, `console-voice-barge.js` 5,
`r18_wiring.py` 5, `personal.py` 5, `vitals/own.py` 4, `src/jarvis/__init__.py` 4 (v5.2.0), and the
calls desk's `config.py`, `app.py`, `kit.py`, its README, requirements and installer (2 each).

**Not flagged, but worth a look** (their refs did not change, so `--check` passes):
`pg_service_hugging_face` (C79 now names Hugging Face for the kit's Whisper downloads; the page
speaks of FLEURS only), `pg_card_c53` and `pg_module_privacy` (the three new privacy rows: "Your
voice profile", "Voice session recordings", "Wake-word files from your voice"), `pg_card_c76` (its
laptop option is now registered, C76).

## 3. Narrations

`--narration-check`: **27 narrations: 26 ok, 0 stale, 1 failing, 0 missing; 16 problems**, all
`module_voice` (R5.2's own; on `r18-book` it passes): it tells the chapter's pages out of order now
that `pg_card_c79` … `pg_card_c83` come after `pg_card_c06` (lines 84, 99 and 115), so
`pg_screen_voice` and the two Google speech service pages have no line; the five new card pages have
no written page and no line. Retell it after the five cards are written and stamped, then
`pages --narration-stamp module_voice`. The other narrations will turn stale as their pages are
rewritten.

## 4. Things in the code that look wrong (not changed here)

1. `tests/test_r63_a_facts_real.py::test_m9_the_route_list_is_the_app_s` still fails here, exactly
   as on `r18-i1` (R18's BOOK-LIST 3.1): the route reader (`gen/facts_routes.py`) skips the
   `**CALLS_ASSETS` spread in `api/console.py`'s `APP_ASSETS` (the 11 `console-calls*.js`,
   `console-calls.css`, `calls-listen-worklet.js`). R18's; R5.2 adds no missing route.
2. `localspeech/selftest.py`: with kit 1.0.0 (no voice slot) the round trip reports "needs an
   English voice and listening engine", so the plan's laptop-kit evals (first audio ≤ 0.7 s,
   listening ×3 real time) are never measured; listening alone is not timed. (C79 says so.)
3. `deploy/local-speech/README.md` says the kit "(later) trains your own Hey Jarvis": stage 1 is
   built and trains now (stage 2 waits for a pinned voice).
4. `voice/profile.py` `SPOKEN_BY_HEADER`: defined and documented, but nothing sends or reads it yet
   (the "Spoken by the owner" label is not built, I1-NOTES 4.7).
5. `api/voice_profile_routes.py`'s docstring still reads "the router skeleton (I0)" and "Not wired
   yet: 501"; I1 wired it (501 is now only the fallback when a part fails to build).
6. `vitals/words.py` `VOICE_ENGINES` and `protocol.DEFAULT_ENGLISH_VOICE` (`bm_george`) name
   Kokoro and Piper, which kit 1.0.0 leaves out (harmless, never shown today).
7. `gen/pages_index.py`'s docstring still counts "8 + 18 + 73 + 23 + 31 = 153 pages" (now 169);
   left as it is so its pages don't turn stale for a comment.
8. I1-NOTES' known limits stand: the speaker check's model slot is empty (`MANIFEST.json`), its
   threshold 0.45 uncalibrated; openWakeWord's feature models are CC BY-NC-SA (a launch blocker for
   stage 2); the kit has no voice and no Indian-language engine.

## 5. Checks run

- `scripts/arch_coverage.py`: OK. `scripts/check_doc_versions.py`: OK.
- `tests/test_arch_coverage.py` passes. On db7650b, with the Book's suites (every `test_r63*`,
  `test_r64*`, `test_r631*`, `test_book*`, `test_r6_*`, `test_r62*`, `test_r61*`, `test_arch*`)
  and every other test that reads the guide (the R7, R11, R11.1, R13, R13.1 and R14 seams and docs
  tests, `test_check_doc_versions`): **2,950 passed, 5 skipped**, the m9 test of section 4, item 1,
  deselected. Before the module map moved, the guide's readers gave 1,042 passed and 1 failed (the
  module map's own pin, red first, then green with `gen/modules.py`).
- `ruff check` and `ruff format --check` on every Python file changed: clean.

## Appendix: `pages --check`, every problem line

```
pg_chapter_what: stale: `src/jarvis/__init__.py` changed since the page was stamped
pg_chapter_what: stale: `src/jarvis/api/console.py` changed since the page was stamped
pg_chapter_what: stale: `src/jarvis/api/static/console.html` changed since the page was stamped
pg_chapter_what: stale: `src/jarvis/buildbook/gen/modules.py` changed since the page was stamped
pg_chapter_example: stale: `src/jarvis/api/static/console-voice-barge.js` changed since the page was stamped
pg_chapter_example: stale: `src/jarvis/api/static/console-wakeword.js` changed since the page was stamped
pg_chapter_example: stale: `src/jarvis/api/voice.py` changed since the page was stamped
pg_chapter_example: stale: `src/jarvis/voice/service.py` changed since the page was stamped
pg_chapter_data: stale: `deploy/cloudrun.sh` changed since the page was stamped
pg_chapter_data: stale: `src/jarvis/config.py` changed since the page was stamped
pg_chapter_setup: stale: `src/jarvis/api/app.py` changed since the page was stamped
pg_chapter_setup: stale: `src/jarvis/api/console.py` changed since the page was stamped
pg_chapter_setup: stale: `src/jarvis/api/personal.py` changed since the page was stamped
pg_chapter_setup: stale: `src/jarvis/api/selfcheck_wiring.py` changed since the page was stamped
pg_chapter_setup: stale: `src/jarvis/api/static/console.html` changed since the page was stamped
pg_chapter_setup: stale: `src/jarvis/config.py` changed since the page was stamped
pg_chapter_technology: stale: `deploy/cloudrun.sh` changed since the page was stamped
pg_chapter_costs: stale: `src/jarvis/__init__.py` changed since the page was stamped
pg_chapter_planned: flow: node built: `docs/plans/r18-calls.md` is not one of the page's refs
pg_chapter_planned: flow: node left: `docs/plans/r18-calls.md` is not one of the page's refs
pg_chapter_planned: stale: `docs/architecture/JARVIS-Architecture.md` changed since the page was stamped
pg_chapter_planned: stale: `docs/plans/r5-2-voice.md` is new to this page
pg_chapter_planned: stale: `docs/plans/r18-calls.md` is no longer one of the page's refs
pg_module_console: stale: `src/jarvis/api/app.py` changed since the page was stamped
pg_module_console: stale: `src/jarvis/api/console.py` changed since the page was stamped
pg_module_console: stale: `src/jarvis/api/personal.py` changed since the page was stamped
pg_module_console: stale: `src/jarvis/api/selfcheck_wiring.py` changed since the page was stamped
pg_module_console: stale: `src/jarvis/api/static/console.html` changed since the page was stamped
pg_module_voice: stale: `deploy/local-speech/README.md` is new to this page
pg_module_voice: stale: `deploy/local-speech/models.json` is new to this page
pg_module_voice: stale: `deploy/local-speech/requirements-kit.txt` is new to this page
pg_module_voice: stale: `deploy/local-speech/start-kit.sh` is new to this page
pg_module_voice: stale: `evals/wakeword/run.py` is new to this page
pg_module_voice: stale: `src/jarvis/api/r52_wiring.py` is new to this page
pg_module_voice: stale: `src/jarvis/api/speaker_assets.py` is new to this page
pg_module_voice: stale: `src/jarvis/api/static/console-voice-barge.js` changed since the page was stamped
pg_module_voice: stale: `src/jarvis/api/static/console-voice-session.css` is new to this page
pg_module_voice: stale: `src/jarvis/api/static/console-voice-session.js` is new to this page
pg_module_voice: stale: and 89 more refs
pg_module_home: stale: `src/jarvis/api/console.py` changed since the page was stamped
pg_module_vitals: stale: `src/jarvis/__init__.py` changed since the page was stamped
pg_module_vitals: stale: `src/jarvis/api/selfcheck_wiring.py` changed since the page was stamped
pg_module_android: stale: `src/jarvis/api/static/console-r7.js` changed since the page was stamped
pg_module_helpers: stale: `deploy/cloudrun.sh` changed since the page was stamped
pg_module_delivery: stale: `deploy/cloudrun.sh` changed since the page was stamped
pg_module_delivery: stale: `evals/run_all_mock.py` changed since the page was stamped
pg_module_delivery: stale: `src/jarvis/config.py` changed since the page was stamped
pg_module_book: stale: `src/jarvis/buildbook/gen/modules.py` changed since the page was stamped
pg_module_wardrobe: stale: `deploy/cloudrun.sh` changed since the page was stamped
pg_module_wardrobe: stale: `src/jarvis/api/static/console-r7.js` changed since the page was stamped
pg_module_calls: stale: `deploy/calldesk/README.txt` changed since the page was stamped
pg_module_calls: stale: `deploy/calldesk/requirements-calldesk.txt` changed since the page was stamped
pg_module_calls: stale: `src/jarvis/api/r18_wiring.py` changed since the page was stamped
pg_module_calls: stale: `src/jarvis/api/static/console-r7.js` changed since the page was stamped
pg_module_calls: stale: `src/jarvis/calldesk/app.py` changed since the page was stamped
pg_module_calls: stale: `src/jarvis/calldesk/config.py` changed since the page was stamped
pg_module_calls: stale: `src/jarvis/calldesk/kit.py` changed since the page was stamped
pg_module_calls: stale: `tests/test_calldesk_kit.py` changed since the page was stamped
pg_card_c01: stale: `src/jarvis/api/console.py` changed since the page was stamped
pg_card_c01: stale: `src/jarvis/api/static/console.html` changed since the page was stamped
pg_card_c02: stale: `src/jarvis/api/app.py` changed since the page was stamped
pg_card_c02: stale: `src/jarvis/api/console.py` changed since the page was stamped
pg_card_c02: stale: `src/jarvis/api/personal.py` changed since the page was stamped
pg_card_c02: stale: `src/jarvis/api/r18_wiring.py` changed since the page was stamped
pg_card_c02: stale: `src/jarvis/api/r52_wiring.py` is new to this page
pg_card_c02: stale: `src/jarvis/api/selfcheck_wiring.py` changed since the page was stamped
pg_card_c02: stale: `src/jarvis/api/speaker_assets.py` is new to this page
pg_card_c02: stale: `src/jarvis/api/static/console-r7.js` changed since the page was stamped
pg_card_c02: stale: `src/jarvis/api/static/console-voice-barge.js` changed since the page was stamped
pg_card_c02: stale: `src/jarvis/api/static/console-voice-session.css` is new to this page
pg_card_c02: stale: and 9 more refs
pg_card_c05: stale: `src/jarvis/api/voice.py` changed since the page was stamped
pg_card_c05: stale: `src/jarvis/voice/calls_bridge.py` is new to this page
pg_card_c05: stale: `src/jarvis/voice/laptop.py` is new to this page
pg_card_c05: stale: `src/jarvis/voice/profile.py` is new to this page
pg_card_c05: stale: `src/jarvis/voice/profile_ports.py` is new to this page
pg_card_c05: stale: `src/jarvis/voice/profile_store.py` is new to this page
pg_card_c05: stale: `src/jarvis/voice/routing.py` is new to this page
pg_card_c05: stale: `src/jarvis/voice/service.py` changed since the page was stamped
pg_card_c05: stale: `src/jarvis/voice/session.py` is new to this page
pg_card_c05: stale: `src/jarvis/voice/session_api.py` is new to this page
pg_card_c05: stale: and 6 more refs
pg_card_c06: stale: `src/jarvis/api/static/console-voice-barge.js` changed since the page was stamped
pg_card_c06: stale: `src/jarvis/api/static/console-wakeword.js` changed since the page was stamped
pg_card_c79: missing
pg_card_c80: missing
pg_card_c81: missing
pg_card_c82: missing
pg_card_c83: missing
pg_card_c63: stale: `src/jarvis/api/console.py` changed since the page was stamped
pg_card_c55: stale: `src/jarvis/__init__.py` changed since the page was stamped
pg_card_c55: stale: `src/jarvis/vitals/own.py` changed since the page was stamped
pg_card_c55: stale: `src/jarvis/vitals/words.py` changed since the page was stamped
pg_card_c56: stale: `src/jarvis/api/selfcheck_wiring.py` changed since the page was stamped
pg_card_c62: stale: `src/jarvis/api/static/console-r7.js` changed since the page was stamped
pg_card_c11: stale: `deploy/cloudrun.sh` changed since the page was stamped
pg_card_c49: stale: `src/jarvis/config.py` changed since the page was stamped
pg_card_c58: stale: `deploy/cloudrun.sh` changed since the page was stamped
pg_card_c59: stale: `evals/run_all_mock.py` changed since the page was stamped
pg_card_c57: stale: `src/jarvis/buildbook/gen/layers.py` changed since the page was stamped
pg_card_c57: stale: `src/jarvis/buildbook/gen/modules.py` changed since the page was stamped
pg_card_c72: stale: `src/jarvis/api/static/console-r7.js` changed since the page was stamped
pg_card_c73: stale: `deploy/cloudrun.sh` changed since the page was stamped
pg_card_c74: stale: `src/jarvis/api/r18_wiring.py` changed since the page was stamped
pg_card_c74: stale: `src/jarvis/api/static/console-r7.js` changed since the page was stamped
pg_card_c77: stale: `deploy/calldesk/README.txt` changed since the page was stamped
pg_card_c77: stale: `deploy/calldesk/install-calldesk.ps1` changed since the page was stamped
pg_card_c77: stale: `deploy/calldesk/requirements-calldesk.txt` changed since the page was stamped
pg_card_c77: stale: `src/jarvis/calldesk/__init__.py` changed since the page was stamped
pg_card_c77: stale: `src/jarvis/calldesk/app.py` changed since the page was stamped
pg_card_c77: stale: `src/jarvis/calldesk/config.py` changed since the page was stamped
pg_card_c77: stale: `src/jarvis/calldesk/kit.py` changed since the page was stamped
pg_card_c77: stale: `tests/test_calldesk_kit.py` changed since the page was stamped
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
pg_screen_voice: stale: `src/jarvis/api/static/console-voice-barge.js` changed since the page was stamped
pg_screen_voice: stale: `src/jarvis/api/static/console-voice-session.js` is new to this page
pg_screen_voice: stale: `src/jarvis/api/static/console-voiceprint-math.js` is new to this page
pg_screen_voice: stale: `src/jarvis/api/static/console-voiceprint-panel.js` is new to this page
pg_screen_voice: stale: `src/jarvis/api/static/console-voiceprint.js` is new to this page
pg_screen_voice: stale: `src/jarvis/api/static/console.html` changed since the page was stamped
pg_screen_voice: stale: `src/jarvis/api/voice.py` changed since the page was stamped
pg_screen_voice: stale: `src/jarvis/api/voice_profile_routes.py` is new to this page
pg_screen_integrations: stale: `src/jarvis/api/static/console.html` changed since the page was stamped
pg_screen_media: stale: `src/jarvis/api/static/console.html` changed since the page was stamped
pg_screen_vitals: stale: `src/jarvis/api/static/console.html` changed since the page was stamped
pg_screen_connectors: stale: `src/jarvis/api/static/console.html` changed since the page was stamped
pg_screen_people: stale: `src/jarvis/api/static/console.html` changed since the page was stamped
pg_screen_book: stale: `src/jarvis/api/static/console.html` changed since the page was stamped
pg_screen_construct: stale: `src/jarvis/api/static/console.html` changed since the page was stamped
pg_screen_helpers: stale: `src/jarvis/api/static/console.html` changed since the page was stamped
pg_screen_camera: stale: `src/jarvis/api/static/console.html` changed since the page was stamped
pg_screen_calls: stale: `src/jarvis/api/static/console.html` changed since the page was stamped
pg_service_anthropic: stale: `src/jarvis/config.py` changed since the page was stamped
pg_service_anthropic: stale: `src/jarvis/vitals/own.py` changed since the page was stamped
pg_service_bhashini: stale: `src/jarvis/config.py` changed since the page was stamped
pg_service_cloud_run: stale: `src/jarvis/api/app.py` changed since the page was stamped
pg_service_cloud_run: stale: `src/jarvis/config.py` changed since the page was stamped
pg_service_cloud_scheduler: stale: `src/jarvis/api/app.py` changed since the page was stamped
pg_service_cloud_scheduler: stale: `src/jarvis/config.py` changed since the page was stamped
pg_service_firestore: stale: `src/jarvis/api/app.py` changed since the page was stamped
pg_service_firestore: stale: `src/jarvis/api/personal.py` changed since the page was stamped
pg_service_firestore: stale: `src/jarvis/api/r18_wiring.py` changed since the page was stamped
pg_service_firestore: stale: `src/jarvis/api/r52_wiring.py` is new to this page
pg_service_firestore: stale: `src/jarvis/api/selfcheck_wiring.py` changed since the page was stamped
pg_service_firestore: stale: `src/jarvis/config.py` changed since the page was stamped
pg_service_firestore: stale: `src/jarvis/voice/service.py` changed since the page was stamped
pg_service_firestore: stale: `src/jarvis/voice/session_api.py` is new to this page
pg_service_frankfurter: stale: `src/jarvis/config.py` changed since the page was stamped
pg_service_frigate: stale: `src/jarvis/config.py` changed since the page was stamped
pg_service_gemini: stale: `src/jarvis/config.py` changed since the page was stamped
pg_service_gemini: stale: `src/jarvis/vitals/own.py` changed since the page was stamped
pg_service_gmail: stale: `src/jarvis/config.py` changed since the page was stamped
pg_service_google_calendar: stale: `src/jarvis/config.py` changed since the page was stamped
pg_service_google_cloud_speech_to_text: stale: `src/jarvis/config.py` changed since the page was stamped
pg_service_google_cloud_speech_to_text: stale: `src/jarvis/voice/service.py` changed since the page was stamped
pg_service_google_cloud_text_to_speech: stale: `src/jarvis/config.py` changed since the page was stamped
pg_service_google_cloud_text_to_speech: stale: `src/jarvis/voice/service.py` changed since the page was stamped
pg_service_google_drive: stale: `src/jarvis/api/app.py` changed since the page was stamped
pg_service_google_drive: stale: `src/jarvis/api/personal.py` changed since the page was stamped
pg_service_google_drive: stale: `src/jarvis/config.py` changed since the page was stamped
pg_service_google_maps_platform: stale: `src/jarvis/config.py` changed since the page was stamped
pg_service_google_photos_picker: stale: `src/jarvis/config.py` changed since the page was stamped
pg_service_google_tasks: stale: `src/jarvis/config.py` changed since the page was stamped
pg_service_google_sign_in: stale: `src/jarvis/config.py` changed since the page was stamped
pg_service_home_assistant: stale: `src/jarvis/config.py` changed since the page was stamped
pg_service_microsoft_azure_speech: stale: `src/jarvis/api/r18_wiring.py` changed since the page was stamped
pg_service_microsoft_azure_speech: stale: `src/jarvis/config.py` changed since the page was stamped
pg_service_mosquitto: stale: `src/jarvis/config.py` changed since the page was stamped
pg_service_ollama: stale: `src/jarvis/config.py` changed since the page was stamped
pg_service_openai_compatible: stale: `src/jarvis/config.py` changed since the page was stamped
pg_service_redis: stale: `src/jarvis/api/selfcheck_wiring.py` changed since the page was stamped
pg_service_redis: stale: `src/jarvis/config.py` changed since the page was stamped
pg_service_sarvam: stale: `src/jarvis/config.py` changed since the page was stamped
pg_service_tailscale: stale: `src/jarvis/config.py` changed since the page was stamped
pg_service_tailscale: stale: `src/jarvis/config_voice.py` is new to this page
pg_service_tailscale: stale: `src/jarvis/voice/laptop.py` is new to this page
pg_service_tailscale: stale: `src/jarvis/voice/session_api.py` is new to this page
pg_service_tavily: stale: `src/jarvis/config.py` changed since the page was stamped
pg_service_telegram: stale: `src/jarvis/config.py` changed since the page was stamped
pg_service_telegram: stale: `src/jarvis/vitals/own.py` changed since the page was stamped
pg_service_web_push: stale: `src/jarvis/config.py` changed since the page was stamped
pg_service_youtube_data_api: stale: `src/jarvis/config.py` changed since the page was stamped
module_voice: cues: line 84: pages are told in the chapter's order; the next is pg_card_c79
module_voice: cues: line 99: pages are told in the chapter's order; the next is pg_card_c79
module_voice: cues: line 115: pages are told in the chapter's order; the next is pg_card_c79
module_voice: pages: pg_card_c79 has no written page to tell (write it first)
module_voice: pages: pg_card_c80 has no written page to tell (write it first)
module_voice: pages: pg_card_c81 has no written page to tell (write it first)
module_voice: pages: pg_card_c82 has no written page to tell (write it first)
module_voice: pages: pg_card_c83 has no written page to tell (write it first)
module_voice: pages: pg_card_c79 has no line (every page is told at least once)
module_voice: pages: pg_card_c80 has no line (every page is told at least once)
module_voice: pages: pg_card_c81 has no line (every page is told at least once)
module_voice: pages: pg_card_c82 has no line (every page is told at least once)
module_voice: pages: pg_card_c83 has no line (every page is told at least once)
module_voice: pages: pg_screen_voice has no line (every page is told at least once)
module_voice: pages: pg_service_google_cloud_speech_to_text has no line (every page is told at least once)
module_voice: pages: pg_service_google_cloud_text_to_speech has no line (every page is told at least once)
```

## Change log

| Version | Date | Release | What changed | By |
|---|---|---|---|---|
| v5.2.0 | 27 Nov 2026, 19:00 IST | R5.2 | First edition: the catalogue for R5.2 (cards C79–C83 in the Voice module, no new screen or service), the full lists split into R18's (none) and R5.2's own (85 stale, 1 failing, 5 missing; `module_voice` failing), what looks wrong in the code, the checks run | 🛠 Mark XXV |
