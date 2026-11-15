# tests/browser/test_r62_book_mic.py -- R6.2 Part 1 (Phase A findings 4.2-4.5): "Ask by voice" in the
# build book's show, with Chromium's own fake microphone (--use-fake-device-for-media-stream) and
# injected getUserMedia / worklet / audio failures, against the Contract stubbed by FakeBook. The 20
# cases of 4.2 as tests: one tap listens, a second stops; the status line says Listening, Processing,
# Done; the words land in the box and are never sent by themselves; every failure has its own words
# (the shared R5 table, JarvisAudio.words, or the server's Book wording) and the typed box always
# still works; "Mic off" is shown, and only a real tap (isTrusted) switches it back on.
# ruff: noqa: E501 -- JavaScript strings
from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest
from book_mocks import HEARD, FakeBook
from test_book_show import _begin, _clean, _show, _to_questions
from test_console import DESKTOP, Console
from test_voice import FakeVoice

from jarvis.buildbook import hear

_pw = pytest.importorskip("playwright.sync_api")

pytestmark = pytest.mark.browser

FAKE_MIC = ["--use-fake-ui-for-media-stream", "--use-fake-device-for-media-stream"]
OFFLINE = "Can’t reach JARVIS. Check your connection."
# every getUserMedia call, and what it gave
TRACE = """
window.__gum = [];
(() => {
  const md = navigator.mediaDevices;
  if (!md || !md.getUserMedia) return;
  const real = md.getUserMedia.bind(md);
  md.getUserMedia = async (c) => { try { const s = await real(c); window.__gum.push('ok'); return s; } catch (e) { window.__gum.push(e.name); throw e; } };
})();
"""
GUM_THROWS = """
(() => { const md = navigator.mediaDevices; if (!md) return;
  md.getUserMedia = async () => { window.__gum = (window.__gum || []).concat('%s'); throw new DOMException('refused', '%s'); };
})();
"""
WORKLET_FAILS = """
(() => { const W = window.AudioWorklet; if (!W) return;
  W.prototype.addModule = function () { return Promise.reject(new DOMException('Unable to load a worklet module.', 'AbortError')); };
})();
"""
NO_WORKLET_NODE = (
    "try { delete window.AudioWorkletNode; } catch (_) {} window.AudioWorkletNode = undefined;"
)
# the microphone opens, but the capture worklet's frames never arrive (audio that never starts;
# the narration's own audio context is untouched, so the show still reaches Questions)
NO_FRAMES = """
(() => { const N = window.AudioWorkletNode; if (!N) return;
  window.AudioWorkletNode = class extends N {
    constructor(...a) { super(...a); Object.defineProperty(this.port, 'onmessage', { configurable: true, get() { return null; }, set() {} }); }
  };
})();
"""
LOCKED = "if (!sessionStorage.getItem('__locked')) { sessionStorage.setItem('__locked', '1'); localStorage.setItem('jarvis_mic_off_v1', '1'); }"
# POST /v1/book/show/hear waits until the test lets it through (window.__hearRelease())
HOLD_HEAR = """
(() => {
  let open = null;
  const gate = new Promise((r) => { open = r; });
  window.__hearRelease = () => open();
  const f = window.fetch.bind(window);
  window.fetch = async (u, o) => { if (String(u).includes('/v1/book/show/hear')) await gate; return f(u, o); };
})();
"""
PRESSED = "() => document.getElementById('shMic').getAttribute('aria-pressed') === '{}'"


@pytest.fixture(scope="module")
def browser() -> Iterator[Any]:
    with _pw.sync_playwright() as p:
        b = p.chromium.launch(args=FAKE_MIC)
        yield b
        b.close()


def _questions(
    browser: Any, url: str, token: str, *init: str, audience: str = "guest"
) -> tuple[Console, FakeBook]:
    c, fake = _show(browser, url, token, audience=audience, init=(TRACE, *init))
    _begin(c)
    _to_questions(c)
    return c, fake


def _status(c: Console) -> str:
    el = c.page.locator("#shHear")
    return "" if el.is_hidden() else str(el.text_content() or "")


def _said(c: Console) -> list[str]:
    return list(
        c.page.evaluate(
            "[...document.querySelectorAll('#shThread .sys')].map((n) => n.textContent)"
        )
    )


def _audio_words(c: Console, code: str) -> str:
    return str(c.page.evaluate(f"window.JarvisAudio.words('{code}')"))


def _record(c: Console, ms: int = 600) -> None:
    """One tap listens, a second tap stops (and sends what was said)."""
    mic = c.page.locator("#shMic")
    mic.click()
    c.page.wait_for_function(PRESSED.format("true"))
    c.page.wait_for_timeout(ms)  # a few 80 ms frames of the fake microphone
    mic.click()
    c.page.wait_for_function(PRESSED.format("false"))


