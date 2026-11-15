Version v13.0.1 · 15 Nov 2026, 21:20 IST · Release R13 · Status: Current · Owner: 🛠 Mark XXI

# R13 Part C · Styling: integration notes (STY-01–17, LND-16, OPS-04)

Written by builder C in the Workshop (🛠 Mark XXI) on branch `r13-c`, cut from `r13-i0` @ `3bf2cb1`.
The plan is `docs/plans/r13-wardrobe.md` v13.0.2 (Ready), Part C, with plan review 1's changes
for C (H1, M12, L4, D15, STY-11); the brief is `BRIEF-COMMON.md`. The owner's "defaults OK"
stands: no calendar until he picks one (title on, location off), the 20:00 evening alert,
auto-swap off, the rewear rule, Holi "okay to stain" only. Styling is fixed rules only; the AI
stylist is R17.

## 1. What Part C built

Everything is under `src/jarvis/wardrobe/styling/` (each module ≤ 400 lines, every function
≤ 50) plus C's router. No wiring, shared, contract or R11 file was edited.

| File | Lines | What |
|---|---|---|
| `rules.json` · `rules.py` | 118 · 196 | D12 as data, checked at start: 12 slots and their types, 7 dress codes (required and optional slots, types per slot, formality target and floor, "okay to stain", sets whole), event words, outdoor and indoor words, heat and cold, the colour-pairing table, colour families, the rewear rule. A file that fails its check raises `RulesError`: the part is "setup failed" |
| `look.py` · `rank.py` · `engine.py` | 135 · 132 · 281 | The pure engine: hard exclusions in order (formality, okay to stain, his rules, rain-ok outdoors, availability with the declared hand-off and sets, reservations), the emptying step named in the gap with a next action, ranking with ties by piece id, his locks and the plan's picks kept, a primary look and up to two alternatives with reasons naming piece ids, outstanding laundry-shop pieces. `AVAILABILITY` is the eval control's switch |
| `plans.py` · `sealed.py` | 199 · 184 | The sealed `wardrobe_plans/{uid}` (plans ≤ 60, 14 days back to 30 ahead; his rules; his choices: calendar, fields, lead, evening alert, auto-swap), `wardrobe_cal/{uid}`, `wardrobe_outlook/{uid}` (purpose `wardrobe`, AAD `<collection>/<uid>/v1`), and the once-only claims in `wardrobe_told/{uid}_styling_<key>` |
| `reserve.py` | 161 | Windows; a plan holds its pieces against plans of the same local day or an overlapping window, never a declared shared piece; deliberate transfer; the shared base (reusable pieces only) |
| `service.py` · `actions.py` · `prefs.py` | 234 · 147 · 112 | His local day (`ctx.now()`, `ctx.zone`), the engine's `Ask` for a day or a plan (weather, rules, reservations, hand-off, locks, the 14-day stale check), plan looks, `outfit_plan`'s seven actions, `outfit_prefs` |
| `wear.py` | 184 | `wear_started` / `wear_done` through A's `transact` with the rewear rule and the plan link; his words to piece ids ("Which one: …?" when several fit); the forgotten wear closed from 04:00 for A's sweep |
| `refresh.py` | 156 | The `ChangeObserver` (`services["refresh"]`, bound first by the wiring) |
| `calendar.py` · `outlook.py` · `jobs.py` | 300 · 212 · 143 | The governed calendar read and `sync`; the weather from his R11 place; `outfit_clock` |
| `views.py` · `texts.py` · `tools.py` · `data.py` · `part.py` | 150 · 206 · 326 · 49 · 68 | The model's and the panel's views, the fixed sentences, the five tools, D's Privacy data, the join |
| `src/jarvis/api/outfits.py` | 160 | `GET /v1/outfits`, `GET /v1/outfits/calendars`, `PUT /v1/outfits/settings` |
| `tests/r13_fakes_c.py` | 337 | A fake Google Calendar and Open-Meteo, a recording notifier, his permission rows, the seeded world (pilot set + a brown belt) with a real gateway and R11's `OutsideStore` |
| `tests/test_r13_c_*.py` (9 files) | 1,337 | below |
| `evals/r13/styling.py` | 348 | BUILT, 19 cases, two controls |

