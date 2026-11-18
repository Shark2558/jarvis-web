# tests/browser/test_r131_d_look.py -- R13.1 Part D: the look does not change
# (docs/plans/r13-1-try-on.md D1, D21; BRIEF-D section 2 "The look does not change", section 4's
# cases), in a real Chromium:
#   - every target in Try it on and in the card under a reply is at least 44 x 44 px, on a laptop
#     (1280 x 800) and a phone (360 x 800)
#   - the stage is 480 px tall on a laptop and 56 % of the viewport's height on a phone, by night
#     and by day, with no sideways scroll on the phone and no error or CSP report
#   - row 388 on a phone: the card opens by itself under the reply, dressed in the card's pieces
#   - with Try-on off on the server, the Wardrobe tab is laid out exactly as R13's (the section
#     takes no room, and nothing of the 3D view loads)
# Fake engine, fake server, pinned clock (test_r131_d_card.py's helpers).
from __future__ import annotations

import time
from typing import Any

import pytest
from test_r131_d_card import CARD_PIECES, Page, browser, d_url, drawn, reset, shown_pieces, until

__all__ = ["browser", "d_url"]
pytestmark = pytest.mark.browser
LAPTOP = {"width": 1280, "height": 800}
PHONE = {"width": 360, "height": 800}
SIZES = {"laptop": LAPTOP, "phone": PHONE}
TARGET_PX = 44
SMALL = """(sel) => { // every target there under 44 x 44 px, with its words and size ([] when none)
  const out = [];
  const kinds = 'button, select, input:not([type=checkbox]):not([type=hidden]), label.wd-tick';
  document.querySelectorAll(sel).forEach((root) => root.querySelectorAll(kinds).forEach((el) => {
    if (el.closest('.tr-stage')) return; // the engine's own canvas (Part B)
    const r = el.getBoundingClientRect();
    if (!r.width && !r.height) return; // not on screen in this state
    if (r.height < 44 || r.width < 44) {
      const words = (el.textContent || el.getAttribute('aria-label') || el.tagName).trim();
      out.push(words.slice(0, 40) + ' ' + Math.round(r.width) + 'x' + Math.round(r.height));
    }
  }));
  return out;
}"""
BOXES = """() => { // every Wardrobe section but Try it on, where it sits
  const pane = document.getElementById('hpp-wardrobe');
  return [...pane.querySelectorAll('.hp-sec')].filter((s) => !s.classList.contains('tr-sec'))
    .map((s) => s.getBoundingClientRect())
    .map((r) => [r.x, r.y, r.width, r.height].map(Math.round));
}"""


def stage_px(c: Page, where: str) -> float:
    box = c.page.locator(f"{where} .tr-stage").first
    return float(box.evaluate("e => e.getBoundingClientRect().height"))


@pytest.mark.parametrize("size", ["laptop", "phone"])
def test_every_target_is_44px_in_try_it_on_and_in_the_card(
    browser: Any, d_url: str, token: str, size: str
) -> None:
    reset(d_url, token)
    c = Page(browser, d_url, token, SIZES[size])
    try:
        c.open()
        c.ask()
        until(c.page, lambda: c.card().count() == 1 and drawn(c), "the card")
        assert c.page.evaluate(SMALL, ".tr-card") == []
        c.wardrobe()
        until(c.page, lambda: drawn(c, 2), "the section's figure")
        assert c.page.evaluate(SMALL, ".tr-sec") == []
        outer = c.section().locator(".tr-item[data-slot='outer']")
        outer.get_by_role("button", name="Change").click()
        c.section().get_by_role("button", name="Show as a list").first.click()
        assert c.page.evaluate(SMALL, ".tr-sec") == []  # the checklist and a slot's options
    finally:
        c.close()


@pytest.mark.parametrize("surface", ["night", "day"])
@pytest.mark.parametrize("size", ["laptop", "phone"])
def test_the_stage_is_480px_on_a_laptop_and_56_percent_on_a_phone_by_night_and_day(
    browser: Any, d_url: str, token: str, size: str, surface: str
) -> None:
    reset(d_url, token)
    c = Page(browser, d_url, token, SIZES[size])
    try:
        c.open()
        if surface == "day":
            c.choose_day()
        c.wardrobe()
        until(c.page, lambda: drawn(c), "the section's figure")
        want = 480.0 if size == "laptop" else 0.56 * PHONE["height"]
        assert abs(stage_px(c, "#hpp-wardrobe .tr-sec") - want) <= 1
        wide = c.page.evaluate(
            "() => [document.documentElement.scrollWidth, window.innerWidth,"
            " document.getElementById('hpp-wardrobe').scrollWidth,"
            " document.getElementById('hpp-wardrobe').clientWidth]"
        )
        assert wide[0] <= wide[1] and wide[2] <= wide[3] + 1, wide  # nothing scrolls sideways
        assert c.page.locator("html").get_attribute("data-surface") == surface
        assert c.errors == [] and c.csp_violations() == []
    finally:
        c.close()


