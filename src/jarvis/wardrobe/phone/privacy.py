# src/jarvis/wardrobe/phone/privacy.py
"""R13 D20 (docs/plans/r13-wardrobe.md): the Privacy panel's section "Wardrobe", four rows over
EVERY part's `WardrobeData` (count, a plain export, delete), read late from the app, so a part
built after D, or rebuilt, is always counted. No row reads a Firestore path itself.

| Row (id)           | Holds                                                | Its sources          |
|--------------------|------------------------------------------------------|----------------------|
| `wardrobe_pieces`  | the index (pieces, pairs, sets, places, labels) and  | row "pieces", else   |
|                    | each piece's own history                             | the name "pieces"    |
| `wardrobe_history` | laundry, the review queue, outfit plans, his wears   | row "history", else  |
|                    |                                                      | "laundry", "outfits" |
| `wardrobe_photos`  | the saved crops and their fingerprints               | row "photos", else   |
|                    |                                                      | the name "photos"    |
| `wardrobe_device`  | nothing on the server or the phone: page memory only | none                 |

A source says its row with a `row` attribute (the contract's field at I1, INTEGRATION-D section 6),
else by its name. FAIL CLOSED (REVIEW-D-1 H3): a source that says no known row, or has an unknown
name, is never counted, exported or deleted under another row, and while one exists every server
row is "Couldn't check right now" and deletes nothing, so no row ever claims "Nothing kept yet"
for data it can't see, and no passkey delete reaches data its label does not name.

The first three are sealed by JARVIS and deleted with the passkey (they can't be brought back);
the device row has nothing to delete. The export is each source's own plain export under its
name (`privacy/export.py` scrubs it again); photos are never in it, as bytes or base64.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import Any, Literal, cast

from jarvis.privacy.ports import CategoryView, PrivacySource
from jarvis.privacy.sources import OURS_ENC, CallbackSource, Look, Spec
from jarvis.wardrobe.ports import WardrobeData

SECTION = "Wardrobe"
PIECES_ID, HISTORY_ID = "wardrobe_pieces", "wardrobe_history"
PHOTOS_ID, DEVICE_ID = "wardrobe_photos", "wardrobe_device"
ROW_IDS: tuple[str, ...] = (PIECES_ID, HISTORY_ID, PHOTOS_ID, DEVICE_ID)
Row = Literal["pieces", "history", "photos"]
ROWS: frozenset[str] = frozenset({"pieces", "history", "photos"})
PIECES_DATA = frozenset({"pieces"})  # A's index and its logs
PHOTOS_DATA = frozenset({"photos"})  # A's photo vault (photos and fingerprints)
HISTORY_DATA = frozenset({"laundry", "outfits"})  # B's and C's sources
_BY_NAME: tuple[tuple[Row, frozenset[str]], ...] = (
    ("pieces", PIECES_DATA),
    ("history", HISTORY_DATA),
    ("photos", PHOTOS_DATA),
)
NOTHING_YET = "Nothing kept yet."
DataFn = Callable[[], Sequence[WardrobeData]]


class UnsortedData(RuntimeError):
    """A part's data fits no row: the server rows can't say what they hold (fail closed)."""


def row_of(d: WardrobeData) -> Row | None:
    """The row `d` belongs to: its own `row` when it says one, else its name; None for anything
    else (never a guess, never "history")."""
    said = getattr(d, "row", None)
    if said is not None:
        return cast(Row, said) if isinstance(said, str) and said in ROWS else None
    return next((row for row, names in _BY_NAME if d.name in names), None)


def _row(spec: Spec, data: DataFn, row: Row) -> CallbackSource:
    def mine() -> list[WardrobeData]:
        every = list(data())
        if any(row_of(d) is None for d in every):
            raise UnsortedData("a wardrobe data source fits no Privacy row")  # nothing counted
        return [d for d in every if row_of(d) == row]

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
    "Each piece you own (its type, colour, your own label, its state and place) and its own "
    "history (scans, taps and moves), its pairs and sets, your places and QR labels, and your "
    "wardrobe settings. A private piece is counted like the others and never has a photo.",
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
    "Laundry steps, loads and outside batches with your label for the shop, the review queue, "
    "outfit plans, reservations and what you wore. A calendar event's title is never kept, only "
    "its time.",
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
        "Each photo, and then its crop, is checked on your phone for a person or a face before it "
        "is kept. The check can miss a hand or a turned face: look before you save. Delete here "
        "removes every wardrobe photo and fingerprint at once; one photo can't be deleted alone "
        "yet."
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
        _row(PIECES_SPEC, data, "pieces"),
        _row(HISTORY_SPEC, data, "history"),
        _row(PHOTOS_SPEC, data, "photos"),
        DeviceRow(),
    )


__all__ = [
    "DEVICE_ID",
    "HISTORY_DATA",
    "HISTORY_ID",
    "NOTHING_YET",
    "PHOTOS_DATA",
    "PHOTOS_ID",
    "PIECES_DATA",
    "PIECES_ID",
    "ROWS",
    "ROW_IDS",
    "SECTION",
    "DeviceRow",
    "Row",
    "UnsortedData",
    "privacy_rows",
    "row_of",
]
