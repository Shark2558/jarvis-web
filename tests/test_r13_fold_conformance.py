# tests/test_r13_fold_conformance.py -- R13 I0 (docs/plans/r13-wardrobe.md D4, plan review H4,
# M1-M3): the ledger's ONE conformance test. Every `WardrobeStore` must pass it: I0's in-memory
# store (`tests/r13_fakes_store.py`) now, and Part A's real store from A on (A adds
# `conformance_store(docs, now)` to its own `tests/r13_fakes_a.py`; this file finds it and runs
# every case against it too, unchanged), so B and C never build on a fake that folds differently.
#
# The rules: an append-only log; a retry (its client id or id already there) is applied once; a
# second record of the same movement is a `duplicate` (no entry, no hold); an unverified event
# older than the newest verified state-setting one is `superseded`; a transition the table refuses
# is a `conflict` that asks for an entry and holds nothing; an unverified change of availability
# is a hold with its entry, in the same commit; a correction re-folds from the valid history; the
# fold is order-independent; device times are corrected by `sent`; a write that fails rolls the
# whole commit back; observers hear each changed piece once, after the commit.
from __future__ import annotations

import random
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import date, datetime, timedelta

import pytest
from r13_fakes import (
    UID,
    FixedClock,
    RecordingObserver,
    RecordingWriter,
    ev,
    ist,
    memory_store,
    piece,
)

from jarvis.storage.docs import Create, MemoryDocs, Set
from jarvis.wardrobe.model import Event
from jarvis.wardrobe.ports import Commit, Committed, Refused, WardrobeStore

Factory = Callable[[MemoryDocs, Callable[[], datetime]], WardrobeStore]
FACTORIES: dict[str, Factory] = {"memory": memory_store}
try:  # Part A's real store, from A on (its own fakes file; never an edit here)
    import r13_fakes_a  # type: ignore[import-not-found]

    if callable(getattr(r13_fakes_a, "conformance_store", None)):
        FACTORIES["catalog"] = r13_fakes_a.conformance_store
except ImportError:
    pass

SHIRT, VEST, BELT = "wi_" + "a" * 12, "wi_" + "b" * 12, "wi_" + "c" * 12
DRAWER, RACK = "wl_" + "1" * 8, "wl_" + "2" * 8
REVIEW_DOC = f"jarvis_wardrobe_review/{UID}"


@dataclass
class Rig:
    store: WardrobeStore
    docs: MemoryDocs
    clock: FixedClock
    writer: RecordingWriter
    observer: RecordingObserver

    async def commit(self, *events: Event, records: tuple[object, ...] = (), extra=()) -> Committed:
        async def fn(view: object, tx: object) -> Commit:
            return Commit(events=tuple(events), extra=tuple(extra), records=tuple(records))  # type: ignore[arg-type]

        return await self.store.transact(UID, fn)

    async def register(self, *pids: str) -> None:
        recs = tuple(piece(p) for p in pids)
        await self.commit(*(ev(p, "registered", self.clock()) for p in pids), records=recs)

    async def state(self, pid: str) -> str:
        found = (await self.store.view(UID)).piece(pid)
        assert found is not None
        return found.state


def _rig(factory: Factory) -> Rig:
    docs, clock = MemoryDocs(), FixedClock(ist(2026, 11, 16, 9, 0))
    store = factory(docs, clock)
    writer, observer = RecordingWriter(), RecordingObserver()
    store.bind(review_writer=writer, observers=[observer])
    return Rig(store, docs, clock, writer, observer)


@pytest.fixture(params=sorted(FACTORIES))
def rig(request: pytest.FixtureRequest) -> Rig:
    return _rig(FACTORIES[request.param])


# ---- the basics --------------------------------------------------------------------------------
async def test_a_registered_piece_is_ready_and_the_view_moves_one_rev_a_commit(rig: Rig) -> None:
    before = (await rig.store.view(UID)).rev
    await rig.register(SHIRT)
    view = await rig.store.view(UID)
    assert view.rev == before + 1 and await rig.state(SHIRT) == "ready"
    assert [h.event.kind for h in await rig.store.history(UID, SHIRT)] == ["registered"]


