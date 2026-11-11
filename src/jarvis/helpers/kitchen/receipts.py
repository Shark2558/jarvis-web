# src/jarvis/helpers/kitchen/receipts.py
"""One e-mailed grocery receipt into facts (docs/plans/r11-free-helpers.md D15, item 15). Pure,
deterministic, no model, no network: the parcels reader's pattern (`jarvis.packages`).

- Only a sender of a FIXED grocery merchant list counts, and only when Gmail's own
  `Authentication-Results` says dkim=pass or dmarc=pass for that merchant's domain
  (`packages.carriers.authenticated`): a From line alone proves nothing. Unknown or unaligned
  senders are ignored. Three merchants share a domain with other shops, so their mail must also
  name the grocery service (Swiggy "Instamart", Amazon "Fresh", Flipkart "Minutes").
- Every 12-19-digit run (and a card number in groups of four) is masked before anything reads the
  text, so a card number can never become an amount, a key or a log line.
- The total is the amount after a strong label ("Order total", "Grand total", "Amount paid" ...),
  never a bare "total" (offers say "minimum total of ₹999"), from ₹1 to ₹1,00,000.
- The order's key is a keyed hash (the caller's `mac`, the keyring's `spend` key) of the merchant
  and the order id (`packages.parse.find_order_id`), or of the message id when there is none, so
  the confirmation and the delivery mail of one order count once. A cancelled or refunded order
  (`packages.parse.detect_status`) is marked, so its total is dropped.
Nothing from the mail is kept but the merchant's name from the table, the day and the amount.
EVERY sender domain below is *unverified* against real mail (the build had none).
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from email.utils import parseaddr, parsedate_to_datetime
from typing import Any
from zoneinfo import ZoneInfo

from jarvis.helpers.kitchen.models import MAX_ORDER_PAISE
from jarvis.packages.carriers import authenticated, domain_of
from jarvis.packages.parse import detect_status, find_order_id, squash
from jarvis.tools.addresses import loose_address
from jarvis.tools.card import one_line
from jarvis.tools.gmail_mime import headers_of, parse_body

MASKED = "[number removed]"
SCAN_CHARS = 12_000
_LONG_RUN = re.compile(r"(?<![0-9A-Za-z])\d{12,19}(?![0-9A-Za-z])")
_GROUPED = re.compile(r"(?<!\d)\d{4}(?:[ -]\d{4}){2,3}(?:[ -]?\d{1,3})?(?!\d)")
_LABEL = (
    r"(?:grand\s+total|order\s+total|bill\s+total|total\s+amount(?:\s+paid)?|amount\s+paid|"
    r"total\s+paid|paid\s+amount|total\s+payable|net\s+payable|amount\s+payable|you\s+paid)"
)
_TOTAL = re.compile(
    _LABEL + r"[^0-9₹\n]{0,20}?(?:₹|rs\.?|inr)\s*([0-9][0-9,]{0,11}(?:\.[0-9]{1,2})?)",
    re.IGNORECASE,
)
_GONE = frozenset({"cancelled", "refunded", "returned"})


@dataclass(frozen=True)
class Merchant:
    key: str
    name: str
    domains: tuple[str, ...]
    needs: re.Pattern[str] | None = None  # the grocery service must be named (a shared domain)


def _re(p: str) -> re.Pattern[str]:
    return re.compile(p, re.IGNORECASE)


MERCHANTS: tuple[Merchant, ...] = (
    Merchant("bigbasket", "BigBasket", ("bigbasket.com",)),
    Merchant("blinkit", "Blinkit", ("blinkit.com",)),
    Merchant("zepto", "Zepto", ("zeptonow.com",)),
    Merchant("instamart", "Swiggy Instamart", ("swiggy.in",), _re(r"\binstamart\b")),
    Merchant("jiomart", "JioMart", ("jiomart.com",)),
    Merchant("amazonfresh", "Amazon Fresh", ("amazon.in",), _re(r"\bamazon\s+fresh\b")),
    Merchant("fkminutes", "Flipkart Minutes", ("flipkart.com",), _re(r"\bflipkart\s+minutes\b")),
    Merchant("dmart", "DMart Ready", ("dmart.in",)),
    Merchant("countrydelight", "Country Delight", ("countrydelight.in",)),
    Merchant("milkbasket", "Milkbasket", ("milkbasket.com",)),
)


@dataclass(frozen=True)
class Receipt:
    key: str
    merchant: str
    day: date
    paise: int
    cancelled: bool = False


def mask(text: str) -> str:
    """Every card-like number replaced (12-19 digits in a run, or 4-digit groups)."""
    return _GROUPED.sub(MASKED, _LONG_RUN.sub(MASKED, text))


def merchant_for(sender: str, results: str | None, text: str) -> tuple[Merchant, str] | None:
    """The merchant and its table domain when `sender` is one AND Gmail vouched for it."""
    host = domain_of(sender)
    for m in MERCHANTS:
        for d in m.domains:
            if (host == d or host.endswith("." + d)) and authenticated(results, d):
                if m.needs is None or m.needs.search(text):
                    return m, d
    return None


def find_total(text: str) -> int | None:
    """The first strongly labelled amount, in paise, from ₹1 to ₹1,00,000; else None."""
    m = _TOTAL.search(squash(text))
    if m is None:
        return None
    try:
        paise = int((Decimal(m.group(1).replace(",", "")) * 100).to_integral_value())
    except InvalidOperation:
        return None
    return paise if 100 <= paise <= MAX_ORDER_PAISE else None


def _day(headers: dict[str, str], internal_ms: Any, tz: str) -> date | None:
    try:
        sent = parsedate_to_datetime(one_line(headers.get("date", ""), 200))
    except (TypeError, ValueError, IndexError, OverflowError):
        try:
            sent = datetime.fromtimestamp(int(internal_ms) / 1000, ZoneInfo("UTC"))
        except (TypeError, ValueError, OverflowError, OSError):
            return None
    if sent.tzinfo is None:
        sent = sent.replace(tzinfo=ZoneInfo("UTC"))
    return sent.astimezone(ZoneInfo(tz)).date()


def read_receipt(m: dict[str, Any], *, mac: Callable[[str], str], tz: str) -> Receipt | None:
    """One Gmail `format=full` message -> a receipt, or None (not a grocery order we trust)."""
    payload = m.get("payload")
    if not isinstance(payload, dict) or not isinstance(m.get("id"), str):
        return None
    h = headers_of(payload)
    sender = loose_address(parseaddr(one_line(h.get("from", ""), 600))[1])
    subject = mask(one_line(h.get("subject", ""), 300))
    body = mask(squash(parse_body(payload).text, SCAN_CHARS))
    text = f"{subject}\n{body}"
    found = merchant_for(sender, h.get("authentication-results"), text) if sender else None
    day = _day(h, m.get("internalDate"), tz)
    if found is None or day is None:
        return None
    merchant, _ = found
    order = find_order_id(text)
    key = mac(f"order:{merchant.key}:{order}" if order else f"mail:{m['id']}")
    if detect_status(subject, body) in _GONE:
        return Receipt(key, merchant.name, day, 0, cancelled=True)
    paise = find_total(text)
    return None if paise is None else Receipt(key, merchant.name, day, paise)


def gmail_query(days: int) -> str:
    senders = " OR ".join(d for m in MERCHANTS for d in m.domains)
    return f"from:({senders}) newer_than:{days}d"


__all__ = [
    "MASKED",
    "MERCHANTS",
    "Merchant",
    "Receipt",
    "find_total",
    "gmail_query",
    "mask",
    "merchant_for",
    "read_receipt",
]