def _typing_still_works(c: Console, fake: FakeBook) -> None:
    """The typed box is usable after any failure: a typed question goes out."""
    c.page.wait_for_function("() => !document.getElementById('shQ').disabled")
    before = len(fake.to("POST", "/v1/book/show/ask"))
    c.page.locator("#shQ").fill("How is the vault built?")
    c.page.locator("#shSend").click()
    c.page.locator("#shThread .row.user .bubble", has_text="How is the vault built?").wait_for()
    for _ in range(100):  # the row shows before the request reaches the stub: wait for it
        if len(fake.to("POST", "/v1/book/show/ask")) == before + 1:
            break
        c.page.wait_for_timeout(50)
    assert len(fake.to("POST", "/v1/book/show/ask")) == before + 1


def _wait_said(c: Console, text: str) -> None:
    c.page.locator("#shThread .sys", has_text=text[:40]).first.wait_for()
    assert text in _said(c), (text, _said(c))


# ---- 1: granted -------------------------------------------------------------------------------------
def test_one_tap_listens_a_second_stops_and_the_words_land_in_the_box_unsent(
    browser: Any, server_url: str, token: str
) -> None:
    c, fake = _questions(browser, server_url, token, HOLD_HEAR)
    try:
        mic = c.page.locator("#shMic")
        assert mic.is_visible() and mic.is_enabled()
        mic.click()
        c.page.wait_for_function(PRESSED.format("true"))
        assert "Listening" in _status(c)
        c.page.wait_for_timeout(700)
        mic.click()
        c.page.wait_for_function(PRESSED.format("false"))
        c.page.wait_for_function(
            "() => document.getElementById('shHear').textContent.startsWith('Processing')"
        )
        c.page.evaluate("window.__hearRelease()")
        c.page.wait_for_function(
            "() => document.getElementById('shHear').textContent.startsWith('Done')"
        )
        assert c.page.locator("#shQ").input_value() == HEARD
        assert "Ask" in _status(c)
        (sent,) = fake.to("POST", "/v1/book/show/hear")
        assert (
            isinstance(sent["body"], bytes)
            and sent["body"][:4] == b"RIFF"
            and len(sent["body"]) > 44 + 2 * 1280
        )
        assert sent["headers"]["content-type"] == "audio/wav"
        c.page.wait_for_timeout(500)
        assert fake.to("POST", "/v1/book/show/ask") == []  # never sent by itself
        assert c.page.evaluate("window.__gum") == ["ok"] and _said(c) == []
        _clean(c)
    finally:
        c.close()


def test_heard_and_understood_as_when_the_free_rules_changed_the_words(
    browser: Any, server_url: str, token: str
) -> None:
    c, fake = _questions(browser, server_url, token)
    fake.hear_answers = [
        (
            200,
            {
                "text": "JARVIS how does the calendar work",
                "heard": "javis how does the calender work",
                "changed": True,
                "no_speech": False,
            },
        )
    ]
    try:
        _record(c)
        c.page.wait_for_function(
            "() => document.getElementById('shHear').textContent.startsWith('Done')"
        )
        assert c.page.locator("#shQ").input_value() == "JARVIS how does the calendar work"
        assert "javis how does the calender work" in _status(c)  # what was heard, shown beside it
        _clean(c)
    finally:
        c.close()


def test_the_owner_is_told_when_a_spoken_question_was_charged(
    browser: Any, server_url: str, token: str
) -> None:
    c, fake = _questions(browser, server_url, token, audience="owner")
    fake.hear_answers = [
        (
            200,
            {"text": HEARD, "heard": HEARD, "changed": False, "no_speech": False, "charged": True},
        )
    ]
    try:
        _record(c)
        c.page.wait_for_function(
            "() => document.getElementById('shHear').textContent.startsWith('Done')"
        )
        assert "free listening minutes" in _status(c) and "charged" in _status(c)
        _clean(c)
    finally:
        c.close()


# ---- 2-4b: the microphone refuses -----------------------------------------------------------------
@pytest.mark.parametrize(
    ("name", "code"),
    [
        ("NotAllowedError", "blocked"),  # 2e: Chrome's Block (and Windows' switch)
        ("NotSupportedError", "failed"),  # 2: what headless Chromium says for a denial
        ("NotFoundError", "no_mic"),
        ("NotReadableError", "busy"),
    ],
)
def test_a_microphone_that_refuses_says_why(
    browser: Any, server_url: str, token: str, name: str, code: str
) -> None:
    c, fake = _questions(browser, server_url, token, GUM_THROWS % (name, name))
    try:
        c.page.locator("#shMic").click()
        words = _audio_words(c, code)
        _wait_said(c, words)
        if code == "blocked":  # how to allow it, in Chrome on Windows and on Android
            assert "Chrome" in words and "Windows" in words and "Android" in words
        assert c.page.locator("#shMic").get_attribute("aria-pressed") == "false"
        assert fake.to("POST", "/v1/book/show/hear") == [] and _status(c) == ""
        _typing_still_works(c, fake)
        _clean(c)
    finally:
        c.close()


