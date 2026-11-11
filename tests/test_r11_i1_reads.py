# tests/test_r11_i1_reads.py -- R11 I1, the mandatory gateway fix (CLAUDE.md: every tool call
# passes jarvis.tools.gateway). Every background reader of his own data -- birthdays (A, Google
# Contacts), to-dos for "top priority" (A, Google Tasks), breach notices (B, Gmail), the missed-
# activity and free-time calendar read (C, Google Calendar) and grocery receipts (D, Gmail) --
# takes ONE governed path, `BackgroundReads.of(gateway)` (jarvis.tools.background): the gateway's
# own policy and his rows decide, only ALLOW reads (Ask first, Never, unreadable rules, no
# permission service, no gateway, an unknown or non-read tool: no read), and each refusal or read
# leaves the same kind-only audit line. Each reader is shown here: a denied row means no request at
# all and that audit line.
# Integrated review fixes: a read inside a tool call the gateway itself decided (Ask first: the
# card, then his OK) reads on "Ask first", never on "Never"; a job still reads on "Allow" only;
# `allowed()` says why (allowed / ask_first / denied / unreadable); a read cut by the job's time
# budget (CancelledError) still leaves its line (`reading()`), and no permission service is no read.
from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from typing import Any

import pytest
from r11_fakes import NO_ROWS, UID, AnyReadRegistry, Clock, ctx, reads_over

from jarvis.core.guardrails import ActionRisk, ConfirmationGate
from jarvis.llm.base import ToolCall
from jarvis.storage.docs import MemoryDocs
from jarvis.tools.audit import AuditEntry, AuditLog, args_hash
from jarvis.tools.background import BackgroundReads
from jarvis.tools.base import Tool
from jarvis.tools.context import tool_context
from jarvis.tools.gateway import Gateway, GatewayOutcome
from jarvis.tools.policy import Effect, Policy, PolicyRule
from jarvis.tools.registry import ToolRegistry

NOON = datetime(2026, 11, 12, 6, 30, tzinfo=UTC)


class Rows:
    """His permission rows: `effect` on tools matching `pattern`; `fail` = the store is down."""

    def __init__(self, pattern: str = "", effect: Effect | None = None, *, fail: bool = False):
        self.pattern, self.effect, self.fail = pattern, effect, fail

    async def rules_for(self, user_id: str) -> list[PolicyRule]:
        if self.fail:
            raise RuntimeError("the permission rows can't be read")
        if self.effect is None:
            return []
        return [PolicyRule(tool_pattern=self.pattern, effect=self.effect, source="owner:test")]


def _tool(name: str, risk: ActionRisk = ActionRisk.READ_ONLY) -> Tool:
    async def run(args: dict[str, Any]) -> dict[str, Any]:
        return {}

    return Tool(name, f"test {name}", {"type": "object", "properties": {}}, risk, run)


def _gateway(rows: Rows | None, *tools: Tool) -> Gateway:
    reg = ToolRegistry()
    for t in tools:
        reg.register(t)
    gw = Gateway(registry=reg, policy=Policy(), gate=ConfirmationGate(), audit=AuditLog())
    gw.rules = rows
    return gw


NO_ARGS = args_hash({})


def _line(e: AuditEntry) -> tuple[str, str, str, str]:
    assert e.args_hash == NO_ARGS and e.risk is ActionRisk.READ_ONLY  # kind only: no arguments
    return (e.agent, e.tool, e.outcome, e.detail)


async def _lines(audit: Any) -> list[tuple[str, str, str, str]]:
    return [_line(e) for e in (await audit.tail(50)).entries]


# ---- the governed path itself ------------------------------------------------------------------
async def test_the_gateways_policy_and_his_rows_decide_and_only_allow_reads() -> None:
    read = _tool("contacts_birthdays")
    cases = [
        # no permission service at all: fail closed (code review M2; D's old pin)
        (None, "unreadable", ("error", "no permission service")),
        (Rows(), "allowed", None),
        (Rows("contacts_*", Effect.ALLOW), "allowed", None),
        (Rows("contacts_*", Effect.ASK), "ask_first", ("denied", "ask first")),  # nobody to ask
        (Rows("contacts_*", Effect.DENY), "denied", ("denied", "never")),
        (Rows(fail=True), "unreadable", ("error", "permissions unreadable")),  # fail closed
    ]
    for rows, reason, line in cases:
        gw = _gateway(rows, read)
        reads = BackgroundReads.of(gw, now=Clock(NOON))
        got_v = await reads.allowed(UID, "contacts_birthdays", job="birthdays")
        ok = reason == "allowed"
        assert got_v.reason == reason and bool(got_v) is ok and got_v.ok is ok, rows
        assert got_v.tool == ("" if reason == "allowed" else "contacts_birthdays")
        assert await reads.verdict(UID, "contacts_birthdays") == got_v  # the same, no line
        got = await _lines(gw.audit)
        want = (
            []
            if line is None
            else [("helpers", "contacts_birthdays", line[0], f"birthdays; {line[1]}")]
        )
        assert got == want, (rows, got)


