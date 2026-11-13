# tests/browser/test_r7_d_follow_ups.py -- R7 Part D's review follow-ups in the real console.
# A failed SOS always leaves the SMS screen and 112 (an empty answer never hides the numbers the
# sheet loaded, a silent server ends in plain words, every error shows its words); one press id per
# hold; a locked phone is offered a real SOS only; the hold ends when the window blurs; the focus
# returns after Cancel; a second pointer or a right click never starts or ends a hold; the one-time
# join link leaves the page; the Watch tab keeps the times he picked.

from __future__ import annotations

import json
import re
from collections.abc import Iterator
from typing import Any

import pytest
from test_r7_d_body import (
    SENT,
    SHEET,
    WATCH,
    Rig,
    _close,
    _hold,
    _sheet,
)
from test_r7_d_body import rig as _body_rig
from test_ui_audit import _open

pytestmark = pytest.mark.browser
rig = _body_rig  # the module's fixture, shared
PRESS = re.compile(r"^[A-Za-z0-9_-]{16,64}$")
LINK = "https://t.me/jarvis_test_bot?start=sos-" + "A1b2C3d4E5" * 3


def _hrefs(c: Any) -> list[str]:
    return c.page.locator("#sosSheet .sos-links a").evaluate_all(
        "(a) => a.map((x) => x.getAttribute('href'))"
    )


@pytest.fixture
def reply(rig: Rig) -> Iterator[Any]:
    """Answer POST /v1/sos/send with (status, body); undone after the test."""
    c = rig.page("desktop", "night")
    done: list[str] = []

    def use(status: int, body: Any, pattern: str = "**/v1/sos/send") -> None:
        done.append(pattern)
        c.page.route(
            pattern,
            lambda r: r.fulfill(
                status=status, content_type="application/json", body=json.dumps(body)
            ),
        )

    yield use
    for pattern in done:
        c.page.unroute(pattern)
    c.page.evaluate("() => { delete window.JarvisMobile.sosTimeoutMs; }")
    _close(c)


def _send(c: Any, selector: str = ".sos-hold") -> str:
    _sheet(c)
    _hold(c, f"#sosSheet {selector}")
    c.page.locator("#sosSheet .sos-result p").first.wait_for(timeout=9000)
    return c.page.locator("#sosSheet .sos-result").text_content() or ""


DOWN = {
    **SENT,
    "sent": False,
    "outcome": "unavailable",
    "reason": "unreadable",
    "results": [],
    "reached": 0,
    "sms": {"numbers": [], "text": ""},
    "call": {"first": None, "emergency": "112"},
    "words": "Your SOS set-up couldn't be read just now, Sir. Use the SMS screen or call 112.",
}


def test_an_unavailable_answer_with_no_numbers_keeps_the_sms_link(rig: Rig, reply: Any) -> None:
    c = rig.page("desktop", "night")
    reply(200, DOWN)
    assert "couldn't be read" in _send(c)
    hrefs = _hrefs(c)
    assert any(h.startswith("sms:+10000000001?body=") for h in hrefs) and hrefs[-1] == "tel:112"


ERRORS = [
    (
        500,
        {"error": "failed", "detail": "The SOS could not be sent. Call 112."},
        "could not be sent",
    ),
    (429, {"error": "busy", "detail": "Too many presses at once, Sir."}, "Too many presses"),
    (
        503,
        {"error": "sos_off", "detail": "Emergency SOS isn't set up on this server."},
        "isn't set up",
    ),
    (422, {"detail": [{"loc": ["body", "kind"], "msg": "bad", "type": "x"}]}, "NOT sent through"),
]


@pytest.mark.parametrize(("status", "body", "words"), ERRORS)
def test_every_error_answer_shows_its_words_and_never_an_object(
    rig: Rig, reply: Any, status: int, body: Any, words: str
) -> None:
    c = rig.page("desktop", "night")
    reply(status, body)
    shown = _send(c)
    assert words in shown and "[object" not in shown and "112" in shown
    assert any(h.startswith("sms:+1000") for h in _hrefs(c)) and "tel:112" in _hrefs(c)


