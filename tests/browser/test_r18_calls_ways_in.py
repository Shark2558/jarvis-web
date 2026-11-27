# tests/browser/test_r18_calls_ways_in.py -- R18 dock (the owner, 27 Nov 2026: "Calls not in the bar
# at 1920"). At 1920 x 1080 the bar is the bar before R18 (tests/browser/test_dock_fit.py): the
# Calls tab is not in it and no More shows for it. Each way in to Calls is checked there: Vitals'
# calls line (a link, ?open=calls), the chat's call card (Edit; Open the record) and the address
# ?open=calls; at 2560 x 1440 the Calls tab is in the bar. The Calls routes are stubbed in the page
# (tests/browser/r18_calls_stub.py), as in test_r18_e_calls.py.
from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest
from r18_calls_stub import RECORDS
from test_r18_e_calls import CHAT_CARD, Calls, until

sync_playwright = pytest.importorskip("playwright.sync_api").sync_playwright
pytestmark = pytest.mark.browser

FULL_HD = {"width": 1920, "height": 1080}
WIDE = {"width": 2560, "height": 1440}
SETTLE_JS = (
    "() => document.fonts.ready.then(() => new Promise("
    "(r) => requestAnimationFrame(() => requestAnimationFrame(r))))"
)
# A card whose call has ended: the chat shows "Open the record" (the stub's first record).
DONE_CARD = {
    **CHAT_CARD,
    "id": "cc_0000000000b1",
    "status": "used",
    "call_id": RECORDS[0]["id"],
    "call_state": "ended",
}


@pytest.fixture(scope="module")
def browser() -> Iterator[Any]:
    with sync_playwright() as p:
        b = p.chromium.launch()
        yield b
        b.close()


@pytest.fixture
def full_hd(browser: Any, server_url: str, token: str) -> Iterator[Calls]:
    c = Calls(browser, server_url, token, FULL_HD)
    yield c
    c.close()


def _not_in_the_dock(c: Calls) -> None:
    """Full HD: the Calls tab is not in the bar, and no More button shows for it."""
    c.page.evaluate(SETTLE_JS)
    assert c.page.locator('.dk[data-open="calls"]').is_hidden()
    assert c.page.locator("#dockMore").is_hidden()


def _calls_open(c: Calls) -> None:
    c.page.locator("#p-calls").wait_for(state="visible")
    c.page.locator("#p-calls .cl-ready .vt-chip").first.wait_for()  # the panel loaded


def test_vitals_calls_line_opens_calls_at_full_hd(full_hd: Calls) -> None:
    c = full_hd
    c.open()
    _not_in_the_dock(c)
    c.open_panel("vitals")
    link = c.page.locator("#p-vitals #sCallsOpen")
    assert link.text_content() == "Calls this month"
    assert link.get_attribute("href") == "?open=calls"  # the deep link (a new tab gets it too)
    assert link.get_attribute("class") == "nanchor"  # the console's own in-text link look
    line = c.page.locator("#sCalls")
    until(c.page, lambda: line.text_content() == "≈ ₹12.40 of ₹200", "the calls line")
    address = c.page.url
    link.focus()
    c.page.keyboard.press("Enter")  # the keyboard way; a click is the same press
    _calls_open(c)
    assert c.page.url == address  # opened here, no reload
    assert c.page.evaluate("document.activeElement.id") == "t-calls"  # focus on the panel
    _not_in_the_dock(c)
    c.page.locator("#p-calls [data-close]").click()
    c.page.locator("#p-calls").wait_for(state="hidden")
    link.click()
    _calls_open(c)
    c.clean()


def _with_cards(route: Any) -> None:
    resp = route.fetch()
    body = resp.json()
    body["cards"] = [*body.get("cards", []), CHAT_CARD, DONE_CARD]
    route.fulfill(response=resp, json=body)


def test_the_chat_call_card_opens_calls_at_full_hd(full_hd: Calls) -> None:
    c = full_hd
    c.page.route("**/v1/chat", _with_cards)
    c.open()
    _not_in_the_dock(c)
    c.send("Call the clinic and book a check-up next week")
    waiting = c.page.locator(f'#log .cl-card[data-card="{CHAT_CARD["id"]}"]')
    done = c.page.locator(f'#log .cl-card[data-card="{DONE_CARD["id"]}"]')
    waiting.wait_for()
    done.wait_for()
    # Edit: Calls -> New call with the card
    waiting.get_by_role("button", name="Edit", exact=True).click()
    _calls_open(c)
    assert c.page.locator("#clt-new").get_attribute("aria-selected") == "true"
    assert c.pane("new").get_by_label("Purpose").input_value() == CHAT_CARD["purpose"]
    c.page.locator("#p-calls [data-close]").click()
    c.page.locator("#p-calls").wait_for(state="hidden")
    # Open the record: Calls -> Calls with that call's record (the panel opens for it)
    done.get_by_role("button", name="Open the record", exact=True).click()
    _calls_open(c)
    assert c.page.locator("#clt-calls").get_attribute("aria-selected") == "true"
    record = c.pane("calls").get_by_role("heading", name=RECORDS[0]["contact_name"], exact=True)
    record.wait_for()  # the record's title (Laundry), not the list
    assert c.stub.calls("GET", f"/v1/calls/records/{RECORDS[0]['id']}")
    _not_in_the_dock(c)
    c.clean()


def test_the_address_opens_calls_at_full_hd(full_hd: Calls) -> None:
    c = full_hd
    c.open("/?open=calls")
    _calls_open(c)
    assert "open=" not in c.page.url  # taken out of the address: a reload never repeats it
    _not_in_the_dock(c)
    c.clean()


def test_a_wide_screen_has_the_calls_tab_in_the_bar(
    browser: Any, server_url: str, token: str
) -> None:
    c = Calls(browser, server_url, token, WIDE)
    try:
        c.open()
        c.page.evaluate(SETTLE_JS)
        tab = c.page.locator('.dk[data-open="calls"]')
        assert tab.is_visible()  # beside every other tab: it displaces none
        tab.click()
        _calls_open(c)
        assert tab.get_attribute("aria-pressed") == "true"
        c.clean()
    finally:
        c.close()
