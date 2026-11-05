# tests/test_camera_feed.py -- R3 D8/D13/D14: the home feed is sealed, days expire after 7, a
# corrupt day is never overwritten, the privacy delete and export carry ids and no names.
from __future__ import annotations

import json

import pytest
from camera_fakes import OTHER, PERSON, T0, UID, rig

from jarvis.camera.feed import FeedSweepJob
from jarvis.camera.models import FeedItem
from jarvis.camera.ports import CameraUnavailable

DAY = 86400.0


def item(at: float, **kw: object) -> FeedItem:
    base: dict[str, object] = {"at": at, "kind": "intruder", "camera": "gate", "zone": "gate"}
    base.update(kw)
    return FeedItem.model_validate(base)


async def test_lines_are_sealed_and_listed_newest_first() -> None:
    r = await rig()
    await r.feed.add(UID, item(T0, decision="ring", telegram=True, push=1))
    await r.feed.add(UID, item(T0 + 60, kind="package", zone="doorstep"))
    lines = await r.feed.view(UID, "today")
    assert [x["words"] for x in lines][0].startswith("A package was left")
    assert lines[1]["sent"] == {"telegram": True, "push": 1}
    dump = json.dumps(r.docs._data, default=str)
    assert "Burglar" not in dump and "package" not in dump


async def test_yesterday_and_today_are_separate_days() -> None:
    r = await rig()
    await r.feed.add(UID, item(T0 - DAY))
    await r.feed.add(UID, item(T0))
    assert len(await r.feed.view(UID, "today")) == 1
    assert len(await r.feed.view(UID, "yesterday")) == 1


async def test_a_day_holds_at_most_300_lines() -> None:
    r = await rig()
    for i in range(305):
        await r.feed.add(UID, item(T0 + i))
    assert len(await r.feed.day_items(UID, r.feed.local_day(T0))) == 300


async def test_days_older_than_seven_are_swept_for_that_owner_only() -> None:
    r = await rig()
    await r.feed.add(UID, item(T0 - 8 * DAY))
    await r.feed.add(UID, item(T0 - 6 * DAY))
    await r.feed.add(OTHER, item(T0 - 8 * DAY))
    out = await FeedSweepJob(r.feed).run([UID])
    assert out == {"swept": 1, "failed": 0}
    assert len(await r.feed.since(UID, T0 - 9 * DAY)) == 1
    assert len(await r.feed.since(OTHER, T0 - 9 * DAY)) == 1


async def test_a_corrupt_day_is_never_overwritten() -> None:
    r = await rig()
    await r.feed.add(UID, item(T0))
    path = next(p for p in r.docs._data if p.startswith("jarvis_home_feed/"))
    r.docs._data[path]["blob"] = "tampered"
    before = dict(r.docs._data[path])
    with pytest.raises(CameraUnavailable):
        await r.feed.add(UID, item(T0 + 1))
    with pytest.raises(CameraUnavailable):
        await r.feed.view(UID, "today")
    assert r.docs._data[path] == before


async def test_wipe_counts_lines_and_leaves_nothing() -> None:
    r = await rig()
    await r.feed.add(UID, item(T0))
    await r.feed.add(UID, item(T0 - DAY))
    assert await r.feed.count(UID) == 2
    assert await r.feed.wipe(UID) == 2
    assert await r.feed.count(UID) == 0


async def test_export_has_ids_and_times_but_no_names() -> None:
    r = await rig()
    await r.feed.add(UID, item(T0, person=PERSON, score=0.95))
    out = await r.feed.export(UID)
    assert out[0]["person"] == PERSON and "name" not in json.dumps(out)


async def test_the_sweep_job_counts_an_owner_it_could_not_serve() -> None:
    r = await rig()
    assert (await FeedSweepJob(r.feed).run(["bad/owner"]))["failed"] == 1


async def test_a_face_directory_that_raises_makes_the_feed_line_unrecognised_not_fail() -> None:
    r = await rig()

    async def boom(*a: object, **k: object) -> object:
        raise RuntimeError("registry unreadable")

    r.faces.resolve = boom  # type: ignore[method-assign]
    await r.feed.add(UID, item(T0, person=PERSON, score=0.95))
    lines = await r.feed.view(UID, "today")
    assert len(lines) == 1 and "omeone JARVIS didn't recognise" in lines[0]["words"]
