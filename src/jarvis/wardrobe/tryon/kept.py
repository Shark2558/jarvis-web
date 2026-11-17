# src/jarvis/wardrobe/tryon/kept.py
"""R13.1's Privacy section "Try-on" (docs/plans/r13-1-try-on.md D16; plan review M4, M10) and what
it keeps on disk, found WITHOUT a key (R13 I1's M1 rule, `wardrobe/kept.py`).

The six rows and who offers each (`ports.PRIVACY_OWNER`): `tryon_figure` (A), `tryon_photo`,
`tryon_pictures`, `tryon_spend` (C), `tryon_all` (A: OPS-05, "Delete all my try-on data"),
`tryon_device` (A, nothing kept on the device). Their fixed words are `SPECS` (the parts reuse
them). They ride `WardrobePart.privacy`, NEVER `data`: R13's Wardrobe rows fail closed on a source
they don't know (fact 5).

`stand_ins(part, docs, prefix)` are the rows of a part that is off or failed (the wiring's
`_with_kept`): while anything of his is on disk they say "Couldn't check right now", export
nothing, and delete by path with no key (the passkey rows still ask for his passkey: the Privacy
service's ceremony is the same); with nothing on disk, "Nothing kept yet". `tryon_spend` is never
deletable (his cap's record, 13 months). `erase_seeme(docs, prefix, uid)` is C's half of OPS-05
by path, for A when C's `seeme` service is missing. Every R13.1 document carries a plain `owner`
field, so the pictures and the spend are found by one equality query.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from jarvis.backup.status import RETENTION_DAYS
from jarvis.privacy.ports import CategoryView, PrivacySource
from jarvis.privacy.sources import OURS_ENC, CallbackSource, Look, Spec
from jarvis.storage.docs import Docs
from jarvis.wardrobe.kept import OWNER_FIELD, WardrobeUnavailable, erase, kept_paths
from jarvis.wardrobe.tryon.model import CONSENT, KEPT_MAX, PERSON, PICTURE, SPEND, TRYON

SECTION = "Try-on"
NOTHING_YET = "Nothing kept yet."
CANT_OPEN = (
    "Couldn't check right now. This is kept on this server, but it can't be opened just now "
    "(the try-on part is off, or the token key is missing or has changed). It can still be "
    "deleted."
)
BACKUP_WORDS = (
    f"Copies inside JARVIS's own daily backups stay locked and are gone within {RETENTION_DAYS} "
    "days."
)
FIGURE_ID, PHOTO_ID, PICTURES_ID = "tryon_figure", "tryon_photo", "tryon_pictures"
SPEND_ID, ALL_ID, DEVICE_ID = "tryon_spend", "tryon_all", "tryon_device"
ROW_IDS = (FIGURE_ID, PHOTO_ID, PICTURES_ID, SPEND_ID, ALL_ID, DEVICE_ID)
PICTURES_OWNED = ((PICTURE, OWNER_FIELD),)
SPEND_OWNED = ((SPEND, OWNER_FIELD),)
PHOTO_SINGLES = (CONSENT, PERSON)  # his YES goes with his photo
ALL_SINGLES = (PERSON, CONSENT, TRYON)  # after the pictures; `tryon/{uid}` LAST (D16's order)

SPECS: dict[str, Spec] = {
    FIGURE_ID: Spec(
        FIGURE_ID, SECTION, "Your measurements and your 3D figure",
        "The six measurements you typed (and which ones JARVIS estimated), their earlier versions, "
        "each piece's figure shape and your saved comparisons. Never sent to Google.",
        "items", "Until you delete them", OURS_ENC, encrypted_by_jarvis=True, delete="confirm",
    ),
    PHOTO_ID: Spec(
        PHOTO_ID, SECTION, "Your photo for See it on me, and your YES",
        "One full-length photo of you, checked on your device and sealed by JARVIS, and when you "
        "typed YES to send it to Google's image model. The export says when and how big, never "
        "the photo.",
        "items", "Until you delete or replace it; your YES goes with it", OURS_ENC,
        encrypted_by_jarvis=True, delete="passkey",
    ),
    PICTURES_ID: Spec(
        PICTURES_ID, SECTION, "See it on me pictures",
        "Each picture Google's image model made of you in a look, as Google returned it, with "
        "the pieces sent. The export lists them, never the pictures.",
        "pictures", f"7 days unless you press Keep (at most {KEPT_MAX} kept)", OURS_ENC,
        encrypted_by_jarvis=True, delete="passkey",
    ),
    SPEND_ID: Spec(
        SPEND_ID, SECTION, "Try-on spend",
        "What See it on me cost each month in rupees, with GST, and how many pictures: numbers "
        "only.",
        "months", "Kept 13 months for your monthly limit", "Firestore, Google-encrypted",
    ),
    ALL_ID: Spec(
        ALL_ID, SECTION, "All your try-on data",
        "Your figure and measurements, your photo, your YES and every See it on me picture, in "
        "one delete. Your wardrobe stays as it is.",
        "items", f"Until you delete them. {BACKUP_WORDS}", OURS_ENC, encrypted_by_jarvis=True,
        delete="passkey",
    ),
}  # fmt: skip


def _look(docs: Docs, prefix: str, singles: Sequence[str], owned: Sequence[tuple[str, str]]) -> Any:
    async def look(uid: str) -> Look:
        found = await kept_paths(docs, prefix, uid, singles=singles, owned=owned)
        if not found:
            return Look(0, deletable=False, note=NOTHING_YET)
        return Look(None, [len(found)], note=CANT_OPEN, delete_count=len(found))

    return look


def kept_row(
    spec: Spec,
    docs: Docs,
    prefix: str,
    *,
    singles: Sequence[str] = (),
    owned: Sequence[tuple[str, str]] = (),
) -> CallbackSource:
    """A row of a part that is off or failed: "Couldn't check right now" while anything is kept."""

    async def export(uid: str) -> dict[str, Any]:
        if await kept_paths(docs, prefix, uid, singles=singles, owned=owned):
            raise WardrobeUnavailable(spec.id)
        return {}

    async def delete(uid: str) -> int:
        return await erase(docs, await kept_paths(docs, prefix, uid, singles=singles, owned=owned))

    look = _look(docs, prefix, singles, owned)
    return CallbackSource(spec, look, export, delete if spec.delete != "none" else None)


class DeviceRow:
    """What Try it on keeps on the phone or laptop: nothing (undo and the figure: page memory)."""

    id = DEVICE_ID
    section = SECTION
    label = "Only on this device: nothing is kept on this device"

    async def describe(self, uid: str) -> CategoryView:
        del uid
        return CategoryView(
            id=self.id, section=self.section, label=self.label,
            what=(
                "The 3D figure is drawn on this device from your measurements; its files are "
                "the same for everyone. Undo steps and the picture you save of a look stay in "
                "this page's memory or your Downloads: JARVIS writes nothing else here."
            ),
            count=None, unit="", retention="Until the page closes", where="This page's memory only",
            note="Nothing to delete here: close the page.",
        )  # fmt: skip

    async def export(self, uid: str) -> dict[str, Any] | None:
        return None

    async def delete(self, uid: str) -> int:
        raise PermissionError("Nothing is kept on this device to delete.")


async def erase_seeme(docs: Docs, prefix: str, uid: str) -> int:
    """C's half of OPS-05 by path: the pictures, his photo, his YES (never the spend)."""
    paths = await kept_paths(docs, prefix, uid, singles=(PERSON, CONSENT), owned=PICTURES_OWNED)
    return await erase(docs, paths)


