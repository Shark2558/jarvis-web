# tests/test_r7_d_watch_store.py -- R7 Part D (docs/plans/r7-mobile.md D17, D18): the server keeps
# one SEALED summary a day (`watch_days/{uid}_{date}`, key purpose `watch`), never logs a value,
# keeps the writer, keeps a night he typed through every sync, and sweeps after 400 days. Without a
# token key nothing is kept (never in clear); a store that fails says so in plain words.
from __future__ import annotations

import json
import logging
from datetime import date, datetime, timedelta
from typing import Any

import pytest
from r7_fakes_d import UID, BrokenDocs, Clock, settings

from jarvis.keyring import Keyring
from jarvis.storage.docs import MemoryDocs
from jarvis.watch.models import IntakeRefused
from jarvis.watch.service import NoteRefused, WatchService
from jarvis.watch.store import WatchOff, WatchStore, WatchUnavailable

HEART = {"min": 58, "avg": 74, "max": 131, "writer": "com.noisefit"}


def _session(start: str, end: str, writer: str = "com.noisefit", stages: Any = None) -> dict:
    return {"start": start, "end": end, "writer": writer, "stages": stages}


def _body(days: list[dict[str, Any]]) -> bytes:
    return json.dumps({"v": 1, "days": days}).encode()


DAY12 = {
    "date": "2026-11-12",
    "steps": {"count": 8123, "writer": "com.noisefit"},
    "heart": HEART,
    "sleep": [
        _session(
            "2026-11-11T23:50:00+05:30",
            "2026-11-12T06:30:00+05:30",
            stages={"awake": 12, "light": 210, "deep": 80, "rem": 98},
        )
    ],
}


def _world(
    *, keyring: bool = True, docs: Any = None, clock: Clock | None = None, **over: Any
) -> tuple[WatchService, WatchStore, Any, Clock]:
    s = settings(**over)
    ring = Keyring.from_settings(s) if keyring else None
    clock = clock or Clock()
    d = docs if docs is not None else MemoryDocs()
    store = WatchStore(d, ring, prefix=s.firestore_prefix, now=clock)
    return WatchService(store, s, now=clock), store, d, clock


async def test_a_day_is_sealed_and_keeps_its_writer(caplog: pytest.LogCaptureFixture) -> None:
    svc, store, docs, _ = _world()
    with caplog.at_level(logging.DEBUG):
        assert await svc.intake(UID, _body([DAY12])) == 1
    (path,) = [p for p in docs._data if "watch_days" in p]
    doc = docs._data[path]
    assert path.endswith(f"watch_days/{UID}_2026-11-12")
    assert set(doc) == {"uid", "date", "v", "kid", "blob", "updated_at"}
    clear = json.dumps(doc) + caplog.text
    for value in ("8123", "131", "com.noisefit", "210"):
        assert value not in clear, value  # sealed, and never in a log line
    day = await store.day(UID, date(2026, 11, 12))
    assert day is not None and day.steps is not None and day.steps.writer == "com.noisefit"
    assert day.heart is not None and day.heart.max == 131


async def test_a_blob_moved_to_another_day_does_not_open() -> None:
    svc, store, docs, _ = _world()
    await svc.intake(UID, _body([DAY12]))
    prefix = settings().firestore_prefix
    src = docs._data[f"{prefix}watch_days/{UID}_2026-11-12"]
    docs._data[f"{prefix}watch_days/{UID}_2026-11-11"] = {**src, "date": "2026-11-11"}
    with pytest.raises(WatchUnavailable):
        await store.day(UID, date(2026, 11, 11))


async def test_without_a_token_key_nothing_is_kept_and_it_says_why() -> None:
    svc, _, docs, _ = _world(keyring=False)
    with pytest.raises(WatchOff) as ei:
        await svc.intake(UID, _body([DAY12]))
    assert "token key" in str(ei.value) and docs._data == {}


async def test_a_store_that_fails_says_so_in_plain_words() -> None:
    svc, _, _, _ = _world(docs=BrokenDocs())
    with pytest.raises(WatchUnavailable) as ei:
        await svc.intake(UID, _body([DAY12]))
    assert str(ei.value) == WatchUnavailable.WORDS


async def test_a_refused_body_writes_nothing() -> None:
    svc, _, docs, _ = _world()
    bad = {**DAY12, "steps": {"count": -5, "writer": "com.noisefit"}}
    with pytest.raises(IntakeRefused):
        await svc.intake(UID, _body([DAY12, bad]))
    assert docs._data == {}


async def test_the_sync_is_recorded_by_kind_never_by_value() -> None:
    svc, store, docs, clock = _world()
    await svc.intake(UID, _body([DAY12]))
    state = await store.state(UID)
    assert state.last_sync == clock() and state.kinds == {
        "steps": True,
        "heart": True,
        "sleep": True,
    }
    raw = json.dumps(docs._data[f"{settings().firestore_prefix}watch_state/{UID}"])
    assert "8123" not in raw and "58" not in raw


