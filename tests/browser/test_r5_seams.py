# tests/browser/test_r5_seams.py — R5 I0 seams in a real browser (docs/plans/r5-voice.md).
# The mic lock (stop, reload, unlock only by a real gesture, other tabs), the chosen input and its
# fallback, the output sink, duck / tone / stop().rest, the command router core, the Voice panel
# slots and device keys, the minimal JarvisVoiceLoop, the status words, and (I1) the frozen shapes
# of the modules that replaced the stubs, with B's matcher loaded by the real page.
from __future__ import annotations

import json
from collections.abc import Callable, Iterator
from typing import Any

import pytest
from test_console import DESKTOP, Console
from test_voice import (  # same directory (pytest prepend import)
    FAKE_RECOGNITION,
    FAKE_SYNTH,
    RECORDER,
    FakeVoice,
    _mic_state,
    _voice_panel,
    _wait,
    speechlike_wav,
    voice_view,
)
from test_voice_robust import LIVE_TRACKS, SLOW_GUM

_pw = pytest.importorskip("playwright.sync_api")

pytestmark = pytest.mark.browser

FAKE_MEDIA = ["--use-fake-ui-for-media-stream", "--use-fake-device-for-media-stream"]
LOCK_KEY = "jarvis_mic_off_v1"
EVENTS = """
window.__ev = [];
for (const n of ['jarvis:mic-lock', 'jarvis:voice-command', 'jarvis:voice-panel',
  'jarvis:audio-route', 'jarvis:voice-loop'])
  document.addEventListener(n, (e) => window.__ev.push({ n, d: e.detail }));
"""
# a button that calls unlock() from inside a real click (user activation)
CLICK_UNLOCK = """() => {
  const b = document.createElement('button');
  b.id = 'unlockTest'; b.textContent = 'unlock';
  b.style.cssText = 'position:fixed;left:0;top:0;z-index:99999;width:120px;height:50px';
  b.onclick = () => { window.__unlocked = window.JarvisAudio.unlock('button'); };
  document.body.append(b);
}"""


@pytest.fixture(scope="module")
def browser(tmp_path_factory: pytest.TempPathFactory) -> Iterator[Any]:
    mic = tmp_path_factory.mktemp("r5seams") / "speech.wav"
    speechlike_wav(mic)
    args = [
        *FAKE_MEDIA,
        f"--use-file-for-fake-audio-capture={mic}",
        "--autoplay-policy=no-user-gesture-required",
    ]
    with _pw.sync_playwright() as p:
        b = p.chromium.launch(args=args)
        yield b
        b.close()


@pytest.fixture
def make(browser: Any, server_url: str, token: str) -> Iterator[Callable[..., Console]]:
    made: list[Console] = []

    def factory(device: dict[str, Any] | None = None, scripts: tuple[str, ...] = ()) -> Console:
        c = Console(browser, server_url, token, DESKTOP)
        c.page.route(
            "**/static/console-wakeword.js",
            lambda r: r.fulfill(status=200, content_type="text/javascript", body=""),
        )
        c.page.add_init_script(RECORDER)
        c.page.add_init_script(EVENTS)
        dev = {"interruptBy": "tap", **(device or {})}
        c.page.add_init_script(
            f"localStorage.getItem('jarvis_voice_device_v1') === null && "
            f"localStorage.setItem('jarvis_voice_device_v1', {json.dumps(json.dumps(dev))});"
        )
        for s in scripts:
            c.page.add_init_script(s)
        made.append(c)
        return c

    yield factory
    for c in made:
        c.close()


def ev(c: Console, js: str) -> Any:
    return c.page.evaluate(js)


def fire(c: Console, js: str) -> None:
    """Run statements in the page without awaiting a promise they start (evaluate would)."""
    c.page.evaluate("() => { " + js + " }")


def events(c: Console, name: str) -> list[Any]:
    return [e["d"] for e in c.page.evaluate("window.__ev") if e["n"] == name]


# ====================================================================== the mic lock (D11)
def test_lock_stops_every_track_and_open_rejects(make: Callable[..., Console]) -> None:
    c = make(scripts=(SLOW_GUM,))
    FakeVoice(c.page)
    c.open()
    ev(c, "JarvisAudio.open()")
    assert ev(c, "JarvisAudio.isOpen()") is True and ev(c, LIVE_TRACKS) == [1]
    ev(c, "JarvisAudio.lock('voice')")
    assert ev(c, "JarvisAudio.locked()") is True and ev(c, "JarvisAudio.isOpen()") is False
    assert ev(c, LIVE_TRACKS) == [0]
    assert ev(c, f"localStorage.getItem('{LOCK_KEY}')") == "1"
    code = ev(c, "JarvisAudio.open().then(() => 'opened', (e) => e.code)")
    assert code == "mic_off"
    assert ev(c, "window.__streams.length") == 1  # getUserMedia was not asked again
    assert {"locked": True, "by": "voice"} in events(c, "jarvis:mic-lock")
    assert c.errors == []


def test_lock_during_a_build_in_flight_leaves_no_live_track(make: Callable[..., Console]) -> None:
    c = make(scripts=(SLOW_GUM,))
    FakeVoice(c.page)
    c.open()
    fire(c, "window.__gumDelays.push(600)")
    fire(c, "window.__p = JarvisAudio.open().then(() => 'opened', (e) => e.code)")
    ev(c, "JarvisAudio.lock('button')")
    assert ev(c, "window.__p") in ("closed", "mic_off")
    c.page.wait_for_timeout(900)
    assert ev(c, LIVE_TRACKS) in ([0], [])
    assert ev(c, "JarvisAudio.isOpen()") is False


