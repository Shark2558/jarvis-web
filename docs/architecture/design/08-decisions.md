Version v6.4.1 · 27 Nov 2026, 17:05 IST · Release R6.4 · Status: Current · Owner: 🛠 Mark XXV

# 08 · Architecture decisions (ADR log)

**In plain words.** Each entry below is one decision that shaped JARVIS: what the situation was,
what was decided, what it costs or gives up, whether it still stands, and which code carries it
out. Many of them are places where the build departs from the original reference architecture
(the PDF, which proposed Postgres, Chroma or Pinecone, Redis, Kafka or NATS, ElevenLabs, MCP,
Kubernetes with Terraform, LangGraph and Next.js); each departure is recorded here with its reason.
From now on a plan that wants to change one of these writes a new ADR first (chapter 00).

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
| 07 | One Cloud Run service, at most one instance, one re-runnable deploy script | Docker → Kubernetes, Terraform | Accepted | Slice 4 (*unverified* date of the move from Render) |
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

## 2. The decisions

### ADR-01 · This document is the canonical architecture reference

- **Status:** Accepted, 27 Nov 2026 (the owner's ask: "create a new architecture design document
  as per the build and the requirements, verify the architecture, and refer to it in future").
  Settles chapter 12's proposed ADR-A.
- **Context:** The reference PDF predates the build and differs from it in at least ten places
  (this log). The plain-language guide explains parts, not rules.
- **Decision:** `docs/architecture/design/` is the reference for planning, building and review;
  the PDF is historical. A conflict is flagged and resolved by an ADR here before work goes on.
- **Consequences:** Every release's paperwork updates the chapters it changed. The version-line
  check does not yet scan this folder (chapter 07, section 5).
- **Code:** none; `docs/architecture/design/00-README.md`.

### ADR-02 · Model-agnostic core

- **Status:** Accepted, Phase 0 (by 1 Nov 2026). Source: `CLAUDE.md`; the guide, 5.4.
- **Context:** The reference made Claude the brain. Cost, privacy and outages argue for choice.
- **Decision:** Callers ask for a tier (fast, balanced, strong), never a model id. Every brain
  implements one provider interface. Only `jarvis.llm` imports an AI vendor's SDK.
- **Consequences:** Gemini, an OpenAI-compatible slot, the laptop and a mock run behind the same
  interface; degradation and fallback live in one router. Only Claude is proved by the real eval
  gate. No automated check enforces the SDK boundary tree-wide (follow-up F1).
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

- **Status:** Accepted. Hosting moved from Render (slice 2, `render.yaml`) to Cloud Run by slice 4
  (*unverified*: no plan records why). Source: `deploy/cloudrun.sh` header.
- **Context:** One owner; free first; no server to patch. Kubernetes and Terraform cost money and
  time for one owner.
- **Decision:** One service in `asia-south1`, `--min-instances 0 --max-instances 1`, 512 MiB, one
  CPU, 300 s timeout, deployed by one re-runnable script.
- **Consequences:** ₹0 at this size; rate limits, the per-conversation lock and nonce stores can
  live in memory; one instance is also one point of failure and the capacity ceiling (chapter 06,
  section 5). "Raise --max-instances only after sessions gain a cross-process concurrency check,
  and the home nonce cache moves out of process" (the script's own words). The conditions for
  moving out are chapter 12's proposed ADR-B.
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

- **Status:** Accepted as built. No plan records this as a decision; the context is reconstructed
  from the code (*unverified* rationale).
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
  Chapter 12's proposed ADR-E would extend it (paid tier only for any brain that sees tools or
  third parties' data).
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
  officially supported host for either program (chapter 12, proposed ADR-C).
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

## 3. Follow-ups found while writing this document

| # | Follow-up | Why | Where |
|---|---|---|---|
| F1 | A tree-wide check that only `jarvis.llm` imports an AI vendor SDK | ADR-02 is enforced by review only | `tests/` or ruff's banned-import rule; an ADR if the rule changes |
| F2 | Teach `scripts/arch_inventory.py` the two idioms it misses (a helper-named collection; a tuple assignment) | 5 collections are invisible to the coverage check | chapter 04, section 2 |
| F3 | Extend `scripts/check_doc_versions.py` to `docs/architecture/design/` | This document's version lines are not checked in CI | chapter 07, section 5 |

## 4. Proposed ADRs

Chapter 12 (section 5) holds the proposals not yet decided: ADR-B (conditions for moving off one
instance; ADR-07 records the current decision), ADR-C (an always-on home box), ADR-D (calls from
a personal SIM), ADR-E (paid tier only for a brain that sees tools or third parties' data; extends
ADR-11), ADR-F (model and dataset licences) and ADR-G (the trading desk). ADR-A is settled by
ADR-01. When one is decided it moves here with the next free number.

## Change log

| Version | Date | Release | What changed | By |
|---|---|---|---|---|
| v6.4.1 | 27 Nov 2026, 17:05 IST | R6.4 | First edition: 24 ADRs with context, decision, consequences, status and code, every departure from the reference architecture included; three follow-ups found while writing; the link to chapter 12's proposed ADRs | 🛠 Mark XXV |
