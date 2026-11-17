# src/jarvis/wardrobe/tryon/store.py
"""R13.1 Part A's one document (docs/plans/r13-1-try-on.md D4, D5, D7, D14, "Data model").

    {prefix}tryon/{uid}   {owner, rev, blob, updated_at}
        blob = AES-GCM(TryonDoc as JSON), keyring purpose `tryon`, AAD `model.aad_tryon(uid)`

`TryonDoc` holds his measurements (`current`, one `draft`, at most five `earlier`, each a
`model.Body` with its typed fields and time), `assets` (piece id -> his figure choice: a template,
a texture view, or an image card only) and `saved` (at most ten comparisons: slots -> piece ids,
tuck, open, layers; never a picture). The `owner` field is plain, so Privacy finds and deletes the
document with no key (R13 I1's M1 rule). Sealed, it is at most `model.TRYON_DOC_MAX_KB`.

No keyring or no storage: `Off` (nothing is ever kept in clear). A document that can't be opened
(the key changed) is `Unreadable` and is never overwritten. Records ignore a field a later
release adds, so a rollback still opens the document. Nothing here logs a value or a blob.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import datetime
from typing import Annotated, Any

from pydantic import BaseModel, ConfigDict, Field

from jarvis.keyring import Keyring
from jarvis.logging import get_logger
from jarvis.storage.docs import Delete, Docs, DocTx
from jarvis.undo.store import owner_ok
from jarvis.wardrobe.model import PieceId, View
from jarvis.wardrobe.tryon.model import (
    EARLIER_MAX,
    OPTIONS_MAX,
    PURPOSE,
    SAVED_ID,
    SAVED_MAX,
    TRYON,
    TRYON_DOC_MAX_KB,
    Body,
    Layers,
    Template,
    aad_tryon,
)

log = get_logger(__name__)
FULL = "Your try-on data is full: delete a saved comparison first."


class Off(RuntimeError):
    """No token key or no storage: Try-on keeps nothing (never in clear)."""


class Unreadable(RuntimeError):
    """`tryon/{uid}` can't be opened (the key changed): it is never overwritten."""


class TooBig(ValueError):
    """The sealed document would pass its 200 KB: nothing is written."""


class _Rec(BaseModel):
    model_config = ConfigDict(frozen=True, extra="ignore", hide_input_in_errors=True)


class Asset(_Rec):
    """His figure choice for one piece (AVT-05), saved against its id."""

    template: Template | None = None
    texture_view: View | None = None
    card_only: bool = False


class SlotRec(_Rec):
    slot: str = Field(min_length=1, max_length=20)
    piece: PieceId


class KeptLook(_Rec):
    plan: str | None = Field(default=None, max_length=40)
    slots: tuple[SlotRec, ...] = Field(min_length=1, max_length=OPTIONS_MAX)
    tucked: bool = False
    open: bool = True
    layers: Layers = "all"


class Saved(_Rec):
    """One saved comparison: one look or two, piece ids only (never a picture)."""

    id: Annotated[str, Field(pattern=SAVED_ID)]
    at: datetime
    looks: tuple[KeptLook, ...] = Field(min_length=1, max_length=2)


class TryonDoc(_Rec):
    current: Body | None = None
    draft: Body | None = None
    earlier: tuple[Body, ...] = Field(default=(), max_length=EARLIER_MAX)
    assets: dict[PieceId, Asset] = Field(default_factory=dict)
    saved: tuple[Saved, ...] = Field(default=(), max_length=SAVED_MAX)


def _owner(uid: str) -> str:
    if not isinstance(uid, str) or not owner_ok(uid):
        raise ValueError("bad owner id")
    return uid


class TryonStore:
    def __init__(
        self,
        docs: Docs | None,
        keyring: Keyring | None,
        *,
        prefix: str,
        now: Callable[[], datetime],
    ) -> None:
        self._docs, self._ring, self._prefix, self._now = docs, keyring, prefix, now

    @property
    def available(self) -> bool:
        return self._docs is not None and self._ring is not None

    def path(self, uid: str) -> str:
        return f"{self._prefix}{TRYON}/{_owner(uid)}"

    def _ready(self) -> tuple[Docs, Keyring]:
        if self._docs is None or self._ring is None:
            raise Off
        return self._docs, self._ring

    def _open(self, uid: str, raw: dict[str, Any] | None) -> TryonDoc:
        _, ring = self._ready()
        if not raw:
            return TryonDoc()
        try:
            plain = ring.cipher(PURPOSE).decrypt(str(raw.get("blob", "")), aad=aad_tryon(uid))
            return TryonDoc.model_validate(json.loads(plain))
        except Exception as exc:  # noqa: BLE001 - never overwrite what can't be opened
            log.error("try-on: tryon/{uid} can't be opened", extra={"error": type(exc).__name__})
            raise Unreadable(TRYON) from None  # never chain a decrypted value

    def _body(self, uid: str, value: TryonDoc, rev: int) -> dict[str, Any]:
        _, ring = self._ready()
        plain = value.model_dump(mode="json", exclude_defaults=True, warnings=False)
        TryonDoc.model_validate(plain)  # the bounds hold on every write, however it was made
        data = json.dumps(plain, separators=(",", ":"), ensure_ascii=False).encode()
        blob = ring.cipher(PURPOSE).encrypt(data, aad=aad_tryon(uid))
        if len(blob.encode()) > TRYON_DOC_MAX_KB * 1024:
            raise TooBig(FULL)
        return {"owner": uid, "rev": rev, "blob": blob, "updated_at": self._now().isoformat()}

    async def read(self, uid: str) -> TryonDoc:
        docs, _ = self._ready()
        return self._open(uid, await docs.get(self.path(uid)))

    async def change(self, uid: str, fn: Callable[[TryonDoc], TryonDoc]) -> TryonDoc:
        """`fn` on the document as stored now, written in one transaction (never over one that
        can't be opened, never past 200 KB)."""
        docs, _ = self._ready()
        path = self.path(uid)

        async def run(tx: DocTx) -> TryonDoc:
            raw = await tx.get(path)
            new = fn(self._open(uid, raw))
            tx.set(path, self._body(uid, new, int((raw or {}).get("rev", 0)) + 1))
            return new

        return await docs.transaction(run)

    async def present(self, uid: str) -> bool:
        """Whether the document is on disk (no key needed: Privacy sees what it can't open)."""
        return self._docs is not None and await self._docs.get(self.path(uid)) is not None

    async def delete(self, uid: str) -> int:
        """Gone by path, with no key; 0 when there was none."""
        if self._docs is None or await self._docs.get(self.path(uid)) is None:
            return 0
        await self._docs.write([Delete(self.path(uid))])
        return 1


__all__ = [
    "FULL",
    "Asset",
    "KeptLook",
    "Off",
    "Saved",
    "SlotRec",
    "TooBig",
    "TryonDoc",
    "TryonStore",
    "Unreadable",
]
