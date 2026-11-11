# tests/test_r11_a_numbers.py -- R11 Part A security review fixes (HIGH-1, MEDIUM-1, LOW-3): ONE
# check (`text.has_number`) refuses a card, account or consumer number in every bill field, the
# payee's name, the note and the UPI ID: 13-19 digits (or more) joined across ANY run of
# separators (spaces of every kind, . - / _ , : dashes, bullets ...), Amex 4-6-5 too, digits of any
# script, invisible characters dropped first; 5 digits in a row in his text (11 in a UPI ID). A
# payee's name is Latin letters, spaces and . , ' & - only (look-alikes mapped, accents dropped):
# no digits, no @, no bidi or control character, so it can't imitate a UPI ID. Amounts take ASCII
# digits only. The reviewer's probe strings are all here.
from __future__ import annotations

import pytest

from jarvis.helpers.today.bills import card_text
from jarvis.helpers.today.models import (
    NUMBER_REFUSAL,
    BillRefused,
    clean_label,
    clean_note,
    clean_payee,
    parse_amount,
    parse_upi,
)
from jarvis.helpers.today.text import PAYEE_REFUSAL, has_number, name_from_label
from jarvis.helpers.today.upi import upi_link

CARD_LIKE = [
    "4111.1111.1111.1111",  # the reviewer's probes
    "4111/1111/1111/1111",
    "4111_1111_1111_1111",
    "4111,1111,1111,1111",
    "4111:1111:1111:1111",
    "4111 -1111 1111 1111",
    "4111 1111 1111 1111",
    "4111-1111-1111-1111",
    "4111 1111 1111 111",  # 15
    "4111​1111​1111​1111",  # zero-width spaces
    "４１１１ ４１１１ ４１１１ ４１１１",
    "4111 - 1111 . 1111 / 1111",  # a mix, and runs of separators
    "4111 1111 1111 1111",  # no-break spaces
    "4111–1111–1111–1111",  # en dashes
    "4111|1111|1111|1111",
    "٤١١١ ٤١١١ ٤١١١ ٤١١١",
    "3782 822463 10005",  # Amex 4-6-5
    "3782-822463-10005",
    "3782.822463.10005",
    "4222 2222 2222 2",  # 13
    "6011 0009 9013 9424 123",  # 19
    "1234 5678 9012 3456 7890",  # 20: holds a 13-19 digit run
]


@pytest.mark.parametrize("text", CARD_LIKE)
def test_a_card_like_number_is_found_across_any_separators(text: str) -> None:
    assert has_number(text)


@pytest.mark.parametrize("text", CARD_LIKE)
def test_every_bill_field_refuses_it_with_the_same_words(text: str) -> None:
    for clean in (clean_label, clean_payee, clean_note):
        with pytest.raises(BillRefused) as got:
            clean(f"X {text}")
        assert str(got.value) == NUMBER_REFUSAL, clean.__name__


@pytest.mark.parametrize(
    "upi",
    [
        "4111.1111.1111.1111@okfake",
        "4111_1111_1111_1111@okfake",
        "4111-1111-1111-1111@okfake",
        "3782-822463-10005@okfake",
        "12345678901@okfake",  # 11 in a row: more than a mobile number
    ],
)
def test_a_upi_id_holding_a_card_or_account_number_is_refused(upi: str) -> None:
    with pytest.raises(BillRefused, match="last 4"):
        parse_upi(upi)


@pytest.mark.parametrize(
    "text",
    [
        "Rent 01-11-2026",  # a date
        "Due 12/11/2026 09:30",  # a date and a time: 12 digits
        "4111  1111",  # 8 digits
        "Electricity Nov 2026",
        "Flat 4, Block 2",
    ],
)
def test_dates_years_and_short_numbers_are_fine(text: str) -> None:
    assert not has_number(text)
    assert clean_label(text)


def test_a_mobile_number_upi_id_is_still_fine() -> None:
    assert parse_upi("9800000000@okfake") == "9800000000@okfake"


@pytest.mark.parametrize(
    ("raw", "kept"),
    [
        ("Power Co", "Power Co"),
        ("  Power &\tLight Co. ", "Power & Light Co."),
        ("O'Brien-Smith", "O'Brien-Smith"),
        ("Café Coffee Day", "Cafe Coffee Day"),  # accents dropped
        ("Pоwer Cо", "Power Co"),  # Cyrillic o look-alikes
        ("ΑΒC Ltd", "ABC Ltd"),  # Greek capitals
        ("Ｐｏｗｅｒ", "Power"),  # fullwidth
        ("", ""),
        (None, ""),
    ],
)
def test_a_payee_name_is_kept_in_the_safe_set(raw: object, kept: str) -> None:
    assert clean_payee(raw) == kept


@pytest.mark.parametrize(
    "bad",
    [
        "Power Co (kseb@sbi) pay",  # imitates a second UPI ID
        "kseb@sbi",
        "kseb＠sbi",  # fullwidth @
        "kseb﹫sbi",  # small @
        "Power‮oC",  # bidi override
        "Power​Co",  # zero-width space
        "Power\x07Co",  # a control character
        "Flat 12",  # digits
        "Power Co #1",
        "केएसईबी",  # not Latin letters
        "x" * 41,
        "...",  # no letter at all
        42,
    ],
)
def test_anything_else_in_a_payee_name_is_refused(bad: object) -> None:
    with pytest.raises(BillRefused):
        clean_payee(bad)


def test_a_payee_refusal_says_what_is_allowed() -> None:
    with pytest.raises(BillRefused) as got:
        clean_payee("kseb@sbi")
    assert str(got.value) == PAYEE_REFUSAL


def test_a_label_cannot_hold_a_upi_id_either() -> None:
    for bad in ("kseb@sbi", "Rent ＠ x"):
        with pytest.raises(BillRefused, match="@"):
            clean_label(bad)


def test_a_bill_without_a_payee_is_paid_in_its_labels_safe_name() -> None:
    assert name_from_label("Rent (Nov) 2026") == "Rent Nov"
    assert name_from_label("Pоwer") == "Power"
    assert name_from_label("2026") == "Payee"


def test_the_upi_link_refuses_a_name_or_note_outside_the_checks() -> None:
    with pytest.raises(BillRefused):
        upi_link(pa="test@okfake", pn="Evil&am=1&pa=x@y #‮ Co\n", paise=12345, tn="x")
    with pytest.raises(BillRefused, match="last 4"):
        upi_link(pa="test@okfake", pn="Power Co", paise=100, tn="Card 4111.1111.1111.1111")


@pytest.mark.parametrize(
    "bad",
    ["١٠٠", "１００", "１,240", "1٢٣"],
)
def test_an_amount_takes_ascii_digits_only(bad: str) -> None:
    with pytest.raises(BillRefused):
        parse_amount(bad)


def test_the_pay_card_quotes_the_payee_name() -> None:
    from datetime import date

    from jarvis.helpers.today.models import Bill, Due

    due = Due(start=date(2026, 11, 13), every_months=1)
    bill = Bill(
        id="a1b2c3d4e5f6", label="Electricity", payee="Power Co", upi="test@okfake", due=due
    )
    text = card_text(bill, 124000, date(2026, 11, 13))
    assert "to “Power Co” (test@okfake)" in text
    plain = bill.model_copy(update={"payee": ""})
    assert "to “Electricity” (test@okfake)" in card_text(plain, 100, date(2026, 11, 13))