async def test_a_retry_is_applied_once_by_its_client_id_and_by_its_id(rig: Rig) -> None:
    await rig.register(SHIRT)
    first = ev(SHIRT, "deposited", rig.clock(), client_id="tap-0000001")
    await rig.commit(first)
    again = await rig.commit(ev(SHIRT, "deposited", rig.clock(), client_id="tap-0000001"))
    same = await rig.commit(first)
    assert list(again.marks.values()) == ["known"] and list(same.marks.values()) == ["known"]
    assert again.already and same.already
    assert [h.event.kind for h in await rig.store.history(UID, SHIRT)] == [
        "registered",
        "deposited",
    ]


async def test_events_of_one_commit_at_the_same_moment_keep_their_order(rig: Rig) -> None:
    for _ in range(5):  # the ids are random: the order must never rest on them
        await rig.register(SHIRT) if not (await rig.store.view(UID)).piece(SHIRT) else None
        rig.clock.advance(minutes=1)
        now = rig.clock()
        got = await rig.commit(ev(SHIRT, "deposited", now), ev(SHIRT, "load_started", now))
        assert list(got.marks.values()) == ["applied", "applied"]
        rig.clock.advance(minutes=1)
        t = rig.clock()
        await rig.commit(ev(SHIRT, "dried", t), ev(SHIRT, "returned", t, place=DRAWER))
        assert await rig.state(SHIRT) == "ready"


async def test_a_second_record_of_the_same_deposit_is_a_duplicate_with_no_entry(rig: Rig) -> None:
    await rig.register(SHIRT)
    rig.clock.advance(minutes=1)
    await rig.commit(ev(SHIRT, "deposited", rig.clock(), source="tap"))
    rig.clock.advance(minutes=1)
    scan = ev(SHIRT, "deposited", rig.clock(), source="phone", how="qr")
    got = await rig.commit(scan)
    assert got.marks[scan.id] == "duplicate" and got.needed == () and got.already
    assert await rig.state(SHIRT) == "in_laundry" and rig.writer.needed == []


# ---- order: the newer verified event wins (OPS-03, LND-05) ---------------------------------------
async def test_an_old_basket_event_after_a_clean_return_cannot_make_the_shirt_dirty(
    rig: Rig,
) -> None:
    await rig.register(SHIRT)
    t0 = rig.clock()
    rig.clock.advance(hours=1)
    await rig.commit(ev(SHIRT, "deposited", rig.clock()))
    rig.clock.advance(hours=2)
    await rig.commit(ev(SHIRT, "returned", rig.clock(), place=DRAWER))
    rig.clock.advance(minutes=5)
    late = ev(SHIRT, "deposited", t0 + timedelta(minutes=30), verified=False, how="match")
    got = await rig.commit(late)
    assert got.marks[late.id] == "superseded" and got.needed == ()
    assert await rig.state(SHIRT) == "ready"
    view = await rig.store.view(UID)
    shirt = view.piece(SHIRT)
    assert shirt is not None and shirt.place == DRAWER and shirt.hold is None


async def _late_verified_deposit(rig: Rig) -> str:
    """A QR read at the basket at 09:30, delivered after the 12:00 clean return."""
    await rig.register(SHIRT)
    t0 = rig.clock()
    rig.clock.advance(hours=1)
    await rig.commit(ev(SHIRT, "deposited", rig.clock()))
    rig.clock.advance(hours=2)
    await rig.commit(ev(SHIRT, "returned", rig.clock(), place=DRAWER))
    rig.clock.advance(minutes=5)
    await rig.commit(ev(SHIRT, "deposited", t0 + timedelta(minutes=30), how="qr"))
    return await rig.state(SHIRT)


async def test_a_verified_basket_scan_delivered_late_folds_in_its_own_place(rig: Rig) -> None:
    assert await _late_verified_deposit(rig) == "ready"


