# tests/test_r11_d_receipts.py -- R11 Part D (plan D15): one e-mailed grocery receipt into facts.
# Pure: only known grocery merchants whose mail Gmail authenticated (as the parcels reader), every
# 12-19-digit run masked before parsing, the order total in paise, a keyed hash for the order.
from __future__ import annotations

import hashlib
from datetime import date

import pytest
from r11_fakes_d import CARD, CARD_DIGITS, eml

from jarvis.helpers.kitchen import receipts
from jarvis.helpers.kitchen.receipts import MERCHANTS, find_total, gmail_query, mask, read_receipt

TZ = "Asia/Kolkata"


def _mac(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()[:32]


def _read(name: str) -> receipts.Receipt | None:
    return read_receipt(eml(name), mac=_mac, tz=TZ)


@pytest.mark.parametrize(
    ("name", "merchant", "day", "paise"),
    [
        ("d_receipt_bigbasket_nov.eml", "BigBasket", date(2026, 11, 3), 123450),
        ("d_receipt_blinkit_nov.eml", "Blinkit", date(2026, 11, 5), 45600),
        ("d_receipt_zepto_oct.eml", "Zepto", date(2026, 10, 28), 78900),
        ("d_receipt_instamart_nov.eml", "Swiggy Instamart", date(2026, 11, 6), 30000),
        ("d_receipt_injected.eml", "BigBasket", date(2026, 11, 8), 15000),
    ],
)
def test_a_receipt_from_a_known_aligned_merchant_gives_merchant_day_and_total(
    name: str, merchant: str, day: date, paise: int
) -> None:
    r = _read(name)
    assert r is not None and (r.merchant, r.day, r.paise, r.cancelled) == (
        merchant,
        day,
        paise,
        False,
    )


@pytest.mark.parametrize(
    "name",
    [
        "d_receipt_unknown_sender.eml",  # not a grocery merchant in the fixed list
        "d_receipt_unaligned.eml",  # says bigbasket.com, but Gmail vouched for another domain
        "d_receipt_swiggy_food.eml",  # Swiggy, but not Instamart
        "d_receipt_bigbasket_promo.eml",  # an offer: no order total
    ],
)
def test_everything_else_is_ignored(name: str) -> None:
    assert _read(name) is None


def test_two_mails_of_one_order_share_its_key() -> None:
    a, b = _read("d_receipt_bigbasket_nov.eml"), _read("d_receipt_bigbasket_delivered.eml")
    assert a is not None and b is not None and a.key == b.key
    other = _read("d_receipt_injected.eml")
    assert other is not None and other.key != a.key


def test_a_cancelled_order_is_marked_so_its_total_can_be_dropped() -> None:
    ok, gone = _read("d_receipt_zepto_nov.eml"), _read("d_receipt_zepto_cancelled.eml")
    assert ok is not None and gone is not None
    assert gone.cancelled and gone.key == ok.key


def test_card_numbers_are_masked_before_anything_reads_the_text() -> None:
    text = f"Card {CARD} or {CARD_DIGITS} or 4111-1111-1111-1111, ending 1111"
    text += ", order 402-1234567-1234567"
    out = mask(text)
    assert CARD not in out and CARD_DIGITS not in out and "4111-1111" not in out
    assert "ending 1111" in out and "402-1234567-1234567" in out  # an order id stays
    r = _read("d_receipt_blinkit_nov.eml")
    assert r is not None and CARD_DIGITS not in repr(r) and "4111" not in repr(r)


@pytest.mark.parametrize(
    ("text", "paise"),
    [
        ("Order Total: Rs. 1,234.50", 123450),
        ("Grand Total ₹ 12,345", 1234500),
        ("Bill total Rs 99,999.99", 9999999),
        ("Amount Paid: INR 99.9", 9990),
        ("total savings ₹40, minimum total of ₹999", None),
        ("Order Total: ₹2,00,000", None),  # above the ₹1,00,000 sanity cap
        ("Order Total: ₹0", None),
    ],
)
def test_the_total_needs_a_strong_label_and_a_sane_amount(text: str, paise: int | None) -> None:
    assert find_total(text) == paise


def test_the_gmail_query_names_only_the_fixed_merchants() -> None:
    q = gmail_query(35)
    assert "newer_than:35d" in q
    for m in MERCHANTS:
        for d in m.domains:
            assert d in q
    assert "example.com" not in q