def test_a_server_that_never_answers_ends_in_plain_words_with_sms_and_112(rig: Rig) -> None:
    c = rig.page("desktop", "night")
    c.page.evaluate("() => { window.JarvisMobile.sosTimeoutMs = 1500; }")
    c.page.route("**/v1/sos/send", lambda r: None)  # never fulfilled
    try:
        words = _send(c)
        assert words.startswith("UNKNOWN") and "may have" in words and "112" in words
        assert any(h.startswith("sms:+1000") for h in _hrefs(c)) and "tel:112" in _hrefs(c)
    finally:
        c.page.unroute("**/v1/sos/send")
        c.page.evaluate("() => { delete window.JarvisMobile.sosTimeoutMs; }")
        _close(c)


def test_each_hold_sends_one_press_id_and_the_next_hold_a_new_one(rig: Rig) -> None:
    c = rig.page("desktop", "night")
    rig.send_answer = SENT
    _sheet(c)
    rig.calls.clear()
    ids = []
    for _ in range(2):
        _hold(c, "#sosSheet .sos-hold")
        c.page.locator("#sosSheet .sos-row").first.wait_for(timeout=9000)
        c.page.locator("#sosSheet .sos-hold").wait_for(state="visible")
        ids.append([x for x in rig.calls if x[1].endswith("/send")][-1][2]["press_id"])
        rig.calls.clear()
    assert all(PRESS.fullmatch(i) for i in ids) and ids[0] != ids[1]
    _close(c)


def test_told_false_is_said_on_the_sheet(rig: Rig, reply: Any) -> None:
    c = rig.page("desktop", "night")
    reply(200, {**SENT, "told": False})
    _send(c)
    assert "couldn’t confirm that your other devices" in (
        c.page.locator("#sosSheet .sos-result").text_content() or ""
    )


def test_a_locked_phone_is_offered_a_real_sos_only_and_no_first_number(rig: Rig) -> None:
    c = rig.page("desktop", "night")
    locked = {**SHEET, "locked": True, "first": None, "unreadable": False}
    locked.pop("label")
    c.page.route(
        "**/v1/sos/sheet",
        lambda r: r.fulfill(status=200, content_type="application/json", body=json.dumps(locked)),
    )
    try:
        c.page.evaluate("() => window.JarvisMobile.parts.sos.open()")
        c.page.locator("#sosSheet").wait_for(state="visible")
        c.page.locator("#sosSheet .sos-test").wait_for(state="hidden")
        assert c.page.locator("#sosSheet .sos-safe").is_hidden()
        assert c.page.locator("#sosSheet .sos-hold").is_visible()
        links = c.page.locator("#sosSheet .sos-links a").all_text_contents()
        assert not [t for t in links if "first contact" in t] and "Call 112" in links
    finally:
        c.page.unroute("**/v1/sos/sheet")
        _close(c)


def test_an_unreadable_contact_book_shows_a_warning_on_the_sheet(rig: Rig) -> None:
    c = rig.page("desktop", "night")
    warning = "Your contacts couldn't be loaded just now, Sir. Call 112 or use your phone's SMS."
    bad = {**SHEET, "numbers": [], "first": None, "unreadable": True, "warning": warning}
    c.page.route(
        "**/v1/sos/sheet",
        lambda r: r.fulfill(status=200, content_type="application/json", body=json.dumps(bad)),
    )
    try:
        c.page.evaluate("() => window.JarvisMobile.parts.sos.open()")
        c.page.locator("#sosSheet .sos-warn").wait_for(state="visible", timeout=5000)
        assert "couldn't be loaded" in (c.page.locator("#sosSheet .sos-warn").text_content() or "")
    finally:
        c.page.unroute("**/v1/sos/sheet")
        _close(c)


def test_a_blur_ends_a_hold_and_nothing_is_sent(rig: Rig) -> None:
    c = rig.page("desktop", "night")
    _sheet(c)
    rig.calls.clear()
    box = c.page.locator("#sosSheet .sos-hold").bounding_box()
    assert box is not None
    c.page.mouse.move(box["x"] + 5, box["y"] + 5)
    c.page.mouse.down()
    c.page.wait_for_timeout(500)
    c.page.evaluate("() => window.dispatchEvent(new Event('blur'))")
    c.page.wait_for_timeout(2600)
    assert "Let go too early" in (c.page.locator("#sosSheet .sos-say").text_content() or "")
    assert c.page.locator("#sosSheet .sos-cancel").is_hidden()
    c.page.mouse.up()
    assert [x for x in rig.calls if x[0] == "POST"] == []
    _close(c)