async def test_control_a_fold_in_arrival_order_fails_this_suite(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import r13_fakes_store as fake

    def arrival(history: Iterable[Event]) -> fake.Folded:  # the same steps, never sorted
        events = list(history)
        voided = {e.voids for e in events if e.kind == "corrected" and e.voids}
        newest, f = fake._newest_verified(events, voided), fake.Folded()  # noqa: SLF001
        for e in events:
            f.marks[e.id] = "voided" if e.id in voided else fake._step(f, e, newest)  # noqa: SLF001
        return f

    monkeypatch.setattr(fake, "fold", arrival)
    assert await _late_verified_deposit(_rig(fake.memory_store)) == "in_laundry"  # dirty again


async def test_a_refused_transition_is_a_conflict_that_holds_nothing(rig: Rig) -> None:
    await rig.register(SHIRT)
    rig.clock.advance(minutes=1)
    odd = ev(SHIRT, "load_started", rig.clock())  # a ready shirt can't start washing
    got = await rig.commit(odd)
    assert got.marks[odd.id] == "conflict" and await rig.state(SHIRT) == "ready"
    assert [(n.kind, n.piece, n.event) for n in got.needed] == [("conflict", SHIRT, odd.id)]
    assert rig.writer.needed[-1][0].kind == "conflict"


async def test_an_unverified_change_of_availability_is_a_hold_written_with_its_entry(
    rig: Rig,
) -> None:
    await rig.register(SHIRT)
    rig.clock.advance(minutes=1)
    maybe = ev(SHIRT, "deposited", rig.clock(), verified=False, how="match", score=0.7)
    got = await rig.commit(maybe)
    assert got.marks[maybe.id] == "held" and await rig.state(SHIRT) == "review"
    view = await rig.store.view(UID)
    shirt = view.piece(SHIRT)
    assert shirt is not None and shirt.back_to == "ready" and shirt.hold
    assert [(n.kind, n.back_to) for n in got.needed] == [("hold", "ready")]
    entry = await rig.docs.get(REVIEW_DOC)  # the writer's op landed in the same commit
    assert entry is not None and maybe.id in entry["events"]


async def test_correcting_an_old_basket_event_never_overwrites_a_later_clean_return(
    rig: Rig,
) -> None:
    await rig.register(SHIRT)
    rig.clock.advance(hours=1)
    dep = ev(SHIRT, "deposited", rig.clock())
    await rig.commit(dep)
    rig.clock.advance(hours=1)
    await rig.commit(ev(SHIRT, "returned", rig.clock(), place=DRAWER))
    rig.clock.advance(hours=1)
    got = await rig.store.correct(UID, SHIRT, dep.id, note="it was the other shirt")
    assert await rig.state(SHIRT) == "ready"  # the later clean return stays authoritative
    hist = await rig.store.history(UID, SHIRT)
    marks = {h.event.id: h.mark for h in hist}
    assert marks[dep.id] == "voided" and hist[-1].event.kind == "corrected"
    assert [e.voids for e in got.events] == [dep.id]


async def test_fifty_seeded_permutations_fold_to_the_same_state_and_marks() -> None:
    t = ist(2026, 11, 16, 8, 0)
    kinds = [
        ("registered", 0, True),
        ("wear_started", 60, True),
        ("wear_done", 600, True),
        ("deposited", 601, True),
        ("deposited", 602, False),  # a second, unverified record of it
        ("load_started", 900, True),
        ("dried", 1000, True),
        ("returned", 1200, True),
        ("deposited", 700, False),  # an old, unverified basket message
    ]
    base = [
        ev(SHIRT, k, t + timedelta(minutes=m), verified=v, recorded=t + timedelta(minutes=m))
        for k, m, v in kinds
    ]
    outcomes = set()
    for seed in range(50):
        order = base[:]
        random.Random(seed).shuffle(order)
        for name, factory in FACTORIES.items():
            r = _rig(factory)
            r.clock.set(t + timedelta(days=1))  # every event is under 24 hours old
            await r.commit(*order, records=(piece(SHIRT),))
            hist = await r.store.history(UID, SHIRT)
            view = await r.store.view(UID)
            shirt = view.piece(SHIRT)
            assert shirt is not None
            marks = tuple(sorted((h.event.id, h.mark) for h in hist))
            outcomes.add((name, shirt.state, shirt.wears, marks))
    assert {(s, w) for _, s, w, _ in outcomes} == {("ready", 1)}
    assert len({m for *_, m in outcomes}) == 1  # the same marks, whatever the order


# ---- time (D4.1, M1) ---------------------------------------------------------------------------
async def test_a_phone_three_hours_fast_and_a_scan_sent_late_fold_in_true_order(rig: Rig) -> None:
    await rig.register(SHIRT)
    rig.clock.advance(hours=1)
    real = rig.clock()
    fast = timedelta(hours=3)
    # the phone's clock is 3 h fast: it captured "13:00" and sent at "13:00" (really 10:00)
    dep = ev(SHIRT, "deposited", real + fast, sent=real + fast, source="phone", how="qr")
    await rig.commit(dep)
    # a return scanned 20 minutes AFTER the deposit was captured but sent 20 minutes late
    rig.clock.advance(minutes=40)
    capture = real + timedelta(minutes=20)
    back = ev(SHIRT, "returned", capture, sent=capture + timedelta(minutes=20), place=DRAWER)
    await rig.commit(back)
    hist = await rig.store.history(UID, SHIRT)
    assert [h.event.kind for h in hist] == ["registered", "deposited", "returned"]
    assert hist[1].event.at == real and hist[2].event.at == rig.clock() - timedelta(minutes=20)
    assert await rig.state(SHIRT) == "ready"


@pytest.mark.parametrize(
    ("at_shift", "sent_shift", "why"),
    [
        (timedelta(minutes=5), timedelta(0), "a capture after its own send: the future"),
        (-timedelta(hours=25), timedelta(0), "more than 24 hours old"),
    ],
)
async def test_a_corrected_device_time_in_the_future_or_a_day_old_is_refused(
    rig: Rig, at_shift: timedelta, sent_shift: timedelta, why: str
) -> None:
    await rig.register(SHIRT)
    now = rig.clock()
    bad = ev(SHIRT, "deposited", now + at_shift, sent=now + sent_shift, source="phone")
    with pytest.raises(Refused):
        await rig.commit(bad)
    assert await rig.state(SHIRT) == "ready", why


async def test_a_stated_time_is_taken_as_said_up_to_thirty_days_back_never_ahead(rig: Rig) -> None:
    await rig.register(SHIRT)
    rig.clock.advance(days=2)
    said = ev(SHIRT, "seen", rig.clock() - timedelta(days=1), place=RACK)  # "yesterday"
    await rig.commit(said)
    assert (await rig.store.history(UID, SHIRT))[-1].event.at == rig.clock() - timedelta(days=1)
    for bad in (rig.clock() + timedelta(minutes=1), rig.clock() - timedelta(days=31)):
        with pytest.raises(Refused):
            await rig.commit(ev(SHIRT, "seen", bad, place=RACK))


# ---- one commit (D4.4, H4) ---------------------------------------------------------------------
async def test_an_extra_write_that_raises_rolls_back_the_index_the_log_and_bs_document(
    rig: Rig,
) -> None:
    await rig.register(SHIRT)
    await rig.docs.write([Set("jarvis_wardrobe_laundry/" + UID, {"loads": []})])
    before = (await rig.store.view(UID)).rev
    clash = Create("jarvis_wardrobe_laundry/" + UID, {"loads": ["x"]})  # exists: the commit fails
    with pytest.raises(Exception):  # noqa: B017 - DocExists or the store's own error
        await rig.commit(ev(SHIRT, "deposited", rig.clock()), extra=(clash,))
    assert (await rig.store.view(UID)).rev == before and await rig.state(SHIRT) == "ready"
    assert len(await rig.store.history(UID, SHIRT)) == 1
    assert await rig.docs.get("jarvis_wardrobe_laundry/" + UID) == {"loads": []}


async def test_a_writer_that_raises_writes_nothing(rig: Rig) -> None:
    await rig.register(SHIRT)
    rig.writer.fail = True
    with pytest.raises(RuntimeError):
        await rig.commit(ev(SHIRT, "deposited", rig.clock(), verified=False, how="match"))
    assert await rig.state(SHIRT) == "ready" and await rig.docs.get(REVIEW_DOC) is None


async def test_observers_hear_each_changed_piece_once_after_the_commit(rig: Rig) -> None:
    await rig.register(SHIRT, VEST)
    rig.observer.heard.clear()
    broken = RecordingObserver(fail=True)
    later = RecordingObserver()
    rig.store.bind(review_writer=rig.writer, observers=[broken, rig.observer, later])
    rig.clock.advance(minutes=1)
    plan = "plan_20261117"
    await rig.commit(
        ev(SHIRT, "wear_started", rig.clock(), plan=plan), ev(VEST, "seen", rig.clock())
    )
    assert [(c.piece, c.kind, c.before, c.after, c.plan) for c in rig.observer.heard] == [
        (SHIRT, "wear_started", "ready", "in_use", plan)
    ]  # the vest's sighting changed nothing
    assert later.heard == rig.observer.heard  # one that raises never stops the others


# ---- the lifecycle the parts build on ----------------------------------------------------------
async def test_a_wear_counts_once_and_the_rewear_rule_picks_where_it_goes(rig: Rig) -> None:
    await rig.register(SHIRT, BELT)
    rig.clock.advance(hours=1)
    await rig.commit(ev(SHIRT, "wear_started", rig.clock()), ev(BELT, "wear_started", rig.clock()))
    rig.clock.advance(hours=9)
    await rig.commit(
        ev(SHIRT, "wear_done", rig.clock(), to="in_laundry"),
        ev(BELT, "wear_done", rig.clock(), to="ready"),  # a belt is worn again
    )
    view = await rig.store.view(UID)
    shirt, belt = view.piece(SHIRT), view.piece(BELT)
    assert shirt is not None and belt is not None
    assert (shirt.state, shirt.wears, belt.state, belt.wears) == ("in_laundry", 1, "ready", 1)
    assert shirt.last_worn == rig.clock() and shirt.wear is None


async def test_a_hold_remembers_back_to_and_release_returns_it(rig: Rig) -> None:
    await rig.register(SHIRT)
    rig.clock.advance(minutes=1)
    await rig.commit(ev(SHIRT, "deposited", rig.clock()))
    rig.clock.advance(minutes=1)
    got = await rig.commit(ev(SHIRT, "held", rig.clock(), note="which shirt?"))
    assert await rig.state(SHIRT) == "review" and [n.kind for n in got.needed] == ["hold"]
    rig.clock.advance(minutes=1)
    await rig.commit(ev(SHIRT, "released", rig.clock()))
    assert await rig.state(SHIRT) == "in_laundry"


async def test_an_archived_piece_comes_back_in_review_and_keeps_its_id(rig: Rig) -> None:
    await rig.register(BELT)
    rig.clock.advance(minutes=1)
    await rig.commit(ev(BELT, "archived", rig.clock()))
    assert await rig.state(BELT) == "archived"
    assert BELT not in {p.id for p in (await rig.store.view(UID)).active()}
    rig.clock.advance(minutes=1)
    await rig.commit(ev(BELT, "restored", rig.clock()))
    assert await rig.state(BELT) == "review"
    rig.clock.advance(minutes=1)
    await rig.commit(ev(BELT, "found", rig.clock(), to="ready"))
    assert await rig.state(BELT) == "ready"


async def test_expected_back_comes_from_the_latest_sent_out(rig: Rig) -> None:
    await rig.register(SHIRT)
    due = date(2026, 11, 18)
    rig.clock.advance(minutes=1)
    await rig.commit(ev(SHIRT, "sent_out", rig.clock(), due=due, batch="b1"))
    view = await rig.store.view(UID)
    shirt = view.piece(SHIRT)
    assert shirt is not None and shirt.state == "with_provider" and shirt.expected_back == due
    rig.clock.advance(days=1)
    await rig.commit(ev(SHIRT, "received", rig.clock(), to="needs_prep"))
    view = await rig.store.view(UID)
    shirt = view.piece(SHIRT)
    assert shirt is not None and shirt.state == "needs_prep" and shirt.expected_back is None


async def test_a_return_records_the_place_and_when_it_was_confirmed(rig: Rig) -> None:
    await rig.register(SHIRT)
    rig.clock.advance(minutes=1)
    await rig.commit(ev(SHIRT, "deposited", rig.clock()))
    rig.clock.advance(hours=3)
    await rig.commit(ev(SHIRT, "returned", rig.clock(), place=RACK))
    shirt = (await rig.store.view(UID)).piece(SHIRT)
    assert shirt is not None and (shirt.place, shirt.place_at) == (RACK, rig.clock())
    rig.clock.advance(minutes=1)
    again = await rig.commit(ev(SHIRT, "returned", rig.clock(), place=RACK))
    assert list(again.marks.values()) == ["duplicate"]
