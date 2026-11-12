# tests/browser/test_r11_1_i1_console.py -- R11.1 I1: the console's rule for every part module (the
# orchestrator's merge gate after Part D found it): NO module calls the API before
# JarvisConsole.ready() says the owner is in. A call made before sign-in is answered 401, and the
# console answers a 401 with the sign-in gate, so an answer landing just after a sign-in threw the
# owner back to the gate. Parts C and D have their own test; this one covers Part A's plan block
# (/v1/series, also on the page becoming visible again) and Part B's files block (/v1/input, also
# on an attach or a conversation switch), with those triggers fired while signed out. (A reply
# cannot happen before sign-in, so jarvis:reply is not fired.)
from __future__ import annotations

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
