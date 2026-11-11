# tests/browser/test_dock_fit.py -- R6.1 D7 "the dock fits every screen" (owner, 11 Nov 2026).
# A measured "priority plus" dock: at every width the tabs keep their order and the ones that do not
# fit fold into the More sheet, last tabs first. No sideways scroll anywhere; More shows only when a
# tab is folded and lights up when an open panel is behind it; the sheet lists exactly the folded
# tabs in dock order; Chat, Brief and Approvals never fold for lack of room; phones keep at most
# eight tabs, each a 44 px touch target. Desktop and phone as the other browser tests emulate them.
# R6.1 review A (H1/M1): a tab shows only while it holds its label: no label overflows its tab and
# two neighbouring labels never touch (>= 6 px apart). A desktop tab whose label is wider than the
# tab (900-1180 px: Approvals, Integrations, ...) moves behind More instead; the approvals badge
# then rides on More. The chat box's hint stays whole on one line (orchestrator, 320 px).
# R6.1 CI: which tabs fold depends on how wide this renderer draws the labels (GitHub's Chromium 153
# draws them wider than this machine's: CONNECTORS outgrows its 78 px tab there). So the tests no
# longer write one machine's counts in: they measure each label and tab themselves and check the
# dock against the rule (dock_rule.py), and a test-only style imitates a wider-text renderer here.
from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest
from dock_rule import (
    MIN_TOUCH,
    PHONE_MAX_TABS,
    SHEET_JS,
    Dock,
    assert_follows_rule,
    measure_dock,
    overflowing,
)
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
NARROW_DESK = 1180  # console-deck.css: 900-1180 px desktops have the smaller 66 / 88 px tabs
PINNED = ("chat", "brief", "approvals")  # Approvals folds only where its label overflows its tab
LABEL_GAP = 6  # px between two neighbouring labels at the least (the dock's 4 px gap + two borders)
HINT, SHORT_HINT = "Message JARVIS", "Message"
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
  // the tab inside its borders, and its visible label as painted (the text's own rect)
  function labelBox(t) {
    const b = t.getBoundingClientRect(), c = getComputedStyle(t);
    const span = [...t.querySelectorAll('span')]
      .find((x) => shown(x) && getComputedStyle(x).position !== 'absolute');
    let label = null;
    if (span) {
      const rg = document.createRange(); rg.selectNodeContents(span);
      const q = rg.getBoundingClientRect(); label = {l: q.left, r: q.right};
    }
    return {id: t.dataset.open || t.id, l: b.left + parseFloat(c.borderLeftWidth),
            r: b.right - parseFloat(c.borderRightWidth), label};
  }
  return {
    scrollW: dock.scrollWidth, clientW: dock.clientWidth,
    overflowX: getComputedStyle(dock).overflowX,
    left: r.left, right: r.right, bottom: r.bottom,
    vw: document.documentElement.clientWidth, vh: innerHeight,
    pageScroll: document.documentElement.scrollWidth - document.documentElement.clientWidth,
    order: tabs.map((t) => t.dataset.open),
    visible: tabs.filter(shown).map((t) => t.dataset.open),
    boxes: [...tabs.filter(shown), ...(shown(more) ? [more] : [])].map(box),
    labels: [...tabs.filter(shown), ...(shown(more) ? [more] : [])].map(labelBox),
    more: shown(more),
    panels: [...document.querySelectorAll('.panel[data-panel]')].map((p) => p.dataset.panel),
  };
}"""
# The letter-spacing of a dock tab's label, in px (the tab's own: .16em on a desktop, 0 on a phone).
TRACKING_JS = (
    "() => parseFloat(getComputedStyle(document.querySelector('#dock .dk > span')).letterSpacing)"
    " || 0"
)
WIDER_PX = 0.4  # px more tracking a letter: CONNECTORS (ten letters) 4 px wider, past its tab
# The chat box's hint as painted: its width in the box's font against the room inside the box, and
# the empty box's scroll height (a hint that wraps makes it taller than the box).
HINT_JS = """(full) => {
  const t = document.getElementById('input');
  if (!t || !t.getClientRects().length || t.value) return null;
  const s = getComputedStyle(t), g = document.createElement('canvas').getContext('2d');
  g.font = `${s.fontStyle} ${s.fontWeight} ${s.fontSize} ${s.fontFamily}`;
  const w = (x) => g.measureText(x).width + (parseFloat(s.letterSpacing) || 0) * x.length;
  return {text: t.placeholder, need: w(t.placeholder), full: w(full),
          room: t.clientWidth - parseFloat(s.paddingLeft) - parseFloat(s.paddingRight),
          scrollH: t.scrollHeight, clientH: t.clientHeight};
}"""


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


def _track_labels(page: Any, tracking: float) -> None:
    """Test-only: draw every dock label with this letter-spacing (px) and let the dock refit. A
    style tag on the label in this page only; the product's files and look are not touched."""
    page.add_style_tag(content=f"#dock .dk > span {{ letter-spacing: {tracking}px }}")
    size = page.viewport_size  # the dock measures again when the window's width changes
    for width in (size["width"] - 1, size["width"]):
        page.set_viewport_size({"width": width, "height": size["height"]})
        page.evaluate(SETTLE_JS)


