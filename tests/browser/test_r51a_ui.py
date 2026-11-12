# tests/browser/test_r51a_ui.py -- R5.1 Part A in a real browser: the Privacy panel (#1), the top-bar
# brain pill (D9), Connectors (#5 #6 #12 #25) and People (#8 #9 #11). The R4 routes are faked with
# page.route (shared mocks: ui_checks.py). The stylesheets are the ones console.html links and the
# /static allow-list serves (tests/test_r51_console_assets_linked.py), nothing is injected.
# ruff: noqa: E501 -- long JS strings and selectors
from __future__ import annotations

import json
from collections.abc import Iterator
from typing import Any

import pytest
from test_console import DESKTOP, PHONE, Console
from ui_checks import MOCK_CONNECTORS, install_mocks

_pw = pytest.importorskip("playwright.sync_api")
sync_playwright, expect = _pw.sync_playwright, _pw.expect

pytestmark = pytest.mark.browser

MEANING = {"ai": "AI on: JARVIS reasons.", "none": "No-AI: fixed rules only."}


@pytest.fixture(scope="module")
def browser() -> Iterator[Any]:
    with sync_playwright() as p:
        b = p.chromium.launch()
        yield b
        b.close()


class Brain:
    """A stateful fake of /v1/settings/brain-mode that records every POST body."""

    def __init__(self) -> None:
        self.mode = "ai"
        self.posts: list[dict[str, str]] = []
        self.fail_get = False  # GET answers 500
        self.fail_post = False  # POST answers 500 (and changes nothing)
        self.hold_post = False  # park POSTs until release()
        self.held: list[Any] = []

    def release(self) -> None:
        held, self.held = self.held, []
        for route, body in held:
            self.mode = body["mode"]
            self._ok(route)

    def _ok(self, route: Any) -> None:
        route.fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps({"mode": self.mode, "meaning": MEANING[self.mode]}),
        )

    def __call__(self, route: Any) -> None:
        if route.request.method == "GET" and self.fail_get:
            route.fulfill(status=500, content_type="application/json", body='{"detail":"x"}')
            return
        if route.request.method == "POST":
            body = json.loads(route.request.post_data or "{}")
            self.posts.append(body)
            if self.fail_post:
                route.fulfill(status=500, content_type="application/json", body='{"detail":"x"}')
                return
            if self.hold_post:
                self.held.append((route, body))
                return
            self.mode = body["mode"]
        route.fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps({"mode": self.mode, "meaning": MEANING[self.mode]}),
        )


def boot(
    browser: Any,
    url: str,
    token: str,
    vp: dict[str, int],
    *,
    connectors: dict[str, Any] | None = None,
) -> tuple[Console, Brain]:
    c = Console(browser, url, token, vp)
    install_mocks(c.page)
    brain = Brain()
    c.page.route("**/v1/settings/brain-mode", brain)
    if connectors is not None:
        c.page.route(
            "**/v1/connectors",
            lambda r: (
                r.fulfill(status=200, content_type="application/json", body=json.dumps(connectors))
                if r.request.method == "GET"
                else r.continue_()
            ),
        )
    c.open()
    c.page.locator("#brainModeBadge").wait_for()
    # the pill says "Brain: ..." until the server has answered (it never claims a mode before): wait
    # for that answer, or the "unknown" of a failed read, before a test looks at it (a slow CI runner
    # reached the assertions first)
    c.page.wait_for_function(
        "() => { const b = document.getElementById('brainModeBadge');"
        " return !!b && (b.getAttribute('aria-label') || '') !== 'Brain: reading the mode'; }"
    )
    expect(c.page.locator("#brainModeBadge").first).to_contain_text("AI", ignore_case=True)
    return c, brain


