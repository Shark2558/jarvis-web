# src/jarvis/helpers/today/privacy.py
"""Part A's privacy rows (docs/plans/r11-free-helpers.md D17, section "Helpers").

- `helpers_bills` (passkey delete: his bills can't be brought back): the sealed bill book (names,
  payees and UPI IDs, amounts, due rules, reminder days, what he marked paid), his Part A choices,
  and the sent-reminder claims (`bills_told`, a hash each). Export: JSON, amounts in ₹.
- `helpers_birthdays` (simple): only the claims of birthday reminders already sent (a one-way
  hash each; never a name, a date or a year: birthdays are read from Google each day, not kept).
Each row says what is never kept: a card / account / consumer number (the last 4 digits at most),
a payment link or QR, a contact's birth year.
"""

from __future__ import annotations

from typing import Any

from jarvis.helpers.kinds import PRIVACY_SECTION
from jarvis.helpers.today.bills import BillsService, amount_words
from jarvis.helpers.today.store import Claims
from jarvis.privacy.sources import GOOGLE_ENC, OURS_ENC, CallbackSource, Look, Spec

BILLS_ID = "helpers_bills"
BIRTHDAYS_ID = "helpers_birthdays"


def _bill_export(svc: BillsService, claims: Claims) -> Any:
    async def export(uid: str) -> dict[str, Any]:
        book = await svc.book(uid)
        bills = [
            {
                "label": b.label,
                "payee": b.payee,
                "upi_id": b.upi,
                "amount": amount_words(b),
                "due": {"from": b.due.start.isoformat(), "every_months": b.due.every_months},
                "remind_days_before": list(b.leads),
                "last_4_digits": b.last4,
                "paid": [{"due": p.due.isoformat(), "on": p.on.isoformat()} for p in b.paid],
            }
            for b in book.bills
        ]
        sent = [str(d.get("at", "")) for _, d in await claims.rows(uid)]
        return {"bills": bills, "choices": book.prefs.model_dump(), "reminders_sent_at": sent}

    return export


def bills_privacy(svc: BillsService, claims: Claims) -> CallbackSource:
    async def look(uid: str) -> Look:
        book = await svc.book(uid)
        told = await claims.count(uid)
        kept = await svc.store.exists(uid)
        return Look(len(book.bills), [book.rev, told], deletable=kept or told > 0)

    async def delete(uid: str) -> int:
        return await svc.store.delete_all(uid) + await claims.delete_all(uid)

    return CallbackSource(
        Spec(
            BILLS_ID,
            PRIVACY_SECTION,
            "Bills and their UPI IDs",
            "Your bills: names, payees and their UPI IDs, amounts, due dates, reminder days and "
            "what you marked paid; when reminders go; which reminders already went (a hash each). "
            "Never a card, account or consumer number (the last 4 digits at most), and never a "
            "payment link or QR: those are made when you open them.",
            "bills",
            "Until you delete them; the sent-reminder hashes 60 days.",
            OURS_ENC,
            encrypted_by_jarvis=True,
            delete="passkey",
            recoverable=False,
            note="Deleting removes every bill and its UPI ID; JARVIS never paid any of them.",
        ),
        look,
        _bill_export(svc, claims),
        delete,
    )


def birthdays_privacy(claims: Claims) -> CallbackSource:
    async def look(uid: str) -> Look:
        n = await claims.count(uid)
        return Look(n, [n], deletable=n > 0)

    async def export(uid: str) -> dict[str, Any]:
        return {"reminders_sent_at": [str(d.get("at", "")) for _, d in await claims.rows(uid)]}

    async def delete(uid: str) -> int:
        return await claims.delete_all(uid)

    return CallbackSource(
        Spec(
            BIRTHDAYS_ID,
            PRIVACY_SECTION,
            "Birthday reminders sent",
            "Which birthday reminders already went, so none goes twice: a one-way hash of the "
            "contact and the year each. Never a name, a date or a birth year: birthdays are read "
            "from your Google Contacts each day and not kept.",
            "items",
            "400 days.",
            GOOGLE_ENC,
            delete="simple",
            note="Deleting may send today's birthday reminder again.",
        ),
        look,
        export,
        delete,
    )


__all__ = ["BILLS_ID", "BIRTHDAYS_ID", "bills_privacy", "birthdays_privacy"]
