# tests/browser/test_things.py -- the Things panel ("Where did I keep it?", R2 D11) in a browser.
# /v1/things is answered by the test (page.route; shapes: src/jarvis/api/belongings.py), so these
# pin the console side: search first, quick add with the right body and CSRF header, move, history,
# delete behind a focus-trapped confirm then Undo, "not available", hostile text shown as text, a
# phone without sideways scroll. 0 JS errors and 0 CSP reports throughout.
from __future__ import annotations

import json
from collections.abc import Iterator
from typing import Any
from urllib.parse import urlsplit

import pytest
from test_console import DESKTOP, PHONE, Console  # same directory (pytest prepend import)

_pw = pytest.importorskip("playwright.sync_api")
sync_playwright = _pw.sync_playwright

pytestmark = pytest.mark.browser

HOSTILE = '<img src=x onerror="window.__pwned=1">Passport'
PASSPORT = {
    "id": "t_0123456789ab",
    "name": "Passport",
    "place": "the blue file, top shelf",
    "note": "",
    "holder": None,
    "updated_at": "2026-11-03T08:00:00+00:00",
    "moves": 1,
}
KEYS = {**PASSPORT, "id": "t_aaaaaaaaaaaa", "name": HOSTILE, "place": "hook", "moves": 0}
UNDO = "del_" + "0" * 20


@pytest.fixture(scope="module")
def browser() -> Iterator[Any]:
    with sync_playwright() as p:
        b = p.chromium.launch()
        yield b
        b.close()


def _json(route: Any, status: int, body: Any) -> None:
    route.fulfill(status=status, content_type="application/json", body=json.dumps(body))


class FakeThings:
    def __init__(self, page: Any, things: list[dict[str, Any]], *, available: bool = True) -> None:
        self.things = list(things)
        self.available = available
        self.calls: list[dict[str, Any]] = []
        page.route("**/v1/things**", self._things)
        page.route("**/v1/deleted/*/restore", self._restore)

    def _rec(self, route: Any) -> None:
        r = route.request
        self.calls.append(
            {
                "method": r.method,
                "path": urlsplit(r.url).path,
                "query": urlsplit(r.url).query,
                "body": r.post_data_json if r.post_data else None,
                "csrf": r.headers.get("x-requested-with"),
            }
        )

    def _things(self, route: Any) -> None:
        self._rec(route)
        r, path = route.request, urlsplit(route.request.url).path
        if not self.available:
            return _json(
                route,
                200,
                {
                    "available": False,
                    "reason": "Not available on this server (no encryption key).",
                    "things": [],
                    "holders": [],
                    "total": 0,
                },
            )
        if r.method == "GET" and path.endswith("/history"):
            return _json(
                route,
                200,
                {
                    "thing": PASSPORT,
                    "earlier": [
                        {
                            "place": "the almirah",
                            "from_at": "2026-10-01T00:00:00+00:00",
                            "to_at": "2026-11-03T08:00:00+00:00",
                        }
                    ],
                },
            )
        if r.method == "GET":
            q = urlsplit(r.url).query
            shown = [t for t in self.things if "keys" not in q or t["id"] == KEYS["id"]]
            return _json(
                route,
                200,
                {"available": True, "things": shown, "holders": [], "total": len(self.things)},
            )
        if r.method == "POST":
            body = r.post_data_json
            self.things.append(
                {
                    **PASSPORT,
                    "id": "t_bbbbbbbbbbbb",
                    "name": body["name"],
                    "place": body["place"],
                    "moves": 0,
                }
            )
            return _json(
                route, 201, {"thing": self.things[-1], "previous_place": None, "moved": False}
            )
        if r.method == "PATCH":
            return _json(
                route, 200, {"thing": PASSPORT, "previous_place": "the blue file", "moved": True}
            )
        if r.method == "DELETE":
            self.things = [t for t in self.things if not path.endswith(t["id"])]
            return _json(
                route, 200, {"undo_id": UNDO, "kind": "thing", "title": "Thing: x", "id": "x"}
            )
        return _json(route, 404, {"error": "not_found", "detail": "no"})

    def _restore(self, route: Any) -> None:
        self._rec(route)
        self.things = [PASSPORT, KEYS]
        _json(route, 200, {"status": "restored", "message": "Restored the thing."})

    def sent(self, method: str) -> list[dict[str, Any]]:
        return [c for c in self.calls if c["method"] == method]


def _open(
    browser: Any, server_url: str, token: str, viewport: Any = DESKTOP, **kw: Any
) -> tuple[Console, FakeThings]:
    c = Console(browser, server_url, token, viewport)
    fake = FakeThings(c.page, kw.pop("things", [PASSPORT, KEYS]), **kw)
    c.open()
    c.open_panel("things")
    return c, fake


