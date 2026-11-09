# ruff: noqa: E501  (long lines are JS snippets and prose)
# Size: this file is over the 800-line soft ceiling on purpose. Test files are exempt (docs/plans/r5-voice.md,
# "Line counts"), and its tests share one set of fixtures (the fake microphones, the tone mic, the TV rooms,
# the stall and hang scripts) that every R5 voice test file imports; splitting it would copy them.
# tests/browser/test_voice_robust.py — slice 9 console voice, the review's findings (docs/plans/
# phase1-slice9-voice.md §9 "Review findings and fixes (console)"): open/close races on the
# microphone, the conversation loop ending by itself, wake-word failures surfaced, wall-clock
# listening limits and an unplugged microphone, the browser-voice watchdog, Esc while JARVIS is
# thinking, a late wake-word script, Chromium's real autoplay rules (a second browser launched
# WITHOUT --autoplay-policy=no-user-gesture-required), pause/resume of the wake word around
# speech, bfcache, the chunker's lists and indented code, accessible names and announcements, and
# the allowance / rate-limit contract of GET /v1/voice and PUT /v1/voice/settings.
from __future__ import annotations

import json
import time
from collections.abc import Callable, Iterator
from typing import Any

import pytest
from test_console import DESKTOP, Console
from test_voice import (  # same directory (pytest prepend import)
    FAKE_RECOGNITION,
    FAKE_SYNTH,
    FAKE_WAKE,
    RECORDER,
    FakeVoice,
    _json,
    _mic_state,
    _speech,
    _voice_panel,
    _wait,
    speechlike_wav,
    voice_view,
    wav_bytes,
)

_pw = pytest.importorskip("playwright.sync_api")

pytestmark = pytest.mark.browser

FAKE_MEDIA = ["--use-fake-ui-for-media-stream", "--use-fake-device-for-media-stream"]
# Beyond test_voice's RECORDER: the voice states with their time, and the wake-word states the
# console reports (jarvis:wake), recorded from before any script runs.
RECORD_MORE = """
window.__states = [];
window.__wakeStates = [];
document.addEventListener('jarvis:state', (e) => {
  window.__states.push({ voice: e.detail.voice || null, at: performance.now() });
});
document.addEventListener('jarvis:wake', (e) => window.__wakeStates.push(e.detail.state));
"""


@pytest.fixture(scope="module")
def _playwright() -> Iterator[Any]:
    p = _pw.sync_playwright().start()  # one driver for both browsers below
    yield p
    p.stop()


@pytest.fixture(scope="module")
def _mic_file(tmp_path_factory: pytest.TempPathFactory) -> str:
    mic = tmp_path_factory.mktemp("voice-robust") / "speech.wav"
    speechlike_wav(mic)
    return str(mic)


def _launch(p: Any, mic: str, autoplay: bool) -> Any:
    args = [*FAKE_MEDIA, f"--use-file-for-fake-audio-capture={mic}"]
    if autoplay:
        args.append("--autoplay-policy=no-user-gesture-required")
    return p.chromium.launch(args=args)


@pytest.fixture(scope="module")
def browser(_playwright: Any, _mic_file: str) -> Iterator[Any]:
    """Like test_voice's: the looping speech-like fake microphone, autoplay allowed."""
    b = _launch(_playwright, _mic_file, autoplay=True)
    yield b
    b.close()


@pytest.fixture(scope="module")
def strict_browser(_playwright: Any, _mic_file: str) -> Iterator[Any]:
    """Chromium's own autoplay rules: audio made without a user gesture stays suspended."""
    b = _launch(_playwright, _mic_file, autoplay=False)
    yield b
    b.close()


def _factory(browser: Any, url: str, token: str, made: list[Console]) -> Callable[..., Console]:
    def factory(
        device: dict[str, Any] | None = None,
        scripts: tuple[str, ...] = (),
        real_wake: bool = False,
        barge: bool = False,
    ) -> Console:
        c = Console(browser, url, token, DESKTOP)
        if not real_wake:  # the real module is tested on its own; these use FAKE_WAKE or none
            c.page.route(
                "**/static/console-wakeword.js",
                lambda r: r.fulfill(status=200, content_type="text/javascript", body=""),
            )
        c.page.add_init_script(RECORDER)
        c.page.add_init_script(RECORD_MORE)
        # R5: the fake microphones talk constantly, so tests that are not about interrupting pin
        # "Tapping only" (docs/plans/r5-voice.md I0 item 9) unless they ask for barge-in.
        pinned = dict(device or {})
        if not barge:
            pinned.setdefault("interruptBy", "tap")
        if pinned:  # this device's voice settings, set before any script runs
            # only the pin alone must not undo what the page saved before a reload
            keep = (
                ""
                if device is not None
                else "localStorage.getItem('jarvis_voice_device_v1') === null && "
            )
            c.page.add_init_script(
                f"{keep}localStorage.setItem('jarvis_voice_device_v1', "
                f"{json.dumps(json.dumps(pinned))});"
            )
        for s in scripts:
            c.page.add_init_script(s)
        made.append(c)
        return c

    return factory


@pytest.fixture
def make(browser: Any, server_url: str, token: str) -> Iterator[Callable[..., Console]]:
    made: list[Console] = []
    yield _factory(browser, server_url, token, made)
    for c in made:
        c.close()


@pytest.fixture
def strict(strict_browser: Any, server_url: str, token: str) -> Iterator[Callable[..., Console]]:
    made: list[Console] = []
    yield _factory(strict_browser, server_url, token, made)
    for c in made:
        c.close()