def overlaps(c: Console, panel: str) -> list[str]:
    """Visible interactive elements of a panel whose painted boxes overlap."""
    return list(
        c.page.evaluate(
            """(sel) => {
          const els = [...document.querySelectorAll(sel + ' button, ' + sel + ' input, ' + sel + ' a[href], ' + sel + ' select')]
            .filter((e) => { const r = e.getBoundingClientRect(); return r.width > 1 && r.height > 1 && getComputedStyle(e).visibility !== 'hidden'; });
          const out = [];
          for (let i = 0; i < els.length; i++) for (let j = i + 1; j < els.length; j++) {
            const a = els[i].getBoundingClientRect(), b = els[j].getBoundingClientRect();
            if (Math.min(a.right, b.right) - Math.max(a.left, b.left) > 1 && Math.min(a.bottom, b.bottom) - Math.max(a.top, b.top) > 1)
              out.push((els[i].textContent || els[i].id) + ' x ' + (els[j].textContent || els[j].id));
          }
          return out;
        }""",
            f"#p-{panel}",
        )
    )


# ---- #1 Privacy ----------------------------------------------------------------------------------
@pytest.mark.parametrize("vp", [DESKTOP, PHONE], ids=["desktop", "phone"])
def test_privacy_panel_is_not_collapsed_to_a_swatch(
    browser: Any, server_url: str, token: str, vp: dict[str, int]
) -> None:
    c, _ = boot(browser, server_url, token, vp)
    c.open_panel("privacy")
    root = c.page.locator("#pvRoot")
    root.wait_for()
    c.page.wait_for_timeout(500)
    assert root.bounding_box()["width"] > 250  # type: ignore[index]
    assert root.bounding_box()["height"] > 100  # type: ignore[index]
    card = c.page.locator("#pvRoot .pv-card").first
    card.wait_for()
    box = card.bounding_box()
    assert box is not None and box["width"] > 150 and box["height"] > 20
    assert (
        c.page.evaluate("getComputedStyle(document.querySelector('#pvRoot')).overflow") != "hidden"
    )
    c.close()


def test_appearance_swatches_keep_their_size(browser: Any, server_url: str, token: str) -> None:
    c, _ = boot(browser, server_url, token, DESKTOP)
    c.page.locator("#themeBtn").click()
    sw = c.page.locator("#themeMenu .pv").first
    sw.wait_for()
    box = sw.bounding_box()
    assert box is not None and abs(box["width"] - 56) < 2.5 and abs(box["height"] - 38) < 2.5
    c.close()


# ---- D9 the brain pill --------------------------------------------------------------------------
def test_brain_pill_is_one_button_in_the_status_pill_style(
    browser: Any, server_url: str, token: str
) -> None:
    c, _ = boot(browser, server_url, token, DESKTOP)
    pill = c.page.locator("#brainModeBadge")
    assert pill.evaluate("e => e.tagName") == "BUTTON"
    assert c.page.locator("#brainModeSlot .bnote").count() == 0
    assert pill.get_attribute("aria-haspopup") == "menu"
    assert pill.get_attribute("aria-expanded") == "false"
    assert "brain: ai on" in str(pill.inner_text()).lower()
    h = pill.bounding_box()["height"]  # type: ignore[index]
    ref = c.page.locator("#status").bounding_box()["height"]  # type: ignore[index]
    assert round(h) == round(ref) == 26
    assert pill.evaluate("e => getComputedStyle(e).fontFamily") == c.page.locator(
        "#status"
    ).evaluate("e => getComputedStyle(e).fontFamily")
    c.close()


def test_choosing_no_ai_switches_at_once_with_the_right_body(
    browser: Any, server_url: str, token: str
) -> None:
    c, brain = boot(browser, server_url, token, DESKTOP)
    c.page.locator("#brainModeBadge").click()
    menu = c.page.locator("#brainMenu")
    menu.wait_for()
    assert c.page.locator("#brainModeBadge").get_attribute("aria-expanded") == "true"
    assert menu.locator("[role=menuitemradio]").count() == 2
    c.page.locator("#brainMenu .bmopt[data-mode=none]").click()
    expect(c.page.locator("#brainModeBadge").first).to_contain_text("No-AI", ignore_case=True)
    assert brain.posts == [{"mode": "none"}]
    pill = c.page.locator("#brainModeBadge")
    assert "alert" in str(pill.get_attribute("class"))
    assert menu.is_hidden()
    assert pill.get_attribute("aria-expanded") == "false"
    c.close()


