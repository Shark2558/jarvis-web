Version v13.0.2 · 16 Nov 2026, 11:30 IST · Release R13 · Status: Current · Owner: 🛠 Mark XXI

# R13 Part C · Styling: integration notes (STY-01–17, LND-16, OPS-04)

Written by builder C in the Workshop (🛠 Mark XXI) on branch `r13-c`, cut from `r13-i0` @ `3bf2cb1`;
v13.0.2 by Part C's fixer after the two fresh-context reviews (`REVIEW-C-SECURITY-1.md`,
`REVIEW-C-CODE-1.md`, both of `54f95f4`, committed beside this file). The plan is
`docs/plans/r13-wardrobe.md` v13.0.2 (Ready), Part C, with plan review 1's changes for C (H1, M12,
L4, D15, STY-11); the brief is `BRIEF-COMMON.md`. The owner's "defaults OK" stands: no calendar
until he picks one (title on, location off), the 20:00 evening alert, auto-swap off, the rewear
rule, Holi "okay to stain" only. Styling is fixed rules only; the AI stylist is R17.

## 1. What Part C built

Everything is under `src/jarvis/wardrobe/styling/` (each module ≤ 400 lines, every function
≤ 50; the largest module is `engine.py`, 340 lines, the longest function 39) plus C's router.
No wiring, shared, contract or R11 file was edited.

| File | Lines | What |
|---|---|---|
| `rules.json` · `rules.py` | 118 · 219 | D12 as data, checked at start: 12 slots and their types, 7 dress codes, event words, outdoor and indoor words, heat and cold, colour pairing and families, the rewear rule (its ONE source: `rewear_default()`, `Rules.reusable_types`). A file that fails its check raises `RulesError`: the part is "setup failed" |
| `look.py` · `rank.py` · `engine.py` | 138 · 133 · 340 | The pure engine: hard exclusions in order (formality, okay to stain, his rules, rain-ok outdoors, availability with the declared hand-off and sets, reservations), a set's mates through the same checks, the emptying step named in the gap with a next action, a reusable piece an earlier plan holds proposed as a shared base, ranking with ties by piece id, his locks and the plan's picks kept, a primary look and up to two alternatives with reasons naming piece ids, outstanding laundry-shop pieces; every day it names is his local day (`Ask.zone`). `AVAILABILITY` is the eval control's switch |
| `plans.py` · `sealed.py` | 258 · 191 | The sealed `wardrobe_plans/{uid}` (plans ≤ 60, at most 20 made by his calendar, 14 days back to 30 ahead; his rules; his choices: calendar, fields, evening alert, auto-swap; the events he dismissed), the compare-and-set merges (`cas`, `strict`), `wardrobe_cal/{uid}` and `wardrobe_outlook/{uid}` (derived caches: unreadable reads as empty), the once-only claims in `wardrobe_told/{uid}_styling_<key>`. Sealed records ignore unknown fields and never echo a value |
| `reserve.py` | 169 | Windows; a plan holds its pieces against plans of the same local day or an overlapping window, never a declared shared piece; deliberate transfer; the shared base (reusable pieces only, from an earlier plan the same day: `can_share_from`) |
| `service.py` · `actions.py` · `prefs.py` | 244 · 153 · 114 | His local day, the engine's `Ask`, plan looks, the plans a day's question answers with (`planned`: by occasion; today not worn and not over), `outfit_plan`'s seven actions (refused when a plan changed meanwhile), `outfit_prefs` (ids only) |
| `wear.py` · `wearlog.py` | 246 · 183 | `wear_started` / `wear_done` through A's `transact`; the plan a wear is for (`plan_for`), "the outfit" (`outfit_of`), a wear told after the fact (`worn_events`), the ledger's verdict (`counted`); his words to piece ids; the forgotten wear closed from 04:00 for A's sweep. `wearlog.py` is the `wear_log` tool and its card |
| `refresh.py` | 160 | The `ChangeObserver` (`services["refresh"]`, bound first by the wiring); writes a plan only where it is still as read |
| `calendar.py` · `outlook.py` · `jobs.py` | 324 · 219 · 198 | The governed calendar read (only the fields he chose; a partial read cancels nothing) and `sync` (at most 20 calendar plans, never a dismissed event, a plan he kept taken back); the weather from his R11 place (3 days); `outfit_clock` (each step on its own; at most three evening alerts a day of plans, then one line) |
| `answers.py` · `cards.py` · `tools.py` | 52 · 266 · 273 | The tools' shared steps; the write tools' checks, fixed summaries and previews; the five tools |
| `views.py` · `texts.py` · `data.py` · `part.py` | 150 · 234 · 49 · 70 | The model's and the panel's views, the fixed sentences, D's Privacy data, the join |
| `src/jarvis/api/outfits.py` | 176 | `GET /v1/outfits`, `GET /v1/outfits/calendars`, `PUT /v1/outfits/settings` (what he did not send stays) |
| `tests/r13_fakes_c.py` | 337 | A fake Google Calendar and Open-Meteo, a recording notifier, his permission rows, the seeded world (pilot set + a brown belt) with a real gateway and R11's `OutsideStore` |
| `tests/test_r13_c_*.py` (13 files) | 2,412 | below |
| `evals/r13/styling.py` | 345 | BUILT, 19 cases, two controls |

