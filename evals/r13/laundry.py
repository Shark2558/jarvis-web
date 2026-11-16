# evals/r13/laundry.py
"""R13 eval, Part B's suite (`laundry`, BUILT): LND-01-08, LND-10-15 and OPS-02 on I0's in-memory
store (`tests/r13_fakes.py`, fixed IST clocks) with Part B built through its one join
(`tests/r13_fakes_b.py`): one case per use case, each the workbook's acceptance check.

Negative control (plan "Tests and evals"): holds off (`holds.hold_events` makes nothing). Then
LND-03 (the pending deposit holds the plausible piece), LND-04 (both near-identical shirts
withheld) and OPS-02 (the pieces touched are held until checked) must fail, and only those: a
suite that cannot fail proves nothing.
"""

from __future__ import annotations

import sys
from collections.abc import Awaitable, Callable
from datetime import date
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tests"))
from r13_fakes import UID, ev, ist  # noqa: E402
from r13_fakes_b import (  # noqa: E402
    BLAZER,
    BLUE_SHIRT,
    DRAWER,
    JACKET,
    JEANS,
    NAVY_SHIRT,
    RACK,
    SOCK_L,
    SOCK_PAIR,
    SOCK_R,
    TEE,
    TRAY,
    TROUSERS,
    TWIN,
    WATCH,
    WHITE_SHIRT,
    Rig,
    rig,
)

from jarvis.wardrobe.laundry import holds  # noqa: E402
from jarvis.wardrobe.states import owned, wearable_pair  # noqa: E402

PART = "laundry"
BUILT = True
CONTROL_FAILS = ("laundry:lnd_03", "laundry:lnd_04", "laundry:ops_02")
Case = Callable[[], Awaitable[list[str]]]


def _want(ok: bool, words: str) -> list[str]:
    return [] if ok else [words]


async def _states(r: Rig, *pids: str) -> list[str]:
    return [await r.state(p) for p in pids]


async def lnd_01() -> list[str]:
    r = await rig()
    before = sum(1 for p in (await r.view()).active() if owned(p.state))
    await r.desk.move(UID, "basket", pieces=(NAVY_SHIRT,))
    shirt = await r.piece(NAVY_SHIRT)
    after = sum(1 for p in (await r.view()).active() if owned(p.state))
    return _want(not shirt.eligible and after == before, "a deposit left the owned or ready set")


async def lnd_02() -> list[str]:
    r = await rig()
    await r.commit(holds.admit(ev(WHITE_SHIRT, "deposited", r.clock(), source="camera")))
    entries = await r.open_entries()
    return _want(
        await r.state(WHITE_SHIRT) == "review" and len(entries) == 1,
        "a camera deposit without a release did not go to review",
    )


async def lnd_03() -> list[str]:
    r = await rig()
    await r.wear(BLUE_SHIRT)
    await r.desk.move(UID, "basket", pieces=(JACKET,), more=1, category="tops")
    (entry,) = await r.open_entries()
    return _want(
        await _states(r, JACKET, BLUE_SHIRT) == ["in_laundry", "review"] and entry.count == 1,
        "the pending deposit did not hold the plausible shirt",
    )


async def lnd_04() -> list[str]:
    r = await rig()
    await r.desk.move(UID, "basket", query="white shirt")
    held = await _states(r, WHITE_SHIRT, TWIN) == ["review", "review"]
    (entry,) = await r.open_entries()
    await r.desk.resolve(UID, entry.id, "none")
    back = await _states(r, WHITE_SHIRT, TWIN) == ["ready", "ready"]
    return _want(held and back, "both copies were not withheld, or 'no deposit' did not clear")


async def lnd_05() -> list[str]:
    r = await rig()
    dirty = await r.desk.move(UID, "basket", pieces=(BLUE_SHIRT,))
    await r.desk.move(UID, "ready", pieces=(BLUE_SHIRT,), place=RACK)
    assert dirty.committed is not None
    await r.desk.correct(UID, BLUE_SHIRT, dirty.committed.events[0].id)
    return _want(await r.state(BLUE_SHIRT) == "ready", "a correction overwrote a clean return")


async def lnd_06() -> list[str]:
    r = await rig()
    await r.desk.move(UID, "basket", pieces=(WHITE_SHIRT,))
    await r.desk.move(UID, "lifted", pieces=(WHITE_SHIRT,), place=DRAWER)
    return _want(not (await r.piece(WHITE_SHIRT)).eligible, "a lifted shirt became available")


async def lnd_07() -> list[str]:
    r = await rig()
    seven = (BLUE_SHIRT, WHITE_SHIRT, NAVY_SHIRT, TEE, JEANS, TROUSERS, JACKET)
    await r.desk.move(UID, "basket", pieces=seven)
    commits = len(r.docs.tx_sizes)
    await r.desk.move(UID, "load", pieces=seven[:5])
    ok = await _states(r, *seven) == ["washing"] * 5 + ["in_laundry"] * 2
    return _want(ok and len(r.docs.tx_sizes) == commits + 1, "the load was not one commit")


async def lnd_08() -> list[str]:
    r = await rig()
    five = (BLUE_SHIRT, WHITE_SHIRT, NAVY_SHIRT, TEE, JEANS)
    await r.desk.move(UID, "basket", pieces=five)
    load = (await r.desk.move(UID, "load", pieces=five)).load
    await r.desk.move(UID, "drying", pieces=five[:3], load=load)
    ok = await _states(r, *five) == ["drying"] * 3 + ["washing"] * 2
    return _want(ok, "drying moved more than the three named")


