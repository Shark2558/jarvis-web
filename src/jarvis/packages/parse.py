# src/jarvis/packages/parse.py
"""Read one order / shipping email into facts (R1 D13). Pure, deterministic, no model, no network.

What is extracted, and how it is kept honest:
  - tracking number: only from a sender in the carrier table, only right after a tracking word,
    only in the format of the carrier the mail names (or a letter-based format when none is named),
    India Post numbers with their S10 check digit verified. Phone numbers, order ids, OTPs and
    amounts are never taken: they never follow a tracking word in a carrier's format.
  - status: a keyword ladder (ordered < shipped < out for delivery < delivered) plus cancelled /
    returned / refunded. The subject is read first, then the start of the body.
  - expected date: "arriving / expected / delivery by ..." phrases, resolved against the mail's own
    Date header (so "Jan 2" in a December mail is next year).
Everything here is heuristic and unverified on real mail (see carriers.py); a miss yields None.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta

from jarvis.packages.carriers import (
    BY_KEY,
    CARRIER_BY_DOMAIN,
    CARRIERS,
    DEFAULT_CARRIER,
    MERCHANTS,
    Carrier,
    known_domain,
    number_ok,
)

BODY_STATUS_CHARS = 1_500
BODY_SCAN_CHARS = 12_000
DATE_WINDOW = 50
STATUS_ORDER = ("ordered", "shipped", "out_for_delivery", "delivered")
TERMINAL = ("cancelled", "returned", "refunded")
CLOSED = frozenset({"delivered", *TERMINAL})
_FLAGS = re.IGNORECASE
RAW_CAP = 60_000  # characters looked at before whitespace is squashed (a hostile body can be huge)


def squash(text: str, cap: int = BODY_SCAN_CHARS) -> str:
    """Hostile-mail guard: every run of Unicode whitespace (NBSP, ideographic space, newlines...)
    becomes ONE space and the text is cut to `cap`, so a pattern can never be fed thousands of
    spaces to backtrack over. Applied at the entry of every scanner here."""
    return " ".join(str(text)[:RAW_CAP].split())[:cap]


# ---- tracking numbers --------------------------------------------------------------------------

_TRACK = re.compile(
    r"(?:tracking|awb|waybill|way\s*bill|consignment|article|docket|shipment|transport\s+reference|lr)"
    r"\s{0,3}(?:id|no\.?|number|num|#|code)?\s{0,3}(?:id|no\.?|number)?\s{0,3}[:#\-–]{0,4}\s{0,3}"
    r"(?:is\s{1,3})?"
    r"([A-Za-z0-9]{8,20})\b",
    _FLAGS,
)


def find_tracking_number(
    text: str, carrier: Carrier | None
) -> tuple[str, Carrier] | tuple[None, None]:
    """The first token that follows a tracking word and is a valid number of `carrier` (or, with
    no carrier named, of a carrier whose format has letters in it)."""
    for m in _TRACK.finditer(squash(text)):
        token = m.group(1).upper()
        if carrier is not None:
            if number_ok(carrier, token):
                return token, carrier
            continue
        for c in CARRIERS:
            if c.distinctive and number_ok(c, token):
                return token, c
    return None, None


# ---- status ------------------------------------------------------------------------------------

_FUTURE = re.compile(
    r"\b(?:will|to|should|shall|be|get|gets|getting|once|when|after|until)\s+(?:be\s+|get\s+)?"
    r"(?:delivered|shipped|dispatched)\b|"
    r"\bdelivered\s+by\s+(?:today|tomorrow|mon|tue|wed|thu|fri|sat|sun|\d|jan|feb|mar|apr|may|"
    r"jun|jul|aug|sep|oct|nov|dec)",
    _FLAGS,
)
_PATTERNS: dict[str, re.Pattern[str]] = {
    "returned": re.compile(
        r"return\s+(?:request\s+|has been\s+|is\s+)?(?:initiated|picked up|received|completed)|"
        r"has been returned|is being returned|returned to (?:seller|sender)",
        _FLAGS,
    ),
    "cancelled": re.compile(
        r"(?:has been|was|is|been)\s+cancel+ed|order\s+cancel+ed|cancel+ation of your order",
        _FLAGS,
    ),
    "refunded": re.compile(
        r"refund\s+(?:has been\s+|is\s+)?(?:initiated|processed|issued|credited)|"
        r"has been refunded",
        _FLAGS,
    ),
    "delivered": re.compile(r"\bdelivered\b", _FLAGS),
    "out_for_delivery": re.compile(r"out for delivery|arriving today", _FLAGS),
    "shipped": re.compile(
        r"\bshipped\b|\bdispatched\b|on (?:its|the) way|in transit|picked up by", _FLAGS
    ),
    "ordered": re.compile(
        r"order\s+(?:is\s+)?(?:confirmed|placed|received)|"
        r"thank(?:s| you) for (?:your )?order(?:ing)?|"
        r"we(?:'ve| have) received your order|order confirmation",
        _FLAGS,
    ),
}
_CHECK_ORDER = ("returned", "cancelled", "refunded", "delivered", "out_for_delivery", "shipped")


def _status_in(text: str) -> str | None:
    t = _FUTURE.sub(" ", squash(text, BODY_STATUS_CHARS))
    for key in _CHECK_ORDER:
        if _PATTERNS[key].search(t):
            return key
    if _PATTERNS["ordered"].search(text):
        return "ordered"
    return None


def detect_status(subject: str, body: str) -> str | None:
    return _status_in(subject) or _status_in(body)


# ---- expected date -----------------------------------------------------------------------------

_MONTHS = {m: i for i, m in enumerate("jan feb mar apr may jun jul aug sep oct nov dec".split(), 1)}
_DAYS = {d: i for i, d in enumerate("mon tue wed thu fri sat sun".split())}
_MON = r"(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?"
_WD = r"(?:(mon|tue|wed|thu|fri|sat|sun)[a-z]*\.?,?\s+)?"
_PHRASE = re.compile(
    r"arriv(?:ing|es|al)|expected|delivery\s+by|delivered\s+by|estimated\s+delivery|"
    r"will\s+(?:arrive|be\s+delivered)|get\s+it\s+by|deliver(?:y|ed)?\s+on|by\s+end\s+of",
    _FLAGS,
)
_DAY_MON = re.compile(
    rf"{_WD}(\d{{1,2}})(?:st|nd|rd|th)?\s+(?:of\s+)?{_MON}(?:,?\s+(\d{{4}}))?", _FLAGS
)
_MON_DAY = re.compile(rf"{_WD}{_MON}\s+(\d{{1,2}})(?:st|nd|rd|th)?(?:,?\s+(\d{{4}}))?", _FLAGS)
_NUMERIC = re.compile(r"\b(\d{1,2})[/-](\d{1,2})[/-](\d{4})\b")
_REL = re.compile(r"\b(today|tomorrow)\b", _FLAGS)
_WEEKDAY = re.compile(r"\b(mon|tue|wed|thu|fri|sat|sun)[a-z]*\b", _FLAGS)
ROLLOVER_DAYS = 60


def _resolve(day: int, month: int, year: int | None, base: date) -> date | None:
    try:
        if year is not None:
            return date(year, month, day)
        cand = date(base.year, month, day)
        if cand < base - timedelta(days=ROLLOVER_DAYS):
            cand = date(base.year + 1, month, day)
        elif cand > base + timedelta(days=300):
            cand = date(base.year - 1, month, day)
        return cand
    except ValueError:
        return None


def _first_date(window: str, base: date) -> tuple[int, date] | None:
    found: list[tuple[int, date]] = []
    for m in _DAY_MON.finditer(window):
        d = _resolve(int(m.group(2)), _MONTHS[m.group(3).lower()], _int(m.group(4)), base)
        if d:
            found.append((m.start(), d))
    for m in _MON_DAY.finditer(window):
        d = _resolve(int(m.group(3)), _MONTHS[m.group(2).lower()], _int(m.group(4)), base)
        if d:
            found.append((m.start(), d))
    for m in _NUMERIC.finditer(window):
        d = _resolve(int(m.group(1)), int(m.group(2)), int(m.group(3)), base)
        if d:
            found.append((m.start(), d))
    for m in _REL.finditer(window):
        found.append(
            (m.start(), base + timedelta(days=1 if m.group(1).lower() == "tomorrow" else 0))
        )
    for m in _WEEKDAY.finditer(window):
        target = _DAYS[m.group(1).lower()[:3]]
        found.append((m.start(), base + timedelta(days=(target - base.weekday()) % 7)))
    return min(found, key=lambda x: x[0]) if found else None


def _int(value: str | None) -> int | None:
    return int(value) if value else None


def detect_expected(text: str, sent: date) -> date | None:
    best: tuple[int, date] | None = None
    text = squash(text)
    for m in _PHRASE.finditer(text):
        hit = _first_date(text[m.end() : m.end() + DATE_WINDOW], sent)
        if hit is not None and (best is None or m.end() + hit[0] < best[0]):
            best = (m.end() + hit[0], hit[1])
    return best[1] if best else None


# ---- order ids (to group mails of one parcel) ---------------------------------------------------

_ORDER_PATTERNS = (
    re.compile(r"\b(\d{3}-\d{7}-\d{7})\b"),  # Amazon order id
    re.compile(r"\b(OD\d{15,20})\b"),  # Flipkart order id
    re.compile(
        r"order\s{0,3}(?:id|no\.?|number|#)?\s{0,3}[:#]?\s{0,3}([A-Z0-9][A-Z0-9-]{5,24})\b", _FLAGS
    ),
)


def find_order_id(text: str) -> str | None:
    text = squash(text)
    for pat in _ORDER_PATTERNS:
        for m in pat.finditer(text):
            token = m.group(1).upper()
            if any(ch.isdigit() for ch in token):
                return token
    return None


# ---- one mail ----------------------------------------------------------------------------------


@dataclass(frozen=True)
class MailFacts:
    message_id: str
    sender: str
    subject: str
    sent: datetime
    domain: str | None  # the table domain of the sender; None = not a known sender
    merchant: str | None
    carrier: str | None  # carrier key
    tracking_number: str | None
    status: str | None
    expected: date | None
    order_id: str | None


def _carrier_for(domain: str | None, text: str, *, default: bool = False) -> Carrier | None:
    if domain in CARRIER_BY_DOMAIN:
        return BY_KEY[CARRIER_BY_DOMAIN[domain]]
    named = [(m.start(), c) for c in CARRIERS if (m := c.mention.search(text))]
    if named:
        return min(named, key=lambda x: x[0])[1]
    if default and domain in DEFAULT_CARRIER:
        return BY_KEY[DEFAULT_CARRIER[domain]]
    return None


def _merchant(domain: str | None, carrier: Carrier | None, text: str) -> str | None:
    if domain in MERCHANTS:
        if domain == "swiggy.in" and "instamart" in text.casefold():
            return "Swiggy Instamart"
        return MERCHANTS[domain]
    if domain in CARRIER_BY_DOMAIN and carrier is not None:
        return carrier.name
    return None


def parse_mail(
    *,
    message_id: str,
    sender: str,
    subject: str,
    sent: datetime,
    body: str,
    find_number=find_tracking_number,  # noqa: ANN001 -- injectable so the eval can break it
) -> MailFacts:
    """`sender` is the bare From address. `body` is the plain text of the message."""
    if sent.tzinfo is None:
        sent = sent.replace(tzinfo=UTC)
    domain = known_domain(sender)
    subject, body = squash(subject, 300), squash(body)
    text = f"{subject}\n{body}"
    named = _carrier_for(domain, text) if domain else None
    number = used = None
    if domain:  # a stranger's mail never yields a tracking number
        number, used = find_number(text, named or _carrier_for(domain, text, default=True))
    chosen = used or named
    return MailFacts(
        message_id=message_id,
        sender=sender,
        subject=subject,
        sent=sent,
        domain=domain,
        merchant=_merchant(domain, chosen, text),
        carrier=chosen.key if chosen else None,
        tracking_number=number,
        status=detect_status(subject, body),
        expected=detect_expected(text, sent.date()),
        order_id=find_order_id(text),
    )


# ---- one parcel from many mails ---------------------------------------------------------------


@dataclass(frozen=True)
class Package:
    merchant: str | None
    item: str  # the newest mail's subject (someone else's words: the tool fences it)
    carrier: str | None
    tracking_number: str | None
    status: str
    expected: date | None
    updated: datetime
    message_id: str
    known_sender: bool
    link: str | None = None
    mails: int = 1


def _keys(f: MailFacts) -> list[str]:
    keys = []
    if f.order_id:
        keys.append(f"order:{f.domain or f.sender}:{f.order_id}")
    if f.tracking_number and f.carrier:
        keys.append(f"track:{f.carrier}:{f.tracking_number}")
    return keys or [f"mail:{f.message_id}"]


def link_for(carrier_key: str | None, number: str | None) -> str | None:
    """A tracking link ONLY from the carrier table, and only where one was verified."""
    c = BY_KEY.get(carrier_key or "")
    if c is None or c.link is None or not number or not c.number.fullmatch(number):
        return None
    return c.link.format(number=number)


def build_packages(mails: Iterable[MailFacts]) -> list[Package]:
    """Group mails of one parcel (same order id, or same carrier + number); the newest mail that
    says anything about status wins; number / carrier / date from the newest mail that has one."""
    groups: list[list[MailFacts]] = []
    index: dict[str, int] = {}
    for f in sorted(mails, key=lambda m: m.sent):
        hit = {index[k] for k in _keys(f) if k in index}
        if not hit:
            groups.append([f])
            at = len(groups) - 1
        else:
            at = min(hit)
            groups[at].append(f)
            for other in sorted(hit - {at}, reverse=True):  # merge groups the mail bridges
                groups[at].extend(groups[other])
                groups[other] = []
        index.clear()
        for g_i, g in enumerate(groups):
            for m in g:
                for k in _keys(m):
                    index[k] = g_i
    out = []
    for g in groups:
        if not g:
            continue
        g.sort(key=lambda m: m.sent)
        out.append(_package(g))
    out.sort(key=lambda p: (p.status in CLOSED, -p.updated.timestamp()))
    return out


def _newest(g: list[MailFacts], attr: str) -> MailFacts | None:
    return next((m for m in reversed(g) if getattr(m, attr)), None)


def _package(g: list[MailFacts]) -> Package:
    last = g[-1]
    st = _newest(g, "status")
    status = st.status if st and st.status else "ordered"
    num = _newest(g, "tracking_number")
    car = num or _newest(g, "carrier")
    exp = _newest(g, "expected")
    mer = _newest(g, "merchant")
    expected = exp.expected if exp and status not in CLOSED else None
    carrier = car.carrier if car else None
    number = num.tracking_number if num else None
    return Package(
        merchant=mer.merchant if mer else None,
        item=last.subject,
        carrier=carrier,
        tracking_number=number,
        status=status,
        expected=expected,
        updated=last.sent,
        message_id=last.message_id,
        known_sender=any(m.domain for m in g),
        link=link_for(carrier, number),
        mails=len(g),
    )


def carrier_name(key: str | None) -> str | None:
    c = BY_KEY.get(key or "")
    return c.name if c else None


__all__ = [
    "CLOSED",
    "MailFacts",
    "Package",
    "build_packages",
    "carrier_name",
    "detect_expected",
    "detect_status",
    "find_order_id",
    "find_tracking_number",
    "link_for",
    "parse_mail",
]
