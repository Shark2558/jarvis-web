# src/jarvis/helpers/today/models.py
"""Part A's records and their checks (docs/plans/r11-free-helpers.md D7, data model). Pure, no I/O.

- `Bill`: his label (≤ 40), the payee's name (≤ 40), the UPI ID (NPCI's shape only; set only by
  his own entry), the amount in paise (None = "varies"), the due rule, the reminder lead days
  (default 3, 1 and the day), at most the last 4 digits of an account, and what he has paid (≤ 24).
- No card, account or consumer number is ever kept: a run of 5 or more digits, or a card-like
  13-19 digits with single spaces or hyphens, in any text field is refused; a UPI ID with 11 or
  more digits in a row (more than a mobile number) is refused too.
- `Due`: once (`every_months` 0) or every N months from `start`, on the start's day of the month,
  clamped to a short month (31 → 30 Nov, 28 Feb).
- Money: paise in, `inr()` out with the Indian grouping ("₹1,00,000.00").
"""

from __future__ import annotations

import calendar
import re
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Annotated, Any

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, field_validator

from jarvis.tools.card import one_line

LABEL_MAX = 40
PAYEE_MAX = 40
NOTE_MAX = 50
MAX_BILLS = 50
MAX_PAID = 24
MAX_LEAD = 14
MAX_EVERY = 12
DEFAULT_LEADS = (3, 1, 0)
PAY_CAP_PAISE = 1_00_000 * 100  # owner decision 12: ₹1,00,000 per prepared payment
MAX_BILL_PAISE = 1_00_00_000 * 100  # what a bill may say it costs (a prepared one: the cap)
BILL_ID = re.compile(r"^[0-9a-f]{12}$")
UPI_ID = re.compile(r"^[A-Za-z0-9._-]{2,256}@[A-Za-z][A-Za-z0-9]{1,63}$")
_LONG_RUN = re.compile(r"\d{5,}")
_CARD_LIKE = re.compile(r"(?<!\d)(?:\d[ -]?){12,18}\d(?!\d)")
_UPI_DIGITS = re.compile(r"\d{11,}")
_AMOUNT = re.compile(r"^\d{1,12}(?:\.\d{1,2})?$")
_HHMM = re.compile(r"^(?:[01]\d|2[0-3]):[0-5]\d$")
VARIES = "varies"
NUMBER_REFUSAL = (
    "Keep card, account and consumer numbers out of your bills, Sir: the last 4 digits at most."
)


class BillRefused(ValueError):
    """A bill value JARVIS won't keep or use; the message is plain words for the owner."""


def has_number(text: str) -> bool:
    """A card, account or consumer number in `text` (a date or a year is fine)."""
    return bool(_LONG_RUN.search(text) or _CARD_LIKE.search(text))


def _text(value: Any, limit: int, what: str, *, empty_ok: bool = False) -> str:
    if value is None and empty_ok:
        return ""
    if not isinstance(value, str):
        raise BillRefused(f"The {what} must be text.")
    flat = one_line(value, limit + 1)
    if not flat and not empty_ok:
        raise BillRefused(f"The {what} is empty.")
    if len(flat) > limit:
        raise BillRefused(f"The {what} can be at most {limit} characters.")
    if has_number(flat):
        raise BillRefused(NUMBER_REFUSAL)
    return flat


def clean_label(value: Any) -> str:
    return _text(value, LABEL_MAX, "bill's name")


def clean_payee(value: Any) -> str:
    return _text(value, PAYEE_MAX, "payee's name", empty_ok=True)


def clean_note(value: Any) -> str:
    return _text(value, NOTE_MAX, "note", empty_ok=True)


def parse_upi(value: Any) -> str:
    """A UPI ID in NPCI's shape (D7), or BillRefused in plain words."""
    raw = value.strip() if isinstance(value, str) else ""
    if not UPI_ID.fullmatch(raw):
        raise BillRefused("That isn't a UPI ID (like name@bank), Sir.")
    if _UPI_DIGITS.search(raw):
        raise BillRefused(NUMBER_REFUSAL)
    return raw


def last_four(value: Any) -> str:
    raw = value.strip() if isinstance(value, str) else ""
    if raw and not re.fullmatch(r"\d{4}", raw):
        raise BillRefused(NUMBER_REFUSAL)
    return raw


def parse_amount(value: Any) -> int | None:
    """Rupees (a number, or text like "1,240.50" / "₹1,240") as paise; "varies" is None."""
    if isinstance(value, bool):
        raise BillRefused("The amount must be a number of rupees, or 'varies'.")
    if isinstance(value, str) and value.strip().lower() == VARIES:
        return None
    text = value if isinstance(value, str) else str(value) if isinstance(value, int | float) else ""
    text = text.strip().replace("₹", "").replace(",", "").replace("Rs.", "").strip()
    if not _AMOUNT.fullmatch(text):
        raise BillRefused("The amount must be rupees with at most 2 decimals, or 'varies'.")
    try:
        paise = int(Decimal(text) * 100)
    except InvalidOperation:
        raise BillRefused("The amount must be a number of rupees.") from None
    if not 0 < paise <= MAX_BILL_PAISE:
        raise BillRefused("The amount must be more than ₹0.")
    return paise


