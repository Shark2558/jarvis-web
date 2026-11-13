# tests/browser/test_r7_d_body.py -- R7 Part D (docs/plans/r7-mobile.md D0, D18-D20): the SOS
# sheet, Integrations -> Emergency SOS and Helpers -> Watch in the real console with mocked answers.
# They pass the visual gate at 1440x900 and 390x844, Night and Day; before sign-in they ask the
# server nothing; a cancelled countdown makes NO request; a full countdown sends ONE POST whose
# address holds no coordinate (the place is in the body only); every answer is shown per contact
# with the SMS screen and 112, a refusal and a failure too; "open SOS" by voice only opens it.
from __future__ import annotations

import json
from collections.abc import Iterator
from typing import Any

import pytest
from test_console import DESKTOP, PHONE, Console
from test_ui_audit import NAMELESS_JS, WRAP_JS, _assert_clean, _open
from ui_checks import DOM_CHECKS_JS, FINISH_ANIMATIONS_JS, install_mocks

_pw = pytest.importorskip("playwright.sync_api")
sync_playwright = _pw.sync_playwright
pytestmark = pytest.mark.browser

LAT, LON = -31.415926, -17.320508  # the open South Atlantic: nobody lives there
NOTE = "This is not an emergency service: in danger, call 112."
VIEW: dict[str, Any] = {
    "part": "body",
    "ready": "ready",
    "locked": False,
    "enabled": True,
    "sealed": True,
    "telegram": True,
    "label": "Kiran Example",
    "label_set": True,
    "max": 5,
    "countdown_s": 10,
    "hold_s": 2,
    "web_countdown_s": 5,
    "contacts": [
        {
            "id": "c_00000000a1",
            "label": "Asha Example",
            "phone_hint": "••01",
            "has_phone": True,
            "joined": True,
            "pending": False,
        },
        {
            "id": "c_00000000b2",
            "label": "Ravi Example with a long name",
            "phone_hint": "",
            "has_phone": False,
            "joined": False,
            "pending": True,
        },
    ],  # fmt: skip
    "last": {
        "at": "2026-11-12T08:35:00+00:00",
        "kind": "test",
        "outcome": "sent",
        "reached": 1,
        "joined": 1,
        "location": True,
    },  # fmt: skip
    "left": {"real_hour": 3, "real_day": 10, "test_hour": 2, "test_day": 9},
    "note": NOTE,
}
SHEET = {
    "enabled": True,
    "label": "Kiran Example",
    "numbers": ["+10000000001"],
    "first": "+10000000001",
    "emergency": "112",
    "text": "SOS from Kiran Example: I need help. My location is not available. Sent by my JARVIS "
    "assistant.",
    "hold_s": 2,
    "countdown_s": 5,
    "note": NOTE,
}
SENT = {
    "sent": True,
    "kind": "real",
    "outcome": "partial",
    "reason": None,
    "reached": 1,
    "joined": 2,
    "total": 2,
    "results": [
        {"id": "c_00000000a1", "label": "Asha Example", "status": "sent"},
        {"id": "c_00000000b2", "label": "Ravi Example", "status": "failed"},
    ],
    "words": "SOS at 14:05 reached 1 of 2 contacts on Telegram. Not reached: Ravi Example. Use the "
    "SMS screen or call 112.",
    "text": "SOS from Kiran Example: I need help.",
    "sms": {"numbers": ["+10000000001"], "text": "SOS from Kiran Example: I need help."},
    "call": {"first": "+10000000001", "emergency": "112"},
    "told": True,
}
REFUSED = {
    **SENT,
    "sent": False,
    "outcome": "refused",
    "reason": "hour",
    "reached": 0,
    "results": [],
    "words": "Not sent on Telegram: the limit of 3 an hour was reached. Use the SMS screen or call "
    "112.",
}
WATCH = {
    "part": "body",
    "ready": "ready",
    "enabled": True,
    "sealed": True,
    "last_synced": "2026-11-12T03:42:00+00:00",
    "kinds": {"steps": True, "heart": True, "sleep": True},
    "today": {
        "steps": {"count": 8123, "source": "watch"},
        "heart": {"min": 58, "avg": 74, "max": 131, "source": "watch"},
    },
    "last_night": {
        "minutes": 400,
        "start": "23:50",
        "end": "06:30",
        "source": "watch",
        "stages": {"awake": 12, "light": 210, "deep": 80, "rem": 98},
    },
    "week": {"nights": 5, "avg_minutes": 412, "bed_from": "23:10", "bed_to": "00:40"},
}


