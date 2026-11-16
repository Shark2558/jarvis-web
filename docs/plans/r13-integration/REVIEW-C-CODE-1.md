Version v13.0.1 · 16 Nov 2026, 10:07 IST · Release R13 · Status: Current · Owner: 🛠 Mark XXI (fresh-context code review, Part C)

# R13 Part C (Styling): code and Python review 1

Fresh context: the reviewer did not write this code. Branch `r13-c` @ `54f95f4` in the detached worktree
`/tmp/rv-c-code`; diff `r13-i0..r13-c` (34 files, +6,112). The review followed `.claude/agents/code-reviewer.md`,
`.claude/agents/python-reviewer.md`, `CLAUDE.md`, `.claude/rules/ecc/` (common and python), the plan
`docs/plans/r13-wardrobe.md` v13.0.2 (Part C, D3, D4, D10, D12-D15, D19, D20), `BRIEF-COMMON.md`, `I0-NOTES.md`,
`INTEGRATION-C.md` and the owner's workbook (`/tmp/mark21/wardrobe-usecases.txt`). The security review
(`C-SECURITY-1.md`: H1, M1-M4, L1-L8) is not repeated here.

**Verdict: WARNING. No CRITICAL, 3 HIGH, 9 MEDIUM, 5 LOW.** The engine, the rules file, the sealing, the clock
discipline and the tests are good work: every module is under 400 lines, no function is over 40, the tests
use fixed IST clocks only, and the claimed numbers reproduce. The three HIGHs are seams where the owner's
own phrasing (D20's No-AI sentences) or D's panel meets C: each was reproduced and each gives him a wrong
answer or a false ringing alert. Fix H1-H3 and M1-M3 before I1 merges Part C; the rest can ride I1.

Probes (scratch scripts outside the repo, against the branch's own fakes, behind `flock /tmp/heavy.lock`):
`/tmp/rv-c-code-scratch/probes.py` (P1-P6), `probe2.py` (P7-P9), `probe3.py` (P10), `probe4.py` (P11),
`probe5.py` (P12); mutation runs on a copy (`/tmp/rv-c-code-scratch/mutate.sh`). Only C's tests and C's eval ran.

## What was run

| Check | Result |
|---|---|
| `tests/test_r13_c_*.py`, Python 3.11 (`/tmp/venv-b`) | **86 passed, 1 xfailed** (as claimed) |
| Coverage `jarvis.wardrobe.styling` + `api/outfits.py` | **94 %** (2,169 statements; as claimed) |
| `evals/r13/run.py --mock --part styling` | **19/19**; the negative controls fail the suite |
| Mutations re-run (on a copy) | any In-use piece eligible: 2 fail; `outfit_ready` at any hour: 3 fail; `description` in `fields`: 1 fail (all as claimed) |
| Real clock under `styling/`, `api/outfits.py`, C's tests, fakes, eval | none (`world()` defaults to a fixed 16 Nov 09:00 IST) |
| Fakes imported bare | yes (`from r13_fakes_c import …`, `from r11_fakes import …`); no `from tests.` |
| Sizes | largest module `tools.py` 331 lines; longest function under 41 lines |
| Ownership (`git diff --name-only r13-i0..r13-c`) | all 34 files are C's: `wardrobe/styling/**`, `api/outfits.py`, `tests/test_r13_c_*.py`, `tests/r13_fakes_c.py`, `evals/r13/styling.py`, `INTEGRATION-C.md`. No wiring, shared, contract or R11 file |

## Use cases against the workbook

| ID | Holds? | Note |
|---|---|---|
| STY-01 | yes | 23:30 and 00:30 IST, sentences whole. "For the meeting" on a planned day: H3 |
| STY-02, STY-03, STY-04, STY-08, STY-09, STY-11, STY-16 | yes | real tests through the gateway or the engine |
| STY-05 (Diwali) | yes | set mates skip reservations and his exclusions: M1 |
| STY-06 (Holi) | yes | |
| STY-07 (rainy day) | partly | he has no way to say indoor or outdoor; the test writes the sealed doc: M7 |
| STY-10 | state and half pair: yes | the stale-sighting clause is untested and names the UTC day: M2; set mates: M1 |
| STY-12, STY-14 | yes | (lock bypass: security L1) |
| STY-13 | with a declaration | a shared base is never suggested; the later plan shows hard gaps: M5 |
| STY-15 | with a plan id | wearing a planned piece by his words marks the plan and rings `outfit_changed`: H1 |
| STY-17 | start then done: yes | "I wore …" after the fact is refused, `day` is unknown: M6; "done" for a plan misses the substitute: M3 |
| LND-16 | yes | counted as a gap in the evening alert: L2 |
| OPS-04 | yes | a settings toggle from D's panel switches his calendar off: H2 |

## HIGH

### H1. Wearing a planned piece by his words marks the plan "needs a new top" and rings a false `outfit_changed`

**Where:** `src/jarvis/wardrobe/styling/tools.py:245` (the plan link only when `args["plan"]` names one),
`:266-267` (the `query` path), `src/jarvis/wardrobe/styling/wear.py:88-99` (`_candidates`: no "outfit" word),
`src/jarvis/wardrobe/styling/refresh.py:67` ("own" needs `change.plan == plan.id`).

```python
plan = args.get("plan") if doc.plan(str(args.get("plan"))) else None   # tools.py:245
```

**Scenario (P1, reproduced):** today 08:00 IST, a 10:00 meeting plan holds the white shirt. He says "I'm
wearing the white shirt", which D's No-AI router sends as `wear_log(action="start", query="the white shirt")`
(`phrases_r13.py` on `r13-d`). The `wear_started` event has `plan=None`, so the refresh judges the plan's own
shirt as "left":
- the plan is stored with `needs=("top",)` and is not marked worn;
- he gets an important, ringing alert: "A white shirt in today's 10:00 outfit is in use. A ready one is
  suggested in Helpers, Wardrobe.";
- the plan's look now offers a different shirt than the one he has on; his later "done" ("left" again) can
  alert a second time after 2 hours.

"Wearing the meeting outfit" (D20's own example, which D passes as `query="the meeting outfit"`) answers
"I couldn't find "the meeting outfit" in your wardrobe". This is exactly STY-15's "wearing the planned outfit
sends nothing and marks nothing" (H1 of plan review 1); every test passes `plan=` explicitly, so none sees it.

**Fix:**
1. In `StylingTools._start`, link a wear with no plan to the plan it belongs to:
   ```python
   def plan_for(doc: StylingDoc, pieces: Sequence[str], here: Here) -> str | None:
       """The earliest plan of his local today, not over, not worn, that holds a named piece (H1)."""
       found = [p for p in doc.on(here.today)
                if p.active and window(p, here.zone)[1] > here.now and set(pieces) & set(p.pieces())]
       return found[0].id if found else None

   plan = args.get("plan") if doc.plan(str(args.get("plan"))) else plan_for(doc, pieces, here)
   ```
   (The whole-day hold means a non-shared piece is in at most one plan of the day; a shared one is in the
   earlier plan first, which is the one it is worn for.)
2. In `_pieces`, a `query` with the word "outfit" (or "plan") means today's current or next active plan:
   use that plan's look now, as `plan=` does.
3. Tests: "I'm wearing the white shirt" with today's plan holding it: the plan is worn, no `needs`, no alert;
   "wearing the meeting outfit" wears the plan's look.

### H2. A settings toggle in D's panel switches his calendar off and turns every calendar plan manual for good

**Where:** `src/jarvis/api/outfits.py:137-151`; `src/jarvis/wardrobe/styling/calendar.py:258`.

```python
cal_id: str | None = None
if body.calendar is not None: ...          # absent and null are the same: "off"
moved = d.choice.calendar != choice.calendar
out = manual_from_now(d, here.now) if moved and d.choice.calendar else d
```

**Scenario (P2, reproduced):** D's panel (`console-helpers-wardrobe.js:189-212` on `r13-d`) sends each toggle
(title, location, evening alert, auto-swap) with `calendar` deleted from the body, because it cannot know the
chosen reference: `SettingsView` has only `calendar_chosen: bool` and `CalendarChoice` has no "chosen" flag.
With the Work calendar chosen and tomorrow's 10:00 plan made from it, one tap on "Auto-swap" gives:
- `200`, `calendar_chosen: false`: his calendar is off;
- every calendar plan becomes `manual=True` (no `outfit_ready`, no edits, no cancellation);
- re-choosing the same calendar does not bring them back: `sync` skips a manual plan with that event key
  (`calendar.py:258`), so those events never get their 20:00 alert (P2: no alert at 20:00).

**Fix:**
1. Keep what was not sent (`model_fields_set`); an explicit `null` still switches the calendar off:
   ```python
   keep_cal = "calendar" not in body.model_fields_set
   sent = body.model_dump(include=body.model_fields_set - {"calendar"})

   def apply(d: StylingDoc) -> StylingDoc:
       cal = d.choice.calendar if keep_cal else cal_id
       choice = d.choice.model_copy(update={**sent, "calendar": cal})
       moved = d.choice.calendar != cal
       ...
   ```
   and answer `_settings_view` from the stored choice.
2. Needs I1 (contract): `CalendarChoice.chosen: bool` (C sets `ref == self.ref(uid, choice.calendar)`), so
   the panel can show and keep the pick.
3. Optional: when he re-chooses a calendar, `sync` adopts back a manual plan with the same event key that he
   never edited (`plan.manual and plan.tentative and not plan.worn`): `manual=False`.
4. Tests: a PUT without `calendar` keeps the calendar and the plans' `manual=False`; `{"calendar": null}`
   still switches off.

### H3. "What should I wear for the meeting tomorrow" answers with four false "reserved" gaps when the meeting is planned

**Where:** `src/jarvis/wardrobe/styling/tools.py:134`; `src/jarvis/wardrobe/styling/service.py:127-128`.

```python
planned = doc.on(day) if occ is None and code is None else ()   # an occasion: always a fresh look
```

**Scenario (P10, reproduced):** tomorrow's 10:00 client meeting is planned (by hand, or by the calendar, which
plans every meeting by itself). He asks D20's first sentence, "what should I wear for the meeting tomorrow"
→ `outfit_suggest(day="tomorrow", occasion="meeting")`. The fresh look is held off every piece of the very
plan he is asking about:

> Tomorrow, Tuesday 17 November: business formal for a meeting. … Wear: a light blue shirt, a pair of grey
> socks, a black belt and a private basic. No bottom for business formal: wi_000000000005 is reserved for your
> 10:00 event.

with four gaps (bottom, shoes, watch, underwear), all "reserved for your 10:00 event".

**Fix:** answer with the plans of that day whose occasion matches; make a fresh look only when none does:
```python
planned = () if code is not None else tuple(
    p for p in doc.on(day) if occ is None or p.occasion == occ
)
```
Test: a planned meeting, then "for the meeting tomorrow" answers that plan's look with no "reserved" gap.

## MEDIUM

### M1. A festive set's mates are placed without the reservation, exclusion, "never" or formality checks
**Where:** `src/jarvis/wardrobe/styling/engine.py:157-163` (`_place_mates`).
**Scenario (P3, reproduced):** two Diwali plans tomorrow. The morning plan holds the pyjama with another top;
the evening plan picks the kurta and `_place_mates` drops the pyjama into its bottom slot: both plans now hold
`wi_…08` (STY-14's conflict and STY-10's "free for the selected event" both broken). The same path places a
pyjama he excluded (`excluded={pyjama}`: still in the look). `whole()` checks only states.
**Fix:** place a mate only if it passes every step for its slot, else treat the set as not wearable whole:
```python
slot = r.rules.slot_of(r.p(x).type)
if slot is None or slot in r.picks or not all(ok(r, slot, r.p(x)) for _, ok in STEPS):
    continue  # and skip the "set is complete" reason unless every mate was placed
```
(`STEPS` includes "reserved" and "prefs"; move `_place_mates` beside `STEPS` or pass them in to avoid the
import cycle.) Tests: a reserved mate and an excluded mate never enter the look.

### M2. D15: the stale-sighting line names the UTC day, `recent()` mixes a UTC date with his local day, and STY-10's stale clause has no test
**Where:** `src/jarvis/wardrobe/styling/rank.py:122-129` and `:23-26`; `engine.py:142-143` (both uncovered:
`rank.py:26`, `:126`, `engine.py:143`).
**Scenario (P4, reproduced):** the watch was last seen Friday 30 October at 01:00 IST (19:30 UTC on the 29th).
The meeting look says "not seen since **Thursday 29 October**". This is the R14 "Recently deleted" bug D15
says R13 must not repeat (00:00-05:30 IST). `recent()` shifts the "worn in the last 2 days" ranking the same way.
**Fix:** give `Ask` his zone (`zone: tzinfo = UTC`, set in `Styling.ask` from `here.zone`) and use local days:
`seen.astimezone(r.ask.zone).date()` and `p.last_worn.astimezone(r.ask.zone).date()`. Tests: a sighting at
01:00 IST names that local day, the sentence asserted whole; a planned piece unseen for 15 days adds the line.

### M3. `wear_log(action="done", plan=…)` misses the substitute he actually wore
**Where:** `src/jarvis/wardrobe/styling/tools.py:262-265`; `service.py:153-158` (a worn plan answers its stored picks).
**Scenario (P7, reproduced):** the white shirt went to the basket, auto-swap off; he starts the plan (deviation 8:
the light-blue substitute is worn, correctly); in the evening "done" for that plan closes 10 pieces but the
light-blue shirt stays **In use with 0 wears** until the 04:00 sweep (the stored picks still name the white one).
**Fix:** for a worn plan, the pieces of the wear are those In use for it:
```python
if plan is not None and plan.worn:
    return [p.id for p in sorted(view.active(), key=lambda x: x.id)
            if p.state == "in_use" and p.wear == plan.id], ""
```
Test: substitute worn, "done" for the plan → the substitute is In laundry with one wear.

### M4. The rewear rule and the forgotten-wear close exist twice (C and A), and they already disagree
**Where:** C: `rules.json:114-116` (`reusable`), `rules.py:105-110`, `wear.py:134-173` (`close_forgotten`).
A (`r13-a`): `src/jarvis/wardrobe/catalog/jobs.py:34-41` (`WORN_AGAIN`, `after_wear`) and `:82-97` (`_close_wears`).
**Scenario (P6):** the sets differ by `festive_layer`: C returns it to Ready after a wear, A's sweep sends it to
the laundry. A's own closer also has no fixed client id and no `plan` link, while Needs I1 #3 asks I1 to add
C's closer to the same sweep: two closers of one wear with two rules.
**Recommendation (single source):** `rules.json` is the source (D12 puts the rewear defaults there; keep
`festive_layer` reusable: it is the outer layer of a festive set, and outerwear is reusable). At I1 delete A's
`WORN_AGAIN`, `after_wear` and `_close_wears`; A's sweep calls C's `close_forgotten` with the checked rules
from C's built part (`part_of(app, "styling").services["refresh"].styling.rules`), and skips the step when C is
"setup failed" (security L7). Pin it with one I1 test: a forgotten `festive_layer` wear closes to Ready, once.

### M5. Deviation 2 (the whole-day hold) is right for shirts, but a later plan gets hard gaps for reusable pieces and no shared base is ever suggested
**Where:** `src/jarvis/wardrobe/styling/reserve.py:38-39`; `rank.py:83-86` (the "reserved" gap has no next action).
**Scenario (P9, reproduced):** a 09:00 meeting and a 16:00 client review tomorrow, the pilot set: the second
plan says "No bottom / No shoes / No watch / No underwear for business formal: … reserved for your 09:00
event", and its 20:00 alert says "with 4 gaps to fix". The workbook's STY-13 asks the system to *suggest* a
shared base; C only accepts one he declares (`outfit_plan(action="share")`), and nothing tells him that.
**Judgement and fix:** keep the whole-day hold (D3: In use is held until a reusable return or a declared
hand-off). For a reserved unit that the rewear rule reuses (`rules.reusable_piece`) and that an *earlier* plan
of the same day holds, end the gap with its next action: "… reserved for your 09:00 event: share it from that
plan (Helpers, Wardrobe)", and better, offer it as the proposed shared base in the look ("Reused from your
09:00 event, if you share it: …"). Test both.

### M6. STY-17's after-the-fact confirmation is refused, and a stated day is an unknown argument
**Where:** `src/jarvis/wardrobe/styling/tools.py:72-80` (`WEAR`: no `day`), `:228-230`.
**Scenario (P12, reproduced):** "I wore the light blue shirt today" (D20; D sends `wear_log(action="done",
query=…)`) on a Ready shirt: "Nothing named is in use." "I wore it yesterday" (D sends `day="yesterday"`, D4.1
"a stated time … at most 30 days back"): the gateway refuses "unknown arguments: day". The workbook's STY-17
trigger is "Owner confirms what they wore", which is mostly after the fact.
**Fix:** add `day` (`today` | `yesterday` | `YYYY-MM-DD`, ≤ 30 days back, never ahead) to `WEAR`; for a named
piece that is Ready, write `wear_started` + `wear_done` in one commit at the stated day's 12:00 his time (D4.1),
linked to that day's plan when it holds the piece (H1's `plan_for`). Tests for both sentences, one wear each.

### M7. STY-07: he can't say an event is outdoors; the rainy-day test writes the sealed document instead
**Where:** `tools.py:47-63` (no setting in `outfit_suggest` or `outfit_plan`), `actions.py:44-57`,
`service.py:132` (`outdoor` only from a calendar location); `tests/test_r13_c_outlook.py:96-98` and
`evals/r13/styling.py:149-151` set `outdoor=True` through `styling.change`.
**Scenario (P11):** the location field is off by default (the owner's choice), so `Plan.outdoor` is never set
by any product path. Rain-ok shoes and the rain jacket still win the ranking for a casual look, but the hard rule
(rain-ok shoes and an outer layer *required* outdoors, with a gap when there is none) is unreachable, and
"Holi at the society lawn" is not treated as outdoors.
**Fix:** a `setting` argument (`"indoor" | "outdoor"`) on `outfit_plan(save)` and `outfit_suggest`, stored in
`Plan.outdoor`; apply `rules.outdoor_of` to his occasion words too; rewrite the STY-07 test and eval case to go
through the tool.

### M8. Deviation 5: drop `lead_h` now, before any `wardrobe_plans` document exists
**Where:** `src/jarvis/wardrobe/styling/plans.py:130`; `api/outfits.py:119,144`; I0's `http_parts.py:121`,
`http_views.py:131`, `model.py:294`; D's panel sends it (`console-helpers-wardrobe.js:191`).
**Judgement:** the owner chose "the evening before at 20:00" (D19); a stored, audited setting that changes
nothing is a promise the panel can't keep. Drop it, do not define it. Do it before the first deploy:
`Choice` is `extra="forbid"` inside a sealed document, so removing the field later makes every stored
`wardrobe_plans/{uid}` `Unreadable` (security M3), and `OutfitSettings` is `extra="forbid"` too, so D must stop
sending it in the same I1 commit. While there, consider `extra="ignore"` on C's sealed models (`plans._M`,
`calendar._M`, `outlook._M`): a later release that adds a field otherwise makes a rollback to R13 unable to open
C's documents, which is D14's own reason for not touching R11's.

### M9. `rules.json` packaging: the tripwire stays green when the line is missing
**Where:** `tests/test_r13_c_part.py:118-121`; `rules.py:181-184`; `pyproject.toml:82` (no entry).
The image installs non-editable (`Dockerfile:24`, `pip install .`), so without the package-data line the
deployed part is "setup failed" while every test and eval passes from the source tree. The strict `xfail` only
trips once the exact string lands; if I1 forgets, or writes the entry another way, it stays xfailed (green).
**Fix (I1):** land Needs I1 #2; replace the `xfail` by a semantic check (`tomllib`:
`"rules.json" in data["tool"]["setuptools"]["package-data"]["jarvis.wardrobe.styling"]`), and add a build-time
smoke step after the install: `RUN python -c "from jarvis.wardrobe.styling.rules import load_rules; load_rules()"`.

