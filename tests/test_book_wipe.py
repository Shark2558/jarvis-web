# tests/test_book_wipe.py -- R6 D14 (and D7's audit-first habit) through `BookService`: open
# audits first and ends the old session; a guest open sets the lock; every close marks closing,
# deletes and reads back, audits ONE content-free `book_close`, sends ONE content-free
# `book_session_closed` and keeps {last_closed_at, notified}; the sweep closes abandoned sessions
# ("ended by itself") and finishes failed deletes without a second notice; after a close a needle
# question is in no document, audit entry or notice. Also the show script and its spoken lines.
from __future__ import annotations

from typing import Any

import pytest
from book_show_fakes import (
    OWNER_EMAIL,
    T0,
    UID,
    Clock,
    FixtureSource,
    FlakyDocs,
    Prefs,
    RecordingNotifier,
    WorstCaseProvider,
    keyring,
)

from jarvis.billing.service import Billing
from jarvis.buildbook.lines import LINES
from jarvis.buildbook.lock import DocShowLock
from jarvis.buildbook.ports import BookOff, SessionGone
from jarvis.buildbook.service import BookService, BookSweepJob
from jarvis.buildbook.sessions import DocBookSessions
from jarvis.buildbook.talk import BookTalk
from jarvis.config import Settings
from jarvis.llm.brains import BrainRegistry, BrainSpec
from jarvis.llm.router import ModelTier
from jarvis.ticks import TickJob
from jarvis.tools.audit import AuditLog

NEEDLE = "NEEDLE7731"
TIERS = {ModelTier.FAST: "f", ModelTier.BALANCED: "b", ModelTier.STRONG: "s"}


class Mode:
    async def load(self, uid: str) -> str:
        return "ai"


class Rig:
    def __init__(self, settings: Settings) -> None:
        self.docs, self.audit, self.sent = FlakyDocs(), AuditLog(), RecordingNotifier()
        self.clock, self.prefs, self.model = Clock(), Prefs(), WorstCaseProvider()
        brains = BrainRegistry([BrainSpec("m", "M", self.model, TIERS)], default_id="m")
        self.sessions = DocBookSessions(self.docs, keyring())
        self.lock = DocShowLock(self.docs, cache_s=0)
        talk = BookTalk(
            brains,
            Billing.in_memory(brains, settings),
            Mode(),
            FixtureSource(),
            self.sessions,
            prefs=self.prefs,
            owner_emails=(OWNER_EMAIL,),
        )
        self.svc = BookService(
            source=FixtureSource(),
            sessions=self.sessions,
            lock=self.lock,
            talk=talk,
            audit=self.audit,
            notifier=self.sent,
            docs=self.docs,
            honorific="Sir",
            timezone="Asia/Kolkata",
            prefs=self.prefs,
            spend=self._spend,
        )

    async def _spend(self, uid: str) -> dict[str, Any]:
        return {"month_inr": 312.5, "limit_inr": 1000}

    async def tools(self) -> list[tuple[str, str, str]]:
        tail = await self.audit.tail(50)
        return [(e.tool, e.outcome, e.detail) for e in tail.entries]

    async def open(self, audience: str = "guest") -> Any:
        return await self.svc.open(UID, audience, how="passkey 1a2b3c4d", now=self.clock())  # type: ignore[arg-type]


@pytest.fixture
def rig(settings: Settings) -> Rig:
    return Rig(settings)


async def test_a_guest_session_from_open_to_wipe(rig: Rig) -> None:
    opened = await rig.open()
    lock = await rig.lock.get(UID)
    assert lock is not None and lock.bk == opened.session.session_id
    view = await rig.svc.resolve(UID, opened.token, now=rig.clock())
    got = await rig.svc.ask(UID, view, f"How does the {NEEDLE} voice pipeline work?", now=T0)
    assert NEEDLE in got.reply  # the worst-case brain echoed it, guarded and stored sealed
    rig.clock.advance(minutes=23)
    closed = await rig.svc.close(UID, view.session_id, reason="closing", now=rig.clock())
    assert closed.wiped and closed.notified and closed.questions == 1
    [(uid, signal, message)] = rig.sent.sent
    assert uid == UID and signal.kind == "book_session_closed" and signal.source == "system"
    assert message == (
        "Sir, the build book session from 14:02 has closed (23 min, 1 question). "
        "Its conversation was deleted; nothing was learned from it."
    )
    tools = await rig.tools()
    assert [t for t, _, _ in tools] == ["book_open", "book_close"]
    assert tools[0][2] == "Build book opened with your passkey at 14:02, for a guest"
    assert tools[1][2] == "Build book closed at 14:25, 23 min, 1 question, conversation deleted"
    entries = " ".join(e.model_dump_json() for e in (await rig.audit.tail(50)).entries)
    for place in (rig.docs.dump(), entries, message):
        assert NEEDLE not in place
    assert await rig.lock.get(UID) is not None  # a finished guest session leaves the lock on
    last = await rig.svc.last_closed(UID)
    assert last == {"last_closed_at": closed.closed_at, "notified": True}
    with pytest.raises(SessionGone):
        await rig.svc.resolve(UID, opened.token, now=rig.clock())


