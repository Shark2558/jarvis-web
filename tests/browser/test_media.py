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
from test_console import (
    DESKTOP,
    PHONE,
    Console,
    PlaywrightTimeout,
)  # same directory (pytest prepend import)

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
    "pricing": "india",
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
    "maps_route_2w": {
        "period": "2026-11",
        "used": 6300,
        "limit": 6300,
        "left": 0,
        "reached": True,
        "paused_today": False,
        "unreadable": False,
    },
    "maps_route_walk": {
        "period": "2026-11",
        "used": 2,
        "limit": 63000,
        "left": 62998,
        "reached": False,
        "paused_today": False,
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
        self.referers: list[str] = []  # the Referer each of them carried ("" when none)
        self.saved: list[Any] = []
        self.gets = 0  # GET /v1/maps/places answered
        c.page.add_init_script("try { localStorage.clear(); } catch (_) {}")
        c.page.route("https://www.youtube-nocookie.com/**", self._yt)
        _json(c.page, "**/v1/quota", QUOTA)
        c.page.route("**/v1/maps/places", self._places)

    def _yt(self, route: Any) -> None:
        self.youtube.append(route.request.url)
        self.referers.append(str(route.request.all_headers().get("referer", "")))
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
            self.gets += 1
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


def test_the_page_sends_no_referrer_and_only_the_player_frame_sends_its_origin(rig: Rig) -> None:
    """Plan D4: the console page keeps Referrer-Policy no-referrer; the player's own iframe
    carries referrerpolicy=strict-origin-when-cross-origin, so YouTube's embed check gets the
    console's ORIGIN (never a path or query) and nothing else on the page sends a referrer."""
    c = rig.c
    policies: list[str] = []

    def on_response(resp: Any) -> None:
        if resp.request.resource_type == "document" and resp.url.startswith(c.url):
            policies.append(str(resp.headers.get("referrer-policy")))

    c.page.on("response", on_response)
    _json(c.page, "**/v1/chat", _reply("Here is some music.", [VIDEOS]))
    c.open("/?from=a-private-path")
    assert policies and set(policies) == {"no-referrer"}
    c.send("play some music")
    c.page.locator(".row.jarvis .mvideos").wait_for()
    c.open_panel("media")
    c.page.locator(".mvideos .mplay").first.click()
    frame = c.page.locator("#mediaStage iframe")
    frame.wait_for()
    assert frame.get_attribute("referrerpolicy") == "strict-origin-when-cross-origin"
    c.page.wait_for_function("document.querySelector('#mediaStage iframe') !== null")
    assert rig.referers, "the player was never requested"
    origin = c.url.rstrip("/") + "/"
    assert all(ref == origin for ref in rig.referers), rig.referers  # origin only, no path
    assert c.csp_violations() == [] and c.errors == []


def test_vitals_shows_the_free_allowance_lines(rig: Rig) -> None:
    c = rig.c
    c.open()
    c.open_panel("vitals")
    c.page.wait_for_function("document.getElementById('sMaps').textContent !== '—'")
    maps = c.page.locator("#sMaps").text_content()
    yt = c.page.locator("#sYouTube").text_content()
    # the two-wheeler SKU (Compute Routes Enterprise) has its own, smaller stop: named when paused
    assert maps == "12 of 31,500 searches / 3 of 31,500 routes this month · two-wheeler paused"
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


# ---- final review: one invisible-character rule (Malayalam keeps its joiners); "Never" hides ----

# chillu n (ZWJ) and a ZWNJ conjunct
MALAYALAM = (
    "\u0d2e\u0d32\u0d2f\u0d3e\u0d33\u0d02 \u0d05\u0d35\u0d28\u0d4d\u200d \u0d15\u0d4d\u200c\u0d15"
)
INTEG_OFF = {
    "google": {"connected": False, "email": None, "scopes": [], "expires_at": None,
               "needs_reconnect": False},
    "drive_available": False,
    "maps_available": False,
}  # fmt: skip


def test_a_malayalam_place_name_keeps_its_zero_width_joiners(rig: Rig) -> None:
    c = rig.c
    name = MALAYALAM + "\u200b\u202e"  # a zero-width space and a bidi override are still dropped
    place = {**PLACES, "items": [{**PLACES["items"][0], "name": name, "address": MALAYALAM}]}
    _json(c.page, "**/v1/chat", _reply("Found it.", [place]))
    c.open()
    c.send("a place in Malayalam")
    c.page.locator(".row.jarvis .mplaces").wait_for()
    shown = c.page.locator(".row.jarvis .mplaces .mtxt b").first.text_content()
    assert shown == MALAYALAM  # ZWJ / ZWNJ kept, the hidden two gone
    assert c.page.locator(".row.jarvis .mplaces .maddr").first.text_content() == MALAYALAM
    kept = c.page.evaluate("(s) => window.JarvisText.strip(s)", MALAYALAM)
    assert kept == MALAYALAM and c.errors == []
    # final review: tag characters (U+E0000-E007F), soft hyphen, CGJ and U+180E go too
    hidden = "\U000e0068\U000e0069\U000e007f\u00ad\u034f\u180e\U000e0000\U000e0001"
    said = c.page.evaluate("(s) => window.JarvisText.strip(s)", MALAYALAM + hidden)
    assert said == MALAYALAM
    assert (
        c.page.evaluate(
            "(s) => window.JarvisText.hasInvisible(s)", "x" + "\U000e0068\U000e0069\U000e007f"
        )
        is True
    )
    assert c.page.evaluate("(s) => window.JarvisText.hasInvisible(s)", MALAYALAM) is False


def test_home_and_work_are_hidden_when_integrations_says_maps_is_off(rig: Rig) -> None:
    c = rig.c
    _json(c.page, "**/v1/integrations", INTEG_OFF)
    c.open()
    c.open_panel("integrations")
    c.page.locator("#integrations .integ").first.wait_for()
    c.page.wait_for_function("document.getElementById('integMaps').hidden === true")
    c.page.wait_for_timeout(300)  # a places answer arriving late must not show it again
    assert c.page.locator("#integMaps").is_hidden() and c.page.locator("#mapsEdit").count() == 0
    assert rig.saved == [] and c.errors == []


def test_maps_off_shows_no_error_and_no_retry_even_when_its_check_would_fail(rig: Rig) -> None:
    """Merge of FE-11 and the final review: while maps_available is false the section is not
    asked for at all, so a failing /v1/maps/places can't bring it back as an error with Retry."""
    c = rig.c
    asked: list[str] = []

    def failing(route: Any) -> None:
        asked.append(route.request.method)
        body = json.dumps({"error": "unavailable", "detail": "Try later."})
        route.fulfill(status=503, content_type="application/json", body=body)

    _json(c.page, "**/v1/integrations", INTEG_OFF)
    c.page.route("**/v1/maps/places", failing)  # the newest route answers first
    c.open()
    c.open_panel("integrations")
    c.page.locator("#integrations .integ").first.wait_for()  # drawn with the maps: false it fired
    c.page.wait_for_function("() => document.getElementById('integMaps').hidden === true")
    asked.clear()  # a check sent before the answer said "off" doesn't count
    c.page.evaluate(
        "document.dispatchEvent(new CustomEvent('jarvis:panel',"
        " {detail: {id: 'integrations', open: true}}))"
    )
    c.page.wait_for_timeout(300)
    assert c.page.locator("#integMaps").is_hidden() and c.page.locator("#mapsRetry").count() == 0
    assert asked == []


# ---- review FE-2: the Maps and YouTube Vitals lines wrap; "paused" is never cut off ------------

PAUSED = {
    **QUOTA,
    "maps_search": {**QUOTA["maps_search"], "used": 31500, "left": 0, "reached": True},
    "maps_route_walk": {**QUOTA["maps_route_walk"], "used": 63000, "left": 0, "reached": True},
    "youtube_search": {**QUOTA["youtube_search"], "used": 90, "left": 0, "reached": True},
}


@pytest.mark.parametrize("width", [1366, 390])
def test_vitals_maps_and_youtube_lines_are_never_cut_off(
    browser: Any, server_url: str, token: str, width: int
) -> None:
    c = Console(browser, server_url, token, {"width": width, "height": 900})
    try:
        Rig(c)
        _json(c.page, "**/v1/quota", PAUSED)  # the newest route answers first
        c.open()
        c.open_panel("vitals")
        c.page.wait_for_function("document.getElementById('sMaps').textContent.includes('paused')")
        maps = str(c.page.locator("#sMaps").text_content())
        assert maps.endswith("· two-wheeler paused · walking paused")  # FE-10: same text
        yt = str(c.page.locator("#sYouTube").text_content())
        assert yt == "90 of 90 searches today · paused until midnight Pacific"
        for el in ("#sMaps", "#sYouTube"):
            fits = c.page.locator(el).evaluate(
                "el => el.scrollWidth <= el.clientWidth && el.getBoundingClientRect().right"
                " <= el.closest('.pbody').getBoundingClientRect().right + 0.5"
            )
            assert fits, el
        # a short value on another row keeps its one line, right-aligned
        net = c.page.locator("#sNet").evaluate(
            "el => [getComputedStyle(el).whiteSpace, getComputedStyle(el).textAlign]"
        )
        assert net == ["nowrap", "right"]
        overflow = c.page.evaluate(
            "document.documentElement.scrollWidth - document.documentElement.clientWidth"
        )
        assert overflow <= 0
        assert c.errors == []
    finally:
        c.close()


# ---- review FE-3: keyboard focus never falls to <body> after a re-render ------------------------


def _active(c: Console) -> str:
    return str(
        c.page.evaluate(
            "(() => { const a = document.activeElement;"
            " return a === document.body || !a ? 'BODY' : (a.id || a.className || a.tagName); })()"
        )
    )


@pytest.mark.parametrize("viewport", [DESKTOP, PHONE], ids=["desktop", "phone"])
def test_keyboard_focus_stays_on_a_control_after_each_media_action(
    browser: Any, server_url: str, token: str, viewport: dict[str, int]
) -> None:
    c = Console(browser, server_url, token, viewport)
    try:
        rig = Rig(c)
        _json(c.page, "**/v1/chat", _reply("Here is some music.", [VIDEOS]))
        c.open()
        c.send("play some music")
        c.page.locator(".row.jarvis .mvideos").wait_for()
        # Play (Enter): on a phone the Media tab replaces the chat, so focus goes into the panel
        c.page.locator(".mvideos .mplay").first.focus()
        c.page.keyboard.press("Enter")
        c.page.locator("#mediaStage iframe").wait_for(state="attached")
        assert _active(c) != "BODY"
        assert c.page.evaluate("document.activeElement.closest('.panel') !== null")
        # a queue item (Enter): focus lands on the now-current item's button
        c.page.locator("#mediaQueue .mqbtn").nth(1).focus()
        c.page.keyboard.press("Enter")
        c.page.wait_for_function(
            "document.querySelector('#mediaStage iframe').src.includes('/embed/abcdefghijk')"
        )
        assert _active(c) == "mqbtn"
        assert c.page.evaluate("document.activeElement.getAttribute('aria-current')") == "true"
        # Stop (Enter): focus goes to the panel heading
        c.page.locator("#mediaStop").focus()
        c.page.keyboard.press("Enter")
        assert rig.iframes() == 0
        assert _active(c) == "t-media"
        assert c.errors == []
    finally:
        c.close()


def test_a_late_places_answer_keeps_what_the_owner_is_typing(rig: Rig) -> None:
    """A full browser run (3 Nov) failed the focus test below once: Home was saved empty. A GET
    /v1/maps/places that answers after the owner opened Set Home and Work redrew the open form
    and wiped what was typed (and the focus). An open form is never redrawn by a load."""
    c = rig.c
    c.open()
    c.open_panel("integrations")
    edit = c.page.locator("#integMaps #mapsEdit")
    edit.wait_for()
    edit.click()
    c.page.locator("#mapsHome").fill("Kowdiar")
    before = rig.gets
    with c.page.expect_response("**/v1/maps/places"):  # the panel opens again: a fresh load
        c.page.evaluate(
            "document.dispatchEvent(new CustomEvent('jarvis:panel',"
            " { detail: { id: 'integrations', open: true } }))"
        )
    c.page.wait_for_timeout(200)  # let the answer be handled
    assert rig.gets == before + 1
    assert c.page.locator("#mapsHome").input_value() == "Kowdiar"
    assert _active(c) == "mapsHome"
    c.page.locator("#integMaps form button[type=submit]").click()
    c.page.locator("#integMaps .inote", has_text="Saved").wait_for()
    assert rig.saved == [{"home": "Kowdiar", "work": None}]
    assert c.errors == []


@pytest.mark.parametrize("viewport", [DESKTOP, PHONE], ids=["desktop", "phone"])
def test_keyboard_focus_stays_in_the_maps_section(
    browser: Any, server_url: str, token: str, viewport: dict[str, int]
) -> None:
    c = Console(browser, server_url, token, viewport)
    try:
        rig = Rig(c)
        c.open()
        c.open_panel("integrations")
        edit = c.page.locator("#integMaps #mapsEdit")
        edit.wait_for()
        assert edit.text_content() == "Set Home and Work"
        edit.focus()
        c.page.keyboard.press("Enter")
        assert _active(c) == "mapsHome"  # Set Home and Work -> the first field
        c.page.locator("#mapsEdit").focus()
        c.page.keyboard.press("Enter")  # Close
        assert _active(c) == "mapsEdit"
        c.page.locator("#mapsEdit").focus()
        c.page.keyboard.press("Enter")  # open again
        c.page.locator("#mapsHome").fill("Kowdiar")
        c.page.locator("#integMaps form button[type=submit]").focus()
        c.page.keyboard.press("Enter")  # Save
        c.page.locator("#integMaps .inote", has_text="Saved").wait_for()
        assert rig.saved == [{"home": "Kowdiar", "work": None}]
        assert _active(c) == "mapsEdit"
        assert c.errors == []
    finally:
        c.close()


# ---- review FE-4: the video stops whenever the Media panel is no longer shown -------------------


STOP_WAIT_MS = 5_000  # the player is gone within this long of the Media panel being hidden
DECK_STATE = """() => ({
  media: !!(window.JarvisDeck && window.JarvisDeck.isOpen('media')),
  chat: !!(window.JarvisDeck && window.JarvisDeck.isOpen('chat')),
  frames: document.querySelectorAll('iframe').length,
})"""


def _stopped(c: Console, rig: Rig) -> None:
    """The video is gone once Media is hidden. Waits (CI run 111 read the frame count while it
    was still 1, on a busy runner) and says what the deck showed if it never goes."""
    try:
        c.page.wait_for_function(
            "() => document.querySelectorAll('iframe').length === 0", timeout=STOP_WAIT_MS
        )
    except PlaywrightTimeout:
        pass
    assert rig.iframes() == 0, c.page.evaluate(DECK_STATE)


def test_on_a_phone_switching_to_chat_stops_the_video(
    browser: Any, server_url: str, token: str
) -> None:
    c = Console(browser, server_url, token, PHONE)
    try:
        rig = Rig(c)
        _json(c.page, "**/v1/chat", _reply("Here is some music.", [VIDEOS]))
        c.open()
        c.send("play some music")
        c.page.locator(".row.jarvis .mvideos .mplay").first.click()
        c.page.locator("#mediaStage iframe").wait_for(state="attached")
        assert rig.iframes() == 1
        c.page.locator('.dk[data-open="chat"]').click()
        c.page.locator("#p-chat").wait_for(state="visible")
        _stopped(c, rig)
        # reset layout (appearance menu) with the panel shown: stops too
        c.page.locator(".row.jarvis .mvideos .mplay").first.click()
        c.page.locator("#mediaStage iframe").wait_for(state="attached")
        c.page.evaluate("document.dispatchEvent(new CustomEvent('jarvis:reset-layout', {}))")
        assert rig.iframes() == 0
        assert c.errors == []
    finally:
        c.close()


def test_on_a_desktop_another_panel_opening_keeps_the_video(rig: Rig) -> None:
    c = rig.c
    _json(c.page, "**/v1/chat", _reply("Here is some music.", [VIDEOS]))
    c.open()
    c.send("play some music")
    c.page.locator(".row.jarvis .mvideos .mplay").first.click()
    c.page.locator("#mediaStage iframe").wait_for(state="attached")
    c.open_panel("vitals")  # the Media panel is still shown beside it
    assert rig.iframes() == 1
    c.page.evaluate("document.dispatchEvent(new CustomEvent('jarvis:reset-layout', {}))")
    # reset closes every panel but the chat; the check runs on the next task (setTimeout 0). A
    # function, not an expression: polling an expression needs eval, which the CSP forbids.
    c.page.wait_for_function("() => !document.querySelector('#mediaStage iframe')", timeout=2000)
    assert rig.iframes() == 0
    assert c.errors == []


# ---- review FE-5: prototype keys are never a mode -----------------------------------------------


@pytest.mark.parametrize("mode", ["toString", "constructor", "__proto__", "hasOwnProperty"])
def test_a_route_with_a_prototype_key_as_mode_is_dropped(rig: Rig, mode: str) -> None:
    c = rig.c
    c.open()
    c.page.wait_for_function("!!window.JarvisMedia")
    got = c.page.evaluate(
        "(card) => window.JarvisMedia.cards(document.createElement('div'), [card])",
        {**ROUTE, "mode": mode},
    )
    assert got is None
    assert c.page.evaluate(
        "(card) => window.JarvisMedia.cards(document.createElement('div'), [card]) !== null", ROUTE
    )
    assert c.errors == []


def test_scope_summary_counts_a_prototype_key_as_another_permission(rig: Rig) -> None:
    c = rig.c
    c.open()
    c.page.wait_for_function("!!window.JarvisIntegrations")
    for key in ("constructor", "toString", "__proto__"):
        got = c.page.evaluate("(k) => window.JarvisIntegrations.scopeSummary([k])", key)
        assert got == "1 other permission", key
    assert c.errors == []


# ---- review FE-6: right-to-left place names keep the route's reading order ---------------------

HEB_FROM = "תל אביב"  # Tel Aviv
HEB_TO = "ירושלים"  # Jerusalem


def test_a_hebrew_route_reads_origin_arrow_destination(rig: Rig) -> None:
    c = rig.c
    route = {**ROUTE, "origin": HEB_FROM, "destination": HEB_TO}
    rtl_places = {**PLACES, "items": [{**PLACES["items"][0], "name": HEB_TO, "address": HEB_FROM}]}
    rtl_videos = {**VIDEOS, "items": [{**VIDEOS["items"][0], "title": HEB_TO, "channel": HEB_FROM}]}
    _json(c.page, "**/v1/chat", _reply("Found.", [route, rtl_places, rtl_videos]))
    c.open()
    c.send("route")
    head = c.page.locator(".row.jarvis .mroute .mrhead")
    head.wait_for()
    boxes = head.evaluate(
        "el => [...el.children].map(n => { const r = n.getBoundingClientRect();"
        " return [n.tagName, n.textContent, r.left, r.right]; })"
    )
    (t0, origin, o_l, o_r), (_, arrow, a_l, a_r), (t2, dest, d_l, _d_r) = boxes
    assert origin == HEB_FROM and dest == HEB_TO
    assert t0 == "BDI" and t2 == "BDI"
    assert o_r <= a_l + 0.5 and a_r <= d_l + 0.5, boxes
    assert arrow == " → "  # FE-10: the same arrow, from an escape
    # place name / address and video title / channel are isolated too
    for sel in (".mplaces .mtxt", ".mvideos .mtxt"):
        tags = c.page.locator(f".row.jarvis {sel}").first.evaluate(
            "el => [...el.querySelectorAll('bdi')].map(b => b.textContent)"
        )
        assert HEB_TO in tags and any(HEB_FROM in t for t in tags), (sel, tags)
    assert c.errors == []


# ---- review FE-11: a failing GET /v1/maps/places says so and offers Retry -----------------------


def test_a_failing_maps_check_says_so_and_retry_fetches_again(
    browser: Any, server_url: str, token: str
) -> None:
    c = Console(browser, server_url, token, DESKTOP)
    try:
        Rig(c)
        calls: list[str] = []
        state = {"fail": True}

        def places(route: Any) -> None:
            calls.append(route.request.method)
            if state["fail"]:
                route.fulfill(
                    status=503,
                    content_type="application/json",
                    body=json.dumps({"error": "unavailable", "detail": "Try again in a minute."}),
                )
            else:
                route.fulfill(
                    status=200,
                    content_type="application/json",
                    body=json.dumps({"configured": True, "home": "Kowdiar", "work": None}),
                )

        c.page.route("**/v1/maps/places", places)  # the newest route answers first
        c.open()
        c.open_panel("integrations")
        sec = c.page.locator("#integMaps")
        sec.locator("#mapsRetry").wait_for()
        assert "Couldn't check Maps" in str(sec.text_content())
        assert sec.get_attribute("data-state") == "error"
        before = len(calls)
        state["fail"] = False
        c.page.locator("#mapsRetry").click()
        sec.locator("#mapsEdit").wait_for()
        assert len(calls) == before + 1
        assert "Kowdiar" in str(sec.text_content())
        assert "Couldn't check Maps" not in str(sec.text_content())
        assert [e for e in c.errors if "503" not in e] == []
    finally:
        c.close()


def test_maps_section_stays_hidden_when_maps_is_not_set_up(
    browser: Any, server_url: str, token: str
) -> None:
    c = Console(browser, server_url, token, DESKTOP)
    try:
        Rig(c)
        _json(c.page, "**/v1/maps/places", {"configured": False, "home": None, "work": None})
        c.open()
        c.open_panel("integrations")
        c.page.wait_for_timeout(400)
        assert c.page.locator("#integMaps").is_hidden()
        assert c.errors == []
    finally:
        c.close()


# ---- review FE-10: the escaped strings render exactly as before --------------------------------


def test_escaped_strings_render_as_before(rig: Rig) -> None:
    c = rig.c
    _json(c.page, "**/v1/chat", _reply("Found.", [ROUTE, VIDEOS]))
    c.open()
    c.send("route")
    c.page.locator(".row.jarvis .mroute").wait_for()
    fig = str(c.page.locator(".row.jarvis .mroute .mrfig").text_content())
    assert fig == "1 h 15 min · 12.3 km by car · with current traffic"
    sub = c.page.locator(".row.jarvis .mvideos .maddr").first.text_content()
    assert sub == "Chan · 3:05"
    c.open_panel("integrations")
    c.page.locator("#integMaps #mapsEdit").click()
    hint = c.page.locator("#integMaps .mform .fine").text_content()
    assert hint == (
        "An area, a street or a landmark — no phone numbers. "
        "Sent to Google only when you ask for a travel time."
    )
    # the page's own slice 12 lines: character references render the same characters as before
    first = c.page.evaluate(
        """async () => {
             const html = await (await fetch('/')).text();
             const d = new DOMParser().parseFromString(html, 'text/html');
             return [d.getElementById('sMaps').textContent,
                     d.getElementById('sYouTube').textContent,
                     d.querySelector('#integrations .empty').textContent];
           }"""
    )
    assert first == ["—", "—", "Checking linked accounts…"]
    assert c.errors == []
