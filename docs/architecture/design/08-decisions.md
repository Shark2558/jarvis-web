Version v6.5.0 · 27 Nov 2026, 20:40 IST · Release R18 · Status: Current · Owner: 🛠 Mark XXV

# 08 · Architecture decisions (ADR log)

**In plain words.** Each entry below is one decision that shaped JARVIS: what the situation was,
what was decided, what it costs or gives up, whether it still stands, and which code carries it
out. Many of them are places where the build departs from the original reference architecture
(the PDF, which proposed Postgres, Chroma or Pinecone, Redis, Kafka or NATS, ElevenLabs, MCP,
Kubernetes with Terraform, LangGraph and Next.js); each departure is recorded here with its reason.
From now on a plan that wants to change one of these writes a new ADR first (chapter 00).

**R18 ("Calls from your laptop")** accepts ADR-27 (calls through Phone Link and a Windows call
desk), now built, and adds ADR-31 to ADR-39: free speech first behind a language check, metering a
call's speech in one place, 8 kHz WAV recordings, English "not yet checked" before its first
check, the dock rule at 1920 px, the one-instance call hub, the phone's doorbell and signed
commands, the one-use grant for every call, and the live socket's ticket.

**Format.** Each ADR has a number that never changes, a status (Accepted, Superseded by ADR-n,
Proposed), the date and the release in which it was taken, and its source plan in `docs/plans/`.
Dates before R6.1 come from the guide's decisions log (section 5.4).

## 1. Index

