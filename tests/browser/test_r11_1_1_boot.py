# tests/browser/test_r11_1_1_boot.py
"""R11.1 hotfix 1 (v11.1.1): what the owner does while the console is still loading is kept.

The console shows its welcome first and only then loads the brains, restores the saved
conversation and puts focus in the message box. On a slow link (and on GitHub's busy test
machines, CI run 111) the owner can act in between:
- a message sent then started a conversation, and the late restore loaded it again over the
  reply that was still arriving (a GET the server may answer 404 for a brand-new id);
- the Appearance menu opened then was closed by the late focus move into the message box.
Both are held here by holding /v1/brains, the first thing the console waits for after the welcome.
"""

from __future__ import annotations

import json
from typing import Any

import pytest
from test_console import DESKTOP, Console, browser  # noqa: F401 - the browser fixture

pytestmark = pytest.mark.browser

HOLD_WAIT_MS = 10_000  # the console asks for /v1/brains within this long of the welcome
REPLY = {
    "reply": "Here I am, Sir.",
    "session_id": "sess_boot",
    "brain": "default",
    "cards": [],
    "usage": {"input_tokens": 1, "output_tokens": 1},
}


def _hold_brains(c: Console) -> list[Any]:
    held: list[Any] = []
    c.page.route("**/v1/brains", lambda r: held.append(r))
    return held


def _wait_held(c: Console, held: list[Any]) -> None:
    for _ in range(HOLD_WAIT_MS // 100):
        if held:
            return
        c.page.wait_for_timeout(100)
    raise AssertionError("the console never asked for /v1/brains")


def _release_and_settle(c: Console, held: list[Any]) -> None:
    """Lets the boot carry on, and returns once it has asked for the conversation list (its
    last request, after the restore and before the focus move)."""
    with c.page.expect_request(lambda q: "/v1/sessions?limit=" in q.url):
        held[0].continue_()
    c.page.wait_for_timeout(300)  # the focus move follows the list request in the same task


def test_a_message_sent_while_the_console_loads_is_not_loaded_again(
    browser: Any,  # noqa: F811 - the fixture imported above
    server_url: str,
    token: str,
) -> None:
    c = Console(browser, server_url, token, DESKTOP)
    try:
        held = _hold_brains(c)
        c.page.route(
            "**/v1/chat",
            lambda r: r.fulfill(
                status=200, content_type="application/json", body=json.dumps(REPLY)
            ),
        )
        opened: list[str] = []
        c.page.on(
            "request",
            lambda q: (
                opened.append(q.url) if q.method == "GET" and "/v1/sessions/" in q.url else None
            ),
        )
        c.open()
        _wait_held(c, held)
        assert c.send("hello") == REPLY["reply"]
        _release_and_settle(c, held)
        assert opened == []  # the conversation he is in was not loaded again over his reply
        assert (
            c.page.locator(".row.jarvis .bubble:not(.typing)").last.text_content() == REPLY["reply"]
        )
        assert c.errors == []
    finally:
        c.close()


def test_the_appearance_menu_opened_while_the_console_loads_stays_open(
    browser: Any,  # noqa: F811 - the fixture imported above
    server_url: str,
    token: str,
) -> None:
    c = Console(browser, server_url, token, DESKTOP)
    try:
        held = _hold_brains(c)
        c.open()
        _wait_held(c, held)
        c.page.locator("#themeBtn").click()
        c.page.locator('label[for="jx-s-day"]').wait_for(state="visible")
        _release_and_settle(c, held)
        assert c.page.locator("#themeMenu").is_visible()  # his menu kept its focus
        c.page.locator('label[for="jx-s-day"]').click()
        assert c.page.locator("html").get_attribute("data-surface") == "day"
        assert c.errors == []
    finally:
        c.close()


def test_with_nothing_touched_the_message_box_still_gets_focus(
    browser: Any,  # noqa: F811 - the fixture imported above
    server_url: str,
    token: str,
) -> None:
    c = Console(browser, server_url, token, DESKTOP)
    try:
        held = _hold_brains(c)
        c.open()
        _wait_held(c, held)
        _release_and_settle(c, held)
        assert c.page.evaluate("document.activeElement && document.activeElement.id") == "input"
    finally:
        c.close()


def test_signing_in_again_after_a_401_restores_the_conversation(
    browser: Any,  # noqa: F811 - the fixture imported above
    server_url: str,
    token: str,
) -> None:
    """Code review M1: a 401 mid-conversation shows the gate; signing in again boots again, with
    the conversation still current. That boot must restore it (it clears the log first)."""
    c = Console(browser, server_url, token, DESKTOP)
    try:
        answers = [
            (200, REPLY),
            (401, {"detail": {"code": "unauthorized", "message": "Sign in required."}}),
        ]
        c.page.route(
            "**/v1/chat",
            lambda r: (
                lambda s, b: r.fulfill(
                    status=s, content_type="application/json", body=json.dumps(b)
                )
            )(*answers.pop(0)),
        )
        transcript = {
            "id": REPLY["session_id"],
            "turns": [
                {"role": "user", "content": "hello"},
                {"role": "assistant", "content": REPLY["reply"], "model": "default"},
            ],
            "metadata": {},
            "total_cost_inr": 0,
        }
        c.page.route(
            f"**/v1/sessions/{REPLY['session_id']}",
            lambda r: r.fulfill(
                status=200, content_type="application/json", body=json.dumps(transcript)
            ),
        )
        c.open()
        assert c.send("hello") == REPLY["reply"]
        c.page.locator("#input").fill("and again")
        c.page.locator("#send").click()
        c.page.locator("#tokIn").wait_for(state="visible")  # the 401 brought the gate back
        with c.page.expect_request(f"**/v1/sessions/{REPLY['session_id']}"):
            c.page.locator("#tokIn").fill(c.token)
            c.page.locator("#tokBtn").click()
        c.page.locator("#log .sys", has_text="Earlier conversation restored.").wait_for()
        assert REPLY["reply"] in c.page.locator("#log").inner_text()
    finally:
        c.close()
