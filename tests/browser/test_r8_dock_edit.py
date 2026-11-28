# tests/browser/test_r8_dock_edit.py -- R8 I, "your bar, your way" (docs/plans/r8-vision.md v8.0.4
# D13; the owner, 28 Nov 2026: "make every icon editable ... drag and drop each item and place it as
# per my requirement. Also, the items I remove should be in the More. I should also have the option
# to hide the bar as well."). The editor in the real console, in Chromium: until he edits it the
# 1920 px bar is byte-identical to the bar before part I (its markup, places and pixels, Night and
# Day: the page with the I0 stub editor served instead is the reference); a right-click, Ctrl +
# Shift + . and the Appearance menu open editing, and a long-press does on a phone (the list
# editor); a drag, a keyboard step, the x, Delete and a drop on More move or take items off; More
# then lists them with Put back; Reset to default (with Undo) and Put back bring the shipped bar
# back and remove the saved key; Hide the bar leaves a handle and Ctrl + . shows it again; a layout
# kept on this device comes back after a reload, a tab it doesn't know at the end.
from __future__ import annotations

import json
from collections.abc import Iterator
from typing import Any

import pytest
from test_console import Console

_pw = pytest.importorskip("playwright.sync_api")
sync_playwright = _pw.sync_playwright
expect = _pw.expect

pytestmark = pytest.mark.browser

KEY = "jarvis_dock_layout_v1"
FULL_HD = {"width": 1920, "height": 1080}
NARROW = {
    "width": 1366,
    "height": 768,
}  # More shows here (tabs fold), so a drop on More can be tried
PHONE = {"width": 390, "height": 844}
STUB = "export const KEY = 'jarvis_dock_layout_v1';\n"  # the editor as I0 left it: it draws nothing
SETTLE_JS = (
    "() => document.fonts.ready.then(() => new Promise("
    "(r) => requestAnimationFrame(() => requestAnimationFrame(r))))"
)
BAR_JS = """() => {
  const d = document.getElementById('dock');
  const box = (e) => {
    const r = e.getBoundingClientRect();
    return [r.left, r.top, r.width, r.height];
  };
  const items = [...d.children].filter((e) => e.getClientRects().length > 0);
  const name = (e) => e.dataset.open || e.id || e.className;
  return {dock: box(d), items: items.map((e) => [name(e), ...box(e)])};
}"""
STATE_JS = "() => window.JarvisDock.state()"
SHOWN_JS = "() => !!window.JarvisDock && document.getElementById('dock').style.visibility === ''"
SAVED_JS = f"() => localStorage.getItem('{KEY}')"
DOCK_ALONE = (
    "body * { visibility: hidden !important } #dock, #dock * { visibility: visible !important }"
)


@pytest.fixture(scope="module")
def browser() -> Iterator[Any]:
    with sync_playwright() as p:
        b = p.chromium.launch()
        yield b
        b.close()


def _open(
    browser: Any,
    url: str,
    token: str,
    view: dict[str, int],
    surface: str = "night",
    stub: bool = False,
    saved: dict[str, Any] | None = None,
    touch: bool = False,
) -> Console:
    c = Console(browser, url, token, view)
    if touch:  # a phone: touch events and the phone layout
        c.ctx.close()
        c.ctx = browser.new_context(viewport=view, has_touch=True, is_mobile=True)
        c.page = c.ctx.new_page()
        c.page.on("pageerror", lambda e: c.errors.append(f"pageerror: {e}"))
    c.page.add_init_script(f"localStorage.setItem('jarvis_surface', '{surface}');")
    if saved is not None:
        c.page.add_init_script(
            f"if (!sessionStorage.getItem('seeded')) {{ sessionStorage.setItem('seeded', '1');"
            f" localStorage.setItem('{KEY}', {json.dumps(json.dumps(saved))}); }}"
        )
    if stub:
        c.page.route(
            "**/static/console-dock-edit.js",
            lambda r: r.fulfill(status=200, content_type="text/javascript", body=STUB),
        )
    c.open()
    c.page.wait_for_function("() => !!window.JarvisDock")
    c.page.evaluate(SETTLE_JS)
    return c


