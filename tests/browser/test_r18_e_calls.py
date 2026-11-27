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

    def __init__(
        self,
        browser: Any,
        url: str,
        token: str,
        viewport: dict[str, int] = DESKTOP,
        *,
        status: dict[str, Any] | None = None,
        templates: bool = True,
        layout: dict[str, Any] | None = None,
        reduced: bool = False,
    ) -> None:
        self.url, self.token, self.errors = url, token, []
        self.ctx = browser.new_context(
            viewport=viewport,
            timezone_id="Asia/Kolkata",
            locale="en-IN",
            reduced_motion="reduce" if reduced else "no-preference",
        )
        self.page = self.ctx.new_page()
        self.page.add_init_script(CSP_SPY)
        self.page.add_init_script(FAKE_PASSKEY)
        if layout is not None:
            self.page.add_init_script(
                f"localStorage.setItem('jarvis_deck_v1', {json.dumps(json.dumps(layout))});"
            )
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
        return str(
            self.page.locator(sel).text_content()
        )  # as written (CSS may uppercase what it shows)

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
    assert (
        "Laundry" in first
        and "14:05" in first
        and "3:12" in first
        and "Malayalam, English" in first
    )
    assert "₹1.20" in first and "Ended" in first
    assert "Today" in calls.text("#clp-calls") and "Earlier this week" in calls.text("#clp-calls")
    assert "No answer" in str(rows.nth(1).text_content()) and "•••••• 0002" in str(
        rows.nth(1).text_content()
    )
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
    layout = {
        "v": 1,
        "p": {
            "chat": {"x": 900, "y": 120, "w": 420, "h": 600, "open": True},
            "calls": {"x": 220, "y": 120, "w": 440, "h": 700, "open": True},
        },
    }
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
    status = {
        **STATUS,
        "desk": {**STATUS["desk"], "connected": True, "ready": False, "bt_headset": True},
        "phone": {"linked": False},
    }
    c = Calls(browser, server_url, token, status=status)
    try:
        c.calls()
        ready = c.text("#p-calls .cl-ready")
        assert "Laptop desk: needs you" in ready and "Phone: not linked" in ready
        assert "Bluetooth headset" in ready and "Phone Link refuses calls" in ready
        assert "Link the JARVIS phone app" in ready
        c.tab("New call")
        sel = c.pane("new").locator("select").first
        until(c.page, lambda: sel.locator("option").count() == 4, "the ready cards")
        sel.select_option("laundry_status")
        c.pane("new").get_by_label("Who it is (a saved contact, or a name for the card)").fill(
            "Laundry"
        )
        c.pane("new").get_by_label("Name to give").fill("Arun")
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
    assert (
        calls.page.evaluate("document.activeElement.className") == "cl-rtitle"
    )  # its title, once loaded
    text = calls.text("#clp-calls .cl-record")
    assert "The laundry will pick up tomorrow at 10:00." in text and "JARVIS said goodbye." in text
    assert (
        "Pickup on Sat 28 Nov at 10:00" in text and "Keep the bag ready by 10:00" in text
    )  # agreed, next steps
    said = rec.locator(".cl-said span").nth(1)
    assert said.get_attribute("lang") == "ml" and said.get_attribute("dir") == "auto"
    assert "നാളെ" in str(said.text_content())
    assert "In English: We can come tomorrow at ten." in text
    assert "Deleted by itself on 27 Dec" in text
    # the recording: fetched on the first Play only, decoded with Web Audio (no <audio>: CSP media-src)
    assert not calls.stub.calls("GET", "/audio") and rec.locator("audio").count() == 0
    play = calls.button("Play", "#clp-calls .cl-record")
    play.click()
    until(
        calls.page,
        lambda: calls.button("Pause", "#clp-calls .cl-record").count() == 1,
        "the recording playing",
    )
    assert calls.stub.calls("GET", "/v1/calls/records/call_0000000000a1/audio")
    seek = rec.locator("input.cl-seek")
    assert seek.get_attribute("aria-label") == "Position in the recording"
    calls.button("Pause", "#clp-calls .cl-record").click()
    # Undo the calendar entry the booking added
    calls.page.get_by_role("button", name="Undo: remove the calendar entry this call added").click()
    until(
        calls.page,
        lambda: "The pickup was taken off your calendar." in calls.text("#clp-calls .cl-record"),
        "the undo",
    )
    assert calls.stub.calls("POST", "/booking/undo")
    # Keep, then Stop keeping
    calls.button("Keep this call", "#clp-calls .cl-record").click()
    until(
        calls.page,
        lambda: "Kept: it stays until you delete it." in calls.text("#clp-calls .cl-record"),
        "kept",
    )
    assert calls.stub.calls("PUT", "/keep")[-1][2] == {"keep": True}
    # Delete asks first; Keep (Esc) leaves it; Delete deletes and goes back to the list
    calls.button("Delete", "#clp-calls .cl-record").click()
    box = rec.locator(".confirm")
    assert "This can’t be undone." in str(box.text_content())
    assert calls.page.evaluate("document.activeElement.textContent") == "Keep"
    calls.page.keyboard.press("Escape")
    assert rec.locator(".confirm").count() == 0 and not calls.stub.calls(
        "DELETE", "/v1/calls/records/"
    )
    calls.button("Delete", "#clp-calls .cl-record").click()
    rec.locator(".confirm .btn.danger").click()
    until(
        calls.page,
        lambda: calls.page.locator("#clp-calls .hp-row").count() == 2,
        "the list without the call",
    )
    assert calls.stub.calls("DELETE", "/v1/calls/records/call_0000000000a1")
    calls.clean()


