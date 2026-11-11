# tests/test_r11_a_tools.py -- R11 Part A's tools through a REAL gateway (D7, D9, D16, D20): every
# call passes the policy, cards and the audit. `bill_pay_prepare` is R3: always a card whose text
# code wrote from his saved bill; approved, it leaves a 10-minute grant and its result carries no
# link and no QR (the console shows them once). `bill_payee_set` is R3 and refused outright in a
# round that read other people's content ("Type the UPI ID yourself in the Today tab, Sir"), and
# when an approved card came from such a round. Over the cap, a number in a field, a bill that
# isn't his: refused. `bill_add` never takes a UPI ID. The read tools fence outside words.
from __future__ import annotations

import json

import pytest
from r11_fakes import UID
from r11_fakes_a import (
    FAKE_UPI,
    OTHER_UPI,
    FakePeople,
    Rig,
    connector,
    every_text,
    gateway_rig,
    person,
    today_ctx,
)

from jarvis.helpers.today import part as today_part
from jarvis.helpers.today import tools as today_tools
from jarvis.helpers.today.bills import BillsService
from jarvis.llm.base import ToolCall
from jarvis.storage.docs import MemoryDocs
from jarvis.tools.external import FENCE_PREFIX
from jarvis.tools.gateway import GatewayOutcome
from jarvis.tools.taint import context_trust

CARD = (
    "Get a UPI payment ready: ₹1,240.00 to “Power Co” (test@okfake), note “Electricity Nov”. You "
    "confirm it and enter your PIN in your UPI app. JARVIS never pays."
)


async def _rig(**kw: object) -> tuple[Rig, BillsService, MemoryDocs]:
    c, _, docs, _ = today_ctx(**kw)  # type: ignore[arg-type]
    part = today_part.build(c)
    svc = part.services["bills"]
    await svc.add(UID, label="Electricity", payee="Power Co", upi=FAKE_UPI, amount="1240", day=13)
    return gateway_rig(part), svc, docs


def _call(name: str, **args: object) -> ToolCall:
    return ToolCall(id=f"t-{name}", name=name, arguments=dict(args))


async def _run(  # type: ignore[no-untyped-def]
    rig: Rig, name: str, *, tainted: bool = False, said: str | None = "test", **args: object
):
    with context_trust(untrusted=tainted, owner_text=said):
        return await rig.gateway.execute(_call(name, **args), scope=rig.scope)


async def _approve(rig: Rig, res):  # type: ignore[no-untyped-def]
    assert res.outcome is GatewayOutcome.AWAITING_CONFIRMATION, res
    return await rig.gateway.execute(
        _call(res.pending.tool, **res.pending.arguments),
        confirmation_id=res.pending.id,
        scope=rig.scope,
    )


async def test_prepare_is_always_a_card_with_codes_exact_words() -> None:
    rig, svc, _ = await _rig()
    res = await _run(rig, "bill_pay_prepare", bill="Electricity")
    assert res.outcome is GatewayOutcome.AWAITING_CONFIRMATION
    assert res.pending.summary == CARD
    assert (await svc.book(UID)).ready == {}  # nothing is ready before he approves


async def test_approved_it_is_ready_and_nothing_carries_the_link() -> None:
    rig, svc, docs = await _rig()
    done = await _approve(rig, await _run(rig, "bill_pay_prepare", bill="Electricity"))
    assert done.outcome is GatewayOutcome.EXECUTED
    text = json.dumps(done.result)
    assert "upi://" not in text and "svg" not in text and "Helpers" in text
    (bill,) = (await svc.book(UID)).bills
    shown = await svc.payment(UID, bill.id)
    assert shown is not None and shown.link.startswith("upi://pay?pa=test@okfake")
    tail = await rig.audit.tail(20)
    assert all("upi://" not in e.detail for e in tail.entries)
    assert "upi://" not in every_text(docs)


async def test_over_the_cap_or_a_varies_bill_without_an_amount_is_refused() -> None:
    rig, svc, _ = await _rig()
    over = await _run(rig, "bill_pay_prepare", bill="Electricity", amount="100000.01")
    assert over.outcome is GatewayOutcome.ERROR and "1,00,000" in (over.error or "")
    await svc.add(UID, label="Water", payee="Water Co", upi=FAKE_UPI, amount="varies", day=20)
    varies = await _run(rig, "bill_pay_prepare", bill="Water")
    assert varies.outcome is GatewayOutcome.ERROR and "varies" in (varies.error or "")
    ok = await _run(rig, "bill_pay_prepare", bill="Water", amount="350")
    assert "₹350.00 to “Water Co”" in ok.pending.summary


