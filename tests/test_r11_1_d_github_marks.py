# tests/test_r11_1_d_github_marks.py -- R11.1 Part D, O11 after the reviews: the six-hour mark of
# the GitHub facts read. A mark in the future (the clock was set back) counts as recent, but only
# up to six hours ahead (security LOW-3). The wait for the read leaves the Vitals source a real
# margin before its own deadline, a read that is cancelled gives the period back (code review M1),
# and a caller cancelled while the mark is being claimed never leaves a mark without a read (code
# review L2). Nothing here is a real token.
from __future__ import annotations

import asyncio
from typing import Any

import pytest
from r11_1_fakes_d import GITHUB_DOC, UID, GithubRig

from jarvis.integrations import github as gh
from jarvis.integrations.github import FACTS_AHEAD_S, FACTS_EVERY_S, FACTS_MARK, FACTS_WAIT_S
from jarvis.storage.docs import Set
from jarvis.vitals.own import SOURCE_TIMEOUT_S

HOUR = 3600.0


async def _unread_rig() -> GithubRig:
    rig = GithubRig()
    await rig.connected_without_facts()
    return rig


async def _mark(rig: GithubRig, at: float) -> None:
    doc = await rig.stored()
    await rig.docs.write([Set(GITHUB_DOC, {**doc, FACTS_MARK: at})])


# ---- security LOW-3: a mark in the future -----------------------------------------------------
@pytest.mark.parametrize("ahead_h", [0.5, 2.0, 6.0])
async def test_a_mark_ahead_of_the_clock_counts_as_recent(ahead_h: float) -> None:
    rig = await _unread_rig()
    rig.answers()
    await _mark(rig, rig.now + ahead_h * HOUR)  # the clock was set back after the read

    assert await rig.client.learn_token_facts(UID) == "waiting"
    assert rig.api.reads() == 0


async def test_a_mark_more_than_six_hours_ahead_is_not_believed() -> None:
    rig = await _unread_rig()
    rig.answers(used=5)
    await _mark(rig, rig.now + FACTS_AHEAD_S + HOUR)

    assert await rig.client.learn_token_facts(UID) == "known"
    assert rig.api.reads() == 1 and (await rig.stored())[FACTS_MARK] == rig.now


async def test_this_processs_own_mark_survives_a_clock_set_back() -> None:
    rig = await _unread_rig()
    rig.answers(503)  # the read learns nothing
    await rig.client.learn_token_facts(UID)
    await rig.client.settled()

    rig.clock.advance(hours=-1)
    rig.answers(used=5)

    assert await rig.client.learn_token_facts(UID) == "waiting" and rig.api.reads() == 1


def test_the_future_is_capped_at_the_period() -> None:
    assert FACTS_AHEAD_S == FACTS_EVERY_S == 6 * HOUR


# ---- code review M1: the wait leaves a margin, and a cancelled read gives the period back ------
def test_the_wait_leaves_the_source_a_real_margin() -> None:
    assert 0 < FACTS_WAIT_S and SOURCE_TIMEOUT_S - FACTS_WAIT_S >= 1.5


async def test_a_read_cancelled_by_shutdown_gives_its_six_hours_back(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(gh, "FACTS_WAIT_S", 0.05)
    rig = await _unread_rig()
    rig.answers(used=7)
    rig.api.hold()
    assert await rig.client.learn_token_facts(UID) == "checking"
    assert FACTS_MARK in await rig.stored()

    await rig.client.aclose()  # the app shuts down while GitHub is still answering

    assert FACTS_MARK not in await rig.stored()
    rig.api.release()
    rig.restart()
    assert await rig.client.learn_token_facts(UID) == "known"
    assert rig.api.reads() == 2  # read again at once, not six hours later


async def test_a_release_never_drops_a_newer_mark() -> None:
    rig = await _unread_rig()
    await _mark(rig, rig.now + 10)
    store = rig.client._store  # noqa: SLF001 - the store's own transaction

    assert await store.release_facts_read(UID, rig.now) is False
    assert (await rig.stored())[FACTS_MARK] == rig.now + 10


# ---- code review L2: a caller cancelled while the mark is claimed ------------------------------
async def test_a_caller_cancelled_mid_claim_never_leaves_a_mark_without_a_read() -> None:
    rig = await _unread_rig()
    rig.answers(used=3)
    store = rig.client._store  # noqa: SLF001
    claim = store.claim_facts_read
    entered = asyncio.Event()

    async def slow_claim(*args: Any, **kw: Any) -> Any:
        entered.set()
        await asyncio.sleep(0.05)
        return await claim(*args, **kw)

    store.claim_facts_read = slow_claim  # type: ignore[method-assign]
    caller = asyncio.create_task(rig.client.learn_token_facts(UID))
    await entered.wait()
    caller.cancel()  # the Vitals source's deadline fires inside the claim
    with pytest.raises(asyncio.CancelledError):
        await caller
    await asyncio.sleep(0.1)
    await rig.client.settled()

    assert FACTS_MARK in await rig.stored() and rig.api.reads() == 1
    assert (await rig.row()).provider.used == 3
