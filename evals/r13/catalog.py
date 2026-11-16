# evals/r13/catalog.py
"""R13 eval, Part A's suite (`catalog`, BUILT): the catalog and the ledger, INV-01 ... INV-17,
OPS-03 and OPS-06 (docs/plans/r13-wardrobe.md "Tests and evals"), each case one acceptance check
on Part A's REAL part (`build(ctx)`: the sealed store, the fold, the tools' services) over
in-memory fakes with a FIXED clock. Nothing here calls a model or the network.

Negative controls (each must make this suite fail, else it proves nothing):
- candidates off: every scan is a new piece (his tapped candidate ignored): INV-05 fails;
- the dedup off: a retry (its id or client id already in the log) is appended again: INV-08 and
  OPS-03 fail.
"""

from __future__ import annotations

import random
import sys
from collections.abc import Awaitable, Callable
from contextlib import ExitStack
from datetime import timedelta
from pathlib import Path
from typing import Any
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
for extra in (ROOT / "src", ROOT / "tests"):
    if str(extra) not in sys.path:
        sys.path.insert(0, str(extra))
from r13_fakes import UID, ev  # noqa: E402
from r13_fakes_a import catalog, fp, jpeg  # noqa: E402

from jarvis.wardrobe.catalog import store as store_mod  # noqa: E402
from jarvis.wardrobe.catalog.edits import Edit, NewPiece  # noqa: E402
from jarvis.wardrobe.catalog.matching import candidates  # noqa: E402
from jarvis.wardrobe.catalog.service import CatalogService  # noqa: E402
from jarvis.wardrobe.ports import Commit  # noqa: E402

PART = "catalog"
BUILT = True
Case = Callable[[], Awaitable[list[str]]]


async def _commit(cat: Any, *events: Any) -> Any:
    async def fn(view: object, tx: object) -> Commit:
        return Commit(events=tuple(events))

    return await cat.store.transact(UID, fn)


async def _add(cat: Any, *specs: NewPiece) -> list[str]:
    return list((await cat.store.desk.service.add(UID, specs)).ids)


def _want(cond: bool, why: str) -> list[str]:
    return [] if cond else [why]


async def inv01() -> list[str]:
    cat = catalog()
    drawer = await cat.store.desk.places.add(UID, "Drawer 2")
    [belt] = await _add(cat, NewPiece(type="belt", place=drawer.id))
    found = await cat.store.desk.search.find(UID, "belt")
    words = (
        cat.store.desk.views.place_words(await cat.store.view(UID), found.best)
        if found.best
        else ""
    )
    return _want(
        found.best is not None and found.best.id == belt and words == "Drawer 2", "not in Drawer 2"
    )


async def inv02() -> list[str]:
    cat = catalog()
    rack, _ = (
        (await cat.store.desk.places.add(UID, "Shirt rack")),
        await cat.store.desk.places.add(UID, "Tray"),
    )
    shirts = await _add(cat, NewPiece(type="shirt", place=rack.id))
    got = await cat.store.desk.places.baseline(UID, rack.id, seen=shirts, unresolved=1)
    return _want(got.unresolved == 1 and len(got.without_baseline) == 1, "coverage not listed")


async def inv03() -> list[str]:
    cat = catalog()
    ids = await _add(cat, NewPiece(type="belt"), NewPiece(type="watch"))
    return _want(
        len(set(ids)) == 2 and len((await cat.store.view(UID)).active()) == 2, "not two records"
    )


async def inv04() -> list[str]:
    cat = catalog()
    [tee] = await _add(cat, NewPiece(type="t_shirt"))
    asked = await cat.store.desk.service.edit(UID, tee, Edit(type="undershirt"))
    kept = await cat.store.desk.service.edit(UID, tee, Edit(type="shirt"))
    return _want(
        asked.status == "ask" and kept.piece is not None and kept.piece.id == tee, "type change"
    )


async def inv05() -> list[str]:
    cat = catalog()
    [kurta] = await _add(cat, NewPiece(type="kurta"))
    await cat.store.desk.service.intake(UID, NewPiece(type="kurta"), candidate=kurta)
    owned = cat.store.desk.counts.of(await cat.store.view(UID)).owned
    return _want(owned == 1, f"a rescan changed the owned count to {owned}")


async def inv06() -> list[str]:
    rng = random.Random(6)
    base = [rng.randint(0, 255) for _ in range(1280)]

    def noisy(spread: int, src: list[int]) -> str:
        import base64

        return base64.b64encode(
            bytes(max(0, min(255, b + rng.randint(-spread, spread))) for b in src)
        ).decode()

    saved = [
        {"p": "wi_" + "a" * 12, "v": noisy(10, base)},
        {"p": "wi_" + "a" * 12, "v": noisy(10, base)},
    ]
    saved += [
        {"p": f"wi_{n:012x}", "v": noisy(4, [rng.randint(0, 255) for _ in range(1280)])}
        for n in range(6)
    ]
    found = candidates(saved, noisy(30, base))
    return _want(bool(found) and found[0].piece == "wi_" + "a" * 12, "the shirt lost its id")


