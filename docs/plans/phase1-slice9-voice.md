# Phase 1 · Slice 9 — Voice: speak to JARVIS, JARVIS speaks back, wit dial, "Hey Jarvis"

Owner (2026-11-01 19:38 IST): "proceed further and develop the voice modules. Kindly remember to clone the
actual JARVIS voice as seen on the movie and also the response should be witty in nature similar to the one
in the movie or a little more than that is also fine."

Phase mapping: Phase 1 (Voice I/O + wake word + TTS) of the build phases; skill = Communication; layers 2
(Input Processing: STT, wake word), 4 (persona), 8 (Response & Output: TTS).

## 1. Decisions

| # | Decision | Why |
|---|---|---|
| D1 | **No clone of the film actor's voice.** JARVIS gets an original British male voice: a stock Google voice chosen by the owner from a curated shortlist with previews, plus an optional light "Comms" finish (client-side audio processing). The voice is a setting behind a `TTSProvider` port, so a voice the owner has rights to can be plugged in later. | The film voice is a real person's voice/likeness; cloning it without consent breaches ElevenLabs' and Google's terms (account bans) and personality rights. Flagged deviation from the project brief's "ElevenLabs (JARVIS voice cloning)". |
| D2 | **TTS = Google Cloud Text-to-Speech v1 `text:synthesize`**, REST over httpx with ADC as `jarvis-run` (no new account, no new secret), global endpoint, MP3. Voices: Chirp 3: HD `en-GB` (male) + `en-GB-Studio-B`. `speakingRate` 0.8–1.25 (Chirp 3 HD supports 0.25–2.0). | Verified 2026-11-01 (cloud.google.com/text-to-speech/pricing; docs.cloud.google.com/text-to-speech/docs/chirp3-hd): Chirp 3 HD 1 M chars/month free then US$30/1 M; Studio 1 M free then US$160/1 M; Neural2 1 M free then US$16/1 M; spaces count; MP3 is batch-only (fine — we use batch). ElevenLabs/Piper/Kokoro remain later adapters. |
| D3 | **STT = Google Cloud Speech-to-Text v1 `speech:recognize`** (sync, ≤ 60 s), LINEAR16 16 kHz mono, `latest_short`, `en-IN` (config `JARVIS_VOICE_LANGUAGE`), automatic punctuation, phrase hints ["JARVIS", "Jarvis", "Sir"], no data logging. Second engine: **the browser's own speech recognition** (Chrome/Edge/Safari) — free, shows live words, audio goes to the browser vendor. Default = cloud when ready, else browser when supported, else typing. | V1: 60 min/month free, then US$0.024/min without data logging (pricing page). V2 lists no free tier and needs recognizer IAM. Cloud keeps audio inside the owner's project. |
| D4 | **One capture pipeline** (`AudioWorklet` → 16 kHz Int16 frames of 1280 samples) feeds level meter, energy VAD, WAV recorder and the wake-word detector. `getUserMedia({echoCancellation, noiseSuppression, autoGainControl})`. Mic only after a user gesture (or the owner's wake-word switch). | Works the same on every browser (no MediaRecorder codec differences; Safari records AAC which STT v1 can't read). |
| D5 | **Playback through Web Audio** (fetch MP3 → `decodeAudioData` → graph). "Comms" finish = high-pass ~120 Hz, low-pass ~9 kHz, gentle compressor, short procedurally generated room reverb, mixed lightly; "Clean" = none. Default **Comms**. An `AnalyserNode` drives the Core 3D scene and the mic ring (real data only). | No `media-src` CSP change needed; enables the finish and real-level visuals. |
| D6 | **Sentence-streamed speech.** The console splits the streamed reply into speakable chunks (first sentence as soon as it ends; later chunks ≤ ~400 chars), never speaks code blocks/tables (says once "The details are on screen, {honorific}."), and plays them in order. The server's `speakable()` is the authority: strips markdown, code, URLs (→ "the link on screen"), emoji, control/bidi chars; caps 600 chars per request. Barge-in (mic tap / Esc / new message) stops audio and aborts pending fetches. | First audio ~1–2 s after the first sentence instead of after the whole reply. |
| D7 | **Voice channel.** `ChatRequest.channel: "text" \| "voice"` (default `text`). For `voice` the per-request trailer adds the spoken-reply rule (answer first; ≤ ~60 words / 3 sentences unless asked for detail; no markdown, lists, tables, URLs; say "on screen" for detail; speak numbers and dates naturally). System prompt stays cacheable. | Long spoken answers are tiring; keeps the cache stable. |
| D8 | **Wit dial** (owner setting, server-side): `measured` (light), **`film` (default: dry, understated British wit; at most one light quip, only where it fits)**, `extra` (drier, more frequent, gentle teasing of the owner allowed). Hard limits at every level: answer first; humour never changes facts; no jokes in confirmations/approvals, money lost, errors, bad news, health, safety, grief, or about other people; never mock third parties; original lines only — never quote films; never claim to be the film character or imitate the actor. Three persona variants, each a stable cacheable string. `PERSONA_VERSION` → `p4.0`. Applies to every brain (no private data involved). | Owner asked for film-like wit "or a little more". |
| D9 | **Costs in ₹, free allowance aware.** Usage counted per month (IST) in the existing meter: TTS characters per voice type, STT seconds. Priced only above Google's free allowance (config: 1,000,000 chars per voice type; 3,600 s STT) at list price × the day's ₹ rate; rupees fixed at the moment of spend. `Billing.ensure_allowed` before any call that would be priced; at the limit → 402 `budget_reached` → console falls back to the browser voice / browser recognition with a one-line note. Allowance figures are JARVIS's own use only (Google's allowance is per billing account). | Owner rule: all costs in INR, show month total vs limit. |
| D10 | **Availability is graceful.** Cloud voice needs the two APIs enabled in the project. A 403 `SERVICE_DISABLED`/`PERMISSION_DENIED` marks cloud voice `unavailable` (reason `api_disabled`) for 10 min; `GET /v1/voice` reports it; the console uses the browser voice and shows a plain "how to switch on" line. Voice list validated against `GET v1/voices?languageCode=en-GB` (cached 24 h; unknown ids hidden). | Voice works right after merge, better after the one Cloud Shell step. |
| D11 | **Approvals are never given by voice** in this slice. When a spoken turn produces an approval card the console says a fixed, wit-free line: "That one needs your approval on screen, {honorific}." | Confirm-before-commit; a TV or recording could say "approve". Speaker verification is a later slice. |
| D12 | **"Hey Jarvis" wake word, on-device, opt-in per device.** openWakeWord pre-trained `hey_jarvis` + melspectrogram + embedding ONNX models run in the browser on onnxruntime-web (MIT), self-hosted under `/static/` with pinned sha256s; loaded only when the switch is on. Audio never leaves the device until the wake word fires. Paused while JARVIS speaks. CSP adds only `'wasm-unsafe-eval'` to `script-src`. **Licence:** openWakeWord code Apache-2.0; pre-trained models **CC BY-NC-SA 4.0 — personal, non-commercial use only; must be replaced by a self-trained model before any public launch (Phase 7)**; attribution in `static/wakeword/LICENSE.txt` and the Voice panel. If the port isn't reliable in this slice it ships as 9b. | Owner's "JARVIS" moment without streaming room audio to anyone. |
| D13 | **Privacy.** No audio stored anywhere; transcripts and spoken text never logged (lengths only); voice endpoints owner-only, rate-limited, `X-Requested-With: JARVIS` on cookie writes. A spoken message is an owner message like a typed one. | Private by default. |

