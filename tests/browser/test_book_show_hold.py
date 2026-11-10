# tests/browser/test_book_show_hold.py -- R6 D14, D15 (docs/plans/r6-build-book.md): the show page's
# review fixes, against the Contract stubbed with page.route (book_mocks.FakeBook).
# Pause holds everything (a line whose audio is still coming, the 2D Core on a phone, the Core in
# Questions: WCAG 2.2.2); a microphone still starting never records after a cancel or the close; a
# spoken question lands in the box and a dropped connection is said calmly; a blip loading the show
# keeps the session (retries, then Try again); the focus stays in the show; a reply mid-show replays
# the line it cut; the close releases the 3D engine (contexts, frames, listeners, observers); and the
# 2D Core is the console's own.
# ruff: noqa: E501 -- JavaScript strings
from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest
from book_mocks import HEARD, SCENES, SPEECH_STUB, TOKEN, FakeBook, script
from test_book_show import (
    GL_SPY,
    QUICK,
    SEED,
    _begin,
    _clean,
    _need_3d,
    _show,
    _state,
    _to_questions,
)
from test_console import DESKTOP, PHONE, Console

_pw = pytest.importorskip("playwright.sync_api")

pytestmark = pytest.mark.browser

# The cloud voice answers 1.5 s late; every AudioBufferSourceNode.start is recorded.
SLOW_SPEAK = """
window.__starts = [];
(() => {
  const start = AudioBufferSourceNode.prototype.start;
  AudioBufferSourceNode.prototype.start = function (...a) { window.__starts.push(performance.now()); return start.apply(this, a); };
  const f = window.fetch.bind(window);
  window.fetch = async (u, o) => { if (String(u).includes('/v1/book/show/speak')) await new Promise((r) => setTimeout(r, 1500)); return f(u, o); };
})();
"""
# A microphone: a real audio track (an oscillator); with __gumHold the permission prompt waits.
GUM_STUB = """
window.__tracks = []; window.__gum = 0; window.__gumHold = false;
(() => {
  let open = null;
  const gate = new Promise((r) => { open = r; });
  window.__gumRelease = () => open();
  const gum = async () => {
    window.__gum += 1;
    if (window.__gumHold) await gate;
    const ctx = new AudioContext(), dst = ctx.createMediaStreamDestination(), osc = ctx.createOscillator();
    osc.connect(dst); osc.start();
    dst.stream.getTracks().forEach((t) => window.__tracks.push(t));
    return dst.stream;
  };
  Object.defineProperty(navigator, 'mediaDevices', { value: { getUserMedia: gum }, configurable: true });
})();
"""
# What the 3D engine leaves behind: DOM listeners it added and did not remove (or abort), and
# ResizeObservers it did not disconnect (found by the engine's module in the call stack).
ENGINE_SPY = """
window.__engine = {};
(() => {
  const from3d = () => String(new Error().stack || '').includes('console-book-3d');
  const cap = (o) => !!(o === true || (o && o.capture));
  const live = [], ros = [];
  const add = EventTarget.prototype.addEventListener, rem = EventTarget.prototype.removeEventListener;
  EventTarget.prototype.addEventListener = function (type, fn, o) {
    if (type !== 'abort' && from3d()) live.push({ t: this, type, fn, c: cap(o), signal: o && typeof o === 'object' ? o.signal || null : null });
    return add.call(this, type, fn, o);
  };
  EventTarget.prototype.removeEventListener = function (type, fn, o) {
    const i = live.findIndex((l) => l.t === this && l.type === type && l.fn === fn && l.c === cap(o));
    if (i >= 0) live.splice(i, 1);
    return rem.call(this, type, fn, o);
  };
  const RO = window.ResizeObserver;
  window.ResizeObserver = class extends RO {
    constructor(cb) { super(cb); this.off = false; if (from3d()) ros.push(this); }
    disconnect() { this.off = true; return super.disconnect(); }
  };
  window.__engine.listeners = () => live.filter((l) => !(l.signal && l.signal.aborted)).map((l) => l.type);
  window.__engine.observers = () => ros.filter((r) => !r.off).length;
})();
"""
# Infinite CSS animations running on the stage (the 2D Core's rings and glow).
SPINNING = """() => document.getAnimations().filter((a) => a.playState === 'running' && a.effect && a.effect.target
  && a.effect.target.closest && a.effect.target.closest('#shStage') && a.effect.getComputedTiming().iterations === Infinity).length"""