def test_prime_does_nothing_while_locked(make: Callable[..., Console]) -> None:
    c = make(
        scripts=(
            "window.__ac = 0; (() => { const R = window.AudioContext;"
            " window.AudioContext = class extends R {"
            " constructor(...a) { super(...a); window.__ac++; } };"
            " })();",
        )
    )
    FakeVoice(c.page)
    c.open()
    ev(c, "JarvisAudio.lock('button')")
    before = ev(c, "window.__ac")
    ev(c, "JarvisAudio.prime()")
    assert ev(c, "window.__ac") == before


def test_reload_stays_locked_and_nothing_opens(make: Callable[..., Console]) -> None:
    c = make(scripts=(SLOW_GUM,))
    FakeVoice(c.page)
    c.open()
    ev(c, "JarvisAudio.lock('button')")
    c.page.reload()
    c.page.wait_for_function("() => !!window.JarvisAudio")
    assert ev(c, "JarvisAudio.locked()") is True
    c.page.locator("#welcome").wait_for()
    assert ev(c, "JarvisAudio.open().then(() => 'opened', (e) => e.code)") == "mic_off"
    assert ev(c, "window.__streams.length") == 0
    assert _mic_state(c) == "off"
    assert {"locked": True, "by": "boot"} in events(c, "jarvis:mic-lock")


def test_unlock_needs_a_real_gesture(make: Callable[..., Console]) -> None:
    c = make()
    FakeVoice(c.page)
    c.open()
    ev(c, "JarvisAudio.lock('button')")
    # Playwright's evaluate counts as a gesture, so ask from a timer that fires after the 5 s the
    # browser keeps an activation for: that is what a script of the page's own can do
    fire(c, "setTimeout(() => { window.__late = JarvisAudio.unlock('button'); }, 5800)")
    c.page.wait_for_timeout(6500)
    assert ev(c, "window.__late") is False  # from script: refused
    assert ev(c, "JarvisAudio.locked()") is True
    ev(c, CLICK_UNLOCK)
    c.page.locator("#unlockTest").click()
    assert ev(c, "window.__unlocked") is True
    assert ev(c, "JarvisAudio.locked()") is False
    assert ev(c, f"localStorage.getItem('{LOCK_KEY}')") is None
    assert ev(c, "JarvisAudio.isOpen()") is False  # unlock never opens the microphone
    ev(c, "JarvisAudio.open()")
    assert ev(c, "JarvisAudio.isOpen()") is True
    assert {"locked": False, "by": "button"} in events(c, "jarvis:mic-lock")


def test_recognizer_is_the_only_constructor_and_lock_aborts_it(
    make: Callable[..., Console],
) -> None:
    c = make(scripts=(FAKE_RECOGNITION,))
    FakeVoice(c.page)
    c.open()
    ev(c, "window.__recSilent = true; window.__r = JarvisAudio.recognizer(); window.__r.start()")
    assert ev(c, "window.__rec.length") == 1
    ev(c, "JarvisAudio.lock('voice')")
    assert ev(c, "window.__rec[0].aborted") is True
    assert (
        ev(
            c,
            "(() => { try { JarvisAudio.recognizer(); return 'built'; }"
            " catch (e) { return e.code; } })()",
        )
        == "mic_off"
    )
    assert ev(c, "window.__rec.length") == 1
    ev(c, "delete window.SpeechRecognition; delete window.webkitSpeechRecognition")
    # unlocking needs a gesture; flip the flag as another tab would, to reach 'unsupported'
    ev(c, f"localStorage.removeItem('{LOCK_KEY}')")


def test_a_second_tab_follows_lock_and_unlock(make: Callable[..., Console]) -> None:
    a = make()
    FakeVoice(a.page)
    a.open()
    b_page = a.ctx.new_page()
    b_page.add_init_script(EVENTS)
    b_page.goto(a.url + "/")
    b_page.wait_for_function("() => !!window.JarvisAudio")
    ev(a, "JarvisAudio.lock('button')")
    b_page.wait_for_function("() => window.JarvisAudio.locked() === true")
    seen = [e["d"] for e in b_page.evaluate("window.__ev") if e["n"] == "jarvis:mic-lock"]
    assert {"locked": True, "by": "storage"} in seen
    a.page.wait_for_timeout(6000)
    ev(a, CLICK_UNLOCK)
    a.page.locator("#unlockTest").click()
    b_page.wait_for_function("() => window.JarvisAudio.locked() === false")
    assert b_page.evaluate("window.JarvisAudio.isOpen()") is False  # never starts a turn
    b_page.close()


# ====================================================================== the chosen input (D13)
GUM_SPY = """
(() => {
  window.__cons = []; window.__missing = false;
  const md = navigator.mediaDevices, real = md.getUserMedia.bind(md);
  md.getUserMedia = (c) => {
    window.__cons.push(JSON.parse(JSON.stringify(c)));
    if (window.__missing && c.audio && c.audio.deviceId)
      return Promise.reject(new DOMException('gone', 'OverconstrainedError'));
    return real(c);
  };
})();
"""


def test_set_input_asks_for_that_device_and_null_goes_back(make: Callable[..., Console]) -> None:
    c = make(scripts=(GUM_SPY,))
    FakeVoice(c.page)
    c.open()
    assert ev(c, "JarvisAudio.inputId()") is None
    ev(c, "JarvisAudio.setInput('dev-42')")
    assert ev(c, "JarvisAudio.inputId()") == "dev-42"
    ev(c, "JarvisAudio.open()")
    assert ev(c, "window.__cons[0].audio.deviceId") == {"exact": "dev-42"}
    assert ev(c, "window.__cons[0].audio.echoCancellation") is True
    assert ev(c, "JarvisAudio.trackLabel()") not in ("", None)
    ev(c, "JarvisAudio.close(); JarvisAudio.setInput(null)")
    assert ev(c, "JarvisAudio.inputId()") is None
    ev(c, "JarvisAudio.open()")
    assert "deviceId" not in ev(c, "window.__cons[1].audio")
    assert ev(c, "JarvisAudio.setInput(7)") is None and ev(c, "JarvisAudio.inputId()") is None


