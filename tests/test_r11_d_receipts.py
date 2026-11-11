# tests/test_r11_d_receipts.py -- R11 Part D (plan D15): one e-mailed grocery receipt into facts.
# Pure: only known grocery merchants whose mail Gmail authenticated (as the parcels reader), every
# 12-19-digit run masked before parsing, the order total in paise, a keyed hash for the order.
from __future__ import annotations

import base64
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


def _read_text(body: str) -> receipts.Receipt | None:
    """The BigBasket fixture's headers around `body`."""
    m = eml("d_receipt_bigbasket_nov.eml")
    m["payload"]["body"]["data"] = base64.urlsafe_b64encode(body.encode()).decode()
    return read_receipt(m, mac=_mac, tz=TZ)


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
        ("Total: ₹300", 30000),  # a bare "Total" counts only as a line of its own
        ("Order Total: Rs. 1,234/-", 123400),
        ("| Grand Total | ₹ 1,23,456.00 |", 12345600),
        ("Order Total: ₹2,00,000", 20000000),  # read, then flagged as too large (not counted)
        ("Total MRP: ₹1,500\nTotal: ₹1,400\nGrand Total: ₹1,234", 123400),  # the strongest
        ("total savings ₹40, minimum total of ₹999", None),
        ("Total savings ₹40", None),
        ("Order Total: 1,234.50", None),  # no currency marker
        ("Order #AB12345 Order total ₹ 1,234.50", None),  # not a total line of its own
        ("Order now: order total of ₹999 or more", None),
        ("Order Total: ₹0", None),
    ],
)
def test_the_total_is_read_only_from_a_labelled_total_line_with_a_currency_marker(
    text: str, paise: int | None
) -> None:
    assert find_total(text) == paise


@pytest.mark.parametrize(
    "body",
    [
        "Order total ₹ 3782 822463 10005",  # Amex 4-6-5
        "Order total: ₹4111-1111-1111-1111",
        "Order total: ₹ 4111111111111111",
        "Order total: ₹ 4111.1111.1111.1111",
        "Order total: ₹ 4111/1111/1111/1111",
        "Order total: ₹ 4111 1111 1111 1111 123",
        "Order total: ₹ 4111 - 1111 - 1111 - 1111",
        "Order total: ₹ \uff14\uff11\uff11\uff11\uff11\uff11\uff11\uff11\uff11\uff11\uff11\uff11",
        "Order total: ₹ 3782 822463",  # a card's first groups, the rest on another line
    ],
)
def test_no_digit_group_of_a_card_like_number_becomes_a_total(body: str) -> None:  # M3
    assert _read_text(body) is None


@pytest.mark.parametrize(
    "text",
    [
        "3782 822463 10005", "4111.1111.1111.1111", "4111/1111/1111/1111", "4111-1111-1111-1111",
        "4111 1111 1111 1111", "4111111111111111", "5105 1051 0510 5100 123", "1234 5678 9012",
        "\uff14\uff11\uff11\uff11\uff11\uff11\uff11\uff11\uff11\uff11\uff11\uff11\uff11",
        "4111 - 1111 - 1111 - 1111",
    ],
)  # fmt: skip
def test_card_and_account_numbers_are_masked_whatever_separates_them(text: str) -> None:
    out = mask(f"Paid with {text} today")
    assert out == "Paid with [number removed] today", out


def test_an_order_id_and_the_last_four_stay() -> None:
    out = mask("Order 402-1234567-1234567, card ending 1111, OD123456789012345")
    assert out == "Order 402-1234567-1234567, card ending 1111, OD123456789012345"


def test_an_implausible_total_is_flagged_not_counted() -> None:
    r = _read_text("Order BB-ORDER-7777\nOrder Total: ₹ 50,000")
    assert r is not None and r.flagged and r.paise == 0
    ok = _read_text("Order BB-ORDER-7778\nOrder Total: ₹ 24,999")
    assert ok is not None and not ok.flagged and ok.paise == 2499900


def test_a_mail_just_after_midnight_in_his_zone_is_in_his_month() -> None:  # code M5
    r = _read("d_receipt_blinkit_month_edge.eml")  # 31 Oct 20:00 UTC = 1 Nov 01:30 IST
    assert r is not None and r.day == date(2026, 11, 1) and r.paise == 12000


def test_a_mail_too_big_to_be_a_receipt_is_not_parsed() -> None:  # security L2
    m = eml("d_receipt_blinkit_nov.eml")
    m["payload"]["body"]["data"] = "QUFB" * (receipts.MAX_BODY_B64 // 4 + 1)
    assert read_receipt(m, mac=_mac, tz=TZ) is None


def test_shared_domains_are_listed_only_with_their_grocery_service() -> None:  # security L3
    q = gmail_query(35)
    assert "(from:swiggy.in instamart)" in q and '(from:amazon.in "amazon fresh")' in q
    assert '(from:flipkart.com "flipkart minutes")' in q
    assert "bigbasket.com OR" in q and "from:(swiggy.in" not in q


def test_the_gmail_query_names_only_the_fixed_merchants() -> None:
    q = gmail_query(35)
    assert "newer_than:35d" in q
    for m in MERCHANTS:
        for d in m.domains:
            assert d in q
    assert "example.com" not in q
