Version v13.1.1 · 18 Nov 2026, 03:35 IST · Release R13.1 · Status: Current · Owner: 🛠 Mark XXIII (integrated code review)

# R13.1 I1 integrated code review (fresh context): code-reviewer and python-reviewer

Branch `r13-1-i1` @ `b11205d` against `main` @ `3f265cb` (221 files, +39,092 / −123). Read
first: `CLAUDE.md`, the two reviewer roles, `.claude/rules/ecc/common/*` and `python/*`, the plan
v13.1.3 (size guards, the HTTP contract, D20, D21), `I1-NOTES.md` (40 items), the four
`REVIEW-<X>-1.md` and each `INTEGRATION-<X>.md` Fix section. What those fixed is not repeated
here; where a fix crosses a part boundary, it was checked in the joined code.

## Verdict

**WARNING: 0 CRITICAL, 1 HIGH, 5 MEDIUM, 8 LOW.**

The parts join cleanly in most places: the engine contract (A's `LookSlot` → D's `figure()` →
B's `show()`; `rgb: null`, patterns, templates and variants agree), the `outfit_plan` lock fix
with `pieces` (all or nothing, one change), the one-card cap, the money path (an atomic hold, a
repeated id answered once, release and settle tried three times and kept), versioned
measurements (one transaction, Use bound to the draft seen), and the packaging and CI fixes all
hold. Every size guard holds; no new Python function is over 50 lines.

The one HIGH is on row 388 itself. The try-on card carries the day, the dress code and the
covered slots, and A's look route takes all three. D's console sends none of them. So a card
with no plan is read for **today** with the **default** code. Every piece of tomorrow's look then
reads "Draft: reserved for your plan" whenever today has a plan, and a formal look is drawn
untucked. The e2e eval, the joins test and A's own tests all build the query the way A expects,
not the way D sends it, so nothing catches this.

## How this was checked

- The diff was read part by part, then across the boundaries: R13's `outfit_suggest` →
  `TryOnCard` → `console-media.js` → `console-tryon-card.js` → `console-tryon.js` →
  `GET /v1/tryon/look` → `looks.py` / `options.py`, then `figure()` → B's stage, then confirm →
  `run_panel_tool` → `outfit_plan` lock.
- Size guards: `wc -l` on every guarded file, plus an AST pass over the changed Python for
  functions over 50 lines (the only one is `billing/service.py:248`, 51 lines, unchanged from
  `main`). `ruff check` on the changed packages is clean.
- Targeted tests were run from an export of HEAD at a path without "131" (`/tmp/rev-code-export`,
  3.12, behind the heavy lock): `test_r131_tryon_card`, `lock_fix`, `i1_joins`, `a_looks`,
  `a_confirm` and `i1_wired` gave **87 passed**.
- Three reviewer's probes were run over the real parts. They live in
  `/tmp/rev-i1code-scripts/probe/` and are not committed:
  - the card query with and without the day (H1);
  - lock by slot after the pick went to the laundry (M1);
  - the day look after today's plan was worn (M2).

  Their output is quoted below.

## HIGH

### H1 · Row 388's card is read for today with the default code: tomorrow's look shows every piece as a draft, untucked

**Evidence.**

- `console-tryon.js:563–566` (`dressed`) builds the list from the card's non-private slots only.
  It then calls `lookOf(v, query(list, v.plan))`.
- `console-tryon-list.js:194–195` (`query`) sends `pieces=` and, if there is a plan, `&plan=`.
  It never sends `&day=` or `&code=`, and never sends a covered `slot:` entry.
- A's route takes all three (`api/tryon.py:257–261`), as A's contract says (INTEGRATION-A §7:
  "The card's `plan`, `day` and `code` may come as `&plan=`, `&day=` and `&code=`", and covered
  slots as `slot:`).
- Without them, `looks.for_pieces` (`looks.py:314–323`) takes `day_of(None)`, which is **today**,
  and `rules.code_of(None)`, which is the default code.

**Failure.** It is the evening, today has a plan, and tomorrow has none. He asks "What should I
wear tomorrow?" (or gives a code, which always gives a no-plan card: `styling/tools.py:145`).
The probe built that card from R13's own answer, then read it both ways:

```
CARD 2026-11-18 None business_formal [top, bottom, shoes, socks, belt, watch, outer, base*, underwear*]
CONSOLE day 2026-11-17 code casual tucked False
RIGHT   day 2026-11-18 code business_formal tucked True
top | Draft: reserved for your plan False | Ready True      (and the same for all seven slots)
```

So the card's 3D summary says "Draft: reserved for your plan: this look can't be confirmed until
it is ready." (`console-tryon-list.js:171–172`), and the shirt is drawn untucked for a business
formal look. The same untucked figure shows whenever no plan answered.

There are two more effects:

- A's F6 fix (a covered slot's readiness from its plan, "Draft: in the laundry") is never reached
  from the console, so a private basic that went to the laundry gets no words on the card.
