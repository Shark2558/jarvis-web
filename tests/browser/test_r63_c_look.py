# tests/browser/test_r63_c_look.py -- R6.3 Part C, the look (docs/plans/r6-3-book-content.md D0,
# "Exit check" 3; the owner's standing rule: the console's look never changes): every new screen
# of Part C passes the console's visual gate (tests/test_ui_audit.py: 44 px targets on the phone,
# labels, contrast, no overflow, no browser-default control) at 360 x 800 and 1280 x 800, by night
# and by day; with R63C_SHOTS=<folder> each screen is also saved as a picture for the owner.
# With the writer OFF (no key) the Book panel is laid out exactly as without R6.3's boxes, so its
# screenshots stay as they were (47ee8fc's look): the same picture, byte for byte.
from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from book_mocks import PASSKEY_STUB, FakeBook
from r63_fakes_c import route_c, serve_c, set_state, until
from test_console import Console
from test_ui_audit import NAMELESS_JS, WRAP_JS, _assert_clean
from ui_checks import DOM_CHECKS_JS, FINISH_ANIMATIONS_JS

_pw = pytest.importorskip("playwright.sync_api")
pytestmark = pytest.mark.browser
SHOTS = os.environ.get("R63C_SHOTS", "")  # pictures only when asked for
SIZES = {"phone": {"width": 360, "height": 800}, "laptop": {"width": 1280, "height": 800}}
WRITER, PAGES, DIALOG = "#p-book .bk-writer", "#p-book .bk-pages", "#bookYesDialog"
PICKED = {
    "brain": "anthropic",
    "picked_at": "2026-11-24T10:00:00+05:30",
    "confirmed": {
        "brain": "anthropic",
        "caps": {"trial": 100, "first": 1500, "release": 500, "month": 1000, "limit_pct": 80},
        "terms_id": "wt_" + "a" * 12,
        "at": "2026-11-24T10:00:00+05:30",
    },
}
BOXES = ".bk-wtop, .bk-writer, .bk-pages"  # R6.3's three boxes (console-book.js, I0 seam 8)
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


def panel(browser: Any, url: str, token: str, size: str, surface: str, **state: Any) -> Console:
    set_state(url, reset=True, **state)
    c = Console(browser, url, token, SIZES[size])
    FakeBook(c.page)
    route_c(c.page)
    c.open()
    c.page.evaluate(PASSKEY_STUB)
    if surface == "day":
        c.choose_day()
    c.open_panel("book")
    c.page.locator("#p-book .bk-release").wait_for()
    return c


def open_writer(c: Console) -> None:
    head = c.page.locator(f"{WRITER} .dsc").first
    head.wait_for()
    head.click()


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
def test_r63_c_look_the_trial_estimate_its_yes_and_its_progress(
    browser: Any, c_url: str, token: str, size: str, surface: str
) -> None:
    c = panel(browser, c_url, token, size, surface)
    try:
        open_writer(c)
        until(c.page, lambda: "About ₹40" in c.page.locator(WRITER).inner_text(), "the estimate")
        scrolled(c, f"{WRITER} .dsc")
        gate(
            c, WRITER, size, f"trial estimate {size} {surface}", f"trial-estimate-{size}-{surface}"
        )
        c.page.locator(WRITER).get_by_role("button", name="Start the trial").click()
        c.page.locator(DIALOG).wait_for()
        gate(c, DIALOG, size, f"trial yes {size} {surface}", f"trial-yes-{size}-{surface}")
        c.page.locator(f"{DIALOG} #bookYes").fill("YES")
        c.page.locator(DIALOG).get_by_role("button", name="Start").click()
        until(c.page, lambda: "of 10 pages" in c.page.locator(WRITER).inner_text(), "the progress")
        c.page.locator(WRITER).get_by_role("button", name="Pause watching").click()
        scrolled(c, f"{WRITER} .dsc")
        gate(
            c, WRITER, size, f"trial progress {size} {surface}", f"trial-progress-{size}-{surface}"
        )
        assert c.errors == [] and c.csp_violations() == []
    finally:
        c.close()