def _hold_every_label(page: Any) -> None:
    """Test-only: labels without tracking hold their desktop tabs with room to spare on any
    renderer (CONNECTORS is then about 57 px in its 76), so a full-HD dock has nothing to fold."""
    _track_labels(page, 0)
    assert overflowing(measure_dock(page)) == [], "every label should hold its tab untracked"


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
    _assert_labels_clear(s["labels"])


def _assert_labels_clear(tabs: list[dict[str, Any]]) -> None:
    """No visible label overflows its tab (inside its borders), and two neighbouring labels are at
    least LABEL_GAP apart: they never touch or overlap. Icon-only tabs (< 360 px) have none."""
    for t in tabs:
        lab = t["label"]
        if lab:
            assert lab["l"] >= t["l"] and lab["r"] <= t["r"], ("label overflows its tab", t)
    named = [t for t in tabs if t["label"]]
    for a, b in zip(named, named[1:], strict=False):
        gap = b["label"]["l"] - a["label"]["r"]
        assert gap >= LABEL_GAP, (f"labels {gap:.2f} px apart", a, b)


def _assert_hint_whole(c: Console, width: int) -> None:
    """The chat box's hint sits on one line, whole: the full one where it fits, else "Message"."""
    h = c.page.evaluate(HINT_JS, HINT)
    if h is None:
        assert width >= PHONE_BELOW, "the Conversation is a phone's first panel"
        return
    assert h["scrollH"] <= h["clientH"] + 1, ("the hint wraps", h)
    assert h["need"] <= h["room"], ("the hint is cut", h)
    assert h["text"] == (HINT if h["full"] <= h["room"] else SHORT_HINT), h


@pytest.mark.parametrize("surface", SURFACES)
@pytest.mark.parametrize("width", list(WIDTHS))
def test_the_dock_fits_and_every_panel_is_reachable_exactly_once(
    browser: Any, server_url: str, token: str, width: int, surface: str
) -> None:
    c = _console(browser, server_url, token, width, surface)
    try:
        s = c.page.evaluate(STATE_JS)
        _assert_fits(s, width)
        dock = measure_dock(c.page)
        over = overflowing(dock)
        folded = _assert_folding(c, s, dock)
        if PHONE_BELOW <= width <= NARROW_DESK:  # the 66 / 88 px tabs are over 2 px narrower than
            assert {"approvals", "integrations"} <= set(over), over  # these labels (review A, M1)
        if width == 1920:  # a full-HD screen has room for every tab: only a tab whose label is
            assert folded == over, (folded, over)  # wider than it folds (none on this machine)
        _assert_hint_whole(c, width)
        assert c.errors == [] and c.csp_violations() == []
    finally:
        c.close()


@pytest.mark.parametrize("width", [1920, 1366, 390])
def test_a_renderer_with_wider_text_folds_the_labels_that_no_longer_fit(
    browser: Any, server_url: str, token: str, width: int
) -> None:
    # GitHub's Chromium 153 draws the dock labels wider than this machine's: CONNECTORS outgrows
    # its 78 px tab on every desktop and a 390 px phone holds one tab fewer. Here a test-only style
    # imitates that renderer, and the dock still follows the measured rule.
    c = _console(browser, server_url, token, width)
    page = c.page
    try:
        _track_labels(page, page.evaluate(TRACKING_JS) + WIDER_PX)
        s = page.evaluate(STATE_JS)
        _assert_fits(s, width)
        dock = measure_dock(page)
        over = overflowing(dock)
        if width >= PHONE_BELOW:  # the path GitHub took: a label too wide for its full-size tab
            assert over, "the wider text should push a label past its tab"
        folded = _assert_folding(c, s, dock)
        assert folded and s["more"], folded
        if width == 1920:
            assert folded == over, (folded, over)  # folded for its label, not for lack of room
        first = folded[0]  # an open folded panel lights More
        page.locator("#dockMore").click()
        page.locator(f'#moreSheet [data-sheet-open="{first}"]').click()
        page.locator(f"#p-{first}").wait_for(state="visible")
        expect(page.locator("#dockMore")).to_have_class("dk more on")
        assert c.errors == [] and c.csp_violations() == []
    finally:
        c.close()


