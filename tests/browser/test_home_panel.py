# tests/browser/test_home_panel.py -- the Home panel (R3 B) in a real browser. The shell of
# #p-home and its dock button are I1's; here the served page is given a copy of the Things shell
# plus this panel's css and script, and /v1/home/* is answered by the test (shapes:
# src/jarvis/api/camera.py). Pins:
# "Armed" only once confirmed, Disarm asks first, then proves with the passkey (never without), a
# reauth link, hostile text as text, a phone without sideways scroll. 0 JS errors, 0 CSP reports.
from __future__ import annotations

import json
import re
from collections.abc import Iterator
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import pytest
from test_console import DESKTOP, PHONE, Console  # same directory (pytest prepend import)

_pw = pytest.importorskip("playwright.sync_api")
sync_playwright = _pw.sync_playwright

pytestmark = pytest.mark.browser

STATIC = Path(__file__).resolve().parents[2] / "src" / "jarvis" / "api" / "static"
HOSTILE = '<img src=x onerror="window.__pwned=1">Gate'
TARGET = "h_0123abcd:7"
SHELL = (
    '<section class="panel card" id="p-home" data-panel="home" aria-labelledby="t-home" hidden>'
    '<header class="ptitle"><h2 id="t-home">Home</h2>'
    '<div class="pacts"><button class="pbtn" type="button" data-close '
    'aria-label="Close Home panel">x</button></div></header><div class="pbody"></div></section>'
)
DOCK = (
    '<button class="dk ovf" type="button" data-open="home" aria-controls="p-home" '
    'aria-pressed="false"><span>Home</span></button>'
)
SHEET = (
    '<button class="sheet-item" type="button" data-sheet-open="home">'
    "<span><b>Home</b></span></button>"
)


@pytest.fixture(scope="module")
def browser() -> Iterator[Any]:
    with sync_playwright() as p:
        b = p.chromium.launch()
        yield b
        b.close()


def _json(route: Any, status: int, body: Any) -> None:
    route.fulfill(status=status, content_type="application/json", body=json.dumps(body))


def _inject(html: str) -> str:
    html = html.replace(
        '<link rel="stylesheet" href="/static/console-things.css">',
        '<link rel="stylesheet" href="/static/console-things.css">'
        '<link rel="stylesheet" href="/static/console-home-panel.css">',
        1,
    )
    html = html.replace(
        '<section class="panel card" id="p-things"',
        SHELL + '\n<section class="panel card" id="p-things"',
        1,
    )
    html = re.sub(r'(<button class="dk ovf"[^>]*data-open="things")', DOCK + r"\1", html, count=1)
    html = re.sub(
        r'(<button class="sheet-item"[^>]*data-sheet-open="things")', SHEET + r"\1", html, count=1
    )
    return html.replace(
        '<script src="/static/console-things.js" defer></script>',
        '<script src="/static/console-things.js" defer></script>'
        '<script src="/static/console-home-panel.js" defer></script>',
        1,
    )