How it plugs in: `build(ctx)` gives `WardrobePart("styling", tools=5, clock_jobs=(outfit_clock,),
data=(OutfitsData,), services={"refresh": …}, ready="ready")`. C may offer no other service name,
so the routes reach the styling service and the calendar through `services["refresh"]`
(`.styling`, `.calendar`). With no token key the part is still built, its ready word is "off: no
token key", its tools and routes say "Outfits are off: JARVIS has no token key to seal your
plans." and nothing is written; with no storage, "off: no storage".

The tools' arguments, for D's No-AI sentences (D20):
`outfit_suggest(day="today"|"tomorrow"|YYYY-MM-DD, occasion=<his words>, code=<dress code>)`;
`wear_log(action="start"|"done", pieces=[ids] | plan=<id> | query=<his words>)` ("done for today":
`action="done"` alone closes everything In use). Each result's `message` is the sentence to show.

## 2. Per use case: what holds and its named test

| ID | Built | Test (file `tests/test_r13_c_…`) |
|---|---|---|
| STY-01 | "tomorrow" is the next day in his zone, at 23:30 and 00:30 IST, the sentence asserted whole; a planned meeting is what tomorrow answers with | `tools::test_sty01_what_to_wear_tomorrow_is_the_next_local_day_with_its_occasion` (both clocks), `tools::test_sty01_a_planned_meeting_is_what_tomorrow_answers_with` |
| STY-02 | an event on his calendar makes a plan for its local date (an event at 00:30 IST is the next day); missing from a read that covers its window → cancelled, kept as a draft, no `outfit_ready`; an edit refreshes by Google's `updated` stamp | `calendar::test_sty02_*` (3) |
| STY-03 | a "Catch-up" event is smart casual, tentative; his dress code makes it business formal and re-picks; Google is only ever read | `tools::test_sty03_changing_catch_up_to_business_formal_gives_a_business_formal_look` |
| STY-04 | light-blue shirt, charcoal trousers, brown dress shoes, a brown belt matching them, the watch, black socks | `engine::test_sty04_*` |
| STY-05 | Diwali: the kurta set worn whole and said; a part in the laundry: the set isn't worn whole, the kurta alone | `engine::test_sty05_*` (2) |
| STY-06 | Holi: okay-to-stain pieces only, never a delicate one, a favourite he excluded stays out (and comes back) | `engine::test_sty06_*`, `prefs::test_sty06_*` |
| STY-07 | rain likely outdoors: rain-ok shoes and an outer layer, "Weather for your home area: rain likely from 15:00."; no place, Helpers off or weather off: "Weather unknown: I assumed indoors." | `engine::test_sty07_*`, `outlook::test_sty07_*` (2) |
| STY-08 | "never tight at the neck" filters; the gap names the rule that left no top, with the ids | `engine::test_sty08_*` |
| STY-09 | the meeting look lists shoes, belt, watch, base layer and underwear; a private piece is "a private basic" in every reason and the model's view; his panel shows its words only with "Show private basics" | `engine::test_sty09_*`, `tools::test_a_result_shows_fixed_words_*`, `routes::test_his_private_basics_*` |
| STY-10 | a dirty belt or a pair missing a shoe is never in a look or an alternative | `engine::test_sty10_*` |
| STY-11 | every look's reasons name each of its piece ids; up to two alternatives | `engine::test_sty11_*` |
| STY-12 | changing the shoes keeps shirt, trousers and watch; a lock is kept while available and replaced with a compromise when not | `engine::test_sty12_*`, `tools::test_sty12_*`, `actions::test_a_locked_slot_*` |
| STY-13 | a meeting and an evening function: the declared shared base (reusable pieces only), "Reused from your 10:00 event: …" and "Change for this one: …"; after "I'm wearing it" the base stays eligible for the evening, nothing marked, nothing sent | `tools::test_sty13_*`, `engine::test_sty13_*` |
| STY-14 | reserved shoes appear for their event and are a gap for a second plan at the same time; reserving them is refused in words; a deliberate transfer moves them | `tools::test_sty14_*`, `engine::test_sty14_*` |
| STY-15 | a planned white shirt into the basket: out of tomorrow's look, the light-blue one shown, "needs a new top", one `outfit_changed` in fixed words; wearing the planned outfit sends and marks nothing; beyond 36 h: marked, not sent; once a plan per 2 hours; auto-swap; a piece back clears its need; a plan worn as it is now (a substitute he took is no change) | `refresh::test_sty15_*` (2) and 8 more, `tools::test_wearing_a_plan_whose_shirt_went_to_the_basket_*` |
| STY-16 | "No ready formal shoes: … are In laundry (wash them)." with the rest of the look standing | `engine::test_sty16_*` |
| STY-17 | saving or previewing a plan changes no count; start then done is one wear; the rewear rule (shirt to the laundry, trousers Ready); the forgotten wear closed from 04:00, once | `tools::test_sty17_*`, `part::test_sty17_*`, `part::test_a_wear_started_today_is_not_closed_tonight` |
| LND-16 | "Outstanding: collect a white shirt (wi_…) from the laundry shop, due back Tuesday 17 November." beside the ready shirt offered | `engine::test_lnd16_*` |
| OPS-04 | only a calendar from his list (a keyed reference; the id sealed, URL-encoded); only `items(id,status,updated,start,end,summary)` (+`location` when he allows), never description or attendees; every read on the Calendar row, Allow only, kind-only audit lines; off stops automatic plans and alerts, its plans stay his; an alert never names a private piece | `calendar::test_ops04_*` (4), `refresh::test_a_private_piece_is_never_named_in_the_alert` |

