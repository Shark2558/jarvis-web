# src/jarvis/wardrobe/tryon/looks.py
"""R13.1 D5, D6, D7, D21 (AVT-04, AVT-05, AVT-06, AVT-14, row 388): the look the figure draws.

Every look is read FRESH from R13's own records: the plan and its look from R13's styling service
(`plans.read`, `answer`, `fresh`, the same answers "Today and tomorrow" shows), the wardrobe view
from A's store, his figure choices from `tryon/{uid}`. Three ways in:

- `for_plan(uid, plan, alt)`: a plan's look now (`alt` 1-2: the engine's alternatives);
- `for_day(uid, day, alt)`: the day's first look by R13's own rule for "what should I wear"
  (`Styling.planned`: today's plans only while not worn and not over), else R13's suggestion;
- `for_pieces(uid, "slot:wi_...,...")`: exactly the pieces on a reply's try-on card (row 388),
  each re-read now; a piece that isn't his any more is refused in words.

Each slot is a `LookSlot`: its template (his choice, else the table's), variants, colour, pattern,
texture view (his, else `detail`, else `front`) and that crop's id, the views kept and the useful
missing ones (`model.useful_views`) and each kept crop by its view (`refs`), readiness and
options (`options.py`), what is approximate, image card only, removable; `rgb` is None when he
set no colour. A private slot (`base`, `underwear`) or one holding a private piece is
COVERED: "Base layer (covered)" only; its piece and words only with `private=True` (his own panel's
"Show private basics"), and even then no template, colour, pattern, photo or option (AVT-14). A
gap of R13's that names a private piece is said without it.

A photo's view (front, back, detail) is the plain `view` field R13's catalog keeps on
`wardrobe_photo/{uid}_{photo}` (read only; the sealed crop itself is never opened here).
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from typing import get_args

from jarvis.storage.docs import Docs
from jarvis.undo.store import owner_ok
from jarvis.wardrobe.model import View, WardrobeView
from jarvis.wardrobe.ports import WardrobeContext
from jarvis.wardrobe.styling import reserve, texts
from jarvis.wardrobe.styling.look import LookOut, Pick
from jarvis.wardrobe.styling.plans import Plan, StylingDoc
from jarvis.wardrobe.styling.rules import Rules
from jarvis.wardrobe.styling.sealed import Unreadable as PlansUnreadable
from jarvis.wardrobe.styling.service import Answer, Here, Styling
from jarvis.wardrobe.tryon import options as o
from jarvis.wardrobe.tryon.assets import effective, tidy
from jarvis.wardrobe.tryon.http import LookSlot, RefCard, TryonLook
from jarvis.wardrobe.tryon.model import (
    COVERED,
    OPTIONS_MAX,
    PRIVATE_SLOTS,
    REMOVABLE_SLOTS,
    TUCKED_CODES,
    VARIANTS,
    Approx,
    Template,
    rgb_of,
    useful_views,
)
from jarvis.wardrobe.tryon.ports import service_of
from jarvis.wardrobe.tryon.store import Asset, Off, TryonStore, Unreadable

VIEWS: tuple[View, ...] = get_args(View)
GONE_PLAN = "That plan isn't there any more."
GONE_LOOK = "That look isn't there any more: open today's look again."
BAD_DAY = "A look's day is today, tomorrow or a date up to 30 days ahead."
BAD_PIECES = "That look's pieces can't be read."
NOT_HIS = "A piece of that look isn't in your wardrobe any more."
WRONG_SLOT = "A piece of that look isn't one for the place it was put."
TWO = "One piece a slot (or its pair)."
NOT_SET_UP = "Outfits aren't set up on this JARVIS."
PRIVATE_GAP = "A private basic isn't ready: see Helpers, Wardrobe."
UNCHECKED = "Not checked here"  # a covered slot with no piece to check (a card with no plan)
MAX_ENTRIES = 24
_ENTRY = re.compile(r"([a-z_]{2,20}):(wi_[0-9a-f]{12})?")


class NoLook(LookupError):
    """The plan or the look asked for isn't there (any more): a 404 in words."""


class BadDay(ValueError):
    """A day that isn't today, tomorrow or a date within R13's range: a 422 in words."""


class NotPieces(ValueError):
    """A reply card's pieces that can't be his look now: a 422 in words."""


