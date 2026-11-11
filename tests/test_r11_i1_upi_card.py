# tests/test_r11_i1_upi_card.py -- R11 I1, the `UpiCard` reply-card kind (INTEGRATION-A 3.3;
# plan D7 "shown once in the card and the bill row"): when he approves `bill_pay_prepare` in the
# console (the chat's Approvals or the Today tab, both through /v1/approvals), the approved run
# spends the one-time grant and the reply carries ONE card with the upi://pay link, its QR and
# code's own words. The tool's result (what the model and the conversation see) still names no
# link; nothing stores, logs or audits the link or the QR; Telegram never shows the card (R3 is
# never approvable there, and its formatter knows no such card); the approval answer is no-store.
from __future__ import annotations

import json
import logging

import pytest
from pydantic import ValidationError
from r11_fakes import UID
from r11_fakes_a import FAKE_UPI, Rig, every_text, gateway_rig, today_ctx

from jarvis.helpers.today import part as today_part
from jarvis.helpers.today import tools as today_tools
from jarvis.helpers.today.bills import BillsService
from jarvis.llm.base import ToolCall
from jarvis.storage.docs import MemoryDocs
from jarvis.telegram.format import card_lines
from jarvis.tools.gateway import GatewayOutcome
from jarvis.tools.reply_cards import AnyCard, UpiCard, collecting_cards
from jarvis.tools.taint import context_trust

LINK = "upi://pay?pa=test@okfake&pn=Power%20Co&am=1240.00&cu=INR&tn=Electricity%20Nov"
QR = "data:image/svg+xml;charset=utf-8,%3Csvg%3E%3C/svg%3E"


async def _rig() -> tuple[Rig, BillsService, MemoryDocs]:
    c, _, docs, _ = today_ctx()
    part = today_part.build(c)
    svc = part.services["bills"]
    await svc.add(UID, label="Electricity", payee="Power Co", upi=FAKE_UPI, amount="1240", day=13)
    return gateway_rig(part), svc, docs


async def _propose_and_approve(rig: Rig, cards: list[AnyCard] | None):  # type: ignore[no-untyped-def]
    call = ToolCall(id="t1", name="bill_pay_prepare", arguments={"bill": "Electricity"})
    with context_trust(untrusted=False, owner_text="pay the electricity bill"):
        res = await rig.gateway.execute(call, scope=rig.scope)
    assert res.outcome is GatewayOutcome.AWAITING_CONFIRMATION
    again = ToolCall(id="t2", name="bill_pay_prepare", arguments=res.pending.arguments)
    if cards is None:
        return await rig.gateway.execute(again, confirmation_id=res.pending.id, scope=rig.scope)
    with collecting_cards(cards):
        return await rig.gateway.execute(again, confirmation_id=res.pending.id, scope=rig.scope)


def test_the_card_takes_only_a_upi_pay_link_and_an_svg_qr() -> None:
    card = UpiCard(link=LINK, qr=QR, words="₹1,240.00 to “Power Co” (test@okfake)")
    assert card.kind == "upi"
    for bad in (
        "https://evil.example/pay",
        "javascript:alert(1)",
        "upi://pay?pa=x y",
        "upi://collect?pa=a@b",
    ):
        with pytest.raises(ValidationError):
            UpiCard(link=bad, qr=QR, words="x")
    with pytest.raises(ValidationError):
        UpiCard(link=LINK, qr="data:image/png;base64,AAAA", words="x")
    with pytest.raises(ValidationError):
        UpiCard(link=LINK, qr=QR, words="x" * 301)


async def test_approved_in_the_console_the_reply_shows_the_payment_once(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.DEBUG)
    rig, svc, docs = await _rig()
    cards: list[AnyCard] = []
    done = await _propose_and_approve(rig, cards)
    assert done.outcome is GatewayOutcome.EXECUTED
    (card,) = cards
    assert isinstance(card, UpiCard) and card.link.startswith("upi://pay?pa=test@okfake")
    assert card.qr.startswith("data:image/svg+xml") and "JARVIS never pays" in card.words
    said = json.dumps(done.result)
    assert "upi://" not in said and "svg" not in said and "below" in said
    (bill,) = (await svc.book(UID)).bills
    assert await svc.payment(UID, bill.id) is None  # the grant was spent by the card: once
    assert "upi://" not in every_text(docs) and "upi://" not in caplog.text
    assert all("upi://" not in e.detail for e in (await rig.audit.tail(30)).entries)


