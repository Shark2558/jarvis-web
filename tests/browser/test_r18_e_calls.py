# tests/browser/test_r18_e_calls.py -- R18 E in a real Chromium (docs/plans/r18-calls.md sections 4-6;
# docs/plans/r18-calls/BUILD-BRIEF.md row E), the Calls routes and the live socket stubbed in the page
# (tests/browser/r18_calls_stub.py): the Calls panel (the readiness line, today's and recent calls, a
# record with its summary, both-language transcript, recording, Keep, Delete and Undo), New call (the
# Laundry templates, the booking fields, the languages that passed, the card, Call with a passkey),
# the call card in the chat (Call, Edit, Cancel), the live call (captions, Listen live through the
# AudioWorklet, Captions only, Take over, Tell JARVIS, Hang up), the language table and its Run with
# an estimate and a confirm, Settings (raising a cap or switching answering on asks first), Vitals'
# calls line, keyboard order, focus and reduced motion. The look: tests/browser/test_r18_e_look.py.
# ruff: noqa: E501 -- JavaScript strings
from __future__ import annotations

import json
import time
from collections.abc import Callable, Iterator
from datetime import UTC, datetime
from typing import Any

import pytest
from r18_calls_stub import LIVE_ID, STATUS, CallsStub
from test_console import CSP_SPY, DESKTOP, PHONE, Console

sync_playwright = pytest.importorskip("playwright.sync_api").sync_playwright
pytestmark = pytest.mark.browser
PAGE_NOW = datetime(2026, 11, 27, 9, 0, tzinfo=UTC)  # 14:30 IST, the stub's "today"

# A signed passkey as the browser would hand it back (the test page has no authenticator).
FAKE_PASSKEY = """
Object.defineProperty(navigator.credentials, 'get', { configurable: true, value: async () => {
  const b = (n) => new Uint8Array([n, n + 1, n + 2]).buffer;
  return { id: 'cred-test', rawId: b(1), type: 'public-key',
    response: { clientDataJSON: b(2), authenticatorData: b(3), signature: b(4), userHandle: null } };
} });
"""


@pytest.fixture(scope="module")
def browser() -> Iterator[Any]:
    with sync_playwright() as p:
        b = p.chromium.launch(args=["--autoplay-policy=no-user-gesture-required"])
        yield b
        b.close()


def until(page: Any, check: Callable[[], Any], what: str, timeout_s: float = 15.0) -> None:
    end = time.monotonic() + timeout_s
    while time.monotonic() < end:
        if check():
            return
        page.wait_for_timeout(100)
    raise AssertionError(f"timed out waiting for {what}")


class Calls(Console):
    """A signed-in console with the Calls routes stubbed; IST clock pinned to 27 Nov 2026, 14:30."""

    def __init__(self, browser: Any, url: str, token: str, viewport: dict[str, int] = DESKTOP, *,
                 status: dict[str, Any] | None = None, templates: bool = True, layout: dict[str, Any] | None = None,
                 reduced: bool = False) -> None:
        self.url, self.token, self.errors = url, token, []
        self.ctx = browser.new_context(viewport=viewport, timezone_id="Asia/Kolkata", locale="en-IN",
                                       reduced_motion="reduce" if reduced else "no-preference")
        self.page = self.ctx.new_page()
        self.page.add_init_script(CSP_SPY)
        self.page.add_init_script(FAKE_PASSKEY)
        if layout is not None:
            self.page.add_init_script(f"localStorage.setItem('jarvis_deck_v1', {json.dumps(json.dumps(layout))});")
        self.page.on("pageerror", lambda e: self.errors.append(f"pageerror: {e}"))
        self.page.on("console", self._on_console)
        self.page.clock.set_system_time(PAGE_NOW)
        self.stub = CallsStub(self.page, status=status, templates=templates)

    def calls(self) -> None:
        self.open()
        self.open_panel("calls")
        self.page.locator("#p-calls .cl-ready .vt-chip").first.wait_for()

    def tab(self, name: str) -> None:
        self.page.locator("#p-calls .hp-tab", has_text=name).click()

    def pane(self, tid: str) -> Any:
        return self.page.locator(f"#clp-{tid}")

    def text(self, sel: str = "#p-calls") -> str:
        return str(self.page.locator(sel).text_content())  # as written (CSS may uppercase what it shows)

    def button(self, name: str, within: str = "#p-calls") -> Any:
        return self.page.locator(within).get_by_role("button", name=name, exact=True)

    def clean(self) -> None:
        assert self.errors == [], self.errors
        assert self.csp_violations() == []