def test_an_objection_says_why_there_is_no_recording(calls: Calls) -> None:
    calls.calls()
    calls.page.locator("#clp-calls .hp-row").nth(2).locator(".btn").click()
    calls.page.locator("#clp-calls .cl-record .cl-transcript").wait_for()
    text = calls.text("#clp-calls .cl-record")
    assert "They asked not to be recorded" in text and "Answered for you" in text
    assert "Call back about the delivery" in text and "Message: Courier \u00b7 A delivery" in text
    assert (
        "Kept: it stays until you delete it." in text
        and calls.button("Stop keeping", "#clp-calls .cl-record").count() == 1
    )
    hindi = calls.page.locator("#clp-calls .cl-said span").first
    assert hindi.get_attribute("lang") == "hi"
    calls.clean()


# ---- New call: a ready card, the booking, the languages, the card, Call with a passkey ----------
def test_new_call_from_the_laundry_pickup_makes_a_card_and_calls(calls: Calls) -> None:
    calls.calls()
    calls.tab("New call")
    pane = calls.pane("new")
    sel = pane.locator("select").first
    until(calls.page, lambda: sel.locator("option").count() == 4, "the three ready cards")
    names = str(sel.text_content())
    assert (
        "Book a laundry pickup" in names
        and "Ask about the laundry" in names
        and "Book an appointment" in names
    )
    sel.select_option("laundry_pickup")
    # a ready card writes its own purpose and lines: only its fields show
    assert (
        pane.get_by_label("Purpose").is_hidden()
        and pane.get_by_label("How many items (optional)").is_visible()
    )
    assert (
        pane.get_by_label("Order number or note (optional)").is_hidden()
        and pane.get_by_label("Reason").is_hidden()
    )
    assert "JARVIS writes this card" in calls.text("#clp-new")
    # only the languages that passed; Odia failed and is not offered; at most 3 Indian languages
    until(calls.page, lambda: pane.locator(".cl-lang").count() == 5, "the languages that passed")
    langs = calls.text("#clp-new .cl-langs")
    assert (
        "Malayalam (not yet heard by a native speaker)" in langs
        and "Hindi" in langs
        and "Odia" not in langs
    )
    assert pane.get_by_label(
        "Malayalam (not yet heard by a native speaker)"
    ).is_checked()  # the laundry's own
    assert pane.get_by_label("It opens in").input_value() == "ml-IN"
    pane.get_by_label("Hindi").check()
    pane.get_by_label("Tamil").check()
    assert pane.get_by_label(
        "Kannada (not yet heard by a native speaker)"
    ).is_disabled()  # three already
    pane.get_by_label("Tamil").uncheck()
    pane.get_by_label("Who it is (a saved contact, or a name for the card)").fill("Laundry")
    pane.get_by_label("Name to give").fill("Arun")
    pane.get_by_label("How many items (optional)").fill("6")
    pane.get_by_label("Day 1").fill("2026-11-28")
    pane.get_by_label("Time 1: from").fill("10:00")
    pane.get_by_label("Time 1: until").fill("12:00")
    calls.button("Add a time", "#clp-new").click()  # a second window, then remove it
    pane.get_by_label("Day 2").fill("2026-11-29")
    calls.button("Remove time 2", "#clp-new").click()
    calls.button("Make the card", "#clp-new").click()
    card = pane.locator(".cl-card")
    card.wait_for()
    body = calls.stub.calls("POST", "/v1/calls/cards")[-1][2]
    assert body == {
        "template": "laundry_pickup",
        "fields": {
            "languages": ["ml-IN", "en-IN", "hi-IN"],
            "max_minutes": 6,
            "contact": "Laundry",
            "give_name": "Arun",
            "windows": [{"day": "2026-11-28", "start": "10:00", "end": "12:00"}],
            "items": 6,
        },
    }
    text = str(card.text_content())
    assert (
        "\u2022\u2022\u2022\u2022\u2022\u2022 0001" in text
        and "Book a laundry pickup" in text
        and "Call Laundry" in text
    )
    assert "Sat 28 Nov, 10:00\u201312:00" in text and "Malayalam (opens), English, Hindi" in text
    assert "\u20b91.35" in text and "never agrees to pay" in text and "AI assistant" in text
    assert "90000" not in text  # the view carries the whole number: never shown
    assert calls.page.evaluate("document.activeElement.textContent") == "Call"
    calls.button("Call", "#clp-new .cl-card").click()
    until(calls.page, lambda: calls.stub.calls("POST", "/approve"), "the approval")
    assert calls.stub.calls("POST", "/approve")[-1][2] == {}  # a number called before: one press
    calls.page.locator("#clp-calls .cl-live").wait_for(state="visible")  # the live call opens
    until(calls.page, lambda: calls.stub.ws is not None, "the live socket")
    assert calls.stub.ws_url.endswith("/v1/calls/" + LIVE_ID + "/live")
    calls.clean()