def _ready(c: Console) -> None:
    """The editor module has loaded (it adds the settings line to the Appearance menu)."""
    c.page.wait_for_function("() => !!document.getElementById('jxBar')")


def _tab(c: Console, tab_id: str) -> Any:
    return c.page.locator(f'#dock .dk[data-open="{tab_id}"]')


def _centre(locator: Any) -> tuple[float, float]:
    b = locator.bounding_box()
    assert b is not None
    return b["x"] + b["width"] / 2, b["y"] + b["height"] / 2


def _edit_by_right_click(c: Console, on: str = "vitals") -> None:
    _ready(c)
    _tab(c, on).click(button="right")
    menu = c.page.locator(".dke-ctx")
    expect(menu).to_be_visible()
    expect(menu.get_by_role("menuitem", name="Edit the bar")).to_be_focused()
    menu.get_by_role("menuitem", name="Edit the bar").click()
    expect(c.page.locator("#dock.dke-edit")).to_have_count(1)
    expect(c.page.locator(".dke-tools")).to_be_visible()


def _drag(c: Console, src: Any, x: float, y: float) -> None:
    sx, sy = _centre(src)
    c.page.mouse.move(sx, sy)
    c.page.mouse.down()
    c.page.mouse.move(sx + 3, sy, steps=2)  # under 8 px: still a click
    c.page.mouse.move(x, y, steps=12)
    c.page.mouse.up()


def _order(c: Console) -> list[str]:
    order: list[str] = c.page.evaluate(STATE_JS)["order"]
    return order


def _dock_shot(c: Console) -> bytes:
    c.page.add_style_tag(content=DOCK_ALONE)
    c.page.mouse.move(0, 0)
    c.page.evaluate(SETTLE_JS)
    shot: bytes = c.page.locator("#dock").screenshot(animations="disabled", caret="hide")
    return shot


def _fresh_bar(browser: Any, url: str, token: str, view: dict[str, int]) -> Any:
    ref = _open(browser, url, token, view, stub=True)
    try:
        return ref.page.evaluate(BAR_JS), ref.page.evaluate(
            "() => document.getElementById('dock').outerHTML"
        )
    finally:
        ref.close()


# ---- the hard rule: the default bar at 1920 px is byte-identical until he edits it ---------------
@pytest.mark.parametrize("surface", ["night", "day"])
def test_until_he_edits_it_the_1920_bar_is_byte_identical(
    browser: Any, server_url: str, token: str, surface: str
) -> None:
    now = _open(browser, server_url, token, FULL_HD, surface)
    before = _open(browser, server_url, token, FULL_HD, surface, stub=True)
    try:
        _ready(now)
        html = "() => document.getElementById('dock').outerHTML"
        assert now.page.evaluate(BAR_JS) == before.page.evaluate(BAR_JS)
        assert now.page.evaluate(html) == before.page.evaluate(html)
        assert now.page.locator("#dockMore").is_hidden()  # More keeps today's behaviour
        _tab(now, "vitals").click(
            button="right"
        )  # opening the bar's menu and leaving it changes nothing
        expect(now.page.locator(".dke-ctx")).to_be_visible()
        now.page.keyboard.press("Escape")
        expect(now.page.locator(".dke-ctx")).to_have_count(0)
        expect(_tab(now, "vitals")).to_be_focused()  # focus back where the menu came from
        assert now.page.evaluate(SAVED_JS) is None  # nothing written
        assert now.page.evaluate(html) == before.page.evaluate(html)
        now.page.evaluate("() => document.activeElement.blur()")
        assert _dock_shot(now) == _dock_shot(before), "the dock's pixels differ before an edit"
        assert now.errors == [] and before.errors == [] and now.csp_violations() == []
    finally:
        now.close()
        before.close()