def test_a_missing_input_falls_back_once_and_says_so(make: Callable[..., Console]) -> None:
    c = make(scripts=(GUM_SPY,))
    FakeVoice(c.page)
    c.open()
    ev(c, "window.__missing = true; JarvisAudio.setInput('unplugged')")
    ev(c, "JarvisAudio.open()")
    assert ev(c, "JarvisAudio.isOpen()") is True
    assert ev(c, "window.__cons.length") == 2
    assert ev(c, "window.__cons[0].audio.deviceId") == {"exact": "unplugged"}
    assert "deviceId" not in ev(c, "window.__cons[1].audio")
    routes = events(c, "jarvis:audio-route")
    assert routes and routes[0]["reason"] == "input_missing"
    assert routes[0]["input"]["id"] == "unplugged"
    ev(c, "JarvisAudio.open()")  # the fallback stands: the next open() asks for nothing again
    assert ev(c, "window.__cons.length") == 2


def test_a_new_input_takes_over_at_the_next_open_and_says_when_it_is_live(
    make: Callable[..., Console],
) -> None:
    # B's review: with the microphone held open through a conversation, chooseInput never took
    # effect; now the next open() (the next listening turn) reopens on it
    c = make(scripts=(GUM_SPY, SLOW_GUM))
    FakeVoice(c.page)
    c.open()
    ev(c, "JarvisAudio.open()")
    assert ev(c, "window.__cons.length") == 1 and "deviceId" not in ev(c, "window.__cons[0].audio")
    other = ev(  # one of Chrome's fake microphones, now that the permission is granted
        c,
        """async () => (await navigator.mediaDevices.enumerateDevices())
          .filter(d => d.kind === 'audioinput' && d.deviceId && d.deviceId !== 'default')
          .map(d => d.deviceId)[0]""",
    )
    assert isinstance(other, str) and other
    ev(c, f"JarvisAudio.setInput({json.dumps(other)})")
    assert ev(c, "JarvisAudio.isOpen()") is True and ev(c, "window.__cons.length") == 1
    ev(c, "JarvisAudio.open()")
    assert ev(c, "window.__cons.length") == 2
    assert ev(c, "window.__cons[1].audio.deviceId") == {"exact": other}
    assert ev(c, LIVE_TRACKS) == [0, 1]  # the old microphone's tracks were stopped
    ev(c, "JarvisAudio.open()")  # unchanged since: shared, no new request
    assert ev(c, "window.__cons.length") == 2
    live = [r for r in events(c, "jarvis:audio-route") if r["reason"] == "input_live"]
    assert [r["input"]["id"] for r in live] == [None, other]
    assert all(r["input"]["label"] == "" for r in live)  # an id only: labels stay with B
    assert c.errors == []


# ====================================================================== the speaker (D13, D15)
SINK_STUB = """
(() => {
  window.__sinks = []; window.__sinkFail = null;
  AudioContext.prototype.setSinkId = function (id) {
    window.__sinks.push(id);
    if (window.__sinkFail) return Promise.reject(new DOMException('x', window.__sinkFail));
    return Promise.resolve();
  };
})();
"""


def test_set_sink_routes_this_and_later_contexts(make: Callable[..., Console]) -> None:
    c = make(scripts=(SINK_STUB,))
    FakeVoice(c.page)
    c.open()
    assert ev(c, "JarvisVoice.speaker.sinkSupported()") is True
    assert ev(c, "JarvisVoice.speaker.sink()") in ("", None)
    assert ev(c, "JarvisVoice.speaker.setSink('buds')") == {"ok": True}
    assert ev(c, "JarvisVoice.speaker.sink()") == "buds"
    # I1: before any sound the context is made for it, so the browser checks the id now
    assert ev(c, "window.__sinks") == ["buds"]
    ev(c, "JarvisVoice.speaker.unlock()")
    assert ev(c, "window.__sinks") == ["buds"]  # the same context: nothing is applied twice
    assert ev(c, "JarvisVoice.speaker.setSink('desk')") == {"ok": True}
    assert ev(c, "window.__sinks") == ["buds", "desk"]
    ev(c, "window.__sinkFail = 'NotFoundError'")
    res = ev(c, "JarvisVoice.speaker.setSink('gone')")
    assert res == {"ok": False, "reason": "not_found"}
    assert ev(c, "JarvisVoice.speaker.sink()") == "desk"  # kept the working one
    ev(c, "window.__sinkFail = null")
    assert ev(c, "JarvisVoice.speaker.setSink(null)") == {"ok": True}
    assert ev(c, "JarvisVoice.speaker.sink()") in ("", None)


def test_set_sink_before_any_sound_is_checked_not_assumed(make: Callable[..., Console]) -> None:
    # B's review: with no audio context yet, setSink said ok without asking the browser
    c = make(scripts=(SINK_STUB,))
    FakeVoice(c.page)
    c.open()
    ev(c, "window.__sinkFail = 'NotFoundError'")
    assert ev(c, "JarvisVoice.speaker.setSink('gone')") == {"ok": False, "reason": "not_found"}
    assert ev(c, "JarvisVoice.speaker.sink()") in ("", None)  # the default, as it really is
    assert ev(c, "window.__sinks") == ["gone"]
    ev(c, "window.__sinkFail = 'NotAllowedError'")
    assert ev(c, "JarvisVoice.speaker.setSink('x')") == {"ok": False, "reason": "blocked"}
    assert c.errors == []


def test_set_sink_says_unsupported_where_the_browser_cannot(make: Callable[..., Console]) -> None:
    c = make(scripts=("delete AudioContext.prototype.setSinkId;",))
    FakeVoice(c.page)
    c.open()
    assert ev(c, "JarvisVoice.speaker.sinkSupported()") is False
    assert ev(c, "JarvisVoice.speaker.setSink('buds')") == {"ok": False, "reason": "unsupported"}


