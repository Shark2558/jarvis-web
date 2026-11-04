# src/jarvis/packages/carriers.py
"""Known senders and carrier tracking-number formats for package tracking (R1 D13).

EVERY FORMAT BELOW IS UNVERIFIED against real mail: it was written from public knowledge of how
Indian carriers number parcels, not from the owner's inbox (nothing could be verified in the build
sandbox). The parser only ever accepts a number that (a) sits next to a tracking word, (b) fully
matches the format of the carrier the mail names, and (c) comes from a sender in this table. A
wrong guess therefore means "no tracking number shown", never a wrong number. Tell the builder
about any real mail that was missed (docs/plans/r1-free-tools.md, "check after deploy").

`link` is None everywhere: a tracking-page URL template may be added only after it was checked on
the carrier's own site, and only here -- a link found inside an email is never used.
"""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class Carrier:
    key: str
    name: str
    domains: tuple[str, ...]
    mention: re.Pattern[str]  # how a mail names this carrier in its text
    number: re.Pattern[str]  # full match of a tracking number (upper-case input)
    distinctive: bool  # letters in the format: safe to use without the carrier being named
    link: str | None = None  # "https://...{number}" once verified on the carrier's site


def _re(pattern: str) -> re.Pattern[str]:
    return re.compile(pattern, re.IGNORECASE)


CARRIERS: tuple[Carrier, ...] = (
    # UNVERIFIED: Amazon Transport Reference IDs look like TBA + 12 digits.
    Carrier(
        "amazon",
        "Amazon Logistics",
        ("amazon.in",),
        _re(r"amazon\s+(?:transport|logistics)"),
        re.compile(r"TBA\d{9,13}"),
        True,
    ),
    # UNVERIFIED: Ekart ids start FMPP / FMPC / FMPR ... followed by digits.
    Carrier(
        "ekart",
        "Ekart",
        ("ekartlogistics.com",),
        _re(r"\bekart\b"),
        re.compile(r"FM[A-Z]{2}\d{9,12}"),
        True,
    ),
    # UNVERIFIED: Delhivery waybills are 11-14 digits.
    Carrier(
        "delhivery",
        "Delhivery",
        ("delhivery.com",),
        _re(r"delhivery"),
        re.compile(r"\d{11,14}"),
        False,
    ),
    # UNVERIFIED: Blue Dart AWB numbers are 11 digits.
    Carrier(
        "bluedart",
        "Blue Dart",
        ("bluedart.com",),
        _re(r"blue\s*dart"),
        re.compile(r"\d{11}"),
        False,
    ),
    # UNVERIFIED: DTDC consignment numbers are one letter + 8-10 digits (e.g. D12345678).
    Carrier(
        "dtdc",
        "DTDC",
        ("dtdc.in", "dtdc.com"),
        _re(r"\bdtdc\b"),
        re.compile(r"[A-Z]\d{8,10}"),
        True,
    ),
    # UNVERIFIED: XpressBees AWB numbers are 14 digits.
    Carrier(
        "xpressbees",
        "XpressBees",
        ("xpressbees.com",),
        _re(r"xpress\s*bees"),
        re.compile(r"\d{14}"),
        False,
    ),
    # UNVERIFIED: Shadowfax ids start SF (+ optional letter) then digits.
    Carrier(
        "shadowfax",
        "Shadowfax",
        ("shadowfax.in",),
        _re(r"shadowfax"),
        re.compile(r"SF[A-Z]?\d{8,14}"),
        True,
    ),
    # UNVERIFIED: Ecom Express AWB numbers are 9-10 digits; a 10-digit run starting 6-9 is
    # treated as a phone number and never accepted.
    Carrier(
        "ecom",
        "Ecom Express",
        ("ecomexpress.in",),
        _re(r"ecom\s*express"),
        re.compile(r"[1-5]\d{8,9}"),
        False,
    ),
    # UPU S10: two letters, 8 digits, a check digit, "IN". The check digit IS verified in code.
    Carrier(
        "indiapost",
        "India Post",
        ("indiapost.gov.in",),
        _re(r"india\s*post|speed\s*post"),
        re.compile(r"[A-Z]{2}\d{9}IN"),
        True,
    ),
)
BY_KEY = {c.key: c for c in CARRIERS}

# Merchants (who sold it): sender domain -> display name.
MERCHANTS: dict[str, str] = {
    "amazon.in": "Amazon",
    "flipkart.com": "Flipkart",
    "myntra.com": "Myntra",
    "swiggy.in": "Swiggy",
    "meesho.com": "Meesho",
}
# A mail from a carrier's own domain: the merchant is the carrier, the carrier is known.
CARRIER_BY_DOMAIN = {d: c.key for c in CARRIERS for d in c.domains if c.key != "amazon"}
SENDER_DOMAINS: tuple[str, ...] = tuple([*MERCHANTS, *CARRIER_BY_DOMAIN])
# The sender of these mails names the carrier even when the text doesn't (UNVERIFIED default).
DEFAULT_CARRIER = {"amazon.in": "amazon"}

SHIPPING_SUBJECT_WORDS = (
    "shipped",
    "dispatched",
    "out for delivery",
    "delivered",
    "tracking",
    "on the way",
    "arriving",
)


def domain_of(address: str) -> str:
    return address.rpartition("@")[2].strip().lower().rstrip(".")


def known_domain(address: str) -> str | None:
    """The table domain this address belongs to (exact or a real subdomain), else None.
    `amazon.in.evil.test` and `notamazon.in` are not Amazon."""
    host = domain_of(address)
    for d in SENDER_DOMAINS:
        if host == d or host.endswith("." + d):
            return d
    return None


def gmail_query(days: int) -> str:
    senders = " OR ".join(SENDER_DOMAINS)
    words = " OR ".join(f'"{w}"' if " " in w else w for w in SHIPPING_SUBJECT_WORDS)
    return f"(from:({senders}) OR subject:({words})) newer_than:{days}d"


def s10_valid(number: str) -> bool:
    """UPU S10 check digit of e.g. 'EE123456785IN' (weights 8 6 4 2 3 5 9 7; 10 -> 0, 11 -> 5)."""
    if not re.fullmatch(r"[A-Z]{2}\d{9}[A-Z]{2}", number):
        return False
    digits = [int(c) for c in number[2:10]]
    total = sum(d * w for d, w in zip(digits, (8, 6, 4, 2, 3, 5, 9, 7), strict=True))
    check = 11 - total % 11
    check = {10: 0, 11: 5}.get(check, check)
    return check == int(number[10])


def number_ok(carrier: Carrier, number: str) -> bool:
    if not carrier.number.fullmatch(number):
        return False
    if carrier.key == "indiapost":
        return s10_valid(number)
    return not (number.isdigit() and len(number) == 10 and number[0] in "6789")  # a phone


__all__ = [
    "BY_KEY",
    "CARRIERS",
    "CARRIER_BY_DOMAIN",
    "DEFAULT_CARRIER",
    "MERCHANTS",
    "SENDER_DOMAINS",
    "Carrier",
    "domain_of",
    "gmail_query",
    "known_domain",
    "number_ok",
    "s10_valid",
]
