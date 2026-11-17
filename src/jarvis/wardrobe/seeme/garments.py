# src/jarvis/wardrobe/seeme/garments.py
"""R13.1 Part C: the photo of a garment he is thinking of BUYING (docs/plans/r13-1-try-on.md D22;
the owner, 17 Nov 2026).

    {prefix}tryon_garment/{uid}_{id}   {v, kid, owner, type, colour, at, bytes, blob, updated_at}
        id `tg_` + 12 hex (`model.new_garment_id`); blob = AES-GCM(the cleaned JPEG), purpose
        `tryon_photos`, AAD `model.aad_garment(uid, id)`; `type` (`model.NEW_TYPES`) and `colour`
        (R13's fixed colours) are fixed words he picked from lists, never free text

It is NEVER his: no `wi_` id, no write to any R13 collection, no ledger line; its words always say
"not in your wardrobe" (`model.new_garment_words`). Untrusted content: only its bytes are kept and
sent (checked and cleaned exactly as his photo, `vault.clean_jpeg`); no text is read from it, its
file name is never seen (the door sends bytes). At most `GARMENT_MAX` (20) at a time; kept
`keep_days` (30) or while a kept picture shows it (`seeme_daily` deletes the rest).
"""

from __future__ import annotations

import re
from collections.abc import Callable, Collection
from datetime import datetime, timedelta
from typing import Any

from pydantic import ValidationError

from jarvis.storage.docs import Delete, Docs, Query, Set
from jarvis.wardrobe.seeme import texts
from jarvis.wardrobe.seeme.texts import SeeMeRefused
from jarvis.wardrobe.seeme.vault import Sealer, clean_jpeg, sealed_doc
from jarvis.wardrobe.tryon.http import GarmentIn, GarmentList, GarmentView, NewGarment
from jarvis.wardrobe.tryon.model import (
    GARMENT,
    GARMENT_ID,
    GARMENT_MAX,
    PHOTO_PURPOSE,
    aad_garment,
    new_garment_id,
    new_garment_words,
)

_ID_RE = re.compile(GARMENT_ID)
SUFFIX = ", not in your wardrobe"


def checked(kind: str, colour: str) -> GarmentIn:
    try:
        return GarmentIn(type=kind, colour=colour)
    except ValidationError:
        raise SeeMeRefused(422, "not_a_garment", texts.NOT_A_GARMENT) from None


def short_words(kind: str, colour: str) -> str:
    """ "a new navy shirt": the words sent to Google and said in the confirm."""
    return new_garment_words(colour, kind).removesuffix(SUFFIX)


def _at(doc: dict[str, Any]) -> datetime:
    return datetime.fromisoformat(str(doc["at"]))


class GarmentStore:
    def __init__(
        self, docs: Docs, prefix: str, sealer: Sealer | None, *, now: Callable[[], datetime]
    ) -> None:
        self.docs, self.prefix, self.now = docs, prefix, now
        self._sealer = sealer  # None: the daily job's deletes by path only

    @property
    def sealer(self) -> Sealer:
        if self._sealer is None:
            raise RuntimeError("no token key: a garment's photo can't be sealed or opened")
        return self._sealer

    def path(self, uid: str, gid: str) -> str:
        return f"{self.prefix}{GARMENT}/{uid}_{gid}"

    async def rows(self, uid: str) -> list[tuple[str, dict[str, Any]]]:
        rows = await self.docs.query(Query(f"{self.prefix}{GARMENT}", where=("owner", uid)))
        return [(i.removeprefix(f"{uid}_"), d) for i, d in rows if i.startswith(f"{uid}_")]

    async def save(
        self, uid: str, kind: str, colour: str, data: bytes, *, keep_days: int, max_kb: int = 700
    ) -> GarmentView:
        asked = checked(kind, colour)
        clean = clean_jpeg(data, max_kb=max_kb)
        if len(await self.rows(uid)) >= GARMENT_MAX:
            raise SeeMeRefused(409, "too_many", texts.TOO_MANY.format(n=GARMENT_MAX))
        gid, at = new_garment_id(), self.now()
        body = sealed_doc(self.sealer, uid, aad_garment(uid, gid), clean, at)
        doc = {**body, "type": asked.type, "colour": asked.colour}
        await self.docs.write([Set(self.path(uid, gid), doc)])
        return self._view(gid, doc, keep_days, False)

    def _view(self, gid: str, doc: dict[str, Any], keep_days: int, kept: bool) -> GarmentView:
        at = _at(doc)
        return GarmentView(
            id=gid, type=doc["type"], colour=doc["colour"],
            words=new_garment_words(doc["colour"], doc["type"]), at=at,
            until=None if kept else at + timedelta(days=keep_days), kept=kept,
            bytes=int(doc.get("bytes", 0)),
        )  # fmt: skip

    async def meta(self, uid: str, gid: str, *, keep_days: int = 30) -> GarmentView | None:
        if not _ID_RE.match(gid):
            return None
        doc = await self.docs.get(self.path(uid, gid))
        if doc is None or doc.get("owner") != uid:
            return None
        try:
            return self._view(gid, doc, keep_days, False)
        except (KeyError, ValueError, ValidationError):
            return None  # an unreadable one is never used

    async def new(self, uid: str, gid: str) -> NewGarment | None:
        g = await self.meta(uid, gid)
        return None if g is None else NewGarment(id=g.id, words=g.words)

    async def listed(self, uid: str, *, keep_days: int, kept: Collection[str]) -> GarmentList:
        out: list[GarmentView] = []
        for gid, doc in sorted(await self.rows(uid), key=lambda r: (str(r[1].get("at")), r[0])):
            try:
                out.append(self._view(gid, doc, keep_days, gid in kept))
            except (KeyError, ValueError, ValidationError):
                continue
        return GarmentList(garments=tuple(out[-GARMENT_MAX:]))

    async def get(self, uid: str, gid: str) -> bytes | None:
        if not _ID_RE.match(gid):
            return None
        doc = await self.docs.get(self.path(uid, gid))
        if doc is None or doc.get("owner") != uid:
            return None
        return self.sealer.open(PHOTO_PURPOSE, aad_garment(uid, gid), doc.get("blob"))

    async def delete(self, uid: str, gid: str) -> bool:
        if not _ID_RE.match(gid) or await self.meta(uid, gid) is None:
            return False
        await self.docs.write([Delete(self.path(uid, gid))])
        return True

    async def expired(self, uid: str, *, keep_days: int, kept: Collection[str]) -> list[str]:
        """The paths `seeme_daily` deletes: past their time and shown by no kept picture."""
        cutoff = self.now() - timedelta(days=keep_days)
        out: list[str] = []
        for gid, doc in await self.rows(uid):
            try:
                old = _at(doc) <= cutoff
            except (KeyError, ValueError):
                old = True  # an unreadable one is never kept
            if old and gid not in kept:
                out.append(self.path(uid, gid))
        return out


__all__ = ["SUFFIX", "GarmentStore", "checked", "short_words"]
