# tests/browser/test_r6_seams.py -- R6 I0 seams in a real browser (docs/plans/r6-build-book.md seam
# 9): /book/show boots its shell (console-fx.js + console-permissions.js without the deck DOM, the
# show stubs, the 3D module and the scene modules it imports) with zero console errors and zero
# CSP violations; the deck boots with the Book stubs and opens #p-book on desktop and phone; and a
# 423 show_locked from any API call sends the console to the show.
from __future__ import annotations

import json
from collections.abc import Iterator
from typing import Any

import pytest
from test_console import DESKTOP, PHONE, Console

_pw = pytest.importorskip("playwright.sync_api")

pytestmark = pytest.mark.browser


@pytest.fixture(scope="module")
def browser() -> Iterator[Any]:
    with _pw.sync_playwright() as p:
        b = p.chromium.launch()
        yield b
        b.close()


def test_the_show_shell_boots_without_the_deck(browser: Any, server_url: str, token: str) -> None:
    c = Console(browser, server_url, token, DESKTOP)
    try:
        c.page.goto(server_url + "/book/show")
        c.page.wait_for_load_state("load")
        c.page.wait_for_function("() => !!window.JarvisFX && !!window.JarvisPasskey")
        assert c.page.evaluate("typeof window.JarvisPasskey.prove") == "function"
        assert c.page.evaluate("() => !!document.getElementById('show')")
        assert c.page.evaluate("() => !document.getElementById('dock')")  # no deck here
        loaded = c.page.evaluate(
            "() => import('/static/console-book-3d.js').then((m) => m.loadScenes())"
            ".then((all) => all.map((s) => typeof s.SCENES))"
        )
        assert loaded == ["object", "object", "object"]
        c.page.wait_for_timeout(300)
        assert c.errors == [] and c.csp_violations() == []
    finally:
        c.close()


@pytest.mark.parametrize("viewport", [DESKTOP, PHONE], ids=["desktop", "phone"])
def test_the_deck_boots_with_the_book_stubs_and_opens_the_book_panel(
    browser: Any, server_url: str, token: str, viewport: dict[str, int]
) -> None:
    c = Console(browser, server_url, token, viewport)
    try:
        c.open()
        if viewport == DESKTOP:  # twenty tabs fit the gate's desktop: none of them off-screen
            box = c.page.locator("#dock").bounding_box()
            assert box is not None and box["x"] >= 0 and box["x"] + box["width"] <= DESKTOP["width"]
        c.open_panel("book")
        assert c.page.locator("#p-book h2").text_content() == "Book"
        assert c.errors == [] and c.csp_violations() == []
    finally:
        c.close()


def test_a_423_sends_the_console_to_the_show(browser: Any, server_url: str, token: str) -> None:
    c = Console(browser, server_url, token, DESKTOP)
    try:
        c.open()
        body = json.dumps({"error": "show_locked", "detail": "A build book show is running."})
        c.page.route(
            "**/v1/book",
            lambda r: r.fulfill(status=423, content_type="application/json", body=body),
        )
        code = c.page.evaluate(
            "() => window.JarvisConsole.api('/v1/book').then(() => 'ok', (e) => e.code)"
        )
        assert code == "show_locked"
        c.page.wait_for_url("**/book/show")
        c.page.wait_for_load_state("load")
        assert c.page.evaluate("() => !!document.getElementById('show')")
        assert [e for e in c.errors if "423" not in e] == []
    finally:
        c.close()
