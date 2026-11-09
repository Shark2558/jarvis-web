# Release R5 — Voice that listens: you can talk over JARVIS to stop him, conversations have no turn limit and end with a spoken handover after a long pause, a "mic off" that really stops the microphone, switching between laptop sound devices (Bluetooth earphones, speaker, the laptop itself), faster first words, and recognition tuned to words the owner chooses

Status: PLAN v1 · 2026-11-09 · branch `r5`, which is `r4` @ `acaee95`. `main` is still R3 @ `e16996a` (see G0). Builders branch from `r5-i0`, which is `r5` plus this plan's I0 seams. The plan carries the owner's voice requirement of 9 Nov.

Not in this plan:
- The owner's own trained wake word, and voice ID. Both need the owner's input first; see the "Needs you first" section.
- A streamed tool loop, deferred to R11 "Free hardening" (latency and cost) (D15).
- Camera extras and smart-home devices. The R4 plan reserved R5 for these (`docs/plans/r4-vitals-health-people.md` line 7). Release plan v4 (9 Nov) moved them to R7 (smart home) and R8 (camera life); R6 is the build book. `claude/release-plan.md` is already updated.

## The owner's requirements for R5 (9 Nov)
1. **Listens whenever I speak.** Inside a conversation, any speech counts. Outside one, "Hey Jarvis" works (still opt-in). Streaming room audio non-stop is not built (privacy and cost).
2. **Long answers are read to the end.** JARVIS never stops by himself. If the owner interrupts, he stops quickly, listens and acts on what was said.
3. **No turn limit.** Today the limit is 3.
4. **The keyboard takes over only after JARVIS says so**, after a long pause.
5. **A "mic off" command.** It cuts the microphone completely, and only a manual action switches it back on.
6. **Several Bluetooth devices**, with a quick switch by voice: speaker, earphones, the laptop itself, whatever is connected.

Project rules that apply:
- Free and private: no new paid service, no new Cloud Scheduler job, no new Secret Manager version.
- Confirm before commit: R5 adds no irreversible action, and approvals are still never given by voice (slice 9 D11 stands).
- Model-agnostic: nothing new under `jarvis.llm`.
- Every `console*.js` stays at or under 800 lines. `textContent` only, no CDN, CSP `script-src 'self'`.
- Interface copy is plain English addressed through `honorific()`, and costs are shown in ₹ only.

## Gate G0 · R4 first
R4 sits on `r4` @ `acaee95` and is not merged to `main`. R5 builds on `r4`. If R4 changes before it merges, the integrator rebases `r5-i0` at I1. R5 touches none of R4's server modules (`vitals/`, `health/`, `people/`, `photos/`). The only R4 code it relies on is `api/r4_wiring.py::voice_allowances`, which only gets read (D17).

## What the code says today (read on `r5` @ `acaee95`)
1. **The 3-turn cap and the 3 s re-listen are real.**
   - `console-voice-mic.js` sets `MAX_HANDS_FREE = 3` (l.39) and `RELISTEN_START_MS = 3000` (l.37).
   - The speaker's `'state'` handler (l.359–370) re-listens only while `S.chain < MAX_HANDS_FREE`. After that it says "Tap the mic to carry on."
   - A re-listen that hears nothing ends quietly: `nothingHeard()` returns with `S.soft` set (l.149–154).
   - Limits: `MAX_LISTEN_MS = 30000`, `NO_SPEECH_MS = 6000`, `RELISTEN_DELAY_MS = 350`.
2. **Interrupting is tap only.**
   - `press()` handles a tap while JARVIS speaks (l.329). Esc and a typed message also stop him: the `jarvis:turn` handler (l.382–389) and `stopAll()`.
   - The VAD exists only inside `listenCloud()`, so only while listening.
   - The microphone is closed while JARVIS thinks and speaks: `transcribe()` → `endCapture()` → `releaseMic()`, which closes unless `wake.on` (l.180).
   - The browser engine closes it as well (`listenBrowser`, l.227).
3. **"Hey Jarvis" is paused whenever the loop is busy.** `busy()` is `S.mode !== 'idle' || V.speaker.speaking()`, and `syncWake()` holds the module (l.426–450).
   - The model is only `hey_jarvis_v0.1.onnx`. There is no local "stop" model (`console-wakeword.js` l.31).
   - `JarvisWake.threshold` is settable between 0 and 1 (l.439). `pause()` and `resume()` reset the buffers, and the first 5 frames after a reset score 0.
   - A wake-word error switches the owner's device setting off: `jarvis:wake` 'error' → `setDevice({wake:false})` (`console-voice.js` l.542).
4. **Microphone capture.**
   - `console-voice-capture.js::build()` calls getUserMedia with `echoCancellation`, `noiseSuppression`, `autoGainControl` and no `deviceId` (l.74–76).
   - `JarvisVad` defaults: `endSilenceMs 1200, noSpeechMs 6000, maxMs 30000, prerollMs 320, floor 0.012, ratio 3.2, startFrames 2` (l.199–200). `create(opts)` already accepts overrides.
5. **The speaker.**
   - `console-voice-speech.js::createSpeaker` builds one lazy AudioContext: master → analyser → destination (l.233–254).
   - `level()` returns 0 while the browser voice is in use (l.370).
   - `stop()` throws the queue away (l.361–367).
   - A chunk whose audio can't be decoded is **skipped silently** (l.288).
   - It fetches 2 chunks ahead (l.270). The chunker sends the first sentence on its own, then chunks of up to 400 characters (l.24–26).
6. **The console does not stream replies.**
   - `console.js::send()` posts `/v1/chat` (l.519) and fires `jarvis:answer` only after the whole reply arrives (l.498).
   - `POST /v1/chat/stream` exists, but it "has no tool round" (`api/routes.py` l.5–14). `Brain._chat_stream` calls `router.stream(...)` without tools (`core/brain.py` l.754–762). No provider's `stream()` takes `tools` (`llm/base.py:202`, and the anthropic, gemini, openai_compat, local and mock providers).
   - The slice-9 build notes already recorded this deviation (`docs/plans/phase1-slice9-voice.md` l.170–175).
7. **Phrase hints already exist on the server.**
   - `VoiceService.phrases = ("JARVIS", "Jarvis", honorific)` (`voice/service.py` l.222). `GoogleSTT.recognize` sends them as `speechContexts` (`voice/google_cloud.py` l.238–239).
   - `tests/test_voice_api.py:378` pins that list.
   - Limits: `/transcribe` 30 a minute, `/speak` 60 a minute (`api/voice.py` l.53–54).
