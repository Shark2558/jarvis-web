Version v13.0.2 · 16 Nov 2026, 11:30 IST · Release R13 · Status: Current · Owner: 🛠 Mark XXI

# R13 Part B — Laundry: integration notes for I1

Written by the R13 Part B builder in the Workshop (🛠 Mark XXI) on branch `r13-b`, cut from
`r13-i0` @ `3bf2cb1`. The plan is `docs/plans/r13-wardrobe.md` v13.0.2 (Ready), Part B: LND-01–08,
LND-10–15 and OPS-02, with every plan review 1 change that touches B (H1, H4, `due` and
`expected_back`, M1, M3, M4, M5, M10, M11). The owner's "defaults OK" (15 Nov, 18:38 IST) stands:
every safe default below is the plan's unless section 4 says otherwise. Tests were written first
(`88ae139`, red), then the code (`0e2b249`, green).

v13.0.2 adds the fixes for the fresh-context review `REVIEW-B-1.md` (v13.0.1, at `d4a4703`:
WARNING, 0 critical, 4 high, 9 medium, 12 low): H1–H4, M1–M7 and L1–L12 are fixed in B's own
files, each with a test that failed first (section 11); M8 and M9 and the contract halves of H2,
H3 and H4 are I1's (section 6). Part A is fixed in parallel on `r13-a`; as the Workshop decided,
B now refuses the card-only kinds in its own `to_correct` too.

## 1. What Part B built

Everything lives in `src/jarvis/wardrobe/laundry/` and `src/jarvis/api/laundry.py`, plugged in
through `part.build(ctx)` only. Every change is ONE commit of A's store (`WardrobeStore.transact`):
the events, the sealed laundry document and the review queue together (D4.4, H4).

