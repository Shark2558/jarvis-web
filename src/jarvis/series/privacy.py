# src/jarvis/series/privacy.py
"""The plans' privacy row (R11.1 O2b; R2 D14's dashboard): what JARVIS keeps about followed
plans, the export of exactly that, and its delete. Deleting stops the follow-up only: the events
stay in the owner's Google Calendar (one "Undo all" of a batch removes those)."""

from __future__ import annotations

from typing import Any

from jarvis.privacy.sources import GOOGLE_ENC, CallbackSource, Look, Spec
from jarvis.series.store import SeriesStore

PRIVACY_ID = "series"
SECTION = "Helpers"


def series_privacy(store: SeriesStore) -> CallbackSource:
    async def look(uid: str) -> Look:
        book = await store.load(uid)
        basis = [[p.id, p.total, p.updated_at.isoformat()] for p in book.plans]
        return Look(len(book.plans), basis, deletable=bool(book.plans))

    async def export(uid: str) -> dict[str, Any]:
        book = await store.load(uid)
        return {
            "plans": [p.model_dump(mode="json") for p in book.plans],
            "never_kept": "The events themselves: they are in your Google Calendar.",
        }

    return CallbackSource(
        Spec(
            PRIVACY_ID,
            SECTION,
            "Calendar plans you follow",
            "For each plan: its name, and per session the calendar event's id, a short title, "
            "its time and whether it is planned, done, skipped or moved; and when each "
            "check-in question went (a hash, never the words).",
            "plans",
            "Until you delete them; the check-in hashes 60 days.",
            GOOGLE_ENC,
            delete="confirm",
            note="Deleting stops the follow-up. The events stay in your Google Calendar.",
        ),
        look,
        export,
        store.delete,
    )


__all__ = ["PRIVACY_ID", "SECTION", "series_privacy"]
