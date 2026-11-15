Version v13.0.1 · 15 Nov 2026, 21:30 IST · Release R13 · Status: Current · Owner: 🛠 Mark XXI

# R13 Part B — Laundry: integration notes for I1

Written by the R13 Part B builder in the Workshop (🛠 Mark XXI) on branch `r13-b`, cut from
`r13-i0` @ `3bf2cb1`. The plan is `docs/plans/r13-wardrobe.md` v13.0.2 (Ready), Part B: LND-01–08,
LND-10–15 and OPS-02, with every plan review 1 change that touches B (H1, H4, `due` and
`expected_back`, M1, M3, M4, M5, M10, M11). The owner's "defaults OK" (15 Nov, 18:38 IST) stands:
every safe default below is the plan's unless section 4 says otherwise. Tests were written first
(`88ae139`, red), then the code (`0e2b249`, green).

## 1. What Part B built

Everything lives in `src/jarvis/wardrobe/laundry/` and `src/jarvis/api/laundry.py`, plugged in
through `part.build(ctx)` only. Every change is ONE commit of A's store (`WardrobeStore.transact`):
the events, the sealed laundry document and the review queue together (D4.4, H4).

| Use case | What Part B does | Where | Named tests |
|---|---|---|---|
| LND-01 | "To laundry": `deposited` (a piece he is wearing: `wear_done` to In laundry, its plan named, H1); stays owned, leaves ready pieces | `holds.plan_basket`, `basket_event` | `test_lnd_01_a_deposit_keeps_the_shirt_owned_but_out_of_ready_pieces`, `test_h1_a_worn_shirt_into_the_basket_closes_its_wear_for_its_plan` |
| LND-02 | A deposit exists only when he presses (a cancelled scan sends nothing); `holds.admit`: a `camera` deposit without a release seen is unverified, so the fold holds it and B's writer opens its entry | `holds.admit`, `writer` | `test_lnd_02_a_cancelled_scan_sends_nothing_and_a_camera_deposit_needs_a_release` |
| LND-03 | "and N more I couldn't show" (`more` + `category`): a pending deposit with NO piece id; holds only the plausible pieces (that category, In use or worn in the last 24 h); none plausible: an entry, no hold | `holds.plausible`, `holds.pending` | `test_lnd_03_a_jacket_hiding_a_shirt_is_one_deposit_and_one_pending_deposit`, `…_with_no_plausible_piece_holds_nothing`, `…_he_says_which_one_and_its_wear_is_closed`, `test_plausible_pieces_are_the_ones_in_use_or_worn_in_the_last_day` |
| LND-04 | Identical copies (`one_of`, or a `query` that fits several): both withheld until he says which; "there was no deposit" clears each to `back_to`; a piece another check holds is never released by this one | `holds.pending`, `resolve._pending` | `test_lnd_04_two_near_identical_shirts_are_both_withheld_until_he_says`, `test_lnd_04_there_was_no_deposit_clears_both_to_their_last_verified_state`, `test_a_piece_held_by_another_check_is_never_released_by_this_one` |
| LND-05 | `laundry_correct` through A's `correct()` (the newest step unless an event id is given) | `flows.Desk.correct`, `history.to_correct` | `test_lnd_05_correcting_an_old_basket_event_never_overwrites_a_later_clean_return` |
| LND-06 | "lifted": still In laundry, a new place, still unavailable | `loads.plan_step` | `test_lnd_06_…` |
| LND-07 | A load holds only the confirmed ids he names; the load and its `load_started` events in one commit; a failed write leaves neither; a piece not in the basket refused | `loads._start` | `test_lnd_07_a_mixed_load_…_in_one_commit`, `…_a_failed_write_leaves_neither…`, `…_a_load_takes_only_pieces_that_are_in_the_basket` |
| LND-08 | Each step moves only the pieces named; a piece not in that load refused; a load alone moves its washing pieces (the phone form of "finished") | `loads._pieces` | three `test_lnd_08_…` |
| LND-10 | Damp (Drying) and "needs pressing" (Needs prep) stay unavailable until returned | `loads._events` | `test_lnd_10_…` |
| LND-11 | A clean return keeps the id, takes the place he names, and the plan check (C's observer) hears `returned` once | `loads`, A's observers | `test_lnd_11_…` |
| LND-12 | Parts of a load come back separately; the load closes when every piece is back or has left the laundry | `loads._returned`, `settle` | `test_lnd_12_…` |
| LND-13 | A half pair: the clean sock stays in inventory, the pair stays out until both are ready; B never re-pairs | `history.half_pairs` | `test_lnd_13_…` |
| LND-14 | Outside batches: his shop label (≤ 40, no run of 5+ digits, nothing that reads as an ID), a bag reference, `due` on each `sent_out` (A's `expected_back`), each piece back on its own (`ready` or `needs_prep`), "short" and "overdue"; never an order, a call or a payment | `providers`, `jobs` | six tests in `test_r13_b_outside.py`, `test_an_overdue_batch_is_told_once_a_day_in_fixed_words` |
| LND-15 | One piece's history: the state, "Drying since 11:05" in his local day, the latest verified movement, the corrections, the last 10 events with their marks | `history.piece_history`, `when_words` | three `test_lnd_15_…`, `test_since_words_use_his_local_day_at_the_midnight_edges` (23:30 / 00:30 IST, a year end) |
| OPS-02 | "I moved things without scanning" (places or categories, the start he states): every piece at rest there gets a `blind` hold and one "check these" entry; answered piece by piece by a scan, a label or a tap; a second report holds nothing twice | `blind.plan_blind`, `resolve._hold` | five `test_ops_02_…` |
| H4 | A hold is written with its entry in the same commit; B's `review_writer` (bound into A's store) | `writer.LaundryWriter` | `test_h4_…`, `test_two_calls_in_one_commit_see_each_other_…`, `test_a_writer_without_a_key_writes_nothing_and_the_commit_rolls_back` |
| M3 | A tap and a scan of one deposit make one change and no entry; a retry with the same client id is applied once ("already done") | `flows._stamp` | `test_m3_a_tap_and_a_scan_of_one_deposit_make_one_change_and_no_entry` |

Also built: the review queue's every answer (`resolve.py`: `these`, `none`, `moved`, `dismiss`
for each entry kind; 13 tests in `test_r13_b_resolve.py`), the 100-entry cap (the oldest stale
checks fold into "check this place"; a hold or a pending deposit is never dropped), the five
tools, `laundry_daily`, B's `WardrobeData`, the two routes, and the eval part.

