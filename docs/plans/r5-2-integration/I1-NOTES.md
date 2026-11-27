Version v5.2.1 · 27 Nov 2026, 22:20 IST · Release R5.2 · Status: Current · Owner: 🛠 Mark XXV

# R5.2 "Your voice": the I1 join

Branch `r5-2-i1`, from `r5-2-i0` (060c3a7). The builders' own notes: `docs/plans/r5-2-integration/I0-SEAMS.md`, `INTEGRATION-V5.md`; the Workshop's collected join needs and its decisions of 27 Nov are followed (section 2, decisions 1–4).

## 1. What was joined

| Branch | Head | Builder | Merged |
|---|---|---|---|
| `r18-i1` | 16fb461 | R18's final join (calls, the call desk, the phone, the Calls panel) | clean |
| `r5-2-v1` | b8f595d | the laptop speech kit: `localspeech/**` (server, engines, model manager, jobs, clip vault, self-test, CLI), `deploy/local-speech/**` | clean |
| `r5-2-v2` | 7a95cd2 | the kit's client and the desk's hook (`localspeech/client.py`, `desk.py`), `voice/laptop.py`, `voice/calls_bridge.py`, `voice/routing.py`, the voice service's routing, Vitals' engine line | clean |
| `r5-2-v3` | 1ec2d08 | the voice session: `voice/session*.py`, `session_api.py`, `session_privacy.py`, `console-voice-session.js/.css` | `console.py`, `console-r7.js`, `test_r51_console_assets_linked.py`: R18 E's Calls entries and V3's kept side by side |
| `r5-2-v4` | c1d5d29 | the wake word: `localspeech/wakeword/**`, `voice/wakeword_api.py`, `console-wakeword-own.js`, `evals/wakeword` | the console.html hash pins in `test_r13_seams` / `test_r63_seams` (re-pinned once every R5.2 tag was in) |
| `r5-2-v5` | bd181f7 | the speaker check: `console-voiceprint*.js`, the barge-in hook, `api/speaker_assets.py`, the model slot | clean |
| `r5-2-pins` | c8c7862 | the Whisper slots' licence and `model.bin` hashes (`deploy/local-speech/models.json`, README, its tests) | clean |

Every builder's tests are kept; the ones the join had to change are listed in section 3.

## 2. Wiring (what is where)

