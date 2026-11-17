# tests/browser/test_r131_d_stage.py -- R13.1 Part D: the stage's life in Helpers -> Wardrobe ->
# Try it on, in a real Chromium (docs/plans/r13-1-try-on.md D1, D6, D8; BRIEF-D section 2):
#   - one WebGL context: the stage is given back when the Wardrobe tab is hidden (another Helpers
#     tab) and when the page is hidden, and comes back when shown
#   - Full screen only where the browser has the Fullscreen API (not on an iPhone)
#   - Turn around stays still under Motion Off, and says so
#   - a fresh wardrobe load keeps every reference card (the views' crops are read again)
#   - his checklist names a private basic only behind "Show private basics" (R13 D10); the figure
#     and the shared picture never do
# Fake engine, fake server, pinned clock (test_r131_d_card.py's helpers).
from __future__ import annotations

from typing import Any

import pytest
from r131_fakes import T
from r131_fakes_d import ENGINE
from test_r131_d_card import Page, browser, d_url, drawn, mode, reset, until

__all__ = ["browser", "d_url"]
pytestmark = pytest.mark.browser
NO_FULLSCREEN = "delete Element.prototype.requestFullscreen;"  # an iPhone's Safari has none
MOTION_OFF = "localStorage.setItem('jarvis_motion', 'off');"


def opened(c: Page) -> Page:
    c.open()
    c.wardrobe()
    until(c.page, lambda: drawn(c), "the section's figure")
    return c


def press(c: Page, name: str) -> None:
    c.section().get_by_role("button", name=name, exact=True).first.click()


def live(c: Page) -> int:
    return int(c.engine()["live"])


def test_the_stage_is_given_back_when_the_wardrobe_tab_is_hidden_and_comes_back(
    browser: Any, d_url: str, token: str
) -> None:
    reset(d_url, token)
    c = opened(Page(browser, d_url, token))
    try:
        c.page.locator("#hpt-today").click()
        until(c.page, lambda: live(c) == 0, "the stage given back")
        assert c.engine()["disposes"] == 1
        c.page.locator("#hpt-wardrobe").click()
        until(c.page, lambda: live(c) == 1 and c.engine()["mounts"] == 2, "the stage back")
        assert c.engine()["maxLive"] == 1
        assert mode(c.section().locator(".tr-view")) == "3d"
        assert c.errors == [] and c.csp_violations() == []
    finally:
        c.close()


def test_the_stage_is_given_back_while_the_page_is_hidden(
    browser: Any, d_url: str, token: str
) -> None:
    reset(d_url, token)
    c = opened(Page(browser, d_url, token))
    try:
        hide = """(on) => {
          Object.defineProperty(document, 'hidden', { value: on, configurable: true });
          document.dispatchEvent(new Event('visibilitychange'));
        }"""
        c.page.evaluate(hide, True)
        until(c.page, lambda: live(c) == 0, "given back while hidden")
        c.page.evaluate(hide, False)
        until(c.page, lambda: live(c) == 1 and c.engine()["mounts"] == 2, "back when shown")
        c.page.evaluate("() => window.dispatchEvent(new PageTransitionEvent('pagehide'))")
        until(c.page, lambda: live(c) == 0, "given back on pagehide")
    finally:
        c.close()


@pytest.mark.parametrize("has_it", [True, False], ids=["laptop", "iphone"])
def test_full_screen_is_offered_only_where_the_browser_has_it(
    browser: Any, d_url: str, token: str, has_it: bool
) -> None:
    reset(d_url, token)
    c = Page(browser, d_url, token)
    if not has_it:
        c.page.add_init_script(NO_FULLSCREEN)
    try:
        opened(c)
        full = c.section().get_by_role("button", name="Full screen", exact=True)
        assert full.count() == (1 if has_it else 0)
    finally:
        c.close()


def test_turn_around_stays_still_under_motion_off_and_says_so(
    browser: Any, d_url: str, token: str
) -> None:
    reset(d_url, token)
    c = Page(browser, d_url, token)
    c.page.add_init_script(MOTION_OFF)
    try:
        opened(c)
        press(c, "Turn around")
        words = "Motion is off: the figure stays still. Use Front, Side and Back."
        until(c.page, lambda: words in c.section().inner_text(), "the words")
        assert c.engine()["spins"] == []  # never asked to spin
        press(c, "Back")
        assert c.engine()["views"] == ["back"]  # the views still turn it
    finally:
        c.close()


def test_a_fresh_wardrobe_load_keeps_every_reference_card(
    browser: Any, d_url: str, token: str
) -> None:
    reset(d_url, token)
    c = opened(Page(browser, d_url, token))
    try:
        c.page.locator("#hpp-wardrobe .wd-plan").nth(1).get_by_role(
            "button", name="Show in 3D"
        ).click()
        refs = c.section().locator(".tr-item[data-slot='top'] + .tr-refs img.tr-thumb")
        until(c.page, lambda: refs.count() == 2, "the kurta's two cards")
        c.page.evaluate("() => document.dispatchEvent(new CustomEvent('jarvis:wardrobe-fresh'))")
        c.page.wait_for_timeout(600)
        until(c.page, lambda: refs.count() == 2, "both cards after the fresh load")
        assert refs.evaluate_all("l => l.map(i => i.dataset.photo)") == [
            "wh_00000000a001",
            "wh_00000000a002",
        ]
    finally:
        c.close()