def _assert_folding(c: Console, s: dict[str, Any], dock: Dock) -> list[str]:
    """The dock shows the tabs the measured rule expects (dock_rule.py) in dock order, More only
    when a tab is folded, and the sheet lists exactly the folded tabs: every panel is reachable
    exactly once. Returns the folded tabs, in dock order."""
    order, visible = s["order"], s["visible"]
    assert sorted(order) == sorted(s["panels"]) and len(order) == len(set(order))
    assert [t.id for t in dock.tabs] == order, order
    assert_follows_rule(dock, visible)
    # dock order kept: a tab whose label overflows it folds wherever it sits; of the others the
    # last ones fold first
    over = overflowing(dock)
    holding = [t for t in order if t not in over]
    assert visible == holding[: len(visible)], (visible, over)
    for pinned in PINNED:  # never folded for lack of room; Approvals only where its label
        assert (pinned in visible) is (pinned not in over), (pinned, visible)  # overflows
    folded = [t for t in order if t not in visible]
    assert s["more"] is bool(folded), (s["more"], folded)
    sheet = _sheet_entries(c) if folded else []
    assert sheet == folded, (sheet, folded)  # exactly the folded tabs, in dock order
    reachable = visible + sheet
    assert sorted(reachable) == sorted(order) and len(reachable) == len(set(reachable))
    return folded


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
        # test-only: no label outgrows its tab on any renderer, so the full-HD dock shows every tab
        # and More can go (GitHub's Chromium folds CONNECTORS there for its label, and More stays)
        _hold_every_label(page)
        s = page.evaluate(STATE_JS)
        assert s["more"] is False and s["visible"] == s["order"], s["visible"]
        page.locator('.dk[data-open="construct"]').focus()
        for width, height in ((1280, 800), (390, 844), (1024, 768), (320, 568)):
            page.set_viewport_size({"width": width, "height": height})
            page.evaluate(SETTLE_JS)
            s = page.evaluate(STATE_JS)
            _assert_fits(s, width)
            assert_follows_rule(measure_dock(page), s["visible"])
            assert s["more"] is True and "construct" not in s["visible"], (width, s["visible"])
        # a focused tab that folds hands its focus to More, never to the page
        assert page.evaluate("document.activeElement.id") == "dockMore"
        page.set_viewport_size({"width": 1920, "height": 1080})
        page.evaluate(SETTLE_JS)
        s = page.evaluate(STATE_JS)
        assert s["more"] is False and s["visible"] == s["order"], s["visible"]
        # More went with the focus on it: the last tab takes it
        assert page.evaluate("document.activeElement.dataset.open") == "construct"
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


def test_an_open_sheet_closes_when_everything_fits_and_focus_lands_on_the_tab(
    browser: Any, server_url: str, token: str
) -> None:
    c = _console(browser, server_url, token, 1280)
    page = c.page
    try:
        # test-only: with every label holding its 78 px tab, everything fits 1920 on any renderer
        # (desktop tabs are the same size at 1280 and 1920, so the check here holds there too)
        _hold_every_label(page)
        page.locator("#dockMore").click()
        page.locator("#moreSheet").wait_for(state="visible")
        first = page.evaluate("document.activeElement.dataset.sheetOpen")
        page.set_viewport_size({"width": 1920, "height": 1080})
        page.locator("#moreSheet").wait_for(state="hidden")
        page.evaluate(SETTLE_JS)
        assert page.locator("#dockMore").is_hidden()
        assert page.evaluate("document.activeElement.dataset.open") == first
        assert c.errors == []
    finally:
        c.close()


def test_more_names_every_open_folded_panel_in_dock_order(
    browser: Any, server_url: str, token: str
) -> None:
    # a desktop shows several panels at once: More's name lists each open folded one (review A, L2)
    c = _console(browser, server_url, token, 1280)
    page, more = c.page, c.page.locator("#dockMore")
    try:
        order, visible = page.evaluate(STATE_JS)["order"], page.evaluate(STATE_JS)["visible"]
        first, second = [t for t in order if t not in visible][:2]
        for panel in (second, first):  # opened out of dock order
            more.click()
            page.locator(f'#moreSheet [data-sheet-open="{panel}"]').click()
            page.locator(f"#p-{panel}").wait_for(state="visible")
        titles = [page.locator(f"#p-{p} .ptitle h2").text_content() for p in (first, second)]
        expect(more).to_have_attribute("aria-label", f"More panels, {titles[0]}, {titles[1]} shown")
        page.locator(f"#p-{first} [data-close]").click()
        expect(more).to_have_attribute("aria-label", f"More panels, {titles[1]} shown")
        assert c.errors == []
    finally:
        c.close()


