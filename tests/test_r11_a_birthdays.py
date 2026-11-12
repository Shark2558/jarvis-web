# tests/test_r11_a_birthdays.py -- R11 Part A (D8, item 7): birthdays from Google Contacts. The
# reader asks `people/me/connections` (names,birthdays; ≤ 2 pages) only while his Contacts row
# allows it (Never or unreadable rows: no request at all), takes the month and day only (the year
# never reaches any document, log, audit or alert), and asks Google about once a day. The job (off
# until he switches it on) sends ONE `birthday` at 08:30 that names nobody; the names go only in
# `named=`; once across restarts; released for a retry.
from __future__ import annotations

import logging
from datetime import date, timedelta

import pytest
from r11_fakes import NO_ROWS, UID, Clock, FakeNotifier, reads_over
from r11_fakes_a import (
    BrokenRules,
    DenyRules,
    FakePeople,
    at,
    connector,
    every_text,
    person,
    today_ctx,
)

from jarvis.helpers.today.bills import BillsService
from jarvis.helpers.today.birthdays import BirthdayReader, birthday_of
from jarvis.helpers.today.jobs import ONE_BIRTHDAY, BirthdaysJob, birthday_text
from jarvis.helpers.today.store import BillStore, Claims
from jarvis.notify.ports import Delivery
from jarvis.tools.audit import AuditLog

PEOPLE = [
    person("c1", "Asha Example", 11, 12, 1988),
    person("c2", "Ravi Example", 11, 12, None),
    person("c3", "Meera Example", 3, 4, 1975),
    person("c4", "Leap Example", 2, 29, 1996),
    {"resourceName": "people/c5", "names": [{"displayName": "No Birthday"}]},
]


def test_only_the_month_and_day_are_read() -> None:
    b = birthday_of(person("c1", "Asha Example", 11, 12, 1988))
    assert b is not None and (b.month, b.day) == (11, 12)
    assert "1988" not in repr(b)
    assert birthday_of({"resourceName": "people/c9", "names": [{"displayName": "X"}]}) is None
    assert (
        birthday_of({"resourceName": "../evil", "birthdays": [{"date": {"month": 1, "day": 1}}]})
        is None
    )
    leap = birthday_of(person("c4", "Leap", 2, 29))
    assert (
        leap is not None and leap.falls_on(date(2027, 2, 28)) and leap.falls_on(date(2028, 2, 29))
    )


async def _reader(fake: FakePeople, rules: object | None = None, **kw: object):  # type: ignore[no-untyped-def]
    clock = Clock(at(2026, 11, 12, 8, 30))
    audit = AuditLog()
    google = await connector(fake, **kw)  # type: ignore[arg-type]
    rows = rules if rules is not None else NO_ROWS
    reads = reads_over(lambda: rows, audit, now=clock)  # type: ignore[arg-type,return-value]
    return BirthdayReader(google, reads=reads, now=clock), audit, clock


async def test_the_reader_asks_once_a_day_and_pages() -> None:
    fake = FakePeople(PEOPLE, page=2)
    reader, audit, _ = await _reader(fake)
    got = await reader.on_day(UID, date(2026, 11, 12))
    assert got.state == "ok" and {p.name for p in got.people} == {"Asha Example", "Ravi Example"}
    assert len(fake.requests) == 2  # two pages of 2, then MAX_PAGES
    q = fake.requests[0].url.params
    assert q["personFields"] == "names,birthdays" and q["pageSize"] == "1000"
    await reader.on_day(UID, date(2026, 11, 12))
    assert len(fake.requests) == 2  # the day's reading is reused
    tail = await audit.tail(10)
    assert [e.outcome for e in tail.entries] == ["executed"]
    assert {e.tool for e in tail.entries} == {"contacts_birthdays"}


async def test_his_row_never_or_unreadable_means_no_request() -> None:
    for rules in (DenyRules("contacts_*"), BrokenRules()):
        fake = FakePeople(PEOPLE)
        reader, _, _ = await _reader(fake, rules)
        got = await reader.on_day(UID, date(2026, 11, 12))
        assert got.state == "denied" and got.people == () and fake.requests == []
        assert "switched off" not in got.note and got.note.startswith("Birthdays paused: ")


async def test_no_grant_or_no_link_is_a_plain_note() -> None:
    fake = FakePeople(PEOPLE)
    reader, _, _ = await _reader(fake, contacts=False)
    got = await reader.on_day(UID, date(2026, 11, 12))
    assert got.state == "not_granted" and "Grant" in got.note and fake.requests == []
    reader2, _, _ = await _reader(fake, linked=False)
    assert (await reader2.on_day(UID, date(2026, 11, 12))).state == "not_connected"


async def test_a_failure_is_asked_again_after_half_an_hour() -> None:
    fake = FakePeople(PEOPLE, status=500)
    reader, _, clock = await _reader(fake)
    assert (await reader.on_day(UID, date(2026, 11, 12))).state == "unavailable"
    n = len(fake.requests)
    await reader.on_day(UID, date(2026, 11, 12))
    assert len(fake.requests) == n
    fake.status = 200
    clock.at += timedelta(minutes=31)
    assert (await reader.on_day(UID, date(2026, 11, 12))).state == "ok"