class FakeHome:
    def __init__(self, page: Any, **over: Any) -> None:
        self.alarm: dict[str, Any] = {
            "available": True,
            "armed": False,
            "mode": "away",
            "confirmed": False,
            "disarm_target": None,
            "dropped_disarmed": 0,
            **over.pop("alarm", {}),
        }
        self.disarm_replies: list[tuple[int, Any]] = over.pop("disarm_replies", [])
        self.calls: list[dict[str, Any]] = []
        self.feed = over.pop("feed", [])
        self.cameras: dict[str, Any] = over.pop(
            "cameras",
            {
                "available": True,
                "cameras": [
                    {
                        "id": "gate",
                        "label": HOSTILE,
                        "alarm_zones": ["gate"],
                        "package_zone": "doorstep",
                        "online": True,
                        "last_event_at": None,
                    }
                ],
                "retention_days": 7,
                "greetings": True,
                "model_note": "",
            },
        )
        page.route("**/", self._page)
        page.route("**/v1/home/**", self._api)
        page.route(
            "**/static/console-home-panel.*", self._static
        )  # I1 adds them to console.py's list
        page.route("**/static/console-deck.js", self._deck)  # I1 adds 'home' to the deck for real

    def _page(self, route: Any) -> None:
        if urlsplit(route.request.url).path != "/":
            return route.fallback()
        resp = route.fetch()
        route.fulfill(response=resp, body=_inject(resp.text()))

    def _static(self, route: Any) -> None:
        name = urlsplit(route.request.url).path.rsplit("/", 1)[-1]
        kind = "text/css" if name.endswith(".css") else "text/javascript"
        route.fulfill(status=200, content_type=kind, body=(STATIC / name).read_text())

    def _deck(self, route: Any) -> None:
        resp = route.fetch()
        js = resp.text().replace("'things', 'notes'", "'things', 'home', 'notes'", 1)
        js = js.replace(
            "      notes: {",
            "      home: { x: col2, y: b.top + 36, w: 400, h: Math.min(availH, 700),"
            " open: false },\n      notes: {",
            1,
        )
        route.fulfill(response=resp, body=js)

    def _api(self, route: Any) -> None:
        r = route.request
        path = urlsplit(r.url).path
        self.calls.append(
            {
                "method": r.method,
                "path": path,
                "query": urlsplit(r.url).query,
                "body": r.post_data_json if r.post_data else None,
            }
        )
        if path == "/v1/home/alarm":
            return _json(route, 200, self.alarm)
        if path == "/v1/home/arm":
            self.alarm = {
                **self.alarm,
                "armed": True,
                "confirmed": False,
                "mode": r.post_data_json["mode"],
                "disarm_target": TARGET,
            }
            return _json(route, 200, self.alarm)
        if path == "/v1/home/disarm":
            status, body = self.disarm_replies.pop(0)
            if status == 200:
                self.alarm = {**self.alarm, "armed": False, "confirmed": False}
                body = self.alarm
            return _json(route, status, body)
        if path == "/v1/home/cameras":
            return _json(route, 200, self.cameras)
        if path == "/v1/home/feed":
            return _json(route, 200, {"items": self.feed})
        if path == "/v1/home/history":
            return _json(route, 200, {"items": [], "more": False, "kept_days": 7, "note": ""})
        return _json(route, 404, {"error": "not_found", "detail": "No."})

    def sent(self, method: str, path: str) -> list[dict[str, Any]]:
        return [c for c in self.calls if c["method"] == method and c["path"] == path]


def _open(
    browser: Any, server_url: str, token: str, viewport: Any = DESKTOP, **over: Any
) -> tuple[Console, FakeHome]:
    c = Console(browser, server_url, token, viewport)
    fake = FakeHome(c.page, **over)
    c.open()
    c.open_panel("home")
    c.page.locator("#homeState:not(:has-text('Loading'))").wait_for()
    return c, fake


def test_armed_is_shown_only_after_the_laptop_confirms(
    browser: Any, server_url: str, token: str
) -> None:
    c, fake = _open(browser, server_url, token)
    try:
        assert "Disarmed" in str(c.page.locator("#homeState").text_content())
        assert c.page.locator("#homeDisarm").is_disabled()
        c.page.locator("#homeArmNight").click()
        c.page.locator("#homeState", has_text="Arming").wait_for()
        assert fake.sent("POST", "/v1/home/arm")[0]["body"] == {"mode": "night"}
        assert "Armed" not in str(c.page.locator("#homeState").text_content())
        assert "laptop" in str(c.page.locator("#homeSub").text_content())
        fake.alarm = {**fake.alarm, "confirmed": True}
        c.page.evaluate("window.JarvisHomePanel.refresh()")
        c.page.locator("#homeState", has_text="Armed (Night)").wait_for()
        assert c.errors == [] and c.csp_violations() == []
    finally:
        c.close()