## 2. Limits
speak: 1–1,200 chars in, ≤ 600 speakable chars per call, ≤ 60 calls/min · transcribe: audio/wav PCM16 mono 16 kHz only, ≤ 2,000,000 bytes (Content-Length checked first, then capped read), 0.3–60 s, ≤ 30 calls/min · Google call timeout 10 s · rate 0.8–1.25 · voice list cache 24 h · unavailable cache 10 min · settings cache 30 s (invalidated on PUT).

## 3. API (owner identity; client `user_id` ignored)
- `GET /v1/voice` → `{cloud:{tts:"ready"|"off"|"unavailable", stt:…, reason:str|null}, settings:{voice, rate, wit}, voices:[{id,label,style,type,available}], wit_levels:[{id,label,description}], allowance:{tts:{used_chars, free_chars, by_type:{chirp3-hd:{used,free}, studio:{used,free}}}, stt:{used_seconds, free_seconds}}, month:{voice_inr}, language}`
- `PUT /v1/voice/settings` `{voice?, rate?, wit?}` → settings · 422 `input_rejected` on unknown voice / wit / rate out of range.
- `POST /v1/voice/speak` `{text, voice?, rate?}` → `200 audio/mpeg`, headers `X-Jarvis-Chars`, `X-Jarvis-Cost-Inr` · 422 `nothing_to_say` / `input_rejected` · 402 `budget_reached` · 503 `voice_unavailable` `{reason: api_disabled|not_configured|upstream_error|timeout}` · 429.
- `POST /v1/voice/transcribe` body `audio/wav` → `{text, confidence, seconds, cost_inr, language, no_speech}` · 413 `too_large` · 422 `bad_audio` · 402 · 503 as above.
- `ChatRequest.channel` (`/v1/chat`, `/v1/chat/stream`). Errors use the app's existing `{detail:{code,message}}` shape.

Sample line for previews (server-fixed, original): "Good evening, {honorific}. Systems are running smoothly — which, I'm told, is my job."

## 4. Voice catalogue (default first; labels are Google's voice names + style)
`en-GB-Chirp3-HD-Algieba` (smooth) · `en-GB-Chirp3-HD-Sadaltager` (knowledgeable) · `en-GB-Chirp3-HD-Charon` (informative, deeper) · `en-GB-Chirp3-HD-Iapetus` (clear) · `en-GB-Chirp3-HD-Schedar` (even) · `en-GB-Studio-B` (formal, crisp; US$160/1 M above the allowance). Browser fallback picks the best `en-GB` male system voice (prefers names containing Ryan, George, Daniel, Arthur, "UK English Male").

## 5. Console
Mic button in the composer (tap = listen; tap again = stop & send; tap while speaking = barge-in + listen; Esc cancels; Ctrl+Space toggles); live level ring; status pill LISTENING / SPEAKING; Core scene listening/speaking states from real levels. Browser engine shows interim words. "Send what I say straight away" (default on). Speak replies: *When I speak* (default) / *Always* / *Never*. Keep listening after replies (default on, 6 s window). **Voice panel** (dock; phone → More): voice list with ▶ Preview, Speed, Wit (3 levels with descriptions), Speech engine, Voice finish, the two switches, "Hey Jarvis" (this device, off by default, privacy + licence note), allowance line in ₹, cloud status with a plain fix. Mic-blocked help text. No "$" anywhere. aria-live states, keyboard operable, reduced motion respected, ≥ 4.5:1 contrast.