def test_focus_returns_to_the_hold_button_after_cancel(rig: Rig) -> None:
    c = rig.page("desktop", "night")
    _sheet(c)
    _hold(c, "#sosSheet .sos-hold")
    c.page.locator("#sosSheet .sos-cancel").click()
    assert c.page.evaluate("() => document.activeElement.className").find("sos-hold") >= 0
    _close(c)


def test_a_right_click_never_starts_a_hold(rig: Rig) -> None:
    c = rig.page("desktop", "night")
    _sheet(c)
    box = c.page.locator("#sosSheet .sos-hold").bounding_box()
    assert box is not None
    c.page.mouse.move(box["x"] + 5, box["y"] + 5)
    c.page.mouse.down(button="right")
    c.page.wait_for_timeout(300)
    assert "Keep holding" not in (c.page.locator("#sosSheet .sos-say").text_content() or "")
    c.page.mouse.up(button="right")
    _close(c)


def test_a_second_pointer_does_not_end_the_first_hold(rig: Rig) -> None:
    c = rig.page("desktop", "night")
    _sheet(c)
    c.page.evaluate(
        """() => {
          const init = (id) => ({ pointerId: id, button: 0, isPrimary: true, bubbles: true });
          const fire = (sel, type, id) =>
            document.querySelector(sel).dispatchEvent(new PointerEvent(type, init(id)));
          fire('#sosSheet .sos-hold', 'pointerdown', 1);
          fire('#sosSheet .sos-test', 'pointerdown', 2);
          fire('#sosSheet .sos-test', 'pointerup', 2);
        }"""
    )
    assert "Keep holding" in (c.page.locator("#sosSheet .sos-say").text_content() or "")
    c.page.evaluate(
        """() => document.querySelector('#sosSheet .sos-hold').dispatchEvent(
          new PointerEvent('pointerup', { pointerId: 1, button: 0, isPrimary: true,
            bubbles: true }))"""
    )
    assert "Let go too early" in (c.page.locator("#sosSheet .sos-say").text_content() or "")
    _close(c)


def test_the_one_time_join_link_leaves_the_page_when_the_sheet_opens(rig: Rig) -> None:
    c = rig.page("desktop", "night")
    c.page.route(
        "**/v1/sos/contacts/*/link",
        lambda r: r.fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps({"link": LINK, "until": "2026-11-13T00:00:00+00:00"}),
        ),
    )
    try:
        assert _open(c, "integrations") is None
        c.page.locator("#sosCard .sos-contact").first.wait_for(timeout=5000)
        c.page.locator("#sosCard button", has_text="Join link").first.click()
        c.page.locator("#sosCard .sos-linkbox").wait_for(timeout=5000)
        assert c.page.locator("#sosCard .sos-linkbox input").input_value() == LINK
        c.page.evaluate("() => window.JarvisMobile.parts.sos.open()")
        c.page.locator("#sosSheet").wait_for(state="visible")
        assert c.page.locator(".sos-linkbox").count() == 0
        assert LINK not in c.page.content() or c.page.evaluate(
            "() => document.body.innerText.indexOf('start=sos-') < 0"
        )
    finally:
        c.page.unroute("**/v1/sos/contacts/*/link")
        _close(c)


def test_the_watch_tab_keeps_the_times_he_picked_after_save(rig: Rig) -> None:
    c = rig.page("desktop", "night")
    c.page.route(
        "**/v1/watch/sleep",
        lambda r: r.fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps({"message": "Noted, Sir.", "night": {}}),
        ),
    )
    try:
        assert _open(c, "helpers") is None
        c.page.locator("#hpt-watch").click()
        c.page.locator("#wtStart").wait_for(timeout=5000)
        c.page.locator("#wtStart").fill("22:15")
        c.page.locator("#wtEnd").fill("05:45")
        c.page.locator(".wt-save").click()
        c.page.locator("#hpp-watch .hp-note, #hpp-watch .sfine").filter(
            has_text="Noted"
        ).first.wait_for(timeout=5000)
        c.page.wait_for_timeout(500)
        assert c.page.locator("#wtStart").input_value() == "22:15"
        assert c.page.locator("#wtEnd").input_value() == "05:45"
        assert WATCH["enabled"]
    finally:
        c.page.unroute("**/v1/watch/sleep")
        c.page.locator("#hpt-today").click()
