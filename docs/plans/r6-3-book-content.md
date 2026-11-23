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

Measured here with the generator exactly as CI's deploy job runs it (`python -m
jarvis.buildbook.gen --out <dir> --best-effort`, Python 3.12, a clean checkout of `47ee8fc`) and
with small standard-library scripts outside the repository.

1. **Version and labels.** `__version__ = "13.1.0"` (`src/jarvis/__init__.py:3`). Exact pins:
   `test_about.py:25`, `test_r7_seams.py:111`, `test_r11_1_seams.py:74`, `test_r13_seams.py:72`,
   `test_r14_seams.py:99`, `test_r131_seams.py:36`; a prefix pin `test_r11_seams.py:60`
   (`startswith("13.")`); `v13.1.0` in `tests/r13_fake_server.py:126`, `test_r13_wiring.py:306`,
   `test_r131_wiring.py:291`. The release label is read from the version (`gen/plans.py:78`
   `release_label`) and pinned as `R13.1` at `test_book_gen_determinism.py:212`,
   `test_r7_seams.py:160`, `test_r14_seams.py:104`, and with its own plan's path at
   `test_book_gen_plans.py:212` (`docs/plans/r13-1-try-on.md`) and `:218` (the first limitation's
   release). Plans are ordered by release number (`gen/plans.py:61–68`), so this plan,
   `r6-3-book-content.md`, is read first only once the version is `6.3.0`; it carries "Risks" and
   "Needs the owner" lists, which `:218` needs.
2. **The generator today.** `book.json` **198,076 bytes**, `source.zip` **9,807,662 bytes** (2,670
   files, 27.3 MB raw), **97** files left out, 4.3 s; total **10.0 MB** a release. The show: 11 scenes,
   **56 beats, 6,036 characters, 1,047 words**. Sections: 66 packages, 69 fit rows, 85 libraries, 38
   stack items, 10 workflows, 29 plan decision lists, 25 cost items at ₹95.24 (2026-11-01), **15**
   integration services, **80** limitations (the cap, `gen/write.py:92` `limits[:MAX_LIMITATIONS]`),
   26 key purposes, 56 alert kinds. Scene 1 says "about 206,413 lines of code" (raw lines).
3. **The guide.** `docs/architecture/JARVIS-Architecture.md` v13.1.5 (18 Nov 2026): **73 cards, C01–C73**
   (C69–C73 are R13's and R13.1's wardrobe and try-on), 14 diagrams (`diagrams/*.markdy`), **0** C-ids in
   any diagram. `scripts/arch_coverage.py`: OK — **66** packages and modules, **104** console modules,
   **2** Scheduler jobs, **31** outside services, **120** Firestore collections. C57 still says "Outside
   services: Anthropic (the talk-through only)" (Phase A G2, open). §11 Roadmap still follows the
   11 Nov release plan (it lists R13 as "camera life"): stale.
4. **Sizes and caps.** `buildbook/model.py` (412 lines): `KEEP = 3` (`:65`), `SNAPSHOT_CAP_BYTES = 15
   MiB` (`:67`), `BOOK_JSON_CAP_BYTES = 2 MiB` (`:68`), `MAX_LIMITATIONS = 80` (`:70`), `FileKind =
   Literal["book", "source"]` (`:83`), `SHOW_SCENES` 13 (`:84`), `BOOK_SCENES = 11` (`:99`),
   `SealedRelease.files` exactly 2 (`:277`). `seal_index.py:43–44` `KINDS = ("book", "source")` and
   their caps; `checked_files` (`:147`) demands exactly those two. `book_max_total_mb` 60
   (`config.py`); **no 80 % storage warning exists** (searched `buildbook/`): `sealer._room` (`:171`)
   only prunes oldest-first at seal time.
5. **The clocks.** `book_seal` is a tick job (`sealer.py:259–264`, `JOB_BUDGET_S = 45.0` at `:51`).
   `ticks.py:32` `MAX_BUDGET_S = 60.0`, `:35` `TICK_TOTAL_BUDGET_S = 150.0`. The brief clock runs
   `0,30 4-11 * * *` IST with a 180 s attempt deadline (`deploy/cloudrun.sh:731–734`): 16 ticks a day,
   04:00–11:30 only. The home watchdog runs `*/5 * * * *` with a 60 s deadline (`:756–759`) and
   `WATCHDOG_BUDGET_S = 50.0` for all its jobs (`home/watchdog.py:61`); R6's jobs join it only when Home
   is on (`api/r6_wiring.py:216–218`); `ADVISORY_JOBS` (`home/watchdog.py:81–84`) holds `book_seal`,
   `book_sweep`. `R6_JOB_NAMES = {"book_seal", "book_sweep"}` (`api/r6_wiring.py:76`, pinned
   `test_r6_wiring_seams.py:154`); the ordered tick-job list is pinned in `test_r2_wiring.py:258–272`
   and `test_r6_wiring.py:133–137` (with `len(st.home_watchdog.jobs) == 2`).
6. **Cloud Run.** 1 CPU, 512 MiB, `--timeout 300`, 0–1 instances (`cloudrun.sh:623–624`); CPU only
   during a request. **`JARVIS_LLM_TIMEOUT_S=20`** in production (`:600`), handed to the Anthropic
   client as its timeout (`llm/factory.py:18`, `anthropic_provider.py:110–116`): a non-streamed call
   that takes longer than 20 s to answer fails. The brain keys are optional secrets:
   `JARVIS_ANTHROPIC_API_KEY` (`:158`) and `JARVIS_GEMINI_API_KEY` (`:162`), mounted at `:614`.
   `JARVIS_DEFAULT_TIER=balanced`, `JARVIS_ENV=prod`, `JARVIS_AUTH_MODE=google` (`:600`). Region
   `asia-south1` (`:48`). `make book` (`:619`).
7. **The router.** `llm/router.py`: `_DEGRADE_TO` STRONG → BALANCED → FAST (`:73–77`); `complete(…,
   allow_degrade=True)` (`:192–203`): with `allow_degrade=False` a transient error raises instead of
   going down a tier (`:262–264`), **but the laptop brain is still asked** on an unreachable cloud, an
   open breaker or no credit (`:215–222`, `:236–253`). `stream` never changes tier but also hands over
   to the laptop before its first text (`:272–336`), and does not say which model answered.
   `Completion` carries `model`, `provider`, `usage`, `cost_usd` and `offline` (set only by the
   laptop) (`llm/base.py:190–200`); `StreamUsage` counts tokens while streaming (`:138–187`). So Phase
   A's "Unverified whether the router already has such a switch" resolves to: half of one
   (`allow_degrade`), no switch for the laptop.
8. **The brains.** `BrainSpec(id, label, provider, tiers, trains_on_content)` (`llm/brains.py:29–34`);
   `router_for(id)` (`:82`); the Gemini brain exists only with `JARVIS_GEMINI_API_KEY`, labelled "Gemini
   (free)" and `trains_on_content = not gemini_paid_tier` (`:128–139`). Tiers: Claude
   `claude-haiku-5-5` / `claude-sonnet-5-5` / `claude-opus-5-5` (`config.py:133–135`); Gemini
   `gemini-3.5-flash-lite` / `gemini-3.8-flash` / `gemini-3.8-flash` (`:142–144`). The talk lane picks
   the default non-training brain (`buildbook/talk.py:145–152`), BALANCED, 400 tokens (`:42`, `:107`).
9. **Prices and the rate.** `llm/pricing.py:27–34`: Sonnet 5.5 US$2 / 10, Opus 5.5 4 / 20, Haiku 5.5
   0.10 / 0.50 per million tokens in / out (cache reads 5 % on Sonnet and Opus, writes 1.25×); every
   Gemini free model $0. `billing/fx.py:33–34` `DEFAULT_RATE = 95.24`, `DEFAULT_AS_OF = "2026-11-01"`
   (the day's rate from Frankfurter otherwise); `config.py:359` `usd_inr_rate` 95.24;
   `gen/costs.py:28` `FALLBACK_RATE = (95.24, "2026-11-01")`. Unchanged since Phase A.
10. **Money.** `billing/service.py:59` `LABELS = {"voice": "Voice", "tryon": "Try-on"}`;
    `ensure_allowed` (`:222`) refuses a paid brain at `used >= limit`, fail closed; `record` (`:333`)
    adds a completion to his IST month under the brain's id and never raises; `billing/spend.py`
    `ensure_spend_allowed` refuses when `used + spend > limit` (R13.1). R13.1's atomic cap with holds is
    `wardrobe/seeme/cap.py` (`reserve` / `settle` / `release` in one transaction, `busy` while a hold
    under 10 minutes exists); its typed YES is `wardrobe/seeme/consent.py:96` (`typed.strip() == YES`).
    R6.2's confirm-before-spend is `confirm_cost: true` (`buildbook/owner.py:80` `CostNotConfirmed`).
11. **Book settings** (`buildbook/owner.py:4`): `creator_name, show_voice, listening, talk_on,
    allow_training_brain, voice_rule, updated_at`; `SETTINGS_KEYS` (`api/r6_wiring.py:77`). Both voices
    default to the browser (R6.2 decision 4).
12. **The show player.** `book.html` (117 lines) loads `console-fx.js`, `console-permissions.js`,
    `console-book-show.js`, `console-voice-capture.js`, `console-book-voice.js`, `console-book-2d.js`,
    `console-book-talk.js` and the module `console-book-3d.js` (`:108–115`); it is not hash-pinned.
    `console-book-show.js` is **390 lines** of its 400 (`test_book_static.py:55–58`: every Book JS ≤ 400,
    CSS ≤ 300, ASCII): `normalScene` accepts `n` 1–11 only and `normalScript` sorts by `n` (`:67–90`),
    `timeline` appends scene 12 and 13 (`:93–99`). Pictures are chosen by scene number:
    `console-book-scenes.js` {1, 2, 12, 13}, `-flow.js` {3, 5, 6, 8}, `-data.js` {4, 7, 9, 10, 11}
    (`test_book_static.py:30–33`; `console-book-scenes-data.js:189`): 4 the vault and keyring purposes,
    7 the home boundary, 9 tags on rings by group, 10 ₹ bars, 11 dimmed "later" nodes, each from the
    scene's facts. Show lines are never hard-coded in JS (`test_book_static.py:70`).
13. **The console.** `console.html` 782 lines, hash-pinned (`test_r13_seams.py:559–560`,
    `test_r131_seams.py:420`); it loads `console-book-reader.js` (`:775`) and `console-book.js`
    (`:776`); the Book panel `#p-book` (`:614`); 22 panels. `console-book.js` 384 / 400,
    `console-book-reader.js` 257 / 400, `console-book-talk.js` 371, `console-book-voice.js` 301.
