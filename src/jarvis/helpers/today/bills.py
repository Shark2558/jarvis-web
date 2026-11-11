# src/jarvis/helpers/today/bills.py
"""Bills and the prepared UPI payment (docs/plans/r11-free-helpers.md D7, item 1). Plain code.

- His own entry: `add` (label, payee name, UPI ID, amount or "varies", a day of the month or a
  date, every N months, lead days, at most the last 4 digits) and `set_payee`. Each value is
  checked by `models` (no card, account or consumer number anywhere); the UPI ID is set only here,
  by him: from the Today tab, or by the R3 `bill_payee_set` that refuses a tainted round (tools).
- `reminders_due(bill, today)`: which reminders are owed today, (due date, offset): each lead day
  (default 3, 1, 0) before an unpaid due date, and once "overdue" on the day after (offset -1).
  A due date before the day he added the bill is never "overdue".
- `prepare`: the payment the R3 card describes, from his saved bill only (amount within the
  ₹1,00,000 cap; a "varies" bill needs the amount said): `Prepared.card` is the exact card text.
- `make_ready` (after the approval) leaves a 10-minute sealed grant; `payment` spends it once and
  only then makes the `upi://pay` link and its QR, which go to his screen and nowhere else.
"""

from __future__ import annotations

import calendar
import secrets
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from typing import Any

from jarvis.helpers.today.models import (
    DEFAULT_LEADS,
    Bill,
    BillRefused,
    Due,
    Paid,
    Prefs,
    add_months,
    clean_label,
    clean_payee,
    inr,
    inr_short,
    last_four,
    parse_amount,
    parse_upi,
)
from jarvis.helpers.today.qr import qr_data_uri
from jarvis.helpers.today.store import READY_FOR, BillStore, Book, Grant
from jarvis.helpers.today.upi import amount_text, upi_link
from jarvis.notify.quiet import local

OVERDUE = -1
LOOK_BACK = timedelta(days=40)  # an unpaid due date this old is still "overdue"
LOOK_AHEAD = timedelta(days=400)
NO_UPI = "This bill has no UPI ID yet, Sir. Type it yourself in Helpers → Today."
VARIES_NEEDS = "This bill's amount varies, Sir: say how much to pay."


def day_text(d: date) -> str:
    return d.strftime("%a %d %b").replace(" 0", " ")


def reminders_due(bill: Bill, today: date) -> list[tuple[date, int]]:
    """(due date, offset) of every reminder owed today; offset -1 = overdue since yesterday."""
    out: list[tuple[date, int]] = []
    for off in (*bill.leads, OVERDUE):
        due = today + timedelta(days=off)
        if not bill.due.on(due) or bill.paid_for(due):
            continue
        if bill.added is not None and due < bill.added:
            continue
        out.append((due, off))
    return out


def current_due(bill: Bill, today: date) -> date | None:
    """The earliest unpaid due date from LOOK_BACK ago (and not before he added it) onwards."""
    first = max(today - LOOK_BACK, bill.added or today - LOOK_BACK)
    for d in bill.due.dates_between(first, today + LOOK_AHEAD):
        if not bill.paid_for(d):
            return d
    return None


def when_words(due: date, today: date) -> str:
    gap = (due - today).days
    if gap == 0:
        return "due today"
    if gap == 1:
        return "due tomorrow"
    if gap < 0:
        return f"overdue since {day_text(due)}"
    return f"due {day_text(due)}"


def amount_words(bill: Bill) -> str:
    return inr_short(bill.amount) if bill.amount is not None else "(amount varies)"


def reminder_text(bill: Bill, due: date, off: int) -> str:
    """The `bill_due` alert: JARVIS's fixed template with his own label and amount (≤ 300)."""
    what = f"{bill.label} {amount_words(bill)}"
    if off == OVERDUE:
        return f"Bill reminder, Sir: {what} was due yesterday and isn't marked paid. Open JARVIS."
    when = {0: "is due today", 1: "is due tomorrow"}.get(off, f"is due in {off} days")
    return (
        f"Bill reminder, Sir: {what} {when} ({day_text(due)}). Open JARVIS to get the payment "
        "ready."
    )