def stand_ins(part: str, docs: Docs, prefix: str) -> tuple[PrivacySource, ...]:
    """The rows of `tryon` or `seeme` when that part offers none (off, failed, not built)."""
    if part == "tryon":
        return (
            kept_row(SPECS[FIGURE_ID], docs, prefix, singles=(TRYON,)),
            kept_row(SPECS[ALL_ID], docs, prefix, singles=ALL_SINGLES, owned=PICTURES_OWNED),
            DeviceRow(),
        )
    if part == "seeme":
        return (
            kept_row(SPECS[PHOTO_ID], docs, prefix, singles=PHOTO_SINGLES),
            kept_row(SPECS[PICTURES_ID], docs, prefix, owned=PICTURES_OWNED),
            kept_row(SPECS[SPEND_ID], docs, prefix, owned=SPEND_OWNED),
        )
    return ()


__all__ = [
    "ALL_ID",
    "ALL_SINGLES",
    "BACKUP_WORDS",
    "CANT_OPEN",
    "DEVICE_ID",
    "FIGURE_ID",
    "NOTHING_YET",
    "PHOTO_ID",
    "PHOTO_SINGLES",
    "PICTURES_ID",
    "PICTURES_OWNED",
    "ROW_IDS",
    "SECTION",
    "SPECS",
    "SPEND_ID",
    "SPEND_OWNED",
    "DeviceRow",
    "erase_seeme",
    "kept_row",
    "stand_ins",
]