| ADR | Decision | Reference proposed | Status | Since |
|---|---|---|---|---|
| 01 | This document is the canonical architecture reference | the PDF | Accepted | 27 Nov 2026 |
| 02 | Model-agnostic core: tiers, one provider interface, vendor SDKs only in `jarvis.llm` | Claude (Opus for reasoning) | Accepted | Phase 0 |
| 03 | One custom tool gateway with in-process tools over direct REST; no MCP | MCP | Accepted | Slices 1 and 6 |
| 04 | Firestore behind a small document port, not Postgres | Postgres | Accepted | Slice 5 |
| 05 | Word matching (BM25) for memory and notes, not a vector database | Chroma or Pinecone | Accepted | Slice 8 |
| 06 | Google Cloud speech with the browser as fallback; wake word on the device; no voice clone | Whisper or Deepgram; ElevenLabs | Accepted | Slice 9 |
| 07 | One Cloud Run service, at most one instance, one re-runnable deploy script | Docker → Kubernetes, Terraform | Accepted | Slice 2 (31 Oct 2026; the reason is *unverified*) |
| 08 | Keyless deploy on merge (Workload Identity Federation), only from `main` | GitHub Actions | Accepted | Slice 5c |
| 09 | A custom brain loop, not an orchestration framework | LangGraph | Accepted | Phase 0 |
| 10 | No event bus: Cloud Scheduler ticks, in-process gateway observers and an alerts port | Kafka or NATS | Accepted | Slice 7 onward |
| 11 | A brain that may train on prompts gets no tools and no personal data | — | Accepted | Slice 3 |
| 12 | All money in ₹, the owner's monthly limit checked before every paid call | — | Accepted | Slice 7b |
| 13 | Telegram and Web Push as the phone channels; WhatsApp only as drafts | Slack, WhatsApp, SMS | Accepted | Slice 12, R1, R3 |
| 14 | The owner's laptop as the offline brain, with at most 12 tools and none irreversible | — | Accepted | R1 |
| 15 | One keyring: a key per purpose derived from one root key; no Cloud KMS | — | Accepted | R2 |
| 16 | The home kit on the owner's laptop, reached through Tailscale Funnel; pictures stay home | Home Assistant and Matter | Accepted | R3 |
| 17 | A persisted No-AI mode that fails closed | — | Accepted | R4 |
| 18 | The phone app is a Trusted Web Activity around the console | React Native; Next.js for multi-device | Accepted (supersedes slice 2's "Next.js for Phase 6") | R7 |
| 19 | Vision runs in the browser with open tools; no cloud vision, no ML Kit | a vision input box | Accepted | R7 |
| 20 | Eleven skills in a register; each turn offered only the tools it needs | ten skills | Accepted | R14 |
| 21 | The Build Book is written at build time by the Workshop; JARVIS makes no AI call for it | — | Accepted (supersedes R6.3's runtime writer) | R6.3.1 |
| 22 | Structured JSON logs and Vitals now; OpenTelemetry later | OpenTelemetry and Grafana | Accepted (OpenTelemetry PLANNED) | Phase 0 |
| 23 | One plain-JavaScript console served by the API, no build step, strict CSP | Next.js and Tailwind | Accepted | Slice 2 |
| 24 | Backups are Google's managed copies after an owner step, proved by a monthly restore drill | — | Accepted | R14 |
| 25 | One instance with its state in memory while JARVIS has one owner (was proposed ADR-B) | — | Accepted | 27 Nov 2026 |
| 26 | The laptop is the home server for now; an always-on box later (was ADR-C) | — | Proposed | — |
| 27 | Calls from the owner's own SIM through Phone Link; a Windows call desk (was ADR-D) | a business call provider | Accepted | R18 |
| 28 | Only a brain that doesn't train on prompts sees tools or other people's data (was ADR-E) | — | Proposed | — |
| 29 | Shipped models and datasets carry permissive licences (was ADR-F) | — | Proposed | — |
| 30 | Trading: the owner approves every money movement, or it is not built (was ADR-G) | — | Proposed | — |
| 31 | Free speech first; every call language passes a language check | ElevenLabs, Deepgram | Accepted | R18 |
| 32 | A call's speech is metered in one place | — | Accepted | R18 (I1) |
| 33 | Call recordings are 8 kHz WAV, not a compressed format | — | Accepted (departs from plan D8's size) | R18 (I1) |
| 34 | English is offered "not yet checked" before its first language check | — | Accepted | R18 (I1) |
| 35 | Calls never displaces a tab in the dock; at 1920 px the bar is the bar before R18 | — | Accepted | R18 |
| 36 | One instance holds the call hub in memory; the request timeout is 30 minutes | Kubernetes | Accepted (applies ADR-25) | R18 |
| 37 | The cloud reaches the phone by a Web Push doorbell; the door carries signed commands | — | Accepted | R18 (Part D) |
| 38 | Placing a call is R3 with a one-use grant per call; never approved from Telegram | — | Accepted | R18 |
| 39 | The live call socket accepts a one-use ticket in token mode | — | Accepted | R18 (I1) |

## 2. The decisions

### ADR-01 · This document is the canonical architecture reference

- **Status:** Accepted, 27 Nov 2026 (the owner's ask: "create a new architecture design document
  as per the build and the requirements, verify the architecture, and refer to it in future").
  Settles chapter 12's proposed ADR-A.
- **Context:** The reference PDF predates the build and differs from it in at least ten places
  (this log). The plain-language guide explains parts, not rules.
- **Decision:** `docs/architecture/design/` is the reference for planning, building and review;
  the PDF is historical. A conflict is flagged and resolved by an ADR here before work goes on.
- **Consequences:** Every release's paperwork updates the chapters it changed. Since 27 Nov 2026
  the version-line check scans this folder too (chapter 07, section 5).
- **Code:** none; `docs/architecture/design/00-README.md`.

### ADR-02 · Model-agnostic core

- **Status:** Accepted, Phase 0 (by 1 Nov 2026). Source: `CLAUDE.md`; the guide, 5.4.
- **Context:** The reference made Claude the brain. Cost, privacy and outages argue for choice.
- **Decision:** Callers ask for a tier (fast, balanced, strong), never a model id. Every brain
  implements one provider interface. Only `jarvis.llm` imports an AI vendor's SDK.
- **Consequences:** Gemini, an OpenAI-compatible slot, the laptop and a mock run behind the same
  interface; degradation and fallback live in one router. Only Claude is proved by the real eval
  gate. `tests/test_llm_sdk_boundary.py` enforces the SDK boundary across `src/jarvis/` (follow-up
  F1, closed 27 Nov 2026).
- **Code:** `src/jarvis/llm/base.py:LLMProvider`, `src/jarvis/llm/router.py:ModelRouter`,
  `tiers_for`, `src/jarvis/llm/brains.py`.

### ADR-03 · One custom tool gateway, direct REST adapters, no MCP

- **Status:** Accepted, Slice 1 (gateway, 1 Nov 2026) and Slice 6 (no MCP, 1 Nov 2026). Sources:
  `docs/plans/phase2-slice1-tool-spine.md`, `docs/plans/phase2-slice6-gmail-calendar.md`.
- **Context:** Google's remote MCP servers were a developer preview; confirm-before-commit must be
  enforced in one place.
- **Decision:** Every tool is an in-process `Tool` with a declared risk; every call passes
  `Gateway.execute`; Google and other services are called by small REST adapters over `httpx`.
  Slice 6's wording: "MCP where a stable server exists; first-party API adapters behind the same
  tool contract otherwise."
- **Consequences:** One checkpoint for policy, cards, passkeys, taint and audit; each new service
  costs an adapter; no MCP client exists yet (`jarvis.tools.mcp_client` waits for a stable server).
- **Code:** `src/jarvis/tools/gateway.py`, `src/jarvis/tools/base.py:Tool`,
  `src/jarvis/integrations/google.py`.

### ADR-04 · Firestore behind a document port

- **Status:** Accepted, Slice 5 (1 Nov 2026). Source: `docs/plans/phase2-slice5-persistence.md`.
- **Context:** Free options compared on 1 Nov 2026: Firestore in the same project (no new account
  or secret, data in Mumbai), Neon Postgres (a new vendor and secret), Cloud SQL (no free tier).
- **Decision:** Firestore Native mode, reached only through the `Docs` port; stores never import
  the SDK.
- **Consequences:** ₹0 at one owner's size; no SQL or joins; transactions through the port; no
  TTL policies, point-in-time recovery or free backups (TTL deletes are billed, so JARVIS sweeps
  itself; backups came in ADR-24). A Postgres version can be added behind the same port.
- **Code:** `src/jarvis/storage/docs.py:Docs`, `src/jarvis/storage/firestore_docs.py:FirestoreDocs`.

### ADR-05 · Word matching, not a vector database

- **Status:** Accepted, Slice 8 (1 Nov 2026). Source: `docs/plans/phase3-slice8-long-term-memory.md`;
  the guide, 2.1.
- **Context:** Embeddings need another service to pay for and to send private text to.
- **Decision:** BM25 word matching over facts, notes and document chunks.
- **Consequences:** Free and private; weaker on paraphrase than embeddings; enough for one person.
- **Code:** `src/jarvis/recall/retrieval.py`, `src/jarvis/kb/search.py`,
  `src/jarvis/documents/chunking.py`.

### ADR-06 · Google speech, browser fallback, on-device wake word, no clone

- **Status:** Accepted, Slice 9 (1 Nov 2026) and R5 (wake word). Source:
  `docs/plans/phase1-slice9-voice.md` (decision 1), `docs/plans/r5-voice.md`.
- **Context:** ElevenLabs, Deepgram and Whisper mean new vendors and keys; copying a film voice
  without consent breaks voice vendors' rules; Whisper is slow on one server CPU.
- **Decision:** Google Cloud Text-to-Speech (British stock voices) and Speech-to-Text v1 as the
  service account, inside 90 % of the free allowance; the browser's own speech as the fallback;
  "Hey Jarvis" detected in the browser by openWakeWord.
- **Consequences:** ₹0 inside the allowance; paid above it against the monthly limit; the wake-word
  models are CC BY-NC-SA 4.0 (non-commercial; chapter 12, C8).
- **Code:** `src/jarvis/voice/google_cloud.py`, `src/jarvis/voice/service.py`,
  `src/jarvis/api/static/console-wakeword.js`.

### ADR-07 · One Cloud Run service, at most one instance

- **Status:** Accepted, slice 2 (31 Oct 2026, UTC). The Render blueprint (`render.yaml`, GitHub
  commit `3e73d81`) was followed 17 minutes later by the Cloud Run script (`db109f3`), before slice
  3. *Unverified:* why; no commit message, plan or deploy file records the reason. Source:
  `deploy/cloudrun.sh` header.
- **Context:** One owner; free first; no server to patch. Kubernetes and Terraform cost money and
  time for one owner.
- **Decision:** One service in `asia-south1`, `--min-instances 0 --max-instances 1`, 512 MiB, one
  CPU, 300 s timeout (1800 s since R18, ADR-36), deployed by one re-runnable script.
- **Consequences:** ₹0 at this size; rate limits, the per-conversation lock and nonce stores can
  live in memory; one instance is also one point of failure and the capacity ceiling (chapter 06,
  section 5). "Raise --max-instances only after sessions gain a cross-process concurrency check,
  and the home nonce cache moves out of process" (the script's own words). The conditions for
  moving out are ADR-25.
- **Code:** `deploy/cloudrun.sh` step 6, `src/jarvis/api/ratelimit.py`,
  `src/jarvis/home/signing.py:NonceCache`.

### ADR-08 · Keyless deploy on merge

- **Status:** Accepted, Slice 5c (1 Nov 2026). Source: `docs/plans/phase2-slice5c-command-deck.md`.
- **Decision:** GitHub Actions deploys `main` through Workload Identity Federation, restricted to
  this repository's id, `main`, push or manual runs of `ci.yml`, on GitHub's runners; a
  no-traffic candidate must pass `/health` before it takes traffic.
- **Consequences:** No stored key anywhere. Whoever can change `main` can ship code that runs as
  `jarvis-run`; branch protection and the owner's 2-step sign-in carry that risk.
- **Code:** `.github/workflows/ci.yml` (`deploy`), `deploy/cloudrun.sh:setup_autodeploy`.

### ADR-09 · A custom brain loop, not an orchestration framework

- **Status:** Accepted, Phase 0. Source: the guide, 2.1 ("Fewer moving parts and one place where
  every safety rule is enforced").
- **Decision:** One loop (`Brain`) runs context, the model, tool rounds through the gateway and
  storage; no LangGraph.
- **Consequences:** Every safety rule sits in code JARVIS owns; multi-step plans are bounded tool
  rounds (6), not graphs.
- **Code:** `src/jarvis/core/brain.py:Brain`, `src/jarvis/core/rounds.py`.

### ADR-10 · No event bus

- **Status:** Accepted as built. *Unverified:* the reason; no plan, commit or deploy file records
  it as a decision, and the context below is read from the code, not from a record.
- **Context:** One instance, scale to zero, free first: a broker would be a paid, always-on
  service.
- **Decision:** Time-driven work rides two Cloud Scheduler jobs; in-process observers hear every
  gateway outcome; alerts go through one port.
- **Consequences:** No durable queue: a job that fails is reported and retried by the next tick,
  not replayed; events between processes are not possible (one process).
- **Code:** `src/jarvis/ticks.py`, `src/jarvis/api/tick_wiring.py`,
  `src/jarvis/tools/observers.py`, `src/jarvis/alerts.py:AlertSink`.

### ADR-11 · A training brain gets no tools and no personal data

- **Status:** Accepted, Slice 3 (1 Nov 2026). Source: `docs/plans/phase2-slice3-gemini-free-brain.md`.
  ADR-28 (proposed) would extend it to other people's data (calls, row 389).
- **Decision:** `tools_allowed` is `not trains_on_content`; such a brain sees only turns after its
  cutoff, never tool output, memory, files or pictures.
- **Code:** `src/jarvis/llm/brains.py:BrainSpec`, `src/jarvis/core/brain.py:Brain._tools_on`,
  `_window_for`, `src/jarvis/recall/gate.py`.

### ADR-12 · Money in rupees, the limit before every paid call

- **Status:** Accepted, Slice 7b (1 Nov 2026). Source: `docs/plans/phase7-slice7b-inr-costs-budget.md`.
- **Decision:** Every cost is shown in ₹ at the day's rate; the owner's monthly limit is checked
  before each paid model or speech call and fails closed when unreadable.
- **Consequences:** No limit until the owner sets one; Anthropic's prepaid credit is then the stop.
- **Code:** `src/jarvis/billing/`.

### ADR-13 · Telegram and Web Push; WhatsApp only as drafts

- **Status:** Accepted, Slice 12 (3 Nov 2026), R1 (Telegram), R3 (Web Push). Source:
  `docs/plans/phase2-slice12-integrations.md`, `docs/plans/r1-free-tools.md`.
- **Context:** WhatsApp's business service bars general AI assistants (outside the EEA and Brazil)
  and needs a second number; unofficial tools risk a ban; SMS costs money.
- **Decision:** Telegram for chat and alerts, Web Push for browsers and the phone app, WhatsApp
  drafts the owner sends himself.
- **Consequences:** Telegram chats are not end-to-end encrypted, so private reads are off there by
  default and R3 is never approved there.
- **Code:** `src/jarvis/telegram/`, `src/jarvis/webpush/`, `src/jarvis/whatsapp/`.

### ADR-14 · The laptop as the offline brain

- **Status:** Accepted, R1 (4 Nov 2026). Source: `docs/plans/r1-free-tools.md` (D10–D12).
- **Decision:** When the cloud brain is unreachable, the same call goes to Ollama on the owner's
  laptop, offered at most 12 tools and none irreversible; writes become one-tap cards.
- **Consequences:** Works only while the laptop is awake; a small model is easier to steer, hence
  the tool limit.
- **Code:** `src/jarvis/llm/fallback.py:OFFLINE_TOOLS`, `src/jarvis/offline/service.py:LocalFallback`.

### ADR-15 · One keyring from one root key

- **Status:** Accepted, R2 (5 Nov 2026). Source: `docs/plans/r2-memory-vault.md` (D2).
- **Decision:** HKDF-SHA256 derives one key per purpose from `jarvis-token-key`; no new secret,
  no Cloud KMS (a paid call per use).
- **Consequences:** Separation without more secrets; the root key and the backups share one
  project; no rotation tool yet (`KEY_ID` allows one later).
- **Code:** `src/jarvis/keyring.py:Keyring`.

### ADR-16 · The home kit on the owner's laptop

- **Status:** Accepted, R3 (5 Nov 2026). Source: `docs/plans/r3-home-camera.md`.
- **Decision:** Home Assistant, Frigate and Mosquitto with JARVIS's bridge in Docker under WSL,
  reached through Tailscale Funnel with HMAC both ways; pictures and the face library stay home;
  one small opt-in burglar snapshot may go to Telegram. Matter is not used.
- **Consequences:** ₹0 and private; home features stop when the laptop sleeps; WSL is not an
  officially supported host for either program (ADR-26, proposed).
- **Code:** `deploy/home/`, `src/jarvis/home/`, `src/jarvis/homebridge/`.

### ADR-17 · A persisted No-AI mode that fails closed

- **Status:** Accepted, R4 (5 Nov 2026). Source: `docs/plans/r4-vitals-health-people.md`.
- **Decision:** A saved switch guarantees no model spend; fixed phrases still run tools through
  the gateway; an unreadable switch reads "none".
- **Code:** `src/jarvis/offline/mode.py`, `src/jarvis/offline/no_ai.py`, `src/jarvis/offline/rules.py`.

### ADR-18 · The phone app as a Trusted Web Activity

- **Status:** Accepted, R7 (12–13 Nov 2026). Supersedes slice 2's "Next.js remains the plan for
  the Phase 6 multi-device app". Source: `docs/plans/r7-mobile.md` (D1, D2).
- **Context:** Google refuses its sign-in inside an app's WebView, and a WebView has no Web Push;
  React Native would be a second copy of the console.
- **Decision:** A small Android app whose main screen is the console drawn by Chrome, plus a few
  native parts; the server accepts only its package and signing fingerprints.
- **Consequences:** One code base for laptop and phone; needs Chrome; the installed app is built on
  the owner's laptop, CI only proves it.
- **Code:** `android/`, `src/jarvis/api/phone.py`, `src/jarvis/phone/`, `src/jarvis/mobile/`.

### ADR-19 · Vision in the browser with open tools

- **Status:** Accepted, R7. Source: `docs/plans/r7-mobile.md` (D14).
- **Decision:** One engine in the page (tesseract.js, zxing-wasm, MediaPipe Tasks Vision, all
  Apache or MIT, served by JARVIS and pinned by hash); results, never frames, reach the server; not
  ML Kit (its terms report usage), not AGPL YOLO, no cloud vision.
- **Code:** `src/jarvis/vision/`, `src/jarvis/api/static/console-vision.js`, `scripts/vision_assets.py`.

### ADR-20 · Eleven skills in a register; tools offered per turn

- **Status:** Accepted, R14 (14 Nov 2026). Source: `docs/plans/r14-hardening.md` (D9, D11);
  the 11th skill was recorded in R6.1 (owner decision 10, 11 Nov 2026).
- **Decision:** Every tool is filed under one group of one of 11 skills (Health & Wellbeing
  added); a turn is offered only the groups its words and recent history need, plus a core of four
  and `skills_open`.
- **Consequences:** Smaller prompts (cost) and a skill map that can't drift (`scripts/skill_coverage.py`
  fails on an unfiled tool); the offer never bypasses the gateway.
- **Code:** `src/jarvis/skills/`.

### ADR-21 · The Build Book written at build time

- **Status:** Accepted, R6.3.1 (24 Nov 2026). Supersedes R6.3's runtime writer (R6's
  code-generated book remains its fact base). Source: `docs/plans/r6-3-1-book-at-build.md`.
- **Context:** Both brains failed the owner's runtime writer trial ("the API server was busy"); he
  asked for the whole book to be written during development, with no cost and no step for him.
- **Decision:** The Workshop writes all 153 pages and the flowcharts in the repository; CI checks
  them against the code before merge; the deploy compiles them; JARVIS makes no AI call for the
  Book.
- **Consequences:** ₹0 and nothing to approve; every release that changes cited code must rewrite
  its pages in the same pull request; the old trial's data stays until the owner deletes it.
- **Code:** `src/jarvis/buildbook/gen/`, `src/jarvis/buildbook/book/`.

### ADR-22 · Logs and Vitals now, OpenTelemetry later

- **Status:** Accepted; OpenTelemetry PLANNED for Phase 7. Source: `README.md` ("OpenTelemetry
  export in P7"); `src/jarvis/logging.py` docstring.
- **Decision:** Structured JSON logs with a per-request trace id in Cloud Logging; Vitals, the
  systems check and the self-health watch for the owner.
- **Consequences:** Free; no traces or metrics dashboards; `logging.py` is the one file to swap.
- **Code:** `src/jarvis/logging.py`, `src/jarvis/vitals/`, `src/jarvis/selfwatch/`.

### ADR-23 · One plain-JavaScript console

- **Status:** Accepted, Slice 2. Source: `docs/plans/phase2-slice2-web-console-auth.md`
  ("Deviation from default stack").
- **Decision:** One static page and its modules served by FastAPI; vanilla JavaScript, no build
  step; all model and tool text shown as text; scripts only from JARVIS itself.
- **Consequences:** One deployable and one URL; the console's look is frozen by rule (chapter 01,
  P6) and checked by the visual gate.
- **Code:** `src/jarvis/api/console.py`, `src/jarvis/api/static/`.

### ADR-24 · Managed backups and a monthly restore drill

- **Status:** Accepted, R14 (14 Nov 2026). Source: `docs/plans/r14-hardening.md` (D3, D4).
- **Decision:** Google's daily Firestore backups kept 7 days and delete protection, switched on
  only by the owner's own step; a monthly drill restores into a throw-away database and checks a
  sealed canary.
- **Consequences:** Recovery from bad writes and deletes; not from losing the project or the root
  key, which share it.
- **Code:** `deploy/backup_setup.sh`, `src/jarvis/backup/`.

### ADR-25 · One instance with its state in memory while JARVIS has one owner

- **Status:** Accepted, as built (27 Nov 2026; chapter 12's proposed ADR-B). The steps for moving
  the state out are recorded here; none of them is built.
- **Context:** ADR-07 chose one Cloud Run instance. Chapter 06, section 5 lists what lives in that
  one process because of it; R18's call hub added more (ADR-36).
- **Decision:** Keep `--max-instances 1` while JARVIS has one owner. Before a second user, a second
  instance or a load one instance can't carry, move out of the process, each with a test that two
  processes agree: the per-conversation lock and the rate limits (to Firestore transactions or
  Redis), the home and phone nonce stores, and, since R18, the call hub with its dial grants, live
  tickets, the desk socket's nonces and the phone's command outbox.
- **Consequences:** ₹0 and simple; one point of failure and one capacity ceiling. The deploy
  script's own warning stays the gate for raising the limit; its header comment names the rate
  limits, the write queue and the home nonce cache but not yet the call hub (chapter 12, section 6).
- **Code:** `deploy/cloudrun.sh` (header comment and step 6), `src/jarvis/api/ratelimit.py`,
  `src/jarvis/core/brain.py:Brain._serialised`, `src/jarvis/home/signing.py:NonceCache`,
  `src/jarvis/phone/door.py`.

### ADR-26 · The laptop is the home server for now; an always-on box later

- **Status:** Proposed (27 Nov 2026; chapter 12's proposed ADR-C). The laptop half is as built
  (ADR-16); the always-on box is not.
- **Context:** The home kit, the laptop brain and, when built, R5.2's speech kit and R18's call
  desk all run on the owner's laptop; when it sleeps, they stop. WSL is not an officially supported
  host for Home Assistant or Frigate.
- **Decision (proposed):** Keep the laptop until "the laptop must be on" hurts or a third camera
  arrives; then an always-on box (a Raspberry Pi 5 with an accelerator, or a mini-PC). Which parts
  move first is decided then (candidates in chapter 12, section 3).
- **Consequences:** No new spend now; the watchdog and Vitals already say when the laptop is off.
- **Code:** as built, `deploy/home/` and `src/jarvis/home/watchdog.py`; nothing yet for the box.

### ADR-27 · Calls from the owner's own SIM through Phone Link; a Windows call desk

- **Status:** Accepted, R18 (27 Nov 2026). Proposed in this log as chapter 12's ADR-D; decided in
  the R18 plan at its approval stop 1 (25 Nov 2026, decision D1); built on the `r18-*` branches and
  joined with this edition (not yet deployed). The plan's S0 laptop test of the real sound path is
  the owner's and has not been run, so the desk checks the path itself before every call. Source:
  `docs/plans/r18-calls.md` (sections 3 and 4).
- **Context:** The owner has no registered business (17 Nov), so a business call provider is out;
  Android does not let an ordinary app hear or speak into a phone call; WSL can't reach Windows
  audio or Bluetooth; Phone Link offers no choice of sound device and uses Windows' defaults;
  automated calls from a personal number fall under TRAI's rules (chapter 12, C5).
- **Decision:** The owner's own number. The phone app dials, answers and ends calls on the cloud's
  signed commands (ADR-37); the call's sound reaches the laptop through Windows Phone Link over
  Bluetooth; the call desk, a Windows program outside the home kit, hears it by recording the
  speaker (WASAPI loopback, sent only while the other person speaks) and speaks into it through
  VB-CABLE, made Windows' default microphone for the call only and restored afterwards, after a
  crash and at the next start. Every call starts with the owner's tap (ADR-38).
- **Consequences:** ₹0 a minute on an unlimited plan; calls need the laptop on, the desk running,
  the phone linked and no Bluetooth headset on the laptop (checked before every call); a second
  laptop runtime beside the home kit, started with it by `deploy/home/start-home.ps1`; a Phone Link
  update can change behaviour; a phone menu that needs keys works only if key tones played as
  sound pass through Phone Link (S0's Test C, not run). The desk's laptop speech mode is a hook
  only, so every call uses cloud speech.
- **Code:** `src/jarvis/calldesk/` (`micguard.py`, `audio.py`, `vad.py`, `checks.py`,
  `watchdog.py`), `deploy/calldesk/`, `src/jarvis/phone/calls.py`,
  `android/app/src/main/AndroidManifest.xml`, `src/jarvis/api/calls_ws.py:CallSockets`.

### ADR-28 · Only a brain that doesn't train on prompts sees tools or other people's data

- **Status:** Proposed (27 Nov 2026; chapter 12's proposed ADR-E; covers C4 and the calls
  exclusion). The tools half is as built (ADR-11). Since R18 the calls half is too: the in-call
  brain is never one that may train on prompts, and with none configured calls are not wired at
  all (`src/jarvis/calls/brain.py:pick_call_brain`, `NoPrivateBrain`). The Gemini brain for Google
  tasks (row 389) is not built, so the ADR stays Proposed.
- **Context:** Calls carry third parties' voices and details; row 389 asks for Gemini as the brain
  for Google tasks.
- **Decision (proposed):** A brain that sees tools, memory or other people's data (call audio,
  contacts, mail) must be one that does not train on prompts: the free Gemini tier stays tool-less
  and is excluded from calls; a Gemini brain for Google tasks only on the paid tier, with each
  Google tool's evals passing on it first.
- **Consequences:** Some free options stay closed to the features that would use them.
- **Code:** as built, `src/jarvis/llm/brains.py:BrainSpec` (`tools_allowed = not
  trains_on_content`), `src/jarvis/core/brain.py:Brain._tools_on` and, for calls,
  `src/jarvis/calls/brain.py:pick_call_brain`.

### ADR-29 · Shipped models and datasets carry permissive licences

- **Status:** Proposed (27 Nov 2026; chapter 12's proposed ADR-F; covers C8). Not true today: the
  wake-word models are CC BY-NC-SA 4.0 (`src/jarvis/api/static/wakeword/LICENSE.txt`).
- **Decision (proposed):** Only permissive licences in the parts JARVIS ships; a non-commercial
  part is replaced before any public launch (R5.2 stage 2's owned wake-word model, before
  R18.1); a licence audit of every model and dataset is an R18.1 precondition.
- **Consequences:** R5.2 stage 2 becomes required work before launch.
- **Code:** the Python packages' licences are already listed (`requirements.licences.json`); no
  check covers models or datasets yet. R18 ships no model or dataset: the language check fetches
  FLEURS test clips (CC BY 4.0) at run time. The cloud image's one new package, NumPy, is
  BSD-3-Clause and listed (`pyproject.toml`, `requirements.licences.json`); the call desk's laptop
  packages (`deploy/calldesk/requirements-calldesk.txt`, among them `soundcard` and `comtypes`) are
  not in that list (*unverified:* their licences were not checked for this edition).

### ADR-30 · Trading: the owner approves every money movement, or it is not built

- **Status:** Proposed (27 Nov 2026; chapter 12's proposed ADR-G; covers C3). Nothing is built
  (R19 is deferred).
- **Context:** The owner's first ask was fully autonomous trading, which breaks confirm before
  commit.
- **Decision (proposed):** Any trading design keeps every order and money movement behind an
  irreversible-class card (R3) with the passkey, with no "don't ask again"; paper trading first.
- **Consequences:** A trading desk is slower than an autonomous one; it is built only on these terms.
- **Code:** none; it would rely on `src/jarvis/core/guardrails.py:ActionRisk` and
  `src/jarvis/tools/policy.py`.

### ADR-31 · Free speech first; every call language passes a language check

- **Status:** Accepted, R18 (plan decisions D3 and D4, 25 Nov 2026; the ranking corrected by the
  combined review on 27 Nov 2026). Source: `docs/plans/r18-calls.md` (sections 5 and 12).
- **Context:** Row 395 asks for calls in any Indian language JARVIS can speak and understand for
  free. Free speech exists in some form for all 22 scheduled languages, but nobody knows how well
  each works over a narrowband phone line. Paid speech must never start without the owner's YES.
- **Decision:** A language is offered on a call card only after it passes the language check for
  a speech option: hearing and speaking over a simulated phone line, speed, and a person's score
  (chapter 07, section 8.1). Among the options that passed, a call uses one that costs ₹0 now for
  the card's length, then the cheapest known price. Sarvam (paid) needs its key, `sarvam_enabled`
  and the owner's YES; Bhashini, with no published price, is never counted as ₹0 and is checked only
  on an explicit request; Gemini's free tier is never used for calls.
- **Consequences:** The check, not the price, decides what is offered; the card's estimate and the
  call use the same option. Languages without FLEURS test clips (8 of the 22) can't be checked and
  are not offered. The first build ranked by list price after the free allowance, so paid Sarvam
  could beat Google while Google was still free; the review fixed it.
- **Code:** `src/jarvis/calls/cards.py:offered`, `Estimator.free_options`,
  `src/jarvis/calls/langcheck/runner.py:LanguageCheck`, `src/jarvis/calls/models.py:LANG_CHECK`,
  `src/jarvis/calls/speech/catalogue.py`.

### ADR-32 · A call's speech is metered in one place

- **Status:** Accepted, R18 I1 (27 Nov 2026). Source: `docs/plans/r18-integration/I1-NOTES.md`
  (decision 1).
- **Context:** Part B's speech adapters meter every hearing and voice through `jarvis.billing`
  (Google against its shared free allowance, Azure F0 held and never billed, Sarvam and Bhashini
  in ₹). Part A2's engine also priced speech, to hold the call to its ₹ cap. Joined as built,
  every Google second would have been counted twice, and Azure's under other keys.
- **Decision:** The adapters' meter is the only record. One `CallTally` per call receives what was
  charged; `CallSpend.speech` hands that to the engine and records nothing itself. A use with an
  unknown price counts for the call's cap at Google's paid rate. Model calls (brain, captions,
  summary, translations) keep their one meter; the calls month is added once, at the call's end.
- **Consequences:** The call's cap sees the same rupees billing holds. For an unknown-price use
  (Bhashini) the cap counts rupees that billing does not hold, which errs on the safe side.
- **Code:** `src/jarvis/calls/join_speech.py:CallTally`, `CallSpend`,
  `src/jarvis/calls/speech/meter.py`, `src/jarvis/calls/hub.py:BillingSpend`.

### ADR-33 · Call recordings are 8 kHz WAV, not a compressed format

- **Status:** Accepted, R18 I1 (27 Nov 2026). Departs from the plan's size estimate (D8: "about
  0.1 MB a minute") and the build brief ("Opus or 16 kHz mono compressed"). Source:
  `docs/plans/r18-integration/I1-NOTES.md` (decision 3; known limit 4).
- **Context:** At approval stop 1 the owner chose to keep each call's audio (D8). Opus needs an
  encoder JARVIS doesn't ship; adding one is a new dependency. The phone line is narrowband
  (8 kHz) anyway.
- **Decision:** Hold the call's mixed audio in memory, resampled to 8 kHz, and seal it at the end
  as `audio/wav` with the vault's envelope encryption; at most 16 MiB.
- **Consequences:** About 0.96 MB a minute, ten times the plan's figure: 80 minutes a month is
  about 77 MB, still inside Firestore's free 1 GiB. A recording stops at about 17 minutes, while a
  call may be set to last up to 30. The records already accept Ogg and WebM Opus, so a compressed
  format can come later without a data change.
- **Code:** `src/jarvis/calls/join.py:RECORD_RATE`, `VaultRecords`,
  `src/jarvis/calls/records.py:MAX_AUDIO_BYTES`, `AUDIO_TYPES`.

### ADR-34 · English is offered "not yet checked" before its first language check

- **Status:** Accepted, R18 I1 (the Workshop's decision, 27 Nov 2026). Source:
  `docs/plans/r18-integration/I1-NOTES.md` (decision 5).
- **Context:** The plan offers only languages that passed the check. On a fresh install nothing
  has been checked, so no call at all, not even in English, could be placed until the owner ran
  the check, and checking every language costs ₹ past Google's free hour.
- **Decision:** While English has no result, a stand-in result is offered for it on the first
  cloud option set up (Google, then Azure), marked "not yet checked"; once English has a result,
  the check decides. Every Indian language still needs a pass.
- **Consequences:** English calls work from the first day, but English is not proved over the
  phone line until the owner runs the check. Deleting the check's results in the Privacy panel
  puts English back to "not yet checked".
- **Code:** `src/jarvis/calls/cards.py:PROVISIONAL_ENGLISH`, `offered`, `provisional`,
  `src/jarvis/calls/join_speech.py:CLOUD_FALLBACK`.

### ADR-35 · Calls never displaces a tab in the dock

- **Status:** Accepted, R18 (the owner's rule, 27 Nov 2026: "Calls not in the bar at 1920"). It
  closes I1's known limit 10. Source: `docs/plans/r18-integration/I1-NOTES.md` (4.10).
- **Context:** At 1920 × 1080 the 22 tabs before R18 fill the dock. Adding Calls as the 23rd folded
  it into More and, because More takes a slot, folded Camera too, which broke his rule that every
  existing tab stays where it was (and P6, never change the console's look).
- **Decision:** Calls is an "extra" tab. The other tabs are placed as if Calls were not there;
  Calls joins the bar only where it fits beside them all (2560 px), sits in More where More shows
  for the others, and otherwise is in neither. It opens from Vitals' calls line, the chat's call
  card and `?open=calls`.
- **Consequences:** At 1920 px the dock is the dock before R18, checked to the pixel, Night and
  Day. At his usual width Calls has no tab and is reached its three other ways.
- **Code:** `src/jarvis/api/static/console-dock.js` (`EXTRA`),
  `src/jarvis/api/static/console-calls-vitals.js`, `tests/browser/dock_rule.py:EXTRA_IDS`,
  `tests/browser/test_dock_fit.py`, `tests/browser/test_r18_calls_ways_in.py`.

### ADR-36 · One instance holds the call hub in memory; the request timeout is 30 minutes

- **Status:** Accepted, R18 (the build brief's "Cloud Run" decision; applies ADR-25). Source:
  `docs/plans/r18-calls/BUILD-BRIEF.md` ("Decisions fixed for the build").
- **Context:** A call joins three live connections (the desk's socket, the phone's door, the
  owner's live listeners) and must answer within about a second. Cloud Run already runs at most
  one instance (ADR-07, ADR-25), and its 300-second timeout would cut a call's sockets.
- **Decision:** One in-memory `CallHub` per process holds every call in progress and its
  listeners; the dial grants, the live tickets, the desk socket's nonces and the phone's command
  outbox and key live in the same process. `--timeout` goes from 300 to 1800 seconds;
  `--max-instances 1` stays.
- **Consequences:** Simple and ₹0. A restart ends a call in progress and leaves no grant to dial
  on, which fails safe. One call at a time. A second instance would split calls, so ADR-25's
  conditions now include moving the hub out and routing each socket to the instance that holds
  its call. Any request, not only a call's, may now run 30 minutes.
- **Code:** `deploy/cloudrun.sh` (step 6), `src/jarvis/calls/hub.py:CallHub`,
  `src/jarvis/calls/approvals.py:GrantBook`, `src/jarvis/api/calls_routes.py:LiveTickets`,
  `src/jarvis/phone/calls.py:PhoneCalls`.

### ADR-37 · The cloud reaches the phone by a Web Push doorbell; the door carries signed commands

- **Status:** Accepted, R18 Part D, joined at I1 (27 Nov 2026). Source:
  `docs/plans/r18-calls/INTEGRATION-D.md` (section 1); `docs/plans/r18-integration/I1-NOTES.md`
  (decision 7).
- **Context:** R7 gave the app no channel of its own from the cloud: no Firebase and no foreground
  service (R7 D9, D22), only the Web Push that Chrome hands to the app. A call must be dialled
  within seconds of the owner's approval.
- **Decision:** A command is signed by the cloud (ECDSA P-256) and queued in an in-memory outbox for
  that phone. A Web Push of kind `call_command`, a plain sentence that never carries a number or a
  name, makes the app ask the door's fifth route, `POST /phone/v1/calls`, whose answer carries the
  commands; the app verifies each before acting. The signing key is made at each start, and its
  public half travels with the door's answers, so no new keyring secret was needed.
- **Consequences:** No new vendor and ₹0. A lost push only delays a command; a restart drops the
  queue and changes the key, like the grants. Android may hold a background dial back; the app then
  shows "Tap to let JARVIS call". Because the public key arrives in the same door answer as the
  commands (over HTTPS from JARVIS's own address), the signature guards against a forged, replayed
  or stale command, not against a forged door answer; HTTPS is the root of trust there (this
  edition's reading of the code).
- **Code:** `src/jarvis/phone/calls.py:PhoneCalls`, `src/jarvis/phone/calls_wire.py:CommandSigner`,
  `src/jarvis/mobile/ports.py`, `android/core/src/main/kotlin/io/github/shark2558/jarvis/core/Calls.kt`.

### ADR-38 · Placing a call is R3 with a one-use grant per call; never approved from Telegram

- **Status:** Accepted, R18 (plan decision D10, 25 Nov 2026; the dial chain at I1; Telegram and
  the phone's Approve settled by the combined review, 27 Nov 2026). Source: `docs/plans/r18-calls.md`
  (section 4 step 1, section 8); `docs/plans/r18-integration/I1-NOTES.md` (decision 2).
- **Context:** A call speaks for the owner, takes the other person's time and can't be undone.
  TRAI's rules turn on direct human dialling (chapter 05, section 8.5). Row 197 asked for laundry
  status calls on a standing permission, which confirm before commit forbids (chapter 12, C1).
- **Decision:** `calls_place` is R3: a card every time, never Approve all, no standing Allow. A
  never-called number needs the passkey and is refused while passkeys are not required. The
  approval issues a grant, one use and 10 minutes, bound to the number and the card's content; the
  engine spends it for one call id just before the dial, counting the day's limits in the same
  transaction; the phone queues the dial only for that grant. `calls_place` is never approved from
  Telegram. A waiting card shows the number's last four digits only.
- **Consequences:** Every call is one tap by the owner, and a template (laundry) only writes a
  draft. On Telegram he must open the console or the phone app to approve. Grants live in memory
  (ADR-36). A waiting card's full arguments still sit in `approvals` in clear for up to 10 minutes
  (chapter 05, residual risk 10).
- **Code:** `src/jarvis/calls/approvals.py:CallsService`, `GrantBook`,
  `src/jarvis/calls/tools.py:calls_tools`, `src/jarvis/core/guardrails.py:CONSOLE_ONLY_TOOLS`,
  `src/jarvis/core/models.py:shown_arguments`, `src/jarvis/calls/join.py:PhoneCardDesk`.

### ADR-39 · The live call socket accepts a one-use ticket in token mode

- **Status:** Accepted, R18 I1 (the Workshop's item 2, 27 Nov 2026; tightened by the combined
  review the same day). Source: `docs/plans/r18-integration/I1-NOTES.md` (decision 13).
- **Context:** The console had no other WebSocket, and a browser can't send an `Authorization`
  header on one, so with token sign-in (`JARVIS_AUTH_MODE=token`) the live view could not get in.
  Putting the bearer token in the address would leak a long-lived secret into access logs.
- **Decision:** `POST /v1/calls/{call_id}/live/ticket` (bearer or cookie) gives a one-use ticket
  for that call, alive 30 seconds, held in memory (at most 64). The live socket takes `?ticket=`
  only from JARVIS's own page and only when it brought no other credential.
- **Consequences:** A spent ticket seen in a log opens nothing; cookie sign-in is unchanged;
  tickets end at a restart (ADR-36).
- **Code:** `src/jarvis/api/calls_routes.py:LiveTickets`, `TICKET_TTL_S`, `TICKETS_MAX`.

## 3. Follow-ups found while writing this document

| # | Follow-up | Why | Where |
|---|---|---|---|
| F1 | A tree-wide check that only `jarvis.llm` imports an AI vendor SDK | ADR-02 was enforced by review only | Closed 27 Nov 2026: `tests/test_llm_sdk_boundary.py` |
| F2 | Teach `scripts/arch_inventory.py` the two idioms it misses (a helper-named collection; a tuple assignment) | 5 collections are invisible to the coverage check | Open: needs the Build Book's `src/jarvis/buildbook/gen/facts_code.py:COLLECTION` changed with it (chapter 04, section 2; chapter 12, section 4) |
| F3 | Extend `scripts/check_doc_versions.py` to `docs/architecture/design/` | This document's version lines were not checked in CI | Closed 27 Nov 2026: `FOLDERS` includes the folder; `tests/test_check_doc_versions.py` |
| F4 | Keep outfit plans 90 days after their day (`src/jarvis/wardrobe/styling/plans.py`) | The code keeps 14 days; R13's plan and the owner's 27 Nov 2026 decision say 90 | Open: next app release (chapter 12, section 4) |
| F5 | Keep a waiting call card's number out of the unsealed `approvals` collection, or seal it there (R18) | The call store seals every number; the gateway's waiting card keeps it in clear for up to 10 minutes | Open: for the R18 review or the next app release (chapter 12, section 6) |
| F6 | A deploy step for the three speech keys (R18) | `deploy/cloudrun.sh` creates and mounts none, so a deployed JARVIS has Google's speech only | Open: needs a deploy-script change (chapter 12, section 6) |
| F7 | Make the calls eval prove the choice a call really uses (R18) | Its `selection` suite tests the language check's own order, not `cards.offered` | Open: an eval change (chapter 12, section 6) |

## 4. Proposed ADRs

Chapter 12's seven proposals now live in section 2: ADR-A is ADR-01, and ADR-B to ADR-G are
ADR-25 to ADR-30. A new proposal is written in section 2 with the next free number and the status
Proposed; it becomes Accepted when the code does what it says, in the same pull request.

## Change log

| Version | Date | Release | What changed | By |
|---|---|---|---|---|
| v6.4.1 | 27 Nov 2026, 17:05 IST | R6.4 | First edition: 24 ADRs with context, decision, consequences, status and code, every departure from the reference architecture included; three follow-ups found while writing; the link to chapter 12's proposed ADRs | 🛠 Mark XXV |
| v6.4.2 | 27 Nov 2026 | R6.4 | Verification (chapter 13): chapter 12's proposals B–G recorded as ADR-25 to ADR-30 (25 Accepted as built, the rest Proposed; A was already ADR-01); ADR-07's date and source from GitHub's history, its reason and ADR-10's marked unverified; F1 and F3 closed, F2 left open with the reason | 🛠 Mark XXV |
| v6.4.3 | 27 Nov 2026 | R6.4 | Follow-up F4 added: outfit plans kept 90 days, as the owner decided | 🛠 Mark XXV |
| v6.5.0 | 27 Nov 2026, 20:40 IST | R18 | R18 "Calls from your laptop": ADR-27 accepted and rewritten as built; nine new ADRs, 31 to 39 (free speech first behind the language check, metering in one place, 8 kHz WAV recordings, English "not yet checked", the 1920 px dock rule, the one-instance call hub and the 1800 s timeout, the phone's doorbell and signed commands, the one-use grant and no Telegram approval, the live socket's ticket); ADR-07, ADR-25, ADR-28 and ADR-29 updated for R18; follow-ups F5–F7 | 🛠 Mark XXV |