def test_a_new_number_is_approved_with_a_passkey_and_edit_replaces_the_card(calls: Calls) -> None:
    calls.calls()
    calls.tab("New call")
    pane = calls.pane("new")
    calls.button("Make the card", "#clp-new").click()
    assert (
        calls.text("#clp-new .lerr") == "Type the number to call, or a saved contact\u2019s name."
    )
    assert pane.get_by_label("Number to call").get_attribute("aria-invalid") == "true"
    pane.get_by_label("Number to call").fill("90000 00007")
    pane.get_by_label("Purpose").fill("Ask whether the shop is open on Sunday")
    calls.button("Make the card", "#clp-new").click()
    pane.locator(".cl-card").wait_for()
    first = calls.stub.calls("POST", "/v1/calls/cards")[-1][2]
    assert (
        first["number"] == "+919000000007"
        and first["purpose"] == "Ask whether the shop is open on Sunday"
    )
    assert set(first) <= {
        "number",
        "contact",
        "purpose",
        "may_say",
        "may_agree",
        "languages",
        "template",
        "booking",
        "max_minutes",
    }
    assert "your passkey approves it" in str(pane.locator(".cl-card").text_content())
    # Edit: the fields come back; saving makes a new card that replaces this one (the number kept)
    old = pane.locator(".cl-card").get_attribute("data-card")
    calls.button("Edit", "#clp-new .cl-card").click()
    pane.get_by_label("Purpose").fill("Ask whether the shop is open on Sunday morning")
    calls.button("Save as a new card", "#clp-new").click()
    pane.locator(".cl-card").wait_for()
    second = calls.stub.calls("POST", "/v1/calls/cards")[-1][2]
    assert second["replaces"] == old and second["number"] == "+919000000007"
    assert "90000" not in calls.text("#clp-new")
    # Call: the cloud asks for his passkey for this approval; his next press signs it
    calls.button("Call", "#clp-new .cl-card").click()
    approve = calls.button("Approve with passkey", "#clp-new .cl-card")
    approve.wait_for()
    assert calls.stub.calls("POST", "/approve")[-1][2] == {}
    assert calls.page.evaluate("document.activeElement.textContent") == "Approve with passkey"
    approve.click()
    until(calls.page, lambda: len(calls.stub.calls("POST", "/approve")) == 2, "the second press")
    sent = calls.stub.calls("POST", "/approve")[-1][2]
    assert sent["approval_id"] == "ap_test1" and sent["passkey"]["challenge_id"] == "pc_test1"
    assert sent["passkey"]["credential"]["id"] == "cred-test"
    assert calls.stub.calls("POST", "/v1/passkeys/challenge")[-1][2] == {
        "purpose": "approve",
        "approval_id": "ap_test1",
    }
    calls.page.locator("#clp-calls .cl-live").wait_for(state="visible")
    calls.clean()