RUNNING_3D = "() => window.JarvisBook3D.stats().running"
OFFLINE = "Can’t reach JARVIS. Check your connection."


@pytest.fixture(scope="module")
def browser() -> Iterator[Any]:
    with _pw.sync_playwright() as p:
        b = p.chromium.launch()
        yield b
        b.close()


def _loading(browser: Any, url: str, token: str, fails: list[Any]) -> tuple[Console, FakeBook]:
    """The show page while GET /v1/book/show/script first fails as `fails` says."""
    c = Console(browser, url, token, DESKTOP)
    for js in (GL_SPY, SPEECH_STUB, SEED % (TOKEN, "guest")):
        c.page.add_init_script(js)
    fake = FakeBook(c.page)
    fake.script_answer = (200, script("guest", QUICK))
    fake.script_fails = list(fails)
    c.page.goto(url + "/book/show")
    return c, fake


def _spoken_ids(fake: FakeBook) -> list[str]:
    return [c["body"]["line_id"] for c in fake.to("POST", "/v1/book/show/speak")]


@pytest.mark.parametrize("voice", ["cloud", "browser"])
def test_pause_holds_a_line_whose_audio_is_still_coming(
    browser: Any, server_url: str, token: str, voice: str
) -> None:
    c, fake = _show(browser, server_url, token, scenes=SCENES, init=(SLOW_SPEAK,))
    if voice == "browser":
        fake.speak_status = 503  # the cloud voice is off: the browser voice takes the line
    try:
        _begin(c)
        c.page.keyboard.press("Space")  # the first line's audio is still on its way
        c.page.wait_for_function("() => !window.JarvisBookShow.state().playing")
        c.page.wait_for_timeout(2600)  # it has landed by now
        assert c.page.evaluate("window.__starts") == []
        assert c.page.evaluate("window.__spoken") == []
        assert _state(c)["index"] == 0
        c.page.keyboard.press("Space")
        c.page.wait_for_function("() => window.__starts.length + window.__spoken.length > 0")
        _clean(c, *([503] if voice == "browser" else []))
    finally:
        c.close()


def test_pause_holds_the_2d_core_on_a_phone(browser: Any, server_url: str, token: str) -> None:
    c, _ = _show(browser, server_url, token, PHONE, scenes=SCENES)
    try:
        c.page.keyboard.press("m")  # captions set the pace: the first scene stays a few seconds
        _begin(c)
        c.page.locator("#sh2d .sh2-core .core").wait_for()
        assert c.page.evaluate(SPINNING) > 0
        c.page.keyboard.press("Space")
        c.page.wait_for_function("() => !window.JarvisBookShow.state().playing")
        assert c.page.evaluate(SPINNING) == 0
        c.page.keyboard.press("Space")
        c.page.wait_for_function(f"() => ({SPINNING})() > 0")
        _clean(c)
    finally:
        c.close()


@pytest.mark.parametrize("renderer", ["3d", "2d"])
def test_play_holds_the_core_in_questions_too(
    browser: Any, server_url: str, token: str, renderer: str
) -> None:
    c, _ = _show(browser, server_url, token, scenes=SCENES, gl_fail=renderer == "2d")
    try:
        _begin(c)
        if renderer == "3d":
            _need_3d(c)
        _to_questions(c)
        c.page.wait_for_function("() => window.JarvisBookShow.state().phase === 'questions'")
        moving = RUNNING_3D if renderer == "3d" else SPINNING
        play = c.page.locator("#shPlay")
        assert c.page.evaluate(moving)  # the Core listens: it moves
        assert play.get_attribute("aria-pressed") == "true"
        play.click()
        assert not c.page.evaluate(moving)
        assert play.get_attribute("aria-pressed") == "false"
        assert _state(c)["phase"] == "questions"
        play.click()
        assert c.page.evaluate(moving)
        _clean(c)
    finally:
        c.close()


