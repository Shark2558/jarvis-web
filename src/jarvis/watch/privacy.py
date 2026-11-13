# src/jarvis/watch/privacy.py
"""Part D's privacy rows (docs/plans/r7-mobile.md D25; I0 seam 20: registered through the part,
so no privacy file is edited):

- `watch_days` (section "Phone and watch"; delete: passkey; export): one sealed summary a day.
- `sos` (section "Settings and safety"; delete: confirm; export): his SOS label, the contacts (his
  labels, numbers, whether they joined) and the log (time, kind, how many were reached, location
  yes / no). Never kept: a place, anything a contact wrote, a join word.
Without a token key both rows say nothing is kept (nothing can be).
"""

from __future__ import annotations

from typing import Any

from jarvis.privacy.sources import OURS_ENC, CallbackSource, Look, Spec
from jarvis.sos.store import SosStore
from jarvis.watch.store import WatchStore

WATCH_ID, SOS_ID = "watch_days", "sos"
WATCH_SECTION, SOS_SECTION = "Phone and watch", "Settings and safety"
OFF_NOTE = "Off: JARVIS has no token key, so nothing is kept."


def watch_privacy(store: WatchStore) -> CallbackSource:
    async def look(uid: str) -> Look:
        if not store.sealed:
            return Look(0, deletable=False, note=OFF_NOTE)
        dates = await store.dates(uid)
        return Look(len(dates), [d.isoformat() for d in dates], deletable=bool(dates))

    async def export(uid: str) -> dict[str, Any]:
        if not store.sealed:
            return {"days": []}
        return {"days": await store.export(uid)}

    return CallbackSource(
        Spec(
            WATCH_ID,
            WATCH_SECTION,
            "Watch days: steps, heart rate and sleep",
            "One summary a day from your watch or phone through Health Connect: steps; heart rate "
            "lowest, average and highest; each night's sleep with minutes per stage; which app "
            "wrote each; and sleep times you typed.",
            "days",
            "400 days, then deleted.",
            OURS_ENC,
            encrypted_by_jarvis=True,
            delete="passkey",
            note="Never kept: raw heart-rate samples or anything else from Health Connect.",
        ),
        look,
        export,
        store.delete_all,
    )


def sos_privacy(store: SosStore) -> CallbackSource:
    async def look(uid: str) -> Look:
        if not store.sealed:
            return Look(0, deletable=False, note=OFF_NOTE)
        book = await store.book(uid)
        logs = await store.log_count(uid)
        count = len(book.contacts) + logs
        basis = [book.label_set, [c.id for c in book.contacts], logs]
        return Look(count, basis, deletable=bool(count) or book.label_set)

    async def export(uid: str) -> dict[str, Any]:
        if not store.sealed:
            return {"contacts": [], "log": []}
        book = await store.book(uid)
        contacts = [
            {"label": c.label, "phone": c.phone, "joined_on_telegram": c.joined}
            for c in book.contacts
        ]
        return {"your_label": book.label, "contacts": contacts, "log": await store.logs(uid)}

    return CallbackSource(
        Spec(
            SOS_ID,
            SOS_SECTION,
            "Emergency SOS: contacts and log",
            "Your name for the message, up to 5 contacts (your label, a phone number for the SMS "
            'screen, whether they joined on Telegram) and each SOS, test and "I\'m safe": the '
            "time, how many were reached and whether a location was sent.",
            "items",
            "Contacts until you delete them; the log 400 days.",
            OURS_ENC,
            encrypted_by_jarvis=True,
            delete="confirm",
            note="Never kept: your location, anything a contact writes, or a join word.",
        ),
        look,
        export,
        store.delete_all,
    )


__all__ = ["SOS_ID", "WATCH_ID", "sos_privacy", "watch_privacy"]
