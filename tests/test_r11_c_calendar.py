# tests/test_r11_c_calendar.py -- R11 Part C's calendar reads (items 8's meeting variant, 11, 12):
# only the primary calendar, timed events only, an event is "his own plan" only when only he wrote
# it; every background read asks his calendar row first (Never or an unreadable rule: no read) and
# leaves one audit line with no words; each read is capped at 8 s; results are cached per owner.
from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from r11_fakes import NO_ROWS, NOON_IST, UID, Clock, reads_over

from jarvis.core.guardrails import ActionRisk
from jarvis.helpers.nudges import calendar as cal
from jarvis.helpers.nudges.calendar import CALENDAR_TOOL, Agenda, GoogleCalendar, to_event
from jarvis.tools.audit import AuditLog
from jarvis.tools.policy import Effect, PolicyRule

START = datetime(2026, 11, 10, tzinfo=UTC)
ME = {"self": True, "email": "owner@example.com"}
OTHER = {"email": "colleague@example.com"}


def item(ident: str, title: str, *, organizer: dict[str, Any] = ME, **over: Any) -> dict[str, Any]:
    base = {
        "id": ident,
        "summary": title,
        "start": {"dateTime": "2026-11-10T17:00:00+05:30"},
        "end": {"dateTime": "2026-11-10T17:45:00+05:30"},
        "organizer": organizer,
        "creator": organizer,
    }
    return {**base, **over}


def test_an_event_is_his_own_plan_only_when_only_he_wrote_it() -> None:
    mine, theirs = (
        to_event(item("abc123", "Evening walk")),
        to_event(item("def456", "Walk", organizer=OTHER)),
    )
    assert mine is not None and mine.own and mine.title == "Evening walk"
    assert theirs is not None and not theirs.own
    assert mine.key != "abc123" and len(mine.key) == 16  # a fingerprint, never the id


@pytest.mark.parametrize(
    "bad",
    [
        {"start": {"date": "2026-11-10"}, "end": {"date": "2026-11-11"}},  # all day
        {"status": "cancelled"},
        {"id": None},
        {"end": {"dateTime": "2026-11-10T16:00:00+05:30"}},  # ends before it starts
        {"start": {"dateTime": "not a time"}},
    ],
)
def test_events_that_block_no_time_or_are_malformed_are_skipped(bad: dict[str, Any]) -> None:
    assert to_event(item("abc123", "Walk", **bad)) is None
    assert to_event("not an event") is None


class Google:
    def __init__(self, items: Any = None, *, slow: bool = False) -> None:
        self.items, self.slow, self.calls = items, slow, []

    async def request(self, uid: str, method: str, url: str, **kw: Any) -> Any:
        self.calls.append((uid, method, url, kw.get("params")))
        if self.slow:
            await asyncio.sleep(1)
        return {"items": self.items} if self.items is not None else []


async def test_google_reads_only_the_primary_calendars_single_events() -> None:
    google = Google([item("abc123", "Evening walk"), {"junk": True}])
    got = await GoogleCalendar(google).events(UID, START, START + timedelta(days=1))
    assert [e.title for e in got] == ["Evening walk"]
    (uid, method, url, params) = google.calls[0]
    assert (uid, method) == (UID, "GET") and url.endswith("/calendars/primary/events")
    assert params["singleEvents"] == "true" and params["maxResults"] == 50
    assert await GoogleCalendar(Google(None)).events(UID, START, START) == []


async def test_a_slow_calendar_is_cut_off(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cal, "OUTSIDE_TIMEOUT_S", 0.01)
    with pytest.raises(TimeoutError):
        await GoogleCalendar(Google([], slow=True)).events(UID, START, START)


class Rules:
    def __init__(self, rules: list[PolicyRule] | None = None, *, fail: bool = False) -> None:
        self.rules, self.fail = rules or [], fail

    async def rules_for(self, uid: str) -> list[PolicyRule]:
        if self.fail:
            raise RuntimeError("permissions down")
        return self.rules


async def test_his_calendar_row_decides_every_background_read() -> None:
    """I1: the governed path (the gateway's policy and his rows; Allow only, fail closed)."""
    never = PolicyRule(tool_pattern="calendar_*", effect=Effect.DENY, risks=[ActionRisk.READ_ONLY])
    ask = PolicyRule(tool_pattern="calendar_*", effect=Effect.ASK, risks=[ActionRisk.READ_ONLY])
    for rules, ok in (
        (None, False),  # no permission service: fail closed (integrated review M2)
        (NO_ROWS, True),
        (Rules(), True),
        (Rules([never]), False),
        (Rules([ask]), False),  # a background read can't ask
        (Rules(fail=True), False),  # fail closed
    ):
        reads = reads_over(lambda r=rules: r, AuditLog())  # type: ignore[misc]
        assert (await reads.allowed(UID, CALENDAR_TOOL, job="nudges")).ok is ok, rules


class Source:
    def __init__(self, *, fail: bool = False) -> None:
        self.fail, self.calls = fail, 0

    async def events(self, uid: str, start: datetime, end: datetime) -> list[Any]:
        self.calls += 1
        if self.fail:
            raise RuntimeError("down")
        return []


async def _agenda(source: Source | None, allowed: bool) -> tuple[Agenda, AuditLog, Clock]:
    never = PolicyRule(tool_pattern="calendar_*", effect=Effect.DENY)
    rules = NO_ROWS if allowed else Rules([never])
    audit, clock = AuditLog(), Clock(NOON_IST)
    reads = reads_over(lambda: rules, audit, now=clock)  # type: ignore[arg-type,return-value]
    return Agenda(source, reads=reads, now=clock), audit, clock


async def test_the_agenda_reads_when_asked_caches_and_audits_without_words() -> None:
    src = Source()
    agenda, audit, clock = await _agenda(src, True)
    assert await agenda.today(UID, START, START + timedelta(days=1)) == []
    clock.at += timedelta(minutes=29)
    await agenda.today(UID, START, START + timedelta(days=1))
    assert src.calls == 1
    clock.at += timedelta(minutes=2)
    await agenda.today(UID, START, START + timedelta(days=1))
    assert src.calls == 2
    entries = (await audit.tail(10)).entries
    assert [(e.agent, e.tool, e.outcome, e.detail) for e in entries] == [
        ("helpers", "calendar_list_events", "executed", "nudges")
    ] * 2


async def test_a_denied_or_failed_read_gives_no_events_and_says_so_in_the_audit() -> None:
    denied, audit, _ = await _agenda(Source(), False)
    assert await denied.today(UID, START, START) is None
    failed, audit2, _ = await _agenda(Source(fail=True), True)
    assert await failed.today(UID, START, START) is None
    assert [e.outcome for e in (await audit.tail(5)).entries] == ["denied"]
    assert [(e.outcome, e.detail) for e in (await audit2.tail(5)).entries] == [
        ("error", "nudges; failed")
    ]
    unlinked, _, _ = await _agenda(None, True)
    assert unlinked.linked is False and await unlinked.today(UID, START, START) is None
