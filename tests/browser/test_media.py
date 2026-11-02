# tests/browser/test_media.py — slice 12 D3/D4 in a real browser: the Maps cards under a reply carry
# the "Google Maps" attribution and an Open in Google Maps link (https Google Maps only, new tab,
# text only — never markup); a route card has its directions link; the YouTube card's Play button is
# the ONLY thing that creates a player: no iframe exists anywhere before the owner clicks Play, and
# nothing requests youtube-nocookie.com before it; Play makes exactly one youtube-nocookie embed for
# that id in the Media panel, Stop removes it; Vitals shows "N of 31,500 searches / N of 31,500
# routes this month" and "N of 90 searches today"; Integrations → Maps saves Home and Work; a phone
# keeps ≤ 8 tabs with Media behind More and no horizontal scroll. /v1/chat, /v1/quota and
# /v1/maps/places are answered by the test (page.route); YouTube's own host is intercepted.
from __future__ import annotations

import json
from collections.abc import Iterator
from typing import Any

import pytest
from test_console import DESKTOP, PHONE, Console  # same directory (pytest prepend import)

_pw = pytest.importorskip("playwright.sync_api")
sync_playwright = _pw.sync_playwright

pytestmark = pytest.mark.browser


@pytest.fixture(scope="module")
def browser() -> Iterator[Any]:
    with sync_playwright() as p:
        b = p.chromium.launch()
        yield b
        b.close()


HOSTILE = '<img src=x onerror="window.__pwned=1">Cafe'
VID = "dQw4w9WgXcQ"
PLACES = {
    "kind": "places",
    "attribution": "Google Maps",
    "query": "cafe",
    "items": [
        {
            "name": HOSTILE,
            "address": "1 MG Road",
            "url": "https://maps.google.com/?cid=1",
            "place_id": "ChIJone",
        },
        {"name": "Bad link", "address": "x", "url": "javascript:alert(1)", "place_id": "ChIJtwo"},
        {"name": "Elsewhere", "address": "x", "url": "https://evil.example/", "place_id": "ChIJ3"},
        {
            "name": "Closed",
            "address": "2 MG Road",
            "status": "permanently closed",
            "url": "https://www.google.com/maps/search/?api=1&query=Closed&query_place_id=ChIJ4",
            "place_id": "ChIJ4",
        },
    ],
}
ROUTE = {
    "kind": "route",
    "attribution": "Google Maps",
    "origin": "Home",
    "destination": "Work",
    "mode": "drive",
    "duration_minutes": 75,
    "distance_km": 12.3,
    "traffic": True,
    "url": "https://www.google.com/maps/dir/?api=1&origin=Kowdiar&destination=Technopark&travelmode=driving",
}
VIDEOS = {
    "kind": "videos",
    "attribution": "YouTube",
    "title": "",
    "items": [
        {"id": VID, "title": "Song one", "channel": "Chan", "duration": "3:05", "embeddable": True},
        {"id": "bad/id", "title": "Bad", "channel": "x", "duration": "", "embeddable": True},
        {
            "id": "abcdefghijk",
            "title": "Song two",
            "channel": "Chan 2",
            "duration": "4:00",
            "embeddable": True,
        },
        {
            "id": "zzzzzzzzzzz",
            "title": "Blocked",
            "channel": "c",
            "duration": "",
            "embeddable": False,
        },
    ],
}
QUOTA = {
    "configured": True,
    "maps_search": {
        "period": "2026-11",
        "used": 12,
        "limit": 31500,
        "left": 31488,
        "reached": False,
        "unreadable": False,
    },
    "maps_route": {
        "period": "2026-11",
        "used": 3,
        "limit": 31500,
        "left": 31497,
        "reached": False,
        "unreadable": False,
    },
    "maps_geocode": {
        "period": "2026-11",
        "used": 6,
        "limit": 63000,
        "left": 62994,
        "reached": False,
        "unreadable": False,
    },
    "youtube_search": {
        "period": "2026-11-15",
        "used": 4,
        "limit": 90,
        "left": 86,
        "reached": False,
        "unreadable": False,
    },
    "youtube_units": {
        "period": "2026-11-15",
        "used": 9,
        "limit": 9000,
        "left": 8991,
        "reached": False,
        "unreadable": False,
    },
}


