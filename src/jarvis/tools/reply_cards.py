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
first ones, in order), so neither kind can crowd the other out. A card is never dropped silently
(final review): a tool checks `reply_full` BEFORE it runs and refuses in plain words when its kind's
cap is reached (`CARD_NOT_SHOWN` / `DRAFT_NOT_SHOWN`: nothing looked up, no allowance spent), and if
`add_card` still says no, its result says the card was not shown and asks the owner to ask again.

Every field is checked when a card is MADE (the pydantic models below raise; `add_card` takes only
a made card): a Maps link must be an https Google Maps address (`google_maps_url`), a video id
exactly 11 characters of [A-Za-z0-9_-], and each card's attribution is fixed by its kind ("Google
Maps", "YouTube"); a WhatsApp draft's number must be E.164, its text clean and its link exactly the
wa.me link of that number and text (`jarvis.whatsapp.draft.WhatsAppCard`). The console checks every
field again and writes text with textContent only (console-media.js, console-whatsapp.js).
"""

from __future__ import annotations

import contextvars
import re
from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from typing import Annotated, Final, Literal

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator

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

CARD_NOT_SHOWN: Final = (
    f"Not shown: one reply shows at most {MAX_CARDS} Maps / YouTube cards and this reply is full, "
    "so nothing was looked up. Tell the owner, and ask them to ask for it again in a new message."
)
DRAFT_NOT_SHOWN: Final = (
    f"Not shown: one reply shows at most {MAX_DRAFTS} WhatsApp drafts and this reply is full, so "
    "this draft was not made and nothing was sent. Tell the owner, and ask them to ask for it "
    "again in a new message."
)


def _count(cards: Iterable[AnyCard], *, drafts: bool) -> int:
    return sum(isinstance(c, WhatsAppCard) is drafts for c in cards)


def _has_room(cards: list[AnyCard], card: AnyCard) -> bool:
    """Whether `cards` can take `card` within the reply's cap for its kind."""
    if isinstance(card, WhatsAppCard):
        return _count(cards, drafts=True) < MAX_DRAFTS
    return _count(cards, drafts=False) < MAX_CARDS


def capped(have: list[AnyCard], new: Iterable[AnyCard]) -> list[AnyCard]:
    """One reply's cards after more arrive (Approve all): the first ones of each kind, in
    order, within MAX_CARDS / MAX_DRAFTS. A new list; `have` is left as it was."""
    out = list(have)
    for card in new:
        if _has_room(out, card):
            out.append(card)
    return out


_current: contextvars.ContextVar[list[AnyCard] | None] = contextvars.ContextVar(
    "jarvis_reply_cards", default=None
)


@contextmanager
def collecting_cards(into: list[AnyCard]) -> Iterator[list[AnyCard]]:
    """Cards added inside go into `into` (within the caps); always reset. `into` may already
    hold the reply's earlier cards (Approve all): they count towards the caps."""
    token = _current.set(into)
    try:
        yield into
    finally:
        _current.reset(token)


def showing_cards() -> bool:
    """True inside a reply that collects cards (a Brain turn or an approval being run)."""
    return _current.get() is not None


def reply_full(*, drafts: bool) -> bool:
    """True only inside a collecting reply that already shows its cap of WhatsApp drafts
    (`drafts`) or of Maps / YouTube cards. A tool asks BEFORE it runs, so a card that could not
    be shown never spends an allowance. Outside a reply: False (nothing to show it on)."""
    sink = _current.get()
    if sink is None:
        return False
    return _count(sink, drafts=drafts) >= (MAX_DRAFTS if drafts else MAX_CARDS)


def add_card(card: AnyCard) -> bool:
    """Show `card` with this reply. False when it won't be shown: outside a collecting reply, or
    the reply already has its kind's cap (MAX_CARDS / MAX_DRAFTS) — then `reply_full` is True
    and the tool's result says the card was not shown."""
    sink = _current.get()
    if sink is None or not _has_room(sink, card):
        return False
    sink.append(card)
    return True


__all__ = [
    "CARD_NOT_SHOWN",
    "DRAFT_NOT_SHOWN",
    "MAPS_ATTRIBUTION",
    "MAX_CARDS",
    "MAX_DRAFTS",
    "VIDEO_ID",
    "YOUTUBE_ATTRIBUTION",
    "AnyCard",
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
    "reply_full",
    "showing_cards",
]
