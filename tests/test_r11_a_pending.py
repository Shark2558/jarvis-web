# tests/test_r11_a_pending.py -- R11 Part A (D9, item 10): "top priority now" and what is pending,
# from every part's pending sources (`ctx.pending_all()`), ranked by plain code: overdue, then due
# today, then urgency, then his pinned item, then the due date; a failing or slow source is left
# out (named), never fails the answer. Part A's own sources: bills due within a week or overdue,
# and Google Tasks due by today (his To-dos row obeyed, fail closed).
from __future__ import annotations

import asyncio
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta

from r11_fakes import NO_ROWS, UID, Clock, reads_over
from r11_fakes_a import FAKE_UPI, DenyRules, FakePeople, at, connector, keyring

from jarvis.helpers.ports import PendingItem
from jarvis.helpers.today.bills import BillsService
from jarvis.helpers.today.pending import (
    BillsPending,
    GoogleTasksDue,
    PendingService,
    TasksPending,
    rank,
)
from jarvis.helpers.today.store import BillStore
from jarvis.storage.docs import MemoryDocs
from jarvis.tools.audit import AuditLog
from jarvis.tools.policy import Effect, PolicyRule

T0 = datetime(2026, 11, 10, 6, 30, tzinfo=UTC)


@dataclass
class Fixed:
    name: str
    items: Sequence[PendingItem] = ()
    fail: bool = False
    slow: bool = False

    async def pending(self, uid: str, now: datetime) -> Sequence[PendingItem]:
        if self.fail:
            raise RuntimeError("down")
        if self.slow:
            await asyncio.sleep(5)
        return self.items


def _item(
    label: str, urgency: str, hours: float | None = None, weight: int = 0, src: str = "house"
) -> PendingItem:
    due = None if hours is None else T0 + timedelta(hours=hours)
    return PendingItem(source=src, label=label, urgency=urgency, due=due, weight=weight)  # type: ignore[arg-type]


def test_the_order_is_overdue_today_urgency_pin_then_due() -> None:
    items = [
        _item("later early", "later", 1),
        _item("soon", "soon", 30),
        _item("today late", "today", 9),
        _item("today pinned", "today", 10, weight=1),
        _item("overdue new", "overdue", -1),
        _item("overdue old", "overdue", -48),
        _item("today early", "today", 2),
        _item("today no time", "today", None),
    ]
    assert [i.label for i in rank(items)] == [
        "overdue old",
        "overdue new",
        "today pinned",
        "today early",
        "today late",
        "today no time",
        "soon",
        "later early",
    ]


async def test_a_failing_or_slow_source_is_left_out_and_named() -> None:
    good = Fixed("house", [_item("Water the plants", "today", 1)])
    svc = PendingService(
        lambda: (good, Fixed("nudges", fail=True), Fixed("kitchen", slow=True)), timeout_s=0.05
    )
    got = await svc.collect(UID, T0)
    assert [i.label for i in got.items] == ["Water the plants"]
    assert set(got.missing) == {"nudges", "kitchen"}
    top, _ = await svc.top(UID, T0)
    assert top is not None and top.label == "Water the plants"


async def test_the_list_is_the_top_ten_grouped_by_source_in_rank_order() -> None:
    many = [_item(f"chore {n}", "soon", n) for n in range(12)]
    bills = [_item("Electricity ₹1,240 due today", "today", 2, src="today")]
    svc = PendingService(lambda: (Fixed("house", many), Fixed("today", bills)))
    groups = await svc.grouped(UID, T0)
    assert [g for g, _ in groups] == ["today", "house"]
    assert sum(len(x) for _, x in groups) == 10


async def _bills(clock: Clock) -> BillsService:
    svc = BillsService(BillStore(MemoryDocs(), keyring()), tz="Asia/Kolkata", now=clock)
    await svc.add(UID, label="Electricity", upi=FAKE_UPI, amount="1240", day=11)
    await svc.add(UID, label="Rent", amount="25000", day=20)
    await svc.add(UID, label="Insurance", amount="varies", on="2027-02-01", every_months=0)
    return svc