def test_switching_ai_back_on_asks_once_first(browser: Any, server_url: str, token: str) -> None:
    c, brain = boot(browser, server_url, token, DESKTOP)
    c.page.locator("#brainModeBadge").click()
    c.page.locator("#brainMenu .bmopt[data-mode=none]").click()
    expect(c.page.locator("#brainModeBadge").first).to_contain_text("No-AI", ignore_case=True)
    c.page.locator("#brainModeBadge").click()
    c.page.locator("#brainMenu .bmopt[data-mode=ai]").click()
    ask = c.page.locator("#brainMenu .bmask")
    ask.wait_for()
    assert "Paid replies resume" in str(ask.inner_text())
    assert brain.posts == [{"mode": "none"}]  # nothing sent yet
    ask.get_by_role("button", name="Cancel").click()
    assert brain.posts == [{"mode": "none"}]
    c.page.locator("#brainMenu .bmopt[data-mode=ai]").click()
    c.page.get_by_role("button", name="Switch on").click()
    expect(c.page.locator("#brainModeBadge").first).to_contain_text("AI on", ignore_case=True)
    assert brain.posts == [{"mode": "none"}, {"mode": "ai"}]
    c.close()


def test_brain_menu_keyboard_escape_and_click_outside(
    browser: Any, server_url: str, token: str
) -> None:
    c, _ = boot(browser, server_url, token, DESKTOP)
    pill = c.page.locator("#brainModeBadge")
    pill.focus()
    c.page.keyboard.press("Enter")
    c.page.locator("#brainMenu").wait_for()
    assert c.page.evaluate("document.activeElement.dataset.mode") == "ai"
    c.page.keyboard.press("ArrowDown")
    assert c.page.evaluate("document.activeElement.dataset.mode") == "none"
    c.page.keyboard.press("ArrowDown")  # wraps
    assert c.page.evaluate("document.activeElement.dataset.mode") == "ai"
    c.page.keyboard.press("Escape")
    assert c.page.locator("#brainMenu").is_hidden()
    assert c.page.evaluate("document.activeElement.id") == "brainModeBadge"
    pill.click()
    c.page.locator("#brainMenu").wait_for()
    c.page.locator("#log").click(position={"x": 5, "y": 5}, force=True)
    assert c.page.locator("#brainMenu").is_hidden()
    assert pill.get_attribute("aria-expanded") == "false"
    c.close()


def test_people_buttons_follow_the_pill_and_the_ai_button_asks_first(
    browser: Any, server_url: str, token: str
) -> None:
    c, brain = boot(browser, server_url, token, DESKTOP)
    c.open_panel("people")
    assert c.page.locator("#modeAi").get_attribute("aria-pressed") == "true"
    c.page.locator("#brainModeBadge").click()
    c.page.locator("#brainMenu .bmopt[data-mode=none]").click()
    expect(c.page.locator("#modeNone")).to_have_attribute("aria-pressed", "true")
    assert c.page.locator("#modeAi").get_attribute("aria-pressed") == "false"
    # R5.1 int fix: the panel's AI button asks first, exactly like the pill's menu
    c.page.locator("#modeAi").click()
    ask = c.page.locator("#brainMenu .bmask")
    ask.wait_for()
    assert brain.posts == [{"mode": "none"}]  # nothing sent by the click alone
    c.page.get_by_role("button", name="Switch on").click()
    expect(c.page.locator("#brainModeBadge").first).to_contain_text("AI on", ignore_case=True)
    assert brain.posts[-1] == {"mode": "ai"}
    expect(c.page.locator("#modeAi")).to_have_attribute("aria-pressed", "true")
    c.close()