def test_disarm_asks_then_proves_with_the_passkey_for_this_arm(
    browser: Any, server_url: str, token: str
) -> None:
    c, fake = _open(
        browser,
        server_url,
        token,
        alarm={"armed": True, "confirmed": True, "disarm_target": TARGET},
        disarm_replies=[
            (403, {"error": "passkey_required", "detail": "Use your passkey."}),
            (200, {}),
        ],
    )
    try:
        c.page.evaluate(
            "window.__proved = []; window.JarvisPasskey = {supported: () => true,"
            " prove: (p, t) => { window.__proved.push([p, t]);"
            " return Promise.resolve({id: 'x'}); }}"
        )
        c.page.locator("#homeDisarm").click()
        c.page.locator("#homeDialog[open]").wait_for()
        assert c.page.evaluate("document.activeElement.textContent") == "Keep it on"
        c.page.keyboard.press("Tab")
        assert c.page.evaluate("document.activeElement.textContent") == "Disarm"
        c.page.keyboard.press("Tab")
        assert c.page.evaluate("document.activeElement.textContent") == "Keep it on"
        c.page.keyboard.press("Escape")
        c.page.locator("#homeDialog[open]").wait_for(state="detached")
        assert fake.sent("POST", "/v1/home/disarm") == []  # asking is not disarming
        c.page.locator("#homeDisarm").click()
        c.page.locator("#homeDialog button", has_text="Disarm").click()
        c.page.locator("#homeState", has_text="Disarmed").wait_for()
        posts = fake.sent("POST", "/v1/home/disarm")
        assert posts[0]["body"] == {} and posts[1]["body"] == {"proof": {"id": "x"}}
        assert c.page.evaluate("window.__proved") == [["home_disarm", TARGET]]
        # the one 403 the first (proof-less) try is meant to get is the only thing logged
        assert [e for e in c.errors if "403" not in e] == [] and c.csp_violations() == []
    finally:
        c.close()


def test_without_a_fresh_sign_in_it_offers_the_sign_in_link(
    browser: Any, server_url: str, token: str
) -> None:
    c, fake = _open(
        browser,
        server_url,
        token,
        alarm={"armed": True, "confirmed": True, "disarm_target": TARGET},
        disarm_replies=[(403, {"error": "reauth_required", "detail": "Sign in again."})],
    )
    try:
        c.page.locator("#homeDisarm").click()
        c.page.locator("#homeDialog button", has_text="Disarm").click()
        link = c.page.locator("#homeNote a")
        link.wait_for()
        assert link.get_attribute("href") == "/auth/login?reauth=1"
        assert "Armed" in str(c.page.locator("#homeState").text_content())  # still on
        assert len(fake.sent("POST", "/v1/home/disarm")) == 1
    finally:
        c.close()


def test_hostile_camera_and_feed_text_is_shown_as_text(
    browser: Any, server_url: str, token: str
) -> None:
    feed = [{"at": "2026-11-05T01:00:00+00:00", "words": HOSTILE, "decision": "ring"}]
    c, _ = _open(browser, server_url, token, feed=feed)
    try:
        c.page.locator("#homeFeed li").wait_for()
        text = str(c.page.locator("#home").text_content())
        assert HOSTILE in text and "alerted you" in text
        assert c.page.locator("#p-home img").count() == 0
        assert c.page.evaluate("window.__pwned") is None
        assert "Draw zones only over your own gate and doorstep" in text
        assert c.errors == [] and c.csp_violations() == []
    finally:
        c.close()


def test_not_available_is_one_plain_line(browser: Any, server_url: str, token: str) -> None:
    c, _ = _open(browser, server_url, token, alarm={"available": False, "reason": "Not set up."})
    try:
        assert "Not available" in str(c.page.locator("#homeState").text_content())
        assert c.page.locator("#homeArmAway").is_disabled()
    finally:
        c.close()


def test_the_panel_fits_a_phone(browser: Any, server_url: str, token: str) -> None:
    c, _ = _open(browser, server_url, token, viewport=PHONE)
    try:
        assert c.page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
        assert c.errors == [] and c.csp_violations() == []
    finally:
        c.close()