async def test_an_abandoned_session_is_swept_and_ended_by_itself(rig: Rig) -> None:
    opened = await rig.open("owner")
    assert await rig.lock.get(UID) is None  # the owner's own session locks nothing
    job = BookSweepJob(rig.svc, clock=rig.clock)
    assert isinstance(job, TickJob) and job.name == "book_sweep"
    rig.clock.advance(minutes=11)
    assert await job.run([UID]) == {"closed": 1, "failed": 0}
    [(_, _, message)] = rig.sent.sent
    assert message.startswith("Sir, the build book session from 14:02 ended by itself (11 min,")
    with pytest.raises(SessionGone):
        await rig.svc.resolve(UID, opened.token, now=rig.clock())
    assert await job.run([UID]) == {"closed": 0, "failed": 0}


async def test_an_expired_token_is_closed_and_told_on_the_spot(rig: Rig) -> None:
    opened = await rig.open()
    rig.clock.advance(minutes=12)
    with pytest.raises(SessionGone):
        await rig.svc.resolve(UID, opened.token, now=rig.clock())
    assert len(rig.sent.sent) == 1 and "ended by itself" in rig.sent.sent[0][2]


async def test_a_failed_delete_is_told_and_finished_by_the_sweep_once(rig: Rig) -> None:
    opened = await rig.open()
    rig.docs.fail_deletes = True
    closed = await rig.svc.close(UID, opened.session.session_id, reason="end", now=T0)
    assert not closed.wiped
    assert rig.sent.sent[0][2].endswith(
        "Its conversation couldn't be deleted yet; I'll keep trying. Nothing was learned from it."
    )
    job = BookSweepJob(rig.svc, clock=rig.clock)
    assert (await job.run([UID]))["failed"] == 1
    rig.docs.fail_deletes = False
    assert await job.run([UID]) == {"closed": 1, "failed": 0}
    assert len(rig.sent.sent) == 1  # no second notice for the retry, one audit line for it
    assert [t for t, _, _ in await rig.tools()] == ["book_open", "book_close", "book_close"]


async def test_a_new_open_ends_the_old_session_with_its_notice(rig: Rig) -> None:
    first = await rig.open("owner")
    rig.clock.advance(minutes=5)
    await rig.open("guest")
    assert len(rig.sent.sent) == 1 and "has closed (5 min, 0 questions)" in rig.sent.sent[0][2]
    with pytest.raises(SessionGone):
        await rig.svc.resolve(UID, first.token, now=rig.clock())


async def test_resume_lifts_only_the_current_lock_and_ends_the_session(rig: Rig) -> None:
    opened = await rig.open()
    lock = await rig.lock.get(UID)
    assert lock is not None
    assert await rig.svc.resume(UID, "bl_000000000000", now=T0) is False
    assert await rig.svc.resume(UID, lock.id, now=T0) is True
    assert await rig.lock.get(UID) is None
    with pytest.raises(SessionGone):
        await rig.svc.resolve(UID, opened.token, now=T0)
    assert "has closed" in rig.sent.sent[0][2]


async def test_privacy_delete_ends_the_live_session(rig: Rig) -> None:
    await rig.open("owner")
    assert await rig.svc.wipe(UID, now=T0) == 1
    assert await rig.svc.wipe(UID, now=T0) == 0


