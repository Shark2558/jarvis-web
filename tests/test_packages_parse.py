# tests/test_packages_parse.py -- R1 D13: package facts from order emails, deterministic.
# The 36 fixture scenarios live in tests/fixtures/package_mails/*.json. Formats are UNVERIFIED on
# real mail (packages/carriers.py); these tests pin what the parser does with the fixtures.
from __future__ import annotations

import json
from datetime import UTC, date, datetime
from email.utils import parseaddr, parsedate_to_datetime
from pathlib import Path
from typing import Any

import pytest

from jarvis.packages import carriers
from jarvis.packages.parse import (
    build_packages,
    detect_expected,
    detect_status,
    find_tracking_number,
    parse_mail,
)

FIXTURES = sorted((Path(__file__).parent / "fixtures" / "package_mails").glob("*.json"))


def load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text())


def facts_of(scenario: dict[str, Any]):
    out = []
    for m in scenario["mails"]:
        out.append(
            parse_mail(
                message_id=m["id"],
                sender=parseaddr(m["from"])[1].lower(),
                subject=m["subject"],
                sent=parsedate_to_datetime(m["date"]),
                body=m["body"],
                authenticated=m.get("authenticated", True),
            )
        )
    return out


def test_there_are_36_fixture_scenarios() -> None:
    assert len(FIXTURES) == 36


@pytest.mark.parametrize("path", FIXTURES, ids=lambda p: p.stem)
def test_fixture_scenario(path: Path) -> None:
    sc = load(path)
    want = sc["expect"]
    pkgs = build_packages(facts_of(sc))
    assert len(pkgs) == want["count"]
    p = pkgs[0]
    assert p.tracking_number == want["tracking_number"]
    assert p.carrier == want["carrier"]
    assert p.status == want["status"]
    assert (p.expected.isoformat() if p.expected else None) == want["expected"]
    assert p.merchant == want["merchant"]
    assert p.known_sender is want.get("known_sender", True)
    assert p.link is None  # no verified link template exists yet


def test_india_post_check_digit() -> None:
    assert carriers.s10_valid("EE123456785IN")
    assert not carriers.s10_valid("EE123456784IN")
    assert not carriers.s10_valid("EE12345678IN")


def test_known_sender_needs_the_real_domain() -> None:
    assert carriers.known_domain("a@amazon.in") == "amazon.in"
    assert carriers.known_domain("a@mail.amazon.in") == "amazon.in"
    assert carriers.known_domain("a@amazon.in.evil.test") is None
    assert carriers.known_domain("a@notamazon.in") is None
    assert carriers.known_domain("nobody") is None


def test_a_tracking_number_needs_a_tracking_word() -> None:
    dl = carriers.BY_KEY["delhivery"]
    assert find_tracking_number("AWB: 12345678901234", dl)[0] == "12345678901234"
    assert find_tracking_number("Your code 12345678901234", dl)[0] is None
    assert find_tracking_number("tracking: 9876543210", dl)[0] is None  # a phone-shaped run


def test_without_a_named_carrier_only_letter_formats_count() -> None:
    assert find_tracking_number("Tracking ID: 12345678901234", None)[0] is None
    num, car = find_tracking_number("Tracking ID: TBA123456789012", None)
    assert (num, car.key if car else None) == ("TBA123456789012", "amazon")


@pytest.mark.parametrize(
    ("subject", "body", "want"),
    [
        ("Your order will be delivered by Monday", "", None),
        ("Out for delivery", "", "out_for_delivery"),
        ("Delivered: x", "", "delivered"),
        ("Update", "Once delivered, please rate us. Your order has been shipped.", "shipped"),
        ("Hello", "Return policy: items can be returned in 7 days.", None),
        ("Order confirmed", "", "ordered"),
        ("Cancelled", "Your order has been cancelled", "cancelled"),
    ],
)
def test_status_ladder(subject: str, body: str, want: str | None) -> None:
    assert detect_status(subject, body) == want