## LOW

- **L1. "Tomorrow" is always "Weather unknown" between 00:00 and 05:00.** `outlook.py:60,80-86`: R11's
  `request_params` asks `forecast_days=2`, so the 18:00 fetch keeps (yesterday, today). Use
  `{**request_params(point, tz), "forecast_days": "3"}` (no R11 edit) and keep 3 days (`max_length=3`).
- **L2. The evening alert counts an LND-16 line as a gap.** `jobs.py:116` with `engine.py:217-221` (P8): a
  complete look says "with 1 gap to fix". Count gaps not starting with "Outstanding:" (deviation 10 stays).
- **L3. "What should I wear today" answers a worn or finished plan.** `tools.py:134`, `api/outfits.py:68`:
  at 18:00 after the 10:00 meeting it says "Worn for your 10:00 event". For today, skip plans whose window has
  ended; fall back to a fresh look.
- **L4. Test gaps.** The fixed client id of `close_forgotten` is never exercised (the third call in
  `test_r13_c_part.py:94-97` returns 0 because the state changed; P5 shows two sweeps from one view make one
  wear: make it a test); `rank.py:26` (recent wear), `engine.py:67,158` (set mates), `jobs.py:136` (calendar
  switched mid-read) are uncovered.
- **L5. Polish.** `texts.tomorrow_of` (`texts.py:176`) is dead code; "HH:MM" is parsed three times
  (`jobs.py:36-38`, `wear.py:129-131`, `service.py:102-111`): one helper; `prefs.py:78` says "left out for
  holi" (the key): use `OCCASION_WORDS` ("for Holi", "for a festival"); the claims prune runs only in the
  00:00-00:05 tick (`jobs.py:69`): a late tick skips the day, use `told.once(uid, f"prune_{today}")`;
  INTEGRATION-C §1 says `tools.py` is 326 lines (it is 331).

