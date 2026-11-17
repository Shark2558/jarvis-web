# src/jarvis/wardrobe/tryon/privacy.py
"""R13.1 D16: Part A's three rows in Privacy's "Try-on" section, on `WardrobePart.privacy`
(never `data`: R13's Wardrobe rows fail closed on a source they don't know, M4). Their words are
I0's `kept.SPECS`, so the stand-ins and these say the same.

- `tryon_figure` "Your measurements and your 3D figure": a count of what `tryon/{uid}` holds
  (measurement versions, figure choices, saved comparisons), his own export (his measurements are
  his data, as R13's labels are in its pieces row), delete with a confirm. A document that can't
  be opened (no key, the key changed) says "Couldn't check right now" and can still be deleted.
- `tryon_all` "All your try-on data": every try-on document of his found by path (no key), and
  its delete is OPS-05 (`erase.erase_all`) through the existing `PrivacyService`: its passkey
  ceremony bound to the row's id and `rev`, its IRREVERSIBLE audit line, its words. The backups
  sentence is `kept.BACKUP_WORDS` (R14's `RETENTION_DAYS`).
- `tryon_device`: `kept.DeviceRow` (nothing is kept on the device).
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from jarvis.privacy.ports import PrivacySource
from jarvis.privacy.sources import CallbackSource, Look
from jarvis.storage.docs import Docs
from jarvis.wardrobe.kept import WardrobeUnavailable, kept_paths
from jarvis.wardrobe.tryon import kept
from jarvis.wardrobe.tryon.store import Off, TryonDoc, TryonStore, Unreadable

Erase = Callable[[str], Awaitable[int]]


def items(doc: TryonDoc) -> int:
    versions = (doc.current is not None) + (doc.draft is not None) + len(doc.earlier)
    return versions + len(doc.assets) + len(doc.saved)


def export_of(doc: TryonDoc) -> dict[str, Any]:
    def body(b: Any) -> Any:
        return b.model_dump(mode="json") if b is not None else None

    return {
        "measurements": {
            "current": body(doc.current), "draft": body(doc.draft),
            "earlier": [body(b) for b in doc.earlier],
        },
        "figure_choices": {pid: a.model_dump(mode="json") for pid, a in doc.assets.items()},
        "saved": [s.model_dump(mode="json") for s in doc.saved],
    }  # fmt: skip


def figure_row(store: TryonStore) -> CallbackSource:
    spec = kept.SPECS[kept.FIGURE_ID]

    async def look(uid: str) -> Look:
        stamp = await store.stamp(uid)
        if stamp is None:
            return Look(0, deletable=False, note=kept.NOTHING_YET)
        try:
            n = items(await store.read(uid))
        except (Off, Unreadable):
            return Look(None, [stamp], note=kept.CANT_OPEN, delete_count=1)
        return Look(n, [stamp], deletable=n > 0)

    async def export(uid: str) -> dict[str, Any]:
        if await store.stamp(uid) is None:
            return {}
        try:
            return export_of(await store.read(uid))
        except (Off, Unreadable):
            raise WardrobeUnavailable(spec.id) from None

    return CallbackSource(spec, look, export, store.delete)


def all_row(docs: Docs, prefix: str, erase: Erase) -> CallbackSource:
    spec = kept.SPECS[kept.ALL_ID]

    async def look(uid: str) -> Look:
        found = await kept_paths(
            docs, prefix, uid, singles=kept.ALL_SINGLES, owned=kept.PICTURES_OWNED
        )
        if not found:
            return Look(0, deletable=False, note=kept.NOTHING_YET)
        return Look(len(found), sorted(found), delete_count=len(found))

    return CallbackSource(spec, look, None, erase)


def rows(docs: Docs, prefix: str, store: TryonStore, erase: Erase) -> tuple[PrivacySource, ...]:
    return (figure_row(store), all_row(docs, prefix, erase), kept.DeviceRow())


__all__ = ["all_row", "export_of", "figure_row", "items", "rows"]
