# tests/browser/test_book_lock_ui.py -- R6 D10 (docs/plans/r6-build-book.md): the guest lock as the
# owner's other consoles see it, and the R5.1 visual gate (D11) on the Book panel and the show page.
# A second console tab that gets 423 show_locked goes to the show, shows the lock with Resume, and
# returns to the console once a book_resume passkey (bound to the lock id) lifts it -- also when the
# lock id has to come from the resume answer, and when the lock is lifted from another device.
# The gate: #p-book (status, and the owner's reader open) and /book/show (start, a scene playing,
# questions, the hand-back) at 1440x900 and 390x844, Night and Day, with the gate's own DOM checks.
# ruff: noqa: E501 -- JavaScript strings
from __future__ import annotations

import json
from collections.abc import Iterator
from typing import Any

import pytest
from book_mocks import LOCK_ID, PASSKEY_STUB, SPEECH_STUB, TOKEN, FakeBook, google_mode, j, script
from test_console import DESKTOP, PHONE, Console
from test_ui_audit import NAMELESS_JS, WRAP_JS, _assert_clean
from ui_checks import DOM_CHECKS_JS, FINISH_ANIMATIONS_JS

_pw = pytest.importorskip("playwright.sync_api")

pytestmark = pytest.mark.browser

LOCKED = {"error": "show_locked", "detail": "A build book show is running."}
VIEWPORTS = {"desktop": DESKTOP, "phone": PHONE}
SETTLE_MS = 700


@pytest.fixture(scope="module")
def browser() -> Iterator[Any]:
    with _pw.sync_playwright() as p:
        b = p.chromium.launch()
        yield b
        b.close()


def _clean(c: Console, *expected: int | str) -> None:
    said = [f"status of {code} " if isinstance(code, int) else code for code in expected]
    errors = [e for e in c.errors if not any(s in e for s in said)]
    assert errors == [] and c.csp_violations() == []


def _locked_tab(browser: Any, url: str, token: str) -> tuple[Console, FakeBook]:
    """A console tab of the owner while a guest show holds the lock: its next API call gets 423."""
    c = Console(browser, url, token, DESKTOP)
    fake = FakeBook(c.page)
    fake.lock = {"on": True, "id": LOCK_ID}
    c.open()
    google_mode(
        c.page
    )  # the console is up (token mode); the show it goes to sees a Google-mode server
    c.page.route("**/v1/locked-probe", lambda r: j(r, 423, LOCKED))
    code = c.page.evaluate(
        "() => window.JarvisConsole.api('/v1/locked-probe').then(() => 'ok', (e) => e.code)"
    )
    assert code == "show_locked"
    c.page.wait_for_url("**/book/show")
    c.page.locator("#shDone").wait_for(state="visible")
    return c, fake


def test_a_second_console_tab_goes_to_the_show_and_back_after_resume(
    browser: Any, server_url: str, token: str
) -> None:
    c, fake = _locked_tab(browser, server_url, token)
    try:
        done = c.page.locator("#shDone")
        assert "locked" in done.inner_text().lower()
        c.page.unroute(
            "**/console/config"
        )  # back in the console it boots with the test token again
        c.page.evaluate(PASSKEY_STUB)
        done.get_by_role("button", name="Resume with my passkey").click()
        c.page.wait_for_url(server_url + "/")
        c.page.locator("#welcome").wait_for()
        (resumed,) = fake.to("POST", "/v1/book/resume")
        assert resumed["body"] == {
            "proof": {"purpose": "book_resume", "target": LOCK_ID, "stub": True}
        }
        _clean(c, 423)
    finally:
        c.close()


def test_a_dropped_connection_at_resume_is_said_calmly(
    browser: Any, server_url: str, token: str
) -> None:
    c, fake = _locked_tab(browser, server_url, token)
    fake.resume_answers = ["abort"]
    try:
        done = c.page.locator("#shDone")
        c.page.evaluate(PASSKEY_STUB)
        done.get_by_role("button", name="Resume with my passkey").click()
        c.page.locator("#shDoneFine", has_text="Can\u2019t reach JARVIS").wait_for()
        assert "Failed to fetch" not in done.inner_text()
        assert done.get_by_role("button", name="Resume with my passkey").is_enabled()
        _clean(c, 423, "net::ERR_FAILED")
    finally:
        c.close()


def test_the_lock_id_can_come_from_the_resume_answer(
    browser: Any, server_url: str, token: str
) -> None:
    c = Console(browser, server_url, token, DESKTOP)
    fake = FakeBook(c.page)
    fake.lock = None  # no lock route on this server: the page asks /auth/me and the resume answer
    fake.resume_answers = [
        (403, {"error": "passkey_required", "detail": "Use your passkey.", "lock_id": LOCK_ID}),
        (200, {"resumed": True}),
    ]
    c.page.route("**/auth/me", lambda r: j(r, 423, LOCKED))
    google_mode(c.page)
    try:
        c.page.goto(server_url + "/book/show")
        done = c.page.locator("#shDone")
        done.wait_for(state="visible")
        c.page.evaluate(PASSKEY_STUB)
        c.page.unroute("**/auth/me")
        done.get_by_role("button", name="Resume with my passkey").click()
        c.page.wait_for_url(server_url + "/")
        bodies = [x["body"] for x in fake.to("POST", "/v1/book/resume")]
        assert bodies == [
            {},
            {"proof": {"purpose": "book_resume", "target": LOCK_ID, "stub": True}},
        ]
        _clean(c, 401, 403, 404, 423)  # the lock poll may reach the real /auth/me (token mode: 401)
    finally:
        c.close()