def test_the_public_setter_cannot_switch_ai_on_without_the_confirm(
    browser: Any, server_url: str, token: str
) -> None:
    c, brain = boot(browser, server_url, token, DESKTOP)
    c.page.evaluate("window.JarvisBrainMode.set('none')")
    expect(c.page.locator("#brainModeBadge").first).to_contain_text("No-AI", ignore_case=True)
    c.page.evaluate("window.JarvisBrainMode.set('ai')")
    c.page.locator("#brainMenu .bmask").wait_for()
    c.page.wait_for_timeout(200)
    assert brain.posts == [{"mode": "none"}]
    assert c.page.evaluate("window.JarvisBrainMode.get()") == "none"
    c.page.get_by_role("button", name="Cancel").click()
    assert brain.posts == [{"mode": "none"}]
    c.close()


# ---- the pill never claims a mode the server has not told it --------------------------------------
def test_the_pill_starts_unknown_and_never_says_ai_on_before_the_server_answers(
    browser: Any, server_url: str, token: str
) -> None:
    c = Console(browser, server_url, token, DESKTOP)
    install_mocks(c.page)
    seen: list[str] = []
    gate: list[Any] = []

    def hold(route: Any) -> None:
        gate.append(route)

    c.page.route("**/v1/settings/brain-mode", hold)
    c.open()
    pill = c.page.locator("#brainModeBadge")
    pill.wait_for()
    seen.append(str(pill.inner_text()).lower())
    assert "ai on" not in seen[0] and "brain:" in seen[0]
    gate[0].fulfill(
        status=200,
        content_type="application/json",
        body=json.dumps({"mode": "none", "meaning": ""}),
    )
    expect(pill.first).to_contain_text("No-AI", ignore_case=True)
    c.close()


def test_a_failed_read_shows_unknown_and_pressing_the_pill_retries(
    browser: Any, server_url: str, token: str
) -> None:
    c = Console(browser, server_url, token, DESKTOP)
    install_mocks(c.page)
    brain = Brain()
    brain.fail_get = True
    c.page.route("**/v1/settings/brain-mode", brain)
    c.open()
    pill = c.page.locator("#brainModeBadge")
    expect(pill.first).to_contain_text("unknown", ignore_case=True)
    assert "ai on" not in str(pill.inner_text()).lower()
    expect(c.page.locator(".bmnote")).to_contain_text("could not read")
    brain.fail_get = False
    pill.click()
    expect(pill.first).to_contain_text("AI on", ignore_case=True)
    c.close()


def test_a_failed_switch_says_so_next_to_the_pill_and_keeps_the_true_mode(
    browser: Any, server_url: str, token: str
) -> None:
    c, brain = boot(browser, server_url, token, DESKTOP)  # the People panel stays CLOSED
    brain.fail_post = True
    c.page.locator("#brainModeBadge").click()
    c.page.locator("#brainMenu .bmopt[data-mode=none]").click()
    note = c.page.locator(".bmnote")
    note.wait_for()
    assert "did not change" in str(note.inner_text())
    assert c.page.locator("#p-people").is_hidden()
    expect(c.page.locator("#brainModeBadge").first).to_contain_text("AI on", ignore_case=True)
    brain.fail_post = False
    c.close()


def test_a_second_pick_while_a_switch_is_in_flight_is_ignored(
    browser: Any, server_url: str, token: str
) -> None:
    c, brain = boot(browser, server_url, token, DESKTOP)
    brain.hold_post = True
    c.page.locator("#brainModeBadge").click()
    c.page.locator("#brainMenu .bmopt[data-mode=none]").click()
    c.page.wait_for_timeout(150)
    assert c.page.locator("#brainModeBadge").get_attribute("aria-busy") == "true"
    c.page.locator("#brainModeBadge").click()
    for mode in ("ai", "none"):  # aria-disabled options still take clicks: the script ignores them
        c.page.locator(f"#brainMenu .bmopt[data-mode={mode}]").click(force=True)
    c.page.evaluate("window.JarvisBrainMode.set('none')")
    c.page.wait_for_timeout(150)
    assert brain.posts == [{"mode": "none"}]  # only one POST ever left the page
    brain.hold_post = False
    brain.release()
    expect(c.page.locator("#brainModeBadge").first).to_contain_text("No-AI", ignore_case=True)
    assert c.page.locator("#brainModeBadge").get_attribute("aria-busy") == "false"
    c.close()


