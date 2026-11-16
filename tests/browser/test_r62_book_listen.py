# tests/browser/test_r62_book_listen.py -- R6.2 owner decision 4 (15 Nov 2026, 20:29 IST): the Book's
# "Ask by voice" listens with THIS browser's own recogniser by default (Rs 0), through the shared
# R5 JarvisAudio.recognizer() (en-IN; the "Mic off" lock refuses and aborts it), and the show speaks
# with the browser's voice, so no cloud speech call happens. A faked SpeechRecognition drives every
# case: start, stop, the words to the box (never sent by themselves; the free corrections at
# /v1/book/show/heard), nothing heard, each Web Speech error, an unsupported browser and "Mic off".
# Where the browser can't recognise speech the page says so plainly and offers typing; only the
# owner is pointed to the switch, and nothing switches by itself. Book settings: the owner's
# Listening and Show voice rows ask first, with what the cloud costs, before a switch to it.
# ruff: noqa: E501 -- JavaScript strings
from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest
from book_mocks import PASSKEY_STUB, FakeBook
from test_book_show import _begin, _clean, _show, _to_questions
from test_console import DESKTOP, Console
from test_r62_book_mic import LOCKED, PRESSED, TRACE, _said, _status, _typing_still_works

_pw = pytest.importorskip("playwright.sync_api")

pytestmark = pytest.mark.browser

# A SpeechRecognition the test drives: every one built is in window.__recs; say(text) gives a final
# result, fail(code) an error and then the end; stop() ends it (after its words), abort() errs
# 'aborted' and ends, as Chrome's do.
FAKE_SR = """
window.__recs = [];
(() => {
  class FakeRec {
    constructor() { this.lang = ''; this.started = false; this.stopped = false; this.aborted = false; this.ended = false; window.__recs.push(this); }
    start() { if (this.started) throw new DOMException('already started', 'InvalidStateError'); this.started = true; }
    stop() { this.stopped = true; setTimeout(() => this._end(), 20); }
    abort() { this.aborted = true; setTimeout(() => { this.onerror && this.onerror({ error: 'aborted' }); this._end(); }, 0); }
    _end() { if (this.ended) return; this.ended = true; this.onend && this.onend({}); }
    say(text) { const alt = [{ transcript: text, confidence: 0.9 }]; alt.isFinal = true; this.onresult && this.onresult({ resultIndex: 0, results: [alt] }); }
    fail(code) { this.onerror && this.onerror({ error: code }); this._end(); }
  }
  window.SpeechRecognition = FakeRec; window.webkitSpeechRecognition = FakeRec;
})();
"""
NO_SR = "window.SpeechRecognition = undefined; window.webkitSpeechRecognition = undefined;"
LIVE = "() => window.__recs.length === 1 && window.__recs[0].started"
SAID = "How does JARVIS keep my data private?"
TO_CLOUD = "switch to Cloud listening in Book settings"


@pytest.fixture(scope="module")
def browser() -> Iterator[Any]:
    with _pw.sync_playwright() as p:
        b = p.chromium.launch()
        yield b
        b.close()


def _questions(
    browser: Any, url: str, token: str, *init: str, audience: str = "guest"
) -> tuple[Console, FakeBook]:
    """The Questions panel with the server's defaults: no voice or listening key, so the page takes
    the free browser for both (the key is "browser" from the real server, test_r62_book_listening)."""
    c, fake = _show(
        browser,
        url,
        token,
        audience=audience,
        init=(TRACE, FAKE_SR, *init),
        voice=None,
        listening=None,
    )
    _begin(c)
    _to_questions(c)
    return c, fake


def _listen(c: Console) -> None:
    c.page.locator("#shMic").click()
    c.page.wait_for_function(LIVE)
    c.page.wait_for_function(PRESSED.format("true"))


def _done(c: Console) -> None:
    c.page.wait_for_function(
        "() => document.getElementById('shHear').textContent.startsWith('Done')"
    )


def _words(c: Console, code: str) -> str:
    return str(c.page.evaluate(f"window.JarvisAudio.words('{code}')"))


def _no_cloud(fake: FakeBook) -> None:
    """The negative control: nothing went to the cloud recogniser or the cloud voice."""
    assert fake.to("POST", "/v1/book/show/hear") == []
    assert fake.to("POST", "/v1/book/show/speak") == []