def _reply(text: str, cards: list[Any]) -> dict[str, Any]:
    return {
        "session_id": "sess_media",
        "reply": text,
        "tool_calls": 1,
        "pending_approvals": [],
        "trace_id": "t1",
        "model": "mock-balanced",
        "brain": "mock",
        "usage": {"input_tokens": 10, "output_tokens": 5},
        "cost_usd": 0.0,
        "cost_inr": 0.0,
        "total_cost_usd": 0.0,
        "total_cost_inr": 0.0,
        "latency_ms": 120,
        "turn_count": 2,
        "memory_used": [],
        "sources": [],
        "cards": cards,
    }


def _json(page: Any, pattern: str, body: Any) -> None:
    page.route(
        pattern,
        lambda route: route.fulfill(
            status=200, content_type="application/json", body=json.dumps(body)
        ),
    )


class Rig:
    def __init__(self, c: Console) -> None:
        self.c = c
        self.youtube: list[str] = []  # every request the page made to YouTube's host
        self.saved: list[Any] = []
        c.page.add_init_script("try { localStorage.clear(); } catch (_) {}")
        c.page.route("https://www.youtube-nocookie.com/**", self._yt)
        _json(c.page, "**/v1/quota", QUOTA)
        c.page.route("**/v1/maps/places", self._places)

    def _yt(self, route: Any) -> None:
        self.youtube.append(route.request.url)
        route.fulfill(
            status=200, content_type="text/html", body="<!doctype html><title>player</title>"
        )

    def _places(self, route: Any) -> None:
        if route.request.method == "PUT":
            body = json.loads(route.request.post_data or "{}")
            self.saved.append(body)
            route.fulfill(
                status=200,
                content_type="application/json",
                body=json.dumps({"configured": True, **body}),
            )
        else:
            route.fulfill(
                status=200,
                content_type="application/json",
                body=json.dumps({"configured": True, "home": None, "work": None}),
            )

    def iframes(self) -> int:
        return int(self.c.page.evaluate("document.querySelectorAll('iframe').length"))


@pytest.fixture
def rig(browser: Any, server_url: str, token: str) -> Iterator[Rig]:
    c = Console(browser, server_url, token, DESKTOP)
    yield Rig(c)
    c.close()


def test_place_and_route_cards_carry_attribution_and_google_maps_links(rig: Rig) -> None:
    c = rig.c
    _json(c.page, "**/v1/chat", _reply("Found these.", [PLACES, ROUTE]))
    c.open()
    c.send("cafes and time to work")
    c.page.locator(".row.jarvis .mcards").wait_for()
    cards = c.page.evaluate(
        """() => [...document.querySelectorAll('.row.jarvis .mcard')].map(card => ({
             cls: card.className, attr: card.querySelector('.mattr')?.textContent,
             links: [...card.querySelectorAll('a')].map(a => ({href: a.getAttribute('href'),
               rel: a.rel, target: a.target, text: a.textContent})),
             names: [...card.querySelectorAll('.mtxt b')].map(b => b.textContent),
             text: card.textContent }))"""
    )
    places, route = cards
    assert places["attr"] == "Google Maps" and route["attr"] == "Google Maps"
    assert places["names"] == [HOSTILE, "Closed"]  # bad links dropped; the name stays text
    hrefs = [link["href"] for link in places["links"]]
    assert hrefs == ["https://maps.google.com/?cid=1", PLACES["items"][3]["url"]]
    for link in places["links"] + route["links"]:
        assert link["text"] == "Open in Google Maps"
        assert link["target"] == "_blank" and link["rel"] == "noopener noreferrer"
    assert "permanently closed" in places["text"]
    assert route["links"][0]["href"] == ROUTE["url"]
    assert "1 h 15 min" in route["text"] and "12.3 km by car" in route["text"]
    assert c.page.locator(".row.jarvis img").count() == 0
    assert c.page.evaluate("window.__pwned === undefined")
    assert rig.iframes() == 0 and rig.youtube == []
    assert c.csp_violations() == [] and c.errors == []