@pytest.fixture
def calls(browser: Any, server_url: str, token: str) -> Iterator[Calls]:
    c = Calls(browser, server_url, token)
    yield c
    c.close()


# ---- the panel: readiness, today's and recent calls ---------------------------------------------
def test_the_calls_tab_opens_the_panel_with_its_readiness_line_and_the_calls(calls: Calls) -> None:
    calls.calls()
    ready = calls.text("#p-calls .cl-ready")
    assert "Laptop desk: ready" in ready and "Phone: linked" in ready
    assert "1 of 10 calls today" in ready and "₹12.40 of ₹200" in ready
    calls.page.locator("#clp-calls .hp-row").first.wait_for()
    rows = calls.page.locator("#clp-calls .hp-row")
    assert rows.count() == 3
    first = str(rows.nth(0).text_content())
    assert "Laundry" in first and "14:05" in first and "3:12" in first and "Malayalam, English" in first
    assert "₹1.20" in first and "Ended" in first
    assert "Today" in calls.text("#clp-calls") and "Earlier this week" in calls.text("#clp-calls")
    assert "No answer" in str(rows.nth(1).text_content()) and "•••••• 0002" in str(rows.nth(1).text_content())
    assert "From •••••• 0003" in str(rows.nth(2).text_content())
    assert calls.page.locator("#callsMeta").text_content() == "Today 1"
    assert calls.stub.calls("GET", "/v1/calls/records?limit=50")
    calls.clean()


def test_nothing_is_asked_before_the_panel_opens_and_a_restored_panel_loads_by_itself(
    browser: Any, server_url: str, token: str
) -> None:
    c = Calls(browser, server_url, token)
    try:
        c.open()
        c.page.wait_for_timeout(600)
        assert c.stub.sent == []  # closed panel: no request at sign-in
    finally:
        c.close()
    layout = {"v": 1, "p": {"chat": {"x": 900, "y": 120, "w": 420, "h": 600, "open": True},
                            "calls": {"x": 220, "y": 120, "w": 440, "h": 700, "open": True}}}
    c = Calls(browser, server_url, token, layout=layout)
    try:
        c.open()
        c.page.locator("#p-calls").wait_for(state="visible")  # restored: no jarvis:panel event
        c.page.locator("#clp-calls .hp-row").first.wait_for()
        assert c.stub.calls("GET", "/v1/calls/status")
        c.clean()
    finally:
        c.close()


def test_a_bluetooth_headset_and_a_missing_desk_say_so_and_the_card_cannot_call(
    browser: Any, server_url: str, token: str
) -> None:
    status = {**STATUS, "desk": {**STATUS["desk"], "connected": True, "ready": False, "bt_headset": True},
              "phone": {"linked": False}}
    c = Calls(browser, server_url, token, status=status)
    try:
        c.calls()
        ready = c.text("#p-calls .cl-ready")
        assert "Laptop desk: needs you" in ready and "Phone: not linked" in ready
        assert "Bluetooth headset" in ready and "Phone Link refuses calls" in ready
        assert "Link the JARVIS phone app" in ready
        c.tab("New call")
        c.pane("new").locator("select").first.select_option("laundry_ready")
        c.button("Make the card").click()
        card = c.page.locator("#clp-new .cl-card")
        card.wait_for()
        assert "Phone Link refuses calls" in str(card.text_content())
        assert c.button("Call", "#clp-new .cl-card").is_disabled()
        c.clean()
    finally:
        c.close()