- In the section, swap, undo and compare's second figure use the same `query(list, null)` for a
  look with no plan (`console-tryon.js:285, 294–295, 114`). A swap in "Another idea for
  tomorrow" is then read for today too.

**Why nothing caught it.**

- `evals/r13_1/e2e.py:268–269` (row 388), `tests/test_r131_i1_joins.py:51–53` and
  `tests/test_r131_a_looks.py:128–133` (`card_query`: "as the console sends them") all send
  `slot:` covered entries and `&day=`/`&code=`. The console sends neither.
- D's fakes ignore the day: `r131_fake_server.py:227` and `r131_fakes_d.py:268`.
- The wired browser test only ever has a planned day, so its cards carry a plan.

**Fix.**

- Give `query(list, plan, at)` a third argument. When there is no plan, it adds
  `&day=` + `at.day` and `&code=` + `(at.code || at.dress_code)`. It also adds `slot:` for each
  covered slot it is given.
- `dressed` passes the card, with covered entries from `card.slots`. Swap, undo, refresh and
  compare pass the look itself; A's `TryonLook` has `day` and `dress_code`.
- These are changes to existing lines in `console-tryon.js` (599 of 600); `console-tryon-list.js`
  has room.
- Tests, red first:
  - a wired-app browser test with a plan today and none tomorrow. It asks "What should I wear
    tomorrow?" and checks that the request carries `day=` and `code=`, the rows read Ready, and
    `look.tucked` is true for business formal;
  - make D's fakes compute readiness by the day sent, or refuse a no-plan `pieces=` with no
    `day=`;
  - change `card_query` and the e2e case to build the query from the console's own rule, or
    drive them through it.

## MEDIUM

### M1 · `outfit_plan` lock by slot skips D20's readiness check: a laundry piece is locked with "Done."

**Evidence.** `styling/actions.py:208–211`. The `slot` branch of `_lock` locks the slot's
current pick with no `unready(...)`, while the `piece` and `pieces` branches go through `_one`,
which checks it. Probe, with the plan's shirt moved to the laundry:

```
BY PIECE True The white shirt is in the laundry: it can't be locked into this plan.
BY SLOT  None Done.
STORED ('wi_000000000002',) True
```