def test_row388_on_a_phone_the_card_opens_by_itself_under_the_reply(
    browser: Any, d_url: str, token: str
) -> None:
    reset(d_url, token)
    c = Page(browser, d_url, token, PHONE)
    try:
        c.open()
        c.ask()
        until(c.page, lambda: c.card().count() == 1 and drawn(c), "the card")
        assert shown_pieces(c.engine()["shown"][-1]["figures"][0]) == CARD_PIECES
        assert stage_px(c, ".row.jarvis .tr-card") >= ENGINE_MIN_PX  # compact, not the section's
        assert c.errors == [] and c.csp_violations() == []
    finally:
        c.close()


ENGINE_MIN_PX = 150  # Part B's engine needs a host at least this tall (INTEGRATION-B section 8)
# Layout rounds to fractions of a pixel: GitHub's Chromium hid 0.1 % of the reply (a fraction of
# one pixel, run 44216933907) where this machine's hides none. Up to one pixel may be cut, never a
# line of words or the figure.
FIT_SLACK_PX = 1.0
CARD_FIT = """() => { // the card as it lands: its size, and how much of each part shows
  const s = document.getElementById('scroll'), sr = s.getBoundingClientRect();
  const row = [...document.querySelectorAll('.row.jarvis')].pop();
  const card = row.querySelector('.tr-card'), stage = card.querySelector('.tr-stage');
  const box = (e) => e.getBoundingClientRect();
  const shows = (b) => Math.max(0, Math.min(b.bottom, sr.bottom) - Math.max(b.top, sr.top));
  const seen = (e) => { const b = e ? box(e) : null; if (!b || !b.height) return 0;
    return shows(b) / b.height; };
  const cut = (e) => { const b = e ? box(e) : null; // the pixels of it hidden (none drawn: all)
    return !b || !b.height ? 1e9 : b.height - shows(b); };
  const shown = [...card.querySelectorAll('button')].filter((b) => box(b).height);
  return { conversation: sr.height, card: box(card).height, stage_px: box(stage).height,
    stage: seen(stage), reply: seen(row.querySelector('.bubble')),
    stage_cut: cut(stage), reply_cut: cut(row.querySelector('.bubble')),
    wide: box(card).right <= sr.right + 1, buttons: shown.map((b) => b.textContent) };
}"""


@pytest.mark.parametrize("before", [0, 3], ids=["fresh", "under-way"])
@pytest.mark.parametrize("size", ["laptop", "phone"])
def test_row388_the_card_fits_the_conversation_with_the_reply_and_the_whole_figure_in_view(
    browser: Any, d_url: str, token: str, size: str, before: int
) -> None:
    # review D-1 H1: the card was 2,704 px (laptop) and 2,942 px (phone) tall in a conversation
    # 467 / 484 px high; as it landed, half the figure and none of its controls showed
    reset(d_url, token)
    c = Page(browser, d_url, token, SIZES[size])
    try:
        c.open()
        for i in range(before):  # a conversation under way: the reply lands at its bottom
            c.send(f"remember note {i}")
        c.ask()
        until(c.page, lambda: c.card().count() == 1 and drawn(c), "the card")
        c.page.wait_for_timeout(300)
        got = c.page.evaluate(CARD_FIT)
        assert got["card"] <= got["conversation"], got  # the card fits the conversation
        # his reply and the WHOLE figure, but for a fraction of a pixel of layout rounding
        assert got["reply_cut"] <= FIT_SLACK_PX and got["stage_cut"] <= FIT_SLACK_PX, got
        assert got["stage_px"] >= ENGINE_MIN_PX and got["wide"], got
        # a small set: turn it, the checklist, the full view in Helpers (layers, tuck, swap ...)
        assert got["buttons"][:3] == ["Turn around", "Show as a list", "Open in Helpers"], got
        assert len(got["buttons"]) <= 4, got  # and "Wearing it" for a plan
        pieces = c.card().locator(".tr-sum")
        assert pieces.count() == 1  # the pieces in one line
        assert "Navy shirt · Charcoal trousers" in pieces.inner_text()
        assert "Base layer (covered)" in pieces.inner_text()
        assert c.errors == [] and c.csp_violations() == []
    finally:
        c.close()


PLAN_BUTTONS = """() => [...document.querySelectorAll('#hpp-wardrobe .wd-plan')]
  .map((p) => [...p.querySelectorAll('button')].map((b) => b.textContent))"""
R13_PLAN = ["Wearing it", "Done for today"]  # R13's own plan row
OFF = {"error": "not_found", "detail": "Try-on is off on this server."}