async def test_with_no_reply_to_show_it_on_the_grant_waits_for_the_today_tab() -> None:
    rig, svc, _ = await _rig()
    done = await _propose_and_approve(rig, None)
    assert done.outcome is GatewayOutcome.EXECUTED and "Helpers" in json.dumps(done.result)
    (bill,) = (await svc.book(UID)).bills
    shown = await svc.payment(UID, bill.id)
    assert shown is not None and shown.link.startswith("upi://pay?")


def test_telegram_never_draws_a_upi_card() -> None:
    assert card_lines([UpiCard(link=LINK, qr=QR, words="x")]) == []


def test_the_result_words_name_where_the_payment_is() -> None:
    assert "below" in today_tools.READY_BELOW and "never pays" in today_tools.READY_BELOW


async def test_the_approval_answer_is_never_cached(settings, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    from httpx import ASGITransport, AsyncClient

    from jarvis.api import create_app
    from jarvis.core.models import ChatResponse
    from jarvis.llm.mock_provider import MockProvider
    from jarvis.memory.inmemory import InMemorySessionStore

    app = create_app(settings, provider=MockProvider(), store=InMemorySessionStore())
    async with app.router.lifespan_context(app):

        async def approve(approval_id: str, **kw: object) -> ChatResponse:
            return ChatResponse.model_validate(
                {
                    "session_id": "s1",
                    "reply": "Done, Sir.",
                    "trace_id": "t",
                    "model": "mock",
                    "usage": {"input_tokens": 0, "output_tokens": 0},
                    "cost_usd": 0.0,
                    "latency_ms": 1,
                    "turn_count": 1,
                    "cards": [{"kind": "upi", "link": LINK, "qr": QR, "words": "x"}],
                }
            )

        monkeypatch.setattr(app.state.brain, "approve", approve)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            r = await c.post(
                "/v1/approvals/a1/approve",
                json={"session_id": "s1"},
                headers={"X-Requested-With": "JARVIS"},
            )
        assert r.status_code == 200 and r.headers["cache-control"] == "no-store"
        assert r.json()["cards"][0]["kind"] == "upi"


# ---- integrated review M3: never spend the grant and then show nothing --------------------------
async def test_a_card_that_fails_its_check_spends_nothing_and_says_prepare_again(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    import jarvis.helpers.today.bills as bills_mod
    from jarvis.tools.reply_cards import UPI_QR_MAX

    caplog.set_level(logging.DEBUG)
    rig, svc, docs = await _rig()
    monkeypatch.setattr(bills_mod, "qr_data_uri", lambda link: QR + "x" * UPI_QR_MAX)
    cards: list[AnyCard] = []
    done = await _propose_and_approve(rig, cards)
    assert done.outcome is GatewayOutcome.EXECUTED and cards == []
    said = json.dumps(done.result, ensure_ascii=False)
    assert today_tools.SHOW_FAILED in said and "Show payment" not in said and "below" not in said
    (bill,) = (await svc.book(UID)).bills
    assert bill.id in (await svc.book(UID)).ready  # nothing was spent
    assert "upi://" not in every_text(docs) and "upi://" not in caplog.text and "upi://" not in said


async def test_nothing_to_show_says_prepare_again_never_points_at_the_today_tab(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rig, svc, _ = await _rig()

    async def nothing(uid: str, bill_id: str, **kw: object) -> None:
        return None

    monkeypatch.setattr(svc, "payment", nothing)
    cards: list[AnyCard] = []
    done = await _propose_and_approve(rig, cards)
    said = json.dumps(done.result, ensure_ascii=False)
    assert done.outcome is GatewayOutcome.EXECUTED and cards == []
    assert today_tools.SHOW_FAILED in said and "Helpers" not in said and "Show payment" not in said


async def test_a_payee_changed_after_the_approval_spends_nothing() -> None:
    rig, svc, _ = await _rig()
    done = await _propose_and_approve(rig, None)  # no reply: the grant waits
    assert done.outcome is GatewayOutcome.EXECUTED
    (bill,) = (await svc.book(UID)).bills
    await svc.set_payee(UID, bill.id, upi="other@okfake", payee="Someone Else")
    assert await svc.payment(UID, bill.id) is None
    assert bill.id in (await svc.book(UID)).ready  # a payee he didn't see is never shown or spent
