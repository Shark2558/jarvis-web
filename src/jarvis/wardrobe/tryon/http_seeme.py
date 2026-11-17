# src/jarvis/wardrobe/tryon/http_seeme.py
"""R13.1 contract: Part C's request and reply models for "See it on me" (re-exported by
`jarvis.wardrobe.tryon.http`, the contract's one name; import from there)."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import Field, StrictBool

from jarvis.wardrobe.model import PhotoId, PieceId
from jarvis.wardrobe.tryon.http_figure import _M, Inr, PictureIdT, RequestIdT
from jarvis.wardrobe.tryon.model import GENERATED, LISTED_MAX


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


class PictureView(_M):
    id: PictureIdT
    made_at: datetime
    until: datetime | None = None  # None while kept
    kept: bool = False
    inr: Inr = 0.0
    sent: tuple[SentPiece, ...] = ()
    not_sent: tuple[NotSent, ...] = ()
    plan: str | None = None
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
    """GET /v1/seeme/estimate?plan=&pieces=."""

    typical_inr: Inr
    hold_inr: Inr
    tax_pct: int = Field(ge=0, le=28)
    sent: tuple[SentPiece, ...] = ()
    not_sent: tuple[NotSent, ...] = ()
    cap_left_inr: Inr = 0.0
    limit_room_inr: Inr | None = None  # None: no monthly limit set
    words: str = ""  # "Make 1 picture of you in ...? About ₹9 with GST. ₹54.3 of ₹300 used ..."


class PictureIn(_M):
    """POST /v1/seeme/pictures (console only; 6 a minute)."""

    pieces: tuple[PieceId, ...] = Field(min_length=1, max_length=3)
    plan: str | None = Field(default=None, max_length=40)
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
    "no_photo", "not_a_garment", "blocked", "not_configured", "retired", "no_ai",
    "provider_unavailable", "console_only", "confirm_cost", "not_yes", "too_large", "not_jpeg",
)  # fmt: skip
