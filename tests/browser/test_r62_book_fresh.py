# tests/browser/test_r62_book_fresh.py -- R6.2 code review 2 (M1, L1, L2, L3): the Questions panel
# reads the owner's choice again where it is used, so a switch to Cloud in Book settings reaches the
# show he already has open; a recogniser that never ends does not leave the mic dead; a late
# correction never writes into a panel that was closed; tapping the mic stops a reply still being
# narrated. A faked SpeechRecognition and Chromium's fake microphone, against FakeBook.
# ruff: noqa: E501 -- JavaScript strings
from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest
from book_mocks import FakeBook
from test_book_show import _begin, _clean, _show, _to_questions
from test_console import Console
from test_r62_book_listen import FAKE_SR, SAID, _done, _listen, _words
from test_r62_book_mic import FAKE_MIC, PRESSED, TRACE, _said

_pw = pytest.importorskip("playwright.sync_api")

pytestmark = pytest.mark.browser

# the recogniser's stop() is heard but it never ends (some Chrome network failures)
NEVER_ENDS = "window.SpeechRecognition.prototype.stop = function () { this.stopped = true; };"
# POST /v1/book/show/heard waits until the test lets it through (window.__heardRelease())
HOLD_HEARD = """
(() => {
  let open = null;
  const gate = new Promise((r) => { open = r; });
  window.__heardRelease = () => open(); window.__heardAsked = false;
  const f = window.fetch.bind(window);
  window.fetch = async (u, o) => { if (String(u).includes('/v1/book/show/heard')) { window.__heardAsked = true; await gate; } return f(u, o); };
})();
"""
# a reply that is still being narrated: the browser voice starts and never ends; every cancel is counted
NARRATING = """() => { window.__cancels = 0; const s = window.speechSynthesis;
  s.cancel = () => { window.__cancels += 1; };
  s.speak = (u) => { window.__spoken.push(u.text); setTimeout(() => u.onstart && u.onstart(), 10); }; }"""


@pytest.fixture(scope="module")
def browser() -> Iterator[Any]:
    with _pw.sync_playwright() as p:
        b = p.chromium.launch(args=FAKE_MIC)
        yield b
        b.close()


def _open(
    browser: Any, url: str, token: str, *init: str, audience: str = "owner"
) -> tuple[Console, FakeBook]:
    """The Questions panel of a show the owner opened with both choices on the free browser."""
    c, fake = _show(
        browser,
        url,
        token,
        audience=audience,
        init=(TRACE, FAKE_SR, *init),
        voice="browser",
        listening="browser",
    )
    _begin(c)
    _to_questions(c)
    return c, fake


def _owner_switched(fake: FakeBook, **choices: str) -> None:
    """Book settings (another tab) now say Cloud: the server's next script says so."""
    code, body = fake.script_answer
    fake.script_answer = (code, {**body, **choices})


def _count(fake: FakeBook, path: str, at_least: int = 1) -> bool:
    return len(fake.to("POST", path)) >= at_least


# ---- L1: a recogniser that never ends must not leave the mic dead ----------------------------------
@pytest.mark.parametrize("said_words", [False, True])
def test_a_recogniser_that_never_ends_after_stop_gives_the_mic_back(
    browser: Any, server_url: str, token: str, said_words: bool
) -> None:
    c, fake = _open(browser, server_url, token, NEVER_ENDS)
    try:
        _listen(c)
        if said_words:
            c.page.evaluate(f"window.__recs[0].say({SAID!r})")
        c.page.locator("#shMic").click()  # stop: its end never comes
        c.page.wait_for_function(PRESSED.format("false"), timeout=8000)
        if said_words:
            _done(c)
            assert c.page.locator("#shQ").input_value() == SAID
        else:
            assert _said(c)[0].startswith(_words(c, "rec_stopped"))
            assert "type your question" in _said(c)[0].lower()
        c.page.locator("#shMic").click()  # and the mic works again
        c.page.wait_for_function("() => window.__recs.length === 2")
        _clean(c)
    finally:
        c.close()