def test_duck_lowers_and_restores_the_cloud_voice_only(make: Callable[..., Console]) -> None:
    c = make(scripts=(FAKE_SYNTH,))
    FakeVoice(c.page)
    c.open()
    ev(c, "JarvisVoice.speaker.unlock()")
    c.page.wait_for_timeout(300)
    assert ev(c, "JarvisVoice.speaker.duck(true)") is True
    c.page.wait_for_timeout(300)
    assert abs(ev(c, "JarvisVoice.speaker.volume()") - 0.2) < 0.03
    ev(c, "JarvisVoice.speaker.duck(false)")
    c.page.wait_for_timeout(300)
    assert abs(ev(c, "JarvisVoice.speaker.volume()") - 1) < 0.03
    ev(c, "JarvisVoice.speaker.browser(true)")
    assert ev(c, "JarvisVoice.speaker.duck(true)") is False  # the OS voice cannot be lowered
    assert abs(ev(c, "JarvisVoice.speaker.volume()") - 1) < 0.03


def test_tone_plays_a_clamped_blip_and_resolves(make: Callable[..., Console]) -> None:
    spy = (
        "(() => { window.__osc = []; const o = AudioContext.prototype.createOscillator;"
        " AudioContext.prototype.createOscillator = function () { const n = o.call(this);"
        " window.__osc.push(n); return n; }; })();"
    )
    c = make(scripts=(spy,))
    FakeVoice(c.page)
    c.open()
    ev(c, "JarvisVoice.speaker.unlock()")
    c.page.wait_for_timeout(300)
    assert ev(c, "JarvisVoice.speaker.tone({ freq: 440, ms: 80, gain: 0.1 })") is True
    assert abs(ev(c, "window.__osc[0].frequency.value") - 440) < 1
    ev(c, "JarvisVoice.speaker.tone({ freq: 99999, ms: 99999, gain: 9 })")
    assert ev(c, "window.__osc[1].frequency.value") <= 4000


def test_stop_returns_the_unplayed_text_and_chunks_carry_a_time(
    make: Callable[..., Console],
) -> None:
    c = make(scripts=(FAKE_SYNTH,))
    FakeVoice(c.page)
    c.open()
    out = ev(
        c,
        """() => {
      const hang = () => new Promise(() => {});
      const s = JarvisSpeaker.create({ synth: hang });
      s.say('One.'); s.say('Two.'); s.say('Three.'); s.end();
      const first = s.stop();
      return { first, again: s.stop() };
    }""",
    )
    assert out["first"] == {"rest": ["One.", "Two.", "Three."]}
    assert out["again"] == {"rest": []}
    got = ev(
        c,
        """async () => {
      const fail = () => Promise.reject(Object.assign(new Error('x'), { fallback: true }));
      const s = JarvisSpeaker.create({ synth: fail });
      const seen = [];
      s.on('chunk', (d) => seen.push(d));
      const t0 = performance.now();
      s.say('Hello there.'); s.end();
      await new Promise((r) => setTimeout(r, 400));
      return { seen, t0, t1: performance.now() };
    }""",
    )
    assert got["seen"] and got["seen"][0]["text"] == "Hello there."
    assert got["t0"] <= got["seen"][0]["at"] <= got["t1"]
    cloud = ev(
        c,
        """async () => {
      const wav = () => { const f = new Int16Array(1280);
        for (let i = 0; i < f.length; i++) f[i] = 3000 * Math.sin(i / 8);
        return JarvisWav.encode([f, f, f, f]); };
      const s = JarvisSpeaker.create({ synth: () => Promise.resolve(wav()) });
      const seen = [];
      s.on('chunk', (d) => seen.push(d));
      s.unlock();
      s.say('Cloud line.'); s.end();
      await new Promise((r) => setTimeout(r, 800));
      return seen;
    }""",
    )
    assert cloud and cloud[0]["engine"] == "cloud" and isinstance(cloud[0]["at"], (int, float))


# ====================================================================== the command router (D12)
def test_normalise_cases(make: Callable[..., Console]) -> None:
    c = make()
    FakeVoice(c.page)
    c.open()
    cases = {
        "Hey Jarvis, stop!": "stop",
        "OK Jarvis please turn off the microphone now": "switch off the mic",
        "Jervis, can you stop talking, sir?": "stop talking",
        "Jarvis's mic off": "mic off",
        "  THAT’S   enough  ": "that's enough",
        "Thank you": "",
        "Switch to the keyboard, ma'am.": "switch to the keyboard",
        "turn the mike off": "switch the mic off",
        "ｍｉｃ　ｏｆｆ": "mic off",
        "Could you please wait a moment thanks": "wait a moment",
        "no, thanks": "no",
        "": "",
    }
    got = ev(c, f"{json.dumps(list(cases))}.map((t) => JarvisVoiceCommands.normalise(t))")
    assert got == list(cases.values())
    assert ev(c, "JarvisVoiceCommands.normalise(null)") == ""


def test_normalise_keeps_combining_marks_so_indic_words_stay_whole(
    make: Callable[..., Console],
) -> None:
    # vowel signs and the virama are combining marks (\p{M}): stripping them split one Malayalam or
    # Hindi word into several, so a nickname could fail the 8-word cap or never match (B's review)
    c = make()
    FakeVoice(c.page)
    c.open()
    for text in ("switch to അമ്മയുടെ ഫോൺ", "use मेरा हेडसेट mic", "switch to ക്ലാസ് റൂം"):
        got = ev(c, f"JarvisVoiceCommands.normalise({json.dumps(text)})")
        assert got == text and len(got.split()) == len(text.split()), (text, got)


