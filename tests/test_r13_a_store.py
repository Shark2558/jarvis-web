# tests/test_r13_a_store.py -- R13 Part A (docs/plans/r13-wardrobe.md D2, D4, OPS-03, plan review
# H4, M1-M3, M9): the sealed store beyond I0's conformance test (which runs on it too, through
# `r13_fakes_a.conformance_store`): sealed at rest, never overwritten when it can't be opened, the
# byte guard and the piece cap in plain words, log pages of 200, a rescan after a correction, and
# A's fold against I0's reference fold over seeded random histories.
from __future__ import annotations

import json
import random
from datetime import timedelta

import pytest
import r13_fakes_store as reference
from r13_fakes import UID, FixedClock, RecordingObserver, RecordingWriter, ev, ist, piece
from r13_fakes_a import conformance_store, ring

from jarvis.storage.docs import MemoryDocs, Set
from jarvis.wardrobe.catalog import fold as a_fold
from jarvis.wardrobe.catalog.store import (
    FULL,
    UNAVAILABLE,
    CatalogStore,
    WardrobeUnavailable,
    too_many,
)
from jarvis.wardrobe.model import Event
from jarvis.wardrobe.ports import Commit, Refused, WardrobeStore
from jarvis.wardrobe.states import EVENT_KINDS, STATES

SHIRT, VEST = "wi_" + "a" * 12, "wi_" + "b" * 12
DRAWER = "wl_" + "1" * 8
INDEX = f"jarvis_wardrobe/{UID}"


def _store(**kw: object) -> tuple[CatalogStore, MemoryDocs, FixedClock]:
    docs, clock = MemoryDocs(), FixedClock(ist(2026, 11, 16, 9, 0))
    return CatalogStore(docs, ring(), clock, **kw), docs, clock  # type: ignore[arg-type]


async def _commit(store: WardrobeStore, *events: Event, records: tuple = ()) -> object:
    async def fn(view: object, tx: object) -> Commit:
        return Commit(events=tuple(events), records=tuple(records))

    return await store.transact(UID, fn)


async def _register(store: CatalogStore, clock: FixedClock, *pids: str, **fields: object) -> None:
    recs = tuple(piece(p, **fields) for p in pids)  # type: ignore[arg-type]
    await _commit(store, *(ev(p, "registered", clock()) for p in pids), records=recs)


def test_the_store_is_a_wardrobe_store() -> None:
    store, *_ = _store()
    assert isinstance(store, WardrobeStore)
    assert isinstance(conformance_store(MemoryDocs(), FixedClock(ist(2026, 11, 16))), CatalogStore)


# ---- sealed at rest (D2: the index and every log page, purpose `wardrobe`) ----------------------
async def test_the_index_and_the_log_are_sealed_and_carry_updated_at() -> None:
    store, docs, clock = _store()
    await _register(store, clock, SHIRT, label="Light blue office shirt", colour="light_blue")
    raw = json.dumps({p: d for p, d in docs._data.items()})  # noqa: SLF001 - every stored byte
    assert "Light blue" not in raw and "light_blue" not in raw and "registered" not in raw
    index = await docs.get(INDEX)
    assert index is not None and set(index) == {"rev", "v", "kid", "blob", "updated_at"}
    assert index["rev"] == 1 and index["kid"] == "tk1"
    page = await docs.get(f"jarvis_wardrobe_log/{UID}_{SHIRT}_0")
    assert page is not None and set(page) == {"v", "kid", "owner", "n", "blob", "updated_at"}
    assert page["n"] == 1


async def test_a_log_page_moved_to_another_piece_does_not_open() -> None:
    store, docs, clock = _store()
    await _register(store, clock, SHIRT, VEST)
    shirt = await docs.get(f"jarvis_wardrobe_log/{UID}_{SHIRT}_0")
    assert shirt is not None
    await docs.write([Set(f"jarvis_wardrobe_log/{UID}_{VEST}_0", shirt)])  # the AAD names it
    with pytest.raises(WardrobeUnavailable):
        await store.history(UID, VEST)