# ---- the default: the browser listens, en-IN; the words land in the box, never sent ------------------
def test_by_default_the_browser_listens_and_the_words_land_in_the_box_unsent(
    browser: Any, server_url: str, token: str
) -> None:
    c, fake = _questions(browser, server_url, token)
    try:
        mic = c.page.locator("#shMic")
        assert mic.is_enabled() and _status(c) == ""
        _listen(c)
        assert "Listening" in _status(c)
        rec = c.page.evaluate(
            "({ lang: window.__recs[0].lang, cont: window.__recs[0].continuous })"
        )
        assert rec == {"lang": "en-IN", "cont": False}
        c.page.evaluate(f"window.__recs[0].say({SAID!r})")
        mic.click()  # the second tap stops: its words, then its end
        c.page.wait_for_function(PRESSED.format("false"))
        _done(c)
        assert c.page.locator("#shQ").input_value() == SAID
        (sent,) = fake.to("POST", "/v1/book/show/heard")
        assert sent["body"] == {"text": SAID} and sent["headers"].get("x-jarvis-book")
        c.page.wait_for_timeout(400)
        assert fake.to("POST", "/v1/book/show/ask") == []  # never sent by itself
        assert c.page.evaluate("window.__recs[0].stopped") is True
        assert c.page.evaluate("window.__gum") == []  # the page itself never opened the microphone
        _no_cloud(fake)
        _clean(c)
    finally:
        c.close()


def test_the_free_corrections_show_what_was_heard(
    browser: Any, server_url: str, token: str
) -> None:
    c, fake = _questions(browser, server_url, token)
    fake.heard_answers = [
        (200, {"text": "JARVIS how does the calendar work", "heard": "javis how does the calender work",
               "changed": True, "no_speech": False})
    ]  # fmt: skip
    try:
        _listen(c)
        c.page.evaluate(
            "window.__recs[0].say('javis how does the calender work'); window.__recs[0].stop()"
        )
        _done(c)
        assert c.page.locator("#shQ").input_value() == "JARVIS how does the calendar work"
        assert "javis how does the calender work" in _status(c)
        _no_cloud(fake)
        _clean(c)
    finally:
        c.close()


def test_a_recogniser_that_ends_by_itself_still_lands_its_words(
    browser: Any, server_url: str, token: str
) -> None:
    c, fake = _questions(browser, server_url, token)
    try:
        _listen(c)
        c.page.evaluate(f"window.__recs[0].say({SAID!r}); window.__recs[0]._end()")
        _done(c)
        assert c.page.locator("#shQ").input_value() == SAID
        assert c.page.locator("#shMic").get_attribute("aria-pressed") == "false"
        _clean(c)
    finally:
        c.close()


def test_a_correction_that_fails_still_lands_the_words_as_heard(
    browser: Any, server_url: str, token: str
) -> None:
    c, fake = _questions(browser, server_url, token)
    fake.heard_answers = ["abort"]
    try:
        _listen(c)
        c.page.evaluate(f"window.__recs[0].say({SAID!r}); window.__recs[0].stop()")
        _done(c)
        assert c.page.locator("#shQ").input_value() == SAID and _said(c) == []
        _typing_still_works(c, fake)
        _clean(c, "net::ERR_FAILED")
    finally:
        c.close()


def test_nothing_heard_says_so_and_keeps_what_was_typed(
    browser: Any, server_url: str, token: str
) -> None:
    c, fake = _questions(browser, server_url, token)
    try:
        c.page.locator("#shQ").fill("my draft")
        _listen(c)
        c.page.evaluate("window.__recs[0].fail('no-speech')")
        c.page.locator("#shThread .sys", has_text="I didn").wait_for()
        assert _said(c) == ["I didn’t hear any words. Try again closer to the microphone, or type."]
        assert c.page.locator("#shQ").input_value() == "my draft" and _status(c) == ""
        assert fake.to("POST", "/v1/book/show/heard") == []
        _no_cloud(fake)
        _clean(c)
    finally:
        c.close()


# ---- each reason the browser can't recognise speech, said plainly; typing always works -------------
ERRORS = [
    (
        "not-allowed",
        "blocked",
    ),  # the microphone blocked: the shared Chrome / Windows / Android steps
    ("service-not-allowed", "rec_refused"),
    ("network", "rec_network"),
    ("language-not-supported", "rec_language"),
    ("aborted", "rec_stopped"),
    ("audio-capture", "no_mic"),
    ("bad-grammar", "failed"),  # anything else: the shared "didn't start" words
]