## 6. Evals (`evals/voice`, in `make eval-mock`)
Mock: speakable shaping ≥ 40 cases (100 %); chunker (browser test); persona assembly per wit level contains every hard limit, voice trailer only on `voice`; billing — ₹0 within allowance, priced above, 0 priced calls past the limit (negative control: gate off → fails); provider error mapping; transcribe input validation (non-WAV, stereo, 44.1 kHz, oversize, too short). Real (`--real`, needs the key): 16 prompts × wit `film` → Haiku judge: answer first, ≤ 1 quip, addresses Sir, no film quotes, voice channel ≤ 80 words and no markdown; 6 sensitive prompts (approval, money lost, bad news, health) → no jokes. Wake word: JS ↔ Python openWakeWord parity on the same audio (scores within 0.02), detection on available positive clips, no detections on noise/silence.

## 7. Deploy
`cloudrun.sh` enables `texttospeech.googleapis.com speech.googleapis.com` and grants `jarvis-run` `roles/serviceusage.serviceUsageConsumer` (harmless if not needed). Owner one-time step after merge (Cloud Shell): `gcloud services enable texttospeech.googleapis.com speech.googleapis.com`. Config: `JARVIS_VOICE_CLOUD` (default on), `JARVIS_VOICE_LANGUAGE` (en-IN).

## 8. Not in this slice
Voice approvals / speaker verification; cloud streaming STT; Gemini-TTS style-prompted voice (≈ ₹0.5/reply, no free tier — candidate upgrade); ElevenLabs/Piper adapters; background listening on phones; languages other than English.

## 9. Review log
(build notes, deviations, findings and fixes appended below)

### Build notes (backend)

Built test-first on the backend branch (`jarvis.voice`, `api/voice.py`, billing units, persona,
deploy, `evals/voice`). The worktree started from `main` (df6b8b5, without this plan or slice 8);
it was fast-forwarded to `slice9-voice` (821abda) before any work.

**API contract as built — the console must use these exact names.**
- **Error shape: the app's real one, `{"error": code, "detail": "plain words"}`** — not
  `{detail:{code,message}}` as §3 says. Every existing endpoint and the console's `api()` helper
  use `{error, detail}`; §3's wording was a slip. `503 voice_unavailable` adds a top-level
  `"reason"` (`api_disabled | not_configured | upstream_error | timeout`); 429s carry `Retry-After`.
- Codes: `402 budget_reached` · `503 voice_unavailable` · `503 budget_unavailable` (limit or month
  record unreadable and the call would be priced; also `GET /v1/voice` when the month can't be
  read) · `429 rate_limited` (speak > 60/min, transcribe > 30/min, per owner) · `429 voice_busy`
  (Google throttled us; `Retry-After: 10`) · `422 input_rejected` (unknown voice / wit, rate
  outside 0.8–1.25, text missing / empty / > 1,200 chars, Google refused the voice or text) ·
  `422 nothing_to_say` (nothing speakable after `speakable()`) · `422 bad_audio` (not
  `audio/wav`|`audio/x-wav`|`audio/wave`|`audio/vnd.wave`, or not 16 kHz mono PCM16 0.3–60 s) ·
  `413 too_large` · `403 csrf` · `401`. Pydantic type errors keep FastAPI's `{"detail": [...]}`.
- Preview: `POST /v1/voice/speak {"preview": true, "voice": "<id>"}` (no text; any text is
  ignored) reads the server-fixed sample line with the honorific. It is metered like any speak.
- Speak response headers: `X-Jarvis-Chars` (speakable characters sent and billed),
  `X-Jarvis-Cost-Inr` (4 decimals, e.g. `"0.0000"` inside the allowance), `Cache-Control: no-store`.
  `voice` / `rate` in the body override the saved settings for that call only.
- `GET /v1/voice` additions (additive to §3): `allowance.tts.type` — the owner's current voice
  type, which `used_chars` / `free_chars` describe (`by_type` has both types); `month.month`
  (`YYYY-MM`, IST). `voices[]` always lists the whole catalogue; `available` is false when cloud
  TTS isn't ready or Google's list (cached 24 h) lacks the id — the console hides those.
  `cloud.reason` is the TTS reason, else the STT one; `off` (JARVIS_VOICE_CLOUD=false) has reason
  `null`, and speak/transcribe then answer `503 voice_unavailable` / `not_configured`.
- `transcribe` response: `language` is the configured `JARVIS_VOICE_LANGUAGE`; `seconds` is the
  audio length; `cost_inr` is this call's rupees; `no_speech` is true when the text is empty.