| Use case | What Part B does | Where | Named tests |
|---|---|---|---|
| LND-01 | "To laundry": `deposited` (a piece he is wearing: `wear_done` to In laundry, its plan named, H1); stays owned, leaves ready pieces | `holds.plan_basket`, `basket_event` | `test_lnd_01_a_deposit_keeps_the_shirt_owned_but_out_of_ready_pieces`, `test_h1_a_worn_shirt_into_the_basket_closes_its_wear_for_its_plan` |
| LND-02 | A deposit exists only when he presses: a card he leaves writes nothing, his press writes one verified tap deposit; `holds.admit` (a `camera` deposit without a release seen is unverified, held, with its entry) is a unit until I1 moves it into A's store (6.3) | `holds.admit`, `writer` | `test_lnd_02_only_his_press_deposits_and_a_card_he_cancels_writes_nothing`, `test_lnd_02_the_camera_rule_a_deposit_without_a_release_is_held` |
| LND-03 | "and N more I couldn't show" (`more` + `category`): a pending deposit with NO piece id; holds only the plausible pieces (that category, In use or worn in the last 24 h); none plausible: an entry, no hold | `holds.plausible`, `holds.pending` | `test_lnd_03_a_jacket_hiding_a_shirt_is_one_deposit_and_one_pending_deposit`, `…_with_no_plausible_piece_holds_nothing`, `…_he_says_which_one_and_its_wear_is_closed`, `test_plausible_pieces_are_the_ones_in_use_or_worn_in_the_last_day` |
| LND-04 | Identical copies (`one_of`, or a `query` that fits several): both withheld until he says which (only Ready or In use candidates; one at the shop or in the basket is refused); "there was no deposit" clears each to `back_to`; a piece another check holds is never released by this one | `holds.pending`, `holds.check_one_of`, `resolve._pending` | `test_lnd_04_two_near_identical_shirts_are_both_withheld_until_he_says`, `test_lnd_04_there_was_no_deposit_clears_both_to_their_last_verified_state`, `test_a_piece_held_by_another_check_is_never_released_by_this_one`, `test_l8_picking_a_piece_another_check_holds_is_refused_in_its_own_words` |
| LND-05 | `laundry_correct` runs through B's own commit: the `corrected` event A's `correct()` builds, and B's loads, batches and checks follow it in the same commit; the card-only kinds (A's `CARD_ONLY`) are refused; a correction that leaves the piece held reopens its check (H3 stop-gap) | `corrections.plan_correct`, `history.to_correct`, `review.reopen`, `flows.Desk.correct` | `test_lnd_05_correcting_an_old_basket_event_never_overwrites_a_later_clean_return`, the 7 tests of `test_r13_b_correct.py`, three `test_lnd_05_…` in `test_r13_b_lifecycle.py` |
| LND-06 | "lifted": still In laundry, a new place, still unavailable | `loads.plan_step` | `test_lnd_06_…` |
| LND-07 | A load holds only the confirmed ids he names; the load and its `load_started` events in one commit; a failed write leaves neither; a piece not in the basket refused | `loads._start` | `test_lnd_07_a_mixed_load_…_in_one_commit`, `…_a_failed_write_leaves_neither…`, `…_a_load_takes_only_pieces_that_are_in_the_basket` |
| LND-08 | Each step moves only the pieces named; a piece not in that load refused; a load alone moves its washing pieces (the phone form of "finished") | `loads._pieces` | three `test_lnd_08_…` |
| LND-10 | Damp (Drying) and "needs pressing" (Needs prep) stay unavailable until returned | `loads._events` | `test_lnd_10_…` |
| LND-11 | A clean return keeps the id, takes the place he names, and the plan check (C's observer) hears `returned` once | `loads`, A's observers | `test_lnd_11_…` |
| LND-12 | Parts of a load come back separately; the load closes when every piece is back or has left the laundry | `loads._returned`, `settle` | `test_lnd_12_…` |
| LND-13 | A half pair: the clean sock stays in inventory, the pair stays out until both are ready; B never re-pairs | `history.half_pairs` | `test_lnd_13_…` |
| LND-14 | Outside batches: his shop label (≤ 40 characters, at most 4 digits in all, no "@", nothing that reads as an ID), a bag reference, `due` on each `sent_out` (A's `expected_back`); a worn piece closes its wear for its plan first (M2); each piece back on its own, only with its own `received` (a held one is refused, M3); one he says is home comes off its batch; "short" and "overdue"; never an order, a call or a payment | `providers`, `jobs` | `test_r13_b_outside.py` (LND-14, M2, M3, L6), `test_an_overdue_batch_is_told_once_a_day_in_fixed_words` |
| LND-15 | One piece's history: the state, "Drying since 11:05" in his local day, the latest verified movement in the words of the state it really took (L11), the corrections, the last 10 events with their marks; his place label fenced (M5) | `history.piece_history`, `when_words` | three `test_lnd_15_…`, `test_since_words_use_his_local_day_at_the_midnight_edges` (23:30 / 00:30 IST, a year end), `test_l11_…`, `test_m5_…` |
| OPS-02 | "I moved things without scanning" (places or categories, the start he states; today before noon: now): every piece at rest there gets a `blind` hold, in checks of at most 200; a piece another check holds is on the check's `waiting` list and is held again when that check lets it go unverified (M4); answered piece by piece by a scan, a label or a tap; a second report holds nothing twice | `blind.plan_blind`, `blind.rehold`, `blind.settle`, `resolve._hold` | five `test_ops_02_…`, three `test_ops_02_m4_…`, `test_l4_…`, two `test_l5_…` |
| H4 | A hold is written with its entry in the same commit; B's `review_writer` (bound into A's store), its per-commit staging held weakly by the `tx` | `writer.LaundryWriter` | `test_h4_…`, `test_two_calls_in_one_commit_see_each_other_…`, `test_a_writer_without_a_key_writes_nothing_and_the_commit_rolls_back`, `test_l7_…` |
| M3 | A tap and a scan of one deposit make one change and no entry; a retry with the same client id is "already done", for a load, a send and a receive too (L3) | `flows._stamp`, `desk._retried` | `test_m3_a_tap_and_a_scan_of_one_deposit_make_one_change_and_no_entry`, two `test_l3_…` |

Also built: the review queue's every answer (`resolve.py`: `these`, `none`, `moved`, `dismiss`
for each entry kind; `test_r13_b_resolve.py`), the 100-entry cap (the oldest stale checks fold into
"check this place"; a hold or a pending deposit is never dropped), the five tools, `laundry_daily`,
B's `WardrobeData`, the two routes, and the eval part.

**The tools** (`tools.py`, schemas and checks in `checks.py`, card words in `cards.py`):

| Tool | Risk | Flags | What |
|---|---|---|---|
| `laundry_status` | R1 | `may_vouch` | the lists (≤ 20 pieces, `more` beyond), loads, batches, half pairs, open checks; or one piece's history (`piece` or `query`). Vouches only when every batch label was typed (a spoken or outside label never vouches) |
| `laundry_move` | R2 | `spoken_ok` | `step` basket / lifted / load / washing / drying / prep / ready with `pieces`, or D10's `query`, `one_of`, `more` + `category`, `place`, `load`, `rev`, `client_id` |
| `laundry_review` | R2 | — | `list`, `resolve` (`entry`, `outcome`, `pieces`, `to`, `place`, `how`: honoured from the panel only), `blind` (`places`, `categories`, `since` or `day`) |
| `laundry_correct` | R2 | — | `piece`, optional `event` |
| `laundry_send_out` | R2 | — | `send` (`pieces`, `shop`, `bag`, `due`) or `receive` (`batch`, `pieces`, `to`); `client_id` for both |

