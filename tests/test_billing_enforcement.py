# tests/test_billing_enforcement.py — slice 7b: the monthly limit is checked BEFORE every paid model
# call (chat, stream, tool rounds, approval narration, the brief's AI lines); free and unpriced
# brains are never blocked; metering never makes a reply fail.
from __future__ import annotations

import logging

import anyio
import pytest
from billing_fakes import (
    NOW,
    UID,
    BrokenDocs,
    DripStream,
    PricedMock,
    billing,
    put_raw,
    registry,
)
from brief_fakes import OWNER_UID, BriefGoogle, SlowDocs, connector, mail, ms, timed

from jarvis.billing import Billing, BudgetPatch, BudgetReached, BudgetUnavailable
from jarvis.brief.models import SettingsPatch
from jarvis.brief.service import BriefService
from jarvis.brief.store import BriefStore
from jarvis.config import Settings
from jarvis.core.brain import Brain
from jarvis.core.models import ChatRequest
from jarvis.llm.base import ToolCall
from jarvis.llm.brains import BrainRegistry
from jarvis.llm.pricing import is_paid
from jarvis.memory.inmemory import InMemorySessionStore
from jarvis.storage.docs import MemoryDocs
from jarvis.tools import Gateway
from jarvis.tools.audit import AuditLog
from jarvis.tools.builtin import InMemoryWorld


def _brain(
    settings: Settings,
    gateway: Gateway | None,
    *,
    paid: PricedMock | None = None,
    free: PricedMock | None = None,
    docs: MemoryDocs | None = None,
) -> tuple[Brain, Billing, PricedMock, PricedMock, InMemorySessionStore]:
    paid = paid or PricedMock()
    free = free or PricedMock()
    reg = registry(paid, free)
    bill = billing(reg, docs=docs)
    store = InMemorySessionStore(ttl_s=3600)
    brain = Brain(brains=reg, store=store, settings=settings, gateway=gateway, billing=bill)
    return brain, bill, paid, free, store


async def _limit(b: Billing, inr: int, *, spent_inr: float = 0.0) -> None:
    await b.budgets.update(UID, BudgetPatch(monthly_limit_inr=inr))
    if spent_inr:
        await b.meter.add(
            UID, brain_id="anthropic", cost_usd=spent_inr / 95.24, cost_inr=spent_inr, now=NOW
        )


def _req(text: str = "hello", **kw: object) -> ChatRequest:
    return ChatRequest(message=text, user_id=UID, **kw)  # type: ignore[arg-type]


# ---- pricing ------------------------------------------------------------------------------------


def test_only_models_with_a_price_above_zero_cost_money() -> None:
    assert is_paid("claude-sonnet-5-5") and is_paid("claude-haiku-5-5")
    assert not is_paid("gemini-3.8-flash")  # priced at ₹0 in the table
    assert not is_paid("mock")
    assert not is_paid("llama-local-70b")  # not in the table: cost unknown, never blocked


# ---- chat ---------------------------------------------------------------------------------------


async def test_at_the_limit_a_paid_brain_is_not_called(
    settings: Settings, gateway: Gateway
) -> None:
    brain, bill, paid, _, store = _brain(settings, gateway)
    await _limit(bill, 10, spent_inr=10.0)
    with pytest.raises(BudgetReached) as ei:
        await brain.chat(_req())
    assert paid.calls == []
    detail = str(ei.value)
    assert detail == (
        "This month's limit of ₹10 is used up (₹10 spent). Raise it in Vitals, or switch to the "
        "free brain."
    )
    assert "$" not in detail
    assert await store.list_for_user(UID) == []  # no empty conversation left behind


async def test_over_the_limit_too(settings: Settings, gateway: Gateway) -> None:
    brain, bill, paid, _, _ = _brain(settings, gateway)
    await _limit(bill, 10, spent_inr=12.4)
    with pytest.raises(BudgetReached, match=r"₹12\.40 spent"):
        await brain.chat(_req())
    assert paid.calls == []


async def test_under_the_limit_it_answers_and_meters(settings: Settings, gateway: Gateway) -> None:
    brain, bill, paid, _, _ = _brain(settings, gateway, paid=PricedMock(per_call=0.01))
    await _limit(bill, 10, spent_inr=9.99)
    r = await brain.chat(_req())
    assert len(paid.calls) == 1 and r.cost_usd == 0.01
    assert r.cost_inr == pytest.approx(0.9524)
    assert r.total_cost_usd == pytest.approx(0.01) and r.total_cost_inr == pytest.approx(0.9524)
    u = await bill.meter.get(UID, "2026-11")
    assert u.calls == 2 and u.inr_total == pytest.approx(9.99 + 0.9524)
    assert u.by_brain["anthropic"] == pytest.approx(9.99 / 95.24 + 0.01)
    # one reply may overshoot by its own cost (the check is before the call): the next is refused
    with pytest.raises(BudgetReached):
        await brain.chat(_req(session_id=r.session_id))
    assert len(paid.calls) == 1


