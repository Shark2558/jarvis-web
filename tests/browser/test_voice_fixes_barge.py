# ruff: noqa: F811, E501  (imported fixtures; long lines are JS snippets and prose)
# tests/browser/test_voice_fixes_barge.py — R5 workstream A, the fixer's regression tests for speak-to-
# interrupt (code + security review of r5-a): the room's noise floor and learned leak (M5, SM3), one resume
# a reply and no energy interruptions after an empty one (SM3), words that keep their combining marks (M6),
# and what check clips may spend and where (SM5).
from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pytest
from test_console import Console
from test_voice import FAKE_WAKE, FakeVoice, _speech, wav_bytes
from test_voice_barge import RECORD_BARGE, _route, _start
from test_voice_robust import (  # noqa: F401  (fixtures and helpers)
    TONE_MIC,
    _count,
    _mic_file,
    _playwright,
    _until,
    browser,
    make,
)

_pw = pytest.importorskip("playwright.sync_api")

pytestmark = pytest.mark.browser

# Record the signal of every request the page makes, so a test can see it was aborted.
SIGNALS = """
(() => {
  window.__sigs = [];
  const real = window.fetch.bind(window);
  window.fetch = (u, init) => { if (init && init.signal) window.__sigs.push({ url: String(u), signal: init.signal }); return real(u, init); };
})();
"""


def _frames(
    page: Any, kind: str, steps: list[list[float]], over: dict[str, float] | None = None
) -> list[int]:
    """The pure gate over [micRms, outLevel, replyAgeMs] steps, 80 ms apart: the indexes it opened at."""
    return page.evaluate(
        """([kind, steps, over]) => {
      const g = JarvisBarge.createGate(kind, over || undefined), opened = [];
      steps.forEach(([mic, out, age], i) => {
        const t = i * 80;
        for (let k = 0; k < 4; k++) g.out(out, t + k * 20);
        if (g.frame(mic, t, age).open) opened.push(i);
      });
      return opened;
    }""",
        [kind, steps, over],
    )


# ================================================================== M5: the room's floor
def test_a_room_that_is_loud_all_the_time_stops_counting_as_speech_but_a_voice_still_opens_the_gate_m5(
    make: Callable[..., Console],
) -> None:
    c = make(barge=True)
    c.open()
    quiet = [[0.004, 0.0, 2000.0]] * 12
    hum = [[0.05, 0.0, 2000.0]] * 90  # a fan or a TV at 0.05, JARVIS silent
    opened = _frames(c.page, "headphones", quiet + hum)
    assert opened and opened[0] == 14  # at first it looks like speech ...
    assert (
        max(opened) < len(quiet) + len(hum) - 30
    )  # ... then the floor follows the room and it stops
    voice = _frames(c.page, "headphones", quiet + hum + [[0.7, 0.0, 2000.0]] * 6)
    assert (
        voice[-1] == len(quiet) + len(hum) + 5
    )  # a real voice still opens it, the cap on the floor sees to that
    # a floor learned in the previous reply starts the next one without that first false alarm
    assert _frames(c.page, "headphones", hum, {"noise": 0.05}) == []
    assert c.errors == []


def test_one_loud_frame_does_not_move_the_floor_m5(make: Callable[..., Console]) -> None:
    c = make(barge=True)
    c.open()
    steps = (
        [[0.004, 0.0, 2000.0]] * 30
        + [[0.2, 0.0, 2000.0]]
        + [[0.004, 0.0, 2000.0]] * 30
        + [[0.1, 0.0, 2000.0]] * 4
    )
    assert _frames(c.page, "headphones", steps) == [63, 64]  # the burst still opens it as before
    assert c.errors == []


