# tests/browser/test_r7_a_links.py -- R7 Part A, launch addresses and tapped alerts (docs/plans/
# r7-mobile.md D8, D9, D10; acceptance checks 2 and 3) in a real browser, real backend (mock brain):
#   - do=talk NEVER starts the microphone, in an ordinary tab or the app's own address: it focuses
#     the mic button and shows "Tap to talk"; a locked mic stays locked (the owner's tap opens it);
#   - do=look opens the Camera panel with the camera off; open=<panel> opens that panel;
#   - only the four words and the dock's panels: anything else is ignored; the words are gone from
#     the address afterwards and every other word stays;
#   - a launch read signed out waits for sign-in, and nothing is asked of the server before it;
#   - the push worker (console-sw.js, run here with a stand-in `self`): a target with its `?` is
#     kept, the tag is the kind, "Talk" is offered; a tap with a JARVIS window open focuses THAT
#     window and hands it the target over BroadcastChannel (no navigate, no second window), and
#     the console opens the right panel; with no window it opens one at the target.
from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from test_console import DESKTOP, PHONE, Console

_pw = pytest.importorskip("playwright.sync_api")
sync_playwright = _pw.sync_playwright
pytestmark = pytest.mark.browser

STATIC = Path(__file__).resolve().parents[2] / "src" / "jarvis" / "api" / "static"
SW_SRC = (STATIC / "console-sw.js").read_text(encoding="utf-8")
TAP = "Tap to talk"
# Every way into the microphone, counted (and never opened: the spy refuses).
MIC_SPY = """(() => {
  window.__mic = { gum: 0, rec: 0 };
  const md = navigator.mediaDevices;
  if (md && md.getUserMedia) {
    md.getUserMedia = function () { window.__mic.gum += 1;
      return Promise.reject(new DOMException('test', 'NotAllowedError')); };
  }
  for (const R of [window.SpeechRecognition, window.webkitSpeechRecognition]) {
    if (R && R.prototype) R.prototype.start = function () { window.__mic.rec += 1; };
  }
})();"""
# console-sw.js with a stand-in `self` (the real BroadcastChannel): its push and click handlers.
SW_HARNESS = """async ([src, run]) => {
  const handlers = {}, shown = [], calls = [];
  const win = (url, focused) => ({ url, focused,
    focus: async function () { calls.push('focus ' + url); return this; },
    navigate: async (u) => { calls.push('navigate ' + u); } });
  const wins = run.windows.map(([u, f]) => win(location.origin + u, f));
  const fake = {
    addEventListener: (n, f) => { handlers[n] = f; },
    location: new URL(location.origin + '/static/console-sw.js'),
    registration: { showNotification: (t, o) => { shown.push([t, o]); return Promise.resolve(); } },
    clients: { matchAll: async () => wins, openWindow: async (u) => { calls.push('open ' + u); } },
  };
  new Function('self', src)(fake);
  const heard = [], ch = new BroadcastChannel('jarvis-launch');
  ch.onmessage = (e) => heard.push(e.data);
  for (const d of run.pushes || []) {
    let p = null;
    await handlers.push({ data: { json: () => d }, waitUntil: (x) => { p = x; } }); await p;
  }
  if (run.click) {
    let p = null;
    handlers.notificationclick({ action: run.click.action || '', waitUntil: (x) => { p = x; },
      notification: { data: run.click.data, close: () => calls.push('close') } });
    await p;
  }
  await new Promise((r) => setTimeout(r, 300)); ch.close();
  return { shown: shown.map(([t, o]) => ({ title: t, tag: o.tag, url: o.data.url, body: o.body,
    actions: o.actions })), calls, heard };
}"""


@pytest.fixture(scope="module")
def browser() -> Iterator[Any]:
    with sync_playwright() as p:
        b = p.chromium.launch()
        yield b
        b.close()