@pytest.mark.parametrize(("size", "surface"), SCREENS)
def test_r63_c_look_the_side_by_side_the_pick_update_and_the_storage_line(
    browser: Any, c_url: str, token: str, size: str, surface: str
) -> None:
    c = panel(
        browser,
        c_url,
        token,
        size,
        surface,
        trial_done=True,
        update_ready=True,
        storage_warn=True,
        pick=PICKED,
    )
    try:
        c.page.locator("#p-book .bk-wtop").wait_for()
        gate(c, "#p-book", size, f"storage line {size} {surface}", f"storage-line-{size}-{surface}")
        open_writer(c)
        until(
            c.page,
            lambda: "Passed after one redraft" in c.page.locator(WRITER).inner_text(),
            "rows",
        )
        scrolled(c, f"{WRITER} .dsc")
        gate(
            c,
            WRITER,
            size,
            f"side by side {size} {surface}",
            f"trial-side-by-side-{size}-{surface}",
        )
        c.page.locator(f"{WRITER} .bev").nth(0).get_by_role("button", name="Read").click()
        until(
            c.page, lambda: "Written by Claude" in c.page.locator(WRITER).inner_text(), "the sample"
        )
        scrolled(c, f"{WRITER} .bk-rhead")
        gate(c, WRITER, size, f"sample page {size} {surface}", f"trial-sample-{size}-{surface}")
        scrolled(c, "#bkWriterBrain")
        gate(c, WRITER, size, f"pick {size} {surface}", f"pick-{size}-{surface}")
        c.page.locator(WRITER).get_by_role("button", name="Update").click()
        c.page.locator(DIALOG).get_by_text("About ₹300").wait_for()
        gate(c, DIALOG, size, f"update yes {size} {surface}", f"update-yes-{size}-{surface}")
        assert c.errors == [] and c.csp_violations() == []
    finally:
        c.close()


@pytest.mark.parametrize(("size", "surface"), SCREENS)
def test_r63_c_look_the_picks_yes_and_the_first_writes_yes(
    browser: Any, c_url: str, token: str, size: str, surface: str
) -> None:
    c = panel(browser, c_url, token, size, surface)
    try:
        open_writer(c)
        c.page.locator("#bkCapFirst").wait_for()
        c.page.locator(WRITER).get_by_role("button", name="Save the pick").click()
        c.page.locator(DIALOG).get_by_text("Up to Rs 1,500").wait_for()
        gate(c, DIALOG, size, f"pick yes {size} {surface}", f"pick-yes-{size}-{surface}")
        c.page.locator(f"{DIALOG} #bookYes").fill("YES")
        c.page.locator(DIALOG).get_by_role("button", name="Confirm").click()
        until(c.page, lambda: "Saved." in c.page.locator(WRITER).inner_text(), "the pick saved")
        c.page.locator(WRITER).get_by_role("button", name="Write the full book").click()
        c.page.locator(DIALOG).get_by_text("About ₹1,140").wait_for()
        gate(c, DIALOG, size, f"first yes {size} {surface}", f"first-write-yes-{size}-{surface}")
        assert [e for e in c.errors if "status of 422 " not in e] == [] and c.csp_violations() == []
    finally:
        c.close()


@pytest.mark.parametrize(("size", "surface"), SCREENS)
def test_r63_c_look_the_full_book_a_written_page_and_one_not_written(
    browser: Any, c_url: str, token: str, size: str, surface: str
) -> None:
    c = panel(browser, c_url, token, size, surface)
    try:
        c.page.get_by_role("button", name="Open for me").click()
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
def test_r63_c_look_with_the_writer_off_the_panel_is_as_it_was(
    browser: Any, c_url: str, token: str, size: str
) -> None:
    c = panel(browser, c_url, token, size, "night", off="no_key")
    try:
        until(
            c.page,
            lambda: c.page.locator(WRITER).get_attribute("hidden") is not None,
            "the writer hidden",
        )
        c.page.wait_for_timeout(300)
        c.page.evaluate(FINISH_ANIMATIONS_JS)
        with_boxes = c.page.evaluate(LAYOUT_JS, "#p-book")
        shot = c.page.locator("#p-book").screenshot()
        c.page.evaluate(f"() => document.querySelectorAll('{BOXES}').forEach((n) => n.remove())")
        assert c.page.evaluate(LAYOUT_JS, "#p-book") == with_boxes  # the boxes take no room at all
        assert c.page.locator("#p-book").screenshot() == shot  # the same picture, byte for byte
        if SHOTS:
            Path(SHOTS).mkdir(parents=True, exist_ok=True)
            (Path(SHOTS) / f"writer-off-{size}-night.png").write_bytes(shot)
        assert c.errors == [] and c.csp_violations() == []
    finally:
        c.close()