# I1: the wired app says Try-on is off with A's 503 {"error": "off"} (no key, no storage, switched
# off; review A-1 F5); I0's fake said 404. Both are off, never "can't load right now".
A_OFF = {"error": "off", "detail": "Off: JARVIS has no token key to seal your measurements."}


@pytest.mark.parametrize("status", [404, 503], ids=["i0_fake_404", "a_off_503"])
def test_with_try_on_off_the_wardrobe_tab_is_laid_out_as_r13s(
    browser: Any, d_url: str, token: str, status: int
) -> None:
    c = Page(browser, d_url, token)
    c.page.route(
        "**/v1/tryon", lambda r: r.fulfill(status=status, json=OFF if status == 404 else A_OFF)
    )
    try:
        c.open()
        c.open_panel("helpers")
        c.page.locator("#hpt-wardrobe").click()
        sec = c.page.locator("#hpp-wardrobe .tr-sec")
        until(c.page, lambda: sec.count() == 1 and sec.get_attribute("hidden") is not None, "off")
        until(c.page, lambda: c.page.locator("#hpp-wardrobe .wd-plan").count() >= 2, "R13's plans")
        c.page.wait_for_timeout(500)
        assert c.page.evaluate(PLAN_BUTTONS) == [R13_PLAN, R13_PLAN]  # no Show in 3D (M7)
        with_it = c.page.evaluate(BOXES)
        c.page.evaluate("() => document.querySelector('#hpp-wardrobe .tr-sec').remove()")
        assert c.page.evaluate(BOXES) == with_it  # the hidden section takes no room at all
        assert sec.count() == 0 and c.engine() is None  # nothing of the 3D view loaded
        assert not [r for r in c.sent if "/v1/tryon/look" in r["url"] or "/v1/seeme" in r["url"]]
        assert [e for e in c.errors if not e.endswith(d_url + "/v1/tryon")] == []  # the browser's
        # own line for the off answer, by design
        assert c.csp_violations() == []
    finally:
        c.close()


@pytest.mark.parametrize("on", [True, False], ids=["on", "off"])
def test_show_in_3d_follows_try_ons_state_even_when_the_tab_draws_first(
    browser: Any, d_url: str, token: str, on: bool
) -> None:
    # review D-1 M7: hiding the button on the section's `hidden` raced the tab's own reads
    c = Page(browser, d_url, token)

    def slow(route: Any) -> None:  # Try-on's answer comes after the tab has drawn its plans
        time.sleep(1.5)
        route.continue_() if on else route.fulfill(status=404, json=OFF)

    c.page.route("**/v1/tryon", slow)
    try:
        c.open()
        c.open_panel("helpers")
        c.page.locator("#hpt-wardrobe").click()
        until(c.page, lambda: c.page.locator("#hpp-wardrobe .wd-plan").count() >= 2, "R13's plans")
        assert c.page.evaluate(PLAN_BUTTONS) == [R13_PLAN, R13_PLAN]  # not known yet: not drawn
        want = R13_PLAN + ["Show in 3D"] if on else R13_PLAN
        until(c.page, lambda: c.page.evaluate(PLAN_BUTTONS) == [want, want], "the state", 15)
        c.page.wait_for_timeout(500)
        assert c.page.evaluate(PLAN_BUTTONS) == [want, want]
    finally:
        c.close()


def test_with_try_on_off_the_joined_hook_offers_no_show_in_3d_and_an_open_says_why(
    browser: Any, d_url: str, token: str
) -> None:
    # I1 applied M7's two lines to I0's hook (this was "before I1, with I0's hook"): with Try-on
    # off no plan row offers Show in 3D, and an open that still arrives says why, loading nothing
    c = Page(browser, d_url, token, hook=False)  # the hook as it is in the tree now
    c.page.route("**/v1/tryon", lambda r: r.fulfill(status=404, json=OFF))
    try:
        c.open()
        c.open_panel("helpers")
        c.page.locator("#hpt-wardrobe").click()
        sec = c.page.locator("#hpp-wardrobe .tr-sec")
        until(c.page, lambda: sec.count() == 1 and sec.get_attribute("hidden") is not None, "off")
        plans = c.page.locator("#hpp-wardrobe .wd-plan")
        until(c.page, lambda: plans.count() >= 1, "R13's plan rows")
        assert plans.get_by_role("button", name="Show in 3D").count() == 0
        c.page.evaluate(
            "() => document.dispatchEvent(new CustomEvent('jarvis:tryon-open',"
            " { detail: { plan: 'op_0000d001' } }))"
        )
        until(c.page, lambda: sec.is_visible(), "the section says why")
        assert "Try it on is off on this server." in sec.inner_text()
        assert c.engine() is None and not [r for r in c.sent if "/v1/tryon/look" in r["url"]]
    finally:
        c.close()
