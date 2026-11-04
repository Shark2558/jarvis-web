# tests/test_activity_store.py -- R1 B: Activity rows on the Docs port, per owner and per local day.
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from jarvis.activity.models import ActivityItem
from jarvis.activity.store import ActivityStore
from jarvis.storage.docs import MemoryDocs, Set

NOW = datetime(2026, 11, 5, 10, 0, tzinfo=UTC)


def item(n: int, uid: str = "owner", at: datetime = NOW, **kw: Any) -> ActivityItem:
    base: dict[str, Any] = {
        "id": f"act_{n:020x}",
        "user_id": uid,
        "at": at,
        "tool": "task_add",
        "risk": "reversible",
        "kind": "write",
        "outcome": "done",
        "words": f"Add a to-do {n}",
        "channel": "console",
        "offline": False,
        "session_id": "s1",
        "trace_id": "t1",
        "audit_seq": n,
        "undo_id": None,
    }
    return ActivityItem(**{**base, **kw})


async def test_add_then_read_back_newest_first() -> None:
    st = ActivityStore(MemoryDocs())
    await st.add(item(1, at=NOW), "20261105")
    await st.add(item(2, at=NOW + timedelta(minutes=5)), "20261105")
    rows = await st.day("owner", "20261105")
    assert [r.audit_seq for r in rows] == [2, 1]
    assert rows[0].words == "Add a to-do 2" and rows[0].undo_id is None


async def test_one_owner_never_reads_anothers_rows() -> None:
    st = ActivityStore(MemoryDocs())
    await st.add(item(1, "alice"), "20261105")
    await st.add(item(2, "bob"), "20261105")
    assert [r.user_id for r in await st.day("alice", "20261105")] == ["alice"]
    assert await st.day("carol", "20261105") == []


async def test_a_bad_owner_or_day_is_refused_not_queried() -> None:
    st = ActivityStore(MemoryDocs())
    assert await st.day("../x", "20261105") == []
    assert await st.day("owner", "2026-11-05") == []
    with pytest.raises(ValueError):
        await st.add(item(1, "a/b"), "20261105")


async def test_an_unreadable_row_is_skipped() -> None:
    docs = MemoryDocs()
    st = ActivityStore(docs)
    await st.add(item(1), "20261105")
    await docs.write([Set("jarvis_activity/owner/d20261105/act_bad", {"nonsense": True})])
    assert len(await st.day("owner", "20261105")) == 1


async def test_sweep_removes_days_older_than_the_cutoff_only() -> None:
    st = ActivityStore(MemoryDocs())
    await st.add(item(1), "20261101")
    await st.add(item(2), "20261103")
    await st.add(item(3), "20261105")
    gone = await st.sweep(["owner"], keep_from="20261103")
    assert gone == 1
    assert await st.day("owner", "20261101") == []
    assert len(await st.day("owner", "20261103")) == 1
    assert len(await st.day("owner", "20261105")) == 1


async def test_sweep_never_raises() -> None:
    class Broken(MemoryDocs):
        async def query(self, q: Any) -> Any:
            raise RuntimeError("down")

    assert await ActivityStore(Broken()).sweep(["owner"], keep_from="20261103") == 0


async def test_sweep_removes_every_old_day_however_old_and_all_rows_of_a_day() -> None:
    st = ActivityStore(MemoryDocs())
    await st.add(item(1), "20260915")  # 50+ days before the cutoff
    await st.add(item(2), "20261001")
    for n in range(10, 1210):  # a day with more rows than one batch
        await st.add(item(n), "20261020")
    await st.add(item(3), "20261104")
    gone = await st.sweep(["owner"], keep_from="20261104")
    assert gone == 1202
    for day in ("20260915", "20261001", "20261020"):
        assert await st.day("owner", day) == []
    assert len(await st.day("owner", "20261104")) == 1
    assert await st.sweep(["owner"], keep_from="20261104") == 0  # nothing left to do


async def test_sweep_only_touches_the_given_owners() -> None:
    st = ActivityStore(MemoryDocs())
    await st.add(item(1, "alice"), "20261001")
    await st.add(item(2, "bob"), "20261001")
    assert await st.sweep(["alice"], keep_from="20261104") == 1
    assert len(await st.day("bob", "20261001")) == 1
