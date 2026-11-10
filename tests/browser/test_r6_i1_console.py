# tests/browser/test_r6_i1_console.py -- R6 I1 in the console (console.js, a wiring file): a console
# tab that is already open when a guest show starts goes to the show without anyone using it: at
# once on the BroadcastChannel('jarvis-book') post a guest open makes in another tab of this
# browser, or when it comes back into focus (review D-sec M2, D10); and a build book session that
# ended (401 session_gone on a book route) never shows the sign-in gate (INTEGRATION-D).
# SEC-2 (integrated review): the re-check fails closed. A tab sent to the background is covered by
# the gate (the app hidden) until /auth/me answers 200; offline, a 503 or an error keeps the cover
# with "Can't reach JARVIS" and Try again; nothing the console rendered shows while it asks.
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


def _google_console(browser: Any, server_url: str, token: str) -> tuple[Console, dict[str, Any]]:
    c = Console(browser, server_url, token, DESKTOP)
    me: dict[str, Any] = {"status": 200, "held": []}

    def bearer(route: Any) -> None:
        route.continue_(headers={**route.request.headers, "authorization": f"Bearer {token}"})

    def config(route: Any) -> None:
        got = route.fetch()
        route.fulfill(response=got, json={**got.json(), "auth_mode": "google"})

    def who(route: Any) -> None:
        if me["status"] == 0:
            route.abort()  # the network is off
        elif me["status"] == -1:
            me["held"].append(route)  # still on its way: the test answers it later
        elif me["status"] == 200:
            route.fulfill(status=200, json={"email": "owner@example.com"})
        elif me["status"] == 503:
            route.fulfill(status=503, json={"error": "show_lock_unreadable", "detail": "?"})
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


VIS = (
    "() => { Object.defineProperty(document, 'visibilityState',"
    " {value: '%s', configurable: true}); document.dispatchEvent(new Event('visibilitychange')); }"
)
HIDE, SHOW = VIS % "hidden", VIS % "visible"
SEEN = (
    "() => { const app = document.getElementById('app'); const r = app.getBoundingClientRect();"
    " return !app.hidden && r.width > 0 && getComputedStyle(app).display !== 'none'; }"
)


@pytest.mark.parametrize("status", [0, 503])
def test_a_tab_that_cannot_confirm_unlocked_stays_covered(
    browser: Any, server_url: str, token: str, status: int
) -> None:
    c, me = _google_console(browser, server_url, token)
    try:
        c.page.locator("#welcome h1").wait_for()
        assert c.page.evaluate(SEEN)
        me["status"] = status  # the guest turned the Wi-Fi off / the lock can't be read
        c.page.evaluate(HIDE)
        assert not c.page.evaluate(SEEN)  # covered the moment it went to the background
        c.page.evaluate(SHOW)
        gate = c.page.locator("#gate.show")
        gate.get_by_text("Can\u2019t reach JARVIS").wait_for()
        assert not c.page.evaluate(SEEN)  # nothing rendered shows while it can't tell
        c.page.wait_for_timeout(1700)
        c.page.evaluate("() => window.dispatchEvent(new Event('focus'))")
        c.page.wait_for_timeout(300)
        assert not c.page.evaluate(SEEN) and c.page.url.endswith("/")
        me["status"] = 200  # back online and unlocked
        gate.get_by_role("button", name="Try again").click()
        c.page.locator("#gate.show").wait_for(state="detached")
        assert c.page.evaluate(SEEN)
    finally:
        _close(c)


def test_a_covered_tab_that_meets_the_lock_replaces_itself_with_the_show(
    browser: Any, server_url: str, token: str
) -> None:
    c, me = _google_console(browser, server_url, token)
    try:
        c.page.locator("#welcome h1").wait_for()
        before = c.page.evaluate("() => history.length")
        c.page.evaluate(HIDE)
        me["status"] = 423
        c.page.evaluate(SHOW)
        _on_the_show(c)
        # replace, not assign: the console page is no Back entry to return to
        assert c.page.evaluate("() => history.length") == before
    finally:
        _close(c)


def test_an_unlocked_tab_comes_back_uncovered(browser: Any, server_url: str, token: str) -> None:
    c, _ = _google_console(browser, server_url, token)
    try:
        c.page.locator("#welcome h1").wait_for()
        c.page.evaluate(HIDE)
        assert not c.page.evaluate(SEEN)
        c.page.evaluate(SHOW)
        c.page.wait_for_function(SEEN)
        assert not c.page.locator("#gate.show").count()
    finally:
        _close(c)


