# tests/test_brief_store.py — slice 7: settings + briefs on the Docs port (claims, inbox, retention)
from __future__ import annotations

import asyncio
from datetime import UTC, date, datetime, timedelta

import pytest

from jarvis.brief.models import BriefData, BriefSettings, InboxState, SectionsStatus
from jarvis.brief.store import BriefStore, ClaimOutcome
from jarvis.storage.docs import MemoryDocs, Set

UID = "u_owner"
DAY = "2027-01-15"
NOW = datetime(2027, 1, 15, 1, 30, tzinfo=UTC)


@pytest.fixture
def docs() -> MemoryDocs:
    return MemoryDocs(strict_indexes=True)  # a composite index would fail loudly


@pytest.fixture
def store(docs: MemoryDocs) -> BriefStore:
    return BriefStore(docs)


async def _claim(
    store: BriefStore,
    *,
    now: datetime = NOW,
    force: bool = False,
    cap: int = 6,
    trigger: str = "scheduled",
    day: str = DAY,
    retry: bool = False,
) -> object:
    return await store.claim(
        UID,
        day,
        tz="Asia/Kolkata",
        trigger=trigger,  # type: ignore[arg-type]
        force=force,
        now=now,
        max_generations=cap,
        retry=retry,
    )


async def _ready(store: BriefStore, **kw: object) -> object:
    c = await _claim(store, **kw)  # type: ignore[arg-type]
    rec = c.record.model_copy(  # type: ignore[attr-defined]
        update={"status": "ready", "data": BriefData(date=DAY, tz="Asia/Kolkata"), "text": "t"}
    )
    assert await store.finish(rec)
    return rec


# ---- settings ---------------------------------------------------------------------------------


async def test_settings_default_update_and_rollback(store: BriefStore, docs: MemoryDocs) -> None:
    assert await store.get_settings(UID) == BriefSettings()
    s = await store.update_settings(UID, lambda c: c.model_copy(update={"time": "06:30"}))
    assert s.time == "06:30" and (await store.get_settings(UID)).time == "06:30"
    writes = docs.sets

    def refuse(_: BriefSettings) -> BriefSettings:
        raise ValueError("no")

    with pytest.raises(ValueError):
        await store.update_settings(UID, refuse)
    assert docs.sets == writes  # nothing written


async def test_corrupt_settings_read_as_defaults(store: BriefStore, docs: MemoryDocs) -> None:
    await docs.write([Set(f"jarvis_brief_settings/{UID}", {"time": "99:99", "enabled": "x"})])
    assert await store.get_settings(UID) == BriefSettings()


async def test_ids_are_validated(store: BriefStore) -> None:
    with pytest.raises(ValueError):
        await store.get_brief("../evil", DAY)
    with pytest.raises(ValueError):
        await store.get_brief(UID, "2027-1-5/x")


# ---- claims ------------------------------------------------------------------------------------


async def test_first_claim_creates_a_generating_record(store: BriefStore) -> None:
    c = await _claim(store)
    assert c.outcome is ClaimOutcome.CLAIMED  # type: ignore[attr-defined]
    rec = await store.get_brief(UID, DAY)
    assert rec is not None and rec.status == "generating" and rec.generations == 1


async def test_fresh_claim_is_busy_stale_claim_is_retaken(store: BriefStore) -> None:
    await _claim(store)
    busy = await _claim(store, now=NOW + timedelta(minutes=9))
    assert busy.outcome is ClaimOutcome.BUSY  # type: ignore[attr-defined]
    retake = await _claim(store, now=NOW + timedelta(minutes=11))
    assert retake.outcome is ClaimOutcome.CLAIMED  # type: ignore[attr-defined]
    assert retake.record.generations == 2  # type: ignore[attr-defined]


async def test_ready_is_kept_unless_forced_and_force_keeps_counters(store: BriefStore) -> None:
    await _ready(store)
    assert await store.begin_inbox(UID, DAY, NOW) is not None
    await store.mark_seen(UID, DAY, NOW)
    exists = await _claim(store, trigger="manual")
    assert exists.outcome is ClaimOutcome.EXISTS  # type: ignore[attr-defined]
    forced = await _claim(store, trigger="manual", force=True)
    assert forced.outcome is ClaimOutcome.CLAIMED  # type: ignore[attr-defined]
    rec = forced.record  # type: ignore[attr-defined]
    assert rec.inbox.status == "sending" and rec.seen_at == NOW and rec.generations == 2
    assert rec.data is not None  # the earlier brief stays visible while regenerating


async def test_failed_is_retaken_and_the_cap_holds(store: BriefStore) -> None:
    c = await _claim(store, cap=2)
    await store.finish(c.record.model_copy(update={"status": "failed"}))  # type: ignore[attr-defined]
    again = await _claim(store, cap=2)
    assert again.outcome is ClaimOutcome.CLAIMED  # type: ignore[attr-defined]
    await store.finish(again.record.model_copy(update={"status": "ready"}))  # type: ignore[attr-defined]
    capped = await _claim(store, cap=2, force=True)
    assert capped.outcome is ClaimOutcome.CAPPED  # type: ignore[attr-defined]


def _partial(state: str = "unavailable") -> BriefData:
    return BriefData(
        date=DAY,
        tz="Asia/Kolkata",
        sections_status=SectionsStatus(calendar=state),  # type: ignore[arg-type]
    )


