# tests/browser/test_console.py — the console in a real browser: loads clean (no JS errors, no
# CSP violations), chats, restores History, switches Night → Day, renders the Integrations panel
# in every state, and fits a 390 px phone with no horizontal scroll.
from __future__ import annotations

import json
from collections.abc import Iterator
from typing import Any
from urllib.parse import quote

import pytest

sync_playwright = pytest.importorskip("playwright.sync_api").sync_playwright

pytestmark = pytest.mark.browser

PHONE = {"width": 390, "height": 844}
DESKTOP = {"width": 1440, "height": 900}
LINKED = {
    "google": {
        "connected": True,
        "email": "owner@example.com",
        "scopes": [
            "https://www.googleapis.com/auth/calendar.readonly",
            "https://www.googleapis.com/auth/calendar.events",
            "https://www.googleapis.com/auth/gmail.readonly",
            "https://www.googleapis.com/auth/gmail.compose",
        ],
        "expires_at": "2026-11-01T12:00:00Z",
        "needs_reconnect": False,
    }
}
# Collected in the page before any script runs: every CSP report the browser raises.
CSP_SPY = """
window.__csp = [];
document.addEventListener('securitypolicyviolation', (e) => {
  window.__csp.push(e.violatedDirective + ' ' + (e.blockedURI || ''));
});
"""


@pytest.fixture(scope="module")
def browser() -> Iterator[Any]:
    with sync_playwright() as p:
        b = p.chromium.launch()
        yield b
        b.close()


class Console:
    """One signed-in console page with error and CSP collectors."""

    def __init__(self, browser: Any, url: str, token: str, viewport: dict[str, int]) -> None:
        self.url = url
        self.token = token
        self.ctx = browser.new_context(viewport=viewport)
        self.page = self.ctx.new_page()
        self.errors: list[str] = []
        self.page.add_init_script(CSP_SPY)
        self.page.on("pageerror", lambda e: self.errors.append(f"pageerror: {e}"))
        self.page.on("console", self._on_console)

    def _on_console(self, msg: Any) -> None:
        if msg.type != "error":
            return
        # The 404s the console handles by design: a backend without the connect flow, the morning
        # brief or long-term memory (those panels then say "Not available in this setup").
        url = str(msg.location.get("url", ""))
        by_design = ("/v1/integrations", "/v1/brief/today", "/v1/memory", "/v1/voice")
        if "404" in msg.text and url.endswith(by_design):
            return
        self.errors.append(f"console.error: {msg.text} @ {msg.location.get('url', '')}")

    def open(self, path: str = "/") -> None:
        self.page.goto(self.url + path)
        # the sign-in gate appears once /console/config has answered; the welcome once signed in
        self.page.locator("#tokIn, #welcome").first.wait_for()
        gate = self.page.locator("#tokIn")
        if gate.count():
            gate.fill(self.token)
            self.page.locator("#tokBtn").click()
        self.page.locator("#welcome").wait_for()

    def csp_violations(self) -> list[str]:
        return list(self.page.evaluate("window.__csp"))

    def send(self, text: str) -> str:
        before = self.page.locator(".row.jarvis .bubble:not(.typing)").count()
        self.page.locator("#input").fill(text)
        self.page.locator("#send").click()
        reply = self.page.locator(".row.jarvis .bubble:not(.typing)").nth(before)
        reply.wait_for()
        return str(reply.text_content())

    def open_panel(self, panel: str) -> None:
        tab = self.page.locator(f'.dk[data-open="{panel}"]')
        if tab.is_visible():
            tab.click()
        else:  # phones: the tabs that don't fit the bar sit behind More (slice 8)
            self.page.locator("#dockMore").click()
            self.page.locator(f'#moreSheet [data-sheet-open="{panel}"]').click()
        self.page.locator(f"#p-{panel}").wait_for(state="visible")

    def close(self) -> None:
        self.ctx.close()


@pytest.fixture
def console(browser: Any, server_url: str, token: str) -> Iterator[Console]:
    c = Console(browser, server_url, token, DESKTOP)
    yield c
    c.close()


def test_page_loads_with_zero_console_errors_and_zero_csp_violations(console: Console) -> None:
    console.open()
    console.page.wait_for_timeout(1500)  # let the deferred scripts and the 3D module settle
    assert str(console.page.locator("#log .welcome h1").text_content()).startswith("Good ")
    assert console.csp_violations() == []
    assert console.errors == []


def test_sending_a_message_shows_the_reply(console: Console) -> None:
    console.open()
    reply = console.send("hello from the browser test")
    assert "hello from the browser test" in reply  # the mock brain echoes the message
    assert console.page.locator(".row.user .bubble").count() == 1
    assert console.errors == []


