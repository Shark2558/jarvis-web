# src/jarvis/wardrobe/tryon/http_seeme.py
"""R13.1 contract: Part C's request and reply models for "See it on me" (re-exported by
`jarvis.wardrobe.tryon.http`, the contract's one name; import from there).

D22 (the owner, 17 Nov 2026): See it on me pictures him in a garment he is thinking of BUYING.
He gives its photo (a shop photo, a website picture or a screenshot, uploaded or shared in; JARVIS
never fetches an address), picks its type and colour from the fixed lists, and pairs it with at
most two non-private pieces he owns. The garment is never a wardrobe piece: its id is `tg_`, its
words say "not in your wardrobe", and nothing here can add it to the catalog."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any, Literal

from pydantic import AfterValidator, Field, StrictBool, model_validator

from jarvis.wardrobe.model import Colour, PhotoId, PieceId
from jarvis.wardrobe.tryon.http_figure import _M, Inr, PictureIdT, RequestIdT
from jarvis.wardrobe.tryon.model import (
    GARMENT_ID,
    GARMENT_MAX,
    GENERATED,
    LISTED_MAX,
    NEW_TYPES,
    PAIR_MAX,
    TEMPLATE_OF,
    TEMPLATE_SLOT,
)


def _new_type(v: str) -> str:
    if v not in NEW_TYPES:
        raise ValueError("a new garment is a top, a bottom or an outer layer")
    return v


GarmentIdT = Annotated[str, Field(pattern=GARMENT_ID)]
NewType = Annotated[str, AfterValidator(_new_type)]


class ProviderView(_M):
    provider: str
    model: str
    model_words: str
    location: str
    location_words: str
    max_garments: int
    retires_on: str = ""
    ends_soon: bool = False  # within 30 days of its end date (D18)


class PhotoView(_M):
    kept: bool = False
    at: datetime | None = None
    bytes: int = 0


class ConsentView(_M):
    given: bool = False
    at: datetime | None = None
    current: bool = False  # given for this template, provider, model and location (D11)
    version: str = ""  # the fixed template's version (POST /v1/seeme/consent sends it back)
    words: tuple[str, ...] = ()  # the fixed lines the card shows before he types YES


class MonthView(_M):
    month: str  # "2026-11", his IST month
    spent_inr: Inr = 0.0
    held_inr: Inr = 0.0
    cap_inr: int = Field(ge=0, le=2000)
    pictures: int = 0
    blocked: int = 0


class SentPiece(_M):
    piece: PieceId
    words: str


class NotSent(_M):
    piece: PieceId | None = None
    slot: str = ""
    words: str
    why: Literal["private_piece", "no_photo", "not_a_garment", "unticked"]
    photo: PhotoId | None = None


class GarmentIn(_M):
    """POST /v1/seeme/garments?type=&colour= (console only; the body is the door's JPEG)."""

    type: NewType
    colour: Colour


class NewGarment(_M):
    """The new garment as a picture or an estimate names it."""

    id: GarmentIdT
    words: str  # `model.new_garment_words`: "a new navy shirt, not in your wardrobe"


class GarmentView(_M):
    """One new garment's photo: kept 30 days, or while a kept picture shows it."""

    id: GarmentIdT
    type: NewType
    colour: Colour
    words: str
    slot: str = ""  # top, bottom or outer: from its type (filled in when not sent)
    at: datetime
    until: datetime | None = None  # None while a kept picture shows it
    kept: bool = False
    bytes: int = Field(default=0, ge=0)

    @model_validator(mode="before")
    @classmethod
    def _slot(cls, data: Any) -> Any:
        kind = data.get("type") if isinstance(data, dict) else None
        if isinstance(kind, str) and kind in NEW_TYPES:
            want = TEMPLATE_SLOT[TEMPLATE_OF[kind]]
            if data.get("slot", "") not in ("", want):
                raise ValueError("the slot is the type's")
            return {**data, "slot": want}
        return data


class GarmentList(_M):
    """GET /v1/seeme/garments: words and sizes only, never the bytes."""

    garments: tuple[GarmentView, ...] = Field(default=(), max_length=GARMENT_MAX)


class Pairing(_M):
    """GET /v1/seeme/pair?garment=: his own pieces R13's rules pick to go with it (none private)."""

    garment: GarmentIdT
    pieces: tuple[SentPiece, ...] = Field(default=(), max_length=PAIR_MAX)
    not_sent: tuple[NotSent, ...] = ()
    words: str = ""  # "With your charcoal trousers." or why nothing of his goes with it


class PictureView(_M):
    id: PictureIdT
    made_at: datetime
    garment: NewGarment  # D22: the new garment in the picture, never one of his
    until: datetime | None = None  # None while kept
    kept: bool = False
    inr: Inr = 0.0
    sent: tuple[SentPiece, ...] = ()  # his own pieces sent with it
    not_sent: tuple[NotSent, ...] = ()
    mime: Literal["image/jpeg", "image/png"] = "image/jpeg"
    label: str = GENERATED
    credentials: str = ""


class SeeMeView(_M):
    """GET /v1/seeme."""

    part: Literal["seeme"] = "seeme"
    ready: str
    on: bool = False
    why: str = ""  # why it is off, in words ("Pictures are not set up on this server.")
    provider: ProviderView | None = None
    photo: PhotoView = PhotoView()
    consent: ConsentView = ConsentView()
    month: MonthView | None = None
    typical_inr: Inr = 0.0
    hold_inr: Inr = 0.0
    tax_pct: int = Field(default=18, ge=0, le=28)
    photo_max_kb: int = Field(default=700, ge=100, le=740)
    notice: str = ""  # "Google may retire this image model on 28 May 2027"
    pictures: tuple[PictureView, ...] = Field(default=(), max_length=LISTED_MAX)


class ConsentIn(_M):
    """POST /v1/seeme/consent: 422 unless `typed` is exactly YES and the template is current."""

    typed: str = Field(max_length=20)
    template_version: str = Field(max_length=20)


class Estimate(_M):
    """GET /v1/seeme/estimate?garment=&pieces=."""

    typical_inr: Inr
    hold_inr: Inr
    tax_pct: int = Field(ge=0, le=28)
    sent: tuple[SentPiece, ...] = ()
    not_sent: tuple[NotSent, ...] = ()
    cap_left_inr: Inr = 0.0
    limit_room_inr: Inr | None = None  # None: no monthly limit set
    garment: NewGarment | None = None
    words: str = ""  # "Make 1 picture of you in a new navy shirt ...? About ₹9 with GST. ..."


class PictureIn(_M):
    """POST /v1/seeme/pictures (console only; 6 a minute): the new garment, at most 2 of his."""

    garment: GarmentIdT
    pieces: tuple[PieceId, ...] = Field(default=(), max_length=PAIR_MAX)
    confirm_cost: StrictBool = False
    inr_shown: Inr
    request_id: RequestIdT


class KeepIn(_M):
    keep: StrictBool


class SeeMeSettingsIn(_M):
    """PUT /v1/seeme/settings: what he sent changes; a higher cap needs `confirm_cost`."""

    on: StrictBool | None = None
    cap_inr: int | None = Field(default=None, ge=0, le=2000)
    keep_days: int | None = Field(default=None, ge=1, le=30)
    confirm_cost: StrictBool = False


SEEME_ERRORS = (
    "cap_reached", "budget_reached", "consent_needed", "price_changed", "busy", "private_piece",
    "no_photo", "not_a_garment", "no_garment", "too_many", "blocked",
    "not_configured", "retired", "no_ai", "provider_unavailable", "console_only", "confirm_cost",
    "not_yes", "too_large", "not_jpeg",
)  # fmt: skip