def test_a_server_without_ready_cards_still_makes_blank_cards(
    browser: Any, server_url: str, token: str
) -> None:
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


# ---- the call card in the chat ------------------------------------------------------------------
CHAT_CARD = {
    "kind": "call_card",
    "id": "cc_00000000c0de",
    "status": "draft",
    "number_e164": "+919000000004",
    "contact_name": "Clinic",
    "purpose": "Book a check-up next week",
    "may_say": ["My name and that I am a patient"],
    "may_agree": ["A slot inside the times below"],
    "languages": ["en-IN", "hi-IN"],
    "booking": {
        "windows": [{"day": "2026-12-01", "start": "09:00", "end": "11:00"}],
        "give_name": "Arun",
        "give_number": "+919000000009",
        "reason": "A check-up",
        "no_payment": True,
        "duration_minutes": 30,
        "add_to_calendar": True,
    },
    "limits": {"max_minutes": 6, "max_inr": 20},
    "estimate_inr": 1.1,
    "new_number": False,
    "ready": {"ok": True, "problems": []},
}


def _with_card(route: Any) -> None:
    resp = route.fetch()
    body = resp.json()
    body["cards"] = [
        *body.get("cards", []),
        CHAT_CARD,
        {"kind": "call_card", "id": "not a card id"},
    ]
    route.fulfill(response=resp, json=body)