async def inv07() -> list[str]:
    cat = catalog()
    a, b = await _add(cat, NewPiece(type="vest"), NewPiece(type="vest"))
    code = (await cat.store.desk.labels.sheet(UID))[0].code
    await cat.store.desk.labels.assign(UID, code, a)
    view = await cat.store.view(UID)
    labels = cat.store.desk.labels
    ok = labels.resolve(view, f"jw1:{code}") == a and labels.resolve(view, "jw1:zzzzzzzz") is None
    return _want(a != b and ok, "labels")


async def inv08() -> list[str]:
    cat = catalog()
    ids = set()
    for _ in range(20):
        ids |= set(
            (
                await cat.store.desk.service.add(
                    UID, [NewPiece(type="shirt", client_id="box-shirt-1")]
                )
            ).ids
        )
    [pid] = ids
    kinds = [h.event.kind for h in await cat.store.history(UID, pid)]
    return _want(kinds == ["registered"], f"{len(kinds)} registration events")


async def inv09() -> list[str]:
    cat = catalog()
    mine, _ = await _add(cat, NewPiece(type="shirt"), NewPiece(type="shirt"))
    await cat.store.desk.service.edit(UID, mine, Edit(colour="blue", pattern="striped"))
    await cat.store.desk.service.edit(UID, mine, Edit(colour="navy", suggested=True))
    found = await cat.store.desk.search.find(UID, "blue striped shirt")
    colour = (await cat.store.view(UID)).pieces[mine].colour
    return _want(
        found.best is not None and found.best.id == mine and colour == "blue", "verified find"
    )


async def inv10() -> list[str]:
    from jarvis.wardrobe.redact import model_view

    cat = catalog()
    [pid] = await _add(cat, NewPiece(type="shirt"))
    await cat.store.desk.service.edit(UID, pid, Edit(care=("hand_wash",), read=True))
    p = (await cat.store.view(UID)).pieces[pid]
    return _want(not p.care[0].ok and "care" not in model_view(p), "an unverified field leaked")


async def inv11() -> list[str]:
    cat = catalog()
    left, right = await _add(cat, NewPiece(type="dress_shoe"), NewPiece(type="dress_shoe"))
    await cat.store.desk.links.pair(UID, left, right)
    await _commit(cat, ev(right, "deposited", cat.clock()))
    c = cat.store.desk.counts.of(await cat.store.view(UID))
    return _want((c.owned, c.pairs, c.pairs_complete) == (2, 1, 0), "pair counted while out")


async def inv12() -> list[str]:
    cat = catalog()
    kurta, pyjama = await _add(cat, NewPiece(type="kurta"), NewPiece(type="pyjama"))
    await cat.store.desk.links.make_set(UID, [(kurta, True), (pyjama, False)])
    await _commit(cat, ev(pyjama, "deposited", cat.clock()))
    [sv] = cat.store.desk.counts.set_views(await cat.store.view(UID))
    return _want(not sv.wearable and sv.alone == (kurta,), "set availability")


async def inv13() -> list[str]:
    cat = catalog()
    await cat.store.desk.places.add(UID, "Tray")
    bag = await cat.store.desk.places.add(UID, "Travel bag", "travel")
    [watch] = await _add(cat, NewPiece(type="watch"))
    await cat.store.desk.service.move(UID, watch, "travel bag")
    cat.clock.advance(days=20)
    view = await cat.store.view(UID)
    words = cat.store.desk.views.place_words(view, view.pieces[watch])
    return _want(view.pieces[watch].place == bag.id and words.endswith("(last known)"), words)


async def inv14() -> list[str]:
    cat = catalog()
    socks = await _add(cat, *(NewPiece(type="sock") for _ in range(4)))
    await cat.store.desk.links.pair(UID, socks[0], socks[1])
    await cat.store.desk.links.pair(UID, socks[2], socks[3])
    await _commit(cat, ev(socks[3], "missing", cat.clock()))
    c = cat.store.desk.counts.of(await cat.store.view(UID))
    return _want((c.owned, c.pairs_complete) == (4, 1), "missing sock counts")


async def inv15() -> list[str]:
    cat = catalog()
    d, h = (
        await cat.store.desk.places.add(UID, "Drawer 2"),
        await cat.store.desk.places.add(UID, "Hook"),
    )
    await _add(
        cat,
        NewPiece(type="belt", colour="black", place=d.id),
        NewPiece(type="belt", colour="black", place=h.id),
    )
    two = await cat.store.desk.search.find(UID, "where is my black belt")
    none = await cat.store.desk.search.find(UID, "where is my passport")
    return _want(two.best is None and len(two.matches) == 2 and none.matches == (), "find")


async def inv16() -> list[str]:
    cat = catalog()
    keep, other = await _add(cat, NewPiece(type="watch"), NewPiece(type="watch"))
    await cat.store.desk.merge.merge(UID, keep, other)
    view = await cat.store.view(UID)
    hist = await cat.store.desk.merge.history(UID, keep)
    return _want([p.id for p in view.active()] == [keep] and len(hist) == 3, "merge")