14. **The routes.** `api/book.py`: `GET /v1/book`, `/sections`, `/releases/{rid}/sections`, `POST
    /releases/{rid}/ticket`, `GET /download/{ticket}`, `GET|PUT /settings`; `api/book_show.py`: `open`,
    `show/script`, `show/speak`, `show/ask`, `show/beat`, `close`, `resume`, `show/lock`;
    `api/book_show_hear.py`: `show/hear`, `show/heard`. `api/book_gate.py:56` `console_only` passes a
    signed-in browser only (R6.2 G11 closed, no token-mode shortcut). Limits `book_show_wiring.py:41–51`.
15. **Size guards in force.** `config.py` **789** (≤ 790: `test_r131_seams.py:110`, `:905`; < 800:
    `test_r13_seams.py:223`, `test_r14_seams.py:480`): **1 line left**. `api/app.py` 732 (≤ 735,
    `test_r131_seams.py:902`), `tools/gateway.py` 760 (`== 760`, `:903`), `core/brain.py` 713 (≤ 741,
    `:904`), `api/console.py` 469 (≤ 475, `:917`). C modules of the Book ≤ 400 and functions ≤ 50
    (`test_book_boundaries.py:19–36`, `:153`), with the lane's import guard `LANE_FORBIDDEN` (`:37–50`).