**Decisions.**
- Billing (D9): the usage month record gains `units {"tts_chirp3-hd", "tts_studio",
  "stt_seconds"}`; `UsageMeter.add_units` counts and prices in ONE transaction (only the part above
  the allowance, at list price × the day's rate), so two calls can't both use the last free units.
  Priced voice spend is the `voice` entry of `by_brain` (label "Voice") and counts in `calls`; a
  free call counts units only. Every meter write goes through one encoder, so chat spend never
  drops the voice counters. Gate (`Billing.ensure_units_allowed`): a call the allowance still
  covers always goes ahead (also at the limit); a priced one is refused at the limit (402, voice
  wording, no "$"); unreadable limit/month → 503 only when the call would be priced. STT is priced
  on Google's `totalBilledTime` when returned, else `ceil(duration)` (the gate uses the latter).
- Availability (D10): any Google 403 → `api_disabled` (covers SERVICE_DISABLED, PERMISSION_DENIED,
  billing off); it and `not_configured` are remembered 10 min per API (no calls meanwhile); 401
  drops the token (refresh next call) → `upstream_error`; 400/404 → `input_rejected`; 5xx /
  unreadable bodies → `upstream_error`; timeouts → `timeout`; nothing is retried (a late voice is
  worse than the browser voice now).
- Credentials: `jarvis.voice.adc` is the only google-auth import (loaded only when cloud voice is
  on); discovery and refresh run in a worker thread under a lock. Discovery has its own 5 s bound,
  and a timeout there counts as `not_configured` (off Google Cloud google-auth probes the metadata
  server for ~10 s; on Cloud Run it answers in ms); refresh timeouts stay transient. User ADC
  (local dev) sends `x-goog-user-project`. No network call at start-up.
- Persona (D7, D8): three variants built once per Brain; the Brain asks `VoiceService.wit_for`
  (settings cache 30 s, own 1 s bound, a failure remembered 30 s; the Brain's outer bound 1.5 s) →
  any failure is `film`. The wit level applies to every model call of the turn, including approval
  narration (its hard limits forbid jokes there) and training brains, which keep every restriction.
- Settings live at `{prefix}voice_settings/{uid}` like every other collection. Stored nonsense
  reads as the default field by field.
- Privacy (D13): logs carry lengths, voice id, seconds and rupees only; Google's error text never
  leaves the adapter (only its machine reason, e.g. `SERVICE_DISABLED`, is logged). A test plants
  marker words in speech and transcripts and checks no log line contains them.
- Deploy (§7): no new secret or env var (ADC; cloud voice defaults on). The summary prints the
  one-time `gcloud services enable …` line.

**Not verified.**
- No live Google call was made: request/response shapes, `speakingRate` on Chirp 3 HD, the
  `latest_short` model for `en-IN`, the `totalBilledTime` format and the 403 error bodies follow the
  public docs and are exercised against mocks only. First real check: `GET /v1/voice` then a
  preview on the deployed service after the Cloud Shell step.
- Whether `roles/serviceusage.serviceUsageConsumer` is all `jarvis-run` needs on the owner's
  project (expected: the speech APIs need no other role), and Cloud Run ADC end to end.
- Google's STT billing increment (the v1 page has used 15 s and 1 s rounding at different times):
  JARVIS meters Google's own `totalBilledTime` when present.
- The Firestore-emulator round trip of the voice documents (`tests/test_voice_storage.py`) runs
  only in CI's emulator job; `evals/voice/run.py --real` was not run (needs the key; spends money).
- The fresh-context code / Python / security reviews from CLAUDE.md were not run in this build
  session.

### Build notes (wake word)
**Shipped.** `static/console-wakeword.js` (registered in `APP_ASSETS`; the console builder adds the `<script … defer>` tag and the Voice-panel switch) exposes exactly `window.JarvisWake = {supported, load, start, pause, resume, stop, state, threshold}`. Vendored, pinned and hash-checked (`MANIFEST.txt` in each folder, verified by `tests/test_wakeword_assets.py`): onnxruntime-web **1.30.0** (npm, published 2026-09-14; tarball matched the registry sha512) — only `ort.wasm.min.mjs`, `ort-wasm-simd-threaded.mjs`, `ort-wasm-simd-threaded.wasm` + MIT licence and ThirdPartyNotices — under `static/vendor/ort/`; openWakeWord **v0.5.1** release models `melspectrogram.onnx`, `embedding_model.onnx`, `hey_jarvis_v0.1.onnx` + Apache-2.0 code licence + `LICENSE.txt` (CC BY-NC-SA 4.0 attribution and the "personal, non-commercial; replace with a self-trained model before any public launch" warning) under `static/wakeword/`. 18.35 MB on disk, of which the WASM binary is 14.2 MB (3.7 MB gzipped).
**Serving.** `/static/vendor/ort-1.30.0/{name}` and `/static/wakeword/oww-0.5.1/{name}`: exact allow-lists (the existing vendor route now also knows the ORT release), `application/wasm` / JS / `application/octet-stream`, `nosniff`, a year-long `immutable` cache (the release is in the URL). Licence and MANIFEST files are on disk and in the wheel but not served. `package-data` covers both folders; `.dockerignore` keeps them.
**CSP.** `script-src 'self' 'wasm-unsafe-eval'` — the only change (needed to compile WebAssembly; it does not allow `eval`/`new Function`). No `worker-src`, `blob:` or host was needed: `env.wasm.numThreads = 1`, `env.wasm.proxy = false`, `wasmPaths` = our same-origin folder, so onnxruntime never starts a worker or makes a blob URL (it only does that for cross-origin paths). The browser tests spy on `Worker`/`SharedWorker` (0 created) and `securitypolicyviolation` (0) on a page with the console's exact CSP *and* on the real console page.
**Pipeline (port of openwakeword 0.6.0 `AudioFeatures._streaming_features` + `Model.predict`).** Per 1280-sample frame: int16 → float32 (unscaled) → melspectrogram model on the frame plus the previous 480 samples (only the frame on the first step) → `x/10 + 2` → append to a 76-row buffer that starts as ones → embedding model on the newest 76 rows → append to the embedding history → `hey_jarvis` on the newest 16 embeddings; scores are 0 for the first 5 frames after a reset. Every stream starts from embeddings of 4 s of noise in [-1000, 1000) like upstream.
**Deviations.** (1) The seed noise comes from mulberry32 with a fixed seed instead of numpy's unseeded RNG (deterministic, same range); the reference script installs the same noise in Python. (2) Detection = 2 consecutive frames ≥ `threshold` (0.5, openWakeWord's recommended default). openWakeWord 0.6.0's own `patience` option was not reused: it compares against the already-filtered prediction buffer and so never fires (checked: `patience=1` or `2` gives 0 detections on a clip that scores 0.999), so this implements its documented intent. The committed near miss "Hey Travis, have you seen Marcus?" (flite awb) peaks at 0.674 for a single frame and is rejected only because of this rule. (3) After a wake: 2 s cooldown (clock time) and openWakeWord's `reset()` (fresh buffers, 5 warm-up frames). (4) Input is consumed in 1280-sample frames; a source sending other sizes is re-chunked (Python would batch them). (5) Speex noise suppression and the Silero VAD gate (both optional, off by default upstream) are not ported; the capture pipeline's `getUserMedia` noise suppression stands in. (6) Backlog: > 12 frames (~1 s) awaiting inference are dropped and the stream resyncs; 3 drops within 30 s → `state = 'error'` (device too slow). `pause()` drops audio; `resume()` restarts from fresh buffers (0.4 s warm-up). Errors: `load()` rejects `.code` `load_failed`/`unsupported` (`state 'error'`, a later `load()` retries); `start()` throws `not_loaded`/`bad_source`/`bad_callback`; `stop()` clears an error. There are no events — the console reads `JarvisWake.state`.
**Parity (`tests/fixtures/wakeword/make_reference.py` → `reference_scores.json`, Python openwakeword 0.6.0 on onnxruntime 1.30.0).** No real "hey jarvis" recording could be obtained offline (openWakeWord's repo ships no such clip; Hugging Face is blocked here), so fixtures (≈ 650 KB) are synthetic: 5 positives (CMU Flite voices kal, kal16, awb, rms, slt via ffmpeg's libflite) and 5 negatives (two spoken weather sentences, the near miss, 2 s silence, 3 s white noise). In headless Chromium every per-frame score matches Python within **2 × 10⁻⁶** (488 frames; the JSON is rounded to 6 decimals; the test allows 0.02). Through the public API all 5 positives wake exactly once (score ≥ 0.99), all 5 negatives never; a second "Hey Jarvis" 0.4 s after the first is held back by the cooldown and detected when the clock is moved 2 s on. Mutation check: patience 1 or cooldown 0 each fail a test. Seen while choosing clips (not committed): the plain flite awb "Hey Jarvis" peaks at 0.44 (missed), and flite slt "Hey Travis…" has 3 frames ≥ 0.5 (would wake) — limits of the model, not the port.
**Speed.** Per 80 ms frame in headless Chromium on this 2-vCPU Xeon container: median 4.2–4.7 ms, p95 5.7–12.5 ms, max 10.7–44 ms when quiet; median 7.5 ms, p95 25 ms while the whole browser suite ran alongside. The test asserts median < 20 ms (desktop target) and p95 < 80 ms (the real-time budget). First `load()` including the 18 MB download from localhost: 1.1 s (2.8 s on the busy box).
**Not verified.** A real microphone and the console's capture pipeline (D4 resampling to 16 kHz Int16 frames is the console builder's); real voices, accents and rooms (far field, TV, music); Safari and Firefox (onnxruntime-web 1.30.0 needs WebAssembly SIMD: Safari ≥ 16.4); phones and low-end CPUs; how often it false-wakes over hours of household audio.
**Follow-ups.** Compress the 14.2 MB WASM (pre-compressed `.wasm.gz`/brotli or compression for `/static/vendor/` only — 3.7 MB gzipped); it downloads once per device, only after the owner switches the wake word on. Replace the CC BY-NC-SA models with a self-trained one before Phase 7 (D12). Consider a state-change event if the console needs one.