class StylingOff(RuntimeError):
    """R13's styling or store is off, failed or not ready: a 503 in its own words."""


def covered(view: WardrobeView, slot: str, unit: Sequence[str]) -> bool:
    """AVT-14: a private slot, or a slot holding a private piece, is never drawn as itself."""
    if slot in PRIVATE_SLOTS:
        return True
    return any((p := view.pieces.get(i)) is None or p.private for i in unit)


async def photo_views(
    docs: Docs | None, prefix: str, uid: str, photos: Sequence[str]
) -> dict[str, View]:
    """{photo: its view} from the catalog's plain field (only his, only a known view)."""
    out: dict[str, View] = {}
    if docs is None or not owner_ok(uid):
        return out
    for ph in dict.fromkeys(photos):
        raw = await docs.get(f"{prefix}wardrobe_photo/{uid}_{ph}") or {}
        view = raw.get("view")
        if raw.get("owner") == uid and view in VIEWS:
            out[ph] = view
    return out


def _entry(view: WardrobeView, rules: Rules, entry: str) -> tuple[str, str | None]:
    """One `slot:wi_...` (a piece of his, in its own slot) or `slot:` (a slot the card covers:
    a private slot, or one holding a private piece; I0's `styling/tryon_card.py`)."""
    found = _ENTRY.fullmatch(entry)
    if found is None:
        raise NotPieces(BAD_PIECES)
    slot, pid = found.group(1), found.group(2)
    if pid is None:
        if slot not in PRIVATE_SLOTS and slot not in rules.slots:
            raise NotPieces(BAD_PIECES)
        return slot, None
    p = view.pieces.get(pid)
    if p is None or p.merged_into is not None:
        raise NotPieces(NOT_HIS)
    if rules.slot_of(p.type) != slot:
        raise NotPieces(WRONG_SLOT)
    return slot, pid


def picks_of(view: WardrobeView, rules: Rules, raw: str) -> tuple[Pick, ...]:
    """`slot:wi_...,...` (a reply card's slots; a slot it covers comes as `slot:`, no id)."""
    entries = raw.split(",") if raw else []
    if not entries or len(entries) > MAX_ENTRIES:
        raise NotPieces(BAD_PIECES)
    by_slot: dict[str, list[str]] = {}
    for entry in entries:
        slot, pid = _entry(view, rules, entry)
        ids = by_slot.get(slot)
        if ids is not None and (pid is None or not ids):
            raise NotPieces(TWO)  # a covered slot is its slot's only entry
        ids = by_slot.setdefault(slot, [])
        if pid is None:
            continue
        if ids and pid not in reserve.unit_of(view, ids[0]):
            raise NotPieces(TWO)
        ids.append(pid)
    if len(by_slot) > OPTIONS_MAX:
        raise NotPieces(BAD_PIECES)
    return tuple(Pick(slot, tuple(ids)) for slot, ids in by_slot.items())


def _held_by(plan: Plan, pick: Pick) -> Pick:
    """A slot a reply card covers (no id) with the piece its plan holds there, if any."""
    held = plan.slot(pick.slot) if not pick.pieces else None
    return Pick(pick.slot, held.pieces) if held is not None else pick


def _alt(ans: Answer, alt: int) -> LookOut:
    if alt == 0:
        return ans.suggestion.primary
    alts = ans.suggestion.alternatives
    if not 0 < alt <= len(alts):
        raise NoLook(GONE_LOOK)
    return alts[alt - 1]


def _texture(asset: Asset | None, kept: Mapping[View, str]) -> View | None:
    wanted = asset.texture_view if asset is not None else None
    return next((v for v in (wanted, "detail", "front") if v is not None and v in kept), None)


def _rgb(colour: str | None) -> tuple[int, int, int] | None:
    """The palette's value; None when he set no colour (D5's "no colour set": B draws it
    mid-grey, D says so; INTEGRATION-A 8.3, review A-1)."""
    return rgb_of(colour) if colour else None


def _approx(template: Template | None, photo: str | None) -> tuple[Approx, ...]:
    if template is None:
        return ()  # an image card only: nothing is drawn, nothing is estimated
    return ("template", "texture") if photo else ("template", "colour")