16. **Keyring** 26 purposes (`keyring.py:42–84`; pinned `test_r131_seams.py:56`, `test_r13_seams.py:107`,
    `test_r14_seams.py:261`, `test_r7_seams.py:295`, `test_r11_seams.py:166`; positions
    `test_r14_seams.py:260`, `test_r7_seams.py:294`). `BookCrypto` (`seal_index.py:59–108`) seals a file
    under a fresh data key wrapped by the keyring's `vault` cipher with the Book's own AADs, and the index
    under `book_index`: a new Book file needs no new purpose.
17. **What the code snapshot holds.** The zip includes **`.claude/**` (46 files)**, `tests/fixtures/**`
    (106 files), `docs/` (135), `android/` (82), `evals/` (156). Phase A §7.3 says the writer never reads
    `.claude/**` or fixtures: true only if the reading packs leave them out (D4); they are in the zip.
18. **The fact sources exist as constants.** `tools/budget.py:33` `MAX_NEW_CARDS = 5`;
    `undo/models.py:23` `RETENTION_DAYS = 30`; `recall/models.py:28` `MAX_FACTS_PER_TURN = 12`;
    `sos/service.py:68` `HOLD_S, WEB_COUNTDOWN_S = 2, 5`; `vault/models.py:26` `REMINDER_CHOICES`;
    `config.py` `memory_learn_daily_cap` (`:341`), `vault_unlock_minutes` (`:247`), `home_heartbeat_s`
    (`:262`), `home_offline_after_s` (`:265`), `sos_max_contacts` 5 (`:537`), `tryon_month_cap_inr` 300
    (`:641`); `wardrobe/tryon/model.py:32` `MEASURES`; 179 settings in all.