Also: the rules file's check (`engine::test_the_rules_file_is_checked_at_start`), the rewear
default, "Holi" never inside "holiday", the fetch slots and at most twice a day, a failed fetch
waits an hour, R11's document never written, the 60-minute calendar cadence, the 20:00
`outfit_ready` once, no evening alert when off or without a key, the contract's three routes and
models, `no-store`, the settings change audited without an id, the wiring's contract check, a
broken rules file "setup failed" while the others run, the Privacy data, the plan actions'
refusals writing nothing, and the trust rule (the two reads vouch; nothing else).

## 3. Plan review 1, for C

- **H1.** `wear_started` / `wear_done` are C's tool and A's ledger; the refresh's `judge`:
  a wear for its own plan marks the plan worn and sends nothing; a wear of a declared shared
  (reusable) piece from the plan it is worn for is a hand-off, nothing; a reusable piece worn
  today is no change for a later day; everything else that leaves eligibility marks and, within
  36 h, alerts. STY-13's base stays eligible through the engine's hand-off rule (In use, worn for
  the declared plan, reusable).
- **Calendar (M12).** Every read, the console's too, goes through `BackgroundReads` on
  `calendar_list_events` (Allow only): the console route has no gateway decision, so "Ask first"
  never reads. Titles are matched in memory only; cancelled events by absence.
- **L4 / D14.** C fetches tomorrow's forecast itself from his R11 place (read-only, late,
  `ctx.outside()`), with R11's `request_params`, `HttpFetcher` and `parse_forecast`, from 05:00
  and from 18:00, sealed in `wardrobe_outlook/{uid}`; R11's document is never written (pinned).
- **D15.** Every "today" and "tomorrow" comes from `ctx.now()` in `ctx.zone(uid)`; nothing under
  `styling/` reads the real clock; every test takes a fixed IST clock; sentences with a day are
  asserted whole; 23:30 and 00:30 IST are tested.
- **STY-11.** Rule-based reasons name the actual piece ids, never his label.

## 4. Checks (2 CPUs shared; heavy runs behind `/tmp/heavy.lock`)