class Rig:
    def __init__(self, browser: Any, url: str, token: str) -> None:
        self.browser, self.url, self.token = browser, url, token
        self.pages: dict[tuple[str, str], Console] = {}
        self.calls: list[tuple[str, str, Any]] = []
        self.send_answer: dict[str, Any] = SENT

    def _json(self, route: Any, body: Any) -> None:
        route.fulfill(status=200, content_type="application/json", body=json.dumps(body))

    def _sos(self, route: Any) -> None:
        req = route.request
        body = json.loads(req.post_data) if req.post_data else None
        path = req.url.split("/v1/sos", 1)[1]
        self.calls.append((req.method, req.url, body))
        if path.startswith("/send"):
            self._json(route, self.send_answer)
        elif path.startswith("/sheet"):
            self._json(route, SHEET)
        else:
            self._json(route, VIEW)

    def page(self, vp: str = "desktop", surface: str = "night") -> Console:
        key = (vp, surface)
        if key not in self.pages:
            c = Console(self.browser, self.url, self.token, DESKTOP if vp == "desktop" else PHONE)
            c.ctx.grant_permissions(["geolocation"])
            c.ctx.set_geolocation({"latitude": LAT, "longitude": LON, "accuracy": 20})
            install_mocks(c.page)
            c.page.route("**/v1/sos", self._sos)
            c.page.route("**/v1/sos/**", self._sos)
            c.page.route("**/v1/watch", lambda r: self._json(r, WATCH))
            c.open()
            if surface == "day":
                c.choose_day()
            c.page.wait_for_timeout(800)
            self.pages[key] = c
        return self.pages[key]

    def close(self) -> None:
        for c in self.pages.values():
            c.close()


@pytest.fixture(scope="module")
def rig(server_url: str, token: str) -> Iterator[Rig]:
    with sync_playwright() as p:
        b = p.chromium.launch()
        r = Rig(b, server_url, token)
        yield r
        r.close()
        b.close()


def _gate(c: Console, sel: str, vp: str, what: str) -> None:
    c.page.evaluate(FINISH_ANIMATIONS_JS)
    res = c.page.evaluate(DOM_CHECKS_JS, sel)
    assert not res.get("missing"), f"{what}: {sel} is not in the page"
    _assert_clean(res, c.page.evaluate(NAMELESS_JS, sel), c.page.evaluate(WRAP_JS, sel), vp, what)
    assert c.errors == [] and c.csp_violations() == []


def _sheet(c: Console) -> Any:
    if not c.page.evaluate("() => !!document.querySelector('#sosSheet[open]')"):
        c.page.evaluate("() => window.JarvisMobile.parts.sos.open()")
    sheet = c.page.locator("#sosSheet")
    sheet.wait_for(state="visible")
    c.page.locator("#sosSheet .sos-place").filter(has_text="Location: ready").wait_for(timeout=8000)
    return sheet


def _close(c: Console) -> None:
    c.page.evaluate("() => window.JarvisMobile.parts.sos.close()")