async def test_an_index_that_cannot_be_opened_is_never_overwritten() -> None:
    store, docs, clock = _store()
    await _register(store, clock, SHIRT)
    broken = {**(await docs.get(INDEX) or {}), "blob": "AAAA" + "B" * 40}
    await docs.write([Set(INDEX, broken)])
    with pytest.raises(WardrobeUnavailable) as got:
        await store.view(UID)
    assert str(got.value) == UNAVAILABLE
    with pytest.raises(WardrobeUnavailable):
        await _commit(store, ev(SHIRT, "deposited", clock()))
    assert await docs.get(INDEX) == broken  # untouched


async def test_another_owners_index_does_not_open_under_his_name() -> None:
    store, docs, clock = _store()
    await _register(store, clock, SHIRT)
    await docs.write([Set("jarvis_wardrobe/owner-x", await docs.get(INDEX) or {})])
    with pytest.raises(WardrobeUnavailable):
        await store.view("owner-x")


async def test_a_bad_owner_id_is_refused_before_any_path_is_made() -> None:
    store, *_ = _store()
    with pytest.raises(ValueError):
        await store.view("../wardrobe")


# ---- the byte guard and the cap (D2, M9) ---------------------------------------------------------
def _maximal(n: int) -> object:
    from jarvis.wardrobe.model import Verified

    return piece(
        f"wi_{n:012x}",
        "shirt",
        label=("ഷർട്ട്" * 12)[:60],  # 60 characters of Malayalam: the widest his labels get
        colour="light_blue", second="navy", pattern="striped",
        locked=("colour", "pattern", "type"),
        features={"sleeve": "long", "collar": "button_down", "fit": "slim", "neck": "tight"},
        size=Verified(v="XL", ok=True), brand=Verified(v="A" * 30, ok=True),
        fabric=tuple(Verified(v="cotton", ok=True) for _ in range(4)),
        care=tuple(Verified(v="machine_wash", ok=True) for _ in range(8)),
        formality=5, occasions=("work", "formal", "festive"), weather=("hot", "rain_ok"),
        mess_ok=True, delicate=True, place=DRAWER, label_code="abcdefgh",
        photos=("wh_" + "1" * 12, "wh_" + "2" * 12, "wh_" + "3" * 12), fp_model="mnv2-int8-1",
        wears=999, events=9999,
    )  # fmt: skip


def _worn_out(n: int) -> object:
    """A maximal piece that has also lived: every field the fold sets, at its widest."""
    from datetime import date

    t = ist(2026, 11, 16, 9, 0)
    return _maximal(n).model_copy(  # type: ignore[attr-defined]
        update={
            "state": "review", "back_to": "with_provider", "hold": "unverified",
            "expected_back": date(2026, 12, 1), "wear": "x" * 40, "wears": 999, "last_worn": t,
            "place_at": t, "events": 99_999, "created_at": t, "updated_at": t,
        }
    )  # fmt: skip


async def test_600_new_maximal_pieces_fit_and_the_guard_bites_before_firestores_limit() -> None:
    store, docs, clock = _store(max_pieces=600)
    for batch in range(12):  # 600 maximal pieces, registered: 864 KB sealed, under the guard
        recs = tuple(_maximal(batch * 50 + i) for i in range(50))
        await _commit(store, *(ev(r.id, "registered", clock()) for r in recs), records=recs)  # type: ignore[attr-defined]
        stored = await docs.get(INDEX)
        assert stored is not None and len(json.dumps(stored)) <= 900 * 1024
    assert len((await store.view(UID)).active()) == 600
    from jarvis.wardrobe.model import WardrobeView

    def sized(n: int) -> WardrobeView:
        pieces = {p.id: p for p in (_worn_out(i) for i in range(n))}  # type: ignore[attr-defined]
        return WardrobeView(uid=UID, rev=99_999, pieces=pieces)

    assert len(json.dumps(store._seal_index(UID, sized(500)))) <= 900 * 1024  # noqa: SLF001
    for n in (550, 600):  # lived-in maximal pieces: the guard refuses, never Firestore's 1 MiB
        with pytest.raises(Refused) as got:
            store._seal_index(UID, sized(n))  # noqa: SLF001
        assert str(got.value) == FULL


