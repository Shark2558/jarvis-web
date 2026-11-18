# src/jarvis/wardrobe/seeme/part.py
"""R13.1 Part C's one join (docs/plans/r13-1-try-on.md "Part split" C, D10-D16, D22):
`build(ctx) -> WardrobePart("seeme", daily_jobs=(seeme_daily,), privacy=(three rows),
services={"seeme": SeeMeService}, ready=...)`. No tool, no `data` (its Privacy rows ride
`privacy`, M4). The try-on provider is `ctx.tryon()`, read at call time (None while pictures are
off); billing and No-AI mode are read late from the app (`ctx.state`).

- No storage: nothing to keep, nothing offered. No token key: only the daily job (it deletes by
  path) and no rows, so the wiring gives I0's stand-ins ("Couldn't check right now") and A's
  OPS-05 erases C's half by path (`kept.erase_seeme`).
- `SeeMeService` is what the routes and A's OPS-05 call: his photo, consent, the garments and the
  pairing, the estimate, the press, the pictures, his settings, the overview, and `erase(uid)`
  (`tryon.ports.SeeMeErase`: the pictures, the garment photos, then his photo, then his YES;
  never the spend).
"""

from __future__ import annotations

from typing import Any

from jarvis.logging import get_logger
from jarvis.storage.docs import Delete
from jarvis.wardrobe.ports import WardrobeContext, WardrobePart
from jarvis.wardrobe.seeme import texts
from jarvis.wardrobe.seeme.books import Sending
from jarvis.wardrobe.seeme.cap import Prefs, TryonCap
from jarvis.wardrobe.seeme.consent import Consent, day_words
from jarvis.wardrobe.seeme.estimate import figures, quote, rate_of, rupees
from jarvis.wardrobe.seeme.garments import GarmentStore, short_words
from jarvis.wardrobe.seeme.jobs import SeeMeDaily
from jarvis.wardrobe.seeme.make import Kit, Press, no_ai, off_reason
from jarvis.wardrobe.seeme.pair import Pairer, split
from jarvis.wardrobe.seeme.pictures import PictureStore
from jarvis.wardrobe.seeme.privacy import rows
from jarvis.wardrobe.seeme.texts import SeeMeRefused
from jarvis.wardrobe.seeme.vault import PersonPhoto, Sealer
from jarvis.wardrobe.tryon import http
from jarvis.wardrobe.tryon.model import CONSENT, PERSON

log = get_logger(__name__)
READY = "Ready: See it on me."
READY_OFF = "Ready: See it on me stays off until pictures are set up on this server."
TYPICAL_GARMENTS = 2  # the overview's figure: the new garment and one of his


