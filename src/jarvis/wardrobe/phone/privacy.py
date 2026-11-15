# src/jarvis/wardrobe/phone/privacy.py
"""R13 D20 (docs/plans/r13-wardrobe.md): the Privacy panel's section "Wardrobe", four rows over
EVERY part's `WardrobeData` (count, a plain export, delete), read late from the app, so a part
built after D, or rebuilt, is always counted. No row reads a Firestore path itself.

| Row (id)           | Holds                                                 | Its sources         |
|--------------------|-------------------------------------------------------|---------------------|
| `wardrobe_pieces`  | the index: pieces, pairs, sets, places, labels        | data named "pieces" |
| `wardrobe_history` | each piece's events, laundry, the review queue, plans | every other source  |
| `wardrobe_photos`  | the saved crops and their fingerprints                | data named "photos" |
| `wardrobe_device`  | nothing on the server or the phone: page memory only  | none                |

The first three are sealed by JARVIS and deleted with the passkey (they can't be brought back);
the device row has nothing to delete. The export is each source's own plain export under its
name (`privacy/export.py` scrubs it again); photos are never in it, as bytes or base64.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import Any

from jarvis.privacy.ports import CategoryView, PrivacySource
from jarvis.privacy.sources import OURS_ENC, CallbackSource, Look, Spec
from jarvis.wardrobe.ports import WardrobeData

SECTION = "Wardrobe"
PIECES_ID, HISTORY_ID = "wardrobe_pieces", "wardrobe_history"
PHOTOS_ID, DEVICE_ID = "wardrobe_photos", "wardrobe_device"
ROW_IDS: tuple[str, ...] = (PIECES_ID, HISTORY_ID, PHOTOS_ID, DEVICE_ID)
PIECES_DATA = frozenset({"pieces"})  # A's index
PHOTOS_DATA = frozenset({"photos"})  # A's photo vault (photos and fingerprints)
NOTHING_YET = "Nothing kept yet."
DataFn = Callable[[], Sequence[WardrobeData]]


def _pieces(d: WardrobeData) -> bool:
    return d.name in PIECES_DATA


def _photos(d: WardrobeData) -> bool:
    return d.name in PHOTOS_DATA


def _history(d: WardrobeData) -> bool:
    return not (_pieces(d) or _photos(d))


def _row(spec: Spec, data: DataFn, pick: Callable[[WardrobeData], bool]) -> CallbackSource:
    def mine() -> list[WardrobeData]:
        return [d for d in data() if pick(d)]

    async def look(uid: str) -> Look:
        sources = mine()
        counts = [await d.count(uid) for d in sources]
        total = sum(counts)
        if not sources:
            return Look(0, deletable=False, note=NOTHING_YET)
        return Look(total, [d.name for d in sources] + counts, deletable=total > 0)

    async def export(uid: str) -> dict[str, Any]:
        return {d.name: await d.export(uid) for d in mine()}

    async def delete(uid: str) -> int:
        return sum([await d.delete(uid) for d in mine()])

    return CallbackSource(spec, look, export, delete)


PIECES_SPEC = Spec(
    PIECES_ID,
    SECTION,
    "Wardrobe pieces and places",
    "Each piece you own (its type, colour, your own label, its state and place), its pairs and "
    "sets, your places and QR labels, and your wardrobe settings. A private piece is counted "
    "like the others and never has a photo.",
    "pieces and places",
    "Until you delete them; a removed piece waits 30 days in Recently deleted",
    OURS_ENC,
    encrypted_by_jarvis=True,
    delete="passkey",
)
HISTORY_SPEC = Spec(
    HISTORY_ID,
    SECTION,
    "Laundry, outfits and wear history",
    "Each piece's history (scans, taps, laundry steps and wears), laundry loads and outside "
    "batches with your label for the shop, the review queue, outfit plans and reservations. A "
    "calendar event's title is never kept, only its time.",
    "entries",
    "A piece's history until it is purged; closed laundry and past plans 90 days",
    OURS_ENC,
    encrypted_by_jarvis=True,
    delete="passkey",
)
PHOTOS_SPEC = Spec(
    PHOTOS_ID,
    SECTION,
    "Wardrobe photos and fingerprints",
    "A photo of a piece you chose to save, cropped to the piece (at most 512 pixels), and its "
    "fingerprint (numbers that compare looks), sealed by JARVIS. Never for a private piece.",
    "photos and fingerprints",
    "Until you delete them, the piece is removed, or you make it private",
    OURS_ENC,
    encrypted_by_jarvis=True,
    delete="passkey",
    note=(
        "Each photo is checked on your phone for a person or a face before it is kept. The check "
        "can miss a hand or a turned face: look before you save, and delete here if one slipped "
        "through."
    ),
)


class DeviceRow:
    """What Camera, Wardrobe keeps on the phone: nothing written anywhere (D4.1, D9)."""

    id = DEVICE_ID
    section = SECTION
    label = "Only on this device: the Wardrobe mode's last choices"

    async def describe(self, uid: str) -> CategoryView:
        del uid
        return CategoryView(
            id=self.id,
            section=self.section,
            label=self.label,
            what=(
                "Camera, Wardrobe keeps its last choices (the step, the place) and any scan not "
                "sent yet in this page's memory only: nothing is written to the phone, and "
                "closing the page drops them."
            ),
            count=None,
            unit="",
            retention="Until the page closes",
            where="This page's memory only",
            note="Nothing to delete here: close the page.",
        )

    async def export(self, uid: str) -> dict[str, Any] | None:
        return None

    async def delete(self, uid: str) -> int:
        raise PermissionError("Nothing is kept on this device to delete.")


def privacy_rows(data: DataFn) -> tuple[PrivacySource, ...]:
    """The section's four rows over `data()` (every built part's `WardrobeData`, read late)."""
    return (
        _row(PIECES_SPEC, data, _pieces),
        _row(HISTORY_SPEC, data, _history),
        _row(PHOTOS_SPEC, data, _photos),
        DeviceRow(),
    )


__all__ = [
    "DEVICE_ID",
    "HISTORY_ID",
    "NOTHING_YET",
    "PHOTOS_ID",
    "PIECES_ID",
    "ROW_IDS",
    "SECTION",
    "DeviceRow",
    "privacy_rows",
]