@pytest.mark.parametrize("how", ["back", "end"])
def test_a_mic_still_starting_never_records_after_a_cancel(
    browser: Any, server_url: str, token: str, how: str
) -> None:
    c, fake = _show(browser, server_url, token, scenes=SCENES, init=(GUM_STUB,))
    try:
        _begin(c)
        c.page.keyboard.press("q")
        c.page.locator("#shTalk").wait_for(state="visible")
        c.page.evaluate("window.__gumHold = true")  # the permission prompt is up
        c.page.locator("#shMic").click()
        c.page.wait_for_function("() => window.__gum === 1")
        if how == "back":
            c.page.locator("#shFinish").click()  # Back to the show
        else:
            c.page.locator("#shEnd").click()
            c.page.locator("#shEndYes").click()
            c.page.locator("#shDone").wait_for(state="visible")
        c.page.evaluate("window.__gumRelease()")
        c.page.wait_for_function("() => window.__tracks.length === 1")
        c.page.wait_for_timeout(800)  # the capture worklet would have loaded by now
        assert c.page.evaluate("window.__tracks.map((t) => t.readyState)") == ["ended"]
        assert c.page.evaluate("window.JarvisBookVoice.record.active()") is False
        assert c.page.locator("#shMic").get_attribute("aria-pressed") == "false"
        assert fake.to("POST", "/v1/book/show/hear") == []
        _clean(c)
    finally:
        c.close()


def test_a_spoken_question_lands_in_the_box_and_a_drop_is_said_calmly(
    browser: Any, server_url: str, token: str
) -> None:
    c, fake = _show(browser, server_url, token, init=(GUM_STUB,))
    fake.hear_answers = [(200, {"text": HEARD}), "abort"]
    pressed = "() => document.getElementById('shMic').getAttribute('aria-pressed') === '{}'"
    try:
        _begin(c)
        _to_questions(c)
        mic = c.page.locator("#shMic")
        for _ in range(2):
            mic.click()
            c.page.wait_for_function(pressed.format("true"))
            c.page.wait_for_timeout(500)  # a few 80 ms frames
            mic.click()  # stop and use what I said
            c.page.wait_for_function(pressed.format("false"))
            c.page.wait_for_function("() => !document.getElementById('shQ').disabled")
            if not fake.hear_answers:
                break
            assert c.page.locator("#shQ").input_value() == HEARD
        (first, _second) = fake.to("POST", "/v1/book/show/hear")
        assert first["headers"]["content-type"] == "audio/wav"
        assert first["headers"]["x-jarvis-book"] == TOKEN
        thread = c.page.locator("#shThread")
        thread.locator(".sys.error", has_text=OFFLINE).wait_for()
        assert "Failed to fetch" not in thread.inner_text()
        _clean(c, "net::ERR_FAILED")
    finally:
        c.close()


def test_the_focus_stays_in_the_show_when_the_questions_close(
    browser: Any, server_url: str, token: str
) -> None:
    c, _ = _show(browser, server_url, token, scenes=SCENES)
    try:
        _begin(c)
        c.page.keyboard.press("q")
        c.page.locator("#shTalk").wait_for(state="visible")
        c.page.locator("#shFinish").focus()
        c.page.keyboard.press("Enter")  # Back to the show
        c.page.locator("#shTalk").wait_for(state="hidden")
        assert c.page.evaluate("document.activeElement.id") == "shPlay"
        _clean(c)
    finally:
        c.close()


