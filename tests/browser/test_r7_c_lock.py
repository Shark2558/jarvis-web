# tests/browser/test_r7_c_lock.py -- R7 Part C in a real browser (docs/plans/r7-mobile.md D21):
# the app lock on the page. The 423 readers send `device_locked` to the unlock cover and
# `show_locked` to the show (api(), raw(), the boot's /auth/me, the recheck on return; the show
# page's own reader is checked in tests/test_r7_c_static.py). The cover hides the console,
# survives the recheck's own cover, and unlocks with a device_unlock passkey check bound to the
# session the server names, then reloads. The app's tab marks its session once after sign-in;
# "I'm here" goes only after a real tap or key press, at most once a minute. Privacy -> This
# device: the switch (off takes the passkey). The visual gate on the cover and the row at
# 1440x900 and 390x844, Night and Day.
from __future__ import annotations

import json
from collections.abc import Iterator
from typing import Any

import pytest
from book_mocks import PASSKEY_STUB
from test_console import DESKTOP, PHONE, Console
from test_ui_audit import NAMELESS_JS, WRAP_JS, _assert_clean
from ui_checks import DOM_CHECKS_JS, FINISH_ANIMATIONS_JS

_pw = pytest.importorskip("playwright.sync_api")

pytestmark = pytest.mark.browser

SS = "ss_" + "A1b2C3d4E5f6G7h8I9j0K1l2"
DEVICE_LOCKED = {"error": "device_locked", "detail": "JARVIS is locked on this device."}
SHOW_LOCKED = {"error": "show_locked", "detail": "A guest is watching the build book."}
VIS = (
    "() => { Object.defineProperty(document, 'visibilityState',"
    " {value: '%s', configurable: true}); document.dispatchEvent(new Event('visibilitychange')); }"
)
HIDE, SHOW = VIS % "hidden", VIS % "visible"
APP_SEEN = (
    "() => { const a = document.getElementById('app'); const r = a.getBoundingClientRect();"
    " return !a.hidden && r.width > 0 && getComputedStyle(a).visibility !== 'hidden'; }"
)


@pytest.fixture(scope="module")
def browser() -> Iterator[Any]:
    with _pw.sync_playwright() as p:
        b = p.chromium.launch()
        yield b
        b.close()


def j(route: Any, status: int, body: Any) -> None:
    route.fulfill(status=status, content_type="application/json", body=json.dumps(body),
                  headers={"Cache-Control": "no-store"})  # fmt: skip


class Unlock:
    """POST /v1/session/unlock: first the target, then {unlocked: true} for a proof."""

    def __init__(self) -> None:
        self.bodies: list[Any] = []

    def __call__(self, route: Any) -> None:
        body = route.request.post_data_json
        self.bodies.append(body)
        if body and body.get("proof"):
            return j(route, 200, {"unlocked": True})
        return j(route, 200, {"unlocked": False, "target": SS, "detail": "Use your passkey."})


def _locked_console(browser: Any, url: str, token: str, viewport: Any = DESKTOP) -> Console:
    c = Console(browser, url, token, viewport)
    c.open()
    c.page.route("**/v1/locked-probe", lambda r: j(r, 423, DEVICE_LOCKED))
    got = c.page.evaluate(
        "() => window.JarvisConsole.api('/v1/locked-probe').then(() => 'ok', (e) => e.code)"
    )
    assert got == "device_locked"
    c.page.locator("#r7Lock").wait_for()
    return c


def _clean(c: Console) -> None:
    assert [e for e in c.errors if "423" not in e] == [] and c.csp_violations() == []


# ---- the 423 readers -----------------------------------------------------------------------------
def test_api_device_locked_shows_the_cover_and_never_the_show(
    browser: Any, server_url: str, token: str
) -> None:
    c = _locked_console(browser, server_url, token)
    try:
        assert c.page.url.endswith("/") and not c.page.evaluate(APP_SEEN)
        assert c.page.locator("html").get_attribute("data-locked") == "device"
        cover = c.page.locator("#r7Lock")
        assert "locked on this device" in cover.inner_text()
        assert cover.get_by_role("button", name="Unlock with passkey").is_visible()
        _clean(c)
    finally:
        c.close()


