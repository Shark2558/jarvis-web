# tests/test_r11_1_d_github.py -- R11.1 Part D, O11 (docs/plans/r11-1-observations.md D19):
# "GitHub token: Unknown, hasn't been used yet". A connected token whose facts were never stored
# (connected before R5.1, or the record could not be saved) is now read by the Vitals refresh
# itself: ONE `GET /rate_limit` at most every 6 hours per owner, the headers' facts stored, the
# row saying "Checking..." while GitHub is slow, and a refused token shown as refused. The 6-hour
# rule is kept in the stored record, so a restart never makes a second read.
from __future__ import annotations

import asyncio
import json
import logging

import httpx
import pytest
from r11_1_fakes_d import GITHUB_DOC, GITHUB_TOKEN, UID, GithubRig
from r51b_fakes import Github, OwnRig

from jarvis.integrations import github as gh
from jarvis.integrations.github import FACTS_EVERY_S, FACTS_WAIT_S
from jarvis.storage.docs import Set
from jarvis.vitals.own import (
    CHECKING_NOTE,
    CHECKING_REASON,
    SOURCE_TIMEOUT_S,
    UNREAD_REASON,
    OwnSources,
)

HOUR = 3600.0


async def _unread_rig() -> GithubRig:
    rig = GithubRig()
    await rig.connected_without_facts()
    return rig


# ---- one read, then the limits -------------------------------------------------------------------
async def test_a_token_with_no_stored_facts_is_read_once_and_shows_its_limits() -> None:
    rig = await _unread_rig()
    rig.answers(used=40)

    v = await rig.row()

    assert rig.api.reads() == 1
    assert v.status == "ok" and v.checking is False
    assert (v.provider.used, v.provider.limit, v.provider.unit) == (40, 5000, "calls this hour")
    assert v.provider.note == "This token doesn't expire."
    assert "hasn't been used" not in json.dumps((await rig.board()).to_json())


async def test_the_read_is_one_plain_get_of_rate_limit_with_the_owners_token() -> None:
    rig = await _unread_rig()
    rig.answers()

    await rig.row()

    (sent,) = rig.api.requests
    assert (sent.method, sent.url.path, str(sent.url.query, "ascii")) == ("GET", "/rate_limit", "")
    assert sent.headers["authorization"] == f"Bearer {GITHUB_TOKEN}"


async def test_the_facts_are_stored_so_later_refreshes_read_nothing() -> None:
    rig = await _unread_rig()
    rig.answers(used=7, expires="2026-12-31 23:59:59 UTC")

    await rig.row()
    meta = (await rig.stored())["meta"]
    rig.restart()  # a new process: only the stored record is left
    rig.clock.advance(hours=30)
    v = await rig.row()

    assert (meta["rate_limit"], meta["rate_used"]) == (5000, 7) and meta["expires_at"] is not None
    assert rig.api.reads() == 1  # nothing was asked again, even after 30 hours
    assert v.provider.expires_at is not None and "hasn't been used" not in v.reason


async def test_a_token_whose_facts_are_known_is_never_asked() -> None:
    rig = GithubRig()
    await rig.connect()

    v = await rig.row()

    assert rig.api.reads() == 0 and rig.api.reads("/user") == 1
    assert v.status == "ok" and v.provider.limit == 5000


# ---- at most once every six hours, per owner, across restarts ------------------------------------
async def test_a_read_that_learns_nothing_is_not_repeated_for_six_hours() -> None:
    rig = await _unread_rig()
    rig.answers(503)  # GitHub is down

    first = await rig.row()
    for _ in range(5):
        rig.clock.advance(hours=1)
        again = await rig.row()

    assert rig.api.reads() == 1
    for v in (first, again):
        assert (v.status, v.reason, v.checking) == ("unknown", UNREAD_REASON, False)
        assert "6 hours" in v.provider.note and "hasn't been used" not in v.provider.note


async def test_a_restart_does_not_make_a_second_read_inside_the_six_hours() -> None:
    rig = await _unread_rig()
    rig.answers(503)
    await rig.row()

    for _ in range(4):
        rig.restart()
        rig.clock.advance(hours=1)
        await rig.row()

    assert rig.api.reads() == 1
    assert (await rig.stored())["facts_checked_at"] == rig.now - 4 * HOUR


async def test_after_six_hours_it_is_read_once_more_and_then_shows_its_limits() -> None:
    rig = await _unread_rig()
    rig.api.on(
        "/rate_limit",
        httpx.Response(503, json={}),
        httpx.Response(
            200,
            json={},
            headers={
                "x-ratelimit-limit": "5000",
                "x-ratelimit-used": "3",
                "x-ratelimit-reset": str(int(rig.now + 8 * HOUR)),
            },
        ),
    )
    await rig.row()

    rig.clock.advance(seconds=FACTS_EVERY_S - 1)
    assert (await rig.row()).status == "unknown" and rig.api.reads() == 1
    rig.clock.advance(seconds=2)
    v = await rig.row()

    assert rig.api.reads() == 2
    assert v.status == "ok" and (v.provider.used, v.provider.limit) == (3, 5000)


async def test_two_refreshes_at_once_share_the_one_read() -> None:
    rig = await _unread_rig()
    rig.answers()

    a, b = await asyncio.gather(rig.board(), rig.board())

    assert rig.api.reads() == 1
    for board in (a, b):
        row = next(v for v in board.items if v.provider.id == "github_token")
        assert row.status == "ok" and row.provider.limit == 5000