## The deviations (§5), judged

| # | Deviation | Verdict |
|---|---|---|
| 1 | His choices in C's sealed `wardrobe_plans` | Accept (C can't write A's index). Needs I1 #4 is **required**, not optional: D's panel builds its PUT from A's `SettingsView`, so until A's view reads C's `Choice` every toggle re-sends A's defaults and silently undoes his other choices. Drop the five fields from A's `WardrobeSettings`: one source |
| 2 | Hold across the whole local day | Accept for pieces that go to the laundry; M5 for reusable ones |
| 3 | `outfit_changed` claim re-claimed every 2 h | Accept |
| 4 | "Twice a day" counts successes; failures retry hourly | Accept (≤ 24 failed calls a day against 10,000) |
| 5 | `lead_h` with no effect | Drop it now (M8) |
| 6 | "Which one: …?" writes nothing | Accept |
| 7 | No live title in the panel | Accept |
| 8 | `wear_log` on a plan wears its look as it is now | Accept for start; "done" misses the substitute (M3) |
| 9 | `outfit_suggest` on a day with plans | Accept for a bare day; wrong with an occasion (H3); ended plans (L3) |
| 10 | LND-16 line in `Look.gaps` | Accept; don't count it in the alert (L2) |
| 11 | More modules under `styling/` | Accept |
| 12 | "Catch-up" is smart casual, tentative | Accept (STY-03) |