async def test_an_existing_conversation_keeps_no_unanswered_turn(
    settings: Settings, gateway: Gateway
) -> None:
    brain, bill, _, _, store = _brain(settings, gateway, paid=PricedMock(per_call=0.2))
    first = await brain.chat(_req())
    await _limit(bill, 10, spent_inr=10.0)
    with pytest.raises(BudgetReached):
        await brain.chat(_req("again", session_id=first.session_id))
    s = await store.get(first.session_id)
    assert s is not None and len(s.turns) == 2  # the refused message was not stored


@pytest.mark.parametrize("brain_id", ["gemini", "custom"])
async def test_free_and_unpriced_brains_are_never_blocked(
    settings: Settings, gateway: Gateway, brain_id: str
) -> None:
    brain, bill, paid, _, _ = _brain(settings, gateway)
    await _limit(bill, 1, spent_inr=500.0)
    r = await brain.chat(_req(brain=brain_id))
    assert r.brain == brain_id and r.reply and paid.calls == []
    assert (await bill.meter.get(UID, "2026-11")).calls == 1  # only the seeded spend


async def test_no_limit_set_means_no_jarvis_limit(settings: Settings, gateway: Gateway) -> None:
    brain, bill, paid, _, _ = _brain(settings, gateway, paid=PricedMock(per_call=5.0))
    for _ in range(3):
        await brain.chat(_req())
    assert len(paid.calls) == 3
    assert (await bill.meter.get(UID, "2026-11")).inr_total == pytest.approx(3 * 5 * 95.24)


async def test_the_limit_is_per_owner(settings: Settings, gateway: Gateway) -> None:
    brain, bill, paid, _, _ = _brain(settings, gateway)
    await _limit(bill, 10, spent_inr=10.0)
    r = await brain.chat(ChatRequest(message="hi", user_id="u_someone_else"))
    assert r.reply and len(paid.calls) == 1


async def test_a_limit_check_that_cannot_read_fails_closed(
    settings: Settings, gateway: Gateway
) -> None:
    docs = BrokenDocs()
    brain, bill, paid, free, _ = _brain(settings, gateway, docs=docs)
    docs.fail_reads = True
    with pytest.raises(BudgetUnavailable) as ei:
        await brain.chat(_req())
    assert paid.calls == [] and "₹" not in str(ei.value) and "$" not in str(ei.value)
    # a free brain does not need the check at all
    docs.fail_reads = False
    r = await brain.chat(_req(brain="gemini"))
    assert r.reply and len(free.calls) == 1


@pytest.mark.parametrize("value", ["500", float("nan"), True, 10**12, {"x": 1}, "missing"])
async def test_a_corrupted_stored_limit_fails_closed_not_open(
    settings: Settings, gateway: Gateway, value: object
) -> None:
    """A limit JARVIS can't read is not "no limit": no paid call until the owner sets it again."""
    docs = MemoryDocs()
    brain, _, paid, free, store = _brain(settings, gateway, docs=docs)
    await put_raw(
        docs,
        f"jarvis_budget/{UID}",
        {"user_id": UID} if value == "missing" else {"monthly_limit_inr": value},
    )
    with pytest.raises(BudgetUnavailable):
        await brain.chat(_req())
    with pytest.raises(BudgetUnavailable):
        await brain.check_budget(_req())  # the stream route's 402/503 before it says 200
    assert paid.calls == [] and await store.list_for_user(UID) == []
    r = await brain.chat(_req(brain="gemini"))  # the free brain still answers
    assert r.reply and len(free.calls) == 1


@pytest.mark.parametrize("bad", ["900", float("nan"), -1.0, None])
async def test_a_corrupted_month_total_fails_closed_not_open(
    settings: Settings, gateway: Gateway, bad: object
) -> None:
    """A month total JARVIS can't read is not ₹0 spent."""
    docs = MemoryDocs()
    brain, bill, paid, _, _ = _brain(settings, gateway, docs=docs)
    await _limit(bill, 10)
    await put_raw(docs, f"jarvis_usage/{UID}_2026-11", {"inr_total": bad, "calls": 40})
    with pytest.raises(BudgetUnavailable):
        await brain.chat(_req())
    assert paid.calls == []


async def test_a_failed_meter_write_never_fails_the_reply(
    settings: Settings, gateway: Gateway, caplog: pytest.LogCaptureFixture
) -> None:
    docs = BrokenDocs(fail_tx=True)
    brain, _, paid, _, _ = _brain(settings, gateway, paid=PricedMock(per_call=0.01), docs=docs)
    with caplog.at_level(logging.ERROR):
        r = await brain.chat(_req("still answers"))
    assert "still answers" in r.reply and r.cost_inr == pytest.approx(0.9524)
    assert docs.tx_calls >= 1  # it did try
    assert any("METER" in rec.getMessage() for rec in caplog.records)