def test_the_call_card_in_the_chat_shows_the_whole_card_and_edit_and_cancel_work(
    calls: Calls,
) -> None:
    calls.page.route("**/v1/chat", _with_card)
    calls.open()
    calls.send("Call the clinic and book a check-up next week")
    card = calls.page.locator("#log .cl-card")
    card.wait_for()
    assert card.count() == 1  # the malformed card is dropped
    text = str(card.text_content())
    assert "Call Clinic" in text and "•••••• 0004" in text and "•••••• 0009" in text
    assert "90000" not in text  # never the whole number, even when the view sends it
    assert "Book a check-up next week" in text and "My name and that I am a patient" in text
    assert "Tue 1 Dec, 09:00–11:00" in text and "English (opens), Hindi" in text
    assert (
        "Adds a 30-minute entry after the call, with Undo" in text and "₹1.10 (at most ₹20)" in text
    )
    assert (
        card.get_attribute("aria-labelledby") and calls.button("Call", "#log .cl-card").is_enabled()
    )
    calls.button("Edit", "#log .cl-card").click()
    calls.page.locator("#p-calls").wait_for(state="visible")
    assert calls.page.locator("#clt-new").get_attribute("aria-selected") == "true"
    assert calls.pane("new").get_by_label("Purpose").input_value() == "Book a check-up next week"
    assert calls.pane("new").get_by_label("Name to give").input_value() == "Arun"
    assert calls.button("Save as a new card", "#clp-new").count() == 1
    calls.page.locator('.dk[data-open="chat"]').click()
    calls.button("Cancel", "#log .cl-card").click()
    until(
        calls.page,
        lambda: "Cancelled. Nothing was dialled." in calls.text("#log .cl-card"),
        "the cancel",
    )
    assert calls.stub.calls("POST", "/v1/calls/cards/cc_00000000c0de/cancel")
    assert calls.button("Call", "#log .cl-card").count() == 0
    calls.clean()


# Every AudioWorkletNode the page makes, and what its port is sent (the live audio's PCM).
WORKLET_SPY = """
window.__awn = [];
if (window.AudioWorkletNode) {
  const Orig = window.AudioWorkletNode;
  window.AudioWorkletNode = class extends Orig {
    constructor(ctx, name, opts) {
      super(ctx, name, opts);
      const rec = { name, posts: 0, bytes: 0 };
      window.__awn.push(rec);
      const post = this.port.postMessage.bind(this.port);
      this.port.postMessage = (m, t) => { if (m instanceof ArrayBuffer) { rec.posts += 1; rec.bytes += m.byteLength; } return post(m, t); };
    }
  };
}
"""


# ---- the live call ------------------------------------------------------------------------------
def _live(calls: Calls) -> None:
    calls.stub.status["active"] = {"call_id": LIVE_ID, "state": "talking"}
    calls.calls()
    calls.page.locator("#clp-calls .cl-live").wait_for(
        state="visible"
    )  # a call on: the live view opens
    until(
        calls.page,
        lambda: calls.page.locator("#clp-calls .cl-captions .cl-line").count() == 2,
        "the first captions",
    )


def test_the_live_call_captions_listen_take_over_tell_and_hang_up(calls: Calls) -> None:
    calls.page.add_init_script(WORKLET_SPY)
    _live(calls)
    live = calls.page.locator("#clp-calls .cl-live")
    text = calls.text("#clp-calls .cl-live")
    assert (
        "On the call" in text and "Malayalam · 0:4" in text and "₹0.40" in text
    )  # the seconds tick on
    log = live.locator(".cl-captions")
    assert log.get_attribute("role") == "log" and log.get_attribute("aria-live") == "polite"
    them = log.locator(".cl-line[data-who='them'] .cl-said span")
    assert them.get_attribute("lang") == "ml" and "In English: We can come tomorrow at ten." in str(
        log.text_content()
    )
    assert calls.stub.live_in[0] == {
        "type": "listen",
        "audio": False,
    }  # captions only until he presses
    assert live.get_by_label("Captions only").is_checked()
    live.get_by_text("Listen live", exact=True).click()
    until(
        calls.page, lambda: {"type": "listen", "audio": True} in calls.stub.live_in, "listen live"
    )
    assert live.get_by_label("Listen live").is_checked()
    calls.stub.audio(
        3
    )  # three 0x03 messages of five 20 ms frames: their PCM (without the byte) to the worklet
    until(
        calls.page,
        lambda: calls.page.evaluate("(window.__awn[0] || {}).posts") == 3,
        "the audio in the worklet",
    )
    spy = calls.page.evaluate("window.__awn[0]")
    assert spy["name"] == "jarvis-calls-listen" and spy["bytes"] == 3 * 3200
    live.get_by_text("Captions only", exact=True).click()
    until(
        calls.page,
        lambda: calls.stub.live_in[-1] == {"type": "listen", "audio": False},
        "captions only",
    )
    # Tell JARVIS: silent to the other person, shown here as a note
    live.get_by_label("Tell JARVIS").fill("Ask for Saturday instead")
    live.get_by_label("Tell JARVIS").press("Enter")
    until(
        calls.page,
        lambda: {"type": "tell", "text": "Ask for Saturday instead"} in calls.stub.live_in,
        "tell",
    )
    assert "You to JARVIS: Ask for Saturday instead" in str(log.text_content())
    calls.button("Take over", "#clp-calls .cl-live").click()
    until(calls.page, lambda: {"type": "takeover"} in calls.stub.live_in, "take over")
    assert calls.button("You have the call", "#clp-calls .cl-live").is_disabled()
    assert "your own microphone is back" in calls.text("#clp-calls .cl-live")
    calls.stub.state("taken_over", lang="ml-IN", seconds=80, cost=0.6, taken=True, recording=False)
    until(
        calls.page,
        lambda: "Recording stopped" in calls.text("#clp-calls .cl-live"),
        "the recording note",
    )
    calls.button("Hang up", "#clp-calls .cl-live").click()
    until(calls.page, lambda: {"type": "hangup"} in calls.stub.live_in, "hang up")
    calls.stub.state("ended", seconds=95, cost=0.7, end="owner_hangup")
    until(calls.page, lambda: "You hung up." in calls.text("#clp-calls .cl-live"), "the end")
    assert calls.button("Open the record", "#clp-calls .cl-live").count() == 1
    assert calls.button("Hang up", "#clp-calls .cl-live").is_disabled()
    calls.clean()