# getUserMedia that answers after window.__gumDelays.shift() ms (default 0), keeping every stream.
SLOW_GUM = """
(() => {
  window.__streams = [];
  window.__gumDelays = [];
  const md = navigator.mediaDevices, real = md.getUserMedia.bind(md);
  md.getUserMedia = (c) => {
    const wait = window.__gumDelays.length ? window.__gumDelays.shift() : 0;
    return new Promise((r) => setTimeout(r, wait)).then(() => real(c))
      .then((s) => { window.__streams.push(s); return s; });
  };
})();
"""
LIVE_TRACKS = (
    "window.__streams.map(s => s.getTracks().filter(t => t.readyState === 'live').length).sort()"
)
# A microphone the test controls: a 180 Hz tone (loud enough for the VAD) switched on and off.
# __talk(on); __tv(): on 1.2 s, off 1.4 s, forever (a TV in the room); __burst(ms): on, then off.
TONE_MIC = """
(() => {
  const mic = window.__mic = { on: false, gains: [], timer: 0 };
  navigator.mediaDevices.getUserMedia = async () => {
    const ac = new AudioContext();
    try { await ac.resume(); } catch (_) {}
    const o = ac.createOscillator(); o.frequency.value = 180;
    const g = ac.createGain(); g.gain.value = mic.on ? 0.25 : 0;
    const d = ac.createMediaStreamDestination();
    o.connect(g); g.connect(d); o.start();
    mic.gains.push(g);
    return d.stream;
  };
  window.__talk = (on) => {
    mic.on = !!on;
    mic.gains.forEach((g) => { g.gain.value = mic.on ? 0.25 : 0; });
  };
  window.__tv = () => {
    clearTimeout(mic.timer);
    let on = false;
    const flip = () => {
      on = !on; window.__talk(on);
      mic.timer = setTimeout(flip, on ? 1200 : 1400);
    };
    flip();
  };
  window.__burst = (ms) => {
    clearTimeout(mic.timer); window.__talk(true);
    mic.timer = setTimeout(() => window.__talk(false), ms);
  };
})();
"""
# A faster room for the check-in tests: talks 0.9 s, pauses 1.05 s, forever (endSilenceMs 800).
FAST_TV = """
window.__tvFast = () => {
  let on = false;
  const flip = () => {
    on = !on; window.__talk(on);
    window.__mic.timer = setTimeout(flip, on ? 900 : 1050);
  };
  flip();
};
"""
# A room that answers every reply promptly: 0.6 s after JARVIS finishes (speaking, or a command that he
# answered with nothing to say) someone talks for 0.9 s, whatever he said (the questions too). Unlike FAST_TV the gap to the next turn does not depend on a
# clock's phase, so "8 quick turns" is exact. window.__replyTv() starts it; the first burst is the test's.
REPLY_TV = """
window.__replyTv = () => {
  let spoke = false;
  document.addEventListener('jarvis:voice-loop', (e) => {
    if (e.detail.state === 'speaking' || e.detail.state === 'thinking') spoke = true;
    else if (spoke && e.detail.state === 'idle') {
      spoke = false;
      setTimeout(() => { window.__talk(true); setTimeout(() => window.__talk(false), 900); }, 600);
    }
  });
};
"""
# Frames from the capture worklet stop reaching the page while window.__stall is true.
STALL = """
(() => {
  window.__stall = false;
  const Real = window.AudioWorkletNode;
  const desc = Object.getOwnPropertyDescriptor(MessagePort.prototype, 'onmessage');
  window.AudioWorkletNode = class extends Real {
    constructor(...args) {
      super(...args);
      const port = this.port;
      Object.defineProperty(port, 'onmessage', {
        configurable: true,
        get() { return desc.get.call(port); },
        set(fn) {
          const pass = (e) => { if (!window.__stall) fn(e); };
          desc.set.call(port, typeof fn === 'function' ? pass : fn);
        },
      });
    }
  };
})();
"""
# The browser voice where an utterance can end without ever saying so (Chrome's network voices).
_SPEAK = "speak(u) { window.__synth.push(u.text); "
STUCK_SYNTH = FAKE_SYNTH.replace(_SPEAK, _SPEAK + "if (window.__synth.length === 1) return; ")
assert STUCK_SYNTH != FAKE_SYNTH
# AudioContext.resume() that never settles while window.__hang (the context stays 'suspended').
HANG_RESUME = """
(() => {
  window.__hang = false;
  const proto = AudioContext.prototype, real = proto.resume;
  const desc = Object.getOwnPropertyDescriptor(BaseAudioContext.prototype, 'state');
  proto.resume = function () { return window.__hang ? new Promise(() => {}) : real.call(this); };
  Object.defineProperty(proto, 'state', { configurable: true,
    get() { return window.__hang ? 'suspended' : desc.get.call(this); } });
})();
"""
# A wake-word module that fails while listening (openWakeWord's too_slow / inference_failed).
ERR_WAKE = """
window.__wake = { started: 0, stopped: 0 };
window.JarvisWake = {
  state: 'idle',
  supported: () => true,
  load() { return Promise.resolve(); },
  start(opts, onWake) {
    window.__wake.started++;
    window.JarvisWake.state = 'listening';
    const off = opts.subscribe(() => {});
    setTimeout(() => { off(); window.JarvisWake.state = 'error'; }, 300);
  },
  pause() {}, resume() {},
  stop() { window.__wake.stopped++; window.JarvisWake.state = 'idle'; },
};
"""
IDLE = (
    "() => document.getElementById('micBtn').dataset.state === 'idle'"
    " && !window.JarvisVoice.speaker.speaking()"
)
LISTENING = "() => document.getElementById('micBtn').dataset.state === 'listening'"