async def test_an_unknown_tool_a_write_tool_no_owner_or_no_gateway_means_no_read() -> None:
    gw = _gateway(None, _tool("chore_add", ActionRisk.REVERSIBLE))
    reads = BackgroundReads.of(gw)
    assert (await reads.allowed(UID, "gmail_search", job="breach_watch")).ok is False
    assert (await reads.allowed(UID, "chore_add", job="chores_due")).ok is False
    assert (await reads.allowed("", "chore_add", job="chores_due")).ok is False
    assert [d for *_, d in await _lines(gw.audit)] == [
        "breach_watch; unknown tool",
        "chores_due; not a read",
        "chores_due; no owner",
    ]
    fallback = AuditLog()
    none = BackgroundReads(lambda: None, audit=fallback)
    assert (await none.allowed(UID, "gmail_search", job="grocery_spend")).ok is False
    assert await _lines(fallback) == [
        ("helpers", "gmail_search", "error", "grocery_spend; no gateway")
    ]


async def test_every_named_tool_must_be_allowed_and_a_refusal_is_audited_once_a_day() -> None:
    gw = _gateway(Rows("spend_*", Effect.DENY), _tool("gmail_search"), _tool("spend_month"))
    clock = Clock(NOON)
    reads = BackgroundReads.of(gw, now=clock)
    for _ in range(3):
        assert (
            await reads.allowed(UID, "gmail_search", "spend_month", job="grocery_spend")
        ).ok is False
    assert len(await _lines(gw.audit)) == 1  # a 5-minute job never floods the chain
    clock.at += timedelta(days=1)
    assert (
        await reads.allowed(UID, "gmail_search", "spend_month", job="grocery_spend")
    ).ok is False
    assert len(await _lines(gw.audit)) == 2


async def test_the_wired_context_reads_through_the_apps_gateway(settings: Any) -> None:
    import jarvis.api.r11_wiring as r11
    from jarvis.api import create_app
    from jarvis.llm.mock_provider import MockProvider
    from jarvis.memory.inmemory import InMemorySessionStore

    app = create_app(settings, provider=MockProvider(), store=InMemorySessionStore())
    async with app.router.lifespan_context(app):
        st = app.state
        audit = st.gateway.audit
        c = r11._context(app, settings, MemoryDocs(), audit, st.helpers_sender, "today")  # noqa: SLF001
        assert c.reads is not None
        assert (await c.reads.allowed(UID, "contacts_birthdays", job="birthdays")).ok is True
        gateway, st.gateway = st.gateway, None
        assert (await c.reads.allowed(UID, "contacts_birthdays", job="birthdays")).ok is False
        st.gateway = gateway
        lines = [e for e in (await gateway.audit.tail(20)).entries if e.agent == "helpers"]
        assert [(e.tool, e.outcome, e.detail) for e in lines][-1:] == [
            ("contacts_birthdays", "error", "birthdays; no gateway")
        ]


# ---- each reader, a denied row: no request and the same audit line ----------------------------
def _denied(rows: Rows, audit: Any) -> BackgroundReads:
    return reads_over(lambda: rows, audit, now=Clock(NOON), registry=AnyReadRegistry())  # type: ignore[arg-type,return-value]


