Version v6.4.4 · 27 Nov 2026, 21:25 IST · Release R18 · Status: Current · Owner: 🛠 Mark XXV

# 11 · Target architecture: the roadmap by release

Chapters 01–08 describe JARVIS as built (live release `v6.4.0`, plus R18 `v18.0.0`, built and
joined with this edition, not yet deployed). This chapter describes where it is going: for each planned release, the components it adds, the existing ports and services it reuses, and where it bends or conflicts with the as-built design. The order is the owner's (17 Nov, reaffirmed 27 Nov): **R18 calls → R5.2 voice → R8 → R8.1 → R9**, then R10, R12, the subscription releases R15–R17, the launch (R18.1) and the deferred trading desk (R19). Requirement rows are the workbook's serials (chapter 10).

## Summary

| Release | Version | Rows | Main layers | New runtime surface | Status (27 Nov) |
|---|---|---|---|---|---|
| R18 Calls from your laptop | `v18.0.0` | 387, 395, 396, 104, 195–197 | 1, 2, 3, 4, 5, 6, 7, 8 | Windows **call desk** on the laptop; phone app call permissions | Built and joined; in its combined review; not yet deployed |
| R18.x follow-ups | — | (within R18's rows) | 2, 4, 6 | — | Planned: the brain check per language first (below) |
| R5.2 Your voice | `v5.2.0` | 81, 83, 84, 383 | 1, 2, 6, 7, 8 | Laptop **speech kit** behind the local gate | Planned (`r5-2-plan`) |
| R8 Vision core & desk camera | `v8.0.0` | R8's 25 (with R13's activity rows) | 2, 5, 6 | Vision engine on the home laptop | Planned; cameras in |
| R8.1 Workout spot | `v8.1.0` | the workout-spot rows | 2, 5 | Pose models on the tripod phone | Planned; camera in |
| R9 Kitchen & nutrition | `v9.0.0` | R9's 20 | 2, 5, 6 | Kitchen camera stream (when installed) | Planned; phone rows first |
| R10 Care & health assist | — | R10's 13 | 2, 5, 7 | Health readings store | Planned; split across builds |
| R12 Smart home | — | R12's 14 | 6 | Home Assistant devices, Cast, Matter | Later (owner lists devices) |
| R13.2 Immersive maps | `v13.2.0` | 384, 385 | 1, 6 | Maps 3D and Street View in the console | Proposed, not approved |
| R15 / R16 / R17 | — | 16 / 11 / 18 | 4, 5, 6 | Paid AI features, social reads | Planned (subscription) |
| R18.1 Launch | `v18.1.0` | 2 | cross-cutting | — | Feb–Mar 2028 |
| R19 Trading desk | — | 1 | 5, 6 | Broker integration | Decision later |

## R18 · Calls from your laptop (`v18.0.0`)

Plan: `docs/plans/r18-calls.md` (approved 25 Nov; D8 keeps the audio recordings). Build brief and contracts: `docs/plans/r18-calls/BUILD-BRIEF.md`; the join: `docs/plans/r18-integration/I1-NOTES.md`. **Status (27 Nov 2026):** built on the `r18-*` branches, joined, in its combined review and joined with this edition of the ADD; not yet merged to `main` or deployed. The as-built design is in chapters 02–08 (components C74–C78, ADR-27 and ADR-31 to ADR-39); the table below is the plan's design delta, kept for the record.

