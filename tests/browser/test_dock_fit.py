# tests/browser/test_dock_fit.py -- R6.1 D7 "the dock fits every screen" (owner, 11 Nov 2026).
# A measured "priority plus" dock: at every width the tabs keep their order and the ones that do not
# fit fold into the More sheet, last tabs first. No sideways scroll anywhere; More shows only when a
# tab is folded and lights up when an open panel is behind it; the sheet lists exactly the folded
# tabs in dock order; Chat, Brief and Approvals never fold; phones keep at most eight tabs, each a
# 44 px touch target. Desktop and phone as the other browser tests emulate them (viewport only).
from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest
from test_console import Console

_pw = pytest.importorskip("playwright.sync_api")
sync_playwright = _pw.sync_playwright
expect = _pw.expect

pytestmark = pytest.mark.browser

WIDTHS = {
    1920: 1080,
    1440: 900,
    1366: 768,
    1280: 800,
    1024: 768,
    900: 800,
    768: 1024,
    390: 844,
    360: 740,
    320: 568,
}
SURFACES = ("night", "day")
PHONE_BELOW = 900  # console-deck.css: (max-width: 899px) is the phone layout
PHONE_MAX_TABS = 8  # More included
MIN_TOUCH = 44
PINNED = ("chat", "brief", "approvals")
DESK_SIZES = {78, 102, 66, 88}  # .dk / .dk.wide, and both again on 900-1180 px desktops

# Waits for the fonts and two frames, so a re-measure scheduled by them has run.
SETTLE_JS = (
    "() => document.fonts.ready.then(() => new Promise("
    "(r) => requestAnimationFrame(() => requestAnimationFrame(r))))"
)
STATE_JS = """() => {
  const dock = document.getElementById('dock'), r = dock.getBoundingClientRect();
  const shown = (e) => e.getClientRects().length > 0;
  const tabs = [...dock.querySelectorAll('.dk[data-open]')];
  const more = document.getElementById('dockMore');
  const box = (e) => {
    const b = e.getBoundingClientRect();
    return {l: b.left, r: b.right, w: b.width, h: b.height};
  };
  return {
    scrollW: dock.scrollWidth, clientW: dock.clientWidth,
    overflowX: getComputedStyle(dock).overflowX,
    left: r.left, right: r.right, bottom: r.bottom,
    vw: document.documentElement.clientWidth, vh: innerHeight,
    pageScroll: document.documentElement.scrollWidth - document.documentElement.clientWidth,
    order: tabs.map((t) => t.dataset.open),
    visible: tabs.filter(shown).map((t) => t.dataset.open),
    boxes: [...tabs.filter(shown), ...(shown(more) ? [more] : [])].map(box),
    more: shown(more),
    panels: [...document.querySelectorAll('.panel[data-panel]')].map((p) => p.dataset.panel),
  };
}"""
SHEET_JS = """() => [...document.querySelectorAll('#moreSheet [data-sheet-open]')]
  .filter((b) => b.getClientRects().length > 0).map((b) => b.dataset.sheetOpen)"""


@pytest.fixture(scope="module")
def browser() -> Iterator[Any]:
    with sync_playwright() as p:
        b = p.chromium.launch()
        yield b
        b.close()


def _console(browser: Any, url: str, token: str, width: int, surface: str = "night") -> Console:
    c = Console(browser, url, token, {"width": width, "height": WIDTHS.get(width, 800)})
    c.page.add_init_script(f"localStorage.setItem('jarvis_surface', '{surface}');")
    c.open()
    c.page.evaluate(SETTLE_JS)
    assert c.page.locator("html").get_attribute("data-surface") == surface
    return c


def _sheet_entries(c: Console) -> list[str]:
    """Open the More sheet, read the entries it shows, close it with Esc (focus returns to More)."""
    more = c.page.locator("#dockMore")
    more.click()
    c.page.locator("#moreSheet").wait_for(state="visible")
    entries: list[str] = c.page.evaluate(SHEET_JS)
    first = c.page.evaluate("document.activeElement.dataset.sheetOpen")
    assert first == entries[0], (first, entries)  # focus lands on the first entry
    c.page.keyboard.press("Escape")
    c.page.locator("#moreSheet").wait_for(state="hidden")
    expect(more).to_be_focused()
    expect(more).to_have_attribute("aria-expanded", "false")
    return entries


def _assert_fits(s: dict[str, Any], width: int) -> None:
    assert s["overflowX"] == "visible", s["overflowX"]  # the dock never scrolls sideways
    assert s["scrollW"] <= s["clientW"] + 1, (s["scrollW"], s["clientW"])
    assert s["left"] >= 0 and s["right"] <= s["vw"] and s["bottom"] <= s["vh"], s
    assert s["pageScroll"] <= 0, s["pageScroll"]
    for b in s["boxes"]:  # every tab inside the window and inside the dock
        assert b["l"] >= s["left"] - 0.5 and b["r"] <= s["right"] + 0.5, b
    if width < PHONE_BELOW:
        assert len(s["boxes"]) <= PHONE_MAX_TABS, len(s["boxes"])
        assert all(b["w"] >= MIN_TOUCH - 0.5 and b["h"] >= MIN_TOUCH for b in s["boxes"]), s
    else:
        assert {round(b["w"]) for b in s["boxes"]} <= DESK_SIZES, s["boxes"]  # usual sizes