async def test_last_night_from_the_watch_and_from_the_phone() -> None:
    svc, _, _, clock = _world()
    await svc.intake(UID, _body([DAY12]))
    night = await svc.night(UID, date(2026, 11, 12))
    assert night is not None and (night.minutes, night.source) == (400, "watch")
    phone = {
        "date": "2026-11-12",
        "steps": None,
        "heart": None,
        "sleep": [_session("2026-11-11T23:00:00+05:30", "2026-11-12T06:00:00+05:30", "android")],
    }
    await svc.intake(UID, _body([phone]))  # a newer sync replaces the phone's sums for that day
    night = await svc.night(UID, date(2026, 11, 12))
    assert night is not None and night.source == "phone"


async def test_a_night_listed_under_the_day_before_still_counts() -> None:
    svc, _, _, _ = _world()
    under_11 = {**DAY12, "date": "2026-11-11"}  # the phone filed it under the night's start
    await svc.intake(UID, _body([under_11]))
    night = await svc.night(UID, date(2026, 11, 12))
    assert night is not None and night.minutes == 400


async def test_a_typed_night_survives_the_next_sync_and_wins() -> None:
    svc, store, _, clock = _world()
    clock.at = datetime(2026, 11, 12, 3, 30, tzinfo=clock.at.tzinfo)  # 09:00 in Kolkata
    night = await svc.note(UID, "23:30", "06:00")
    assert (night.source, night.minutes, night.start, night.end) == ("typed", 390, "23:30", "06:00")
    await svc.intake(UID, _body([DAY12]))
    got = await svc.night(UID, date(2026, 11, 12))
    assert got is not None and got.source == "typed"
    day = await store.day(UID, date(2026, 11, 12))
    assert day is not None and day.typed is not None and day.steps is not None


@pytest.mark.parametrize(
    ("start", "end"),
    [("25:00", "06:00"), ("23:00", "23:10"), ("12:00", "15:00"), ("6", "7"), ("", "06:00")],
)
async def test_a_typed_time_that_is_not_a_night_is_refused_in_plain_words(
    start: str, end: str
) -> None:
    svc, _, docs, _ = _world()
    with pytest.raises(NoteRefused) as ei:
        await svc.note(UID, start, end)
    assert "Sir" in str(ei.value) and docs._data == {}


async def test_a_typed_end_later_than_now_is_last_nights_of_yesterday() -> None:
    svc, _, _, clock = _world()
    clock.at = datetime(2026, 11, 12, 0, 0, tzinfo=clock.at.tzinfo)  # 05:30 in Kolkata
    await svc.note(UID, "23:00", "06:00")  # 06:00 has not come yet today: it was yesterday's
    assert await svc.night(UID, date(2026, 11, 11)) is not None
    assert await svc.night(UID, date(2026, 11, 12)) is None


async def test_the_week_reads_seven_days() -> None:
    svc, _, _, clock = _world()
    days = []
    for back in range(7):
        d = date(2026, 11, 12) - timedelta(days=back)
        prev = d - timedelta(days=1)
        days.append(
            {
                "date": d.isoformat(),
                "sleep": [_session(f"{prev}T23:30:00+05:30", f"{d}T06:30:00+05:30")],
            }
        )
    await svc.intake(UID, _body(days))
    w = await svc.week(UID, date(2026, 11, 12))
    assert w is not None and (w.nights, w.avg_minutes, w.bed_from, w.bed_to) == (
        7,
        420,
        "23:30",
        "23:30",
    )


async def test_the_sweep_keeps_400_days_and_delete_removes_everything() -> None:
    svc, store, docs, clock = _world()
    await svc.intake(UID, _body([DAY12]))
    prefix = settings().firestore_prefix
    old = {**docs._data[f"{prefix}watch_days/{UID}_2026-11-12"], "date": "2025-10-01"}
    docs._data[f"{prefix}watch_days/{UID}_2025-10-01"] = old
    assert await store.sweep(UID, keep_from=date(2025, 10, 9)) == 1
    assert await store.count(UID) == 1
    assert await store.delete_all(UID) == 1
    assert [p for p in docs._data if "watch_" in p] == []


async def test_the_view_says_last_synced_and_today() -> None:
    svc, _, _, clock = _world()
    empty = await svc.view(UID)
    assert empty["last_synced"] is None and empty["today"] is None and empty["sealed"] is True
    today = {**DAY12, "date": "2026-11-12"}
    await svc.intake(UID, _body([today]))
    v = await svc.view(UID)
    assert v["last_synced"] == clock().isoformat()
    assert v["today"]["steps"] == {"count": 8123, "source": "watch"}
    assert v["today"]["heart"] == {"min": 58, "avg": 74, "max": 131, "source": "watch"}
    assert v["last_night"]["minutes"] == 400 and v["last_night"]["stages"]["deep"] == 80
    assert "writer" not in json.dumps(v)  # the view names watch or phone, never a package
