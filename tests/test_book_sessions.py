# tests/test_book_sessions.py -- R6 D9/D14: book sessions on the document store. A token is 32
# random bytes shown once (only its MAC is stored, keyring MAC domain `book_session`), 45 minutes
# absolute and 10 idle by default, one live session per owner, turns sealed under `book_session`
# with AAD book/session/{uid}/{bk}/v1 (the last 8 kept), close = mark closing (turns dropped at
# once) -> delete -> read back absent; a failed delete leaves `wiped` False for the sweep.
from __future__ import annotations

import pytest
from book_show_fakes import OTHER_UID, T0, UID, Clock, FlakyDocs, keyring

from jarvis.buildbook.model import OpenedSession
from jarvis.buildbook.ports import BookSessions, SessionGone
from jarvis.buildbook.sessions import DocBookSessions, SessionEnded
from jarvis.storage.docs import Query, Set

PREFIX = "jarvis_"
COLL = f"{PREFIX}book_sessions"


@pytest.fixture
def docs() -> FlakyDocs:
    return FlakyDocs()


@pytest.fixture
def store(docs: FlakyDocs) -> DocBookSessions:
    return DocBookSessions(docs, keyring(), prefix=PREFIX)


async def _open(store: DocBookSessions, audience: str = "guest", uid: str = UID) -> OpenedSession:
    opened, ended = await store.open(uid, audience, now=T0)  # type: ignore[arg-type]
    assert ended is None
    return opened


def test_it_is_the_port() -> None:
    assert isinstance(DocBookSessions(FlakyDocs(), keyring()), BookSessions)


async def test_open_shows_the_token_once_and_stores_only_its_mac(
    store: DocBookSessions, docs: FlakyDocs
) -> None:
    opened = await _open(store)
    s = opened.session
    assert len(opened.token) >= 43 and opened.token not in repr(opened)
    assert s.session_id.startswith("bk_") and s.audience == "guest" and s.state == "open"
    assert s.until == "2026-11-10T09:17:00+00:00"  # 45 minutes
    assert s.idle_until == "2026-11-10T08:42:00+00:00"  # 10 minutes
    assert (s.questions, s.questions_left) == (0, 20)
    raw = docs.dump()
    assert opened.token not in raw and keyring().mac("book_session", opened.token) in raw
    rows = await docs.query(Query(COLL))
    assert [r[0] for r in rows] == [s.session_id] and rows[0][1]["uid"] == UID


async def test_resolve_needs_the_token_and_the_same_owner(store: DocBookSessions) -> None:
    opened = await _open(store)
    view = await store.resolve(UID, opened.token, now=T0)
    assert view == opened.session
    for uid, token in [(OTHER_UID, opened.token), (UID, "x" * 43), (UID, ""), (UID, "a b")]:
        with pytest.raises(SessionGone):
            await store.resolve(uid, token, now=T0)


async def test_a_beat_moves_the_idle_limit_never_the_absolute_one(store: DocBookSessions) -> None:
    opened = await _open(store)
    clock = Clock()
    for _ in range(8):  # a beat every 5 minutes for 40 minutes
        view = await store.beat(UID, opened.token, now=clock.advance(minutes=5))
    assert view.idle_until == "2026-11-10T09:17:00+00:00" == view.until  # capped at the end
    with pytest.raises(SessionEnded) as gone:
        await store.resolve(UID, opened.token, now=clock.advance(minutes=6))
    assert gone.value.closed.reason == "expired" and gone.value.closed.wiped
    assert gone.value.closed.minutes == 46


async def test_an_idle_session_is_closed_on_the_spot(store: DocBookSessions) -> None:
    opened = await _open(store)
    with pytest.raises(SessionEnded) as gone:
        await store.resolve(UID, opened.token, now=T0.replace(minute=43))
    closed = gone.value.closed
    assert closed.reason == "idle" and closed.audience == "guest" and closed.minutes == 11
    with pytest.raises(SessionGone):
        await store.resolve(UID, opened.token, now=T0)  # gone for good
    assert await store.live(UID, now=T0) is None


async def test_a_new_open_ends_the_old_one(store: DocBookSessions) -> None:
    first = await _open(store, "owner")
    second, ended = await store.open(UID, "guest", now=T0.replace(minute=40))
    assert ended is not None and ended.session_id == first.session.session_id
    assert ended.reason == "new_open" and ended.wiped and ended.minutes == 8
    with pytest.raises(SessionGone):
        await store.resolve(UID, first.token, now=T0.replace(minute=40))
    live = await store.live(UID, now=T0.replace(minute=40))
    assert live is not None and live.session_id == second.session.session_id
    other = await _open(store, uid=OTHER_UID)  # another owner keeps his own
    assert (await store.live(UID, now=T0.replace(minute=40))) == live
    assert other.session.session_id != live.session_id