class Launch(Console):
    def __init__(self, browser: Any, url: str, token: str, viewport: dict[str, int]) -> None:
        super().__init__(browser, url, token, viewport)
        self.requests: list[str] = []
        self.ctx.on("request", lambda r: self.requests.append(r.url))
        self.page.add_init_script(MIC_SPY)

    def mic(self) -> dict[str, int]:
        out: dict[str, int] = self.page.evaluate("window.__mic")
        return out

    def visible(self, panel: str) -> bool:
        return bool(self.page.locator(f"#p-{panel}").is_visible())

    def focused(self) -> str:
        return str(self.page.evaluate("document.activeElement && document.activeElement.id"))


def _talk_ready(c: Launch) -> None:
    c.page.locator("#voiceLine", has_text=TAP).wait_for(timeout=10_000)
    c.page.wait_for_timeout(1200)  # the boot's own focus and the brains list have run by now


# ---- do=talk (D8, D9) ---------------------------------------------------------------------------
@pytest.mark.parametrize("path", ["/?do=talk", "/?source=app&do=talk"])
@pytest.mark.parametrize("size", ["desktop", "phone"])
def test_do_talk_readies_the_mic_button_and_never_starts_the_microphone(
    browser: Any, server_url: str, token: str, path: str, size: str
) -> None:
    c = Launch(browser, server_url, token, DESKTOP if size == "desktop" else PHONE)
    try:
        c.open(path)
        _talk_ready(c)
        assert c.focused() == "micBtn" and c.page.locator("#micBtn").is_visible()
        assert c.mic() == {"gum": 0, "rec": 0}
        assert c.page.evaluate("window.JarvisVoiceLoop.state()") == "idle"
        assert c.page.locator("#micBtn").get_attribute("aria-pressed") == "false"
        assert c.page.evaluate("location.search") == ("?source=app" if "source" in path else "")
        assert c.errors == [] and c.csp_violations() == []
    finally:
        c.close()


def test_do_talk_never_unlocks_a_locked_microphone(
    browser: Any, server_url: str, token: str
) -> None:
    c = Launch(browser, server_url, token, PHONE)
    try:
        c.page.goto(server_url + "/health")
        c.page.evaluate("localStorage.setItem('jarvis_mic_off_v1', '1')")  # the hard "mic off"
        c.open("/?source=app&do=talk")
        _talk_ready(c)
        assert c.page.evaluate("window.JarvisAudio.locked()") is True
        assert c.page.evaluate("window.JarvisVoiceLoop.state()") == "off"
        assert c.focused() == "micBtn" and c.mic() == {"gum": 0, "rec": 0}
    finally:
        c.close()


def test_the_owners_own_tap_after_do_talk_is_what_starts_listening(
    browser: Any, server_url: str, token: str
) -> None:
    c = Launch(browser, server_url, token, DESKTOP)
    try:
        c.open("/?do=talk")
        _talk_ready(c)
        assert c.mic()["gum"] + c.mic()["rec"] == 0
        c.page.locator("#micBtn").click()  # a real tap: R5's press()
        for _ in range(50):
            if sum(c.mic().values()):
                break
            c.page.wait_for_timeout(100)
        assert sum(c.mic().values()) > 0
    finally:
        c.close()


# ---- do=look, open=, the allow-lists, the address -----------------------------------------------
@pytest.mark.parametrize("size", ["desktop", "phone"])
def test_do_look_opens_the_camera_panel_with_the_camera_off(
    browser: Any, server_url: str, token: str, size: str
) -> None:
    c = Launch(browser, server_url, token, DESKTOP if size == "desktop" else PHONE)
    try:
        c.page.goto(server_url + "/?source=app&do=look")  # on a phone the Camera panel replaces
        c.page.locator("#tokIn").fill(c.token)  # the Conversation, so sign in by hand
        c.page.locator("#tokBtn").click()
        c.page.locator("#p-camera").wait_for(state="visible", timeout=10_000)
        c.page.wait_for_timeout(1000)
        assert c.mic() == {"gum": 0, "rec": 0}  # no camera and no microphone was asked for
        assert c.page.evaluate("location.search") == "?source=app"
    finally:
        c.close()


