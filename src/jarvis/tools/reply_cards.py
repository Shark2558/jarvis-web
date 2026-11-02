# src/jarvis/tools/reply_cards.py
"""Console cards a reply carries (slice 12 D3/D4; Layer 6 → 1): places, a route, videos.

A tool adds a card for the OWNER's screen with `add_card` while it runs; the card travels beside
the tool's result, never inside what the model sees (so a link on a card always came from Google's
answer, never from the model's words). The Brain opens `collecting_cards` around one owner
message's tool rounds (and around an approved card's run) and puts what was collected on the
reply (`ChatResponse.cards`). Cards are shown once, with that reply: they are not stored with the
conversation (Google Maps terms: JARVIS caches nothing but place ids).

Every field is checked on the way in (`parse_cards` drops anything that doesn't read back): a Maps
link must be an https Google Maps address (`google_maps_url`), a video id exactly 11 characters of
[A-Za-z0-9_-], and each card's attribution is fixed by its kind ("Google Maps", "YouTube"). The
console checks every field again and writes text with textContent only.
"""

from __future__ import annotations

import contextvars
import re
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Annotated, Any, Final, Literal

import httpx
from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, ValidationError, field_validator

MAX_CARDS = 8
MAX_ITEMS = 10
MAX_URL = 2048  # Google Maps URLs are limited to 2,048 characters
TEXT_LIMIT = 300
VIDEO_ID = re.compile(r"[A-Za-z0-9_-]{11}")
MAPS_ATTRIBUTION: Final = "Google Maps"
YOUTUBE_ATTRIBUTION: Final = "YouTube"
# hosts a Google Maps link may use; for the www / bare google.com hosts only paths under /maps
_MAPS_ANY_PATH = frozenset({"maps.google.com", "maps.app.goo.gl"})
_MAPS_UNDER_MAPS = frozenset({"www.google.com", "google.com"})


def google_maps_url(raw: object) -> str | None:
    """`raw` when it is an https Google Maps address (no user info, no port), else None."""
    if not isinstance(raw, str) or not raw or len(raw) > MAX_URL or any(c.isspace() for c in raw):
        return None
    try:
        u = httpx.URL(raw)
    except (httpx.InvalidURL, ValueError):
        return None
    if u.scheme != "https" or u.userinfo or u.port is not None:
        return None
    if u.host in _MAPS_ANY_PATH:
        return raw
    if u.host in _MAPS_UNDER_MAPS and (u.path == "/maps" or u.path.startswith("/maps/")):
        return raw
    return None


def _maps_link(v: object) -> str:
    url = google_maps_url(v)
    if url is None:
        raise ValueError("not a Google Maps address")
    return url


class _Strict(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class PlaceItem(_Strict):
    name: str = Field(max_length=TEXT_LIMIT)
    address: str = Field(default="", max_length=TEXT_LIMIT)
    url: str
    place_id: str = Field(pattern=r"^[A-Za-z0-9_-]{1,256}$")
    status: Literal["temporarily closed", "permanently closed"] | None = None

    @field_validator("url")
    @classmethod
    def _google_maps(cls, v: str) -> str:
        return _maps_link(v)


class PlacesCard(_Strict):
    kind: Literal["places"] = "places"
    attribution: Literal["Google Maps"] = MAPS_ATTRIBUTION
    query: str = Field(default="", max_length=TEXT_LIMIT)
    items: list[PlaceItem] = Field(default_factory=list, max_length=MAX_ITEMS)


class RouteCard(_Strict):
    kind: Literal["route"] = "route"
    attribution: Literal["Google Maps"] = MAPS_ATTRIBUTION
    origin: str = Field(max_length=TEXT_LIMIT)
    destination: str = Field(max_length=TEXT_LIMIT)
    mode: Literal["drive", "two_wheeler", "walk"]
    duration_minutes: int = Field(ge=0, le=100_000)
    distance_km: float = Field(ge=0, le=100_000)
    traffic: bool = False
    url: str

    @field_validator("url")
    @classmethod
    def _google_maps(cls, v: str) -> str:
        return _maps_link(v)


class VideoItem(_Strict):
    id: str = Field(pattern=r"^[A-Za-z0-9_-]{11}$")
    title: str = Field(max_length=TEXT_LIMIT)
    channel: str = Field(default="", max_length=TEXT_LIMIT)
    duration: str = Field(default="", max_length=16)  # "3:05", "1:02:03", "" when unknown
    embeddable: bool = True
    live: bool = False


class VideosCard(_Strict):
    kind: Literal["videos"] = "videos"
    attribution: Literal["YouTube"] = YOUTUBE_ATTRIBUTION
    title: str = Field(default="", max_length=TEXT_LIMIT)  # a playlist's name, when it is one
    items: list[VideoItem] = Field(default_factory=list, max_length=MAX_ITEMS * 2)


ReplyCard = Annotated[PlacesCard | RouteCard | VideosCard, Field(discriminator="kind")]
_ONE: TypeAdapter[PlacesCard | RouteCard | VideosCard] = TypeAdapter(ReplyCard)


def parse_cards(raw: object) -> list[PlacesCard | RouteCard | VideosCard]:
    """Cards that read back exactly; anything else is dropped (never raises)."""
    out: list[PlacesCard | RouteCard | VideosCard] = []
    for item in raw if isinstance(raw, list) else []:
        if isinstance(item, PlacesCard | RouteCard | VideosCard):
            out.append(item)
            continue
        try:
            out.append(_ONE.validate_python(item))
        except ValidationError:
            continue
    return out[:MAX_CARDS]


_current: contextvars.ContextVar[list[Any] | None] = contextvars.ContextVar(
    "jarvis_reply_cards", default=None
)


@contextmanager
def collecting_cards(into: list[Any]) -> Iterator[list[Any]]:
    """Cards added inside go into `into` (at most MAX_CARDS); always reset."""
    token = _current.set(into)
    try:
        yield into
    finally:
        _current.reset(token)


def add_card(card: PlacesCard | RouteCard | VideosCard) -> None:
    """Show `card` with this reply (no-op outside a collecting reply)."""
    sink = _current.get()
    if sink is not None and len(sink) < MAX_CARDS:
        sink.append(card)


__all__ = [
    "MAPS_ATTRIBUTION",
    "MAX_CARDS",
    "VIDEO_ID",
    "YOUTUBE_ATTRIBUTION",
    "PlaceItem",
    "PlacesCard",
    "ReplyCard",
    "RouteCard",
    "VideoItem",
    "VideosCard",
    "add_card",
    "collecting_cards",
    "google_maps_url",
    "parse_cards",
]