# ================================================================== M6: words keep their marks
def test_a_real_interruption_in_malayalam_or_hindi_is_not_dropped_as_echo_m6(
    make: Callable[..., Console],
) -> None:
    c = make(barge=True)
    c.open()
    js = "([t, s, p]) => JarvisBarge.isEcho(t, s, p, 4.0)"
    said = "ഇപ്പോൾ സമയം മൂന്ന് മണി ആയി"  # "it is three o'clock now"
    assert c.page.evaluate(js, ["ഇപ്പോൾ സമയം മൂന്ന് മണി", said, 1.0]) is True  # his own words back
    assert (
        c.page.evaluate(js, ["ഇപ്പോൾ മഴ പെയ്യുന്നു", said, 1.0]) is False
    )  # "it is raining" shares one word of three
    assert c.page.evaluate(js, ["बारिश हो रही है", "आज मौसम कैसा है", 1.0]) is False
    assert c.page.evaluate(js, ["आज मौसम कैसा है", "आज मौसम कैसा है", 1.0]) is True
    accents = "Zoë and Renée left the café"
    assert c.page.evaluate(js, ["Zoë left the café", accents, 1.0]) is True
    assert (
        c.page.evaluate(js, ["Zoe left the cafe", accents, 1.0]) is False
    )  # a different spelling is a different word
    assert c.errors == []


# ================================================================== SM3: the browser voice, one resume, no loop
def test_with_the_browsers_own_voice_there_is_no_energy_interruption_on_speakers_sm3(
    make: Callable[..., Console],
) -> None:
    c = make(device={"interruptBy": "speech"}, scripts=(TONE_MIC,), barge=True)
    _route(c)
    FakeVoice(c.page)
    c.open()
    c.page.evaluate("JarvisAudio.open()")
    c.page.wait_for_function("() => JarvisAudio.isOpen()")
    got = c.page.evaluate(
        """() => {
      const mk = (kind, browserVoice) => { window.__kind = kind;
        const a = JarvisBarge.arm({ onBarge() {}, browserVoice }); const live = a.gate() !== null; a.disarm(); return live; };
      return { speakersBrowser: mk('speakers', true), unknownBrowser: mk('unknown', true),
        headphonesBrowser: mk('headphones', true), speakersCloud: mk('speakers', false) };
    }"""
    )
    assert got == {
        "speakersBrowser": False, "unknownBrowser": False, "headphonesBrowser": True, "speakersCloud": True,
    }  # fmt: skip
    c.page.evaluate("JarvisVoice.setDevice({ interruptBy: 'tap' })")
    assert c.page.evaluate("JarvisBarge.arm({ onBarge() {}, browserVoice: false }).gate()") is None
    assert c.errors == []


def test_a_noisy_room_costs_one_resume_a_reply_and_then_no_more_interruptions_sm3(
    make: Callable[..., Console],
) -> None:
    c = make(
        device={"interruptBy": "speech", "speak": "always", "keepListening": True},
        scripts=(TONE_MIC, RECORD_BARGE),
        barge=True,
    )
    fake = FakeVoice(c.page)
    _route(c)
    c.open()
    _start(c, fake)
    first = _speech(c)
    fake.transcript.update({"text": "", "no_speech": True})
    c.page.evaluate("window.__burst(450)")  # a cough
    _until(
        c, f"window.__voice.speech.length > {len(first)}", 15
    )  # he read the stopped chunk again, once
    _until(c, "JarvisVoice.speaker.speaking()", 5)
    assert c.page.evaluate("window.__barges.length") == 1
    c.page.evaluate("window.__burst(450)")  # the same noise again, while he reads on
    c.page.wait_for_timeout(2500)
    assert (
        c.page.evaluate("window.__barges.length") == 1
    )  # no second interruption: energy barge is off for this reply
    assert c.page.evaluate("JarvisVoice.speaker.speaking()") is True
    assert len(_speech(c)) == len(first) + 1  # and nothing was read a third time
    assert c.errors == []