How it plugs in: `build(ctx)` gives `WardrobePart("styling", tools=5, clock_jobs=(outfit_clock,),
data=(OutfitsData,), services={"refresh": …}, ready="ready")`. C may offer no other service name,
so the routes reach the styling service and the calendar through `services["refresh"]`
(`.styling`, `.calendar`). With no token key the part is still built, its ready word is "off: no
token key", its tools and routes say "Outfits are off: JARVIS has no token key to seal your
plans." and nothing is written; with no storage, "off: no storage".

The tools' arguments, for D's No-AI sentences (D20) and the panel:
- `outfit_suggest(day="today"|"tomorrow"|YYYY-MM-DD, occasion=<his words>, code=<dress code>,
  setting="indoor"|"outdoor")`: an occasion answers with that day's plans of the occasion
  (today: not worn, not over), else a fresh look; outdoors from `setting`, else his words.
- `wear_log(action="start"|"done", pieces=[ids] | plan=<id> | query=<his words>,
  day="today"|"yesterday"|YYYY-MM-DD)`: "the meeting outfit" is today's plan; a start linked to
  today's plan holding the piece; "I wore … yesterday" for a Ready piece is one wear at 12:00 his
  time that day; "done for today" (`action="done"` alone) closes everything In use.
- `outfit_plan(action=…, occasion=holi|festival|meeting|sport|function, setting=…, …)` and
  `outfit_prefs(…, occasion=<the same keys>)`: an occasion on the write tools is a rules key;
  `outfit_plan(action="save", plan=<id>, setting="outdoor")` marks an existing plan outdoors.
  Removing a whole plan is always a card.
Each result's `message` is the sentence to show.

## 2. Per use case: what holds and its named test