def test_expected_date_is_read_against_the_mail_date() -> None:
    sent = date(2026, 11, 5)
    assert detect_expected("Arriving tomorrow", sent) == date(2026, 11, 6)
    assert detect_expected("Arriving today", sent) == date(2026, 11, 5)
    assert detect_expected("Expected by 12th November 2026", sent) == date(2026, 11, 12)
    assert detect_expected("Delivery by 12/11/2026", sent) == date(2026, 11, 12)
    assert detect_expected("Estimated delivery: Nov 14", sent) == date(2026, 11, 14)
    assert detect_expected("Arriving Monday", sent) == date(2026, 11, 9)
    assert detect_expected("Arriving Jan 2", date(2026, 12, 28)) == date(2027, 1, 2)
    assert detect_expected("Arriving 31 Feb", sent) is None
    assert detect_expected("No dates here, call 12 Nov", sent) is None  # no arrival phrase


def test_naive_dates_are_taken_as_utc() -> None:
    f = parse_mail(
        message_id="x",
        sender="a@amazon.in",
        subject="Shipped",
        sent=datetime(2026, 11, 5, 9, 0),
        body="",
    )
    assert f.sent.tzinfo is UTC


def test_the_newest_mail_wins_even_when_it_is_less_advanced() -> None:
    sc = load(next(p for p in FIXTURES if p.stem == "cancelled_after_shipped"))
    p = build_packages(facts_of(sc))[0]
    assert p.status == "cancelled" and p.expected is None
    assert p.tracking_number == "FMPP7770001112"  # kept from the earlier mail


def test_open_parcels_sort_before_closed_ones() -> None:
    mails = []
    for stem in ("amazon_delivered", "flipkart_shipped_ekart"):
        mails += facts_of(load(next(p for p in FIXTURES if p.stem == stem)))
    pkgs = build_packages(mails)
    assert [p.status for p in pkgs] == ["shipped", "delivered"]


def test_a_mail_that_bridges_two_groups_merges_them() -> None:
    a = load(next(p for p in FIXTURES if p.stem == "amazon_ordered"))
    b = load(next(p for p in FIXTURES if p.stem == "amazon_shipped"))
    for m in b["mails"]:
        m["id"] = "other"
    pkgs = build_packages(facts_of(a) + facts_of(b))
    assert len(pkgs) == 1 and pkgs[0].tracking_number == "TBA123456789012"


@pytest.mark.parametrize(
    ("header", "ok"),
    [
        ("mx.google.com; dkim=pass header.i=@amazon.in header.s=s1; spf=pass", True),
        ("mx.google.com; dkim=pass header.d=mail.amazon.in", True),
        ("mx.google.com; spf=pass; dmarc=pass (p=REJECT) header.from=amazon.in", True),
        ("mx.google.com; DKIM=PASS header.i=@amazon.in", True),
        ("mx.google.com; dkim=fail header.i=@amazon.in; dmarc=fail header.from=amazon.in", False),
        ("mx.google.com; dkim=none; dmarc=none", False),
        ("mx.google.com; spf=pass smtp.mailfrom=amazon.in", False),  # SPF alone does not align
        ("mx.google.com; dkim=pass header.i=@evil.test; dmarc=pass header.from=evil.test", False),
        ("mx.google.com; dkim=pass header.i=@notamazon.in", False),
        ("mx.google.com; dkim=pass header.i=@amazon.in.evil.test", False),
        ("", False),
        (None, False),
    ],
)
def test_authentication_results_must_pass_for_the_from_domain(header: str | None, ok: bool) -> None:
    assert carriers.authenticated(header, "amazon.in") is ok


def test_an_unauthenticated_mail_yields_no_known_sender_and_no_number() -> None:
    f = parse_mail(
        message_id="m",
        sender="shipment-tracking@amazon.in",
        subject="Shipped",
        sent=datetime(2026, 11, 5, tzinfo=UTC),
        body="Tracking ID: TBA123456789012",
        authenticated=False,
    )
    assert f.domain is None and f.tracking_number is None and f.merchant is None
    (p,) = build_packages([f])
    assert p.known_sender is False


def test_parse_mail_fails_closed_when_not_told_about_authentication() -> None:
    f = parse_mail(
        message_id="m",
        sender="shipment-tracking@amazon.in",
        subject="Shipped",
        sent=datetime(2026, 11, 5, tzinfo=UTC),
        body="Tracking ID: TBA123456789012",
    )
    assert f.domain is None and f.tracking_number is None
