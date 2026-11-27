# tests/browser/test_r18_e_look.py -- R18 E: the visual gate for every new Calls screen (the owner's
# standing rule: the console's look never changes; new screens blend with its theme exactly), at
# DESKTOP (1440x900) and PHONE (390x844), Night and Day, with the Calls routes stubbed
# (tests/browser/r18_calls_stub.py). Each screen must pass the console's own DOM checks
# (tests/browser/ui_checks.py DOM_CHECKS_JS and test_ui_audit.py's probes): no overlaps, theme fonts
# only, no browser-default controls, nothing overflowing sideways, every control named and labelled
# before it, no button text on a third line, contrast >= 4.5:1, 44 px touch targets on the phone.
# The screens: the calls list with the readiness line, the Bluetooth warning, a record, New call with
# a Laundry card, the live call, the language table and its confirm, Settings, the call card in the
# chat and Vitals' calls line. Screenshots only when R18_E_SHOTS names a folder (build/r18-shots/,
# never committed), to be looked at by a person.
# ruff: noqa: E501 -- long test names and selectors
from __future__ import annotations

import os
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import pytest
from r18_calls_stub import LIVE_ID, STATUS
from test_console import DESKTOP, PHONE
from test_r18_e_calls import Calls, _with_card, until
from test_ui_audit import NAMELESS_JS, WRAP_JS, _assert_clean
from ui_checks import DOM_CHECKS_JS, FINISH_ANIMATIONS_JS

sync_playwright = pytest.importorskip("playwright.sync_api").sync_playwright
pytestmark = pytest.mark.browser
SHOTS = os.environ.get("R18_E_SHOTS", "")
VIEWPORTS = {"desktop": DESKTOP, "phone": PHONE}


@pytest.fixture(scope="module")
def browser() -> Iterator[Any]:
    with sync_playwright() as p:
        b = p.chromium.launch(args=["--autoplay-policy=no-user-gesture-required"])
        yield b
        b.close()


def _gate(c: Calls, sel: str, vp: str, what: str) -> None:
    c.page.evaluate("() => document.fonts.ready.then(() => true)")
    c.page.wait_for_timeout(400)
    c.page.evaluate(FINISH_ANIMATIONS_JS)
    res = c.page.evaluate(DOM_CHECKS_JS, sel)
    assert not res.get("missing"), f"{what}: {sel} is not in the page"
    _assert_clean(res, c.page.evaluate(NAMELESS_JS, sel), c.page.evaluate(WRAP_JS, sel), vp, what)


def _shot(c: Calls, name: str, panel: str = "#p-calls", bottom: bool = False) -> None:
    if not SHOTS:
        return
    folder = Path(SHOTS)
    folder.mkdir(parents=True, exist_ok=True)
    c.page.screenshot(path=str(folder / f"{name}.png"))
    if bottom:  # the rest of a long pane: its middle, then its end
        c.page.locator(f"{panel} .pbody").first.evaluate("b => { b.scrollTop = (b.scrollHeight - b.clientHeight) / 2; }")
        c.page.wait_for_timeout(150)
        c.page.screenshot(path=str(folder / f"{name}-mid.png"))
        c.page.locator(f"{panel} .pbody").first.evaluate("b => { b.scrollTop = b.scrollHeight; }")
        c.page.wait_for_timeout(150)
        c.page.screenshot(path=str(folder / f"{name}-end.png"))
        c.page.locator(f"{panel} .pbody").first.evaluate("b => { b.scrollTop = 0; }")


