Version v5.2.3 · 27 Nov 2026, 22:20 IST · Release R5.2 · Status: Current (approved under the owner's 27 Nov instruction) · Owner: 🛠 Mark XXV

# R5.2 — Your voice: the plan

**Workbook rows:** 81 (recognition tuned on your own voice), 83 (your own trained "Hey Jarvis"), 84 (the speaker check: JARVIS knows it's you), 383 (local speech on your laptop, the VoiceStudio project, to cut voice costs). These are R5's items 7–9 and the local speech option weighed here, as `claude/release-plan-part-2.md` (R5) and `docs/plans/r5-voice.md` ("Needs you first") say.

**Order:** after R18 Calls (the owner's order of 17 Nov: calls → R5.2 → R8 → R8.1 → R9). **Approval:** the owner approved everything on 27 Nov and asked for autonomous, parallel building; every decision below is a safe default "approved under the owner's 27 Nov instruction". Anything that needs his hands waits until he tests, and nothing is spent without his typed YES.

**Layers:** 1 (console screens), 2 (speech-to-text, wake word, speaker check), 6 (the laptop speech kit), 7 (voice profile data), 8 (JARVIS's voice). **Skill:** Communication. **Phase:** 1 (voice), with Phase 6's laptop surface.

---

## 1. In plain words

**What you get.**
1. **One 20-minute "voice session"** (in the console, with breaks): you read short prompts aloud — commands, names, places, numbers, and "Hey Jarvis" in different ways. From it JARVIS learns three things:
   - **how you speak** (row 81): it tests every listening engine on *your* voice and picks the one that understands you best, then learns your common mishearings ("Java's" → "JARVIS") and your words;
   - **your own "Hey Jarvis"** (row 83): a small extra check trained on your voice sits on top of the wake word, so it wakes for you and far less for the TV; later, a wake word fully trained by and owned by you replaces today's borrowed model;
   - **your voice print** (row 84): only you can interrupt JARVIS while he speaks, so a TV or another person can't cut him off.
2. **Your laptop as JARVIS's voice** (row 383): a free speech kit on your laptop listens and speaks for JARVIS (an English voice in JARVIS's British style, and the Indian-language engines the calls feature needs), so Google's free minutes last longer and nothing costs money. If the laptop is off, JARVIS uses Google as today, then the browser.

**What it costs.** ₹0 a month. Everything new runs on your laptop or in your browser. The voice session's one comparison against Google's listening uses about 20 of Google's free minutes; if this month's free minutes are used up, it shows the ₹ first (at most about ₹46) and asks.

**Privacy.** Your voice print and wake-word check stay on your own devices. The session's recordings stay on your laptop (encrypted), never in the cloud; you can delete them at any time. Your voice is never used to approve anything.

**What you do (after R5.2 is merged).** Install the laptop speech kit (about 30 minutes, mostly downloads of 3–5 GB), then the 20-minute voice session, then a 1-minute enrolment on your phone's browser for the speaker check there. Optional, before any public launch: let the laptop train your fully owned wake word overnight (about 2–3 hours, unattended).

**VoiceStudio.** You named a "VoiceStudio project" for local speech. The plan builds the local speech kit from free, permissively licensed parts (below). If VoiceStudio is a particular project you want used, tell me its name and I'll check its licence and swap it in behind the same engine slots; nothing waits on this.

---

## 2. Scope by row

| Row | What is built | Needs you |
|---|---|---|
| 81 Recognition on your voice | The voice session; an engine comparison on your recordings (browser, Google with your words, laptop Whisper); your best engine chosen by measured word error; a learned correction list and word list; a "check again" button | The session (20 min) |
| 83 Your own "Hey Jarvis" | Stage 1: a personal verifier trained on your session clips on top of today's model (personal use); stage 2: a fully owned model trained on the laptop from your clips, synthetic voices and openly licensed background audio, replacing today's non-commercial model | The session; stage 2 run before launch (optional now) |
| 84 Speaker check | An on-device voice print (browser, per device); barge-in only by your voice; turns marked "spoken by the owner"; never for approvals | The session (laptop); 1 minute per other device |
| 383 Local speech | The laptop speech kit: a small speech server behind the existing laptop gate (Caddy + Tailscale https, as the offline brain uses); English listening and voice; the Indian-language engines R18's calls use in "laptop" mode; JARVIS's voice service and the call desk use it when it is healthy | Install the kit |

---

## 3. Design by layer

### 3.1 The laptop speech kit (row 383; Layer 6)
- **Where:** `deploy/local-speech/` (installer, start scripts, README) and `src/jarvis/localspeech/` (the server, run on the laptop). Same pattern as `deploy/local-brain/`: a local HTTP server on `127.0.0.1`, the Caddy gate with the kit's key, reached by the cloud only through the owner's Tailscale **https** name (row 392's rule: http refused).
- **Engines** (each in its own slot, loaded on demand so a 4 GB graphics card is enough; CPU fallback):
  - Listening, English: faster-whisper (MIT; Whisper weights MIT), `small` int8 by default, `medium` int8 if the session shows it is clearly better for you.
  - Voice, English: Kokoro-82M (Apache-2.0) with a British male voice; Piper (MIT; per-voice licences checked) as the light fallback.
  - Indian languages for R18's laptop mode: AI4Bharat IndicConformer 600M int8 ONNX (MIT) for listening; AI4Bharat Indic Parler-TTS (Apache-2.0) and Piper voices where licensed, for speaking. R18's language check decides which languages actually use them.
  - Wake-word training (row 83) and the session's scoring jobs (row 81) run here too.
- **API** (JSON + PCM16 16 kHz mono): `GET /health` (engines, device, free memory), `POST /stt` {lang, audio} → {text, confidence, seconds}, `POST /tts` {lang, voice, text} → audio, `POST /session/*` (store a clip, score, results), `POST /wakeword/*` (train, status, model), all behind the gate's key; requests and audio never logged.
- **Downloads:** pinned model files with SHA-256 checks and their licence files saved beside them; one "what this kit installed" list.

### 3.2 Cloud side (Layers 2, 8)
- `src/jarvis/voice/laptop.py`: an adapter on the existing voice ports (`jarvis/voice/ports.py`) for listening and speaking through the kit; health-checked and cached; failures map to the existing errors so the console falls back to Google, then the browser, exactly as today.
- Engine routing: the owner's best engine from the session (row 81) when healthy; Vitals shows which engine served and ₹0 for the laptop.
- **R18 reuse, not duplication:** R18 owns `src/jarvis/calls/speech/**` (its cloud adapters, language detection, phone-line simulation, the language check) and `src/jarvis/calldesk/**`. R5.2 adds only `src/jarvis/voice/calls_bridge.py`, an adapter that satisfies R18's `Hearing`/`Voice` ports by calling the kit, plus a one-line registration of the "laptop" option in R18's selection at the R5.2 join, and points the call desk's laptop-speech hook at the kit on `127.0.0.1`. The language check, phone-line simulation and scoring code are R18's and are called, not copied.

### 3.3 The voice session (row 81; Layers 1, 2, 7)
- Console screen "Your voice" in the existing look: about 120 short prompts in 4 blocks of 5 minutes (commands JARVIS knows, your words list, places and names, numbers and times, "Hey Jarvis" said 30 ways: near, far, quiet, tired, over music), progress, redo a prompt, breaks.
- Audio goes browser → JARVIS → the laptop kit (stored there, encrypted at rest with a key only the kit holds); the cloud keeps nothing.
- Scoring on held-out prompts: word error and command accuracy for the browser's listening, Google (with your words) and the laptop engines; the best becomes your default; mishearings that repeat become a correction list applied after listening (never to numbers in money or codes); new words join "words to recognise".
- Results page: engines ranked for your voice, the chosen one, Check again, Delete my recordings.

### 3.4 Your own "Hey Jarvis" (row 83; Layer 2)
- **Stage 1 (personal verifier):** openWakeWord's custom-verifier method (Apache-2.0 code): a small classifier on the wake-word embeddings, trained on the kit from your session clips and openly licensed negatives; exported as plain weights the console applies after today's detector. Works on laptop and phone browsers.
- **Stage 2 (owned model):** a training job on the kit: your clips + synthetic "Hey Jarvis" from permissively licensed voices + openly licensed background audio (licences listed; no dataset of unclear licence); output an ONNX model in the console's format with its own MANIFEST and licence (yours); swapped in when it beats the old model on the evals. Today's `hey_jarvis_v0.1` is CC BY-NC-SA (personal use is fine; replace before any launch).

### 3.5 Speaker check (row 84; Layer 2)
- A small speaker-embedding model running in the browser with the vendored onnxruntime-web (candidates: WeSpeaker ResNet34 or 3D-Speaker CAM++, Apache-2.0; the builder verifies the weights' licence and training data before shipping), enrolment from the session's clips (laptop) or 1 minute of reading (other devices); the voice print stored only in that browser (encrypted with a device key), never uploaded.
- Uses: barge-in accepts only your voice (others and the TV are ignored while JARVIS speaks); turns marked "spoken by the owner". **Never** an approval, a passkey or an unlock (slice 9 D11 stands). Off switch per device; falls back to today's behaviour when not enrolled.

---

## 4. Costs (₹)

| Item | ₹ |
|---|---|
| Laptop speech kit, engines, training | ₹0 (your laptop's electricity) |
| Speaker check and wake word in the browser | ₹0 |
| The session's Google comparison (about 20 minutes once) | ₹0 inside the free allowance; ≈ ₹2.29 a minute beyond it (at most ≈ ₹46), shown first and asked |
| Monthly running | ₹0; speech served by the laptop saves Google's free minutes and any ≈ ₹2.29 a minute beyond them |

---

## 5. Evals (before ship)

| Suite | Pass |
|---|---|
| Recognition (owner's held-out prompts; in CI a synthetic set) | The chosen engine's word error ≤ the best cloud engine's + 2 points; commands ≥ 95 % right; corrections never touch numbers in money or codes |
| Wake word | False wakes ≤ 0.5 an hour on 2 hours of openly licensed TV/podcast audio; misses ≤ 5 % on your held-out clips; with the verifier, other speakers' "Hey Jarvis" rejected ≥ 90 % |
| Speaker check | Equal error rate ≤ 5 % (your clips vs openly licensed other speakers); TV barge-in ignored; a test proves it can never approve anything |
| Laptop kit | First audio ≤ 0.7 s for a short reply on the graphics card (≤ 1.5 s on CPU); listening faster than real time ×3; the gate refuses http and a wrong key; nothing logged |
| Fallback | Kit off or slow → Google → browser, with the existing messages |
| Privacy | No audio, print or recording stored in the cloud; Delete removes them from the laptop |

Mock evals in CI; real models only on the laptop (the kit's own self-test prints a report the owner can paste).

---

## 6. Decisions (safe defaults, approved under the owner's 27 Nov instruction)

| # | Decision |
|---|---|
| D1 | Local speech is a laptop kit behind the existing gate pattern (Caddy key + Tailscale https), not a new cloud service |
| D2 | English engines: faster-whisper small int8 (medium if better for you), Kokoro-82M British male voice, Piper fallback |
| D3 | Indian-language laptop engines (IndicConformer, Indic Parler-TTS, licensed Piper voices) live in the same kit; R18's language check decides their use |
| D4 | One 20-minute session feeds rows 81, 83 and 84; recordings stay on the laptop, encrypted, deletable |
| D5 | Wake word: stage 1 personal verifier now; stage 2 owned model built now, run by the owner when he chooses, required before any launch |
| D6 | Speaker check per device, in the browser; barge-in and "spoken by the owner" only; never approvals |
| D7 | Engine order for the console: the session's best → Google → browser; for calls, R18's selection with "laptop" first when it passed the language check |
| D8 | Release `v5.2.0`; if R18's pull request is not merged when R5.2 starts, R5.2 branches from R18's final branch and its pull request names R18 as a prerequisite |
| D9 | VoiceStudio: the default parts above unless the owner names a specific project (then its licence is checked and it goes behind the same slots) |

---

## 7. Builder split (parallel; file ownership like R18's build brief)

| Agent | Branch | Owns |
|---|---|---|
| I0 | `r5-2-i0` | `src/jarvis/localspeech/protocol.py` (the kit's API models), `src/jarvis/voice/profile.py` (voice-profile settings and results models), routes skeleton `src/jarvis/api/voice_profile_routes.py`, config keys (kit address and key as `SecretStr`), version `v5.2.0`, `docs/plans/r5-2-voice/I0-SEAMS.md` |
| V1 | `r5-2-v1` | `src/jarvis/localspeech/**` (server, engines, model manager, jobs) except `protocol.py`; `deploy/local-speech/**` (installer, gate config, README, hash-pinned requirements, model manifest with licences) |
| V2 | `r5-2-v2` | `src/jarvis/voice/laptop.py`, `src/jarvis/voice/calls_bridge.py`, engine routing edits in `src/jarvis/voice/service.py`, Vitals' engine line |
| V3 | `r5-2-v3` | The voice session: console screen and scripts (new files), `src/jarvis/voice/session.py` (prompts, routing clips to the kit, scoring calls, corrections and word list), its handlers |
| V4 | `r5-2-v4` | Wake word: kit-side training jobs in `src/jarvis/localspeech/wakeword/**` (V1 leaves that folder to V4), console verifier runtime and model swap (new console files + the smallest edit to `console-wakeword.js`), the MANIFEST and licence handling |
| V5 | `r5-2-v5` | Speaker check: console embedding runtime, enrolment and storage (new console files), the barge-in hook (smallest edit to `console-voice-barge.js`), the model file and its licence, the "never approves" tests |

Then I1 join (`r5-2-i1`), the Build Book pages for the new modules, one combined security + code review with its single final check pass, and the PR `v5.2.0 · R5.2 Your voice · Mark <N>`.

---

## 7a. Overlaps with R18 (read before building)

- `src/jarvis/calls/speech/**`, `src/jarvis/calls/langcheck/**` and `src/jarvis/calldesk/**` are R18's. R5.2 calls them and registers into them at its join; it never copies their code.
- The kit's Indian-language engines are the "laptop" option R18's plan describes; R18's call desk ships that option disabled until the kit exists.
- Both releases touch the voice service's fallback order: R5.2's change is limited to adding the laptop engine before Google for console voice.

---

## 8. Risks

1. **Laptop speed:** a 4 GB graphics card can't hold every engine at once; engines load on demand and the kit reports when a reply would be slow, so routing falls back.
2. **Licences of model weights** (speaker model, Piper voices, background audio for wake-word training): each builder verifies and records the licence before a file is shipped or downloaded; anything unclear is left out.
3. **Wake-word stage 2 quality:** if the owned model doesn't beat the old one on the evals, it isn't swapped in; stage 1 still works.
4. **Speaker check across microphones:** enrolment is per device; a cold or a new headset can lower the match, so the check only ever *blocks barge-in*, never anything important.
5. **The laptop is off or asleep:** routing falls back to Google and the browser, as today.

---

## Change log

| Version | Date | Release | What changed | By |
|---|---|---|---|---|
| v5.2.1 | 27 Nov 2026, 13:40 IST | R5.2 | First edition: rows 81, 83, 84, 383; the laptop speech kit, the voice session, the two-stage wake word, the on-device speaker check; costs ₹0; evals; decisions D1–D9 approved under the owner's 27 Nov instruction; builder split for six agents; overlaps with R18 | 🛠 Mark XXV |
| v5.2.2 | 27 Nov 2026, 19:30 IST | R5.2 | I1 join (`docs/plans/r5-2-integration/I1-NOTES.md`). **Deviation from the build brief's rule 9** (the Workshop's decision): the kit's model manager accepts, only for a small plain-git text file (JSON or TXT, at most 5 MB) at a pinned full commit, its git blob id instead of a SHA-256 (checked after download, its SHA-256 then recorded); weights always need a SHA-256. faster-whisper small and medium are pinned that way. Also: the kit's Funnel port is 10000 (the offline brain keeps 8443); D2/D3 as built: the GPL phonemiser, piper-tts and the PyTorch Indian engines are left out (empty slots: Google's voice, Indian languages on the cloud options R18's check passes) | 🛠 Mark XXV |
| v5.2.3 | 27 Nov 2026, 22:20 IST | R5.2 | Combined review (`docs/plans/r5-2-integration/REVIEW.md`): Funnel's ports, one door each: the home bridge 8443, the offline brain 443, the kit 10000 (the offline brain's start scripts had taken the bridge's 8443, so v5.2.2's "the offline brain keeps 8443" is corrected); every start script refuses a port that already serves something else. The blob-id pins hold only for a file fetched at its commit (the host's raw-file address). The self-test times listening alone when the kit has no voice | 🛠 Mark XXV |