def test_open_names_a_panel_and_the_rest_of_the_address_stays(
    browser: Any, server_url: str, token: str
) -> None:
    c = Launch(browser, server_url, token, DESKTOP)
    try:
        c.open("/?source=app&open=home&keep=1#top")
        c.page.locator("#p-home").wait_for(state="visible", timeout=10_000)
        assert c.page.evaluate("location.search + location.hash") == "?source=app&keep=1#top"
    finally:
        c.close()


@pytest.mark.parametrize(
    "query",
    [
        "?do=call",
        "?do=TALK",
        "?open=nowhere",
        "?open=constructor",  # a name every plain object has: the allow-list keeps it out
        "?open=__proto__",
        "?do=talk&do=look",
        "?open=home&open=vault",
        "?do=",
    ],
)
def test_anything_else_is_ignored_and_still_taken_out_of_the_address(
    browser: Any, server_url: str, token: str, query: str
) -> None:
    c = Launch(browser, server_url, token, DESKTOP)
    try:
        c.open("/" + query)
        c.page.wait_for_timeout(1500)
        assert c.page.locator("#voiceLine", has_text=TAP).count() == 0
        assert c.focused() != "micBtn"
        for panel in ("home", "vault", "camera"):
            assert not c.visible(panel), panel
        assert c.page.evaluate("location.search") == ""
        assert c.mic() == {"gum": 0, "rec": 0}
        assert c.errors == []
    finally:
        c.close()


def _until(c: Any, expression: str, seconds: float = 10.0) -> None:
    """Polls with evaluate: wait_for_function evaluates its string with eval, which the console's
    CSP refuses whenever the first look finds the condition not yet true."""
    for _ in range(int(seconds * 10)):
        if c.page.evaluate(expression):
            return
        c.page.wait_for_timeout(100)
    raise AssertionError(f"never true: {expression}")


def test_do_sos_asks_the_sos_part_to_open_its_sheet_and_nothing_else(
    browser: Any, server_url: str, token: str
) -> None:
    c = Launch(browser, server_url, token, PHONE)
    try:
        c.page.goto(server_url + "/?source=app&do=sos")
        _until(c, "!!(window.JarvisMobile && window.JarvisMobile.parts.sos)")
        # Part D's sheet is not in this branch: a stand-in records the call
        c.page.evaluate("window.JarvisMobile.parts.sos.open = (o) => { window.__sos = o; }")
        c.page.locator("#tokIn").fill(c.token)
        c.page.locator("#tokBtn").click()
        _until(c, "window.__sos !== undefined")
        assert c.page.evaluate("window.__sos") == {"via": "launch"}
        assert c.mic() == {"gum": 0, "rec": 0}
    finally:
        c.close()


def test_before_sign_in_the_block_asks_the_server_nothing(
    browser: Any, server_url: str, token: str
) -> None:
    c = Launch(browser, server_url, token, PHONE)
    try:
        c.page.goto(server_url + "/?source=app&do=talk")
        c.page.locator("#tokIn").wait_for()
        c.page.wait_for_timeout(2000)
        assert [u for u in c.requests if "/v1/" in u or "/app/" in u] == []
        assert c.page.evaluate("location.search") == "?source=app"  # the word is out at once
        assert c.page.evaluate("sessionStorage.getItem('jarvis_r7_launch_v1')") is not None
        c.page.locator("#tokIn").fill(c.token)
        c.page.locator("#tokBtn").click()
        _talk_ready(c)  # it waited for sign-in, then readied the mic button
        assert c.focused() == "micBtn" and c.mic() == {"gum": 0, "rec": 0}
    finally:
        c.close()