def test_brain_menu_structure_and_default_focus_on_cancel(
    browser: Any, server_url: str, token: str
) -> None:
    c, _ = boot(browser, server_url, token, DESKTOP)
    c.page.locator("#brainModeBadge").click()
    c.page.locator("#brainMenu .bmopt[data-mode=none]").wait_for()
    # role=menu holds menu items only; the confirm group sits beside it, outside the menu
    assert (
        c.page.locator("#brainMenu [role=menu] .btn, #brainMenu [role=menu] [role=group]").count()
        == 0
    )
    assert c.page.locator("#brainMenu [role=menu] > [role=menuitemradio]").count() == 2
    assert c.page.locator("#brainMenu > .bmask[role=group]").count() == 1
    c.page.locator("#brainMenu .bmopt[data-mode=none]").click()  # No-AI: immediate
    expect(c.page.locator("#brainModeBadge").first).to_contain_text("No-AI", ignore_case=True)
    c.page.locator("#brainModeBadge").click()
    c.page.locator("#brainMenu .bmopt[data-mode=ai]").click()
    c.page.locator("#brainMenu .bmask").wait_for()
    assert c.page.evaluate("document.activeElement.textContent") == "Cancel"
    c.page.keyboard.press("Tab")  # Cancel -> Switch on stays inside the menu
    assert c.page.evaluate("document.activeElement.textContent") == "Switch on"
    assert c.page.locator("#brainMenu").is_visible()
    c.close()


def test_tab_leaves_and_closes_the_menu_and_a_switch_is_announced(
    browser: Any, server_url: str, token: str
) -> None:
    c, _ = boot(browser, server_url, token, DESKTOP)
    pill = c.page.locator("#brainModeBadge")
    pill.click()
    c.page.locator("#brainMenu .bmopt").first.wait_for()
    c.page.keyboard.press("Tab")
    assert c.page.locator("#brainMenu").is_hidden()
    pill.click()
    c.page.locator("#brainMenu .bmopt[data-mode=none]").click()
    live = c.page.locator(".bmslot .sr-only[aria-live=polite]")
    expect(live).to_have_text("Brain: No-AI")
    c.close()


def test_pill_touch_area_is_44px_on_a_phone_and_does_not_reach_the_picker(
    browser: Any, server_url: str, token: str
) -> None:
    c, _ = boot(browser, server_url, token, PHONE)
    pb = c.page.locator("#brainModeBadge").bounding_box()
    sb = c.page.locator("#brainSel").bounding_box()
    assert pb is not None and sb is not None
    assert round(pb["height"]) == 26  # the look is unchanged
    cx = pb["x"] + pb["width"] / 2
    # the points 20 px above and below the centre (the pill is 26 px tall) still hit the pill
    for dy in (-21, 21):
        hit = c.page.evaluate(
            "([x, y]) => { const e = document.elementFromPoint(x, y); return e && (e.closest('#brainModeBadge') ? 'pill' : e.id || e.tagName); }",
            [cx, pb["y"] + pb["height"] / 2 + dy],
        )
        assert hit == "pill", (dy, hit)
    beyond = c.page.evaluate(
        "([x, y]) => { const e = document.elementFromPoint(x, y); return !!(e && e.closest('#brainModeBadge')); }",
        [cx, pb["y"] + pb["height"] / 2 + 24],
    )
    assert beyond is False  # the band is 44 px, no more
    area = c.page.evaluate(
        "(() => { const r = document.querySelector('#brainModeBadge'); const b = getComputedStyle(r, '::before');"
        " return parseFloat(b.height); })()"
    )
    assert area >= 43
    assert pb["x"] + pb["width"] <= sb["x"] - 2  # beside the picker, never over it
    c.close()


