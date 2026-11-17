# src/jarvis/wardrobe/tryon/http_figure.py
"""R13.1 contract: the shared base (`_M`, `Refusal`, the id types) and Part A's request and reply
models (re-exported by `jarvis.wardrobe.tryon.http`, the contract's one name; import from there)."""

from __future__ import annotations

from datetime import date, datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

from jarvis.wardrobe.model import PhotoId, PieceId, View
from jarvis.wardrobe.tryon.model import (
    OPTIONS_MAX,
    PICTURE_ID,
    REQUEST_ID,
    SAVED_ID,
    SAVED_MAX,
    Approx,
    Layers,
    Measure,
    Template,
)

PictureIdT = Annotated[str, Field(pattern=PICTURE_ID)]
RequestIdT = Annotated[str, Field(pattern=REQUEST_ID)]
SavedIdT = Annotated[str, Field(pattern=SAVED_ID)]
Inr = Annotated[float, Field(ge=0, le=100_000)]
Rgb = tuple[int, int, int]


class _M(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class Refusal(_M):
    """Every refusal of an R13.1 route (L6)."""

    error: str = Field(pattern=r"^[a-z_]{2,32}$")
    detail: str = Field(max_length=300)


# ---- A · the figure's data ------------------------------------------------------------------
class BodyView(_M):
    height: int
    shoulders: int
    chest: int
    waist: int
    hips: int
    inseam: int
    typed: tuple[Measure, ...] = ()  # the rest are shown "estimated"
    at: datetime
    weights: dict[str, float] = Field(default_factory=dict)  # `model.morph_weights`: the engine's


class BodyVersions(_M):
    current: BodyView | None = None
    draft: BodyView | None = None
    earlier: tuple[BodyView, ...] = Field(default=(), max_length=5)


class RangeView(_M):
    measure: Measure
    low: int
    high: int
    words: str  # "The figure can be 150 to 195 cm tall"


class AssetChoice(_M):
    """His template choice for one piece (AVT-05: saved against its id)."""

    piece: PieceId
    template: Template | None = None
    texture_view: View | None = None
    card_only: bool = False


class SavedRef(_M):
    id: SavedIdT
    at: datetime
    draft: bool = False  # a piece in it is no longer eligible (re-checked on reading)


class TryonView(_M):
    """GET /v1/tryon."""

    part: Literal["tryon"] = "tryon"
    ready: str
    release: str = "m1"  # the mannequin files' folder (`/static/vendor/mannequin/{release}/`)
    files: tuple[str, ...] = ()  # the file names the engine loads
    body: BodyVersions = BodyVersions()
    ranges: tuple[RangeView, ...] = ()
    assets: tuple[AssetChoice, ...] = ()
    saved: tuple[SavedRef, ...] = Field(default=(), max_length=SAVED_MAX)
    words: str = ""  # "No figure yet: type your measurements." / "Estimated from ..."


class BodyIn(_M):
    """PUT /v1/tryon/body: the measurements he typed (a draft); each is range-checked in words by
    A (`model.range_words`), so the bounds here only stop nonsense."""

    height: int | None = Field(default=None, ge=0, le=300)
    shoulders: int | None = Field(default=None, ge=0, le=300)
    chest: int | None = Field(default=None, ge=0, le=300)
    waist: int | None = Field(default=None, ge=0, le=300)
    hips: int | None = Field(default=None, ge=0, le=300)
    inseam: int | None = Field(default=None, ge=0, le=300)


class LookOption(_M):
    piece: PieceId
    words: str  # fixed words ("a navy blazer"); his label only in his own panel
    readiness: str  # "Ready", "Draft: in the laundry", "Draft: reserved for your 18:00 event"
    eligible: bool
    photo: PhotoId | None = None
    template: Template | None = None


class RefCard(_M):
    """One kept reference crop of a piece and its view (AVT-04's front and back cards)."""

    view: View
    photo: PhotoId


class LookSlot(_M):
    """One slot of a look for the figure. A private slot (`base`, `underwear`) is covered only:
    no template, colour, pattern, photo or option; its piece and words only with `?private=1`."""

    slot: str
    piece: PieceId | None = None
    words: str = ""
    private: bool = False
    template: Template | None = None
    variants: tuple[str, ...] = ()
    rgb: Rgb | None = None
    pattern: str | None = None
    texture_view: View | None = None
    photo: PhotoId | None = None  # the crop the texture comes from (detail, else front)
    views: tuple[View, ...] = ()  # the views kept
    refs: tuple[RefCard, ...] = Field(default=(), max_length=3)  # each kept crop, front first
    missing: tuple[View, ...] = ()  # a useful view not kept yet (AVT-04)
    readiness: str = ""
    eligible: bool = False
    approximate: tuple[Approx, ...] = ()
    card_only: bool = False
    removable: bool = False
    options: tuple[LookOption, ...] = Field(default=(), max_length=OPTIONS_MAX)


class TryonLook(_M):
    """GET /v1/tryon/look?plan= or ?day=today|tomorrow&alt=0|1|2 (&private=1)."""

    plan: str | None = None
    day: date
    dress_code: str = ""
    slots: tuple[LookSlot, ...] = ()
    tucked: bool = False  # the default from the dress code (D6)
    open: bool = True  # a jacket's default
    layers: Layers = "all"
    gaps: tuple[str, ...] = ()


class ConfirmSlot(_M):
    slot: str = Field(max_length=20)
    piece: PieceId


class ConfirmIn(_M):
    """POST /v1/tryon/confirm: 409 with the draft's words, else ONE `outfit_plan` lock of every
    slot through `run_panel_tool` (the reply is R13's `ToolReply`: at most one card)."""

    plan: str = Field(max_length=40)
    slots: tuple[ConfirmSlot, ...] = Field(min_length=1, max_length=OPTIONS_MAX)
    session_id: str | None = Field(default=None, max_length=64)


class SavedLook(_M):
    plan: str | None = Field(default=None, max_length=40)
    slots: tuple[ConfirmSlot, ...] = Field(min_length=1, max_length=OPTIONS_MAX)
    tucked: bool = False
    open: bool = True
    layers: Layers = "all"


class SavedIn(_M):
    """POST /v1/tryon/saved: one look, or two compared (never a picture)."""

    looks: tuple[SavedLook, ...] = Field(min_length=1, max_length=2)


class SavedLookView(_M):
    look: SavedLook
    readiness: tuple[str, ...] = ()  # one word a slot, in its order
    draft: bool = False


class SavedView(_M):
    id: SavedIdT
    at: datetime
    looks: tuple[SavedLookView, ...]
    draft: bool = False


class SavedList(_M):
    saved: tuple[SavedView, ...] = Field(default=(), max_length=SAVED_MAX)