**The tools** (`tools.py`, schemas and checks in `checks.py`, card words in `cards.py`):

| Tool | Risk | Flags | What |
|---|---|---|---|
| `laundry_status` | R1 | `may_vouch` | the lists (≤ 20 pieces, `more` beyond), loads, batches, half pairs, open checks; or one piece's history (`piece` or `query`). Vouches only when every batch label was typed (a spoken or outside label never vouches) |
| `laundry_move` | R2 | `spoken_ok` | `step` basket / lifted / load / washing / drying / prep / ready with `pieces`, or D10's `query`, `one_of`, `more` + `category`, `place`, `load`, `rev`, `client_id`, `via` |
| `laundry_review` | R2 | — | `list`, `resolve` (`entry`, `outcome`, `pieces`, `to`, `place`, `how`), `blind` (`places`, `categories`, `since` or `day`) |
| `laundry_correct` | R2 | — | `piece`, optional `event` |
| `laundry_send_out` | R2 | — | `send` (`pieces`, `shop`, `bag`, `due`) or `receive` (`batch`, `pieces`, `to`) |

Every result fences his words (piece labels, place labels, shop labels; masked on a spoken or
Telegram turn) and shows a private piece as its slot and "a private basic" (`redact.model_view`).
Every card's words come from `preview` through `redact.fixed_words` (never his label, a shop
label or the words he typed); a look-up that finds nothing still writes a card. Activity shows
fixed words. No argument could order, pay, call or send anything.