def test_brain_pill_fits_a_phone_without_touching_the_picker(
    browser: Any, server_url: str, token: str
) -> None:
    c, _ = boot(browser, server_url, token, PHONE)
    pill = c.page.locator("#brainModeBadge")
    assert str(pill.inner_text()).strip().lower() == "ai on"
    pb = pill.bounding_box()
    sb = c.page.locator("#brainSel").bounding_box()
    assert pb is not None and sb is not None
    assert pb["x"] + pb["width"] <= sb["x"] - 2
    assert pb["height"] >= 26
    pill.click()
    m = c.page.locator("#brainMenu").bounding_box()
    assert m is not None and m["x"] >= 0 and m["x"] + m["width"] <= PHONE["width"]
    assert c.page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
    c.page.locator("#brainMenu .bmopt[data-mode=none]").click()
    c.page.wait_for_timeout(200)
    assert str(pill.inner_text()).strip().lower() == "no-ai"
    c.close()


# ---- Connectors ---------------------------------------------------------------------------------
def test_connectors_connected_card_and_no_overlap(
    browser: Any, server_url: str, token: str
) -> None:
    c, _ = boot(browser, server_url, token, DESKTOP)
    c.open_panel("connectors")
    gh = c.page.locator("#p-connectors .integ").first
    gh.wait_for()
    expect(c.page.locator("#p-connectors .istate").first).to_contain_text(
        "Connected", ignore_case=True
    )
    assert gh.get_attribute("data-state") == "linked"
    assert "shark2558" in str(gh.locator(".who").inner_text())
    assert c.page.locator("#p-connectors .chip").count() == 0
    assert gh.locator("h3").count() == 0
    assert overlaps(c, "connectors") == []
    fam = c.page.evaluate(
        "getComputedStyle(document.querySelector('#p-connectors .ihead b')).fontFamily"
    ).lower()
    assert any(f in fam for f in ("rajdhani", "share tech mono", "orbitron"))
    c.close()


def test_connectors_not_connected_shows_a_labelled_token_field(
    browser: Any, server_url: str, token: str
) -> None:
    off = {**MOCK_CONNECTORS, "github": {"connected": False, "login": ""}}
    c, _ = boot(browser, server_url, token, DESKTOP, connectors=off)
    c.open_panel("connectors")
    c.page.locator("#ghToken").wait_for()
    assert c.page.locator("label[for=ghToken]").text_content() == "GitHub token"
    lab = c.page.locator("label[for=ghToken]").bounding_box()
    inp = c.page.locator("#ghToken").bounding_box()
    assert lab is not None and inp is not None and lab["y"] + lab["height"] <= inp["y"] + 1
    assert c.page.locator("#p-connectors .integ").first.get_attribute("data-state") == "unlinked"
    assert c.page.get_by_role("button", name="Connect GitHub").is_visible()
    assert overlaps(c, "connectors") == []
    c.close()


def test_github_disconnect_is_a_two_step_confirm(browser: Any, server_url: str, token: str) -> None:
    c, _ = boot(browser, server_url, token, DESKTOP)
    deletes: list[str] = []

    def drop(route: Any) -> None:
        if route.request.method == "DELETE":
            deletes.append(route.request.url)
            route.fulfill(status=200, content_type="application/json", body="{}")
        else:
            route.continue_()

    c.page.route("**/v1/connectors/github", drop)
    c.open_panel("connectors")
    c.page.get_by_role("button", name="Disconnect").first.wait_for()
    c.page.get_by_role("button", name="Disconnect").first.click()
    # the GitHub row's own confirm (since R11.1 the panel also holds the photo import's)
    confirm = c.page.locator("#p-connectors .confirm[aria-label='Confirm disconnect']")
    confirm.wait_for()
    assert deletes == []  # the first click only asks
    confirm.get_by_role("button", name="Keep").click()
    assert deletes == [] and confirm.is_hidden()
    c.page.get_by_role("button", name="Disconnect").first.click()
    confirm.get_by_role("button", name="Disconnect").click()
    c.page.wait_for_timeout(300)
    assert len(deletes) == 1
    c.close()


