# src/jarvis/wardrobe/seeme/pair.py
"""R13.1 Part C: which of HIS pieces may go in a picture, and the pairing with a garment he is
thinking of buying (docs/plans/r13-1-try-on.md D13.1, D22.5).

- `split(ctx, uid, view, pieces, garment_slot=)`: checks each piece he asked for against a FRESH
  view (never the console's word): only a top, a bottom or an outer layer (`model.GARMENTS`), one a
  slot and never in the new garment's slot, never private (`private_piece`, and never named: no
  id, no words but "Base layer (covered)"), with a `front` crop (`no_photo` without one; the view
  is the plain `view` field of R13's `wardrobe_photo` document, the crop opened later through
  `ports.photo_vault(ctx).get`). The rest are `not_a_garment`, with their thumbnail for the card.
- `Pairer.pair(uid, garment)`: R13's engine (`styling.engine.suggest`, read only) on a COPY of his
  view with the garment as a transient piece (its type and colour; an id no stored piece has;
  never written, never returned), locked into its slot, on today's dress code and weather as
  `outfit_suggest` would (a plan of today's first, else the default code). At most `PAIR_MAX` of
  his sendable pieces from the primary look, with fixed words ("With your charcoal trousers.");
  the look's other pieces are listed as not in the picture; nothing of his: the words why.
"""

from __future__ import annotations

import secrets
from collections.abc import Sequence
from dataclasses import dataclass, replace
from typing import Any

from jarvis.logging import get_logger
from jarvis.wardrobe.model import Piece, WardrobeView
from jarvis.wardrobe.ports import WardrobeContext
from jarvis.wardrobe.seeme import texts
from jarvis.wardrobe.styling.engine import suggest
from jarvis.wardrobe.styling.texts import piece_words
from jarvis.wardrobe.tryon.http import GarmentView, NotSent, Pairing, SentPiece
from jarvis.wardrobe.tryon.model import (
    COVERED,
    GARMENTS,
    PAIR_MAX,
    PRIVATE_SLOTS,
    TEMPLATE_SLOT,
    category_of,
    template_of,
)
from jarvis.wardrobe.tryon.ports import service_of

log = get_logger(__name__)
PHOTO_COLLECTION = "wardrobe_photo"  # R13's catalog: {owner, piece, view, ...} plain fields
NOT_HIS_WORDS = "a piece not in your wardrobe"


@dataclass(frozen=True)
class Mine:
    """One of his pieces that may be sent: its id, slot, fixed words and front crop's id."""

    piece: str
    slot: str
    words: str
    photo: str

    def sent(self) -> SentPiece:
        return SentPiece(piece=self.piece, words=self.words)


def slot_of_type(kind: str) -> str | None:
    tpl = template_of(kind)
    return TEMPLATE_SLOT[tpl] if tpl is not None and tpl in GARMENTS else None


def mine_words(p: Piece) -> str:
    """ "charcoal trousers", "navy shirt": R13's fixed words without the article."""
    words = piece_words(p)
    for lead in ("a ", "an "):
        if words.startswith(lead):
            return words[len(lead) :]
    return words


async def front_of(ctx: WardrobeContext, uid: str, p: Piece) -> str | None:
    """The id of the piece's `front` crop (R13's own record of its views), or None."""
    if ctx.docs is None:
        return None
    for photo in p.photos:
        doc = await ctx.docs.get(f"{ctx.s.firestore_prefix}{PHOTO_COLLECTION}/{uid}_{photo}")
        if doc and doc.get("owner") == uid and doc.get("piece") == p.id:
            if doc.get("view") == "front":
                return photo
    return None


def _no(p: Piece | None, pid: str, why: Any, slot: str = "") -> NotSent:
    if p is None:
        return NotSent(piece=pid, slot=slot, words=NOT_HIS_WORDS, why=why)
    if p.private:
        return NotSent(piece=None, slot=slot, words=COVERED, why="private_piece")
    photo = p.photos[0] if p.photos else None
    return NotSent(piece=p.id, slot=slot, words=mine_words(p), why=why, photo=photo)


async def check(
    ctx: WardrobeContext, uid: str, view: WardrobeView, pid: str, *, taken: set[str]
) -> Mine | NotSent:
    """One piece: Mine when it may be sent; NotSent (and why) when not. `taken`: slots in use."""
    p = view.piece(pid)
    if p is None or p.merged_into is not None or p.state == "archived":
        return _no(None, pid, "not_a_garment")
    if p.private:
        return _no(p, pid, "private_piece")
    slot = slot_of_type(p.type)
    if slot is None or slot in taken:
        return _no(p, pid, "not_a_garment", slot or "")
    front = await front_of(ctx, uid, p)
    if front is None:
        return _no(p, pid, "no_photo", slot)
    return Mine(piece=p.id, slot=slot, words=mine_words(p), photo=front)