def _until(c: Console, js: str, timeout_s: float = 15.0) -> None:
    """Poll with evaluate (not wait_for_function: some tests fake the page's clock)."""
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if c.page.evaluate(js):
            return
        c.page.wait_for_timeout(100)
    raise AssertionError(f"timed out waiting for {js}")


def chat_reply(approvals: int = 0, text: str = "Done, Sir. It is ready to send.") -> dict[str, Any]:
    """A /v1/chat answer with fixed words (the test server's own reply repeats the transcript, which his
    echo guard rightly treats as his voice coming back when a loop test says the same thing every turn)."""
    pending = {
        "id": "ap1", "tool": "gmail_send", "summary": "Send the email to Priya", "arguments": {},
        "risk": "R3", "expires_at": "2026-11-01T12:00:00Z", "session_id": "s-voice",
    }  # fmt: skip
    return {
        "session_id": "s-voice", "reply": text, "tool_calls": 0,
        "pending_approvals": [pending] * approvals, "trace_id": "t1", "model": "mock", "brain": "mock",
        "usage": {"input_tokens": 1, "output_tokens": 1}, "cost_usd": 0, "cost_inr": 0,
        "total_cost_usd": 0, "total_cost_inr": 0, "latency_ms": 5, "turn_count": 2, "memory_used": [],
    }  # fmt: skip


def route_reply(c: Console, reply: dict[str, Any] | None = None) -> list[int]:
    """Answer every chat turn with `reply`; the returned list gets a 1 per message sent."""
    sent: list[int] = []
    body = reply if reply is not None else chat_reply(text="Noted, Sir.")
    c.page.route("**/v1/chat", lambda r: (sent.append(1), _json(r, 200, body)))
    return sent


def _count(fake: FakeVoice, path: str) -> int:
    return len(fake.to("POST", path))


def _chat_counter(c: Console) -> list[int]:
    chats: list[int] = []
    c.page.route("**/v1/chat", lambda r: (chats.append(1), r.continue_()))
    return chats


def _line(c: Console) -> str:
    return str(c.page.locator("#voiceLine").text_content())


# ================================================================== 1 · open / close races
def test_close_while_the_microphone_is_still_opening_leaves_nothing_live(
    make: Callable[..., Console],
) -> None:
    c = make(scripts=(SLOW_GUM,))
    c.open()
    got = c.page.evaluate(
        """async () => {
      const A = window.JarvisAudio;
      window.__gumDelays = [600];
      const p = A.open().then(() => 'ok', (e) => 'rejected:' + (e && e.code));
      A.close();
      const r = await p;
      await new Promise((res) => setTimeout(res, 300));
      return { r, open: A.isOpen() };
    }"""
    )
    assert got == {"r": "rejected:closed", "open": False}
    assert c.page.evaluate(LIVE_TRACKS) == [0]  # the late stream stopped its own tracks
    assert c.errors == []


def test_open_close_open_keeps_only_the_newest_microphone(make: Callable[..., Console]) -> None:
    c = make(scripts=(SLOW_GUM,))
    c.open()
    got = c.page.evaluate(
        """async () => {
      const A = window.JarvisAudio, sleep = (ms) => new Promise((r) => setTimeout(r, ms));
      window.__gumDelays = [900, 100];  // the first answer arrives last
      const p1 = A.open().then(() => 'ok', (e) => 'rejected:' + (e && e.code));
      A.close();
      const p2 = A.open().then(() => 'ok', (e) => 'rejected:' + (e && e.code));
      const r = [await p1, await p2];
      await sleep(300);
      const open = A.isOpen();
      let frames = 0;
      const off = A.subscribe(() => { frames++; });
      await sleep(600);
      off();
      A.close();
      await sleep(200);
      return { r, open, frames, openAfter: A.isOpen() };
    }"""
    )
    assert got["r"] == ["rejected:closed", "ok"]
    assert got["open"] is True and got["frames"] > 2 and got["openAfter"] is False
    assert c.page.evaluate(LIVE_TRACKS) == [0, 0]  # close() stopped the one it owned
    assert c.errors == []


def test_tap_escape_tap_with_the_first_microphone_answering_last(
    make: Callable[..., Console],
) -> None:
    c = make(device={"keepListening": False}, scripts=(SLOW_GUM,))
    fake = FakeVoice(c.page)
    c.open()
    c.page.evaluate("window.__gumDelays = [1500, 100]")
    mic = c.page.locator("#micBtn")
    mic.click()
    c.page.wait_for_timeout(300)
    c.page.keyboard.press("Escape")
    assert _mic_state(c) == "idle"
    mic.click()  # the second microphone answers first; the first one 1.2 s later
    _wait(c, "() => window.__voice.speech.length >= 2", 25000)  # heard, sent, answered aloud
    _wait(c, IDLE, 10000)
    c.page.wait_for_timeout(1500)
    assert _mic_state(c) == "idle"
    assert c.page.evaluate("window.JarvisAudio.isOpen()") is False
    assert c.page.evaluate(LIVE_TRACKS) == [0, 0]  # no microphone left on
    assert _count(fake, "/v1/voice/transcribe") == 1
    assert c.errors == []


# ================================================================== 2 · the conversation loop ends
def test_conversation_is_not_capped(make: Callable[..., Console]) -> None:
    # the browser recognition always hears something, at a human pace: 12 turns and still going
    c = make(device={"engine": "browser", "checkIn": False}, scripts=(FAKE_RECOGNITION,))
    FakeVoice(c.page)
    chats = _chat_counter(c)
    c.open()
    c.page.locator("#micBtn").click()
    _wait(c, "() => window.__rec.length >= 12", 120000)
    assert len(chats) >= 11  # the old cap stopped at 4
    assert "Tap the mic" not in _line(c)
    c.page.keyboard.press("Escape")
    assert c.errors == []