async def test_a_commit_past_the_byte_guard_is_refused_and_writes_nothing() -> None:
    store, docs, clock = _store(max_pieces=600, index_max_bytes=100 * 1024)
    added, refused = 0, None
    for batch in range(12):
        recs = tuple(_maximal(batch * 50 + i) for i in range(50))
        try:
            await _commit(store, *(ev(r.id, "registered", clock()) for r in recs), records=recs)  # type: ignore[attr-defined]
        except Refused as exc:
            refused = str(exc)
            break
        added += 50
        stored = await docs.get(INDEX)
        assert stored is not None and len(json.dumps(stored)) <= 100 * 1024
    assert refused == FULL and 0 < added < 600
    assert len((await store.view(UID)).pieces) == added  # the refused batch wrote nothing
    assert await docs.get(f"jarvis_wardrobe_log/{UID}_wi_{added:012x}_0") is None


async def test_the_piece_cap_refuses_in_words_and_archived_pieces_do_not_count() -> None:
    store, _, clock = _store(max_pieces=50)
    await _register(store, clock, *(f"wi_{i:012x}" for i in range(50)))
    with pytest.raises(Refused) as got:
        await _register(store, clock, SHIRT)
    assert str(got.value) == too_many(50)
    clock.advance(minutes=1)
    await _commit(store, ev(f"wi_{0:012x}", "archived", clock()))
    await _register(store, clock, SHIRT)  # an archived piece frees its place
    assert (await store.view(UID)).piece(SHIRT) is not None


async def test_an_event_for_a_piece_not_in_the_index_is_refused() -> None:
    store, *_ = _store()
    with pytest.raises(Refused):
        await _commit(store, ev(SHIRT, "seen", ist(2026, 11, 16, 9, 0)))


# ---- log pages of 200 (D2) ----------------------------------------------------------------------
async def test_a_log_past_200_events_goes_on_to_a_second_page_and_reads_whole() -> None:
    store, docs, clock = _store()
    await _register(store, clock, SHIRT)
    for _ in range(4):
        clock.advance(minutes=1)
        t = clock()
        await _commit(store, *(ev(SHIRT, "seen", t, place=DRAWER) for _ in range(50)))
    assert (await docs.get(f"jarvis_wardrobe_log/{UID}_{SHIRT}_1")) is not None
    assert len(await store.history(UID, SHIRT)) == 201
    shirt = (await store.view(UID)).piece(SHIRT)
    assert shirt is not None and shirt.events == 201


# ---- a correction that leaves later events in conflict asks for a rescan (D4.3) -----------------
async def test_a_correction_that_makes_later_events_conflict_asks_for_one_rescan() -> None:
    store, _, clock = _store()
    writer = RecordingWriter()
    store.bind(review_writer=writer)
    await _register(store, clock, SHIRT)
    clock.advance(minutes=1)
    dep = ev(SHIRT, "deposited", clock())
    await _commit(store, dep)
    clock.advance(minutes=1)
    await _commit(store, ev(SHIRT, "load_started", clock()))
    clock.advance(minutes=1)
    got = await store.correct(UID, SHIRT, dep.id, note="that was the vest")
    assert [n.kind for n in got.needed] == ["rescan"]  # washing a shirt never in the basket
    assert (await store.view(UID)).piece(SHIRT).state == "ready"  # type: ignore[union-attr]


async def test_observers_hear_nothing_when_the_commit_fails() -> None:
    store, _, clock = _store()
    heard = RecordingObserver()
    writer = RecordingWriter(fail=True)
    store.bind(review_writer=writer, observers=[heard])
    await _register(store, clock, SHIRT)
    with pytest.raises(RuntimeError):
        await _commit(store, ev(SHIRT, "deposited", clock(), verified=False, how="match"))
    assert heard.heard == [] or [c.kind for c in heard.heard] == ["registered"]