# ---- drag and drop, kept on this device ----------------------------------------------------------
def test_a_right_click_edits_and_a_drag_moves_an_item_kept_after_a_reload(
    browser: Any, server_url: str, token: str
) -> None:
    c = _open(browser, server_url, token, FULL_HD)
    try:
        _edit_by_right_click(c)
        expect(_tab(c, "vitals").locator(".dke-grip")).to_have_count(1)
        bx, by = _centre(_tab(c, "approvals"))
        aw = _tab(c, "approvals").bounding_box()["width"]
        _drag(c, _tab(c, "vitals"), bx - aw / 2 + 4, by)  # onto Approvals' left half
        order = _order(c)
        assert order[:4] == ["chat", "brief", "vitals", "approvals"], order
        assert (
            "Vitals is 3rd now, between Brief and Approvals."
            in c.page.locator("#dkeSay").inner_text()
        )
        assert json.loads(c.page.evaluate(SAVED_JS))["order"][:3] == ["chat", "brief", "vitals"]
        assert c.page.locator("#p-vitals").is_hidden()  # editing never opened the panel
        c.page.locator(".dke-tools").get_by_role("button", name="Done").click()
        expect(c.page.locator("#dock.dke-edit")).to_have_count(0)
        assert c.page.locator("#dock .dke-grip, #dock .dke-x").count() == 0
        c.page.reload()
        c.page.locator("#welcome, #tokIn").first.wait_for()
        c.page.wait_for_function(SHOWN_JS)  # the bar waits unseen for his layout, then shows
        c.page.evaluate(SETTLE_JS)
        assert _order(c)[:4] == ["chat", "brief", "vitals", "approvals"]
        expect(_tab(c, "vitals")).to_be_visible()
        _tab(c, "vitals").click()  # out of editing, a press opens the panel as ever
        expect(c.page.locator("#p-vitals")).to_be_visible()
        assert c.errors == [] and c.csp_violations() == []
    finally:
        c.close()


def test_a_drop_on_more_takes_an_item_off_and_put_back_restores_the_shipped_bar(
    browser: Any, server_url: str, token: str
) -> None:
    c = _open(browser, server_url, token, NARROW)
    try:
        before_bar, before_html = _fresh_bar(browser, server_url, token, NARROW)
        assert c.page.locator("#dockMore").is_visible()  # tabs fold at 1366
        _edit_by_right_click(c, "construct" if _tab(c, "construct").is_visible() else "vault")
        mx, my = _centre(c.page.locator("#dockMore"))
        _drag(c, _tab(c, "vault"), mx, my)
        state = c.page.evaluate(STATE_JS)
        assert state["removed"] == ["vault"] and "vault" not in state["shown"]
        assert "Vault is off the bar" in c.page.locator("#dkeSay").inner_text()
        c.page.keyboard.press("Escape")  # ends editing
        expect(c.page.locator("#dock.dke-edit")).to_have_count(0)
        c.page.locator("#dockMore").click()
        sheet = c.page.locator("#moreSheet")
        expect(sheet.locator("h3.dke-sub").first).to_have_text("Taken off the bar")
        row = sheet.locator('.dke-off[data-id="vault"]')
        expect(row.locator(".dke-open")).to_be_focused()
        assert sheet.locator('[data-sheet-open="vault"]').is_hidden()  # listed once, with Put back
        row.get_by_role("button", name="Put Vault back on the bar").click()
        c.page.evaluate(SETTLE_JS)
        assert c.page.evaluate(SAVED_JS) is None  # the shipped bar again: nothing kept
        if sheet.is_visible():  # More still shows for the tabs this width folds: focus stays in it
            expect(sheet.locator("[data-sheet-open]:not([hidden])").first).to_be_focused()
            sheet.get_by_role("button", name="Close").click()
            expect(sheet).to_be_hidden()
        assert c.page.evaluate(BAR_JS) == before_bar
        assert c.page.evaluate("() => document.getElementById('dock').outerHTML") == before_html
        assert c.errors == [] and c.csp_violations() == []
    finally:
        c.close()