@pytest.mark.parametrize(("error", "code"), ERRORS, ids=[e for e, _ in ERRORS])
def test_each_recogniser_error_is_said_and_the_box_still_works(
    browser: Any, server_url: str, token: str, error: str, code: str
) -> None:
    c, fake = _questions(browser, server_url, token)  # a guest: never pointed to the switch
    try:
        _listen(c)
        c.page.evaluate(f"window.__recs[0].fail({error!r})")
        words = _words(c, code)
        c.page.locator("#shThread .sys", has_text=words[:30]).wait_for()
        (said,) = _said(c)
        assert said.startswith(words) and TO_CLOUD not in said
        assert "type your question" in said.lower()  # decision 4: every failure offers typing
        assert c.page.locator("#shMic").get_attribute("aria-pressed") == "false"
        assert fake.to("POST", "/v1/book/show/heard") == []
        _no_cloud(fake)
        _typing_still_works(c, fake)
        _clean(c)
    finally:
        c.close()


START_THROWS = "window.SpeechRecognition.prototype.start = function () { throw new DOMException('no', 'InvalidStateError'); };"


def test_a_recogniser_that_wont_start_says_so_and_offers_typing(
    browser: Any, server_url: str, token: str
) -> None:
    c, fake = _questions(browser, server_url, token, START_THROWS)
    try:
        c.page.locator("#shMic").click()
        words = _words(c, "failed")
        c.page.locator("#shThread .sys", has_text=words[:30]).wait_for()
        (said,) = _said(c)
        assert said.startswith(words) and "type your question" in said.lower()
        assert c.page.locator("#shMic").get_attribute("aria-pressed") == "false"
        _no_cloud(fake)
        _typing_still_works(c, fake)
        _clean(c)
    finally:
        c.close()


@pytest.mark.parametrize(
    ("error", "code"), [("network", "rec_network"), ("not-allowed", "blocked")]
)
def test_the_owner_alone_is_pointed_to_the_switch_and_nothing_switches_by_itself(
    browser: Any, server_url: str, token: str, error: str, code: str
) -> None:
    c, fake = _questions(browser, server_url, token, audience="owner")
    try:
        _listen(c)
        c.page.evaluate(f"window.__recs[0].fail({error!r})")
        c.page.locator("#shThread .sys").first.wait_for()
        (said,) = _said(c)
        assert said.startswith(_words(c, code))
        assert (TO_CLOUD in said) is code.startswith(
            "rec_"
        )  # a blocked mic: the cloud needs it too
        c.page.locator("#shMic").click()  # tapped again: still the browser's own recogniser
        c.page.wait_for_function("() => window.__recs.length === 2")
        assert (
            fake.to("PUT", "/v1/book/settings") == []
            and fake.to("POST", "/v1/book/show/hear") == []
        )
        _clean(c)
    finally:
        c.close()


@pytest.mark.parametrize("audience", ["guest", "owner"])
def test_a_browser_that_cant_recognise_speech_says_so_and_offers_typing(
    browser: Any, server_url: str, token: str, audience: str
) -> None:
    c, fake = _questions(browser, server_url, token, NO_SR, audience=audience)
    try:
        mic = c.page.locator("#shMic")
        assert mic.is_visible() and mic.is_disabled()
        line = _status(c)
        assert line.startswith(_words(c, "rec_unsupported")) and "Type your question" in line
        assert (TO_CLOUD in line) is (audience == "owner")
        _typing_still_works(c, fake)
        _no_cloud(fake)
        _clean(c)
    finally:
        c.close()


# ---- "Mic off": no recogniser is even built; a lock while listening aborts it -----------------------
def test_mic_off_builds_no_recogniser(browser: Any, server_url: str, token: str) -> None:
    c, fake = _questions(browser, server_url, token, LOCKED)
    try:
        assert "switched off on this device" in _status(c)
        c.page.locator("#shMic").click()
        assert c.page.evaluate("window.__recs.length") == 0
        assert c.page.locator("#shMicOn").is_hidden()  # a guest's show: no way back (H1)
        _typing_still_works(c, fake)
        _clean(c)
    finally:
        c.close()


