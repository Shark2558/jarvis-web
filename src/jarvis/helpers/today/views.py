# src/jarvis/helpers/today/views.py
"""What the Today tab shows (docs/plans/r11-free-helpers.md D19): his bills with their next due
date and whether an approved payment can be opened, his Part A choices, birthdays today and in
the coming week (only once he switched them on: no Google call before), and the top priority
with what is pending. This goes only to his own screen, where the console writes every string
with textContent; nothing here goes to a model, an alert or a log.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from typing import Any

from jarvis.helpers.ports import PendingItem
from jarvis.helpers.today.bills import BillsService, day_text
from jarvis.helpers.today.birthdays import BirthdayReader
from jarvis.helpers.today.focus import SOURCE_WORDS
from jarvis.helpers.today.pending import PendingService
from jarvis.helpers.today.store import OFF_NOTE, BillsOff, Book
from jarvis.helpers.today.tools import bill_view
from jarvis.notify.quiet import local

SOON_DAYS = 7


def _item(item: PendingItem) -> dict[str, Any]:
    return {
        "source": SOURCE_WORDS.get(item.source, item.source),
        "label": item.label,
        "urgency": item.urgency,
        "due": item.due.isoformat() if item.due else None,
    }


async def _bills(svc: BillsService, uid: str, now: datetime) -> tuple[Book, dict[str, Any]]:
    try:
        book = await svc.book(uid)
    except BillsOff:
        return Book(), {"available": False, "note": OFF_NOTE, "items": []}
    if not svc.store.available:
        return book, {"available": False, "note": OFF_NOTE, "items": []}
    items = [
        {**bill_view(b, svc), "ready": (g := book.ready.get(b.id)) is not None and g.until > now}
        for b in book.bills
    ]
    return book, {"available": True, "note": "", "items": items}


async def _birthdays(
    reader: BirthdayReader, book: Book, uid: str, now: datetime, tz: str
) -> dict[str, Any]:
    prefs = book.prefs
    out: dict[str, Any] = {"on": prefs.birthdays_on, "at": prefs.birthday_at}
    if not prefs.birthdays_on:
        return {**out, "state": "off", "note": "", "today": [], "soon": []}
    today = local(now, tz).date()
    reading, soon = await reader.upcoming(uid, today, SOON_DAYS)
    return {
        **out,
        "state": reading.state,
        "note": reading.note,
        "today": [p.name for p in reading.people if p.falls_on(today)],
        "soon": [{"name": p.name, "on": day_text(d)} for d, p in soon],
    }


async def today_view(services: Mapping[str, Any], uid: str, now: datetime) -> dict[str, Any]:
    svc: BillsService = services["bills"]
    reader: BirthdayReader = services["birthdays"]
    pending: PendingService = services["pending"]
    book, bills = await _bills(svc, uid, now)
    bills["prefs"] = book.prefs.model_dump()
    got = await pending.collect(uid, now)
    groups: dict[str, list[dict[str, Any]]] = {}
    for item in got.items[:10]:
        groups.setdefault(SOURCE_WORDS.get(item.source, item.source), []).append(_item(item))
    return {
        "bills": bills,
        "birthdays": await _birthdays(reader, book, uid, now, svc.tz),
        "top": _item(got.items[0]) if got.items else None,
        "pending": [{"source": s, "items": items} for s, items in groups.items()],
        "not_checked": [SOURCE_WORDS.get(m, m) for m in got.missing],
    }


__all__ = ["today_view"]
