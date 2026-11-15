# tests/test_r13_b_writer.py -- R13 Part B's `review_writer` (docs/plans/r13-wardrobe.md D4.4, D11,
# plan review H4): bound into A's store, it writes every `ReviewNeeded`'s entry in the SAME commit
# as the event (a hold never lives without the entry that resolves it); a need already covered is
# never written twice; two writers' calls in one commit see each other (C's stale check beside the
# fold's holds); past 100 open entries the oldest stale checks fold into one "check this place"
# entry and a pending deposit or a hold is never dropped; without a key it writes nothing in clear.
from __future__ import annotations

from datetime import timedelta

import pytest
from r13_fakes import UID, FixedClock, ev, ist
from r13_fakes_b import BELT, NAVY_SHIRT, RACK, TEE, TRAY, WATCH, WHITE_SHIRT, rig

from jarvis.storage.docs import DocTx
from jarvis.wardrobe.laundry import review
from jarvis.wardrobe.laundry.holds import admit
from jarvis.wardrobe.laundry.store import Entry, LaundryUnavailable, ReviewDoc
from jarvis.wardrobe.model import WardrobeView
from jarvis.wardrobe.ports import Commit, ReviewNeeded


async def test_h4_an_unverified_change_is_held_with_its_entry_in_one_commit() -> None:
    r = await rig()
    commits = len(r.docs.tx_sizes)
    await r.commit(admit(ev(TEE, "deposited", r.clock(), source="camera")))
    assert len(r.docs.tx_sizes) == commits + 1
    (entry,) = await r.open_entries()
    assert (entry.kind, entry.reason, entry.pieces, entry.back_to) == (
        "hold",
        "unverified",
        (TEE,),
        "ready",
    )
    assert review.words_of(entry) == "A change JARVIS couldn't confirm: check this piece."


async def test_a_conflict_asks_for_an_entry_and_holds_nothing() -> None:
    r = await rig()
    await r.commit(ev(TEE, "dried", r.clock()))  # Ready can't be dried: the table refuses it
    (entry,) = await r.open_entries()
    assert entry.kind == "conflict" and entry.pieces == () and entry.candidates == (TEE,)
    assert await r.state(TEE) == "ready"


@pytest.mark.parametrize(
    ("kind", "reason", "words"),
    [
        ("held", "held", "On hold until you check it."),
        ("missing", "missing", "Missing: tell JARVIS where it is."),
        ("blind", "blind", "Moved without a scan: check it."),
    ],
)
async def test_each_hold_reason_has_its_fixed_words(kind: str, reason: str, words: str) -> None:
    r = await rig()
    await r.commit(ev(BELT, kind, r.clock()))  # type: ignore[arg-type]
    (entry,) = await r.open_entries()
    assert entry.reason == reason and review.words_of(entry) == words and entry.pieces == (BELT,)


async def test_a_need_already_covered_is_never_written_twice() -> None:
    r = await rig()
    await r.commit(admit(ev(TEE, "deposited", r.clock(), source="camera")))
    (entry,) = await r.open_entries()
    view = await r.view()

    async def again(v: WardrobeView, tx: DocTx) -> Commit:
        need = ReviewNeeded("hold", TEE, entry.events[0], back_to="ready", reason="unverified")
        same = ReviewNeeded("hold", TEE, None, back_to="ready", reason="unverified")
        return Commit(extra=tuple(await r.writer.entries(UID, view, tx, [need, same])))

    await r.store.transact(UID, again)
    assert await r.open_entries() == (entry,)


async def test_two_calls_in_one_commit_see_each_other_cs_stale_check_beside_the_folds_hold() -> (
    None
):
    r = await rig()

    async def fn(view: WardrobeView, tx: DocTx) -> Commit:
        stale = ReviewNeeded("stale", BELT, reason="stale")
        ops = await r.writer.entries(UID, view, tx, [stale])
        deposit = admit(ev(TEE, "deposited", r.clock(), source="camera"))
        return Commit(events=(deposit,), extra=tuple(ops))

    await r.store.transact(UID, fn)
    kinds = sorted((e.kind, e.pieces or e.candidates) for e in await r.open_entries())
    assert kinds == [("hold", (TEE,)), ("stale", (BELT,))]
    (stale_entry,) = [e for e in await r.open_entries() if e.kind == "stale"]
    assert review.words_of(stale_entry) == "Not seen for a while: a quick check, please."
    assert stale_entry.pieces == ()  # a stale check holds nothing