async def test_birthdays_a_denied_contacts_row_means_no_request_and_one_audit_line() -> None:
    from r11_fakes_a import FakePeople, connector, person

    from jarvis.helpers.today.birthdays import BirthdayReader

    fake = FakePeople([person("c1", "Asha Example", 11, 12, 1988)])
    audit = AuditLog()
    google = await connector(fake)
    reader = BirthdayReader(
        google, reads=_denied(Rows("contacts_*", Effect.DENY), audit), now=Clock(NOON)
    )
    got = await reader.on_day(UID, date(2026, 11, 12))
    assert got.state == "denied" and fake.requests == []
    assert await _lines(audit) == [("helpers", "contacts_birthdays", "denied", "birthdays; never")]
    allowed = BirthdayReader(google, reads=reads_over(lambda: NO_ROWS, audit), now=Clock(NOON))
    assert (await allowed.on_day(UID, date(2026, 11, 12))).state == "ok"
    last = (await _lines(audit))[-1]
    assert last == ("helpers", "contacts_birthdays", "executed", "birthdays")
    nobody = BirthdayReader(google, reads=None, now=Clock(NOON))  # no governed path: no read
    n = len(fake.requests)
    assert (await nobody.on_day(UID, date(2026, 11, 13))).state == "denied" and len(
        fake.requests
    ) == n


async def test_todos_a_denied_tasks_row_means_no_request_and_one_audit_line() -> None:
    from jarvis.helpers.today.pending import TasksPending

    class Tasks:
        calls = 0

        async def due(self, uid: str, today: date) -> list[tuple[str, date]]:
            Tasks.calls += 1
            return [("File the return", today)]

    audit = AuditLog()
    src = TasksPending(
        Tasks(), reads=_denied(Rows("tasks_*", Effect.DENY), audit), tz="Asia/Kolkata"
    )
    assert await src.pending(UID, NOON) == [] and Tasks.calls == 0
    assert await _lines(audit) == [("helpers", "tasks_list", "denied", "pending; never")]
    ok = TasksPending(Tasks(), reads=reads_over(lambda: NO_ROWS, audit), tz="Asia/Kolkata")
    assert [i.label for i in await ok.pending(UID, NOON)] == ["File the return"]
    assert (await _lines(audit))[-1] == ("helpers", "tasks_list", "executed", "pending")


async def test_breach_notices_a_denied_email_row_means_no_request_and_one_audit_line() -> None:
    from r11_fakes_b import Rules, gmail_with, house_ctx

    from jarvis.helpers.house import breach
    from jarvis.helpers.house.store import HouseStore, OutsideStore

    gmail = gmail_with("b_gmail_hibp.json")
    hc, notifier, docs, _ = house_ctx(google=gmail, rules=Rules(never=("gmail_*",)))
    outside = OutsideStore(docs, hc.keyring, prefix=hc.prefix)
    await outside.change(UID, lambda o: o.model_copy(update={"breach_on": True}))
    got = await breach.BreachJob(hc, outside, HouseStore(docs, prefix=hc.prefix)).run(())
    assert got["sent"] == 0 and gmail.calls == [] and notifier.calls == []
    assert await _lines(hc.audit) == [("helpers", "gmail_search", "denied", "breach_watch; never")]


async def test_the_calendar_read_a_denied_calendar_row_means_no_request_and_one_audit_line() -> (
    None
):
    from jarvis.helpers.nudges.calendar import Agenda

    class Source:
        calls = 0

        async def events(self, uid: str, start: datetime, end: datetime) -> list[Any]:
            Source.calls += 1
            return []

    audit = AuditLog()
    agenda = Agenda(
        Source(), reads=_denied(Rows("calendar_*", Effect.DENY), audit), now=Clock(NOON)
    )
    assert await agenda.today(UID, NOON, NOON + timedelta(hours=8)) is None and Source.calls == 0
    assert await _lines(audit) == [("helpers", "calendar_list_events", "denied", "nudges; never")]
    ok = Agenda(Source(), reads=reads_over(lambda: NO_ROWS, audit), now=Clock(NOON))
    assert await ok.today(UID, NOON, NOON + timedelta(hours=8)) == [] and Source.calls == 1
    last = (await _lines(audit))[-1]
    assert last == ("helpers", "calendar_list_events", "executed", "nudges")


async def test_receipts_a_denied_email_row_means_no_request_and_one_audit_line() -> None:
    from r11_fakes_d import MailBox, Rules, connector, kctx

    from jarvis.helpers.kitchen.spend import GrocerySpendJob, SpendService
    from jarvis.helpers.kitchen.store import SpendStore

    box = MailBox(("d_receipt_bigbasket_nov.eml",))
    conn = await connector(box.client())
    c, _, docs, _ = kctx(google=conn, rules=Rules("gmail_*", Effect.DENY))
    svc = SpendService(SpendStore(docs, c.keyring, now=c.now, tz=c.tz), google=conn, now=c.now)
    await svc.set_on(UID, True)
    counts = await GrocerySpendJob(svc, owners=c.owners, reads=c.reads).run([])
    assert counts["skipped"] == 1 and box.requests == []
    assert await _lines(c.audit) == [("helpers", "gmail_search", "denied", "grocery_spend; never")]