def test_a_reply_mid_show_then_play_replays_the_line_it_cut(
    browser: Any, server_url: str, token: str
) -> None:
    c, fake = _show(browser, server_url, token, scenes=SCENES)
    beats = [b["id"] for s in SCENES for b in s["beats"]]
    try:
        _begin(c)
        c.page.keyboard.press("q")  # pauses the show on its current line
        c.page.locator("#shTalk").wait_for(state="visible")
        cut = beats[_state(c)["index"]]
        c.page.locator("#shQ").fill("How are you built?")
        c.page.locator("#shSend").click()
        c.page.locator("#shThread .row.jarvis .bubble", has_text="Anything else").wait_for()
        c.page.wait_for_timeout(300)  # the follow-up line is spoken
        c.page.locator("#shFinish").click()  # Back to the show
        after: list[str] = []
        for _ in range(50):  # the next line the show asks the cloud voice for
            ids = _spoken_ids(fake)
            after = ids[ids.index("anything_else") + 1 :] if "anything_else" in ids else []
            if after:
                break
            c.page.wait_for_timeout(100)
        assert after and after[0] == cut, (cut, _spoken_ids(fake))
        _clean(c)
    finally:
        c.close()


def test_the_close_releases_the_3d_engine(browser: Any, server_url: str, token: str) -> None:
    c, _ = _show(browser, server_url, token, scenes=SCENES, init=(ENGINE_SPY,))
    try:
        _begin(c)
        _need_3d(c)
        assert c.page.evaluate("window.__engine.listeners().length") > 0  # the spy sees the engine
        assert c.page.evaluate("window.__engine.observers()") > 0
        c.page.locator("#shEnd").click()
        c.page.locator("#shEndYes").click()
        c.page.locator("#shDone").wait_for(state="visible")
        st = c.page.evaluate("window.JarvisBook3D.stats()")
        assert st["state"] == "closed" and st["running"] is False, st
        c.page.wait_for_function(
            "() => window.__glCtx.length > 0 && window.__glCtx.every((g) => g.isContextLost())"
        )
        assert c.page.evaluate("window.__engine.listeners()") == []
        assert c.page.evaluate("window.__engine.observers()") == 0
        before = c.page.evaluate("window.__raf")
        c.page.wait_for_timeout(1200)
        assert c.page.evaluate("window.__raf") - before <= 1  # no frame loop left
        _clean(c)
    finally:
        c.close()


def test_a_blip_loading_the_show_is_retried_and_keeps_the_session(
    browser: Any, server_url: str, token: str
) -> None:
    c, fake = _loading(browser, server_url, token, [503, "abort"])
    try:
        c.page.locator("#shBegin").wait_for(timeout=10000)
        assert len(fake.to("GET", "/v1/book/show/script")) == 3
        assert c.page.evaluate("sessionStorage.getItem('jarvis_book_token')") == TOKEN
        assert c.page.locator("#shDone").is_hidden()
        _clean(c, 503, "net::ERR_FAILED")
    finally:
        c.close()


def test_a_connection_still_down_keeps_the_session_and_offers_try_again(
    browser: Any, server_url: str, token: str
) -> None:
    c, fake = _loading(browser, server_url, token, ["abort"] * 3)
    try:
        done = c.page.locator("#shDone")
        done.wait_for(state="visible", timeout=10000)
        assert OFFLINE in done.inner_text()
        assert "Failed to fetch" not in c.page.locator("body").inner_text()
        assert c.page.evaluate("sessionStorage.getItem('jarvis_book_token')") == TOKEN
        assert fake.to("POST", "/v1/book/close") == []
        done.get_by_role("button", name="Try again").click()
        c.page.locator("#shBegin").wait_for()
        assert done.is_hidden()
        _begin(c)
        _clean(c, "net::ERR_FAILED")
    finally:
        c.close()


def test_the_2d_core_is_the_consoles_own(browser: Any, server_url: str, token: str) -> None:
    c, _ = _show(browser, server_url, token)
    try:
        mine, console = c.page.evaluate(
            """() => {
              const shape = (root) => [...root.querySelectorAll('svg *')].map((n) => n.localName + '.' + (n.getAttribute('class') || ''));
              const doc = new DOMParser().parseFromString(window.JarvisFX.core('lg'), 'text/html');
              return [shape(document.querySelector('#shStart .sh-emblem')), shape(doc.body)];
            }"""
        )
        assert mine == console
        _clean(c)
    finally:
        c.close()
