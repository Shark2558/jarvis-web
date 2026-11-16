# tests/test_r13_b_part.py -- R13 Part B's one join (docs/plans/r13-wardrobe.md "Part split",
# jarvis.wardrobe.ports): `build(ctx)` returns WardrobePart("laundry") with only B's five tools,
# B's daily job, B's one service (`review_writer`, a `ReviewWriter`) and B's data; it passes the
# wiring's contract check, also with no key and no store (the tools then say so), and its ready
# word says plainly what works.
from __future__ import annotations

import dataclasses

from fastapi import FastAPI
from r13_fakes import wardrobe_context

from jarvis.api import r13_wiring as wiring
from jarvis.keyring import Keyring
from jarvis.wardrobe.laundry import part as laundry_part
from jarvis.wardrobe.ports import (
    JOB_OWNER,
    SERVICE_OWNER,
    TOOL_OWNER,
    ReviewWriter,
    WardrobeData,
)

ROOT = bytes(range(1, 33))


def test_the_part_owns_only_its_tools_job_service_and_data() -> None:
    ctx = dataclasses.replace(wardrobe_context(), keyring=Keyring(ROOT))
    part = wiring.check_part("laundry", laundry_part.build(ctx))
    assert {t.name for t in part.tools} == {n for n, o in TOOL_OWNER.items() if o == "laundry"}
    assert [j.name for j in part.daily_jobs] == [n for n, o in JOB_OWNER.items() if o == "laundry"]
    assert part.clock_jobs == () and part.observers == () and part.privacy == ()
    assert set(part.services) == {n for n, o in SERVICE_OWNER.items() if o == "laundry"}
    assert isinstance(part.services["review_writer"], ReviewWriter)
    assert all(isinstance(d, WardrobeData) for d in part.data)
    assert part.ready == laundry_part.READY


def test_without_a_key_or_a_store_it_still_builds_and_says_so() -> None:
    part = wiring.check_part("laundry", laundry_part.build(wardrobe_context()))
    assert part.ready == laundry_part.READY_NO_KEY
    assert part.ready == "Laundry off: this server has no token key"
    assert len(part.tools) == 5  # the tools answer in words; the wiring still lists them


def test_the_wiring_builds_b_and_binds_its_writer() -> None:
    ctx = dataclasses.replace(wardrobe_context(), keyring=Keyring(ROOT))
    parts = wiring.build_parts(ctx)
    assert parts["laundry"].ready == laundry_part.READY
    app = FastAPI()
    app.state.r13_parts = parts
    assert "laundry_daily" in [j.name for j in wiring.r13_tick_jobs(app)]
    names = [t.name for t in wiring.r13_tools(parts)]
    assert {"laundry_status", "laundry_move"} <= set(names)
