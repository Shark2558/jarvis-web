# src/jarvis/wardrobe/seeme/vault.py
"""R13.1 Part C: his photo for See it on me, and the one check every picture of his passes
(docs/plans/r13-1-try-on.md D12; plan review M7, L4, L11).

    {prefix}tryon_person/{uid}   {v, kid, owner, at, bytes, blob, updated_at}
        blob = AES-GCM(the cleaned JPEG), purpose `tryon_photos`, AAD `model.aad_person(uid)`

- `clean_jpeg(data, max_kb)`: JPEG only, at most `max_kb` (`tryon_photo_max_kb`, 700), cleaned by
  structure (`photos.imaging.sanitise_jpeg`: EXIF, GPS and comments dropped; never decoded), its
  side at most 1,568 px from its SOF marker (R13's `catalog.photos.frame_size`). His photo and a
  garment's photo both pass it (D22).
- `PersonPhoto`: one photo; a new one replaces the old in ONE write; read back for his signed-in
  console only (the route's rule); a delete takes his YES with it in the same write (D11's
  withdraw). Never in the Vault panel, R13's backup file, an export or the AI.
- `Sealer`: the one way R13.1 Part C seals and opens (only `jarvis.keyring` derives keys). A blob
  that won't open (another owner's AAD, a changed key) reads as None and is logged by class name.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from typing import Any

from jarvis.keyring import KEY_ID, Keyring
from jarvis.logging import get_logger
from jarvis.photos.errors import PickerError
from jarvis.photos.imaging import sanitise_jpeg
from jarvis.storage.docs import Delete, Docs, Set
from jarvis.wardrobe.catalog.photos import frame_size
from jarvis.wardrobe.seeme import texts
from jarvis.wardrobe.seeme.texts import SeeMeRefused
from jarvis.wardrobe.tryon.http import PhotoView
from jarvis.wardrobe.tryon.model import (
    CONSENT,
    PERSON,
    PHOTO_PURPOSE,
    PHOTO_SIDE_MAX,
    aad_person,
)

log = get_logger(__name__)
VERSION = 1


class Sealer:
    def __init__(self, keyring: Keyring) -> None:
        self._ring = keyring

    @property
    def kid(self) -> str:
        return KEY_ID

    def seal(self, purpose: str, aad: str, data: bytes) -> str:
        return self._ring.cipher(purpose).encrypt(data, aad=aad)

    def open(self, purpose: str, aad: str, blob: object) -> bytes | None:
        """The plaintext, or None when it won't open (never the reason's text in a log)."""
        if not isinstance(blob, str):
            return None
        try:
            return self._ring.cipher(purpose).decrypt(blob, aad=aad)
        except Exception as exc:  # noqa: BLE001 - another owner's, or a changed key
            log.warning(
                "see it on me: a sealed blob won't open", extra={"error": type(exc).__name__}
            )
            return None


def clean_jpeg(data: bytes, *, max_kb: int) -> bytes:
    if len(data) > max_kb * 1024:
        raise SeeMeRefused(413, "too_large", texts.TOO_LARGE)
    try:
        clean = sanitise_jpeg(data)
        width, height = frame_size(clean)
    except (PickerError, ValueError):
        raise SeeMeRefused(422, "not_jpeg", texts.NOT_JPEG) from None
    if max(width, height) > PHOTO_SIDE_MAX:
        raise SeeMeRefused(422, "too_large", texts.TOO_WIDE)
    return clean


def sealed_doc(sealer: Sealer, uid: str, aad: str, clean: bytes, at: datetime) -> dict[str, Any]:
    """The fields every sealed picture document of Part C carries (a plain `owner`)."""
    blob = sealer.seal(PHOTO_PURPOSE, aad, clean)
    return {"v": VERSION, "kid": sealer.kid, "owner": uid, "at": at.isoformat(),
            "bytes": len(clean), "blob": blob, "updated_at": at.isoformat()}  # fmt: skip


def _at(doc: dict[str, Any]) -> datetime | None:
    try:
        return datetime.fromisoformat(str(doc.get("at")))
    except ValueError:
        return None


class PersonPhoto:
    def __init__(
        self, docs: Docs, prefix: str, sealer: Sealer, *, now: Callable[[], datetime]
    ) -> None:
        self.docs, self.prefix, self.sealer, self.now = docs, prefix, sealer, now

    def path(self, uid: str) -> str:
        return f"{self.prefix}{PERSON}/{uid}"

    async def save(self, uid: str, data: bytes, *, max_kb: int = 700) -> PhotoView:
        clean = clean_jpeg(data, max_kb=max_kb)
        at = self.now()
        await self.docs.write([Set(self.path(uid), sealed_doc(self.sealer, uid, aad_person(uid),
                                                               clean, at))])  # fmt: skip
        return PhotoView(kept=True, at=at, bytes=len(clean))

    async def _doc(self, uid: str) -> dict[str, Any] | None:
        doc = await self.docs.get(self.path(uid))
        return doc if doc is not None and doc.get("owner") == uid else None

    async def get(self, uid: str) -> bytes | None:
        doc = await self._doc(uid)
        if doc is None:
            return None
        return self.sealer.open(PHOTO_PURPOSE, aad_person(uid), doc.get("blob"))

    async def view(self, uid: str) -> PhotoView:
        doc = await self._doc(uid)
        if doc is None:
            return PhotoView()
        size = doc.get("bytes")
        return PhotoView(kept=True, at=_at(doc), bytes=size if isinstance(size, int) else 0)

    async def delete(self, uid: str) -> bool:
        """His photo and his YES, in ONE write (D11: withdraw = delete the photo)."""
        had = await self.docs.get(self.path(uid)) is not None
        consent = f"{self.prefix}{CONSENT}/{uid}"
        if not had and await self.docs.get(consent) is None:
            return False
        await self.docs.write([Delete(self.path(uid)), Delete(consent)])
        return had


__all__ = ["VERSION", "PersonPhoto", "Sealer", "clean_jpeg", "sealed_doc"]