- **`src/jarvis/api/r52_wiring.py`** (new): `voice_service(app, s, docs, engines)` replaces `build_voice_service` in `app._wire_core` (one line, + its import: `app.py` 738 → 739). It builds V2's `LaptopVoice` from the settings (`app.state.voice_laptop`; no client, state "off", without `JARVIS_LOCAL_SPEECH_URL` and the key), **one** `DocProfileStore(docs, prefix=)` (`voice_profiles`), the voice service with both (`build_voice_service(laptop=, profiles=)`: V2's routing), V4's `WakewordHandlers(laptop.kit, profiles)` (`voice_wakeword`) and V3's `build_profile_api(...)` (`voice_profile_api`). The kit has **one** `HttpKit` (Funnel https, pinned transport), shared by the console's voice, R18's calls, the session and the wake word; it is closed with the voice service (`VoiceService.aclose` → the route → the laptop). With `voice_profile_enabled` off the profile slots stay None (the routes answer 503) and the service listens in the usual order. A failure building the session API is logged by name and leaves its routes at 501.
- **R18's two registrations**: `r18_wiring._SpeechFactory.options` passes `laptop=calls_laptop(app)` to `build_speech` (V2's `laptop_speech`: `(None, None)` without the kit, so R18 lists it missing as before); the call desk's `run_desk` passes `local=local_speech(cfg)` to `serve` (V2's `desk_speech` over `LOOPBACK_BASE`), closed when the desk stops.
- **The desk's key** (the open question of V2's note; the safe default): `calldesk/config.py` reads `JARVIS_LOCAL_SPEECH_KEY` from the desk's environment, else `local-speech.key` in the desk's own private folder (`%LOCALAPPDATA%\JARVIS\CallDesk`, beside `secret.json`); a key under 32 characters or an unreadable file is no key (cloud speech). `install-calldesk.ps1` copies the kit's key file from the kit's private folder (step 5b; `-SpeechKit` later, e.g. after a new key). Never in the kit zip (`SKIP_NAMES`, `.key`) or the repo. The desk kit ships `jarvis.localspeech.{protocol,client,desk}` and `jarvis.offline.config` (`kit.SAFE_JARVIS`, `PACKAGES`) and hash-pins httpx 0.28.1, httpcore 1.0.9, h11 0.16.0, anyio 4.16.0, idna 3.20 and certifi 2026.11.20 (PyPI's SHA-256; MPL-2.0 for certifi, used unmodified). `DESK_VERSION` 18.0.0 → 18.1.0 (its own track).
- **V1 ↔ V4's wake-word seam** (adapted V1's side, as the brief has V4 define the interface): `localspeech/ports.py` now re-exports V4's `WakewordKit` (with `NoWakeword` for a kit without it); `KitService.wake_train` hands `prepare` **every** clip of the session (V1 passed only the "Hey Jarvis" ones and no session; V4's verifier uses his other prompts as negatives) and so refuses an untrainable request before a job is queued; `train` runs in the job, and a cancel ("Delete my recordings") stops it at its next progress step. `localspeech/wakejoin.py` (new, kit-only): `kit_wakeword(config)` = V4's `build_wakeword(config.wakeword_dir, sealer=FileSealer(...), voices=None)`; `__main__.serve` builds the server with it. The trained files are sealed (AES-256-GCM) with **their own key** `wakeword.secret`: deleting every recording replaces the recordings' key, and the owner may keep the wake-word files.
- **V3**: its three privacy rows (`voice_profile`, `voice_recordings`, `voice_wakeword_files`) in `personal.privacy_sources` after R13's (`r52_privacy_sources`); the delete route passes `{"wakeword": true}` on (a bool only; any other key is 422); **the comparison is Google's alone**: V2's `transcribe` routes the owner's listening to the laptop and applies his corrections, so `VoiceService.transcribe(..., google_only=True)` (Google with his words, no routing, no corrections) is what `ServiceGoogle.hear` calls.
- **V2**: Vitals' engine line (`OwnSources(voice=app.state.voice_laptop)` in `selfcheck_wiring`; left out while the kit is not set up).
- **V4**: the Train buttons on V3's "Your voice" section, after a scored session and when `JarvisWakeOwn` is on the page: "Train my Hey Jarvis" (`train('verifier')`) and "Train my own wake word (2 to 3 hours)" (`train('owned')`; it says the laptop's speech waits meanwhile and the old model stays unless the new one does better). `evals/wakeword` is in `evals/run_all_mock.py` (gated; both controls fail it).
- **V5**: `console-voiceprint-math.js`, `console-voiceprint.js`, `console-voiceprint-panel.js` in `APP_ASSETS` and in `console.html` after V4's tag on the mic's line (R5's voice-script order stays exact; the barge-in hook reads the check at call time; still 782 lines; its hash re-pinned in the R13, R13.1 and R6.3 seams); its Record button is hidden, not faded, while no model is installed (R5's AA contrast check); the speaker model route `GET /static/vendor/speaker/{release}/{name}` mounted by `install_voice`; V3's screen hands each clip's PCM to `JarvisVoicePrint.offerSessionClip` before it is sent (V5's seam; V5's test now allows exactly that call there). The optional `'speaker'` panel slot was not added (the panel inserts its own).
- **Deploy**: `deploy/cloudrun.sh` asks once (or with `--local-speech`) for the kit's address, checked as JARVIS checks it (`*.ts.net`, https, port 443 / 8443 / 10000, no path), and its key, straight to the secret `jarvis-local-speech-key`, granted to `jarvis-run` like the others; an optional part never stops the deploy. The kit's README step 6 says so.
- **The Workshop's decisions**: (1) GPL engines (Kokoro's phonemiser, piper-tts) and the PyTorch Indian engines stay out: empty slots in `models.json` `left_out`; the voice falls back to Google and Indian languages use the cloud options R18's check passes. (2) The kit's Funnel port is **10000** everywhere: `protocol.FUNNEL_PORT`, the start scripts' default (`-HttpsPort 443` when 10000 is taken), the Caddyfile, the README, the brief, the seams doc, the config's example; the offline brain keeps 8443 (corrected by the review: the brain's scripts took the home bridge's 8443; the brain now has 443, so one door each: bridge 8443, brain 443, kit 10000). (3) The R18 dock: no console edit here touches the dock (the fix is on `r18-dock`). (4) **Model pins — a recorded deviation from the build brief's rule 9**: the model manager accepts, only for a small plain-git text file (JSON or TXT, ≤ 5 MB) at a full commit that appears in its address, its **git blob id** (`git_blob_sha1`) instead of a SHA-256; it checks `sha1("blob <size>\0" + data)` after download, refuses a mismatch and records the file's SHA-256 in `installed.json` and `LICENCE.txt`. Weights (`model.bin`, any LFS file) always need a SHA-256. faster-whisper **small** (536b066…) and **medium** (08e178d…), MIT, are now pinned: `model.bin` by the SHA-256 the pins agent read on two pages; `config.json`, `tokenizer.json`, `vocabulary.txt` by the `oid` read at I1 from the API tree at each revision, twice (two different requests, the same answer; README table). The plan's change log (v5.2.2) records the deviation.

