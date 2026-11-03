# src/jarvis/tools/reply_cards.py
"""Console cards a reply carries (slice 12 D3/D4/D6; Layer 6 → 1): places, a route, videos, and
WhatsApp drafts — one mechanism for every card under a reply.

A tool adds a card for the OWNER's screen with `add_card` while it runs; the card travels beside
the tool's result, never inside what the model sees (so a link on a card always came from Google's
answer or from the checked draft, never from the model's words). Only code inside a tool that
actually ran can add one: a call that became an approval card adds nothing until it is approved
and runs. The Brain opens `collecting_cards` around one owner message's tool rounds (and around an
approved card's run; Approve all joins each approved call's cards with `capped`) and puts what was
collected on the reply (`ChatResponse.cards`). Cards are shown once, with that reply: they are not
stored with the conversation (Google Maps terms: JARVIS caches nothing but place ids).

Caps per reply: MAX_CARDS Maps / YouTube cards and, separately, MAX_DRAFTS WhatsApp drafts (the
first ones, in order), so neither kind can crowd the other out. A tool asks `has_room(kind)`
BEFORE its work (code review CR-1): past the cap it sends nothing to Google, takes nothing from
the allowances, and says so (`CARDS_FULL`, `DRAFTS_FULL`) — never "ready" for a card not shown.

Every field is checked on the way in (`parse_cards` drops anything that doesn't read back): a Maps
link must be an https Google Maps address (`google_maps_url`), a video id exactly 11 characters of
[A-Za-z0-9_-], and each card's attribution is fixed by its kind ("Google Maps", "YouTube"); a
WhatsApp draft's number must be E.164, its text clean and its link exactly the wa.me link of that
number and text (`jarvis.whatsapp.draft.WhatsAppCard`). The console checks every field again and
writes text with textContent only (console-media.js, console-whatsapp.js).
"""

from __future__ import annotations

import contextvars
import re
from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from typing import Annotated, Any, Final, Literal

import httpx
from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, ValidationError, field_validator

from jarvis.whatsapp.draft import WhatsAppCard

MAX_CARDS = 8  # Maps / YouTube cards per reply
MAX_DRAFTS = 5  # WhatsApp draft cards per reply (slice 12 D6), counted apart from MAX_CARDS
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


AnyCard = PlacesCard | RouteCard | VideosCard | WhatsAppCard
ReplyCard = Annotated[AnyCard, Field(discriminator="kind")]
_ONE: TypeAdapter[AnyCard] = TypeAdapter(ReplyCard)


CardKind = Literal["places", "route", "videos", "whatsapp"]
KINDS: tuple[CardKind, ...] = ("places", "route", "videos", "whatsapp")
# What a tool says when the reply can't show its card (code review CR-1): nothing was done
CARDS_FULL = (
    f"This reply already shows {MAX_CARDS} Maps and YouTube cards, the most one reply can show, "
    "so this look-up was not made and nothing was sent to Google. Answer with what you have; the "
    "owner can ask for more in a new message."
)
DRAFTS_FULL = (
    f"This reply already has {MAX_DRAFTS} WhatsApp drafts, the most one reply can show, so this "
    "draft was not made. Tell the owner which ones are still to do; they can ask for them in a "
    "new message."
)


def _room(cards: list[Any], *, draft: bool) -> bool:
    if draft:
        return sum(isinstance(c, WhatsAppCard) for c in cards) < MAX_DRAFTS
    return sum(not isinstance(c, WhatsAppCard) for c in cards) < MAX_CARDS


def _has_room(cards: list[Any], card: AnyCard) -> bool:
    """Whether `cards` can take `card` within the reply's cap for its kind."""
    return _room(cards, draft=isinstance(card, WhatsAppCard))


def capped(have: list[Any], new: Iterable[AnyCard]) -> list[Any]:
    """One reply's cards after more arrive (Approve all): the first ones of each kind, in
    order, within MAX_CARDS / MAX_DRAFTS. A new list; `have` is left as it was."""
    out = list(have)
    for card in new:
        if _has_room(out, card):
            out.append(card)
    return out


def parse_cards(raw: object) -> list[AnyCard]:
    """Cards that read back exactly, within the caps; anything else is dropped (never raises)."""
    out: list[AnyCard] = []
    for item in raw if isinstance(raw, list) else []:
        try:
            card = item if isinstance(item, AnyCard) else _ONE.validate_python(item)
        except ValidationError:
            continue
        if _has_room(out, card):
            out.append(card)
    return out


_current: contextvars.ContextVar[list[Any] | None] = contextvars.ContextVar(
    "jarvis_reply_cards", default=None
)


@contextmanager
def collecting_cards(into: list[Any]) -> Iterator[list[Any]]:
    """Cards added inside go into `into` (within the caps); always reset."""
    token = _current.set(into)
    try:
        yield into
    finally:
        _current.reset(token)


def has_room(kind: CardKind) -> bool:
    """Whether this reply can still show a card of `kind` (code review CR-1). A tool asks BEFORE
    its work, so it never pays Google for — or calls ready — a card the owner won't see. Outside
    a collecting reply (a script) True: nothing caps it there."""
    if kind not in KINDS:
        raise ValueError("unknown card kind")
    sink = _current.get()
    return sink is None or _room(sink, draft=kind == "whatsapp")


def add_card(card: AnyCard) -> bool:
    """Show `card` with this reply. False when it won't be shown: outside a collecting reply, or
    the reply already has its kind's cap (MAX_CARDS / MAX_DRAFTS)."""
    sink = _current.get()
    if sink is None or not _has_room(sink, card):
        return False
    sink.append(card)
    return True


__all__ = [
    "CARDS_FULL",
    "DRAFTS_FULL",
    "KINDS",
    "MAPS_ATTRIBUTION",
    "MAX_CARDS",
    "MAX_DRAFTS",
    "VIDEO_ID",
    "YOUTUBE_ATTRIBUTION",
    "AnyCard",
    "CardKind",
    "PlaceItem",
    "PlacesCard",
    "ReplyCard",
    "RouteCard",
    "VideoItem",
    "VideosCard",
    "WhatsAppCard",
    "add_card",
    "capped",
    "collecting_cards",
    "google_maps_url",
    "has_room",
    "parse_cards",
]
