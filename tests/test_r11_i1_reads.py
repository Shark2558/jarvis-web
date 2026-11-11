# tests/test_r11_i1_reads.py -- R11 I1, the mandatory gateway fix (CLAUDE.md: every tool call
# passes jarvis.tools.gateway). Every background reader of his own data -- birthdays (A, Google
# Contacts), to-dos for "top priority" (A, Google Tasks), breach notices (B, Gmail), the missed-
# activity and free-time calendar read (C, Google Calendar) and grocery receipts (D, Gmail) --
# takes ONE governed path, `Gateway.background()` (jarvis.tools.background): the gateway's own
# policy and his rows decide, only ALLOW reads (Ask first, Never, unreadable rules, no gateway, an
# unknown or non-read tool: no read), and each refusal or read leaves the same kind-only audit
# line. Each reader is shown here: a denied row means no request at all and that audit line.
from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from typing import Any

from r11_fakes import UID, AnyReadRegistry, Clock, ctx, reads_over

from jarvis.core.guardrails import ActionRisk, ConfirmationGate
from jarvis.storage.docs import MemoryDocs
from jarvis.tools.audit import AuditEntry, AuditLog, args_hash
from jarvis.tools.background import BackgroundReads
from jarvis.tools.base import Tool
from jarvis.tools.gateway import Gateway
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
        (None, True, None),  # no permission service: the gateway's configured policy (allow)
        (Rows(), True, None),
        (Rows("contacts_*", Effect.ALLOW), True, None),
        (Rows("contacts_*", Effect.ASK), False, ("denied", "ask first")),  # nobody to ask
        (Rows("contacts_*", Effect.DENY), False, ("denied", "never")),
        (Rows(fail=True), False, ("error", "permissions unreadable")),  # fail closed
    ]
    for rows, ok, line in cases:
        gw = _gateway(rows, read)
        reads = gw.background(now=Clock(NOON))
        assert await reads.allowed(UID, "contacts_birthdays", job="birthdays") is ok, rows
        got = await _lines(gw.audit)
        want = (
            []
            if line is None
            else [("helpers", "contacts_birthdays", line[0], f"birthdays; {line[1]}")]
        )
        assert got == want, (rows, got)


async def test_an_unknown_tool_a_write_tool_no_owner_or_no_gateway_means_no_read() -> None:
    gw = _gateway(None, _tool("chore_add", ActionRisk.REVERSIBLE))
    reads = gw.background()
    assert await reads.allowed(UID, "gmail_search", job="breach_watch") is False
    assert await reads.allowed(UID, "chore_add", job="chores_due") is False
    assert await reads.allowed("", "chore_add", job="chores_due") is False
    assert [d for *_, d in await _lines(gw.audit)] == [
        "breach_watch; unknown tool",
        "chores_due; not a read",
        "chores_due; no owner",
    ]
    fallback = AuditLog()
    none = BackgroundReads(lambda: None, audit=fallback)
    assert await none.allowed(UID, "gmail_search", job="grocery_spend") is False
    assert await _lines(fallback) == [
        ("helpers", "gmail_search", "error", "grocery_spend; no gateway")
    ]


async def test_every_named_tool_must_be_allowed_and_a_refusal_is_audited_once_a_day() -> None:
    gw = _gateway(Rows("spend_*", Effect.DENY), _tool("gmail_search"), _tool("spend_month"))
    clock = Clock(NOON)
    reads = gw.background(now=clock)
    for _ in range(3):
        assert await reads.allowed(UID, "gmail_search", "spend_month", job="grocery_spend") is False
    assert len(await _lines(gw.audit)) == 1  # a 5-minute job never floods the chain
    clock.at += timedelta(days=1)
    assert await reads.allowed(UID, "gmail_search", "spend_month", job="grocery_spend") is False
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
        assert await c.reads.allowed(UID, "contacts_birthdays", job="birthdays") is True
        gateway, st.gateway = st.gateway, None
        assert await c.reads.allowed(UID, "contacts_birthdays", job="birthdays") is False
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
    allowed = BirthdayReader(google, reads=reads_over(lambda: None, audit), now=Clock(NOON))
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
    ok = TasksPending(Tasks(), reads=reads_over(lambda: None, audit), tz="Asia/Kolkata")
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
    ok = Agenda(Source(), reads=reads_over(lambda: None, audit), now=Clock(NOON))
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