## Checked and holding

- **Time (D15).** Every "today" and "tomorrow" is `ctx.now()` in `ctx.zone(uid)`: `Styling.where`, `day_of`,
  calendar plans by local date (00:30 IST is the next day, tested), the 20:00 evening edge, the fetch slots,
  `closing_events`' local midnight and 04:00, `in_range`, `pruned`. Exceptions: M2 only.
- **The rewear rule in C.** `after_wear` matches D12; only reusable pieces can be shared (`reserve.share`);
  the hand-off needs In use + the declared plan + reusable (`engine._handed`), and the refresh's "own",
  "handoff", "later", "back", "left" verdicts follow plan review H1.
- **`close_forgotten`.** Closes only wears started before his local midnight, from 04:00; its client id
  `wclose-<piece>-<day>` (28 characters, inside `CLIENT_ID`) dedups two sweeps from one view (P5).
- **Weather retries.** A failure keeps the slot and waits an hour (`failed_at`), a new place fetches at once,
  success clears it; R11's document is never written (pinned).
- **Engine.** Hard exclusions in a fixed order, ties by piece id, deterministic (tested), a pair only whole,
  his locks kept only while available and unreserved, alternatives vary top, bottom, then shoes.
- **Python.** Frozen pydantic and dataclass records; the only mutable state is the engine's local `Run`
  accumulator; full type hints; no bare `except`; broad catches only at observer and job boundaries, logged
  with class names.

## Change log

| Version | Date | Release | What changed | By |
|---|---|---|---|---|
| v13.0.1 | 16 Nov 2026, 10:07 IST | R13 | First edition: a fresh-context code and Python review of Part C at `r13-c` @ `54f95f4`: 0 CRITICAL, 3 HIGH, 9 MEDIUM, 5 LOW with file:line and exact fixes (12 probes reproduced them), the use cases against the workbook, the twelve deviations judged, the claimed checks re-run; verdict WARNING | 🛠 Mark XXI (code review) |
