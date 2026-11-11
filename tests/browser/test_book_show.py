# tests/browser/test_book_show.py -- R6 D9, D13-D15 (docs/plans/r6-build-book.md): the show page
# (/book/show) against the Contract stubbed with page.route (book_mocks.FakeBook). Beats advance in
# order with stubbed audio, every book call carries X-Jarvis-Book, captions-only timing when the
# sound is off, the browser voice when the cloud voice is unavailable, the keys, reduced motion runs
# no animation loop, a phone and a WebGL failure get the 2D show with no GL context, the 3D show
# keeps its budget, questions get a reply and a follow-up, the closing lines come in order, and
# after the close the page holds no DOM text, token or audio (the guest sees the hand-back and Resume).
# ruff: noqa: E501 -- JavaScript strings
from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest
from book_mocks import LINES, LOCK_ID, SCENES, SPEECH_STUB, TOKEN, FakeBook, google_mode, script
from test_console import DESKTOP, PHONE, Console

_pw = pytest.importorskip("playwright.sync_api")

pytestmark = pytest.mark.browser

# Every WebGL context the page asks for (and, with __glFail, a GPU that gives none), every
# requestAnimationFrame, and every console.warn (a 3D layer that fails says so there).
GL_SPY = """
window.__gl = []; window.__glCtx = []; window.__warns = [];
(() => {
  const orig = HTMLCanvasElement.prototype.getContext;
  HTMLCanvasElement.prototype.getContext = function (type, ...rest) {
    if (/webgl/.test(String(type))) { window.__gl.push(String(type)); if (window.__glFail) return null; }
    const ctx = orig.call(this, type, ...rest);
    if (ctx && /webgl/.test(String(type))) window.__glCtx.push(ctx);
    return ctx;
  };
  const warn = console.warn.bind(console);
  console.warn = (...a) => { window.__warns.push(a.map(String).join(' ')); warn(...a); };
  window.__raf = 0;
  const raf = window.requestAnimationFrame.bind(window);
  window.requestAnimationFrame = (cb) => { window.__raf += 1; return raf(cb); };
})();
"""
SEED = """
if (!sessionStorage.getItem('__seeded')) {
  sessionStorage.setItem('__seeded', '1');
  sessionStorage.setItem('jarvis_book_token', '%s');
  sessionStorage.setItem('jarvis_book_session', JSON.stringify({ audience: '%s', session_id: 'bk_0123456789abcdef' }));
}
"""
STATE = "() => window.JarvisBookShow && window.JarvisBookShow.state()"
QUICK = [  # one or two short beats a scene: the whole show runs in a few seconds
    {**s, "beats": [{**b, "text": " ".join(b["text"].split()[:2])} for b in s["beats"]]}
    for s in SCENES
]


@pytest.fixture(scope="module")
def browser() -> Iterator[Any]:
    with _pw.sync_playwright() as p:
        b = p.chromium.launch()
        yield b
        b.close()


def _show(
    browser: Any,
    url: str,
    token: str,
    viewport: dict[str, int] = DESKTOP,
    *,
    audience: str = "guest",
    reduced: bool = False,
    gl_fail: bool = False,
    scenes: list[dict[str, Any]] | None = None,
    google: bool = False,
    init: tuple[str, ...] = (),
) -> tuple[Console, FakeBook]:
    c = Console(browser, url, token, viewport)
    for script_js in init:
        c.page.add_init_script(script_js)
    if reduced:
        c.page.emulate_media(reduced_motion="reduce")
    if gl_fail:
        c.page.add_init_script("window.__glFail = true;")
    c.page.add_init_script(GL_SPY)
    c.page.add_init_script(SPEECH_STUB)
    c.page.add_init_script(SEED % (TOKEN, audience))
    fake = FakeBook(c.page)
    fake.script_answer = (200, script(audience, QUICK if scenes is None else scenes))
    if google:  # a guest show runs in Google mode: its lock stays on after the close
        google_mode(c.page)
    c.page.goto(url + "/book/show")
    c.page.locator("#shBegin").wait_for()
    return c, fake


def _begin(c: Console) -> None:
    c.page.locator("#shBegin").click()
    c.page.wait_for_function("() => { const s = window.JarvisBookShow.state(); return s.playing; }")


def _state(c: Console) -> dict[str, Any]:
    return dict(c.page.evaluate(STATE))


def _to_questions(c: Console) -> None:
    c.page.locator("#shChapters").click()
    c.page.locator("#shChapterList button", has_text="Questions").click()
    c.page.locator("#shTalk").wait_for(state="visible")


