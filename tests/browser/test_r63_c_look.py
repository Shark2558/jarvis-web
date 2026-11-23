# tests/browser/test_r63_c_look.py -- R6.3 Part C, the look (docs/plans/r6-3-book-content.md D0,
# "Exit check" 3; the owner's standing rule: the console's look never changes): every new screen
# of Part C passes the console's visual gate (tests/test_ui_audit.py: 44 px targets on the phone,
# labels, contrast, no overflow, no browser-default control) at 360 x 800 and 1280 x 800, by night
# and by day; with R63C_SHOTS=<folder> each screen is also saved as a picture for the owner.
# Without a book session the Book panel is laid out exactly as without R6.3's box, so its
# screenshots stay as they were (47ee8fc's look): the same picture, byte for byte. (R6.3.1 D8: the
# writer's screens and boxes went with the writer.)
from __future__ import annotations

import json
import os
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from book_mocks import PASSKEY_STUB, FakeBook
from r63_fakes_c import route_c, serve_c, set_state
from test_console import Console
from test_ui_audit import NAMELESS_JS, WRAP_JS, _assert_clean
from ui_checks import DOM_CHECKS_JS, FINISH_ANIMATIONS_JS

_pw = pytest.importorskip("playwright.sync_api")
pytestmark = pytest.mark.browser
SHOTS = os.environ.get("R63C_SHOTS", "")  # pictures only when asked for
SIZES = {"phone": {"width": 360, "height": 800}, "laptop": {"width": 1280, "height": 800}}
PAGES = "#p-book .bk-pages"
PLACE = {"release": "3f2a1c9", "page": "pg_card_c01"}  # continue: Demo router
BOXES = ".bk-pages"  # R6.3's box (console-book.js, I0 seam 8; R6.3.1: the writer's two went)
LAYOUT_JS = """(sel) => [...document.querySelectorAll(sel + ' *')]
  .filter((e) => e.getClientRects().length)
  .map((e) => {
    const r = e.getBoundingClientRect();
    const leaf = e.children.length ? '' : (e.textContent || '').trim();
    return [e.tagName, e.className, ...[r.x, r.y, r.width, r.height].map(Math.round), leaf];
  })"""


@pytest.fixture(scope="module")
def c_url(token: str) -> Iterator[str]:
    if os.environ.get("JARVIS_BROWSER_TESTS") != "1":
        pytest.skip("JARVIS_BROWSER_TESTS=1 not set")
    url, stop = serve_c(token)
    try:
        yield url
    finally:
        stop()


@pytest.fixture(scope="module")
def browser() -> Iterator[Any]:
    with _pw.sync_playwright() as p:
        b = p.chromium.launch()
        yield b
        b.close()


def panel(
    browser: Any, url: str, token: str, size: str, surface: str, place: Any = None, **state: Any
) -> Console:
    set_state(url, reset=True, **state)
    c = Console(browser, url, token, SIZES[size])
    if place is not None:
        js = json.dumps(json.dumps(place))
        c.page.add_init_script(f"localStorage.setItem('jarvis_book_place_v1', {js});")
    FakeBook(c.page)
    route_c(c.page)
    c.open()
    c.page.evaluate(PASSKEY_STUB)
    if surface == "day":
        c.choose_day()
    c.open_panel("book")
    c.page.locator("#p-book .bk-release").wait_for()
    return c


def gate(c: Console, sel: str, size: str, what: str, shot: str) -> None:
    c.page.evaluate("() => document.fonts.ready.then(() => true)")
    c.page.evaluate(FINISH_ANIMATIONS_JS)
    vp = "phone" if size == "phone" else "desktop"
    res = c.page.evaluate(DOM_CHECKS_JS, sel)
    assert not res.get("missing"), what
    _assert_clean(res, c.page.evaluate(NAMELESS_JS, sel), c.page.evaluate(WRAP_JS, sel), vp, what)
    if SHOTS:
        folder = Path(SHOTS)
        folder.mkdir(parents=True, exist_ok=True)
        c.page.screenshot(path=str(folder / f"{shot}.png"))
        c.page.locator(sel).screenshot(path=str(folder / f"{shot}-part.png"))


def scrolled(c: Console, sel: str) -> None:
    c.page.locator(sel).first.scroll_into_view_if_needed()


SCREENS = [(s, f) for s in SIZES for f in ("night", "day")]


@pytest.mark.parametrize(("size", "surface"), SCREENS)
def test_r63_c_look_the_full_book_a_written_page_and_one_not_written(
    browser: Any, c_url: str, token: str, size: str, surface: str
) -> None:
    c = panel(browser, c_url, token, size, surface, place=PLACE)
    try:
        c.page.get_by_role("button", name="Open for me").click()
        c.page.locator(PAGES).get_by_role("button", name="Continue: Demo router").wait_for()
        c.page.locator(f"{PAGES} .dsc", has_text="Parts").click()
        c.page.locator(f"{PAGES} .bk-row", has_text="Demo router").wait_for()
        scrolled(c, f"{PAGES} .bk-rhead")
        gate(c, PAGES, size, f"full book {size} {surface}", f"full-book-{size}-{surface}")
        c.page.locator(f"{PAGES} .bk-row", has_text="Demo router").get_by_role(
            "button", name="Read"
        ).click()
        c.page.locator(f"{PAGES} .bk-rhead", has_text="Reading Demo router").wait_for()
        scrolled(c, f"{PAGES} .bk-rhead")
        gate(c, PAGES, size, f"written page {size} {surface}", f"page-written-{size}-{surface}")
        c.page.locator(PAGES).get_by_role("button", name="Back to the contents").click()
        c.page.locator(f"{PAGES} .bk-row", has_text="Demo console").get_by_role(
            "button", name="Read"
        ).click()
        c.page.locator(f"{PAGES} .bk-rhead", has_text="Reading Demo console").wait_for()
        scrolled(c, f"{PAGES} .bk-rhead")
        gate(
            c, PAGES, size, f"unwritten page {size} {surface}", f"page-not-written-{size}-{surface}"
        )
        assert c.errors == [] and c.csp_violations() == []
    finally:
        c.close()


@pytest.mark.parametrize("size", list(SIZES))
def test_r63_c_look_without_a_session_the_panel_is_as_it_was(
    browser: Any, c_url: str, token: str, size: str
) -> None:
    c = panel(browser, c_url, token, size, "night")
    try:
        # the ambient loops held still, so two pictures of the same layout can match byte for byte
        c.page.emulate_media(reduced_motion="reduce")
        assert c.page.locator("#p-book .bk-wtop, #p-book .bk-writer").count() == 0  # R6.3.1 D8
        c.page.wait_for_timeout(300)
        c.page.evaluate(FINISH_ANIMATIONS_JS)
        with_boxes = c.page.evaluate(LAYOUT_JS, "#p-book")
        shot = c.page.locator("#p-book").screenshot(animations="disabled")
        c.page.evaluate(f"() => document.querySelectorAll('{BOXES}').forEach((n) => n.remove())")
        assert c.page.evaluate(LAYOUT_JS, "#p-book") == with_boxes  # the boxes take no room at all
        again = c.page.locator("#p-book").screenshot(animations="disabled")
        assert again == shot  # the same picture, byte for byte
        if SHOTS:
            Path(SHOTS).mkdir(parents=True, exist_ok=True)
            (Path(SHOTS) / f"panel-{size}-night.png").write_bytes(shot)
        assert c.errors == [] and c.csp_violations() == []
    finally:
        c.close()