| ID | Built | Test (file `tests/test_r13_c_…`) |
|---|---|---|
| STY-01 | "tomorrow" is the next day in his zone, at 23:30 and 00:30 IST, the sentence asserted whole; a planned meeting is what tomorrow, and "for the meeting tomorrow", answer with; today skips a worn or finished plan | `tools::test_sty01_*` (3), `tools::test_h3_*` (2), `tools::test_l3_*` (2) |
| STY-02 | an event on his calendar makes a plan for its local date; missing from a whole read that covers its window → cancelled, a draft until its day has passed, no `outfit_ready`; an edit refreshes by `updated` | `calendar::test_sty02_*` (3), `calendar::test_a_cancelled_calendar_draft_goes_*`, `calendar::test_a_read_cut_short_*` |
| STY-03 | an event with no rule word is smart casual, tentative; his dress code makes it business formal and re-picks; Google is only ever read | `tools::test_sty03_*` |
| STY-04 | light-blue shirt, charcoal trousers, brown dress shoes, a matching brown belt, the watch, black socks | `engine::test_sty04_*` |
| STY-05 | Diwali: the kurta set worn whole and said; a part in the laundry, held by another plan or excluded: not worn whole, the kurta alone, said | `engine::test_sty05_*` (2), `engine::test_m1_*` (3) |
| STY-06 | Holi: okay-to-stain pieces only, never a delicate one, a favourite he excluded stays out (and comes back) | `engine::test_sty06_*`, `prefs::test_sty06_*` |
| STY-07 | rain likely outdoors (his `setting`, or his words "in the park"): rain-ok shoes and an outer layer, the weather said; no place, Helpers off or weather off: "Weather unknown: I assumed indoors."; "tomorrow" at 00:30 still has the evening's forecast | `outlook::test_sty07_*` (4), `outlook::test_tomorrow_after_midnight_*`, `engine::test_sty07_*` |
| STY-08 | "never tight at the neck" filters; the gap names the rule | `engine::test_sty08_*` |
| STY-09 | the meeting look lists shoes, belt, watch, base layer and underwear; a private piece is "a private basic" everywhere but his panel with "Show private basics" | `engine::test_sty09_*`, `tools::test_a_result_shows_fixed_words_*`, `routes::test_his_private_basics_*` |
| STY-10 | a dirty belt or a half pair is never in a look; a piece unseen for 14 days says its local day | `engine::test_sty10_*`, `engine::test_m2_*` (3) |
| STY-11 | every look's reasons name each of its piece ids; up to two alternatives | `engine::test_sty11_*` |
| STY-12 | changing the shoes keeps the rest; a lock is kept while available, replaced with a compromise when not | `engine::test_sty12_*`, `tools::test_sty12_*`, `actions::test_a_locked_slot_*` |
| STY-13 | a meeting and an evening function: the declared shared base, "Reused from …" and "Change for this one: …"; a later plan PROPOSES an earlier plan's reusable pieces as the shared base with its next action, no hard gap; after "I'm wearing it" the base stays eligible | `tools::test_sty13_*`, `tools::test_m5_*` (2), `engine::test_sty13_*` |
| STY-14 | reserved shoes are a gap for a second plan; reserving or locking them is refused in words; a deliberate transfer moves them | `tools::test_sty14_*`, `engine::test_sty14_*`, `actions::test_locking_a_piece_another_plan_holds_*` |
| STY-15 | a planned white shirt into the basket: the light-blue one shown, "needs a new top", one `outfit_changed`; wearing the planned outfit (by plan, by "the meeting outfit", or by naming its shirt) sends and marks nothing; beyond 36 h marked, not sent; once a plan per 2 h; auto-swap | `refresh::test_sty15_*` (2) and 8 more, `wear::test_wearing_a_planned_shirt_*`, `wear::test_wearing_the_meeting_outfit_*` |
| STY-16 | "No ready formal shoes: … are In laundry (wash them)." with the rest standing | `engine::test_sty16_*` |
| STY-17 | saving a plan changes no count; start then done is one wear; done for a plan closes the substitute worn; "I wore … today / yesterday" is one wear at the stated local day (00:30 IST edge); the forgotten wear closed from 04:00, once, by its fixed client id | `tools::test_sty17_*`, `wear::test_*` (8), `part::test_sty17_*`, `part::test_a_forgotten_festive_layer_*` |
| LND-16 | "Outstanding: collect a white shirt (wi_…) from the laundry shop, due back Tuesday 17 November." beside the ready shirt; not counted as a gap in the evening alert | `engine::test_lnd16_*`, `calendar::test_the_evening_alert_does_not_count_*` |
| OPS-04 | only a calendar from his list; only the fields he chose are requested AND used; every read governed; a toggle keeps his calendar; off stops automatic plans and alerts and deletes the last read; at most 20 calendar plans, a removed one never made again, at most three evening alerts then one line | `calendar::test_ops04_*` (4), `calendar::test_a_toggle_*`, `calendar::test_choosing_the_same_calendar_*`, `calendar::test_switching_*`, `calendar::test_fifty_invites_*`, `calendar::test_a_calendar_plan_he_released_*`, `calendar::test_a_title_google_sends_*` |

Also: the rules file's check, the rewear default and its one source, "Holi" never inside
"holiday", the fetch slots and at most twice a day, a failed fetch waits an hour, R11's document
never written, the 60-minute cadence, the 20:00 `outfit_ready` once, no evening alert when off or
without a key, the contract's three routes, `no-store`, the settings change audited without an
id, the wiring's contract check, a broken rules file "setup failed" while the others run, the
Privacy data, the write tools' cards and checks (`cards::*`), the races (`races::*`), the sealed
records across releases and a key change (`sealed::*`).

