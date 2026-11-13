# tests/test_r7_b_store.py -- R7 Part B (docs/plans/r7-mobile.md D12, data model): the results he
# pressed Keep on. One sealed document a day (`vision_results/{uid}_{yyyymmdd}`, the `vision`
# key, 90 days); a result outside its task's schema is dropped and never stored or repaired; the
# read text never sits in the clear; a document moved to another day or sealed under another key
# is refused; the sweep removes the days past the keep.
from __future__ import annotations

import asyncio
import json
from datetime import timedelta

import pytest
from r7_fakes_b import (
    LABEL_TEXT,
    OTHER_KEY,
    QR_TEXT,
    UID,
    Clock,
    code_result,
    objects_result,
    quality_result,
    result,
    store,
    text_result,
)

from jarvis.storage.docs import MemoryDocs
from jarvis.vision.store import (
    COLLECTION,
    PER_DAY_MAX,
    DayFull,
    Dropped,
    TooBig,
    VisionOff,
    VisionUnavailable,
)


async def test_a_kept_result_is_listed_with_an_id_and_sealed() -> None:
    docs = MemoryDocs()
    s = store(docs=docs)
    kept = await s.keep(UID, text_result())
    assert kept["id"].startswith("vr_") and kept["task"] == "text"
    assert kept["data"]["text"] == LABEL_TEXT
    listed = await s.list(UID, days=7)
    assert [k["id"] for k in listed] == [kept["id"]]
    raw = await docs.get(f"jarvis_{COLLECTION}/{UID}_20261113")
    assert raw is not None and raw["uid"] == UID and raw["day"] == "2026-11-13" and raw["n"] == 1
    flat = json.dumps(raw)
    assert "MRP" not in flat and "125" not in flat and "text" not in flat  # sealed, no task word
    assert s.sealed is True


@pytest.mark.parametrize(
    "raw",
    [
        None,
        "text",
        {**text_result(), "pixels": "iVBORw0KGgo="},  # an unknown field: pixels never ride along
        text_result("x" * 2001),
        text_result(ok=False),
        result(
            "objects",
            {
                "objects": [
                    {"label": "dragon", "score": 0.9, "box": {"x": 0, "y": 0, "w": 1, "h": 1}}
                ]
            },
        ),  # fmt: skip
        result("pose", {"points": [{"x": 0.5, "y": 0.5, "z": 0.0, "visibility": 1.0}] * 34}),
        result("code", {"codes": [{"format": "qr_code", "value": "x", "image": "AAAA"}]}),
        result("quality", {"light": 1.5, "sharp": 0.2}),
        result("faces", {"faces": 1}),
        {**quality_result(), "device": "laptop"},
    ],
)
async def test_a_result_outside_its_schema_is_dropped_and_nothing_is_stored(raw: object) -> None:
    docs = MemoryDocs()
    s = store(docs=docs)
    with pytest.raises(Dropped):
        await s.keep(UID, raw)
    assert docs.sets == 0 and await s.list(UID, days=90) == []


async def test_every_task_with_good_data_is_kept_newest_first() -> None:
    clock = Clock()
    s = store(clock)
    first = await s.keep(UID, code_result())
    clock.at += timedelta(days=1)
    second = await s.keep(UID, objects_result())
    third = await s.keep(UID, quality_result())
    listed = await s.list(UID, days=7)
    assert [k["id"] for k in listed] == [third["id"], second["id"], first["id"]]
    assert listed[-1]["data"]["codes"][0]["value"] == QR_TEXT
    assert await s.count(UID) == 3


async def test_a_day_holds_at_most_its_cap() -> None:
    s = store()
    for _ in range(PER_DAY_MAX):
        await s.keep(UID, quality_result())
    with pytest.raises(DayFull):
        await s.keep(UID, quality_result())
    assert await s.count(UID) == PER_DAY_MAX


async def test_one_result_and_then_everything_can_be_deleted() -> None:
    s = store()
    a = await s.keep(UID, text_result())
    b = await s.keep(UID, quality_result())
    assert await s.delete(UID, a["id"]) is True
    assert await s.delete(UID, a["id"]) is False
    assert await s.delete(UID, "vr_nothere0000") is False
    assert [k["id"] for k in await s.list(UID, days=7)] == [b["id"]]
    assert await s.delete_all(UID) == 1
    assert await s.list(UID, days=7) == [] and await s.count(UID) == 0


async def test_the_last_delete_of_a_day_removes_its_document() -> None:
    docs = MemoryDocs()
    s = store(docs=docs)
    a = await s.keep(UID, text_result())
    assert await s.delete(UID, a["id"]) is True
    assert await docs.get(f"jarvis_{COLLECTION}/{UID}_20261113") is None


async def test_days_past_the_keep_are_not_listed_and_the_sweep_removes_them() -> None:
    clock = Clock()
    docs = MemoryDocs()
    s = store(clock, docs=docs, keep_days=90)
    await s.keep(UID, text_result())
    clock.at += timedelta(days=90)
    await s.keep(UID, quality_result())
    assert len(await s.list(UID, days=90)) == 1  # the first day is past the keep
    assert await s.sweep(UID) == 1
    assert await docs.get(f"jarvis_{COLLECTION}/{UID}_20261113") is None
    assert await s.sweep(UID) == 0