# ---- A's fold is I0's reference fold, over seeded random histories (D4.3) -----------------------
def _random_history(rng: random.Random) -> list[Event]:
    t = ist(2026, 11, 16, 8, 0)
    out = [ev(SHIRT, "registered", t, recorded=t)]
    for n in range(rng.randint(1, 14)):
        at = t + timedelta(minutes=rng.randint(1, 600))
        kind = rng.choice([k for k in EVENT_KINDS if k not in ("registered", "corrected")])
        to = rng.choice([None, *STATES]) if rng.random() < 0.3 else None
        out.append(
            ev(SHIRT, kind, at, verified=rng.random() < 0.7, to=to,  # type: ignore[arg-type]
               place=DRAWER if rng.random() < 0.3 else None, recorded=at + timedelta(seconds=n))
        )  # fmt: skip
    if rng.random() < 0.3:
        victim = rng.choice(out[1:])
        at = t + timedelta(minutes=700)
        out.append(ev(SHIRT, "corrected", at, voids=victim.id, recorded=at))
    return out


def test_as_fold_agrees_with_the_reference_on_500_seeded_histories() -> None:
    for seed in range(500):
        history = _random_history(random.Random(seed))
        mine, ref = a_fold.fold(history), reference.fold(history)
        got = (mine.state, mine.back_to, mine.place, mine.hold, mine.wears, mine.wear)
        want = (ref.state, ref.back_to, ref.place, ref.hold, ref.wears, ref.wear)
        assert got == want, seed
        assert dict(mine.marks) == ref.marks, seed
        shuffled = history[:]
        random.Random(seed + 1).shuffle(shuffled)
        assert a_fold.fold(shuffled) == mine, seed  # order-independent


def test_the_fold_result_is_frozen() -> None:
    folded = a_fold.fold([ev(SHIRT, "registered", ist(2026, 11, 16, 9, 0))])
    with pytest.raises(AttributeError):
        folded.state = "washing"  # type: ignore[misc]
    with pytest.raises(TypeError):
        folded.marks["x"] = "applied"  # type: ignore[index]


async def test_m6_each_whole_wardrobe_read_opens_the_index_once_not_once_a_piece(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from r13_fakes_a import catalog

    from jarvis.wardrobe.catalog.edits import NewPiece

    cat = catalog()
    desk = cat.store.desk  # type: ignore[attr-defined]
    n = 20
    ids = (await desk.service.add(UID, [NewPiece(type="t_shirt")] * n)).ids
    for pid in ids[:3]:  # three wears, forgotten overnight, for the sweep to close

        async def wear(view: object, tx: object, pid: str = pid) -> Commit:
            return Commit(events=(ev(pid, "wear_started", cat.clock()),))

        await cat.store.transact(UID, wear)
    cat.clock.set(ist(2026, 11, 17, 4, 30))
    body = await desk.backup.file(UID)
    reads: list[str] = []
    real = cat.docs.get

    async def counting(path: str) -> object:
        reads.append(path)
        return await real(path)

    monkeypatch.setattr(cat.docs, "get", counting)
    data, _ = cat.part.data
    [sweep] = cat.part.daily_jobs
    from jarvis.api.r13_wiring import sweep_closer
    from jarvis.wardrobe.styling.rules import load_rules

    sweep.closer = sweep_closer(
        cat.store, load_rules()
    )  # C's closer, joined as the wiring joins it
    for name, read, want in (
        ("backup", lambda: desk.backup.file(UID), (1, n)),
        ("pilot", lambda: desk.pilot.counts(UID), (1, n)),
        ("export", lambda: data.export(UID), (1, n)),
        ("restore check", lambda: desk.restore.check(UID, body), (1, n)),
        # the sweep's view, C's closer's view, then the commit's: three, never one a piece
        ("sweep", lambda: sweep.sweep(UID), (3, 6)),
    ):
        reads.clear()
        await read()
        index = [p for p in reads if p == INDEX]
        logs = [p for p in reads if p.startswith("jarvis_wardrobe_log/")]
        assert (name, len(index), len(logs)) == (name, *want)
