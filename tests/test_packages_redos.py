# tests/test_packages_redos.py -- hostile mail text must not stall the event loop (review fix: the
# tracking-word pattern backtracked catastrophically on "tracking" + many spaces + "!").
from __future__ import annotations

import time
from datetime import UTC, datetime

import pytest

from jarvis.packages.parse import (
    detect_expected,
    detect_status,
    find_order_id,
    find_tracking_number,
    parse_mail,
)

SENT = datetime(2026, 11, 5, 8, 0, tzinfo=UTC)
LIMIT_S = 0.1
FILLERS = {
    "spaces": " ",
    "nbsp": " ",
    "mixed": "  \t 　\n",
    "dashes": "-",
    "colons": ":",
}
WORDS = ["tracking", "awb", "order", "order id", "shipment", "delivered by", "expected", "arriving"]


def timed(fn, *args) -> float:  # type: ignore[no-untyped-def]
    start = time.perf_counter()
    fn(*args)
    return time.perf_counter() - start


@pytest.mark.parametrize("word", WORDS)
@pytest.mark.parametrize("filler", sorted(FILLERS))
def test_ten_thousand_filler_characters_are_cheap(word: str, filler: str) -> None:
    text = word + FILLERS[filler] * 10_000 + "!"
    assert timed(find_tracking_number, text, None) < LIMIT_S
    assert timed(find_order_id, text) < LIMIT_S
    assert timed(detect_status, text, text) < LIMIT_S
    assert timed(detect_expected, text, SENT.date()) < LIMIT_S


@pytest.mark.parametrize("filler", sorted(FILLERS))
def test_parse_mail_is_cheap_on_a_hostile_body(filler: str) -> None:
    body = ("tracking" + FILLERS[filler] * 5_000 + "!") * 20
    elapsed = timed(
        lambda: parse_mail(
            message_id="m",
            sender="shipment-tracking@amazon.in",
            subject="Shipped",
            sent=SENT,
            body=body,
        )
    )
    assert elapsed < 0.5


def test_the_200_space_case_from_the_review() -> None:
    assert timed(find_tracking_number, "tracking" + " " * 400 + "!", None) < LIMIT_S


def test_unicode_whitespace_does_not_hide_a_real_number() -> None:
    sender = "shipment-tracking@amazon.in"
    mail = parse_mail(
        message_id="m",
        sender=sender,
        subject="Shipped",
        sent=SENT,
        body="Your package has shipped. Tracking ID:  TBA123456789012 arriving Monday",
    )
    assert mail.tracking_number == "TBA123456789012" and mail.status == "shipped"


def test_a_huge_body_is_capped() -> None:
    body = "Delivered. " + "x " * 2_000_000
    assert (
        timed(
            lambda: parse_mail(
                message_id="m",
                sender="shipment-tracking@amazon.in",
                subject="s",
                sent=SENT,
                body=body,
            )
        )
        < 0.5
    )


def test_grocery_titles_from_google_are_cheap_too() -> None:
    from jarvis.groceries.items import parse_title

    for hostile in ("milk" + " " * 10_000 + "(", "(" * 5_000, "a (" + "1 " * 5_000, "x " * 9_000):
        assert timed(parse_title, hostile) < LIMIT_S