def test_the_fake_context_carries_the_governed_path() -> None:
    c, _, _, _ = ctx("today")
    assert isinstance(c.reads, BackgroundReads)


# ---- integrated review fixes -------------------------------------------------------------------
def _reader_tool(reads: BackgroundReads, name: str, row_tool: str) -> Tool:
    """A console tool that reads his data through the path, as focus_now reads his to-dos."""

    async def run(args: dict[str, Any]) -> dict[str, Any]:
        got = await reads.allowed(UID, row_tool, job="pending")
        return {"reason": got.reason}

    return Tool(
        name, f"test {name}", {"type": "object", "properties": {}}, ActionRisk.READ_ONLY, run
    )


async def _decided(rows: Rows) -> tuple[str, Gateway]:
    """`pending_list` (its own row: Allow) reads `tasks_list` (another row) inside the gateway's
    decided call: the gateway decided `pending_list`'s row, not the to-dos'."""
    holder: dict[str, Gateway] = {}
    reads = BackgroundReads(lambda: holder["gw"], audit=AuditLog(), now=Clock(NOON))
    gw = _gateway(rows, _reader_tool(reads, "pending_list", "tasks_list"), _tool("tasks_list"))
    holder["gw"] = gw
    call = ToolCall(id="p1", name="pending_list", arguments={})
    res = await gw.execute(call, scope=f"{UID}:s1")
    assert res.outcome is GatewayOutcome.EXECUTED, res
    return str(res.result["reason"]), gw


async def test_a_decided_call_on_one_row_never_opens_another_rows_ask_first() -> None:
    # Mark XIV review of the fixer: no to-do card was shown, so "Ask first" on the to-dos holds
    assert (await _decided(Rows("tasks_*", Effect.ASK)))[0] == "ask_first"
    assert (await _decided(Rows("tasks_*", Effect.DENY)))[0] == "denied"
    assert (await _decided(Rows("tasks_*", Effect.ALLOW)))[0] == "allowed"


async def test_inside_the_gateways_call_for_that_very_tool_ask_first_reads() -> None:
    gw = _gateway(Rows("tasks_*", Effect.ASK), _tool("tasks_list"), _tool("pending_list"))
    reads = BackgroundReads.of(gw, now=Clock(NOON))
    with tool_context(f"{UID}:s1", approved_risk=ActionRisk.READ_ONLY, tool="tasks_list"):
        assert (await reads.allowed(UID, "tasks_list", job="pending")).reason == "allowed"
    with tool_context(f"{UID}:s1", approved_risk=ActionRisk.READ_ONLY, tool="pending_list"):
        assert (await reads.allowed(UID, "tasks_list", job="pending")).reason == "ask_first"
    gw_never = _gateway(Rows("tasks_*", Effect.DENY), _tool("tasks_list"))
    never = BackgroundReads.of(gw_never, now=Clock(NOON))
    with tool_context(f"{UID}:s1", approved_risk=ActionRisk.READ_ONLY, tool="tasks_list"):
        assert (await never.allowed(UID, "tasks_list", job="pending")).reason == "denied"


async def test_a_job_still_reads_on_allow_only_and_cannot_pass_its_way_in() -> None:
    gw = _gateway(Rows("tasks_*", Effect.ASK), _tool("tasks_list"))
    reads = BackgroundReads.of(gw, now=Clock(NOON))
    assert (await reads.allowed(UID, "tasks_list", job="pending")).reason == "ask_first"
    with tool_context(f"{UID}:s1"):  # a context that is not the gateway's decision (no risk)
        assert (await reads.allowed(UID, "tasks_list", job="pending")).reason == "ask_first"
    with tool_context("someone_else:s1", approved_risk=ActionRisk.READ_ONLY):  # another owner
        assert (await reads.allowed(UID, "tasks_list", job="pending")).reason == "ask_first"
    with tool_context(f"{UID}:s1", approved_risk=ActionRisk.READ_ONLY, tool="tasks_list"):
        assert (await reads.verdict(UID, "tasks_list")).reason == "ask_first"  # status: a job's