### Build notes (console)

Built on the console branch (fast-forwarded to `slice9-voice` 821abda, then merged with the backend
at ee859a2). New: `voice-capture-worklet.js`, `console-voice-capture.js` (`JarvisAudio`, `JarvisWav`,
`JarvisVad`), `console-voice-speech.js` (`JarvisSpeechChunker`, `JarvisSpeaker`), `console-voice.js`
(Voice panel, settings, engines, the shared speaker → `JarvisVoice`), `console-voice-mic.js`
(composer mic, spoken turns, "Hey Jarvis" wiring), `console-voice.css`. Changed: `console.js`,
`console-fx.js` (pill), `console-deck.js` (panel order, Core label), `console-3d*.js` (Core level),
`console.html`, `console.py` (`APP_ASSETS`). CSP unchanged (`audioWorklet.addModule` is `script-src
'self'`); the wake-word builder adds `'wasm-unsafe-eval'` and its own `<script>`.

**Contract as the console uses it.** `GET /v1/voice` (cloud.tts/stt/reason, settings, voices with
`available` — only those shown, wit_levels, allowance.tts.used_chars/free_chars,
allowance.stt.used_seconds/free_seconds, month.voice_inr, language) · `PUT /v1/voice/settings`
`{voice?, rate?, wit?}` · `POST /v1/voice/speak` `{text, voice, rate}` or exactly `{preview: true,
voice}` → audio bytes into `decodeAudioData` · `POST /v1/voice/transcribe` raw WAV with
`Content-Type: audio/wav` → `{text, no_speech}` · `/v1/chat` body gains `channel: "voice"` (only on
spoken turns). Every call carries `X-Requested-With: JARVIS` (+ the bearer token in token mode)
through console.js. Errors read as `{error, detail, reason}` + `Retry-After` (console.js `api()` now
also sets `err.code` from `error`).