# ---- code re-review #3: the cover hides every pop-up outside #app too, until a 200 ---------------
POP_UP = (
    "() => { const d = document.getElementById('sysCheck'); return !!d && d.open"
    " && d.getBoundingClientRect().width > 0 && getComputedStyle(d).display !== 'none'; }"
)
LAYERS = (  # what is drawn at the body's top level besides the gate and the aria-hidden decor
    "() => [...document.body.children].filter((el) => el.id !== 'gate' && el.localName !== 'script'"
    " && el.getAttribute('aria-hidden') !== 'true' && el.getBoundingClientRect().width > 0"
    " && getComputedStyle(el).display !== 'none').map((el) => el.id || el.className)"
)
OVERLAY = (  # a confirm backdrop as console-vault.js appends one, outside #app
    "() => { const b = document.createElement('div'); b.className = 'vd-back'; b.id = 'probeBack';"
    " b.textContent = 'Delete the vault item?'; document.body.append(b); }"
)


def test_a_covered_tab_hides_its_pop_ups_and_brings_them_back_only_when_unlocked(
    browser: Any, server_url: str, token: str
) -> None:
    c, me = _google_console(browser, server_url, token)
    try:
        c.page.locator("#welcome h1").wait_for()
        c.page.evaluate("window.JarvisSystemsCheck.open({closeAfterMs: 600000})")
        c.page.wait_for_function(POP_UP)
        c.page.evaluate(OVERLAY)
        c.page.evaluate(
            "() => document.getElementById('sysCheck')"
            ".addEventListener('close', () => { window.__sysClosed = true; })"
        )
        me["status"] = 0  # the guest turned the Wi-Fi off and switched to this tab
        c.page.evaluate(HIDE)
        assert not c.page.evaluate(POP_UP) and c.page.evaluate(LAYERS) == []
        c.page.evaluate(SHOW)
        gate = c.page.locator("#gate.show")
        gate.get_by_text("Can’t reach JARVIS").wait_for()
        assert not c.page.evaluate(POP_UP)  # Vitals, spend and the briefing stay out of sight
        assert c.page.evaluate(LAYERS) == []
        me["status"] = 200
        gate.get_by_role("button", name="Try again").click(timeout=5000)  # the gate is not inert
        c.page.locator("#gate.show").wait_for(state="detached")
        c.page.wait_for_function(POP_UP)  # back as it was: still open, never closed for its owner
        assert c.page.evaluate("() => window.__sysClosed === undefined")
        assert "probeBack" in c.page.evaluate(LAYERS) and c.page.evaluate(SEEN)
    finally:
        _close(c)


# ---- security re-review #6: a guest open hops at once; an old answer never lifts a newer cover --
def test_a_guest_open_in_another_tab_hops_this_tab_at_once(
    browser: Any, server_url: str, token: str
) -> None:
    """The channel's message comes only from this origin after a guest open: the tab replaces
    itself with the show at once, even while /auth/me would still say 200 (a raced answer)."""
    c, _ = _google_console(browser, server_url, token)
    try:
        c.page.locator("#welcome h1").wait_for()
        before = c.page.evaluate("() => history.length")
        other = c.ctx.new_page()
        other.goto(server_url + "/health")
        other.evaluate(
            "() => { const ch = new BroadcastChannel('jarvis-book');"
            " ch.postMessage({ type: 'guest-show' }); ch.close(); }"
        )
        c.page.wait_for_url("**/book/show", timeout=10000)
        assert c.page.evaluate("() => history.length") == before  # replaced, no Back entry
    finally:
        _close(c)


def test_an_answer_older_than_the_latest_cover_decides_nothing(
    browser: Any, server_url: str, token: str
) -> None:
    c, me = _google_console(browser, server_url, token)
    try:
        c.page.locator("#welcome h1").wait_for()
        me["status"] = -1  # check A goes out and is held on its way
        c.page.evaluate(HIDE)
        c.page.evaluate(SHOW)
        for _ in range(50):  # until check A reaches the route
            if me["held"]:
                break
            c.page.wait_for_timeout(100)
        assert len(me["held"]) == 1
        me["status"] = 0  # the guest turns the network off; the tab is covered and asks again
        c.page.evaluate(HIDE)
        c.page.evaluate(SHOW)
        gate = c.page.locator("#gate.show")
        gate.get_by_text("Can\u2019t reach JARVIS").wait_for()
        with c.page.expect_response("**/auth/me"):
            me["held"][0].fulfill(status=200, json={"email": "owner@example.com"})  # A, late
        c.page.wait_for_timeout(300)
        assert not c.page.evaluate(SEEN)  # A was sent before the latest cover: it lifts nothing
        assert gate.get_by_text("Can\u2019t reach JARVIS").is_visible()
    finally:
        _close(c)