async def _finish_ready(store: BriefStore, claim: object, data: BriefData) -> None:
    rec = claim.record.model_copy(update={"status": "ready", "data": data, "text": "t"})  # type: ignore[attr-defined]
    assert await store.finish(rec)


async def test_a_partial_brief_is_retaken_by_a_retry_at_most_twice(store: BriefStore) -> None:
    """Security review F3: a ready brief with an unavailable section may be retried twice by
    the scheduler; each retry is a counted generation and is recorded on the record."""
    await _finish_ready(store, await _claim(store), _partial())
    assert (await _claim(store)).outcome is ClaimOutcome.EXISTS  # type: ignore[attr-defined]
    for n in (1, 2):
        c = await _claim(store, retry=True)
        assert c.outcome is ClaimOutcome.CLAIMED  # type: ignore[attr-defined]
        assert (c.record.retries, c.record.generations) == (n, n + 1)  # type: ignore[attr-defined]
        await _finish_ready(store, c, _partial())
    assert (await _claim(store, retry=True)).outcome is ClaimOutcome.EXISTS  # type: ignore[attr-defined]
    forced = await _claim(store, trigger="manual", force=True)
    assert forced.record.retries == 2  # type: ignore[attr-defined]  # a refresh keeps the count


@pytest.mark.parametrize("state", ["ok", "not_connected"])
async def test_complete_or_unlinked_briefs_are_not_retried(store: BriefStore, state: str) -> None:
    await _finish_ready(store, await _claim(store), _partial(state))
    assert (await _claim(store, retry=True)).outcome is ClaimOutcome.EXISTS  # type: ignore[attr-defined]


async def test_retries_count_against_the_generation_cap(store: BriefStore) -> None:
    await _finish_ready(store, await _claim(store, cap=1), _partial())
    assert (await _claim(store, retry=True, cap=1)).outcome is ClaimOutcome.CAPPED  # type: ignore[attr-defined]


async def test_concurrent_claims_have_exactly_one_winner(store: BriefStore) -> None:
    results = await asyncio.gather(*(_claim(store) for _ in range(8)))
    won = [r for r in results if r.outcome is ClaimOutcome.CLAIMED]  # type: ignore[attr-defined]
    assert len(won) == 1


async def test_finish_needs_the_current_claim_and_keeps_seen(store: BriefStore) -> None:
    first = await _claim(store)
    second = await _claim(store, now=NOW + timedelta(minutes=11))  # retaken
    old = first.record.model_copy(update={"status": "ready"})  # type: ignore[attr-defined]
    assert await store.finish(old) is False
    await store.mark_seen(UID, DAY, NOW)
    new = second.record.model_copy(update={"status": "ready"})  # type: ignore[attr-defined]
    assert await store.finish(new) is True
    rec = await store.get_brief(UID, DAY)
    assert rec is not None and rec.status == "ready" and rec.seen_at == NOW


# ---- inbox at-most-once -----------------------------------------------------------------------


async def test_inbox_sending_mark_is_taken_once(store: BriefStore) -> None:
    assert await store.begin_inbox(UID, DAY, NOW) is None  # no brief yet
    await _ready(store)
    marks = await asyncio.gather(*(store.begin_inbox(UID, DAY, NOW) for _ in range(5)))
    assert sum(m is not None for m in marks) == 1
    done = InboxState(status="delivered", at=NOW, message_id="m1")
    assert await store.end_inbox(UID, DAY, done) is True
    assert await store.end_inbox(UID, DAY, done) is False  # only from "sending"
    rec = await store.get_brief(UID, DAY)
    assert rec is not None and rec.inbox == done


async def test_inbox_can_be_failed_without_an_attempt(store: BriefStore) -> None:
    await _ready(store)
    failed = InboxState(status="failed", at=NOW)
    assert await store.end_inbox(UID, DAY, failed, expect="off") is True
    assert await store.begin_inbox(UID, DAY, NOW) is None  # never retried


# ---- seen + retention -------------------------------------------------------------------------


async def test_mark_seen(store: BriefStore) -> None:
    assert await store.mark_seen(UID, DAY, NOW) is None
    await _ready(store)
    rec = await store.mark_seen(UID, DAY, NOW)
    assert rec is not None and rec.seen_at == NOW


async def test_prune_keeps_the_window_and_other_owners(store: BriefStore, docs: MemoryDocs) -> None:
    for d in range(1, 16):
        await _claim(store, day=date(2027, 1, d).isoformat())
    await docs.write(
        [Set("jarvis_briefs/u_other_2027-01-01", {"user_id": "u_other", "date": "2027-01-01"})]
    )
    removed = await store.prune(UID, keep_from=date(2027, 1, 9))
    assert removed == 8
    left = sorted(p for p in docs._data if p.startswith("jarvis_briefs/"))
    assert left[0] == "jarvis_briefs/u_other_2027-01-01"
    assert [p.rsplit("_", 1)[1] for p in left[1:]] == [f"2027-01-{d:02d}" for d in range(9, 16)]


async def test_a_quiet_tick_reads_two_documents(store: BriefStore, docs: MemoryDocs) -> None:
    await _ready(store)
    docs.reads = 0
    await store.get_settings(UID)
    await store.get_brief(UID, DAY)
    assert docs.reads == 2
