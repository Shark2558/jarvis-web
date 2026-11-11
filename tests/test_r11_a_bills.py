# tests/test_r11_a_bills.py -- R11 Part A (D7): the bills service on fakes. Add a bill (his own
# entry: the UPI ID only from him), find it by id or by name, "I paid" records the due date, and a
# prepared payment: the card text written by code, the amount within the cap (a "varies" bill needs
# one), the payee only from his saved bill; the link and QR only when the approved grant is spent.
from __future__ import annotations

from datetime import date, timedelta

import pytest
from r11_fakes import NOON_IST, UID, Clock
from r11_fakes_a import FAKE_UPI, every_text, keyring

from jarvis.helpers.today.bills import BillsService, current_due, reminders_due
from jarvis.helpers.today.models import BillRefused, Due
from jarvis.helpers.today.store import BillsOff, BillStore
from jarvis.storage.docs import MemoryDocs

CARD = (
    "Get a UPI payment ready: ₹1,240.00 to Power Co (test@okfake), note 'Electricity Nov'. You "
    "confirm it and enter your PIN in your UPI app. JARVIS never pays."
)


def _svc(keys: bool = True) -> tuple[BillsService, MemoryDocs, Clock]:
    docs, clock = MemoryDocs(), Clock()
    store = BillStore(docs, keyring() if keys else None, prefix="jarvis_")
    return BillsService(store, tz="Asia/Kolkata", now=clock), docs, clock


async def _electricity(svc: BillsService, **over: object) -> str:
    args: dict[str, object] = {
        "label": "Electricity",
        "payee": "Power Co",
        "upi": FAKE_UPI,
        "amount": "1240",
        "day": 13,
    }
    args.update(over)
    bill = await svc.add(UID, **args)  # type: ignore[arg-type]
    return bill.id


async def test_a_bill_is_added_found_by_name_and_listed() -> None:
    svc, docs, _ = _svc()
    bid = await _electricity(svc)
    book = await svc.book(UID)
    (bill,) = book.bills
    assert bill.id == bid and bill.amount == 124000 and bill.upi == FAKE_UPI
    assert bill.due == Due(start=date(2026, 11, 13), every_months=1)  # the next 13th
    assert svc.find(book, "electricity") == bill and svc.find(book, bid) == bill
    with pytest.raises(BillRefused):
        svc.find(book, "water")
    assert FAKE_UPI not in every_text(docs)


async def test_a_number_in_any_field_or_a_bad_upi_id_is_refused() -> None:
    svc, _, _ = _svc()
    for over in (
        {"label": "Card 4111 1111 1111 1111"},
        {"payee": "Acct 1234567890"},
        {"upi": "not-a-upi"},
        {"last4": "4111111111111111"},
    ):
        with pytest.raises(BillRefused):
            await _electricity(svc, **over)
    assert (await svc.book(UID)).bills == ()


async def test_without_a_keyring_bills_say_they_are_off() -> None:
    svc, _, _ = _svc(keys=False)
    with pytest.raises(BillsOff):
        await _electricity(svc)


async def test_i_paid_records_the_current_due_date_and_stops_its_reminders() -> None:
    svc, _, _ = _svc()
    await _electricity(svc)
    bill, due = await svc.mark_paid(UID, "Electricity")
    assert due == date(2026, 11, 13) and bill.paid_for(due)
    assert reminders_due(bill, date(2026, 11, 12)) == []
    assert current_due(bill, date(2026, 11, 12)) == date(2026, 12, 13)


async def test_the_payee_is_set_only_by_his_own_entry_and_is_checked() -> None:
    svc, _, _ = _svc()
    await _electricity(svc, upi="")
    with pytest.raises(BillRefused, match="UPI ID"):
        await svc.prepare(UID, "Electricity")
    bill = await svc.set_payee(UID, "Electricity", upi=FAKE_UPI, payee="Power Co")
    assert bill.upi == FAKE_UPI
    with pytest.raises(BillRefused):
        await svc.set_payee(UID, "Electricity", upi="x@1")


async def test_the_card_text_is_written_by_code_exactly() -> None:
    svc, _, _ = _svc()
    await _electricity(svc)
    prepared = await svc.prepare(UID, "Electricity")
    assert prepared.card == CARD
    assert prepared.paise == 124000 and prepared.due == date(2026, 11, 13)


async def test_a_varies_bill_needs_an_amount_and_the_cap_holds() -> None:
    svc, _, _ = _svc()
    await _electricity(svc, amount="varies")
    with pytest.raises(BillRefused, match="varies"):
        await svc.prepare(UID, "Electricity")
    assert (await svc.prepare(UID, "Electricity", amount="899.50")).paise == 89950
    with pytest.raises(BillRefused, match="1,00,000"):
        await svc.prepare(UID, "Electricity", amount="100000.01")


async def test_the_payment_is_shown_once_after_the_grant_and_never_stored() -> None:
    svc, docs, clock = _svc()
    bid = await _electricity(svc)
    assert await svc.payment(UID, bid) is None  # nothing approved yet
    await svc.make_ready(UID, await svc.prepare(UID, bid))
    shown = await svc.payment(UID, bid)
    assert shown is not None
    assert shown.link.startswith("upi://pay?pa=test@okfake&pn=Power%20Co&am=1240.00&cu=INR")
    assert shown.qr.startswith("data:image/svg+xml")
    assert await svc.payment(UID, bid) is None  # once
    raw = every_text(docs)
    assert "upi://" not in raw and "svg" not in raw
    await svc.make_ready(UID, await svc.prepare(UID, bid))
    clock.at = NOON_IST + timedelta(minutes=11)
    assert await svc.payment(UID, bid) is None  # expired


async def test_remove_and_prefs() -> None:
    svc, _, _ = _svc()
    bid = await _electricity(svc)
    prefs = await svc.set_prefs(UID, bills_at="08:15", birthdays_on=True)
    assert prefs.bills_at == "08:15" and prefs.birthdays_on
    assert await svc.remove(UID, bid) and not await svc.remove(UID, bid)
    with pytest.raises(BillRefused):
        await svc.set_prefs(UID, bills_at="25:00")


async def test_the_shown_payment_is_exactly_the_approved_one() -> None:
    svc, _, _ = _svc()
    bid = await _electricity(svc)
    await svc.make_ready(UID, await svc.prepare(UID, bid))
    await svc.set_payee(UID, bid, upi="mallory@okfake", payee="Someone Else")  # changed since
    assert await svc.payment(UID, bid) is None  # never a payee he didn't approve
    await svc.make_ready(UID, await svc.prepare(UID, bid))
    shown = await svc.payment(UID, bid)
    assert shown is not None and "pa=mallory@okfake&pn=Someone%20Else" in shown.link