**The job** `laundry_daily` (morning tick, budget 20 s): `laundry_overdue` once a batch a day
past its `due`, once for a batch that came back short with no `due`; `wardrobe_review` (info)
once a day for checks opened before his local today; claims (`wardrobe_told/{uid}_laundry_…`)
written before the send and released when the send raises; the sweep (closed loads and batches
after 90 days, answered checks after `wardrobe_review_keep_days`, B's claims after 30 days). Off
without a key; one owner's failure stops no one.

**The routes** (`api/laundry.py`): `GET /v1/laundry` (`LaundryView`) and `GET /v1/laundry/review`
(`ReviewView`), exactly the contract's two rows, owner-only, `no-store`, 60 reads a minute per
owner, 503 `{"detail": …}` in plain words when B is left out ("Laundry isn't set up yet."), off
("Laundry is off: this server has no token key.") or A's store isn't there ("The wardrobe isn't
ready yet: try again in a minute.").

## 2. What it keeps (prefix `jarvis_`; all named in card C70 by I0)

| Collection | Holds | Sealed |
|---|---|---|
| `wardrobe_laundry/{uid}` | `{v, kid, blob, updated_at}`: open loads (≤ 50) and batches (≤ 20); closed ones 90 days. AAD `wardrobe/laundry/{uid}/v1` | `wardrobe` |
| `wardrobe_review/{uid}` | `{v, kid, blob, updated_at}`: the queue (≤ 100 open, answered ones `wardrobe_review_keep_days`). AAD `wardrobe/review/{uid}/v1` | `wardrobe` |
| `wardrobe_told/{uid}_laundry_…` | `{uid, part: "laundry", updated_at}`; the key is ids and a day only | no |

Events carry ids only (`load`, `batch`, `place`, `plan`); B never sets an event's `note`. Logs
carry class names and counts only. A document that can't be opened is never overwritten.

## 3. The seams Part B offers and relies on

- **`services["review_writer"]`** (`LaundryWriter`, a `ReviewWriter`): `entries(uid, view, tx,
  needed)` reads the queue through `tx` and answers one `Set` of the whole sealed document, or
  nothing when every need is covered (its event already listed, or its piece already held by an
  open entry). Each answer is **staged on that `tx` object**, so a second call in the same commit
  starts from it. Two rules of A's contract make that safe (the ports docstring says them; I1
  should pin them, section 6.2): A passes the SAME `tx` object to `fn` and to the writer, and A
  writes `extra` before the writer's entries.
- **For C** (stale checks, OPS-02's second half, STY-10): inside C's own `transact` `fn`, call
  `ops = await writer.entries(uid, view, tx, [ReviewNeeded("stale", piece, reason="stale")])` and
  return `ops` in `Commit.extra` (tested: `test_two_calls_in_one_commit_see_each_other_…`). C's
  refresh hears B's changes with these kinds: `deposited` (plan None), `wear_done` (the wear's
  plan: wearing for that plan, no change), `held` (a plausible piece of a pending deposit), `blind`,
  `load_started`, `dried`, `needs_prep`, `returned`, `sent_out`, `received`, `released`, `found`.
- **For A**: `holds.admit(event)` (LND-02) for phone and camera events (section 6.3); the sweep's
  repair can pass every held piece as `ReviewNeeded("hold", pid, None, back_to=…, reason=hold)`:
  the writer is idempotent on held pieces.
- **For D**: the panel's changes call B's tools through `POST /v1/wardrobe/tools/{tool}`. The
  answers each entry kind takes (until the contract carries them, section 6.6):

| `ReviewEntry.kind` (`words`) | Answers |
|---|---|
| `pending_deposit` | `these` + `pieces` (from `candidates`; any piece when there are none; at most the count), `none` |
| `hold` | `these` (as it was; an unconfirmed change: it did happen), `moved` + `to` (+ `place`); `none` only for "A change JARVIS couldn't confirm" |
| `rescan`, "Moved without a scan" | `these` (+ `pieces`: these are where they were), `moved` + `to` (+ `place`) |
| `rescan`, "Which of these did you mean?" | `these` + one of `candidates`, `none`, `dismiss` |
| `conflict` | `dismiss` (or `these` / `none`: noted) |
| `stale`, `place` | `these` (+ `pieces`: seen where it is), `moved` + `place`, `dismiss` |

## 4. Decisions taken in Part B (safe defaults)

1. **Plausible** (LND-03): the named category, In use, or Ready with `last_worn` within 24 hours;
   never one already in the laundry, held, out or archived.
2. **A name he says** matches strictly: every word he said (after `belongings.text.thing_key`:
   plurals, a leading "my" or "the") must be one of the piece's own words (its label, colour,
   type and pattern words; "t-shirt", "tshirt" and "tee" are one). Only pieces that can take the
   step count; one: that piece; several: never a guess (the basket: a pending deposit with holds;
   another step: a "which one?" entry that holds nothing).
