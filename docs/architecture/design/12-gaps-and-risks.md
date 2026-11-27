Version v6.4.1 · 27 Nov 2026, 14:30 IST · Release R6.4 · Status: Current · Owner: 🛠 Mark XXV

# 12 · Gaps, conflicts and risks

What the design does not yet cover, where requirements pull against its rules, where it stops scaling, and the debt carried from earlier releases. Each item ends with what to do; the proposed ADRs at the end go into chapter 08 when they are decided.

## 1. Requirements with no code home yet

Every workbook module maps to a layer and a skill (chapter 10: "no architectural home: none"), but some skills and modules have **no package** in `src/jarvis/` yet. Their design is a sentence in chapter 11, not a component.

| Module / skill | Rows | Status | What is missing | Do |
|---|---|---|---|---|
| Learning (skill) | 8 | Pending (R17) | No package, data model or evals | R17's plan creates `jarvis.learning`; tutoring of children needs the consent rules of R10 |
| Decision Support (skill) | 4 | Pending (R15) | No package | R15's plan; keep it advisory (no tool that acts) |
| Activity (AI) | 2 | Pending (R16) | Depends on R8's activity timeline | Plan after R8 |
| Social (paid) | 4 | Pending (R15) | No connector; platforms' terms | R15 plan with read-only scopes |
| Kitchen / wardrobe (AI) | 3 | Pending (R17) | Paid AI on top of R13 and R9 | R17 plan; ₹ estimates first |
| Gesture control | 1 | Not placed | No design beyond chapter 11 | A build prompt for the owner's approval |
| Health & Wellbeing (skill) | 75 | 4 Done | The largest unbuilt body; one engine (R7), no coaches yet | R8–R10 in camera order |

## 2. Conflicts between requirements and the design's rules

| # | Conflict | Rule it touches | Resolution |
|---|---|---|---|
| C1 | Row 197 asked for laundry **status calls on a standing permission** | R3: placing a call is irreversible and never gets "don't ask again" | Resolved (decision 17): each call is prepared on a card and placed after the owner's tap. R18 builds it that way |
| C2 | Row 104, **answering missed calls**, speaks for the owner without a tap | Confirm before commit | Answering is off by default, takes messages only and never agrees to anything; it commits the owner to nothing |
| C3 | R19's first ask: **fully autonomous trading** | Confirm before commit (money) | Open: an ADR before any design; paper trading first |
| C4 | Row 389, **Gemini as the brain for Google tasks** | "A brain that may learn from content never sees tools" | Only the **paid** tier, with each tool's evals passing on it; the free tier stays tool-less |
| C5 | Calls with **automated voice** from a personal SIM | TRAI's 2026 rules on calls placed by software without direct human dialling | Every call starts with the owner's tap, own number, personal volume, AI disclosure in the first sentence, daily caps (R18 plan §7) |
| C6 | The **reference architecture PDF** (Postgres, Chroma, Kafka/NATS, ElevenLabs, MCP servers, Kubernetes) | This document's as-built chapters (Firestore, the custom tool gateway, Google speech, one Cloud Run instance) | Proposed ADR-A: this document is canonical; the PDF is a historical reference |
| C7 | The old R18 text named a **business call provider** | The owner has no registered business (17 Nov) | Resolved: the personal laptop route (R18 plan §3); row 198 stays Pending |
| C8 | Today's **"Hey Jarvis" model is non-commercial** (CC BY-NC-SA) | A public launch | R5.2 stage 2 builds an owned model; required before R18.1 |
| C9 | Indoor cameras record **other household members** | Privacy by default; India's data-protection law | Only the owner tracked by default, per-person consent, children never (vision rules) |

## 3. Scaling and availability limits