@dataclass(frozen=True)
class Prepared:
    bill: Bill
    paise: int
    due: date
    card: str


@dataclass(frozen=True)
class Payment:
    """Shown once on his screen; never stored or logged."""

    link: str
    qr: str
    upi: str
    payee: str
    amount: str
    note: str


def card_text(bill: Bill, paise: int, due: date) -> str:
    payee = bill.payee or bill.label
    return (
        f"Get a UPI payment ready: {inr(paise)} to {payee} ({bill.upi}), note '{bill.note(due)}'. "
        "You confirm it and enter your PIN in your UPI app. JARVIS never pays."
    )


def _start(today: date, day: Any, on: Any) -> date:
    if on is not None:
        try:
            return on if isinstance(on, date) else date.fromisoformat(str(on))
        except ValueError:
            raise BillRefused("A due date is YYYY-MM-DD.") from None
    if isinstance(day, bool) or not isinstance(day, int) or not 1 <= day <= 31:
        raise BillRefused("Give the day of the month (1 to 31) or a due date.")
    for n in (0, 1):
        month = add_months(today.replace(day=1), n)
        d = month.replace(day=min(day, calendar.monthrange(month.year, month.month)[1]))
        if d >= today:
            return d
    raise BillRefused("Give the day of the month (1 to 31) or a due date.")  # pragma: no cover


