Version v6.5.0 · 27 Nov 2026, 21:00 IST · Release R18 · Status: Current · Owner: 🛠 Mark XXV

# 12 · Gaps, conflicts and risks

What the design does not yet cover, where requirements pull against its rules, where it stops scaling, and the debt carried from earlier releases. Each item ends with what to do; the proposed ADRs are in chapter 08 (section 5 below). R18's own gaps and risks are in section 6.

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
| C1 | Row 197 asked for laundry **status calls on a standing permission** | R3: placing a call is irreversible and never gets "don't ask again" | Resolved in the R18 plan (`docs/plans/r18-calls.md`: rows 195–197 "each placed after the owner's tap") and built so: a laundry template only writes a draft card (`src/jarvis/calls/templates.py`), and every call needs his tap (ADR-38) |
| C2 | Row 104, **answering missed calls**, speaks for the owner without a tap | Confirm before commit | Built so: answering is off by default, switching it on is its own card, it takes messages only and never agrees to anything (`src/jarvis/calls/answering.py`); it commits the owner to nothing |
| C3 | R19's first ask: **fully autonomous trading** | Confirm before commit (money) | Open: ADR-30 (proposed) before any design; paper trading first |
| C4 | Row 389, **Gemini as the brain for Google tasks** | "A brain that may learn from content never sees tools" | Only the **paid** tier, with each tool's evals passing on it; the free tier stays tool-less (ADR-28, proposed) |
| C5 | Calls with **automated voice** from a personal SIM | TRAI's 2026 rules on calls placed by software without direct human dialling | Every call starts with the owner's tap, own number, personal volume, AI disclosure in the first sentence, daily caps (R18 plan §7); built in R18 (chapter 05, sections 8.4 and 8.5). A reading, not legal advice |
| C6 | The **reference architecture PDF** (Postgres, Chroma, Kafka/NATS, ElevenLabs, MCP servers, Kubernetes) | This document's as-built chapters (Firestore, the custom tool gateway, Google speech, one Cloud Run instance) | Resolved: ADR-01 (this document is canonical; the PDF is a historical reference) |
| C7 | The old R18 text named a **business call provider** | The owner has no registered business (17 Nov) | Resolved: the personal laptop route (R18 plan §3); row 198 stays Pending |
| C8 | Today's **"Hey Jarvis" model is non-commercial** (CC BY-NC-SA) | A public launch | R5.2 stage 2 builds an owned model; required before R18.1 (ADR-29, proposed) |
| C9 | Indoor cameras record **other household members** | Privacy by default; India's data-protection law | Only the owner tracked by default, per-person consent, children never (vision rules) |
| C10 | The slice 1 plan names an **R0 risk tier** ("default by risk: R0/R1 ALLOW, R3 ASK", `docs/plans/phase2-slice1-tool-spine.md`) | The code's three risk classes, R1 read, R2 reversible, R3 irreversible (`src/jarvis/core/guardrails.py:ActionRisk`) | Resolved: the code is the design, and this document says R1–R3 throughout (chapters 01, 05). No requirement row assumes an R0 tier: "R0" in the workbook's Release column (32 rows) is the first release, not a risk tier. The plan is marked "Superseded by the build log" and is left as written |
| C11 | The R18 plan kept recordings **compressed, about 0.1 MB a minute** (D8) | No new dependency without need (no encoder is shipped) | Resolved by ADR-33: 8 kHz WAV, about 0.96 MB a minute, still inside the free storage |
| C12 | R18 added a **23rd console tab**, which at 1920 px folded Calls and Camera into More | P6 and the owner's rule that every existing tab stays where it was | Resolved by ADR-35: Calls never displaces a tab; at 1920 px it has no tab and opens three other ways |

## 3. Scaling and availability limits