# ---- the push worker (D8, D10) ------------------------------------------------------------------
def _sw(page: Any, run: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = page.evaluate(SW_HARNESS, [SW_SRC, run])
    return out


def test_a_push_keeps_its_target_tags_its_kind_and_offers_talk(
    browser: Any, server_url: str, token: str
) -> None:
    c = Launch(browser, server_url, token, DESKTOP)
    try:
        c.page.goto(server_url + "/health")
        out = _sw(
            c.page,
            {
                "windows": [],
                "pushes": [
                    {"kind": "home_intruder", "text": "Someone at the Gate.", "url": "/?open=home"},
                    {"kind": "sos_sent", "text": "SOS sent.", "url": "/?open=integrations"},
                    {"kind": "x", "text": "ok", "url": "/?open=home&evil=1"},
                    {"kind": "<b>", "text": "ok", "url": "/#home"},
                ],
            },
        )
        shown = out["shown"]
        assert [(s["tag"], s["url"]) for s in shown] == [
            ("home_intruder", "/?open=home"),
            ("sos_sent", "/?open=integrations"),
            ("x", "/"),
            ("alert", "/"),
        ]
        assert all(s["actions"] == [{"action": "talk", "title": "Talk"}] for s in shown)
        assert shown[0]["title"] == "JARVIS" and shown[0]["body"] == "Someone at the Gate."
    finally:
        c.close()


def test_a_tap_with_a_window_open_focuses_it_and_hands_over_never_navigating(
    browser: Any, server_url: str, token: str
) -> None:
    c = Launch(browser, server_url, token, DESKTOP)
    try:
        c.open()
        harness = c.ctx.new_page()
        harness.goto(server_url + "/health")
        out = _sw(
            harness,
            {
                "windows": [["/book/show", True], ["/", False]],
                "click": {"data": {"url": "/?open=home"}},
            },
        )
        # that window (not the show's), no navigate, no second window
        assert out["calls"] == ["close", f"focus {server_url}/"]
        assert out["heard"] == [{"type": "launch", "open": "home", "do": ""}]
        c.page.bring_to_front()
        c.page.locator("#p-home").wait_for(state="visible", timeout=10_000)  # the right panel
        assert c.errors == [] and c.csp_violations() == []
    finally:
        c.close()


def test_the_talk_action_readies_the_mic_in_the_open_window(
    browser: Any, server_url: str, token: str
) -> None:
    c = Launch(browser, server_url, token, PHONE)
    try:
        c.open("/?source=app")
        c.page.wait_for_timeout(1200)
        harness = c.ctx.new_page()
        harness.goto(server_url + "/health")
        out = _sw(
            harness,
            {
                "windows": [["/?source=app", True]],
                "click": {"action": "talk", "data": {"url": "/"}},
            },
        )
        assert out["heard"] == [{"type": "launch", "open": "", "do": "talk"}]
        c.page.bring_to_front()
        _talk_ready(c)
        assert c.focused() == "micBtn" and c.mic() == {"gum": 0, "rec": 0}
    finally:
        c.close()


def test_with_no_jarvis_window_a_tap_opens_one_at_the_target(
    browser: Any, server_url: str, token: str
) -> None:
    c = Launch(browser, server_url, token, DESKTOP)
    try:
        c.page.goto(server_url + "/health")
        out = _sw(c.page, {"windows": [], "click": {"data": {"url": "/?open=approvals"}}})
        assert out["calls"] == ["close", "open /?open=approvals"] and out["heard"] == []
        junk = _sw(c.page, {"windows": [], "click": {"data": {"url": "https://evil.example/"}}})
        assert junk["calls"] == ["close", "open /"]
    finally:
        c.close()


def test_a_forged_launch_message_can_only_open_an_allowed_screen(
    browser: Any, server_url: str, token: str
) -> None:
    c = Launch(browser, server_url, token, DESKTOP)
    try:
        c.open()
        c.page.wait_for_timeout(1200)
        other = c.ctx.new_page()
        other.goto(server_url + "/health")
        for msg in (
            {"type": "launch", "open": "../vault"},
            {"type": "launch", "do": "send"},
            {"type": "other", "open": "vault"},
            "launch",
        ):
            other.evaluate(
                "(m) => { const ch = new BroadcastChannel('jarvis-launch'); ch.postMessage(m); "
                "ch.close(); }",
                msg,
            )
        c.page.bring_to_front()
        c.page.wait_for_timeout(800)
        assert not c.visible("vault") and c.mic() == {"gum": 0, "rec": 0}
    finally:
        c.close()