def test_no_player_exists_until_the_owner_clicks_play(rig: Rig) -> None:
    c = rig.c
    _json(c.page, "**/v1/chat", _reply("Here is some music.", [VIDEOS]))
    c.open()
    c.send("play some music")
    c.page.locator(".row.jarvis .mvideos").wait_for()
    assert c.page.locator(".mvideos .mattr").text_content() == "YouTube"
    # two valid embeddable ids get Play; the bad id is dropped; the blocked one says so in words
    assert c.page.locator(".mvideos .mplay").count() == 2
    assert "Can only be played on YouTube" in str(c.page.locator(".mvideos").text_content())
    c.open_panel("media")
    c.page.wait_for_timeout(400)
    assert rig.iframes() == 0 and rig.youtube == []  # opening the panel plays nothing
    c.page.locator(".mvideos .mplay").first.click()
    frame = c.page.locator("#mediaStage iframe")
    frame.wait_for()
    assert rig.iframes() == 1
    src = str(frame.get_attribute("src"))
    assert src.startswith(f"https://www.youtube-nocookie.com/embed/{VID}?")
    assert "autoplay=1" in src  # started by the click itself
    assert frame.get_attribute("referrerpolicy") == "strict-origin-when-cross-origin"
    c.page.wait_for_function(
        "document.querySelector('#mediaNote').textContent.startsWith('Playing')"
    )
    # the second Play replaces the player (never two)
    c.page.locator(".mvideos .mplay").nth(1).click()
    c.page.wait_for_function(
        "document.querySelector('#mediaStage iframe').src.includes('/embed/abcdefghijk')"
    )
    assert rig.iframes() == 1
    c.page.locator("#mediaStop").click()
    assert rig.iframes() == 0
    assert all(u.startswith("https://www.youtube-nocookie.com/embed/") for u in rig.youtube)
    assert c.csp_violations() == [] and c.errors == []


def test_vitals_shows_the_free_allowance_lines(rig: Rig) -> None:
    c = rig.c
    c.open()
    c.open_panel("vitals")
    c.page.wait_for_function("document.getElementById('sMaps').textContent !== '—'")
    maps = c.page.locator("#sMaps").text_content()
    yt = c.page.locator("#sYouTube").text_content()
    assert maps == "12 of 31,500 searches / 3 of 31,500 routes this month"
    assert yt == "4 of 90 searches today"
    assert (
        c.page.locator("#sYouTube").get_attribute("aria-label") == "YouTube searches today: 4 of 90"
    )
    for el in ("#sMaps", "#sYouTube"):
        title = str(c.page.locator(el).get_attribute("title"))
        assert "$" not in title and "₹" not in title
    assert c.errors == []


def test_integrations_saves_home_and_work(rig: Rig) -> None:
    c = rig.c
    c.open()
    c.open_panel("integrations")
    c.page.locator("#integMaps #mapsEdit").click()
    c.page.locator("#mapsHome").fill("Kowdiar, Thiruvananthapuram")
    c.page.locator("#mapsWork").fill("Technopark Phase 3")
    c.page.locator("#integMaps form button[type=submit]").click()
    c.page.locator("#integMaps .inote", has_text="Saved").wait_for()
    assert rig.saved == [{"home": "Kowdiar, Thiruvananthapuram", "work": "Technopark Phase 3"}]
    assert "Technopark Phase 3" in str(c.page.locator("#integMaps").text_content())
    assert c.errors == []


def test_a_phone_keeps_eight_tabs_and_the_cards_fit(
    browser: Any, server_url: str, token: str
) -> None:
    c = Console(browser, server_url, token, PHONE)
    try:
        rig = Rig(c)
        long = {**VIDEOS, "items": [{**VIDEOS["items"][0], "title": "A very long title " * 10}]}
        _json(c.page, "**/v1/chat", _reply("Here.", [PLACES, ROUTE, long]))
        c.open()
        tabs = c.page.locator("#dock .dk:visible").count()
        assert tabs <= 8
        c.send("everything")
        c.page.locator(".row.jarvis .mcards").wait_for()
        overflow = c.page.evaluate(
            "document.documentElement.scrollWidth - document.documentElement.clientWidth"
        )
        assert overflow <= 0
        box = c.page.locator(".mvideos .mplay").first.bounding_box()
        assert box and box["height"] >= 44
        c.open_panel("media")  # behind More on a phone
        assert rig.iframes() == 0
        assert c.errors == []
    finally:
        c.close()