| Layer | Adds | Reuses |
|---|---|---|
| L1 | Calls panel, call cards (number masked), live call view (captions, Listen live, Take over, Tell JARVIS, Hang up), the language table | Console theme and tokens; approval cards and passkeys; Vitals' cost line |
| L2 | Call hearing and voice adapters (Google within its free allowance, Azure free tier, Bhashini, Sarvam off), language detection, phone-line simulation, the **language check** that gates every language | `jarvis.voice` (Google speech, free-allowance metering) |
| L3 | The call session state machine and an in-memory **call hub** joining the desk, the phone and live listeners | Session and owner auth; the home bridge's signed-device auth |
| L4 | The in-call brain prompt on the **fast** tier with structured output; the **reply guard** (no OTP/card/bank/ID-shaped strings unless on the card; nothing beyond the card) | `jarvis.llm` tiers and prompt caching; untrusted-content rules |
| L5 | `jarvis.calls` (Communication skill): cards, approvals, limits and caps, booking, templates (laundry), answering policy | Gateway R3 confirmation tokens; skill register |
| L6 | **Call desk** (`jarvis.calldesk`): a Windows program (WASAPI loopback hearing, VB-CABLE as the microphone during a call, watchdog restore, Bluetooth-headset check, DTMF); phone app commands `call.dial/answer/end/route` and `call.state` events | R7 phone door and its cloud → phone channel; the home kit's download and signing pattern |
| L7 | `calls`, call limits, language results; recordings, transcripts and summaries **in the vault** (30 days) | Vault encryption; retention job on the scheduler |
| L8 | JARVIS's voice in the call; English summary; Google Calendar entry with Undo after a booking | Calendar tool via the gateway; undo |

