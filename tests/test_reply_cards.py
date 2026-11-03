# tests/test_reply_cards.py — slice 12 D3/D4: the console cards (place, route, video) a reply
# carries. A tool adds a card for the owner's screen beside its result (never in what the model
# sees); the Brain collects the cards of one owner message onto the reply (never the stored turn);
# every field is checked when a card is made, so a card can't carry a non-Google link or a bad
# video id. Final review: a full reply is known before a tool runs (`reply_full`).
from __future__ import annotations

from typing import Any

import pytest
from pydantic import TypeAdapter, ValidationError

from jarvis.core.models import ChatResponse, Session, Turn
from jarvis.llm.base import Role
from jarvis.tools.reply_cards import (
    MAX_CARDS,
    MAX_DRAFTS,
    AnyCard,
    PlacesCard,
    ReplyCard,
    RouteCard,
    VideosCard,
    WhatsAppCard,
    add_card,
    collecting_cards,
    reply_full,
)
from jarvis.whatsapp.draft import wa_link

_ONE: TypeAdapter[AnyCard] = TypeAdapter(ReplyCard)


def parse_cards(raw: list[Any]) -> list[AnyCard]:
    """The cards among `raw` that can be made (each checked field by field), in order."""
    out: list[AnyCard] = []
    for item in raw:
        try:
            out.append(_ONE.validate_python(item))
        except ValidationError:
            continue
    return out


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
    assert parse_cards([_places(url)]) == []


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
    assert len(parse_cards([_places(url)])) == 1


@pytest.mark.parametrize("vid", ["short", "dQw4w9WgXcQ1", "dQw4w9WgX/Q", "dQw4w9WgX Q", 5])
def test_a_video_card_needs_an_eleven_character_video_id(vid: object) -> None:
    assert parse_cards([_video(vid)]) == []  # type: ignore[arg-type]


def test_parse_cards_drops_what_does_not_read_back_and_keeps_the_rest() -> None:
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
    cards = parse_cards(["junk", {"kind": "nope"}, _places(), route, _video(), None])
    assert [type(c) for c in cards] == [PlacesCard, RouteCard, VideosCard]


def test_attribution_is_fixed_by_kind() -> None:
    assert parse_cards([{**_places(), "attribution": "Evil Maps"}]) == []
    assert parse_cards([{**_video(), "attribution": "Not YouTube"}]) == []


def test_cards_ride_on_the_live_reply_only_never_on_the_stored_turn() -> None:
    """Plan D3: JARVIS caches nothing from Google but place ids. A card is shown once, with the
    reply; the stored conversation keeps the reply's text, not the card."""
    assert "cards" in ChatResponse.model_fields
    assert "cards" not in Turn.model_fields
    t = Turn(role=Role.ASSISTANT, content="Here")
    assert "maps.google.com" not in Session(user_id="u", turns=[t]).model_dump_json()


def _draft(i: int) -> WhatsAppCard:
    text = f"hi {i}"
    return WhatsAppCard(number="+919876543210", text=text, link=wa_link("+919876543210", text))


def test_reply_full_is_known_per_kind_before_a_tool_runs() -> None:
    got: list[AnyCard] = []
    assert reply_full(drafts=True) is False and reply_full(drafts=False) is False  # no reply
    with collecting_cards(got):
        for i in range(MAX_DRAFTS):
            assert reply_full(drafts=True) is False
            assert add_card(_draft(i))
        assert reply_full(drafts=True) is True  # five drafts: the sixth would be dropped
        assert reply_full(drafts=False) is False  # Maps / YouTube cards are counted apart
        for _ in range(MAX_CARDS):
            assert add_card(VideosCard.model_validate(_video()))
        assert reply_full(drafts=False) is True
        assert add_card(_draft(9)) is False and add_card(PlacesCard()) is False
