# tests/test_r11_a_models.py -- R11 Part A (docs/plans/r11-free-helpers.md D7, data model): the bill
# record and its checks, written before helpers/today/models.py. A UPI ID only in NPCI's shape; no
# card, account or consumer number in any bill field (the last 4 digits at most); amounts in paise,
# with the Indian grouping on the way out; the due rule (once, or every N months on a day) clamps
# to short months.
from __future__ import annotations

from datetime import date

import pytest

from jarvis.helpers.today.models import (
    PAY_CAP_PAISE,
    Bill,
    BillRefused,
    Due,
    clean_label,
    inr,
    inr_short,
    last_four,
    parse_amount,
    parse_upi,
)


@pytest.mark.parametrize("upi", ["test@okfake", "bill.pay-1_x@okfake", "9800000000@okfake"])
def test_a_upi_id_in_npcis_shape_is_kept(upi: str) -> None:
    assert parse_upi(f"  {upi} ") == upi


@pytest.mark.parametrize(
    "bad",
    [
        "",
        "no-at-sign",
        "a@1bank",  # the handle starts with a letter
        "x@ok.fake",  # no dots in the handle
        "t@okfake extra",
        "1234567890123456@okfake",  # an account-like run of digits
        "a" * 257 + "@okfake",
        None,
        42,
    ],
)
def test_anything_else_is_refused(bad: object) -> None:
    with pytest.raises(BillRefused):
        parse_upi(bad)


@pytest.mark.parametrize(
    "text",
    [
        "Card 4111111111111111",
        "Card 4111 1111 1111 1111",
        "Card 4111-1111-1111-1111",
        "Consumer 1234567",  # a run of 5+ digits
    ],
)
def test_a_card_account_or_consumer_number_in_a_label_is_refused(text: str) -> None:
    with pytest.raises(BillRefused, match="last 4"):
        clean_label(text)


def test_a_plain_label_is_one_clean_line_of_at_most_40() -> None:
    assert clean_label("  Electricity\n Nov 2026 ") == "Electricity Nov 2026"
    assert clean_label("Rent 01-11-2026") == "Rent 01-11-2026"  # a date is not a number to hide
    with pytest.raises(BillRefused):
        clean_label("x" * 41)
    with pytest.raises(BillRefused):
        clean_label("   ")


def test_only_the_last_4_digits_are_ever_kept() -> None:
    assert last_four("1234") == "1234"
    assert last_four("") == ""
    for bad in ("12345", "12a4", "4111111111111111"):
        with pytest.raises(BillRefused):
            last_four(bad)


@pytest.mark.parametrize(
    ("raw", "paise"),
    [
        ("1240", 124000),
        ("1,240.50", 124050),
        ("₹1,00,000", 10_000_000),
        (1240, 124000),
        ("varies", None),
    ],
)
def test_amounts_are_kept_in_paise(raw: object, paise: int | None) -> None:
    assert parse_amount(raw) == paise


@pytest.mark.parametrize("bad", ["0", "-5", "12.345", "abc", "1e5", True, 10**12])
def test_a_bad_amount_is_refused(bad: object) -> None:
    with pytest.raises(BillRefused):
        parse_amount(bad)


def test_rupees_are_shown_with_the_indian_grouping() -> None:
    assert inr(124000) == "₹1,240.00"
    assert inr(PAY_CAP_PAISE) == "₹1,00,000.00"
    assert inr(123456789) == "₹12,34,567.89"
    assert inr_short(124000) == "₹1,240"
    assert inr_short(124050) == "₹1,240.50"
    assert PAY_CAP_PAISE == 1_00_000 * 100


def test_a_monthly_due_day_clamps_to_short_months_and_once_is_once() -> None:
    monthly = Due(start=date(2026, 1, 31), every_months=1)
    assert monthly.on(date(2026, 2, 28)) and not monthly.on(date(2026, 2, 27))
    assert monthly.on(date(2026, 11, 30)) and monthly.on(date(2026, 12, 31))
    assert not monthly.on(date(2025, 12, 31))  # never before it starts
    quarterly = Due(start=date(2026, 1, 15), every_months=3)
    assert quarterly.on(date(2026, 4, 15)) and not quarterly.on(date(2026, 5, 15))
    once = Due(start=date(2026, 11, 13), every_months=0)
    assert once.on(date(2026, 11, 13)) and not once.on(date(2026, 12, 13))
    assert monthly.dates_between(date(2026, 11, 1), date(2026, 12, 31)) == [
        date(2026, 11, 30),
        date(2026, 12, 31),
    ]


def test_a_bill_refuses_a_number_in_any_field_and_unknown_fields() -> None:
    due = Due(start=date(2026, 11, 13), every_months=1)
    ok = Bill(id="a1b2c3d4e5f6", label="Electricity", payee="Power Co", amount=124000, due=due)
    assert ok.leads == (3, 1, 0) and ok.upi == "" and ok.last4 == ""
    with pytest.raises(ValueError):
        Bill(id="a1b2c3d4e5f6", label="Electricity", payee="Acct 123456789", due=due)
    with pytest.raises(ValueError):
        Bill(id="a1b2c3d4e5f6", label="E", due=due, card="4111111111111111")  # type: ignore[call-arg]
    with pytest.raises(ValueError):
        Bill(id="a1b2c3d4e5f6", label="E", due=due, leads=(30,))