def test_register_handle_round_trip_and_the_guards(make: Callable[..., Console]) -> None:
    c = make()
    FakeVoice(c.page)
    c.open()
    ev(
        c,
        """() => { window.__un = JarvisVoiceCommands.register('test.hello', {
      match: (n) => (n === 'say hello' ? { who: 'x' } : null),
      run: (args, ctx) => ({ say: 'Hello ' + args.who + ' ' + ctx.state, then: 'idle' }) }); }""",
    )
    voice = {"source": "voice", "state": "listening"}
    r = ev(c, f"JarvisVoiceCommands.handle('Hey Jarvis, say hello please.', {json.dumps(voice)})")
    assert r == {
        "handled": True,
        "id": "test.hello",
        "result": {"say": "Hello x listening", "then": "idle"},
    }
    assert {"id": "test.hello", "handled": True, "state": "listening"} in events(
        c, "jarvis:voice-command"
    )
    typed = {"source": "typed", "state": "listening"}
    assert ev(c, f"JarvisVoiceCommands.handle('say hello', {json.dumps(typed)})") == {
        "handled": False
    }
    assert ev(c, "JarvisVoiceCommands.handle('say hello', null)") == {"handled": False}
    for text in ("remind me to say hello", "say hello to the team at five o'clock sharp", "", "  "):
        assert ev(c, f"JarvisVoiceCommands.handle({json.dumps(text)}, {json.dumps(voice)})") == {
            "handled": False
        }, text
    off = {"source": "voice", "state": "off"}
    assert ev(c, f"JarvisVoiceCommands.handle('say hello', {json.dumps(off)})") == {
        "handled": False
    }
    dup = ev(
        c,
        "(() => { try { JarvisVoiceCommands.register('test.hello', { match() {}, run() {} });"
        " return 'ok'; } catch (e) { return 'threw'; } })()",
    )
    assert dup == "threw"
    bad = ev(
        c,
        "(() => { try { JarvisVoiceCommands.register('Bad Id', { match() {}, run() {} });"
        " return 'ok'; } catch (e) { return 'threw'; } })()",
    )
    assert bad == "threw"
    ev(c, "window.__un()")
    assert ev(c, f"JarvisVoiceCommands.handle('say hello', {json.dumps(voice)})") == {
        "handled": False
    }


# The listening loop binds its actions once, at load. This page keeps that first binding back,
# so the test can bind the router's actions itself (bindLoop is one-shot), as the I0 test did.
HOLD_LOOP_BIND = """
(() => {
  window.__holdLoop = true;
  let real = null;
  Object.defineProperty(window, 'JarvisVoiceCommands', { configurable: true, get() { return real; },
    set(v) { real = Object.freeze(Object.assign({}, v, {
      bindLoop: (a) => {
        if (window.__holdLoop) { window.__held = a; return undefined; }
        return v.bindLoop(a);
      } })); } });
})();
"""


def test_states_priority_and_a_throwing_command(make: Callable[..., Console]) -> None:
    c = make(scripts=(HOLD_LOOP_BIND,))
    FakeVoice(c.page)
    c.open()
    ev(
        c,
        """() => {
      const C = JarvisVoiceCommands;
      window.__holdLoop = false;
      C.bindLoop({ micOff: () => ({}), keyboard: () => ({}), stop: () => ({ say: 'right' }) });
      const stop = (n) => (n === 'stop' ? {} : null);
      C.register('zzz.first', { match: stop, run: () => ({ say: 'wrong' }) });
      C.register('test.only-speaking', { match: (n) => (n === 'sing' ? {} : null),
        run: () => ({ say: 'la' }), states: ['speaking'] });
      C.register('test.boom', { match: (n) => (n === 'boom' ? {} : null),
        run: () => { throw new Error('boom'); } });
      C.register('test.async', { match: (n) => (n === 'later' ? {} : null),
        run: () => new Promise((r) => setTimeout(() => r({ say: 'done' }), 30)) });
      C.register('test.badmatch', { match: () => { throw new Error('x'); }, run: () => ({}) });
    }""",
    )
    h = lambda t, s: ev(  # noqa: E731
        c, f"JarvisVoiceCommands.handle({json.dumps(t)}, {{ source: 'voice', state: '{s}' }})"
    )
    first = h("stop", "speaking")
    assert first["id"] == "speech.stop"  # fixed priority beats registration order
    assert first["result"] == {"say": "right"}
    assert h("sing", "listening") == {"handled": False}  # a state filter: only while he speaks
    assert h("sing", "speaking")["id"] == "test.only-speaking"
    assert ev(c, "JarvisVoiceCommands.owns('stop', 'speaking')") == "speech.stop"
    assert (
        ev(c, "JarvisVoiceCommands.owns('stop', 'off')") is None
    )  # nothing is heard while the mic is off
    assert ev(c, "JarvisVoiceCommands.owns('nothing like it', 'speaking')") is None
    assert h("boom", "speaking") == {
        "handled": True,
        "id": "test.boom",
        "result": {"error": "failed"},
    }
    assert h("later", "speaking")["result"] == {"say": "done"}
    assert h("unrelated words", "speaking") == {"handled": False}  # a throwing matcher is no match


def test_a_built_in_cannot_be_replaced_and_the_loop_binds_once(
    make: Callable[..., Console],
) -> None:
    c = make()
    FakeVoice(c.page)
    c.open()
    got = ev(
        c,
        """() => {
      const C = JarvisVoiceCommands, out = {};
      for (const id of ['mic.off', 'speech.stop', 'conversation.keyboard']) {
        try {
          C.register(id, { match: () => ({}), run: () => ({ say: 'hijacked' }) });
          out[id] = 'registered';
        }
        catch (e) { out[id] = 'threw'; }
      }
      try {
        C.bindLoop({ micOff: () => ({ say: 'hijacked' }), stop: () => ({}), keyboard: () => ({}) });
        out.bind = 'bound';
      }
      catch (e) { out.bind = 'threw'; }
      return out;
    }""",
    )
    assert set(got) == {"mic.off", "speech.stop", "conversation.keyboard", "bind"}
    assert set(got.values()) == {"threw"}
    assert ev(c, "JarvisVoiceCommands.owns('mic off', 'listening')") == "mic.off"
    assert ev(c, "JarvisAudio.locked()") is False  # and nothing ran
    assert c.errors == []