async def inv17() -> list[str]:
    cat = catalog()
    [belt] = await _add(cat, NewPiece(type="belt"))
    await _commit(cat, ev(belt, "archived", cat.clock()))
    out = cat.store.desk.counts.of(await cat.store.view(UID)).owned
    cat.clock.advance(minutes=1)
    await _commit(cat, ev(belt, "restored", cat.clock()))
    state = (await cat.store.view(UID)).pieces[belt].state
    return _want(out == 0 and state == "review", "archive and restore")


async def ops03() -> list[str]:
    cat = catalog()
    [shirt] = await _add(cat, NewPiece(type="shirt"))
    t0 = cat.clock()
    cat.clock.advance(hours=1)
    tap = ev(shirt, "deposited", cat.clock(), client_id="tap-0000001")
    await _commit(cat, tap)
    await _commit(cat, ev(shirt, "deposited", cat.clock(), client_id="tap-0000001"))  # a retry
    cat.clock.advance(hours=2)
    await _commit(cat, ev(shirt, "returned", cat.clock()))
    await _commit(
        cat, ev(shirt, "deposited", t0 + timedelta(minutes=30), verified=False, how="match")
    )
    kinds = [h.event.kind for h in await cat.store.history(UID, shirt)]
    state = (await cat.store.view(UID)).pieces[shirt].state
    out = _want(state == "ready", f"an old basket event made it {state}")
    return out + _want(kinds.count("deposited") == 2, f"{kinds.count('deposited')} deposits kept")


async def ops06() -> list[str]:
    cat = catalog()
    [shirt] = await _add(cat, NewPiece(type="shirt"))
    await cat.store.desk.vault.prints.save(UID, shirt, "front", "mnv2-int8-1", fp(1))
    await cat.store.desk.vault.save(UID, shirt, "front", jpeg())
    body = await cat.store.desk.backup.file(UID, photos=True)
    fresh = catalog(clock=cat.clock)
    check = await fresh.store.desk.restore.check(UID, body)
    wrote = bool(fresh.docs._data)  # noqa: SLF001 - the check writes nothing
    await fresh.store.desk.restore.apply(UID, body, check.token)
    again = await fresh.store.desk.restore.apply(UID, body, check.token)
    same = sorted((await fresh.store.view(UID)).pieces) == [shirt]
    return _want(not wrote and same and again.counts.events == 0, "restore")


CASES: dict[str, Case] = {
    **{f"INV-{n:02d}": globals()[f"inv{n:02d}"] for n in range(1, 18)},
    "OPS-03": ops03,
    "OPS-06": ops06,
}


async def _run(names: list[str] | None = None) -> list[dict[str, Any]]:
    out = []
    for name, case in CASES.items():
        if names is not None and name not in names:
            continue
        try:
            failures = await case()
        except Exception as exc:  # noqa: BLE001 - a case that breaks is a failed case
            failures = [f"raised {type(exc).__name__}"]
        out.append({"id": f"{PART}:{name}", "passed": not failures, "failures": failures})
    return out


async def cases() -> list[dict[str, Any]]:
    return await _run()


def _no_candidates() -> Any:
    real = CatalogService.add

    async def intake(self: CatalogService, uid: str, spec: NewPiece, *, candidate: str | None,
                     source: str = "phone") -> Any:  # fmt: skip
        return await real(self, uid, [spec], source=source)

    return mock.patch.object(CatalogService, "intake", intake)


def _no_dedup() -> Any:
    async def append(self: Any, w: Any, uid: str, tx: Any, events: Any, as_stored: bool) -> None:
        from jarvis.wardrobe.catalog import fold as folding

        for raw in events:
            p = w.pieces.get(raw.piece)
            if raw.piece not in w.logs:
                w.logs[raw.piece] = await self._read_log(tx.get, uid, p)
            e = folding.settle(raw.model_copy(update={"id": ev(raw.piece, raw.kind, raw.at).id}),
                               self.now(), w.logs[raw.piece])  # fmt: skip
            w.logs[raw.piece].append(e)
            w.new.setdefault(e.piece, []).append(e)

    return mock.patch.object(store_mod.CatalogStore, "_append", append)


async def control() -> dict[str, Any]:
    failed: list[str] = []
    for patch, names in ((_no_candidates, ["INV-05"]), (_no_dedup, ["INV-08", "OPS-03"])):
        with ExitStack() as stack:
            stack.enter_context(patch())
            got = await _run(names)
        failed += [r["id"] for r in got if not r["passed"]]
    want = {f"{PART}:INV-05", f"{PART}:INV-08", f"{PART}:OPS-03"}
    return {
        "name": "candidates off; the dedup off",
        "suite_failed": want <= set(failed),
        "failed_cases": failed,
    }


__all__ = ["BUILT", "CASES", "PART", "cases", "control"]