@pytest.mark.parametrize("surface", SURFACES)
@pytest.mark.parametrize("width", list(WIDTHS))
def test_the_dock_fits_and_every_panel_is_reachable_exactly_once(
    browser: Any, server_url: str, token: str, width: int, surface: str
) -> None:
    c = _console(browser, server_url, token, width, surface)
    try:
        s = c.page.evaluate(STATE_JS)
        _assert_fits(s, width)
        order, visible = s["order"], s["visible"]
        assert sorted(order) == sorted(s["panels"]) and len(order) == len(set(order))
        # dock order kept: the last tabs fold first
        assert visible == order[: len(visible)], visible
        assert set(PINNED) <= set(visible), visible  # never folded (Approvals keeps its badge)
        folded = order[len(visible) :]
        assert s["more"] is bool(folded), (s["more"], folded)
        sheet = _sheet_entries(c) if folded else []
        assert sheet == folded, (sheet, folded)  # exactly the folded tabs, in dock order
        reachable = visible + sheet
        assert sorted(reachable) == sorted(order) and len(reachable) == len(set(reachable))
        if width == 1920:
            assert not folded, folded  # everything fits a full-HD screen: no More
        assert c.errors == [] and c.csp_violations() == []
    finally:
        c.close()


@pytest.mark.parametrize("width", [1280, 360])
def test_a_folded_panel_lights_more_and_focus_comes_back_to_more(
    browser: Any, server_url: str, token: str, width: int
) -> None:
    c = _console(browser, server_url, token, width)
    page, more = c.page, c.page.locator("#dockMore")
    try:
        folded = page.evaluate(STATE_JS)["order"][-1]
        assert page.locator(f'.dk[data-open="{folded}"]').is_hidden()
        assert "on" not in str(more.get_attribute("class"))
        more.click()
        page.locator(f'#moreSheet [data-sheet-open="{folded}"]').click()
        page.locator(f"#p-{folded}").wait_for(state="visible")
        assert page.locator("#moreSheet").is_hidden()
        expect(more).to_have_class("dk more on")
        title = page.locator(f"#p-{folded} .ptitle h2").text_content()
        assert more.get_attribute("aria-label") == f"More panels, {title} shown"
        more.click()  # the open panel is marked in the sheet
        current = page.locator(f'#moreSheet [data-sheet-open="{folded}"]')
        assert current.get_attribute("aria-current") == "true"
        page.keyboard.press("Escape")
        expect(more).to_be_focused()
        if width >= PHONE_BELOW:  # closing it returns focus to More (its tab is folded)
            page.locator(f"#p-{folded} [data-close]").click()
            page.locator(f"#p-{folded}").wait_for(state="hidden")
            expect(more).to_be_focused()
        else:  # a phone shows one panel at a time: a pinned tab switches back
            page.locator('.dk[data-open="chat"]').click()
            page.locator("#p-chat").wait_for(state="visible")
        expect(more).to_have_class("dk more")
        assert more.get_attribute("aria-label") == "More panels"
        assert c.errors == []
    finally:
        c.close()


def test_the_dock_refits_on_resize_without_a_layout_loop(
    browser: Any, server_url: str, token: str
) -> None:
    c = _console(browser, server_url, token, 1920)
    page = c.page
    try:
        assert page.evaluate(STATE_JS)["more"] is False
        page.locator('.dk[data-open="construct"]').focus()
        for width, height in ((1280, 800), (390, 844), (1024, 768), (320, 568)):
            page.set_viewport_size({"width": width, "height": height})
            page.evaluate(SETTLE_JS)
            s = page.evaluate(STATE_JS)
            _assert_fits(s, width)
            assert s["more"] is True and "construct" not in s["visible"], (width, s["visible"])
        # a focused tab that folds hands its focus to More, never to the page
        assert page.evaluate("document.activeElement.id") == "dockMore"
        page.set_viewport_size({"width": 1920, "height": 1080})
        page.evaluate(SETTLE_JS)
        s = page.evaluate(STATE_JS)
        assert s["more"] is False and s["visible"] == s["order"], s["visible"]
        # settled: nothing in the dock changes on its own any more (no measure loop)
        changes = page.evaluate(
            """() => new Promise((done) => {
                 let n = 0;
                 const mo = new MutationObserver((list) => { n += list.length; });
                 mo.observe(document.getElementById('dock'), {subtree: true, attributes: true,
                   attributeFilter: ['hidden', 'class', 'style']});
                 setTimeout(() => { mo.disconnect(); done(n); }, 800);
               })"""
        )
        assert changes == 0, changes
        assert c.errors == []
    finally:
        c.close()


@pytest.mark.parametrize("width", [1280, 320])
def test_the_approvals_badge_stays_on_screen(
    browser: Any, server_url: str, token: str, width: int
) -> None:
    c = _console(browser, server_url, token, width)
    try:
        c.page.evaluate(
            "document.dispatchEvent(new CustomEvent('jarvis:approvals', {detail: {count: 3}}))"
        )
        badge = c.page.locator("#dockBadge")
        assert badge.is_visible() and badge.text_content() == "3"
        tab = c.page.locator('.dk[data-open="approvals"]').bounding_box()
        assert tab is not None and 0 <= tab["x"] and tab["x"] + tab["width"] <= width, tab
        assert c.errors == []
    finally:
        c.close()