def _clean(c: Console, *expected: int | str) -> None:
    """No JS error, no CSP violation, no 3D layer that failed quietly. `expected`: a status the test
    asked for (the browser logs it), or a network error text such as "net::ERR_FAILED"."""
    said = [f"status of {code} " if isinstance(code, int) else code for code in expected]
    errors = [e for e in c.errors if not any(s in e for s in said)]
    assert errors == [] and c.csp_violations() == []
    warns = c.page.evaluate("window.__warns || []")
    assert [w for w in warns if "Build book 3D" in w] == []


def _need_3d(c: Console) -> None:
    """The 3D show must be on. Only a Chromium without WebGL2 may skip; a 3D layer that failed to
    load or to start fails the test (it never hides behind the 2D show)."""
    if _state(c)["renderer"] == "3d":
        return
    st = c.page.evaluate("window.JarvisBook3D ? window.JarvisBook3D.stats() : {state: 'missing'}")
    assert st["state"] == "no-webgl2", st
    pytest.skip("this Chromium has no WebGL2: the 2D show is covered elsewhere")


def _spoken_ids(fake: FakeBook) -> list[str]:
    return [c["body"]["line_id"] for c in fake.to("POST", "/v1/book/show/speak")]


def test_the_beats_play_in_order_and_every_call_carries_the_token(
    browser: Any, server_url: str, token: str
) -> None:
    c, fake = _show(browser, server_url, token)
    try:
        assert "R6" in c.page.locator("#shStart").inner_text()
        _begin(c)
        c.page.locator("#shTalk").wait_for(state="visible", timeout=30000)
        want = [b["id"] for s in QUICK for b in s["beats"]] + ["ask"]
        ids = list(dict.fromkeys(_spoken_ids(fake)))  # a prefetch asks once, ahead of time
        assert ids == want
        assert c.page.locator("#shCapText").inner_text() == LINES["ask"]
        for call in fake.calls:
            if call["path"].startswith("/v1/book/show/"):
                assert call["headers"].get("x-jarvis-book") == TOKEN, call["path"]
        _clean(c)
    finally:
        c.close()


def test_with_the_sound_off_captions_set_the_pace(
    browser: Any, server_url: str, token: str
) -> None:
    c, fake = _show(browser, server_url, token)
    try:
        c.page.keyboard.press("m")
        assert c.page.locator("#shSound").get_attribute("aria-pressed") == "false"
        c.page.evaluate(
            "() => { window.__caps = []; new MutationObserver(() => window.__caps.push([performance.now(),"
            " document.getElementById('shCapText').textContent])).observe(document.getElementById('shCapText'),"
            " { childList: true, characterData: true, subtree: true }); }"
        )
        _begin(c)
        first, second = (b["text"] for b in QUICK[0]["beats"][:2])
        c.page.locator("#shCapText", has_text=second).wait_for(timeout=5000)
        caps = c.page.evaluate("window.__caps")
        texts = [t for _, t in caps]
        assert texts[:2] == [first, second], texts
        # captions only: 330 ms a word + 800 ms (two words: 1.46 s), and no audio fetched
        assert caps[1][0] - caps[0][0] >= 1300, caps
        assert _spoken_ids(fake) == []
        _clean(c)
    finally:
        c.close()


# A browser whose speech fails at once ("synthesis-failed"; no voice installed, as headless Chromium).
FAILING_SPEECH = """
(() => {
  const synth = { speaking: false, pending: false, paused: false,
    speak(u) { setTimeout(() => u.onerror && u.onerror({ error: 'synthesis-failed' }), 5); },
    cancel() {}, pause() {}, resume() {}, getVoices() { return []; } };
  try { Object.defineProperty(window, 'speechSynthesis', { value: synth, configurable: true }); } catch (_) {}
})();
"""


def test_a_browser_voice_that_fails_at_once_leaves_the_pace_to_the_captions(
    browser: Any, server_url: str, token: str
) -> None:
    """I1 (seen on the real server in headless Chromium): an utterance that errors before it
    starts must not end its line at once, or the show races to Questions in a second."""
    c, fake = _show(browser, server_url, token, init=())
    c.page.add_init_script(FAILING_SPEECH)
    c.page.reload()
    c.page.locator("#shBegin").wait_for()
    fake.speak_status = 503  # no cloud voice: the browser's, which fails
    try:
        c.page.evaluate(
            "() => { window.__caps = []; new MutationObserver(() => window.__caps.push([performance.now(),"
            " document.getElementById('shCapText').textContent])).observe(document.getElementById('shCapText'),"
            " { childList: true, characterData: true, subtree: true }); }"
        )
        _begin(c)
        first, second = (b["text"] for b in QUICK[0]["beats"][:2])
        c.page.locator("#shCapText", has_text=second).wait_for(timeout=8000)
        caps = c.page.evaluate("window.__caps")
        assert [t for _, t in caps][:2] == [first, second]
        assert caps[1][0] - caps[0][0] >= 1300, caps  # the captions' pace, not at once
        _clean(c, 503)
    finally:
        c.close()