# ---- stream -------------------------------------------------------------------------------------


async def test_stream_at_the_limit_yields_nothing_and_calls_nothing(
    settings: Settings, gateway: Gateway
) -> None:
    brain, bill, paid, _, _ = _brain(settings, gateway)
    await _limit(bill, 10, spent_inr=10.0)
    with pytest.raises(BudgetReached):
        await brain.check_budget(_req())  # the route asks first, so it can answer 402
    got: list[str] = []
    with pytest.raises(BudgetReached):
        async for d in brain.chat_stream(_req()):
            got.append(d)
    assert got == [] and paid.calls == []


async def test_stream_under_the_limit_is_metered_with_an_estimate(
    settings: Settings, gateway: Gateway
) -> None:
    brain, bill, paid, _, store = _brain(settings, gateway)
    await _limit(bill, 10)
    await brain.check_budget(_req())
    text = "".join([d async for d in brain.chat_stream(_req("stream please"))])
    assert "stream please" in text and len(paid.calls) == 1
    u = await bill.meter.get(UID, "2026-11")
    assert u.calls == 1 and u.inr_total > 0  # the stream has no usage: tokens are estimated
    (summary,) = await store.list_for_user(UID)
    assert summary.total_cost_usd > 0


async def test_a_stream_cut_short_is_still_metered(settings: Settings, gateway: Gateway) -> None:
    brain, bill, _, _, _ = _brain(settings, gateway)
    gen = brain.chat_stream(_req("a long answer please"))
    first = await gen.__anext__()  # the owner reads one chunk, then goes away
    assert first
    await gen.aclose()
    u = await bill.meter.get(UID, "2026-11")
    assert u.calls == 1 and u.inr_total > 0


async def test_a_stream_cut_off_while_the_model_is_still_writing_is_metered(
    settings: Settings, gateway: Gateway
) -> None:
    """How a real disconnect looks: uvicorn speaks ASGI 2.3, so Starlette cancels the response
    task through an anyio cancel scope while it waits for the model's next chunk. The meter write
    in the stream's cleanup must not be cancelled with it (the provider bills what it wrote)."""
    docs = SlowDocs()  # database calls really wait, like Firestore
    brain, bill, paid, _, _ = _brain(settings, gateway, paid=DripStream(), docs=docs)
    got: list[str] = []
    first = anyio.Event()
    async with anyio.create_task_group() as tg:

        async def read() -> None:
            async for d in brain.chat_stream(_req("a long answer please " * 10)):
                got.append(d)
                first.set()

        async def client_goes_away() -> None:
            await first.wait()
            await anyio.sleep(0.005)  # the reader is now waiting for the next chunk
            tg.cancel_scope.cancel()

        tg.start_soon(read)
        tg.start_soon(client_goes_away)
    assert len(got) == 1 and len(paid.calls) == 1
    u = await bill.meter.get(UID, "2026-11")
    assert u.calls == 1 and u.inr_total > 0


# ---- tool rounds --------------------------------------------------------------------------------


async def test_every_tool_round_is_checked_before_its_call(
    settings: Settings, gateway: Gateway
) -> None:
    paid = PricedMock(per_call=0.02)  # ₹1.90 a call
    brain, bill, _, _, _ = _brain(settings, gateway, paid=paid)
    await _limit(bill, 3)
    paid.script_tool_calls([ToolCall(id="t1", name="list_tasks", arguments={})])
    paid.script_tool_calls([ToolCall(id="t2", name="list_tasks", arguments={})])
    paid.script("done")
    with pytest.raises(BudgetReached):
        await brain.chat(_req("loop"))
    assert len(paid.calls) == 2  # ₹0 → call, ₹1.90 → call, ₹3.81 ≥ ₹3 → no third call
    assert (await bill.meter.get(UID, "2026-11")).calls == 2


# ---- approval narration -------------------------------------------------------------------------


async def test_narration_at_the_limit_uses_the_plain_reply_and_the_action_stands(
    settings: Settings, gateway: Gateway, world: InMemoryWorld
) -> None:
    paid = PricedMock(per_call=0.01)
    brain, bill, _, _, _ = _brain(settings, gateway, paid=paid)
    paid.script_tool_calls(
        [ToolCall(id="s1", name="send_message", arguments={"to": "p@example.com", "body": "3pm"})],
        "Awaiting your approval, Sir.",
    )
    r = await brain.chat(_req("tell P"))
    pending = r.pending_approvals[0]
    await _limit(bill, 1, spent_inr=5.0)
    calls = len(paid.calls)
    done = await brain.approve(pending.id, session_id=r.session_id, user_id=UID)
    assert world.sent == [{"to": "p@example.com", "body": "3pm"}]  # the owner's decision ran
    assert done.reply.startswith("Done, Sir") and len(paid.calls) == calls  # no narration call
    assert done.cost_usd == 0.0 and done.cost_inr == 0.0