def test_a_room_that_never_stops_talking_gets_a_check_in_then_the_keyboard(
    make: Callable[..., Console],
) -> None:
    c = make(device={"speak": "always", "endSilenceMs": 800}, scripts=(TONE_MIC, REPLY_TV))
    fake = FakeVoice(c.page)
    route_reply(c)
    c.open()
    c.page.evaluate("window.__replyTv()")  # someone answers every reply, promptly, forever
    c.page.evaluate("window.__talk(true)")  # the first words, as the tap opens the microphone
    c.page.locator("#micBtn").click()
    _until(c, "document.getElementById('voiceLive').textContent === 'Hearing you'", 10)
    c.page.wait_for_timeout(500)
    c.page.evaluate("window.__talk(false)")
    question = "Shall I keep listening, Sir?"
    deadline = time.monotonic() + 150
    while time.monotonic() < deadline and question not in fake.spoken():
        c.page.wait_for_timeout(500)
    assert question in fake.spoken()
    # D6: the tap's turn, then 8 quick hands-free turns; he asks at the end of the 8th hands-free reply
    assert _count(fake, "/v1/voice/transcribe") == 9
    _until(
        c,
        "document.getElementById('micBtn').dataset.state === 'idle'"
        " && !JarvisVoice.speaker.speaking()",
        60,
    )
    assert "I'll switch to the keyboard, Sir." in fake.spoken()  # the room never says yes
    assert c.page.evaluate("window.JarvisAudio.isOpen()") is False
    assert c.errors == []


def test_silence_goes_to_standby_at_8_s_and_hands_over_at_20_s(
    make: Callable[..., Console],
) -> None:
    c = make(device={"speak": "always"}, scripts=(TONE_MIC,))
    fake = FakeVoice(c.page)
    c.open()
    c.page.evaluate(
        "window.__t = []; document.addEventListener('jarvis:voice-loop', (e) =>"
        " window.__t.push({ s: e.detail.state, at: performance.now() }));"
    )
    ended = (
        "(() => { const i = window.__t.map(x => x.s).lastIndexOf('speaking');"
        " return i < 0 || !window.__t[i + 1] ? null : window.__t[i + 1].at; })()"
    )
    c.page.evaluate("window.__talk(true)")  # one sentence, then a quiet room
    c.page.locator("#micBtn").click()
    _until(c, "document.getElementById('voiceLive').textContent === 'Hearing you'", 10)
    c.page.wait_for_timeout(500)
    c.page.evaluate("window.__talk(false)")
    _wait(c, "() => window.__voice.speech.length >= 2", 20000)
    _wait(c, "() => document.getElementById('micBtn').dataset.state === 'standby'", 14000)
    end = c.page.evaluate(ended)
    stand = c.page.evaluate("window.__t.find(x => x.s === 'standby').at")
    assert 7000 < stand - end < 9800, (end, stand)
    assert c.page.locator("#statusText").text_content() == "Standing by"
    _until(c, "window.__t.some(x => x.s === 'handover')", 20)
    hand = c.page.evaluate("window.__t.find(x => x.s === 'handover').at") - end
    assert 18000 < hand < 23500, hand
    assert "I'll switch to the keyboard, Sir." in fake.spoken()
    _wait(c, IDLE, 15000)
    assert "Switched to the keyboard" in _line(c)
    assert c.page.evaluate("window.JarvisAudio.isOpen()") is False
    assert c.errors == []


def test_a_wake_word_turn_has_no_turn_limit_either(make: Callable[..., Console]) -> None:
    c = make(
        device={"engine": "browser", "wake": True, "checkIn": False},
        scripts=(FAKE_WAKE, FAKE_RECOGNITION),
    )
    FakeVoice(c.page)
    c.open()
    _wait(c, "() => window.__wake.started === 1")
    c.page.evaluate("window.__wake.fire({ score: 0.9 })")
    _wait(
        c, "() => window.__rec.length >= 6", 60000
    )  # "Hey Jarvis" + 5 follow-ups, and still going
    c.page.keyboard.press("Escape")
    assert c.errors == []


# ================================================================== 3 · wake-word failures surface
def test_a_wake_word_module_that_fails_while_listening_is_switched_off_plainly(
    make: Callable[..., Console],
) -> None:
    c = make(device={"wake": True, "keepListening": False}, scripts=(ERR_WAKE,))
    FakeVoice(c.page)
    c.open()
    _voice_panel(c)
    chip = c.page.locator("#vWakeChip.bad")
    chip.wait_for(timeout=6000)
    assert "switched off" in str(chip.text_content())
    assert c.page.locator("#vWake").get_attribute("aria-pressed") == "false"
    saved = json.loads(c.page.evaluate("localStorage.getItem('jarvis_voice_device_v1')"))
    assert saved["wake"] is False
    assert c.page.evaluate("window.JarvisAudio.isOpen()") is False  # nothing else used the mic
    assert c.errors == []


# ======================================================== 4 · wall-clock limits, unplugged mic
def test_listening_ends_on_the_clock_when_the_microphone_sends_nothing(
    make: Callable[..., Console],
) -> None:
    c = make(device={"keepListening": False}, scripts=(STALL,))
    fake = FakeVoice(c.page)
    c.open()
    c.page.evaluate("window.__stall = true")
    c.page.locator("#micBtn").click()
    _wait(c, "() => window.JarvisAudio.isOpen()", 8000)
    t0 = time.monotonic()
    _wait(c, IDLE, 12000)
    assert 4.5 < time.monotonic() - t0 < 8.5
    assert "didn't hear" in _line(c)
    assert _count(fake, "/v1/voice/transcribe") == 0
    assert c.page.evaluate("window.JarvisAudio.isOpen()") is False
    assert c.errors == []


