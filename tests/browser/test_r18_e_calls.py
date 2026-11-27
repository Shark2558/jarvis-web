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

    def _on_console(self, msg: Any) -> None:
        if msg.type == "error" and "/v1/calls/templates" in str(msg.location.get("url", "")) + msg.text and "404" in msg.text:
            return  # a server without templates: New call says nothing (asserted where it matters)
        super()._on_console(msg)

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