def test_mic_off_set_while_the_browser_listens_aborts_it_and_sends_nothing(
    browser: Any, server_url: str, token: str
) -> None:
    c, fake = _questions(browser, server_url, token, audience="owner")
    try:
        _listen(c)
        c.page.evaluate(f"window.__recs[0].say({SAID!r}); window.JarvisAudio.lock('button')")
        c.page.wait_for_function(PRESSED.format("false"))
        assert c.page.evaluate("window.__recs[0].aborted") is True
        assert "switched off" in _status(c) and c.page.locator("#shMicOn").is_visible()
        c.page.wait_for_timeout(400)
        assert (
            fake.to("POST", "/v1/book/show/heard") == []
            and c.page.locator("#shQ").input_value() == ""
        )
        _clean(c)
    finally:
        c.close()


def test_a_typed_question_while_the_browser_listens_drops_what_it_heard(
    browser: Any, server_url: str, token: str
) -> None:
    c, fake = _questions(browser, server_url, token)
    try:
        _listen(c)
        c.page.evaluate("window.__recs[0].say('words the owner did not want')")
        c.page.locator("#shQ").fill("How is the vault built?")
        c.page.locator("#shQ").press("Enter")
        c.page.locator("#shThread .row.user .bubble", has_text="How is the vault built?").wait_for()
        assert c.page.evaluate("window.__recs[0].aborted") is True
        assert c.page.locator("#shMic").get_attribute("aria-pressed") == "false"
        c.page.wait_for_function("() => !document.getElementById('shQ').disabled")
        c.page.locator("#shQ").fill("my next typed draft")
        c.page.wait_for_timeout(400)
        assert c.page.locator("#shQ").input_value() == "my next typed draft"
        assert fake.to("POST", "/v1/book/show/heard") == []
        _clean(c)
    finally:
        c.close()


# ---- Book settings: the owner's switch asks first, with the cost, and says what the browser sends ---
def _settings(browser: Any, url: str, token: str) -> tuple[Console, FakeBook]:
    c = Console(browser, url, token, DESKTOP)
    fake = FakeBook(c.page)
    c.open()
    c.page.evaluate(PASSKEY_STUB)
    c.open_panel("book")
    c.page.locator("#p-book .bk-release").wait_for()
    c.page.locator("#p-book .bk-set .dsc").click()
    c.page.locator("#bkListen").wait_for()
    return c, fake


@pytest.mark.parametrize(
    ("select", "field", "cost"),
    [("#bkListen", "listening", "a minute"), ("#bkVoice", "show_voice", "a tour")],
)
def test_a_switch_to_the_cloud_asks_first_with_its_cost(
    browser: Any, server_url: str, token: str, select: str, field: str, cost: str
) -> None:
    c, fake = _settings(browser, server_url, token)
    try:
        sel = c.page.locator(select)
        assert sel.input_value() == "browser"  # Rs 0 by default
        assert sel.locator("option").all_text_contents() == ["Browser (free)", "Cloud (₹)"]
        sel.select_option("cloud")
        dialog = c.page.locator("dialog.bdialog[open]")
        dialog.wait_for()
        assert "free Google allowance first" in dialog.inner_text() and cost in dialog.inner_text()
        assert "₹" in dialog.inner_text()
        assert "stops at the free allowance and is never charged" in dialog.inner_text()
        dialog.get_by_role("button", name="Keep it free").click()
        assert sel.input_value() == "browser" and fake.to("PUT", "/v1/book/settings") == []
        sel.select_option("cloud")
        c.page.locator("dialog.bdialog[open]").get_by_role("button", name="Use the cloud").click()
        c.page.locator("#p-book .bk-setnote", has_text="Saved").wait_for()
        (put,) = fake.to("PUT", "/v1/book/settings")
        assert put["body"] == {field: "cloud", "confirm_cost": True}
        assert c.page.locator(select).input_value() == "cloud"
        c.page.locator(select).select_option("browser")  # back to free: no question asked
        for _ in range(40):
            if len(fake.to("PUT", "/v1/book/settings")) == 2:
                break
            c.page.wait_for_timeout(50)
        assert fake.to("PUT", "/v1/book/settings")[-1]["body"] == {field: "browser"}
        assert c.page.locator("dialog.bdialog[open]").count() == 0
        _clean(c)
    finally:
        c.close()


def test_the_listening_row_says_what_the_browser_sends(
    browser: Any, server_url: str, token: str
) -> None:
    c, _ = _settings(browser, server_url, token)
    try:
        row = c.page.locator("#p-book .bopt", has=c.page.locator("#bkListen"))
        text = row.inner_text()
        assert "free" in text and "Chrome may send your audio to Google" in text
        assert "unless it listens on the device" in text
        _clean(c)
    finally:
        c.close()