3. **Answering a pending deposit** releases this entry's own holds (`released` to `back_to`) and
   records the basket for the pieces he names in the same commit (`wear_done` for a piece he was
   wearing). A piece held by another check is refused, never released.
4. **A confirmed unverified change** is recorded again as his verified word (the original event is
   read from A's history before the commit).
5. **At rest** for a blind period: Ready, In laundry, Needs prep (not washing, drying, out or
   already waiting for a check).
6. **Times**: B's taps are the server's now (one clock rule, M1: B never sends a device time); a
   stated start is at most 30 days back and never ahead; a stated day is 12:00 his time.
7. **"Already done"** only when every event was a duplicate or a retry AND nothing of B's was
   written (a closed check is a change).
8. **Due dates**: from his today up to 60 days ahead.
9. **Ready words**: "Laundry on: the basket, loads, outside laundry and the review queue", or
   "Laundry off: this server has no token key".

## 5. Deviations from the plan, and why

1. **Three modules beyond the plan's file list** (`checks.py`, `cards.py`, `resolve.py`, all in
   `wardrobe/laundry/`): the 400-line guard. `review.py` (the queue) and `resolve.py` (answering it)
   were one file at 425 lines; the tool schemas and card words would have made `tools.py` ≈ 550.
2. **Blind holds are recorded at the moment he reports**, and the start he states is kept on the
   entry (`since`). A back-dated hold would turn a later verified event into a conflict ("later
   verified events stay authoritative", D4.3); the hold is about now.
3. **A batch that came back short with no `due` is told once**, not every day. D19 says "once a
   batch a day" for the kind; the failure table says "a batch with no due date never alerts". A
   short batch with no due date has no day to count from, and a daily line he cannot stop (there
   is no "write off") would be noise. Overdue stays once a batch a day.
4. **A shop label from a round that read other people's content is refused before any card** (and
   at run time for a card proposed in such a round): R11's UPI rule. Stricter than the plan; it
   keeps an outside label out of the approvals store and out of his batches.
5. **Place labels are fenced** in tool results, like piece labels (his words).
6. **The blind report is an action of `laundry_review`** (`action: "blind"`); the plan names no
   tool for it and the 18 names are fixed.

## 6. Needs I1 (exact diffs)

### 6.1 I0's pins that move now that Part B is built

`tests/test_r13_wiring.py` assumes every part says "not built yet"; with B built (and A, C, D
later) two tests fail on this branch (the only failures in the seam, wiring, conformance and
Telegram runs). Proposed:

```diff
@@ def test_every_stub_part_builds_through_the_real_modules(settings: Settings) -> None:
     parts = wiring.build_parts(_ctx(settings))
     assert tuple(parts) == PARTS
-    assert {p.ready for p in parts.values()} == {"not built yet"}
+    assert all(p.ready != wiring.SETUP_FAILED for p in parts.values())
@@ async def test_the_app_builds_the_four_parts_and_answers_v1_r13(settings: Settings) -> None:
-        assert [(p["part"], p["ready"]) for p in body["parts"]] == [
-            (n, "not built yet") for n in PARTS
-        ]
+        assert [p["part"] for p in body["parts"]] == list(PARTS)
+        assert all(p["ready"] != wiring.SETUP_FAILED for p in body["parts"])
```

