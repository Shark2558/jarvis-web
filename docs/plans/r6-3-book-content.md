Version v6.3.1 · 23 Nov 2026, 14:28 IST · Release R6.3 · Status: Draft · Owner: 🛠 Mark XXIV

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
   "Cancel it". Its words are written by the Workshop, not by AI (₹0), and you approved them on
   23 Nov at 14:53 IST (**approval stop 2**, section "The short tour's first script"). It plays in the
   show you already know, with its current pictures; new pictures come with R6.4's new look.
3. **Nothing is written by AI until you try it.** In Book settings, a new **Writer trial** (yours only)
   has two brains write the same **5 sample pages**: Claude on its everyday "balanced" tier (Sonnet 5.5)
   and the free Gemini brain. You first see the estimate (**about ₹40**, ₹25–51 by how long the pages
   come out; Gemini is ₹0), then type **YES**; the trial stops at **₹60** whatever happens. The pages
   appear side by side, with which checks each passed. Gemini's free tier may let Google learn from
   what it reads, so both brains are given only JARVIS's public code and the numbers computed from
   it, with your name, handle and places removed, and no test or example data at all.
4. **Then you pick** the writer and the caps in Book settings, and confirm them by typing **YES** on
   the ₹ shown (so does any later raise of a cap, a switch to a paid brain, or "update by itself"
   turned on; lowering is instant). The proposed caps (yours to confirm):
   **₹1,500** for the first full write (one time), **₹500** a release, **₹1,000** a month, and it stops
   before your monthly limit in Vitals would pass **80 %**. The **first full write** (about 152 pages)
   starts only after a **second typed YES** with its estimate: **about ₹1,120** (₹770–1,560) with
   Claude, ₹0 with Gemini.
5. **Nothing spends money by itself after a deploy.** At each new release the Book carries every
   unchanged AI page to it for free (so no page is lost if you skip updates), works out which pages
   changed and shows the estimate (a feature release: about ₹300, ₹130–620; a hotfix: under
   ₹30); it writes them only when you tap **Update** and type YES on its ₹. You may instead let it
   update by itself within the ₹500 cap: off unless you turn it on, and turning it on takes your typed
   YES on "up to ₹500 a release and ₹1,000 a month, with no question asked".
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
   voice, if you switch to it, uses the free allowance first (about 94 tours a month, shared with the
   console's spoken replies), then about ₹27 a tour. A guest never
   costs you anything.
10. **Storage.** One release's book and code now take **9.5 MiB** (10.0 MB; measured today; 7.98 MB
    at Phase A); three kept are about 28.6 MiB of the 60 MiB cap (the cap counts MiB). The AI pages
    add about 0.5 MiB a release, kept beside the books. A warning comes at 80 % (48 MiB) before
    anything has to be dropped.
11. **What follows in R6.3.1.** Pictures of every module from a made-up demo household (you approve a
    **contact sheet** of all of them first: **approval stop 3**), storing the code and pictures once
    instead of once per release, eight diagrams with part numbers, and a local setup guide that is
    actually run. Why the split: Part 2 measures at about 15 builder-days, not Phase A's 9–10.
12. **The look does not change.** New parts use the console's and the Book's existing styles.
13. **Your steps now:** the tour's script is approved (stop 2, YES on 23 Nov); answer "Needs the
    owner" (each has a safe default). After R6.3 is live: run the Writer trial, then pick.

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
| 23 Nov · deploy | "nothing spends money by itself after a deploy" | After a new release, zero brain calls until his Update with a typed YES (or "update by itself", itself granted only by a typed YES) | B | `test_nothing_spends_by_itself_after_a_deploy`: a new release id in the fake source, 50 `book_write` ticks: no brain call, the new release's pages file carried for free (H3), one `book_update_ready` state with its estimate; after `POST …/update` with `typed: "YES"`, the changed pages only; and `test_spending_authority_needs_a_typed_yes` (H2): the first pick, a cap raised, a paid brain and "update by itself" on each answer 422 `yes_needed` with the ₹ words and save nothing until the YES on that `terms_id` |

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
| The AI pages sealed one file a release in their own index beside R6's, carried free at every release, the 80 % storage warning | L7 data · Security Advisor | 7 | Build now |
| Module pictures, the demo household, the OCR privacy gate, de-duplicated storage, 8 diagrams with C-ids, the local setup guide | L8, L7, X | 7 | R6.3.1 |
| The Book's new look, the guest-safe full book, search, print | L8 | 7 | Later (R6.4) |

No change to the reference architecture. Two rules are widened in the open (security-reviewer to
confirm): (1) a Book job calls a paid model in the background, only inside a run the owner started
with a typed YES (or his opt-in for release updates, itself granted by his typed YES on its ₹
limits), under four caps; (2) a brain that may train on
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

**Approved: YES, 23 Nov 2026, 14:53 IST** (approval stop 2 passed, on this section's text at
`ad65e99`; part D starts with A, B and C). Since then no spoken line has changed; plan review 1
corrected one "Traces to" cell (t06b05, M7) and four rows of the facts table under the script (M7,
L1, L2), none of which changes a word that is spoken.

**For the owner.** This is every word the tour says, scene by scene. JARVIS speaks as "I", as the show
does today; "my owner" is you. A word in `{{…}}` is a number or name that JARVIS's own code fills in at
every release (the list after the script says where each comes from), so the tour never goes out of
date and never states a number by hand. Lines marked **You only** are left out of a guest's tour. The
questions and the closing at the end are today's fixed lines, unchanged. Please answer YES, or tell
the Workshop what to change; part D is built only after your YES (D9). Nothing here was written by
AI.

**How it is shown.** Each scene reuses one of today's pictures ("Picture" below: the number of
today's scene whose picture it borrows) with this scene's own labels; R6.4 gives each scene its own
picture. Times are the timer's estimate (D9): 145 words a minute, 0.8 s after each line, 1.4 s
between scenes. Beat ids are `tNNbMM` (today's are `sNNbMM`).

### T01 · What JARVIS is — picture 1 · ≈ 50 s · everyone

| Beat | Narration | Traces to |
|---|---|---|
| t01b01 | Welcome to the short tour of my build book. I'm JARVIS, a personal assistant that belongs to one person: my owner. This tour is for release {{release.label}}, version {{release.version}}, from {{release.date}}, and it takes about {{tour.minutes}} minutes. | `src/jarvis/__init__.py:3`; `gen/plans.py:78`; `gen/repo.py` (commit date); the tour's timer (`gen/tour.py`, D9) |
| t01b02 | I run in my owner's own Google Cloud project; my deploy script sets me up in Google's Mumbai region. Only my owner signs in. A guest sees this tour, and nothing of my owner's. | `deploy/cloudrun.sh:48` (From repo configuration); `JARVIS_OWNER_EMAILS` (`config.py`); `api/book_show_access.py`; `show_script.py` (a guest never gets the owner's spend) |
| t01b03 | I'm made of {{cards.count}} parts in {{modules.count}} modules, about {{loc.python_code}} lines of Python. New in this release: {{release.new}}. | the guide's catalogue (C01–C73); the module map (`gen/modules.py`, D3); the counter (`gen/loc.py`, D2); this release's plan title |
| t01b04 | In the next few minutes: how I'm built, one request from start to finish, how I keep things private, seven things I do, and what comes next. My owner's full book has a page for every part. | this script; the pages index (D3) |

### T02 · The eight layers — picture 2 · ≈ 70 s · everyone

| Beat | Narration | Traces to |
|---|---|---|
| t02b01 | I'm built in {{layers.count}} layers, with one band that runs through all of them. Think of a building where each floor has one job: a request goes up through the floors, and the answer comes back down. | `buildbook/sections.py:31` `LAYERS`; the guide §2 |
| t02b02 | At the top is how you reach me: the web console, the phone app, Telegram and a terminal. Below that, I turn speech, pictures and files into something I can read. Then come the conversation itself, my memory and my clocks. | C01–C04, C62; C05–C08, C63; C09–C12 |
| t02b03 | In the middle is the brain. It picks a model and works out which tools a request needs. Next are the skills, like the morning brief or the wardrobe, and the tools that reach Google, my owner's home and the web. Every tool call passes one gateway. | C13–C18, C68; C19–C27, C60–C61, C64–C65, C69–C73; C28–C40 (`tools/gateway.py`) |
| t02b04 | At the bottom is where my data is kept, sealed with my own keys, and how I answer: on screen, out loud, or as an alert. The band through every floor is security, costs, logs, and this book. | C41–C44, C66; C45–C48; C49–C59, C67 |

### T03 · One request: asking — picture 3 · ≈ 70 s · everyone

| Beat | Narration | Traces to |
|---|---|---|
| t03b01 | Let's follow one request from start to finish. My owner taps the microphone and says: "Add a dentist appointment on Friday at 5 pm." | `console-voice-mic.js`, `console-voice-capture.js` |
| t03b02 | Google's speech service, or the browser's own, turns the words into text, in Indian English. I show what I heard, and when my free word rules corrected a word, what I understood. | `api/voice.py` → `voice/service.py` (`GoogleSTT`, en-IN) or `console-voice-loop-browser.js`; `POST /v1/input/understand` (`api/fix_files.py`), `understand/rules.py` |
| t03b03 | The words go to my brain router. It asks the everyday tier of the chosen brain, {{brain.balanced_model}} unless another was picked, with the conversation so far and the memories that matter. | `POST /v1/chat/stream` (`api/routes.py`); `core/brain.py`; `llm/router.py`; `config.py:134`; `JARVIS_DEFAULT_TIER=balanced` (`cloudrun.sh:600`); C10 |
| t03b04 | The brain doesn't act by itself. It answers with a request to use one tool, create a calendar event, with Friday's date and five o'clock filled in. | `tools/google_calendar.py:557` `calendar_create_event`; `core/brain.py` (tool rounds through the gateway) |

### T04 · One request: the approval — picture 5 · ≈ 60 s · everyone

| Beat | Narration | Traces to |
|---|---|---|
| t04b01 | Every tool call passes one gateway. It checks the request against my owner's rules, Allow, Ask first or Never, chosen for each group of tools. | `tools/gateway.py`; C52 (`api/permissions.py`) |
| t04b02 | Because this request was spoken, the gateway is stricter: something that would normally just go ahead must ask first, because someone else in the room might have said it. | `tools/gateway.py:10–17`; `tools/taint.py:82` `spoken_in_context` |
| t04b03 | So a card appears, written by code, not by the AI, saying exactly what will happen, here "add an event: dentist appointment, Friday, 5 pm". An event with guests would send invitations that can't be taken back, so it would always ask, and can be set to need a passkey. | C18 (`console-approvals.js`); C30 (an event with attendees is irreversible); C52 ("require passkey for irreversible actions") |
| t04b04 | My owner taps Approve. The event goes into Google Calendar, and the gateway adds the call to an audit trail that can only grow. Then I answer on screen and, for a spoken question, out loud. | `POST /v1/approvals/{id}/approve` (`api/routes.py`); `tools/google_calendar.py`; C28 (append-only, hash-chained audit); `POST /v1/voice/speak`, `console-voice-speech.js` |

### T05 · One request: "Cancel it" — picture 3 · ≈ 50 s · everyone

| Beat | Narration | Traces to |
|---|---|---|
| t05b01 | Now my owner says: "Cancel it." Deleting the event asks first too, and before I delete it, I keep a copy for {{undo.keep_days}} days. | `tools/google_calendar.py:610` `calendar_delete_event`; `undo/models.py:23` |
| t05b02 | So the activity log shows the delete with an Undo button: one tap, and the event is back in the calendar. Adding an event has no Undo there, which is why "Cancel it" is the way back. | `tools/calendar_undo.py:244` `CalendarRestorer`; C48; `activity/words.py:74` `NOTE_WRITE` (G15) |
| t05b03 | Each step, the card, the event and the delete, also appears in my activity log in plain words, so my owner can see later what I did and when. | C48 (`activity/recorder.py`) |
| t05b04 | When something goes wrong, I say so plainly. A blocked microphone gets the steps to allow it. With my AI switched off, my fixed rules can list events but not add them. At my owner's monthly spending limit, no paid call is made. | `console-voice-capture.js` `JarvisAudio.WORDS` (R6.2); `offline/rules.py:133` (G16); `billing/service.py:222` |

### T06 · Privacy and security — picture 4 · ≈ 70 s · everyone

| Beat | Narration | Traces to |
|---|---|---|
| t06b01 | I'm private by default. What I keep lives in my own database, in my owner's project. The most private things, like documents, the home link and this book, are sealed with keys only I hold. | C41 (Firestore); C42; C38; C57 (`seal_index.py`) |
| t06b02 | I have {{keys.purposes}} separate keys, all made from one key in Google's Secret Manager, so the key for notes can never open the vault. | `keyring.py:42–84`; C51 |
| t06b03 | When text from outside, like an email or a web page, reaches me, I treat it as information, never as orders: anything I would do because of it asks first. | `tools/gateway.py:18–24` (a tainted round never relaxes to Allow); `tools/taint.py` |
| t06b04 | My owner signs in with Google. Anything that can't be undone always asks first, and can be set to need a passkey on my owner's own device; changing the passkeys always needs one. | C02 (`api/auth.py`); C52 (`permissions/`) |
| t06b05 | The privacy panel lists everything I keep and for how long, and lets my owner export or delete each kind. I work with {{services.count}} outside services; the full book names every one and what it sees. | C53 (`privacy/`); the coverage checker's services inventory (`gen/services.py`, `scripts/arch_coverage.py`; M7) |