19. **The running example still holds** (Phase A §9.1): `tools/google_calendar.py:557` and `:610`
    (`calendar_create_event`, `calendar_delete_event`), `tools/taint.py:82` `spoken_in_context`,
    `tools/calendar_undo.py:244` `CalendarRestorer`, `activity/words.py:74` `NOTE_WRITE` (G15: no Undo
    for a created event), `offline/rules.py:133` "appointments?" (G16: No-AI lists today's events).
20. **Measured for the estimates.** Cards whose cited files changed: R6.2 **8**, R13 **34**, R13.1 **25**
    (`git diff --name-only` between the merges against each card's "Where in the code"). Python source
    by the standard library's `tokenize` (909 files): **124,475** code, **18,290** docstring, **2,785**
    comment-only, **27,272** blank lines. Tracked files 2,766; top-level functions and classes in
    `src/` 6,665; a path-and-symbol index of them is 383 KB of JSON (59 KB gzipped).

**Phase A facts corrected here.**

| Phase A said (15 Nov, on `9a8392b`) | On `47ee8fc` | Where it matters |
|---|---|---|
| One release 7.98 MB; book.json 182,037; source.zip 7,800,117; 73 left out; 2,277 files, 22.4 MB raw | **10.0 MB**; 198,076; 9,807,662; **97**; 2,670 files, 27.3 MB raw | Storage, D12 |
| +0.63 MB a feature release; the 15 MiB zip cap in ≈ 12 releases | R13 and R13.1 added ≈ 1 MB each: the cap is ≈ **6 feature releases** away | R6.3.1 de-duplication (G14 is nearer) |
| 3 kept 23.9 MB, at seal time 31.9 MB | ≈ 30 MB, ≈ 40 MB | Storage |
| 68 cards C01–C68; 17 modules | **73 cards C01–C73; 18 modules** (Wardrobe & Try-on: C69–C73) | Pages, D3 |
| 65 packages; 90 console modules; 30 outside services; 106 collections | **66; 104; 31; 120** | Fact pack |
| 155 settings | **179** | Fact pack |
| Scenes 1–11: 56 beats, 6,231 characters, 1,084 words; "176,907 lines" in scene 1 | 56 beats, **6,036** characters, **1,047** words; "206,413 lines" | Tour, timer |
| Python 107,710 code, 15,302 docstring, 2,446 comment, 23,028 blank (772 files) | **124,475; 18,290; 2,785; 27,272 (909 files)** | LOC fact |
| ≈ 135 pages (68 + 22 + 30 + 15) | **≈ 152** (73 cards + 18 modules + 22 screens + 31 services + 8 chapters) | Estimates |
| Changed cards a feature release 7–44 | R6.2 8, R13 34, R13.1 25 | Estimates |
| First write ₹711 / ₹1,027 / ₹1,418 (incl. the AI tour) | **₹766 / ₹1,122 / ₹1,562** (no tour) | Cost |
| `cloudrun.sh:149` key, `:533` secrets, `:520` prod env, `:542–543` CPU and memory | `:158`, `:614`, `:600`, `:623–624` | Sources |
| "Unverified whether the router has a no-fallback switch" | `allow_degrade` exists; no laptop switch; production LLM timeout 20 s | D5 |
| The writer never reads `.claude/**` | `.claude/**` is inside `source.zip` | D4 |
| Gemini's balanced model (not named) | `gemini-3.8-flash` (`config.py:143`) | Trial |
| §6 G2, G3, G4, G5, G6, G7, G8, G9, G10, G14 | still open; G11, G12, G13 closed by R6.2; G1 fixed by R6.2 | D10, R6.3.1 |
| ₹95.24 a dollar (`config.usd_inr_rate`) | unchanged (`billing/fx.py:33`, `config.py:359`, `gen/costs.py:28`) | Cost |

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