def test_history_restores_an_earlier_conversation(console: Console) -> None:
    console.open()
    console.send("remember this one")
    console.page.locator("#newBtn").click()
    assert console.page.locator(".row.user").count() == 0
    console.open_panel("history")
    row = console.page.locator("#convos .convo .open").first
    row.wait_for()
    row.click()
    console.page.locator(".sys", has_text="Earlier conversation restored.").wait_for()
    assert console.page.locator(".row.user .bubble").text_content() == "remember this one"
    assert console.errors == []


@pytest.mark.parametrize("which", ["reply_lost", "message_lost", "code_only"])
def test_session_conflict_reloads_the_conversation_and_says_so(
    console: Console, which: str
) -> None:
    """Slice 10 A3 + review L5: another window saved this conversation first (409
    session_conflict). The console reloads what the server holds, shows the server's own line
    (it says whether the owner's message was kept) — not an error — and never resends."""
    from jarvis.api.routes import MESSAGE_LOST, REPLY_LOST

    detail = {"reply_lost": REPLY_LOST, "message_lost": MESSAGE_LOST, "code_only": "conflict"}
    console.open()
    console.send("first message")
    reloads: list[str] = []
    posts: list[str] = []
    console.page.on(
        "request",
        lambda r: reloads.append(r.url) if "/v1/sessions/sess_" in r.url else None,
    )
    conflict = {"error": "session_conflict", "detail": detail[which]}

    def refuse(route: Any) -> None:
        posts.append(route.request.method)
        route.fulfill(status=409, content_type="application/json", body=json.dumps(conflict))

    console.page.route("**/v1/chat", refuse)
    console.page.locator("#input").fill("second message")
    console.page.locator("#send").click()
    line = console.page.locator("#log .sys", has_text="another window")
    line.wait_for()
    want = detail[which] if which != "code_only" else "This conversation changed in another window"
    assert str(line.text_content()).startswith(want)
    assert line.get_attribute("role") == "status"  # a note, not an alert
    assert reloads, "the conversation was not reloaded from the server"
    users = console.page.locator(".row.user .bubble")
    assert users.count() == 1 and users.text_content() == "first message"  # what the server holds
    assert console.page.locator("#log .sys.error").count() == 0
    assert console.page.locator("#send").is_disabled() is True  # idle again, composer empty
    console.page.wait_for_timeout(300)
    assert posts == ["POST"]  # never resent behind the owner's back
    assert [e for e in console.errors if "409" not in e] == []


def test_switching_night_to_day_changes_the_surface(console: Console) -> None:
    console.open()
    html = console.page.locator("html")
    assert html.get_attribute("data-surface") == "night"
    console.page.locator("#themeBtn").click()
    console.page.locator('label[for="jx-s-day"]').click()
    assert html.get_attribute("data-surface") == "day"
    console.page.keyboard.press("Escape")
    console.page.reload()
    console.open()
    assert html.get_attribute("data-surface") == "day"  # remembered
    assert console.errors == []


def test_integrations_panel_shows_not_available_when_the_route_is_missing(
    console: Console,
) -> None:
    """Token-auth setups (and a backend without slice 6) answer 404: no error, a plain message."""
    console.open()
    console.open_panel("integrations")
    row = console.page.locator("#integrations .integ").first  # Google; the WhatsApp row follows
    row.wait_for()
    assert row.get_attribute("data-state") in {"unavailable", "unlinked"}
    text = row.text_content()
    assert "Not available in this setup" in text or "Connect Google" in text
    assert console.page.locator("#rGoogle").text_content() in {"—", "Not linked"}
    assert console.errors == []


def test_integrations_panel_not_connected_state(console: Console) -> None:
    console.page.route(
        "**/v1/integrations",
        lambda r: r.fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps(
                {
                    "google": {
                        "connected": False,
                        "email": None,
                        "scopes": [],
                        "expires_at": None,
                        "needs_reconnect": False,
                    }
                }
            ),
        ),
    )
    console.open()
    console.open_panel("integrations")
    row = console.page.locator('#integrations .integ[data-state="unlinked"]')
    row.wait_for()
    assert "Not connected" in row.text_content()
    assert console.page.locator("#googleConnect").text_content() == "Connect Google"
    assert console.page.locator("#rGoogle").text_content() == "Not linked"
    assert console.errors == []


