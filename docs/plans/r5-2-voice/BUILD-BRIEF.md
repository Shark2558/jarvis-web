Version v5.2.0 · 27 Nov 2026, 15:00 IST · Release R5.2 · Status: Current · Owner: 🛠 Mark XXV

# R5.2 Your voice — build brief for the builder agents

Read first: `docs/plans/r5-2-voice.md` (the approved plan, v5.2.1+), `docs/plans/r5-2-integration/I0-SEAMS.md` (the seams you code against), `CLAUDE.md`, `.claude/rules/ecc/**`, and R18's seams you reuse: `docs/plans/r18-calls/I0-SEAMS.md`. The owner approved everything on 27 Nov and asked for autonomous, parallel building; every decision below is a safe default approved under that instruction. Anything that needs his hands (installing the kit, the 20-minute session, the 1-minute enrolment, the stage 2 training run) waits until he tests, and nothing is spent without his typed YES.

## Ground rules for every agent

1. Work only in your own git worktree and branch (below). Commit small, push after every commit: `git -c push.negotiate=true push -u origin <branch>`. Never force-push, never push to `main`.
2. Commit trailers (all four, every commit):
   `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>` / `Claude-Session: https://claude.ai/code/session_01KbmAkthzyK1jEx5wBXVxqW` / `JARVIS-Version: v5.2.0` / `JARVIS-Mark: XXV`.