def test_the_alert_names_nobody_and_named_is_for_names_in_alerts() -> None:
    b = [birthday_of(p) for p in PEOPLE[:3]]
    msg, named = birthday_text([x for x in b if x][:1])
    assert msg == ONE_BIRTHDAY and named == "Today is Asha Example's birthday."
    msg, named = birthday_text([x for x in b if x][:2])
    assert "2 birthdays today" in msg and "Asha" not in msg and "Ravi Example's" in named
    msg, named = birthday_text([x for x in b if x])
    assert named == "Birthdays today: Asha Example, Ravi Example and Meera Example."


async def _job(
    clock: Clock, fake: FakePeople, notifier: FakeNotifier | None = None, on: bool = True
):  # type: ignore[no-untyped-def]
    google = await connector(fake)
    c, n, docs, _ = today_ctx(clock=clock, notifier=notifier, google=google)
    svc = BillsService(BillStore(docs, c.keyring, prefix=c.prefix), tz=c.tz, now=c.now)
    if on:
        await svc.set_prefs(UID, birthdays_on=True)
    reader = BirthdayReader(google, reads=c.reads, now=c.now)
    claims = Claims(docs, "birthdays_told", prefix=c.prefix, keep_days=400)
    job = BirthdaysJob(svc, reader, claims, c.sender, owners=c.owners, tz=c.tz, now=c.now)
    return job, n, docs, c


async def test_one_alert_at_half_past_eight_once_and_no_year_anywhere(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.DEBUG)
    clock = Clock(at(2026, 11, 12, 8, 0))
    fake = FakePeople(PEOPLE)
    job, notifier, docs, c = await _job(clock, fake)
    for _ in range(24):  # 08:00 -> 09:55, every 5 minutes, twice over (a restart in between)
        await job.run(())
        clock.at += timedelta(minutes=5)
    assert len(notifier.calls) == 1
    uid, kind, message, named = notifier.calls[0]
    assert (
        kind == "birthday"
        and message == "2 birthdays today in your contacts: open JARVIS to see whose."
    )
    assert named == "Today is Asha Example's and Ravi Example's birthday."
    stored = every_text(docs)
    assert "1988" not in stored and "Asha" not in stored and "people/c1" not in stored
    assert "1988" not in caplog.text and "Asha" not in caplog.text
    tail = await c.audit.tail(20)
    assert all("1988" not in e.detail for e in tail.entries)


async def test_off_until_he_switches_it_on() -> None:
    clock = Clock(at(2026, 11, 12, 9, 0))
    fake = FakePeople(PEOPLE)
    job, notifier, _, _ = await _job(clock, fake, on=False)
    await job.run(())
    assert notifier.calls == [] and fake.requests == []


async def test_a_birthday_no_channel_took_goes_next_run() -> None:
    clock = Clock(at(2026, 11, 12, 8, 30))
    notifier = FakeNotifier(clock=clock, delivery=Delivery(action="ring", reason="none"))
    job, _, _, _ = await _job(clock, FakePeople(PEOPLE), notifier)
    await job.run(())
    notifier.delivery = Delivery(action="ring", reason="ok", telegram=True)
    clock.at += timedelta(minutes=5)
    await job.run(())
    clock.at += timedelta(minutes=5)
    await job.run(())
    assert len(notifier.calls) == 2


class FlakySweep(Claims):
    """Claims whose old-claim sweep fails `fails` times (the store briefly down)."""

    def __init__(self, *args: object, fails: int = 1, **kw: object) -> None:
        super().__init__(*args, **kw)  # type: ignore[arg-type]
        self.fails, self.sweeps = fails, 0

    async def sweep(self, uid: str, now):  # type: ignore[no-untyped-def]
        self.sweeps += 1
        if self.fails > 0:
            self.fails -= 1
            raise RuntimeError("store down for Asha Example 1988")
        return await super().sweep(uid, now)


async def test_a_failed_claim_sweep_never_stops_the_birthday_and_is_retried(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.DEBUG)
    clock = Clock(at(2026, 11, 12, 8, 30))
    job, notifier, docs, c = await _job(clock, FakePeople(PEOPLE))
    claims = FlakySweep(docs, "birthdays_told", prefix=c.prefix, keep_days=400)
    job._claims = claims  # noqa: SLF001 - the same job, its claims' sweep failing once
    got = await job.run(())
    assert got["sent"] == 1 and len(notifier.calls) == 1  # the birthday still went
    (warned,) = [r for r in caplog.records if r.getMessage() == "old claims not swept"]
    assert warned.error == "RuntimeError"  # type: ignore[attr-defined]  # the class only
    assert "Asha" not in caplog.text and all("Asha" not in repr(r.__dict__) for r in caplog.records)
    clock.at += timedelta(minutes=5)
    await job.run(())
    assert claims.sweeps == 2  # retried on the next run, not tomorrow
    clock.at += timedelta(minutes=5)
    await job.run(())
    assert claims.sweeps == 2 and len(notifier.calls) == 1  # swept once today; nothing twice
