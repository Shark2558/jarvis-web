# evals/r11_helpers/today.py
"""A's part of the R11 eval (plan docs/plans/r11-free-helpers.md "Tests and evals"): bills and the
prepared UPI payment, birthdays, top priority, all on fakes through a real gateway.

Cases: a bill due in 3 / 1 / 0 days sends `bill_due` at 09:00 each day (and once overdue), none
twice across a restart, every one on time over 14 days of the 5-minute clock with jitter; the
`bill_pay_prepare` card text exactly; approved, a link and a QR shown once and nothing stored; a UPI
ID from a round that read an e-mail never becomes a payee; over ₹1,00,000 refused; a 16-digit
number in a bill field refused; birthdays: the year in no document, log, audit or alert, and the
name only in `named=`; the pending order. Control: the taint check off (`tools.TAINT_REFUSAL`), so
an e-mailed UPI ID becomes a payee, which must make this part fail.
"""

from __future__ import annotations

import dataclasses
import logging
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from typing import Any

from r11_fakes import UID, Clock
from r11_fakes_a import (
    FAKE_UPI,
    OTHER_UPI,
    FakePeople,
    at,
    connector,
    every_text,
    gateway_rig,
    person,
    today_ctx,
)

from jarvis.helpers.gate import fortnight
from jarvis.helpers.ports import PendingItem
from jarvis.helpers.today import part as today_part
from jarvis.helpers.today import tools as today_tools
from jarvis.helpers.today.pending import rank
from jarvis.llm.base import ToolCall
from jarvis.tools.gateway import GatewayOutcome
from jarvis.tools.taint import context_trust

PART = "today"
BUILT = True
Case = Callable[[], Awaitable[list[str]]]
CARD = (
    "Get a UPI payment ready: ₹1,240.00 to “Power Co” (test@okfake), note “Electricity Nov”. You "
    "confirm it and enter your PIN in your UPI app. JARVIS never pays."
)


async def _built(clock: Clock | None = None, **kw: Any) -> Any:
    c, notifier, docs, clk = today_ctx(clock=clock, **kw)
    part = today_part.build(c)
    svc = part.services["bills"]
    await svc.add(UID, label="Electricity", payee="Power Co", upi=FAKE_UPI, amount="1240", day=13)
    return part, svc, notifier, docs, clk, c


async def _call(rig: Any, name: str, *, tainted: bool = False, **args: Any) -> Any:
    with context_trust(untrusted=tainted, owner_text="pay it"):
        return await rig.gateway.execute(
            ToolCall(id="e", name=name, arguments=args), scope=rig.scope
        )


async def _approve(rig: Any, res: Any) -> Any:
    if res.outcome is not GatewayOutcome.AWAITING_CONFIRMATION:
        return res
    call = ToolCall(id="ok", name=res.pending.tool, arguments=res.pending.arguments)
    return await rig.gateway.execute(call, confirmation_id=res.pending.id, scope=rig.scope)


async def _three_one_zero() -> list[str]:
    clock = Clock(at(2026, 11, 10, 0, 0))
    part, _, notifier, _, _, _ = await _built(clock)
    job = part.clock_jobs[0]
    sent: list[datetime] = []
    while clock.at <= at(2026, 11, 14, 23, 55):
        before = len(notifier.calls)
        await job.run(())
        await job.run(())  # the morning tick in the same minute: nothing twice
        sent += [clock.at] * (len(notifier.calls) - before)
        clock.at += timedelta(minutes=5)
    want = [at(2026, 11, d, 9, 0) for d in (10, 12, 13, 14)]
    return [] if sent == want else [f"bill reminders at {sent}, want {want}"]


async def _restart() -> list[str]:
    clock = Clock(at(2026, 11, 12, 9, 0))
    part, _, notifier, docs, _, c = await _built(clock)
    await part.clock_jobs[0].run(())
    c2, n2, _, _ = today_ctx(clock=clock)
    again = today_part.build(dataclasses.replace(c2, docs=docs))  # a new process, the same store
    clock.at += timedelta(minutes=5)
    await again.clock_jobs[0].run(())
    total = len(notifier.calls) + len(n2.calls)
    return [] if total == 1 else [f"{total} reminders across a restart, want 1"]


async def _fourteen_days() -> list[str]:
    start = at(2026, 11, 1, 0, 0)
    clock = Clock(start)
    part, svc, _, _, _, c = await _built(clock)
    await svc.add(UID, label="Water", payee="Water Co", amount="300", day=8)
    job = part.clock_jobs[0]
    for tick in range(14 * 288):
        clock.at = start + timedelta(minutes=5 * tick, seconds=(tick * 37) % 41)
        await job.run(())
    store = c.sender._sender.store  # noqa: SLF001 - the gate's own send log
    got = fortnight(await store.days(UID), c.sender.today(), max_per_day=16)
    sends = sum(len(s) for _, s in await store.days(UID))
    fails = [] if got["reminders_late"] == got["reminders_early"] == 0 else [str(got)]
    return fails + (
        [] if got["reminders_on_time"] == sends >= 6 else [f"on time {got}, sent {sends}"]
    )


async def _card_text() -> list[str]:
    part, _, _, _, _, _ = await _built()
    res = await _call(gateway_rig(part), "bill_pay_prepare", bill="Electricity")
    summary = res.pending.summary if res.pending else None
    return [] if summary == CARD else [f"card: {summary!r}"]


