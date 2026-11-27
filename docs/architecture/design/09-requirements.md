Version v6.4.2 · 27 Nov 2026 · Release R6.4 · Status: Current · Owner: 🛠 Mark XXV

# 09 · Requirements baseline

This chapter fixes the requirements the architecture answers to. The record is the owner's requirements workbook, **`JARVIS_Requirements_Complete_v13.1.10.xlsx`** (27 Nov 2026), kept outside this public repository (git tracks no workbook; *unverified* from the repository: that its home is the owner's Drive), because its remarks hold personal details. Every count below was re-counted from the workbook on 27 Nov 2026 (chapter 13). Chapter 10 lists every row against the architecture; this chapter gives the totals, how a requirement finds its place in the design, and the rules for adding one.

## 1. The baseline in numbers

**390 requirements: 215 Done, 7 Next up, 146 Pending, 22 Declined** (built ≈ 55 %). 326 are Free, 57 Subscription and 7 have no type (declined asks).

### By phase (the roadmap's phases P0–P7)

| Phase | Rows | Done | Next up | Pending | Declined |
|---|---|---|---|---|---|
| P0 Core loop | 10 | 7 | 0 | 3 | 0 |
| P1 Voice | 16 | 8 | 0 | 7 | 1 |
| P2 Tools + safety | 41 | 33 | 0 | 7 | 1 |
| P3 Memory + profile | 114 | 73 | 0 | 37 | 4 |
| P4 Proactive | 44 | 34 | 0 | 10 | 0 |
| P5 Smart home (incl. 2 "smart home + camera") | 89 | 5 | 0 | 71 | 13 |
| P6 Mobile + wearables | 15 | 7 | 7 | 1 | 0 |
| P7 Hardening + launch | 46 | 41 | 0 | 2 | 3 |
| Deferred (after maturity) | 15 | 7 | 0 | 8 | 0 |

P3 is large because the 80 wardrobe use cases (rows 296–375) sit there; P5 holds most of the 66 vision use cases (R8–R10) and the smart-home rows (R12), which is why it is mostly Pending.

### By architecture layer and by skill

The workbook names a **module** for every row; chapter 10's generator maps each module to the layer and the skill that own it (the map is `MODULES` in `scripts/docs/adds_traceability.py`, reviewed with this chapter).

| Layer | Rows | Done | Next up | Pending | Declined |
|---|---|---|---|---|---|
| L1 Interaction | 4 | 4 | 0 | 0 | 0 |
| L2 Input & perception | 21 | 12 | 0 | 8 | 1 |
| L3 Context & orchestration | 8 | 7 | 0 | 1 | 0 |
| L4 Reasoning | 16 | 11 | 0 | 5 | 0 |
| L5 Skills | 275 | 128 | 7 | 123 | 17 |
| L6 Integration & tools | 15 | 7 | 0 | 7 | 1 |
| L7 Data | 0 | — | — | — | — |
| L8 Output | 1 | 1 | 0 | 0 | 0 |
| Cross-cutting (security, observability, quality, documentation) | 50 | 45 | 0 | 2 | 3 |

No requirement names Layer 7 directly: storage is a means, so data needs appear inside the features that keep data (the vault, the wardrobe, memory). Most rows are skills, as expected for an assistant.

| Skill (the 11 of the skill register, `src/jarvis/skills/ids.py`) | Rows | Done | Next up | Pending | Declined |
|---|---|---|---|---|---|
| Task & Productivity (incl. the wardrobe) | 108 | 88 | 0 | 19 | 1 |
| Health & Wellbeing | 75 | 4 | 0 | 58 | 13 |
| Code & DevOps | 39 | 38 | 0 | 1 | 0 |
| Research & Intel | 34 | 20 | 0 | 11 | 3 |
| Communication (incl. calls) | 31 | 13 | 7 | 10 | 1 |
| Security Advisor | 24 | 17 | 0 | 7 | 0 |
| Automation Engine | 21 | 10 | 0 | 11 | 0 |
| Creative | 9 | 1 | 0 | 7 | 1 |
| Finance & Analytics | 8 | 4 | 0 | 4 | 0 |
| Learning | 8 | 0 | 0 | 8 | 0 |
| Decision Support | 4 | 0 | 0 | 4 | 0 |
| No single skill (platform: brain, console, phone, No-AI mode) | 29 | 20 | 0 | 6 | 3 |