## 3. Plan review 1, for C

Unchanged from v13.0.1: H1 (`judge`: own, handoff, later, back, left), the calendar's governed
reads (M12), C's own weather (L4, D14), D15's clocks, STY-11's reasons. The code review's H1 and
M3 complete H1 for his own words ("I'm wearing the white shirt", "done" for a substitute).

## 4. Review fixes (v13.0.2)

Both reviews' verdicts were WARNING with no CRITICAL. Every HIGH and MEDIUM is fixed inside Part
C's own files with the review's fix, each test written first and seen red (a few were missing
tests the review asked for and already held: marked "pin"). Commits on `r13-c`.

| Review | ID | Fix | Test (`tests/test_r13_c_…`) | Commit |
|---|---|---|---|---|
| code | H1 | a start with no plan links to today's plan holding the piece (`wear.plan_for`); "outfit"/"plan" in his words is today's current or next plan | `wear::test_wearing_a_planned_shirt_*`, `test_wearing_the_meeting_outfit_*`, `test_the_outfit_with_no_plan_today_*` | `7029e33` |
| code | H2 | `PUT /v1/outfits/settings` keeps what was not sent (`model_fields_set`); `null` still switches off; the answer from the stored choice; re-choosing a calendar takes back plans he never edited | `calendar::test_a_toggle_without_the_calendar_*`, `test_choosing_the_same_calendar_again_*` | `4c1465b` |
| code | H3 | an occasion answers with that day's plans of the occasion (`Styling.planned`) | `tools::test_h3_*` (2) | `6ef0036` |
| code | M1 | a set's mates pass every hard exclusion (`engine.mate_fails`); a not-alone part needs its mates free; "complete" only when every mate placed | `engine::test_m1_*` (2 red, 1 pin) | `f53b3bf` |
| code | M2 | `Ask.zone`: the stale line and `recent()` use his local day | `engine::test_m2_*` (2 red, the 15-day stale clause a pin) | `5c3443d` |
| code | M3 | "done" for a worn plan closes what is In use for it, the substitute too | `wear::test_done_for_a_plan_closes_the_substitute_*` | `0d1eebf` |
| code | M4 | `rules.json` the one source: `rewear_default()`, `Rules.reusable_types`; A's copy and closer go at I1 (§6.3) | `part::test_the_rewear_rule_is_read_from_cs_rules_file_only`, `test_a_forgotten_festive_layer_*` (pin) | `a8d7d9c` |
| code | M5 | a required slot emptied only by an earlier same-day plan's reusable pieces is a proposed shared base with its next action, not a gap | `tools::test_m5_*` (1 red, 1 pin) | `8fa5d70` |
| code | M6 | `day` on `wear_log`; a Ready piece "worn today/yesterday" is start + done in one commit at 12:00 his time (now if ahead), linked to that day's plan | `wear::test_i_wore_*`, `test_today_before_noon_*`, `test_yesterday_at_00_30_ist_*`, `test_a_stated_day_*` | `0d1eebf` |
| code | M7 | `setting` on `outfit_plan(save)` (new or existing plan) and `outfit_suggest`; his outdoor words in `outfit_suggest`; STY-07's test and eval case through the tool | `outlook::test_sty07_*` (3) | `62dcfcc` |
| code | M8 | `Choice.lead_h` dropped; C's sealed records `extra="ignore"` | `sealed::test_a_document_with_a_field_*`, `test_the_settings_answer_the_contracts_lead_*` | `2d66311` |
| code | M9 | the tripwire is semantic (`tomllib`); the line and the Docker step are I1's (§6.2) | `part::test_the_package_ships_the_rules_file` (strict xfail) | `84cf901` |
| code | L1 | 3 forecast days kept; an uncovered day stays unknown | `outlook::test_tomorrow_after_midnight_*`, `test_a_day_the_forecast_does_not_cover_*` (pin) | `84cf901` |
| code | L2 | the evening alert doesn't count an "Outstanding" line | `calendar::test_the_evening_alert_does_not_count_*` | `b5cfd44` |
| code | L3 | today skips worn or finished plans in `outfit_suggest` (the panel keeps them: §5.14) | `tools::test_l3_*` (2) | `6ef0036` |
| code | L4 | the missing tests: the close id, recent wear, set mates, the calendar switched mid-read | `wear::test_two_sweeps_*`, `engine::test_m2_worn_lately_*`, `engine::test_m1_*`, `races::test_switching_calendars_*` | `0d1eebf`, `5c3443d`, `f53b3bf`, `c7103b4` |
| code | L5 | `tomorrow_of` gone; one HH:MM reader (`texts.time_of`); "for Holi"; the prune once a day at any hour; §1's line counts | `prefs::test_sty06_*`, `sealed::test_the_claims_are_pruned_*` | `cf1c2c6`, `2105a0a`, `84cf901` |
| security | H1 | at most 20 calendar plans; a removed calendar plan not made again (`dismissed`); at most three `outfit_ready` a day of plans, then one line; a cancelled draft goes once its day has passed | `calendar::test_fifty_invites_*`, `test_a_calendar_plan_he_released_*`, `test_a_cancelled_calendar_draft_*` | `b5cfd44` |
| security | M1 | `sync` inside the transaction; repicks, the refresh and the plan actions by compare-and-set (`plans.cas`, `plans.strict`); prefs made again inside the transaction | `races::*` (5) | `c7103b4` |
| security | M2 | ids checked before any record (`prefs.BY_ID`); excluding a piece not in his wardrobe refused; `days` checked; `hide_input_in_errors` | `cards::test_a_name_instead_of_an_id_*`, `test_the_rules_refuse_a_name_*`, `test_excluding_a_piece_not_in_*` | `cf1c2c6`, `2d66311` |
| security | M3 | derived caches reset when unreadable; each clock step on its own, counted by class; the tools and routes say so in words (503) | `sealed::test_an_unreadable_weather_cache_*`, `test_with_a_new_key_*` | `2105a0a` |
| security | M4 | fixed summaries and previews in fixed words; a whole-plan release always a card | `cards::test_removing_a_whole_plan_*`, `test_each_plan_action_card_*`, `test_each_rule_card_*` | `cf1c2c6` |
| security | L1 | lock with a piece refused like reserve | `actions::test_locking_a_piece_another_plan_holds_*` | `146f07a` |
| security | L2 | a pure `check=` on the five tools, fixed words, no echo | `cards::test_a_bad_argument_*` (15 cases) | `cf1c2c6` |
| security | L3 | an occasion on `outfit_plan`/`outfit_prefs` is a rules key | `cards::test_an_occasion_on_the_write_tools_*` | `cf1c2c6` |
| security | L4 | `nextPageToken`: a partial read cancels nothing; title and location used only when his fields allow | `calendar::test_a_read_cut_short_*`, `test_a_title_google_sends_*` | `146f07a` |
| security | L5 | switching calendars deletes `wardrobe_cal/{uid}` | `calendar::test_switching_the_calendar_off_deletes_*` | `4c1465b` |
| security | L6 | `Unreadable(...) from None`; `hide_input_in_errors=True` | `sealed::test_a_document_that_fails_its_check_*` | `2d66311` |
| security | L7 | the sweep takes C's checked rules from C's part and skips when C is "setup failed" (I1, §6.3) | — (I1) | — |
| security | L8 | the ledger's `Refused` in its words; "Already noted"; transfer of a purged piece refused | `wear::test_the_ledgers_refusal_*`, `test_a_start_the_ledger_takes_as_a_duplicate_*`, `actions::test_transferring_a_piece_purged_*` | `0d1eebf` |