async def test_nothing_opens_when_the_open_cannot_be_audited(rig: Rig) -> None:
    async def broken(**kw: Any) -> Any:
        raise RuntimeError("audit down")

    rig.audit.append = broken  # type: ignore[method-assign]
    with pytest.raises(BookOff):
        await rig.open()
    assert await rig.sessions.live(UID, now=T0) is None and await rig.lock.get(UID) is None


async def test_no_guest_session_without_its_lock(rig: Rig) -> None:
    rig.docs.fail_reads = False

    async def broken(uid: str, session_id: str, *, now: Any) -> Any:
        raise RuntimeError("lock store down")

    rig.lock.set = broken  # type: ignore[method-assign]
    with pytest.raises(BookOff):
        await rig.open()
    assert await rig.sessions.live(UID, now=T0) is None


async def test_a_notice_that_fails_still_closes(rig: Rig) -> None:
    opened = await rig.open()
    rig.sent.fail = True
    closed = await rig.svc.close(UID, opened.session.session_id, reason="end", now=T0)
    assert closed.wiped and not closed.notified
    assert await rig.svc.last_closed(UID) == {"last_closed_at": closed.closed_at, "notified": False}


async def test_the_script_is_the_book_plus_the_fixed_lines(rig: Rig) -> None:
    """The shape D's show reads (INTEGRATION-D "Contract", I1): scenes 1-11 from book.show, the
    fixed lines by name (scene 12's ask, or ai_off), the closing (scene 13) as a list."""
    guest = (await rig.open("guest")).session
    s = await rig.svc.script(UID, guest)
    assert [x["n"] for x in s["scenes"]] == list(range(1, 12))
    assert s["lines"]["ask"] == {"id": "ask", "text": LINES["ask"]}
    assert s["lines"]["ai_off"] == {"id": "ai_off", "text": LINES["ai_off"]}
    assert s["lines"]["anything_else"]["text"] == LINES["anything_else"]
    assert s["lines"]["hand_back"] == {"id": "hand_back", "text": LINES["hand_back"]}
    assert [x["id"] for x in s["closing"]] == ["credit", "sealed_guest", "thanks_guest"]
    assert s["closing"][0]["text"] == (
        "Everything you've seen was designed and built by my owner and creator. "
        "The credit is all his."
    )
    assert "month_inr" not in s["costs"] and s["audience"] == "guest"
    assert s["release"]["id"] == "4a70683" and s["talk"]["on"] is True and s["voice"] == "cloud"
    assert s["until"] == guest.until and s["session"]["questions_left"] == guest.questions_left
    rig.prefs.values.update(creator_name="Akash", show_voice="browser")
    owner = (await rig.open("owner")).session
    o = await rig.svc.script(UID, owner)
    assert o["costs"]["month_inr"] == 312.5 and "hand_back" not in o["lines"]
    assert (
        o["closing"][1]["text"]
        == "The code is sealed in your vault, for the people you allow, Sir."
    )
    assert "Akash, my owner and creator" in o["closing"][0]["text"]
    assert o["voice"] == "browser"


async def test_spoken_lines_are_beats_or_fixed_lines_only(rig: Rig) -> None:
    view = (await rig.open("guest")).session
    assert await rig.svc.line_text(UID, view, "s02b02") == "The core loop sits in layer four."
    assert await rig.svc.line_text(UID, view, "thanks_owner") == "Thank you, Sir."
    for bad in ("s99b01", "nope", "", "s02b02 ", "{h}"):
        assert await rig.svc.line_text(UID, view, bad) is None


async def test_without_a_talk_lane_a_question_gets_the_off_line(rig: Rig) -> None:
    rig.svc.talk = None
    view = (await rig.open("guest")).session
    got = await rig.svc.ask(UID, view, "How does voice work?", now=T0)
    assert got.reply == LINES["ai_off"] and got.refused
    assert (await rig.svc.talk_state(UID)).on is False


async def test_a_session_has_a_speech_budget(rig: Rig) -> None:
    view = (await rig.open("guest")).session
    sid = view.session_id
    assert rig.svc.allow_speech(sid, 20_000) and rig.svc.allow_speech(sid, 4_000)
    assert not rig.svc.allow_speech(sid, 1)  # ~4x the show's narration, then the browser voice
    assert all(rig.svc.allow_hearing(sid) for _ in range(30)) and not rig.svc.allow_hearing(sid)
    await rig.svc.close(UID, sid, reason="end", now=T0)
    assert rig.svc.allow_speech(sid, 1)  # forgotten with the session