async def test_turns_are_sealed_kept_to_eight_and_counted(
    store: DocBookSessions, docs: FlakyDocs
) -> None:
    opened = await _open(store)
    sid = opened.session.session_id
    for n in range(10):
        left = await store.add_turn(UID, sid, f"needle question {n}", f"reply {n}")
    assert left == 10
    turns = await store.turns(UID, sid)
    assert turns == tuple((f"needle question {n}", f"reply {n}") for n in range(2, 10))
    assert "needle" not in docs.dump() and "reply 9" not in docs.dump()
    view = await store.resolve(UID, opened.token, now=T0)
    assert (view.questions, view.questions_left) == (10, 10)
    with pytest.raises(SessionGone):
        await store.add_turn(OTHER_UID, sid, "q", "r")
    assert await store.turns(OTHER_UID, sid) == ()


async def test_a_blob_moved_to_another_session_does_not_open(
    store: DocBookSessions, docs: FlakyDocs
) -> None:
    a = (await _open(store)).session.session_id
    await store.add_turn(UID, a, "q", "r")
    b = (await _open(store, uid=OTHER_UID)).session.session_id
    moved = (await docs.get(f"{COLL}/{a}")) or {}
    doc_b = (await docs.get(f"{COLL}/{b}")) or {}
    await docs.write([Set(f"{COLL}/{b}", {**doc_b, "blob": moved["blob"]})])
    assert await store.turns(OTHER_UID, b) == ()  # AAD names the owner and the session


async def test_close_deletes_and_reads_back(store: DocBookSessions, docs: FlakyDocs) -> None:
    opened = await _open(store)
    sid = opened.session.session_id
    await store.add_turn(UID, sid, "needle", "reply")
    closed = await store.close(UID, sid, reason="end", now=T0.replace(minute=55))
    assert closed.wiped and closed.reason == "end" and closed.questions == 1
    assert closed.minutes == 23 and closed.created_at == T0.isoformat()
    assert await docs.get(f"{COLL}/{sid}") is None
    with pytest.raises(SessionGone):
        await store.close(UID, sid, reason="end", now=T0)
    with pytest.raises(SessionGone):
        await store.close(OTHER_UID, (await _open(store)).session.session_id, reason="end", now=T0)


async def test_a_failed_delete_drops_the_turns_at_once_and_the_sweep_finishes(
    store: DocBookSessions, docs: FlakyDocs
) -> None:
    opened = await _open(store)
    sid = opened.session.session_id
    await store.add_turn(UID, sid, "needle", "reply")
    docs.fail_deletes = True
    closed = await store.close(UID, sid, reason="end", now=T0.replace(minute=40))
    assert not closed.wiped
    left = await docs.get(f"{COLL}/{sid}")
    assert left is not None and left["state"] == "closing" and left.get("blob") is None
    with pytest.raises(SessionGone):
        await store.resolve(UID, opened.token, now=T0)  # closing: no longer usable
    docs.fail_deletes = False
    swept = await store.sweep(now=T0.replace(minute=45))
    assert [(c.session_id, c.reason, c.wiped) for c in swept] == [(sid, "end", True)]
    assert await docs.get(f"{COLL}/{sid}") is None


async def test_the_sweep_closes_expired_and_idle_sessions_only(store: DocBookSessions) -> None:
    idle = await _open(store)
    live = await _open(store, uid=OTHER_UID)
    await store.beat(OTHER_UID, live.token, now=T0.replace(minute=40))
    swept = await store.sweep(now=T0.replace(minute=45))
    assert [(c.session_id, c.reason) for c in swept] == [(idle.session.session_id, "idle")]
    assert (await store.live(OTHER_UID, now=T0.replace(minute=45))) is not None
    assert await store.sweep(now=T0.replace(minute=46)) == ()


async def test_limits_come_from_the_settings(docs: FlakyDocs) -> None:
    store = DocBookSessions(
        docs, keyring(), prefix=PREFIX, session_minutes=15, idle_minutes=5, questions=3
    )
    opened = await _open(store)
    assert opened.session.until == "2026-11-10T08:47:00+00:00"
    assert opened.session.idle_until == "2026-11-10T08:37:00+00:00"
    assert opened.session.questions_left == 3
    with pytest.raises(ValueError):
        DocBookSessions(docs, keyring(), session_minutes=5)