### 6.2 Pin the two lines of A's contract B's writer stands on

A conformance case for `tests/test_r13_fold_conformance.py` (every store, A's too):

```python
async def test_the_writer_sees_the_tx_fn_saw_and_its_entries_land_after_extra(rig: Rig) -> None:
    await rig.register(SHIRT)
    seen: list[object] = []

    class Writer:
        async def entries(self, uid, view, tx, needed):  # type: ignore[no-untyped-def]
            seen.append(tx)
            return [Set(REVIEW_DOC, {"from": "writer"})]

    rig.store.bind(review_writer=Writer(), observers=[])

    async def fn(view: object, tx: object) -> Commit:
        seen.append(tx)
        held = ev(SHIRT, "deposited", rig.clock(), verified=False)
        return Commit(events=(held,), extra=(Set(REVIEW_DOC, {"from": "extra"}),))

    await rig.store.transact(UID, fn)
    assert seen[0] is seen[1]  # one tx object for fn and the writer
    assert await rig.docs.get(REVIEW_DOC) == {"from": "writer"}  # entries last
```

### 6.3 A's scan route: LND-02's camera rule

`POST /v1/wardrobe/scan` (A) passes each event through `jarvis.wardrobe.laundry.holds.admit`
before `transact` (a `camera` deposit without `released` becomes unverified: held, with B's
entry). Or I1 moves `admit` into `wardrobe/states.py` beside the table, as one line of the
contract. Until then phone events are unaffected (`admit` changes only `source == "camera"`).

### 6.4 A's fold and `place_at`

A verified `seen` at the piece's current place is a `duplicate` in the reference fold, so
`place_at` does not move. Answering a stale check with `these` records that sighting (it is in
his history, `how` qr / tap) but `place_at` stays old. If C's 14-day check reads `place_at`, A's
fold should refresh `place_at` on a verified `seen` at the same place (a conformance case), or C
reads the latest verified sighting from the history. I1 decides; B needs nothing either way.

### 6.5 The needles eval (I1's)

A shop's label is his words. Allowed places, like a piece label's: tool results for the model,
fenced; and, on a SPOKEN turn only, a `laundry_send_out` card's stored arguments (the card's text
comes from `preview` in fixed words; a tainted round is refused before any card). Proposed: list
that second place beside D10's `query` exception.

### 6.6 Optional: what `ReviewEntry` could carry for D's panel

Backward compatible (defaults); B fills them when the contract has them:

```diff
 class ReviewEntry(_M):
     id: str
     kind: Literal["hold", "conflict", "pending_deposit", "stale", "rescan", "place"]
     pieces: tuple[PieceId, ...] = ()
     candidates: tuple[PieceId, ...] = ()
     words: str  # fixed words ("Which of these went into the basket?")
     opened_at: datetime
+    reason: str = ""  # unverified, held, missing, restored, blind, which, pending, refused, stale
+    count: int = Field(default=0, ge=0, le=20)  # a pending deposit: how many he couldn't show
+    answers: tuple[Literal["these", "none", "moved", "dismiss"], ...] = ()  # what fits (3.)
```

### 6.7 Nothing else

No wiring file, contract file, shared file or earlier release's test was edited. The skill
register, the permission rows, the Telegram patterns, the alert kinds and the guide already had
everything B uses (I0). `evals/r13/run.py` needs nothing (`laundry` is BUILT).

## 7. Checks (this worktree, 15 Nov 2026, Python 3.11, behind `/tmp/heavy.lock`)