def test_github_token_field_is_cleared_after_a_failed_save_too(
    browser: Any, server_url: str, token: str
) -> None:
    off = {**MOCK_CONNECTORS, "github": {"connected": False, "login": ""}}
    c, _ = boot(browser, server_url, token, DESKTOP, connectors=off)
    sent: list[str] = []

    def refuse(route: Any) -> None:
        if route.request.method == "PUT":
            sent.append(route.request.post_data or "")
            route.fulfill(status=422, content_type="application/json", body='{"detail":"No."}')
        else:
            route.continue_()

    c.page.route("**/v1/connectors/github", refuse)
    c.open_panel("connectors")
    field = c.page.locator("#ghToken")
    field.wait_for()
    assert field.get_attribute("autocomplete") == "new-password"
    assert field.get_attribute("spellcheck") == "false"
    field.fill("ghp_notarealtoken0123456789")
    c.page.get_by_role("button", name="Connect GitHub").click()
    c.page.locator("#p-connectors .bnote.bad").wait_for()
    assert len(sent) == 1
    assert field.input_value() == ""  # not left sitting in the page after a refusal
    assert c.page.evaluate("document.activeElement.id") == "ghToken"
    c.close()


def test_github_disconnect_returns_focus_after_success_and_after_failure(
    browser: Any, server_url: str, token: str
) -> None:
    c, _ = boot(browser, server_url, token, DESKTOP)
    mode = {"fail": True}

    def drop(route: Any) -> None:
        if route.request.method != "DELETE":
            route.continue_()
        elif mode["fail"]:
            route.fulfill(status=500, content_type="application/json", body='{"detail":"No."}')
        else:
            route.fulfill(status=200, content_type="application/json", body="{}")

    c.page.route("**/v1/connectors/github", drop)
    c.open_panel("connectors")
    c.page.get_by_role("button", name="Disconnect").first.wait_for()
    c.page.get_by_role("button", name="Disconnect").first.click()
    c.page.locator("#p-connectors .confirm").get_by_role("button", name="Disconnect").click()
    c.page.locator("#p-connectors .bnote.bad").wait_for()
    # failure: the row collapsed; focus is on the Disconnect button, not on the page body
    assert c.page.evaluate("document.activeElement.textContent") == "Disconnect"
    assert c.page.evaluate("document.activeElement.tagName") == "BUTTON"
    mode["fail"] = False
    off = {**MOCK_CONNECTORS, "github": {"connected": False, "login": ""}}
    c.page.route(
        "**/v1/connectors",
        lambda r: (
            r.fulfill(status=200, content_type="application/json", body=json.dumps(off))
            if r.request.method == "GET"
            else r.continue_()
        ),
    )
    c.page.get_by_role("button", name="Disconnect").first.click()
    c.page.locator("#p-connectors .confirm").get_by_role("button", name="Disconnect").click()
    c.page.locator("#ghToken").wait_for(state="visible")
    c.page.wait_for_timeout(200)
    assert c.page.evaluate("document.activeElement.id") == "ghToken"  # success: the empty field
    c.close()


def test_photos_off_offers_open_integrations(browser: Any, server_url: str, token: str) -> None:
    c, _ = boot(browser, server_url, token, DESKTOP)
    c.open_panel("connectors")
    btn = c.page.get_by_role("button", name="Open Integrations")
    btn.wait_for()
    expect(c.page.locator("#p-connectors .integ").nth(2).locator(".istate")).to_have_text("Off")
    assert "Press Grant" in str(c.page.locator("#p-connectors .integ").nth(2).inner_text())
    btn.click()
    c.page.locator("#p-integrations").wait_for(state="visible")
    c.close()


def test_connectors_on_a_phone_have_44px_targets(browser: Any, server_url: str, token: str) -> None:
    c, _ = boot(browser, server_url, token, PHONE)
    c.open_panel("connectors")
    c.page.locator("#p-connectors .integ").first.wait_for()
    c.page.wait_for_timeout(600)
    heights = c.page.evaluate(
        "[...document.querySelectorAll('#p-connectors button, #p-connectors input:not([type=checkbox])')]"
        ".filter((e) => e.getBoundingClientRect().width > 0).map((e) => e.getBoundingClientRect().height)"
    )
    assert heights and min(heights) >= 43.5
    assert overlaps(c, "connectors") == []
    c.close()