def _screens(c: Calls, vp: str, surface: str) -> list[tuple[str, Callable[[], None], str, bool]]:
    p = c.page

    def calls_list() -> None:
        p.locator("#clp-calls .hp-row").first.wait_for()

    def record() -> None:
        p.get_by_role("button", name="Open the record of Laundry").click()
        p.locator("#clp-calls .cl-record .cl-transcript .cl-line").first.wait_for()

    def new_form() -> None:
        c.button("Back to calls").click()
        c.tab("New call")
        sel = c.pane("new").locator("select").first
        until(p, lambda: sel.locator("option").count() == 4, "the templates")
        sel.select_option("laundry_pickup")
        until(
            p, lambda: c.pane("new").locator(".cl-lang").count() == 5, "the languages that passed"
        )

    def new_card() -> None:
        pane = c.pane("new")
        pane.get_by_label("Who it is (a saved contact, or a name for the card)").fill("Laundry")
        pane.get_by_label("Name to give").fill("Arun")
        pane.get_by_label("Day 1").fill("2026-11-28")
        pane.get_by_label("Time 1: from").fill("10:00")
        pane.get_by_label("Time 1: until").fill("12:00")
        c.button("Make the card", "#clp-new").click()
        p.locator("#clp-new .cl-card").wait_for()

    def languages() -> None:
        c.tab("Languages")
        p.locator("#clp-langs .hp-row").first.wait_for()
        c.button("Run language check", "#clp-langs").click()
        p.locator("#clp-langs .mbox").wait_for(state="visible")

    def settings() -> None:
        c.tab("Settings")
        until(
            p,
            lambda: (
                c.pane("settings").get_by_label("Calls in a month, in rupees").input_value()
                == "200"
            ),
            "settings",
        )

    def live() -> None:
        c.tab("Calls")
        c.stub.status["active"] = {"call_id": LIVE_ID, "state": "talking"}
        p.evaluate(f"window.JarvisCalls.live('{LIVE_ID}')")
        until(p, lambda: p.locator("#clp-calls .cl-captions .cl-line").count() == 2, "the captions")
        c.stub.caption("jarvis", "ml-IN", "ശരി, നാളെ പത്തു മണി.", "Right: tomorrow at ten.")
        p.locator("#clp-calls .cl-live").get_by_text("Listen live", exact=True).click()
        until(p, lambda: {"type": "listen", "audio": True} in c.stub.live_in, "listen")

    return [
        ("calls", calls_list, "#p-calls", False),
        ("record", record, "#p-calls", True),
        ("new-call-form", new_form, "#p-calls", True),
        ("new-call-card", new_card, "#p-calls", True),
        ("languages", languages, "#p-calls", True),
        ("settings", settings, "#p-calls", True),
        ("live", live, "#p-calls", True),
    ]


@pytest.mark.parametrize("surface", ["night", "day"])
@pytest.mark.parametrize("vp", list(VIEWPORTS))
def test_every_calls_screen_passes_the_visual_gate(
    browser: Any, server_url: str, token: str, vp: str, surface: str
) -> None:
    c = Calls(browser, server_url, token, VIEWPORTS[vp])
    try:
        c.open()
        if surface == "day":
            c.choose_day()
        c.open_panel("calls")
        c.page.locator("#p-calls .cl-ready .vt-chip").first.wait_for()
        for name, go, sel, long in _screens(c, vp, surface):
            go()
            _gate(c, sel, vp, f"{name} {vp} {surface}")
            _shot(c, f"{name}-{vp}-{surface}", bottom=long)
        c.clean()
    finally:
        c.close()


@pytest.mark.parametrize("surface", ["night", "day"])
@pytest.mark.parametrize("vp", list(VIEWPORTS))
def test_the_chat_card_vitals_line_and_warnings_pass_the_visual_gate(
    browser: Any, server_url: str, token: str, vp: str, surface: str
) -> None:
    status = {**STATUS, "desk": {**STATUS["desk"], "ready": False, "bt_headset": True}}
    c = Calls(browser, server_url, token, VIEWPORTS[vp], status=status)
    try:
        c.page.route("**/v1/chat", _with_card)
        c.open()
        if surface == "day":
            c.choose_day()
        c.send("Call the clinic and book a check-up next week")
        c.page.locator("#log .cl-card").wait_for()
        c.page.locator("#log .cl-card").scroll_into_view_if_needed()
        _gate(c, "#p-chat", vp, f"chat card {vp} {surface}")
        _shot(c, f"chat-card-{vp}-{surface}", "#p-chat")
        c.open_panel("calls")
        c.page.locator("#p-calls .cl-ready .bnote.bad").wait_for()
        _gate(c, "#p-calls", vp, f"warning {vp} {surface}")
        _shot(c, f"warning-{vp}-{surface}")
        c.open_panel("vitals")
        until(
            c.page,
            lambda: (c.page.locator("#sCalls").text_content() or "").startswith("≈"),
            "the calls line",
        )
        c.page.locator("#sCalls").scroll_into_view_if_needed()
        _gate(c, "#p-vitals", vp, f"vitals {vp} {surface}")
        _shot(c, f"vitals-{vp}-{surface}", "#p-vitals")
        c.clean()
    finally:
        c.close()
