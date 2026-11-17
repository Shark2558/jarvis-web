# src/jarvis/wardrobe/seeme/make.py
"""R13.1 Part C: the press, from the ₹ shown to the picture (docs/plans/r13-1-try-on.md D13.4-D13.7;
plan review L9, L10; review C-1).

The gates, in this order, each refusing BEFORE any spend (the route adds console-only and 6 presses
a minute first): pictures on (`tryon_pictures`, a provider, his own switch) and before the model's
own end date (`describe().retires_on`, the one source); not No-AI mode (`offline.mode.BrainMode`,
fail closed); his consent current (D11, with the cache); his photo kept; the new garment's photo
kept (404 `no_garment`); every piece of his sendable, from the RECORD (`pair.split`, never the
console's word), its crop opened, and every word sent a fixed word; `confirm_cost`; the fresh
typical ₹ at most `inr_shown` + ₹0.01 (409 `price_changed`); his overall monthly limit
(`billing.spend.ensure_spend_allowed` on the hold, fail closed); the cap's ATOMIC reserve of the
hold (`busy` and `cap_reached` inside it). Then ONE `make` (a 120 s deadline): settled from its
usage into the cap and his usage month (label `tryon`), at the hold without one; released in full
on `TryOnNotBilled`; kept at the hold on `TryOnMaybeBilled` and a blocked 200. A repeated request
id answers its first outcome (`done`), so a retry never charges twice. A picture is kept only
while his photo, his YES and the garment's photo are still there after the call (OPS-05, his
withdrawal or a Privacy delete during the call wins); it is still settled, as made. A settle or
release that fails after the cap's tries is kept by the cap for later; his usage month hears
every billed call whatever the settle did.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any

from jarvis.billing.service import BudgetReached, BudgetUnavailable
from jarvis.billing.spend import MSG_SPEND_UNAVAILABLE, ensure_spend_allowed, with_tax
from jarvis.llm.tryon import (
    MAX_GARMENTS,
    Garment,
    TryOnAsk,
    TryOnMaybeBilled,
    TryOnNotBilled,
    TryOnProvider,
    TryOnResult,
)
from jarvis.logging import get_logger
from jarvis.wardrobe.model import WardrobeView
from jarvis.wardrobe.ports import WardrobeContext
from jarvis.wardrobe.seeme import texts
from jarvis.wardrobe.seeme.cap import CapHold, Done, Prefs, TryonCap
from jarvis.wardrobe.seeme.consent import Consent
from jarvis.wardrobe.seeme.estimate import Figures, approx, figures, rate_of, settled_usd
from jarvis.wardrobe.seeme.garments import GarmentStore, short_words
from jarvis.wardrobe.seeme.pair import Mine, Pairer, refusal, sendable, split
from jarvis.wardrobe.seeme.pictures import Made, PictureStore
from jarvis.wardrobe.seeme.texts import SeeMeRefused
from jarvis.wardrobe.seeme.vault import PersonPhoto
from jarvis.wardrobe.tryon.http import (
    GarmentView,
    NewGarment,
    NotSent,
    PictureIn,
    PictureView,
    SentPiece,
)
from jarvis.wardrobe.tryon.model import CALL_DEADLINE_S, new_picture_id
from jarvis.wardrobe.tryon.ports import photo_vault

log = get_logger(__name__)
ENDS_SOON_DAYS = 30
SHOWN_SLACK = 0.01  # ₹: the fresh typical may be at most this above what he was shown
DEADLINE_SLACK_S = 5.0  # past the provider's own 120 s: a timeout here is "maybe billed"
_SAID = "about the price shown"  # a repeat's ₹ (it was said the first time)
WITHDRAWN = "withdrawn"  # made, but a photo it needs went during the call: not kept (billed)
REPEATED = {  # a repeated request id's refusal: the first answer's status, code and words
    "provider_unavailable": (503, "provider_unavailable", texts.UNAVAILABLE),
    "maybe_billed": (503, "provider_unavailable", texts.MAYBE_BILLED.format(about=_SAID)),
    "blocked": (502, "blocked", texts.BLOCKED.format(about=_SAID)),
    WITHDRAWN: (422, "no_photo", texts.WITHDRAWN.format(about=_SAID)),
}


@dataclass
class Kit:
    """Part C's stores over one context (built by `part.build`)."""

    ctx: WardrobeContext
    photo: PersonPhoto
    consent: Consent
    garments: GarmentStore
    pictures: PictureStore
    cap: TryonCap
    pairer: Pairer

    def provider(self) -> TryOnProvider | None:
        try:
            return self.ctx.tryon()
        except Exception as exc:  # noqa: BLE001 - a broken provider is "not configured"
            log.error("see it on me: no provider", extra={"error": type(exc).__name__})
            return None

    def billing(self) -> Any:
        return self.ctx.state("billing")

    def cap_inr(self, prefs: Prefs) -> int:
        return prefs.cap_inr if prefs.cap_inr is not None else self.ctx.s.tryon_month_cap_inr

    def keep_days(self, prefs: Prefs) -> int:
        return prefs.keep_days if prefs.keep_days is not None else self.ctx.s.tryon_keep_days

    async def today(self, uid: str) -> date:
        return self.ctx.now().astimezone(await self.ctx.zone(uid)).date()

    def retires_on(self) -> str:
        """The model's own end date (`describe().retires_on`, from `llm.tryon.RETIRES_ON`): the
        one source for the gate, the notice and the panel; "" when it names none (review C-1, 6)."""
        provider = self.provider()
        return provider.describe().retires_on if provider is not None else ""

    async def ends(self, uid: str) -> tuple[bool, bool]:
        """(the end date is within 30 days, it has come): D18, on his local day."""
        day = self.retires_on()
        if not day:
            return False, False  # no provider (off anyway), or a model with no end date known
        try:
            end = date.fromisoformat(day)
        except ValueError:
            return False, True  # an end date that can't be read: off (fail closed)
        today = await self.today(uid)
        return today >= end - timedelta(days=ENDS_SOON_DAYS), today >= end