async def test_narration_under_the_limit_is_metered(
    settings: Settings, gateway: Gateway, world: InMemoryWorld
) -> None:
    paid = PricedMock(per_call=0.01)
    brain, bill, _, _, _ = _brain(settings, gateway, paid=paid)
    paid.script_tool_calls(
        [ToolCall(id="s2", name="send_message", arguments={"to": "p@example.com", "body": "x"})],
        "Waiting.",
    )
    r = await brain.chat(_req("send"))
    paid.script("Sent, Sir.")
    done = await brain.approve(r.pending_approvals[0].id, session_id=r.session_id, user_id=UID)
    assert done.reply == "Sent, Sir." and done.cost_inr == pytest.approx(0.9524)
    assert (await bill.meter.get(UID, "2026-11")).calls == 3


# ---- the brief's AI lines -----------------------------------------------------------------------


async def _brief_rig(paid: PricedMock, bill: Billing | None, reg: BrainRegistry) -> BriefService:
    fake = BriefGoogle(
        events=[timed("e1", "Standup", "2026-11-15T09:30", "2026-11-15T10:00")],
        messages=[
            mail("m1", "Priya <p@x.com>", "Budget", internal_ms=ms("2026-11-15T06:40:00+05:30"))
        ],
    )
    svc = BriefService(
        store=BriefStore(MemoryDocs()),
        google=await connector(fake),
        brains=reg,
        approvals=None,
        audit=AuditLog(),
        owners=[OWNER_UID],
        default_tz="Asia/Kolkata",
        clock=lambda: NOW,
        billing=bill,
    )
    await svc.update_settings(OWNER_UID, SettingsPatch(ai_summary=True, confirm_spend=True))
    return svc


async def test_the_brief_skips_its_ai_lines_at_the_limit() -> None:
    paid = PricedMock(per_call=0.002)
    reg = registry(paid)
    bill = billing(reg)
    await bill.budgets.update(OWNER_UID, BudgetPatch(monthly_limit_inr=5))
    await bill.meter.add(OWNER_UID, brain_id="anthropic", cost_usd=0.06, cost_inr=5.0, now=NOW)
    svc = await _brief_rig(paid, bill, reg)
    audit: AuditLog = svc._audit  # type: ignore[assignment]
    view = await svc.generate(OWNER_UID, trigger="manual", force=False)
    assert paid.calls == []
    assert view.brief is not None and view.brief.ai is None
    note = view.brief.ai_note or ""
    assert "limit of ₹5 is used up" in note and "Vitals" in note and "$" not in note
    assert view.brief.ai_calls_today == 0  # nothing was called, nothing counted
    assert not [e for e in audit._entries if e.tool == "morning_brief.summarize"]
    assert view.brief.data is not None  # the facts are all there


async def test_the_brief_ai_call_is_metered() -> None:
    paid = PricedMock(per_call=0.002)
    reg = registry(paid)
    bill = billing(reg)
    svc = await _brief_rig(paid, bill, reg)
    view = await svc.generate(OWNER_UID, trigger="manual", force=False)
    assert len(paid.calls) == 1 and view.brief is not None and view.brief.ai is not None
    u = await bill.meter.get(OWNER_UID, "2026-11")
    assert u.calls == 1 and u.by_brain == pytest.approx({"anthropic": 0.002})


async def test_the_brief_with_an_unreadable_limit_makes_no_ai_call() -> None:
    paid = PricedMock(per_call=0.002)
    reg = registry(paid)
    docs = BrokenDocs()
    bill = billing(reg, docs=docs)
    svc = await _brief_rig(paid, bill, reg)  # the brief keeps its own store: only billing fails
    docs.fail_reads = True
    view = await svc.generate(OWNER_UID, trigger="manual", force=False)
    assert paid.calls == [] and view.brief is not None and view.brief.ai is None
    assert "limit" in (view.brief.ai_note or "") and view.brief.ai_calls_today == 0


async def test_the_app_wires_one_billing_into_chat_and_the_brief(settings: Settings) -> None:
    from jarvis.api import create_app
    from jarvis.llm.mock_provider import MockProvider

    app = create_app(settings, provider=MockProvider(), store=InMemorySessionStore())
    async with app.router.lifespan_context(app):
        b = app.state.billing
        assert app.state.brain.billing is b and app.state.brief._billing is b
        assert b.fx.peek().inr_per_usd == 95.24