async def test_a_writer_without_a_key_writes_nothing_and_the_commit_rolls_back() -> None:
    r = await rig(keyring=False)
    with pytest.raises(LaundryUnavailable) as off:
        await r.commit(admit(ev(TEE, "deposited", r.clock(), source="camera")))
    assert str(off.value) == "Laundry is off: this server has no token key."
    assert await r.state(TEE) == "ready"  # the hold never lands without its entry


async def test_the_review_document_is_sealed_with_updated_at() -> None:
    r = await rig()
    await r.commit(admit(ev(NAVY_SHIRT, "deposited", r.clock(), source="camera")))
    raw = await r.docs.get(r.desk.store.review_path(UID))
    assert raw is not None and set(raw) == {"v", "kid", "blob", "updated_at"}
    assert NAVY_SHIRT not in repr(raw) and "unverified" not in repr(raw)


# ---- the cap (pure) ---------------------------------------------------------------------------
def _entry(n: int, kind: str, *, place: str | None = None, at_min: int = 0) -> Entry:
    t0 = ist(2026, 11, 1, 9, 0)
    pid = f"wi_{n:012x}"
    return Entry.model_validate(
        {
            "id": f"rv_{n:010x}",
            "kind": kind,
            "reason": kind,
            "pieces": () if kind in ("stale", "conflict") else (pid,),
            "candidates": (pid,),
            "place": place,
            "opened_at": t0 + timedelta(minutes=at_min),
        }
    )


def test_past_100_open_entries_the_oldest_stale_checks_fold_into_place_checks() -> None:
    now = FixedClock(ist(2026, 11, 16, 9, 0))()
    stale = [_entry(i, "stale", place=(RACK if i % 2 else TRAY), at_min=i) for i in range(1, 98)]
    keep = [_entry(200, "hold"), _entry(201, "pending_deposit"), _entry(202, "hold")]
    new = [_entry(300 + i, "stale", place=RACK, at_min=900 + i) for i in range(3)]
    doc = review.add(ReviewDoc(entries=tuple(stale + keep)), new, now)
    open_ = review.open_entries(doc)
    assert len(open_) <= review.MAX_OPEN
    assert {e.id for e in keep} <= {e.id for e in open_}  # never dropped
    places = [e for e in open_ if e.kind == "place"]
    assert places and all(review.words_of(e).startswith("Check this place") for e in places)
    folded = {c for e in places for c in e.candidates}
    assert len(folded) + sum(1 for e in open_ if e.kind == "stale") == 100  # nothing lost


def test_resolved_entries_go_after_the_keep_days_and_open_ones_stay() -> None:
    now = ist(2026, 11, 16, 9, 0)
    closed = _entry(1, "hold").model_copy(update={"closed_at": now - timedelta(days=31)})
    recent = _entry(2, "hold").model_copy(update={"closed_at": now - timedelta(days=2)})
    still = _entry(3, "hold")
    doc = review.prune(ReviewDoc(entries=(closed, recent, still)), now, keep_days=30)
    assert [e.id for e in doc.entries] == [recent.id, still.id]


async def test_the_review_view_counts_open_entries_and_shows_at_most_100() -> None:
    r = await rig()
    await r.commit(admit(ev(WHITE_SHIRT, "deposited", r.clock(), source="camera")))
    await r.commit(ev(WATCH, "missing", r.clock()))
    got = await r.desk.review_view(UID)
    assert got.open == 2 and [e.kind for e in got.entries] == ["hold", "hold"]
    assert got.entries[1].words == "Missing: tell JARVIS where it is."