def test_the_live_view_says_why_when_the_server_closes_it(calls: Calls) -> None:
    _live(calls)
    calls.stub.ws.close(code=4501, reason="not built")
    until(
        calls.page,
        lambda: "isn’t ready on this JARVIS yet" in calls.text("#clp-calls .cl-live"),
        "the close words",
    )
    calls.page.wait_for_timeout(1500)
    assert (
        calls.stub.ws.url and calls.page.locator("#clp-calls .cl-live .snote.bad").count() == 1
    )  # no retry loop
    calls.clean()


# ---- the language table -------------------------------------------------------------------------
def test_the_language_table_and_run_with_its_estimate_and_a_confirm(calls: Calls) -> None:
    calls.calls()
    calls.tab("Languages")
    pane = calls.pane("langs")
    pane.locator(".hp-row").first.wait_for()
    rows = {
        str(r.locator("b").text_content()): str(r.text_content())
        for r in pane.locator(".hp-row").all()
    }
    assert list(rows)[0] == "English"
    assert (
        "Passed" in rows["Malayalam"]
        and "Google (free allowance)" in rows["Malayalam"]
        and "₹0 a minute" in rows["Malayalam"]
    )
    assert (
        "Not yet heard by a native speaker." in rows["Malayalam"]
        and "Not yet heard" not in rows["Hindi"]
    )
    assert (
        "Failed: Phone-line hearing: 78 % of key facts right (needs 90 %); Character errors"
        in rows["Odia"]
    )
    assert "Needs the balanced brain" in rows["Kannada"] and "₹2.40 a minute" in rows["Kannada"]
    calls.button("Run language check", "#clp-langs").click()
    box = pane.locator(".mbox")
    box.wait_for(state="visible")
    assert "Run the language check for 3 languages?" in str(box.text_content()) and "₹0" in str(
        box.text_content()
    )
    assert calls.page.evaluate("document.activeElement.textContent") == "Not now"
    calls.button("Not now", "#clp-langs").click()
    assert box.is_hidden() and not [
        s for s in calls.stub.calls("POST", "/languages/check") if s[2].get("confirm")
    ]
    calls.button("Run language check", "#clp-langs").click()
    calls.button("Run", "#clp-langs .mbox").click()
    until(
        calls.page, lambda: "The language check is running" in calls.text("#clp-langs"), "the run"
    )
    assert calls.stub.calls("POST", "/languages/check")[-1][2]["confirm"] is True
    assert calls.button("Checking…", "#clp-langs").is_disabled()
    until(
        calls.page,
        lambda: "Being checked now" in calls.text("#clp-langs"),
        "a language being checked",
    )
    calls.clean()