def test_the_browser_voice_takes_over_when_the_cloud_voice_is_unavailable(
    browser: Any, server_url: str, token: str
) -> None:
    c, fake = _show(browser, server_url, token)
    fake.speak_status = 503
    try:
        _begin(c)
        c.page.wait_for_function("() => window.__spoken.length >= 3")
        spoken = c.page.evaluate("window.__spoken")
        assert spoken[:2] == [b["text"] for b in QUICK[0]["beats"]]
        assert len(set(_spoken_ids(fake))) <= 2  # the failed line and at most its prefetch
        _clean(c, 503)
    finally:
        c.close()


def test_the_keys_drive_the_show(browser: Any, server_url: str, token: str) -> None:
    c, _ = _show(browser, server_url, token, scenes=SCENES)
    try:
        _begin(c)
        c.page.keyboard.press("Space")
        c.page.wait_for_function("() => !window.JarvisBookShow.state().playing")
        assert c.page.locator("#shPlay").get_attribute("aria-pressed") == "false"
        if _state(c)["renderer"] == "3d":  # Pause holds the 3D still too (WCAG 2.2.2)
            assert c.page.evaluate("window.JarvisBook3D.stats().running") is False
        before = _state(c)["index"]
        c.page.keyboard.press("ArrowRight")
        c.page.wait_for_function(f"() => window.JarvisBookShow.state().index === {before + 1}")
        c.page.keyboard.press("ArrowLeft")
        c.page.wait_for_function(f"() => window.JarvisBookShow.state().index === {before}")
        scene = _state(c)["scene"]
        c.page.keyboard.press("PageDown")
        c.page.wait_for_function(f"() => window.JarvisBookShow.state().scene === {scene + 1}")
        c.page.keyboard.press("PageUp")
        c.page.wait_for_function(f"() => window.JarvisBookShow.state().scene === {scene}")
        c.page.keyboard.press("c")
        assert c.page.locator("#shCaptions").get_attribute("aria-pressed") == "false"
        assert c.page.locator("#shCap").get_attribute("aria-live") == "polite"
        c.page.keyboard.press("c")
        c.page.keyboard.press("Space")
        c.page.wait_for_function("() => window.JarvisBookShow.state().playing")
        c.page.keyboard.press("q")
        c.page.locator("#shTalk").wait_for(state="visible")
        assert c.page.evaluate("document.activeElement.id") == "shQ"
        c.page.locator("#shPlay").focus()
        c.page.keyboard.press("Escape")
        confirm = c.page.locator("#shConfirm")
        confirm.wait_for(state="visible")
        assert "deleted" in confirm.inner_text()
        confirm.get_by_role("button", name="Keep watching").click()
        assert c.page.evaluate(
            "!!document.activeElement.closest('#show')"
        )  # focus kept in the show
        _clean(c)
    finally:
        c.close()


def test_reduced_motion_runs_no_animation_loop(browser: Any, server_url: str, token: str) -> None:
    c, _ = _show(browser, server_url, token, reduced=True, scenes=SCENES)
    try:
        _begin(c)
        c.page.wait_for_timeout(600)
        before = c.page.evaluate("window.__raf")
        c.page.wait_for_timeout(1500)
        assert c.page.evaluate("window.__raf") - before <= 3
        st = _state(c)
        assert st["motion"] != "full" and st["playing"]
        if st["renderer"] == "3d":
            assert c.page.evaluate("window.JarvisBook3D.stats().running") is False
        _clean(c)
    finally:
        c.close()


def test_a_phone_gets_the_2d_show_and_no_gl_context(
    browser: Any, server_url: str, token: str
) -> None:
    c, _ = _show(browser, server_url, token, PHONE)
    try:
        _begin(c)
        c.page.locator("#sh2d .sh2-scene").wait_for()
        assert _state(c)["renderer"] == "2d"
        assert c.page.evaluate("window.__gl") == []
        assert c.page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
        for name in ("#shPlay", "#shNext", "#shPrev", "#shEnd"):
            box = c.page.locator(name).bounding_box()
            assert box and box["width"] >= 44 and box["height"] >= 44, name
        _clean(c)
    finally:
        c.close()