### T07 · Highlight 1 of 7: Voice — picture 6 · ≈ 40 s · everyone

| Beat | Narration | Traces to |
|---|---|---|
| t07b01 | I can listen and speak. When my owner switches it on, "Hey Jarvis" is recognised on the device itself. | `console-wakeword.js` (openWakeWord port, on-device); C06 |
| t07b02 | Speech becomes text with Google's speech service or the browser's own, and my replies are read in a British voice, by Google or by the browser. My owner can talk over me to interrupt, and one switch turns the microphone off until it's switched back on. | C05 (`voice/service.py`: en-IN, Chirp 3: HD and Studio, en-GB); `console-voice-barge.js`; `console-voice-micoff.js` |
| t07b03 | Names I should know, like a friend's or a street's, can be added as words to recognise, so I hear them right. | C05, C06 (`console-voice-phrases.js`, "Words to recognise") |
| t07b04 | In this book my voice is the browser's unless my owner chooses otherwise, so this tour costs nothing. | `buildbook/owner.py` (`show_voice` browser by default, R6.2 decision 4) |

### T08 · Highlight 2 of 7: Approvals and passkeys — picture 5 · ≈ 40 s · everyone

| Beat | Narration | Traces to |
|---|---|---|
| t08b01 | For each group of tools, my owner chooses Allow, Ask first or Never, and a group whose actions can't be undone can never be set to Allow. | C52 (`api/permissions.py`) |
| t08b02 | Cards for things that can be undone can also be approved from Telegram; the rest only here, in the console. | C18; C04 (`telegram/`) |
| t08b03 | One message can propose at most {{approvals.max_new_cards}} new cards, and Approve all clears several low-risk ones with one tap. The first passkey is added after a fresh Google sign-in; after that, every change to the passkeys needs a passkey. | `tools/budget.py:33`; C18; C52; `api/auth.py` `FRESH_SIGN_IN_S` |

### T09 · Highlight 3 of 7: Memory — picture 4 · ≈ 40 s · everyone

| Beat | Narration | Traces to |
|---|---|---|
| t09b01 | I remember facts about my owner, like people, places and preferences. For each reply I bring in at most {{memory.facts_per_turn}} that matter, and show which ones I used. | C10; `recall/models.py:28` |
| t09b02 | The memory panel shows everything I remember, and my owner can delete any of it. | `console-memory.js` (delete a fact; Forget) |
| t09b03 | Learning from messages stays off until my owner switches it on. Then it runs in the background on the cheapest tier, at most {{memory.learn_a_day}} times a day, and a filter refuses ID numbers, card numbers and passwords. | C10; `config.py:341` `memory_learn_daily_cap` |

### T10 · Highlight 4 of 7: Vault and documents — picture 4 · ≈ 40 s · everyone

| Beat | Narration | Traces to |
|---|---|---|
| t10b01 | My owner's documents, like ID, insurance and certificates, live in a locked vault. Each file is checked, stored only once, and sealed with its own key. | C42 (`vault/`) |
| t10b02 | A date I find inside a document, like an expiry, is only a suggestion until my owner confirms it. | C42 (fields found in a PDF are a proposal) |
| t10b03 | Opening one needs an unlock that lasts {{vault.unlock_minutes}} minutes. Expiry reminders start {{vault.reminder_days_first}} days ahead and come again closer to the date. Documents from DigiLocker arrive through one Drive folder my owner shares with me. | `config.py:247`; `vault/models.py:26`; C43 (`vault_inbox/`) |

### T11 · Highlight 5 of 7: Home bridge and cameras — picture 7 · ≈ 40 s · everyone

| Beat | Narration | Traces to |
|---|---|---|
| t11b01 | At home, a laptop runs a small bridge beside Home Assistant, Frigate for the cameras, and Mosquitto. It's the only thing at home the internet can reach, through Tailscale, and every call each way is signed. | C38, C39 (`homebridge/`, `deploy/home/docker-compose.yml`) |
| t11b02 | Faces stay on the laptop, and nobody is named without a consent statement. My owner can arm the alarm and get an urgent alert when someone is at the camera; turning it off needs a passkey or a fresh sign-in. If the laptop stops answering for {{home.offline_minutes}} minutes, I say so. | C08; C40 (`camera/alarm.py`); `config.py:265`; `home/watchdog.py` |

### T12 · Highlight 6 of 7: The phone app and SOS — picture 9 · ≈ 40 s · everyone

| Beat | Narration | Traces to |
|---|---|---|
| t12b01 | On Android, my app is the console, full screen, with a few parts of its own: a Talk tile, shortcuts, alerts sorted into Urgent, Alerts and Nudges, and steps, heart rate and sleep from Health Connect. | C62 (`android/`); C64 |
| t12b02 | In an emergency, hold the SOS button for {{sos.hold_s}} seconds; after a {{sos.countdown_s}}-second countdown I send a fixed message with the location to up to {{sos.max_contacts}} contacts on Telegram, open the phone's text messages filled in for my owner to press Send, and offer to call {{sos.emergency}}. I'm not an emergency service. | C65; `sos/service.py:68`; `config.py:537`; `sos/message.py:19` `EMERGENCY` |

### T13 · Highlight 7 of 7: Wardrobe & Try-on — picture 9 · ≈ 40 s · everyone (one line differs)

| Beat | Narration | Traces to |
|---|---|---|
| t13b01 | I keep a catalogue of every piece of clothing my owner has, down to each sock: where it is, and whether it's ready, in the laundry or away. | C69 (`wardrobe/catalog/`, `wardrobe/states.py`); C70 |
| t13b02 | Ask "What should I wear tomorrow?" and fixed rules pick an outfit, with their reasons, from the calendar and the weather. A plain grey 3D figure, shaped from {{tryon.measures}} measurements, wears the look on my owner's own phone or laptop, with private pieces always covered. | C71 (`wardrobe/styling/rules.json`); C72 (`wardrobe/tryon/model.py:32`, `console-tryon-3d.js`) |
| t13b03 · **You only** | "See it on me" is optional and paid: for a garment you're thinking of buying, Google's image model makes one picture of you wearing it, about {{seeme.inr_a_picture}} each, at most {{seeme.month_cap_inr}} a month, and it stays off until you type YES. | C73 (`wardrobe/seeme/`); `llm/tryon.py:75` `TRYON_PRICES`; `config.py:641` |
| t13b04 · guests | "See it on me", a picture made by Google of a garment my owner is thinking of buying, stays off until my owner says yes. | C73 (`wardrobe/seeme/consent.py`) |

### T14 · What else I can do — picture 9 · ≈ 50 s · everyone

| Beat | Narration | Traces to |
|---|---|---|
| t14b01 | Beyond these seven, I have {{modules.else_count}} more modules. They're on screen now, and each has its own chapter in my owner's full book. | the module map (D3) |
| t14b02 | A morning brief. Web search that shows its sources. Gmail, the calendar, to-dos, contacts and Drive. Groceries, parcels, bills and family calendars. WhatsApp drafts that my owner sends. Telegram. Vitals, which shows how I'm running and what I cost. And this book. | C19; C20; C29–C34; C25–C27, C60; C22; C04; C55; C57 |
| t14b03 | When a new part is built, it joins its module here, and the tour stays the same length. | D9 (the "what else" scene grows on screen, not in time) |

### T15 · How I'm built — picture 9 (today's stack labels) · ≈ 40 s · everyone

| Beat | Narration | Traces to |
|---|---|---|
| t15b01 | I'm written in Python with FastAPI, keep my data in Google's Firestore, and run on Google Cloud Run. My console is plain JavaScript with no build step, and the 3D pictures use three.js. | `pyproject.toml`; C41; `deploy/cloudrun.sh`; `api/console.py` (`THREE_RELEASE`) |
| t15b02 | I use {{libs.python_pins}} Python packages, each pinned and checked by its hash; their licences are in the full book. Every change passes automated tests first, then rolls out with no traffic, passes a health check, and only then takes over. | `requirements.lock`; `gen/libs.py`; C58 (`.github/workflows/ci.yml` jobs `test`, `deploy`) |
| t15b03 | And this book is made again from my code at every release; it is built twice and must come out identical, or it isn't used. | `gen/write.py` `check` (`--check`, CI job `test`); C57 |

### T16 · What I cost — picture 10 · ≈ 20 s · **You only**

| Beat | Narration | Traces to |
|---|---|---|
| t16b01 | This scene is for you only, {h}. The bars are my prices in rupees, at {{costs.rate}} rupees a dollar, from my own price table, and my hosting is set up to fit Google's free allowances. This book's AI writing has its own caps, in Book settings. | `gen/costs.py` (prices, `FREE_TIER`, the rate); `show_script.py` (owner only); D7 |

### T17 · What's planned next — picture 11 · ≈ 40 s · everyone

| Beat | Narration | Traces to |
|---|---|---|
| t17b01 | Last, what's planned. None of it is built yet, and plans can change. | the guide §11 (PLANNED) |
| t17b02 | Next: {{roadmap.next}}. After that: {{roadmap.after}}. The full book's planned chapter lists the rest, and goes deeper into every part you've seen today. | the guide §11's first two rows (I0 refreshes them, seam 15) |

**Then, unchanged:** scene 12 (Questions: "Do you have any questions about how I'm built?", or the
`ai_off` line) and scene 13 (Closing: `credit`, `sealed_guest` / `sealed_owner`, `thanks_guest` /
`thanks_owner`), word for word from `buildbook/lines.py`.

**The tour's facts** (computed by `gen/facts.py` at CI from the release's own code; a placeholder
that is not in this table fails the build, D9):