## 3. Mismatches found and fixed

1. **The wake-word seam**: two interfaces (V1's `WakewordTrainer`, V4's `WakewordKit`) — V1's server adapted (2, above); V1's `FakeTrainer` follows V4's shape and its test now sees every clip (`given == [2]`).
2. **V1's cloud import guard** refused V4's `wakeword_api` reading `localspeech.wakeword.formats`; that module is V4's pure file-format module (stdlib + Pydantic) meant for the cloud: the guard allows it by name.
3. **The session's comparison** would have been heard by the laptop and corrected (V2's routing): `google_only` (2, above).
4. **The delete route** dropped V3's `wakeword` choice: passed on (I0's route test fake takes the keyword).
5. **The desk's key** had no home: the desk's own folder or environment (2, above).
6. **The desk kit** refused `jarvis.localspeech.*`, `jarvis.offline.config` and httpx: allowed and pinned; R18's kit tests list them.
7. **V3's screen** neither offered clips to the speaker check nor had a way to train the wake word: both added (2, above).
8. **Shared test harnesses on the joined page**: R5's `FakeVoice` passes `/v1/voice/profile*` to the real routes; V5's harness doesn't link its scripts twice and its barge-in tests keep their stand-in check; V3's phone test reads the real section; R1's deploy test keeps `${WEB_SECRET}JARVIS_` adjacent; `test_notify_hardening` reads the call desk's own pins for `calldesk` modules (it failed on `r18-i1` already: websockets, soundcard, comtypes).
9. **Budgets moved, one line each**: `app.py` 739 (`test_r63_seams` ==, `test_r131_seams`, `test_r11_1_seams`, `test_r7_seams`, `test_r13_seams`, `test_r14_seams` ≤); `console-r7.js` ≤ 96 (`test_r131_seams`, V3's registration). `console.py` stays 473 (R5.2's entries share lines, as the file already does) and `console.html` 782.
10. **Pins moved**: the console.html hash (`test_r13_seams`, `test_r63_seams`, `test_r131_seams`); `DESK_VERSION` 18.1.0 (`test_calldesk_kit`, `test_calldesk_app`, `test_calldesk_link`); the kit's port 10000 (`test_r52_v1_deploy`); the Whisper pins (`test_r52_v1_deploy`, `test_r52_v1_cli` uses a no-model manifest for "nothing to install", so no test downloads).

## 4. Known limits