# ---- People -------------------------------------------------------------------------------------
def test_people_inputs_have_visible_labels_above_them(
    browser: Any, server_url: str, token: str
) -> None:
    c, _ = boot(browser, server_url, token, DESKTOP)
    c.open_panel("people")
    c.page.locator("#peopleName").wait_for()
    for fid, text in (("peopleName", "Name"), ("peopleContext", "Role or organisation")):
        lab = c.page.locator(f"label[for={fid}]")
        assert text in str(lab.text_content())
        lb, ib = lab.bounding_box(), c.page.locator(f"#{fid}").bounding_box()
        assert lb is not None and ib is not None and lb["y"] + lb["height"] <= ib["y"] + 1
        assert ib["width"] > 250
    assert overlaps(c, "people") == []
    c.close()


def test_people_dossier_does_not_reuse_the_panel_title_classes(
    browser: Any, server_url: str, token: str
) -> None:
    c, _ = boot(browser, server_url, token, DESKTOP)
    c.open_panel("people")
    name = c.page.locator("#peopleCard .pname")
    name.wait_for()
    assert name.inner_text() == "Satya Nadella"
    assert c.page.locator("#peopleCard .ptitle, #peopleCard .pbody").count() == 0
    assert c.page.locator("#peopleCard .integ, #peopleCard.integ").count() >= 1
    links = c.page.locator("#peopleCard a.plink")
    assert links.count() == 3
    assert links.first.get_attribute("href") == "https://www.linkedin.com/in/satyanadella"
    assert (
        c.page.locator("#peopleOpen").is_visible() and c.page.locator("#peopleSpeak").is_visible()
    )
    # the name can be selected (the title bar's user-select:none is gone)
    assert name.evaluate("e => getComputedStyle(e).userSelect") != "none"
    assert overlaps(c, "people") == []
    gap = c.page.evaluate(
        "(() => { const a = document.querySelector('#peopleOpen').getBoundingClientRect(),"
        " b = document.querySelector('#peopleSpeak').getBoundingClientRect(); return b.left - a.right; })()"
    )
    assert gap >= 6
    c.close()


def test_people_on_a_phone_fit_and_have_44px_targets(
    browser: Any, server_url: str, token: str
) -> None:
    c, _ = boot(browser, server_url, token, PHONE)
    c.open_panel("people")
    c.page.locator("#peopleCard .pname").wait_for()
    c.page.wait_for_timeout(600)
    heights = c.page.evaluate(
        "[...document.querySelectorAll('#p-people button, #p-people input')]"
        ".filter((e) => e.getBoundingClientRect().width > 0).map((e) => e.getBoundingClientRect().height)"
    )
    assert heights and min(heights) >= 43.5
    assert c.page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
    c.close()


# ---- D10 panels carrying fixed-size ---------------------------------------------------------------
@pytest.mark.parametrize("panel", ["approvals", "integrations", "vitals"])
def test_fixed_size_panels_survive_being_resized(
    browser: Any, server_url: str, token: str, panel: str
) -> None:
    """Without .fixed-size (the integrator removes it) the panel must hold at its extremes."""
    c, _ = boot(browser, server_url, token, DESKTOP)
    c.page.evaluate(f"document.getElementById('p-{panel}').classList.remove('fixed-size')")
    c.open_panel(panel)
    c.page.wait_for_timeout(600)
    for w, h in ((300, 320), (560, 760), (900, 500)):
        c.page.evaluate(
            f"(() => {{ const e = document.getElementById('p-{panel}');"
            f" e.style.width = '{w}px'; e.style.height = '{h}px'; }})()"
        )
        c.page.wait_for_timeout(150)
        probe = c.page.evaluate(
            f"(() => {{ const e = document.getElementById('p-{panel}'), b = e.querySelector('.pbody');"
            " return { sideways: b.scrollWidth - b.clientWidth, w: e.getBoundingClientRect().width,"
            " page: document.documentElement.scrollWidth - window.innerWidth }; })()"
        )
        assert probe["sideways"] <= 1, (panel, w, h, probe)
        assert probe["page"] <= 0, (panel, w, h, probe)
    assert overlaps(c, panel) == []
    c.close()