**Failure.** "Lock the top for tomorrow's meeting" answers "Done." and stores a locked laundry
shirt. The engine then swaps it out of the look ("… is in the laundry: another one is
suggested"), so the confirmation is false and the plan still holds the piece against other
plans. D20's rule is "lock and reserve refuse a piece that isn't ready".

`transfer` (`actions.py:169–171` → `reserve.transfer`) is a sibling from before R13.1. It locks
the moved piece with no check either; the repick then drops it from the target while the source
has already lost it.

**Fix.** Before locking, check the current pick: `words = unready(s, view, plan, current.pieces)`,
and refuse with `PlanRefused(words)` if it isn't ready. Add one test beside
`test_r131_lock_fix.py::test_a_piece_in_the_laundry_is_refused_and_the_plan_is_unchanged` for
`slot=`. Consider the same check in `transfer`.

### M2 · A's look "by day" takes today's plan even when it is worn: every slot "Draft: in use", and "Another idea" is a 404

**Evidence.**

- `looks.py:301–305` (`for_day`) answers with `r.doc.on(when)[0]`. R13's own rule for "what
  should I wear" (`styling/service.py:115–121`, `planned`) leaves out today's plans that are worn
  or over, and so does C's `pair.look`.
- D's `first()` (`console-tryon.js:493`) also opens today's first saved plan before tomorrow's,
  whatever the hour. R13's `PlanView` has no `worn`, so D can't tell.

The probe, after `wear_log start` on today's plan:

```
DAY LOOK plan op_55a0eeba [('top', 'Draft: in use'), ('bottom', 'Draft: in use'), ...]
ALT1 NoLook: That look isn't there any more: open today's look again.
R13 planned today: ()
```

**Failure.**

- On any normal evening after he wore today's plan, the section opens this morning's outfit with
  every piece a draft, rather than tomorrow's.
- Compare → "Another idea for this day" (`day=today&alt=1`, `console-tryon.js:336`) answers 404
  "That look isn't there any more", because a worn answer has no alternatives.

**Fix.**

- A: `for_day` uses `r.s.planned(r.doc, when, r.here, None)` (the rule `outfit_suggest` uses),
  else `fresh`. Pin it with a test of today's plan worn.
- D: in the evening, look for a plan in Tomorrow first; or add `worn` to R13's `PlanView` (a
  one-field R13 change) and skip a worn plan.

### M3 · AVT-15: the card shows no checklist when `GET /v1/tryon` fails but the look can be read

**Evidence.** `console-tryon.js:564–569`. `if (!S.tryon) await readTryon();` is inside the same
`try` as the look. When the figure document can't be read, the look is never asked for, and the
card draws only the error (`render` shows nothing for `v.look === null`, line 205). A's look does
not need that document: `looks.py:336–340` reads his shape choices tolerantly.

**Failure.** After a key change, `tryon/{uid}` is `Unreadable` (503 `unreadable`). Every "what
should I wear?" card then says "Your try-on data can't be opened on this server…" with no list of
the outfit, though the checklist could be drawn. A storage blip on that one read does the same.

**Fix.**

- Call `readTryon()` in its own `try`. When `S.off` is set, say A's "off" words and stop.
- Otherwise read the look and draw the checklist, with a why of its own (for example
  `'figure'`: "Your figure can't be read just now: here is the checklist."). It needs one WHY
  entry in `console-tryon-list.js`.
- Add a browser test with `GET /v1/tryon` answering 503 `unreadable`.

### M4 · A picture made and billed but not saved says "can't be reached", its retry "isn't there any more", and the audit says ₹0

**Evidence.**

- `wardrobe/seeme/make.py:304–323` (`_keep`) sets `outcome = {"picture": pid}` before `_save`.
  A storage error in `PictureStore.save`'s transaction, or in `Made(...)`/`_doc`'s seal, is not a
  `SeeMeRefused`.
- So the `finally` settles the hold at the billed ₹ with `{"picture": pid}`, and the route's
  generic branch (`api/seeme.py:320–321`) answers 503 `unavailable`, "See it on me can't be
  reached just now. Try again in a minute.", and audits `inr: 0.0`.
- D's retry keeps the same `request_id`. It then finds `done` → `answer` (`make.py:211–219`) →
  404 `gone`, "That picture isn't there any more."

**Failure.** He is charged about ₹9. Neither answer says "It may still be charged", which the
plan's "a cut answer → may be charged" rule and `texts.MAYBE_BILLED` / `WITHDRAWN` say
everywhere else. The audit line under-reports a billed call.

**Fix.**

