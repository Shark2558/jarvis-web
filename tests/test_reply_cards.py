# tests/test_reply_cards.py — slice 12 D3/D4: the console cards (place, route, video) a reply
# carries. A tool adds a card for the owner's screen beside its result (never in what the model
# sees); the Brain collects the cards of one owner message onto the reply (never the stored turn);
# every field is checked when a card is made (`ReplyCard`, what ChatResponse.cards holds), so a
# card can't carry a non-Google link or a bad video id.
from __future__ import annotations

from typing import Any

import pytest
from pydantic import TypeAdapter, ValidationError

from jarvis.core.models import ChatResponse, Session, Turn
from jarvis.llm.base import Role
from jarvis.tools.reply_cards import (
    MAX_CARDS,
    PlacesCard,
    ReplyCard,
    RouteCard,
    VideosCard,
    add_card,
    collecting_cards,
)

_CARD: TypeAdapter[Any] = TypeAdapter(ReplyCard)


def _made(raw: object) -> bool:
    """Whether a card can be made from `raw` (ChatResponse.cards' own type)."""
    try:
        _CARD.validate_python(raw)
    except ValidationError:
        return False
    return True


def _places(url: str = "https://maps.google.com/?cid=1") -> dict[str, Any]:
    return {
        "kind": "places",
        "attribution": "Google Maps",
        "items": [{"name": "Cafe", "address": "MG Road", "url": url, "place_id": "ChIJabc"}],
    }


def _video(vid: str = "dQw4w9WgXcQ") -> dict[str, Any]:
    return {
        "kind": "videos",
        "attribution": "YouTube",
        "items": [
            {"id": vid, "title": "Song", "channel": "Ch", "duration": "3:05", "embeddable": True}
        ],
    }


def test_add_card_outside_a_message_is_a_no_op() -> None:
    add_card(PlacesCard.model_validate(_places()))  # nothing collects it, nothing breaks


def test_cards_are_collected_in_order_up_to_the_cap() -> None:
    got: list[Any] = []
    with collecting_cards(got):
        for _ in range(MAX_CARDS + 3):
            add_card(VideosCard.model_validate(_video()))
    assert len(got) == MAX_CARDS


@pytest.mark.parametrize(
    "url",
    [
        "javascript:alert(1)",
        "http://maps.google.com/?cid=1",
        "https://evil.example/",
        "https://maps.google.com.evil.example/",
        "https://u:p@www.google.com/maps/",
        "https://www.google.com/search?q=x",  # Google, but not Maps
    ],
)
def test_a_place_card_link_must_be_a_google_maps_address(url: str) -> None:
    assert not _made(_places(url))


@pytest.mark.parametrize(
    "url",
    [
        "https://maps.google.com/?cid=1",
        "https://www.google.com/maps/search/?api=1&query=x",
        "https://www.google.com/maps/dir/?api=1&origin=a&destination=b",
        "https://google.com/maps/place/x",
        "https://maps.app.goo.gl/abc",
    ],
)
def test_google_maps_links_are_kept(url: str) -> None:
    assert _made(_places(url))


@pytest.mark.parametrize("vid", ["short", "dQw4w9WgXcQ1", "dQw4w9WgX/Q", "dQw4w9WgX Q", 5])
def test_a_video_card_needs_an_eleven_character_video_id(vid: object) -> None:
    assert not _made(_video(vid))  # type: ignore[arg-type]


def test_each_kind_is_made_as_its_own_card_and_anything_else_is_refused() -> None:
    route = {
        "kind": "route",
        "attribution": "Google Maps",
        "origin": "Home",
        "destination": "Work",
        "mode": "drive",
        "duration_minutes": 25,
        "distance_km": 12.3,
        "url": "https://www.google.com/maps/dir/?api=1&origin=a&destination=b&travelmode=driving",
    }
    made = [_CARD.validate_python(c) for c in (_places(), route, _video())]
    assert [type(c) for c in made] == [PlacesCard, RouteCard, VideosCard]
    for junk in ("junk", {"kind": "nope"}, None):
        assert not _made(junk)


def test_attribution_is_fixed_by_kind() -> None:
    assert not _made({**_places(), "attribution": "Evil Maps"})
    assert not _made({**_video(), "attribution": "Not YouTube"})


def test_cards_ride_on_the_live_reply_only_never_on_the_stored_turn() -> None:
    """Plan D3: JARVIS caches nothing from Google but place ids. A card is shown once, with the
    reply; the stored conversation keeps the reply's text, not the card."""
    assert "cards" in ChatResponse.model_fields
    assert "cards" not in Turn.model_fields
    t = Turn(role=Role.ASSISTANT, content="Here")
    assert "maps.google.com" not in Session(user_id="u", turns=[t]).model_dump_json()


def test_has_room_counts_each_kinds_cap_apart_and_is_open_outside_a_reply() -> None:
    """Code review CR-1: a tool asks BEFORE its work whether the reply can still show its card."""
    from jarvis.tools.reply_cards import MAX_DRAFTS, has_room
    from jarvis.whatsapp.draft import WhatsAppCard, wa_link

    assert has_room("places") and has_room("whatsapp")  # no reply collecting: nothing to cap
    got: list[Any] = []
    with collecting_cards(got):
        for _ in range(MAX_CARDS):
            assert has_room("videos")
            assert add_card(VideosCard.model_validate(_video()))
        assert not has_room("videos") and not has_room("places") and not has_room("route")
        assert not add_card(VideosCard.model_validate(_video()))
        for i in range(MAX_DRAFTS):
            assert has_room("whatsapp")
            text = f"hi {i}"
            add_card(WhatsAppCard(number="+919876543210", text=text,
                                  link=wa_link("+919876543210", text)))  # fmt: skip
        assert not has_room("whatsapp")
    assert has_room("places")
