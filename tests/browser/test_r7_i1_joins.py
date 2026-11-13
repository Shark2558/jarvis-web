# tests/browser/test_r7_i1_joins.py -- R7 I1: the console's joins between the parts, with every
# part's REAL module loaded (Parts A, B and D each tested these against a stand-in):
#   - A's do=look opens B's Camera panel on its Look tab (`JarvisMobile.parts.panel.choose`) and
#     never starts a camera (`getUserMedia` stays at 0 and no camera is live);
#   - A's do=sos opens D's real SOS sheet (`JarvisMobile.parts.sos.open({via: 'launch'})`), which
#     still needs the hold: nothing is sent;
#   - the share tray's "Look at it here" hands the picture to B's panel (`parts.panel.look(file)`):
#     it is looked at on this device and no request carries it.
from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest
from test_console import DESKTOP, PHONE
from test_r7_a_links import Launch, _until  # polls: the CSP refuses eval
from test_r7_a_share import Tray, _two_pictures

_pw = pytest.importorskip("playwright.sync_api")
sync_playwright = _pw.sync_playwright
pytestmark = pytest.mark.browser


@pytest.fixture(scope="module")
def browser() -> Iterator[Any]:
    with sync_playwright() as p:
        b = p.chromium.launch()
        yield b
        b.close()


def _sign_in(c: Any) -> None:
    c.page.locator("#tokIn").fill(c.token)
    c.page.locator("#tokBtn").click()


@pytest.mark.parametrize("size", ["desktop", "phone"])
def test_do_look_opens_the_look_tab_of_the_real_panel_and_never_a_camera(
    browser: Any, server_url: str, token: str, size: str
) -> None:
    c = Launch(browser, server_url, token, DESKTOP if size == "desktop" else PHONE)
    try:
        c.page.goto(server_url + "/?source=app&do=look")
        _until(c, "!!(window.JarvisMobile && JarvisMobile.parts.panel && window.JarvisCamera)")
        c.page.evaluate("JarvisMobile.parts.panel.choose('results')")  # he left it on Results
        assert c.page.evaluate("JarvisMobile.parts.panel.tab()") == "results"
        _sign_in(c)
        c.page.locator("#p-camera").wait_for(state="visible", timeout=10_000)
        _until(c, "JarvisMobile.parts.panel.tab() === 'look'")
        c.page.wait_for_timeout(800)
        assert c.mic() == {"gum": 0, "rec": 0}  # no camera and no microphone was asked for
        assert c.page.evaluate("JarvisCamera.live()") is False
        assert c.page.evaluate("location.search") == "?source=app"  # C's lock reads it
        assert c.errors == [] and c.csp_violations() == []
    finally:
        c.close()


def test_do_sos_opens_part_ds_real_sheet_and_sends_nothing(
    browser: Any, server_url: str, token: str
) -> None:
    c = Launch(browser, server_url, token, PHONE)
    try:
        c.page.goto(server_url + "/?source=app&do=sos")
        _until(c, "!!(window.JarvisMobile && JarvisMobile.parts.sos)")
        _sign_in(c)
        _until(c, "JarvisMobile.parts.sos.isOpen() === true")
        c.page.wait_for_timeout(1500)  # longer than any countdown could start by itself
        assert not [u for u in c.requests if "/v1/sos/send" in u]  # the hold is still his
        assert c.page.evaluate("JarvisMobile.parts.sos.isOpen()") is True
        assert c.mic() == {"gum": 0, "rec": 0}
        assert c.errors == [] and c.csp_violations() == []
    finally:
        c.close()


def test_the_trays_look_at_it_here_is_looked_at_by_the_real_panel_on_this_device(
    browser: Any, server_url: str, token: str
) -> None:
    t = Tray(browser, server_url, token, DESKTOP)
    try:
        t.at_health()
        t.share({"files": [_two_pictures()["files"][1]]})  # receipt.png, drawn in the page
        t.open()
        t.page.locator("#shareTray[open]").wait_for(timeout=15_000)
        before = len(t.requests)
        t.page.get_by_role("button", name="Look at it here").click()
        t.page.locator("#p-camera").wait_for(state="visible", timeout=10_000)
        t.page.locator("#p-camera canvas.cam-view").wait_for(timeout=10_000)
        assert t.page.evaluate("JarvisMobile.parts.panel.tab()") == "look"
        assert t.page.locator("#shareTray[open]").count() == 0
        assert t.sent(before) == [] and t.uploads == []  # the picture never left this device
        posts = [u for m, u in t.requests[before:] if m == "POST"]
        assert not [u for u in posts if "/v1/vision" in u]  # nothing kept without a press
        assert t.page.evaluate("JarvisCamera.live()") is False
        assert t.errors == [] and t.csp_violations() == []
    finally:
        t.close()


def test_a_file_that_is_not_a_picture_is_refused_by_the_panel_in_plain_words(
    browser: Any, server_url: str, token: str
) -> None:
    t = Tray(browser, server_url, token, DESKTOP)
    try:
        t.open()
        got = t.page.evaluate(
            "async () => { try { await JarvisMobile.parts.panel.look("
            "new File(['%PDF-1.4'], 'bill.pdf', { type: 'application/pdf' })); return 'looked'; }"
            " catch (e) { return e.name + ': ' + e.message; } }"
        )
        assert got == "Error: That is not a picture. Choose a JPEG or PNG photo."
    finally:
        t.close()
