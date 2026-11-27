Version v6.4.3 · 27 Nov 2026 · Release R6.4 · Status: Current · Owner: 🛠 Mark XXV

# 12 · Gaps, conflicts and risks

What the design does not yet cover, where requirements pull against its rules, where it stops scaling, and the debt carried from earlier releases. Each item ends with what to do; the proposed ADRs are in chapter 08 (section 5 below).

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
| C1 | Row 197 asked for laundry **status calls on a standing permission** | R3: placing a call is irreversible and never gets "don't ask again" | Resolved in the R18 plan (`docs/plans/r18-calls.md`, branch `r18-a1`: rows 195–197 "each placed after the owner's tap"): each call is prepared on a card and placed after the owner's tap. R18 builds it that way |
| C2 | Row 104, **answering missed calls**, speaks for the owner without a tap | Confirm before commit | Answering is off by default, takes messages only and never agrees to anything; it commits the owner to nothing |
| C3 | R19's first ask: **fully autonomous trading** | Confirm before commit (money) | Open: ADR-30 (proposed) before any design; paper trading first |
| C4 | Row 389, **Gemini as the brain for Google tasks** | "A brain that may learn from content never sees tools" | Only the **paid** tier, with each tool's evals passing on it; the free tier stays tool-less (ADR-28, proposed) |
| C5 | Calls with **automated voice** from a personal SIM | TRAI's 2026 rules on calls placed by software without direct human dialling | Every call starts with the owner's tap, own number, personal volume, AI disclosure in the first sentence, daily caps (R18 plan §7) |
| C6 | The **reference architecture PDF** (Postgres, Chroma, Kafka/NATS, ElevenLabs, MCP servers, Kubernetes) | This document's as-built chapters (Firestore, the custom tool gateway, Google speech, one Cloud Run instance) | Resolved: ADR-01 (this document is canonical; the PDF is a historical reference) |
| C7 | The old R18 text named a **business call provider** | The owner has no registered business (17 Nov) | Resolved: the personal laptop route (R18 plan §3); row 198 stays Pending |
| C8 | Today's **"Hey Jarvis" model is non-commercial** (CC BY-NC-SA) | A public launch | R5.2 stage 2 builds an owned model; required before R18.1 (ADR-29, proposed) |
| C9 | Indoor cameras record **other household members** | Privacy by default; India's data-protection law | Only the owner tracked by default, per-person consent, children never (vision rules) |
| C10 | The slice 1 plan names an **R0 risk tier** ("default by risk: R0/R1 ALLOW, R3 ASK", `docs/plans/phase2-slice1-tool-spine.md`) | The code's three risk classes, R1 read, R2 reversible, R3 irreversible (`src/jarvis/core/guardrails.py:ActionRisk`) | Resolved: the code is the design, and this document says R1–R3 throughout (chapters 01, 05). No requirement row assumes an R0 tier: "R0" in the workbook's Release column (32 rows) is the first release, not a risk tier. The plan is marked "Superseded by the build log" and is left as written |

## 3. Scaling and availability limits

| Limit | Why it exists | What breaks first | Do |
|---|---|---|---|
| **Cloud Run `--max-instances 1`** | The per-conversation lock, the rate limiters, the home and phone nonce stores and (from R18) the call hub are in memory; the Telegram webhook is registered for one connection. Conversations themselves are in Firestore | A second instance would split the locks, the rate limits, replay protection and call state | Keep 1 for one owner; before any second user or higher load, move that state out (ADR-25) |
| **Cloud Run request timeout** (300 s today) | Set by `deploy/cloudrun.sh` step 6 (`--timeout 300`) | WebSockets longer than 5 minutes (calls) | R18 raises it to 1800 s |
| **The laptop as the home server** | Free first: the home kit (WSL2 + Docker: Home Assistant, Frigate, the bridge), the local brain, R5.2's speech kit and R18's call desk all run on it | Laptop asleep, off or away = home alerts, calls, local speech and laptop brain stop | Vitals already alerts "laptop off"; the always-on box (Raspberry Pi 5 with an accelerator, or a mini-PC) when the owner chooses (ADR-26, proposed) |
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
- Found by the verification of this document (chapter 13), 27 Nov 2026:
  - `scripts/arch_inventory.py` misses 5 collection names (chapter 04, section 2), and so does the
    Build Book's fact pack, which uses the same patterns
    (`src/jarvis/buildbook/gen/facts_code.py:COLLECTION`; `tests/test_r63_a_facts_real.py` holds the
    two counts equal). Teaching both the two idioms is an app-code change, left for a release
    (follow-up F2).
  - The AI-SDK boundary test (`tests/test_llm_sdk_boundary.py`) found no offender: the only vendor
    SDK import is `anthropic` inside `src/jarvis/llm/`. Nothing is marked to fail.
  - `README.md` still offers `render.yaml` as an alternative host; nothing deploys it.
  - Outfit plans: R13's plan (`docs/plans/r13-wardrobe.md`, the data table) keeps
    `wardrobe_plans` "90 days after the event"; the code drops a plan 14 days after its day
    (`src/jarvis/wardrobe/styling/plans.py:StylingDoc.pruned`). The owner decided on 27 Nov 2026:
    keep plans 90 days after their day, as R13 planned. The code changes in the next app release
    (follow-up F4); until then it keeps 14 days.

## 5. Proposed ADRs

Moved to chapter 08 on 27 Nov 2026: ADR-A is ADR-01, and ADR-B to ADR-G are ADR-25 to ADR-30.

## Change log

| Version | Date | Release | What changed | By |
|---|---|---|---|---|
| v6.4.1 | 27 Nov 2026, 14:30 IST | R6.4 | First edition: modules with no code home, nine conflicts and their resolutions, scaling and availability limits, carried-over debt, seven proposed ADRs | 🛠 Mark XXV |
| v6.4.2 | 27 Nov 2026 | R6.4 | Verification (chapter 13): conflict C10 (the slice 1 plan's R0 tier against the code's three classes); C1's source and C6's resolution; the one-instance row says what is really in memory; the timeout is set, not a default; three debt items the verification found; the proposed ADRs moved to chapter 08 with a pointer left here | 🛠 Mark XXV |
| v6.4.3 | 27 Nov 2026 | R6.4 | Outfit plans: the owner chose 90 days; the code change is follow-up F4 | 🛠 Mark XXV |