async def off_reason(kit: Kit, uid: str) -> SeeMeRefused | None:
    s = kit.ctx.s
    if not s.tryon_enabled:
        return SeeMeRefused(503, "not_configured", texts.OFF_TRYON)
    if not s.tryon_pictures or kit.provider() is None:
        return SeeMeRefused(503, "not_configured", texts.OFF_PICTURES)
    if (await kit.ends(uid))[1]:
        return SeeMeRefused(503, "retired", texts.RETIRED)
    if not (await kit.cap.prefs(uid)).on:
        return SeeMeRefused(503, "not_configured", texts.OFF_BY_HIM)
    return None


async def no_ai(kit: Kit, uid: str) -> bool:
    mode = kit.ctx.state("brain_mode")
    if mode is None:
        return True  # can't tell: fail closed
    try:
        return bool(await mode.load(uid) == "none")
    except Exception:  # noqa: BLE001 - BrainMode fails closed itself; belt and braces
        return True


def sent_of(mine: Sequence[Mine]) -> tuple[SentPiece, ...]:
    """What of his the picture shows: exactly the pieces SENT (AVT-12), never a plan's list."""
    return tuple(m.sent() for m in mine)


class Press:
    def __init__(self, kit: Kit) -> None:
        self.kit = kit

    async def _on(self, uid: str) -> TryOnProvider:
        refused = await off_reason(self.kit, uid)
        if refused is not None:
            raise refused
        if await no_ai(self.kit, uid):
            raise SeeMeRefused(503, "no_ai", texts.NO_AI)
        provider = self.kit.provider()
        assert provider is not None  # off_reason checked it
        cache = self.kit.ctx.s.tryon_cache  # what Google keeps is part of what he agreed to
        if not await self.kit.consent.current(uid, provider.describe(), cache=cache):
            raise SeeMeRefused(409, "consent_needed", texts.CONSENT_NEEDED)
        return provider

    async def _view(self, uid: str) -> WardrobeView:
        store = self.kit.ctx.store()
        if store is None:
            raise SeeMeRefused(503, "not_configured", texts.NO_WARDROBE)
        return await store.view(uid)

    async def _garment(self, uid: str, gid: str) -> tuple[GarmentView, bytes]:
        g = await self.kit.garments.meta(uid, gid)
        data = await self.kit.garments.get(uid, gid) if g is not None else None
        if g is None or data is None:
            raise SeeMeRefused(404, "no_garment", texts.NO_GARMENT)
        return g, data

    async def mine(
        self, uid: str, view: WardrobeView, pieces: Sequence[str], slot: str
    ) -> tuple[list[Mine], list[bytes]]:
        """His pieces from the RECORD, each with its front crop; the first refusal in words."""
        sent, refused = await split(self.kit.ctx, uid, view, pieces, garment_slot=slot)
        if refused:
            raise refusal(refused[0])
        vault = photo_vault(self.kit.ctx)
        crops = [await vault.get(uid, m.photo) if vault is not None else None for m in sent]
        if any(c is None for c in crops):
            raise SeeMeRefused(422, "no_photo", texts.NO_FRONT)
        return sent, [c for c in crops if c is not None]

    async def _limit(self, uid: str, hold_inr: float) -> None:
        billing = self.kit.billing()
        if billing is None:
            raise SeeMeRefused(503, "cap_unreadable", MSG_SPEND_UNAVAILABLE)
        try:
            await ensure_spend_allowed(billing, uid, hold_inr)
        except BudgetReached as exc:
            raise SeeMeRefused(402, "budget_reached", str(exc)) from None
        except BudgetUnavailable as exc:
            raise SeeMeRefused(503, "cap_unreadable", str(exc)) from None

    async def answer(self, uid: str, outcome: Mapping[str, Any]) -> PictureView:
        """A request id answered before: the same picture, or the same refusal."""
        pid = outcome.get("picture")
        if isinstance(pid, str):
            prefs = await self.kit.cap.prefs(uid)
            found = await self.kit.pictures.view(uid, pid, keep_days=self.kit.keep_days(prefs))
            if found is not None:
                return found
            raise SeeMeRefused(404, "gone", texts.PICTURE_GONE)
        first = str(outcome.get("error"))
        status, code, words = REPEATED.get(first, REPEATED["provider_unavailable"])
        raise SeeMeRefused(status, code, words)

    async def press(self, uid: str, body: PictureIn) -> PictureView:
        done = (await self.kit.cap.month(uid)).done.get(body.request_id)
        if done is not None:
            return await self.answer(uid, done)
        provider = await self._on(uid)
        person = await self.kit.photo.get(uid)
        if person is None:
            raise SeeMeRefused(422, "no_photo", texts.NO_PHOTO)
        g, new = await self._garment(uid, body.garment)
        view = await self._view(uid)
        mine, crops = await self.mine(uid, view, body.pieces, g.slot)
        words = (short_words(g.type, g.colour), *(m.prompt for m in mine))  # fixed words only
        if not all(sendable(w) for w in words):  # JARVIS's own words: refused before any spend
            raise SeeMeRefused(422, "not_a_garment", texts.NO_WORDS)
        if not body.confirm_cost:
            raise SeeMeRefused(422, "confirm_cost", texts.CONFIRM_COST)
        rate = await rate_of(self.kit.billing(), self.kit.ctx.s.usd_inr_rate)
        fig = figures(
            provider, garments=1 + len(mine), rate=rate, tax_pct=self.kit.ctx.s.tryon_tax_pct
        )
        if fig.typical_inr > body.inr_shown + SHOWN_SLACK:
            raise SeeMeRefused(409, "price_changed", texts.PRICE_CHANGED)
        await self._limit(uid, fig.hold_inr)
        prefs = await self.kit.cap.prefs(uid)
        hold = await self.kit.cap.reserve(
            uid, body.request_id, fig.hold_inr, self.kit.cap_inr(prefs)
        )
        if isinstance(hold, Done):
            return await self.answer(uid, hold.outcome)
        garments = tuple(
            Garment(image=x, words=w) for x, w in zip((new, *crops), words, strict=True)
        )
        ask = TryOnAsk(person=person, garments=garments, timeout_s=CALL_DEADLINE_S)
        call = Call(provider, ask, hold, fig, g, mine, view, prefs)
        return await self._make(uid, call)

    async def _make(self, uid: str, call: Call) -> PictureView:
        try:
            async with asyncio.timeout(CALL_DEADLINE_S + DEADLINE_SLACK_S):  # whatever the provider
                result = await call.provider.make(call.ask)
        except TryOnNotBilled as exc:
            await _closed(
                self.kit.cap.release(call.hold, outcome={"error": "provider_unavailable"})
            )
            said = texts.GOOGLE_BUSY if str(exc) == "status_429" else texts.UNAVAILABLE
            raise SeeMeRefused(503, "provider_unavailable", said) from None
        except (TryOnMaybeBilled, TimeoutError) as exc:  # it may have left: kept at the hold
            why = {"error": type(exc).__name__, "request_id": call.hold.request_id}
            log.warning("see it on me: no picture, maybe billed", extra=why)
            raise await self._maybe(uid, call) from None
        except Exception as exc:  # noqa: BLE001 - a provider bug; the request may have left too
            why = {"error": type(exc).__name__, "request_id": call.hold.request_id}
            log.error("see it on me: a provider bug, kept at the hold", extra=why)
            raise await self._maybe(uid, call) from None
        if not result.made:
            await self._at_hold(uid, call, "blocked", blocked=True)
            words = texts.BLOCKED.format(about=f"about {approx(call.fig.typical_inr)}")
            raise SeeMeRefused(502, "blocked", words, inr=call.hold.inr)
        return await self._keep(uid, call, result)

    async def _maybe(self, uid: str, call: Call) -> SeeMeRefused:
        await self._at_hold(uid, call, "maybe_billed", blocked=False)
        words = texts.MAYBE_BILLED.format(about=f"about {approx(call.fig.typical_inr)}")
        return SeeMeRefused(503, "provider_unavailable", words, inr=call.hold.inr)

    async def _at_hold(self, uid: str, call: Call, code: str, *, blocked: bool) -> None:
        hold = call.hold
        try:
            await _closed(
                self.kit.cap.settle(hold, hold.inr, outcome={"error": code}, blocked=blocked)
            )
        finally:  # his usage month hears it, whatever the settle did
            await _record(self.kit, uid, call.provider.estimate(MAX_GARMENTS)[1])

    async def _keep(self, uid: str, call: Call, result: TryOnResult) -> PictureView:
        usd = settled_usd(call.provider, result.usage)
        tax = self.kit.ctx.s.tryon_tax_pct
        inr = call.hold.inr if usd is None else with_tax(usd * call.fig.rate, tax)
        pid = new_picture_id()
        outcome = {"picture": pid}
        try:  # made and billed: from here on, whatever fails, the cap and his month hear it
            made = Made(
                picture=result.picture or b"", mime=result.mime or "image/jpeg",
                made_at=self.kit.ctx.now(), garment=call.garment_new(),
                garment_type=call.garment.type, garment_colour=call.garment.colour,
                sent=sent_of(call.mine), not_sent=await self.not_sent(uid, call), inr=inr,
                usage=result.usage,
            )  # fmt: skip
            view = await self._save(uid, pid, call, made)
            if view is None:  # OPS-05, his withdrawal or a Privacy delete ran during the call
                outcome = {"error": WITHDRAWN}
                words = texts.WITHDRAWN.format(about=f"about {approx(inr)}")
                raise SeeMeRefused(422, "no_photo", words, inr=inr)
            return view
        finally:
            try:
                await _closed(self.kit.cap.settle(call.hold, inr, outcome=outcome, picture=True))
            finally:  # his usage month hears it, whatever the settle did
                worst = call.provider.estimate(MAX_GARMENTS)[1]
                await _record(self.kit, uid, usd if usd is not None else worst)

    async def _save(self, uid: str, pid: str, call: Call, made: Made) -> PictureView | None:
        """Kept only while his photo, his YES (still current) and the garment's photo are his;
        the last check and the write are one transaction (`PictureStore.save`'s `needs`)."""
        k = self.kit
        desc, cache = call.provider.describe(), k.ctx.s.tryon_cache
        if not (await k.photo.view(uid)).kept or not await k.consent.current(
            uid, desc, cache=cache
        ):
            return None
        needs = (k.photo.path(uid), k.consent.path(uid), k.garments.path(uid, call.garment.id))
        return await k.pictures.save(uid, pid, made, keep_days=k.keep_days(call.prefs), needs=needs)

    async def not_sent(self, uid: str, call: Call) -> tuple[NotSent, ...]:
        """The rest of the look around the garment: "not in the picture" (never a private id).
        Nothing when it can't be read: the picture is made and billed, so it is still shown."""
        try:
            found = await self.kit.pairer.look(uid, call.garment)
            if found is None:
                return ()
            view, picks = found
            paired, rest = await self.kit.pairer.from_look(uid, view, picks, call.garment.slot)
        except Exception as exc:  # noqa: BLE001 - a list beside the picture, never its loss
            log.warning("see it on me: no list beside it", extra={"error": type(exc).__name__})
            return ()
        sent = {m.piece for m in call.mine}
        unticked = [m.unticked() for m in paired if m.piece not in sent]
        return tuple([*unticked, *(n for n in rest if n.piece not in sent)])