- In `_keep`, catch `Exception` around building and saving `Made`. Set
  `outcome = {"error": "not_kept"}`, or reuse `maybe_billed`, and raise
  `SeeMeRefused(503, "provider_unavailable", texts.MAYBE_BILLED-style words with the ₹, inr=inr)`.
- Add the code to `REPEATED`, so the retry gets the same words.
- Test it with a `PictureStore.save` that raises.

### M5 · The same rule lives twice, across R13 and A

**Evidence.**

| What | Where |
|---|---|
| "The navy jacket" (`_the`) | `styling/actions.py:64` and `tryon/confirm.py:82` |
| The STY-13 shared-base rule (`_handed`) | `actions.py:69` and `tryon/options.py:82` |
| The readiness check and its words | `actions.unready` (`:77`, with `NOT_READY`) and `options.blocker` (`:99`) + `confirm.words_of` (`:87`) |
| `PRIVATE_SLOTS` | `styling/look.py:24` and `tryon/model.py:172` |
| The AVT-14 covered rule | `tryon/looks.py:94` (`covered`) and `styling/tryon_card.py:31` (`_covered`) |

Two different names `NOT_READY` also exist: a dict at `actions.py:55` and a string at
`options.py:47`. `confirm.py` imports the dict.

**Failure.** The early check (A) and the guarantee (R13) are meant to be the same rule, as D20
says. A change to one leaves A's words and R13's refusal disagreeing: a piece Ready on the figure
but refused by `outfit_plan`, or the reverse. A private slot added to R13 would also be drawn by
the card or by A.

**Fix.**

- Make one home in R13's styling package (for example `styling/ready.py`: `the()`, `handed()`,
  `blocker()`, and the state words). Both `actions.unready` and `options.readiness` /
  `confirm.words_of` then read it.
- `tryon/model.py` imports `PRIVATE_SLOTS` from `styling.look`.
- `tryon_card._covered` calls `tryon.looks.covered`, or both call one helper in `styling.look`.
- Rename one of the two `NOT_READY`.

## LOW

1. **L1 · `settled_inr` is tested but unused.** `seeme/estimate.py:87–91` is pinned by
   `test_r131_c_cap.py:53–55`. The press, however, re-computes the same figure inline
   (`make.py:301`), without `_rate`'s check, so the test pins a helper the money path doesn't
   use. Fix: `inr = settled_inr(...)`, or `call.hold.inr` when it returns None.
2. **L2 · Standard logging in one module.** `styling/tryon_card.py:26` is the only wardrobe module
   on `logging.getLogger`; every other one uses `jarvis.logging.get_logger`. Fix: use
   `get_logger`.
3. **L3 · Card viewers are never let go.** Each reply's card adds a viewer to `S.views` with its
   own `ResizeObserver` (`console-tryon.js:85–87, 556`). None is removed when its row leaves the
   DOM (a new chat, a cleared history), so a long day of "what should I wear?" keeps every
   detached viewer alive. Fix: in `inline`, drop and `ro.disconnect()` every card viewer whose
   `view.isConnected` is false.
4. **L4 · A shared garment picture can be lost.** `console-r7-share.js:175` removes the tray's
   copy as soon as `garment()` resolves. If See it on me's module then fails to load,
   `console-tryon.js:536–538` drops `S.file` with "See it on me couldn't load.", and the picture
   is gone from the phone. Fix: resolve only after `take()` ran, or hand the file back to the
   tray on failure.
5. **L5 · Silent console fallbacks cache a failed read for the page.**
   - `savedList` says "No saved comparisons yet." when the read failed (`console-tryon.js:365`).
   - `photosOf` caches an empty map until a wardrobe refresh (`:59`), so the view cards collapse
     to one photo.
   - `outfits()` caches empty lists (`:327`), so compare offers no plans.

   Fix: say the failure in words with Try again, and leave the cache empty (`null`) after a
   failed read.
6. **L6 · Weak and brittle pins.**
   - `test_r131_i1_wired.py:85` asserts `status_code != 403`, so a 500 passes. Assert the
     expected status and `error` code.
   - `test_r131_i1_console.py` pins exact source strings. The browser tests carry the behaviour,
     so this is acceptable, but any reformat turns these red.