def test_a_webgl_failure_falls_back_to_the_2d_show(
    browser: Any, server_url: str, token: str
) -> None:
    c, _ = _show(browser, server_url, token, gl_fail=True)
    try:
        _begin(c)
        c.page.locator("#sh2d .sh2-scene").wait_for()
        assert _state(c)["renderer"] == "2d"
        assert c.page.evaluate("window.JarvisBook3D.stats().contexts") == 0
        _clean(c)
    finally:
        c.close()


def test_the_3d_show_keeps_its_budget_in_every_scene(
    browser: Any, server_url: str, token: str
) -> None:
    c, fake = _show(browser, server_url, token, scenes=SCENES)
    try:
        _begin(c)
        _need_3d(c)
        c.page.keyboard.press("Space")
        for n in range(1, 14):
            c.page.wait_for_function(f"() => window.JarvisBookShow.state().scene === {n}")
            c.page.wait_for_timeout(250)
            st = c.page.evaluate("window.JarvisBook3D.stats()")
            assert st["calls"] <= 150 and st["labels"] <= 24 and st["dpr"] <= 1.5, (n, st)
            assert st["scene"] == n, (n, st)
            if n < 13:  # the button: at 12 the questions box has the focus (keys type there)
                c.page.locator("#shNextScene").click()
        assert not fake.to("POST", "/v1/book/close")  # walking the scenes never ends it
        _clean(c)
    finally:
        c.close()


def test_a_question_gets_a_reply_and_the_follow_up_and_a_refusal_shows(
    browser: Any, server_url: str, token: str
) -> None:
    c, fake = _show(browser, server_url, token)
    refusal = (
        "That belongs to my owner, and none of it is in this session. I can tell you how I'm built."
    )
    fake.ask_answers = [FakeBook.reply(), FakeBook.reply(refusal, refused=True, left=18)]
    try:
        _begin(c)
        _to_questions(c)
        c.page.locator("#shQ").fill("How do you read e-mail?")
        c.page.locator("#shSend").click()
        thread = c.page.locator("#shThread")
        thread.locator(".row.jarvis .bubble", has_text="Gmail connector").wait_for()
        thread.locator(".row.jarvis .bubble", has_text=LINES["anything_else"]).wait_for()
        (asked, *_) = fake.to("POST", "/v1/book/show/ask")
        assert asked["body"] == {"text": "How do you read e-mail?"}
        c.page.locator("#shQ").fill("What is your owner's e-mail address?")
        c.page.locator("#shQ").press("Enter")
        thread.locator(".row.jarvis .bubble", has_text="belongs to my owner").wait_for()
        assert "18" in c.page.locator("#shLeft").inner_text()
        assert "r_0123456789ab" in _spoken_ids(fake)  # the guarded reply is spoken by its id
        _clean(c)
    finally:
        c.close()


def test_the_guest_closing_comes_in_order_then_the_page_is_wiped_and_handed_back(
    browser: Any, server_url: str, token: str
) -> None:
    c, fake = _show(browser, server_url, token, google=True)
    fake.lock = {"on": True, "id": LOCK_ID}
    try:
        _begin(c)
        _to_questions(c)
        c.page.locator("#shQ").fill("How are you built?")
        c.page.locator("#shSend").click()
        c.page.locator("#shThread .row.jarvis").first.wait_for()
        c.page.locator("#shFinish").click()
        done = c.page.locator("#shDone")
        done.wait_for(state="visible", timeout=30000)
        ids = _spoken_ids(fake)
        assert ids[-3:] == ["credit", "sealed_guest", "thanks_guest"]
        [closed] = fake.to("POST", "/v1/book/close")
        assert closed["body"] == {"reason": "closing"}  # I1: D14's reason reaches the server
        assert LINES["hand_back"] in done.inner_text()
        assert done.get_by_role("button", name="Resume with my passkey").is_visible()
        assert (
            c.page.evaluate(
                "Object.keys(sessionStorage).filter((k) => k.startsWith('jarvis_book'))"
            )
            == []
        )
        assert c.page.locator("#shCapText").inner_text() == ""
        assert c.page.locator("#shThread *").count() == 0
        assert c.page.locator("#shLabels *").count() == 0 and c.page.locator("#sh2d *").count() == 0
        assert c.page.evaluate("window.JarvisBookShow.state().audio") == "closed"
        _clean(c)
    finally:
        c.close()