def test_ask_takes_one_yes_or_no_and_times_out(make: Callable[..., Console]) -> None:
    c = make()
    FakeVoice(c.page)
    c.open()
    v = "{ source: 'voice', state: 'speaking' }"
    assert ev(c, f"JarvisVoiceCommands.handle('yes', {v})") == {"handled": False}  # nothing asked
    assert ev(c, "JarvisVoiceCommands.ask('Shall I?', { timeoutMs: 300 })") == "timeout"
    fire(c, "window.__a = JarvisVoiceCommands.ask('Shall I keep listening?', { timeoutMs: 5000 })")
    assert ev(c, "JarvisVoiceCommands.pending()") == "Shall I keep listening?"
    assert ev(c, "JarvisVoiceCommands.owns('carry on', 'speaking')") == "answer.yes"
    r = ev(c, f"JarvisVoiceCommands.handle('Yes please', {v})")
    assert r["handled"] is True and r["id"] == "answer.yes"
    assert ev(c, "window.__a") == "yes"
    assert ev(c, "JarvisVoiceCommands.pending()") is None
    fire(c, "window.__b = JarvisVoiceCommands.ask('Again?', { timeoutMs: 5000 })")
    assert ev(c, f"JarvisVoiceCommands.handle('not now', {v})")["id"] == "answer.no"
    assert ev(c, "window.__b") == "no"
    # a newer question cancels the older one; other words pass through while one is pending
    fire(c, "window.__c = JarvisVoiceCommands.ask('First?', { timeoutMs: 5000 })")
    fire(c, "window.__d = JarvisVoiceCommands.ask('Second?', { timeoutMs: 5000 })")
    assert ev(c, "window.__c") == "cancelled"
    assert ev(c, f"JarvisVoiceCommands.handle('what is the weather', {v})") == {"handled": False}
    assert ev(c, "JarvisVoiceCommands.pending()") == "Second?"
    fire(
        c,
        "window.__hit = []; JarvisVoiceCommands.ask('Third?', { timeoutMs: 5000,"
        " yes: () => window.__hit.push('y'), no: () => window.__hit.push('n') })",
    )
    ev(c, f"JarvisVoiceCommands.handle('no', {v})")
    assert ev(c, "window.__hit") == ["n"]
    assert ev(c, "window.__d") == "cancelled"


def test_phrases_are_frozen_and_the_same_table_the_tests_parse(
    make: Callable[..., Console],
) -> None:
    c = make()
    FakeVoice(c.page)
    c.open()
    assert ev(c, "Object.isFrozen(JarvisVoiceCommands.PHRASES)") is True
    assert "mic off" in ev(c, "JarvisVoiceCommands.PHRASES['mic.off']")
    assert ev(c, "Object.isFrozen(JarvisVoiceCommands)") is True


# ============================== the Voice panel (D2, D4, D7, D11, D15)
def test_panel_slots_exist_once_built_and_announce_it(make: Callable[..., Console]) -> None:
    c = make()
    FakeVoice(c.page)
    c.open()
    assert ev(c, "JarvisVoice.panelSlot('devices')") is None  # not built yet
    _voice_panel(c)
    for name in ("devices", "phrases", "pace"):
        assert ev(c, f"JarvisVoice.panelSlot('{name}') instanceof HTMLElement") is True, name
        assert ev(c, f"JarvisVoice.panelSlot('{name}') === JarvisVoice.panelSlot('{name}')") is True
        assert ev(
            c, f"document.getElementById('p-voice').contains(JarvisVoice.panelSlot('{name}'))"
        )
    assert ev(c, "JarvisVoice.panelSlot('bogus')") is None
    assert ev(c, "JarvisVoice.panelSlot(null)") is None
    assert {"built": True} in events(c, "jarvis:voice-panel")


def test_update_settings_sends_known_keys_and_merges_phrases(make: Callable[..., Console]) -> None:
    c = make()
    fake = FakeVoice(c.page)
    fake.view = voice_view()
    fake.view["settings"]["phrases"] = ["Trivandrum"]
    put = fake._put

    def put_and_keep(route: Any, body: Any) -> None:  # the real server stores what it is given
        if "phrases" in body:
            fake.view["settings"]["phrases"] = body["phrases"]
        put(route, body)

    fake._put = put_and_keep  # type: ignore[method-assign]
    fake.view["phrase_limits"] = {"items": 50, "chars": 40}
    c.open()
    ev(c, "JarvisVoice.load(true)")
    _wait(c, "() => !!JarvisVoice.config()")
    assert ev(c, "JarvisVoice.config().settings.phrases") == ["Trivandrum"]
    assert ev(c, "JarvisVoice.settings().phrases") == ["Trivandrum"]
    assert ev(c, "JarvisVoice.config().phraseLimits") == {"items": 50, "chars": 40}
    assert ev(c, "JarvisVoice.updateSettings({ bogus: 1, phrases: 'nope' })") is False
    assert ev(c, "JarvisVoice.updateSettings({ phrases: ['Thiruvananthapuram', 'Kochi'] })") is True
    assert ev(c, "JarvisVoice.settings().phrases") == ["Thiruvananthapuram", "Kochi"]
    c.page.wait_for_timeout(1200)
    puts = fake.to("PUT", "/v1/voice/settings")
    assert [p["body"] for p in puts] == [{"phrases": ["Thiruvananthapuram", "Kochi"]}]
    assert ev(c, "JarvisVoice.settings().phrases") == [
        "Thiruvananthapuram",
        "Kochi",
    ]  # kept after PUT
    assert ev(c, "JarvisVoice.updateSettings({ rate: 1.1 })") is True


