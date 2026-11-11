# tests/test_r11_c_store.py -- R11 Part C's stores (plan data model): `nudges/{uid}` (his settings
# and free-time list, plain), the claims doc `nudges/{uid}_told` (content-free keys, made in a
# transaction before a send, released when no channel took it) and `wellbeing/{uid}_{date}` (water,
# stand-ups, activity check-ins), sealed with the keyring purpose `wellbeing` (AAD
# `wellbeing/{uid}/v1`): never stored in clear, and OFF without a keyring.
from __future__ import annotations

import asyncio
import json

import pytest
from r11_fakes import UID
from r11_fakes_c import keyring

from jarvis.helpers.nudges.models import Idea
from jarvis.helpers.nudges.store import (
    Checkin,
    NudgeStore,
    NudgesUnavailable,
    WellbeingOff,
    WellbeingStore,
)
from jarvis.storage.docs import MemoryDocs, Set

DAY = "2026-11-10"


async def test_settings_start_at_the_defaults_and_change_in_a_transaction() -> None:
    docs = MemoryDocs()
    store = NudgeStore(docs)
    assert (await store.settings(UID)).rev == 0
    new = await store.change(UID, lambda s: s.changed("nudge_hydrate", {"on": True}))
    assert new.rev == 1 and new.nudge("nudge_hydrate").on
    again = await store.change(UID, lambda s: s.with_idea(Idea.new("Sketch", 30, "indoor")))
    assert again.rev == 2 and [i.text for i in again.ideas] == ["Sketch"]
    raw = await docs.get(f"jarvis_nudges/{UID}")
    assert raw is not None and raw["uid"] == UID and docs.tx_sizes[-1] == 1


async def test_unreadable_settings_say_so_in_plain_words() -> None:
    docs = MemoryDocs()
    await docs.write([Set(f"jarvis_nudges/{UID}", {"uid": UID, "settings": {"nudges": 5}})])
    with pytest.raises(NudgesUnavailable, match="couldn't be read"):
        await NudgeStore(docs).settings(UID)


async def test_a_claim_is_made_once_and_a_released_claim_can_be_made_again() -> None:
    store = NudgeStore(MemoryDocs())
    assert await store.claim(UID, DAY, "nudge_hydrate@a")
    assert not await store.claim(UID, DAY, "nudge_hydrate@a")
    assert await store.claim(UID, DAY, "nudge_hydrate@b")
    await store.release(UID, DAY, "nudge_hydrate@a")
    assert await store.claim(UID, DAY, "nudge_hydrate@a")


async def test_claims_race_safely_two_runs_at_once_claim_one() -> None:
    store = NudgeStore(MemoryDocs())
    got = await asyncio.gather(*(store.claim(UID, DAY, "nudge_standup@x") for _ in range(5)))
    assert sorted(got) == [False, False, False, False, True]


async def test_the_claims_doc_keeps_only_the_last_few_days() -> None:
    docs = MemoryDocs()
    store = NudgeStore(docs)
    for d in range(1, 8):
        await store.claim(UID, f"2026-11-0{d}", "k")
    told = await store.told(UID)
    assert sorted(told) == ["2026-11-05", "2026-11-06", "2026-11-07"]


async def test_delete_all_removes_settings_and_claims() -> None:
    docs = MemoryDocs()
    store = NudgeStore(docs)
    await store.change(UID, lambda s: s.changed("nudge_focus", {"on": True}))
    await store.claim(UID, DAY, "k")
    assert await store.delete_all(UID) == 2
    assert await docs.get(f"jarvis_nudges/{UID}") is None
    assert await store.delete_all(UID) == 0


# ---- the sealed wellbeing log --------------------------------------------------------------------
async def test_the_water_log_is_sealed_and_never_in_clear() -> None:
    docs = MemoryDocs()
    well = WellbeingStore(docs, keyring())
    day = await well.change(UID, DAY, lambda d: d.plus_water(3))
    assert day.water == 3
    day = await well.change(UID, DAY, lambda d: d.plus_stood(1))
    assert (day.water, day.stood) == (3, 1)
    raw = await docs.get(f"jarvis_wellbeing/{UID}_{DAY}")
    assert raw is not None and set(raw) == {"uid", "day", "blob"}
    assert "water" not in json.dumps(raw) and '"3"' not in json.dumps(raw)
    assert (await well.day(UID, DAY)).water == 3


async def test_a_check_in_is_kept_by_a_fingerprint_with_his_word_inside_the_seal() -> None:
    well = WellbeingStore(MemoryDocs(), keyring())
    got = await well.change(
        UID, DAY, lambda d: d.with_checkin("ab12", Checkin(w="walk", o="asked", at="17:00"))
    )
    assert got.checkins["ab12"].o == "asked"
    done = got.checkins["ab12"].did("done")
    got = await well.change(UID, DAY, lambda d: d.with_checkin("ab12", done))
    assert got.checkins["ab12"].o == "done"


async def test_without_a_keyring_the_log_is_off_and_nothing_is_stored() -> None:
    docs = MemoryDocs()
    well = WellbeingStore(docs, None)
    assert well.on is False
    with pytest.raises(WellbeingOff, match="token key"):
        await well.change(UID, DAY, lambda d: d.plus_water(1))
    assert docs.sets == 0


async def test_a_day_sealed_for_another_owner_or_date_is_not_read() -> None:
    docs = MemoryDocs()
    well = WellbeingStore(docs, keyring())
    await well.change(UID, DAY, lambda d: d.plus_water(2))
    raw = await docs.get(f"jarvis_wellbeing/{UID}_{DAY}")
    assert raw is not None
    await docs.write([Set(f"jarvis_wellbeing/other_{DAY}", {**raw, "uid": "other"})])
    await docs.write([Set(f"jarvis_wellbeing/{UID}_2026-11-11", {**raw, "day": "2026-11-11"})])
    assert (await well.day("other", DAY)).water == 0  # unreadable: treated as empty
    assert (await well.day(UID, "2026-11-11")).water == 0


async def test_old_days_are_swept_after_thirty_days_and_delete_all_removes_every_day() -> None:
    docs = MemoryDocs()
    well = WellbeingStore(docs, keyring())
    for day in ("2026-10-01", "2026-10-11", "2026-11-10"):
        await well.change(UID, day, lambda d: d.plus_water(1))
    assert await well.sweep(UID, "2026-11-10") == 1
    assert [d for d, _ in await well.days(UID)] == ["2026-10-11", "2026-11-10"]
    assert await well.delete_all(UID) == 2 and await well.days(UID) == []


async def test_counts_stay_inside_their_limits() -> None:
    well = WellbeingStore(MemoryDocs(), keyring())
    for _ in range(4):
        day = await well.change(UID, DAY, lambda d: d.plus_water(9))
    with pytest.raises(ValueError):
        await well.change(UID, DAY, lambda d: d.plus_water(5))  # 36 + 5 > 40 a day
    assert day.water == 36
    for bad in (0, 11):
        with pytest.raises(ValueError):
            await well.change(UID, DAY, lambda d, n=bad: d.plus_water(n))  # type: ignore[misc]
