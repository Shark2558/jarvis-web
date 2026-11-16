# tests/browser/test_r13_d_helpers.py -- R13 Part D in a real Chromium (docs/plans/r13-wardrobe.md
# D1, D10, D13, D19, LND-15), against D's fake server (tests/r13_fakes_d.py over I0's fake server):
#   - Helpers -> Wardrobe draws its six sections from the HTTP contract's shapes: the review queue
#     (his candidates, "there was no deposit"), tomorrow's plan (slots, reasons, gaps, the weather's
#     assumption), the laundry, the pieces (counts, private basics HIDDEN until he taps, a piece's
#     latest history), labels and settings
#   - a change goes through POST /v1/wardrobe/tools/{tool} (the gateway); the calendar picker says
#     the governed read's answer; the QR sheet downloads as a file
#   - before sign-in the tab asks the server nothing
#   - the visual gate at 1440x900 and 390x844, Night and Day; screenshots into /tmp/r13-d-shots
from __future__ import annotations

import json
import os
import time
import urllib.request
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import pytest
from r13_fakes_d import VEST1, serve_d
from test_console import DESKTOP, PHONE, Console
from test_ui_audit import NAMELESS_JS, WRAP_JS, _assert_clean
from ui_checks import DOM_CHECKS_JS, FINISH_ANIMATIONS_JS, install_mocks

sync_playwright = pytest.importorskip("playwright.sync_api").sync_playwright
pytestmark = pytest.mark.browser
SHOTS = Path(os.environ.get("R13_D_SHOTS", "/tmp/r13-d-shots"))
TAB_KEY = "try { localStorage.setItem('jarvis_helpers_tab', 'wardrobe'); } catch (e) {}"


@pytest.fixture(scope="module")
def d_url(token: str) -> Iterator[str]:
    if os.environ.get("JARVIS_BROWSER_TESTS") != "1":
        pytest.skip("JARVIS_BROWSER_TESTS=1 not set")
    url, stop = serve_d(token)
    try:
        yield url
    finally:
        stop()


@pytest.fixture(scope="module")
def browser() -> Iterator[Any]:
    with sync_playwright() as p:
        b = p.chromium.launch()
        yield b
        b.close()


def until(page: Any, check: Callable[[], bool], what: str, timeout_s: float = 30.0) -> None:
    end = time.monotonic() + timeout_s
    while time.monotonic() < end:
        if check():
            return
        page.wait_for_timeout(100)
    raise AssertionError(f"timed out waiting for {what}")


def seen(url: str, token: str) -> Any:
    auth = {"Authorization": f"Bearer {token}"}
    req = urllib.request.Request(url + "/v1/test/r13-d", headers=auth)
    with urllib.request.urlopen(req, timeout=5) as r:
        return json.loads(r.read())


def tab(browser: Any, url: str, token: str, viewport: dict[str, int] = DESKTOP) -> Console:
    c = Console(browser, url, token, viewport)
    install_mocks(c.page)
    c.open()
    c.open_panel("helpers")
    c.page.locator("#hpt-wardrobe").click()
    ready = ("Which of these went into the basket?", "pieces,", "Weather for your home area")
    until(c.page, lambda: all(w in text(c) for w in ready), "the sections")
    return c


def text(c: Console) -> str:
    return str(c.page.locator("#hpp-wardrobe").inner_text())


def button(c: Console, name: str) -> Any:
    return c.page.locator("#hpp-wardrobe").get_by_role("button", name=name, exact=True)


def test_the_six_sections_draw_the_contracts_shapes(browser: Any, d_url: str, token: str) -> None:
    c = tab(browser, d_url, token)
    try:
        t = text(c)
        for heading in ("NEEDS A CHECK", "TODAY AND TOMORROW", "LAUNDRY", "PIECES", "LABELS"):
            assert heading in t.upper(), heading
        assert "Which of these went into the basket?" in t
        up = t.upper()  # buttons are uppercase in the console's look
        assert "THIS ONE: A PRIVATE BASIC (NO. 2)" in up and "THERE WAS NO DEPOSIT" in up
        assert "tap Show private basics in Pieces" in t  # two copies, told apart only there
        assert "Weather for your home area: rain likely from 15:00." in t
        assert "Tomorrow" in t and "business formal" in t and "Light blue office shirt" in t
        assert "Press the white shirt for Wednesday" in t
        assert "Nothing in the laundry." in t and "never orders, pays, calls" in t
        assert "24 pieces" in t and "Black sock" in t
        assert "3 pieces are hidden" in t  # the private basics, behind a tap (D10)
        assert c.errors == [] and c.csp_violations() == []
    finally:
        c.close()


def test_private_basics_show_only_after_his_tap(browser: Any, d_url: str, token: str) -> None:
    c = tab(browser, d_url, token)
    try:
        assert "A private basic" in text(c)  # in the review queue, by default
        c.page.locator("#hpp-wardrobe").get_by_role("button", name="Show private basics").click()
        until(c.page, lambda: "Shown here only" in text(c), "the private basics shown")
        assert "Base layers and socks" in text(c)
    finally:
        c.close()