def test_the_learned_leak_carries_into_the_next_reply_of_a_conversation_sm3(
    make: Callable[..., Console],
) -> None:
    c = make(device={"interruptBy": "speech"}, scripts=(TONE_MIC,), barge=True)
    _route(c)
    FakeVoice(c.page)
    c.open()
    c.page.evaluate("JarvisAudio.open()")
    c.page.wait_for_function("() => JarvisAudio.isOpen()")
    got = c.page.evaluate(
        """() => {
      window.__kind = 'speakers';
      const a = JarvisBarge.arm({ onBarge() {}, browserVoice: false }), g = a.gate();
      const guess = g.stats().leak;
      for (let i = 0; i < 20; i++) { const t = performance.now() + i * 80; g.out(0.5, t); g.frame(0.075, t, 2000); }  // he leaks 15 %
      const learned = g.stats().leak;
      a.disarm();
      const b = JarvisBarge.arm({ onBarge() {}, browserVoice: false }), next = b.gate().stats().leak;
      b.disarm();
      JarvisBarge.forget();
      const c2 = JarvisBarge.arm({ onBarge() {}, browserVoice: false }), after = c2.gate().stats().leak;
      c2.disarm();
      return { guess, learned, next, after };
    }"""
    )
    assert got["guess"] == pytest.approx(1.0)
    assert got["learned"] == pytest.approx(0.15, abs=0.02)
    assert got["next"] == pytest.approx(got["learned"], abs=1e-6)  # kept across the re-arm
    assert got["after"] == pytest.approx(1.0)  # forgotten when the conversation ends
    assert c.errors == []


# ================================================================== SM5: check clips
def _arm_clips(c: Console, clips: bool = True) -> None:
    """Name mode, microphone open, an armed gate whose clips go to the router stand-in below."""
    c.page.evaluate("JarvisVoice.setDevice({ interruptBy: 'name' })")
    c.page.evaluate("JarvisAudio.open()")
    c.page.wait_for_function("() => JarvisAudio.isOpen()")
    c.page.wait_for_timeout(600)  # let the first frames flow
    c.page.evaluate(
        f"""() => {{
      window.__routed = []; window.__ends = [];
      window.__arm = () => {{
        if (window.__a) window.__a.disarm();
        window.__a = JarvisBarge.arm({{ clips: {str(clips).lower()}, browserVoice: false, said: () => '',
          handle: async (text) => {{ window.__routed.push(text); return {{ handled: false }}; }},
          onBarge: (ev) => window.__ends.push(ev.how) }});
      }};
      window.__arm();
    }}"""
    )


def _burst_and_wait_for_request(c: Console, fake: FakeVoice, before: int, tries: int = 1) -> bool:
    """A burst of talk in the room; True when it made a clip go out (the first one after opening may need a second try)."""
    for _ in range(tries):
        c.page.evaluate("window.__burst(700)")
        for _ in range(40):
            if _count(fake, "/v1/voice/transcribe") > before:
                return True
            c.page.wait_for_timeout(100)
    return False


def test_a_reply_may_send_three_clips_even_while_the_answers_are_still_out_sm5(
    make: Callable[..., Console],
) -> None:
    c = make(scripts=(TONE_MIC,), barge=True)
    fake = FakeVoice(c.page)
    fake.hold_transcribe = (
        True  # the cloud is slow: counting on the response would let any number out
    )
    _route(c)
    c.open()
    _arm_clips(c)
    sent = 0
    for _ in range(4):
        before = _count(fake, "/v1/voice/transcribe")
        if _burst_and_wait_for_request(c, fake, before):
            sent += 1
        c.page.wait_for_timeout(3200)  # past the 3 s between clips
    assert sent == 3
    assert c.errors == []


def test_with_no_conversation_there_are_no_clips_at_all_sm5(make: Callable[..., Console]) -> None:
    c = make(scripts=(TONE_MIC,), barge=True)
    fake = FakeVoice(c.page)
    _route(c)
    c.open()
    _arm_clips(c, clips=False)
    before = _count(fake, "/v1/voice/transcribe")
    assert _burst_and_wait_for_request(c, fake, before) is False
    c.page.wait_for_timeout(1500)
    assert c.page.evaluate("JarvisVoice.speaker.volume()") == pytest.approx(
        1.0, abs=0.01
    )  # not even ducked
    assert _count(fake, "/v1/voice/transcribe") == before
    assert c.errors == []


