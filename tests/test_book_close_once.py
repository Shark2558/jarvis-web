# tests/test_book_close_once.py -- R6 D14 under failure: every close tells the owner EXACTLY once.
# Privacy -> Delete and Resume end EVERY session of the owner (expired and idle ones too); the sweep
# closes and tells one session at a time (a failure on one loses no other's notice); a closer that
# dies after marking is recovered by the sweep once its claim expires; two closers tell once; a
# delete that finally succeeds after failing adds one audit line and no second notice; the talk
# lane reserves a question atomically before its model call.
from __future__ import annotations

import asyncio
from typing import Any

import pytest
from book_rig_fakes import ServiceRig
from book_show_fakes import OTHER_UID, UID

from jarvis.buildbook.closing import NOTICE_LEASE
from jarvis.buildbook.lines import LINES
from jarvis.buildbook.ports import SessionGone
from jarvis.config import Settings
from jarvis.storage.docs import Query

COLL = "jarvis_book_sessions"


@pytest.fixture
def rig(settings: Settings) -> ServiceRig:
    return ServiceRig(settings)


async def _turn(rig: ServiceRig, opened: Any) -> None:
    view = await rig.svc.resolve(UID, opened.token, now=rig.clock())
    await rig.svc.ask(UID, view, "How does voice work?", now=rig.clock())


async def test_privacy_delete_wipes_an_idle_session_too(rig: ServiceRig) -> None:
    opened = await rig.open(UID, "owner")
    await _turn(rig, opened)
    rig.clock.advance(minutes=11)  # idle, not swept yet
    assert await rig.svc.wipe(UID, now=rig.clock()) == 1
    assert await rig.docs.get(f"{COLL}/{opened.session.session_id}") is None
    assert len(rig.notices()) == 1 and "ended by itself" in rig.notices()[0]
    assert await rig.svc.wipe(UID, now=rig.clock()) == 0


async def test_resume_ends_an_idle_guest_session_too(rig: ServiceRig) -> None:
    opened = await rig.open(UID)
    lock = await rig.lock.get(UID)
    rig.clock.advance(minutes=11)
    assert await rig.svc.resume(UID, lock.id, now=rig.clock()) is True
    assert await rig.docs.get(f"{COLL}/{opened.session.session_id}") is None
    assert len(rig.notices()) == 1


async def test_the_sweep_tells_each_session_as_it_goes(rig: ServiceRig) -> None:
    first, second = await rig.open(UID, "owner"), await rig.open(OTHER_UID, "owner")
    real = rig.sessions.close_claim
    broken = {second.session.session_id}

    async def flaky(uid: str, bk: str, *a: Any, **k: Any) -> Any:
        if bk in broken:
            broken.discard(bk)
            raise RuntimeError("store hiccup")
        return await real(uid, bk, *a, **k)

    rig.sessions.close_claim = flaky  # type: ignore[method-assign]
    rig.clock.advance(minutes=11)
    report = await rig.svc.sweep(now=rig.clock())
    assert report.errors == 1 and [c.session_id for c in report.closed] == [
        first.session.session_id
    ]
    assert len(rig.notices()) == 1  # the first was told at once, not lost with the loop
    again = await rig.svc.sweep(now=rig.clock())
    assert again.errors == 0 and len(again.closed) == 1 and len(rig.notices()) == 2
    assert (await rig.svc.sweep(now=rig.clock())).closed == () and len(rig.notices()) == 2


async def test_a_closer_that_died_after_the_delete_is_told_by_the_sweep_once(
    rig: ServiceRig,
) -> None:
    opened = await rig.open(UID, "owner")
    rig.clock.advance(minutes=5)
    sid = opened.session.session_id
    await rig.sessions.close_claim(UID, sid, "end", rig.clock())  # then the process died
    assert await rig.docs.get(f"{COLL}/{sid}") is None and rig.notices() == []
    assert (await rig.svc.sweep(now=rig.clock())).closed == ()  # its claim is still fresh
    rig.clock.advance(seconds=NOTICE_LEASE.total_seconds())
    report = await rig.svc.sweep(now=rig.clock())
    assert [c.session_id for c in report.closed] == [sid]
    assert rig.notices() == [
        "Sir, the build book session from 14:02 has closed (5 min, 0 questions). "
        "Its conversation was deleted; nothing was learned from it."
    ]
    rig.clock.advance(minutes=10)
    assert (await rig.svc.sweep(now=rig.clock())).closed == () and len(rig.notices()) == 1
    tools = [t for t, _ in await rig.tools()]
    assert tools == ["book_open", "book_close"]