1. **Model slots**: only faster-whisper small and medium are pinned. Kokoro, Piper (GPL-3.0 runtime) and IndicConformer, Indic Parler-TTS (PyTorch) are left out by the Workshop's decision: the kit has **no voice** and no Indian-language engine; the console speaks with Google, calls use cloud speech for Indian languages.
2. **No synthetic voices for the wake word**: with the voice slot empty, `kit_wakeword` passes `voices=None`: stage 1 trains without other speakers' negatives (its evals say "other speakers were not measured", so the plan's ≥ 90 % rejection bar can't be shown) and stage 2 refuses with V4's words until a permissively licensed voice is pinned.
3. **Launch blocker**: openWakeWord's mel-spectrogram and embedding models (the console's front end, which both stages build on) are **CC BY-NC-SA**: an owned or permissive front end is needed before any public launch, stage 2 included (V4's finding).
4. **The speaker check's model is not vendored**: WeSpeaker VoxCeleb CAM++ (CC BY 4.0, checked at primary sources) has an empty slot in `static/vendor/speaker/spk-1/MANIFEST.json` (no SHA-256 could be taken); the threshold 0.45 is uncalibrated and the EER ≤ 5 % eval needs the real model. Until then the console says "no model" and barge-in is unchanged. "Spoken by the owner" is not shown anywhere yet (the label only; it never approves anything).
5. **Hugging Face was reachable only through the web reader**, not from the shell: the blob ids were read twice from the API tree, not computed from downloaded files; the manager re-checks every file on the laptop and refuses a mismatch.
6. **Untested here** (no laptop, no network): the kit's real engines, Caddy, Tailscale Funnel and the PowerShell scripts; the desk's `-SpeechKit` step; a call heard on the kit (R18's language check decides when "laptop" is used: it must pass it first).
7. Not done (as the builders said): the recognition eval on his real voice (CI runs the synthetic set), the "Spoken by the owner" label, the optional `'speaker'` panel slot.

## 5. What needs the owner's hands

1. **Install the kit** (`deploy/local-speech/README.md`): `install-kit.ps1` (Python and Caddy only with his Y; about 2 GB of Whisper downloads, each file checked), then `start-kit.ps1 -SelfTest` and paste the report; it prints `https://<laptop>.<tailnet>.ts.net:10000` and the key.
2. **Give JARVIS the address and key**: in Cloud Shell `bash deploy/cloudrun.sh --local-speech`.
3. **The call desk on the same laptop**: `install-calldesk.ps1 -SpeechKit`, then restart the desk.
4. **The 20-minute voice session** (Voice → Your voice); the comparison's Google minutes are free inside the allowance, else the ₹ is shown first (402 `needs_yes`, at most ≈ ₹46).
5. **Train his Hey Jarvis** (the button after the session); optionally the owned model overnight (2–3 hours) before any launch — which also needs the permissive front end (4.3).
6. **The speaker check**: download the CAM++ model on the laptop and pin its SHA-256 in the slot (its `MANIFEST.json` says how), then 1 minute of reading per other device.
7. Run R18's language check again once the kit is up, so "laptop" can be chosen for calls.

## 6. The Build Book after the join

`PYTHONPATH=src python -m jarvis.buildbook.gen pages --list` on `r5-2-i1` (d59318d, the same at 2e3b64e): **154 pages: 64 ok, 88 stale, 1 failing, 1 missing** (R18's join: 68 ok, 84 stale, 1 failing, 1 missing). New since R18's list (R5.2's): `pg_module_voice`, `pg_card_c05` (Voice service), `pg_card_c06` (Voice loop in the console), `pg_card_c56` (Systems check). Every other item is R18's (its I1-NOTES section 6).

**Missing (1):** `pg_screen_calls` (R18's).

**Failing (1):** `pg_chapter_planned` (R18's).

**Stale (88)**, by kind:

- chapters (7): `pg_chapter_what`, `pg_chapter_example`, `pg_chapter_data`, `pg_chapter_answers`, `pg_chapter_setup`, `pg_chapter_technology`, `pg_chapter_costs`
- modules (11): `pg_module_console`, `pg_module_brain`, `pg_module_home`, `pg_module_vitals`, `pg_module_approvals`, `pg_module_android`, `pg_module_helpers`, `pg_module_delivery`, `pg_module_book`, `pg_module_wardrobe`, **`pg_module_voice`**
- cards (22): `pg_card_c01`, `pg_card_c02`, **`pg_card_c05`**, **`pg_card_c06`**, `pg_card_c11`, `pg_card_c28`, `pg_card_c39`, `pg_card_c49`, `pg_card_c51`, `pg_card_c55`, **`pg_card_c56`**, `pg_card_c57`, `pg_card_c58`, `pg_card_c59`, `pg_card_c62`, `pg_card_c63`, `pg_card_c64`, `pg_card_c65`, `pg_card_c67`, `pg_card_c68`, `pg_card_c72`, `pg_card_c73`
- screens (22: `console.html` changed): `pg_screen_chat`, `pg_screen_brief`, `pg_screen_approvals`, `pg_screen_activity`, `pg_screen_history`, `pg_screen_memory`, `pg_screen_vault`, `pg_screen_things`, `pg_screen_notes`, `pg_screen_privacy`, `pg_screen_home`, `pg_screen_faces`, `pg_screen_voice`, `pg_screen_integrations`, `pg_screen_media`, `pg_screen_vitals`, `pg_screen_connectors`, `pg_screen_people`, `pg_screen_book`, `pg_screen_construct`, `pg_screen_helpers`, `pg_screen_camera`
- services (26): as R18's list (`config.py` changed)

**Not in the Book's catalogue yet (the Book refresh adds them; after R18's proposed C74–C78):**

- guide cards **C79–C82** (proposed): the laptop speech kit (`src/jarvis/localspeech/**` but `wakeword/`, `deploy/local-speech/**`, `config_voice.py`); your voice (`voice/{profile,profile_ports,profile_store,laptop,routing,calls_bridge,session*}.py`, `api/voice_profile_routes.py`, `api/r52_wiring.py`, `console-voice-session.js/.css`); your own "Hey Jarvis" (`localspeech/wakeword/**`, `voice/wakeword_api.py`, `console-wakeword-own.js`, `evals/wakeword`); the speaker check (`console-voiceprint*.js`, `api/speaker_assets.py`, `static/vendor/speaker/**`);
- a module for the kit in `buildbook/gen/modules.py` (e.g. `localspeech`, "Laptop speech kit") → **`pg_module_localspeech`** and its narration `module_localspeech.md`; the voice profile and the speaker check in `pg_module_voice`'s refresh; the cards' pages `pg_card_c79`…`pg_card_c82`;
- the collections `voice_profile` and `voice_session` (guide and `arch_coverage.json`), the console's new screens (Your voice, the session pop-up, Speaker check), a Hugging Face service page (model downloads; R18 proposed it for FLEURS too).

## 7. Checks run at I1

- **Touched and related tests, once** (229 files behind `flock /tmp/jarvis-heavy.lock`: every `test_r52_*`, R18's `test_r18_*`, `test_calls_*`, `test_calldesk_*`, every `*seams*`, the voice, Vitals, privacy, deploy and Book suites, `test_about`, `test_notify_hardening`, the console asset tests): **5,600 passed, 9 skipped, 5 failed**. Two are the known ones not owned here: `test_arch_coverage::test_the_real_guide_passes` (R18's guide cards, on `r18-book`) and `test_r14_a_verify::test_the_known_sub_collections_are_pinned_against_the_stores` (R18's). Three were the join's, fixed (3.8) and rerun with their neighbours: `test_r5_seams` (the voice-script order), `test_deploy_web` (the secrets' order), `test_notify_hardening` (R18's desk): **1,177 passed**.
- **Browser** (`JARVIS_BROWSER_TESTS=1`, `/tmp/venv-c` Python 3.13; NumPy from R18's separate target `/tmp/i1np`, linked at the worktree root for the server's `-m` start only and removed after, nothing installed): R5.2's `test_r52_v3_voice_session.py`, `test_r52_v4_wake_own.py`, `test_r52_v5_voiceprint.py` **23 passed**; `test_voice_barge.py`, `test_voice_fixes_barge.py`, `test_voice.py`, `test_dock_fit.py` **121 passed** (after 3.8 and the Record button; the 1920 px dock unchanged, R18's rule as `r18-dock` will fix it).
- `ruff check` on every Python file R5.2 touched: clean but the known E501 in `tests/test_r63_seams.py`, now line **115** (one pin comment above it). `ruff format`: new files clean but V5's browser test (as on its branch); `api/console.py` keeps its paired entries (unformatted on R18's base too).
- `mypy --strict` on `jarvis.localspeech`, `jarvis.voice`, `jarvis.calldesk`, `jarvis.vitals`, `config_voice` and the API files touched: **clean (112 files)**; `memory/redis_store.py:67` was not reached by this set.
- `python evals/wakeword/run.py --mock`: passes, both controls fail it.
- The Book: section 6.

## Change log

| Version | Date | Release | What changed | By |
|---|---|---|---|---|
| v5.2.0 | 27 Nov 2026, 20:30 IST | R5.2 | First edition: the join, its wiring decisions, the mismatches fixed, the known limits, the owner's steps, the Book's list | 🛠 Mark XXV |
| v5.2.1 | 27 Nov 2026, 22:20 IST | R5.2 | Combined review: section 2's port note corrected (one door each: the home bridge 8443, the offline brain 443, the kit 10000); the review's findings are in `REVIEW.md` | 🛠 Mark XXV |
