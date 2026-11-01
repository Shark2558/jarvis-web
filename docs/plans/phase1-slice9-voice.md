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