# ---- settings -----------------------------------------------------------------------------------
def test_settings_ask_before_raising_a_cap_or_answering_and_keep_three_languages(
    calls: Calls,
) -> None:
    calls.calls()
    calls.tab("Languages")
    calls.pane("langs").locator(".hp-row").first.wait_for()
    calls.tab("Settings")
    pane = calls.pane("settings")
    month = pane.get_by_label("Calls in a month, in rupees")
    until(calls.page, lambda: month.input_value() == "200", "the settings")
    assert "10 calls a day" in calls.text(
        "#clp-settings"
    ) and "no calls 21:00–08:00 IST" in calls.text("#clp-settings")
    month.fill("300")
    calls.button("Save the caps", "#clp-settings").click()
    assert "Raise the calls caps?" in calls.text(
        "#clp-settings .mbox"
    ) and "₹300 a month" in calls.text("#clp-settings .mbox")
    calls.button("Not now", "#clp-settings").click()
    assert not calls.stub.calls("PUT", "/v1/calls/settings")
    calls.button("Save the caps", "#clp-settings").click()
    calls.button("Raise", "#clp-settings").click()
    until(calls.page, lambda: calls.stub.calls("PUT", "/v1/calls/settings"), "the raise")
    method, path, body = calls.stub.calls("PUT", "/v1/calls/settings")[-1]
    assert body == {
        "month_cap_inr": 300,
        "call_cap_inr": 20,
        "call_max_minutes": 6,
        "confirm_raise": True,
    }
    month.fill("150")
    calls.button("Save the caps", "#clp-settings").click()
    until(
        calls.page, lambda: len(calls.stub.calls("PUT", "/v1/calls/settings")) == 2, "the lower cap"
    )
    assert (
        "confirm_raise" not in calls.stub.calls("PUT", "/v1/calls/settings")[-1][2]
    )  # lowering never asks
    # answering missed calls: off by default; switching on asks
    sw = pane.get_by_role("button", name="Answer the calls I miss")
    assert (
        sw.get_attribute("aria-pressed") == "false"
        and pane.get_by_label("After this many rings").is_hidden()
    )
    sw.click()
    assert "Let JARVIS answer the calls you miss?" in calls.text("#clp-settings .mbox")
    calls.button("Switch on", "#clp-settings .mbox").click()
    until(calls.page, lambda: sw.get_attribute("aria-pressed") == "true", "answering on")
    assert calls.stub.calls("PUT", "/v1/calls/settings")[-1][2] == {
        "answering_on": True,
        "confirm_raise": True,
    }
    pane.get_by_text("Saved contacts", exact=True).click()
    until(
        calls.page,
        lambda: (
            calls.stub.calls("PUT", "/v1/calls/settings")[-1][2] == {"answer_policy": "contacts"}
        ),
        "the policy",
    )
    # default languages: Malayalam ticked; at most three
    for name in ("Hindi", "Tamil"):
        pane.get_by_label(name, exact=True).check()
    assert pane.get_by_label("Kannada", exact=True).is_disabled()
    calls.button("Save the languages", "#clp-settings").click()
    until(
        calls.page,
        lambda: (
            calls.stub.calls("PUT", "/v1/calls/settings")[-1][2].get("default_languages")
            == ["en-IN", "hi-IN", "ml-IN", "ta-IN"]
        ),
        "the languages",
    )
    # records: lowering the days asks first (older calls go)
    pane.get_by_label("Keep calls for this many days").fill("10")
    calls.button("Save", "#clp-settings section:has(h3:text('Records'))").click()
    assert "Keep calls for 10 days?" in calls.text("#clp-settings .mbox")
    calls.clean()