def test_list_search_first_hostile_text_is_text(browser: Any, server_url: str, token: str) -> None:
    c, fake = _open(browser, server_url, token)
    try:
        c.page.locator("#thingsList .trow").first.wait_for()
        assert (
            c.page.evaluate("window.__pwned") is None and c.page.locator("#things img").count() == 0
        )
        names = c.page.locator("#thingsList .tname").all_text_contents()
        assert names == ["Passport", HOSTILE]
        row = c.page.locator('.trow[data-id="t_0123456789ab"]')
        assert "the blue file, top shelf" in str(row.text_content()) and "updated 3 Nov" in str(
            row.text_content()
        )
        order = c.page.evaluate("[...document.querySelectorAll('#things input')].map(i => i.id)")
        assert order[0] == "thingsSearch"  # the search box comes first
        c.page.locator("#thingsSearch").fill("keys")
        c.page.locator('#thingsList .trow[data-id="t_0123456789ab"]').wait_for(state="detached")
        assert c.page.locator("#thingsList .trow").count() == 1
        assert any("q=keys" in x["query"] for x in fake.sent("GET"))
        assert c.errors == [] and c.csp_violations() == []
    finally:
        c.close()


def test_quick_add_posts_name_and_place_with_the_csrf_header(
    browser: Any, server_url: str, token: str
) -> None:
    c, fake = _open(browser, server_url, token)
    try:
        c.page.locator("#thingsList .trow").first.wait_for()
        c.page.locator("#thingsName").fill("Spare keys")
        c.page.locator("#thingsPlace").fill("kitchen drawer")
        c.page.locator("#thingsSave").click()
        c.page.locator("#thingsList .tname", has_text="Spare keys").wait_for()
        post = fake.sent("POST")[-1]
        assert (
            post["body"] == {"name": "Spare keys", "place": "kitchen drawer"}
            and post["csrf"] == "JARVIS"
        )
        assert c.page.locator("#thingsName").input_value() == ""
        assert c.errors == [] and c.csp_violations() == []
    finally:
        c.close()


def test_move_says_where_it_was_and_history_lists_earlier_places(
    browser: Any, server_url: str, token: str
) -> None:
    c, fake = _open(browser, server_url, token)
    try:
        row = c.page.locator('.trow[data-id="t_0123456789ab"]')
        row.wait_for()
        row.get_by_role("button", name="Move \u201cPassport\u201d").click()
        row.locator(".tmove input").fill("the almirah")
        row.locator(".tmove button[type=submit]").click()
        c.page.locator("#thingsNote", has_text="It was in the blue file.").wait_for()
        patch = fake.sent("PATCH")[-1]
        assert patch["body"] == {"place": "the almirah"} and patch["csrf"] == "JARVIS"
        row = c.page.locator('.trow[data-id="t_0123456789ab"]')
        row.get_by_role("button", name="History of \u201cPassport\u201d").click()
        row.locator(".thist li", has_text="the almirah").wait_for()
        assert c.errors == [] and c.csp_violations() == []
    finally:
        c.close()


def test_delete_asks_first_traps_focus_and_undo_brings_it_back(
    browser: Any, server_url: str, token: str
) -> None:
    c, fake = _open(browser, server_url, token)
    try:
        row = c.page.locator('.trow[data-id="t_0123456789ab"]')
        row.wait_for()
        row.get_by_role("button", name="Delete \u201cPassport\u201d").click()
        c.page.locator("#thingsDialog[open]").wait_for()
        assert c.page.evaluate("document.activeElement.textContent") == "Keep it"
        c.page.keyboard.press("Tab")
        assert c.page.evaluate("document.activeElement.textContent") == "Forget"
        c.page.keyboard.press("Tab")  # wraps inside the dialog
        assert c.page.evaluate("document.activeElement.textContent") == "Keep it"
        c.page.keyboard.press("Escape")
        c.page.locator("#thingsDialog[open]").wait_for(state="detached")
        assert fake.sent("DELETE") == []  # Esc is "Keep it"
        row.get_by_role("button", name="Delete \u201cPassport\u201d").click()
        c.page.locator("#thingsDialogTitle").wait_for()
        c.page.get_by_role("button", name="Forget").click()
        c.page.locator('.trow[data-id="t_0123456789ab"]').wait_for(state="detached")
        c.page.locator("#thingsNote .tundo").click()
        c.page.locator('.trow[data-id="t_0123456789ab"]').wait_for()
        assert fake.sent("DELETE")[-1]["csrf"] == "JARVIS"
        assert fake.sent("POST")[-1]["path"].endswith(f"/v1/deleted/{UNDO}/restore")
        assert c.errors == [] and c.csp_violations() == []
    finally:
        c.close()


def test_without_a_key_the_panel_says_so(browser: Any, server_url: str, token: str) -> None:
    c, _ = _open(browser, server_url, token, available=False)
    try:
        c.page.locator("#thingsState", has_text="no encryption key").wait_for()
        assert c.errors == [] and c.csp_violations() == []
    finally:
        c.close()


def test_the_panel_fits_a_phone(browser: Any, server_url: str, token: str) -> None:
    c = Console(browser, server_url, token, PHONE)
    try:
        FakeThings(c.page, [PASSPORT, KEYS])
        c.open()
        c.page.evaluate("window.JarvisDeck.open('things')")
        c.page.locator("#p-things").wait_for(state="visible")
        c.page.locator("#thingsList .trow").first.wait_for()
        overflow = c.page.evaluate(
            "document.documentElement.scrollWidth - document.documentElement.clientWidth"
        )
        assert overflow <= 0
        box = c.page.locator("#thingsSave").bounding_box()
        assert box is not None and box["height"] >= 44
        assert c.errors == []
    finally:
        c.close()