| Check | Result |
|---|---|
| `pytest tests/test_r13_b_*.py` (13 files) | **162 passed**, 0 skipped |
| Branch coverage, `jarvis.wardrobe.laundry` + `jarvis.api.laundry` | **94 %** (every module ≥ 89 %) |
| `pytest tests/test_r13_seams.py tests/test_r13_wiring.py tests/test_r13_fold_conformance.py tests/test_telegram_tool_guard.py` | 329 passed, **2 failed: the two I0 pins of 6.1** (expected) |
| Tests that see every tool or row: `test_r14_skill_coverage`, `test_permissions_policy`, `test_telegram_personal_reads`, `test_test_imports`, `test_r11_1_b_guard`, `test_activity_words`, `test_activity_words_r2`, `test_r14_seams`, `test_r2_seams` | 576 passed |
| `evals/r13/run.py --mock --part laundry` | **15/15**; control "holds off" failed exactly `lnd_03`, `lnd_04`, `ops_02` |
| `evals/r13/run.py --mock` (all parts, staged) | 33/33; negative control failed the suite |
| `ruff check`, `ruff format --check` (B's files) | clean |
| `mypy src` (strict) | 1 error: the baseline's (`memory/redis_store.py:67`) |
| `scripts/arch_coverage.py`, `scripts/check_doc_versions.py` | OK (109 collections); 29 documents pass; this file checked with the same rules (`problems()`): OK |
| Mutation spot-checks (cap off, wear not closed, load membership off, shop number check off, another check's hold released) | each caught by a named test |
| Sizes | every module ≤ 400 (largest `flows.py` 355); every function ≤ 50 lines; no real clock under `wardrobe/` |

| File | Lines | File | Lines |
|---|---|---|---|
| `wardrobe/laundry/flows.py` | 355 | `wardrobe/laundry/providers.py` | 212 |
| `wardrobe/laundry/texts.py` | 315 | `wardrobe/laundry/history.py` | 190 |
| `wardrobe/laundry/store.py` | 299 | `wardrobe/laundry/jobs.py` | 147 |
| `wardrobe/laundry/holds.py` | 264 | `wardrobe/laundry/cards.py` | 127 |
| `wardrobe/laundry/checks.py` | 256 | `wardrobe/laundry/blind.py` | 82 |
| `wardrobe/laundry/tools.py` | 252 | `wardrobe/laundry/writer.py` | 80 |
| `wardrobe/laundry/loads.py` | 242 | `api/laundry.py` | 66 |
| `wardrobe/laundry/review.py` | 230 | `wardrobe/laundry/part.py` | 43 |
| `wardrobe/laundry/resolve.py` | 227 | `evals/r13/laundry.py` | 247 |

## 8. Reviews still owed (never the builder's own)

`code-reviewer` and `python-reviewer` in a fresh context (CLAUDE.md), and `security-reviewer`
because B adds tools (the taint rule on shop labels, the card words, the sealed documents, the
writer inside A's commit). None was run here: the builder does not review his own work and this
session has no agent to hand it to.

## 9. Blocked actions

None. No push was refused, nothing touched `main`, no force-push, no edit to a lint, type or
coverage file.

## 10. Not verified here

A's real store with B's writer bound (6.2's two lines, its conformance, Firestore's retries with
the staging); Firestore's real transaction sizes for a 50-piece load; D's panel drawing the queue
and its answers; the notifier's real ring, hold and Telegram delivery of `laundry_overdue` and
`wardrobe_review`; a real camera event (LND-02's camera half is later); the needles eval and the
end-to-end tests 1–4 (I1's).

## Change log

| Version | Date | Release | What changed | By |
|---|---|---|---|---|
| v13.0.1 | 15 Nov 2026, 21:30 IST | R13 | First edition: what Part B built per use case with its named tests, what it keeps, the seams it offers (the writer's per-commit staging, C's stale checks, A's `admit` and sweep, D's answers), its decisions, six deviations with reasons, Needs I1 with exact diffs (I0's two pins, two lines of A's contract, A's scan route, `place_at`, the needles eval, an optional `ReviewEntry` change), every check with its numbers, the reviews still owed | 🛠 Mark XXI |
