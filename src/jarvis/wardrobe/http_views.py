# src/jarvis/wardrobe/http_views.py
"""R13 H5: the shared views and Part A's request and reply models (re-exported by
`jarvis.wardrobe.http`, the contract's one name; import them from there)."""

from __future__ import annotations

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from jarvis.wardrobe.model import (
    CATEGORIES,
    Category,
    ClientId,
    EventId,
    How,
    LabelCode,
    PhotoId,
    PieceId,
    PlaceId,
    Source,
    View,
)
from jarvis.wardrobe.ports import Mark
from jarvis.wardrobe.states import EventKind, State

SCAN_MAX = 50  # events in one POST /v1/wardrobe/scan
PAGE_MAX = 200  # pieces in one GET /v1/wardrobe page
LABELS_A_PAGE = 24


class _M(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


# ---- shared views ---------------------------------------------------------------------------
class Ready(_M):
    part: str
    ready: str


class PieceView(_M):
    """The panel's view of a piece (his own console: everything; a private piece only when he
    has tapped "Show private basics", else counted in `WardrobeView.private_hidden`)."""

    id: PieceId
    category: Category
    type: str
    label: str = Field(max_length=60)
    colour: str | None = None
    second: str | None = None
    pattern: str | None = None
    locked: tuple[str, ...] = ()
    features: dict[str, str] = Field(default_factory=dict)
    size: tuple[str, bool] | None = None  # (value, verified)
    brand: tuple[str, bool] | None = None
    fabric: tuple[tuple[str, bool], ...] = ()
    care: tuple[tuple[str, bool], ...] = ()
    formality: int | None = Field(default=None, ge=1, le=5)
    occasions: tuple[str, ...] = ()
    weather: tuple[str, ...] = ()
    mess_ok: bool = False
    delicate: bool = False
    private: bool = False
    state: State
    state_words: str
    eligible: bool
    place: PlaceId | None = None
    place_words: str = ""  # "Drawer 2", or "Drawer 2 (last known)"
    place_at: datetime | None = None
    expected_back: date | None = None
    hold: str | None = None
    wears: int = 0
    last_worn: datetime | None = None
    label_code: LabelCode | None = None
    photos: tuple[PhotoId, ...] = ()
    pair: str | None = None
    sets: tuple[str, ...] = ()


class CountRow(_M):
    category: Category
    owned: int = Field(ge=0)
    ready: int = Field(ge=0)


class Counts(_M):
    owned: int = Field(ge=0)
    ready: int = Field(ge=0)
    review: int = Field(ge=0)  # pending checks, apart (INV-14)
    pairs_complete: int = Field(ge=0)
    pairs: int = Field(ge=0)
    sets_complete: int = Field(ge=0)
    sets: int = Field(ge=0)
    by_category: tuple[CountRow, ...] = ()
    places_without_baseline: int = Field(default=0, ge=0)  # "scope covered" (INV-02, INV-14)


class PairView(_M):
    id: str
    pieces: tuple[PieceId, PieceId]
    wearable: bool
    missing: tuple[PieceId, ...] = ()  # the half that is out (LND-13)


class SetView(_M):
    id: str
    label: str = ""
    parts: tuple[tuple[PieceId, bool], ...]  # (piece, can be worn alone)
    wearable: bool
    alone: tuple[PieceId, ...] = ()


class PlaceView(_M):
    id: PlaceId
    label: str
    kind: Literal["storage", "intake", "basket", "return", "travel", "out"]
    baseline_at: datetime | None = None


class LabelView(_M):
    code: LabelCode
    number: int = Field(ge=1, le=9999)
    piece: PieceId | None = None


class SettingsView(_M):
    calendar_chosen: bool = False  # the id itself stays sealed on the server
    fields: tuple[Literal["title", "location"], ...] = ("title",)
    lead_h: int = Field(default=12, ge=0, le=48)
    plan_alerts: bool = True
    ai_tagging: bool = False
    auto_swap: bool = False
    show_private: bool = False
    tag_month_inr: float = Field(default=0.0, ge=0.0)
    tag_cap_inr: int = Field(default=30, ge=0)
    custom_types: tuple[str, ...] = ()


class WardrobeView(_M):
    """GET /v1/wardrobe."""

    part: Literal["catalog"] = "catalog"
    ready: str
    rev: int = Field(ge=0)
    pieces: tuple[PieceView, ...] = Field(max_length=PAGE_MAX)
    next: str | None = None  # the next page's cursor
    private_hidden: int = Field(default=0, ge=0)
    counts: Counts
    pairs: tuple[PairView, ...] = ()
    sets: tuple[SetView, ...] = ()
    places: tuple[PlaceView, ...] = ()
    labels: tuple[LabelView, ...] = ()
    settings: SettingsView = SettingsView()
    categories: tuple[str, ...] = CATEGORIES


class EventView(_M):
    id: EventId
    kind: EventKind
    at: datetime
    source: Source
    verified: bool
    mark: Mark
    to: State | None = None
    place_words: str = ""
    note: str = ""


class PieceDetail(_M):
    """GET /v1/wardrobe/pieces/{id}: one piece and its history summary (LND-15)."""

    piece: PieceView
    history: tuple[EventView, ...] = Field(default=(), max_length=50)
    step: str = ""  # the current step in words ("Drying since 14:05")


# ---- POST /v1/wardrobe/scan ---------------------------------------------------------------
class EventIn(_M):
    """One event from the phone or a tap. Time (D4.1): a device sends `at` (capture) and `sent`
    (its clock at send); a time he states is `stated_at` (<= 30 days back) or `day` (12:00 local
    that day); none of them: now."""

    client_id: ClientId
    piece: PieceId
    kind: EventKind
    at: datetime | None = None
    sent: datetime | None = None
    stated_at: datetime | None = None
    day: date | None = None
    source: Source = "tap"
    via: str = Field(default="panel", min_length=1, max_length=40)
    how: How = "tap"
    score: float | None = Field(default=None, ge=0.0, le=1.0)
    verified: bool = True
    to: State | None = None
    place: PlaceId | None = None
    load: str | None = Field(default=None, max_length=24)
    batch: str | None = Field(default=None, max_length=24)
    due: date | None = None
    plan: str | None = Field(default=None, max_length=40)
    note: str = Field(default="", max_length=120)


class ScanRequest(_M):
    rev_seen: int | None = Field(default=None, ge=0)
    events: tuple[EventIn, ...] = Field(min_length=1, max_length=SCAN_MAX)


class ScanReply(_M):
    applied: int = Field(ge=0)
    duplicates: int = Field(ge=0)
    review: int = Field(ge=0)  # entries opened (holds, conflicts)
    already_done: bool = False
    marks: dict[str, Mark] = Field(default_factory=dict)  # client_id -> mark
    message: str
    view: WardrobeView | None = None  # the fresh view when `already_done`


# ---- photos, fingerprints, tagging (the door: console-r7-send.js wardrobe() / tag()) ---------
class PhotoSaved(_M):
    """POST /v1/wardrobe/photos?piece=&view= (body: image/jpeg, <= wardrobe_photo_max_kb)."""

    photo: PhotoId
    piece: PieceId
    view: View
    bytes: int = Field(ge=1)


class Deleted(_M):
    deleted: bool
    message: str


class FingerprintIn(_M):
    piece: PieceId
    view: View
    model: Literal["mnv2-int8-1", "mnv2-fp32-1"]
    v: str = Field(min_length=1708, max_length=1708, pattern=r"^[A-Za-z0-9+/]+=*$")


class FingerprintView(_M):
    piece: PieceId
    view: View
    v: str = Field(min_length=1708, max_length=1708)


class Fingerprints(_M):
    """GET /v1/wardrobe/fingerprints?model=: his saved fingerprints of ONE model (never a
    private piece's); decrypted for the signed-in console, kept in its memory only."""

    model: Literal["mnv2-int8-1", "mnv2-fp32-1"]
    items: tuple[FingerprintView, ...] = Field(default=(), max_length=1800)


class FingerprintSaved(_M):
    piece: PieceId
    view: View
    model: str


class TagEstimate(_M):
    """GET /v1/wardrobe/tag/estimate?piece=: the press's rupees, before anything is sent."""

    inr: float = Field(ge=0.0)
    month_inr: float = Field(ge=0.0)
    cap_inr: int = Field(ge=0)
    allowed: bool
    why: str = ""


class TagSuggestion(_M):
    category: Category | None = None
    type: str | None = None
    colour: str | None = None
    pattern: str | None = None
    formality: int | None = Field(default=None, ge=1, le=5)
    occasions: tuple[str, ...] = ()


class TagReply(_M):
    """POST /v1/wardrobe/tag?piece= (body: image/jpeg): a suggestion, never a locked field."""

    piece: PieceId
    suggestion: TagSuggestion
    inr: float = Field(ge=0.0)
    month_inr: float = Field(ge=0.0)


# ---- labels, backup and restore -----------------------------------------------------------
class LabelAssign(_M):
    code: LabelCode
    piece: PieceId | None = None  # None: the label is free again


class RestoreCounts(_M):
    added: int = Field(ge=0)
    already_there: int = Field(ge=0)
    superseded: int = Field(ge=0)
    back_from_bin: int = Field(ge=0)
    purged_since: int = Field(ge=0)
    events: int = Field(ge=0)


class RestoreCheck(_M):
    """POST /v1/wardrobe/restore/check (the file): checked, nothing written (D17)."""

    token: str = Field(min_length=16, max_length=64)
    counts: RestoreCounts
    purged: tuple[PieceId, ...] = ()
    photos: bool = False
    message: str


class RestoreApply(_M):
    """POST /v1/wardrobe/restore?token=&include= (the same file): applied in chunks of <= 50
    pieces, idempotent; a purged piece comes back only if ticked (`include`)."""

    token: str = Field(min_length=16, max_length=64)
    include_purged: tuple[PieceId, ...] = ()


class RestoreDone(_M):
    counts: RestoreCounts
    chunks: int = Field(ge=0)
    message: str


class Pilot(_M):
    """GET /v1/wardrobe/pilot: e2e 8's counts (counts only, never a piece)."""

    scans_with_candidate: int = Field(ge=0)
    first_candidate_chosen: int = Field(ge=0)
    events: int = Field(ge=0)
    state_corrections: int = Field(ge=0)
    suggested: int = Field(ge=0)
    unavailable_suggested: int = Field(ge=0)


class ToolCall(_M):
    """POST /v1/wardrobe/tools/{tool}: the panel's change through `gateway.execute` (D1): the
    same cards, rows and audit as the AI's call."""

    arguments: dict[str, object] = Field(default_factory=dict)


class ToolReply(_M):
    status: Literal["executed", "needs_approval", "denied", "error"]
    message: str
    result: dict[str, object] | None = None
    approval_id: str | None = None


__all__ = [
    "LABELS_A_PAGE",
    "PAGE_MAX",
    "SCAN_MAX",
    "CountRow",
    "Counts",
    "Deleted",
    "EventIn",
    "EventView",
    "FingerprintIn",
    "FingerprintSaved",
    "FingerprintView",
    "Fingerprints",
    "LabelAssign",
    "LabelView",
    "PairView",
    "PhotoSaved",
    "PieceDetail",
    "PieceView",
    "Pilot",
    "PlaceView",
    "Ready",
    "RestoreApply",
    "RestoreCheck",
    "RestoreCounts",
    "RestoreDone",
    "ScanReply",
    "ScanRequest",
    "SetView",
    "SettingsView",
    "TagEstimate",
    "TagReply",
    "TagSuggestion",
    "ToolCall",
    "ToolReply",
    "WardrobeView",
]