def test_a_lock_lifted_elsewhere_sends_this_tab_back_to_the_console(
    browser: Any, server_url: str, token: str
) -> None:
    c, fake = _locked_tab(browser, server_url, token)
    try:
        c.page.unroute(
            "**/console/config"
        )  # back in the console it boots with the test token again
        fake.lock = {"on": False}  # the owner resumed on his phone
        c.page.wait_for_url(server_url + "/", timeout=15000)
        c.page.locator("#welcome").wait_for()
        assert fake.to("POST", "/v1/book/resume") == []
        _clean(c, 423)
    finally:
        c.close()


# ---- the visual gate (R5.1 D11) on the Book panel and the show ---------------------------------------
def _audit(c: Console, sel: str, vp: str, what: str) -> None:
    c.page.mouse.move(0, 0)
    c.page.wait_for_timeout(SETTLE_MS)
    c.page.evaluate(FINISH_ANIMATIONS_JS)
    res = c.page.evaluate(DOM_CHECKS_JS, sel)
    assert not res.get("missing"), f"{what}: {sel} is not in the page"
    _assert_clean(res, c.page.evaluate(NAMELESS_JS, sel), c.page.evaluate(WRAP_JS, sel), vp, what)


def _surface(c: Console, surface: str) -> None:
    c.page.add_init_script(
        f"try {{ localStorage.setItem('jarvis_surface', '{surface}'); }} catch (_) {{}}"
    )


@pytest.mark.parametrize("surface", ["night", "day"])
@pytest.mark.parametrize("vp", list(VIEWPORTS))
def test_the_book_panel_passes_the_visual_gate(
    browser: Any, server_url: str, token: str, vp: str, surface: str
) -> None:
    c = Console(browser, server_url, token, VIEWPORTS[vp])
    _surface(c, surface)
    fake = FakeBook(c.page)
    fake.status["lock"] = {"on": False}
    try:
        c.open()
        assert c.page.locator("html").get_attribute("data-surface") == surface
        c.page.evaluate(PASSKEY_STUB)
        c.open_panel("book")
        c.page.locator("#p-book .bk-release").wait_for()
        c.page.locator("#p-book .bk-set .dsc").click()
        c.page.locator("#bkCreator").wait_for()
        _audit(c, "#p-book", vp, f"book panel {vp} {surface}")
        c.page.get_by_role("button", name="Open for me").click()
        c.page.locator("#p-book .bk-reader .dsc").first.wait_for()
        for name in ("Architecture", "Libraries", "Costs"):
            c.page.locator("#p-book .bk-reader .dsc", has_text=name).click()
        _audit(c, "#p-book", vp, f"book panel reader {vp} {surface}")
        _clean(c)
    finally:
        c.close()


@pytest.mark.parametrize("surface", ["night", "day"])
@pytest.mark.parametrize("vp", list(VIEWPORTS))
def test_the_show_passes_the_visual_gate(
    browser: Any, server_url: str, token: str, vp: str, surface: str
) -> None:
    c = Console(browser, server_url, token, VIEWPORTS[vp])
    _surface(c, surface)
    c.page.add_init_script(SPEECH_STUB)
    c.page.add_init_script(
        "if (!sessionStorage.getItem('__seeded')) { sessionStorage.setItem('__seeded', '1');"
        f" sessionStorage.setItem('jarvis_book_token', '{TOKEN}'); }}"
    )
    fake = FakeBook(c.page)
    fake.script_answer = (200, script("guest"))
    fake.lock = {"on": True, "id": LOCK_ID}
    google_mode(c.page)
    try:
        c.page.goto(server_url + "/book/show")
        c.page.locator("#shBegin").wait_for()
        assert c.page.locator("html").get_attribute("data-surface") == surface
        _audit(c, "#show", vp, f"show start {vp} {surface}")
        c.page.locator("#shBegin").click()
        c.page.wait_for_function("() => window.JarvisBookShow.state().playing")
        for _ in range(2):  # the eight layers: plates and labels on screen
            c.page.keyboard.press("PageDown")
        c.page.keyboard.press("Space")
        c.page.wait_for_function("() => window.JarvisBookShow.state().scene === 3")
        _audit(c, "#show", vp, f"show scene {vp} {surface}")
        c.page.locator("#shChapters").click()
        c.page.locator("#shChapterList button", has_text="Questions").click()
        c.page.locator("#shTalk").wait_for(state="visible")
        c.page.locator("#shQ").fill("How do you read e-mail?")
        c.page.locator("#shSend").click()
        c.page.locator("#shThread .row.jarvis .bubble").first.wait_for()
        _audit(c, "#show", vp, f"show questions {vp} {surface}")
        c.page.locator("#shFinish").click()
        c.page.locator("#shDone").wait_for(state="visible", timeout=30000)
        _audit(c, "#show", vp, f"show hand-back {vp} {surface}")
        _clean(c)
    finally:
        c.close()


def test_the_show_page_answers_with_the_console_csp(server_url: str) -> None:
    import urllib.request

    with urllib.request.urlopen(server_url + "/book/show", timeout=5) as r:
        csp = r.headers["Content-Security-Policy"]
        body = r.read().decode()
    with urllib.request.urlopen(server_url + "/", timeout=5) as r:
        assert r.headers["Content-Security-Policy"] == csp
    assert json.dumps(csp) and 'id="show"' in body