Declined or partly declined, with the reason:
- **Security H1.5 (declined events).** Requesting `attendees(self,responseStatus)` differs from
  D13 ("attendees never fetched"): the owner's decision, listed in §6.14.
- **Code L3 for the panel.** `GET /v1/outfits` still lists today's plans as they are: D's panel
  puts "Done for today" on each, so hiding a worn plan would take that button away (§5.14).
- **Security M3 "a C-only reset".** D's Privacy row is D's file: listed in §6.9.

### Checks (v13.0.2, Python 3.11, `PYTHONPATH=$PWD/src`; 2 CPUs shared)

| Check | Result |
|---|---|
| Part C's tests (`tests/test_r13_c_*.py`, 13 files) | **159 passed, 1 xfailed** (the I1 tripwire, §6.2); 86 at v13.0.1 |
| Coverage of `jarvis.wardrobe.styling` and `api/outfits.py` | **96 %** (2,618 statements; every module ≥ 86 %) |
| The seam tests and their neighbours (`test_r13_seams`, `test_r13_wiring`, `test_r13_fold_conformance`, `test_telegram_tool_guard`, `test_permissions_policy`, `test_r14_skill_coverage`, `test_telegram_personal_reads`, `test_r11_1_b_guard`, `test_test_imports`) | **733 passed, 2 failed**: the two I0 pins every built part moves (§6.1), nothing else |
| `evals/r13/run.py --mock --part styling` | **19/19**; the controls fail it: availability off → LND-16, STY-04, STY-10, STY-13, STY-15, STY-16; the wear rule off → STY-13, STY-15 |
| `ruff check`, `ruff format --check` (C's 39 Python files) | clean |
| `mypy src` | 1 error: the baseline's (`memory/redis_store.py:67`); the two the fixes had introduced (a `dict` invariance, a reused name) were fixed in `b30cda8` |
| Sizes | every module under `styling/` ≤ 400 (largest `engine.py` 340), every function ≤ 50 (longest 39) |
| `scripts/arch_coverage.py` · `scripts/check_doc_versions.py` | OK · 29 documents pass; this file and the two reviews pass the same rules (`problems()`) |
| Clocks and imports | fixed IST clocks only (00:30 and 23:30 edges where days matter: "tomorrow", "yesterday", the stale line, worn lately, the forecast); fakes imported bare |

The tests, the seam set, the eval and `mypy src` ran behind `flock /tmp/heavy.lock` (at
`84cf901`, then the tests, the eval and `mypy src` again at `b30cda8`). While another agent's
70-minute browser run held the lock, the red-then-green runs of single C test files ran without
it, as BRIEF-COMMON §6 allows for a part's own tests.

## 5. Deviations from the plan, with reasons

1. **His outfit choices live in C's sealed `wardrobe_plans/{uid}`** (`plans.Choice`: calendar id,
   fields, evening alert, auto-swap), not in A's index: `Commit` lets only A write the index.
   The code review judged §6.4 required, not optional.