def test_new_device_keys_are_validated_and_the_defaults_hold(make: Callable[..., Console]) -> None:
    junk = {
        "interruptBy": "loud",
        "followUpS": "8",
        "longPauseS": 500,
        "endSilenceMs": 1300,
        "checkIn": "yes",
        "cues": 1,
    }
    c = make(device=junk)
    FakeVoice(c.page)
    c.open()
    d = ev(c, "JarvisVoice.device()")
    assert d["interruptBy"] == "auto"  # a value outside the list is dropped
    assert d["checkIn"] is True and d["cues"] is True
    assert d["followUpS"] == 8 and d["longPauseS"] == 20 and d["endSilenceMs"] == 1200


def test_long_pause_is_kept_five_seconds_after_the_follow_up_window(
    make: Callable[..., Console],
) -> None:
    c = make(device={"followUpS": 12, "longPauseS": 13, "interruptBy": "name", "cues": False})
    FakeVoice(c.page)
    c.open()
    d = ev(c, "JarvisVoice.device()")
    assert (d["followUpS"], d["longPauseS"], d["interruptBy"], d["cues"]) == (12, 17, "name", False)
    ev(c, "JarvisVoice.setDevice({ followUpS: 99, endSilenceMs: 2000, checkIn: false })")
    d = ev(c, "JarvisVoice.device()")
    assert d["followUpS"] == 12 and d["endSilenceMs"] == 2000 and d["checkIn"] is False
    ev(c, "JarvisVoice.setDevice({ followUpS: 30 })")
    assert ev(c, "JarvisVoice.device().longPauseS") == 35
    saved = json.loads(ev(c, "localStorage.getItem('jarvis_voice_device_v1')"))
    assert saved["followUpS"] == 30 and saved["longPauseS"] == 35


def test_the_panel_rows_write_the_device_keys_and_the_mic_switch_locks(
    make: Callable[..., Console],
) -> None:
    c = make()
    FakeVoice(c.page)
    c.open()
    panel = _voice_panel(c)
    panel.locator("#vInterrupt").select_option("name")
    panel.locator("#vFollow").select_option("12")
    panel.locator("#vLongPause").select_option("60")
    panel.locator("#vEndSilence").select_option("1600")
    panel.locator("#vCheckIn").click()
    panel.locator("#vCues").click()
    saved = json.loads(ev(c, "localStorage.getItem('jarvis_voice_device_v1')"))
    assert (saved["interruptBy"], saved["followUpS"], saved["longPauseS"]) == ("name", 12, 60)
    assert (saved["endSilenceMs"], saved["checkIn"], saved["cues"]) == (1600, False, False)
    mic = panel.locator("#vMic")
    assert mic.get_attribute("aria-pressed") == "true"
    mic.click()  # the owner's switch: lock
    assert ev(c, "JarvisAudio.locked()") is True and mic.get_attribute("aria-pressed") == "false"
    assert _mic_state(c) == "off"
    assert {"locked": True, "by": "panel"} in events(c, "jarvis:mic-lock")
    mic.click()  # a real click: unlock
    assert ev(c, "JarvisAudio.locked()") is False and mic.get_attribute("aria-pressed") == "true"
    assert _mic_state(c) == "idle"


def test_the_wake_chip_knows_the_mic_is_off(make: Callable[..., Console]) -> None:
    c = make()
    FakeVoice(c.page)
    c.open()
    _voice_panel(c)
    ev(
        c,
        "document.dispatchEvent(new CustomEvent('jarvis:wake', { detail: { state: 'micoff' } }))",
    )
    text = str(c.page.locator("#vWakeChip").text_content()).lower()
    assert "microphone" in text and "off" in text
    assert "bad" not in str(c.page.locator("#vWakeChip").get_attribute("class"))


# ================================================================== the mic button with the lock
def test_pressing_the_mic_while_locked_listens_to_nothing(make: Callable[..., Console]) -> None:
    c = make(scripts=(SLOW_GUM,))
    fake = FakeVoice(c.page)
    c.open()
    ev(c, "JarvisAudio.lock('button')")
    assert _mic_state(c) == "off"
    # a click with no real user behind it (a script's own, isTrusted false) does nothing, even with
    # an activation live; a real tap unlocks (test_voice_micoff.py, SM1)
    ev(c, "document.getElementById('micBtn').click()")
    c.page.wait_for_timeout(500)
    assert _mic_state(c) == "off" and ev(c, "window.__streams.length") == 0
    assert "switched off" in str(c.page.locator("#voiceLine").text_content())
    assert fake.to("POST", "/v1/voice/transcribe") == []
    assert "Mic off" in str(c.page.locator("#statusText").text_content())


def test_locking_mid_listen_cancels_the_turn_and_sends_nothing(
    make: Callable[..., Console],
) -> None:
    c = make(scripts=(SLOW_GUM,))
    fake = FakeVoice(c.page)
    c.open()
    c.page.locator("#micBtn").click()
    _wait(c, "() => document.getElementById('micBtn').dataset.state === 'listening'")
    _wait(c, "() => JarvisAudio.isOpen()")
    ev(c, "JarvisAudio.lock('voice')")
    _wait(c, "() => document.getElementById('micBtn').dataset.state === 'off'")
    c.page.wait_for_timeout(2500)
    assert ev(c, LIVE_TRACKS) == [0]
    assert fake.to("POST", "/v1/voice/transcribe") == []
    assert _mic_state(c) == "off"


