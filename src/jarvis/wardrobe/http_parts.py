# src/jarvis/wardrobe/http_parts.py
"""R13 H5: Part B's and Part C's request and reply models, and GET /v1/r13's (re-exported by
`jarvis.wardrobe.http`, the contract's one name; import them from there)."""

from __future__ import annotations

from datetime import date, datetime
from typing import Annotated, Literal

from pydantic import Field, StrictBool

from jarvis.wardrobe.http_views import _M, Ready
from jarvis.wardrobe.model import PieceId


# ---- B: laundry ---------------------------------------------------------------------------
class LoadView(_M):
    id: str
    started_at: datetime | None = None
    pieces: tuple[PieceId, ...] = ()
    step: Literal["washing", "drying", "needs_prep", "done"] = "washing"


class BatchView(_M):
    id: str
    shop: str = Field(max_length=40)  # his label for the shop (no number, no address)
    bag: str = Field(default="", max_length=24)
    pieces: tuple[PieceId, ...] = ()
    back: tuple[PieceId, ...] = ()
    due: date | None = None
    overdue: bool = False
    short: bool = False


class LaundryView(_M):
    """GET /v1/laundry."""

    part: Literal["laundry"] = "laundry"
    ready: str
    basket: tuple[PieceId, ...] = ()
    drying: tuple[PieceId, ...] = ()
    prep: tuple[PieceId, ...] = ()
    loads: tuple[LoadView, ...] = ()
    batches: tuple[BatchView, ...] = ()


class ReviewEntry(_M):
    id: str
    kind: Literal["hold", "conflict", "pending_deposit", "stale", "rescan", "place"]
    pieces: tuple[PieceId, ...] = ()
    candidates: tuple[PieceId, ...] = ()
    words: str  # fixed words ("Which of these went into the basket?")
    opened_at: datetime
    reason: Literal[
        "", "unverified", "held", "missing", "restored", "blind", "which", "pending", "refused",
        "stale", "corrected", "sweep", "rescan",
    ] = ""  # the closed set: B's `review.REASONS` ("rescan": a rescan that names none)  # fmt: skip
    count: int = Field(default=0, ge=0, le=20)  # a pending deposit: how many he couldn't show
    answers: tuple[Literal["these", "none", "moved", "dismiss"], ...] = ()  # the resolver's own


class ReviewView(_M):
    """GET /v1/laundry/review."""

    part: Literal["laundry"] = "laundry"
    ready: str
    entries: tuple[ReviewEntry, ...] = Field(default=(), max_length=100)
    open: int = Field(ge=0)


# ---- C: outfits ---------------------------------------------------------------------------
class SlotPick(_M):
    slot: str
    piece: PieceId | None = None
    words: str = ""  # "a navy shirt"; a private basic only in his view
    locked: bool = False


class Look(_M):
    pieces: tuple[SlotPick, ...]
    reasons: tuple[str, ...] = ()
    compromises: tuple[str, ...] = ()
    gaps: tuple[str, ...] = ()  # "no ready formal shoes" + its next action


class PlanView(_M):
    id: str
    day: date
    event: str | None = None  # a fingerprint, never a title
    starts: datetime | None = None
    dress_code: str
    tentative: bool = True
    look: Look | None = None
    needs: tuple[str, ...] = ()  # "needs a new shirt"
    manual: bool = True
    cancelled: bool = False


class OutfitsView(_M):
    """GET /v1/outfits."""

    part: Literal["styling"] = "styling"
    ready: str
    today: tuple[PlanView, ...] = ()
    tomorrow: tuple[PlanView, ...] = ()
    weather: str = ""  # "Weather for your home area: rain likely from 15:00" / "Weather unknown"


class CalendarChoice(_M):
    id_ref: str = Field(min_length=8, max_length=64)  # a reference to one id from HIS list
    title: str = Field(max_length=200)  # shown live, never stored
    primary: bool = False
    chosen: bool = False  # this is the calendar he picked


class Calendars(_M):
    """GET /v1/outfits/calendars (a governed read, the Calendar row's Allow only)."""

    calendars: tuple[CalendarChoice, ...] = ()
    why: str = ""  # "Your Calendar permission is Ask first: allow it, or plan by hand."


class OutfitSettings(_M):
    """PUT /v1/outfits/settings."""

    calendar: str | None = Field(default=None, max_length=64)  # an `id_ref`, or None: off
    fields: tuple[Literal["title", "location"], ...] = ("title",)
    plan_alerts: bool = True
    auto_swap: bool = False


class WardrobeSettingsIn(_M):
    """PUT /v1/wardrobe/settings: his own wardrobe settings (D7, D10), what he sent changes and
    what he did not send stays. The calendar, its fields, the alert and auto-swap are Part C's
    (`PUT /v1/outfits/settings`). Owner-only: never a tool the model can call."""

    ai_tagging: StrictBool | None = None
    show_private: StrictBool | None = None
    custom_types: tuple[Annotated[str, Field(max_length=24)], ...] | None = Field(
        default=None, max_length=30
    )


class R13Status(_M):
    """GET /v1/r13: each part's ready word."""

    version: str
    parts: tuple[Ready, ...]


__all__ = [
    "BatchView",
    "CalendarChoice",
    "Calendars",
    "LaundryView",
    "LoadView",
    "Look",
    "OutfitSettings",
    "OutfitsView",
    "PlanView",
    "R13Status",
    "ReviewEntry",
    "ReviewView",
    "SlotPick",
    "WardrobeSettingsIn",
]
