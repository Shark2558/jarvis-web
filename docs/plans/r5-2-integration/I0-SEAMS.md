Version v5.2.0 · 27 Nov 2026, 15:00 IST · Release R5.2 · Status: Current · Owner: 🛠 Mark XXV

# R5.2 Your voice — the I0 seams (code against these)

Built on `r5-2-i0` (R18's `r18-i0` + `r5-2-plan`) from the plan's I0 row and `docs/plans/r5-2-voice/BUILD-BRIEF.md`. Import, don't copy. Names that **differ from the plan** are marked ⚠. R18's join (`r18-i1`) is **not merged yet** (its `I1-NOTES.md` did not exist when these seams were pushed): code needing `jarvis.calls.speech`, `jarvis.calls.langcheck` or `jarvis.calldesk` codes against the shapes in "R18 reuse" below, with fakes, until `r5-2-i0` merges it.

## Differences from the plan ⚠

| Plan | Code | Why |
|---|---|---|
| kit API `GET /health`, `POST /stt`, … | the same paths **relative to a `/v1` base** (`GET /v1/health` on the wire; `protocol.API_PREFIX`) | the cloud's base is exactly what `jarvis.offline.config.check_url` returns (`https://<machine>.<tailnet>.ts.net[:port]/v1`), so the offline brain's SSRF-safe rule and `PinnedTransport` apply unchanged |
| `POST /wakeword/*` (status, model) | `POST /wakeword/status` `{}`, `POST /wakeword/model` `{artifact}`; `GET /jobs/{job_id}` added | one method per path keeps the gate's matcher small; long jobs (scoring, training) are polled |
| `docs/plans/r5-2-voice/I0-SEAMS.md` | **this file**, `docs/plans/r5-2-integration/I0-SEAMS.md`; the brief is `docs/plans/r5-2-voice/BUILD-BRIEF.md` | the Workshop's instruction; earlier releases keep integration notes in `*-integration/` |
| config keys in `config.py` | **`src/jarvis/config_voice.py`** (`LocalSpeechConfig`, a base class of `Settings` like R18's `CallsConfig`: still `settings.<key>`, `JARVIS_<KEY>`) | config.py's size guard (now 792) |
| I0: protocol, profile, routes, config | also **`localspeech/memory.py`** (`MemoryKit`), **`voice/profile_ports.py`**, **`voice/profile_store.py`** | the seams V2, V3 and V4 share: a fake kit to test against, where the profile lives, what the routes call |
| V1 owns `localspeech/**` except `protocol.py` | V1 also leaves `memory.py`, `__init__.py` (I0), `wakeword/**` (V4) and **`client.py`, `desk.py` (V2)** | the call desk runs on the laptop and can't import `jarvis.voice` (its package pulls the cloud's service and billing): the kit client and the desk's hook must live in kit-safe `localspeech/` |
| routes mounted in `app.py` | mounted by `jarvis.api.voice.install_voice` (+2 lines) | app.py's guard (≤ 735, it is 734) |
| "your words list" | R5's existing `VoiceSettings.phrases` ("words to recognise", ≤ 50) | one list, already sent to Google as hints and in the privacy dashboard |
| the kit's voice "→ audio" | `TtsRequest.format`: `pcm16` (calls, scoring) or `mp3` (the console: `POST /v1/voice/speak` answers `audio/mpeg`) | the console's player is unchanged |

## Modules

| Module | Names |
|---|---|
| `jarvis.localspeech.protocol` (I0, **kit-safe**: stdlib, Pydantic, `jarvis.calls.models`/`protocol`) | `PROTOCOL` 1, `KIT_VERSION` (the kit's own semver track); paths `HEALTH`, `STT`, `TTS`, `CLIP`, `SCORE`, `RESULTS`, `DELETE`, `WAKE_TRAIN`, `WAKE_STATUS`, `WAKE_MODEL`, `JOBS` + `job_path(id)`, `ROUTES` (what the gate passes); `GATE_PORT` 11436, `SERVER_PORT` 11437, `FUNNEL_PORT` 8443, `LOOPBACK_BASE` `http://127.0.0.1:11436/v1`; `KEY_MIN_CHARS` 32, `bearer(key)`; `BODY_MAX` 3 MB, `REPLY_MAX` 4 MB; audio `SAMPLE_RATE`/`SAMPLE_BYTES` (R18's), `MIN_AUDIO_S` 0.3, `STT_MAX_S` 60, `CLIP_MAX_S` 20, `TTS_MAX_CHARS` 600, `PHRASES_MAX` 50, `encode_pcm`, `decode_pcm(b64, max_s=)`, `pcm_seconds`; `Kind`, `Device`, `AudioFormat`, `EngineSlot` (`whisper-small`, `whisper-medium`, `kokoro`, `piper`, `indic-conformer`, `indic-parler`), `SLOT_KIND`, `default_slots(kind, lang)`, `DEFAULT_ENGLISH_VOICE` `bm_george`, `PERMISSIVE_LICENCES`, `OWNER_LICENCE` `LicenseRef-Owner`; ids `SESSION_ID` `vs_<12hex>` (`new_session_id`), `JOB_ID` `job_<12hex>`, `PROMPT_ID` `^[a-z][a-z0-9_]{0,31}$` |
| models (requests strict, replies ignore extra fields) | `EngineHealth`, `KitHealth` (`.compatible`, `.engine_for(kind, lang)`, `.languages(kind)`, `slow`), `SttRequest` (`.of_pcm`, `.pcm()`), `SttResult` (`lang`, `text`, `confidence`, `seconds` = R18's `Heard` 1:1; `alternatives` ≤ 2 like `voice.Transcript`), `TtsRequest`, `TtsResult` (`.audio_bytes()`, `first_audio_ms`), `PromptKind` (`command`, `words`, `places`, `numbers`, `wake`), `ClipIn`, `ClipStored`, `ScoreIn`, `ResultsIn`, `HeardRow`, `SessionHeard`, `DeleteIn` (`session_id=None`: every recording; `wakeword`), `Deleted`, `JobKind`, `JobState`, `JobView` (`.finished`), `WakeArtifact` (`verifier`, `owned`), `WakeTrainIn`, `ArtifactInfo` (`beats_current`), `WakeStatus`, `WakeModelIn`, `WakeModel` (hash checked, licence checked) |
| errors | `KitErrorBody {error, detail}` (codes `KitErrorCode`), `KitError`, `KitUnavailable(reason)` (`not_configured`, `offline`, `timeout`, `busy`, `slow`, `unauthorized`, `protocol`, `error`: fall back), `KitRefused(code, words)` (this request); `parse_request(Model, raw)` → `KitRefused` (the server; never quotes input), `parse_reply(Model, raw)` → `KitUnavailable("protocol")` (the clients) |
| `KitClient` (Protocol) | `health`, `stt`, `tts`, `put_clip`, `score`, `results(session_id)`, `delete(DeleteIn)`, `job(job_id)`, `wakeword_train`, `wakeword_status`, `wakeword_model(artifact)` |
| `jarvis.localspeech.memory` (I0, kit-safe) | `MemoryKit(heard={sha256(pcm): text}, health=)` with `down` (a reason), `slow`, `calls` (method names only), `clip_count(session_id)`, `DEFAULT_TEXT`; `default_health()`, `INDIAN_TEST_LANGUAGES` (`hi-IN`, `ml-IN`) |
| `jarvis.voice.profile` (I0, pure) | `ListenEngine` (`browser`, `google`, `laptop-whisper-small`, `laptop-whisper-medium`; `.slot`, `.on_laptop`), `LAPTOP_ENGINES`, `DEFAULT_LAPTOP`, `engine_of_slot`; `SessionState`; `Prompt` (block 1–4), `EngineScore` (`wer` as a fraction, `commands`, `prompts`, `median_ms`); `Correction` (`heard` folded, 1–3 words; `meant` 1–5 words; letters only; never a `PROTECTED_WORDS` number, money or code word), `apply_corrections(text, corrections)` (whole words, one pass); `VoiceProfile` (`state`, `session_id`, `chosen`, `ranking`, `corrections`, `corrections_on`, `clips`, `compare_seconds`, `measured_at`; `.best()`); `listening_order(profile, laptop_ready=)`; `BARS` (`ProfileBars`: the plan's section 5, `.recognition_ok(...)`); `SESSION_MINUTES` 20, `BLOCKS` 4, `BLOCK_MINUTES` 5, `PROMPTS_TARGET` 120, `WAKE_PROMPTS` 30, `CORRECTIONS_MAX` 100, `WORDS_MAX` 50; `SPOKEN_BY_HEADER` `x-jarvis-spoken-by`, `SPOKEN_BY_OWNER` (a label, **never** an approval) |
| `jarvis.voice.profile_ports` (I0) | `ProfileStore` (`get`, `save`, `update(uid, change)`, `delete`), `ProfileApi` (V3), `LaptopApi` (V2), `WakewordApi` (V4), `ProfileRefused(status, code, words)`, `Answer` |
| `jarvis.voice.profile_store` (I0) | `DocProfileStore(docs, prefix=)` (30 s cache, transactional `update`, a bad document reads as the default), `MemoryProfileStore()`, `decode`, `encode`, `COLLECTION` |
| `jarvis.config_voice` (I0) | `LocalSpeechConfig`, `kit_origin(url)`, `FUNNEL_PORTS` (= `offline.config.ALLOWED_PORTS`), `KIT_KEY_MIN_CHARS` |

## The kit's API (`protocol`; base `…/v1`; JSON; `Authorization: Bearer <key>`)

| Method, path | Body → reply | Who |
|---|---|---|
| `GET /health` | → `KitHealth` | V2 (cached `local_speech_health_s`), the desk |
| `POST /stt` | `SttRequest` → `SttResult` | V2 (console, calls), the desk |
| `POST /tts` | `TtsRequest` → `TtsResult` | V2 (console `mp3`, calls `pcm16`), the desk |
| `POST /session/clip` | `ClipIn` → `ClipStored` | V3 |
| `POST /session/score` | `ScoreIn` → `JobView` (the laptop engines hear the held-out clips) | V3 |
| `POST /session/results` | `ResultsIn` → `SessionHeard` (V3 scores them) | V3 |
| `POST /session/delete` | `DeleteIn` → `Deleted` | V3 |
| `POST /wakeword/train` | `WakeTrainIn` → `JobView` | V4 |
| `POST /wakeword/status` | `{}` → `WakeStatus` | V4 |
| `POST /wakeword/model` | `WakeModelIn` → `WakeModel` | V4 |
| `GET /jobs/{job_id}` | → `JobView` | V3, V4 |

Refusals: an HTTP status with `KitErrorBody` (401 `unauthorized` from the gate, 404 `not_found`, 413 `too_large`, 422 `bad_request` / `bad_audio` / `unsupported_language`, 503 `engine_not_ready` / `busy`). The client maps 401, 5xx, timeouts and unreadable replies to `KitUnavailable`, 4xx to `KitRefused`; V2 maps `KitUnavailable` to "fall back silently" (Google, then the browser: **never** a `VoiceUnavailable` with Google's words for a kit failure) and `KitRefused("bad_audio")` to `BadAudio`; for calls, both to R18's `SpeechUnavailable`.

## Routes (`src/jarvis/api/voice_profile_routes.py`, `install_voice_profile_routes(app)`, mounted by `install_voice`)

Owner-only (`require_auth` + `current_user`), `no-store`, bodies JSON objects ≤ 16 KB (a clip ≤ `CLIP_BODY_MAX` 1,000,000). 501 `not_built` until I1 sets the slot; 503 `voice_profile_off` when `voice_profile_enabled` is off; `ProfileRefused` → `{error, detail}` (402 `needs_yes` is the comparison's ₹ question). `vr.SLOTS` maps each route to its slot and method.

| Path | Slot.method |
|---|---|
| `GET`, `PUT /v1/voice/profile` | `voice_profile_api.view(uid)`, `.update(uid, body)` |
| `GET /v1/voice/profile/session`, `POST …/session/start` | `.session(uid)`, `.start(uid, body)` |
| `PUT /v1/voice/profile/session/clips/{prompt_id}` `{audio: base64 WAV 16 kHz mono PCM16 ≤ 20 s, browser_heard?}` | `.put_clip(uid, prompt_id, body)` — V3 reads the WAV with `jarvis.voice.wav.parse_wav`, then `ClipIn(audio=encode_pcm(pcm))` |
| `POST /v1/voice/profile/session/score`, `GET …/session/results`, `POST …/recheck` | `.score(uid, body)`, `.results(uid)`, `.recheck(uid, body)` |
| `POST /v1/voice/profile/recordings/delete` `{confirm: "DELETE"}` (else 422 `confirm_needed`) | `.delete_recordings(uid)` |
| `GET /v1/voice/profile/laptop` | `voice_laptop.status(uid)` |
| `GET /v1/voice/profile/wakeword`, `POST …/wakeword/train` | `voice_wakeword.status(uid)`, `.train(uid, body)` |
| `GET /v1/voice/profile/wakeword/verifier`, `GET …/wakeword/model` | `.verifier(uid)`, `.model(uid)` → `(bytes, media type)` |

## Store layout (Docs port)

`{p}voice_profile/{uid}` — `user_id`, the `VoiceProfile` fields, `updated_at`. No audio, voice print or wake-word file in the cloud. The words stay in `{p}voice_settings/{uid}.phrases` (R5).

## Config (`config_voice.LocalSpeechConfig`, on `Settings`)

`local_speech_url` (None; `https://<machine>.<tailnet>.ts.net[:443|8443|10000]`, normalised to the origin, http / IP / other paths refused) · `local_speech_key` (SecretStr|None, ≥ 32) · `local_speech_enabled` (True) · `.local_speech_configured` (enabled and both set) · `local_speech_timeout_s` 8 · `local_speech_health_s` 30 · `voice_profile_enabled` (True) · `voice_session_compare_minutes` 20 (≤ 30). Secret Manager name for the key: `jarvis-local-speech-key` (I1 adds it to `deploy/cloudrun.sh`).

## The version (decided here)

`jarvis.__version__ = "5.2.0"`; the About line reads **"About JARVIS · v5.2.0 · built …"**; the book's release is R5.2 (`docs/plans/r5-2-voice.md` first, then R18's and R14's plans; `release.new` "Your voice: the plan"); the guide's version line reads v5.2.0 · Release R5.2. R5.2 ships after R18 (v18.0.0), so the number goes down: as when R6.3 (6.3.0) followed R13.1 (13.1.0), the number names the release, not an order. Nothing compares `jarvis.__version__` (the deploy watch and the backup canary test equality only); the kits keep their own, increasing tracks and are never set from it (home `BRIDGE_VERSION`, the call desk's `DESK_VERSION` 18.x — bump it on its own track if R5.2's join edits the desk — and the speech kit's `kit_version`, starting 1.0.0). Every pin moved: `test_about` (the one literal), the seams tests of R7, R11, R11.1, R13, R13.1, R14, R6.3, the book tests, `r63_fakes_a`. PR title: `v5.2.0 · R5.2 Your voice · Mark XXV`; trailers `JARVIS-Version: v5.2.0`.

## R18 reuse (call, never copy)

| Need | R18's seam | Who, when |
|---|---|---|
| Calls hear and speak through the kit | `jarvis.calls.ports.Hearing` / `Voice` (`name = "laptop"`, `SpeechOption.LAPTOP`), errors as `SpeechUnavailable`; passed as `jarvis.calls.speech.build.build_speech(..., laptop=(hearing, voice))` | V2 `voice/calls_bridge.py`; the one-line registration at R5.2's I1 |
| The call desk uses the kit on the laptop | `jarvis.calldesk.speech_local.LocalSpeech` (`status() → LocalStatus(installed, languages)`, `transcribe → LocalHeard(lang, text, confidence)`, `speak → PCM16`), `LocalSpeechUnavailable`; given to the desk app as `local=` | V2 `localspeech/desk.py` (over `LOOPBACK_BASE`, languages from `KitHealth.languages`); the one-line hand-over at R5.2's I1 |
| Languages and what was heard | `jarvis.calls.models.Heard`, `ENGLISH`, `LANGUAGES`, `is_language` (the protocol validates languages with them) | everyone |
| Audio format | `jarvis.calls.protocol.SAMPLE_RATE`, `SAMPLE_BYTES` (re-exported by the protocol) | everyone |
| ₹0 for the laptop | `jarvis.calls.prices.speech_prices(...)[SpeechOption.LAPTOP]` | V2 (Vitals) |
| Normalising transcripts before word error | `jarvis.calls.langcheck.scoring.normalise` (R18 B) | V3 |
| Which Indian languages use the laptop | R18's language check (`jarvis.calls.langcheck`, phone-line simulation `jarvis.calls.speech.phoneline`), results per `SpeechOption.LAPTOP` | R18's code decides; V1's engines are what it measures |

## Left for I1 and the Book

Merge `r18-i1` when final (if this branch hasn't). Wire `app.state.voice_profile_api` (V3), `voice_laptop` (V2), `voice_wakeword` (V4), a `DocProfileStore(docs, prefix=settings.firestore_prefix)` and V2's kit client (or nothing when `local_speech_configured` is False); the two R18 registrations above; the privacy-dashboard source (V3's) where `settings_source(` is; `JARVIS_LOCAL_SPEECH_URL` and the `jarvis-local-speech-key` secret in `deploy/cloudrun.sh`. Book and guide: cards for `src/jarvis/localspeech`, `config_voice`, the `voice_profile` collection, the console's new screens and the speaker check; `tests/test_arch_coverage.py::test_the_real_guide_passes` already fails on R18's calls cards (left for R18's Book refresh) and will list these too until then. Known before R5.2: `ruff` E501 at `tests/test_r63_seams.py:114` (R18's line). Layers: `localspeech` L6, `config_voice` X (`buildbook/gen/layers.py`); `python -m jarvis.buildbook.gen --check` passes on this branch (R5.2, two builds byte-identical).

## Change log

| Version | Date | Release | What changed | By |
|---|---|---|---|---|
| v5.2.0 | 27 Nov 2026, 15:00 IST | R5.2 | First edition: every I0 seam, the differences from the plan, the version decision, the R18 seams to reuse, what is left for I1 | 🛠 Mark XXV |