# Sets the waiting count and reads the badge in one go: the page's own approvals poll can change
# the count between two separate reads. More's name follows in a mutation-observer microtask.
BADGE_JS = """async (n) => {
  document.dispatchEvent(new CustomEvent('jarvis:approvals', {detail: {count: n}}));
  await Promise.resolve();
  const b = document.getElementById('dockBadge'), holder = b.closest('.dk');
  const r = holder.getBoundingClientRect();
  return {shown: !b.hidden && b.getClientRects().length > 0, text: b.textContent,
          holder: holder.dataset.open || holder.id, l: r.left, r: r.right,
          tabShown: !document.querySelector('.dk[data-open="approvals"]').hidden,
          more: document.getElementById('dockMore').getAttribute('aria-label')};
}"""


@pytest.mark.parametrize("width", [1280, 1024, 320])
def test_the_approvals_badge_stays_on_screen(
    browser: Any, server_url: str, token: str, width: int
) -> None:
    c = _console(browser, server_url, token, width)
    try:
        b = c.page.evaluate(BADGE_JS, 3)
        assert b["shown"] and b["text"] == "3", b
        assert 0 <= b["l"] and b["r"] <= width, b
        # its tab carries it; where the APPROVALS label is wider than the tab (900-1180 px) the
        # tab is behind More, and More carries the badge and says so in its name
        assert b["tabShown"] is (width != 1024), b
        assert b["holder"] == ("dockMore" if width == 1024 else "approvals"), b
        if width == 1024:
            assert b["more"] == "More panels, Approvals 3 waiting", b
            b = c.page.evaluate(BADGE_JS, 0)
            assert not b["shown"] and b["more"] == "More panels", b
        assert c.errors == []
    finally:
        c.close()


# ---- before console-dock.js has run (code review L5) --------------------------------------------
# The script is deferred: on a slow network or a cold cache the page can paint while it is still on
# its way, with every tab showing. Desktop tabs keep their sizes (flex: none), so they used to run
# hundreds of px past the dock's right edge (264 px at 1440, 424 px at 1280). The guard is CSS
# only: until the first fit the dock clips them. It keeps the dock's size (console-deck.js, which
# runs first, sizes the panels from the dock's top) and never matches once the fit has run.
EARLY_JS = """() => {
  const d = document.getElementById('dock'), r = d.getBoundingClientRect();
  const tabs = [...d.querySelectorAll('.dk')].filter((t) => t.getClientRects().length);
  const box = (e) => {
    const b = e.getBoundingClientRect();
    return {l: b.left, r: b.right, t: b.top};
  };
  return {ready: document.readyState, vw: innerWidth, left: r.left, right: r.right, top: r.top,
          bottom: r.bottom, boxes: tabs.map(box), rows: new Set(tabs.map((t) => box(t).t)).size,
          overflowX: getComputedStyle(d).overflowX,
          panelMax: getComputedStyle(document.documentElement).getPropertyValue('--panel-max-h'),
          pageScroll: document.documentElement.scrollWidth - document.documentElement.clientWidth};
}"""


@pytest.mark.parametrize("width", [w for w in WIDTHS if w >= PHONE_BELOW])
def test_before_its_script_runs_no_tab_shows_past_the_dock(
    browser: Any, server_url: str, width: int
) -> None:
    ctx = browser.new_context(viewport={"width": width, "height": WIDTHS[width]})
    page = ctx.new_page()
    try:
        held: list[Any] = []
        page.route("**/static/console-dock.js", lambda route: held.append(route))  # on its way
        page.goto(server_url + "/", wait_until="commit")
        page.wait_for_function("document.readyState !== 'loading'")
        page.evaluate(SETTLE_JS)
        early = page.evaluate(EARLY_JS)
        assert held and early["ready"] == "interactive", early["ready"]  # painted, not yet fitted
        assert len(early["boxes"]) == 20 and early["rows"] == 1  # every tab, More still hidden
        assert early["overflowX"] == "clip", early  # what runs past the dock is not painted
        assert early["right"] <= early["vw"] and early["pageScroll"] <= 0, early

        for route in held:
            route.continue_()
        page.wait_for_load_state("load")
        page.evaluate(SETTLE_JS)
        after = page.evaluate(EARLY_JS)
        assert after["overflowX"] == "visible" and after["rows"] == 1, after  # the guard is off
        # the dock kept its size, so the panels were sized from the right room
        assert (after["top"], after["bottom"]) == (early["top"], early["bottom"]), (early, after)
        assert after["panelMax"] == early["panelMax"]
    finally:
        page.unroute_all(behavior="ignoreErrors")  # a failed check leaves the script held
        ctx.close()