def test_the_owner_closing_thanks_him_and_offers_the_console(
    browser: Any, server_url: str, token: str
) -> None:
    c, fake = _show(browser, server_url, token, audience="owner")
    try:
        _begin(c)
        _to_questions(c)
        c.page.locator("#shFinish").click()
        done = c.page.locator("#shDone")
        done.wait_for(state="visible", timeout=30000)
        assert _spoken_ids(fake)[-3:] == ["credit", "sealed_owner", "thanks_owner"]
        assert done.get_by_role("button", name="Back to the console").is_visible()
        assert done.get_by_role("button", name="Resume with my passkey").count() == 0
        _clean(c)
    finally:
        c.close()


def test_end_asks_first_then_wipes(browser: Any, server_url: str, token: str) -> None:
    c, fake = _show(browser, server_url, token, scenes=SCENES)
    try:
        _begin(c)
        c.page.locator("#shChapters").click()  # the chapter list holds the scene titles
        c.page.locator("#shChapClose").click()
        c.page.locator("#shEnd").click()
        confirm = c.page.locator("#shConfirm")
        confirm.wait_for(state="visible")
        confirm.get_by_role("button", name="End the session").click()
        c.page.locator("#shDone").wait_for(state="visible")
        [closed] = fake.to("POST", "/v1/book/close")
        assert closed["body"] == {"reason": "end"}
        assert c.page.evaluate("sessionStorage.getItem('jarvis_book_token')") is None
        assert c.page.locator("#shChapterItems *").count() == 0  # D14: no scene title stays
        _clean(c)
    finally:
        c.close()


@pytest.mark.parametrize("status", [401, 403, 404, 410])
def test_an_expired_session_says_so_and_forgets_the_token(
    browser: Any, server_url: str, token: str, status: int
) -> None:
    """Only a definitive refusal (the Contract's 401/403/404/410) forgets the token."""
    c = Console(browser, server_url, token, DESKTOP)
    c.page.add_init_script(SEED % (TOKEN, "guest"))
    fake = FakeBook(c.page)
    fake.script_answer = (status, {"error": "session_gone", "detail": "This session has ended."})
    try:
        c.page.goto(server_url + "/book/show")
        done = c.page.locator("#shDone")
        done.wait_for(state="visible")
        assert "ended" in done.inner_text()
        assert c.page.evaluate("sessionStorage.getItem('jarvis_book_token')") is None
        _clean(c, status)
    finally:
        c.close()


def test_a_3d_layer_that_fails_to_load_is_reported_never_silent(
    browser: Any, server_url: str, token: str
) -> None:
    """A broken scene module (or three.js) must fail the 3D tests, not skip them: the page warns,
    the engine says load-failed, and _need_3d fails instead of skipping."""
    c = Console(browser, server_url, token, DESKTOP)
    c.page.route(
        "**/static/console-book-scenes-data.js",
        lambda r: r.fulfill(
            status=200, content_type="text/javascript", body="export const SCENES = ;"
        ),
    )
    c.page.add_init_script(GL_SPY)
    c.page.add_init_script(SPEECH_STUB)
    c.page.add_init_script(SEED % (TOKEN, "guest"))
    fake = FakeBook(c.page)
    fake.script_answer = (200, script("guest", QUICK))
    try:
        c.page.goto(server_url + "/book/show")
        c.page.locator("#shBegin").wait_for()
        _begin(c)
        assert c.page.evaluate("window.JarvisBook3D.stats().state") == "load-failed"
        assert any("Build book 3D" in w for w in c.page.evaluate("window.__warns"))
        with pytest.raises(AssertionError):
            _need_3d(c)
    finally:
        c.close()


def test_the_start_card_names_the_version_next_to_the_commit(
    browser: Any, server_url: str, token: str
) -> None:
    """R6.1 decision 3: the show's release line is "R6.1 · v6.1.0 · <id>" (R6 books: "R6 · <id>")."""
    c = Console(browser, server_url, token, DESKTOP)
    c.page.add_init_script(GL_SPY)
    c.page.add_init_script(SPEECH_STUB)
    c.page.add_init_script(SEED % (TOKEN, "guest"))
    fake = FakeBook(c.page)
    body = script("guest", QUICK)
    body["release"] = {
        "id": "8308815",
        "label": "R6.1",
        "version": "v6.1.0",
        "committed_at": "2026-11-11T09:00:00+05:30",
    }
    fake.script_answer = (200, body)
    try:
        c.page.goto(server_url + "/book/show")
        c.page.locator("#shBegin").wait_for()
        # both labels are set in capitals by their CSS (the look); their text is this line
        assert c.page.locator("#shStartRel").text_content() == "R6.1 · v6.1.0 · 8308815"
        assert c.page.locator("#shRelease").text_content() == "R6.1 · v6.1.0 · 8308815"
        _clean(c)
    finally:
        c.close()