2. **A plan holds its pieces against every plan of the same local day** (D3). Reusable pieces an
   earlier plan holds are proposed as a shared base, not hard gaps (code review M5).
3. **`outfit_changed`'s claim** is re-claimed every 2 hours (`Told.every`); `outfit_ready` is a
   create-only claim per plan plus three per-day slots and one "more" claim.
4. **The weather's "twice a day"** counts successful fetches; a failure is retried after an hour.
5. **No alert lead.** `lead_h` was dropped before the first deploy (code review M8): D19 fixes
   the alert at 20:00. The route accepts the contract's `lead_h` and stores nothing (§6.6).
6. **A name that fits several pieces in `wear_log`** answers "Which one: …?" and writes nothing.
7. **No live event title in the panel** (`PlanView` has no title field).
8. **`wear_log` on a plan** wears its look as it is now (a substitute he accepted); "done" for it
   closes what is In use for it (code review M3).
9. **`outfit_suggest` on a day with plans** answers with those of the occasion asked (code review
   H3); for today, not worn and not over (L3); a dress code is always a fresh look.
10. **The LND-16 line sits in `Look.gaps`**; the evening alert doesn't count it (code review L2).
11. **More modules than the plan's list** (`look`, `rank`, `sealed`, `service`, `actions`, `views`,
    `data`, and now `answers`, `wearlog`, `cards`), all under `wardrobe/styling/`, each ≤ 400.
12. **An event with no rule word** ("Catch-up") is smart casual, tentative.
13. **The evening's fourth and later alerts are one line** (security H1): "Tomorrow's outfits for
    17 more events are ready in Helpers, Wardrobe." This is a new D19 sentence on the same
    `outfit_ready` kind: **the Workshop's OK is asked** (§6.14).
14. **Today's question skips worn and finished plans; the panel does not** (code review L3).
15. **An occasion on the write tools is a rules key** (security L3): the model maps his words
    (`outfit_suggest` keeps his words, R1 and never a card); "Catch-up" is no occasion.