| Check | Result |
|---|---|
| Part C's tests, Python 3.11 (`tests/test_r13_c_*.py`, 9 files) | **86 passed, 1 xfailed** (the I1 tripwire, §6.2) |
| Coverage of `jarvis.wardrobe.styling` and `api/outfits.py` | **94 %** (2,169 statements; every module ≥ 86 %) |
| The seam tests and their neighbours (`test_r13_seams`, `test_r13_wiring`, `test_r13_fold_conformance`, `test_telegram_tool_guard`, `test_permissions_policy`, `test_r14_skill_coverage`, `test_telegram_personal_reads`, `test_r11_1_b_guard`, `test_test_imports`) | **730 passed, 2 failed**: the two I0 pins that every built part moves (§6.1) |
| `evals/r13/run.py --mock --part styling` | **19/19**, the controls fail it: availability off → LND-16, STY-04, STY-10, STY-13, STY-15, STY-16; the wear rule off → STY-13, STY-15 |
| `evals/r13/run.py --mock` (all parts, staged) | 37/37, negative control fails the suite |
| `ruff check`, `ruff format --check` (C's 31 files) | clean |
| `mypy src` | 1 error: the baseline's (`memory/redis_store.py:67`) |
| `scripts/arch_coverage.py` · `scripts/check_doc_versions.py` | OK · 29 documents pass; this file passes the same rules (`problems()`) |
| Mutations (each reverted): `description` in `fields`; cancellation off; `outfit_ready` at any hour; a fetch every run; any In-use piece eligible | each caught (1, 1, 3, 2 and 2 failing tests) |
| Part C's tests, Python 3.12 | **86 passed, 1 xfailed** |

**Test first, honestly.** The engine (its red run: the module did not exist), the tools and the
refresh were written test first. For the calendar, the weather, the clock, the routes and the
part, the code was drafted alongside and their tests written straight after from the acceptance
checks; the five mutations above and the two eval controls show those tests fail when the
behaviour breaks.

## 5. Deviations from the plan, with reasons

1. **His outfit choices live in C's sealed `wardrobe_plans/{uid}`** (`plans.Choice`: calendar id,
   fields, lead, evening alert, auto-swap), not in A's index as the data model says: `Commit`
   lets only A write the index (`records` are A's), so C has no way to write there. §6.4.
2. **A plan holds its pieces against every plan of the same local day**, not only overlapping
   windows: a shirt worn at 10:00 is not clean at 19:00, and D3 holds an In-use piece "for other
   plans until a reusable return or an allowed hand-off". A declared shared base is the way to
   reuse (STY-13). Different days: overlapping windows only.
3. **`outfit_changed`'s claim** is one `wardrobe_told/{uid}_styling_changed_<plan>` document
   re-claimed in a transaction once 2 hours have passed (`Told.every`); `outfit_ready` is a
   create-only `…_styling_ready_<plan>`. Claims older than 30 days are pruned once a day.
4. **The weather's "twice a day"** counts successful fetches; a failed one is retried after an
   hour (Open-Meteo's allowance is 10,000 a day).
5. **`lead_h` (the "alert lead")** is stored, returned and audited, but changes nothing: D19
   fixes `outfit_ready` at 20:00 the evening before, and the plan does not say what a lead
   changes. A plan found after that evening is told when found, until it starts. §6.7.
6. **A name that fits several pieces in `wear_log`** answers "Which one: wi_… (a light blue
   shirt) or …?" and writes nothing. No review entry: a wear is not a hold, and the review
   queue is B's and the fold's.
7. **No live event title in the panel**: `PlanView` has no title field (adding one is a contract
   change); the panel says "your 10:00 event". Settings shows his calendars' names live.
8. **`wear_log` on a plan** wears the plan's look as it is now (a substitute he accepted), not
   its stored picks, so a substitute worn for its plan is no change (H1).
9. **`outfit_suggest` on a day with plans** answers with those plans' looks (STY-01's "shows the
   occasion"); with an occasion or a code it makes a fresh suggestion.
10. **The LND-16 line sits in `Look.gaps`**, as D12 lists it among the gaps' next actions.
11. **More modules than the plan's list** (`look`, `rank`, `sealed`, `service`, `actions`,
    `views`, `data`), all under `wardrobe/styling/`, to keep each ≤ 400 lines.