No schema offers `via`: where a tap came from is worked out from the call's context (Telegram, a
spoken turn, a chat turn, else his panel), and the gateway refuses an argument a schema doesn't
name (L1). Every result fences his words (piece labels, place labels, shop labels; masked on a
spoken or Telegram turn) and shows a private piece as its slot and "a private basic"
(`redact.model_view`). Every card's words come from `preview` through `redact.card_words` (his
label's number when the piece has one; private pieces with none are counted, L12), never his
label, a shop label or the words he typed; a look-up that finds nothing still writes a card. A
record past its limits is refused in plain words. Activity shows fixed words. No argument could
order, pay, call or send anything.

**The job** `laundry_daily` (morning tick, budget 20 s): `laundry_overdue` once a batch a day
past its `due`, once for a batch that came back short with no `due`; `wardrobe_review` (info)
once a day for checks opened before his local today; each alert claimed in
`wardrobe_told/{uid}_laundry_…` before the send and kept only when he has it, by the codebase's
one rule (`selfwatch.texts.reached`: a channel took it, it waits in the held summary, or his own
setting dropped it); anything else, a send that raised or one the tick's budget cancelled gives
the claim back (H4). A send that raises counts as `failed`, so the tick reports the job failed
and R14's self-health hears it (M6). The sweep: closed loads and batches after 90 days, answered
checks after `wardrobe_review_keep_days`, B's claims after 30 days. Off without a key; one
owner's failure stops no one.

**The routes** (`api/laundry.py`): `GET /v1/laundry` (`LaundryView`) and `GET /v1/laundry/review`
(`ReviewView`), exactly the contract's two rows, owner-only, `no-store`, 60 reads a minute per
owner, 503 `{"detail": …}` in plain words when B is left out ("Laundry isn't set up yet."), off
("Laundry is off: this server has no token key.") or A's store isn't there ("The wardrobe isn't
ready yet: try again in a minute.").

## 2. What it keeps (prefix `jarvis_`; all named in card C70 by I0)

| Collection | Holds | Sealed |
|---|---|---|
| `wardrobe_laundry/{uid}` | `{v, kid, blob, updated_at}`: open loads (≤ 50) and batches (≤ 20); closed ones 90 days. AAD `wardrobe/laundry/{uid}/v1` | `wardrobe` |
| `wardrobe_review/{uid}` | `{v, kid, blob, updated_at}`: the queue (≤ 100 open, answered ones `wardrobe_review_keep_days`); a blind check's `waiting` list is inside the blob (v13.0.2, a default, so older documents read as before). AAD `wardrobe/review/{uid}/v1` | `wardrobe` |
| `wardrobe_told/{uid}_laundry_…` | `{uid, part: "laundry", updated_at}`; the key is ids and a day only | no |

Events carry ids only (`load`, `batch`, `place`, `plan`); B never sets an event's `note`. Logs
carry class names and counts only. A document that can't be opened is never overwritten. Privacy's
delete needs no key (the documents and the claims are found and deleted without one); without a
key, count and export say plainly that records remain and can still be deleted, never "0" (M7).

## 3. The seams Part B offers and relies on

- **`services["review_writer"]`** (`LaundryWriter`, a `ReviewWriter`): `entries(uid, view, tx,
  needed)` reads the queue through `tx` and answers one `Set` of the whole sealed document, or
  nothing when every need is covered (its event already listed, or its piece already held by an
  open entry). Each answer is **staged on that `tx` object** (held weakly: it goes with the
  commit, L7), so a second call in the same commit starts from it. Two rules of A's contract make
  that safe (the ports docstring says them; I1 should pin them, section 6.2): A passes the SAME
  `tx` object to `fn` and to the writer, and A writes `extra` before the writer's entries. A
  reason word B doesn't know gets its kind's safe default (`review.REASONS`), so another part's
  need never fails A's commit.
- **For C** (stale checks, OPS-02's second half, STY-10): inside C's own `transact` `fn`, call
  `ops = await writer.entries(uid, view, tx, [ReviewNeeded("stale", piece, reason="stale")])` and
  return `ops` in `Commit.extra` (tested: `test_two_calls_in_one_commit_see_each_other_…`). C's
  refresh hears B's changes with these kinds: `deposited` (plan None), `wear_done` (the wear's
  plan: wearing for that plan, no change), `sent_out` (a worn piece: the wear's plan too, M2),
  `held` (a plausible piece of a pending deposit), `blind`, `load_started`, `dried`,
  `needs_prep`, `returned`, `received`, `released`, `found`, `corrected`.
- **For A**: `holds.admit(event)` (LND-02) for phone and camera events (section 6.3); the
  sweep's repair works with any reason since H2 (B matches the piece's own hold), and I1 should
  still pass `reason=p.hold` (6.8). B no longer calls A's `correct()`: it commits the same
  `corrected` event through `transact` with its own records (section 5, deviation 8).
- **For D**: the panel's changes call B's tools through `POST /v1/wardrobe/tools/{tool}`. The
  answers each entry kind takes (until the contract carries them, section 6.6):

| `ReviewEntry.kind` (`words`) | Answers |
|---|---|
| `pending_deposit` | `these` + `pieces` (from `candidates`; any piece when there are none; at most the count), `none` |
| `hold` (any reason, `sweep` too) | `these` (as it was; an unconfirmed change: it did happen), `moved` + `to` (+ `place`; never `with_provider`); `none` only when the piece's own hold is an unconfirmed change |
| `rescan`, "Moved without a scan: check these." | `these` (+ `pieces`: these are where they were), `moved` + `to` (+ `place`); refused while it only waits for pieces another check holds ("answer that one first") |
| `rescan`, "Which of these did you mean?" with its step (B's own) | `these` + one of `candidates`, `none`, `dismiss` |
| `rescan`, any other ("Two later steps disagree: check this piece.", a plain check) | `these` (a sighting where it is), `moved` + `place`, `dismiss` |
| `conflict` | `dismiss` (or `these` / `none`: noted) |
| `stale`, `place` | `these` (+ `pieces`: seen where it is), `moved` + `place`, `dismiss` |

## 4. Decisions taken in Part B (safe defaults)

1. **Plausible** (LND-03): the named category, In use, or Ready with `last_worn` within 24 hours;
   never one already in the laundry, held, out or archived.
2. **A name he says** matches strictly: every word he said (after `belongings.text.thing_key`:
   plurals, a leading "my" or "the") must be one of the piece's own words (its label, colour,
   type and pattern words; "t-shirt", "tshirt" and "tee" are one). Only pieces that can take the
   step count; one: that piece; several: never a guess (the basket: a pending deposit with holds;
   another step: a "which one?" entry that holds nothing). A piece named by id and by his words
   counts once (L2).
3. **Answering a pending deposit** releases this entry's own holds (`released` to `back_to`) and
   records the basket for the pieces he names in the same commit (`wear_done` for a piece he was
   wearing). A piece held by another check is refused, never released.
4. **A confirmed unverified change** is recorded again as his verified word (the event the entry
   names, else the piece's newest one the fold marked `held`, read from A's history before the
   commit).
5. **At rest** for a blind period: Ready, In laundry, Needs prep (not washing, drying, out). A
   piece another check holds is on the blind check's `waiting` list; when that check lets it go
   back to a state at rest unverified, it is held again for the blind check; when he verifies it
   (a deposit he names, a `found`, a confirmed change) it leaves the list.
6. **Times**: B's taps are the server's now (one clock rule, M1: B never sends a device time); a
   stated start is at most 30 days back and never ahead; a stated day is 12:00 his time, or now
   when the day is today and noon hasn't come (L4).
7. **"Already done"** only when every event was a duplicate or a retry AND nothing of B's was
   written (a closed check is a change); a retry with the same client id is "already done" before
   any state check (L3). "Done" only when something was done: a check answered another way
   meanwhile says "Nothing to change" (H2).
8. **Due dates**: from his today up to 60 days ahead.
9. **Ready words**: "Laundry on: the basket, loads, outside laundry and the review queue", or
   "Laundry off: this server has no token key".
10. **Where a tap came from** (`via`) is the call's context, never an argument; `how` (`qr`,
    `label`, …) is honoured from his panel only, the model's call is a tap (L1).