async def test_bills_due_within_a_week_or_overdue_are_pending() -> None:
    clock = Clock(at(2026, 11, 10, 12, 0))
    svc = await _bills(clock)
    src = BillsPending(svc)
    got = await src.pending(UID, clock.at)
    assert [(i.label, i.urgency) for i in got] == [("Electricity ₹1,240 due tomorrow", "soon")]
    clock.at = at(2026, 11, 12, 12, 0)
    (late,) = [i for i in await src.pending(UID, clock.at) if i.label.startswith("Electricity")]
    assert late.urgency == "overdue" and late.label == "Electricity ₹1,240 overdue since Wed 11 Nov"
    await svc.mark_paid(UID, "Electricity")
    assert [i for i in await src.pending(UID, clock.at) if i.label.startswith("Electricity")] == []


async def test_without_a_keyring_bills_add_nothing() -> None:
    svc = BillsService(BillStore(MemoryDocs(), None), tz="Asia/Kolkata", now=Clock())
    assert await BillsPending(svc).pending(UID, T0) == []


class FakeTasks:
    def __init__(self, found: list[tuple[str, date]], fail: bool = False) -> None:
        self.found, self.fail, self.calls = found, fail, 0

    async def due(self, uid: str, day: date) -> list[tuple[str, date]]:
        self.calls += 1
        if self.fail:
            raise RuntimeError("tasks down")
        return self.found


async def test_tasks_due_by_today_obey_his_row() -> None:
    clock = Clock(at(2026, 11, 10, 12, 0))
    tasks = FakeTasks(
        [("File the GST return", date(2026, 11, 9)), ("Call the plumber", date(2026, 11, 10))]
    )
    src = TasksPending(tasks, reads=reads_over(lambda: NO_ROWS, AuditLog()), tz="Asia/Kolkata")
    got = await src.pending(UID, clock.at)
    assert [(i.label, i.urgency, i.source) for i in got] == [
        ("File the GST return", "overdue", "tasks"),
        ("Call the plumber", "today", "tasks"),
    ]
    never = reads_over(lambda: DenyRules("tasks_*"), AuditLog())  # type: ignore[arg-type,return-value]
    denied = TasksPending(tasks, reads=never, tz="Asia/Kolkata")
    calls = tasks.calls
    assert await denied.pending(UID, clock.at) == [] and tasks.calls == calls


class AskRules:
    """The owner's rows: Ask first for tools matching `pattern`."""

    def __init__(self, pattern: str) -> None:
        self.pattern = pattern

    async def rules_for(self, user_id: str) -> list[PolicyRule]:
        return [PolicyRule(tool_pattern=self.pattern, effect=Effect.ASK, source="owner:test")]


async def test_todos_on_ask_first_are_named_not_checked_never_silently_left_out() -> None:
    # Mark XIV review: "top priority" is decided on the Nudges row, so no to-do card was shown;
    # his To-dos row on "Ask first" means no read, and the answer names them as not checked.
    clock = Clock(at(2026, 11, 10, 12, 0))
    tasks = FakeTasks([("File the GST return", date(2026, 11, 9))])
    ask = reads_over(lambda: AskRules("tasks_*"), AuditLog())  # type: ignore[arg-type,return-value]
    svc = PendingService(lambda: [TasksPending(tasks, reads=ask, tz="Asia/Kolkata")])
    top, got = await svc.top(UID, clock.at)
    assert top is None and got.missing == ("tasks",) and tasks.calls == 0
    never = reads_over(lambda: DenyRules("tasks_*"), AuditLog())  # type: ignore[arg-type,return-value]
    quiet = PendingService(lambda: [TasksPending(tasks, reads=never, tz="Asia/Kolkata")])
    _, got = await quiet.top(UID, clock.at)
    assert got.missing == () and tasks.calls == 0  # "Never" is his own "don't read my to-dos"


async def test_google_tasks_not_granted_add_nothing() -> None:
    google = await connector(FakePeople())  # linked, but without the Tasks scope
    assert await GoogleTasksDue(google).due(UID, date(2026, 11, 10)) == []
    unlinked = await connector(FakePeople(), linked=False)
    assert await GoogleTasksDue(unlinked).due(UID, date(2026, 11, 10)) == []
