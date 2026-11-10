# tests/browser/test_r6_i1_console.py -- R6 I1 in the console (console.js, a wiring file): a console
# tab that is already open when a guest show starts goes to the show without anyone using it: at
# once on the BroadcastChannel('jarvis-book') post a guest open makes in another tab of this
# browser, or when it comes back into focus (review D-sec M2, D10); and a build book session that
# ended (401 session_gone on a book route) never shows the sign-in gate (INTEGRATION-D).
# The browser server runs in token mode; Google mode is played by answering /console/config and
# /auth/me here and adding the bearer to every /v1 call, so the real routes still answer.
from __future__ import annotations

import json
from collections.abc import Iterator
from typing import Any

import pytest
from test_console import Console

sync_playwright = pytest.importorskip("playwright.sync_api").sync_playwright

pytestmark = pytest.mark.browser

DESKTOP = {"width": 1440, "height": 900}
LOCKED = json.dumps({"error": "show_locked", "detail": "A guest is watching the build book."})


@pytest.fixture(scope="module")
def browser() -> Iterator[Any]:
    with sync_playwright() as p:
        b = p.chromium.launch()
        yield b
        b.close()


def _google_console(browser: Any, server_url: str, token: str) -> tuple[Console, dict[str, int]]:
    c = Console(browser, server_url, token, DESKTOP)
    me = {"status": 200}

    def bearer(route: Any) -> None:
        route.continue_(headers={**route.request.headers, "authorization": f"Bearer {token}"})

    def config(route: Any) -> None:
        got = route.fetch()
        route.fulfill(response=got, json={**got.json(), "auth_mode": "google"})

    def who(route: Any) -> None:
        if me["status"] == 200:
            route.fulfill(status=200, json={"email": "owner@example.com"})
        else:
            route.fulfill(status=423, content_type="application/json", body=LOCKED)

    c.ctx.route("**/v1/**", bearer)  # the later routes win where they overlap
    c.ctx.route("**/console/config", config)
    c.ctx.route("**/auth/me", who)
    c.page.goto(server_url + "/")
    c.page.locator("#welcome").wait_for()
    return c, me


def _close(c: Console) -> None:
    """Drop the routes first: a /console/config fetch still in flight when the page hopped must
    not surface in the next test's browser call ("Response has been disposed")."""
    c.ctx.unroute_all(behavior="ignoreErrors")
    c.close()


def _on_the_show(c: Console) -> None:
    c.page.wait_for_url("**/book/show", timeout=10000)
    c.page.wait_for_load_state("load")
    assert c.page.evaluate("() => !!document.getElementById('show')")
    assert [e for e in c.errors if "423" not in e] == []


def test_an_open_console_tab_goes_to_the_show_when_a_guest_show_starts(
    browser: Any, server_url: str, token: str
) -> None:
    c, me = _google_console(browser, server_url, token)
    try:
        assert c.page.url.endswith("/")
        me["status"] = 423  # a guest open in another tab: the lock is on
        other = c.ctx.new_page()
        other.goto(server_url + "/health")  # same origin: the channel reaches the console tab
        other.evaluate(
            "() => { const ch = new BroadcastChannel('jarvis-book');"
            " ch.postMessage({ type: 'guest-show' }); ch.close(); }"
        )
        _on_the_show(c)
    finally:
        _close(c)


def test_an_open_console_tab_asks_again_when_it_comes_back_into_focus(
    browser: Any, server_url: str, token: str
) -> None:
    c, me = _google_console(browser, server_url, token)
    try:
        c.page.wait_for_timeout(1700)  # past the re-check's 1.5 s throttle after the boot
        me["status"] = 423  # the lock came on while this tab was in the background
        assert c.page.url.endswith("/")
        c.page.evaluate("() => window.dispatchEvent(new Event('focus'))")
        _on_the_show(c)
    finally:
        _close(c)


def test_a_book_session_that_ended_never_shows_the_sign_in_gate(
    browser: Any, server_url: str, token: str
) -> None:
    c = Console(browser, server_url, token, DESKTOP)
    try:
        c.open()
        body = json.dumps({"error": "session_gone", "detail": "Open the build book again."})
        c.page.route(
            "**/v1/book/sections",
            lambda r: r.fulfill(status=401, content_type="application/json", body=body),
        )
        got = c.page.evaluate(
            "() => window.JarvisConsole.api('/v1/book/sections').then(() => 'ok',"
            " (e) => [e.status, e.code || ''])"
        )
        assert got == [401, "session_gone"]
        assert not c.page.locator("#gate.show").count()
        c.page.route(
            "**/v1/book/settings",
            lambda r: r.fulfill(status=401, content_type="application/json", body="{}"),
        )
        got = c.page.evaluate(
            "() => window.JarvisConsole.api('/v1/book/settings').then(() => 'ok', (e) => e.status)"
        )
        assert got == 401 and c.page.locator("#gate.show").count() == 1  # any other 401: the gate
    finally:
        c.close()