| Limit | Why it exists | What breaks first | Do |
|---|---|---|---|
| **Cloud Run `--max-instances 1`** | The per-conversation lock, the rate limiters, the home and phone nonce stores and, since R18, the call hub, dial grants, live tickets and the phone's command outbox are in memory; the Telegram webhook is registered for one connection. Conversations themselves are in Firestore | A second instance would split the locks, the rate limits, replay protection and call state | Keep 1 for one owner; before any second user or higher load, move that state out (ADR-25, ADR-36) |
| **Cloud Run request timeout** (1800 s since R18) | Set by `deploy/cloudrun.sh` step 6 (`--timeout 1800`; 300 before) | A call's sockets longer than 30 minutes; a call itself stops at 30 minutes at most | Done in R18 (ADR-36) |
| **The laptop as the home server** | Free first: the home kit (WSL2 + Docker: Home Assistant, Frigate, the bridge), the local brain, R5.2's speech kit and R18's call desk all run on it | Laptop asleep, off or away = home alerts, calls, local speech and laptop brain stop | Vitals already alerts "laptop off"; the always-on box (Raspberry Pi 5 with an accelerator, or a mini-PC) when the owner chooses (ADR-26, proposed) |
| **WSL2 for Home Assistant and Frigate** | Trial set-up | Neither supports it officially | Same as above |
| **Laptop compute** (16 GB RAM, 4 GB graphics) | Vision, speech and the local brain share it | 2–3 cameras at a few frames a second; one speech model loaded at a time | R5.2 loads engines on demand; R8 measures camera load |
| **Firestore free 1 GiB** | ₹0 storage | Call recordings (≈ 0.96 MB a minute as built, not the plan's 0.1; 30 days), wardrobe photos, vision results | Recordings are sealed like vault files with a 30-day retention; 80 call minutes a month ≈ 77 MB; watch in Vitals |
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

## 6. R18 "Calls from your laptop": gaps, limits and risks

From the join's known limits (`docs/plans/r18-integration/I1-NOTES.md`, section 4), the combined
review's fixes so far, and what this edition found reading the code. The combined review has not
written its report yet (no REVIEW.md in the R18 integration folder on 27 Nov 2026, 21:00 IST), so
this list is to be checked again against it. Items marked *found here* were not in the join's
notes.

### 6.1 Not built, or built differently from the plan

| # | Gap | What it means for the owner | Do |
|---|---|---|---|
| G1 | **The brain check per language** (plan 5.3, step 4: a 10-turn mock call with the safety cases) is not built; the check leaves it empty, never a failure, and the speed bar uses the fast tier's 0.6 s estimate (`src/jarvis/calls/langcheck/runner.py:BRAIN_ESTIMATE_S`) | A language can be offered without proof that the brain holds a conversation in it within the card | The first R18.x follow-up |
| G2 | **Laptop speech mode can't be chosen**: no laptop hearing or voice reaches the desk from the cloud, so the check never passes a laptop option and every call is cloud mode (`src/jarvis/calldesk/speech_local.py`) | The call's audio always goes to a cloud speech service; the plan's most private option is not available | R5.2's speech kit and its bridge to R18's ports (chapter 11) |
| G3 | **FLEURS untested here**: the clips come from Hugging Face at run time, and nothing in this environment fetched them. FLEURS has no clips for 8 of the 22 scheduled languages (Konkani, Maithili, Bodo, Dogri, Manipuri, Santali, Sanskrit, Kashmiri), and the plan's second source, AI4Bharat IndicVoices, was not built | The first real check is the owner's; those 8 languages can never pass, so they are never offered, although row 395 asks for any free language | A second clip source for the 8, with its licence checked (ADR-29) |
| G4 | **Bhashini is opt-in only**: with no published price it runs only when a check request sets `accept_unknown`, which the console never sends (`src/jarvis/calls/langcheck/api.py:CheckRequest`); the plan's "its data terms are read before any use" has no record (*unverified*) | Bhashini is in effect never offered from the console | Read Bhashini's terms; decide in the console whether to offer it |
| G5 | **The opening lines' audio is not cached**: their text is, their voice is made per call | A few hundred characters of Google's free voice allowance a call | R18.x |
| G6 | **Recordings are 8 kHz WAV** (ADR-33) and stop at about 17 minutes (16 MiB), while a call may be set to last up to 30 | A very long call keeps only its first 17 minutes of audio | A compressed format when an encoder is acceptable |
| G7 | **Detection on Azure tries each language**: up to 4 hearings an utterance for a call with more than one language | Azure's 5 free hours go up to four times faster on multi-language calls | Prefer Google for multi-language calls, or a detector on the desk |
| G8 | **The records list has no purpose**, and a booking's Undo shows no title or time | Harder to tell old calls apart | R18.x |
| G9 | **Nothing ran on real devices**: Phone Link, Windows sound and Bluetooth, the PowerShell scripts, the Android build on his phone, real Web Push; the plan's S0 laptop test has not been run | The sound path, background dialling on Android 16 and key tones through Phone Link are unproved | The owner's live checks (`docs/plans/r18-integration/I1-NOTES.md`, section 5) |

### 6.2 Found here: gaps the join's notes don't list

| # | Gap | Evidence | Do |
|---|---|---|---|
| G10 | **The speech keys have no deploy step**: `deploy/cloudrun.sh` creates and mounts no secret for `azure_speech_key`, `sarvam_api_key` or `bhashini_api_key`, although the setting's own description says Secret Manager | `src/jarvis/config_calls.py:CallsConfig`; chapter 02, section 2.3 | Follow-up F6: a deploy step like the optional web-search key's |
| G11 | **A waiting call card's number is in clear** in the unsealed `approvals` collection for up to 10 minutes (the console shows it masked) | `src/jarvis/storage/approvals.py:DocApprovalStore.put`; chapter 05, residual risk 10 | Follow-up F5, for the review to decide |
| G12 | **A call card's other fields are not sealed** (purpose, lines, the contact's name, a booking's name and number to give), and cards and the numbers called before are kept until the Privacy delete; only records have the 30-day retention | `src/jarvis/calls/store.py:DocCallStore` (`_sealed` seals the number only); chapter 04, section 2 | Seal the card's text, or give cards a retention |
| G13 | **The calls eval proves a choice the app doesn't make**: its `selection` suite tests the language check's own order; the app chooses by `cards.offered` (free now first) | `evals/calls_language/suites.py`; chapter 07, section 8.2 | Follow-up F7 |
| G14 | **The background language check under request-only CPU**: it runs after its request returns, so it gets CPU while the console's table polls it (*unverified* that a long check finishes when the console is closed) | chapter 06, section 6.4 | Measure on the deployed service |
| G15 | **The deploy script's warning** about raising `--max-instances` names the rate limits, the write queue and the home nonce cache, not the call hub | `deploy/cloudrun.sh` (header comment) | Add it in the next app release (ADR-25) |
| G16 | **The call desk's laptop packages** (`soundcard`, `comtypes` and others) are hash-pinned but not in the licence list | `deploy/calldesk/requirements-calldesk.txt`, `requirements.licences.json` | Add them before R18.1 (ADR-29) |
| G17 | **The guide's card C74 says the Privacy panel has no calls row**; the combined review added four | `docs/architecture/JARVIS-Architecture.md` (C74), `src/jarvis/calls/privacy.py` | The guide's next edition |

### 6.3 Fixed by the combined review so far (27 Nov 2026)

On branch `r18-review`, before this edition: speech options ranked free first (a HIGH finding: paid
Sarvam could beat free Google); Telegram can never approve a call card and the phone's Approve
keeps the passkey; a pending call's number masked in the Approvals panel; the calls' four Privacy
rows; no bare 500 from a calls route; the restore drill counts the calls' sub-collections; the
Build Book reads the console's calls assets; a live ticket is taken only when the socket brought no
other credential. Each is described as built in chapters 04–07.

### 6.4 Risks

| Risk | Why | Mitigation as built | Left |
|---|---|---|---|
| The sound path fails on the owner's laptop | Phone Link picks its own devices; Bluetooth adapters without hands-free support can't do calls | The desk checks the path before every call and nothing is dialled if it fails | S0 decides; the plan's fallbacks are the call box or a personal-KYC number, each with its ₹ |
| TRAI or the operator treats AI-assisted personal calls as A2P | The 2026 rules are about commercial calls; personal AI calls are not addressed | Every call is his tap, own number, personal volume, disclosure first (chapter 05, section 8.5) | The plan pauses the feature for his decision if anything is issued |
| Spam flags on his number | Operators watch calling patterns | The day's limits | — |
| Phone Link updates | Its behaviour can change | The checks before every call | — |
| The other person's data at speech vendors | Their voice reaches the chosen speech option | Only options set up and passed; Sarvam only with his YES; Bhashini opt-in | Each vendor's own terms (Google's and Azure's say they don't train on it, per the plan; *unverified* here) |

## Change log

| Version | Date | Release | What changed | By |
|---|---|---|---|---|
| v6.4.1 | 27 Nov 2026, 14:30 IST | R6.4 | First edition: modules with no code home, nine conflicts and their resolutions, scaling and availability limits, carried-over debt, seven proposed ADRs | 🛠 Mark XXV |
| v6.4.2 | 27 Nov 2026 | R6.4 | Verification (chapter 13): conflict C10 (the slice 1 plan's R0 tier against the code's three classes); C1's source and C6's resolution; the one-instance row says what is really in memory; the timeout is set, not a default; three debt items the verification found; the proposed ADRs moved to chapter 08 with a pointer left here | 🛠 Mark XXV |
| v6.4.3 | 27 Nov 2026 | R6.4 | Outfit plans: the owner chose 90 days; the code change is follow-up F4 | 🛠 Mark XXV |
| v6.5.0 | 27 Nov 2026, 21:00 IST | R18 | R18 "Calls from your laptop": C1, C2 and C5 as built; conflicts C11 (recording size, ADR-33) and C12 (the 23rd tab, ADR-35); the one-instance, timeout and storage rows as built; new section 6: what is not built or differs from the plan (the brain check per language, laptop speech mode, FLEURS untested and 8 languages without clips, Bhashini opt-in, and five more), eight gaps found while writing this edition, the review's fixes so far, and R18's risks | 🛠 Mark XXV |