# ---- "Checking..." while GitHub is slow ----------------------------------------------------------
async def test_a_slow_github_shows_checking_and_the_limits_on_the_next_refresh(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(gh, "FACTS_WAIT_S", 0.05)
    rig = await _unread_rig()
    rig.answers(used=9)
    rig.api.hold()

    slow = await rig.row()
    still = await rig.row()  # a second refresh while the first read is still in flight

    assert (slow.status, slow.reason, slow.checking) == ("unknown", CHECKING_REASON, True)
    assert slow.provider.note == CHECKING_NOTE and CHECKING_NOTE.startswith("Checking")
    assert still.checking is True and rig.api.reads() == 1
    assert "hasn't been used" not in slow.reason + slow.provider.note

    rig.api.release()
    await rig.client.settled()
    v = await rig.row()

    assert rig.api.reads() == 1
    assert (v.status, v.checking, v.provider.used) == ("ok", False, 9)


async def test_a_board_that_is_still_checking_is_not_kept_in_the_cache(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(gh, "FACTS_WAIT_S", 0.05)
    rig = await _unread_rig()
    rig.answers(used=9)
    rig.api.hold()
    first = await rig.rig.svc.board_cached(UID)

    rig.api.release()
    await rig.client.settled()
    second = await rig.rig.svc.board_cached(UID)  # at once: well inside the cache's 15 seconds

    rows = [next(v for v in b.items if v.provider.id == "github_token") for b in (first, second)]
    assert [r.checking for r in rows] == [True, False] and rows[1].provider.used == 9


async def test_two_refreshes_of_a_slow_github_both_say_checking_and_share_the_read(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(gh, "FACTS_WAIT_S", 0.05)
    rig = await _unread_rig()
    rig.answers()
    rig.api.hold()

    a, b = await asyncio.gather(rig.row(), rig.row())
    rig.api.release()
    await rig.client.settled()

    assert a.checking is True and b.checking is True and rig.api.reads() == 1


async def test_facts_another_instance_stored_meanwhile_are_used_without_a_read() -> None:
    rig = await _unread_rig()
    rig.answers(used=77)
    await rig.row()  # instance A reads and stores
    other = GithubRig()
    other.docs, other.api = rig.docs, rig.api
    other.restart()  # instance B: the same documents, an empty memory

    state = await other.client.learn_token_facts(UID)

    assert state == "known" and rig.api.reads() == 1
    meta = await other.client.token_meta(UID)
    assert meta is not None and meta.rate_used == 77


async def test_an_owner_with_no_token_learns_nothing_and_reads_nothing() -> None:
    rig = GithubRig()

    assert await rig.client.learn_token_facts(UID) == "waiting"
    assert rig.api.requests == []


def test_the_wait_fits_inside_the_boards_own_deadline() -> None:
    assert 0 < FACTS_WAIT_S < SOURCE_TIMEOUT_S and FACTS_EVERY_S == 6 * HOUR


# ---- a refused token -----------------------------------------------------------------------------
async def test_a_refused_token_shows_as_refused() -> None:
    rig = await _unread_rig()
    rig.answers(401)

    v = await rig.row()
    rig.restart()
    after = await rig.row()

    assert rig.api.reads() == 1
    for row in (v, after):
        assert (row.status, row.reason) == ("red", "the token was refused")
    assert (await rig.stored())["meta"]["rejected_at"] == rig.now


# ---- nothing to read, nothing read ---------------------------------------------------------------
async def test_no_token_or_an_unreadable_record_makes_no_read() -> None:
    none = GithubRig()
    broken = await _unread_rig()
    doc = await broken.stored()
    await broken.docs.write([Set(GITHUB_DOC, {**doc, "blob": "x"})])

    assert await none.row() is None
    v = await broken.row()

    assert (v.status, v.reason) == ("red", "needs reconnecting")
    assert none.api.requests == [] and broken.api.requests == []


async def test_when_the_six_hour_mark_cannot_be_saved_nothing_is_read() -> None:
    rig = await _unread_rig()
    rig.answers()

    async def broken(fn: object) -> object:
        raise RuntimeError("firestore said: " + GITHUB_TOKEN)

    rig.docs.transaction = broken  # type: ignore[method-assign]
    v = await rig.row()

    assert rig.api.requests == []  # a read JARVIS could not count is not made
    assert (v.status, v.reason) == ("unknown", UNREAD_REASON)
    assert GITHUB_TOKEN not in json.dumps((await rig.board()).to_json())


async def test_a_token_replaced_while_the_read_is_in_flight_keeps_its_own_facts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(gh, "FACTS_WAIT_S", 0.05)
    rig = await _unread_rig()
    rig.answers(used=4999)  # the OLD token's numbers
    rig.api.hold()
    assert (await rig.row()).checking is True  # the read has started and hangs

    rig.api.stop_holding()
    await rig.client.disconnect(UID)
    await rig.connect()  # a NEW token: /user says 12 of 5000
    rig.api.release()  # now the old read's answer arrives
    await rig.client.settled()
    v = await rig.row()

    assert v.provider.used == 12 and (await rig.stored())["meta"]["rate_used"] == 12


async def test_the_token_never_reaches_a_log_line(caplog: pytest.LogCaptureFixture) -> None:
    rig = await _unread_rig()
    rig.answers(500)

    with caplog.at_level(logging.DEBUG):
        await rig.row()

    said = " ".join(r.getMessage() + json.dumps(r.__dict__, default=str) for r in caplog.records)
    assert GITHUB_TOKEN not in said


# ---- a reader that cannot ask GitHub keeps the old, honest words ---------------------------------
async def test_a_reader_without_the_check_keeps_the_r51_words() -> None:
    rig = OwnRig(OwnSources(github=Github(None)))

    v = next(x for x in (await rig.svc.board(UID)).items if x.provider.id == "github_token")

    assert v.status == "unknown" and "next time" in v.provider.note and v.checking is False