11. **A shop's label and a bag reference** hold at most 4 digits in all, however spaced or split,
    and no "@" (L6).
12. **Striking out a step** (LND-05, M1): a load start takes the piece out of its load (an emptied
    load is gone); a send-out takes it off its batch (an emptied batch is gone, one with nothing
    out closes); a `received` or `returned` puts it back on its batch or load (reopened); a hold
    shrinks the check that holds it, closed when nothing is left to ask (a pending deposit stays).
13. **A big blind report** is held in checks of at most 200 pieces, one commit each (Entry's cap,
    under Firestore's 500 writes a commit), up to the wardrobe's piece cap (L5).
14. **A release's words** in one piece's history: the piece's own state when nothing has moved it
    since, else "Back as it was before its check" (L11).

## 5. Deviations from the plan, and why

1. **Three modules beyond the plan's file list** (`checks.py`, `cards.py`, `resolve.py`, all in
   `wardrobe/laundry/`): the 400-line guard. `review.py` (the queue) and `resolve.py` (answering it)
   were one file at 425 lines; the tool schemas and card words would have made `tools.py` ≈ 550.
   Accepted by REVIEW-B-1.
2. **Blind holds are recorded at the moment he reports**, and the start he states is kept on the
   entry (`since`). A back-dated hold would turn a later verified event into a conflict ("later
   verified events stay authoritative", D4.3); the hold is about now. Accepted.
3. **A batch that came back short with no `due` is told once**, not every day. D19 says "once a
   batch a day" for the kind; the failure table says "a batch with no due date never alerts". A
   short batch with no due date has no day to count from, and a daily line he cannot stop (there
   is no "write off") would be noise. Overdue stays once a batch a day. Accepted, and since H4 the
   once-only alert is kept only when he has it.
4. **A shop label from a round that read other people's content is refused before any card** (and
   at run time for a card proposed in such a round): R11's UPI rule. Stricter than the plan; it
   keeps an outside label out of the approvals store and out of his batches. Accepted.