def test_the_browser_recogniser_is_built_through_the_lock(make: Callable[..., Console]) -> None:
    c = make(device={"engine": "browser"}, scripts=(FAKE_RECOGNITION,))
    FakeVoice(c.page)
    c.open()
    ev(c, "window.__recSilent = true")
    c.page.locator("#micBtn").click()
    _wait(c, "() => window.__rec.length === 1")
    ev(c, "JarvisAudio.lock('voice')")
    _wait(c, "() => window.__rec[0].aborted === true")
    c.page.wait_for_timeout(300)
    assert _mic_state(c) == "off" and ev(c, "window.__rec.length") == 1


# ====================================================================== the minimal loop (item 5)
def test_the_loop_has_its_frozen_shape_and_works_on_say(make: Callable[..., Console]) -> None:
    c = make()
    FakeVoice(c.page)
    c.open()
    keys = ev(c, "Object.keys(JarvisVoiceLoop).sort()")
    assert keys == ["ask", "end", "inConversation", "offer", "say", "state"]
    assert ev(c, "JarvisVoiceLoop.state()") == "idle"
    assert ev(c, "JarvisVoiceLoop.inConversation()") is False
    ev(c, "JarvisVoiceLoop.say('Switched, Sir.', { speak: false })")
    assert str(c.page.locator("#voiceLine").text_content()) == "Switched, Sir."
    assert ev(c, "JarvisVoiceLoop.ask('Shall I?', { timeoutMs: 300 })") == "timeout"
    fire(  # (evaluate would call a function it is given back, which is the dismiss)
        c,
        "window.__ran = []; window.__dismiss = JarvisVoiceLoop.offer('Buds connected.',"
        " [{ label: 'Use Buds', run: () => window.__ran.push('use') },"
        " { label: 'Not now', run: () => {} }])",
    )
    offer = c.page.locator("#voiceOffer")
    assert "Buds connected." in str(offer.text_content())
    assert offer.locator("button").count() == 2
    offer.locator("button", has_text="Use Buds").click()
    assert ev(c, "window.__ran") == ["use"]
    assert offer.locator("button").count() == 0
    ev(c, "JarvisVoiceLoop.offer('Again.', [{ label: 'Ok', run() {} }])")
    ev(c, "JarvisVoiceLoop.end('keyboard')")
    assert ev(c, "JarvisVoiceLoop.state()") == "idle"
    ev(c, "JarvisVoiceLoop.say(42)")  # not a string: ignored, no error
    assert c.errors == []


def test_the_loop_event_follows_the_mic_state(make: Callable[..., Console]) -> None:
    c = make()
    FakeVoice(c.page)
    c.open()
    ev(c, "JarvisAudio.lock('button')")
    _wait(c, "() => JarvisVoiceLoop.state() === 'off'")
    last = events(c, "jarvis:voice-loop")[-1]
    assert last["state"] == "off" and last["conversation"] is False and last["turns"] == 0


# ====================================================================== status words and stubs
def test_status_words_for_standby_and_mic_off(make: Callable[..., Console]) -> None:
    c = make()
    FakeVoice(c.page)
    c.open()
    text = lambda: str(c.page.locator("#statusText").text_content())  # noqa: E731
    ev(c, "JarvisFX.setVoice('standby')")
    assert text() == "Standing by"
    ev(c, "JarvisFX.setVoice('micoff')")
    assert text() == "Mic off" and ev(c, "document.documentElement.dataset.voice") == "micoff"
    ev(c, "JarvisFX.setVoice('bogus')")
    assert text() == "Online"
    ev(c, "JarvisFX.setVoice('listening')")
    assert text() == "Listening"


def test_the_real_page_defines_the_device_matcher_and_the_route(
    make: Callable[..., Console],
) -> None:
    # B's matcher must load before the devices module in console.html itself (I1): its own tests
    # add it with add_init_script, which would hide a missing <script> tag
    c = make()
    FakeVoice(c.page)
    c.open()
    assert ev(c, "typeof window.JarvisAudioMatch") == "object"
    assert ev(c, "typeof window.JarvisAudioRoute") == "object"
    assert ev(c, "Object.isFrozen(JarvisAudioMatch) && Object.isFrozen(JarvisAudioRoute)") is True
    assert ev(c, "typeof window.JarvisAudioRoutePrefs") == "object"
    # the devices module ran to its end: its voice commands are registered in the real page
    assert ev(c, "JarvisVoiceCommands.owns('switch to my speaker', 'listening')") == "device.switch"
    assert c.errors == [] and c.csp_violations() == []


def test_the_modules_that_replaced_the_stubs_have_their_frozen_shapes(
    make: Callable[..., Console],
) -> None:
    c = make()
    FakeVoice(c.page)
    c.open()
    keys = lambda name: ev(c, f"Object.keys(window.{name}).sort()")  # noqa: E731
    frozen = lambda name: ev(c, f"Object.isFrozen(window.{name})")  # noqa: E731
    route = ["supported", "refresh", "current", "chooseOutput", "chooseInput", "outputKind"]
    assert keys("JarvisAudioRoute") == sorted([*route, "find", "on"])
    assert ev(c, "JarvisAudioRoute.outputKind()") in ("headphones", "speakers", "unknown")
    assert ev(c, "typeof JarvisAudioRoute.find('speaker')") == "object"  # a device or null
    barge = ["policy", "arm", "createGate", "isEcho", "BARGE", "kind", "margin", "forget"]
    assert keys("JarvisBarge") == sorted([*barge, "clipsLeft"])
    assert ev(c, "JarvisBarge.policy()") == "tap"  # the factory pins interruptBy: 'tap'
    assert keys("JarvisVoicePace") == ["cue", "last", "mark"]
    assert ev(c, "JarvisVoicePace.last()") is None  # nothing timed yet on a fresh page
    assert keys("JarvisVoicePhrases") == ["apply", "clean", "list"]
    for name in ("JarvisAudioRoute", "JarvisAudioMatch", "JarvisBarge", "JarvisVoicePace",
                 "JarvisVoicePhrases"):  # fmt: skip
        assert frozen(name) is True, name
    assert c.errors == [] and c.csp_violations() == []