7. **L7 · CI ties B's byte-for-byte rebuild to the face engine's NumPy.** The 3.12 leg installs
   `scipy==1.18.1` (`ci.yml:32`) beside the homebridge extra's `numpy==2.5.4`
   (`pyproject.toml:68`). The script's own pin is `numpy==2.5.3`
   (`scripts/mannequin/requirements-dev.txt:2`). A NumPy bump made for the bridge can turn B's
   determinism test red for a reason unrelated to the figure. Fix: line the two pins up (and pin
   one against the other in a test), or skip the byte-for-byte case unless NumPy is the script's
   pin.
8. **L8 · A needle that matches paths and clocks (outside the diff, pre-existing).**
   `tests/test_r13_i1_evals.py:39` (`assert "131" not in row`) and R7's runner test search log
   rows for "131". I1 saw them fail from any checkout path holding "131", and a millisecond, port
   or thread id can hold it too. Fix: use a needle that can't occur by chance (a fixed 12-hex
   marker).

## What holds (checked across the boundaries)

- **Row 388's server half.** `outfit_suggest` adds ONE card per reply (`_has_room`), only while
  `tryon_enabled`, only in a collecting reply. Piece ids only; a private slot or piece is
  covered, and `TryOnSlot` refuses an id on a private slot. Telegram shows nothing. The model
  never sees the card. The look itself comes from R13's engine: a locked or kept pick stays only
  while available (`engine.py:206–221`), so a laundry piece never reaches the card's pieces.
- **The lock fix with `pieces`.** Every piece is checked by `_one` before any is applied, a slot
  can't be given twice, and the whole lock is one `strict` change. A's confirm sends one piece a
  slot and refuses `left_out` before any call; R13's `refused` result reads as 409, never as
  done.
- **Money.** The hold is reserved atomically, with `busy` and `cap_reached` inside the
  transaction. A repeated id answers its first outcome. Settle and release set `released` before
  the first await, are tried three times, and are kept in `pending` for the next press and the
  job. The overall monthly limit fails closed. Usage is recorded whatever the settle did.
- **Measurements.** One transaction per change, and Use is bound to the draft's `at` (409
  `changed`). `BodyIn` is strict while `Body` reads with `extra="ignore"`.
- **I1's five bugs, and siblings looked for.**
  - Plan ids from `/v1/outfits`: `PLAN.test` sits in `first`, `open`, `chooser` and the hook.
    C's pairer reads R13's service, not the list.
  - A's 503 "off": only `GET /v1/tryon` sets `S.off`. `StylingOff` from the look route does
    not, so a "wardrobe not ready" never hides Try-on.
  - Package data: all six `m1` files and every new `console-tryon*` file match a pattern.
  - Playwright at module top: only the pre-existing `ui_checks.py` has it, behind its users'
    skips.
  - Import-time mutation in `tests/r131_*.py`: none left.
- **Words.** ₹ only, GST in every ₹ shown to him, no "$" in any owner-facing string. Plain words
  throughout.

## Change log

| Version | Date | Release | What changed | By |
|---|---|---|---|---|
| v13.1.1 | 18 Nov 2026, 03:35 IST | R13.1 | Integrated code review (code-reviewer and python-reviewer, fresh context) of `r13-1-i1` @ `b11205d` against `main` @ `3f265cb`: verdict WARNING (0 CRITICAL, 1 HIGH, 5 MEDIUM, 8 LOW). H1: the card's day, dress code and covered slots never reach A's look. M1: lock by slot unchecked. M2: the day look takes a worn plan. M3: no checklist when the figure can't be read. M4: a billed picture not saved says "can't be reached" and audits ₹0. M5: the readiness and AVT-14 rules duplicated. With the checks run (87 targeted tests, three probes, size guards, ruff) and what holds | 🛠 Mark XXIII (integrated code review) |