def test_listening_is_capped_at_fifty_five_seconds_on_the_clock(
    make: Callable[..., Console],
) -> None:
    c = make(device={"keepListening": False}, scripts=(STALL, TONE_MIC))
    fake = FakeVoice(c.page)
    fake.hold_transcribe = True
    c.open()
    c.page.clock.install()
    c.page.evaluate("window.__talk(true)")
    c.page.locator("#micBtn").click()
    _until(c, "document.getElementById('voiceLive').textContent === 'Hearing you'", 10)
    c.page.wait_for_timeout(800)  # a second of speech so far
    c.page.evaluate("window.__stall = true")  # mid-sentence the frames stop coming
    c.page.wait_for_timeout(500)
    assert _mic_state(c) == "listening" and fake.held_transcribe == []
    c.page.clock.fast_forward(56000)
    _until(c, "document.getElementById('micBtn').dataset.state !== 'listening'", 5)
    for _ in range(30):
        if fake.held_transcribe:
            break
        c.page.wait_for_timeout(100)
    assert len(fake.held_transcribe) == 1  # what was heard so far is sent
    sent = c.page.evaluate("window.__sent.find(s => s.path === '/v1/voice/transcribe')")
    assert sent and sent["size"] > 44 + 4 * 2560
    fake.release_transcribe()
    assert c.errors == []


def test_an_unplugged_microphone_ends_listening_and_says_so(make: Callable[..., Console]) -> None:
    c = make(device={"keepListening": False}, scripts=(SLOW_GUM, STALL))
    fake = FakeVoice(c.page)
    c.open()
    c.page.evaluate("window.__stall = true")  # nothing heard yet, so only the unplug ends it
    c.page.locator("#micBtn").click()
    _wait(c, "() => window.JarvisAudio.isOpen() && window.__streams.length === 1")
    c.page.evaluate("window.__streams[0].getAudioTracks()[0].dispatchEvent(new Event('ended'))")
    _wait(c, IDLE, 2000)
    assert "microphone stopped" in str(c.page.locator("#micHelp").text_content())
    assert c.page.evaluate("window.JarvisAudio.isOpen()") is False
    assert c.page.evaluate("window.__streams[0].getAudioTracks()[0].readyState") == "ended"
    assert _count(fake, "/v1/voice/transcribe") == 0
    assert c.errors == []


# ================================================================== 5 · the browser voice watchdog
def test_browser_voice_moves_on_when_an_utterance_never_ends(make: Callable[..., Console]) -> None:
    c = make(
        device={"engine": "browser", "keepListening": False},
        scripts=(FAKE_RECOGNITION, STUCK_SYNTH),
    )
    fake = FakeVoice(c.page)
    fake.speak_status = 503
    c.open()
    c.page.locator("#micBtn").click()
    _wait(c, "() => window.__synth.length >= 2", 15000)  # the first never said it ended
    assert c.page.evaluate("window.__synth") == [
        "Certainly, Sir.",
        "You said: Remind me about the review.",
    ]
    _wait(c, IDLE, 5000)
    assert c.errors == [] or all("status of" in e for e in c.errors)


def test_browser_voice_reads_long_chunks_in_short_pieces(make: Callable[..., Console]) -> None:
    c = make(device={"speak": "always"}, scripts=(FAKE_SYNTH,))
    FakeVoice(c.page, voice_view(cloud={"tts": "off", "stt": "off", "reason": None}))
    c.open()
    _voice_panel(c)  # loads the voice config: the cloud voice is off, so the browser speaks
    sentence = "This sentence is long enough to be part of a chunk of its own."
    c.send("One. " + " ".join([sentence] * 6))
    _wait(c, "() => window.__synth.length >= 3", 15000)
    _wait(c, IDLE, 15000)
    said = c.page.evaluate("window.__synth")
    assert all(len(t) <= 180 for t in said), [len(t) for t in said]
    assert " ".join(said).count(sentence) == 6  # every word, in order, nothing lost at the cuts
    assert c.errors == []


def test_a_resume_the_browser_never_settles_does_not_hang_speech(
    make: Callable[..., Console],
) -> None:
    c = make(device={"speak": "always"}, scripts=(HANG_RESUME, FAKE_SYNTH))
    FakeVoice(c.page)
    c.open()
    c.page.evaluate("window.__hang = true")
    c.send("Hello there.")
    _wait(c, "() => window.__synth.length >= 1", 10000)  # said with the browser's voice
    _wait(c, IDLE, 10000)
    assert "tap the page" in _line(c).lower()
    assert c.errors == []


# ================================================================== 6 · Esc while thinking
def test_escape_while_transcribing_drops_the_words(make: Callable[..., Console]) -> None:
    c = make(device={"keepListening": False})
    fake = FakeVoice(c.page)
    fake.hold_transcribe = True
    chats = _chat_counter(c)
    c.open()
    c.page.locator("#micBtn").click()
    for _ in range(150):
        if fake.held_transcribe:
            break
        c.page.wait_for_timeout(100)
    assert fake.held_transcribe and _mic_state(c) == "thinking"
    c.page.keyboard.press("Escape")
    assert _mic_state(c) == "idle"
    assert c.page.locator("#voiceLive").text_content() == "Cancelled"
    fake.release_transcribe()
    c.page.wait_for_timeout(1500)
    assert chats == [] and c.page.locator(".row.user").count() == 0
    assert _mic_state(c) == "idle"
    assert c.errors == []