async def test_an_approved_birthdays_card_reads_and_the_morning_job_does_not() -> None:
    from r11_fakes_a import FakePeople, connector, gateway_rig, person, today_ctx

    from jarvis.helpers.today import part as today_part

    fake = FakePeople([person("c1", "Asha Example", 11, 12, 1988)])
    c, _, _, _ = today_ctx(google=await connector(fake), clock=Clock(NOON))
    holder: dict[str, Gateway] = {}
    c = replace(c, reads=BackgroundReads(lambda: holder["gw"], audit=c.audit, now=Clock(NOON)))
    part = today_part.build(c)
    rig = gateway_rig(part, rules=Rows("contacts_*", Effect.ASK))
    holder["gw"] = rig.gateway
    call = ToolCall(id="b1", name="contacts_birthdays", arguments={"days": 7})
    res = await rig.gateway.execute(call, scope=rig.scope)
    assert res.outcome is GatewayOutcome.AWAITING_CONFIRMATION and fake.requests == []
    assert res.pending is not None
    again = ToolCall(id="b2", name="contacts_birthdays", arguments={"days": 7})
    done = await rig.gateway.execute(again, confirmation_id=res.pending.id, scope=rig.scope)
    assert done.outcome is GatewayOutcome.EXECUTED and fake.requests, done
    assert "Asha Example" in str(done.result["today"]) and "switched off" not in str(done.result)
    # the morning job (no gateway decision): "Ask first" is no read, and it says so plainly
    got = await part.services["birthdays"].on_day(UID, date(2026, 11, 12))
    assert got.state == "denied"
    assert "Contacts permission is set to Ask first" in got.note and "switched off" not in got.note


async def test_a_read_cut_by_the_budget_leaves_its_line_and_the_cancel_goes_on() -> None:
    gw = _gateway(Rows(), _tool("gmail_search"))
    reads = BackgroundReads.of(gw, now=Clock(NOON))

    async def slow() -> None:
        async with reads.reading("gmail_search", job="breach_watch"):
            await asyncio.sleep(5)

    with pytest.raises(TimeoutError):
        await asyncio.wait_for(slow(), 0.05)
    async with reads.reading("gmail_search", job="breach_watch"):
        pass
    with pytest.raises(RuntimeError):
        async with reads.reading("gmail_search", job="breach_watch"):
            raise RuntimeError("Gmail down")
    assert [(o, d) for _, _, o, d in await _lines(gw.audit)] == [
        ("error", "breach_watch; cut"),
        ("executed", "breach_watch"),
        ("error", "breach_watch; failed"),
    ]


async def test_each_reader_audits_a_read_the_tick_budget_cuts() -> None:
    from jarvis.helpers.nudges.calendar import Agenda
    from jarvis.helpers.today.pending import TasksPending

    class Slow:
        async def due(self, uid: str, today: date) -> list[tuple[str, date]]:
            await asyncio.sleep(5)
            return []

        async def events(self, uid: str, start: datetime, end: datetime) -> list[Any]:
            await asyncio.sleep(5)
            return []

    audit = AuditLog()
    reads = reads_over(lambda: NO_ROWS, audit, now=Clock(NOON))
    with pytest.raises(TimeoutError):
        await asyncio.wait_for(
            TasksPending(Slow(), reads=reads, tz="Asia/Kolkata").pending(UID, NOON), 0.05
        )
    agenda = Agenda(Slow(), reads=reads, now=Clock(NOON))
    with pytest.raises(TimeoutError):
        await asyncio.wait_for(agenda.today(UID, NOON, NOON + timedelta(hours=8)), 0.05)
    assert [(t, o, d) for _, t, o, d in await _lines(audit)] == [
        ("tasks_list", "error", "pending; cut"),
        ("calendar_list_events", "error", "nudges; cut"),
    ]


async def test_no_permission_service_wired_means_no_read_for_every_reader() -> None:
    """D's old pin, restored for the one path (code review M2): rules None = unreadable."""
    from jarvis.helpers.today.pending import NotRead, TasksPending

    class Tasks:
        calls = 0

        async def due(self, uid: str, today: date) -> list[tuple[str, date]]:
            Tasks.calls += 1
            return [("File the return", today)]

    audit = AuditLog()
    src = TasksPending(Tasks(), reads=reads_over(lambda: None, audit), tz="Asia/Kolkata")
    with pytest.raises(NotRead):  # no read; "top priority" names his to-dos as not checked
        await src.pending(UID, NOON)
    assert Tasks.calls == 0
    assert await _lines(audit) == [
        ("helpers", "tasks_list", "error", "pending; no permission service")
    ]