# ---- the keyboard way ----------------------------------------------------------------------------
def test_the_keyboard_edits_moves_removes_and_chat_stays(
    browser: Any, server_url: str, token: str
) -> None:
    c = _open(browser, server_url, token, FULL_HD)
    page = c.page
    try:
        _ready(c)
        page.locator("#input").focus()
        page.keyboard.press("Control+Shift+Period")
        expect(page.locator("#dock.dke-edit")).to_have_count(1)
        expect(_tab(c, "chat")).to_be_focused()
        page.keyboard.press("Delete")  # Chat can't leave the bar
        assert "Chat stays on the bar" in page.locator("#dkeSay").inner_text()
        assert "chat" in page.evaluate(STATE_JS)["shown"]
        page.keyboard.press("ArrowRight")
        expect(_tab(c, "brief")).to_be_focused()
        assert "Brief, 2nd of 23." in page.locator("#dkeSay").inner_text()
        page.keyboard.press("Shift+ArrowRight")
        expect(_tab(c, "brief")).to_be_focused()
        assert _order(c)[:3] == ["chat", "approvals", "brief"]
        page.keyboard.press("Enter")  # the Move panel
        panel = page.locator(".dke-keys")
        expect(panel).to_be_visible()
        panel.get_by_role("button", name="Move left").click()
        assert _order(c)[:3] == ["chat", "brief", "approvals"]
        _tab(c, "construct").focus()
        page.keyboard.press("Delete")
        state = page.evaluate(STATE_JS)
        assert state["removed"] == ["construct"] and state["more"] is True
        expect(page.locator("#dockMore")).to_be_visible()  # More shows: he took one off
        undo = page.locator("#dkeSay").get_by_role("button", name="Undo")
        undo.click()
        assert page.evaluate(STATE_JS)["removed"] == []
        page.keyboard.press("Escape")
        expect(page.locator("#dock.dke-edit")).to_have_count(0)
        assert page.evaluate(SAVED_JS) is None  # back to the shipped order: nothing kept
        assert c.errors == [] and c.csp_violations() == []
    finally:
        c.close()


def test_reset_to_default_brings_the_shipped_bar_back_with_an_undo(
    browser: Any, server_url: str, token: str
) -> None:
    saved = {"v": 1, "order": ["camera", "chat", "brief"], "more": ["vault"], "hidden": False}
    c = _open(browser, server_url, token, FULL_HD, saved=saved)
    try:
        before_bar, _ = _fresh_bar(browser, server_url, token, FULL_HD)
        _ready(c)
        assert _order(c)[:3] == ["camera", "chat", "brief"]  # his order; the rest after it
        assert c.page.evaluate(STATE_JS)["removed"] == ["vault"]
        c.page.locator("#themeBtn").click()  # the settings line
        c.page.locator("#jxBar").click()
        expect(c.page.locator("#dock.dke-edit")).to_have_count(1)
        c.page.locator(".dke-tools").get_by_role("button", name="Reset to default").click()
        assert c.page.evaluate(SAVED_JS) is None
        assert "Back to the shipped bar." in c.page.locator("#dkeSay").inner_text()
        c.page.locator("#dkeSay").get_by_role("button", name="Undo").click()
        assert _order(c)[0] == "camera" and json.loads(c.page.evaluate(SAVED_JS))["more"] == [
            "vault"
        ]
        c.page.locator(".dke-tools").get_by_role("button", name="Reset to default").click()
        c.page.locator(".dke-tools").get_by_role("button", name="Done").click()
        c.page.evaluate(SETTLE_JS)
        assert c.page.evaluate(BAR_JS) == before_bar
        assert c.errors == [] and c.csp_violations() == []
    finally:
        c.close()


# ---- hide and show -------------------------------------------------------------------------------
def test_hide_the_bar_leaves_a_handle_and_ctrl_dot_shows_it_again(
    browser: Any, server_url: str, token: str
) -> None:
    c = _open(browser, server_url, token, FULL_HD)
    page = c.page
    try:
        _edit_by_right_click(c)
        page.locator(".dke-tools").get_by_role("button", name="Hide the bar").click()
        expect(page.locator("#dock")).to_be_hidden()
        handle = page.get_by_role("button", name="Show the bar")
        expect(handle).to_be_visible()
        expect(handle).to_be_focused()
        expect(page.locator("#dkeHandleTip")).to_be_visible()  # its tip says how
        assert json.loads(page.evaluate(SAVED_JS))["hidden"] is True
        page.reload()
        page.locator("#welcome, #tokIn").first.wait_for()
        expect(page.get_by_role("button", name="Show the bar")).to_be_visible()
        expect(page.locator("#dock")).to_be_hidden()  # kept on this device
        page.locator("#input").focus()
        page.keyboard.press("Control+Period")
        expect(page.locator("#dock")).to_be_visible()
        expect(page.get_by_role("button", name="Show the bar")).to_have_count(0)
        assert page.evaluate(SAVED_JS) is None
        _tab(c, "vitals").click(button="right")  # the menu hides it too; the handle shows it
        page.locator(".dke-ctx").get_by_role("menuitem", name="Hide the bar").click()
        expect(page.locator("#dock")).to_be_hidden()
        page.get_by_role("button", name="Show the bar").click()
        expect(page.locator("#dock")).to_be_visible()
        assert c.errors == [] and c.csp_violations() == []
    finally:
        c.close()