3. Tests first; your own tests only, run once green. **Never run the whole suite** (the reviewer does). Any test run over a minute goes behind `flock /tmp/jarvis-heavy.lock`. Python: `/tmp/venv-12/bin/python` (3.12, `.[dev,homebridge]`); never `pip install` into it — a new dependency goes into `pyproject.toml` (cloud) or `deploy/local-speech/` (the kit) with a licence comment, and your report says so. CI runs plain `pytest` with the repo root not on `sys.path`: never `from tests.x import`. Tests use `MemoryKit` and synthetic audio; real models run only on the laptop (the kit's self-test prints a report the owner can paste).
4. `ruff check` and `mypy --strict` clean on the files you own. Types, error handling, logging (never log audio, transcripts, prompts' recordings, a voice print, the kit's key or the owner's Tailscale name), at least one test per behaviour.
5. Project non-negotiables: nothing outside `jarvis.llm` imports a cloud vendor SDK (Google is reached by `jarvis.voice`'s REST code, the kit over `httpx`); the kit's model runtimes (faster-whisper, Kokoro, Piper, onnxruntime, openWakeWord) are imported **only** inside V1's and V4's kit modules, lazily, are listed only in `deploy/local-speech/` (hash-pinned), never in `pyproject.toml`'s runtime dependencies, and the cloud app never imports those modules (V1 adds the import-guard test); every tool call goes through `jarvis.tools.gateway` (R5.2 adds no tool); secrets only via env/`SecretStr`; append-only audit where the plan touches tools.
6. **The speaker check never approves anything** (plan D6, slice 9 D11): not a tool call, a card, a passkey, an unlock or a Telegram approval. "Spoken by the owner" is a display label only. V5 adds the test that proves it.
7. UI: never change the console's look; new screens blend with the existing theme and tokens (ui-ux-pro-max guidance). Costs only in ₹.
8. The repository is public: no personal data, recordings, voice prints, the owner's city, employer or Tailscale name in code, tests, fixtures or docs. Use `my-laptop.tail1234.ts.net`-style names and synthetic audio (silence, tones, or openly licensed clips fetched at run time, never committed).
9. Licences (plan risk 2): every model file, voice, dataset and background-audio set is recorded with its licence and SHA-256 before it is downloaded or shipped; only `jarvis.localspeech.protocol.PERMISSIVE_LICENCES` (and `OWNER_LICENCE` for the owner's own wake-word files); anything unclear is left out and named in your report.
10. **Reuse R18, never copy it** (plan 3.2, 7a): R18 owns `src/jarvis/calls/**` (speech adapters, language detection, phone-line simulation, the language check and its scoring) and `src/jarvis/calldesk/**`. Call them; register into them only at R5.2's I1 join.
11. Your final report to the Workshop: **at most 150 words** — branch, head commit, what is done, what is not, any decision you took, any new dependency.

## Branches

`r5-2-i0` is the base (R18's `r18-i0` + the R5.2 plan + these seams + this brief). Builders branch from `origin/r5-2-i0`: `r5-2-v1`, `r5-2-v2`, `r5-2-v3`, `r5-2-v4`, `r5-2-v5`. The I1 join is `r5-2-i1`. Plan D8: R18's pull request is not merged yet, so R5.2 builds on R18's branches and its pull request names R18 as its prerequisite. When R18's I1 join (`r18-i1`) is final, it is merged into `r5-2-i0` and the seams doc says so; builders then merge `origin/r5-2-i0` again. Until then, code that needs R18's unjoined parts (`jarvis.calls.speech`, `jarvis.calls.langcheck`, `jarvis.calldesk`) codes against the shapes named in the seams doc and is tested with fakes.

## Decisions fixed for the build

| Topic | Decision |
|---|---|
| Release | R5.2 "Your voice", `v5.2.0`; the About line reads v5.2.0. It ships after R18 (v18.0.0): the number names the release, not an order (R6.3 followed R13.1 the same way); nothing compares `jarvis.__version__` |
| Rows | 81 (recognition on his voice), 83 (his own "Hey Jarvis"), 84 (the speaker check), 383 (local speech on the laptop) |
| The kit (D1) | A speech server on the laptop at `127.0.0.1:11437`, behind a Caddy gate at `127.0.0.1:11436` with the kit's key (≥ 32 characters, fail closed), published by Tailscale Funnel on https port **8443** (the offline brain keeps 443); the cloud reaches it only by `JARVIS_LOCAL_SPEECH_URL` (https `*.ts.net`, http refused) with `JARVIS_LOCAL_SPEECH_KEY`; the call desk on the same laptop uses `http://127.0.0.1:11436/v1` |
| Engines (D2, D3) | English: faster-whisper small int8 (medium int8 if the session shows it clearly better), Kokoro-82M British male (`bm_george` by default), Piper fallback. Indian languages: IndicConformer 600M int8 ONNX, Indic Parler-TTS, licensed Piper voices; R18's language check decides which languages use them. Loaded on demand (4 GB graphics card), CPU fallback; the kit reports `slow` so routing falls back |
| API | JSON; audio as base64 of 16 kHz mono PCM16 (R18's format); MP3 for the console's voice (`format: "mp3"`, since `POST /v1/voice/speak` answers `audio/mpeg`); requests and audio never logged |
| Recordings (D4) | The session's clips are stored on the kit only, encrypted at rest with a key only the kit holds; the cloud passes them through and keeps nothing; "Delete my recordings" removes them (and, if asked, the wake-word files trained from them) |
| Recognition (row 81) | Held-out prompts scored by word error and command accuracy for the browser, Google (with his words) and the laptop engines; the best becomes his default; repeating mishearings become corrections applied after listening (**never** to numbers, money or codes: enforced by `Correction`); new words join R5's existing "words to recognise" (`VoiceSettings.phrases`, ≤ 50) — no second list |
| Engine order (D7) | Console: `jarvis.voice.profile.listening_order` — the session's best → Google → browser; before a session, the laptop's Whisper small first while the kit is healthy (plan 7a). Calls: R18's selection with "laptop" first when it passed the language check |
| Wake word (D5) | Stage 1: openWakeWord's custom-verifier method trained on the kit from his session clips; exported as plain JSON weights the console applies after today's detector (laptop and phone browsers). Stage 2: an owned ONNX model in the console's format with its MANIFEST and `LicenseRef-Owner`, trained on the kit when he chooses (2–3 hours), swapped in only when it beats the old model on the evals; required before any launch (today's model is CC BY-NC-SA) |
| Speaker check (D6) | A small speaker-embedding model in the browser (vendored onnxruntime-web; WeSpeaker ResNet34 or 3D-Speaker CAM++, licence and training data verified first); enrolment from the session's clips on the laptop, 1 minute of reading elsewhere; the print stays in that browser, encrypted with a device key, never uploaded; barge-in only by his voice; an off switch per device; falls back to today's behaviour when not enrolled |
| Costs | ₹0 a month. The session's Google comparison uses ≈ 20 free minutes (`voice_session_compare_minutes`); beyond this month's free allowance the route answers **402 `needs_yes`** with the ₹ (≈ ₹2.29 a minute, at most ≈ ₹46) and runs only after his YES |
| Fallback | Kit off, slow or refusing → Google → browser, with the existing messages (a kit failure is never shown as a Google error) |
| VoiceStudio (D9) | The default parts above unless the owner names a specific project |

## Contracts

All in `docs/plans/r5-2-integration/I0-SEAMS.md` (import, don't copy): the kit's API (`jarvis.localspeech.protocol`), `MemoryKit`, the voice profile and its store, the route-facing ports, the routes under `/v1/voice/profile`, the config keys, and the R18 seams each builder calls.

## Who owns what (no two agents edit the same file; the I1 join wires the rest)

| Agent | Branch | Owns |
|---|---|---|
| I0 | `r5-2-i0` | `src/jarvis/localspeech/{__init__,protocol,memory}.py`, `src/jarvis/voice/{profile,profile_ports,profile_store}.py`, `src/jarvis/api/voice_profile_routes.py` (501 stubs) and its two-line mount in `api/voice.py`, `src/jarvis/config_voice.py` (+ its import in `config.py`), the layers map, the version bump to `v5.2.0`, this brief, `docs/plans/r5-2-integration/I0-SEAMS.md`. A builder who needs a seam changed says so in its report; it does not edit these files |
| V1 | `r5-2-v1` | `src/jarvis/localspeech/**` except I0's files, `client.py`, `desk.py` and `wakeword/**`: the server (the API above, `parse_request` on every body, `KitErrorBody` refusals), engines in their slots, the model manager (pinned files, SHA-256, licence files beside them, "what this kit installed"), jobs (the session's scoring runs), clip storage encrypted at rest, the self-test; `deploy/local-speech/**` (installer `.ps1`, start scripts, the Caddy gate for `protocol.ROUTES`, hash-pinned requirements, the model manifest with licences, README) |
| V2 | `r5-2-v2` | `src/jarvis/localspeech/client.py` (the real `KitClient` over `httpx`: `bearer`, `parse_reply`, `REPLY_MAX`, no redirects; the cloud's transport is `jarvis.offline.config.PinnedTransport` after `check_url`), `src/jarvis/localspeech/desk.py` (R18's `calldesk.speech_local.LocalSpeech` over `LOOPBACK_BASE`), `src/jarvis/voice/laptop.py` (adapters on `jarvis.voice.ports` STT/TTS, health cached `local_speech_health_s`, `LaptopApi`), `src/jarvis/voice/calls_bridge.py` (R18's `Hearing`/`Voice`, name `"laptop"`), the engine-routing edits in `src/jarvis/voice/service.py` (`listening_order`, corrections applied after listening), Vitals' engine line |
| V3 | `r5-2-v3` | The voice session: console screen and scripts (new files only, plus the smallest registration edit), `src/jarvis/voice/session.py` (the ~120 prompts in 4 blocks, clips to the kit via `KitClient`, the comparison and its ₹ question, scoring, the chosen engine, corrections and words), its handlers module `src/jarvis/voice/session_api.py` (`ProfileApi`), the privacy-dashboard source for the profile and the recordings |
| V4 | `r5-2-v4` | The wake word: kit-side training in `src/jarvis/localspeech/wakeword/**` (V1 leaves that folder to V4; V1's server calls it through a small interface V4 defines there), `src/jarvis/voice/wakeword_api.py` (`WakewordApi`), the console's verifier runtime and model swap (new console files + the smallest edit to `console-wakeword.js`), the MANIFEST and licence handling |
| V5 | `r5-2-v5` | The speaker check: console embedding runtime, enrolment and storage (new console files), the barge-in hook (the smallest edit to `console-voice-barge.js`), the model file and its licence, the "never approves" tests |

## After the builders

I1 join (`r5-2-i1`): merge R18's final branch if not yet in, merge all, wire `app.state.voice_profile_api`, `voice_laptop`, `voice_wakeword`, the profile store and the kit client; the one-line "laptop" registrations in R18's selection (`build_speech(..., laptop=...)`) and the call desk (`local=`); fix integration; run the touched tests once. Then the Book: new pages for `localspeech`, the voice profile and the speaker check, the guide's cards, the strict `pages --check` and `--narration-check` passing. Then one combined security + code review that fixes its findings and runs the one final check pass. Then the PR `v5.2.0 · R5.2 Your voice · Mark XXV`, naming R18's PR as its prerequisite.

## Change log

| Version | Date | Release | What changed | By |
|---|---|---|---|---|
| v5.2.0 | 27 Nov 2026, 15:00 IST | R5.2 | First edition: ground rules, decisions fixed for the build, ownership for I0 and V1–V5 (V2 also owns the kit's client and the call desk's hook in `localspeech/`), the join | 🛠 Mark XXV |