class SeeMeService:
    def __init__(self, kit: Kit) -> None:
        self.kit, self._press = kit, Press(kit)

    # ---- his photo, his YES -------------------------------------------------------------------
    async def save_photo(self, uid: str, data: bytes) -> http.PhotoView:
        return await self.kit.photo.save(uid, data, max_kb=self.kit.ctx.s.tryon_photo_max_kb)

    async def photo(self, uid: str) -> bytes | None:
        return await self.kit.photo.get(uid)

    async def delete_photo(self, uid: str) -> bool:
        """His withdrawal: his photo and his YES; a shown-once picture goes from page memory."""
        gone = await self.kit.photo.delete(uid)
        self.kit.pictures.once.clear(uid)
        return gone

    def _provider(self) -> Any:
        provider = self.kit.provider()
        if provider is None or not self.kit.ctx.s.tryon_pictures:
            raise SeeMeRefused(503, "not_configured", texts.OFF_PICTURES)
        return provider

    async def give_consent(self, uid: str, typed: str, version: str) -> http.ConsentView:
        desc, cache = self._provider().describe(), self.kit.ctx.s.tryon_cache
        return await self.kit.consent.give(uid, typed, version, desc, cache=cache)

    # ---- a garment he is thinking of buying (D22) ---------------------------------------------
    async def _keep_days(self, uid: str) -> int:
        return self.kit.keep_days(await self.kit.cap.prefs(uid))

    async def add_garment(self, uid: str, kind: str, colour: str, data: bytes) -> http.GarmentView:
        return await self.kit.garments.save(
            uid, kind, colour, data, keep_days=await self._keep_days(uid),
            max_kb=self.kit.ctx.s.tryon_photo_max_kb,
        )  # fmt: skip

    async def garments(self, uid: str) -> http.GarmentList:
        kept = await self.kit.pictures.kept_garments(uid)
        return await self.kit.garments.listed(uid, keep_days=await self._keep_days(uid), kept=kept)

    async def garment_photo(self, uid: str, gid: str) -> bytes | None:
        return await self.kit.garments.get(uid, gid)

    async def delete_garment(self, uid: str, gid: str) -> bool:
        return await self.kit.garments.delete(uid, gid)

    async def _garment(self, uid: str, gid: str) -> http.GarmentView:
        g = await self.kit.garments.meta(uid, gid)
        if g is None:
            raise SeeMeRefused(404, "no_garment", texts.NO_GARMENT)
        return g

    async def pair(self, uid: str, gid: str) -> http.Pairing:
        return await self.kit.pairer.pair(uid, await self._garment(uid, gid))

    # ---- the estimate, the press, the pictures ------------------------------------------------
    async def estimate(self, uid: str, gid: str, pieces: list[str]) -> http.Estimate:
        refused = await off_reason(self.kit, uid)
        if refused is not None:
            raise refused
        g, store = await self._garment(uid, gid), self.kit.ctx.store()
        if store is None:
            raise SeeMeRefused(503, "not_configured", texts.NO_WARDROBE)
        view = await store.view(uid)
        sent, not_sent = await split(self.kit.ctx, uid, view, pieces, garment_slot=g.slot)
        rate = await rate_of(self.kit.billing(), self.kit.ctx.s.usd_inr_rate)
        tax = self.kit.ctx.s.tryon_tax_pct
        fig = figures(self._provider(), garments=1 + len(sent), rate=rate, tax_pct=tax)
        prefs, month = await self.kit.cap.prefs(uid), await self.kit.cap.month(uid)
        rest = await self._rest(uid, g, {m.piece for m in sent} | set(pieces))
        return quote(
            fig, tax_pct=tax, garment=http.NewGarment(id=g.id, words=g.words),
            garment_words=short_words(g.type, g.colour), sent=tuple(m.sent() for m in sent),
            not_sent=(*not_sent, *rest), spent=month.spent_inr, held=month.held_inr,
            cap=self.kit.cap_inr(prefs), room=await self._room(uid),
        )  # fmt: skip

    async def _rest(self, uid: str, g: http.GarmentView, asked: set[str]) -> list[http.NotSent]:
        found = await self.kit.pairer.look(uid, g)
        if found is None:
            return []
        paired, rest = await self.kit.pairer.from_look(uid, found[0], found[1], g.slot)
        unticked = [m.unticked() for m in paired if m.piece not in asked]
        return [*unticked, *(n for n in rest if n.piece not in asked)]

    async def _room(self, uid: str) -> float | None:
        """His overall limit's room this month (None: no limit set; 0 when it can't be read)."""
        billing = self.kit.billing()
        try:
            limit = await billing.budgets.get(uid)
            if limit is None:
                return None
            month = billing.meter.month_of(billing.clock())
            used = (await billing.meter.get(uid, month)).inr_total
        except Exception as exc:  # noqa: BLE001 - can't tell: no room (fail closed), said
            log.warning(
                "see it on me: his limit's room can't be read", extra={"error": type(exc).__name__}
            )
            return 0.0
        return max(0.0, float(limit) - float(used))

    async def press(
        self, uid: str, body: http.PictureIn, *, on_send: Sending | None = None
    ) -> http.PictureView:
        """The paid press; `on_send(hold_inr)` runs after the reserve, before the call."""
        return await self._press.press(uid, body, on_send=on_send)

    async def picture(self, uid: str, pid: str) -> tuple[bytes, str] | None:
        await self.tidy(uid)
        return await self.kit.pictures.get(uid, pid)

    async def tidy(self, uid: str) -> None:
        """A picture of a piece now private or gone goes before anything shows it (finding 4).
        His wardrobe unreadable just now: the panel still opens; the morning job is the backstop."""
        store = self.kit.ctx.store()
        try:
            await self.kit.pictures.drop_taken(uid, await store.view(uid) if store else None)
        except Exception as exc:  # noqa: BLE001 - logged; seeme_daily deletes it in the morning
            log.warning("see it on me: pictures not tidied", extra={"error": type(exc).__name__})

    async def keep(self, uid: str, pid: str, keep: bool) -> http.PictureView:
        return await self.kit.pictures.keep(uid, pid, keep, keep_days=await self._keep_days(uid))

    async def delete_picture(self, uid: str, pid: str) -> bool:
        return await self.kit.pictures.delete(uid, pid)

    # ---- the overview and his settings --------------------------------------------------------
    async def overview(self, uid: str) -> http.SeeMeView:
        k, s = self.kit, self.kit.ctx.s
        refused = await _safe_off(k, uid)
        if refused is None and await no_ai(k, uid):
            refused = SeeMeRefused(503, "no_ai", texts.NO_AI)
        provider = k.provider() if s.tryon_pictures else None
        soon, _ = await k.ends(uid)
        month = await self._month(uid)
        await self.tidy(uid)
        out: dict[str, Any] = {
            "ready": READY if provider is not None else READY_OFF, "on": refused is None,
            "why": "" if refused is None else refused.words, "photo": await k.photo.view(uid),
            "month": month, "tax_pct": s.tryon_tax_pct, "photo_max_kb": s.tryon_photo_max_kb,
            "pictures": await k.pictures.listed(uid, keep_days=await self._keep_days_safe(uid)),
        }  # fmt: skip
        if provider is not None:
            out |= await self._provider_half(uid, provider, soon)
        return http.SeeMeView(**out)

    async def _provider_half(self, uid: str, provider: Any, soon: bool) -> dict[str, Any]:
        k, s, d = self.kit, self.kit.ctx.s, provider.describe()
        rate = await rate_of(k.billing(), s.usd_inr_rate)
        fig = figures(provider, garments=TYPICAL_GARMENTS, rate=rate, tax_pct=s.tryon_tax_pct)
        day = day_words(d.retires_on)  # the model's own date: one source (review C-1, 6)
        return {
            "provider": http.ProviderView(
                provider=d.provider, model=d.model, model_words=d.model_words,
                location=d.location, location_words=d.location_words,
                max_garments=d.max_garments, retires_on=d.retires_on, ends_soon=soon,
            ),
            "consent": await k.consent.view(uid, d, cache=s.tryon_cache),
            "typical_inr": fig.typical_inr, "hold_inr": fig.hold_inr,
            "notice": texts.NOTICE.format(day=day) if soon else "",
        }  # fmt: skip

    async def _month(self, uid: str) -> http.MonthView | None:
        try:
            m, prefs = await self.kit.cap.month(uid), await self.kit.cap.prefs(uid)
        except SeeMeRefused:
            return None  # unreadable: shown as nothing, and the press refuses (fail closed)
        return http.MonthView(
            month=m.month, spent_inr=round(m.spent_inr, 2), held_inr=round(m.held_inr, 2),
            cap_inr=self.kit.cap_inr(prefs), pictures=m.pictures, blocked=m.blocked,
        )  # fmt: skip

    async def _keep_days_safe(self, uid: str) -> int:
        try:
            return await self._keep_days(uid)
        except SeeMeRefused:
            return self.kit.ctx.s.tryon_keep_days

    async def settings(
        self, uid: str, *, on: bool | None, cap_inr: int | None, keep_days: int | None,
        confirm_cost: bool,
    ) -> http.SeeMeView:  # fmt: skip
        prefs = await self.kit.cap.prefs(uid)
        if cap_inr is not None and cap_inr > self.kit.cap_inr(prefs) and not confirm_cost:
            raise SeeMeRefused(422, "confirm_cost", texts.RAISE_CONFIRM.format(cap=rupees(cap_inr)))
        new = Prefs(
            on=prefs.on if on is None else on,
            cap_inr=prefs.cap_inr if cap_inr is None else cap_inr,
            keep_days=prefs.keep_days if keep_days is None else keep_days,
        )
        await self.kit.cap.set_prefs(uid, new)
        return await self.overview(uid)

    # ---- OPS-05's half (tryon.ports.SeeMeErase) -----------------------------------------------
    async def erase(self, uid: str) -> int:
        """His pictures, the garment photos, then his photo, then his YES; never the spend."""
        k = self.kit
        docs = k.ctx.docs
        assert docs is not None  # built only with storage
        paths = [k.pictures.path(uid, pid) for pid, _ in await k.pictures.rows(uid)]
        paths += [k.garments.path(uid, gid) for gid, _ in await k.garments.rows(uid)]
        for single in (PERSON, CONSENT):
            path = f"{k.ctx.s.firestore_prefix}{single}/{uid}"
            if await docs.get(path) is not None:
                paths.append(path)
        if paths:
            await docs.write([Delete(p) for p in paths])  # in this order (one chunk)
        # a picture saved between the list and the delete (a press in flight) goes too; then
        # page memory (`delete_all` clears it)
        return len(paths) + await k.pictures.delete_all(uid)