def _hold(c: Console, selector: str, ms: int | None = None) -> None:
    """Press and hold. With `ms`, let go after that long; else hold until the countdown shows (a
    loaded machine may run the 2-second timer late), then let go, as a finger would."""
    box = c.page.locator(selector).bounding_box()
    assert box is not None
    c.page.mouse.move(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
    c.page.mouse.down()
    if ms is None:
        c.page.locator("#sosSheet .sos-cancel").wait_for(state="visible", timeout=15000)
    else:
        c.page.wait_for_timeout(ms)
    c.page.mouse.up()


@pytest.mark.parametrize("surface", ["night", "day"])
@pytest.mark.parametrize("vp", ["desktop", "phone"])
def test_the_card_the_sheet_and_the_watch_tab_pass_the_visual_gate(
    rig: Rig, vp: str, surface: str
) -> None:
    c = rig.page(vp, surface)
    assert _open(c, "integrations") is None
    card = c.page.locator("#sosCard")
    card.locator(".sos-contact").first.wait_for(timeout=5000)
    text = card.text_content() or ""
    for words in ("Emergency SOS", "Asha Example", "Joined on Telegram", "Join link", NOTE):
        assert words in text, words
    _gate(c, "#sosCard", vp, f"sos card {vp} {surface}")
    _sheet(c)
    _gate(c, "#sosSheet", vp, f"sos sheet {vp} {surface}")
    _close(c)
    assert _open(c, "helpers") is None
    c.page.locator("#hpt-watch").click()
    pane = c.page.locator("#hpp-watch")
    pane.locator(".hp-row").first.wait_for(timeout=5000)
    words = pane.text_content() or ""
    for w in ("8,123 steps", "6 h 40 min, 23:50 to 06:30", "from your watch", "Estimates, never"):
        assert w in words, w
    _gate(c, "#p-helpers", vp, f"watch tab {vp} {surface}")
    c.page.locator("#hpt-today").click()  # leave the remembered tab as it was


def test_a_cancelled_countdown_makes_no_request(rig: Rig) -> None:
    c = rig.page("desktop", "night")
    _sheet(c)
    rig.calls.clear()
    _hold(c, "#sosSheet .sos-hold")
    assert "Sending SOS in" in (c.page.locator("#sosSheet .sos-say").text_content() or "")
    c.page.locator("#sosSheet .sos-cancel").click()
    c.page.wait_for_timeout(6000)  # past the countdown
    assert [x for x in rig.calls if x[0] == "POST"] == []
    assert "Nothing was sent" in (c.page.locator("#sosSheet .sos-say").text_content() or "")
    _close(c)


def test_letting_go_before_the_hold_sends_nothing(rig: Rig) -> None:
    c = rig.page("desktop", "night")
    _sheet(c)
    rig.calls.clear()
    _hold(c, "#sosSheet .sos-hold", ms=900)
    c.page.wait_for_timeout(6500)
    assert [x for x in rig.calls if x[0] == "POST"] == [] and c.page.locator(
        "#sosSheet .sos-cancel"
    ).is_hidden()
    _close(c)


def test_a_full_countdown_sends_once_with_the_place_in_the_body_only(rig: Rig) -> None:
    c = rig.page("desktop", "night")
    rig.send_answer = SENT
    _sheet(c)
    rig.calls.clear()
    _hold(c, "#sosSheet .sos-hold")
    c.page.locator("#sosSheet .sos-row").first.wait_for(timeout=9000)
    posts = [x for x in rig.calls if x[0] == "POST"]
    assert len(posts) == 1
    _, url, body = posts[0]
    assert url.endswith("/v1/sos/send") and "?" not in url and "31.4" not in url
    assert body["kind"] == "real" and body["location"]["lat_e6"] == round(LAT * 1e6)
    assert body["location"]["accuracy_m"] == 20 and isinstance(body["location"]["age_s"], int)
    rows = c.page.locator("#sosSheet .sos-row").all_text_contents()
    assert rows == [
        "Asha Example: sent on Telegram",
        "Ravi Example: NOT sent: Telegram did not take it",
    ]
    hrefs = c.page.locator("#sosSheet .sos-links a").evaluate_all(
        "(a) => a.map((x) => x.getAttribute('href'))"
    )
    assert hrefs[0].startswith("sms:+10000000001?body=") and hrefs[-1] == "tel:112"
    _close(c)


def test_a_refused_send_still_offers_the_sms_screen_and_112(rig: Rig) -> None:
    c = rig.page("desktop", "night")
    rig.send_answer = REFUSED
    _sheet(c)
    _hold(c, "#sosSheet .sos-test")
    c.page.locator("#sosSheet .sos-result p").first.wait_for(timeout=9000)
    assert "the limit of 3 an hour" in (
        c.page.locator("#sosSheet .sos-result").text_content() or ""
    )
    hrefs = c.page.locator("#sosSheet .sos-links a").evaluate_all(
        "(a) => a.map((x) => x.getAttribute('href'))"
    )
    assert any(h.startswith("sms:") for h in hrefs) and "tel:112" in hrefs
    rig.send_answer = SENT
    _close(c)


def test_a_failed_request_never_says_sent_and_offers_112(rig: Rig) -> None:
    c = rig.page("desktop", "night")
    _sheet(c)
    c.page.route(
        "**/v1/sos/send",
        lambda r: r.fulfill(
            status=503,
            content_type="application/json",
            body='{"error":"unavailable","detail":"Down."}',
        ),
    )
    try:
        _hold(c, "#sosSheet .sos-hold")
        c.page.locator("#sosSheet .sos-result p").first.wait_for(timeout=9000)
        words = c.page.locator("#sosSheet .sos-result").text_content() or ""
        assert words.startswith("NOT sent through JARVIS") and "112" in words
        hrefs = c.page.locator("#sosSheet .sos-links a").evaluate_all(
            "(a) => a.map((x) => x.getAttribute('href'))"
        )
        assert "tel:112" in hrefs and any(h.startswith("sms:+10000000001") for h in hrefs)
    finally:
        c.page.unroute("**/v1/sos/send")
        _close(c)


def test_open_sos_by_voice_only_opens_the_sheet(rig: Rig) -> None:
    c = rig.page("desktop", "night")
    rig.calls.clear()
    got = c.page.evaluate(
        "() => window.JarvisVoiceCommands.handle('Jarvis, open SOS',"
        " {source: 'voice', state: 'listening'})"
    )
    assert got["handled"] is True and got["id"] == "sos.open"
    c.page.locator("#sosSheet").wait_for(state="visible")
    c.page.wait_for_timeout(7500)  # longer than a hold and a countdown
    assert [x for x in rig.calls if x[0] == "POST"] == []
    assert c.page.locator("#sosSheet .sos-cancel").is_hidden()
    _close(c)


def test_before_sign_in_the_block_asks_the_server_nothing(rig: Rig) -> None:
    """Signed out, neither the card, the sheet, the voice command nor the Watch tab asks the server
    anything (a call made then would answer 401 and throw him back to the gate); once he is in, the
    card asks when Integrations opens."""
    c = Console(rig.browser, rig.url, rig.token, DESKTOP)
    install_mocks(c.page)
    c.page.route("**/v1/sos", rig._sos)
    c.page.route("**/v1/sos/**", rig._sos)
    c.page.route("**/v1/watch", lambda r: rig._json(r, WATCH))
    asked: list[str] = []
    c.page.on(
        "request",
        lambda r: asked.append(r.url) if "/v1/sos" in r.url or "/v1/watch" in r.url else None,
    )
    c.page.add_init_script(
        "localStorage.setItem('jarvis_helpers_tab', 'watch')"
    )  # the tab mounts at load
    c.page.goto(rig.url + "/")
    c.page.locator("#tokIn").wait_for()
    c.page.wait_for_timeout(1200)  # the R7 modules have loaded
    c.page.evaluate("() => window.JarvisMobile.parts.sos.open()")
    c.page.locator("#sosSheet").wait_for(state="visible")
    assert c.page.locator("#sosSheet .sos-hold").is_disabled()
    assert "Sign in" in (c.page.locator("#sosSheet .sos-say").text_content() or "")
    hrefs = c.page.locator("#sosSheet .sos-links a").evaluate_all(
        "(a) => a.map((x) => x.getAttribute('href'))"
    )
    assert hrefs == ["tel:112"]
    c.page.evaluate("() => window.JarvisMobile.parts.sos.close()")
    c.page.wait_for_timeout(600)
    assert asked == [] and c.errors == []

    c.page.locator("#tokIn").fill(rig.token)
    c.page.locator("#tokBtn").click()
    c.page.locator("#welcome").wait_for()
    assert _open(c, "integrations") is None
    c.page.locator("#sosCard").wait_for(timeout=5000)
    c.page.wait_for_timeout(600)
    assert any("/v1/sos" in u for u in asked)  # once he is in, the card asks
    assert c.errors == [] and c.csp_violations() == []
    c.close()
