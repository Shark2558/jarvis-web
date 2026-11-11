# src/jarvis/helpers/today/models.py
"""Part A's records and their checks (docs/plans/r11-free-helpers.md D7, data model). Pure, no I/O.

- `Bill`: his label (≤ 40, no `@`), the payee's name (≤ 40, in `text.payee_name`'s safe set),
  the UPI ID (NPCI's shape only; set only by his own entry), the amount in paise (None =
  "varies"), the due rule, the reminder lead days (default 3, 1 and the day), at most the last 4
  digits of an account (`last4`, the one place the plan allows digits of one), and what he has
  paid (≤ 24). `pay_name` is who the UPI app shows as paid: the payee, or the label's safe name.
- No card, account or consumer number is ever kept: `text.has_number` (one check for every field,
  the note and the UPI ID) refuses 13+ digits joined across any separators, or 5 digits in a row
  (11 in a UPI ID: more than a mobile number).
- `Due`: once (`every_months` 0) or every N months from `start`, on `day` of the month (the day
  he asked for), which falls on a short month's last day: a day-31 bill is due 28 Feb (29 in a
  leap year), 31 Mar, 30 Apr. A document from before `day` was kept reads with the start's day.
- Money: paise in (ASCII digits only), `inr()` out with the Indian grouping ("₹1,00,000.00").
"""

from __future__ import annotations

import calendar
import re
import unicodedata
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Annotated, Any

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, field_validator, model_validator

from jarvis.helpers.today.text import (
    NUMBER_REFUSAL,
    PAYEE_MAX,
    UPI_PLAIN_MAX,
    BillRefused,
    has_number,
    name_from_label,
    payee_name,
)
from jarvis.tools.card import one_line

LABEL_MAX = 40
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
_AMOUNT = re.compile(r"^[0-9]{1,12}(?:\.[0-9]{1,2})?$")
_LAST4 = re.compile(r"[0-9]{4}")
_HHMM = re.compile(r"^(?:[01][0-9]|2[0-3]):[0-5][0-9]$")
VARIES = "varies"
AT_REFUSAL = "A bill's name or note can't hold an @, Sir: a UPI ID goes only in its own field."


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
    if "@" in unicodedata.normalize("NFKC", flat):  # a label must not read as a UPI ID
        raise BillRefused(AT_REFUSAL)
    return flat


def clean_label(value: Any) -> str:
    return _text(value, LABEL_MAX, "bill's name")


def clean_payee(value: Any) -> str:
    """The payee's name in the safe set (`text.payee_name`): it can't imitate a UPI ID."""
    return payee_name(value)


def clean_note(value: Any) -> str:
    return _text(value, NOTE_MAX, "note", empty_ok=True)


def parse_upi(value: Any) -> str:
    """A UPI ID in NPCI's shape (D7), or BillRefused in plain words."""
    raw = value.strip() if isinstance(value, str) else ""
    if not UPI_ID.fullmatch(raw):
        raise BillRefused("That isn't a UPI ID (like name@bank), Sir.")
    if has_number(raw, plain_max=UPI_PLAIN_MAX):
        raise BillRefused(NUMBER_REFUSAL)
    return raw


def last_four(value: Any) -> str:
    raw = value.strip() if isinstance(value, str) else ""
    if raw and not _LAST4.fullmatch(raw):
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
    pairs: list[str] = []
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


def on_day(year: int, month: int, day: int) -> date:
    """`day` of that month, or its last day when the month is shorter (31 → 30 Apr, 28 Feb)."""
    return date(year, month, min(day, calendar.monthrange(year, month)[1]))


def add_months(start: date, months: int, day: int | None = None) -> date:
    """`months` after `start`, on `day` of the month (default: the start's day), clamped."""
    y, m = divmod(start.month - 1 + months, 12)
    return on_day(start.year + y, m + 1, start.day if day is None else day)


class Due(BaseModel):
    """Once (`every_months` 0) or every N months from `start`, on `day` of the month."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    start: date
    every_months: int = Field(default=1, ge=0, le=MAX_EVERY)
    day: int = Field(ge=1, le=31)

    @model_validator(mode="before")
    @classmethod
    def _anchor(cls, data: Any) -> Any:
        """A document from before `day` was kept: the start's own day of the month."""
        if isinstance(data, dict) and data.get("day") is None and "start" in data:
            start = data["start"]
            start = start if isinstance(start, date) else date.fromisoformat(str(start))
            return {**data, "day": start.day}
        return data

    @model_validator(mode="after")
    def _fits(self) -> Due:
        if on_day(self.start.year, self.start.month, self.day) != self.start:
            raise ValueError("the first due date is not on the bill's day of the month")
        return self

    def nth(self, n: int) -> date:
        """The n-th due date (0 is `start`)."""
        return add_months(self.start, n * self.every_months, self.day)

    def _index(self, day: date) -> int | None:
        if day < self.start:
            return None
        if self.every_months == 0:
            return 0 if day == self.start else None
        gap = (day.year - self.start.year) * 12 + day.month - self.start.month
        return gap // self.every_months if gap % self.every_months == 0 else None

    def on(self, day: date) -> bool:
        n = self._index(day)
        return n is not None and self.nth(n) == day

    def dates_between(self, first: date, last: date) -> list[date]:
        """Every due date in [first, last], in order (at most a few dozen)."""
        if self.every_months == 0:
            return [self.start] if first <= self.start <= last else []
        out: list[date] = []
        n = 0
        while (d := self.nth(n)) <= last and n < 400:
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

    @property
    def pay_name(self) -> str:
        """Who the UPI app shows as paid (`pn`, and the card): the payee, or the label's name."""
        return self.payee or name_from_label(self.label)

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
    "AT_REFUSAL",
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
    "on_day",
    "parse_amount",
    "parse_upi",
]