**Bends the as-built design:**
- **Cloud Run `--timeout` 300 → 1800 s** so a call's WebSockets survive; still `--max-instances 1`, which the in-memory hub relies on.
- A **second laptop runtime outside the home kit's Linux container** (Windows-native), because WSL cannot reach Windows audio or Bluetooth.
- **Personal SIM, personal volume:** every call starts with the owner's tap (TRAI's 2026 rules on automated calls; chapter 12).
- The **Gemini free tier is excluded** from calls (third parties' voices and details), extending the existing "free brains never see tools" rule.

**Where the build differs from the plan** (each in chapter 12, section 6):

| Plan | As built in `v18.0.0` |
|---|---|
| Laptop speech mode, chosen per language by the check | A hook only; every call uses cloud speech |
| The check's step 4: a 10-turn mock call per language | Not built; never fails a language |
| Test clips from FLEURS and AI4Bharat IndicVoices | FLEURS only: English and 14 Indian languages can be checked, 8 can't |
| Bhashini tried when a language fails the others | Checked only when a request asks for it (the console never does), so never offered from the console |
| Recordings compressed, about 0.1 MB a minute | 8 kHz WAV, about 0.96 MB a minute (ADR-33) |
| The opening lines pre-made once per language | Their text is cached; their audio is made per call |
| Calls in the dock | No tab at 1920 px; Vitals' line, the chat's card and `?open=calls` (ADR-35) |
| A Privacy row for calls | Four rows, added by the combined review |

**Done by the combined review** (27 Nov 2026, `docs/plans/r18-integration/REVIEW.md`), so no
longer next: the deploy step for the speech keys (`deploy/cloudrun.sh:speech_keys`, mounted only
when stored) and sealing a waiting call card's number in `approvals`
(`src/jarvis/calls/pending.py:CallNumberSeal`).

**Next for R18 (R18.x, planned):** the brain check per language (the first follow-up); caching the
opening lines' audio; sealing every R3 card at rest the way calls now are; a compressed recording
format once an encoder is acceptable; laptop speech through R5.2's speech kit. The go-live guide
(a project document) needs the speech keys' step. Then the owner's live checks of plan step 6:
install the new phone app and the call desk, run the language check and score each voice, one
English call, one call with a language switch.

## R5.2 · Your voice (`v5.2.0`)

Plan: `docs/plans/r5-2-voice.md`, on branch `r5-2-plan` (not yet in `main`).

| Layer | Adds | Reuses |
|---|---|---|
| L1 | "Your voice" session screen; results page | Console theme |
| L2 | Personal wake-word verifier (stage 1) and an owned wake-word model (stage 2); in-browser speaker check (barge-in only, **never approvals**); engine choice by measured word error | Today's wake word and barge-in console modules |
| L6 | **Laptop speech kit** (planned: `jarvis.localspeech`, `deploy/local-speech/`): English and Indian-language engines behind Caddy + Tailscale **https** | The local-brain gate pattern (row 392's https rule) |
| L7 | Voice profile results; recordings only on the laptop, encrypted | — |
| L8 | Laptop English voice before Google, then the browser | `jarvis.voice` fallback order |

**Reuses R18, never copies it:** R18 owns `jarvis.calls.speech`, the language check and the call desk; R5.2 adds a bridge that satisfies R18's `Hearing`/`Voice` ports through the kit (`src/jarvis/calls/ports.py`), which is also what makes the call desk's laptop speech mode, a hook in `v18.0.0` (`src/jarvis/calldesk/speech_local.py`), selectable. **Conflict to close before launch:** today's wake-word model is licensed CC BY-NC-SA (personal use only); stage 2 replaces it.

## R8 and R8.1 · Vision core, desk camera and workout spot (`v8.0.0`, `v8.1.0`)

| Layer | Adds | Reuses |
|---|---|---|
| L2 | The vision engine on the home laptop (fixed cameras) and in the browser (desk camera); pose and object models added when first needed | R7's on-device engine (`jarvis.vision`, `jarvis.camera`) |
| L5 | Fitness coach items (rep and tempo, form, yoga, plank, balance …), desk posture, the activity timeline and screen time (R13's 2 rows) | Health & Wellbeing skill; nudges |
| L6 | Camera setup: each camera and spot, per-camera and per-room off switches, camera health in Vitals, the **no-cloud camera check** (row 377) | Home bridge (RTSP, Frigate, MQTT); "cameras off" |

**Principles carried from the vision plan:** frames are looked at on the device and thrown away; only results are kept; only the owner is tracked by default; children never; form tips are fixed rules, not AI calls. **Load limit:** 2–3 fixed cameras at a few frames a second on the 16 GB laptop (an estimate to confirm at R8).

**Hardware note for row 377 (27 Nov recommendation, no brand implied here):** a mains-powered indoor 2K pan/tilt camera that serves **RTSP (a main and a sub stream) and ONVIF Profile S on the home network**, H.264, with a memory card slot. A one-time vendor-app setup is acceptable; afterwards its internet access is blocked at the router and it is read only by the home laptop. Detection runs on the sub stream; face matching pulls frames from the main stream only.

## R9 · Kitchen & nutrition, R10 · Care & health assist

| Layer | Adds | Reuses |
|---|---|---|
| L2 | Food and label recognition on the phone; kitchen-camera events (boil-over as an **extra** warning only, never a fire or gas detector) | Vision engine; phone camera |
| L5 | Meal log, label scanner, tiffin check, pantry inventory (merges row 175), thermometer reader, fall-hazard survey, rehab and test helpers | R11's kitchen tools and USDA subset; Health & Wellbeing skill |
| L7 | Health readings: encrypted, in the Privacy panel, per-person consent | Vault keyring; privacy rows |

Medication items **remind only, never confirm a dose**; nothing states a diagnosis (an automated test). Kitchen-camera and medicine-station rows wait for those cameras.

## R12 · Smart home and camera extras

Layer 6 work on the home bridge: Home Assistant devices the owner lists (robot cleaner, Google Home and Nest via Cast with spoken greetings, Tuya, Matter), scenes, guest mode, quiet hours, parental controls, intercom, fall detection, smoke/gas/glass-break alerts. **Reuses** the home kit, its alert rule and Telegram/web-push alerts. **Bends:** the home kit is a laptop trial (WSL2 is not officially supported by Home Assistant or Frigate); an always-on box is the proper home (chapter 12).

## R13.2 · Immersive maps (proposed)

3D maps and Street View inside the console through the Maps JavaScript API JARVIS already uses, loaded only on request (expected ₹0 within the free monthly uses). Layers 1 and 6; awaits the owner's approval.

## R15–R17 · The subscription releases

| Release | Adds (by layer) | Reuses / bends |
|---|---|---|
| R15 Smart assistant | L4 helper agents, decision helper, deep research; L5 scam checker, trip planner, drafts in the owner's style, memory tidy-up, statements → spending; L6 social reads (X, Instagram, Facebook; LinkedIn browser-open only); camera search in plain words | `jarvis.llm` balanced/strong tiers with ₹ estimates; people-research scope stays limited (public figures and work contacts) |
| R16 Proactive smart features | L5 Automation Engine: smart nudges, follow-ups, meeting prep, work mode, news digest, the renewal tracker ★ and automation builder ★, evening home brief, AI time-use summary | Ticks and the scheduler; the brief; permissions rows; alert caps |
| R17 Learning, creative, coaching, kitchen AI | L5 Learning (tutor, kids' learning, language tutor), interpreter (Malayalam ↔ English first), what's-this camera, AI stylist, AI meal planner, voice-guided chef, AI fitness coach | **R18's speech and language check** for the interpreter; R13's wardrobe engine for the stylist; R9's meal log |

**Learning and Decision Support have no code today** (chapter 12); R15 and R17 create their packages.

## R18.1 · Launch (`v18.1.0`) and R19 · Trading desk

- **R18.1:** the full red-team test, final tests and two weeks of stable running (rows 108 and 113). Preconditions from this document: the owned wake-word model (R5.2 stage 2), a licence audit of every model and dataset, the scaling items of chapter 12 decided.
- **R19 (deferred, decision later):** an agent desk for trading. **Conflicts with confirm-before-commit** (the owner first asked for fully autonomous trading); any design needs an ADR that keeps money movements behind the owner's approval (ADR-30, proposed), plus paper trading first. *Unverified:* the "three months" of paper trading this chapter's first edition gave; no plan in the repository records a length.

## Not placed yet

| Row | What | Where it would go | Note |
|---|---|---|---|
| 376 | Gesture control | L2 on-device hand tracking (MediaPipe-class, Apache-2.0) in the browser and on the home laptop | Needs a build prompt approved; gestures never approve anything |
| 389 (and 2) | Gemini as the brain for Google tasks | L4: a paid Gemini provider in `jarvis.llm`, routed by skill | Paid tier only (the free tier never sees tools); each Google tool's evals must pass on it first |
| 386 | A 3D model of the owner from his photo | L5 wardrobe, cloud model behind a provider port | Release "Later" in the workbook, after "See it on me" proves itself |
| 198 | WhatsApp Business route | L6 | Needs a registered business |
| 129 | JARVIS Zero, a ₹0 edition | L4 provider order | Paused by the owner (2 Nov) |
| 35 | Swiggy and Instamart ordering | L6 | Placed in R1 in the workbook but still Pending; waiting on Swiggy's access |

## Change log

| Version | Date | Release | What changed | By |
|---|---|---|---|---|
| v6.4.1 | 27 Nov 2026, 14:20 IST | R6.4 | First edition: every planned release's design delta by layer, what it reuses and where it bends the as-built design; the hardware note for the no-cloud camera; the rows not placed yet | 🛠 Mark XXV |
| v6.4.2 | 27 Nov 2026 | R6.4 | Verification (chapter 13): the R18 and R5.2 plans named as branch files, not yet in `main`; the paper-trading period marked unverified; rows 35 and 386 carry their workbook release; R5.2's speech-kit folder marked planned | 🛠 Mark XXV |
| v6.4.3 | 27 Nov 2026, 20:50 IST | R18 | R18 "Calls from your laptop" built and joined: its status and where the as-built design lives; where the build differs from the plan; R18.x's follow-ups; R5.2 makes the desk's laptop speech selectable | 🛠 Mark XXV |
| v6.4.4 | 27 Nov 2026, 21:25 IST | R18 | The R18 review's later fixes: the speech keys' deploy step and the approvals seal moved from "next" to done; R18.x adds sealing every R3 card at rest and the go-live guide's speech-key step; the live checks include scoring each voice | 🛠 Mark XXV |