5. **Place labels are fenced** in tool results, like piece labels (his words). Accepted; the one
   path that missed it (one piece's history) is fixed (M5).
6. **The blind report is an action of `laundry_review`** (`action: "blind"`); the plan names no
   tool for it and the 18 names are fixed. Accepted.
7. **Two more modules** (v13.0.2): `corrections.py` (LND-05's planner and the reconciliation of
   B's records, M1) and `desk.py` (`DeskCore`: the one commit and the reads, split from
   `flows.py` at 387 of its 400 lines). Every import path stays (`flows.Desk`, `flows.Done`).
8. **B commits its own `corrected` event** (v13.0.2, M1) instead of calling A's `correct()`, so
   B's loads, batches and checks change in the same commit as the ledger. The event is the one
   A's `correct()` builds (`kind="corrected"`, `voids`, `source="tap"`), and B refuses A's
   `CARD_ONLY` kinds (`registered`, `archived`, `restored`, `merged`, `corrected`) with A's words.
   If I1 changes A's correction rules, B's `corrections.CARD_ONLY` follows (or the contract
   offers one builder both use).
9. **`Entry.waiting`** (v13.0.2, M4): a field of B's own sealed queue (not the contract), default
   empty.
10. **`laundry_send_out` takes a `client_id`** (v13.0.2, L3), like `laundry_move`, so the panel's
    send and receive can be retried safely; no schema offers `via` any more (L1).

## 6. Needs I1 (exact diffs and the review's recommended options)

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

REVIEW-B-1: right as written, add it. A conformance case for `tests/test_r13_fold_conformance.py`
(every store, A's too):

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

### 6.3 LND-02's camera rule into the contract, applied by A's store (M9)

- Move `holds.admit` into the contract beside the table (`wardrobe/states.py` or `model.py`, pure).
- **A's store** applies it inside `transact` to every incoming event (not the route), so no caller
  can skip it; a conformance case: "a camera deposit without a release seen is held, with its
  entry, in the same commit".
- In the same change, `POST /v1/wardrobe/scan` refuses `source="camera"` and `evidence.released`
  until R8, and takes only the checkpoint kinds (`registered`, `seen`, `deposited`, `wear_*`,
  `returned`, `lifted`): B stays the only writer of the kinds its documents track (`held`,
  `released`, `blind`, `load_started`, `sent_out`, `received`, `found`), so the scan route can't
  clear a hold behind its entry or start "washing" outside any load.
- B's `holds.admit` then becomes a re-export of the contract's, or goes.

### 6.4 A's fold refreshes `place_at` on every verified sighting (M8)

A verified, non-voided `seen` sets `place_at = e.at`, including one at the same place; its mark
stays `duplicate` (no entry, no observer, so M3's "one change" holds). Add a conformance case. C
keeps reading `place_at` (not the history: that would be a log read per planned piece on every
5-minute clock). Until then, B's `these` answer to a stale check records the sighting in his
history but C flags the piece stale again the next day.

### 6.5 The needles eval (I1's)

A shop's label is his words. Allowed places, like a piece label's: tool results for the model,
fenced; and, on a SPOKEN turn only, a `laundry_send_out` card's stored arguments (the card's text
comes from `preview` in fixed words; a tainted round is refused before any card). Proposed: list
that second place beside D10's `query` exception.

### 6.6 What `ReviewEntry` carries for D's panel

Backward compatible (defaults); B fills them when the contract has them:

```diff
 class ReviewEntry(_M):
     id: str
     kind: Literal["hold", "conflict", "pending_deposit", "stale", "rescan", "place"]
     pieces: tuple[PieceId, ...] = ()
     candidates: tuple[PieceId, ...] = ()
     words: str  # fixed words ("Which of these went into the basket?")
     opened_at: datetime
+    reason: Literal[
+        "", "unverified", "held", "missing", "restored", "blind", "which", "pending", "refused",
+        "stale", "corrected", "sweep", "rescan",
+    ] = ""  # the closed set: B's `review.REASONS` ("rescan": a rescan that names none)
+    count: int = Field(default=0, ge=0, le=20)  # a pending deposit: how many he couldn't show
+    answers: tuple[Literal["these", "none", "moved", "dismiss"], ...] = ()  # one shared function
```

`answers` comes from ONE function shared with `resolve._OUTCOMES` and `_family` (the piece's own
hold decides `none`), so the panel and the resolver can't drift. B's half is done: a reason word
outside the set gets its kind's safe default instead of failing A's commit.

### 6.7 The fold asks for a hold entry after a correction (H3)

The fold emits `ReviewNeeded("hold", piece, <corrected id>, back_to=f.back_to, reason=f.hold)`
when a `corrected` event leaves the piece held and it wasn't held before: one line in the
reference fold (`tests/r13_fakes_store.py` `_need`), one in A's `_refold`, and a conformance case
"striking out a release reopens its check, in the same commit". B's stop-gap (`Desk._reopen`, a
second commit) then finds the piece covered and writes nothing; it can stay as a backstop or go.

### 6.8 A's sweep passes the piece's own hold (H2)

`wardrobe_sweep`'s repair: `ReviewNeeded("hold", pid, back_to=p.back_to, reason=p.hold)` instead
of `reason="sweep"`, so the repaired entry's words say why. B already answers a sweep entry by
the piece's own hold.

### 6.9 `took` as one shared rule in `notify/ports.py` (H4)

Lift `selfwatch.texts.reached` (and `home.watchdog.took`'s idle form, `notify/sink.py`'s
`result_of`) into `notify/ports.py` as one `took(delivery)`: a channel took it, it waits in the
held summary, or his own setting (`switched_off`, `feed_only`) dropped it. B imports
`selfwatch.texts.reached` until then (`laundry/jobs.py`).

### 6.10 D's panel calls B's tools with names B's schemas don't take

On `r13-d` (read here, not changed): `console-helpers-wardrobe.js` calls `laundry_review` with
`piece: id` and `none: true` (B takes `pieces: [id]` and `outcome: "these" | "none"`), and
`console-wardrobe-scan.js` calls `laundry_move` with `unseen` (B takes `more`). The gateway
refuses an argument a schema doesn't name, so those presses would fail. I1 aligns D's calls with
B's schemas (and section 3's answers table).