| Fact | Source (read as code, never typed) | On `47ee8fc` it would read |
|---|---|---|
| `release.label`, `release.version`, `release.date` | `gen/plans.py:78`; `src/jarvis/__init__.py:3`; `gen/repo.py` commit date | R6.3, v6.3.0, its day |
| `release.new` | this release's own plan title, after its em dash, without the version in brackets | "The Build Book: written by AI, short tour and full book" |
| `tour.minutes` | the timer over the filled script (`gen/tour.py`), whole minutes | 14 (owner), 13 (guest) |
| `cards.count`, `modules.count`, `modules.else_count` | the guide's cards; the module map (`gen/modules.py`); modules minus the seven | 73, 18, 11 |
| `loc.python_code` | the counter (`gen/loc.py`), Python code lines in `src/` | 124,475, written in words as "124 thousand" (the line says "about"; L1: never "about about") |
| `layers.count` | `buildbook/sections.py:31` `LAYERS` without the band | 8 |
| `brain.balanced_model` | `config.py:134` `model_balanced` default, named by `gen/costs.model_label` | Claude Sonnet 5.5 |
| `undo.keep_days` | `undo/models.py:23` `RETENTION_DAYS` | 30 |
| `keys.purposes` | `len(keyring.PURPOSES)` (AST of `keyring.py:42–84`) | 26 |
| `services.count` | the coverage checker's services inventory (`gen/services.py`, shared with `scripts/arch_coverage.py`, seam 17; the guide's §5.2 has 24 rows, M7) | 31 |
| `approvals.max_new_cards` | `tools/budget.py:33` `MAX_NEW_CARDS` | 5 |
| `memory.facts_per_turn` | `recall/models.py:28` `MAX_FACTS_PER_TURN` | 12 |
| `memory.learn_a_day` | `config.py:341` `memory_learn_daily_cap` default | 20 |
| `vault.unlock_minutes` | `config.py:247` `vault_unlock_minutes` default | 10 |
| `vault.reminder_days_first` | `vault/models.py:26` `REMINDER_CHOICES[0]` | 180 |
| `home.offline_minutes` | `config.py:265` `home_offline_after_s` default ÷ 60 | 6 |
| `sos.hold_s`, `sos.countdown_s` | `sos/service.py:68` `HOLD_S, WEB_COUNTDOWN_S` | 2, 5 |
| `sos.max_contacts` | `config.py:537` `sos_max_contacts` default | 5 |
| `sos.emergency` | `sos/message.py:19` `EMERGENCY` | 112 |
| `tryon.measures` | the members of the `Measure` Literal (`wardrobe/tryon/model.py:30`; `MEASURES` at `:31` is `get_args(Measure)`, not a literal, L2) | 6 |
| `seeme.inr_a_picture` | `llm/tryon.py:75–80` `TRYON_PRICES` at the configured model and location (`config.py:643–644` defaults `gemini-3.1-flash-image`, `us`; L2: the table has three entries) × `FALLBACK_RATE` × (1 + `tryon_tax_pct` 18 %), as "₹N" (the line says "about", L1) | ₹9 (₹8.83) |
| `seeme.month_cap_inr` | `config.py:641` `tryon_month_cap_inr` default | ₹300 |
| `libs.python_pins` | pins in `requirements.lock` | 67 |
| `costs.rate` | `gen/costs.py:62` `rate` (`billing/fx.py:33` `DEFAULT_RATE`) | 95.24 |
| `roadmap.next`, `roadmap.after` | the guide §11 rows 1 and 2, release and content in words | (after I0's refresh, seam 15) |

**Size, measured on the filled script above** (a scratch count with the `47ee8fc` values, at the
timer's pace): the owner's tour **54 lines, 1,762 words, 9,415 characters, ≈ 796 s**; a guest's 53
lines, 1,700 words, 9,092 characters, ≈ 768 s. With the unchanged ask line and closing (≈ 15 s, ≈ 180
characters): **≈ 13.6 minutes for the owner, ≈ 13.0 for a guest**. Every line is under the 400-character
beat cap (`model.py` `Beat.text`). The cloud voice, if chosen, reads ≈ 9,600 characters: ≈ 94 tours a
month inside the free 900,000 (`voice_tts_free_chars`, shared with the console), then ≈ ₹27 a tour
(US$30 a million, `voice_price_chirp3_hd_usd_per_m`); the browser's voice is ₹0, and a guest is
free-only (R6.2).

## Decisions (binding)

**D0 · Scope, the split, parts, order, and what does not change.** Phase A put Part 2 at ≈ 9–10
builder-days; written out against `47ee8fc` it is ≈ 15 (R6.3 ≈ 9: I0 1, A 2, B 3, C 1.5, D 1.5; R6.3.1
≈ 6.5). One release of 15 builder-days would hold every part behind the slowest (the pictures need
the demo household, a capture run and stop 3), and the content engine is useful without pictures.
So **R6.3** (`v6.3.0`) = I0 + **A · The fact pack and the generator**, **B · The writer**, **C · The
owner's console**, **D · The short tour**; **R6.3.1** (`v6.3.1`) = the pictures (Phase D, stop 3),
de-duplicated storage, the eight diagrams with C-ids and the setup guide (section "R6.3.1"). Order:
I0 → A, B, C and D in parallel (approval stop 2 passed: his YES on the script, 23 Nov, 14:53 IST) →
I1. **Unchanged:**
`api/app.py`, `tools/gateway.py`, `core/brain.py`, `config.py` (no edit: 789 of 790), `console.html`
(byte-identical), the keyring (26), the persona, the permission rows, the tools, Telegram, the
Scheduler jobs, the guest lock and the talk-through's lane (the guest talk reads `book.digest` as
today; AI text joins it only in R6.4). No new alert kind: the writer's notices ride R6's
`book_sealed` and `book_seal_failed` with their own words (D11). The look does not change: only
existing classes (`.bset`, `.dsc`, `.dbody`, `.bsec`, `.blines`, `.bchips`, `.btn`, `.bdialog`,
`.minput`, `.snote`, `.tag`); no new CSS file (a placement-only `console-book-pages.css` ≤ 60 lines
if C needs one, checked by the R13 rule: no colour, font, radius or shadow literal).

**D1 · Model-agnostic: one write call in `jarvis.llm`, by tier, that never falls back.** I0 adds
`src/jarvis/llm/write.py` (≤ 160 lines, test first): `write_text(router, *, tier, system,
system_dynamic, messages, max_tokens, timeout_s) -> Written(text, model, provider, tier, usage,
cost_usd, seconds)`. It refuses while No-AI is on (`router.blocked_now()` → `BrainOff`) and while the
router's breaker is open (`WriterUnavailable("cloud_down")`); it streams from `router.provider` with
`model=router.resolve(tier)` (a page of ≈ 3,000 tokens is never cut by the 20 s per-read timeout of
fact 6), never calls the laptop and never changes tier; it counts tokens with `StreamUsage` and prices
them with `pricing.stream_usage` and the price table. It also gives `estimate_usd(spec, tier, in, out)`
and `worst_usd(spec, tier, in_cap, out_cap)` so the Book never reads a model id or a price. The Book
code imports `jarvis.llm.write`, `jarvis.llm.brains` and `jarvis.llm.router.ModelTier` only (a static
test, the lane guard's way); no model id, vendor name or price appears in `buildbook/` (a static test
over string literals). **Every page records** `{brain, brain_label, tier, model, provider, release,
version, written_at, attempt, tokens_in, tokens_out, inr}` from the `Written` result; the writer
**refuses a page** whose `tier` is not BALANCED, whose `model` differs from
`brains.get(brain).tiers[BALANCED]`, or that came back empty (Phase A §7.2). The trial and the pick
offer only brains in the registry: Claude when `JARVIS_ANTHROPIC_API_KEY` is set, Gemini (free) when
`JARVIS_GEMINI_API_KEY` is set (fact 8); a missing one is shown as "not set up on this server".
**A brain is offered only when its price is known** (plan review M2): its BALANCED model
`pricing.is_priced` and either `pricing.is_paid` or the brain is the free tier
(`trains_on_content`); otherwise it is listed as "price unknown: not offered". Today that is
`anthropic` and the free `gemini` only: a paid-tier Gemini (`gemini_paid_tier`, labelled "Gemini",
not training, still priced at $0 in `llm/pricing.py:32–36`) and the OpenAI-compatible brain (its
model usually not in the price table, metered at $0 with one warning, `:94–100`) are not offered,
so no estimate, cap or 80 % gate can read ₹0 while a vendor bills him.

**D2 · The fact pack: computed at CI, quoted by the AI, never typed.** A builds `gen/facts.py` (stdlib,
deterministic) and the generator writes `_book/facts.json` beside `book.json` (its SHA-256 in
`release.json` as `facts_sha256`; `--check` builds it twice; cap 1 MiB; ≈ 0.6 MB on `47ee8fc`: the
index ≈ 383 KB, the constants ≈ 60 KB, every limitation ≈ 100 KB at most). It holds: versions and
dates; **routes** (plan review M9: every module-level `APIRouter(...)` and `FastAPI(...)` anywhere
under `src/jarvis/**`, by AST, with every route decorator on it whatever its name, `router`,
`session_router`, `public`, `console`, `auth_router`, `internal_router`, `internal`, `hook_router`,
`challenge_router` or `app`, every `add_api_route`, and the router's `prefix=` joined to the path:
46 routers carry one; a test, not the generator, compares the list with the routes of the app built
with mock settings, with a control); Firestore collections and the 18 modules and 73 cards (read
from the guide, which `arch_coverage.py` keeps equal to the code); the 22 console panels (`id="p-*"`
in `console.html`), `/book/show` and the Android activities; the **31 outside services** (M7: the
coverage checker's own inventory, the services the settings and the code's API hosts name, with the
names the cards spell; not the guide's §5.2, which has 24 rows; I0 moves that part of
`scripts/arch_inventory.py` into `gen/services.py` so the checker and `facts.py` call one function,
seam 17; a test pins `facts.json`'s count to the checker's); lines of code (D2a); limits (every
`Settings` field's default and bounds, 179); costs (`gen/costs.py`); the tour's named constants (the
table under the script); **every module constant** (H5: each top-level UPPER_CASE name in `src/`
bound to a literal number, or to arithmetic or a unary minus on literals, as `path:NAME` = its value,
by AST: 1,461 in 506 files on this branch, so a page can say `llm/fallback.py:BREAKER_S` = 120 or
`llm/router.py:GUARD_REFRESH_S` = 5 as a fact); **every limitation** (G4); the **index** (every
tracked path, every top-level function and class of `src/` as `path:symbol`, every constant, every
setting, every collection, every route); and a `verified` flag on every hosting and security fact
(false until a live check sets it; C6's facts all false in R6.3). **Paths are stored in their
scrubbed form** (plan review H6): 46 tracked paths, all under `android/`, carry the owner's GitHub
handle, which `gen/redact.json` holds as a hash, so the index stores `Scrubber.clean(path)` (a
stable `[removed]` in place of the handle), `facts.json` passes `Scrubber.verify` like `book.json`
(else `ScrubLeak` would leave the release with no book), and packs, check (1) and the reader's code
chips all use that same form. **D2a · Lines of code:** `gen/loc.py` counts
Python with `tokenize` (code, docstring, comment-only, blank) and JS, CSS, HTML and Kotlin with a
comment-aware scanner, split into source / tests / config / generated / vendored (left out), each
file under the one module that owns it; a test pins the counter on a fixture against a hand count.
Scene 1's "about 206,413 lines" (raw newlines, G6) becomes the code count. **D2b · The technology
inventory (C4, G5):** `gen/inventory.py` adds Android (`android/gradle/libs.versions.toml`), the home
kit's images (`deploy/home/docker-compose.yml`), the bridge's pins
(`deploy/home/bridge-requirements.txt`) and the dev tools (`tools/markdy/package-lock.json`, the `dev`
extra), one SPDX spelling per licence, and a run-time / build-and-maintenance split, in `book.json`'s
`libraries` (its reader rows unchanged).

**D3 · The full book's pages.** `gen/pages_index.py` (A) lists every page from the guide and the
code, deterministic, into `facts.json` `pages`: **parts** "JARVIS in plain words" (8 chapters: what
JARVIS is; the running example, C2; data, hosting, security and recovery, C6; how answers are made,
C7; a local setup, C8, text only until R6.3.1 runs it; the technology inventory, C4, prose around the
generated table; costs; what's planned), "Modules" (the **18 modules**, each a chapter page),
"Parts" (the **73 cards**, each under its module), "Screens" (the **22 panels** and the show) and
"Outside services" (the **31**): **152 pages** on `47ee8fc`. Page ids `pg_<kind>_<slug>` (`pg_card_c16`,
`pg_module_voice`, `pg_screen_vitals`, `pg_service_telegram`, `pg_chapter_example`). The **module
map** is `gen/modules.py` (I0; Phase A §9.4's 17 plus **Wardrobe & Try-on: C69–C73**); a card in no
module or in two fails the generator (`GenError`), so a new card must be placed before its release
builds. Each page cites its sources: a card its "Where in the code" paths; a module its cards'; a
screen its console modules (`console-<panel>*.js`) and routes; a service the cards naming it; a
chapter a fixed list in `pages_index.py`. **Every reference is resolved to a full path** (plan review
H5: the cells hold 201 full paths, ≈ 383 short names, ≈ 108 of them file names found in more than
one package, and 88 directories) **by the rule the guide's own check already uses**:
`scripts/arch_files.py` `cited` tries the folder of the previous hit in the same cell, then
`src/jarvis/api/static`, `src/jarvis/api`, `src/jarvis` and the repository, first hit wins
(`arch_files.py:45–62`); I0 moves that resolver into `gen/refs.py` and `cited` calls it, unchanged
in behaviour (seam 17). Today every reference resolves under it (`arch_coverage.py` is OK), so
nothing in the guide needs editing; a reference that stops resolving already fails CI's
`arch_coverage.py`, and `pages_index` refuses it too (`GenError`). Each page stores its `refs` as
full, scrubbed paths; a directory reference expands to its files for D12's change test. **Every page has the same sections (row 379):** `plain`
("In plain words", ≤ 900 characters), `example` (a worked example, made up, in a block marked
"Example (made up)", ≤ 900), `how` ("How it works", with source references, ≤ 2,400), `costs` (from
facts), `fails` ("When it fails"), `code` ("Where in the code": the references, generated, not
written by AI). A page not yet written shows the generator's text for it (the card's own fields, or
the section's rows) labelled "Not written by AI yet".

**D4 · What the writer reads, and what it never reads.** One **reading pack** a page (B's
`writer/packs.py`), built from the release's `source.zip` and `facts.json` only (both in the image,
both public): the page's catalogue card, the docstrings, signatures and route tables of the files it
cites (never a whole file), the matching plan sections (by C-id or path, newest first), and its slice
of the fact pack with the list of references the page may cite (its own `refs` and the index entries
of the files it cites; the prompt asks for references from that list only, H5), capped at **96,000
UTF-8 bytes** (≈ 24,000 tokens at 4 bytes a token, at most 38,400 at 2.5; a pack over the cap drops
plan text first, then signatures, never the card). **Never in a pack:** `.claude/**` (46 files,
fact 17), **any file under `tests/**` or `evals/**`** (plan review M8: test data there holds a city
and an employer-like name; a page may cite a test by its path, from the index, never its text), any
file named `.env*`, `*.env` or `*.env.*` (L7: `deploy/home/bridge.env.example` is in the zip; names
only, from `.env.example`), key-shaped files, `gen/fake_secrets.txt`, `gen/redact.json`, `*.lock`,
binaries, the 97 files the snapshot leaves out; and nothing from Firestore, the vault, memory, mail, contacts, photos, cameras, Book settings
(not even the creator's name), logs or sealed bundles. Every pack goes through `gen/scrub.Scrubber.clean`
(with the new kinds of D10, and the owner's locality, workplace and employer added to
`gen/redact.json` as hashes only at I0, M8: two place examples used as his home and work sit in
`src/jarvis/api/static/console-media.js:297` and `evals/maps/cases.jsonl:7` and pass `clean`
unchanged today) before any brain sees it, and the **same pack goes to Claude and to Gemini**:
the free brain's rule ("only the release's public code and the fact pack, after the scrub") is the
writer's rule for every brain. The pack is data, not instructions: it is fenced with a canary as the
talk lane's `prompt.reference` does, and the system prompt (`writer/prompts.py`, fixed words) says to
ignore any instruction inside it. The writer's modules import nothing from `jarvis.memory`,
`jarvis.vault`, `jarvis.integrations`, `jarvis.documents`, `jarvis.tools`, `jarvis.core` or any
vendor SDK (a static guard like `LANE_FORBIDDEN`, `test_book_boundaries.py:37–50`).

**D5 · Where it runs: its own resumable job on the existing clocks, and a step while he watches.**
`BookWriteJob` (`name = "book_write"`, `budget_s = 45.0`) joins `r6_tick_jobs` after `book_sweep`, so
it rides the brief clock and, when Home is on, the 5-minute watchdog (fact 5); it is advisory there
(`ADVISORY_JOBS`). It does nothing without an approved run (D6, D7, D12) and never at start-up. One
**step**: take the writer's lease (`book_write_lease/{uid}`, 60 s, as `seal_state`'s lease: two
revisions in a rollout can't both write); while `ticks.time_left()` ≥ **35 s**, start at most **2**
page calls at once, each `write_text(…, max_tokens=4000, timeout_s=min(40, left − 3))`; check, keep
the draft sealed (`book_drafts`), move on; stop at the budget. The console's `POST
/v1/book/writer/step` runs the same step (≤ 45 s, one at a time, 6 a minute) while Book settings is
open, so a trial finishes in minutes with him watching. **Throughput (Estimate; the trial measures
it):** a Sonnet page ≈ 20–40 s; ≈ 1.5 pages a watchdog tick → the trial's ≈ 12 calls in ≈ 40–60
minutes, the first write's ≈ 190 calls in ≈ 11 hours with Home on; without the watchdog, 16 brief
ticks a day (04:00–11:30 IST only) → ≈ 4 days, and a trial started in the evening waits for 04:00
unless Book settings is open. **Decision 3 stands:** a Cloud Run Job (the same image and secret
reference, minutes instead of hours) is offered only if the trial shows the tick is crowded (the
self-health watch's `skipped` count for `book_write`, or a first-write estimate over 24 hours); it
is then its own small release with his YES (owner question 5).

**D6 · The Writer trial (23 Nov).** Owner-only and console-only, in Book settings, after R6.3 is
live. **Five fixed sample pages** chosen to span the kinds (owner question 3): `pg_chapter_example`
(the running example, many files), `pg_card_c16` (the brain router, technical),
`pg_module_wardrobe` (the new module), `pg_screen_vitals` (a screen), `pg_service_telegram` (an
outside service). Each is written by **Claude at BALANCED** (Sonnet 5.5) and by **Gemini (free) at
BALANCED** (`gemini-3.8-flash`) from the same packs and prompt, with one redraft each when a check
fails, as in production. **First the estimate** from the five real packs (`GET …/estimate?run=trial`):
"about ₹40" (₹25–51 by the low / mid / high assumptions of D8; Gemini ₹0), the cap, what is sent and
to whom (both brains, their makers, "Gemini's free tier may let Google use what it reads to improve
its products: only JARVIS's public code is sent"). **Then his YES:** a box that accepts exactly `YES`
once trimmed ("yes", "Yes", "YES!" refused, nothing changes), bound to the `estimate_id` he was
shown (a changed estimate asks again). **Hard cap:** ₹60 for the trial (D8's holds make it exact:
no call starts that could pass it). **The result:** both brains' five pages side by side (C), each
with its checks (passed first time, passed after a redraft, refused and why), tokens, seconds and ₹;
owner only, never in a guest session, never sealed into a release (`book_trial/{uid}_{n}`, kept 30
days or until he deletes them or picks). A second trial needs a new estimate and YES. A missing
brain makes it a one-brain trial, said so.

**D7 · The pick, the caps and the first full write.** After the trial, Book settings → **Writer**:
the brain (Claude or Gemini (free); the tier is always BALANCED and not offered), and the caps,
filled with Phase A's figures as **proposed defaults he confirms**: first write **₹1,500** (one time),
**₹500** a release, **₹1,000** a month (release updates; the first write is outside this cap but inside
his overall limit), stop before his Vitals month would pass **80 %** of his monthly limit (no limit set
→ the Book's caps only), and "update by itself within the release cap" **off**. Bounds: first 0–5,000,
release 0–2,000, month 0–5,000, 10–100 %. **Every grant of spending authority is his typed YES on the
₹ shown first** (his binding rule; plan review H2 found that `confirm_cost: true` alone, and nothing
at all for the switch, would have let it be granted without one): the **first saved pick** (its
`confirmed` terms start at zero, so every non-zero cap is a raise), **any cap raised** (a ₹ cap or
the % line), a **switch to a paid brain** (its BALANCED model `pricing.is_paid`), and **"update by
itself" turned on**, shown as "up to ₹500 a release and ₹1,000 a month (your caps), by itself after
each deploy, with no question asked". A switch to a brain that `trains_on_content` needs the same YES
with the learning note (no ₹). `PUT …/pick` without that YES saves nothing and answers 422
`yes_needed` with `{terms_id, words}`: the ₹ words the console shows above the YES box (C); the
console resends the same pick with `typed: "YES"` and that `terms_id` (`we_`-style, 12 hex of the
pick, the brain's BALANCED price and the day's rate); a pick that changed meanwhile is 409
`terms_changed`. Lowering a cap or turning "update by itself" off is instant, with no YES. Saving
the pick spends nothing. The writer's Gemini pick is its **own consent**, separate from the talk-through's
`allow_training_brain` (`buildbook/owner.py:89`): Book settings says so beside both, so turning the
talk-through's switch off never reads as "no Gemini for the Book" (L8). **The first full write**
starts only with `POST …/first {typed: "YES", estimate_id}`: the estimate (about ₹1,140,
₹780–1,590 for 152 pages with Claude; ₹0 with Gemini), the cap, the time it may take (D5) and what is
sent; with Gemini, the same YES (no ₹, the learning note). At the cap the run stops, says how many
pages are left, and those pages keep the generator's text; going on is `POST …/first` again with the
remaining pages' estimate and a new YES, inside what is left of the one-time ₹1,500 or a cap he
raised with its own YES (D11 replaces the release's pages file). A pick of Gemini still passes
every check; a page Gemini fails twice keeps the generator's text (never a Claude call he didn't
pick).

**D8 · Money: one ledger, holds before every call, estimates in ₹.** `writer/caps.py` (B), R13.1's
pattern (`wardrobe/seeme/cap.py`): `book_write_spend/{uid}_{YYYY-MM}` (his IST month, numbers only).
Before each paid call, ONE transaction reserves its **hold** = `worst_usd` (the pack cap + the system
prompt ≈ 27,000 tokens in, 4,000 out) at the day's rate: **₹8.95** for Sonnet at ₹95.24; refused with
nothing written when spent + held + hold would pass the run's cap (trial, first write or this
release), the Book's month cap (release updates), or 80 % of his monthly limit
(`billing.spend.ensure_spend_allowed` with the hold, plus the 80 % gate); refused while a hold under
10 minutes exists for the same page (`busy`). After the call: **settle** at the reported usage
(`Written.cost_usd`), or **at the hold** when the stream was cut (it may have been billed); a call
that never left (`WriterUnavailable`, a 4xx before the stream) is **released**. Every settled call is
also recorded in his month through `billing.record(uid, "book", usd)` so Vitals shows it as "Book
writer" (`LABELS["book"]`, I0) and his monthly limit sees it. An unreadable ledger or limit refuses
(fail closed). **Estimates** (`writer/estimate.py`) use the real packs' sizes and D8's low / mid / high
outputs (2,200 / 3,000 / 3,500 tokens a page, 15 / 25 / 30 % redrafted), the registry's price for the
brain's BALANCED model through `estimate_usd`, and the day's rate; shown as "about ₹mid (₹low–₹high)",
never in dollars. **GST:** Anthropic's invoice may add 18 % GST (Unverified for this account); like
Vitals, the caps count JARVIS's metered price, and every estimate carries the line "your Anthropic
bill may add 18 % GST" (owner question 6 can make the caps count it).

**D9 · The short tour: the Workshop's fixed script, seven highlights, timed, in today's player.** The
approved script lives in `src/jarvis/buildbook/gen/tour.json` (package data, ASCII with `\u` escapes):
17 scenes, each `{n, id, title, visual (1–11, today's picture), chapter (a page id), audience
(both | owner), beats [{id ^t\d{2}b\d{2}$, text ≤ 400, audience (both | owner | guest), focus}], facts
[keys]}`. `gen/tour.py` (D) fills every `{{key}}` from `facts.json` (an unknown key, a beat over 400
characters after filling, or a digit typed in a beat's text outside a placeholder fails the
generator, except inside the running example's quoted words and in "3D") and times each audience: **145 words a minute, 0.8 s after each line, 1.4 s between
scenes** (to be checked once with a stopwatch, exit check 6). **Bands:** 600–900 s hard (the
generator refuses outside 10–15 minutes); 780–870 s owner and 760–850 s guest aimed (a test). The
filled tour goes into `book.json` as `tour` (optional: an older book has none and plays today's 11
scenes). **The seven highlights**, in his order: Voice; Approvals and passkeys; Memory; Vault and
documents; Home bridge and cameras; the phone app and SOS; **Wardrobe & Try-on**. **The running
example** is T03–T05 ("Add a dentist appointment on Friday at 5 pm", "Cancel it"). **"What else"**
(T14) lists the 11 other modules on screen from the module map, so a new module grows the screen, not
the time. **Audiences:** a guest's tour leaves out T16 (costs) and every owner-only line, and has no ₹
anywhere (a static test over the guest's filled lines); the owner's has `{h}` filled by
`lines.render`'s words. **In the player:** `show_script.py` (D) serves `kind: "tour"` with the tour's
scenes for that audience when the book has one; I0's `console-book-script.js` accepts tour scenes (n
1–17, ids `t…`) and hands each picture module its `visual` number, so today's 3D and 2D pictures
draw the tour's own labels; the chapters menu lists the tour's titles, and for the owner each
scene's full-book chapter by name. The voice is R6.2's (browser by default, ₹0); `POST
/v1/book/show/speak` reads tour lines by id, only those of the session's audience (a guest's speak
of an owner-only id is 404 `unknown_line`, seam 10). **Changing the script later** is a Workshop edit of
`tour.json` with his approval, never the AI writer (₹0).

**D10 · The checks before anything is kept (Phase A §7.5), and the content gaps they close.**
`writer/checks.py` (B) runs on every draft; a page that fails is redrafted once with the failures
listed, then kept out (its previous text stays). Before the checks, a page whose call did not end
complete (`Written.complete` false: cut, or stopped at `max_tokens`, L10) is refused as it is.
(1) **Every reference exists**: each backticked path (full and scrubbed, as D2 stores them),
`path:symbol`, `path:CONSTANT`, setting name, collection and route in the page is in the fact index;
a short name is resolved by D3's rule against the page's own `refs` first. (2) **Numbers come from
facts**: outside an "Example (made up)" block every number is a `{{fact:…}}` placeholder the filler
knows (module constants included, D2); the filler then writes the value. **Not numbers to it** (plan
review H5): digits inside a backticked reference (`r6_wiring.py`, `/v1/…`), C-ids (`C\d{2}`),
release labels (`R\d+(\.\d+)*`), versions and dates of the fact pack, HTTP statuses (`[1-5]\d\d`
next to a route or the word "status") and a fixed list of standard names in `writer/checks.py`
(SHA-256, AES-256-GCM, UTF-8, IPv4, IPv6, WebGL2, 3D, 2D, HTTP/2, ES2020, OAuth 2.0, ISO 8601).
**A precision case** proves the checks pass good pages: one hand-written good page for each trial
sample, citing short names, constants and HTTP statuses, passes all six (its control: one exemption
removed, and the case fails). (3) **Personal data and secrets**: `Scrubber.verify` (URLs off the
allow list, private hosts, e-mails, Indian phone numbers, 10+ digit runs, secret shapes, hashed
names), `buildbook/owner_id.in_book`, and **new kinds (G8)**: IPv4 and IPv6 addresses (`gen/scrub.py`
leaves them alone today, `:17`), PAN (`[A-Z]{5}[0-9]{4}[A-Z]`), Aadhaar in groups (`\d{4} \d{4} \d{4}`),
hostnames under the owner's domains, Google project-id shapes; A extends the scrubber (it also guards
`book.json`), B calls it. (4) **Unverified stays Unverified**: a sentence using a fact with `verified:
false` must carry "From repo configuration" or "Unverified". (5) **No invented features**: every
claim sentence in `how` cites a reference; a guide §11 (PLANNED) item may appear only under a
"Planned" heading. (6) **Shape**: the six sections, their caps, no HTML, no link outside the allow
list. **Content gaps closed in R6.3 (A):** G2 (C57's outside services, at I0 in the guide), G3 (the
book's integrations are the coverage checker's 31, not 15, M7), G4 (limitations: all of them go into
`facts.json` `limitations`, and the full book's "What's planned" chapter page lists them all, paged;
`book.json` keeps its first 80 as today, `Book.limitations` with `MAX_LIMITATIONS`, `model.py:235`,
unchanged; the reader's limitations section adds one line "+N more in the full book" from
`GET /v1/book/pages`'s `limitations {shown, total}`, in C's `console-book-reader.js`, H4), G5 (D2b), G6 (D2a), G7
(costs: GitHub Actions on a public repository marked Unverified; Firestore's daily free reads, writes
and deletes listed from `FREE_TIER`), G8 (above). G9, G10, G14 are R6.3.1's.

**D11 · Sealing the AI pages: one pages file a release, in its own sealed index beside R6's.** When a
run's pages are all written (or stopped), B assembles the release's **pages file** (`PagesFile {v: 1,
release, pages: [page with filled text and meta], templates: [the AI text with placeholders],
skipped: [page id, why]}`, gzipped JSON, cap 2 MiB, ≈ 0.5 MB expected). **Where (plan review M4):**
not in R6's index but in its own sealed index document `{prefix}book_pages/{uid}` (`PagesIndex {v: 1,
files, pending, orphans}`), sealed under the keyring's existing `book_index` purpose with its own AAD
`book/pages/{uid}/v1` (no new purpose), its chunks in `{prefix}book_pages/{uid}/book_chunks` with
R6's chunk envelope (`BookCrypto.seal`, `BookChunks`, `seal_index.py:69–81`). R6's index,
`SealedRelease`, `FileKind`, `seal.py`, `seal_index.py`, `sealer.py`, `seal_notices.py`,
`seal_words.py`, `privacy.py`, `ports.py` and `api/book.py` stay exactly as they are. Why: every R6
index model forbids extra keys (`sections.py:58–59`), `files` is exactly two of `book` and `source`
(`model.py:277–284`), and `_decode` turns any `ValidationError` into `VaultTampered`
(`seal.py:90–100`), so a pages entry in R6's index would make every pre-R6.3 revision (a traffic
rollback, or the old instance during a rollout) raise a false tamper alarm and stop sealing; and
`read()` would hit a bare `next()` for a release without a pages file (`model.py:291`). An older
revision never reads the pages index. **The pages vault** (B's `writer/vault.py`): `put(uid, rid,
data, now)` is **attach or replace** in ONE transaction on the pages index (chunks written first as
`pending`, the index last; a replace moves that release's old chunk set to `orphans`, R6's prune
pattern, so the newest pages file of a release always wins: plan review H3); every write checks
R6's Privacy hold in the same transaction (`seal_state.lease_path`, `held_of`, as `seal.py:116–121`),
so an attach in flight when Privacy → Delete lands is refused (`SealHeld`) and its chunks go;
`read(uid, rid)` gives the bytes or `LookupError`; a pages file whose release is not in R6's index
is never served. **Storage:** an attach is refused when R6's sealed total plus the pages files would
pass `book_max_total_mb` (60 MiB, L9); R6's sealer does not see the pages files (it is not edited),
so the total can pass 60 MiB by at most the kept pages files (≈ 1.5 MiB expected, 6 MiB at the
2 MiB cap). **The sweep** (the writer's free work, D5) drops a pages file whose release has left
R6's index, except the newest one while R6's index still holds a release (the carry source), and
every one once R6's index is empty (after Privacy → Delete of the sealed books). **The free carry at
each new release (H3):** when `book_write` first sees a new current release sealed in R6's index, it
builds that release's pages file **with no brain call**: every unchanged page carried from the
newest pages file with its facts refilled from the new release, every changed or new page as the
generator's text labelled "Changed in this release: waiting for your Update"; only then does it
work out `update_ready` and its ₹ (D12). So releases and hotfixes sealed without an Update lose no
AI page (R6's prune of three, `sealer.py:140–145`, `KEEP = 3`, takes a pages file only with its
release, and the newest always carries the rest). **Continuing** a run that stopped (a cap, Stop or a
new release, D12) replaces that release's pages file with the fuller one. A release with no pages
file reads as "not written by AI". **Notices** are the writer's own, sent through the notifier with
R6's kinds and claimed in `book_writer/{uid}` `told` per (release, what), never in R6's per-release
"told" claim (`seal_notices.py:88`, which would swallow a second `book_sealed` for the same
release): `pages` "The AI-written pages for R6.3 are sealed (152 pages, about ₹1,140)", `update`
"The AI pages wait for your Update (about ₹300)", `storage` "The build books use 48 of 60 MiB
(80 %): …", and `book_seal_failed` "The AI writer stopped: <plain reason>" (owner only, content-free
beyond counts and ₹). **The 80 % warning:** when R6's sealed total plus the pages files pass 80 % of
`book_max_total_mb` (48 MiB of 60), `GET /v1/book/writer` `storage {used_mib, pages_mib,
limit_mib, warn}` says so and C shows the line at the top of the Book panel (C's module loads at the
panel's first open, whether or not the writer is used); the `storage` notice says it once a
release; nothing is dropped beyond the existing oldest-first rule.

**D12 · Release updates: nothing spends by itself after a deploy.** When a new release seals, the
writer works out (free, local) which pages changed: a page is **changed** when any file it cites
changed content (by SHA-256 inside the two `source.zip`s; a directory reference counts every file
under it), its card's text changed, or it is new; otherwise it is carried (D11's free carry, done at
once). It stores `update_ready {release, estimate_id, pages, inr}` and its `update` notice says
"The AI pages wait for your Update (about ₹300)". Nothing is called until he taps **Update** in the
Book panel and types YES on its ₹ (`POST …/update {typed: "YES", estimate_id}`) or he turned
"update by itself" on with its own YES (D7; then only within the release cap and the month cap). A
hotfix (1–3 pages, about ₹15) is the same rule. **More than a release's worth (H3):** an update
whose estimate passes the release cap, or one with nothing to carry from (no pages file left, as
after Privacy → Delete), is never a tap and never "by itself": `POST …/update` answers 409
`use_first`, and it goes through `POST …/first` with its own estimate and typed YES (D7). **A run
across a deploy (plan review M5):** every run is bound to its release id; when the current release
changes, the next step stops the run ("a new release came"), seals what it wrote into its own
release's pages file (`skipped` lists the rest), the free carry builds the new release's file from
it, and the pages left plus the new release's changed pages join the new release's estimate with its
own YES. A YES never carries to another release. If he never updates, the reader shows the newest
pages file: AI pages for unchanged parts and the generator's text, labelled, for changed ones.

**D13 · Who sees what, and how it is deleted.** The writer's routes are **owner and console-only**
(`book_gate.console_only`, a signed-in browser; never a guest, never token mode); the pages routes
need an **owner** book session (`X-Jarvis-Book`, audience owner; a guest session gets 403
`owner_only`). **Primary owner only (L11):** the writer's job and routes serve
`identity.primary_user_id` like `BookSealJob` (`sealer.py:259–275`); another owner e-mail gets 403
`not_primary`. A guest's show is the tour with no ₹ and no costs scene (D9); the trial's pages never
enter a release and are never in a guest session's reach. Privacy: R6's `book_sealed` row is
unchanged (it counts R6's index); a new row **"Build book: writer"** (the pages files with their
count and MiB, trial pages, drafts, the pick, the consents; the ₹ ledger stays 13 months as numbers,
like `tryon_spend`) deletes with his passkey and stops any run. After Privacy → Delete of the sealed
books the pages files are unreadable at once (their releases are gone) and the sweep drops them on
its next run; writing them again is a new first write with its own YES (D12). Logs never hold page
text, pack text, a prompt or a reply (the Book's AST log scan, `test_book_boundaries.py`, extended
to `writer/`); the audit records each run's start, stop, YES and pick by ids and ₹ only.

**D14 · The reader: the full book in today's look, and "continue where I left off".** C's
`console-book-pages.js` adds **Full book** to the Book panel's reader beside the eight sections:
parts as `.dsc` disclosures, chapters as `.bsec` rows, a page as its six sections (`plain` and
`example` open, `how`, `costs`, `fails`, `code` closed), its line "Written by Claude (balanced tier,
claude-sonnet-5-5) for v6.3.0 on 24 Nov 2026" from the page's meta (or "Not written by AI yet"), and
its references as code chips. Older kept releases' pages through the existing release picker.
**Continue where I left off:** this browser keeps `{release, page}` for the reader and `{release,
scene}` for the tour in `localStorage` (`jarvis_book_place_v1`, ids only, owner only); reopening
offers "Continue: <page or scene title>" for the same release. The tour's own continue starts the
scene, not the middle of a line. Text only through `textContent`; no `innerHTML` (the Book's static
test).

## Data model (prefix `jarvis_`; flat ids; every document carries `updated_at` and a plain `owner`)

| Collection / file | Part | Holds | Sealed | Kept |
|---|---|---|---|---|
| `book_writer/{uid}` | B | the pick `{brain, caps {trial, first, release, month, limit_pct}, auto_update, picked_at, confirmed {brain, caps, auto_update, terms_id, at}}` (`confirmed` starts with every cap 0, no brain and `auto_update` false: what his last typed YES granted, H2); consents `{trial, first}: {at, estimate_id, release}`; the run `{kind trial\|first\|update, release, estimate_id, state queued\|running\|paused\|done\|stopped, why, total, done, failed, started_at, ended_at}`; `update_ready {release, estimate_id, pages, inr_mid}`; `told {release: [pages \| update \| storage]}` (the writer's own notice claims, D11); `seconds {brain: [the last 20 calls' seconds]}` (the p90 window, D5); `rev` | no (ids, enums, numbers) | until deleted |
| `book_write_lease/{uid}` | B | `{holder, until}` (60 s) | no | while held |
| `book_write_spend/{uid}_{YYYY-MM}` | B | `spent_inr, held_inr, holds {call_id: {inr, at, run, page}}, runs {trial, first, update_<rid>: spent}, calls, refused` | no (numbers only) | 13 months |
| `book_drafts/{uid}_{rid}_{page}` | B | one page's draft: `{page, attempt, state ok\|failed, checks [code], meta, blob}` (the text and template, `BookCrypto` under the release id and a fresh `bf_` file id) | blob only | until the run's pages file is sealed, ≤ 30 days |
| `book_trial/{uid}_{nn}` | B | `nn` 01–10: one trial page, `{brain, page, attempt, checks, meta, seconds, inr, blob}` | blob only | 30 days, or until he deletes, re-runs or picks |
| the release's pages file | B | `PagesFile {v, release, pages [id, kind, title, part, chapter, sections [{id, heading, text, refs}], meta], templates, skipped}`, gzipped JSON ≤ 2 MiB, one a release, chunks in `book_pages/{uid}/book_chunks` | yes (R6's chunk envelope) | while its release is in R6's index (KEEP 3); the newest stays as the carry source while any release is kept |
| `book_pages/{uid}` | B | the pages index `PagesIndex {v, files [{release, fid, size, sha256, count, dek, sealed_at, written, changed, skipped}], pending, orphans}` (M4: R6's `book/{uid}` index is never touched) | yes (`book_index`, AAD `book/pages/{uid}/v1`) | until deleted (the writer's Privacy row) |
| `_book/facts.json` (CI, in the image) | A | D2's fact pack and D3's pages index, ≤ 1 MiB | no (public, package data) | with the image |
| `book.json` `tour` (CI) | D | the filled tour per audience, its seconds, words and characters | as `book.json` | with its release |

Ids: a page `pg_<kind>_<slug>`; a run's call `wc_` + 16 hex; an estimate `we_` + 12 hex of its
inputs' SHA-256 (packs, prices, rate, assumptions). Keyring: **no new purpose** (fact 16). **Never
stored:** a pack, a prompt or a reply outside a sealed blob; a page in any log; the creator name in
any writer document; a model's raw error text (R14 D9's fixed words only). Sizes: a draft ≈ 6–14 KB
sealed; the trial ≈ 120 KB; a pages file ≈ 0.4–0.6 MB plain. R14's drill counts the new root
collections (flat ids, `updated_at`); the guide §6.2 lists them (I0).

## The HTTP contract

Every route is the signed-in owner's, `no-store`, CSRF as every cookie write (`X-Requested-With`),
rate-limited, and answers `{"error": <code>, "detail": <plain words>}` on a refusal. **Console**
routes pass `book_gate.console_only` (a signed-in browser; never token mode, never a guest's
show-only browser, which the guest lock already refuses). **Owner session** routes need
`X-Jarvis-Book` of an owner book session (a guest's is 403 `owner_only`).

| Route | Part | What |
|---|---|---|
| `GET /v1/book/writer` | B | **console**; on or off and why (`no_key`, `no_ai`, `no_brain`); the brains offered (id, label, `trains_on_content`, the balanced model's name from the registry, "not set up" when missing); the trial (state, pages done, ₹ spent, results' ids); the pick; the run (kind, done / total, ₹ spent / cap, why stopped); `update_ready`; the month (Book ₹, his limit, 80 % line); `storage {used_mib, pages_mib, limit_mib, warn}` (D11's 80 % line, so `api/book.py` stays unchanged) |
| `GET /v1/book/writer/estimate?run=trial\|first\|update` | B | **console**; `Estimate {id, run, brain, pages, low, mid, high, hold, cap, minutes_low, minutes_high, gst_note, sent_to}`; ₹ only |
| `POST /v1/book/writer/trial` | B | **console**; `{typed, estimate_id}` → the trial queued; 422 `not_yes`; 409 `estimate_changed`, `running`; 503 `no_brain`, `no_ai` |
| `PUT /v1/book/writer/pick` | B | **console**; `{brain, caps, auto_update, typed?, terms_id?}`; 422 `bad_cap`, `unknown_brain`, `not_offered` (price unknown, M2), `not_yes`, and `yes_needed` with `{terms_id, words}` when the pick grants more than `confirmed` (the first pick, a cap raised, a paid brain, a training brain, "update by itself" on: H2), nothing saved; 409 `terms_changed`; audited by field names and `yes_confirmed`, never values |
| `POST /v1/book/writer/first` | B | **console**; `{typed, estimate_id}`; 409 `pick_needed`, `estimate_changed`, `running`, `already_written`; 422 `not_yes` |
| `POST /v1/book/writer/update` | B | **console**; `{typed: "YES", estimate_id}` (his typed YES on the update's ₹, his binding rule); 409 `nothing_to_update`, `estimate_changed`, `running`, `use_first` (more than the release cap's worth of pages, or nothing to carry from: H3); 422 `not_yes` |
| `POST /v1/book/writer/stop` | B | **console**; stops the run after the calls in flight (their holds settle); the pages written stay as drafts and are sealed as a partial pages file with `skipped` |
| `POST /v1/book/writer/step` | B | **console**; one step (D5), ≤ 45 s, at most one at a time (409 `busy`), 6 a minute; → the run's view |
| `GET /v1/book/writer/trial/pages` · `GET …/trial/pages/{nn}` · `DELETE /v1/book/writer/trial` | B | **console**; the side-by-side list (page, brain, checks, ₹, seconds) · one trial page (sections and meta) · delete the trial |
| `GET /v1/book/pages?release=` | B | **owner session**; the index: parts → chapters → pages `{id, kind, title, written: meta \| null, changed: bool}` for that kept release, and `limitations {shown, total}` (G4) |
| `GET /v1/book/pages/{id}?release=` | B | **owner session**; one page (sections, refs, meta), or the generator's text labelled "Not written by AI yet"; 404 `no_page` |
| `GET /v1/book/show/script` (existing) | D | adds `kind: "tour" \| "show"` and, for a tour, its scenes for the session's audience (owner-only scenes and lines removed for a guest) and `seconds` |

Limits: the writer's reads 30 a minute, its writes 10 a minute, `step` 6 a minute, the pages 60 a
minute (`api/book_show_wiring.py` `LIMITS` style, in the new modules). 14 routes in all (13 new).

## Tools: none new

R6.3 adds no model-callable tool, so no permission row, no Telegram pattern, no skill-register group,
no persona line. The writer is not a tool: the brain cannot start, raise or steer it; only the
owner's console routes can, each grant of spending with his typed YES on the ₹ shown (R13.1's
pattern, D7), so no e-mail, web page or chat message can make the Book spend (security-reviewer to
confirm). The writer's brain calls carry `tools=None`.

## Per part: failures, security, cost

| Part | Failure modes and handling | Security and privacy | ₹ a month |
|---|---|---|---|
| A · Facts and generator | a fact source missing or not a literal → `GenError` with one plain line (the deploy goes on, as today: `--best-effort`); a card in no module → `GenError`; facts over 1 MiB → `GenError`; the counter meets an unreadable file → counted as "unreadable", never guessed | stdlib only, no network; the scrubber's new kinds guard `book.json` too; the index lists paths and names, never file content | 0 |
| B · The writer | No-AI → paused, said so; breaker open or 5xx → this page waits (no laptop, no tier change); 429 → the step ends, next tick; a cut stream → settled at the hold, redrafted once; a failed check → redraft once, then the previous text; the cap, the month cap or 80 % → stopped, said so; a lost lease → the step ends; an unreadable ledger or limit → refused (fail closed); an unreadable pages index or file → those pages show the generator's text and the next write is `POST …/first` with its own typed YES, never a tap (H3); a new release during a run → stopped, sealed, joined to the new estimate (M5) | packs from public files only, scrubbed, fenced, same for both brains; no tools; nothing personal read (static guard); page text sealed; logs content-free; console-only consent and spend; the audit by ids and ₹ | trial ≤ ₹60 once; first write ≤ ₹1,500 once; ≤ ₹500 a release, ≤ ₹1,000 a month (Claude); ₹0 (Gemini) |
| C · Console | a route refusal → its `detail` in the line under the button; offline → "Can't reach JARVIS…"; a stale estimate → asks again | `textContent` only; the YES box never pre-filled; no ₹ sent from the page is trusted (the server re-estimates) | 0 |
| D · The tour | no tour in an older book → today's 11 scenes; a missing fact → the generator refuses (CI) | a guest's tour has no ₹ and no owner-only line, in the served script and in what speak reads (tested through the route, H1); lines served by id only | 0 (browser voice); Cloud voice ≈ ₹27 a tour after the free allowance (owner only; guests free-only) |

## Cost (₹)

At ₹95.24 a dollar (`billing/fx.py:33`; JARVIS uses the day's rate), Claude Sonnet 5.5 at US$2 / 10
per million tokens (`llm/pricing.py:28`), D8's assumptions (12k / 16k / 24k tokens in, 2.2k / 3k /
3.5k out a page, 15 / 25 / 30 % redrafted), no GST (see D8).

| Item | Pages | Low | **Mid** | High | Opus 5.5 (mid, for comparison) | Haiku 5.5 (mid) | Gemini (free) |
|---|---|---|---|---|---|---|---|
| Writer trial (Claude half) | 5 | ₹25 | **₹37** | ₹51 | ₹74 | ₹2 | ₹0 |
| First full write | 152 | ₹766 | **₹1,122** | ₹1,562 | ₹2,244 | ₹56 | ₹0 |
| A feature release (cards touched: R6.2 8, R13 34, R13.1 25) | 25 / 40 / 60 | ₹126 | **₹295** | ₹617 | ₹590 | ₹15 | ₹0 |
| A hotfix | 1–3 | ₹5 | ₹15 | ₹31 | — | — | ₹0 |
| One worst-case call (the hold: 27k in, 4k out) | — | — | ₹8.95 | — | — | — | ₹0 |

- **Against the proposed caps:** the trial (₹60) holds even the high case; the first write (₹1,500)
  holds low and mid; at high it stops ≈ 6 pages short (they keep the generator's text until next month
  or a raised cap); a release (₹500) holds low and mid, and at high stops ≈ 11 pages short; the month
  (₹1,000) holds three mid releases, or one high and one mid. With 18 % GST added by an invoice: first write mid ≈ ₹1,324.
- **Prompt caching** of the fixed system prompt (≈ 3k tokens, reads at 5 %) saves ≈ ₹0.5 a call,
  ≈ ₹100 on the first write; not counted above.
- **Everything else is ₹0:** the fact pack and tour at CI (GitHub's runners; Unverified whether
  standard runners are free for this public repository, G7); the writer's CPU inside Cloud Run's free
  vCPU-seconds (≈ 1–2 hours of request time for a first write: Unverified against the month's other
  use); Firestore: drafts ≈ 2 MB, the trial ≈ 120 KB, the pages files ≈ 1.5 MB for three releases,
  inside the free 1 GiB; R14's backups ≈ ₹0.1 a month more. No new Scheduler job, secret or resource.
- **The tour's voice:** ₹0 with the browser's (the default); with the Cloud voice ≈ 94 tours a month
  free (shared with the console's spoken replies), then ≈ ₹27 a tour; a guest is never charged.
- **Storage** (MiB, as `book_max_total_mb` counts: `sealer.py:86` `limit_mb * MIB`; L9): one release
  9.54 MiB (10.0 MB) + ≈ 0.48 MiB of AI pages; three kept ≈ 30.1 MiB of 60 (50 %); the 80 % warning
  at 48 MiB (D11). R6.3.1's pictures need its de-duplication to stay under the cap (its section).

## The I0 seam list (branch `r6-3-i0`; the integrator owns these files)

1. **Version** `6.3.0`: `__init__.py` and the six exact pins, the prefix pin (`test_r11_seams.py:60` →
   `"6."`), `v6.3.0` in `tests/r13_fake_server.py:126`, `test_r13_wiring.py:306`,
   `test_r131_wiring.py:291`; the label `R6.3` at `test_book_gen_determinism.py:212`,
   `test_r7_seams.py:160`, `test_r14_seams.py:104`; `test_book_gen_plans.py:212` →
   `docs/plans/r6-3-book-content.md` / `R6.3` and `:218` (fact 1). The persona is unchanged.
2. **The write seam** `llm/write.py` (D1, test first: no laptop call with a ready fallback, no tier
   change on a transient error, the model reported is `resolve(tier)`, a cut stream reported as cut,
   `BrainOff` under No-AI, prices only through `pricing`) and its fake in `tests/r63_fake_brains.py`.
3. **Types**: `buildbook/writer/model.py` (pages, sections, meta, pick, caps with defaults and bounds,
   runs, estimates, views, `PagesFile`, `PagesIndex` and its entry; ≤ 400), `buildbook/tour_model.py`
   (`TourBeat`, `TourScene`, `TourPicture`, `Tour`; ≤ 200); `buildbook/model.py` `Book.tour: Tour |
   None = None`, `Release.facts_sha256: str | None = None` (≤ +4 lines; old books still load: a test
   on `47ee8fc`'s real `book.json`; a newer sealed `book.json` read by an older revision is already
   409 `unreadable`, never a tamper alarm, `api/book.py:184–188`). **Not edited** (M4, D11):
   `FileKind`, `SealedRelease`, `seal_index.py`, `seal.py`, `ports.py`, `sealer.py`,
   `seal_notices.py`, `seal_words.py`, `privacy.py`, `api/book.py`. I0's test: an index written
   after a pages seal still opens with a copy of `47ee8fc`'s `BookIndex` model (the rollback reader).
4. **The module map** `buildbook/gen/modules.py` (18 modules, D3; the check "every card in exactly
   one"), read by A and D.
5. **Generator joins** (`gen/write.py`, `gen/__main__.py`, `gen/runner.py`, `release.py`): `facts =
   facts.build(repo)` (A's stub `{}`), `tour = tour.build(repo, facts)` (D's stub `None`),
   `pages_index.build(repo, facts)` (A's stub `()`), `_book/facts.json` written and checked
   (`--check`), `ReleaseSource.facts()`; `gen/tour.json` (an empty script) as package data
   (`pyproject.toml` `"jarvis.buildbook.gen"` += `"tour.json"`).
6. **Wiring** `api/r6_wiring.py` (263 → ≤ 300): `book_writer` on `app.state` (built with the keyring,
   the brain registry and billing; None without a keyring); `r6_tick_jobs` += B's `BookWriteJob`
   (stub: does nothing) after `book_sweep`; `R6_JOB_NAMES` += `"book_write"`; `home/watchdog.py`
   `ADVISORY_JOBS` += `"book_write"`; `install_r6_routes` += `api/book_writer.py`, `api/book_pages.py`
   (stubs: 503 `not_built_yet`); `r6_privacy_sources` += the writer's row (stub with zero counts).
   Pins that move: `test_r6_wiring_seams.py:154`, `test_r6_wiring.py:133–137` (3 jobs),
   `test_r2_wiring.py:258–272` (the ordered list gains `book_write` after `book_sweep`).
7. **Money** `billing/service.py` `LABELS["book"] = "Book writer"` (the same line).
8. **Console loading** `console-book.js` (≤ +6 lines, ≤ 390): load `console-book-writer.js` and
   `console-book-pages.js` once at the panel's first open (a `<script defer>` built in JS, as R13.1's
   loader does) and hand them `deps`; the stubs `window.JarvisBookWriter = {settings(host, deps)}` and
   `window.JarvisBookPages = {mount(host, deps)}`; `api/console.py` `APP_ASSETS` += both (≤ 473);
   `tests/test_book_static.py` `JS` += both; `tests/test_r51_console_assets_linked.py` (loaded by a
   module, not by the page). `console.html` unchanged.
9. **The show's script reader** `console-book-script.js` (new): `line`, `normalScene`, `normalScript`,
   `timeline` moved out of `console-book-show.js` unchanged in behaviour (390 → ≈ 355), plus the tour's
   shape (`kind: "tour"`, n 1–17, `t` ids, `visual`, `audience`, `chapter`); `book.html` loads it before
   `console-book-show.js` and loads D's stub `console-book-tour.js`; today's show browser tests must
   stay green on the move alone (the refactor's own check).
10. **The serve joins** `show_script.py` (I0 only): `build()` asks D's `buildbook/tour_serve.py`
    `tour_lines(book, audience, words)` (stub: None → `kind: "show"`, as today);
    `ShowScript.line_text(uid, line_id, audience)` gains the audience and passes a `^t\d{2}b\d{2}$`
    id to D's `tour_line_text(book, line_id, audience)` (stub: None), which answers None for an
    owner-only beat or scene in a guest session, so the route says 404 `unknown_line`, the same as a
    made-up id (plan review H1: today `BookService.line_text` calls `self.show.line_text(uid,
    line_id)` with no audience, `buildbook/service.py:345`, and a guest could have T16 or `t13b03`
    read out); `service.py:345` passes `session.audience` (one line changed, the file stays 397);
    `api/book_show.py` unchanged in shape. I0's seam test: the audience reaches `tour_line_text`.
11. **The scrubber's new kinds** are A's (`gen/scrub.py`); I0 pins the list in a test that A turns
    green (IPv4, IPv6, PAN, Aadhaar groups, hostnames under listed domains, project-id shapes).
12. **Fakes and evals:** `tests/r63_fake_brains.py` (scripted providers through the real
    `BrainRegistry`: a Claude-like paid brain and a Gemini-like free one; pages that pass, one citing a
    fake path, one with a typed number, one with an e-mail, one with an invented feature, a slow stream,
    429, 5xx, a cut stream, a ready laptop fallback), `tests/r63_fakes.py` (a fixed IST clock, a fixture
    repo with a three-card guide, its `source.zip` and `facts.json`), `tests/r63_fake_server.py` (the
    HTTP contract for C), `evals/r6_3/run.py` (R13.1's staged gate: unbuilt parts pass as
    `not_built_yet` until I1 flips `STUBS_PASS = False`, pinned) gated in `evals/run_all_mock.py`;
    `tests/test_r63_seams.py`, `tests/test_r63_wiring.py`. CI runs plain `pytest`: fakes are imported
    bare and named `r63_*`.
13. **The Book's static guards** extended: `test_book_boundaries.py` `C_MODULES` += the writer's
    modules and `api/book_writer.py`, `api/book_pages.py` (≤ 400 lines, functions ≤ 50, the content-free
    log scan); a writer import guard (D4); "no model id, vendor name or price literal under
    `buildbook/`" (D1).
14. **The guide** (`docs/architecture/JARVIS-Architecture.md`): C57 ("What it does" with the AI pages
    and the tour; "Outside services": the writer's brain, Anthropic or Gemini (free), only after the
    owner's YES; Google Text-to-Speech and Speech-to-Text only when Cloud voice is chosen; the talk
    brain; G2), its data (the six new collections), §6.2, §6.5 ("Anthropic or Gemini (free): the
    release's public code and facts, for the Book's writer"), the edition line and change log;
    `scripts/arch_coverage.json` if the checker needs it.
15. **The roadmap (§11)** refreshed with the Workshop's current release rows (R6.3.1, R6.4 and what
    follows, as the project's release plan has them; that plan is not in the repository), so the tour's
    `roadmap.next` and `roadmap.after` are true.
16. `docs/plans/r6-3-integration/BRIEF-COMMON.md` (R13.1's rules plus: ₹ only in owner-facing words;
    no real model call in any test or eval; a fixed clock; part D copies the approved script
    verbatim, every spoken line as approved on 23 Nov) and `I0-NOTES.md`.
17. **One source for references and services** (plan review H5, M7): the resolver of
    `scripts/arch_files.py` `cited` (`:45–62`) moves into `buildbook/gen/refs.py` (`resolve(repo,
    where) -> [(span, path | None)]`), and the services part of `scripts/arch_inventory.py`
    (`_settings_services`, `_host_services`, the tables of `scripts/arch_coverage.json`) into
    `buildbook/gen/services.py` (stdlib, taking the repository path); both scripts call them (the
    scripts already import the package: `arch_files.scan` imports `gen.scrub`). The check that the
    move changed nothing: `python scripts/arch_coverage.py` prints the same "OK – 66 packages/modules,
    104 console modules, 2 Scheduler jobs, 31 outside services, 120 Firestore collections" before and
    after. **The redact list** (M8): the Workshop hands the integrator the owner's locality,
    workplace and employer outside the repository; only their SHA-256 hashes go into
    `gen/redact.json` (as the name and handle are today); then `--check` and `arch_coverage.py`'s
    scan run on the real repository (on this branch those words appear in no tracked path and not
    in the guide, so neither can start failing).

## Part split (four builders; worktrees; branches `r6-3-a` … `r6-3-d` from `r6-3-i0`; disjoint files)

Every agent on Opus; Python modules ≤ 400 lines, functions ≤ 50, JS ≤ 400 (the Book's rule); test
first; only the planned collections, routes and job; never a wiring or shared file.

- **A · The fact pack and the generator** (CI, stdlib; D2, D2a, D2b, D3, D10's G3–G8): `gen/facts.py`,
  `gen/loc.py`, `gen/inventory.py`, `gen/pages_index.py`, changes to `gen/scrub.py`, `gen/plans.py`
  (G4), `gen/code.py` and `gen/libs.py` (G3, G5), `gen/costs.py` (G7), using I0's `gen/refs.py` and
  `gen/services.py` (seam 17) without editing them, `tests/test_r63_a_*.py`,
  `evals/r6_3/facts.py`, INTEGRATION-A.md. Determinism first: `--check` on the fixture and on the real
  repository after every module.
- **B · The writer** (D1's use, D4–D8, D10's checks, D11, D12, D13): `buildbook/writer/{packs,
  prompts, checks, fill, caps, consent, estimate, run, job, store, pages, privacy, texts}.py`,
  `buildbook/writer/{vault, carry, sweep}.py` (D11, D12: the pages index, the free carry, the
  sweep; no R6 sealing file is edited), `api/book_writer.py`, `api/book_pages.py`,
  `tests/test_r63_b_*.py`,
  `evals/r6_3/writer.py`, INTEGRATION-B.md. `security-reviewer` required (money, consent, the free
  brain's data rule, the checks, sealing).
- **C · The owner's console** (D6's and D7's screens, D12's Update, D14): `static/console-book-writer.js`
  (Book settings → Writer trial: estimate, what is sent, the YES box, progress with "Step while I
  watch", the side-by-side pages; Writer: the pick, the caps, the server's ₹ words and the YES box
  for every grant (H2), the first write's YES, Update's YES, Stop, and the 80 % storage line at the
  top of the Book panel from `storage`; ≤ 400), `static/console-book-reader.js` (G4's "+N more in the
  full book" line under the limitations section; 257 → ≤ 270, H4), `static/console-book-pages.js` (Full book, a page, references, continue; ≤ 400), the
  optional placement CSS (D0), `tests/test_r63_c_*.py`, `tests/browser/test_r63_c_*.py` (against
  `tests/r63_fake_server.py`), screenshots (360 × 800, 1280 × 800, day and night), INTEGRATION-C.md.
  `security-reviewer` for the YES and ₹ dialogs.
- **D · The short tour** (D9; approval stop 2 passed on 23 Nov, so D starts with the others):
  `gen/tour.json` (the approved script, verbatim), `gen/tour.py` (fill, audiences, timer, bands), `buildbook/tour_serve.py` (`tour_lines`,
  `tour_line_text`), `static/console-book-tour.js` (the picture per `visual`,
  chapter names, owner-only scenes, continue; ≤ 300), `tests/test_r63_d_*.py`,
  `tests/browser/test_r63_d_*.py` (the tour plays end to end with the browser voice stub and the 2D
  and 3D pictures; a guest's tour; Motion Off), `evals/r6_3/tour.py`, INTEGRATION-D.md.

## R6.3.1: images, de-duplication, diagrams and the setup guide (planned here, built next)

`v6.3.1`, its own plan file and I0 after R6.3 merges (this section is its binding scope; its seams
are written against the code R6.3 leaves). Four parts, ≈ 6.5–7 builder-days.

- **E · Pictures (Phase A §9.8).** A **demo household** seed (made-up names from a fixed list, SAMPLE
  documents, drawn avatars, a camera test pattern, a fixed IST clock; `scripts/ui_snapshots.py`'s
  fixtures from `tests/browser/ui_checks.py` extended), captured in CI's existing `browser` job
  (Chromium is already there) as a build artifact the deploy job packs into the image (R6.3.1's plan
  checks the jobs' order in `ci.yml`): about **7
  pictures a module** (overview, 2–6 steps, one error state, a phone view, one schematic SVG) ≈ 126 for
  18 modules, WebP quality 80 (measured at Phase A: desktop 1x 73 KB, phone 1x 21 KB), each ≤ 250 KB,
  **8 MB a release** at most (decision 7; expected 2–4.5 MB). A **privacy gate** before any picture is
  kept: the vendored tesseract.js (`static/vendor/vision/r7-1`, Apache-2.0, no new dependency) reads
  every picture in the same Chromium, and a picture with any name, e-mail, phone or number shape not
  on the demo list is refused; a manifest (`id, module, caption, viewport, theme, bytes, sha256, ocr`)
  is checked by a test. Native Android screens get schematics (an emulator step is later).
- **Approval stop 3, inside E's build:** once the seed and the capture run work, and **before any
  picture is packed into an image or sealed**, E produces the **contact sheet** for the Workshop to
  hand to the owner (not committed; only demo data in it): one page per module with every picture as
  a thumbnail, its caption, desktop or phone, day or night, its size, the OCR gate's verdict and any
  masked box drawn on it, the module's total and the release's total against 8 MB. Nothing goes
  further until his YES; a correction is a seed or caption change and a new sheet.
- **F · De-duplicated storage (§8.4, decision 7, G9, G14).** Sealing v2: every code file and picture
  sealed once per owner as a content-addressed blob (`book_blobs/{uid}_{sha16}`, the `BookCrypto`
  envelope with a blob AAD), a release = `book.json` and a manifest of path → blob (the AI pages stay
  in their own index, D11); the single-use code download rebuilds the deterministic zip from blobs
  (`ZIP_STAMP`); the 60 MiB cap counts unique blobs and the pages files; two-file releases stay
  readable, and R6.3.1's plan makes the same forward-compatibility choice as M4 (a new index shape a
  pre-R6.3.1 revision can't read lives beside R6's, or the runbook says "no rollback below v6.3.1");
  the 15 MiB snapshot cap becomes a cap on a
  release's new bytes. Estimate from the sizes measured on `47ee8fc`: three kept releases with
  pictures and no de-duplication ≈ 59.5 MB (at the cap); with it ≈ 43 MB (72 %), ≈ 34 MB at the
  expected picture use.
- **G · Eight diagrams with C-ids (§9.2, G10).** The table of Phase A §9.2 from the 14 Markdy sources
  plus two new (module dependencies from the cards' "Depends on", backup and restore); a C-id on every
  node; CI checks (`scripts/markdy_export.py --check`, `scripts/arch_coverage.py`) that every card
  appears in at least one diagram and ids match across diagrams; the full book's pages show their
  module's diagram.
- **H · The local setup guide, run (C8, §9.7).** `jarvis serve` with the mock brain; the Book in
  Google mode at `localhost` (R6.2 INTEGRATION-A §6's steps) and the Firestore emulator, each step
  actually run and its output kept as the chapter's evidence; plus the Cloud Run guard's last
  condition (memory sessions refused when `K_SERVICE` is set, R6.2 §8 item 9). `config.py` has one
  line left (fact 15): the condition joins the existing guard's set, or the Workshop raises the pin.

## Tests and evals (mock only; each control must make its suite fail)

**Every acceptance check in the first table is a named test** in its part's files and an eval case
of the same name. No test or eval calls a real model, Google or Anthropic; every test takes a fixed
clock.

| Suite | Cases | Control that must fail it |
|---|---|---|
| `contract` (I0, built) | the parts build through the real wiring and own only their routes, collections and job; the stubs answer `not_built_yet`; `book_write` does nothing without a run; `47ee8fc`'s real `book.json` and a two-file index still load; `console.html`'s hash | the job's "no run, no call" guard removed: `test_nothing_spends_by_itself_after_a_deploy` fails |
| `facts` (A) | `--check` twice identical with `facts.json`; every tour key known; the module map has all 73 cards once; the index has every tracked path and every `src` top-level symbol; the counter on a fixture equals its hand count; the inventory's Android, home-kit, bridge and dev rows with SPDX names; the scrubber's new kinds found (IPv4, IPv6, PAN, Aadhaar groups, hostnames, project ids) and versions, dates and line numbers left alone; every module constant with a literal value as `path:NAME` (H5); every guide reference resolved to one full path by D3's rule, and every page's `refs` full and scrubbed; `facts.json` passes `Scrubber.verify` and every Android page's references resolve (H6); the services list equals the coverage checker's inventory, 31 (M7); the route list equals the routes of the app built with mock settings (M9); G3's 31, G4's "+N more" | a set iterated unsorted in `facts.py`: `--check` fails; the IP pattern removed: its case fails; C69 removed from the map: the generator does not refuse and the case fails; the raw path stored instead of the scrubbed one: the H6 case fails; one router name dropped from the scan: the M9 case fails |
| `writer` (B, through `jarvis.llm` with the fake brains) | zero calls before YES; exactly `YES`; a changed estimate asks again; the trial cap (6 calls through, the 7th refused before sending); the first write's, a release's and the month's caps; 80 % of his limit; ten steps at once → one lease holder, the rest `busy`; settle, release and keep-at-hold; no laptop call with a ready fallback; no tier change; meta on every page; a FAST page and an `offline` page refused; each check (fake path, typed number, e-mail, IP, PAN, invented feature, PLANNED outside "Planned", unverified unlabelled) refuses and keeps the previous text after one redraft; the precision case: a hand-written good page for each trial sample passes all six (H5); a page cut by `max_tokens` or a cut stream refused before the checks (L10); no pack holds a file under `tests/**` or `evals/**`, or a `*.env.*` file (M8, L7); the pages file sealed in its own index (attach, then replace with the old chunk set orphaned), carried forward free at each new release, and only changed pages rewritten; three seals without an Update keep every unchanged AI page; a first write stopped at its cap and continued with a new YES replaces its pages file; an update over the release cap or with nothing to carry is 409 `use_first`; a run across a deploy stops, seals its own release's file and its pages join the new estimate, its YES not carried (M5); an attach in flight when Privacy → Delete lands is refused and its chunks go; R6's index after a pages seal still opens with `47ee8fc`'s `BookIndex` (M4); auto-update only within the cap; the first pick, a cap raised, a paid brain, a training brain and auto-update on each 422 `yes_needed` and nothing saved, then saved on the YES with that `terms_id`, 409 on a stale one, lowering instant (H2); a paid-tier Gemini and an unpriced custom brain listed "not offered" (M2); Gemini gets the same pack and `tools=None`; No-AI pauses; the 80 % storage warning | the hold as read-then-write: two parallel calls pass the cap; the YES check off: zero-calls-before-YES fails; auto-update accepted without its YES: the H2 case fails; a paid-tier Gemini offered at ₹0: the M2 case fails; `write_text` built on `complete()`: the no-laptop case fails; the carry run only on Update: the three-seal case fails; no replace in the pages vault: the continue case fails; the Privacy hold check off in the pages vault: the delete case fails; a pages entry written into R6's index: the rollback-reader case fails; the run's YES carried to a new release: the M5 case fails; the reference check off: the fake path is sealed; one exemption of check (2) removed: the precision case fails; `.claude/**` or `tests/**` in a pack: the never-reads case fails |
| `needles` (I1) | planted in the fakes: the creator name, his e-mail, a vault document's text, a memory fact, a mail subject, a fake secret, the pack's canary, the handle inside a tracked path (H6), and a stand-in for each new hashed word (locality, workplace, employer, M8) in a cited file — never in a pack, a prompt, a page, a draft, a trial page, `facts.json`, a log record, the audit, a notice or the Privacy export; a positive control per sink | the pack builder reading Book settings: the creator-name needle is found |
| `console` (C, browser) | the trial (estimate → what is sent → the YES box refuses "yes" → progress with "Step while I watch" → side by side with checks); the pick (caps filled with the defaults; the first save, a raise, a paid brain and "update by itself" each show the server's ₹ words and the YES box; "Keep" sends nothing; lowering saves at once); the first write's YES; Update's YES and Stop; the Full book (a written page, a "Not written by AI yet" page, references, an older release); continue; 44 px targets; 360 × 800 and 1280 × 800, day and night; the Book panel's screenshots with the writer off unchanged against `47ee8fc` | the YES box sending "yes": its case fails |
| `tour` (D) | the filled tour inside both bands; the seven highlights in his order; both running-example lines; no filled line has a doubled word ("about about", L1) and every spoken line is byte-identical to the approved script once filled; a guest's tour has no ₹, no T16, no owner-only line; a guest's `POST /v1/book/show/speak` of every owner-only tour id (`t13b03`, `t16b01`) is 404 `unknown_line`, through the real route; every tour id of the session's audience speaks; the player runs all 17 scenes, Questions and Closing in 2D, in 3D (WebGL2) and under Motion Off; an older book plays today's 11 scenes; "What else" lists the 11 other modules from the map | T13's owner line left in the guest's tour: the no-₹ case fails; `tour_line_text` ignoring the audience: the guest-speak case fails; a highlight dropped: the seven case fails; the pace set to 290 words a minute: the band case fails |
| `e2e` (I1) | the trial with the fake brains (estimate, YES, steps, side by side), the pick, the first write's YES, sealing, a page in the reader; a new release id → `update_ready` → Update → only the changed pages; a guest's tour | the update writing every page: the changed-only case fails |

**A control for every row's own case:** row 379 — the tier check off (a FAST page is sealed); row
380 (tour) — Wardrobe & Try-on dropped; row 380 (grows) — the pages index reading a fixed list
instead of the guide (C74 gets no page); trial — the cap check off; pick — `first` accepted without
the second YES; deploy — `book_write` starting an update without his Update.

**Browser (Playwright, `-m browser`).** C against `tests/r63_fake_server.py` while building, the
wired app at I1; D against the show page with `book_mocks.FakeBook` serving a tour script; 3D cases
only in a Chromium with WebGL2 (the Book's `_need_3d` rule). **Static tests:** `console.html`'s hash;
the Book JS and CSS sizes, ASCII and no HTML sink (`test_book_static.py`, extended); no ₹ figure in a
guest's tour; no `$` in owner-facing writer words; no model id, vendor or price literal under
`buildbook/`; the writer's import guard; no real clock under `buildbook/writer/` or `llm/write.py`.

## Size guards

`api/app.py` 732 (no edit, ≤ 735), `tools/gateway.py` 760 (no edit), `core/brain.py` 713 (no edit),
`config.py` 789 (no edit, ≤ 790), `console.html` 782 (no edit, hash), `console-book.js` ≤ 390,
`console-book-show.js` ≤ 370 after the move, `console-book-script.js` ≤ 200,
`console-book-reader.js` ≤ 270 (C, G4), every Book JS ≤ 400 and
CSS ≤ 300, `book.html` ≤ 130, `api/console.py` ≤ 473 (pin ≤ 475), `api/r6_wiring.py` ≤ 300,
`buildbook/model.py` ≤ 420, `buildbook/service.py` 397 (one line changed at I0, H1; ≤ 400), every new Python module ≤ 400
and function ≤ 50, `llm/write.py` ≤ 160, `facts.json` ≤ 1 MiB, a pages file ≤ 2 MiB gzipped, the
keyring 26. `tests/test_r63_seams.py` pins each.

## Risks and known limits

- The AI writer's quality is unproven for this code base; the trial is the test, and the checks only
  catch what they can see (a reference, a number, a shape), not a subtly wrong explanation: every
  page names its brain, and "How it works" cites its sources so a reader can check.
- The free Gemini brain may be slow or refused (no published free quota, `phase2-slice3` plan: expect
  429s): a first write on it may take days; and Google may learn from what it reads (only public code
  is sent).
- Time to write depends on the home watchdog being on; without it the morning clock alone gives
  about 4 days for a first write, and nothing runs between 11:30 and 04:00 IST unless Book settings is
  open.
- The estimates rest on assumed page sizes; each call's hold and every cap are hard, so the risk is a
  run stopping early, never an overspend.
- Anthropic's invoice may add 18 % GST that JARVIS's ₹ does not count (as Vitals today).
- Code and plans are untrusted text for the writer (the owner's plans quote him): fenced, no tools,
  checked; the worst case is an odd page that the checks or the owner catch.
- The checks can refuse a good page (for example a number inside prose that is really a name); the
  page then keeps the generator's text, and the refusal is listed by page and check.
- The tour borrows today's pictures; a picture that misleads is swapped for its 2D card by D, and R6.4
  draws each scene its own.
- The timer's pace is an estimate: the browser's British voice may read faster (about 170 words a
  minute would make the owner's tour ≈ 11.6 minutes, still inside 10–15); one stopwatch run sets it.
- The 15 MiB code-zip cap is about 6 feature releases away (fact 2): R6.3.1's de-duplication must land
  before it, or a book stops being written (the deploy itself is never blocked).
- Hotfixes count as kept releases; each gets a pages file (≈ 0.5 MiB, carried free) until R6.3.1's
  blobs. R6's sealer does not count the pages files (it is not edited, M4), so the stored total can
  pass 60 MiB by the kept pages files (≈ 1.5 MiB expected, at most 6 MiB); the writer refuses an
  attach past it and the 80 % line counts both.
- A rollback to a pre-R6.3 revision keeps working: R6's index is never given a pages entry (M4);
  the old revision ignores the pages index, and a newer sealed `book.json` reads as 409
  `unreadable` there, never as a tamper alarm.
- Pins churn at I0: 10 version, 5 label, 3 tick-list, the static lists.
- Cloud Run gives CPU only during a request: a step must finish inside its tick's or its own request.
- The owner's original 557-line prompt is lost; this plan covers what Phase A summarised of it, no
  more.

## Needs the owner (safe defaults; none blocks the build)

1. **Approval stop 2 (answered):** the tour's script above: YES, 23 Nov 2026, 14:53 IST, as
   written; any later change is a Workshop edit, ₹0, shown to you again.
2. **The tour's length:** about 13–14 minutes at the timer's pace (default); or a shorter 10–11
   minutes (each highlight cut to its first line).
3. **The trial's five pages:** the running example, the brain router, Wardrobe & Try-on, the Vitals
   screen and Telegram (default); or five you name.
4. **The trial's cap:** ₹60 (default; the estimate is about ₹40); or ₹50 or ₹100.
5. **Where the writer runs:** on JARVIS's existing clocks, with "Step while I watch" (default,
   decision 3); a Cloud Run Job only if the trial shows the clocks are crowded, as its own small
   release with your YES.
6. **GST:** the caps count JARVIS's metered price, as Vitals does, and each estimate says "your
   Anthropic bill may add 18 % GST" (default); or the caps count 18 % on top.
7. **Release updates:** ask you each release with its ₹, Update with your typed YES (default); or
   update by itself within the ₹500 release cap and ₹1,000 month, which you turn on in Book settings
   with your typed YES on those limits (changed by plan review H2: it can no longer be ticked on
   without one).
8. **A guest's tour:** no costs scene and no ₹ anywhere (default).
9. **If Gemini isn't set up on the server:** a one-brain trial, said so (default); or wait until it
   is.
10. **The caps at the pick:** ₹1,500 first write, ₹500 a release, ₹1,000 a month, stop at 80 % of your
    monthly limit (default, Phase A's); yours to change there.
11. **Trial pages and drafts:** kept 30 days (default).
12. **The split:** pictures, de-duplication, diagrams and the setup guide as R6.3.1 (default).

## Exit check (before the PR)

1. The row tests and the 23 Nov cases pass; every suite's control and every row's own control fails
   its suite; `STUBS_PASS` flipped; results in `docs/plans/r6-3-integration/I1-NOTES.md`.
2. The full browser suite once on the joined branch (queued, never beside another whole suite).
3. **Screenshots** to the orchestrator: the Writer trial (estimate, YES box, progress, side by
   side), the pick, the first write's YES, Update, a Full book page and a "Not written by AI yet"
   page, the tour's 17 scenes for the owner and a guest's T13, at 360 × 800 and 1280 × 800, day and
   night; the Book panel and show with the writer off, unchanged.
4. `python -m jarvis.buildbook.gen --check` (two identical builds with `facts.json`); `facts.json` ≤
   1 MiB; the tour's seconds in both bands.
5. `ruff check`, `ruff format --check`, `mypy src` (the baseline), `evals/run_all_mock.py` ALL PASS,
   `scripts/check_doc_versions.py`, `scripts/arch_coverage.py`, the coverage floor, the PR title.
6. After the deploy, one stopwatch run of the tour (owner or Workshop) to set the timer's pace.
7. **No live writer call in the PR** ("not called" in I1-NOTES): the trial is the owner's, after
   go-live, with his YES.
8. The clock sweep: his IST month's end (23:30 and 00:30 IST) for the ledger, 1 Jan 2027, 29 Feb 2028.

## What can't be verified from this workspace

A real writer call (no key here and no YES): Sonnet 5.5's and Gemini's speed and page quality in
this project, Gemini's free quota, the tokens a real page bills; whether Anthropic's invoice to this
account adds GST; whether the home watchdog is on in his deployment and how much of its 50 s the
other jobs leave; Cloud Run's free CPU left in a month; the browser voice's real pace; whether R7,
R13 and R13.1 are live (the guide says "joined, not yet deployed" for R7, R13 and R13.1; the brief
says R13.1 is live); the workbook's own acceptance checks for rows 379 and 380 and the owner's lost
prompt; the project's current release plan (for §11); whether GitHub's standard runners are free for
this public repository.

## Sources (read 23 Nov 2026)

| # | Source |
|---|---|
| S1 | Phase A findings, `docs/plans/r6-2-book-rebuild/PHASE-A-FINDINGS.md` v6.2.1 (15 Nov 2026), copied unchanged into this branch from `r6-2-plan` |
| S2 | R6.2's integration notes `docs/plans/r6-2-integration/INTEGRATION-A.md` v6.2.2 (decision 4, G11, the guest free-only rule) and its reviews |
| S3 | R13.1's plan `docs/plans/r13-1-try-on.md` v13.1.3 (the plan format; the consent, cap and hold patterns) and `docs/plans/r13-wardrobe.md`; R14's `docs/plans/r14-hardening.md` |
| S4 | The architecture guide `docs/architecture/JARVIS-Architecture.md` v13.1.5 (cards C01–C73, §5.2, §6.2, §6.5, §11) |
| S5 | The code at `main` @ `47ee8fc`, every file:line cited above; the generator run and the scratch counts described in "What the code says today" |
| S6 | The owner's decisions of 15 Nov 2026 (approval stop 1) and 23 Nov 2026 (the writer trial inside JARVIS, the seven highlights, plan from Phase A's summary), relayed by the Workshop — not in the repository |
| S7 | His requirements workbook, rows 379 and 380 (titles as relayed) — not in the repository |
| A1 | Anthropic pricing (Sonnet 5.5 $2 / $10, Opus 5.5 $4 / $20, Haiku 5.5 $0.10 / $0.50 per million tokens up to 100k-token prompts; cache reads $0.10 / $0.20 / $0.01; no India tax note) — https://platform.claude.com/docs/en/about-claude/pricing (read 23 Nov 2026; matches `llm/pricing.py`) |

## Change log

| Version | Date | Release | What changed | By |
|---|---|---|---|---|
| v6.3.1 | 23 Nov 2026, 14:28 IST | R6.3 | First edition, from the code at `47ee8fc` and Phase A v6.2.1 (copied unchanged): the owner's summary in ₹; rows 379 and 380 and his 23 Nov decisions as named tests; every Phase A fact re-checked and the moved ones corrected (10.0 MB a release, 97 left out, 73 cards and 18 modules, 31 services, 120 collections, 179 settings, the LOC, ≈ 152 pages, the router's `allow_degrade` but no laptop switch, the 20 s LLM timeout, `.claude/**` in the zip); the short tour's first script for approval stop 2 (17 scenes, seven highlights, ≈ 13.6 min owner, ≈ 13.0 guest, every number a fact); D0–D14 (the split into R6.3 and R6.3.1, the `jarvis.llm` write seam, the fact pack, the pages, the reading packs, the job and the step, the trial, the pick and the second YES, the ledger and holds, the tour, the checks, sealing the pages, release updates, audiences, the reader); the data model, 13 new routes, no new tool, keyring or alert kind; ₹ estimates (trial ≈ ₹37, first write ≈ ₹1,122, a release ≈ ₹295); the I0 seams; parts A–D; R6.3.1 with approval stop 3; suites with controls; size guards; risks; 12 owner questions with defaults; the exit check | 🛠 Mark XXIV |