| Limit | Why it exists | What breaks first | Do |
|---|---|---|---|
| **Cloud Run `--max-instances 1`** | Sessions, rate limiters, the Telegram webhook and (from R18) the call hub are in memory | A second instance would split sessions and call state | Keep 1 for one owner; before any second user or higher load, move session and hub state to Firestore or Redis (proposed ADR-B) |
| **Cloud Run request timeout** (300 s today) | Default deploy | WebSockets longer than 5 minutes (calls) | R18 raises it to 1800 s |
| **The laptop as the home server** | Free first: the home kit (WSL2 + Docker: Home Assistant, Frigate, the bridge), the local brain, R5.2's speech kit and R18's call desk all run on it | Laptop asleep, off or away = home alerts, calls, local speech and laptop brain stop | Vitals already alerts "laptop off"; the always-on box (Raspberry Pi 5 with an accelerator, or a mini-PC) when the owner chooses (proposed ADR-C) |
| **WSL2 for Home Assistant and Frigate** | Trial set-up | Neither supports it officially | Same as above |
| **Laptop compute** (16 GB RAM, 4 GB graphics) | Vision, speech and the local brain share it | 2–3 cameras at a few frames a second; one speech model loaded at a time | R5.2 loads engines on demand; R8 measures camera load |
| **Firestore free 1 GiB** | ₹0 storage | Call recordings (≈ 0.1 MB a minute, 30 days), wardrobe photos, vision results | Recordings live in the vault with a 30-day retention; watch in Vitals |
| **Single owner** | The design's assumption | Guests and household members are limited modes | Any multi-user step needs its own ADR |

## 4. Technical debt carried over

From the handoff's carried-over list and the R6.4 review (left on purpose, documented):

- Voice timing tests flake under load; `approve_all[phone]` and `test_vitals_board` flaked once.
- `src/jarvis/vault/service.py` is 876 lines (over the 800-line soft ceiling).
- R4's lock registries and rate limiters are in memory (tied to §3's single instance).
- R5's dead phrase hints; the notes export is not audited.
- `mypy src` keeps one baseline error in `memory/redis_store.py:67`.
- R6.4 lows: background calls on an unpriced brain are over-counted (`billing/service.py:461`, errs high); a trace effect can repeat on a slow device; one-letter search ≈ 190 ms.
- Rollbacks across the Book's sealed releases show a one-time notice (documented, no fix planned).
- "Recently deleted" names a deletion's day in UTC (between 00:00 and 05:30 IST it says the day before).
- The owner's real name is in old git history (his call).
- The go-live guide's Parts 5–6 still describe R6.3.1's Book.

## 5. Proposed ADRs

| ADR | Decision to record | Trigger |
|---|---|---|
| ADR-A | This Architecture Design Document (docs/architecture/design/) is the canonical architecture; the reference PDF is historical; every release updates the chapters it changes | Owner's ask of 27 Nov |
| ADR-B | One Cloud Run instance with in-memory state while JARVIS has one owner; the conditions and steps for moving state out | Before any second user or a second instance |
| ADR-C | The laptop is the home server for now; the always-on box and what moves to it first (home kit, call desk, speech kit) | When "laptop must be on" hurts, or a third camera |
| ADR-D | Calls from a personal SIM through Phone Link; the call desk as a Windows-native runtime outside the home kit | R18 (decided in its plan; record here) |
| ADR-E | Paid-tier-only rule for any brain that sees tools or third parties' data (covers C4 and the calls exclusion) | R18; row 389 |
| ADR-F | Model and dataset licences: permissive only in shipped parts; non-commercial parts replaced before launch (covers C8) | R5.2; before R18.1 |
| ADR-G | Trading desk: approval on every money movement, or not built (C3) | Before any R19 design |

## Change log

| Version | Date | Release | What changed | By |
|---|---|---|---|---|
| v6.4.1 | 27 Nov 2026, 14:30 IST | R6.4 | First edition: modules with no code home, nine conflicts and their resolutions, scaling and availability limits, carried-over debt, seven proposed ADRs | 🛠 Mark XXV |