**Decisions and deviations.**
- **Spoken turns use `/v1/chat` (JSON), not `/v1/chat/stream`** (deviation from D6's "streamed"
  reply). The console never streamed, and the stream route returns no session id, runs no tools and
  carries no approvals — a voice turn there could not keep a new conversation, use Calendar/Gmail or
  give D11 its approval card. `JarvisSpeechChunker` is streaming-ready (`push(delta)`, identical
  output whole or char by char, tested); fed the whole reply, the first sentence is still its own
  chunk, so first audio = one short TTS call after the reply.
- `window.JarvisChat` {send(text, {channel}), busy(), honorific(), raw()} is a new frozen global:
  `JarvisConsole`'s exact shape is pinned by a test. Events: `jarvis:turn` / `turn-end` /
  `answer {channel, text, approvals}` / `switch` (console.js), `jarvis:speech`, `jarvis:wake`,
  `jarvis:voice-config` / `voice-device`.
- Engines: Automatic = cloud → this browser → typing. A chosen engine is never swapped for another
  (audio never goes where the owner didn't pick; the mic help says how to switch). Under Automatic a
  transcribe 402 / 503 / `voice_busy` marks cloud listening down (10 min; `Retry-After` for busy)
  and the browser's recognition starts at once ("Say that again: this browser is listening").
- Speak refusals: 402 / 503 → browser voice for 10 min; `voice_busy` → for Retry-After; network,
  `rate_limited`, other 422 / 5xx → browser voice for that reply; `nothing_to_say` → chunk skipped.
  One note per page load. Chunks are fetched one ahead; on a fallback the in-flight fetches abort.
- D11: a spoken turn that leaves an approval waiting speaks only "That one needs your approval on
  screen, {honorific}." (never the reply's words), with no conversation-mode re-listen; no voice
  script calls an approvals endpoint (unit-tested).
- The capture AudioContext is made inside the tap; the microphone closes after each capture unless
  "Hey Jarvis" is on (the browser's mic light goes off). The browser engine does not open our
  capture (no second mic consumer), so its ring "breathes" instead of showing a level.
- "Hey Jarvis": frames reach `JarvisWake` through a gate that drops them unless the mic is idle and
  nothing is playing (no pause API needed); `start()` may return `{stop()}` or the module's `stop()`
  is used. Saved on, after a reload the context may wait for a gesture: the chip says "tap anywhere"
  and the first tap or key resumes it. A start error switches the setting off with a plain line.
- Allowance line uses the spec's grouping ("12,340 of 1,000,000 free characters · 3 of 60 free
  minutes · ≈ ₹0.00": minutes used round up); rupees via `JarvisDeck.rupees`. No "$" (unit test
  over every voice script; browser test over the page text).
- Pill precedence: Offline > Listening / Speaking > Thinking > Needs you. Reduced motion: Off = no
  level visuals; Calm = the ring shows the level by brightness, never size; the 3D Core follows
  levels only under Full (Calm/Off render still frames on state changes).
- Hazard found: the authoring tool turned `\u2028`-style escapes into literal characters (a literal
  U+2028 ended a regex: a page error). Fixed, and a unit test now rejects literal invisible / bidi /
  line-separator characters in every console source.

**Tests.** Unit: `tests/test_console_assets.py` (voice assets served, no HTML sinks / fetch / hosts,
order, contract strings, worklet allow-list, panel + dock + More wiring, no "$", no invisible
characters). Browser (`tests/browser/test_voice.py`, fake microphone = a generated speech-like WAV,
`/v1/voice*` route-mocked): chunker (fences, tables with and without outer pipes, URLs, "Mr.",
"e.g.", "a.m.", "₹1,234.50", lists, ellipses, initials; streamed = whole), WAV header, VAD start /
end / 6 s timeout / 30 s cap, worklet resampling 48 and 44.1 kHz offline (pitch kept, 12 kHz alias
filtered), live 1280-sample Int16 frames at 12.5/s, mic → VAD → WAV → transcribe → `channel: voice`
→ reply spoken in order → conversation re-listen, browser engine interim words, send-straight-away
off, barge-in, Esc + new conversation silence, 503 / 402 / voice_busy fallbacks, transcribe 503 →
browser recognition, chosen cloud engine never swapped, the approval line, mic blocked help,
Ctrl+Space / Esc, Voice panel (available voices only, debounced + serialized PUTs, preview body,
device settings persisted, 422 reload, four cloud statuses, 404 "not available"), "Hey Jarvis"
hidden without `JarvisWake` and wired to a stub, phone layout, contrast Night + Day, no "$", 0 JS
errors, 0 CSP reports. `tests/browser/test_voice_live.py` runs the real app with only Google faked
(`voice_live_server.py` + `tests/voice_fakes.py`): panel round trip + preview, and a whole spoken
turn through the real WAV check, transcription, chat and /speak, with the allowance counting it.

**Not verified.** A real microphone and speakers (echo cancellation against Web Audio playback,
AGC / noise-suppression effect on the energy VAD's thresholds in a real room), Safari and Firefox
(AudioWorklet resampling, `webkitSpeechRecognition`, autoplay / resume rules, MP3 decoding — tests
decode WAV), Android Chrome with SpeechRecognition while "Hey Jarvis" holds the mic, the real
`console-wakeword.js` (only a stub), the Comms finish by ear, the 3D Core's level response on a real
GPU (headless only), real Google voices, and contrast on themes other than the default (Night and
Day measured). The fresh-context reviews from CLAUDE.md were not run in this session.

### Review findings and fixes (backend)

Two fresh-context reviews of the backend; every item fixed test-first (failing regression test
seen red, then green; mutation-checked where the fix is a guard). Where a fix needed judgement
the safer option was taken (noted). D9, §2 and §7 above are superseded where this table differs.

| # | Sev | Finding | Fix | Test |
|---|---|---|---|---|
| 1 | MED | Free allowance drift: Google's free tier is per billing account on Pacific-time months; JARVIS counted per owner on IST months, and never metered a call that timed out after it was sent. | One counter for the deployment, `{prefix}allowance/{YYYY-MM}` keyed by the America/Los_Angeles month; ₹ stay in the owner's IST month (`UsageMeter.add_units` reads the counter, prices the excess, adds ₹ to the caller's month and counts — one transaction). Defaults are 90 % of Google's: `JARVIS_VOICE_TTS_FREE_CHARS=900000` per voice type, `JARVIS_VOICE_STT_FREE_SECONDS=3240`; README/.env.example say to set both to 0 on a shared billing account. `VoiceUnavailable.maybe_billed` (sent then timeout / broken connection, or an unreadable 2xx) and a cancel mid-call meter the estimate (chars sent / ceil of audio s); clean 4xx/5xx and connect/pool/credential failures don't. GET /v1/voice shows the effective allowance plus `allowance.month`, `allowance.resets_at`, `allowance.scope: "deployment"`. | `test_voice_billing` (shared by owners, Pacific vs IST month at the boundary, resets_at), `test_voice_api::test_a_failed_call_that_may_have_reached_google_is_still_metered` (7 cases), `test_voice_service` (cancel mid-call), `test_voice_settings` (90 %, env names, docs), evals billing v01–v18 + errors e18 |
| 2 | MED | Spoken turns fully trusted: a TV / auto-send / keep-listening could save memories, drafts, events without a card. | `channel == "voice"` runs tool calls under `context_trust(untrusted=True, spoken=True)`; the gateway tightens every non-read-only ALLOW to ASK while spoken (not only memory_save). Safer extra: a presented approval token now always goes through the gate, so a card made on a spoken turn and approved on screen spends its token and can never run twice. `Turn.channel` records how an owner message arrived; the learning snapshot skips voice turns. (The stream path calls no tools; its turns are marked and skipped by learning.) | `test_voice_trust` (draft/memory card on voice, typed unchanged, reads run, approve once, gateway unit, learning skip stream + non-stream) |
| 3 | LOW/MED | Gate and meter not atomic: concurrent speak/transcribe at the allowance edge or the limit could all pass. | Per-owner `asyncio.Lock` per kind (tts, stt) held across gate → Google → meter (one instance in production). STT is gated on ceil(duration) and billed on Google's `totalBilledTime` when returned (documented in `voice/service.py`). The allowance is deployment-wide but the lock is per owner, as asked: two owners racing at the edge can overshoot by at most one call (the count stays exact). | `test_voice_service` concurrent speak / transcribe (mutation: no lock → fails), per-kind independence |
| 4 | LOW | A corrupt `units` map decoded to 0 (fail open). | A bad value under a counter key → `UsageUnreadable` for that key (priced calls under a limit → 503 `budget_unavailable`; GET /v1/voice → 503; the meter writes nothing for it and keeps the bad value as stored when writing other keys); a non-map `units` → all unreadable. Mirrors `inr_total`: with no limit set, calls still go ahead and their meter write fails (logged). | `test_voice_billing` corrupt counter / map cases, `test_voice_api::test_a_corrupt_allowance_counter_fails_closed_for_priced_calls`, evals v17–v18 |
| 5 | MED | GET /v1/voice blocked on Google's voice list; failures not cached; no per-owner rate limit. | Adapter remembers a failed list (timeout, 5xx, 429) 60 s. The view waits ≤ 2 s for one shared, shielded fetch that keeps going in the background (timeout → availability unknown, the whole catalogue listed as available while TTS is ready). GET /v1/voice and PUT /v1/voice/settings ≤ 60 a minute per owner (429 `rate_limited` + Retry-After). | `test_voice_google::test_a_failed_voice_list_is_remembered_for_a_minute`, `test_voice_service` (bounded view, one fetch for concurrent views), `test_voice_api` rate-limit tests |
| 6 | LOW | ADC refresh made a new `Request()` (unclosed `requests.Session`) each time; a timed-out refresh thread kept running while the next caller started another. | One transport per `AdcTokens`, closed by `close()` (called from `VoiceService.aclose` in the app lifespan; `TokenSource.close` added to the port). A refresh is a single in-flight task every caller awaits (shielded, own timeout). | `test_voice_google::test_adc_reuses_one_transport_and_closes_it`, `…_awaited_by_the_next_caller_not_restarted` (mutation: always start → fails), `test_voice_service` close |
| 7 | MED | The 10 s timeout wasn't a total deadline (credential lookup + refresh outside it; httpx timeout per phase). | `async with asyncio.timeout(12 s)` around credentials + request; `httpx.Timeout(10, connect=3)`; `TimeoutError` → `VoiceUnavailable("timeout")` (`maybe_billed` only if the request had been handed to httpx). | `test_voice_google::test_one_total_deadline_covers_credentials_and_the_request`, runtime client timeout, error-mapping table |
| 8 | LOW | Deploy: the speech APIs were in the required `gcloud services enable` under `set -euo pipefail`; an org policy blocking them stopped the deploy. | Own command, `\|\| say "…the browser voice will be used."`; the `serviceUsageConsumer` grant moved out of the must-succeed loop to a non-fatal `try_bind` with a note. **Decision: the grant is kept** — it only allows using APIs that are already enabled, and avoids a second owner step if Google requires it. | `test_deploy_config` (separate non-fatal enable, non-fatal grant helper without `die`, never removed, script parses) |
| 9 | LOW | After a failed wit read, a successful PUT of a new wit was ignored for up to 30 s. | `update_settings` clears the per-owner failure memo. | `test_voice_service::test_a_put_clears_the_failure_memo…` |
| 10 | LOW | Wit read on every model call of the tool loop. | Read once per turn in `_chat` (and once per approval narration) and passed down with the trailer (`_Prompt`), as the stream path did. | `test_voice_persona::test_the_wit_level_is_read_once_per_turn…` |
| 11 | LOW | `speakable()` changed meaning. | digit `*` digit → "times"; `~`digit → "about "; only real HTML tag names stripped ("x <y and z> w" survives); one level of parentheses in markdown link/image targets; `_HAS_WORD = [^\W_]`. | `test_voice_speakable` (12 + 4 cases), evals s58–s67 (67 cases) |
| 12 | LOW | `core/brain.py` over 800 lines; duplicated capped-body readers. | Persona/wit selection → `core/persona.py` (`Persona`, `WitSource`; brain.py 793 lines); one `read_capped(request, limit, too_large=…)` in `api/body.py` used by transcribe and memory import. | size guard in `test_voice_persona`, `test_body_limits::test_read_capped_is_the_one_shared_helper` |
| 13 | LOW | Settings read in speak and GET had no time bound. | `settings_of` uses the same 1 s bound + 30 s failure memo as the wit read (one memo, shared); fallback: default voice / rate / wit. | `test_voice_service::test_speak_and_the_view_never_hang…` |
| 14 | LOW | STT model. | `latest_short` for clips ≤ 15 s, `latest_long` above (both take en-IN with punctuation per Google's language table — not verified live). | `test_voice_google::test_recognize_picks_the_model_by_clip_length` |
| 15 | LOW | JSON bodies parsed before auth with no size cap (all routes). | `BodySizeLimit` pure-ASGI middleware (innermost, so the trace id is still set): Content-Length > 2,100,000 → 413 `too_large` before reading; chunked bodies cut off at the same size (`BodyTooLarge`, an `HTTPException` so FastAPI's parser passes it on). Per-route caps (transcribe 2,000,000, import 512 KB) still apply first with their own messages. | `test_body_limits` (with and without Content-Length, four routes, route caps, mutation: cap off → fails) |
| — | check | Film/Extra example lines must substitute the honorific. | Already correct (`{honorific}` in the rule text); now covered. | `test_voice_persona::test_the_film_and_extra_example_lines_use_the_configured_honorific` |

**API changes the console must know.** `GET /v1/voice` `allowance` gains `month` (Pacific
`YYYY-MM`), `resets_at` (ISO 8601, the next 1st 00:00 America/Los_Angeles) and `scope`
(`"deployment"`); `free_chars` / `free_seconds` are the effective figures (900,000 / 3,240 by
default, 0 on a shared billing account); `used_*` are the whole deployment's this Pacific month.
New statuses: `429 rate_limited` on GET /v1/voice and PUT settings (60 a minute); `503
budget_unavailable` on GET /v1/voice when the allowance counter is corrupt; `413 too_large` on any
route for a body over 2,100,000 bytes. On a spoken turn every write tool comes back as a pending
approval card (D11's fixed line applies). `GET /v1/sessions/{id}` turns carry `channel`.

**Not verified (in addition to the build notes).** Google's real billing of timed-out requests
(JARVIS assumes it may bill them); `latest_long` en-IN quality; the 90 % margin against real
drift. CLAUDE.md's fresh-context `code-reviewer` / `python-reviewer` / `security-reviewer` passes
were not run on these fixes in this session (the gateway change touches tools: worth a security
review before merge).