16. **Removing a whole plan is always a card** (security M4), from the panel too.
17. **A wear told after the fact is at 12:00 his time that day, or now when that is ahead**
    (D4.1's stated-day rule, never in the future); its start and end share one time and the
    ledger keeps their order by arrival.

## 6. Needs I1 (exact diffs)

1. **I0's two "not built yet" pins** fail on every branch with a built part
   (`tests/test_r13_wiring.py`, I0's; still the only failures in C's seam run, §4 checks):
   ```diff
   @@ def test_every_stub_part_builds_through_the_real_modules
   -    assert {p.ready for p in parts.values()} == {"not built yet"}
   +    assert all(p.ready != wiring.SETUP_FAILED for p in parts.values())
   @@ def test_the_app_builds_the_four_parts_and_answers_v1_r13
   -        assert [(p["part"], p["ready"]) for p in body["parts"]] == [
   -            (n, "not built yet") for n in PARTS
   -        ]
   +        assert [p["part"] for p in body["parts"]] == list(PARTS)
   +        assert all(p["ready"] != wiring.SETUP_FAILED for p in body["parts"])
   ```
2. **Ship the rules file (code review M9).** The image installs non-editable, so without it the
   deployed part is "setup failed" while every test passes from the source tree:
   ```diff
   # pyproject.toml [tool.setuptools.package-data]
    "jarvis.skills" = ["catalogue.json"]
   +# R13 Part C (D12): the styling rules (data, checked at start)
   +"jarvis.wardrobe.styling" = ["rules.json"]
   # Dockerfile, after `pip install .`
   +RUN python -c "from jarvis.wardrobe.styling.rules import load_rules; load_rules()"
   ```
   Then delete the `xfail` line of `tests/test_r13_c_part.py::test_the_package_ships_the_rules_file`
   (now a `tomllib` check: strict, it trips once the entry lands in any spelling).
3. **The rewear rule's one source (code review M4, A's M8; security L7).** A's `wardrobe_sweep`
   calls C's closer with the checked rules from C's built part, and A's `WORN_AGAIN`,
   `after_wear` and `_close_wears` (`wardrobe/catalog/jobs.py`) are deleted:
   ```python
   from jarvis.wardrobe.styling.wear import close_forgotten

   styling = part_of(app, "styling")  # C's built part; "setup failed": no services
   refresh = styling.services.get("refresh") if styling is not None else None
   if refresh is not None:  # C off or "setup failed": the step is skipped, A's work goes on
       closed = await close_forgotten(
           store, uid, now=ctx.now(), zone=await ctx.zone(uid),
           close=ctx.s.wardrobe_wear_close, rules=refresh.styling.rules,
       )
   ```
   Pinned on C's side by `test_a_forgotten_festive_layer_wear_closes_to_ready_once`; I1 adds the
   same case on A's sweep. A reader without the part uses `rules.rewear_default()`.
4. **A's settings view reads C's choice (required).** D's panel builds its PUT from A's
   `SettingsView`; with C's route now keeping what was not sent, A's `GET /v1/wardrobe` should
   still answer `calendar_chosen`, `fields`, `plan_alerts`, `auto_swap` from
   `part_of(request, "styling").services["refresh"].styling.plans.read(uid)` → `.choice`, and the
   five fields of A's `WardrobeSettings` (`wardrobe/model.py`) go (a contract change for A and D;
   one source). Guide C71 says the choice is sealed in `wardrobe_plans/{uid}`.