def test_a_capture_part_that_fails_to_load_says_so(
    browser: Any, server_url: str, token: str
) -> None:
    c, fake = _questions(browser, server_url, token, WORKLET_FAILS)
    try:
        c.page.locator("#shMic").click()
        _wait_said(c, _audio_words(c, "failed"))
        assert fake.to("POST", "/v1/book/show/hear") == []
        _typing_still_works(c, fake)
        _clean(c)
    finally:
        c.close()


# ---- 6: an old browser --------------------------------------------------------------------------------
def test_an_unsupported_browser_keeps_the_button_disabled_with_the_reason(
    browser: Any, server_url: str, token: str
) -> None:
    c, fake = _questions(browser, server_url, token, NO_WORKLET_NODE)
    try:
        mic = c.page.locator("#shMic")
        assert mic.is_visible() and mic.is_disabled()  # not hidden any more (H4)
        assert _status(c) == _audio_words(c, "unsupported")
        assert mic.get_attribute("aria-describedby") == "shHear"
        _typing_still_works(c, fake)
        assert mic.is_disabled()  # it stays so after a question
        _clean(c)
    finally:
        c.close()


# ---- 3: "Mic off" -------------------------------------------------------------------------------------
def test_mic_off_is_shown_and_only_a_real_tap_switches_it_on(
    browser: Any, server_url: str, token: str
) -> None:
    c, fake = _questions(browser, server_url, token, LOCKED)
    try:
        on = c.page.locator("#shMicOn")
        assert "switched off" in _status(c) and on.is_visible()
        c.page.locator("#shMic").click()  # the locked mic: nothing opens, the way back is offered
        assert c.page.evaluate("window.__gum") == []
        assert c.page.evaluate("document.activeElement.id") == "shMicOn"
        c.page.evaluate("document.getElementById('shMicOn').click()")  # a script: never
        c.page.evaluate(
            "document.getElementById('shMicOn').dispatchEvent(new MouseEvent('click', {bubbles: true}))"
        )
        assert c.page.evaluate("window.JarvisAudio.locked()") is True and on.is_visible()
        on.click()  # his tap
        assert c.page.evaluate("window.JarvisAudio.locked()") is False
        assert c.page.evaluate("localStorage.getItem('jarvis_mic_off_v1')") is None
        assert (
            on.is_hidden() and c.page.evaluate("window.__gum") == []
        )  # switching on never listens
        _record(c)
        c.page.wait_for_function(f"() => document.getElementById('shQ').value === {HEARD!r}")
        assert len(fake.to("POST", "/v1/book/show/hear")) == 1
        _clean(c)
    finally:
        c.close()


def test_mic_off_set_while_listening_stops_and_sends_nothing(
    browser: Any, server_url: str, token: str
) -> None:
    c, fake = _questions(browser, server_url, token)
    try:
        c.page.locator("#shMic").click()
        c.page.wait_for_function(PRESSED.format("true"))
        c.page.evaluate(
            "window.JarvisAudio.lock('button')"
        )  # "mic off" said elsewhere in this browser
        c.page.wait_for_function(PRESSED.format("false"))
        assert "switched off" in _status(c) and c.page.locator("#shMicOn").is_visible()
        c.page.wait_for_timeout(500)
        assert fake.to("POST", "/v1/book/show/hear") == []
        _typing_still_works(c, fake)
        _clean(c)
    finally:
        c.close()


def test_mic_off_offers_no_way_back_once_the_questions_run_out(
    browser: Any, server_url: str, token: str
) -> None:
    c, fake = _questions(browser, server_url, token, LOCKED)
    fake.ask_answers = [FakeBook.reply(left=0)]  # the session's last question
    try:
        on = c.page.locator("#shMicOn")
        assert on.is_visible()
        c.page.locator("#shQ").fill("How is the vault built?")
        c.page.locator("#shSend").click()
        c.page.wait_for_function(
            "() => document.getElementById('shLeft').textContent === '0 questions left'"
        )
        assert on.is_hidden()  # nothing left to ask: no button beside "No more questions"
        assert c.page.locator("#shFinish").is_visible()
        assert c.page.evaluate("window.JarvisAudio.locked()") is True  # still off: untouched
        _clean(c)
    finally:
        c.close()