async def lnd_10() -> list[str]:
    r = await rig()
    await r.desk.move(UID, "basket", pieces=(BLUE_SHIRT, WHITE_SHIRT))
    load = (await r.desk.move(UID, "load", pieces=(BLUE_SHIRT, WHITE_SHIRT))).load
    await r.desk.move(UID, "drying", pieces=(BLUE_SHIRT,), load=load)
    await r.desk.move(UID, "prep", pieces=(WHITE_SHIRT,), load=load)
    out = not any([(await r.piece(p)).eligible for p in (BLUE_SHIRT, WHITE_SHIRT)])
    await r.desk.move(UID, "ready", pieces=(BLUE_SHIRT, WHITE_SHIRT), place=RACK)
    back = all([(await r.piece(p)).eligible for p in (BLUE_SHIRT, WHITE_SHIRT)])
    return _want(out and back, "damp or unpressed pieces were available before their return")


async def lnd_11() -> list[str]:
    r = await rig()
    await r.desk.move(UID, "basket", pieces=(NAVY_SHIRT,))
    r.observer.heard.clear()
    await r.desk.move(UID, "ready", pieces=(NAVY_SHIRT,), place=RACK)
    shirt = await r.piece(NAVY_SHIRT)
    heard = [c.piece for c in r.observer.heard]
    return _want(shirt.eligible and heard == [NAVY_SHIRT], "the return lost its id or plan check")


async def lnd_12() -> list[str]:
    r = await rig()
    six = (BLUE_SHIRT, WHITE_SHIRT, NAVY_SHIRT, TEE, JEANS, TROUSERS)
    await r.desk.move(UID, "basket", pieces=six)
    load = (await r.desk.move(UID, "load", pieces=six)).load
    await r.desk.move(UID, "ready", pieces=six[:4], load=load, place=RACK)
    view = await r.view()
    ok = [view.pieces[p].eligible for p in six] == [True] * 4 + [False] * 2
    return _want(ok, "a part-return did not restore exactly four")


async def lnd_13() -> list[str]:
    r = await rig()
    await r.desk.move(UID, "basket", pieces=(SOCK_L, SOCK_R))
    await r.desk.move(UID, "ready", pieces=(SOCK_L,), place=DRAWER)
    view = await r.view()
    pair = view.pairs[SOCK_PAIR]
    half = not wearable_pair([view.pieces[p].state for p in pair.pieces])
    return _want(half and view.pieces[SOCK_L].eligible, "a half pair was offered as a pair")


async def lnd_14() -> list[str]:
    r = await rig()
    sent = await r.desk.send_out(
        UID, (BLAZER, TROUSERS, JACKET), "Dry cleaner", due=date(2026, 11, 18)
    )
    assert sent.batch is not None
    await r.desk.receive(UID, sent.batch, (BLAZER, TROUSERS))
    (batch,) = (await r.laundry()).batches
    states = await _states(r, BLAZER, TROUSERS, JACKET)
    ok = states == ["ready", "ready", "with_provider"] and batch.short
    return _want(ok, "two of three back did not leave the batch short with one out")


async def lnd_15() -> list[str]:
    r = await rig()
    await r.desk.move(UID, "basket", pieces=(WHITE_SHIRT,))
    load = (await r.desk.move(UID, "load", pieces=(WHITE_SHIRT,))).load
    await r.desk.move(UID, "drying", load=load)
    got = await r.desk.history(UID, piece=WHITE_SHIRT)
    latest = got.get("latest_verified") or {}
    return _want(
        got["state"] == "drying" and latest.get("kind") == "dried",
        "the history did not show Drying and its latest verified move",
    )


async def ops_02() -> list[str]:
    r = await rig(at=ist(2026, 11, 16, 9, 0))
    await r.desk.blind(UID, places=(TRAY,))
    held = not (await r.piece(WATCH)).eligible
    (entry,) = await r.open_entries()
    await r.desk.resolve(UID, entry.id, "these")
    return _want(held and (await r.piece(WATCH)).eligible, "a blind period did not hold the tray")


CASES: dict[str, Case] = {
    "lnd_01": lnd_01, "lnd_02": lnd_02, "lnd_03": lnd_03, "lnd_04": lnd_04, "lnd_05": lnd_05,
    "lnd_06": lnd_06, "lnd_07": lnd_07, "lnd_08": lnd_08, "lnd_10": lnd_10, "lnd_11": lnd_11,
    "lnd_12": lnd_12, "lnd_13": lnd_13, "lnd_14": lnd_14, "lnd_15": lnd_15, "ops_02": ops_02,
}  # fmt: skip


async def _run(name: str, case: Case) -> dict[str, Any]:
    try:
        failures = await case()
    except Exception as exc:  # noqa: BLE001 - a case that raises fails, with the class name
        failures = [f"raised {type(exc).__name__}"]
    return {"id": f"{PART}:{name}", "passed": not failures, "failures": failures}


async def cases() -> list[dict[str, Any]]:
    return [await _run(name, case) for name, case in CASES.items()]


async def control() -> dict[str, Any]:
    real = holds.hold_events
    holds.hold_events = lambda *a, **k: ()  # type: ignore[assignment]  # holds off
    try:
        results = await cases()
    finally:
        holds.hold_events = real  # type: ignore[assignment]
    failed = [r["id"] for r in results if not r["passed"]]
    return {
        "name": "holds off",
        "suite_failed": bool(failed) and set(failed) == set(CONTROL_FAILS),
        "failed_cases": failed,
    }