def _covered_slot(f: o.Fresh, slot: str, unit: Sequence[str], private: bool) -> LookSlot:
    """Covered: fixed words only, its readiness from the piece (UNCHECKED when there is none to
    check: a reply card's covered slot with no plan, review A-1 F6)."""
    words, ok = o.readiness(f, slot, unit) if unit else (UNCHECKED, False)
    first = f.view.pieces.get(unit[0]) if unit else None
    if not private or first is None:
        return LookSlot(slot=slot, words=COVERED, private=True, readiness=words, eligible=ok)
    said = texts.private_view_words(first) if first.private else o.unit_words(f, unit)
    return LookSlot(slot=slot, piece=first.id, words=said, private=True, readiness=words,
                    eligible=ok)  # fmt: skip


def slot_of(
    f: o.Fresh, pick: Pick, chosen: Mapping[str, Asset], views: Mapping[str, View], private: bool,
    cover: frozenset[str] = frozenset(),
) -> LookSlot:  # fmt: skip
    unit = o.unit_of(f, pick.pieces) if pick.pieces else ()
    if not unit or pick.slot in cover or covered(f.view, pick.slot, unit):
        return _covered_slot(f, pick.slot, unit, private)
    p = f.view.pieces[unit[0]]
    words, ok = o.readiness(f, pick.slot, unit)
    template, card = effective(p, chosen)
    kept = {views[ph]: ph for ph in p.photos if ph in views}
    texture = _texture(chosen.get(p.id), kept)
    photo = kept.get(texture) if texture is not None else None
    return LookSlot(
        slot=pick.slot, piece=p.id, words=o.unit_words(f, unit), template=template,
        variants=VARIANTS.get(template, ()) if template else (), rgb=_rgb(p.colour),
        pattern=p.pattern, texture_view=texture, photo=photo,
        views=tuple(v for v in VIEWS if v in kept),
        refs=tuple(RefCard(view=v, photo=kept[v]) for v in VIEWS if v in kept),
        missing=tuple(v for v in useful_views(p.type) if v not in kept),
        readiness=words, eligible=ok, approximate=_approx(template, photo), card_only=card,
        removable=pick.slot in REMOVABLE_SLOTS, options=o.options(f, pick.slot, unit, chosen),
    )  # fmt: skip


def gaps_of(view: WardrobeView, gaps: Sequence[str], private: bool) -> tuple[str, ...]:
    """R13's gaps; one that names a private piece is said without it (unless he asked)."""
    if private:
        return tuple(gaps)
    hidden = [p.id for p in view.pieces.values() if p.private]
    out: list[str] = []
    for g in gaps:
        line = PRIVATE_GAP if any(pid in g for pid in hidden) else g
        if line not in out:
            out.append(line)
    return tuple(out)


@dataclass(frozen=True)
class Read:
    """One fresh read: R13's styling service, here and now, his plans, the wardrobe view."""

    s: Styling
    here: Here
    doc: StylingDoc
    view: WardrobeView

    def fresh(self, *, day: date, code: str, plan: Plan | None) -> o.Fresh:
        return o.fresh_of(self.view, self.doc, self.s.rules, self.here.zone, day=day, code=code,
                          plan=plan)  # fmt: skip


