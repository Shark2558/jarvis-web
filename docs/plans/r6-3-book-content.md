Version v6.3.1 · 23 Nov 2026, 14:10 IST · Release R6.3 · Status: Draft · Owner: 🛠 Mark XXIV

# Release R6.3 — The Build Book: written by AI, short tour and full book (`v6.3.0`)

**Phase:** 7 (quality, evals, cost) on R6's Build Book (cross-cutting, the Learning skill), with ONE
paid path (the AI writer) that is off until the owner's typed YES. **Type:** ₹0 a month fixed: no new
Scheduler job, no new secret, no new Cloud resource, no new keyring purpose, no new model-callable
tool. **Scope:** Part 2 of the Book rebuild (Phase A §11), as the owner approved it at approval stop 1
(15 Nov 2026: Part 1 approved, "the AI writer: a trial first") and decided it on 23 Nov 2026 (the
writer trial runs inside JARVIS after R6.3 is live; seven tour highlights; plan from Phase A's summary
of his lost 557-line prompt). His requirements workbook rows **379** ("the Book written by AI with
more explanations and examples") and **380** ("two versions: a short 10–15 minute tour and a
descriptive full book that grows with JARVIS"). **Split (D0):** R6.3 builds the content engine, the
writer, the full book in the reader and the short tour; **R6.3.1** (`v6.3.1`) builds the pictures
(Phase D, approval stop 3), the de-duplicated storage, the eight diagrams and the local setup guide;
both are planned in full here. **Not in scope:** R6.4 (Phase E, the Book's new look), the guest-safe
full book, AI text in the guest talk-through. **Branches:** plan `r6-3-plan` (from `main` @
`47ee8fc`, R13.1 live as `v13.1.0`) → I0 `r6-3-i0` → parts `r6-3-a` … `r6-3-d` → integration
`r6-3-i1` → PR `v6.3.0 · R6.3 The Build Book: written by AI · Mark XXIV`. Every commit carries
`JARVIS-Version: v6.3.0` and `JARVIS-Mark: XXIV`. Read on `47ee8fc`; every file:line below is from
that commit. The basis is Phase A (`docs/plans/r6-2-book-rebuild/PHASE-A-FINDINGS.md` v6.2.1, copied
unchanged into this branch); every Phase A fact this plan uses was re-checked on `47ee8fc` and the
ones that moved are corrected in "What the code says today". This document's version line is the
plan's edition (v6.3.1); the code's version is `6.3.0`.

## Summary for the owner (plain words)

1. **Two versions of the Book.** A **short tour** of about **13–14 minutes** (inside your 10–15) and a
   **full book** in the console's Book panel: one page for each part of JARVIS, written by AI with
   plain explanations and a worked example, that grows by itself as JARVIS grows (a new part gets a new
   page at the next release).
2. **The tour has seven highlights**, as you chose today: Voice; Approvals and passkeys; Memory; Vault
   and documents; Home bridge and cameras; the phone app and SOS; and the new **Wardrobe & Try-on**.
   It follows one request from start to finish: "Add a dentist appointment on Friday at 5 pm", then
   "Cancel it". Its words are written by the Workshop, not by AI (₹0), and are in this plan for your
   approval (**approval stop 2**, section "The short tour's first script"). It plays in the show you
   already know, with its current pictures; new pictures come with R6.4's new look.
3. **Nothing is written by AI until you try it.** In Book settings, a new **Writer trial** (yours only)
   has two brains write the same **5 sample pages**: Claude on its everyday "balanced" tier (Sonnet 5.5)
   and the free Gemini brain. You first see the estimate (**about ₹40**, most likely ₹30–50; Gemini is
   ₹0), then type **YES**; the trial stops at **₹60** whatever happens. The pages appear side by side,
   with which checks each passed. Gemini's free tier may let Google learn from what it reads, so it is
   given only JARVIS's public code and the numbers computed from it, never anything of yours.
4. **Then you pick** the writer and the caps in Book settings. The proposed caps (yours to confirm):
   **₹1,500** for the first full write (one time), **₹500** a release, **₹1,000** a month, and it stops
   before your monthly limit in Vitals would pass **80 %**. The **first full write** (about 152 pages)
   starts only after a **second typed YES** with its estimate: **about ₹1,120** (₹770–1,560) with
   Claude, ₹0 with Gemini.
5. **Nothing spends money by itself after a deploy.** At each new release the Book works out which
   pages changed and shows the estimate (a feature release: about ₹300, ₹130–620; a hotfix: under
   ₹30); it writes them only when you tap **Update** and confirm the ₹. At the pick you may instead let
   it update by itself within the ₹500 cap (off unless you choose it).
6. **Checked before anything is kept.** Every file, function and setting a page names must exist;
   every number comes from the code, never from the AI; personal data and secret shapes are refused; an
   unverified fact stays marked "Unverified"; a feature that isn't built may appear only under
   "Planned". A page that fails keeps its previous text (or the plain generated text). A page written
   by a smaller model, or by the laptop brain, is refused.
7. **Who sees what.** You: the tour, the full book, the trial. A guest: the tour only, without the
   costs scene and without any ₹ figure; never the trial and never the full book (a guest-safe full book
   is R6.4's).
8. **How long it takes.** The writer works in the background on JARVIS's existing clocks and never at
   start-up. The trial takes minutes while Book settings is open, else about an hour; the first full
   write about half a day with the home watchdog running (every 5 minutes), a few days without it (the
   morning clock only). These times are estimates until the trial measures them.
9. **Voice stays free.** The tour uses the browser's voice by default (₹0), as R6.2 set it; the Cloud
   voice, if you switch to it, uses the free allowance first, then about ₹27–29 a tour. A guest never
   costs you anything.
10. **Storage.** One release's book and code now take **10.0 MB** (measured today; 7.98 MB at Phase A);
    three kept are about 30 MB of the 60 MB cap. The AI pages add about 0.5 MB a release. A warning
    comes at 80 % (48 MB) before anything has to be dropped.
11. **What follows in R6.3.1.** Pictures of every module from a made-up demo household (you approve a
    **contact sheet** of all of them first: **approval stop 3**), storing the code and pictures once
    instead of once per release, eight diagrams with part numbers, and a local setup guide that is
    actually run. Why the split: Part 2 measures at about 15 builder-days, not Phase A's 9–10.
12. **The look does not change.** New parts use the console's and the Book's existing styles.
13. **Your steps now:** approve or correct the tour's script (stop 2) and answer "Needs the owner"
    (each has a safe default). After R6.3 is live: run the Writer trial, then pick.

## What is built: rows 379 and 380, and where each goes

His workbook (not in the repository) gives the two rows' titles quoted below; their own acceptance
checks were not available to this plan, so each check here is written from Phase A §7–§9 and his
decisions of 15 and 23 Nov 2026, and is marked so. Each named test is in its part's files; the eval
case of the same name runs it through the wired app at I1.

| Row | His words | Acceptance check (from Phase A and his decisions) | Part | The test (what must hold) |
|---|---|---|---|---|
| 379 | "the Book written by AI with more explanations and examples" | Every full-book page has a plain-words part, at least one worked example marked as made up, a "how it works" part whose every source reference exists, and its numbers from the fact pack; it records the brain and tier that wrote it; a page below BALANCED is refused | A (facts, pages index), B (writer, checks), C (reader) | `test_row379_a_page_is_written_at_balanced_with_an_example_and_every_source_checked`: the fake Claude brain writes `pg_card_c16`; the sealed page has the sections `plain`, `example` (marked "Example (made up)"), `how`, `costs`, `fails`, `code`; every `path`, `path:symbol`, setting and collection in it is in the fact index; every number outside the example is a filled placeholder; its meta says brain `anthropic`, tier `balanced`, model = the registry's balanced model; the same page from a router that answered on FAST, or from the laptop (`offline`), is refused and the generator's text stays |
| 380 | "two versions: a short 10–15 minute tour and a descriptive full book that grows with JARVIS" | The tour lasts 10–15 minutes by the timer (13–14 aimed), has the seven highlights he chose and the running example; the full book has a page for every catalogue card, module, console screen and outside service, and a new card gets a page at the next release with no hand edit | A (pages index, facts), D (tour), B (update), C (reader) | `test_row380_the_tour_is_ten_to_fifteen_minutes_with_his_seven_highlights` (the filled tour of `47ee8fc` times 780–870 s for the owner and 760–850 s for a guest, inside the hard 600–900 s band; its highlight ids are exactly the seven, in his order; the running example has both lines) and `test_row380_a_new_card_gets_its_own_page_at_the_next_release` (a fixture guide with a C74 card: the pages index gains `pg_card_c74` in its module's chapter, the update's estimate counts it, and after the update the reader lists it) |
| 23 Nov · trial | "an owner-only Writer trial in Book settings: 5 representative sample pages each by the BALANCED Claude brain and by the free Gemini brain; the ₹ estimate shown first, his typed YES, a hard cap; the pages shown side by side" | As his words; never for a guest; nothing spent before the YES | B, C | `test_the_trial_spends_nothing_before_yes_and_stops_at_its_cap`: zero brain calls before `YES`; "yes", "Yes", "YES!" refused; with the fake brains, 5 + 5 pages; with every Claude call settling at its hold (₹8.95 at ₹95.24 a dollar, D8) the cap of ₹60 lets 6 calls through and refuses the 7th before it is sent; the side-by-side view lists both brains' pages with their checks; a guest session gets 403 on every trial route |
| 23 Nov · pick | "then he picks the writer and the caps; the full first write starts only after his pick and a second typed YES with its ₹ estimate" | No first write without a pick and a second YES bound to the estimate shown | B, C | `test_the_first_write_needs_the_pick_and_a_second_yes_on_the_estimate_shown`: `POST …/first` before a pick is 409 `pick_needed`; with a pick but a stale `estimate_id` 409 `estimate_changed`; with both, the run starts and its cap is the pick's |
| 23 Nov · deploy | "nothing spends money by itself after a deploy" | After a new release, zero brain calls until his Update (or his opt-in) | B | `test_nothing_spends_by_itself_after_a_deploy`: a new release id in the fake source, 50 `book_write` ticks: no brain call, one `book_update_ready` state with its estimate; after `POST …/update` with `confirm_cost: true`, the changed pages only |

**Where Phase A goes further than what he approved, and what this plan does.**

| Phase A | His decision | This plan |
|---|---|---|
| §8.1 the tour "written and timed twice" by the AI writer (≈ ₹30) | the first script is fixed text written by the Workshop, ₹0, approved at stop 2 | The tour is a fixed script with fact placeholders (`gen/tour.json`), filled at CI; no AI writes it; its cost is out of every estimate |
| §8.2 six highlights | seven, with Wardrobe & Try-on (+40 s, ≈ 13–14 min) | Seven (D9) |
| §7.1 the writer as a resumable tick job | stands (decision 3) | `book_write` on the existing clocks, plus a console "step" while he watches (D5); a Cloud Run Job only if the trial shows the tick is crowded (owner question 5) |
| §7.6 the caps ₹1,500 / ₹500 / ₹1,000, stop at 80 % | proposed defaults he confirms at the pick | The pick shows them filled in; nothing runs without his pick (D7) |
| §13 decision 1, the free Gemini brain only after a 5-page trial | the trial runs both brains inside JARVIS after R6.3 is live | Built as the Writer trial (D6) |
| §13 decision 4, listening stops at the free minutes | superseded by R6.2's browser voice by default | Nothing to build; the tour inherits R6.2's settings |
| §9.8 images, §8.4 de-duplication, §9.2 the 8 diagrams, §9.7 the setup guide | in Part 2 | R6.3.1, planned in full below (D0) |
| §9.9 Simple / Technical / Both, search, print, the guest-safe full book | R6.4 | Not here; each page keeps a plain part first and the technical part in a closed disclosure |

## How it fits the architecture

| Feature | Layer · skill | Phase | Verdict |
|---|---|---|---|
| The fact pack, the lines-of-code counter, the technology inventory (CI, deterministic, ₹0) | X cross-cutting (delivery) · Learning | 7 | Build now |
| The pages index and the module map (every card in exactly one module) | X · Learning | 7 | Build now |
| The AI writer: reading packs, prompts, the `jarvis.llm` write call by tier, the resumable job | L4 reasoning, L3 orchestration (tick) · Learning | 7 | Build now; off until his YES |
| The writer's checks before anything is sealed | L4 guardrails, X security · Security Advisor | 7 | Build now |
| The trial, the pick, the caps and the two typed YES | X costs · Finance & Analytics | 7 | Build now |
| The full book in the owner's reader, "continue where I left off" | L8 rich output · Learning | 7 | Build now |
| The short tour (fixed script, seven highlights, timer) in the existing player | L8 · Learning | 7 | Build now |
| The AI pages sealed as a third file of a release, the 80 % storage warning | L7 data · Security Advisor | 7 | Build now |
| Module pictures, the demo household, the OCR privacy gate, de-duplicated storage, 8 diagrams with C-ids, the local setup guide | L8, L7, X | 7 | R6.3.1 |
| The Book's new look, the guest-safe full book, search, print | L8 | 7 | Later (R6.4) |

No change to the reference architecture. Two rules are widened in the open (security-reviewer to
confirm): (1) a Book job calls a paid model in the background, only inside a run the owner started
with a typed YES (or his opt-in for release updates), under four caps; (2) a brain that may train on
what it reads (the free Gemini brain) may be sent the release's **public** code and fact pack, only
by the writer, only after his choice, never with tools (the registry's rule, `llm/brains.py:1–6`,
still holds: no tool specs, no tool output). The writer names no model: it asks `jarvis.llm` for the
BALANCED tier of a brain from the registry and records what answered. The project's default stack
lists MCP as the tool protocol; the repository's own rule (`CLAUDE.md`: "tools via the custom
gateway, no MCP") stands, and R6.3 adds no tool at all.

## What the code says today (`main` @ `47ee8fc`)

## The short tour's first script (approval stop 2)

## Decisions (binding)

## Data model (prefix `jarvis_`; flat ids; every document carries `updated_at` and a plain `owner`)

## The HTTP contract

## Tools: none new

## Per part: failures, security, cost

## Cost (₹)

## The I0 seam list (branch `r6-3-i0`; the integrator owns these files)

## Part split (four builders; worktrees; branches `r6-3-a` … `r6-3-d` from `r6-3-i0`; disjoint files)

## R6.3.1: images, de-duplication, diagrams and the setup guide (planned here, built next)

## Tests and evals (mock only; each control must make its suite fail)

## Size guards

## Risks and known limits

## Needs the owner (safe defaults; none blocks the build)

## Exit check (before the PR)

## What can't be verified from this workspace

## Sources (read 23 Nov 2026)

## Change log

| Version | Date | Release | What changed | By |
|---|---|---|---|---|
| v6.3.1 | 23 Nov 2026, 14:10 IST | R6.3 | Skeleton | 🛠 Mark XXIV |