async def _safe_off(kit: Kit, uid: str) -> SeeMeRefused | None:
    try:
        return await off_reason(kit, uid)
    except SeeMeRefused as exc:  # his settings unreadable: off, in its words
        return exc


def build(ctx: WardrobeContext) -> WardrobePart:
    if ctx.docs is None:
        return WardrobePart("seeme", ready=f"off: {texts.OFF_NO_STORE}")
    docs, prefix = ctx.docs, ctx.s.firestore_prefix
    cap = TryonCap(docs, prefix, tz=ctx.s.user_timezone, now=ctx.now)
    sealer = Sealer(ctx.keyring) if ctx.keyring is not None else None
    pictures = PictureStore(docs, prefix, sealer, now=ctx.now)
    garments = GarmentStore(docs, prefix, sealer, now=ctx.now)
    job = SeeMeDaily(ctx, pictures, garments, cap)
    if sealer is None:  # only the job (by path); I0's stand-in rows; A erases C's half by path
        return WardrobePart("seeme", daily_jobs=(job,), ready=f"off: {texts.OFF_NO_KEY}")
    kit = Kit(
        ctx=ctx, photo=PersonPhoto(docs, prefix, sealer, now=ctx.now),
        consent=Consent(docs, prefix, sealer, now=ctx.now), garments=garments,
        pictures=pictures, cap=cap, pairer=Pairer(ctx),
    )  # fmt: skip
    service = SeeMeService(kit)
    on = ctx.s.tryon_pictures and ctx.s.tryon_enabled
    return WardrobePart(
        "seeme", daily_jobs=(job,), privacy=rows(service), services={"seeme": service},
        ready=READY if on else READY_OFF,
    )  # fmt: skip


__all__ = ["READY", "READY_OFF", "SeeMeService", "build"]