# ---- Vitals' calls line -------------------------------------------------------------------------
def test_vitals_shows_this_months_calls_spend_and_the_calls_cap(calls: Calls) -> None:
    calls.open()
    calls.open_panel("vitals")
    line = calls.page.locator("#sCalls")
    until(calls.page, lambda: line.text_content() == "≈ ₹12.40 of ₹200", "the calls line")
    row = line.locator("xpath=..")
    assert row.get_attribute("class") == "kv" and "Calls this month" in str(row.text_content())
    before = (
        calls.page.locator("#sCost")
        .locator("xpath=..")
        .evaluate("e => e.nextElementSibling === document.getElementById('sCalls').parentElement")
    )
    assert before is True  # right under "This conversation", in the list's own look
    calls.clean()


# ---- keyboard, focus, reduced motion, the phone -------------------------------------------------
def test_the_tabs_move_with_arrow_keys_and_focus_is_always_visible(calls: Calls) -> None:
    calls.calls()
    calls.page.locator("#clt-calls").focus()
    calls.page.keyboard.press("ArrowRight")
    assert (
        calls.page.evaluate("document.activeElement.id") == "clt-new"
        and calls.pane("new").is_visible()
    )
    calls.page.keyboard.press("End")
    assert calls.page.evaluate("document.activeElement.id") == "clt-settings"
    calls.page.keyboard.press("Home")
    assert calls.page.evaluate("document.activeElement.id") == "clt-calls"
    tabbable = calls.page.evaluate(
        """() => [...document.querySelectorAll('#clt-calls, #clt-new, #clt-langs, #clt-settings')].map(t => t.tabIndex)"""
    )
    assert tabbable == [0, -1, -1, -1]  # one tab stop for the strip (roving tabindex)
    calls.page.keyboard.press("Tab")  # into the open pane
    ring = calls.page.evaluate(
        "() => { const s = getComputedStyle(document.activeElement); return [document.activeElement.id, s.outlineStyle, s.outlineWidth]; }"
    )
    assert ring[0] == "clp-calls" and ring[1] != "none" and ring[2] != "0px"
    calls.page.keyboard.press("Tab")
    focused = calls.page.evaluate(
        "() => { const e = document.activeElement; const s = getComputedStyle(e); return [e.tagName, s.outlineStyle]; }"
    )
    assert focused == ["BUTTON", "solid"]
    calls.clean()


def test_reduced_motion_stops_the_panels_transitions(
    browser: Any, server_url: str, token: str
) -> None:
    c = Calls(browser, server_url, token, reduced=True)
    try:
        c.calls()
        assert c.page.evaluate("document.documentElement.dataset.motion") == "calm"
        dur = c.page.evaluate(
            "getComputedStyle(document.querySelector('#p-calls .hp-tab')).transitionDuration"
        )
        assert set(dur.replace(" ", "").split(",")) == {"0s"}
        c.clean()
    finally:
        c.close()


def test_the_phone_layout_opens_calls_from_more_and_the_live_call_fits(
    browser: Any, server_url: str, token: str
) -> None:
    status = {**STATUS, "active": {"call_id": LIVE_ID, "state": "talking"}}
    c = Calls(browser, server_url, token, PHONE, status=status)
    try:
        c.calls()  # behind More on a phone
        c.page.locator("#clp-calls .cl-live").wait_for(state="visible")
        width = c.page.evaluate("[document.documentElement.scrollWidth, window.innerWidth]")
        assert width[0] <= width[1]
        for name in ("Take over", "Hang up"):
            box = c.button(name, "#clp-calls .cl-live").bounding_box()
            assert (
                box
                and box["height"] >= 44
                and box["x"] >= 0
                and box["x"] + box["width"] <= PHONE["width"]
            )
        c.clean()
    finally:
        c.close()