def test_integrations_panel_connected_state_and_two_step_disconnect(console: Console) -> None:
    posted: list[dict[str, str]] = []

    def integrations(route: Any) -> None:
        body = LINKED if not posted else {"google": {**LINKED["google"], "connected": False}}
        route.fulfill(status=200, content_type="application/json", body=json.dumps(body))

    def disconnect(route: Any) -> None:
        posted.append(dict(route.request.headers))
        route.fulfill(status=204, body="")

    console.page.route("**/v1/integrations", integrations)
    console.page.route("**/v1/integrations/google/disconnect", disconnect)
    console.open()
    console.open_panel("integrations")
    row = console.page.locator('#integrations .integ[data-state="linked"]')
    row.wait_for()
    text = row.text_content()
    assert "Connected as" in text and "owner@example.com" in text
    assert "Calendar: read & edit" in text and "Gmail: read, draft, send" in text
    assert console.page.locator("#rGoogle").text_content() == "Linked"
    # two-step confirm: the first click only asks
    console.page.locator("#googleDisconnect").click()
    assert posted == []
    confirm = console.page.locator("#integrations .confirm")
    assert "Disconnect Google?" in confirm.text_content()
    confirm.locator("button", has_text="Keep").click()
    assert console.page.locator("#integrations .confirm").count() == 0 and posted == []
    console.page.locator("#googleDisconnect").click()
    console.page.locator("#integrations .confirm .btn.danger").click()
    console.page.locator('#integrations .integ[data-state="unlinked"]').wait_for()
    assert len(posted) == 1
    assert posted[0].get("x-requested-with") == "JARVIS"  # the CSRF header travels with it
    assert posted[0].get("authorization") == "Bearer " + console.token
    assert "Google disconnected." in console.page.locator("#integrations").text_content()
    assert console.errors == []


def test_integrations_panel_needs_reconnecting_state(console: Console) -> None:
    body = {"google": {**LINKED["google"], "needs_reconnect": True}}
    console.page.route(
        "**/v1/integrations",
        lambda r: r.fulfill(status=200, content_type="application/json", body=json.dumps(body)),
    )
    console.open()
    console.open_panel("integrations")
    row = console.page.locator('#integrations .integ[data-state="reconnect"]')
    row.wait_for()
    assert "Needs reconnecting" in row.text_content()
    assert console.page.locator("#googleConnect").text_content() == "Reconnect"
    assert console.page.locator("#rGoogle").text_content() == "Reconnect"
    assert console.errors == []


def test_return_from_google_opens_the_panel_and_cleans_the_url(console: Console) -> None:
    console.page.route(
        "**/v1/integrations",
        lambda r: r.fulfill(status=200, content_type="application/json", body=json.dumps(LINKED)),
    )
    console.open("/?connected=google")
    console.page.locator("#p-integrations").wait_for(state="visible")
    console.page.locator("#integrations .inote", has_text="Google connected").wait_for()
    assert console.page.evaluate("location.search") == ""
    assert console.errors == []


@pytest.mark.parametrize(
    "code, words",
    [
        ("missing_scopes", "left unticked"),
        ("wrong_account", "different Google account"),
        ("not_started", "wasn't started"),
        ("oauth_failed", "didn't finish"),
        ("no_refresh_token", "lasting access"),
        ("<img src=x onerror=alert(1)>", "didn't complete"),  # unknown code: generic line
    ],
)
def test_connect_error_explains_itself_opens_the_panel_and_cleans_the_url(
    console: Console, code: str, words: str
) -> None:
    """Security review L6: /?connect_error=<code> → a plain-English line, never the raw code."""
    body = {"google": {**LINKED["google"], "connected": False, "email": None, "scopes": []}}
    console.page.route(
        "**/v1/integrations",
        lambda r: r.fulfill(status=200, content_type="application/json", body=json.dumps(body)),
    )
    console.open("/?connect_error=" + quote(code))
    console.page.locator("#p-integrations").wait_for(state="visible")
    line = console.page.locator("#integrations .inote.bad")
    line.wait_for()
    assert words in str(line.text_content())
    assert code not in str(console.page.locator("#integrations").inner_html())
    assert console.page.evaluate("location.search") == ""
    assert console.page.locator("#googleConnect").is_visible()  # the way forward is right there
    assert console.errors == []


def test_phone_width_has_no_horizontal_scroll(browser: Any, server_url: str, token: str) -> None:
    c = Console(browser, server_url, token, PHONE)
    try:
        c.open()
        c.open_panel("integrations")
        c.page.wait_for_timeout(300)
        widths = c.page.evaluate(
            "[document.documentElement.scrollWidth, document.body.scrollWidth, window.innerWidth]"
        )
        assert widths[0] <= widths[2] and widths[1] <= widths[2], widths
        assert c.page.locator('.dk[data-open="integrations"]').is_visible()
        assert c.errors == []
    finally:
        c.close()