async def split(
    ctx: WardrobeContext, uid: str, view: WardrobeView, pieces: Sequence[str], *, garment_slot: str
) -> tuple[list[Mine], list[NotSent]]:
    sent: list[Mine] = []
    not_sent: list[NotSent] = []
    taken = {garment_slot}
    for pid in dict.fromkeys(pieces):
        got = await check(ctx, uid, view, pid, taken=taken)
        if isinstance(got, Mine):
            sent.append(got)
            taken.add(got.slot)
        else:
            not_sent.append(got)
    return sent, not_sent


def _ghost(view: WardrobeView, g: GarmentView) -> Piece:
    """The garment as a transient piece: an id no stored piece has; never written or returned."""
    tid = "wi_" + secrets.token_hex(6)
    while tid in view.pieces:
        tid = "wi_" + secrets.token_hex(6)
    return Piece.model_validate(
        {"i": tid, "c": category_of(g.type) or "tops", "t": g.type, "co": g.colour}
    )


class Pairer:
    def __init__(self, ctx: WardrobeContext) -> None:
        self.ctx = ctx

    async def look(
        self, uid: str, g: GarmentView
    ) -> tuple[WardrobeView, list[tuple[str, str]]] | None:
        """(his fresh view, the primary look's (slot, piece) of HIS pieces), or None."""
        styling = getattr(service_of(self.ctx, "refresh"), "styling", None)
        store = self.ctx.store()
        if styling is None or store is None:
            return None
        try:
            view = await store.view(uid)
            here = await styling.where(uid)
            doc = await styling.plans.read(uid)
            planned = styling.planned(doc, here.today, here, None)
            code = planned[0].code if planned else styling.rules.code_of(None, event=False)
            occ = planned[0].occasion if planned else None
            ask, _ = await styling.ask(uid, here, doc, day=here.today, code=code, occasion=occ)
        except Exception as exc:  # noqa: BLE001 - no suggestion: he picks, or none
            log.warning("see it on me: no pairing", extra={"error": type(exc).__name__})
            return None
        ghost = _ghost(view, g)
        copy = view.model_copy(update={"pieces": {**view.pieces, ghost.id: ghost}})
        found = suggest(copy, replace(ask, locked={g.slot: (ghost.id,)}, keep={}), styling.rules)
        picks = [(p.slot, i) for p in found.primary.picks for i in p.pieces if i != ghost.id]
        return view, picks

    async def pair(self, uid: str, g: GarmentView) -> Pairing:
        found = await self.look(uid, g)
        if found is None:
            return Pairing(garment=g.id, words=texts.PAIR_OFF)
        view, picks = found
        sent, not_sent = await self.from_look(uid, view, picks, g.slot)
        words = texts.PAIR_WITH.format(words=" and ".join(m.words for m in sent))
        return Pairing(
            garment=g.id, pieces=tuple(m.sent() for m in sent), not_sent=tuple(not_sent),
            words=words if sent else texts.PAIR_NONE,
        )  # fmt: skip

    async def from_look(
        self, uid: str, view: WardrobeView, picks: list[tuple[str, str]], garment_slot: str
    ) -> tuple[list[Mine], list[NotSent]]:
        sent: list[Mine] = []
        not_sent: list[NotSent] = []
        covered: set[str] = set()
        taken = {garment_slot}
        for slot, pid in picks:
            p = view.pieces[pid]
            if p.private or slot in PRIVATE_SLOTS:
                if slot not in covered:  # one covered line a slot; never its id or words
                    not_sent.append(NotSent(slot=slot, words=COVERED, why="private_piece"))
                    covered.add(slot)
                continue
            got = await check(self.ctx, uid, view, pid, taken=taken)
            if isinstance(got, Mine) and len(sent) < PAIR_MAX:
                sent.append(got)
                taken.add(got.slot)
            elif isinstance(got, Mine):
                not_sent.append(_no(p, pid, "unticked", got.slot))
            else:
                not_sent.append(got.model_copy(update={"slot": slot}))
        return sent, not_sent


__all__ = ["Mine", "Pairer", "check", "front_of", "mine_words", "slot_of_type", "split"]