def test_a_change_goes_through_the_gateway_and_a_piece_shows_its_history(
    browser: Any, d_url: str, token: str
) -> None:
    c = tab(browser, d_url, token)
    try:
        before = len(seen(d_url, token)["tools"])
        button(c, "Wearing it").click()
        until(c.page, lambda: len(seen(d_url, token)["tools"]) > before, "the tool call")
        call = seen(d_url, token)["tools"][before]
        assert call == {"tool": "wear_log", "arguments": {"action": "start", "plan": "pl_1"}}
        c.page.locator("#hpp-wardrobe").get_by_role("button", name="Details").first.click()
        until(c.page, lambda: "Now: Ready" in text(c), "the piece's history")
        assert "Added" in text(c)
    finally:
        c.close()


def test_the_review_queue_answers_in_bs_own_argument_names(
    browser: Any, d_url: str, token: str
) -> None:
    c = tab(browser, d_url, token)
    try:
        for press, args in (
            ("There was no deposit", {"outcome": "none"}),
            ("This one: A private basic (No. 2)", {"outcome": "these", "pieces": [VEST1]}),
        ):
            before = len(seen(d_url, token)["tools"])
            button(c, press).click()
            until(c.page, lambda n=before: len(seen(d_url, token)["tools"]) > n, press)
            call = seen(d_url, token)["tools"][before]
            want = {"action": "resolve", "entry": "rv_1", **args}  # r13-b checks.SCHEMAS
            assert call == {"tool": "laundry_review", "arguments": want}, press
    finally:
        c.close()


def test_the_calendar_picker_says_the_governed_reads_answer_and_the_sheet_downloads(
    browser: Any, d_url: str, token: str
) -> None:
    c = tab(browser, d_url, token)
    try:
        button(c, "Choose a calendar").click()
        until(c.page, lambda: "Your Calendar permission is Ask first" in text(c), "the answer")
        with c.page.expect_download() as dl:
            button(c, "Download the sheet").click()
        assert dl.value.suggested_filename == "jarvis-wardrobe-labels.svg"
    finally:
        c.close()


def test_before_sign_in_the_tab_asks_the_server_nothing(
    browser: Any, d_url: str, token: str
) -> None:
    c = Console(browser, d_url, token, DESKTOP)
    try:
        c.page.add_init_script(TAB_KEY)  # last visit left Helpers on Wardrobe
        asked: list[str] = []
        c.page.on("request", lambda r: asked.append(r.url))
        c.page.goto(d_url + "/")
        c.page.locator("#tokIn").wait_for()
        c.page.wait_for_timeout(1500)
        wardrobe = ("/v1/wardrobe", "/v1/laundry", "/v1/outfits")
        assert not [u for u in asked if any(p in u for p in wardrobe)]
    finally:
        c.close()


def _audit(c: Console, vp: str, what: str, shot: str) -> None:
    c.page.wait_for_timeout(400)
    c.page.evaluate(FINISH_ANIMATIONS_JS)
    sel = "#p-helpers"
    res = c.page.evaluate(DOM_CHECKS_JS, sel)
    assert not res.get("missing"), what
    _assert_clean(res, c.page.evaluate(NAMELESS_JS, sel), c.page.evaluate(WRAP_JS, sel), vp, what)
    SHOTS.mkdir(parents=True, exist_ok=True)
    c.page.screenshot(path=str(SHOTS / f"{shot}.png"))
    c.page.locator("#p-helpers").screenshot(path=str(SHOTS / f"{shot}-panel.png"))


@pytest.mark.parametrize("surface", ["night", "day"])
@pytest.mark.parametrize("vp", ["desktop", "phone"])
def test_helpers_wardrobe_passes_the_visual_gate(
    browser: Any, d_url: str, token: str, vp: str, surface: str
) -> None:
    c = tab(browser, d_url, token, DESKTOP if vp == "desktop" else PHONE)
    try:
        if surface == "day":
            c.choose_day()
            c.open_panel("helpers")
            c.page.locator("#hpt-wardrobe").click()
        size = "1440x900" if vp == "desktop" else "390x844"
        _audit(c, vp, f"helpers wardrobe {vp} {surface}", f"helpers-wardrobe-{size}-{surface}")
        c.page.locator("#hpp-wardrobe").get_by_role("button", name="Show private basics").click()
        until(c.page, lambda: "Shown here only" in text(c), "the private basics")
        c.page.locator("#hpp-wardrobe").get_by_role("button", name="Details").first.click()
        until(c.page, lambda: "Now:" in text(c), "a piece's history")
        _audit(c, vp, f"helpers pieces {vp} {surface}", f"helpers-wardrobe-pieces-{size}-{surface}")
        assert c.errors == [] and c.csp_violations() == []
    finally:
        c.close()
