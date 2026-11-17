# tests/test_r131_a_part.py -- R13.1 Part A's join (`wardrobe/tryon/part.py`) through I0's REAL
# wiring (`api/r13_wiring.build_parts`, `check_part`): `WardrobePart("tryon")` with no tool, job or
# `data`, only its three Privacy rows, the `tryon_looks` service (C reads it late through
# `ports.looks_service`), one plain ready word; Off in words with no storage, no token key or
# Try-on switched off, and then no service and nothing kept in clear.
from __future__ import annotations

from typing import Any

from r131_fakes import RING, FixedClock, ist

from jarvis.api import r13_wiring as wiring
from jarvis.config import Settings
from jarvis.keyring import Keyring
from jarvis.storage.docs import MemoryDocs
from jarvis.wardrobe.ports import WardrobeContext
from jarvis.wardrobe.tryon import kept
from jarvis.wardrobe.tryon.part import OFF_NO_KEY, OFF_NO_STORE, OFF_SWITCHED, READY, build
from jarvis.wardrobe.tryon.ports import TryonLooks, looks_service


def _ctx(
    *, docs: MemoryDocs | None = None, ring: Keyring | None = RING, s: Settings | None = None,
    state: dict[str, Any] | None = None,
) -> WardrobeContext:  # fmt: skip
    async def zone(uid: str) -> Any:
        return None

    return WardrobeContext(
        s=s or Settings(_env_file=None), docs=docs if docs is not None else MemoryDocs(),
        keyring=ring, audit=None, now=FixedClock(ist(2026, 11, 17, 9, 0)), zone=zone,
        state=(state if state is not None else {}).get,
    )  # fmt: skip


def test_the_built_part_passes_the_contract_with_its_rows_and_service() -> None:
    part = wiring.check_part("tryon", build(_ctx()))
    assert part.ready == READY and part.tools == () and part.data == ()
    assert part.clock_jobs == () and part.daily_jobs == () and part.observers == ()
    assert [r.id for r in part.privacy] == [kept.FIGURE_ID, kept.ALL_ID, kept.DEVICE_ID]
    assert set(part.services) == {"tryon_looks"}
    assert isinstance(part.services["tryon_looks"], TryonLooks)


def test_the_real_wiring_builds_it_and_c_reads_its_service_late() -> None:
    state: dict[str, Any] = {}
    ctx = _ctx(state=state)
    parts = wiring.build_parts(ctx)
    assert parts["tryon"].ready == READY  # built, not "setup failed"
    assert looks_service(ctx) is None  # read late: nothing until the parts are on the app
    state["r13_parts"] = parts
    assert looks_service(ctx) is parts["tryon"].services["tryon_looks"]


def test_off_says_why_in_words_offers_no_service_and_keeps_the_stand_in_rows() -> None:
    cases = (
        (_ctx(ring=None), OFF_NO_KEY),
        (_ctx(s=Settings(_env_file=None, tryon_enabled=False)), OFF_SWITCHED),  # type: ignore[call-arg]
    )
    for ctx, words in cases:
        part = wiring.check_part("tryon", build(ctx))
        assert part.ready == words and part.ready.startswith("Off") and part.services == {}
        assert [r.id for r in part.privacy] == [kept.FIGURE_ID, kept.ALL_ID, kept.DEVICE_ID]


def test_no_storage_is_off_with_no_rows_of_its_own() -> None:
    ctx = WardrobeContext(
        s=Settings(_env_file=None), docs=None, keyring=RING, audit=None,
        now=FixedClock(ist(2026, 11, 17, 9, 0)), zone=lambda uid: None,  # type: ignore[arg-type,return-value]
        state={}.get,
    )  # fmt: skip
    part = build(ctx)
    assert part.ready == OFF_NO_STORE and part.privacy == () and part.services == {}
