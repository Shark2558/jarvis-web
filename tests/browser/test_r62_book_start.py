# tests/browser/test_r62_book_start.py -- R6.2 round 3 (review 3): the mic tap reads the owner's
# choice again (a network GET) before it listens. While that read is in flight the panel may close
# (Finish, End, a jump) or "Mic off" may be switched on, and nothing may start then; and a second
# tap during the read never starts a second recogniser or recording, in the browser's mode or the
# Cloud's. A faked SpeechRecognition and Chromium's fake microphone, against FakeBook.
# ruff: noqa: E501 -- JavaScript strings
from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest
from book_mocks import FakeBook
from test_book_show import _clean
from test_console import Console
from test_r62_book_fresh import _open, _owner_switched
from test_r62_book_listen import FAKE_SR  # noqa: F401 -- used by _open
from test_r62_book_mic import FAKE_MIC, PRESSED, _status

_pw = pytest.importorskip("playwright.sync_api")

pytestmark = pytest.mark.browser

# GET /v1/book/show/script waits, once armed (window.__holdScript()), until window.__scriptRelease()
HOLD_SCRIPT = """
(() => {
  window.__scriptAsked = 0; let gate = null;
  window.__holdScript = () => { gate = new Promise((r) => { window.__scriptRelease = () => { gate = null; r(); }; }); };
  const f = window.fetch.bind(window);
  window.fetch = async (u, o) => {
    if (String(u).includes('/v1/book/show/script')) { window.__scriptAsked += 1; if (gate) await gate; }
    return f(u, o);
  };
})();
"""
MODES = ["browser", "cloud"]


@pytest.fixture(scope="module")
def browser() -> Iterator[Any]:
    with _pw.sync_playwright() as p:
        b = p.chromium.launch(args=FAKE_MIC)
        yield b
        b.close()


def _tap_during_the_read(c: Console, fake: FakeBook, mode: str) -> int:
    """Choose `mode`, hold the next script read, tap the mic once; returns after the read began."""
    if mode == "cloud":
        _owner_switched(fake, listening="cloud")
    asked = int(c.page.evaluate("window.__scriptAsked"))
    c.page.evaluate("window.__holdScript()")
    c.page.locator("#shMic").click()
    c.page.wait_for_function(f"() => window.__scriptAsked > {asked}")
    return asked + 1


def _release_and_settle(c: Console) -> None:
    c.page.evaluate("window.__scriptRelease()")
    c.page.wait_for_timeout(600)


def _nothing_started(c: Console) -> None:
    assert c.page.evaluate("window.__recs.length") == 0
    assert c.page.evaluate("window.__gum") == []
    assert c.page.locator("#shMic").get_attribute("aria-pressed") == "false"


@pytest.mark.parametrize("mode", MODES)
def test_a_panel_closed_during_the_read_never_starts_the_mic(
    browser: Any, server_url: str, token: str, mode: str
) -> None:
    c, fake = _open(browser, server_url, token, HOLD_SCRIPT)
    try:
        _tap_during_the_read(c, fake, mode)
        c.page.locator("#shFinish").click()  # the panel closes while the choice is being read
        c.page.wait_for_function("() => document.getElementById('shTalk').hidden")
        _release_and_settle(c)
        _nothing_started(c)
        _clean(c)
    finally:
        c.close()


@pytest.mark.parametrize("mode", MODES)
def test_mic_off_set_during_the_read_never_starts_the_mic(
    browser: Any, server_url: str, token: str, mode: str
) -> None:
    c, fake = _open(browser, server_url, token, HOLD_SCRIPT)
    try:
        _tap_during_the_read(c, fake, mode)
        c.page.evaluate("window.JarvisAudio.lock('button')")  # "Mic off", set from another tab
        _release_and_settle(c)
        _nothing_started(c)
        assert "switched off" in _status(c)
        _clean(c)
    finally:
        c.close()


@pytest.mark.parametrize("mode", MODES)
def test_a_second_tap_during_the_read_starts_no_second_listener(
    browser: Any, server_url: str, token: str, mode: str
) -> None:
    c, fake = _open(browser, server_url, token, HOLD_SCRIPT)
    try:
        _tap_during_the_read(c, fake, mode)
        c.page.locator("#shMic").click()  # a second tap while the read is still in flight
        _release_and_settle(c)
        c.page.wait_for_function(PRESSED.format("true"))
        started = c.page.evaluate("window.__recs.length") + c.page.evaluate("window.__gum.length")
        assert started == 1  # one recogniser (browser) or one microphone request (cloud)
        _clean(c)
    finally:
        c.close()