def test_a_modal_dialog_never_stays_above_the_cover(
    browser: Any, server_url: str, token: str
) -> None:
    c = Console(browser, server_url, token, DESKTOP)
    try:
        c.open()
        opened = c.page.evaluate(
            "() => { const ds = [...document.querySelectorAll('dialog')].slice(0, 2);"
            " ds.forEach((d) => d.showModal());"
            " return document.querySelectorAll('dialog[open]').length; }"
        )
        assert opened >= 1
        c.page.route("**/v1/locked-probe", lambda r: j(r, 423, DEVICE_LOCKED))
        c.page.evaluate("() => window.JarvisConsole.api('/v1/locked-probe').catch(() => null)")
        c.page.locator("#r7Lock").wait_for()
        assert c.page.evaluate("() => document.querySelectorAll('dialog[open]').length") == 0
        # nothing above the cover keeps it inert: its button is the element under its own centre
        assert c.page.evaluate(
            "() => { const b = document.getElementById('r7Unlock');"
            " const r = b.getBoundingClientRect();"
            " const at = document.elementFromPoint(r.x + r.width / 2, r.y + r.height / 2);"
            " return b.contains(at); }"
        )
    finally:
        c.close()


def test_raw_device_locked_shows_the_cover_too(browser: Any, server_url: str, token: str) -> None:
    c = Console(browser, server_url, token, DESKTOP)
    try:
        c.open()
        c.page.route("**/v1/locked-probe", lambda r: j(r, 423, DEVICE_LOCKED))
        c.page.evaluate("() => window.JarvisChat.raw('/v1/locked-probe').catch(() => null)")
        c.page.locator("#r7Lock").wait_for()
        assert c.page.url.endswith("/")
    finally:
        c.close()


def test_show_locked_still_goes_to_the_show(browser: Any, server_url: str, token: str) -> None:
    c = Console(browser, server_url, token, DESKTOP)
    try:
        c.open()
        c.page.route("**/v1/locked-probe", lambda r: j(r, 423, SHOW_LOCKED))
        c.page.evaluate("() => window.JarvisConsole.api('/v1/locked-probe').catch(() => null)")
        c.page.wait_for_url("**/book/show", timeout=10000)
        assert c.page.locator("#r7Lock").count() == 0
    finally:
        c.ctx.unroute_all(behavior="ignoreErrors")
        c.close()


def _google_console(
    browser: Any, url: str, token: str, me: dict[str, Any], path: str = "/"
) -> Console:
    """Google mode played here: /console/config and /auth/me answered, the bearer on every /v1."""
    c = Console(browser, url, token, DESKTOP)

    def bearer(route: Any) -> None:
        route.continue_(headers={**route.request.headers, "authorization": f"Bearer {token}"})

    def config(route: Any) -> None:
        got = route.fetch()
        route.fulfill(response=got, json={**got.json(), "auth_mode": "google"})

    def who(route: Any) -> None:
        if me["status"] == 200:
            return j(route, 200, {"email": "owner@example.com"})
        return j(route, 423, DEVICE_LOCKED if me["status"] == 423 else SHOW_LOCKED)

    c.ctx.route("**/v1/**", bearer)
    c.ctx.route("**/console/config", config)
    c.ctx.route("**/auth/me", who)
    c.page.goto(url + path)
    return c


def test_a_locked_boot_shows_the_cover_not_the_show(
    browser: Any, server_url: str, token: str
) -> None:
    c = _google_console(browser, server_url, token, {"status": 423})
    try:
        c.page.locator("#r7Lock").wait_for()
        assert c.page.url.endswith("/") and not c.page.evaluate(APP_SEEN)
        _clean(c)
    finally:
        c.ctx.unroute_all(behavior="ignoreErrors")
        c.close()