async def test_a_closer_that_died_before_the_delete_is_finished_by_the_sweep_once(
    rig: ServiceRig,
) -> None:
    opened = await rig.open(UID, "owner")
    sid = opened.session.session_id
    await rig.sessions._mark(UID, sid, "end", rig.clock(), due_only=False, by_due=False)  # died
    left = await rig.docs.get(f"{COLL}/{sid}")
    assert left is not None and left["state"] == "closing" and left["blob"] is None
    await rig.svc.sweep(now=rig.clock())  # finishes the delete; the claim isn't its to tell yet
    assert await rig.docs.get(f"{COLL}/{sid}") is None and rig.notices() == []
    rig.clock.advance(minutes=3)
    report = await rig.svc.sweep(now=rig.clock())
    assert [(c.reason, c.wiped) for c in report.closed] == [("end", True)]
    rig.clock.advance(minutes=3)
    await rig.svc.sweep(now=rig.clock())
    assert len(rig.notices()) == 1 and await rig.docs.get(f"{COLL}/{sid}") is None


async def test_two_closers_tell_once(rig: ServiceRig) -> None:
    opened = await rig.open(UID)
    sid = opened.session.session_id
    got = await asyncio.gather(
        rig.svc.close(UID, sid, reason="end", now=rig.clock()),
        rig.svc.close(UID, sid, reason="closing", now=rig.clock()),
        return_exceptions=True,
    )
    assert all(not isinstance(g, Exception) or isinstance(g, SessionGone) for g in got)
    assert len(rig.notices()) == 1
    assert [t for t, _ in await rig.tools()] == ["book_open", "book_close"]


async def test_a_delete_that_finally_succeeds_adds_one_audit_line_and_no_notice(
    rig: ServiceRig,
) -> None:
    opened = await rig.open(UID)
    rig.docs.fail_deletes = True
    closed = await rig.svc.close(UID, opened.session.session_id, reason="end", now=rig.clock())
    assert not closed.wiped and closed.notified
    rig.docs.fail_deletes = False
    rig.clock.advance(minutes=6)
    await rig.svc.sweep(now=rig.clock())
    await rig.svc.sweep(now=rig.clock())
    assert len(rig.notices()) == 1
    tools = await rig.tools()
    assert [t for t, _ in tools] == ["book_open", "book_close", "book_close"]
    assert tools[-1][1] == (
        "Build book conversation from 14:02 deleted at 14:08 (its first delete had failed)"
    )
    assert await rig.docs.query(Query("jarvis_book_notices")) == []


async def test_parallel_asks_never_pass_the_session_limit(settings: Settings) -> None:
    rig = ServiceRig(settings, questions=1)
    opened = await rig.open(UID)
    view = await rig.svc.resolve(UID, opened.token, now=rig.clock())
    got = await asyncio.gather(
        *(rig.svc.ask(UID, view, "How does voice work?", now=rig.clock()) for _ in range(6))
    )
    assert len(rig.model.calls) == 1  # one model call, however many raced
    assert sum(1 for g in got if g.reply == LINES["limit"]) == 5
    doc = await rig.docs.get(f"{COLL}/{opened.session.session_id}")
    assert doc is not None and doc["questions"] == 1


async def test_a_question_no_model_answered_is_given_back(rig: ServiceRig) -> None:
    opened = await rig.open(UID)
    view = await rig.svc.resolve(UID, opened.token, now=rig.clock())
    rig.mode.value = "none"
    got = await rig.svc.ask(UID, view, "How does voice work?", now=rig.clock())
    assert got.reply == LINES["ai_off"] and got.left == 20
    rig.mode.value = "ai"

    async def down(**kw: Any) -> Any:
        raise RuntimeError("provider down")

    rig.model.complete = down  # type: ignore[method-assign]
    got = await rig.svc.ask(UID, view, "How does voice work?", now=rig.clock())
    assert got.reply == LINES["ai_off"] and got.left == 20
    doc = await rig.docs.get(f"{COLL}/{opened.session.session_id}")
    assert doc is not None and doc["questions"] == 0


async def test_a_question_whose_session_closed_meanwhile_is_session_gone(
    rig: ServiceRig,
) -> None:
    opened = await rig.open(UID)
    view = await rig.svc.resolve(UID, opened.token, now=rig.clock())
    real = rig.model.complete

    async def slow(**kw: Any) -> Any:  # the closing ends while the brain thinks
        await rig.svc.close(UID, view.session_id, reason="end", now=rig.clock())
        return await real(**kw)

    rig.model.complete = slow  # type: ignore[method-assign]
    with pytest.raises(SessionGone):
        await rig.svc.ask(UID, view, "How does voice work?", now=rig.clock())