5. **Contract: `CalendarChoice.chosen` (code review H2)**, so the panel can show and keep the
   pick (`wardrobe/http_parts.py`):
   ```diff
    class CalendarChoice(_M):
        id_ref: str = Field(min_length=8, max_length=64)
        title: str = Field(max_length=200)  # shown live, never stored
        primary: bool = False
   +    chosen: bool = False  # this is the calendar he picked
   ```
   and in `api/outfits.py` (C's, at I1): `chosen=ref == calendar.ref(uid, doc.choice.calendar)`.
6. **Contract: drop `lead_h` (code review M8)**, in ONE commit with D's panel no longer sending
   it: `OutfitSettings.lead_h` (`http_parts.py:121`), `SettingsView.lead_h` (`http_views.py:131`),
   `WardrobeSettings.lead_h` (`model.py:294`), `console-helpers-wardrobe.js` (D's, the `lead_h`
   in its settings body). C stores nothing already; `OutfitSettings` is `extra="forbid"`, so the
   panel must stop sending it in the same commit.
7. **`core/guardrails.py`: `outfit_plan` into `NO_BULK_TOOLS` (security M4)**, beside
   `wardrobe_merge` and `wardrobe_retire`: a whole-plan release is now always a card and should
   never ride "Approve all".
8. **The gateway's `log.exception("tool failed")` (security M2, for every part).** It prints any
   tool's exception text; C's arguments no longer reach an exception, but another part's may.
   Proposed: log the class name only (`extra={"tool": …, "error": type(exc).__name__}`).
9. **A C-only reset in D's Privacy (security M3).** C's `OutfitsData.delete` already deletes only
   C's three documents and its claims; D's row "Laundry, outfits and wear history" also clears
   B's data. Proposed: an "Outfit plans" row of its own, so a key change costs his plans only.
10. **The runbook's key-change note (security M3, corrects v13.0.1's §6.9).** After a `KEY_ID`
    change: his outfit plans can't be opened; the tools and Helpers say "Your outfit plans can't
    be opened (JARVIS's key changed): delete them in Privacy to start again.", the routes answer
    503 in those words, and the clock counts `plans_failed_Unreadable` while its weather step
    goes on. C's weather and calendar caches are made again by their next write. Nothing is
    overwritten until he deletes them; then Settings asks him to pick his calendar again.
11. **Guide C71** (PLANNED → built): C's collections are `wardrobe_plans`, `wardrobe_cal`,
    `wardrobe_outlook` and `wardrobe_told` (keys `styling_…`), all sealed but the claims; the
    calendar read is the `calendar_list_events` row, Allow only; at most 20 calendar plans.
12. **Reviews of these fixes in a fresh context** (never by C's builder or fixer):
    `code-reviewer`, `python-reviewer` and `security-reviewer` (the tools' checks and cards, the
    governed read, the routes).
13. **D's phrases and panel.** The No-AI sentences already send what C now takes (`query="the
    meeting outfit"`, `day="yesterday"`); a panel call of `outfit_plan` or `outfit_prefs` with an
    occasion sends a rules key; a whole-plan release from the panel is a card.
14. **For the owner and the Workshop.** (a) The evening's one-line overflow sentence (§5.13). (b)
    Whether to skip events he declined (`attendees(self,responseStatus)`, his own response only;
    D13 says attendees are never fetched): not done.

## 7. What can't be verified here

Google's `fields`, `nextPageToken` and `singleEvents` behaviour on `calendarList.list` and
`events.list` (a fake answers here); his real calendars; Open-Meteo's values for his place and its
`forecast_days=3`; the alerts' delivery through Telegram and Web Push (a recording notifier);
Firestore's transaction retries with the compare-and-set closures (the in-memory store runs each
once; every closure resets what it records, so a retry is safe); the evening alert at 20:00 on
Cloud Run's clock; the wired-app end-to-end test 5 with A's real store (I1). The reviewers'
probe scripts were read as data only; each scenario they reproduced is now one of C's tests.

## Change log

| Version | Date | Release | What changed | By |
|---|---|---|---|---|
| v13.0.1 | 15 Nov 2026, 21:20 IST | R13 | First edition: Part C built on `r13-c` (rules, engine, plans and reservations, wear, refresh, calendar, weather, `outfit_clock`, five tools, three routes, Privacy data, the BUILT eval with two controls), each use case's named test, plan review 1's changes for C, the checks with their numbers, twelve deviations with reasons, nine Needs-I1 items with diffs, what can't be verified here | 🛠 Mark XXI |
| v13.0.2 | 16 Nov 2026, 11:30 IST | R13 | The two fresh-context reviews' fixes: every HIGH and MEDIUM of both (code H1–H3, M1–M8; security H1, M1–M4) and the LOWs (code L1–L5; security L1–L6, L8) inside C's files, each test first; the findings table; the checks re-run; deviations 13–17; Needs I1 updated (the rewear rule's one source, `CalendarChoice.chosen`, dropping `lead_h`, `NO_BULK_TOOLS`, the gateway's log line, a C-only reset, the corrected key-change note, the owner's two questions) | 🛠 Mark XXI (Part C fixer) |
