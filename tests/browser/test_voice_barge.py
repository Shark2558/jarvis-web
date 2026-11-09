# ruff: noqa: F811, E501  (imported fixtures; long lines are JS snippets and prose)
# tests/browser/test_voice_barge.py — R5 workstream A, speak to interrupt (docs/plans/r5-voice.md D7-D9):
# the pure double-talk gate on synthetic frames, the policies, the text-aware echo guard, and the real
# thing in a browser: talking over JARVIS on earphones stops him fast, on speakers it lowers his volume
# and asks the router, "Hey Jarvis" works over his speech, a false interruption is resumed, and his own
# echo never interrupts him (negative control).
from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

import pytest
from test_console import Console
from test_voice import FAKE_WAKE, FakeVoice, _speech, _wait, wav_bytes

# the fixtures of test_voice_robust (module-level so pytest finds them here)
from test_voice_robust import (  # noqa: F401
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

# A stand-in for B's audio route: the output kind is whatever window.__kind says.
ROUTE_STUB = """
window.JarvisAudioRoute = Object.freeze({
  supported: () => false, refresh: () => Promise.resolve({ outputs: [], inputs: [] }),
  current: () => ({ output: null, input: null }),
  chooseOutput: () => Promise.resolve({ ok: false }), chooseInput: () => Promise.resolve({ ok: false }),
  outputKind: () => window.__kind || 'unknown', find: () => null, on() {},
});
"""
RECORD_BARGE = """
window.__barges = [];
document.addEventListener('jarvis:barge', (e) => window.__barges.push(e.detail));
"""
# TONE_MIC plus an echo path: the microphone also hears JARVIS's own output level x 0.35, 60 ms late.
ECHO_MIC = (
    TONE_MIC
    + """
(() => {
  const queue = [];
  const real = navigator.mediaDevices.getUserMedia;
  navigator.mediaDevices.getUserMedia = async (c) => {
    const s = await real(c);
    return s;
  };
  setInterval(() => {
    const L = window.JarvisVoice && window.JarvisVoice.speaker ? window.JarvisVoice.speaker.level() : 0;
    queue.push({ at: performance.now(), v: L });
    while (queue.length > 1 && performance.now() - queue[1].at >= 60) queue.shift();
    const echo = window.__echo === false ? 0 : (queue[0].v * 0.35) / 0.707;
    window.__mic.gains.forEach((g) => { g.gain.value = (window.__mic.on ? 0.25 : 0) + echo; });
  }, 20);
})();
"""
)
LONG = "Alpha beta gamma. " + "This sentence is long enough to be part of a chunk of its own. " * 8


def _route(c: Console) -> None:
    c.page.route(
        "**/static/console-voice-devices.js",
        lambda r: r.fulfill(status=200, content_type="text/javascript", body=ROUTE_STUB),
    )


def _start(c: Console, fake: FakeVoice, said: str = "Tell me something long.") -> None:
    """A voice conversation: the owner speaks, JARVIS starts answering (long audio)."""
    fake.speak_audio = wav_bytes(seconds=7.0)
    fake.transcript["text"] = said
    c.page.evaluate("window.__talk(true)")
    c.page.locator("#micBtn").click()
    _until(c, "document.getElementById('voiceLive').textContent === 'Hearing you'", 10)
    c.page.wait_for_timeout(300)
    c.page.evaluate("window.__talk(false)")
    _until(c, "document.getElementById('micBtn').dataset.state === 'speaking'", 30)
    c.page.wait_for_timeout(700)  # past the first 400 ms of the reply


def _mode(c: Console) -> str:
    return str(c.page.locator("#micBtn").get_attribute("data-state"))


def _gate(page: Any, kind: str, steps: list[list[float]], margin: float | None = None) -> list[int]:
    """Run the pure gate over [micRms, outLevel, replyAgeMs] steps (80 ms apart); the indexes it opened at."""
    return page.evaluate(
        """([kind, steps, margin]) => {
      const g = JarvisBarge.createGate(kind, margin === null ? undefined : { margin });
      const opened = [];
      steps.forEach(([mic, out, age], i) => {
        const t = i * 80;
        for (let k = 0; k < 4; k++) g.out(out, t + k * 20);
        if (g.frame(mic, t, age).open) opened.push(i);
      });
      return opened;
    }""",
        [kind, steps, margin],
    )


# ================================================================== the pure gate
def test_gate_opens_after_three_frames_on_earphones_and_four_on_speakers(
    make: Callable[..., Console],
) -> None:
    c = make(barge=True)
    c.open()
    quiet = [[0.004, 0.0, 2000.0]] * 10
    speech = [[0.2, 0.0, 2000.0]] * 6
    assert _gate(c.page, "headphones", quiet + speech)[0] == 12  # the 3rd loud frame
    assert _gate(c.page, "speakers", quiet + speech)[0] == 13  # the 4th
    assert c.errors == []


def test_gate_needs_one_more_frame_in_the_first_400_ms_of_a_reply(
    make: Callable[..., Console],
) -> None:
    c = make(barge=True)
    c.open()
    quiet = [[0.004, 0.0, 100.0]] * 4
    assert _gate(c.page, "headphones", quiet + [[0.2, 0.0, 100.0]] * 6)[0] == 7  # 4 frames
    assert c.errors == []


def test_gate_stays_shut_for_a_steady_echo_and_opens_for_a_real_voice(
    make: Callable[..., Console],
) -> None:
    c = make(barge=True)
    c.open()
    echo = [[0.35 * 0.3, 0.3, 2000.0]] * 40  # JARVIS at 0.3 leaks 35 % back into the mic
    assert _gate(c.page, "speakers", echo) == []
    voice = echo + [[0.7, 0.3, 2000.0]] * 6  # someone talks over him: 0.7 vs 4 x 0.105
    got = _gate(c.page, "speakers", voice)
    assert got and got[0] == 43
    # the control: margin 1.0 treats a small wobble above the echo as a voice (this is what the margin is for)
    wobble = [[0.35 * 0.3, 0.3, 2000.0]] * 20 + [[0.14, 0.3, 2000.0]] * 8
    assert _gate(c.page, "speakers", wobble) == []
    assert _gate(c.page, "speakers", wobble, margin=1.0) != []
    assert c.errors == []


def test_gate_is_not_fooled_by_a_quiet_room_noise_floor(make: Callable[..., Console]) -> None:
    c = make(barge=True)
    c.open()
    assert _gate(c.page, "headphones", [[0.015, 0.0, 2000.0]] * 40) == []  # below the 0.018 floor
    assert c.errors == []


def test_echo_guard_counts_mostly_his_own_words_unless_the_sound_was_far_louder(
    make: Callable[..., Console],
) -> None:
    c = make(barge=True)
    c.open()
    js = "([t, s, p]) => JarvisBarge.isEcho(t, s, p, 4.0)"
    said = "Please wait while I stop the oven and tell Jarvis about it."
    assert c.page.evaluate(js, ["wait while I stop the oven", said, 1.0]) is True
    assert c.page.evaluate(js, ["what is the weather today", said, 1.0]) is False
    assert (
        c.page.evaluate(js, ["wait while I stop the oven", said, 6.5]) is False
    )  # >= 1.5 x margin
    assert c.page.evaluate(js, ["", said, 1.0]) is False
    assert c.errors == []


def test_automatic_policy_follows_the_output_kind_and_explicit_choices_win(
    make: Callable[..., Console],
) -> None:
    c = make(barge=True)
    _route(c)
    c.open()
    pol = "window.JarvisBarge.policy()"
    c.page.evaluate("window.__kind = 'headphones'")
    assert c.page.evaluate(pol) == "speech"
    c.page.evaluate("window.__kind = 'speakers'")
    assert c.page.evaluate(pol) == "name"
    c.page.evaluate("window.__kind = 'unknown'")
    assert c.page.evaluate(pol) == "name"  # unknown counts as speakers, the safe side
    for choice in ("speech", "name", "tap"):
        c.page.evaluate(f"JarvisVoice.setDevice({{ interruptBy: '{choice}' }})")
        assert c.page.evaluate(pol) == choice
    assert c.errors == []


# ================================================================== speaking policy, in the browser
def test_talking_over_jarvis_on_earphones_stops_him_within_the_ci_threshold(
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
    c.page.evaluate("window.__kind = 'headphones'")
    _start(c, fake)
    assert c.page.evaluate("window.JarvisVoice.speaker.speaking()") is True
    # The clock starts when the page first SEES the voice (a frame from the microphone): the fake
    # microphone's own pipeline adds a few hundred ms in headless Chromium that is not the app's.
    got = c.page.evaluate(
        """() => new Promise((res) => {
      const t0 = performance.now();
      let seen = 0;
      const off = JarvisAudio.subscribe((f) => { if (!seen && JarvisVad.rms(f) > 0.05) seen = performance.now(); });
      window.__talk(true);
      const iv = setInterval(() => {
        if (!JarvisVoice.speaker.speaking()) {
          clearInterval(iv); off();
          res({ rig: performance.now() - t0, ms: seen ? performance.now() - seen : 0 });
        }
      }, 5);
      setTimeout(() => { clearInterval(iv); off(); res({ rig: 99999, ms: 99999 }); }, 5000);
    })"""
    )
    ms = got["ms"]
    assert ms <= 600, ms  # the plan's CI bound (owner target is 0.5 s on real hardware)
    assert (
        _mode(c) == "listening"
    )  # and he listens, with what was just said as the start of the turn
    barge = c.page.evaluate("window.__barges")
    assert barge and barge[0]["how"] == "speech"
    fake.transcript["text"] = "Actually, never mind that."
    c.page.evaluate("window.__talk(false)")
    sent = None
    for _ in range(100):
        sent = c.page.evaluate(
            "window.__sent.filter(s => s.path === '/v1/voice/transcribe').at(-1)"
        )
        if _count(fake, "/v1/voice/transcribe") >= 2 and sent:
            break
        c.page.wait_for_timeout(100)
    assert _count(fake, "/v1/voice/transcribe") >= 2
    assert (
        sent["size"] > 44 + 7 * 2560
    )  # the frames from before the gate opened are in the recording
    assert c.errors == []


def test_a_false_interruption_is_picked_up_again_where_he_stopped(
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
    _until(c, "document.getElementById('micBtn').dataset.state === 'listening'", 5)
    _until(c, f"window.__voice.speech.length > {len(first)}", 15)
    again = _speech(c)
    assert len(again) > len(first)
    assert again[len(first)] == first[-1]  # the interrupted chunk is read again, from its start
    assert c.errors == []


def test_a_real_question_after_an_interruption_is_not_followed_by_the_old_reply(
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
    fake.transcript["text"] = "What time is it?"
    c.page.evaluate("window.__burst(1500)")
    _until(c, "document.querySelectorAll('.row.user').length >= 2", 20)
    assert "What time is it?" in str(c.page.locator(".row.user").last.text_content())
    assert c.errors == []


# ================================================================== name policy (speakers)
def test_on_speakers_talking_over_him_lowers_his_volume_and_a_stop_transcript_stops_him(
    make: Callable[..., Console],
) -> None:
    c = make(
        device={"interruptBy": "name", "speak": "always", "keepListening": True},
        scripts=(TONE_MIC, RECORD_BARGE),
        barge=True,
    )
    fake = FakeVoice(c.page)
    _route(c)
    c.open()
    _start(c, fake)
    before = _count(fake, "/v1/voice/transcribe")
    fake.transcript["text"] = "stop"
    c.page.evaluate("window.__burst(1200)")
    _until(c, "JarvisVoice.speaker.volume() < 0.5", 3)  # ducked within about half a second
    _until(c, "!JarvisVoice.speaker.speaking()", 8)
    assert _count(fake, "/v1/voice/transcribe") == before + 1  # one check clip
    barge = c.page.evaluate("window.__barges")
    assert barge and barge[0]["how"] == "stop"
    assert c.page.evaluate("JarvisVoice.speaker.volume()") == pytest.approx(1.0, abs=0.01)
    assert c.errors == []


def test_on_speakers_other_words_return_his_volume_and_he_reads_on(
    make: Callable[..., Console],
) -> None:
    c = make(
        device={"interruptBy": "name", "speak": "always", "keepListening": True},
        scripts=(TONE_MIC, RECORD_BARGE),
        barge=True,
    )
    fake = FakeVoice(c.page)
    _route(c)
    chats: list[int] = []
    c.page.route("**/v1/chat", lambda r: (chats.append(1), r.continue_()))
    c.open()
    _start(c, fake)
    before_chats = len(chats)
    fake.transcript["text"] = "the weather is lovely today"
    c.page.evaluate("window.__burst(1200)")
    _until(c, "JarvisVoice.speaker.volume() < 0.5", 3)
    _until(c, "JarvisVoice.speaker.volume() > 0.9", 8)
    assert c.page.evaluate("JarvisVoice.speaker.speaking()") is True
    assert c.page.evaluate("window.__barges") == []
    assert len(chats) == before_chats  # the clip's words were dropped, never sent
    assert "weather" not in str(c.page.locator("body").inner_text())
    assert c.errors == []


def test_saying_jarvis_in_a_check_clip_interrupts_and_the_rest_becomes_the_turn(
    make: Callable[..., Console],
) -> None:
    c = make(
        device={"interruptBy": "name", "speak": "always", "keepListening": True},
        scripts=(TONE_MIC, RECORD_BARGE),
        barge=True,
    )
    fake = FakeVoice(c.page)
    _route(c)
    c.open()
    _start(c, fake)
    fake.transcript["text"] = "Jarvis, what is on my calendar"
    c.page.evaluate("window.__burst(1200)")
    _until(c, "document.querySelectorAll('.row.user').length >= 2", 20)
    assert "calendar" in str(c.page.locator(".row.user").last.text_content())
    assert c.errors == []


def test_check_clips_are_limited_after_three_that_find_nothing(
    make: Callable[..., Console],
) -> None:
    c = make(
        device={"interruptBy": "name", "speak": "always", "keepListening": True},
        scripts=(TONE_MIC, RECORD_BARGE),
        barge=True,
    )
    fake = FakeVoice(c.page)
    _route(c)
    c.open()
    _start(c, fake)
    fake.speak_audio = wav_bytes(seconds=30.0)
    fake.transcript["text"] = "some chatter in the room"
    before = _count(fake, "/v1/voice/transcribe")
    for _ in range(4):
        c.page.evaluate("window.__burst(900)")
        c.page.wait_for_timeout(3600)
    assert _count(fake, "/v1/voice/transcribe") - before <= 3
    assert c.errors == []


def test_a_fake_hey_jarvis_stops_him_while_he_speaks(make: Callable[..., Console]) -> None:
    c = make(
        device={"interruptBy": "name", "speak": "always", "keepListening": True, "wake": True},
        scripts=(TONE_MIC, FAKE_WAKE, RECORD_BARGE),
        barge=True,
    )
    fake = FakeVoice(c.page)
    _route(c)
    c.open()
    _wait(c, "() => window.__wake.started === 1")
    _start(c, fake)
    assert (
        c.page.evaluate("window.JarvisWake.state") == "listening"
    )  # the model runs while he speaks
    c.page.evaluate("window.__wake.fire({ score: 0.9 })")
    _until(c, "!JarvisVoice.speaker.speaking()", 2)
    assert c.page.evaluate("window.__barges.at(-1).how") == "wake"
    assert c.errors == []


# ================================================================== negative controls
def _echo_run(c: Console, fake: FakeVoice, policy: str) -> tuple[list[str], int]:
    _route(c)
    c.page.evaluate("0")
    fake.speak_audio = wav_bytes(seconds=1.0)
    fake.transcript["text"] = "Stop. Wait. Jarvis."
    c.page.evaluate("window.__talk(true)")
    c.page.locator("#micBtn").click()
    _until(c, "document.getElementById('voiceLive').textContent === 'Hearing you'", 10)
    c.page.wait_for_timeout(300)
    c.page.evaluate("window.__talk(false)")
    _until(c, "document.getElementById('micBtn').dataset.state === 'speaking'", 30)
    before = _count(fake, "/v1/voice/transcribe")
    c.page.wait_for_timeout(4500)
    return _speech(c), _count(fake, "/v1/voice/transcribe") - before


def test_his_own_echo_on_built_in_speakers_never_interrupts_him(
    make: Callable[..., Console],
) -> None:
    c = make(
        device={"interruptBy": "speech", "speak": "always", "keepListening": True},
        scripts=(ECHO_MIC, RECORD_BARGE),
        barge=True,
    )
    fake = FakeVoice(c.page)
    c.open()
    c.page.evaluate("window.__kind = 'speakers'")
    spoken, clips = _echo_run(c, fake, "speech")
    assert len(spoken) >= 2  # "Certainly, Sir." and the You said line, both read out
    assert c.page.evaluate("window.__barges") == []
    assert clips == 0
    assert c.errors == []


def test_tapping_only_never_arms_the_gate_even_with_a_talking_room(
    make: Callable[..., Console],
) -> None:
    c = make(
        device={"interruptBy": "tap", "speak": "always", "keepListening": True},
        scripts=(TONE_MIC, RECORD_BARGE),
    )
    fake = FakeVoice(c.page)
    _route(c)
    c.open()
    _start(c, fake)
    c.page.evaluate("window.__talk(true)")
    c.page.wait_for_timeout(1500)
    assert c.page.evaluate("JarvisVoice.speaker.speaking()") is True
    assert json.loads(json.dumps(c.page.evaluate("window.__barges"))) == []
    assert c.errors == []