def test_escape_while_jarvis_answers_mutes_that_answer(make: Callable[..., Console]) -> None:
    c = make(device={"keepListening": True})
    fake = FakeVoice(c.page)
    held: list[Any] = []
    c.page.route("**/v1/chat", lambda r: held.append(r))
    c.open()
    c.page.locator("#micBtn").click()
    for _ in range(150):
        if held:
            break
        c.page.wait_for_timeout(100)
    assert held and _mic_state(c) == "thinking"
    c.page.keyboard.press("Escape")
    assert _mic_state(c) == "idle"
    held[0].continue_()
    c.page.locator(".row.jarvis .bubble:not(.typing)").first.wait_for()  # shown on screen
    c.page.wait_for_timeout(1500)
    assert fake.to("POST", "/v1/voice/speak") == [] and _speech(c) == []  # not spoken
    assert _mic_state(c) == "idle"  # and no conversation-mode re-listen
    assert c.errors == []


# ================================================================== 7 · a late wake-word script
def test_a_saved_wake_word_starts_when_its_script_arrives_late(
    make: Callable[..., Console], token: str
) -> None:
    c = make(
        device={"wake": True, "keepListening": False},
        scripts=(f"sessionStorage.setItem('jarvis_token', {json.dumps(token)});",),
    )
    FakeVoice(c.page)

    def slow(route: Any) -> None:
        time.sleep(2.5)
        route.fulfill(status=200, content_type="text/javascript", body=FAKE_WAKE)

    c.page.route("**/static/console-wakeword.js", slow)  # the newest route answers first
    c.page.goto(c.url + "/")
    c.page.locator("#welcome").wait_for()
    _wait(c, "() => window.__wake && window.__wake.started === 1", 10000)
    assert c.page.evaluate(
        "[...document.scripts].findIndex(s => s.src.endsWith('/console-wakeword.js'))"
        " < [...document.scripts].findIndex(s => s.src.endsWith('/console-voice-mic.js'))"
    )
    assert c.errors == []


def test_a_wake_word_module_that_appears_after_boot_is_picked_up(
    make: Callable[..., Console],
) -> None:
    c = make(device={"wake": True, "keepListening": False})
    FakeVoice(c.page)
    c.open()
    c.page.wait_for_timeout(600)
    c.page.evaluate(FAKE_WAKE)
    _wait(c, "() => window.__wake.started === 1 && window.__wake.frames > 0", 6000)
    assert c.errors == []


# ================================================================== 8 · tests that would catch it
def test_tap_again_sends_what_the_browser_heard(make: Callable[..., Console]) -> None:
    c = make(
        device={"engine": "browser", "keepListening": False},
        scripts=(FAKE_RECOGNITION, "window.__recEndMs = 60000;"),  # only a tap can end it
    )
    FakeVoice(c.page)
    c.open()
    c.page.locator("#micBtn").click()
    c.page.wait_for_function("() => document.getElementById('input').value === 'Remind'")
    c.page.locator("#micBtn").click()  # tap again: stop and send
    c.page.locator(".row.user .bubble", has_text="Remind me about the review.").wait_for(
        timeout=4000
    )
    assert c.page.evaluate("window.__rec[0].stopped") is True
    assert c.errors == []


def _open_signed_in(c: Console, token: str) -> None:
    """Load the console with the token already stored: no sign-in typing, so no user gesture."""
    c.page.add_init_script(f"sessionStorage.setItem('jarvis_token', {json.dumps(token)});")
    c.page.goto(c.url + "/")
    c.page.locator("#welcome").wait_for()


def test_strict_autoplay_mic_to_reply_spoken(strict: Callable[..., Console]) -> None:
    c = strict(device={"keepListening": False})
    fake = FakeVoice(c.page)
    c.open()
    c.page.locator("#micBtn").click()  # the tap unlocks playback for the reply
    c.page.locator(".row.user").first.wait_for(timeout=20000)
    _wait(c, "() => window.__voice.speech.length >= 2", 15000)
    assert _speech(c) == ["Certainly, Sir.", "You said: Turn on the lights. Then dim them to half."]
    assert len(fake.to("POST", "/v1/voice/speak")) == 2
    _wait(c, IDLE, 10000)
    assert c.errors == [] and c.csp_violations() == []


def test_strict_autoplay_barge_in(strict: Callable[..., Console]) -> None:
    c = strict(device={"speak": "always", "keepListening": False})
    fake = FakeVoice(c.page)
    fake.speak_audio = wav_bytes(seconds=4.0)
    c.open()
    c.send("One. " + "This sentence is long enough to be part of a chunk of its own. " * 14)
    _wait(c, "() => window.__voice.speech.length >= 1")
    assert _mic_state(c) == "speaking"
    c.page.locator("#micBtn").click()
    assert c.page.evaluate("window.JarvisVoice.speaker.speaking()") is False
    assert _mic_state(c) == "listening"
    c.page.keyboard.press("Escape")
    assert _mic_state(c) == "idle" and len(_speech(c)) == 1
    assert c.errors == []


def test_strict_autoplay_saved_wake_word_waits_for_a_tap_then_listens(
    strict: Callable[..., Console], token: str
) -> None:
    c = strict(device={"wake": True, "keepListening": False}, scripts=(FAKE_WAKE,))
    FakeVoice(c.page)
    _open_signed_in(c, token)  # a reload: no gesture yet, so the capture context stays suspended
    c.page.wait_for_timeout(2500)  # (no evaluate before this point: it would count as a gesture)
    got = c.page.evaluate(
        "({ states: window.__wakeStates, suspended: window.JarvisAudio.suspended(),"
        " frames: window.__wake.frames })"
    )
    assert "resume" in got["states"] and got["suspended"] is True and got["frames"] == 0
    c.page.locator("#scroll").click()  # tap anywhere
    _wait(c, "() => window.__wake.frames >= 3", 8000)
    assert c.page.evaluate("window.JarvisAudio.suspended()") is False
    assert c.page.evaluate("window.__wakeStates.at(-1)") == "on"
    assert c.errors == []


