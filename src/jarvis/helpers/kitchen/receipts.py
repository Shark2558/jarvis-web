# src/jarvis/helpers/kitchen/receipts.py
"""One e-mailed grocery receipt into facts (docs/plans/r11-free-helpers.md D15, item 15). Pure,
deterministic, no model, no network: the parcels reader's pattern (`jarvis.packages`).

- Only a sender of a FIXED grocery merchant list counts, and only when Gmail's own
  `Authentication-Results` says dkim=pass or dmarc=pass for that merchant's domain
  (`packages.carriers.authenticated`): a From line alone proves nothing. Unknown or unaligned
  senders are ignored. Three merchants share a domain with other shops, so their mail must also
  name the grocery service (Swiggy "Instamart", Amazon "Fresh", Flipkart "Minutes"), and the
  Gmail query asks for that word too. A mail with more than about 1 MB of text is not parsed.
- The text is read line by line (NFKC, whitespace runs as one space), and every run of 12 or more
  digits, whatever separates them (spaces, dots, dashes, slashes: a 4-4-4-4 card, Amex 4-6-5, an
  account number), is masked first, so a card number can never become an amount, a key or a log
  line. Amazon's 3-7-7 order id stays (it keys the order); "ending 1111" stays.
- The total is read only from a labelled total line ("Order total", "Grand total", "Amount paid",
  "Total" ... at the start of a line) that carries a currency marker (₹, Rs, INR), and the amount
  must end there: no digit group can be the start of a longer number. The strongest label wins
  (a bare "Total" only when there is no other). Above ₹25,000 it is flagged, not counted.
- The order's key is a keyed hash (the caller's `mac`, the keyring's `spend` key) of the merchant
  and the order id (`packages.parse.find_order_id`), or of the message id when there is none, so
  the confirmation and the delivery mail of one order count once. A cancelled or refunded order
  (`packages.parse.detect_status`) is marked, so its total is dropped.
Nothing from the mail is kept but the merchant's name from the table, the day and the amount.
EVERY sender domain below is *unverified* against real mail (the build had none).
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from email.utils import parseaddr, parsedate_to_datetime
from typing import Any
from zoneinfo import ZoneInfo

from jarvis.packages.carriers import authenticated, domain_of
from jarvis.packages.parse import detect_status, find_order_id
from jarvis.tools.addresses import loose_address
from jarvis.tools.card import one_line
from jarvis.tools.gmail_mime import headers_of, parse_body

MASKED = "[number removed]"
SCAN_CHARS = 12_000
MAX_LINES = 400
MAX_BODY_B64 = 1_400_000  # about 1 MB of mail text: no receipt is that big
MAX_PARTS = 64
PLAUSIBLE_PAISE = 2_500_000  # ₹25,000: a grocery order above this is flagged, never counted
_NUMBERISH = re.compile(r"(?<![^\W_])\d(?:[ \t.\-/]{1,3}\d|\d){11,}(?![^\W_])")
_AMAZON_ID = re.compile(r"\d{3}-\d{7}-\d{7}")
_STRONG = (
    r"grand\s+total|order\s+total|bill\s+total|total\s+amount(?:\s+paid)?|amount\s+paid|"
    r"total\s+paid|paid\s+amount|total\s+payable|net\s+payable|amount\s+payable|you\s+paid"
)
_TOTAL_LINE = re.compile(
    rf"^[^0-9A-Za-z₹]{{0,3}}(?P<label>{_STRONG}|total)(?:\s*\([^)]{{0,30}}\))?[\s:|\-–]{{0,6}}"
    r"(?:₹|rs\.?|inr)\s{0,3}(?P<int>[0-9]{1,3}(?:,[0-9]{2,3})+|[0-9]{1,9})(?:\.(?P<dec>[0-9]{1,2}))?"
    r"(?:/-)?\.?(?=[\s|*]*$|\s+[^0-9\s.,\-/|])",
    re.IGNORECASE,
)
_GONE = frozenset({"cancelled", "refunded", "returned"})


@dataclass(frozen=True)
class Merchant:
    key: str
    name: str
    domains: tuple[str, ...]
    needs: re.Pattern[str] | None = None  # the grocery service must be named (a shared domain)
    ask: str = ""  # ... and the Gmail query asks for it


def _re(p: str) -> re.Pattern[str]:
    return re.compile(p, re.IGNORECASE)


MERCHANTS: tuple[Merchant, ...] = (
    Merchant("bigbasket", "BigBasket", ("bigbasket.com",)),
    Merchant("blinkit", "Blinkit", ("blinkit.com",)),
    Merchant("zepto", "Zepto", ("zeptonow.com",)),
    Merchant("instamart", "Swiggy Instamart", ("swiggy.in",), _re(r"\binstamart\b"), "instamart"),
    Merchant("jiomart", "JioMart", ("jiomart.com",)),
    Merchant(
        "amazonfresh", "Amazon Fresh", ("amazon.in",), _re(r"\bamazon\s+fresh\b"), '"amazon fresh"'
    ),
    Merchant(
        "fkminutes",
        "Flipkart Minutes",
        ("flipkart.com",),
        _re(r"\bflipkart\s+minutes\b"),
        '"flipkart minutes"',
    ),
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
    flagged: bool = False  # a total too large for groceries: shown as "not counted", never added


def _masked(m: re.Match[str]) -> str:
    return m.group(0) if _AMAZON_ID.fullmatch(m.group(0)) else MASKED


def mask(text: str) -> str:
    """Every card- or account-like number replaced: 12 or more digits, whatever separates them."""
    return _NUMBERISH.sub(_masked, unicodedata.normalize("NFKC", text))


def lines_of(text: str) -> list[str]:
    """Clean, masked, non-empty lines (NFKC; whitespace runs as one space)."""
    raw = unicodedata.normalize("NFKC", str(text)[:SCAN_CHARS])
    flat = (" ".join(line.split()) for line in raw.splitlines()[:MAX_LINES])
    return [mask(line) for line in flat if line]


def merchant_for(sender: str, results: str | None, text: str) -> tuple[Merchant, str] | None:
    """The merchant and its table domain when `sender` is one AND Gmail vouched for it."""
    host = domain_of(sender)
    for m in MERCHANTS:
        for d in m.domains:
            if (host == d or host.endswith("." + d)) and authenticated(results, d):
                if m.needs is None or m.needs.search(text):
                    return m, d
    return None


def _paise(m: re.Match[str]) -> int | None:
    try:
        rupees = Decimal(m.group("int").replace(",", "") + "." + (m.group("dec") or "0"))
    except InvalidOperation:
        return None
    paise = int((rupees * 100).to_integral_value())
    return paise if paise >= 100 else None


def find_total(text: str) -> int | None:
    """The amount of the strongest labelled total line, in paise (₹1 or more); else None."""
    found = [m for line in lines_of(text) if (m := _TOTAL_LINE.match(line))]
    found.sort(key=lambda m: m.group("label").casefold() == "total")  # stable: first strongest
    return _paise(found[0]) if found else None


def too_big(payload: dict[str, Any]) -> bool:
    """True when the mail's parts hold more text than any receipt (checked before parsing)."""
    total, stack, parts = 0, [payload], 0
    while stack:
        part, parts = stack.pop(), parts + 1
        if parts > MAX_PARTS:
            return True
        body = part.get("body") if isinstance(part, dict) else None
        data = body.get("data") if isinstance(body, dict) else None
        total += len(data) if isinstance(data, str) else 0
        kids = part.get("parts") if isinstance(part, dict) else None
        stack.extend(k for k in kids or () if isinstance(k, dict))
    return total > MAX_BODY_B64


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
    if not isinstance(payload, dict) or not isinstance(m.get("id"), str) or too_big(payload):
        return None
    h = headers_of(payload)
    sender = loose_address(parseaddr(one_line(h.get("from", ""), 600))[1])
    subject = mask(one_line(h.get("subject", ""), 300))
    body = "\n".join(lines_of(parse_body(payload).text))
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
    if paise is None:
        return None
    if paise > PLAUSIBLE_PAISE:
        return Receipt(key, merchant.name, day, 0, flagged=True)
    return Receipt(key, merchant.name, day, paise)


def gmail_query(days: int) -> str:
    """The fixed merchants' mail; a shared domain only with its grocery service's name."""
    plain = " OR ".join(d for m in MERCHANTS if not m.ask for d in m.domains)
    shared = " OR ".join(f"(from:{d} {m.ask})" for m in MERCHANTS if m.ask for d in m.domains)
    return f"(from:({plain}) OR {shared}) newer_than:{days}d"


__all__ = [
    "MASKED",
    "MAX_BODY_B64",
    "MERCHANTS",
    "PLAUSIBLE_PAISE",
    "Merchant",
    "Receipt",
    "find_total",
    "gmail_query",
    "lines_of",
    "mask",
    "merchant_for",
    "read_receipt",
]