class BillsService:
    def __init__(self, store: BillStore, *, tz: str, now: Callable[[], datetime]) -> None:
        self.store = store
        self._tz = tz
        self._now = now

    @property
    def tz(self) -> str:
        return self._tz

    def today(self) -> date:
        return local(self._now(), self._tz).date()

    def at_local(self, day: date, hhmm: str) -> datetime:
        """`day` at `hhmm` in his zone, as an aware time."""
        h, m = (int(x) for x in hhmm.split(":"))
        zone = local(self._now(), self._tz).tzinfo
        return datetime.combine(day, time(h, m), tzinfo=zone)

    async def book(self, uid: str) -> Book:
        return await self.store.book(uid)

    @staticmethod
    def find(book: Book, ref: Any) -> Bill:
        """A bill by its id, or by its name (case-insensitive, exactly one; "the X bill" too)."""
        key = " ".join(ref.split()).casefold() if isinstance(ref, str) else ""
        by_id = [b for b in book.bills if b.id == key]
        named = [b for b in book.bills if b.label.casefold() in (key, f"{key} bill")]
        found = by_id or named
        if len(found) != 1:
            raise BillRefused("No bill by that name, Sir." if not found else "Two bills share it.")
        return found[0]

    async def add(  # noqa: PLR0913 - one field each, as he types them
        self,
        uid: str,
        *,
        label: Any,
        payee: Any = "",
        upi: Any = "",
        amount: Any = None,
        day: Any = None,
        on: Any = None,
        every_months: Any = 1,
        leads: Any = None,
        last4: Any = "",
    ) -> Bill:
        today = self.today()
        months = every_months if isinstance(every_months, int) else -1
        bill = Bill(
            id=secrets.token_hex(6),
            label=clean_label(label),
            payee=clean_payee(payee),
            upi=parse_upi(upi) if upi else "",
            amount=None if amount is None else parse_amount(amount),
            due=Due(start=_start(today, day, on), every_months=months),
            leads=tuple(leads) if leads else DEFAULT_LEADS,
            last4=last_four(last4),
            added=today,
        )
        await self.store.change(uid, lambda b: b.with_bills((*b.bills, bill)))
        return bill

    async def _replace(self, uid: str, ref: Any, fn: Callable[[Bill], Bill]) -> Bill:
        done: list[Bill] = []

        def change(b: Book) -> Book:
            old = self.find(b, ref)
            new = fn(old)
            done.append(new)
            return b.with_bills(tuple(new if x.id == old.id else x for x in b.bills))

        await self.store.change(uid, change)
        return done[-1]

    async def set_payee(self, uid: str, ref: Any, *, upi: Any, payee: Any = None) -> Bill:
        clean = parse_upi(upi)
        name = None if payee is None else clean_payee(payee)

        def put(bill: Bill) -> Bill:
            return bill.model_copy(
                update={"upi": clean, "payee": bill.payee if name is None else name}
            )

        return await self._replace(uid, ref, put)

    async def mark_paid(self, uid: str, ref: Any) -> tuple[Bill, date]:
        today = self.today()
        paid: list[date] = []

        def mark(bill: Bill) -> Bill:
            due = current_due(bill, today)
            if due is None:
                raise BillRefused("Nothing is due on that bill, Sir.")
            paid.append(due)
            history = (*bill.paid, Paid(due=due, on=today))[-24:]
            return bill.model_copy(update={"paid": history})

        bill = await self._replace(uid, ref, mark)
        return bill, paid[-1]

    async def remove(self, uid: str, bill_id: str) -> bool:
        gone: list[bool] = []

        def drop(b: Book) -> Book:
            kept = tuple(x for x in b.bills if x.id != bill_id)
            gone.append(len(kept) != len(b.bills))
            ready = {k: v for k, v in b.ready.items() if k != bill_id}
            return b.with_bills(kept).with_ready(ready)

        await self.store.change(uid, drop)
        return bool(gone and gone[-1])

    async def set_prefs(self, uid: str, **changes: Any) -> Prefs:
        def put(b: Book) -> Book:
            try:
                prefs = Prefs.model_validate({**b.prefs.model_dump(), **changes})
            except ValueError as exc:
                raise BillRefused("A time is HH:MM, like 09:00.") from exc
            return b.with_prefs(prefs)

        return (await self.store.change(uid, put)).prefs

    async def prepare(self, uid: str, ref: Any, amount: Any = None) -> Prepared:
        """The payment the card shows, from his saved bill. Read-only."""
        bill = self.find(await self.store.book(uid), ref)
        if not bill.upi:
            raise BillRefused(NO_UPI)
        paise = parse_amount(amount) if amount not in (None, "") else bill.amount
        if paise is None:
            raise BillRefused(VARIES_NEEDS)
        amount_text(paise)  # the cap
        due = current_due(bill, self.today()) or self.today()
        return Prepared(bill, paise, due, card_text(bill, paise, due))

    async def make_ready(self, uid: str, prepared: Prepared) -> datetime:
        b, now = prepared.bill, self._now()
        grant = Grant(now + READY_FOR, prepared.paise, prepared.due, b.upi, b.payee or b.label)
        return await self.store.make_ready(uid, b.id, grant, now)

    async def payment(self, uid: str, bill_id: str) -> Payment | None:
        """The approved payment, once: None when nothing was approved, it expired, or the bill's
        payee changed since the card he approved (never a payee he didn't see)."""
        grant = await self.store.take_ready(uid, bill_id, self._now())
        if grant is None:
            return None
        bill = self.find(await self.store.book(uid), bill_id)
        if (bill.upi, bill.payee or bill.label) != (grant.upi, grant.payee):
            return None
        note = bill.note(grant.due)
        link = upi_link(pa=grant.upi, pn=grant.payee, paise=grant.paise, tn=note)
        return Payment(link, qr_data_uri(link), grant.upi, grant.payee, inr(grant.paise), note)


__all__ = [
    "NO_UPI",
    "OVERDUE",
    "VARIES_NEEDS",
    "BillsService",
    "Payment",
    "Prepared",
    "amount_words",
    "card_text",
    "current_due",
    "day_text",
    "reminder_text",
    "reminders_due",
    "when_words",
]