# ======================================================== 9 · wake word paused around speech
def test_wake_word_is_paused_while_jarvis_speaks_and_resumes_after_the_echo(
    make: Callable[..., Console],
) -> None:
    c = make(device={"speak": "always", "wake": True, "keepListening": False}, scripts=(FAKE_WAKE,))
    fake = FakeVoice(c.page)
    fake.speak_audio = wav_bytes(seconds=1.5)
    c.open()
    _wait(c, "() => window.__wake.started === 1 && window.__wake.frames >= 3")
    c.send("Read this out.")
    _wait(c, "() => window.JarvisVoice.speaker.speaking()")
    assert c.page.evaluate("window.JarvisWake.state") == "paused"
    before = c.page.evaluate("window.__wake.frames")
    c.page.wait_for_timeout(700)
    assert c.page.evaluate("window.__wake.frames") == before  # no frames while JARVIS speaks
    _wait(c, IDLE, 15000)
    _wait(c, "() => window.JarvisWake.state === 'listening'", 3000)
    got = c.page.evaluate(
        """() => {
      const ends = window.__states.filter((s, i, all) => i && all[i - 1].voice === 'speaking'
        && s.voice !== 'speaking');
      return { quiet: ends.at(-1).at, resumed: window.__wake.resumedAt };
    }"""
    )
    assert got["resumed"] - got["quiet"] >= 350, got  # the echo of the last clip is not heard
    assert c.errors == []


def test_wake_word_runs_while_jarvis_speaks_under_the_name_policy_at_a_stricter_score(
    make: Callable[..., Console],
) -> None:
    c = make(
        device={"speak": "always", "wake": True, "keepListening": False, "interruptBy": "name"},
        scripts=(FAKE_WAKE, "window.JarvisWake.threshold = 0.5;"),
    )
    fake = FakeVoice(c.page)
    fake.speak_audio = wav_bytes(seconds=2.5)
    c.open()
    _wait(c, "() => window.__wake.started === 1 && window.__wake.frames >= 3")
    c.send("Read this out.")
    _wait(c, "() => window.JarvisVoice.speaker.speaking()")
    _wait(
        c, "() => window.JarvisWake.state === 'listening'", 3000
    )  # not paused: it hears "Hey Jarvis" over him
    assert c.page.evaluate("window.JarvisWake.threshold") == 0.6
    _wait(c, IDLE, 15000)
    _wait(
        c,
        "() => window.JarvisWake.state === 'listening' && window.JarvisWake.threshold === 0.5",
        3000,
    )
    assert c.errors == []


# ================================================================== 10 · bfcache
def test_pagehide_stops_the_wake_word_and_a_bfcache_return_restarts_it(
    make: Callable[..., Console],
) -> None:
    c = make(device={"wake": True, "keepListening": False}, scripts=(FAKE_WAKE,))
    FakeVoice(c.page)
    c.open()
    _wait(c, "() => window.__wake.started === 1 && window.__wake.frames >= 2")
    c.page.evaluate(
        "window.dispatchEvent(new PageTransitionEvent('pagehide', { persisted: true }))"
    )
    assert c.page.evaluate("window.__wake.stopped") == 1
    assert c.page.evaluate("window.JarvisAudio.isOpen()") is False
    frames = c.page.evaluate("window.__wake.frames")
    c.page.evaluate(
        "window.dispatchEvent(new PageTransitionEvent('pageshow', { persisted: true }))"
    )
    _wait(c, f"() => window.__wake.started === 2 && window.__wake.frames > {frames}", 6000)
    assert json.loads(c.page.evaluate("localStorage.getItem('jarvis_voice_device_v1')"))["wake"]
    assert c.errors == []


# ================================================================== 12 · names and announcements
def test_mic_button_name_is_stable_and_its_state_is_pressed_and_announced(
    make: Callable[..., Console],
) -> None:
    c = make(device={"speak": "always", "keepListening": False})
    fake = FakeVoice(c.page)
    fake.speak_audio = wav_bytes(seconds=2.0)
    c.open()
    mic = c.page.locator("#micBtn")
    live = c.page.locator("#voiceLive")
    assert mic.get_attribute("aria-label") == "Voice input"
    assert mic.get_attribute("aria-pressed") == "false"
    mic.click()
    assert mic.get_attribute("aria-label") == "Voice input"
    assert mic.get_attribute("aria-pressed") == "true"
    assert live.text_content() in {"Listening", "Hearing you"}
    c.page.keyboard.press("Escape")
    assert mic.get_attribute("aria-pressed") == "false" and live.text_content() == "Cancelled"
    c.send("Say something.")
    _wait(c, "() => document.getElementById('micBtn').dataset.state === 'speaking'")
    assert mic.get_attribute("aria-label") == "Voice input"
    assert mic.get_attribute("aria-pressed") == "false" and live.text_content() == "Speaking"
    c.page.keyboard.press("Escape")
    c.page.evaluate(
        "JarvisAudio.lock('button')"
    )  # off: still the same name, not pressed, announced
    assert (
        mic.get_attribute("aria-label") == "Voice input"
        and mic.get_attribute("data-state") == "off"
    )
    assert mic.get_attribute("aria-pressed") == "false" and live.text_content() == "Microphone off"
    assert c.errors == []


