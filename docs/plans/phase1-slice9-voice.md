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