def test_the_recheck_on_return_shows_the_cover_and_its_own_cover_never_uncovers_it(
    browser: Any, server_url: str, token: str
) -> None:
    me = {"status": 200}
    c = _google_console(browser, server_url, token, me)
    try:
        c.page.locator("#welcome").wait_for()
        c.page.wait_for_timeout(1700)  # past the recheck's 1.5 s throttle after the boot
        me["status"] = 423
        c.page.evaluate(HIDE)
        c.page.evaluate(SHOW)
        c.page.locator("#r7Lock").wait_for()
        assert c.page.url.endswith("/")
        # /auth/me is never locked: the next return answers 200 and the console's own cover lifts,
        # but the app lock's cover stays and the console stays hidden
        me["status"] = 200
        c.page.wait_for_timeout(1700)
        c.page.evaluate(HIDE)
        c.page.evaluate(SHOW)
        c.page.wait_for_timeout(600)
        assert c.page.locator("#r7Lock").is_visible() and not c.page.evaluate(APP_SEEN)
    finally:
        c.ctx.unroute_all(behavior="ignoreErrors")
        c.close()


# ---- unlocking -----------------------------------------------------------------------------------
def test_unlock_proves_for_this_session_then_reloads(
    browser: Any, server_url: str, token: str
) -> None:
    c = _locked_console(browser, server_url, token)
    unlock = Unlock()
    try:
        c.page.route("**/v1/session/unlock", unlock)
        c.page.evaluate(PASSKEY_STUB)
        with c.page.expect_navigation():
            c.page.locator("#r7Unlock").click()
        c.page.locator("#tokIn, #welcome").first.wait_for()
        assert unlock.bodies[0] == {}
        assert unlock.bodies[1] == {
            "proof": {"purpose": "device_unlock", "target": SS, "stub": True}
        }
    finally:
        c.close()


def test_a_failed_unlock_says_so_and_stays_locked(
    browser: Any, server_url: str, token: str
) -> None:
    c = _locked_console(browser, server_url, token)
    try:
        c.page.route(
            "**/v1/session/unlock",
            lambda r: j(
                r, 403, {"error": "passkey_rejected", "detail": "That passkey check didn't work."}
            ),
        )
        c.page.locator("#r7Unlock").click()
        c.page.locator("#r7LockNote", has_text="didn't work").wait_for()
        assert c.page.locator("#r7Unlock").is_enabled() and not c.page.evaluate(APP_SEEN)
    finally:
        c.close()


# ---- the app's tab: the mark and "I'm here" ---------------------------------------------------
def _spy(c: Console) -> list[str]:
    seen: list[str] = []
    c.page.on(
        "request", lambda r: seen.append(r.method + " " + r.url.split("//", 1)[1].split("/", 1)[1])
    )
    return seen


def test_the_apps_tab_marks_its_session_once_and_says_here_only_after_real_input(
    browser: Any, server_url: str, token: str
) -> None:
    c = Console(browser, server_url, token, DESKTOP)
    seen = _spy(c)
    try:
        c.open("/?source=app")
        c.page.wait_for_timeout(500)
        assert seen.count("POST v1/session/app") == 1
        assert "POST v1/session/here" not in seen
        c.page.evaluate(
            "() => document.dispatchEvent(new PointerEvent('pointerdown', {bubbles: true}))"
        )  # made by a script: not a real tap
        c.page.wait_for_timeout(200)
        assert "POST v1/session/here" not in seen
        c.page.mouse.click(700, 20)
        c.page.wait_for_timeout(300)
        c.page.keyboard.press("Shift")
        c.page.mouse.click(700, 20)
        c.page.wait_for_timeout(300)
        assert seen.count("POST v1/session/here") == 1  # at most once a minute
    finally:
        c.close()


def test_an_ordinary_tab_never_marks_or_says_here(
    browser: Any, server_url: str, token: str
) -> None:
    c = Console(browser, server_url, token, DESKTOP)
    seen = _spy(c)
    try:
        c.open("/")
        c.page.mouse.click(700, 20)
        c.page.wait_for_timeout(400)
        assert not [s for s in seen if "v1/session/" in s]
    finally:
        c.close()