# ---- 5c, 9c: the microphone opens but sends no sound ----------------------------------------------------
def test_a_microphone_that_sends_no_sound_says_so(
    browser: Any, server_url: str, token: str
) -> None:
    c, fake = _questions(browser, server_url, token, NO_FRAMES)
    try:
        c.page.locator("#shMic").click()
        _wait_said(c, _audio_words(c, "silent"))  # after 1.5 s without one frame
        assert c.page.locator("#shMic").get_attribute("aria-pressed") == "false"
        assert fake.to("POST", "/v1/book/show/hear") == []
        _typing_still_works(c, fake)
        _clean(c)
    finally:
        c.close()


def test_a_tap_tap_at_once_is_too_short_and_says_so(
    browser: Any, server_url: str, token: str
) -> None:
    c, fake = _questions(browser, server_url, token, NO_FRAMES)
    try:
        mic = c.page.locator("#shMic")
        mic.click()
        c.page.wait_for_function(PRESSED.format("true"))
        mic.click()  # at once: no frame yet
        _wait_said(c, "That was too short to hear anything. Tap the mic, speak, then tap it again.")
        assert fake.to("POST", "/v1/book/show/hear") == []
        _typing_still_works(c, fake)
        _clean(c)
    finally:
        c.close()


# ---- 7-9b: the server's answers, in the Book's own words ------------------------------------------------
def _unavailable(reason: str, why: str | None = None) -> tuple[int, dict[str, Any]]:
    return 503, {
        "error": "voice_unavailable",
        "detail": hear.words(why or reason, owner=False),
        "reason": reason,
    }


SERVER = [
    _unavailable("not_configured"),
    _unavailable("api_disabled"),
    _unavailable("upstream_error"),
    _unavailable("timeout"),
    _unavailable("budget_unreadable"),
    _unavailable("budget", "session_budget"),
    (402, {"error": "budget_reached", "detail": hear.words("budget_reached", owner=False)}),
    (429, {"error": "voice_busy", "detail": hear.words("busy", owner=False)}),
    (422, {"error": "bad_audio", "detail": "That recording is too short to hear anything."}),
    (422, {"error": "input_rejected", "detail": hear.words("rejected", owner=False)}),
]


@pytest.mark.parametrize(
    ("status", "body"), SERVER, ids=[f"{s}-{b.get('reason', b['error'])}" for s, b in SERVER]
)
def test_each_server_answer_is_said_and_the_box_still_works(
    browser: Any, server_url: str, token: str, status: int, body: dict[str, Any]
) -> None:
    c, fake = _questions(browser, server_url, token)
    fake.hear_answers = [(status, body)]
    try:
        _record(c)
        _wait_said(c, body["detail"])
        assert _status(c) == "" and c.page.locator("#shQ").input_value() == ""
        _typing_still_works(c, fake)
        _clean(c, status)
    finally:
        c.close()


def test_a_server_answer_without_words_gets_the_books_own(
    browser: Any, server_url: str, token: str
) -> None:
    c, fake = _questions(browser, server_url, token)
    fake.hear_answers = [(503, {"error": "voice_unavailable", "reason": "upstream_error"})]
    try:
        _record(c)
        _wait_said(c, "I didn’t catch that. Type the question instead.")
        _clean(c, 503)
    finally:
        c.close()


def test_nothing_heard_says_so_and_keeps_what_was_typed(
    browser: Any, server_url: str, token: str
) -> None:
    c, fake = _questions(browser, server_url, token)
    fake.hear_answers = [(200, {"text": "", "heard": "", "changed": False, "no_speech": True})]
    try:
        c.page.locator("#shQ").fill("my draft")
        _record(c)
        _wait_said(c, "I didn’t hear any words. Try again closer to the microphone, or type.")
        assert c.page.locator("#shQ").input_value() == "my draft" and _status(c) == ""
        _clean(c)
    finally:
        c.close()


def test_a_dropped_connection_is_said_calmly(browser: Any, server_url: str, token: str) -> None:
    c, fake = _questions(browser, server_url, token)
    fake.hear_answers = ["abort"]
    try:
        _record(c)
        _wait_said(c, OFFLINE)
        _typing_still_works(c, fake)
        _clean(c, "net::ERR_FAILED")
    finally:
        c.close()


# ---- the shared R5 words: the console says the same ---------------------------------------------------
def test_the_console_reads_the_same_words_for_a_blocked_microphone(
    browser: Any, server_url: str, token: str
) -> None:
    c = Console(browser, server_url, token, DESKTOP)
    c.page.add_init_script(GUM_THROWS % ("NotAllowedError", "NotAllowedError"))
    FakeVoice(c.page)
    try:
        c.open()
        c.page.locator("#micBtn").click()
        help_ = c.page.locator("#micHelp")
        help_.wait_for(state="visible")
        assert help_.text_content() == _audio_words(c, "blocked")
        assert "tap the mic again" in str(help_.text_content())  # R5's words kept
        assert c.errors == []
    finally:
        c.close()