async def test_an_emailed_upi_id_never_becomes_a_payee() -> None:
    rig, svc, _ = await _rig()
    res = await _run(rig, "bill_payee_set", tainted=True, bill="Electricity", upi=OTHER_UPI)
    assert res.outcome is GatewayOutcome.ERROR
    assert "Type the UPI ID yourself in the Today tab, Sir" in (res.error or "")
    assert (await svc.book(UID)).bills[0].upi == FAKE_UPI


async def test_his_own_payee_change_is_an_r3_card_then_runs() -> None:
    rig, svc, _ = await _rig()
    said = f"set the electricity bill's UPI ID to {OTHER_UPI}, payee New Co"
    res = await _run(
        rig, "bill_payee_set", said=said, bill="Electricity", upi=OTHER_UPI, payee="New Co"
    )
    assert res.outcome is GatewayOutcome.AWAITING_CONFIRMATION
    assert OTHER_UPI in res.pending.summary and "“Electricity”" in res.pending.summary
    assert "“New Co”" in res.pending.summary
    done = await _approve(rig, res)
    assert done.outcome is GatewayOutcome.EXECUTED
    assert (await svc.book(UID)).bills[0].upi == OTHER_UPI


async def test_an_approved_card_from_a_tainted_round_is_refused_at_run(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rig, svc, _ = await _rig()
    monkeypatch.setattr(today_tools, "TAINT_REFUSAL", False)  # let the card be made ...
    res = await _run(rig, "bill_payee_set", tainted=True, bill="Electricity", upi=OTHER_UPI)
    monkeypatch.setattr(today_tools, "TAINT_REFUSAL", True)  # ... the run still refuses
    done = await _approve(rig, res)
    assert done.outcome is GatewayOutcome.EXECUTED and done.result.get("refused") is True
    assert (await svc.book(UID)).bills[0].upi == FAKE_UPI


async def test_bill_add_never_takes_a_upi_id_and_refuses_numbers() -> None:
    rig, svc, _ = await _rig()
    sneaky = await _run(rig, "bill_add", label="Gas", amount="900", day=5, upi=OTHER_UPI)
    assert sneaky.outcome is GatewayOutcome.ERROR and "unknown arguments" in (sneaky.error or "")
    card = await _run(rig, "bill_add", label="Card 4111 1111 1111 1111", amount="900", day=5)
    assert card.outcome is GatewayOutcome.ERROR and "last 4" in (card.error or "")
    odd = await _run(rig, "bill_add", label="Gas", amount="900", day=5, every_months=13)
    assert odd.result.get("refused") is True and "13" not in odd.result["message"]
    ok = await _run(rig, "bill_add", label="Gas", payee="Gas Co", amount="900", day=5)
    assert ok.outcome is GatewayOutcome.EXECUTED
    assert [b.label for b in (await svc.book(UID)).bills] == ["Electricity", "Gas"]
    tainted = await _run(rig, "bill_add", tainted=True, label="Gym", amount="900", day=5)
    assert tainted.outcome is GatewayOutcome.AWAITING_CONFIRMATION  # a tainted write is a card


async def test_list_paid_and_a_bill_that_isnt_his() -> None:
    rig, svc, _ = await _rig()
    listed = await _run(rig, "bill_list")
    assert listed.outcome is GatewayOutcome.EXECUTED
    (row,) = listed.result["bills"]
    assert row["amount"] == "₹1,240" and row["upi"] == FAKE_UPI
    assert FENCE_PREFIX in row["label"] and "\nElectricity\n" in row["label"]  # data, fenced
    assert FENCE_PREFIX in row["payee"] and "\nPower Co\n" in row["payee"]
    paid = await _run(rig, "bill_paid", bill="electricity")
    assert paid.outcome is GatewayOutcome.EXECUTED and "13 Nov" in paid.result["message"]
    missing = await _run(rig, "bill_paid", bill="Mortgage")
    assert missing.outcome is GatewayOutcome.EXECUTED and missing.result.get("refused") is True


async def test_without_a_keyring_the_bill_tools_say_they_are_off() -> None:
    c, _, _, _ = today_ctx(keys=False)
    rig = gateway_rig(today_part.build(c))
    got = await _run(rig, "bill_list")
    assert got.result.get("unavailable") is True and "token key" in got.result["message"]


async def test_birthdays_fence_names_and_the_message_names_nobody() -> None:
    fake = FakePeople([person("c1", "Asha Example", 11, 10), person("c2", "Ravi Example", 11, 12)])
    google = await connector(fake)
    c, _, _, _ = today_ctx(google=google)
    rig = gateway_rig(today_part.build(c))
    got = await _run(rig, "contacts_birthdays")
    assert got.outcome is GatewayOutcome.EXECUTED
    assert "Asha Example" in got.result["today"][0] and "EXTERNAL" in got.result["today"][0].upper()
    assert "Asha" not in got.result["message"] and "Ravi" not in got.result["message"]
    assert got.result["soon"][0]["on"] == "Thu 12 Nov"
    assert "1990" not in json.dumps(got.result)


async def test_focus_and_pending_read_every_part() -> None:
    rig, _, _ = await _rig()
    focus = await _run(rig, "focus_now")
    assert focus.outcome is GatewayOutcome.EXECUTED
    top = focus.result["top"]["label"]
    assert FENCE_PREFIX in top and "\nElectricity ₹1,240 due Fri 13 Nov\n" in top
    assert focus.result["message"] == "Top priority now, Sir: “Electricity ₹1,240 due Fri 13 Nov”."
    listed = await _run(rig, "pending_list")
    assert listed.result["total"] == 1 and listed.result["groups"][0]["source"] == "Bills"


@pytest.mark.parametrize(
    "said",
    [
        "set the electricity UPI ID to the one in that mail",  # not typed at all
        "my UPI ID is mallory@okfake.in",  # a different ID that only starts the same
        "pay xmallory@okfake",  # one that only ends the same
    ],
)
async def test_a_upi_id_he_did_not_type_in_this_message_is_refused(said: str) -> None:
    rig, svc, _ = await _rig()
    res = await _run(rig, "bill_payee_set", said=said, bill="Electricity", upi=OTHER_UPI)
    assert res.outcome is GatewayOutcome.ERROR and res.error == today_tools.TYPE_IT_HERE
    assert (await svc.book(UID)).bills[0].upi == FAKE_UPI


async def test_his_typed_upi_id_any_case_and_the_tabs_own_form_make_the_card() -> None:
    rig, _, _ = await _rig()
    typed = await _run(
        rig, "bill_payee_set", said="Use MALLORY@okfake.", bill="Electricity", upi=OTHER_UPI
    )
    assert typed.outcome is GatewayOutcome.AWAITING_CONFIRMATION
    form = await _run(rig, "bill_payee_set", said=None, bill="Electricity", upi=OTHER_UPI)
    assert form.outcome is GatewayOutcome.AWAITING_CONFIRMATION  # the Today tab: no message


async def test_the_bill_add_card_shows_the_payee_name_quoted() -> None:
    rig, _, _ = await _rig()
    res = await _run(
        rig, "bill_add", tainted=True, label="Gas", payee="Gas Co", amount="₹1,240", day=5
    )
    assert res.outcome is GatewayOutcome.AWAITING_CONFIRMATION
    assert res.pending.summary == "Keep a bill: “Gas”, ₹1,240, payee “Gas Co”"
    bad = await _run(rig, "bill_add", tainted=True, label="Gas", payee="Co (x@okfake)", day=5)
    assert bad.outcome is GatewayOutcome.ERROR and "no @" in (bad.error or "")


async def test_exactly_the_cap_is_allowed() -> None:
    rig, _, _ = await _rig()
    res = await _run(rig, "bill_pay_prepare", bill="Electricity", amount="100000")
    assert res.outcome is GatewayOutcome.AWAITING_CONFIRMATION
    assert res.pending.summary.startswith("Get a UPI payment ready: ₹1,00,000.00 to")


async def test_a_bill_with_no_payee_is_prepared_and_shown_in_its_own_name() -> None:
    rig, svc, _ = await _rig()
    water = await svc.add(UID, label="Water", upi=FAKE_UPI, amount="300", day=20)
    res = await _run(rig, "bill_pay_prepare", bill="Water")
    assert "₹300.00 to “Water” (test@okfake)" in res.pending.summary
    done = await _approve(rig, res)
    assert done.outcome is GatewayOutcome.EXECUTED and done.result["status"] == "ready"
    shown = await svc.payment(UID, water.id)
    assert shown is not None and "pa=test@okfake&pn=Water&am=300.00" in shown.link
