# tests/browser/test_r14_d_console.py -- R14 D13 (3) in a real browser: a lock that can't be read
# never leaves the console on screen. Before R14 the console's transport read 423 only (console.js
# api() and raw()), so a 503 from a lock re-check left the page showing. Now:
#   503 lock_unreadable (R7's app lock)       -> the app's unlock cover (its unlock reads the lock
#                                                again before anything opens), the console hidden;
#   503 show_lock_unreadable (R6's show lock) -> the gate's "Can't reach JARVIS" cover with Try
#                                                again, which uncovers only on a 200 from /auth/me;
#   any other 503                             -> an error for its caller, as before (no cover).
# The browser server runs in token mode; Google mode is played (as test_r6_i1_console.py does) by
# answering /console/config and /auth/me here and adding the bearer to every /v1 call.
from __future__ import annotations

import json
from collections.abc import Iterator
from typing import Any

import pytest
from test_console import DESKTOP, Console

_pw = pytest.importorskip("playwright.sync_api")

pytestmark = pytest.mark.browser

APP_SEEN = (
    "() => { const a = document.getElementById('app'); const r = a.getBoundingClientRect();"
    " return !a.hidden && r.width > 0 && getComputedStyle(a).visibility !== 'hidden'; }"
)
CALL = "(p) => window.JarvisConsole.api(p).then(() => 'ok', (e) => (e.status || 0) + ' ' + e.code)"
RAW = "(p) => window.JarvisChat.raw(p).then((r) => 'answered ' + r.status, () => 'threw')"


@pytest.fixture(scope="module")
def browser() -> Iterator[Any]:
    with _pw.sync_playwright() as p:
        b = p.chromium.launch()
        yield b
        b.close()


def _j(route: Any, status: int, body: Any) -> None:
    route.fulfill(status=status, content_type="application/json", body=json.dumps(body))


def _unreadable(code: str) -> Any:
    return lambda route: _j(route, 503, {"error": code, "detail": "?"})


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
            _j(route, 200, {"email": "owner@example.com"})
        else:
            _j(route, me["status"], {"error": "show_lock_unreadable", "detail": "?"})

    c.ctx.route("**/v1/**", bearer)
    c.ctx.route("**/app/status", bearer)
    c.ctx.route("**/console/config", config)
    c.ctx.route("**/auth/me", who)
    c.page.goto(server_url + "/")
    c.page.locator("#welcome").wait_for()
    return c, me


def _close(c: Console) -> None:
    c.ctx.unroute_all(behavior="ignoreErrors")
    c.close()


def test_an_unreadable_app_lock_brings_the_unlock_cover(
    browser: Any, server_url: str, token: str
) -> None:
    c = Console(browser, server_url, token, DESKTOP)
    try:
        c.open()
        assert c.page.evaluate(APP_SEEN)
        c.page.route("**/v1/lock-probe", _unreadable("lock_unreadable"))
        assert c.page.evaluate(CALL, "/v1/lock-probe") == "503 lock_unreadable"
        c.page.locator("#r7Lock").wait_for()
        assert c.page.evaluate("() => document.documentElement.dataset.locked") == "device"
        assert not c.page.evaluate(APP_SEEN)
    finally:
        c.close()


def test_the_bytes_transport_covers_the_page_too(browser: Any, server_url: str, token: str) -> None:
    c = Console(browser, server_url, token, DESKTOP)
    try:
        c.open()
        c.page.route("**/v1/lock-probe", _unreadable("lock_unreadable"))
        assert c.page.evaluate(RAW, "/v1/lock-probe") == "answered 503"
        c.page.locator("#r7Lock").wait_for()
        assert not c.page.evaluate(APP_SEEN)
    finally:
        c.close()


def test_an_unreadable_show_lock_covers_until_the_check_says_200(
    browser: Any, server_url: str, token: str
) -> None:
    c, me = _google_console(browser, server_url, token)
    try:
        assert c.page.evaluate(APP_SEEN)
        c.page.route("**/v1/show-probe", _unreadable("show_lock_unreadable"))
        me["status"] = 503  # the lock still can't be read when the gate asks again
        assert c.page.evaluate(CALL, "/v1/show-probe") == "503 show_lock_unreadable"
        gate = c.page.locator("#gate.show")
        gate.get_by_text("Can’t reach JARVIS").wait_for()
        assert not c.page.evaluate(APP_SEEN)
        gate.get_by_role("button", name="Try again").click()
        c.page.wait_for_timeout(300)
        assert not c.page.evaluate(APP_SEEN)  # still covered: /auth/me answered 503
        me["status"] = 200
        gate.get_by_role("button", name="Try again").click()
        c.page.locator("#gate.show").wait_for(state="detached")
        assert c.page.evaluate(APP_SEEN)
    finally:
        _close(c)


def test_another_503_is_only_an_error_for_its_caller(
    browser: Any, server_url: str, token: str
) -> None:
    c = Console(browser, server_url, token, DESKTOP)
    try:
        c.open()
        c.page.route("**/v1/other-probe", _unreadable("notes_off"))
        assert c.page.evaluate(CALL, "/v1/other-probe") == "503 notes_off"
        c.page.wait_for_timeout(200)
        assert c.page.evaluate(APP_SEEN)
        assert c.page.locator("#r7Lock").count() == 0
    finally:
        c.close()