@dataclass(frozen=True)
class Call:
    provider: TryOnProvider
    ask: TryOnAsk
    hold: CapHold
    fig: Figures
    garment: GarmentView
    mine: list[Mine]
    view: WardrobeView
    prefs: Prefs

    def garment_new(self) -> NewGarment:
        return NewGarment(id=self.garment.id, words=self.garment.words)


async def _closed(close: Awaitable[None]) -> None:
    """A settle or release. The cap tries it three times, then logs it at ERROR with its request
    id and keeps it for his next press and the daily job: never the reason a made picture, or the
    refusal he is owed, becomes "can't be reached"."""
    try:
        await close
    except Exception:  # noqa: BLE001 - logged and kept by the cap (`TryonCap.pending`)
        return


async def _record(kit: Kit, uid: str, usd: float) -> None:
    """His usage month, label `tryon` (Vitals: "Try-on"). `Billing.record` never raises; if it
    ever did, it is logged and the press goes on (the cap has counted the call)."""
    billing = kit.billing()
    if billing is None or usd <= 0:
        return
    try:
        await billing.record(uid, "tryon", usd)
    except Exception as exc:  # noqa: BLE001 - belt and braces
        log.error(
            "see it on me: his usage month missed a call", extra={"error": type(exc).__name__}
        )


__all__ = ["ENDS_SOON_DAYS", "Call", "Kit", "Press", "no_ai", "off_reason", "sent_of"]
