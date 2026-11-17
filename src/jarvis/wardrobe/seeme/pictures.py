# src/jarvis/wardrobe/seeme/pictures.py
"""R13.1 Part C: the pictures (docs/plans/r13-1-try-on.md D10, D13.6-D13.7, D14; plan review L5).

    {prefix}tryon_picture/{uid}_{id}   {v, kid, owner, at, kept, garment, garment_type,
                                       garment_colour, pieces, sent, not_sent, inr, tokens, mime,
                                       bytes, blob, updated_at}
        id `tp_` + 12 hex; blob = AES-GCM(the picture AS GOOGLE RETURNED IT), purpose
        `tryon_photos`, AAD `model.aad_picture(uid, id)`. The plain fields are ids, numbers and
        FIXED words (a type and a colour): never a label of his, a private piece or Google's text.

- A picture is kept only when it is at most 700 KB (a sealed envelope must fit a document);
  a bigger one is shown ONCE from page memory (`OnceCache`, never on disk) and not kept, said.
  Its structure was checked by the adapter (JPEG or PNG by its magic bytes); it is never decoded
  or re-encoded here, so its Content Credentials stay. Served with its detected type.
- Kept `keep_days` (30, the owner's answer to question 3) unless Keep (at most `KEPT_MAX`, 24).
  `expired` names what `seeme_daily` deletes: past its time and not kept, or showing a piece of
  his that is now private or gone.
- `sent` is what of his was SENT (the request's own pieces, never a plan's list); `not_sent` the
  rest of the look the console lists as "not in the picture".
- A press in flight never outlives a delete (review C-1, finding 3): `save` keeps the picture
  only while his photo, his YES and the garment's photo are still his, checked and written in
  ONE transaction; `delete_all` (OPS-05, the Privacy row) lists, deletes, then sweeps once more,
  so a picture saved between its list and its delete goes too; page memory is cleared after.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from pydantic import ValidationError

from jarvis.llm.tryon import TryOnUsage
from jarvis.storage.docs import Delete, Docs, DocTx, Query, Set
from jarvis.wardrobe.model import WardrobeView
from jarvis.wardrobe.seeme import texts
from jarvis.wardrobe.seeme.texts import SeeMeRefused
from jarvis.wardrobe.seeme.vault import VERSION, Sealer
from jarvis.wardrobe.tryon.http import NewGarment, NotSent, PictureView, SentPiece
from jarvis.wardrobe.tryon.model import (
    CREDENTIALS,
    GENERATED,
    KEPT_MAX,
    LISTED_MAX,
    PHOTO_PURPOSE,
    PICTURE,
    PICTURE_ID,
    aad_picture,
    new_garment_words,
)

KEEP_MAX_BYTES = 700 * 1024
ONCE_MAX, ONCE_S = 2, 600.0  # at most two big pictures in page memory, 10 minutes
_ID = re.compile(PICTURE_ID)


@dataclass(frozen=True)
class Made:
    """What the press hands over: the picture and everything its view names."""

    picture: bytes
    mime: str
    made_at: datetime
    garment: NewGarment
    garment_type: str
    garment_colour: str
    sent: tuple[SentPiece, ...]
    not_sent: tuple[NotSent, ...]
    inr: float
    usage: TryOnUsage | None


class OnceCache:
    """A picture too big to keep: shown once, from page memory, within 10 minutes."""

    def __init__(self, now: Callable[[], datetime]) -> None:
        self._now, self._items = now, dict[tuple[str, str], tuple[bytes, str, datetime]]()

    def put(self, uid: str, pid: str, data: bytes, mime: str) -> None:
        self._items[(uid, pid)] = (data, mime, self._now())
        while len(self._items) > ONCE_MAX:
            self._items.pop(next(iter(self._items)))

    def clear(self, uid: str) -> None:
        for key in [k for k in self._items if k[0] == uid]:
            del self._items[key]

    def discard(self, uid: str, pid: str) -> None:
        self._items.pop((uid, pid), None)

    def take(self, uid: str, pid: str) -> tuple[bytes, str] | None:
        found = self._items.pop((uid, pid), None)
        if found is None or (self._now() - found[2]).total_seconds() > ONCE_S:
            return None
        return found[0], found[1]


def _doc(uid: str, pid: str, made: Made, sealer: Sealer, at: str) -> dict[str, Any]:
    usage = made.usage
    tokens = None if usage is None else [usage.input_tokens, usage.image_tokens, usage.text_tokens]
    return {
        "v": VERSION, "kid": sealer.kid, "owner": uid, "at": made.made_at.isoformat(),
        "kept": False, "garment": made.garment.id, "garment_type": made.garment_type,
        "garment_colour": made.garment_colour, "pieces": [p.piece for p in made.sent],
        "sent": [p.model_dump(mode="json") for p in made.sent],
        "not_sent": [n.model_dump(mode="json") for n in made.not_sent],
        "inr": made.inr, "tokens": tokens, "mime": made.mime, "bytes": len(made.picture),
        "blob": sealer.seal(PHOTO_PURPOSE, aad_picture(uid, pid), made.picture),
        "updated_at": at,
    }  # fmt: skip


def view_of(pid: str, doc: dict[str, Any], keep_days: int) -> PictureView:
    at = datetime.fromisoformat(str(doc["at"]))
    kept = doc.get("kept") is True
    words = new_garment_words(str(doc["garment_colour"]), str(doc["garment_type"]))
    return PictureView(
        id=pid, made_at=at, garment=NewGarment(id=doc["garment"], words=words),
        until=None if kept else at + timedelta(days=keep_days), kept=kept,
        inr=float(doc.get("inr", 0.0)), sent=tuple(SentPiece(**p) for p in doc.get("sent", ())),
        not_sent=tuple(NotSent(**n) for n in doc.get("not_sent", ())), mime=doc["mime"],
        label=GENERATED, credentials=CREDENTIALS,
    )  # fmt: skip


class PictureStore:
    def __init__(
        self, docs: Docs, prefix: str, sealer: Sealer | None, *, now: Callable[[], datetime]
    ) -> None:
        self.docs, self.prefix, self.now = docs, prefix, now
        self._sealer = sealer  # None: the daily job's deletes by path only
        self.once = OnceCache(now)

    @property
    def sealer(self) -> Sealer:
        if self._sealer is None:
            raise RuntimeError("no token key: pictures can't be sealed or opened")
        return self._sealer

    def path(self, uid: str, pid: str) -> str:
        return f"{self.prefix}{PICTURE}/{uid}_{pid}"

    async def rows(self, uid: str) -> list[tuple[str, dict[str, Any]]]:
        rows = await self.docs.query(Query(f"{self.prefix}{PICTURE}", where=("owner", uid)))
        return [(i.removeprefix(f"{uid}_"), d) for i, d in rows if i.startswith(f"{uid}_")]

    async def save(
        self, uid: str, pid: str, made: Made, *, keep_days: int, needs: Sequence[str] = ()
    ) -> PictureView | None:
        """Kept (or shown once when too big) only while every document in `needs` is still his;
        None when one went while the picture was being made (nothing kept)."""
        doc = _doc(uid, pid, made, self.sealer, self.now().isoformat())
        if len(made.picture) > KEEP_MAX_BYTES:
            self.once.put(uid, pid, made.picture, made.mime)
            if not await self._all_his(self.docs, uid, needs):  # after the put: a delete's
                self.once.discard(uid, pid)  # clear of page memory may have come before it
                return None
            return view_of(pid, doc, keep_days).model_copy(update={"until": None})
        path = self.path(uid, pid)

        async def fn(tx: DocTx) -> bool:
            if not await self._all_his(tx, uid, needs):
                return False  # nothing written
            tx.set(path, doc)
            return True

        return view_of(pid, doc, keep_days) if await self.docs.transaction(fn) else None

    @staticmethod
    async def _all_his(reader: Docs | DocTx, uid: str, needs: Sequence[str]) -> bool:
        for need in needs:
            found = await reader.get(need)
            if found is None or found.get("owner") != uid:
                return False
        return True

    async def delete_all(self, uid: str) -> int:
        """Every picture of his, then once more for one saved meanwhile; page memory after."""
        n = 0
        for _ in range(2):
            paths = [self.path(uid, pid) for pid, _ in await self.rows(uid)]
            if paths:
                await self.docs.write([Delete(p) for p in paths])
            n += len(paths)
        self.once.clear(uid)
        return n

    async def _mine(self, uid: str, pid: str) -> dict[str, Any] | None:
        if not _ID.fullmatch(pid):  # fullmatch: `$` alone lets a trailing newline through
            return None
        doc = await self.docs.get(self.path(uid, pid))
        return doc if doc is not None and doc.get("owner") == uid else None

    async def view(self, uid: str, pid: str, *, keep_days: int) -> PictureView | None:
        doc = await self._mine(uid, pid)
        try:
            return None if doc is None else view_of(pid, doc, keep_days)
        except (KeyError, ValueError, TypeError, ValidationError):
            return None

    async def listed(self, uid: str, *, keep_days: int) -> tuple[PictureView, ...]:
        out: list[PictureView] = []
        for pid, doc in sorted(await self.rows(uid), key=lambda r: (str(r[1].get("at")), r[0]))[
            ::-1
        ]:
            try:
                out.append(view_of(pid, doc, keep_days))
            except (KeyError, ValueError, TypeError, ValidationError):
                continue  # an unreadable one is not listed (seeme_daily deletes it)
        return tuple(out[:LISTED_MAX])

    async def get(self, uid: str, pid: str) -> tuple[bytes, str] | None:
        once = self.once.take(uid, pid)
        if once is not None:
            return once
        doc = await self._mine(uid, pid)
        if doc is None or doc.get("mime") not in ("image/jpeg", "image/png"):
            return None
        data = self.sealer.open(PHOTO_PURPOSE, aad_picture(uid, pid), doc.get("blob"))
        return None if data is None else (data, str(doc["mime"]))

    async def keep(self, uid: str, pid: str, keep: bool, *, keep_days: int) -> PictureView:
        doc = await self._mine(uid, pid)
        if doc is None:
            raise SeeMeRefused(404, "gone", texts.PICTURE_GONE)
        if keep and doc.get("kept") is not True:
            kept = sum(1 for _, d in await self.rows(uid) if d.get("kept") is True)
            if kept >= KEPT_MAX:
                raise SeeMeRefused(409, "too_many", texts.TOO_MANY_KEPT.format(n=KEPT_MAX))
        new = {**doc, "kept": keep, "updated_at": self.now().isoformat()}
        await self.docs.write([Set(self.path(uid, pid), new)])
        return view_of(pid, new, keep_days)

    async def delete(self, uid: str, pid: str) -> bool:
        if await self._mine(uid, pid) is None:
            return False
        await self.docs.write([Delete(self.path(uid, pid))])
        return True

    async def kept_garments(self, uid: str) -> set[str]:
        return {str(d.get("garment")) for _, d in await self.rows(uid) if d.get("kept") is True}

    async def expired(self, uid: str, *, keep_days: int, view: WardrobeView | None) -> list[str]:
        """Past its time and not kept, unreadable, or showing a piece now private or gone."""
        cutoff = self.now() - timedelta(days=keep_days)
        out: list[str] = []
        for pid, doc in await self.rows(uid):
            if _gone(doc, cutoff, view):
                out.append(self.path(uid, pid))
        return out


def _gone(doc: dict[str, Any], cutoff: datetime, view: WardrobeView | None) -> bool:
    try:
        at = datetime.fromisoformat(str(doc["at"]))
    except (KeyError, ValueError):
        return True
    if doc.get("kept") is not True and at <= cutoff:
        return True
    return view is not None and _taken(doc.get("pieces", ()), view)


def _taken(pieces: Iterable[object], view: WardrobeView) -> bool:
    for pid in pieces:
        p = view.piece(str(pid))
        if p is None or p.private or p.merged_into is not None:
            return True
    return False


__all__ = ["KEEP_MAX_BYTES", "Made", "OnceCache", "PictureStore", "view_of"]