class Looks:
    """The `tryon_looks` service's looks (C reads `look(uid, plan)` through `ports.TryonLooks`)."""

    def __init__(self, ctx: WardrobeContext, store: TryonStore) -> None:
        self.ctx, self.store = ctx, store

    def styling(self) -> Styling:
        found = getattr(service_of(self.ctx, "refresh"), "styling", None)  # read late, per call
        if not isinstance(found, Styling):
            raise StylingOff(NOT_SET_UP)
        off = found.off()
        if off:
            raise StylingOff(off)
        return found

    async def read(self, uid: str) -> Read:
        s = self.styling()
        view = await s.view(uid)
        if view is None:
            raise StylingOff(texts.NOT_READY_YET)
        try:
            doc = await s.plans.read(uid)
        except PlansUnreadable:
            raise StylingOff(texts.UNREADABLE) from None
        return Read(s, await s.where(uid), doc, view)

    def plan_of(self, r: Read, plan: str | None) -> Plan | None:
        found = r.doc.plan(plan) if plan else None
        if plan and (found is None or found.cancelled):
            raise NoLook(GONE_PLAN)
        return found

    async def look(self, uid: str, plan: str) -> TryonLook:
        return await self.for_plan(uid, plan)

    async def for_plan(self, uid: str, plan: str, alt: int = 0, private: bool = False) -> TryonLook:
        r = await self.read(uid)
        found = r.doc.plan(plan)
        if found is None or found.cancelled:
            raise NoLook(GONE_PLAN)
        ans = await r.s.answer(uid, r.here, r.doc, r.view, found)
        return await self._answer(uid, r, ans, alt, private)

    async def for_day(self, uid: str, day: str, alt: int = 0, private: bool = False) -> TryonLook:
        r = await self.read(uid)
        when = r.s.day_of(day, r.here.today)
        if when is None:
            raise BadDay(BAD_DAY)
        plans = r.s.planned(r.doc, when, r.here, None)  # R13's "what should I wear" (M2)
        if plans:
            ans = await r.s.answer(uid, r.here, r.doc, r.view, plans[0])
        else:
            ans = await r.s.fresh(uid, r.here, r.doc, r.view, day=when, occasion=None, code=None)
        return await self._answer(uid, r, ans, alt, private)

    async def for_pieces(
        self, uid: str, pieces: str, *, plan: str | None = None, day: str | None = None,
        code: str | None = None, private: bool = False,
    ) -> TryonLook:  # fmt: skip
        r = await self.read(uid)
        found = self.plan_of(r, plan)
        when = found.day if found is not None else r.s.day_of(day, r.here.today)
        if when is None:
            raise BadDay(BAD_DAY)
        rules = r.s.rules
        if found is not None:
            chosen = found.code
        elif code is not None and code in rules.codes:
            chosen = code
        else:
            chosen = rules.code_of(None, event=False)
        picks = picks_of(r.view, rules, pieces)
        cover = frozenset(p.slot for p in picks if not p.pieces)  # the card covers: never drawn
        if found is not None:  # ... but its readiness is its plan's piece's, read now (F6)
            picks = tuple(_held_by(found, p) for p in picks)
        f = r.fresh(day=when, code=chosen, plan=found)
        return await self.build(uid, f, picks, (), private, cover=cover)

    async def _answer(self, uid: str, r: Read, ans: Answer, alt: int, private: bool) -> TryonLook:
        look = _alt(ans, alt)
        f = r.fresh(day=ans.day, code=ans.code, plan=ans.plan)
        return await self.build(uid, f, look.picks, look.gaps, private)

    async def assets(self, uid: str, view: WardrobeView) -> dict[str, Asset]:
        try:
            return tidy((await self.store.read(uid)).assets, view)
        except (Off, Unreadable):
            return {}  # his choices can't be read now: the table's defaults

    async def build(
        self, uid: str, f: o.Fresh, picks: Sequence[Pick], gaps: Sequence[str], private: bool,
        cover: frozenset[str] = frozenset(),
    ) -> TryonLook:  # fmt: skip
        chosen = await self.assets(uid, f.view)
        shown = [p.pieces[0] for p in picks if p.pieces and p.slot not in cover
                 and not covered(f.view, p.slot, p.pieces)]  # fmt: skip
        photos = [ph for pid in shown if pid in f.view.pieces for ph in f.view.pieces[pid].photos]
        views = await photo_views(self.ctx.docs, self.ctx.s.firestore_prefix, uid, photos)
        slots = tuple(slot_of(f, p, chosen, views, private, cover) for p in picks)
        return TryonLook(
            plan=f.plan.id if f.plan is not None else None, day=f.day, dress_code=f.code,
            slots=slots, tucked=f.code in TUCKED_CODES, gaps=gaps_of(f.view, gaps, private),
        )  # fmt: skip


__all__ = [
    "BAD_DAY",
    "BAD_PIECES",
    "GONE_LOOK",
    "GONE_PLAN",
    "NOT_HIS",
    "NOT_SET_UP",
    "PRIVATE_GAP",
    "TWO",
    "UNCHECKED",
    "WRONG_SLOT",
    "BadDay",
    "Looks",
    "NoLook",
    "NotPieces",
    "Read",
    "StylingOff",
    "covered",
    "gaps_of",
    "photo_views",
    "picks_of",
    "slot_of",
]