def test_his_checklist_names_a_private_basic_only_behind_show_private_basics(
    browser: Any, d_url: str, token: str
) -> None:
    reset(d_url, token)
    c = opened(Page(browser, d_url, token))
    try:
        base = c.section().locator(".tr-col[data-look='0'] .tr-item[data-slot='base']")
        assert "Base layer (covered)" in base.inner_text()
        show = c.section().locator(".tr-view button.bsw[aria-label='Show private basics']")
        toggle = c.page.locator("button.bsw[aria-label='Show private basics']")
        assert "Private basics" in c.section().locator(".tr-view .hp-row", has=toggle).inner_text()
        show.click()
        until(c.page, lambda: "black vest" in base.inner_text(), "named behind the tap")
        figure = c.engine()["shown"][-1]["figures"][0]["look"]["slots"]
        assert [s for s in figure if s["slot"] == "base"] == [{"slot": "base", "private": True}]
        press(c, "Save a picture of this look")
        until(c.page, lambda: c.engine()["snapshots"], "the snapshot")
        cap = " ".join(c.engine()["snapshots"][-1]["caption"])
        assert "Base layer (covered)" in cap and "vest" not in cap.lower()
        assert T.vest not in cap
        c.section().locator(".tr-view button.bsw[aria-label='Show private basics']").click()
        until(c.page, lambda: "Base layer (covered)" in base.inner_text(), "covered again")
        assert c.errors == [] and c.csp_violations() == []
    finally:
        c.close()


def test_the_card_under_a_reply_never_offers_private_basics(
    browser: Any, d_url: str, token: str
) -> None:
    reset(d_url, token)
    c = Page(browser, d_url, token)
    try:
        c.open()
        c.ask()
        until(c.page, lambda: c.card().count() == 1 and drawn(c), "the card")
        assert c.card().locator("button.bsw").count() == 0
        assert "Base layer (covered)" in c.card().inner_text()
    finally:
        c.close()


def test_a_second_look_in_the_section_reuses_its_one_stage(
    browser: Any, d_url: str, token: str
) -> None:
    reset(d_url, token)
    c = opened(Page(browser, d_url, token))
    try:
        c.page.locator("#hpp-wardrobe .wd-plan").nth(1).get_by_role(
            "button", name="Show in 3D"
        ).click()
        until(c.page, lambda: drawn(c, 2), "the second look shown")
        rec = c.engine()
        assert rec["mounts"] == 1 and rec["maxLive"] == 1  # one WebGL context, never two
        assert c.section().locator(".tr-stage svg").count() == 1
    finally:
        c.close()


def test_a_stage_that_arrives_while_its_tab_is_hidden_gives_the_context_back(
    browser: Any, d_url: str, token: str
) -> None:
    # review D-1 L6: the tab was hidden while the engine's file loaded (the ResizeObserver had
    # already fired), so the stage kept its WebGL context out of sight
    reset(d_url, token)
    c = Page(browser, d_url, token, fake_engine=False)
    held: list[Any] = []
    c.page.route("**/static/console-tryon-3d.js*", lambda r: held.append(r))  # on its way
    try:
        c.open()
        c.wardrobe()
        until(c.page, lambda: held, "the engine asked for")
        c.page.locator("#hpt-today").click()  # another Helpers tab: Try it on is out of sight
        c.page.wait_for_timeout(300)
        held[0].fulfill(path=str(ENGINE), content_type="application/javascript")
        until(c.page, lambda: c.engine() and c.engine()["mounts"] == 1, "the stage mounted")
        until(c.page, lambda: live(c) == 0, "the context given back")
        c.page.locator("#hpt-wardrobe").click()
        until(c.page, lambda: live(c) == 1, "taken again once shown")
    finally:
        c.close()


def test_a_plan_changed_elsewhere_is_shown_with_its_new_pieces_after_a_fresh_load(
    browser: Any, d_url: str, token: str
) -> None:
    # review D-1 L5: a fresh load re-read the look by the pieces shown, so a plan changed from the
    # chat kept its old pieces under the same plan (and "Use this look" confirmed them)
    reset(d_url, token)
    c = opened(Page(browser, d_url, token))
    replanned: list[bool] = []

    def white_shirt(route: Any) -> None:  # the plan now has the white shirt (R13 changed it)
        r = route.fetch()
        look = r.json()
        for s in look["slots"]:
            if replanned and s["slot"] == "top":
                s.update(piece=T.white, words="white shirt")
        route.fulfill(response=r, json=look)

    c.page.route("**/v1/tryon/look?plan=*", white_shirt)
    try:
        replanned.append(True)
        c.page.evaluate("() => document.dispatchEvent(new CustomEvent('jarvis:wardrobe-fresh'))")
        top = c.section().locator(".tr-item[data-slot='top']").first
        until(c.page, lambda: top.get_attribute("data-piece") == T.white, "the new top")
    finally:
        c.close()