# ---- a call's record --------------------------------------------------------------------------
def test_a_record_shows_its_summary_both_languages_audio_and_keep_delete_undo(calls: Calls) -> None:
    calls.calls()
    calls.page.locator("#clp-calls .hp-row").first.wait_for()
    calls.page.get_by_role("button", name="Open the record of Laundry").click()
    rec = calls.page.locator("#clp-calls .cl-record")
    rec.locator(".cl-transcript .cl-line").first.wait_for()
    assert calls.page.evaluate("document.activeElement.className") == "cl-rtitle"  # its title, once loaded
    text = calls.text("#clp-calls .cl-record")
    assert "The laundry will pick up tomorrow at 10:00." in text and "JARVIS said goodbye." in text
    said = rec.locator(".cl-said span").nth(1)
    assert said.get_attribute("lang") == "ml" and said.get_attribute("dir") == "auto"
    assert "നാളെ" in str(said.text_content())
    assert "In English: We can come tomorrow at ten." in text
    assert "Deleted by itself on 27 Dec" in text
    # the recording: fetched on the first Play only, decoded with Web Audio (no <audio>: CSP media-src)
    assert not calls.stub.calls("GET", "/audio") and rec.locator("audio").count() == 0
    play = calls.button("Play", "#clp-calls .cl-record")
    play.click()
    until(calls.page, lambda: calls.button("Pause", "#clp-calls .cl-record").count() == 1, "the recording playing")
    assert calls.stub.calls("GET", "/v1/calls/records/call_0000000000a1/audio")
    seek = rec.locator("input.cl-seek")
    assert seek.get_attribute("aria-label") == "Position in the recording"
    calls.button("Pause", "#clp-calls .cl-record").click()
    # Undo the calendar entry the booking added
    calls.page.get_by_role("button", name="Undo: remove the calendar entry this call added").click()
    until(calls.page, lambda: "Removed from your calendar." in calls.text("#clp-calls .cl-record"), "the undo")
    assert calls.stub.calls("POST", "/booking/undo")
    # Keep, then Stop keeping
    calls.button("Keep this call", "#clp-calls .cl-record").click()
    until(calls.page, lambda: "Kept: it stays until you delete it." in calls.text("#clp-calls .cl-record"), "kept")
    assert calls.stub.calls("PUT", "/keep")[-1][2] == {"keep": True}
    # Delete asks first; Keep (Esc) leaves it; Delete deletes and goes back to the list
    calls.button("Delete", "#clp-calls .cl-record").click()
    box = rec.locator(".confirm")
    assert "This can’t be undone." in str(box.text_content())
    assert calls.page.evaluate("document.activeElement.textContent") == "Keep"
    calls.page.keyboard.press("Escape")
    assert rec.locator(".confirm").count() == 0 and not calls.stub.calls("DELETE", "/v1/calls/records/")
    calls.button("Delete", "#clp-calls .cl-record").click()
    rec.locator(".confirm .btn.danger").click()
    until(calls.page, lambda: calls.page.locator("#clp-calls .hp-row").count() == 2, "the list without the call")
    assert calls.stub.calls("DELETE", "/v1/calls/records/call_0000000000a1")
    calls.clean()


def test_an_objection_says_why_there_is_no_recording(calls: Calls) -> None:
    calls.calls()
    calls.page.locator("#clp-calls .hp-row").nth(2).locator(".btn").click()
    calls.page.locator("#clp-calls .cl-record .cl-transcript").wait_for()
    text = calls.text("#clp-calls .cl-record")
    assert "They asked not to be recorded" in text and "Answered for you" in text
    assert "Kept: it stays until you delete it." in text and calls.button("Stop keeping", "#clp-calls .cl-record").count() == 1
    hindi = calls.page.locator("#clp-calls .cl-said span").first
    assert hindi.get_attribute("lang") == "hi"
    calls.clean()