12. **An event with no rule word** ("Catch-up") is smart casual, tentative; no event is casual.

## 6. Needs I1 (exact diffs)

1. **I0's two "not built yet" pins** fail on every branch with a built part
   (`tests/test_r13_wiring.py`, I0's; not edited here):
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
2. **Ship the rules file** (`pyproject.toml`, the image installs non-editable; without it the
   deployed part is "setup failed"), then delete the `xfail` line of
   `tests/test_r13_c_part.py::test_the_package_ships_the_rules_file` (strict: it fails once
   this lands, as a tripwire):
   ```diff
    # R14 Part C (D11): the skill register's catalogue (data)
    "jarvis.skills" = ["catalogue.json"]
   +# R13 Part C (D12): the styling rules (data, checked at start)
   +"jarvis.wardrobe.styling" = ["rules.json"]
   ```
3. **A's `wardrobe_sweep` closes forgotten wears with C's rewear rule** (from 04:00 his time;
   idempotent by its client id `wclose-<piece>-<day>`):
   ```python
   from jarvis.wardrobe.styling.rules import load_rules
   from jarvis.wardrobe.styling.wear import close_forgotten

   closed = await close_forgotten(
       store, uid, now=ctx.now(), zone=await ctx.zone(uid),
       close=ctx.s.wardrobe_wear_close, rules=load_rules(),
   )
   ```
4. **The outfit settings' home.** A's `GET /v1/wardrobe` `SettingsView` should take
   `calendar_chosen`, `fields`, `lead_h`, `plan_alerts`, `auto_swap` from C
   (`part_of(request, "styling").services["refresh"].styling.plans.read(uid)` → `.choice`), and
   `WardrobeSettings.calendar` / `fields` / `lead_h` / `plan_alerts` / `auto_swap`
   (`wardrobe/model.py`) are then unused: keep them as reserved or drop them (a contract change
   for A and D). The data model row of `wardrobe/{uid}` and guide card C71 should say the
   calendar choice is sealed in `wardrobe_plans/{uid}`.
5. **Guide C71** (PLANNED → built, I1): C's collections are `wardrobe_plans`, `wardrobe_cal`,
   `wardrobe_outlook` and `wardrobe_told` (keys `styling_…`), all sealed but the claims; the
   calendar read is the `calendar_list_events` row, Allow only.
6. **Reviews in a fresh context** (never by builder C): `code-reviewer` and `python-reviewer`;
   `security-reviewer` too, since C's tools, the governed calendar read and the routes touch the
   gateway (CLAUDE.md).
7. **`lead_h`**: the owner (or I1) decides what the "alert lead" changes, or it goes.
8. **D's phrases** call the arguments of §1; D's panel calls C's write tools through A's
   `POST /v1/wardrobe/tools/{tool}` and reads `GET /v1/outfits`.
9. **A key change** (`KEY_ID`) changes the keyed event fingerprints and calendar references: the
   next read makes new calendar plans and cancels the old ones (drafts), and Settings asks him to
   pick his calendar again. Say so in the runbook beside the backup's key note.

## 7. What can't be verified here

Google's `fields` and `singleEvents` behaviour on `calendarList.list` and `events.list` (a fake
answers here); his real calendars; Open-Meteo's values for his place; the alerts' delivery
through Telegram and Web Push (a recording notifier here); Firestore's transaction retries and
sizes; the evening alert at 20:00 his time on Cloud Run's clock (fixed clocks here); the
wired-app end-to-end test 5 with A's real store (I1).

## Change log

| Version | Date | Release | What changed | By |
|---|---|---|---|---|
| v13.0.1 | 15 Nov 2026, 21:20 IST | R13 | First edition: Part C built on `r13-c` (rules, engine, plans and reservations, wear, refresh, calendar, weather, `outfit_clock`, five tools, three routes, Privacy data, the BUILT eval with two controls), each use case's named test, plan review 1's changes for C, the checks with their numbers, twelve deviations with reasons, nine Needs-I1 items with diffs, what can't be verified here | 🛠 Mark XXI |