8. **Why "long answers stop in between" (likely causes; it can't be reproduced in the sandbox).**
   - (a) `VOICE_RULE` asks for at most about 60 words or 3 sentences, and to "give the gist and say the details are on screen" (`core/prompts.py` l.498–504). The screen shows the same text, so those details often are not there at all.
   - (b) The chunker replaces code and tables with "The details are on screen" (by design).
   - (c) Undecodable chunks are dropped (fact 5).
   - (d) R5's own new risk: a false interruption. D7 and D9 address all four.
9. **The Notes memo recorder shares the microphone and can interfere.**
   - `console-notes-memo.js::start()` opens `JarvisAudio` and falls back to the browser recogniser on *any* open failure (l.57–59).
   - Its `release()` calls `JarvisAudio.close()` (l.68), which would close a live conversation's microphone.
   - getUserMedia is called only in `console-voice-capture.js`. SpeechRecognition is constructed only in `console-voice-mic.js` (l.230) and `console-notes-memo.js` (l.81).
10. **Constraints from the CSP and the static-file list.**
    - The CSP has no `media-src` (`api/console.py` l.141–146), so output routing must use Web Audio (`AudioContext.setSinkId`), never an `<audio>` element.
    - New static files must be added to `APP_ASSETS` (`api/console.py` l.30–97).
    - `console-deck.js` l.461 and `console-3d.js` treat unknown voice states as idle. `console-fx.js::setVoice` accepts only listening and speaking (l.172–187).
11. **Vitals already covers voice.** `api/r4_wiring.py::voice_allowances` (l.132–135) adds one `AllowanceSpec` per TTS voice type plus STT, so the Vitals board shows voice minutes and characters, and warns at 80% (R4 D3).
12. **Audit precedent for settings.** Changes that alter what JARVIS sends to Google are audited with `api/settings_audit.py::record_change` (SEC-3).

## How it fits the architecture

| Feature | Layer · skill | Phase | Verdict |
|---|---|---|---|
| Speak to interrupt, plus the "Hey Jarvis" model running while JARVIS speaks | L2 input (VAD, wake word), L8 output (stop, lower the volume) · voice interface (cross-cutting) | 1, refinement | Build now |
| No turn limit, standing by, long-pause handover | L1/L3 session state, kept client-side | 1 | Build now |
| Mic off | L1 + privacy (cross-cutting) | 1 / 7 | Build now |
| Local voice-command router | L2, before L3/L4 | 1 | Build now; works in No-AI mode |
| Laptop audio devices | L1 devices, L6 browser media APIs | 5/6 multi-device, pulled forward for the laptop only | Build now; Android gets instructions |
| Faster spoken replies | L8 / L4 latency | 7 (partial) | Client-side levers now; streamed tool loop in R11 |
| Tuned recognition (phrase hints) | L2 · personalisation | 1/3 | Build now |
| Own wake word, voice ID | L2 | 3/7 | Needs you first |

No new tier is added. Proposed `JARVIS_Architecture.pdf` note:
- Layer 2 gains "on-device voice-command router (before the core) and barge-in detector".
- Layer 1 gains "audio route (output/input device)".
- The privacy cross-cut gains "hard microphone lock".

## Decisions

### D1 · Mostly client-side, no tools, no SDK
- Interrupting, the conversation loop, mic off, the router and device switching run in the console. None of them is a gateway tool.
- They are local, reversible settings of the owner's own browser. Pressing a key or button is not a commit.
- Server changes are limited to three things:
  - phrase hints (`voice/settings.py`, `voice/service.py`, `api/voice.py`);
  - the persona text (`core/prompts.py`);
  - a privacy-registry source.
- No vendor SDK is involved (voice stays on httpx REST). There are no new routes, so no new rate limits.

### D2 · The listening loop, new states
`S.mode` currently takes four values: idle, listening, thinking, speaking. It gains three more:
- **standby** (still listening, with a stricter start gate);
- **handover** (speaking the fixed handover line, with interruption off);
- **off** (the microphone is locked).

A *conversation* starts with a tap, Ctrl+Space or "Hey Jarvis" and ends at handover, Esc, a typed message, a new conversation, mic off, or page-hide.

```
                   tap · Ctrl+Space · "Hey Jarvis"
  +--------+ -----------------------------------------> +-----------+   speech ends · tap   +----------+
  |  IDLE  |                                            | LISTENING | --------------------> | THINKING |
  +--------+ <-- Esc · nothing heard 6 s after a tap -- +-----------+                       +----------+
    ^    ^                                                |   ^   ^                               |
    |    |                     followUpS (8 s), silent    |   |   | reply done (+0.35 s)          | reply (spoken turn)
    |    |                                                v   |   |                               v
    |    |                                          +---------+   |                         +----------+
    |    |              speech (stricter gate) <--- | STANDBY |   +------------------------ | SPEAKING |
    |    |                    -> LISTENING          +---------+   barge-in: speech ·        | mic open |
    |    |                                  longPauseS |          "Hey Jarvis" · "stop" ·   +----------+
    |    |                                  (20 s)     v          tap  -> LISTENING
    |    +------------- line spoken -------------- +----------+
    |                                              | HANDOVER | <-- "keyboard" · check-in unanswered (D6)
    |                                              +----------+     · mic unplugged · cloud listening down
    +---- typed message · new conversation · Esc · approval line (slice 9 D11) ---- from any state
  +---------+
  | MIC OFF | <==== "mic off" · Ctrl+Shift+Space · off button · Voice panel switch ==== from ANY state
  +---------+ ====> IDLE only by a manual click/tap/key (user activation); a tap on the mic then LISTENS
```

Transition rules beyond the diagram:
- A reply to a **typed** message (with Speak replies: Always) never opens the microphone. It can be interrupted by tap or Esc only.
- After the fixed approval line, the conversation ends quietly, as today (D11 and its test stand).
- The button's `data-state` takes idle, listening, standby, thinking, speaking or off. Handover shows as speaking.
- The button's accessible name stays "Voice input" (existing test). The status pill shows "Standing by" or "Mic off" (I0 adds both to `console-fx.js` `STATUS_WORDS`).

### D3 · The microphone stays open for the whole voice conversation
- From the first listen to the end of the conversation, `JarvisAudio` stays open through thinking and speaking. This lets an interruption be heard, and the next turn starts with no getUserMedia re-open delay.
- The browser's mic indicator is therefore lit for the whole conversation, which is honest, and the off button sits right beside the mic (D11).
- **As built (I1):** this holds for the **cloud engine** only. With the **browser engine** the loop closes `JarvisAudio` between turns, as before R5 (SpeechRecognition records on its own), so there is no energy interruption there: only a tap, Esc or "Hey Jarvis" stops JARVIS. `JarvisAudio` stays open beside the recogniser only while "Hey Jarvis" standby is on. The Interrupt row's help text says so.
- Android: if the recogniser fails with `audio-capture` while `JarvisAudio` is open, the loop closes `JarvisAudio` during browser listening turns and interruption falls back to tap for that page (D14).
- A microphone chosen while the conversation holds it open takes over at the next listening turn: that turn's `open()` closes and reopens on the new device (subscribers kept) and capture fires `jarvis:audio-route {reason: 'input_live'}`, which clears the picker's "Pending" note (I1).

### D4 · No turn limit; follow-up window, standing by and the long pause are separate
`MAX_HANDS_FREE` and `RELISTEN_START_MS` are removed. After a spoken reply ends (plus 350 ms, as today):

| Time after the reply ends | State | What happens |
|---|---|---|
| 0 to `followUpS` (default 8 s) | LISTENING | Speech here is the next turn; the VAD works as today. |
| `followUpS` to `longPauseS` (default 20 s) | STANDBY | Still listening. The VAD start gate is stricter (`ratio 4.0, startFrames 4`, so 320 ms of speech is needed); a cough or a distant TV does not start a turn. The ring dims and the pill says "Standing by". |
| `longPauseS` | HANDOVER | See D5. |

Also:
- **Pause allowed mid-sentence** (`endSilenceMs`, default 1200, adjustable) is the gap that ends a *turn*. It is distinct from both waits above.
- A tap-started turn keeps "nothing heard in 6 s → I didn't hear anything", because the tap is explicit. A "Hey Jarvis" start with no speech ends quietly after 6 s, as today (probably a false wake).
- The turn cap rises from 30 s to **55 s**. That fits STT v1's 60 s synchronous limit and `MAX_AUDIO_BYTES` of 2,000,000 bytes (55 s × 32,000 B/s ≈ 1.76 MB), so long dictation is not cut off mid-thought.
- The browser engine's recogniser ends by itself after a few silent seconds. The loop restarts it quietly until the long pause, at most once every 4 s.
- Waiting costs ₹0: the cloud engine only runs the local VAD, and nothing is sent until speech starts.

### D5 · Every ending the owner didn't choose is announced
The owner's rule: "only after notifying me". Each of these ends the conversation with a fixed line, spoken when output is available and Speak replies is not Never, and always shown in `#voiceLine`:
- the long pause;
- a check-in with no answer (D6);
- the microphone stopping by itself (unplugged);
- cloud listening becoming unavailable with no browser fallback;
- a "keyboard" command;
- on phones, the page being hidden.

The lines:
- Spoken: "I'll switch to the keyboard, {honorific}."
- Shown: "Switched to the keyboard. Tap the mic (or say "Hey Jarvis") to talk." The "Hey Jarvis" part appears only if standby is on.
- When the microphone stopped: "The microphone stopped, {honorific}. I'll switch to the keyboard."

After the line: the composer gets focus, the microphone closes, and "Hey Jarvis" standby resumes after `WAKE_RESUME_MS`, as today. Endings the owner chose (Esc, tap, typing, mic off) stay as they are today: no speech.

### D6 · Runaway guard: a check-in when the room keeps talking
- **Risk.** With no turn limit, a TV can keep a conversation going for ever. That spends STT minutes and brain calls (≈ ₹1–3 a turn on a paid brain). This trap is exactly why the existing test `test_conversation_mode_with_continuous_room_audio_stops_by_itself` exists.
- **When it triggers.** Only when every one of these holds:
  - 8 hands-free turns in a row, each starting within 1.5 s of JARVIS finishing (or after an interruption);
  - all of them within 4 minutes;
  - no tap or key in between.
- **What JARVIS does.** At the end of the 8th reply he asks "Shall I keep listening, {honorific}?" and waits 8 s for an answer through the router's `ask()` (D12).
  - "Yes" (or "carry on", "keep listening") continues the conversation, and he won't ask again for 15 minutes.
  - Anything else, or silence, goes to handover. A TV rarely says "yes" on cue.
- **Setting.** "Check in when the room keeps talking" (`checkIn`), default **on**. The owner can switch it off to get strictly no checks; that is an open question.
- There is still no count cap: an owner talking at a normal pace never hits this.
- **Absolute bound (as built, A's SH1).** Whatever `checkIn` says, 25 hands-free turns or 30 minutes since the last tap or key force the same check-in; a "yes" grants exactly 8 more turns. With `checkIn` off only the quick-turn rule above is off. Three empty turns in a row (noise, not a conversation) hand over.

### D7 · Speak to interrupt: the policy, and how JARVIS avoids interrupting himself
Device setting "Interrupt JARVIS by" (`interruptBy`). This extends the two options in the brief:
- **Automatic** (default). Behaves as Speaking when the output is earphones or a headset (B's `JarvisAudioRoute.outputKind() === 'headphones'`, from the device label or the owner's "This is: earphones" mark) or the input is a headset mic. Otherwise behaves as "Saying "Jarvis" or "stop"". Unknown outputs count as speakers, the safe side; this includes Android and unclassifiable Bluetooth names.
- **Speaking.** Sustained speech that passes the double-talk gate stops JARVIS at once. The words, including 320 ms before the speech began, become the next turn.
- **Saying "Jarvis" or "stop"** (`name`).
  - "Hey Jarvis" or "Jarvis" stops him at once, using the on-device wake model (D8).
  - Talking over him lowers his volume to 20% within about 0.3 s (ducking). A clip of up to 2.5 s then goes through the cloud engine to the local router:
    - "stop", "wait", "mic off", "keyboard", "switch to …", or anything starting with "Jarvis", interrupts him;
    - anything else returns his volume to normal and he carries on. The clip's words are dropped: never sent to the chat, shown or stored.
- **Tapping only.** Today's behaviour.

| Effective policy | Output | Voice | Interrupt on speech energy | Lower volume + check clip | Wake model while he speaks |
|---|---|---|---|---|---|
| Speaking | earphones | cloud or browser | yes, margin 2.0 | — | no |
| Speaking | speakers | cloud | yes, margin 4.0, 4 frames | — | no |
| Speaking | speakers | browser | **no** (no echo reference) | — | yes (fallback) |
| Jarvis or stop | any | cloud | — | yes (cloud STT only) | yes |
| Jarvis or stop | any | browser | — | no (can't lower the OS voice's volume) | yes |
| Tapping only | — | — | — | — | — |

**The double-talk gate** lives in `console-voice-barge.js` and is pure, so it is unit-tested:
- **Inputs.** Each 80 ms frame gives `micRms` (`JarvisVad.rms`). `outLevel` is sampled every 20 ms from `V.speaker.level()` while JARVIS speaks.
- **Echo estimate.** `echoEst = leak × max(outLevel over the last 320 ms)`. `leak` is the 20th percentile of `micRms / outLevel` over the last 3 s, using frames with `outLevel > 0.02`, clamped to [0, 2]. It learns how much of JARVIS leaks back into the mic after Chrome's echo canceller.
- **When the gate opens.** `micRms > max(0.018, noise × 3.2, echoEst × margin)` for N frames in a row.
- **Constants.** N = 3 (240 ms) on earphones and 4 on speakers, plus 1 extra frame during the first 400 ms of each reply. Margin 2.0 on earphones, 4.0 on speakers. Lowered volume 0.2 with a 60 ms ramp; volume returns after 2.5 s without a command. All constants sit in one frozen `BARGE` object.

**Text-aware echo guard.** The speaker's `chunk` events carry the words being spoken:
- A check transcript or interrupt transcript counts as echo when 60% or more of its words appear in what JARVIS said in the last 4 s. The exception is when the gate's peak ratio reached at least 1.5 × margin.
- A wake during a chunk that contains "Jarvis" counts only if the gate was open in the same 400 ms.

**Limits on check clips.** At most one every 3 s. After 3 checks in one reply that find nothing (a noisy room), no more checks for that reply.

### D8 · How "Hey Jarvis" runs while JARVIS speaks
- **Standby on** (`device.wake`):
  - The module runs as today, paused during LISTENING and THINKING.
  - During SPEAKING with an effective policy that uses the wake model, it is resumed at `threshold = 0.6` (the default is 0.5), and `onWake` interrupts.
  - When speech ends it pauses for the follow-up turn, or resumes at 0.5 once idle.
- **Standby off:**
  - The model loads from same-origin static files on the page's first spoken reply that needs it, and is started only while JARVIS speaks.
  - It never listens while idle; standby stays opt-in.
  - The Interrupt row's help text says so.
- **Errors.** A wake-model error *during speech* switches interruption-by-name off for this page, with one plain line. It never flips the owner's "Hey Jarvis" setting, which `wakeFail` does today. While the mic is off the wake chip shows a new 'micoff' state, which is not an error.
- **Known limit.** After each resume there are 5 warm-up frames (0.4 s). A "Hey Jarvis" in the first ~0.5 s of a reply may be missed.

### D9 · JARVIS reads the whole answer
- **Persona (`VOICE_RULE`, p5.0).**
  - Keep "answer first, about 60 words unless asked for detail".
  - Add: "when the owner asks for detail, steps, a list or a read-out, give all of it in plain spoken sentences: it is read aloud in full; never stop part-way or promise the details elsewhere".
  - "The details are on screen" is said only for code, tables and links.
- **Speaker.** A chunk whose audio can't be decoded is spoken by the browser voice instead of being skipped (`pump()`). A 422 `nothing_to_say` is still skipped.
- **Resume after a false interruption.**
  - `speaker.stop()` returns `{rest}`, the unplayed text starting with the interrupted chunk.
  - If the interrupting turn has no words (`no_speech`, fewer than 4 frames, or only "um", "uh", "hmm"), JARVIS resumes from that chunk within 10 s.
  - "Stop" or a real question means he does not resume.

### D10 · Timing targets

| Path | Target | How |
|---|---|---|
| Speech starts → JARVIS silent (Speaking; wired or laptop output) | **≤ 0.4 s** (owner's target < 0.5 s) | 80 ms frames; 3 gated frames (240 ms) + ≤ 80 ms frame alignment + `AudioBufferSourceNode.stop()` + ≤ 40 ms output latency |
| Same, Bluetooth output | ≤ 0.4 s to stop sending audio, **plus the headset's own buffer (≈ 0.1–0.25 s, out of our control)** | as above |
| "Hey Jarvis" over speech → silent | ≤ 0.3 s after the phrase ends | 2 frames ≥ 0.6, inference ≤ 80 ms a frame |
| Talking over JARVIS on speakers → volume lowered / → stopped | ≤ 0.4 s / ≤ 2.0 s | 3–4 gated frames / clip end (500 ms) + STT round trip |
| Mic-off button or shortcut → all tracks stopped | synchronous (< 50 ms) | `track.stop()` |
| Mic off by voice | the phrase's transcription + < 50 ms | router runs before the chat |
| Laptop output switch | ≤ 0.3 s | `AudioContext.setSinkId` |

CI asserts ≤ 0.6 s for the first row to allow for headless timing jitter. Owner check 1 confirms the real < 0.5 s target, and the timing line (D15) logs every interruption with its delay.

### D11 · Mic off: a hard lock inside `JarvisAudio`, the one place everything opens the mic
**Mechanism (I0, `console-voice-capture.js`).**
- `lock(by)`:
  - sets the flag and persists `localStorage['jarvis_mic_off_v1']='1'` (in try/catch);
  - calls `close()`, so `gen++`: a build in flight stops its own tracks, and the live tracks and the primed context are closed;
  - `abort()`s every recogniser made through `recognizer()`;
  - fires `onLock` callbacks and `jarvis:mic-lock {locked:true, by}`.
- `open()` rejects with `.code 'mic_off'` while locked, and `prime()` does nothing.
- `recognizer()` is the only way to construct SpeechRecognition. It throws `'mic_off'` or `'unsupported'`.
- `unlock(by)` returns true only when `navigator.userActivation.isActive`, meaning a real click, tap or key press. It never opens the microphone by itself.
- The flag is read when the script loads. It loads first among the voice scripts, so after a reload nothing can open the mic before the lock applies.
- Lock and unlock sync across this browser's tabs through the `storage` event. An unlock never starts a listening turn anywhere; a saved "Hey Jarvis" standby resumes.

**Code paths that must refuse while locked.** Each one gets a test.

| Path | Behaviour while locked |
|---|---|
| `listen()`, re-listen, standby and long-pause timers | cleared on lock; `listen()` refuses |
| `listenBrowser` | uses `JarvisAudio.recognizer()` |
| Fallback to the browser recogniser after a 402/503 on `transcribeFailed` | refuses |
| Wake controller `start` / `boot` on jarvis:ready, DOMContentLoaded, load, pageshow | wake state 'micoff'; the owner's `device.wake` is kept |
| Barge-in detector, and the wake model during speech | off |
| Notes memo `start()` and its `useBrowser()` | refuse, with "The microphone is switched off. Switch it on with the mic button, then record." (no fallback) |
| A memo being recorded | stops, and frames not yet sent are dropped |
| B's device module | never opens the mic to get device labels |

**When the lock lands mid-turn.**
- A listening turn is cancelled and nothing is sent.
- A transcription already in flight is aborted (`Chat.raw` takes `signal`) and its result is dropped.
- A reply that is already playing finishes when the lock came from the button or the shortcut. "Mic off" said aloud also stops the reply.
- No re-listen follows.

**UI (A).**
- `#micBtn` with `data-state="off"` shows a struck-through mic. Its title is "Microphone off: tap to switch it on (Ctrl + Shift + Space)", and the live region announces "Microphone off".
- A tap on it unlocks and starts listening.
- `#micOffBtn` (I0 markup) is shown whenever the mic is open: in a conversation, or with standby on.
- The Voice panel's "Microphone on this device" switch.
- Ctrl + Shift + Space toggles off and on. The existing Ctrl + Space handler must then ignore Shift (today it doesn't check `shiftKey`). Ctrl + Shift + M is avoided because Chrome uses it for the profile menu.
- The voice command `mic.off` (D12).

"Manual" means a click, tap, Ctrl + Space or Ctrl + Shift + Space, all of which carry user activation. No timer, event, voice command, other module or reload can switch the mic on. Voice can't by construction, because nothing is listening.

**Residual risk (accepted, SM1).** A script that can remove `localStorage['jarvis_mic_off_v1']` and then reload the page would come back unlocked. Such a script is same-origin and already owns the page (CSP `script-src 'self'`, no third-party script), so it could do worse; the lock defends against JARVIS's own code paths and other tabs' synthetic events (`storage` events must be trusted), not against code running as the console. When the storage write itself fails, the `jarvis:mic-lock` detail carries `persisted: false` and the owner is told the lock won't survive a reload.

### D12 · The local voice-command router (`window.JarvisVoiceCommands`)
- It runs in the console **before** a transcript reaches the chat, inside `deliver()`. That covers listening turns, interruption turns and check clips, and it runs before the auto-send or "leave it in the box" choice.
- Commands therefore work in No-AI mode and offline from the brain. They cost nothing beyond the transcription the utterance needed anyway.
- Every action is local and reversible, so a TV saying "mic off" fails safe.
- **Inputs that are never routed:** typed composer text, reply text, `jarvis:answer` or `jarvis:speech` text, and anything from the server. `handle()` refuses unless `ctx.source === 'voice'`. There is no typed "/mic off" command; the button and shortcut cover typing. The persona tells the brain to point the owner to them (D19).

```js
// console-voice-commands.js (I0 core; A adds the built-in matchers; B registers device commands)
JarvisVoiceCommands.register(id, { match(norm, raw) /* -> null | args */, run(args, ctx) /* -> Result | Promise<Result> */,
                                   states /* optional: ['listening','standby','thinking','speaking'] */ }) // -> unregister()
JarvisVoiceCommands.handle(text, ctx)   // ctx {source:'voice', state, spoken /* JARVIS's words, last 4 s */, peak /* gate ratio */}
                                        // -> Promise<{handled, id?, result?}>   Result = {say?: string, then?: 'listen'|'idle'|'keyboard'|'off'}
JarvisVoiceCommands.ask(question, { yes, no, timeoutMs = 8000 })  // one-shot yes/no; used by the check-in (D6) and device offers (D13)
JarvisVoiceCommands.normalise(text)     // -> string
JarvisVoiceCommands.owns(text, state)   // dry run for tests -> id | null
JarvisVoiceCommands.PHRASES             // frozen JSON between /*PHRASES-BEGIN*/ /*PHRASES-END*/ (tests/test_r5_seams.py parses it)
// fires jarvis:voice-command {id, handled, state}. ids are unique (a duplicate throws).
```

**Normalisation.**
- NFKC, lower case, punctuation removed (apostrophes kept), spaces collapsed.
- A leading "hey jarvis", "ok jarvis" or "jarvis" is dropped, including the speech-recognition variants "jervis" and "jarvis's". So are "please", "can you" and "could you".
- A trailing "please", "now", "sir", "ma'am", "thanks" or "thank you" is dropped.
- "Turn" counts as "switch"; "microphone" and "mike" count as "mic".
- Only the whole remaining utterance is matched, and only if it is 8 words or fewer. "Remind me to stop at the shop" is a chat message.

**Matching order:** `answer.*` (only while an `ask()` is pending) → `mic.off` → `speech.stop` → `conversation.keyboard` → registered commands in registration order. The first match wins.

| id (owner) | Owns | When | Does | Says (fixed) |
|---|---|---|---|---|
| `answer.yes` / `answer.no` (A) | yes, yes please, yeah, yep, sure, okay, go ahead, do it, carry on, keep listening / no, no thanks, not now, nope, leave it | only while an `ask()` is pending | runs that question's yes/no | — |
| `mic.off` (A) | mic off; switch off (the) mic; switch (the) mic off; mute (the) mic; mute yourself; stop listening (to me); don't listen (to me) | any state | stops speech, `lock('voice')` **first**, then speaks | "Microphone off, {h}." |
| `speech.stop` (A) | stop; stop it; stop talking; stop speaking; stop there; wait; wait a moment; hold on; hang on; one moment; quiet; be quiet; enough; that's enough; pause; shush; cancel; never mind; forget it | speaking: stop and listen. Thinking: drop the answer (shown, not spoken) and listen. Listening: ignored | — |
| `conversation.keyboard` (A) | keyboard; keyboard mode; switch to (the) keyboard; I'll type; let me type; typing mode; that's all; that'll be all; we're done; end (the) conversation; goodbye; bye | any state except off | handover (D5) | "I'll switch to the keyboard, {h}." |
| `device.switch` (B) | switch to / change to / use / move (the sound) to / play (it) on / speak through + (my/the) X (instead), **only when X resolves** to a connected device, a nickname or a device word | any state except off | switches the output for **this page only** (a voice choice is not saved; a panel click is), or the Android / browser-voice line | "Switching to {kind}, {h}." (e.g. "your earphones"); name on screen: "Switching to {name}, {h}." |
| `device.input` (B) | use (my/the) X mic(rophone); listen through (my/the) X | any state except off | switches the input for this page only; with the mic open it takes effect at the next listening turn | "I'll listen through {kind}, {h}." or "I'll use that microphone from the next time I open the mic, {h}."; name on screen |
| `device.list` (B) | what's connected; which devices are connected; list (my) (sound/audio) devices; which speaker are you using | any state except off | reads `current()` and the device list | "You have {n} outputs: {kind words}. I'm speaking through {kind}; the names are on screen, {h}."; names on screen |

- **Device names are never spoken (I1, binding; B's security review H1).** Spoken text goes to the cloud voice (`POST /v1/voice/speak`), so a device label or nickname ("Akash's AirPods") never appears in it: spoken device lines use kind words only ("your earphones", "the laptop speakers", "that device"). The name is shown on screen only. The loop speaks a `device.*` result's `say` once and leaves `#voiceLine` to the devices module, which shows the named line, or the same name-free line when there is no name (so it is visible with Speak replies: Never).

- During a name-mode check clip, "Jarvis …" interrupts, and the rest (if any) becomes the next turn.
- A transcript caught by the echo guard (D7) is never handled.
- "Switch to dark mode" doesn't resolve to a device, so it goes to the chat.

### D13 · Audio devices on the laptop (B)
- **Listing.** `enumerateDevices()` runs at boot and on `devicechange`, debounced by 500 ms because Windows fires bursts. It never calls getUserMedia. Without the mic permission, the picker says "Device names appear after you allow the microphone once (tap the mic)."
- **Output.** `speaker.setSink(id)` uses `AudioContext.setSinkId` (Chrome 110 and later), glitch-free mid-reply. Before any sound the speaker's context is made for it (suspended until a tap), so the browser checks every id and a missing device fails at once with `{ok: false, reason}` (I1; B's review found the old "ok" before a context existed was never checked).
  - Windows' "Hands-Free AG Audio" outputs are deprioritised and labelled "(call quality)" when the same device has a stereo endpoint.
- **Input.** `JarvisAudio.setInput(id)` makes the next `open()` ask for `deviceId: {exact}`. An `OverconstrainedError` retries once on the default input and emits `jarvis:audio-route {reason:'input_missing'}` (I0).
  - Default: **keep the laptop mic** when output moves to Bluetooth earphones. Opening a Bluetooth headset mic forces Windows into the hands-free profile, which turns all sound into call quality. The picker warns about this when the headset mic is chosen.
- **Kind.** From the label:
  - headphone, headset, earphone, earbud, buds, airpods, hands-free → earphones;
  - speaker, soundbar, the "Speakers (Realtek / High Definition / Built-in)" style → speakers;
  - anything else → unknown.
  - The owner can mark each device "This is: earphones / a speaker". The barge-in Automatic policy (D7) uses this.
- **Remembering.** `localStorage['jarvis_audio_route_v1']`, holding ids **and** labels so a changed id can be matched again. At most 20 kind marks and nicknames. Choices made in the panel are saved; choices made by voice last for this page only (B's M1).
- **Device connected.**
  - "Ask" (default): an offer chip in `#voiceOffer`: "{name} connected. [Use {name}] [Not now]" for 30 s (on screen). In a conversation and not mid-reply, JARVIS also asks aloud, by kind: "New earphones have connected — shall I use them, {h}?"
  - "Switch automatically": he switches and says so, by kind ("Switching to your earphones, {h}."); the name is on screen.
  - "Do nothing".
- **Device removed.** If it was the chosen output, sound falls back to the default. He says "{Kind} disconnected. I'll use the default output, {h}."; the screen says "{name} disconnected. I'll use {fallback}, {h}."
- **Spoken lines use kind words only; names are on screen only** (D12, D18).
- **Browser voice.** `speechSynthesis` always plays on Windows' default output and can't be routed. The picker and the switch command say "My browser voice follows Windows' sound output, {h}: press Windows + Ctrl + V to choose it." That shortcut is Windows 11's quick output picker; confirm at owner check.
- **Fuzzy matching (`find(name)`).** Normalised tokens. Score = max(nickname exact 1.0, device-word alias 1.0, character-bigram Dice of the joined tokens, token overlap). Threshold 0.6.
  - "Speaker" prefers an external speaker over the built-in one.
  - "Laptop", "computer", "desktop" and "built-in" mean the built-in output.
  - "Default" means the OS default.
- **Privacy.** Device labels and ids stay in this browser's localStorage and the in-page event log. They are never sent to the server or written to the audit; labels can hold names such as "Akash's AirPods". A static test checks the module makes no `api()` or `fetch()` call.

### D14 · Android and browsers that can't route output
- Chrome for Android has no `setSinkId`, so `speaker.sinkSupported()` is false. The picker and `device.switch` say: "On this phone Android chooses where I sound, {h}: open Quick Settings and pick it under media output (the name varies by phone)."
- Input is listed if Android exposes more than one; otherwise "Android picks the microphone".
- Barge-in Automatic treats Android output as unknown, so it behaves as speakers.
- When the page is hidden on a phone, the conversation ends with the D5 line. The desktop keeps listening in hidden tabs, as today.
- Recogniser restarts may chime on Android, so the help text recommends the cloud engine there.
- With the browser engine (any platform) the mic closes between turns (D3 as built), so interrupting JARVIS there is by tap, Esc or "Hey Jarvis" only.

### D15 · Faster spoken replies: no streaming yet, and why
**Why not streaming.** Moving spoken turns to `/v1/chat/stream` would silently drop tools, approvals, cards and the session id (code fact 6). Streaming the *tool loop* needs `stream(tools=…)` with tool-call detection in all five providers (base, anthropic, gemini, openai_compat, local, plus mock). That is an `jarvis.llm`-wide change, recorded for **R11 (free hardening: latency and cost)**.

**What R5 does (owner C), all free:**
1. **A short first chunk.** If the first sentence is over 140 characters, the chunker cuts at the last clause break (", ", "; ", " — ") before 140, so the first `/v1/voice/speak` comes back sooner. Existing chunker tests have short first sentences and stay green.
2. **No mic re-open between turns** (D3) saves the getUserMedia start on each follow-up.
3. **"Pause allowed mid-sentence"** is adjustable (D4). Every 100 ms here comes straight off the delay.
4. **Fixed lines cached.** Handover, mic off and check-in audio is cached per page (8 entries, keyed by text + voice + rate) when the caller marks `meta.fixed`. This saves characters and a round trip.
5. **Sound cues** (`cues`, default on). Short generated tones, no file, through the speaker's context so they follow the chosen device and the echo canceller. Rising tone when listening starts, a soft tick when JARVIS has heard the owner, falling tone for mic off, a longer fall for handover. The loop starts the VAD 100 ms after a cue ends. No rise for an interruption's own turn (`jarvis:voice-loop` carries `barge: true`; it starts at once) or when speech is heard while standing by (the owner is already talking) (I1).
6. **A timing line.** `performance.mark` at each stage (speech ended → words → answer → first audio, plus each interruption's delay) is emitted as `jarvis:voice-timing` and as an event-log line. The Voice panel shows "Last reply: 3.1 s (listening 1.2 · words 0.6 · answer 0.9 · voice 0.4)".

Expected per-stage ranges are unmeasured: listening 1.2 s by default, words ~0.6–1.2 s, answer ~1–6 s, voice ~0.3–0.9 s. The timing line measures them, and owner check 14 reports the slowest stage.

### D16 · Tuned recognition (owner C)
- **Server.** `VoiceSettings.phrases: tuple[str, ...]`, owner-editable in the Voice panel under "Words to recognise". Each request sends the **base list** followed by the owner's list, de-duplicated case-insensitively.
  - The base list lives in a new `voice/commands.py`: JARVIS, Jarvis, Hey Jarvis, the honorific, and the multi-word command phrases (mic off, stop listening, switch off the mic, switch to the keyboard, switch to my earphones, switch to my speaker).
  - Single common words such as "stop" are not hints, to avoid biasing ordinary speech.
  - No `boost` is set in R5; it risks inserting "Jarvis" where it wasn't said. Revisit after owner feedback.
- **Validation (`apply`).**
  - At most 50 entries, each 1–40 characters after NFC, stripping invisible and control characters, and collapsing spaces.
  - Each needs a letter; allowed are letters, digits, space and `-'.&`.
  - Too many or too long is rejected with a 422 in plain words; nothing is silently trimmed.
  - `decode` drops stored entries that are invalid.
- **Size.** 50 × 40 = 2,000 characters, far below Google v1's limits. The exact per-phrase and per-request limits are confirmed at build from the quotas page.
- **Reading settings.** `transcribe()` reads the settings through `settings_of(uid)`: cached, bounded to 1 s, falling back to the defaults. A settings failure means base hints only and never fails the transcription. Memos benefit too.
- **No contacts dump.** The list is manual only.
  - Suggested entries in the help text: "Thiruvananthapuram, Trivandrum, the names you use".
  - The words are sent to Google STT in the owner's own project and are never logged (count only).
  - A change is audited with `record_change(agent='owner', tool='voice_phrases_set', args={'count': n})`, never the words, following the SEC-3 precedent.
  - They appear in the Privacy panel through a new `voice/privacy.py::voice_phrases_source` (look / export / delete), wired at I1.
- **Browser engine.** Chrome's recogniser ignores `SpeechGrammarList`, so it **can't take these hints**.
  - If the build finds a `phrases` contextual-biasing option on `SpeechRecognition` (newer Chrome, on-device recognition), pass the same list after feature-detecting it; otherwise do nothing. Verify at build from primary docs.
  - **As built (I1):** the Web Speech spec ties `phrases` to on-device recognition: on a recogniser without `processLocally === true`, `start()` fails with `phrases-not-supported`. So `JarvisVoicePhrases.apply()` sets `phrases` only when `processLocally` is true (the console does not set it today, so the browser engine gets no hints yet), and a `phrases-not-supported` error retries the same turn once without them. The editor says "the browser's own listening uses them only where your browser supports it".
  - The router's "jarvis" variants partly make up for it.

### D17 · Costs
- **Waiting:** ₹0.
- **Each spoken turn:** costs what it costs today, metered on Google's `totalBilledTime`.
- **No turn limit means more minutes.** A 6 s turn is 0.1 minute. The free 54 minutes cover about 540 turns a month (~18 a day). Beyond that it is ≈ ₹2.3 a minute, about ₹0.23 a turn.
- **The 55 s turn cap** raises only the worst case.
- **Name-mode checks:** at most 3 empty checks per reply, each ≤ 2.5 s.
- **Open item.** If Google rounds each v1 request up (for example to 15 s), checks and short turns cost several times more. Owner check 13 reads one 2 s clip's billed time. If it is rounded, checks drop to wake word only by default.
- **Fixed lines:** about 40 characters each, from the 900,000 free characters.
- **Wake model while JARVIS speaks, device switching, router, cues:** ₹0, all local.
- **Vitals:** already shows both voice allowances and warns at 80% (code fact 11). No Vitals change.
- **No new paid service, no Cloud Scheduler job, no secret.** The runaway guard (D6) plus the existing monthly limit (402) cap a runaway loop.

### D18 · Privacy and security
- No audio is stored, and transcripts are never logged (slice 9 D13 is unchanged).
- Check clips send up to 2.5 s of room audio to Google Cloud (the owner's project) **only** while JARVIS speaks, in a conversation the owner started, in name mode, on the cloud engine. The Interrupt row says so.
- The router can never approve, pay, send or delete, and it can never unlock the mic.
- Device labels and nicknames never leave the browser, **including spoken text**: the cloud voice posts every spoken line to `/v1/voice/speak`, so spoken device lines use kind words only and names are shown on screen only (I1 binding decision, B's H1; D12, D13). Capture's route events carry device ids, never labels.
- The unlock check (user activation) protects against JARVIS's own code paths. Same-origin script is already governed by CSP `script-src 'self'`.
- Run `security-reviewer` on A (mic lock, router, check clips) and C (phrases, PUT, audit, privacy source).

### D19 · Persona p4.9 → p5.0
- The new `VOICE_RULE` (D9).
- A new paragraph, `VOICE_CONTROL_RULE`: "The console itself handles 'mic off', 'stop', 'switch to the keyboard' and 'switch to <device>' before a message reaches you, also with the AI off. If the owner types such a request, point to the mic button or Ctrl + Shift + Space, or Voice → Sound devices. You cannot switch the microphone or sound devices; never claim you did."
- It is pinned by `tests/test_r5_persona.py`. The integrator bumps `PERSONA_VERSION` at I1 and updates the 14 tests that pin `"p4.9"`.

## Settings

**This device** (`localStorage['jarvis_voice_device_v1']`, validated in `readDevice` / `setDevice` in `console-voice.js`; a value of the wrong type or range is dropped and the default used):

| Key | Values | Default | Voice panel → On this device |
|---|---|---|---|
| (existing) `engine, finish, speak, autoSend, keepListening, wake` | unchanged | unchanged | "Keep listening" help text: "After a spoken reply JARVIS keeps listening. If you say nothing for 20 seconds he tells you and switches to the keyboard." |
| `interruptBy` | `auto`, `speech`, `name`, `tap` | `auto` | "Interrupt JARVIS by": Automatic · Speaking · Saying "Jarvis" or "stop" · Tapping only |
| `followUpS` | 5, 8, 12, 20, 30 (accepts 3–30) | 8 | "Wait for me to start speaking" |
| `longPauseS` | 15, 20, 30, 60, 120 (10–120, clamped to ≥ `followUpS + 5`) | 20 | "Switch to the keyboard after" |
| `endSilenceMs` | 800, 1000, 1200, 1600, 2000, 2500 | 1200 | "Pause allowed mid-sentence" |
| `checkIn` | boolean | true | "Check in when the room keeps talking" |
| `cues` | boolean | true | "Sound cues" |

**Mic lock:** `localStorage['jarvis_mic_off_v1']` = `'1'` or absent, owned by `console-voice-capture.js`. Shown as the "Microphone on this device" switch at the top of "On this device".

**Audio route:** `localStorage['jarvis_audio_route_v1']` = `{v:2, output:{id,label}|null, input:{id,label}|null, kinds:{id:{value:'headphones'|'speakers', label}}, names:{id:{value: ≤30 chars, label}}, onConnect:'ask'|'auto'|'never'}` (B: marks keep the label so a device whose id changed is found again; a stored v1 migrates). `onConnect` defaults to `'ask'`; input `null` means the system default (the laptop mic). Only panel choices are written here.

**Owner, server** (`{prefix}voice_settings/{uid}`): `phrases: list[str]`, at most 50 entries of 1–40 characters each, default `[]`. The base hints are always added server-side. `GET /v1/voice` returns `settings.phrases` and `phrase_limits {items: 50, chars: 40}`. `PUT /v1/voice/settings {phrases}` replaces the list.

**Fixed constants (not settings):** `MAX_LISTEN_MS 55000`, `RELISTEN_DELAY_MS 350`, the D6 check-in rule, the D7 `BARGE` constants, wake threshold 0.6 while JARVIS speaks.

## Events (new)

| Event | Detail | Fired by | Read by |
|---|---|---|---|
| `jarvis:mic-lock` | `{locked, by: 'button'\|'shortcut'\|'voice'\|'panel'\|'storage'\|'boot'}` | capture | mic, wake, mic-off UI, Voice panel, memo, devices |
| `jarvis:voice-loop` | `{state, conversation, turns, barge}` (`barge`: an interruption's own turn) | mic | devices (offers), pace (cues), mic-off UI, tests |
| `jarvis:barge` | `{how: 'speech'\|'wake'\|'stop'\|'tap', ms}` | mic / barge | pace (timing), tests |
| `jarvis:voice-command` | `{id, handled, state}` | commands | event log, tests |
| `jarvis:audio-devices` | `{outputs:[{id,label,kind}], inputs:[…]}` | devices | devices panel |
| `jarvis:audio-route` | `{output, input, reason}`; from capture `{input: {id, label: ''}, reason: 'input_missing' \| 'input_live'}` (ids only) | devices, capture | devices (missing input, live input clears "Pending"), panel |
| `jarvis:voice-timing` | `{heard, words, answer, voice, total, engine}` (ms) | pace | panel line, tests |
| `jarvis:voice-panel` | `{built: true}` | voice.js | devices panel, phrases, pace (render into slots) |

## I0 seams (integrator, before builders; branch `r5-i0`, tests green)
1. **`console-voice-capture.js`**, implemented fully:
   - `lock(by)`, `unlock(by) → bool` (requires user activation), `locked()`, `onLock(fn)`, `recognizer()`;
   - `setInput(id|null)`, `inputId()`, `trackLabel()`;
   - `open()` rejecting `'mic_off'`; `prime()` doing nothing while locked;
   - persistence and cross-tab sync; the OverconstrainedError fallback for a chosen input; `jarvis:mic-lock`.
2. **`console-voice-speech.js`**, implemented fully:
   - `speaker.setSink(id) → Promise<{ok, reason?}>`, `sink()`, `sinkSupported()`;
   - `duck(on)` (master gain 0.2/1, 60 ms ramp; does nothing for the browser voice);
   - `tone({freq, ms, gain}) → Promise`;
   - `stop()` returning `{rest: string[]}`;
   - `chunk` events gaining `at: performance.now()`.
3. **`console-voice-commands.js`** (new): the full core (registry, `normalise`, `handle`, `ask`, `owns`) and the PHRASES JSON table. Built-in matchers are left to A.
4. **`console-voice.js`**:
   - the new device keys, validators and panel rows (D4/D7/D15/D11 switch);
   - `JarvisVoice.panelSlot(name)` for `'devices' | 'phrases' | 'pace'`, firing `jarvis:voice-panel`;
   - `JarvisVoice.updateSettings(patch)` (wraps `change()`);
   - `phrases` in `normal()`, in `settings()` and in the after-PUT merge in `save()`;
   - `WAKE_WORDS.micoff`.
5. **`console-voice-mic.js`**: a minimal working `window.JarvisVoiceLoop = {state(), inConversation(), say(text, {speak}), ask(question, {yes, no}), offer(text, [{label, run}]), end(reason)}` built on the existing `say()`. A completes it; its shape is pinned.
6. **Stubs with frozen shapes:**
   - `console-voice-devices.js`: `JarvisAudioRoute {supported, refresh, current, chooseOutput, chooseInput, outputKind: () => 'unknown', find: () => null, on}`;
   - `console-voice-barge.js`: `JarvisBarge {policy: () => 'tap', arm: () => ({disarm(){}})}`;
   - `console-voice-pace.js`: `JarvisVoicePace {cue(){}, mark(){}, last: () => null}`;
   - empty headers: `console-voice-wake.js`, `console-voice-conversation.js`, `console-voice-micoff.js`, `console-voice-devices-panel.js`, `console-voice-phrases.js`, `console-voice-devices.css`.
7. **`console.html`:**
   - script order: capture → speech → commands → wakeword → voice → devices → devices-panel → pace → phrases → barge → conversation → voice-wake → micoff → voice-mic, and then the existing tags. **As built (I1):** capture → speech → commands → wakeword → voice → devices-match → devices → devices-panel → pace → phrases → barge → conversation → voice-wake → micoff → loop-glue → loop-browser → voice-mic;
   - the `console-voice-devices.css` link;
   - `#micOffBtn` (hidden, `aria-keyshortcuts="Control+Shift+Space"`), the struck-mic SVG inside `#micBtn`, and `#voiceOffer` under `#voiceLine`.
   - `api/console.py`: every new file in `APP_ASSETS`.
   - `console-fx.js`: `STATUS_WORDS.standby = 'Standing by'`, `.micoff = 'Mic off'`; `setVoice` accepts both. `console-voice.css`: minimal off and standby looks.
8. **`src/jarvis/voice/commands.py`** (new): `BASE_PHRASES` and `COMMAND_HINTS`.
9. **Test fixtures:**
   - the `make` factories in `tests/browser/test_voice.py` and `test_voice_robust.py` pin `interruptBy: 'tap'` unless a test passes `barge=True` or sets it. Their fake mics talk constantly, and tests that aren't about interrupting must not be interrupted.
   - Update `test_voice_panel_device_settings_are_kept_on_this_device` for the new keys.
10. **`tests/test_r5_seams.py`** (static):
    - assets registered and in order;
    - `getUserMedia(` only in capture;
    - no `new …SpeechRecognition`, `new R(` or `new Speech(` outside capture;
    - every multi-word phrase in PHRASES is in `COMMAND_HINTS`;
    - device defaults; the FX words.
    
    **`tests/browser/test_r5_seams.py`:**
    - lock stops every track and `open()` rejects; reload stays locked; `unlock()` from `evaluate` is false and from a clicked test button is true;
    - `setInput` constraints and the missing-device fallback;
    - `setSink` calls a stubbed `AudioContext.prototype.setSinkId`, including for a later context;
    - `duck` / `tone` / `stop().rest`;
    - command round trip; panel slots; `JarvisVoiceLoop` shape.

## Workstreams (worktrees; tests first; branches `r5-a`, `r5-b`, `r5-c` from `r5-i0`)

**A · The listening loop.** Interrupting, no turn limit, standby and handover, check-in, mic off, router built-ins, memo safety.
- **Owns:** `console-voice-mic.js`, `console-voice-wake.js` (first commit: move the "Hey Jarvis" block, l.419–538, out of mic.js with no behaviour change), `console-voice-conversation.js` (follow-up / standby / long-pause clock, quick-reply detection, check-in), `console-voice-barge.js` (gate, policy, check clips, echo guard, wake while speaking), `console-voice-micoff.js` (off button, shortcut, announcements), `console-voice-commands.js` (after I0), `console-voice-capture.js` (after I0: VAD `seed`, a strict mode after a set time, `maxMs`), `console-voice.js` (after I0: help texts), `console-voice.css`, `console-notes-memo.js`.
- **Tests:** `tests/browser/test_voice.py`, `test_voice_robust.py`, `test_notes.py`, and new `test_voice_loop.py`, `test_voice_barge.py`, `test_voice_commands.py`, `test_voice_micoff.py`, `tests/fixtures/voice_commands_cases.json`.
- **Must not touch:** speech.js, devices*, pace, phrases, any server code, console.html, console.py, console-fx.js.

**B · Audio devices.**
- **Owns:** `console-voice-devices.js` (route, kinds, persistence, devicechange, `find`, registers `device.*` and uses `JarvisVoiceLoop.say/ask/offer`), `console-voice-devices-panel.js` (picker in the 'devices' slot: outputs and inputs, kind and nickname, Test tone with `speaker.tone`, "When a new device connects", Android and browser-voice lines), `console-voice-devices.css`.
- **Tests:** new `tests/browser/test_voice_devices.py` (stubbed `enumerateDevices`, `setSinkId`, `devicechange`; Android user agent with `setSinkId` removed) and `tests/test_voice_devices_static.py` (no `api(` or `fetch(`, `textContent` only).
- **Must not touch:** everything else. It uses only the I0 APIs.

**C · Faster replies, read-it-all, tuned recognition.**
- **Owns:** `console-voice-speech.js` (after I0: short first chunk, decode-failure fallback, fixed-line cache), `console-voice-pace.js` (cues, timing, panel line in the 'pace' slot), `console-voice-phrases.js` (editor in the 'phrases' slot through `updateSettings`; existing classes only).
- **Server:** `voice/settings.py`, `voice/service.py`, `voice/privacy.py` (new), `api/voice.py` (audit on phrases, docstring), `core/prompts.py` (`VOICE_RULE` and `VOICE_CONTROL_RULE` only), `evals/voice/*`.
- **Tests:** `test_voice_settings.py`, `test_voice_service.py`, `test_voice_api.py`, `test_voice_google.py`, `test_voice_persona.py`, new `test_r5_persona.py`, `test_voice_privacy.py`, `test_evals_voice.py`, `tests/voice_fakes.py`, `tests/browser/test_voice_live.py`, new `tests/browser/test_voice_pace.py`.
- **Must not touch:** mic, capture, commands, barge, wake, mic-off, devices, voice.js, `PERSONA_VERSION`. If an existing `test_voice.py` expectation has to change, C asks the integrator.

**I1 (integrator):**
- Merge A → C → B; the file sets are disjoint.
- Register `voice_phrases_source` where `settings_source(` is wired.
- `PERSONA_VERSION` to p5.0, updating the 14 tests that pin it.
- Run `make test lint type eval-mock` and the browser suite with `JARVIS_BROWSER_TESTS=1`.
- `code-reviewer` and `python-reviewer` in a fresh context; `security-reviewer` on A and C.
- Write the review log in this file; update `release-plan.md` (R5 status) and the go-live guide.

**Shared rules:**
- Tests first, 80%+ coverage; functions ≤ 50 lines; files ≤ 800 lines (extract at 720).
- `textContent` only, no CDN, ₹ only, plain English with `honorific()`.
- Secrets via env only; append-only audit; transcripts and device labels never logged.
- No vendor SDK outside `jarvis.llm`.
- No edits to lint or format config.

## Tests

**Existing tests that change (new behaviour, not weaker tests):**
- `test_voice_robust.py` §2, by A:
  - `test_conversation_mode_stops_after_three_hands_free_turns` → `test_conversation_is_not_capped` (12 turns at human pace);
  - `test_conversation_mode_with_continuous_room_audio_stops_by_itself` → `test_a_room_that_never_stops_talking_gets_a_check_in_then_the_keyboard`;
  - `test_relisten_ends_when_speech_does_not_start_within_three_seconds` → `test_silence_goes_to_standby_at_8_s_and_hands_over_at_20_s`;
  - `test_a_wake_word_turn_relistens_under_the_same_cap` → no turn limit after "Hey Jarvis" as well.
- Also in `test_voice_robust.py`, by A:
  - `test_listening_is_capped_at_thirty_seconds_on_the_clock` → 55 s;
  - `test_an_unplugged_microphone_ends_listening_and_says_so` → the announced handover in a conversation;
  - `test_wake_word_is_paused_while_jarvis_speaks_and_resumes_after_the_echo` → split by policy (paused under tap and speech; resumed at 0.6 under name);
  - `test_mic_button_name_is_stable…` → adds standby and off.
- `test_voice.py`: the factory pin (I0); `test_voice_panel_device_settings…` (I0).
- `tests/test_voice_api.py:378` → base plus owner phrases (C). `tests/test_voice_persona.py:169` → still includes "60 words" and "on screen", plus the read-out clause (C).
- `tests/test_evals_voice.py` suite set gains `"hints"` (C). The 14 `PERSONA_VERSION` pins (I1).

**New browser tests.** Playwright with `--use-fake-ui-for-media-stream`, `--use-fake-device-for-media-stream` and `--use-file-for-fake-audio-capture` (the existing `browser` fixture), plus the existing `TONE_MIC`, `SLOW_GUM`, `FAKE_WAKE` and `FAKE_RECOGNITION` stubs from `test_voice_robust.py`:
- **Interrupting** (`test_voice_barge.py`, A):
  - the pure gate run on synthetic frame and output-level sequences;
  - Speaking policy with an earphones route: `__talk(true)` mid-reply stops JARVIS in ≤ 0.6 s, and the turn starts with the seeded frames;
  - name policy: talking over JARVIS lowers his volume and sends one check clip; a "stop" transcript stops him; another transcript returns his volume and the reply plays to the end;
  - a fake wake fires while he speaks;
  - resume after an empty interruption;
  - limits on check clips.
- **Loop** (`test_voice_loop.py`, A): no turn limit, standby, handover line and microphone closed (`JarvisAudio.isOpen()` false unless standby is on), check-in yes and no, the notified endings, a typed reply never opening the mic.
- **Router** (`test_voice_commands.py`, A): at least 80 cases from `voice_commands_cases.json` (positives and negatives at 100%), `ask()` timeout, typed "mic off" goes to the chat and the mic stays on.
- **Mic off** (`test_voice_micoff.py`, A): button, shortcut, voice, panel, reload, cross-tab, memo refusal, an in-flight transcription aborted.
- **Devices** (`test_voice_devices.py`, B): the list with kinds, choosing and remembering, restore after reload, offer, automatic switch, disconnect fallback, voice switch commands, the browser-voice line, Android instructions, no server call carrying labels.
- **Pace** (`test_voice_pace.py`, C): long first sentence gives a first chunk ≤ 140 characters, decode failure falls back to the browser voice, cues play and are skipped while he speaks, `jarvis:voice-timing` has every stage, fixed-line cache hit.

**Negative controls** (each must make its suite fail if the guard is removed):
1. **Mic off on:**
   - no `MediaStreamTrack` with `readyState === 'live'` (the `SLOW_GUM` wrapper keeps every stream);
   - the getUserMedia call count is unchanged for 25 s, across follow-up and long-pause timers, "Hey Jarvis" boot, `pageshow` and a memo Record;
   - no recogniser constructed;
   - `JarvisAudio.unlock()` from script returns false.
2. **No self-interruption on built-in speakers.** An `ECHO_MIC` stub drives the mic from `JarvisVoice.speaker.level() × 0.35` with a 60 ms delay, on a speakers route, with a 6-chunk reply containing "stop", "wait" and "Jarvis". Result: every chunk is spoken, no `jarvis:barge`, no `/transcribe` call. Control: margin 1.0 must fail this.
3. **Router never substring-matches.** "remind me to stop at the shop", "wait for the delivery at five", "switch to dark mode" and "use the earphones coupon" all go to the chat. Control: a naive substring matcher run in the page must fail at least 10 negative cases.
4. **Echo transcripts are never handled.** A forced check transcript equal to the current chunk's text is ignored.
5. **The runaway guard holds.** A TV pattern reaches the check-in at 8 turns, then handover. With `checkIn` off, the same pattern runs on (the test stops at 15).
6. **Phrases are bounded.** 51 entries or a 41-character entry give 422 and nothing is written. Control: with validation off, the "hints" eval sees an oversized list reach the engine and fails.

**Server unit tests (C):**
- `apply` / `decode` for phrases;
- `transcribe` sends base plus owner hints, and only base when settings can't be read;
- phrases never appear in logs (caplog);
- PUT with phrases writes one audit entry holding only a count;
- the privacy source supports look, export and delete;
- the persona paragraphs are pinned.

**Mock evals** (`evals/voice`, in `make eval-mock`):
- new "hints" suite, at least 12 cases with the negative control above;
- "persona" gains p5.0 voice-rule cases (the read-out clause on `voice` only; the control rule on every channel).

## Owner checks at test time (Windows laptop with Chrome, then the Android phone; none can be checked in the sandbox)
1. With Bluetooth earphones, ask for a long answer and talk over JARVIS halfway. He goes quiet in under half a second and answers what you just said.
2. With the laptop's speakers and "Interrupt by: Automatic", ask for a long answer that includes the words "stop" and "wait". He reads it to the end without stopping himself.
3. Same setup, say "Hey Jarvis" or "stop" over him. He goes quieter at once and stops within about two seconds.
4. Hold a 10-turn conversation without touching anything. Nothing caps it.
5. Say nothing after a reply. At about 8 s the status reads "Standing by". At about 20 s he says "I'll switch to the keyboard, Sir." and the browser's mic icon goes out, unless "Hey Jarvis" is on, in which case "Hey Jarvis" still works.
6. Say "mic off". The browser's and Windows' mic-in-use icons go out. Reload: still off. Say "Hey Jarvis": nothing. Tap the mic: he listens.
7. Ctrl + Shift + Space switches the mic off and on. Notes → Record refuses while the mic is off.
8. Pair your earphones and a speaker in Windows. Voice → Sound devices lists both. Pick each and press Test. Say "switch to my speaker", "switch to my earphones" and "switch to the laptop".
9. Switch the earphones on while JARVIS is idle: the offer appears. Try "Switch automatically".
10. Choose the earphones' microphone. Sound becomes call quality; that is Windows, as warned. Switch back to the laptop mic.
11. On the phone: Sound devices shows the Android steps, and "switch to my earphones" tells you where to switch.
12. Add Thiruvananthapuram, Trivandrum and the names you use under "Words to recognise". Say a sentence with them before and after adding them.
13. After a day of use, check Voice → This month and the voice rows on Vitals. Tell us the billed time of one 2-second "stop" (from the server log), to settle D17's rounding question.
14. Read the "Last reply" timing line and tell us which stage is slowest.
15. With a TV on near the laptop on speakers, JARVIS must not keep interrupting himself or keep talking to the TV. If he checks in, say "yes".

## Acceptance criteria (what the owner sees)
- Talking over JARVIS on earphones stops him in under half a second; on speakers he never stops himself.
- Conversations have no turn limit and end only with his spoken handover line.
- "Mic off" puts the mic icon out, survives a reload, and only your tap switches it back on.
- JARVIS switches between earphones, speaker and the laptop by voice or in the panel.
- The first words of a reply come sooner, and the timing line shows where the time goes.
- Your words are recognised better on the cloud engine.
- Cost stays at ₹0 within the free allowance.

## Risks
- **Echo cancellation quality.** How well Chrome cancels JARVIS on built-in speakers, or with a non-default output, is uncertain. Mitigation: Automatic uses name mode on speakers; checks 2 and 15.
- **Android.** getUserMedia next to SpeechRecognition can conflict, echo cancellation is weaker, there is no `setSinkId`, and recogniser restarts chime. Mitigation: D3 fallback, D14 instructions, cloud engine recommended.
- **Bluetooth.** The hands-free profile drops quality when a headset mic is used (D13 keeps the laptop mic). Headset output latency (~0.2 s) is out of our control (D10).
- **Wake model while JARVIS speaks.** It runs on the main thread. If the device is overloaded, interruption by name switches off for that page only; the owner's setting is kept.
- **A runaway TV loop.** D6 plus the monthly limit. **STT rounding** could raise check costs (D17, check 13).
- **False interruptions break "read to the end".** Mitigations: the gate, the echo guard, and resume after an empty interruption (D9).
- **The mic light stays on for the whole conversation.** It is honest, and the off button sits next to the mic.
- **Old tests encode the 3-turn cap and the 3 s wait.** They are rewritten to the new behaviour, listed above, and are not weakened.
- **The R4 plan reserved R5 for camera and smart home.** Rescheduled to R7/R8 by release plan v4.
- **The wake model's licence** (CC BY-NC-SA, personal use) covers its use while JARVIS speaks too. It must be replaced before any public launch (unchanged from slice 9 D12).
- **Device labels can contain personal names.** They stay local (D13, with a static test).

## Open questions (none block the build; safe defaults until answered)
1. Should "stop listening" mean mic off (default, as the requirement says) or just end the conversation?
2. Check-in when the room keeps talking: on (default) or off?
3. Interrupt by: Automatic (default)?
4. Keep the mic open while JARVIS thinks during a conversation (default yes)?
5. When a new device connects: Ask (default)?
6. After mic off, should a tap on the mic also start listening (default yes)?
7. Is Ctrl + Shift + Space acceptable as the shortcut?
8. Should speech during THINKING be ignored (default) or queued?
9. Persona version name: p5.0 (default) or p4.10?

## Line counts (estimates; extract if a file passes 720)

| File | Now | After I0 | After the build | Extraction |
|---|---|---|---|---|
| console-voice-mic.js | 553 | ~575 | ~610 | wake → `console-voice-wake.js`; clock → `-conversation.js`; barge → `-barge.js`; off UI → `-micoff.js` |
| console-voice-wake.js | — | stub | ~170 | — |
| console-voice-conversation.js | — | stub | ~200 | — |
| console-voice-barge.js | — | ~40 | ~260 | — |
| console-voice-micoff.js | — | stub | ~110 | — |
| console-voice-commands.js | — | ~170 | ~300 | — |
| console-voice-capture.js | 249 | ~325 | ~355 | — |
| console-voice-speech.js | 387 | ~425 | ~455 | — |
| console-voice.js | 567 | ~650 | ~660 | B and C render into slots; if over 720 at I0, move the device rows to `console-voice-rows.js` |
| console-voice-devices.js / -devices-panel.js / .css | — | stubs | ~400 / ~300 / ~90 | logic and UI kept apart |
| console-voice-pace.js / -phrases.js | — | stubs | ~230 / ~200 | — |
| console-notes-memo.js | 152 | 152 | ~170 | — |
| console-fx.js | 569 | ~572 | ~572 | — |
| console-wakeword.js | 443 | 443 | 443 | unchanged |
| console-voice.css | 100 | ~120 | ~150 | — |

Server files:

| File | Now | After the build |
|---|---|---|
| `voice/settings.py` | 135 | ~200 |
| `voice/service.py` | 532 | ~555 |
| `voice/commands.py` | new | ~50 |
| `voice/privacy.py` | new | ~70 |
| `api/voice.py` | 180 | ~195 |
| `core/prompts.py` | — | +~15 |

## Needs you first (skipped this release)
- **Your own trained wake word.** Needs your recordings and a training pipeline. It would also replace the non-commercial model before any launch.
- **The speaker check / voice ID.** Needs enrolment samples. It is the real fix for a TV or another person interrupting JARVIS, and the only route to voice approvals; even then, never for irreversible (R3) actions.

**Deferred without needing you:**
- the streamed tool loop (R11, D15);
- cloud streaming STT (needs a WebSocket or gRPC bridge);
- output switching on Android (a platform limit).

## To verify at build (primary docs or Context7; not accessed while planning)
- `AudioContext.setSinkId` support (Chrome 110 and later), and that Chrome for Android lacks `setSinkId` (the brief cites caniuse).
- Whether Chrome's echo canceller references Web Audio output sent to a non-default sink.
- Google Speech-to-Text v1 speech adaptation with `latest_short` / `latest_long`, the `speechContexts` limits, and how `totalBilledTime` rounds.
- Any contextual-biasing (`phrases`) option on the Web Speech API in current Chrome.
- Windows 11's Win + Ctrl + V quick sound-output picker.
