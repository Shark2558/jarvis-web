# src/jarvis/wardrobe/tryon/assets.py
"""R13.1 D5 (AVT-05's association): each piece's figure choice, saved against its id in
`tryon/{uid}.assets` (never in page memory). Pure: documents and views in, documents out.

- `effective(piece, chosen)`: (template, card only) for the figure: his choice, else the table's
  default (`model.template_of`); a type with no template is an image card only.
- `choose(doc, view, piece, choice)`: another template of the same slot (`model.templates_for`),
  "image card only", a texture view, or the default again (the entry goes). A private piece is
  never drawn; a merged-away or purged piece isn't his to choose for.
- `tidy(chosen, view)`: a merged-away or purged piece's entry is dropped (on every read; the next
  write keeps the tidied list).
"""

from __future__ import annotations

from collections.abc import Mapping

from jarvis.wardrobe.model import Piece, WardrobeView
from jarvis.wardrobe.tryon.http import AssetChoice
from jarvis.wardrobe.tryon.model import TEMPLATE_SLOT, Template, template_of, templates_for
from jarvis.wardrobe.tryon.store import Asset, TryonDoc

NOT_IN = "That piece isn't in your wardrobe."
NOT_THIS = "That choice is for another piece."
PRIVATE = "A private piece is never drawn: the figure wears a plain base layer instead."
BOTH = "Pick a shape or the photo card only, not both."
CARD_ONLY = "This kind of piece is shown as its photo card only."
WRONG = "That shape isn't for this kind of piece: pick one of the same kind, or the photo card."


class NotIn(LookupError):
    """The piece isn't his (any more): a 404 in words."""


class Refused(ValueError):
    """A choice that doesn't fit the piece: a 422 in words."""


def effective(p: Piece, chosen: Mapping[str, Asset]) -> tuple[Template | None, bool]:
    """(the template the figure draws, image card only)."""
    default = template_of(p.type)
    a = chosen.get(p.id)
    if a is None:
        return default, default is None
    if a.card_only:
        return None, True
    t = a.template or default
    return t, t is None


def tidy(chosen: Mapping[str, Asset], view: WardrobeView) -> dict[str, Asset]:
    def live(pid: str) -> bool:
        p = view.pieces.get(pid)
        return p is not None and p.merged_into is None

    return {pid: a for pid, a in chosen.items() if live(pid)}


def _check(p: Piece | None, pid: str, body: AssetChoice) -> None:
    if p is None or p.merged_into is not None:
        raise NotIn(NOT_IN)
    if body.piece != pid:
        raise Refused(NOT_THIS)
    if p.private:
        raise Refused(PRIVATE)
    if body.card_only and body.template is not None:
        raise Refused(BOTH)
    if body.template is None:
        return
    default = template_of(p.type)
    if default is None:
        raise Refused(CARD_ONLY)
    if body.template not in templates_for(TEMPLATE_SLOT[default]):
        raise Refused(WRONG)


def choose(
    doc: TryonDoc, view: WardrobeView, pid: str, body: AssetChoice
) -> tuple[TryonDoc, AssetChoice]:
    """The document with his choice for `pid`, and the choice as saved."""
    _check(view.pieces.get(pid), pid, body)
    asset = Asset(template=body.template, texture_view=body.texture_view, card_only=body.card_only)
    kept = tidy(doc.assets, view)
    if asset == Asset():
        kept.pop(pid, None)  # the table's default again: nothing to keep
    else:
        kept[pid] = asset
    return doc.model_copy(update={"assets": kept}), choice_of(pid, asset)


def choice_of(pid: str, asset: Asset) -> AssetChoice:
    return AssetChoice(
        piece=pid, template=asset.template, texture_view=asset.texture_view,
        card_only=asset.card_only,
    )  # fmt: skip


__all__ = [
    "BOTH",
    "CARD_ONLY",
    "NOT_IN",
    "NOT_THIS",
    "PRIVATE",
    "WRONG",
    "NotIn",
    "Refused",
    "choice_of",
    "choose",
    "effective",
    "tidy",
]
