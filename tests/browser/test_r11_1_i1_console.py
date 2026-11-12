# tests/browser/test_r11_1_i1_console.py -- R11.1 I1: the console's rule for every part module (the
# orchestrator's merge gate after Part D found it): NO module calls the API before
# JarvisConsole.ready() says the owner is in. A call made before sign-in is answered 401, and the
# console answers a 401 with the sign-in gate, so an answer landing just after a sign-in threw the
# owner back to the gate. Parts C and D have their own test; this one covers Part A's plan block
# (/v1/series, also on the page becoming visible again) and Part B's files block (/v1/input, also
# on an attach or a conversation switch), with those triggers fired while signed out. (A reply
# cannot happen before sign-in, so jarvis:reply is not fired.)
from __future__ import annotations

import json
from collections.abc import Iterator
from typing import Any

import pytest
from test_console import DESKTOP, Console

_pw = pytest.importorskip("playwright.sync_api")
sync_playwright = _pw.sync_playwright

pytestmark = pytest.mark.browser


@pytest.fixture(scope="module")
def browser() -> Iterator[Any]:
    with sync_playwright() as p:
        b = p.chromium.launch()
        yield b
        b.close()


# the hint fetch only runs in a browser whose recogniser takes hints: give headless Chromium one
HINTS_INIT = "window.SpeechRecognitionPhrase = window.SpeechRecognitionPhrase || function () {};"
TRIGGERS = """() => {
  Object.defineProperty(document, 'visibilityState', { configurable: true, get: () => 'visible' });
  document.dispatchEvent(new Event('visibilitychange'));
  for (const name of ['jarvis:attach', 'jarvis:switch'])
    document.dispatchEvent(new CustomEvent(name, { detail: { count: 0, busy: false } }));
}"""


@pytest.mark.parametrize(("block", "path"), [("planChecks", "/v1/series"), ("", "/v1/input")])
def test_before_sign_in_the_block_asks_the_server_nothing(
    browser: Any, server_url: str, token: str, block: str, path: str
) -> None:
    c = Console(browser, server_url, token, DESKTOP)
    asked: list[str] = []
    c.page.add_init_script(HINTS_INIT)
    c.page.on("request", lambda r: asked.append(r.url) if path in r.url else None)
    c.page.goto(server_url + "/")
    c.page.locator("#tokIn").wait_for()
    c.page.wait_for_timeout(1200)  # the R11.1 modules have loaded and built their blocks
    if block:
        assert c.page.locator(f"#{block}").count() == 1
    c.page.evaluate(TRIGGERS)  # what could make the block ask, while he is signed out
    c.page.wait_for_timeout(900)  # past the hint fetch's own 400 ms wait

    assert asked == [] and c.errors == []
    assert c.page.locator("#tokIn").is_visible()

    c.page.locator("#tokIn").fill(token)
    c.page.locator("#tokBtn").click()
    c.page.locator("#welcome").wait_for()
    c.page.wait_for_timeout(900)

    assert len(asked) >= 1  # once he is in, the block asks the server
    assert c.page.locator("#welcome").is_visible() and not c.page.locator("#tokIn").is_visible()
    assert c.errors == [] and c.csp_violations() == []
    c.close()


# ---- INTEGRATION-D 4.D: the "Look up" card under a real reply ---------------------------------
NAME = "Lekha Examplekar"  # a made-up public figure
CAPTION = "MINISTER LEKHA EXAMPLEKAR OPENS THE HARBOUR BRIDGE"
OFFER = {
    "kind": "people_offer",
    "name": NAME,
    "caption": CAPTION,
    "words": f"The picture's text names {NAME}. Press 'Look up' to check them with your people "
    "research.",
    "button": "Look up",
}


def test_the_look_up_card_shows_under_the_reply_and_researches_only_on_his_press(
    browser: Any, server_url: str, token: str
) -> None:
    from test_media import _json, _reply

    c = Console(browser, server_url, token, DESKTOP)
    asked: list[Any] = []

    def research(route: Any) -> None:
        asked.append(json.loads(route.request.post_data or "{}"))
        route.fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps({"refused": True, "message": "Not a public figure I can verify."}),
        )

    c.page.route("**/v1/people/research", research)
    _json(c.page, "**/v1/chat", _reply("The picture's text names someone, Sir.", [OFFER]))
    c.open()
    c.send("who is on this poster?")
    card = c.page.locator(".row.jarvis [data-kind='people_offer']")
    card.wait_for()
    assert OFFER["words"] in card.inner_text() and f"Caption read: '{CAPTION}'" in card.inner_text()
    assert asked == []  # nothing is researched until he presses it
    card.locator("button", has_text="Look up").click()
    c.page.wait_for_function("() => document.getElementById('peopleName').value !== ''")
    assert c.page.input_value("#peopleName") == NAME
    c.page.wait_for_timeout(300)
    assert asked == [{"name": NAME}]
    assert c.errors == [] and c.csp_violations() == []
    c.close()