# ---- New call: a template, the booking, the languages, the card, Call with a passkey -----------
def test_new_call_from_the_laundry_template_makes_a_card_and_calls_with_a_passkey(calls: Calls) -> None:
    calls.calls()
    calls.tab("New call")
    pane = calls.pane("new")
    sel = pane.locator("select").first
    until(calls.page, lambda: sel.locator("option").count() == 4, "the three Laundry templates")
    assert "Laundry: book a pickup" in str(sel.text_content()) and "Laundry: deliver it back" in str(sel.text_content())
    sel.select_option("laundry_pickup")
    assert pane.get_by_label("Purpose").input_value() == "Book a laundry pickup"
    assert "Leave it empty to call the number ending 0001." in calls.text("#clp-new")
    assert pane.get_by_label("Name to give").input_value() == "Arun"
    assert pane.get_by_label("Day 1").input_value() == "2026-11-28"
    # only the languages that passed; Odia failed and is not offered; at most 3 Indian languages
    langs = calls.text("#clp-new .cl-langs")
    assert "Malayalam (not yet heard by a native speaker)" in langs and "Hindi" in langs and "Odia" not in langs
    assert pane.get_by_label("Malayalam (not yet heard by a native speaker)").is_checked()
    pane.get_by_label("Hindi").check()
    pane.get_by_label("Tamil").check()
    assert pane.get_by_label("Kannada (not yet heard by a native speaker)").is_disabled()  # three already
    pane.get_by_label("Tamil").uncheck()
    pane.get_by_label("It opens in").select_option("ml-IN")
    # a second time window, then remove it
    calls.button("Add a time", "#clp-new").click()
    pane.get_by_label("Day 2").fill("2026-11-29")
    calls.button("Remove time 2", "#clp-new").click()
    calls.button("Make the card", "#clp-new").click()
    card = pane.locator(".cl-card")
    card.wait_for()
    body = calls.stub.calls("POST", "/v1/calls/cards")[-1][2]
    assert body["template"] == "laundry_pickup" and "number" not in body
    assert body["languages"] == ["ml-IN", "en-IN", "hi-IN"] and body["limits"] == {"max_minutes": 5}
    assert body["booking"]["windows"] == [{"day": "2026-11-28", "start": "10:00", "end": "12:00"}]
    assert body["booking"]["no_payment"] is True and body["booking"]["give_name"] == "Arun"
    text = str(card.text_content())
    assert "•••••• 0001" in text and "Book a laundry pickup" in text
    assert "Sat 28 Nov, 10:00–12:00" in text and "Malayalam (opens), English, Hindi" in text
    assert "₹1.35" in text and "never agrees to pay" in text and "AI assistant" in text
    assert calls.page.evaluate("document.activeElement.textContent") == "Call"
    calls.button("Call", "#clp-new .cl-card").click()
    until(calls.page, lambda: calls.stub.calls("POST", "/approve"), "the approval")
    assert "passkey" not in (calls.stub.calls("POST", "/approve")[-1][2] or {})  # a number called before
    calls.page.locator("#clp-calls .cl-live").wait_for(state="visible")  # the live call opens
    until(calls.page, lambda: calls.stub.ws is not None, "the live socket")
    assert calls.stub.ws_url.endswith("/v1/calls/" + LIVE_ID + "/live")
    calls.clean()


def test_a_new_number_asks_for_the_passkey_before_the_approval(calls: Calls) -> None:
    calls.calls()
    calls.tab("New call")
    pane = calls.pane("new")
    calls.button("Make the card", "#clp-new").click()
    assert calls.text("#clp-new .lerr") == "Type the number to call."
    assert pane.get_by_label("Number to call").get_attribute("aria-invalid") == "true"
    pane.get_by_label("Number to call").fill("90000 00007")
    pane.get_by_label("Purpose").fill("Ask whether the shop is open on Sunday")
    calls.button("Make the card", "#clp-new").click()
    pane.locator(".cl-card").wait_for()
    assert calls.stub.calls("POST", "/v1/calls/cards")[-1][2]["number"] == "+919000000007"
    text = str(pane.locator(".cl-card").text_content())
    assert "•••••• 0007" in text and "90000" not in calls.text("#clp-new .cl-card")
    assert "your passkey is asked" in text
    calls.button("Call with passkey", "#clp-new .cl-card").click()
    until(calls.page, lambda: calls.stub.calls("POST", "/approve"), "the approval")
    sent = calls.stub.calls("POST", "/approve")[-1][2]
    assert sent["passkey"]["challenge_id"] == "pc_test1" and sent["passkey"]["credential"]["id"] == "cred-test"
    assert calls.stub.calls("POST", "/v1/passkeys/challenge")[-1][2]["purpose"] == "approve"
    calls.page.locator("#clp-calls .cl-live").wait_for(state="visible")
    calls.clean()


def test_a_server_without_ready_cards_still_makes_blank_cards(browser: Any, server_url: str, token: str) -> None:
    c = Calls(browser, server_url, token, templates=False)
    try:
        c.calls()
        c.tab("New call")
        c.page.wait_for_timeout(300)
        assert c.pane("new").locator("select").first.locator("option").count() == 1
        assert c.text("#clp-new .snote") == ""
        c.clean()
    finally:
        c.close()