def test_a_typed_message_answered_aloud_with_hey_jarvis_on_sends_no_clips_sm5(
    make: Callable[..., Console],
) -> None:
    c = make(
        device={"interruptBy": "name", "speak": "always", "keepListening": True, "wake": True},
        scripts=(TONE_MIC, FAKE_WAKE, RECORD_BARGE),
        barge=True,
    )
    fake = FakeVoice(c.page)
    _route(c)
    c.open()
    c.page.wait_for_function("() => window.__wake.started === 1")
    fake.speak_audio = wav_bytes(seconds=7.0)
    c.send("Read this out, please.")  # typed: not a conversation
    _until(c, "document.getElementById('micBtn').dataset.state === 'speaking'", 20)
    c.page.wait_for_timeout(700)
    before = _count(fake, "/v1/voice/transcribe")
    c.page.evaluate("window.__burst(1200)")
    c.page.wait_for_timeout(3000)
    assert _count(fake, "/v1/voice/transcribe") == before  # the room was not sent anywhere
    assert c.page.evaluate("JarvisVoice.speaker.speaking()") is True
    assert c.errors == []


def test_a_clip_does_not_reach_the_router_when_the_microphone_is_switched_off_meanwhile_sm5(
    make: Callable[..., Console],
) -> None:
    c = make(scripts=(TONE_MIC, SIGNALS), barge=True)
    fake = FakeVoice(c.page)
    fake.hold_transcribe = True
    fake.transcript["text"] = "stop"
    _route(c)
    c.open()
    _arm_clips(c)
    assert _burst_and_wait_for_request(c, fake, _count(fake, "/v1/voice/transcribe"), tries=2)
    c.page.evaluate("JarvisAudio.lock('button')")
    fake.release_transcribe()
    c.page.wait_for_timeout(800)
    assert c.page.evaluate("window.__routed") == []  # the router never saw it
    assert c.page.evaluate("window.__ends") == []
    assert c.errors == []


def test_disarming_aborts_a_clip_that_is_still_in_flight_sm5(make: Callable[..., Console]) -> None:
    c = make(scripts=(TONE_MIC, SIGNALS), barge=True)
    fake = FakeVoice(c.page)
    fake.hold_transcribe = True
    _route(c)
    c.open()
    _arm_clips(c)
    assert _burst_and_wait_for_request(c, fake, _count(fake, "/v1/voice/transcribe"), tries=2)
    sig = "window.__sigs.filter(s => s.url.includes('/v1/voice/transcribe')).at(-1).signal.aborted"
    assert c.page.evaluate(sig) is False
    c.page.evaluate("window.__a.disarm()")
    assert c.page.evaluate(sig) is True
    assert c.errors == []


def test_clips_are_capped_at_twelve_an_hour_and_twenty_a_conversation_sm5(
    make: Callable[..., Console],
) -> None:
    c = make(scripts=(TONE_MIC,), barge=True)
    fake = FakeVoice(c.page)
    fake.hold_transcribe = True
    _route(c)
    c.page.clock.install()
    c.open()
    _arm_clips(c)
    sent = 0
    for _ in range(14):  # a fresh reply (and so a fresh per-reply allowance) each time
        c.page.evaluate("window.__arm()")
        for _ in range(3):
            before = _count(fake, "/v1/voice/transcribe")
            if _burst_and_wait_for_request(c, fake, before):
                sent += 1
            c.page.clock.fast_forward(3300)
        if c.page.evaluate("JarvisBarge.clipsLeft().hour") <= 0:
            break
    assert sent == 12 and c.page.evaluate("JarvisBarge.clipsLeft()") == {
        "conversation": 8,
        "hour": 0,
    }
    c.page.clock.fast_forward(
        60 * 60 * 1000 + 1000
    )  # an hour later: the hour is clean, the conversation is not
    assert c.page.evaluate("JarvisBarge.clipsLeft()") == {"conversation": 8, "hour": 12}
    for _ in range(4):
        c.page.evaluate("window.__arm()")
        for _ in range(3):
            before = _count(fake, "/v1/voice/transcribe")
            if _burst_and_wait_for_request(c, fake, before):
                sent += 1
            c.page.clock.fast_forward(3300)
    assert sent == 20  # the conversation's 20 clips, not one more
    c.page.evaluate("JarvisBarge.forget()")  # a new conversation starts again
    assert c.page.evaluate("JarvisBarge.clipsLeft().conversation") == 20
    assert c.errors == []