# ---- Privacy -> This device -------------------------------------------------------------------
class Switch:
    def __init__(self) -> None:
        self.state = {"app": True, "on": True, "armed": True, "waiting": False, "minutes": 5}
        self.bodies: list[Any] = []

    def __call__(self, route: Any) -> None:
        if route.request.method == "GET":
            return j(route, 200, self.state)
        body = route.request.post_data_json
        self.bodies.append(body)
        if body.get("on") is False and not body.get("proof"):
            return j(route, 200, {**self.state, "needs": "passkey", "target": SS})
        self.state = {**self.state, "on": body["on"], "armed": body["on"], "waiting": False}
        return j(route, 200, self.state)


def _privacy(
    browser: Any, url: str, token: str, sw: Switch, viewport: Any = DESKTOP, day: bool = False
) -> Console:
    c = Console(browser, url, token, viewport)
    c.page.route("**/v1/session/lock", sw)
    c.open()
    if day:
        c.choose_day()
    c.page.evaluate(PASSKEY_STUB)
    c.open_panel("privacy")
    c.page.locator("#r7LockState").wait_for()
    return c


def test_the_switch_off_takes_the_passkey_and_on_takes_nothing(
    browser: Any, server_url: str, token: str
) -> None:
    sw = Switch()
    c = _privacy(browser, server_url, token, sw)
    try:
        row = c.page.locator("#r7LockCard")
        assert c.page.locator("#r7LockState").inner_text().upper() == "ON"
        assert "can never lock you out" in row.inner_text()
        row.get_by_role("button", name="Turn off").click()
        c.page.locator("#r7LockNote", has_text="The lock is off.").wait_for()
        assert sw.bodies == [
            {"on": False},
            {"on": False, "proof": {"purpose": "device_unlock", "target": SS, "stub": True}},
        ]
        c.page.locator("#r7LockCard").get_by_role("button", name="Turn on").click()
        c.page.locator("#r7LockNote", has_text="The lock is on.").wait_for()
        assert sw.bodies[-1] == {"on": True}
        _clean(c)
    finally:
        c.close()


def test_the_row_says_it_waits_for_a_passkey_from_the_app(
    browser: Any, server_url: str, token: str
) -> None:
    sw = Switch()
    sw.state = {**sw.state, "armed": False, "waiting": True, "app": False}
    c = _privacy(browser, server_url, token, sw)
    try:
        assert c.page.locator("#r7LockState").inner_text().upper() == "WAITS FOR A PASSKEY"
        assert "add a passkey from the phone app" in c.page.locator("#r7LockCard").inner_text()
    finally:
        c.close()


# ---- the visual gate -----------------------------------------------------------------------------
def _audit(c: Console, sel: str, vp: str, what: str) -> None:
    c.page.evaluate(FINISH_ANIMATIONS_JS)
    res = c.page.evaluate(DOM_CHECKS_JS, sel)
    assert not res.get("missing"), f"{what}: {sel} is not in the page"
    _assert_clean(res, c.page.evaluate(NAMELESS_JS, sel), c.page.evaluate(WRAP_JS, sel), vp, what)


@pytest.mark.parametrize("vp", ["desktop", "phone"])
@pytest.mark.parametrize("surface", ["night", "day"])
def test_the_cover_and_the_row_pass_the_visual_gate(
    browser: Any, server_url: str, token: str, vp: str, surface: str
) -> None:
    sw = Switch()
    viewport = DESKTOP if vp == "desktop" else PHONE
    c = _privacy(browser, server_url, token, sw, viewport, day=surface == "day")
    try:
        c.page.locator("#r7LockSet").scroll_into_view_if_needed()
        _audit(c, "#r7LockSet", vp, f"Privacy, This device ({vp}, {surface})")
        c.page.route("**/v1/locked-probe", lambda r: j(r, 423, DEVICE_LOCKED))
        c.page.evaluate("() => window.JarvisConsole.api('/v1/locked-probe').catch(() => null)")
        c.page.locator("#r7Lock").wait_for()
        _audit(c, "#r7Lock", vp, f"unlock cover ({vp}, {surface})")
        assert c.page.evaluate("() => document.documentElement.scrollWidth <= innerWidth")
    finally:
        c.close()