def _grouped(rupees: int) -> str:
    """Indian digit grouping: 12,34,567."""
    s = str(rupees)
    if len(s) <= 3:
        return s
    head, tail = s[:-3], s[-3:]
    pairs = []
    while len(head) > 2:
        pairs.insert(0, head[-2:])
        head = head[:-2]
    return ",".join([head, *pairs, tail]) if head else ",".join([*pairs, tail])


def inr(paise: int) -> str:
    return f"₹{_grouped(paise // 100)}.{paise % 100:02d}"


def inr_short(paise: int) -> str:
    return f"₹{_grouped(paise // 100)}" if paise % 100 == 0 else inr(paise)


def hhmm(value: Any) -> str:
    if not isinstance(value, str) or not _HHMM.fullmatch(value.strip()):
        raise BillRefused("A time is HH:MM, like 09:00.")
    return value.strip()


def add_months(start: date, months: int) -> date:
    y, m = divmod(start.month - 1 + months, 12)
    year, month = start.year + y, m + 1
    return date(year, month, min(start.day, calendar.monthrange(year, month)[1]))


class Due(BaseModel):
    """Once (`every_months` 0) or every N months from `start` on its day of the month."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    start: date
    every_months: int = Field(default=1, ge=0, le=MAX_EVERY)

    def _index(self, day: date) -> int | None:
        if day < self.start:
            return None
        if self.every_months == 0:
            return 0 if day == self.start else None
        gap = (day.year - self.start.year) * 12 + day.month - self.start.month
        return gap // self.every_months if gap % self.every_months == 0 else None

    def on(self, day: date) -> bool:
        n = self._index(day)
        return n is not None and add_months(self.start, n * self.every_months) == day

    def dates_between(self, first: date, last: date) -> list[date]:
        """Every due date in [first, last], in order (at most a few dozen)."""
        if self.every_months == 0:
            return [self.start] if first <= self.start <= last else []
        out: list[date] = []
        n = 0
        while (d := add_months(self.start, n * self.every_months)) <= last and n < 400:
            if d >= first:
                out.append(d)
            n += 1
        return out


class Paid(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    due: date
    on: date


Label = Annotated[str, AfterValidator(clean_label)]
Payee = Annotated[str, AfterValidator(clean_payee)]


class Bill(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str = Field(pattern=BILL_ID.pattern)
    label: Label
    payee: Payee = ""
    upi: str = ""
    amount: int | None = Field(default=None, gt=0, le=MAX_BILL_PAISE)
    due: Due
    leads: tuple[int, ...] = DEFAULT_LEADS
    last4: str = ""
    paid: tuple[Paid, ...] = Field(default=(), max_length=MAX_PAID)
    added: date | None = None

    @field_validator("upi")
    @classmethod
    def _upi(cls, v: str) -> str:
        return parse_upi(v) if v else ""

    @field_validator("last4")
    @classmethod
    def _last4(cls, v: str) -> str:
        return last_four(v)

    @field_validator("leads")
    @classmethod
    def _leads(cls, v: tuple[int, ...]) -> tuple[int, ...]:
        if not v or len(v) > 4 or any(not 0 <= d <= MAX_LEAD for d in v):
            raise BillRefused(f"Reminder days are 0 to {MAX_LEAD} days before, at most 4 of them.")
        return tuple(sorted(set(v), reverse=True))

    def paid_for(self, due: date) -> bool:
        return any(p.due == due for p in self.paid)

    def note(self, due: date) -> str:
        """The UPI note (tn): his label and the due month, ≤ 50 characters."""
        return one_line(f"{self.label} {due.strftime('%b')}", NOTE_MAX)


class Prefs(BaseModel):
    """His Part A choices: when bill and birthday reminders go, and whether birthdays are on."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    bills_at: str = "09:00"
    birthdays_on: bool = False
    birthday_at: str = "08:30"

    @field_validator("bills_at", "birthday_at")
    @classmethod
    def _times(cls, v: str) -> str:
        return hhmm(v)


__all__ = [
    "BILL_ID",
    "DEFAULT_LEADS",
    "LABEL_MAX",
    "MAX_BILLS",
    "MAX_PAID",
    "NOTE_MAX",
    "NUMBER_REFUSAL",
    "PAYEE_MAX",
    "PAY_CAP_PAISE",
    "UPI_ID",
    "VARIES",
    "Bill",
    "BillRefused",
    "Due",
    "Paid",
    "Prefs",
    "add_months",
    "clean_label",
    "clean_note",
    "clean_payee",
    "has_number",
    "hhmm",
    "inr",
    "inr_short",
    "last_four",
    "parse_amount",
    "parse_upi",
]