Health & Wellbeing, the 11th skill added for the vision use cases, is the largest body of unbuilt work; Learning and Decision Support have no code yet (chapter 12).

### By release

| Release | Rows | Status |
|---|---|---|
| R0–R4, R5.1, R6–R6.4, R7, R11, R11.1, R13, R13.1, R14 (live) | 213 | 209 Done; 4 Pending: R1's Phase 0 re-check and Swiggy ordering (rows 33, 35) and R13's activity timeline and screen time (rows 182, 183, designed with R8) |
| R5 (live) | 10 | 6 Done; rows 81, 83, 84 and 383 move to **R5.2** (plan `docs/plans/r5-2-voice.md`, on branch `r5-2-plan`, not yet in `main`) |
| **R18 Calls from your laptop** (`v18.0.0`, building) | 7 | 387, 395, 396, 104, 195–197: Next up |
| R18.1 Launch | 2 | Pending (Feb–Mar 2028) |
| R8 / R8.1 / R9 / R10 (vision) | 25 / — / 20 / 13 | Pending, split by camera (chapter 11) |
| R12 Smart home | 14 | Pending |
| R15 / R16 / R17 (subscription) | 16 / 11 / 18 | Pending |
| R19 Trading desk | 1 | Pending (decision later) |
| Later (wardrobe extras, row 386) | 12 | Pending |
| Not placed | 28 | 22 Declined; 6 Pending (rows 129, 198, 376, 384, 385, 389) |

## 2. How a requirement finds its place in the design

1. **Module → layer and skill.** Every workbook module maps to one layer and one skill (chapter 10). A module that is not in the map shows up in chapter 10's summary as "no architectural home"; today there is none.
2. **Skill → code.** Every tool is filed under one group of one skill in the skill register (`src/jarvis/skills/catalogue.json`, R14 D11); a tool outside the register fails CI.
3. **Release → plan.** A row's release names the plan in `docs/plans/` that designs it; a plan states its layers, its skill, its phase and its decisions, and the chapters of this document it changes.
4. **Done → code.** Chapter 10 points each Done row at the file that carries it, reviewed against the row's full text and the code (the generator's `OVERRIDES`), or, for a use-case row (INV-01, LND-14 …), at the test named after it; a row that has no one place says "not located" and why (`NOT_LOCATED`). A Done row not yet reviewed falls back to the file that best matches its own words, shown as a lead, not a proof.

## 3. Rules for adding and changing requirements

These are the owner's standing rules (17 Nov, repeated 23 Nov) and workshop rule 3.8:

1. **A new requirement becomes a workbook row at once**, Pending, with its module, phase, type, release (or "—") and the owner's own words; the workbook's version goes up at every change.
2. **Serial numbers never change** (retired serials stay retired), so every document's row numbers keep pointing at the same feature.
3. **Status is only Done, Next up, Pending or Declined.**
4. **A row whose module is new** gets an entry in the generator's `MODULES` map (layer, skill, code paths) in the same change, or is listed as "no architectural home" until it does. **A row that becomes Done** gets a reviewed pointer in `OVERRIDES` (or a reason in `NOT_LOCATED`) in the release that builds it; the generator reports a pointer that no longer fits.
5. **A requirement that conflicts with this design** (a rule, a layer's contract, a privacy or cost principle) gets an ADR in chapter 08 before it is built; the conflict and its resolution are listed in chapter 12.
6. **At every release** the Workshop regenerates chapter 10 from the new workbook (`python scripts/docs/adds_traceability.py <workbook>`), updates this chapter's tables, and updates the chapters the release changes.
7. **Declined is a decision, not a deletion:** declined rows keep their reason in the workbook and come back only on the owner's Yes.

## Change log

| Version | Date | Release | What changed | By |
|---|---|---|---|---|
| v6.4.1 | 27 Nov 2026, 14:10 IST | R6.4 | First edition: the baseline from workbook v13.1.10 (390 rows) by status, phase, layer, skill and release; how a requirement finds its place; the rules for adding requirements | 🛠 Mark XXV |
| v6.4.2 | 27 Nov 2026 | R6.4 | Verification (chapter 13): the live releases' row fixed (213 rows, 209 Done, 4 Pending, not 215 and 213); the R5.2 plan's branch named; how chapter 10 now locates Done rows; a reviewed pointer for every row that becomes Done; the workbook's home marked unverified | 🛠 Mark XXV |