### 6.11 Nothing else

No wiring file, contract file, shared file or earlier release's test was edited. The skill
register, the permission rows, the Telegram patterns, the alert kinds and the guide already had
everything B uses (I0). `evals/r13/run.py` needs nothing (`laundry` is BUILT).

## 7. Checks (this worktree, 16 Nov 2026, Python 3.11, behind `/tmp/heavy.lock`)

Re-run for v13.0.2 at `f08909ee` (a frozen copy) and `4e506451` (the checkout); every run behind
the shared lock.

| Check | Result |
|---|---|
| `pytest tests/test_r13_b_*.py` (14 files) | **221 passed**, 0 skipped (162 at v13.0.1) |
| Branch coverage, `jarvis.wardrobe.laundry` + `jarvis.api.laundry` | **95 %** (every module ≥ 89 %; `corrections.py` 93 %) |
| `pytest tests/test_r13_seams.py tests/test_r13_wiring.py tests/test_r13_fold_conformance.py tests/test_telegram_tool_guard.py` | 331 passed, **2 failed: the two I0 pins of 6.1** (expected; the only failures) |
| Tests that see every tool or row: `test_r14_skill_coverage`, `test_permissions_policy`, `test_telegram_personal_reads`, `test_test_imports`, `test_r11_1_b_guard`, `test_activity_words`, `test_activity_words_r2`, `test_r14_seams`, `test_r2_seams` | 576 passed |
| `evals/r13/run.py --mock --part laundry` | **15/15**; control "holds off" failed the suite (exactly `lnd_03`, `lnd_04`, `ops_02`) |
| `ruff check`, `ruff format --check` (B's 36 files) | clean |
| `mypy src` (strict, 810 files) | 1 error: the baseline's (`memory/redis_store.py:67`) |
| `scripts/arch_coverage.py`, `scripts/check_doc_versions.py` | OK (109 collections); 29 documents pass; this file and `REVIEW-B-1.md` checked with the same rules (`problems()`): OK |
| Mutation (L8): the held-elsewhere refusal removed in a scratch copy | caught by `test_l8_…` (the older suite stayed green) |
| Sizes | every module ≤ 400 (largest `texts.py` 339); every function ≤ 50 lines (largest 40); no real clock under `wardrobe/` |

| File | Lines | File | Lines |
|---|---|---|---|
| `wardrobe/laundry/texts.py` | 339 | `wardrobe/laundry/providers.py` | 241 |
| `wardrobe/laundry/store.py` | 313 | `wardrobe/laundry/history.py` | 204 |
| `wardrobe/laundry/holds.py` | 276 | `wardrobe/laundry/desk.py` | 189 |
| `wardrobe/laundry/tools.py` | 273 | `wardrobe/laundry/jobs.py` | 165 |
| `wardrobe/laundry/review.py` | 272 | `wardrobe/laundry/cards.py` | 155 |
| `wardrobe/laundry/checks.py` | 257 | `wardrobe/laundry/blind.py` | 146 |
| `wardrobe/laundry/flows.py` | 251 | `wardrobe/laundry/corrections.py` | 135 |
| `wardrobe/laundry/resolve.py` | 243 | `wardrobe/laundry/writer.py` | 77 |
| `wardrobe/laundry/loads.py` | 242 | `api/laundry.py` | 66 |
| `evals/r13/laundry.py` | 247 | `wardrobe/laundry/part.py` | 43 |

## 8. Reviews still owed (never the builder's own)

REVIEW-B-1 (code, Python, security and silent failures, fresh context) is answered in section 11.
These fixes need their own fresh-context re-review (`code-reviewer`, `python-reviewer`, and
`security-reviewer` for the tool argument changes, the shop-label rule and the Privacy delete).
None was run here: the builder does not review his own work.

## 9. Blocked actions

None. No push was refused, nothing touched `main`, no force-push, no edit to a lint, type or
coverage file.

## 10. Not verified here

A's real store with B's writer bound (6.2's two lines, its conformance, Firestore's retries with
the staging); B's own `corrected` event in A's real `transact` (the reference store only);
Firestore's real transaction sizes for a 50-piece load or a 200-piece blind check; D's panel
drawing the queue and its answers (6.10); the notifier's real ring, hold and Telegram delivery of
`laundry_overdue` and `wardrobe_review`; a real camera event (LND-02's camera half is later); the
needles eval and the end-to-end tests 1–4 (I1's).

## 11. REVIEW-B-1 findings

Every fix is in B's own files, with a test that failed before it (or, for L8, a mutation that the
new test catches and the old suite missed). Commits are on `r13-b`.

| ID | Fix | Test | Commit |
|---|---|---|---|
| H1 | Only B's own "which one?" (reason `which` and its step) takes a laundry step; every other rescan is a check (sighting, place, dismiss); `_which` refuses an entry without its step; words for A's "corrected" | `test_h1_as_rescan_answered_these_is_a_sighting_never_a_clean_return`, `test_h1_any_other_rescan_is_a_check_that_may_be_moved_or_dismissed`, `test_h1_a_which_entry_without_its_step_takes_no_laundry_step` | `ccc90d02` |
| H2 | A hold is matched on the piece's own hold; `none` and the confirm read it; the original is the entry's event, else the newest `held`-marked one; "Nothing to change: it was answered another way" when nothing was released | `test_h2_a_hold_the_sweep_repaired_is_released_by_these`, `test_h2_a_sweep_repaired_unverified_change_keeps_none_and_its_confirm` (2), `test_h2_a_hold_answered_another_way_never_says_done` | `061ba01b` |
| H3 | Stop-gap: a correction that leaves the piece held with no open entry gets its hold entry in a second commit (`review.reopen`); the atomic fix is I1's (6.7) | `test_lnd_05_striking_out_a_release_reopens_its_check`, `…_a_correction_that_leaves_no_hold_opens_nothing`, `…_a_correction_beside_an_open_check_opens_no_second_one` | `04bab8f3` |
| H4 | The claim stands only by `selfwatch.texts.reached`; it goes back in a `finally` with `asyncio.shield`, so a cancelled send is retried too | `test_h4_a_once_only_alert_no_channel_took_is_tried_again_at_the_next_run`, `test_h4_told_is_the_codebases_one_rule` (5), `test_h4_a_send_the_ticks_budget_cancels_gives_its_claim_back` | `43d76db4` |
| M1 | `laundry_correct` through B's own commit (`corrections.plan_correct`): loads, batches, `received` / `returned` and checks follow the struck-out step; card-only kinds refused | the 7 tests of `test_r13_b_correct.py` | `52d164e0` |
| M2 | A worn piece sent out: `wear_done` (its plan) before `sent_out` (its plan) | `test_h1_a_worn_blazer_to_the_dry_cleaner_closes_its_wear_for_its_plan` | `94373bb3` |
| M3 | A receive refuses a held piece and one not at the shop, and marks back only with `received`; `with_provider` out of `FOUND_TO` and refused; `one_of` only Ready or In use; a piece he says is home comes off its batch | `test_m3_a_piece_held_meanwhile_is_never_marked_back_without_its_return`, `test_m3_a_piece_from_the_shop_he_says_is_home_comes_off_its_batch`, `test_m3_a_check_never_lands_a_piece_at_the_shop_without_a_batch`, `test_m3_one_of_never_holds_a_piece_at_the_shop_or_already_in_the_basket` | `fdf0a3a0` |
| M4 | A blind check lists the pieces another check holds (`waiting`); a release path holds them again (`released` + `blind`) or, when he verifies them, drops them; the check stays open while it waits; "already" only when a blind check covers every touched piece | three `test_ops_02_m4_…` | `6e04157c` |
| M5 | One piece's history: the piece through `cards.fenced`, the top-level place fenced (masked when spoken); a private piece has no place | `test_m5_one_pieces_history_fences_its_place_and_a_private_piece_has_none` | `90ce0669` |
| M6 | A notifier that raises counts as `failed`: the tick reports the job failed | `test_m6_a_notifier_that_raises_is_a_job_failure_self_health_sees` | `b044ba12` |
| M7 | Privacy's delete needs no key; count and export say plainly what remains without one | `test_m7_without_a_key_delete_still_deletes_and_count_says_what_remains` | `29a9c468` |
| M8 | I1: `place_at` on every verified sighting (6.4) | — | — |
| M9 | I1: `admit` in A's store, the scan route's kinds and camera source (6.3) | — | — |
| L1 | `via` from the call's context, out of every schema; `how` from the panel only | `test_l1_the_model_cannot_say_where_a_tap_came_from_or_how_it_was_checked` | `ba63f2c2` |
| L2 | Ids de-duplicated when a query matches a piece already named | `test_l2_a_piece_named_by_id_and_by_his_words_is_counted_once` | `98f4fe27` |
| L3 | `DeskCore._retried`: a retried client id is "already done" before any state check; `laundry_send_out` takes `client_id` | `test_l3_a_retried_load_send_or_receive_is_already_done`, `test_l3_the_send_out_tool_takes_the_panels_client_id` | `98f4fe27` |
| L4 | A blind day of today starts at min(noon, now) | `test_l4_a_blind_report_for_today_before_noon_starts_now` | `b2673ea6` |
| L5 | Blind reports in chunks of 200 (one check and one commit each); a record past its limits is refused in plain words | `test_l5_a_blind_report_over_200_pieces_is_held_in_checks_of_at_most_200`, `test_l5_a_record_too_big_to_note_is_refused_in_plain_words` | `b2673ea6` |
| L6 | A shop label or a bag reference: at most 4 digits in all, no "@" | `test_a_shop_label_never_holds_a_phone_number_and_stays_short` (11 cases), `test_l6_a_bag_reference_holds_no_long_number_or_address` (2) | `64842c48` |
| L7 | The writer's staging is a `WeakKeyDictionary` keyed by the `tx` | `test_l7_a_commits_staging_goes_with_its_transaction` | `97f79619` |
| L8 | The held-elsewhere refusal pinned by its words (mutation: caught by the new test, missed by the old suite); LND-02's phone half real; its camera half named as a unit until 6.3 | `test_l8_picking_a_piece_another_check_holds_is_refused_in_its_own_words`, `test_lnd_02_only_his_press_deposits_and_a_card_he_cancels_writes_nothing`, `test_lnd_02_the_camera_rule_a_deposit_without_a_release_is_held` | `f08909ee` |
| L9 | An unknown check id: "That check isn't in your list." | `test_l9_a_check_that_never_existed_is_not_in_his_list` | `558777b7` |
| L10 | A resolve's `place` must be one of his | `test_l10_an_answer_names_only_one_of_his_places` | `558777b7` |
| L11 | A verified step's words are the state the piece really took | `test_l11_the_latest_verified_step_says_where_it_really_went` | `558777b7` |
| L12 | Card words through `redact.card_words` with his label's number; private pieces with none are counted | `test_l12_two_private_pieces_on_a_card_are_never_twins` | `0f98cba0` |
| 6.6 (B's half) | A reason word B doesn't know gets its kind's safe default | `test_a_reason_word_b_does_not_know_never_fails_the_commit` | `11bdeb5a` |

Also: `134fb22b` (refactor: `desk.py` split from `flows.py`, no behaviour change) and `4e506451`
(LND-05's corrections covered, 79 % to 93 %). Declined:
none. Partly I1's: H2 (A's sweep, 6.8), H3 (the fold, 6.7), H4 (the shared rule, 6.9), L8's
camera half (6.3).

## Change log

| Version | Date | Release | What changed | By |
|---|---|---|---|---|
| v13.0.1 | 15 Nov 2026, 21:30 IST | R13 | First edition: what Part B built per use case with its named tests, what it keeps, the seams it offers (the writer's per-commit staging, C's stale checks, A's `admit` and sweep, D's answers), its decisions, six deviations with reasons, Needs I1 with exact diffs (I0's two pins, two lines of A's contract, A's scan route, `place_at`, the needles eval, an optional `ReviewEntry` change), every check with its numbers, the reviews still owed | 🛠 Mark XXI |
| v13.0.2 | 16 Nov 2026, 11:30 IST | R13 | REVIEW-B-1's fixes: H1–H4, M1–M7, L1–L12 and B's half of 6.6 in B's own files, each with a test that failed first (section 11's findings table with commits); the use-case table, tools, job, storage, seams and answers updated; decisions 10–14; deviations 7–10 (two more modules, B's own `corrected` commit, `Entry.waiting`, `client_id` on the send-out tool); Needs I1 rewritten with the review's recommended options (`admit` in A's store and the scan route, `place_at`, `ReviewEntry`'s closed `reason`, `count` and shared `answers`, the fold's hold need after a correction, A's sweep reason, one shared `took`, D's argument names); the checks re-run | 🛠 Mark XXI |