WATCH_LIVE = """() => {
  window.__said = [];
  const row = document.getElementById('vWakeRow');
  const live = () => [...row.querySelectorAll('[aria-live], [role=status], [role=alert]')]
    .filter((n) => n.getAttribute('aria-live') !== 'off');
  let last = live().map((n) => n.textContent).join('|');
  new MutationObserver(() => {
    const now = live().map((n) => n.textContent).join('|');
    if (now !== last) { last = now; if (now.replace(/\\|/g, '')) window.__said.push(now); }
  }).observe(row, { subtree: true, childList: true, characterData: true });
}"""


def test_wake_chip_announces_real_changes_only(make: Callable[..., Console]) -> None:
    c = make(device={"keepListening": False}, scripts=(FAKE_WAKE,))
    FakeVoice(c.page)
    c.open()
    _voice_panel(c)
    c.page.evaluate(WATCH_LIVE)
    c.page.locator("#vWake").click()
    _wait(c, "() => window.__wake.frames >= 3")
    for _ in range(2):  # listen, cancel: the chip flips to "Paused" and back, silently
        c.page.evaluate("window.__wake.fire({ score: 0.9 })")
        c.page.wait_for_timeout(300)
        c.page.keyboard.press("Escape")
        _wait(c, "() => window.JarvisWake.state === 'listening'", 3000)
    assert c.page.locator("#vWakeChip").text_content() == "Listening for ‘Hey Jarvis’"
    said = c.page.evaluate("window.__said")
    assert said == ["Loading the wake word…", "Listening for ‘Hey Jarvis’"], said
    live = c.page.locator("#vWakeRow [aria-live='polite']")
    assert live.count() == 1
    assert c.errors == []


# ================================================================== the allowance and rate limits
def test_allowance_line_counts_against_the_free_allowance_and_says_when_it_resets(
    make: Callable[..., Console],
) -> None:
    c = make()
    FakeVoice(c.page)
    c.open()
    panel = _voice_panel(c)
    text = str(panel.locator("#vAllow").text_content())
    assert text == "This month: 12,340 of 900,000 free characters · 3 of 54 free minutes · ≈ ₹0.00"
    fine = str(panel.locator("#vUseT ~ .bfine").text_content())
    assert "resets on 1 Dec" in fine and "Pacific" in fine
    assert c.errors == []


def test_allowance_line_says_priced_when_there_is_no_free_allowance(
    make: Callable[..., Console],
) -> None:
    c = make()
    view = voice_view(month={"month": "2026-11", "voice_inr": 3.2})
    view["allowance"]["tts"]["free_chars"] = 0
    view["allowance"]["stt"]["free_seconds"] = 0
    FakeVoice(c.page, view)
    c.open()
    panel = _voice_panel(c)
    text = str(panel.locator("#vAllow").text_content())
    assert " of 0 free" not in text
    assert text == "This month: 12,340 characters, priced · 3 minutes, priced · ≈ ₹3.20"
    assert "priced" in str(panel.locator("#vUseT ~ .bfine").text_content())
    assert c.errors == []


def test_a_rate_limited_voice_view_is_not_asked_again_at_once(
    make: Callable[..., Console],
) -> None:
    c = make(device={"engine": "browser", "keepListening": False}, scripts=(FAKE_RECOGNITION,))
    fake = FakeVoice(c.page)
    fake.get_status = 429
    c.open()
    c.open_panel("voice")
    c.page.locator("#voiceState", has_text="Too many requests").wait_for()
    for _ in range(3):  # each tap would ask for the voice view again
        c.page.locator("#micBtn").click()
        c.page.wait_for_timeout(200)
        c.page.keyboard.press("Escape")
    assert c.page.locator("#voiceRetry").is_disabled()  # until the wait is over
    assert len(fake.to("GET", "/v1/voice")) == 1  # backed off, not hammered
    assert c.errors == [] or all("429" in e for e in c.errors)


def test_a_rate_limited_settings_save_keeps_the_change_and_saves_later(
    make: Callable[..., Console],
) -> None:
    c = make()
    fake = FakeVoice(c.page)
    fake.put_status = 429  # the first PUT only
    c.open()
    panel = _voice_panel(c)
    panel.locator("label", has_text="Measured").click()
    c.page.locator("#voiceNote.bad", has_text="again").wait_for(timeout=5000)
    assert len(fake.to("PUT", "/v1/voice/settings")) == 1
    c.page.wait_for_timeout(1500)
    assert len(fake.to("PUT", "/v1/voice/settings")) == 1  # not retried at once
    c.page.locator("#voiceNote.ok").wait_for(timeout=12000)
    puts = fake.to("PUT", "/v1/voice/settings")
    assert [p["body"] for p in puts] == [{"wit": "measured"}, {"wit": "measured"}]
    assert fake.view["settings"]["wit"] == "measured"
    assert c.errors == [] or all("429" in e for e in c.errors)


def test_an_unreadable_allowance_keeps_the_panel_usable_with_the_browser_voice(
    make: Callable[..., Console],
) -> None:
    c = make()
    fake = FakeVoice(c.page)
    fake.get_status, fake.get_code = 503, "budget_unavailable"
    c.open()
    c.open_panel("voice")
    state = c.page.locator("#voiceState")
    state.locator("p").wait_for()
    assert "voice allowance" in str(state.text_content())
    assert c.page.locator("#vDevT").is_visible()  # this device's settings still work
    assert c.page.locator("#voiceMeta").text_content() == "Browser voice"
    assert c.page.evaluate("window.JarvisVoice.outputEngine()") == "browser"
    assert c.errors == [] or all("503" in e for e in c.errors)
