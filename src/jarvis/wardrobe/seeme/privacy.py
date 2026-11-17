# src/jarvis/wardrobe/seeme/privacy.py
"""R13.1 Part C's three Privacy rows, section "Try-on" (docs/plans/r13-1-try-on.md D16; plan review
M4, M10), on `WardrobePart.privacy` (never `data`), in `kept.ROW_IDS`' order, with I0's words
(`kept.SPECS`, the one source):

- `tryon_photo` "Your photo for See it on me, and your YES": the export says when and how big,
  never the photo; the delete (his passkey) takes the photo and his YES.
- `tryon_pictures` "See it on me pictures and garment photos": the export lists them (ids, when,
  kept, fixed words, ₹), never a picture's or a photo's bytes; the delete (his passkey) takes them.
- `tryon_spend` "Try-on spend": numbers per month; not deletable (his cap's record, 13 months).

A part that is off or failed gets I0's stand-ins instead (`kept.stand_ins`).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from jarvis.privacy.ports import PrivacySource
from jarvis.privacy.sources import CallbackSource, Look
from jarvis.storage.docs import Delete
from jarvis.wardrobe.seeme.texts import SeeMeRefused
from jarvis.wardrobe.tryon import kept
from jarvis.wardrobe.tryon.model import CONSENT

if TYPE_CHECKING:
    from jarvis.wardrobe.seeme.part import SeeMeService


def _photo_row(svc: SeeMeService) -> CallbackSource:
    k = svc.kit

    async def look(uid: str) -> Look:
        photo, given = await k.photo.view(uid), await k.consent.given_at(uid)
        n = int(photo.kept) + int(await _consent_kept(svc, uid))
        basis = (photo.at.isoformat() if photo.at else "", photo.bytes, str(given))
        return Look(n, basis, deletable=n > 0)

    async def export(uid: str) -> dict[str, Any]:
        photo, given = await k.photo.view(uid), await k.consent.given_at(uid)
        return {
            "photo": {"kept": photo.kept, "at": photo.at.isoformat() if photo.at else None,
                      "bytes": photo.bytes},  # when and how big: never the photo
            "yes": {"given": given is not None, "at": given.isoformat() if given else None},
        }  # fmt: skip

    async def delete(uid: str) -> int:
        n = (await look(uid)).count or 0
        await svc.delete_photo(uid)  # his photo and his YES; page memory too
        return n

    return CallbackSource(kept.SPECS[kept.PHOTO_ID], look, export, delete)


async def _consent_kept(svc: SeeMeService, uid: str) -> bool:
    docs = svc.kit.ctx.docs
    path = f"{svc.kit.ctx.s.firestore_prefix}{CONSENT}/{uid}"
    return docs is not None and await docs.get(path) is not None


def _pictures_row(svc: SeeMeService) -> CallbackSource:
    k = svc.kit

    async def look(uid: str) -> Look:
        pics, gars = await k.pictures.rows(uid), await k.garments.rows(uid)
        return Look(len(pics) + len(gars), sorted([i for i, _ in pics] + [i for i, _ in gars]),
                    deletable=bool(pics or gars))  # fmt: skip

    async def export(uid: str) -> dict[str, Any]:
        days = await svc._keep_days_safe(uid)  # noqa: SLF001 - the part's own helper
        pictures = [
            {"id": p.id, "made_at": p.made_at.isoformat(), "kept": p.kept,
             "garment": p.garment.words, "with": [s.words for s in p.sent], "inr": p.inr}
            for p in await k.pictures.listed(uid, keep_days=days)
        ]  # fmt: skip
        garments = [
            {"id": g.id, "words": g.words, "at": g.at.isoformat(), "bytes": g.bytes}
            for g in (await svc.garments(uid)).garments
        ]
        return {"pictures": pictures, "garments": garments}  # never their bytes

    async def delete(uid: str) -> int:
        paths = [k.pictures.path(uid, i) for i, _ in await k.pictures.rows(uid)]
        paths += [k.garments.path(uid, i) for i, _ in await k.garments.rows(uid)]
        if paths and k.ctx.docs is not None:
            await k.ctx.docs.write([Delete(p) for p in paths])
        return len(paths) + await k.pictures.delete_all(uid)  # one saved meanwhile; page memory

    return CallbackSource(kept.SPECS[kept.PICTURES_ID], look, export, delete)


def _spend_row(svc: SeeMeService) -> CallbackSource:
    cap = svc.kit.cap

    async def look(uid: str) -> Look:
        try:
            months = await cap.months(uid)
        except SeeMeRefused:
            return Look(None, note=kept.CANT_OPEN, deletable=False)
        return Look(len(months), [(m.month, m.spent_inr, m.pictures) for m in months],
                    deletable=False)  # fmt: skip

    async def export(uid: str) -> dict[str, Any]:
        return {
            "months": [
                {"month": m.month, "spent_inr": round(m.spent_inr, 2),
                 "held_inr": round(m.held_inr, 2), "pictures": m.pictures, "blocked": m.blocked}
                for m in await cap.months(uid)
            ]
        }  # fmt: skip

    return CallbackSource(kept.SPECS[kept.SPEND_ID], look, export, None)


def rows(svc: SeeMeService) -> tuple[PrivacySource, ...]:
    return (_photo_row(svc), _pictures_row(svc), _spend_row(svc))


__all__ = ["rows"]