async def test_without_a_token_key_nothing_is_kept() -> None:
    s = store(key=None)
    assert s.sealed is False
    with pytest.raises(VisionOff, match="token key"):
        await s.keep(UID, text_result())
    with pytest.raises(VisionOff):
        await s.list(UID, days=7)
    assert await s.count(UID) == 0


async def test_a_document_under_another_key_or_moved_to_another_day_is_refused() -> None:
    docs = MemoryDocs()
    await store(docs=docs).keep(UID, text_result())
    with pytest.raises(VisionUnavailable):
        await store(docs=docs, key=OTHER_KEY).list(UID, days=7)
    path = f"jarvis_{COLLECTION}/{UID}_20261113"
    raw = await docs.get(path)
    assert raw is not None
    await docs.transaction(_move(path, f"jarvis_{COLLECTION}/{UID}_20261112", raw))
    with pytest.raises(VisionUnavailable):
        await store(docs=docs).list(UID, days=7)


def _move(old: str, new: str, raw: dict[str, object]):  # type: ignore[no-untyped-def]
    async def work(tx):  # type: ignore[no-untyped-def]
        tx.delete(old)
        tx.set(new, {**raw, "day": "2026-11-12"})

    return work


async def test_a_bad_owner_id_is_refused() -> None:
    with pytest.raises(ValueError):
        await store().keep("../other", text_result())


async def test_an_export_lists_what_was_kept_and_never_the_blob() -> None:
    s = store()
    await s.keep(UID, text_result())
    out = await s.export(UID)
    assert out["results"][0]["data"]["text"] == LABEL_TEXT
    assert "blob" not in json.dumps(out)


# ---- review follow-ups: size limits, pagination, one unreadable day --------------------------
def big_code(n: int = 20, size: int = 1900) -> dict[str, object]:
    codes = [{"format": "qr_code", "value": chr(97 + i) * size} for i in range(n)]
    return result("code", {"codes": codes})


async def test_a_kept_day_never_passes_the_document_limit() -> None:
    s = store()
    kept = 0
    with pytest.raises((DayFull, TooBig)):
        for _ in range(60):
            await s.keep(UID, big_code(8))
            kept += 1
    raw = await s._docs.get(f"jarvis_{COLLECTION}/{UID}_20261113")
    assert raw is not None and len(json.dumps(raw)) < 1_000_000
    assert kept >= 1 and await s.count(UID) == kept


async def test_a_full_day_says_so_in_plain_words() -> None:
    s = store()
    with pytest.raises(DayFull, match="That day's results are full, Sir"):
        for _ in range(60):
            await s.keep(UID, big_code(8))


async def test_one_result_that_is_too_big_is_dropped_and_nothing_is_written() -> None:
    s = store()
    with pytest.raises(TooBig, match="too big"):
        await s.keep(UID, big_code())
    assert await s.count(UID) == 0 and await s.list(UID, days=7) == []


async def test_the_daily_cap_holds_when_a_hundred_and_one_keeps_race() -> None:
    s = store()
    outcomes = await asyncio.gather(
        *(s.keep(UID, quality_result()) for _ in range(PER_DAY_MAX + 1)), return_exceptions=True
    )
    assert sum(isinstance(o, DayFull) for o in outcomes) == 1
    assert sum(isinstance(o, dict) for o in outcomes) == PER_DAY_MAX
    assert await s.count(UID) == PER_DAY_MAX


async def test_a_page_of_results_comes_with_its_total() -> None:
    s = store()
    for _ in range(5):
        await s.keep(UID, quality_result())
    page = await s.page(UID, days=7, limit=2, offset=0)
    assert len(page.items) == 2 and page.total == 5 and page.unreadable == 0
    last = await s.page(UID, days=7, limit=2, offset=4)
    assert len(last.items) == 1
    assert [i["id"] for i in (await s.page(UID, days=7, limit=50, offset=0)).items] == [
        i["id"] for i in await s.list(UID, days=7)
    ]


async def _break_day(docs: MemoryDocs, day: str) -> None:
    path = f"jarvis_{COLLECTION}/{UID}_{day}"
    raw = await docs.get(path)
    assert raw is not None

    async def work(tx):  # type: ignore[no-untyped-def]
        tx.set(path, {**raw, "blob": "not a sealed blob"})

    await docs.transaction(work)


async def test_one_unreadable_day_never_hides_or_blocks_the_others() -> None:
    clock = Clock()
    docs = MemoryDocs()
    s = store(clock, docs=docs)
    old = await s.keep(UID, text_result())
    clock.at += timedelta(days=1)
    a = await s.keep(UID, quality_result())
    b = await s.keep(UID, code_result())
    await _break_day(docs, "20261113")
    page = await s.page(UID, days=7, limit=50, offset=0)
    assert {i["id"] for i in page.items} == {a["id"], b["id"]} and page.unreadable == 1
    assert {i["id"] for i in (await s.export(UID))["results"]} == {a["id"], b["id"]}
    assert await s.delete(UID, a["id"]) is True  # another day's delete still works
    assert await s.delete(UID, old["id"]) is False  # the unreadable day's own item can't open
    assert await s.delete_all(UID) >= 1


async def test_an_unreadable_day_is_still_never_overwritten() -> None:
    docs = MemoryDocs()
    s = store(docs=docs)
    await s.keep(UID, text_result())
    await _break_day(docs, "20261113")
    with pytest.raises(VisionUnavailable):
        await s.keep(UID, quality_result())