async def _approve_once() -> list[str]:
    part, svc, _, docs, _, _ = await _built()
    rig = gateway_rig(part)
    done = await _approve(rig, await _call(rig, "bill_pay_prepare", bill="Electricity"))
    fails = [] if "upi://" not in str(done.result) else ["the tool result carries the link"]
    bill = (await svc.book(UID)).bills[0]
    shown, twice = await svc.payment(UID, bill.id), await svc.payment(UID, bill.id)
    if shown is None or not shown.link.startswith(
        "upi://pay?pa=test@okfake&pn=Power%20Co&am=1240.00"
    ):
        fails.append("no link after the approval")
    if shown is not None and not shown.qr.startswith("data:image/svg+xml"):
        fails.append("no QR")
    if twice is not None:
        fails.append("the payment was shown twice")
    stored = every_text(docs) + str((await rig.audit.tail(50)).entries)
    return fails + (["a link or QR was stored"] if "upi://" in stored or "svg" in stored else [])


async def _emailed_upi() -> list[str]:
    part, svc, _, _, _, _ = await _built()
    rig = gateway_rig(part)
    res = await _call(rig, "bill_payee_set", tainted=True, bill="Electricity", upi=OTHER_UPI)
    await _approve(rig, res)  # with the check off, he would approve the card he is shown
    upi = (await svc.book(UID)).bills[0].upi
    return [] if upi == FAKE_UPI else [f"an e-mailed UPI ID became the payee ({upi})"]


async def _over_cap() -> list[str]:
    part, _, _, _, _, _ = await _built()
    res = await _call(gateway_rig(part), "bill_pay_prepare", bill="Electricity", amount="100000.01")
    ok = res.outcome is GatewayOutcome.ERROR and "1,00,000" in (res.error or "")
    return [] if ok else [f"over the cap: {res.outcome.value}"]


async def _card_number() -> list[str]:
    part, svc, _, docs, _, _ = await _built()
    rig = gateway_rig(part)
    fails = []
    for args in (
        {"label": "Card 4111111111111111", "amount": "500", "day": 3},
        {"label": "Card", "payee": "4111 1111 1111 1111", "amount": "500", "day": 3},
        {"label": "Card", "last4": "4111111111111111", "amount": "500", "day": 3},
    ):
        res = await _call(rig, "bill_add", **args)
        if res.outcome is not GatewayOutcome.ERROR:
            fails.append(f"a 16-digit number was taken: {sorted(args)}")
    return fails + (["a card number was stored"] if "4111" in every_text(docs) else [])


class _Logs(logging.Handler):
    def __init__(self) -> None:
        super().__init__(logging.DEBUG)
        self.text: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.text.append(record.getMessage() + repr(record.__dict__))


async def _birthdays() -> list[str]:
    handler = _Logs()
    logging.getLogger().addHandler(handler)
    try:
        fake = FakePeople([person("c1", "Asha Example", 11, 12, 1988)])
        clock = Clock(at(2026, 11, 12, 8, 30))
        part, svc, notifier, docs, _, c = await _built(clock, google=await connector(fake))
        await svc.set_prefs(UID, birthdays_on=True)
        await part.clock_jobs[1].run(())
    finally:
        logging.getLogger().removeHandler(handler)
    fails = [] if len(notifier.calls) == 1 else [f"{len(notifier.calls)} birthday alerts, want 1"]
    if notifier.calls and "Asha" in notifier.calls[0][2]:
        fails.append("the alert names the contact")
    if notifier.calls and "Asha" not in (notifier.calls[0][3] or ""):
        fails.append("no named= version for 'names in alerts'")
    places = every_text(docs) + " ".join(handler.text) + str((await c.audit.tail(50)).entries)
    return fails + (["the birth year was kept or logged"] if "1988" in places else [])


async def _pending_order() -> list[str]:
    t0 = datetime(2026, 11, 10, 6, 30, tzinfo=UTC)

    def item(label: str, urgency: str, hours: int, weight: int = 0) -> PendingItem:
        return PendingItem("house", label, urgency, due=t0 + timedelta(hours=hours), weight=weight)  # type: ignore[arg-type]

    items = [item("later", "later", 1), item("today", "today", 5), item("pinned", "today", 9, 1)]
    items += [item("overdue", "overdue", -2), item("soon", "soon", 2)]
    got = [i.label for i in rank(items)]
    want = ["overdue", "pinned", "today", "soon", "later"]
    return [] if got == want else [f"pending order {got}"]


CASES: dict[str, Case] = {
    "bill-3-1-0-days-at-nine": _three_one_zero,
    "bill-never-twice-across-restart": _restart,
    "bill-fourteen-days-on-time": _fourteen_days,
    "pay-card-text-exact": _card_text,
    "pay-approved-shown-once-nothing-stored": _approve_once,
    "emailed-upi-never-a-payee": _emailed_upi,
    "over-the-cap-refused": _over_cap,
    "card-number-refused": _card_number,
    "birthday-no-year-names-only-named": _birthdays,
    "pending-order": _pending_order,
}


async def _run() -> list[dict[str, Any]]:
    out = []
    for name, case in CASES.items():
        try:
            failures = await case()
        except Exception as exc:  # noqa: BLE001 - a case that raises fails, it never stops the suite
            failures = [f"raised {type(exc).__name__}"]
        out.append({"id": f"{PART}:{name}", "passed": not failures, "failures": failures})
    return out


async def cases() -> list[dict[str, Any]]:
    return await _run()


async def control() -> dict[str, Any]:
    """The taint check off: an e-mailed UPI ID is taken as the payee."""
    today_tools.TAINT_REFUSAL = False
    try:
        got = await _run()
    finally:
        today_tools.TAINT_REFUSAL = True
    failed = [r["id"] for r in got if not r["passed"]]
    return {"name": "taint_check_off", "suite_failed": bool(failed), "failed_cases": failed}