# ---- a phone: long-press, the list editor --------------------------------------------------------
def _long_press(c: Console, locator: Any) -> None:
    x, y = _centre(locator)
    cdp = c.ctx.new_cdp_session(c.page)
    cdp.send("Input.dispatchTouchEvent", {"type": "touchStart", "touchPoints": [{"x": x, "y": y}]})
    c.page.wait_for_timeout(750)
    cdp.send("Input.dispatchTouchEvent", {"type": "touchEnd", "touchPoints": []})
    # Chromium follows the lift with a mousedown and a click where the finger was, now on the list:
    # the editor takes no press until a moment after the lift (then a person's next tap is a tap)
    c.page.wait_for_timeout(450)


def test_a_long_press_on_a_phone_opens_the_list_editor(
    browser: Any, server_url: str, token: str
) -> None:
    c = _open(browser, server_url, token, PHONE, touch=True)
    page = c.page
    try:
        _ready(c)
        _long_press(c, _tab(c, "brief"))
        ed = page.locator("#dockEdit")
        expect(ed).to_be_visible()
        assert page.locator("#p-brief").is_hidden()  # the press never opened Brief
        assert page.evaluate(STATE_JS)["removed"] == []  # and its lift pressed nothing in the list
        expect(ed.locator('[data-id="brief"] .dke-hold')).to_be_focused()
        expect(ed.locator(".dke-fold")).to_have_text("This phone's bar ends here")
        rows = ed.locator(".dke-row")
        assert rows.count() == 23
        chat_x = ed.locator('[data-id="chat"] .dke-del')
        expect(chat_x).to_have_attribute("aria-disabled", "true")
        ed.locator('[data-id="vitals"]').get_by_role(
            "button", name="Take Vitals off the bar"
        ).click()
        expect(ed.locator('.dke-offs [data-id="vitals"]')).to_be_visible()
        ed.locator('[data-id="brief"] .dke-hold').focus()
        page.keyboard.press("Shift+ArrowDown")
        assert _order(c)[:3] == ["chat", "approvals", "brief"]
        ed.locator('[data-id="approvals"] .dke-hold').click()  # tap: Move up / down / to More
        ed.locator('[data-id="approvals"]').get_by_role("button", name="Move up").click()
        assert _order(c)[:2] == ["approvals", "chat"]
        ed.get_by_role("button", name="Done").click()
        expect(ed).to_be_hidden()
        state = page.evaluate(STATE_JS)
        assert state["removed"] == ["vitals"] and state["order"][0] == "approvals"
        page.locator("#dockMore").click()
        expect(page.locator('#moreSheet .dke-off[data-id="vitals"]')).to_be_visible()
        assert c.errors == []
    finally:
        c.close()


def test_a_saved_layout_missing_a_tab_puts_that_tab_at_the_end(
    browser: Any, server_url: str, token: str
) -> None:
    # a layout kept before a later release added its tab: the new tab is appended, never lost
    shipped = _open(browser, server_url, token, FULL_HD, stub=True).page
    ids: list[str] = shipped.evaluate("() => window.JarvisDock.shipped()")
    shipped.context.close()
    older = [t for t in ids if t != "helpers"]
    saved = {"v": 1, "order": older, "more": [], "hidden": False}
    c = _open(browser, server_url, token, FULL_HD, saved=saved)
    try:
        _ready(c)
        assert _order(c) == [*older, "helpers"]
        assert c.errors == []
    finally:
        c.close()
