# ruff: noqa: F811, E501  (imported fixtures; long lines are JS snippets and prose)
# tests/browser/test_voice_loop.py — R5 workstream A, the listening loop (docs/plans/r5-voice.md D2-D6):
# no turn limit, the follow-up / standby / long-pause clock, the spoken handover to the keyboard, the
# runaway check-in, the announced endings, and a typed reply never opening the microphone.
from __future__ import annotations

import time
from collections.abc import Callable

import pytest
from test_console import Console
from test_voice import FAKE_WAKE, FakeVoice, _wait, wav_bytes
from test_voice_robust import (  # noqa: F401  (fixtures and helpers)
    FAST_TV,
    SLOW_GUM,
    STALL,
    TONE_MIC,
    _chat_counter,
    _count,
    _mic_file,
    _playwright,
    _until,
    browser,
    make,
)

_pw = pytest.importorskip("playwright.sync_api")

pytestmark = pytest.mark.browser

# every state change of the loop with its time
RECORD_LOOP = """
window.__loop = [];
document.addEventListener('jarvis:voice-loop', (e) =>
  window.__loop.push({ state: e.detail.state, conv: e.detail.conversation, at: performance.now() }));
"""


def _first(c: Console, state: str, after: float = 0.0) -> float | None:
    return c.page.evaluate(
        "([s, a]) => { const x = window.__loop.find(e => e.state === s && e.at > a); return x ? x.at : null; }",
        [state, after],
    )


def _reply_end(c: Console) -> float | None:
    return c.page.evaluate(
        "() => { const i = window.__loop.map(e => e.state).lastIndexOf('speaking');"
        " return i < 0 || !window.__loop[i + 1] ? null : window.__loop[i + 1].at; }"
    )


def _say_one_sentence(c: Console) -> None:
    """Tap the mic and talk for about a second, then go quiet: one turn, then a quiet room."""
    c.page.evaluate("window.__talk(true)")
    c.page.locator("#micBtn").click()
    _until(c, "document.getElementById('voiceLive').textContent === 'Hearing you'", 10)
    c.page.wait_for_timeout(500)
    c.page.evaluate("window.__talk(false)")


# ================================================================== the clock and the tracker, pure
def test_the_clock_fires_standby_then_the_long_pause_and_stops_when_the_owner_speaks(
    make: Callable[..., Console],
) -> None:
    c = make()
    c.open()
    got = c.page.evaluate(
        """async () => {
      const sleep = (ms) => new Promise(r => setTimeout(r, ms)), log = [];
      const a = JarvisConversation.create({ followUpMs: 60, longPauseMs: 140,
        onStandby: () => log.push('a-standby'), onLongPause: () => log.push('a-pause') });
      a.replyEnded();
      await sleep(250);
      const b = JarvisConversation.create({ followUpMs: 60, longPauseMs: 140,
        onStandby: () => log.push('b-standby'), onLongPause: () => log.push('b-pause') });
      b.replyEnded();
      await sleep(90);
      b.heard();
      await sleep(150);
      const c = JarvisConversation.create({ followUpMs: 60, longPauseMs: 140,
        onStandby: () => log.push('c-standby'), onLongPause: () => log.push('c-pause') });
      c.replyEnded(); c.stop();
      await sleep(200);
      return { log, waiting: [a.waiting(), b.waiting(), c.waiting()] };
    }"""
    )
    assert got["log"] == ["a-standby", "a-pause", "b-standby"]
    assert got["waiting"] == [False, False, False]
    assert c.errors == []


def test_the_runaway_tracker_counts_only_quick_unbroken_turns_inside_four_minutes(
    make: Callable[..., Console],
) -> None:
    c = make()
    c.open()
    got = c.page.evaluate(
        """() => {
      const R = JarvisConversation.runaway, K = JarvisConversation.RUNAWAY, out = {};
      let r = R();
      for (let i = 0; i < 7; i++) r.turn(300, 1000 + i);
      out.seven = r.due(2000);
      r.turn(300, 1100); out.eight = r.due(2000);
      r = R(); for (let i = 0; i < 7; i++) r.turn(300, 1000 + i);
      r.turn(K.QUICK_MS + 1, 1100); out.slow = r.due(2000);            // a human-paced turn resets the count
      for (let i = 0; i < 7; i++) r.turn(300, 1200 + i);               // M3: the slow turn is not itself the first quick one
      out.sevenAfterSlow = r.due(2000);
      r.turn(300, 1300); out.eightAfterSlow = r.due(2000);
      r = R(); for (let i = 0; i < 7; i++) r.turn(300, 1000 + i);
      r.touch(); r.turn(300, 1100); out.touched = r.due(2000);         // a tap or key resets it too
      r = R(); for (let i = 0; i < 8; i++) r.turn(300, i * 40000);     // 8 turns over 280 s
      out.slowWindow = r.due(8 * 40000);
      return out;
    }"""
    )
    assert got == {
        "seven": False, "eight": True, "slow": False, "sevenAfterSlow": False,
        "eightAfterSlow": True, "touched": False, "slowWindow": False,
    }  # fmt: skip
    assert c.errors == []


def test_a_conversation_has_an_absolute_bound_whatever_the_pace_sh1(
    make: Callable[..., Console],
) -> None:
    """SH1: 25 hands-free turns, or 30 minutes, since the last human touch force a check-in; a yes buys 8 turns."""
    c = make()
    c.open()
    got = c.page.evaluate(
        """() => {
      const R = JarvisConversation.runaway, K = JarvisConversation.RUNAWAY, out = {};
      let r = R();
      for (let i = 0; i < 24; i++) r.turn(25000, 1000 + i * 25000);    // a TV that pauses 25 s: never "quick"
      out.t24 = [r.due(0), r.capped(1000 + 24 * 25000)];
      r.turn(25000, 1000 + 24 * 25000);
      out.t25 = [r.due(0), r.capped(1000 + 25 * 25000)];
      r.touch(5000);                                                    // a tap, click or key press
      out.touched = r.capped(5000 + 1000);
      r = R(); r.touch(0); r.turn(40000, 40000);
      out.early = r.capped(K.MAX_MS - 1);
      out.thirtyMin = r.capped(K.MAX_MS + 1);                           // 30 minutes since the touch
      r = R(); r.touch(0);
      out.noTurnsNoCap = r.capped(K.MAX_MS * 3);                        // nothing hands-free happened: nothing to bound
      r = R(); r.touch(0);
      for (let i = 0; i < 25; i++) r.turn(25000, 1000 + i);
      r.answered(true, 90000);                                          // a "yes"
      const after = [];
      for (let i = 0; i < 8; i++) { after.push(r.capped(90000 + i)); r.turn(25000, 90001 + i); }
      out.yesBuys = after.concat([r.capped(91000)]);
      r = R(); r.touch(0); for (let i = 0; i < 25; i++) r.turn(25000, i);
      r.answered(false, 1000); out.noResets = r.total();
      return out;
    }"""
    )
    assert got == {
        "t24": [False, False], "t25": [False, True], "touched": False, "early": False,
        "thirtyMin": True, "noTurnsNoCap": False,
        "yesBuys": [False, False, False, False, False, False, False, False, True],
        "noResets": 25,
    }  # fmt: skip
    assert c.errors == []


# ================================================================== no turn limit
# ================================================================== standby and the handover
def test_the_handover_waits_are_the_owners_settings(make: Callable[..., Console]) -> None:
    c = make(
        device={"keepListening": True, "followUpS": 3, "longPauseS": 10},
        scripts=(TONE_MIC, FAST_TV, RECORD_LOOP),
    )
    FakeVoice(c.page)
    c.open()
    _say_one_sentence(c)
    _until(c, "document.querySelectorAll('.row.user').length >= 1", 30)
    _until(c, "window.__loop.some(e => e.state === 'standby')", 20)
    t0 = _first(c, "listening", 0)
    assert t0 is not None
    _until(
        c,
        "document.getElementById('micBtn').dataset.state === 'idle' && "
        "window.__loop.some(e => e.state === 'standby')",
        25,
    )
    assert (
        "Switched to the keyboard" in c.page.locator("#voiceLine").text_content()
    )  # no speech, still said
    assert c.page.evaluate("JarvisAudio.isOpen()") is False
    assert c.errors == []


def test_speech_in_standby_still_starts_a_turn(make: Callable[..., Console]) -> None:
    c = make(
        device={"keepListening": True, "followUpS": 3, "longPauseS": 30},
        scripts=(TONE_MIC, FAST_TV, RECORD_LOOP),
    )
    FakeVoice(c.page)
    chats = _chat_counter(c)
    c.open()
    _say_one_sentence(c)
    _until(c, "document.querySelectorAll('.row.user').length >= 1", 30)
    _until(c, "document.getElementById('micBtn').dataset.state === 'standby'", 12)
    c.page.evaluate("window.__burst(1500)")  # firmer, longer: passes the stricter gate
    _until(c, "document.querySelectorAll('.row.user').length >= 2", 20)
    assert len(chats) >= 2
    c.page.keyboard.press("Escape")
    assert c.errors == []


def test_with_hey_jarvis_on_the_handover_keeps_the_microphone_for_the_wake_word(
    make: Callable[..., Console],
) -> None:
    c = make(
        device={
            "keepListening": True,
            "followUpS": 3,
            "longPauseS": 10,
            "wake": True,
        },
        scripts=(TONE_MIC, FAKE_WAKE, RECORD_LOOP),
    )
    FakeVoice(c.page)
    c.open()
    _wait(c, "() => window.__wake.started === 1")
    _say_one_sentence(c)
    _until(c, "document.querySelectorAll('.row.user').length >= 1", 30)
    _until(
        c,
        "document.getElementById('micBtn').dataset.state === 'idle' && window.__loop.some(e => e.state === 'standby')",
        25,
    )
    assert "or say" in c.page.locator("#voiceLine").text_content()
    assert c.page.evaluate("JarvisAudio.isOpen()") is True  # standby still needs it
    assert c.errors == []


def test_a_keyboard_command_hands_over_without_a_chat_message(make: Callable[..., Console]) -> None:
    c = make(device={"speak": "always", "keepListening": True})
    fake = FakeVoice(c.page)
    fake.transcript["text"] = "Jarvis, switch to the keyboard"
    chats = _chat_counter(c)
    c.open()
    c.page.locator("#micBtn").click()
    _until(c, "document.getElementById('micBtn').dataset.state === 'speaking'", 30)
    assert chats == []
    assert "I'll switch to the keyboard, Sir." in fake.spoken()
    _until(c, "document.getElementById('micBtn').dataset.state === 'idle'", 10)
    assert c.page.evaluate("JarvisAudio.isOpen()") is False
    assert c.errors == []


def test_an_unplugged_microphone_in_a_conversation_is_announced(
    make: Callable[..., Console],
) -> None:
    c = make(device={"speak": "always", "keepListening": True}, scripts=(SLOW_GUM, STALL))
    fake = FakeVoice(c.page)
    c.open()
    c.page.evaluate("window.__stall = true")
    c.page.locator("#micBtn").click()
    _wait(c, "() => window.JarvisAudio.isOpen() && window.__streams.length === 1")
    c.page.evaluate("window.__streams[0].getAudioTracks()[0].dispatchEvent(new Event('ended'))")
    _until(c, "window.__voice.speech.length >= 1", 10)
    assert "The microphone stopped, Sir. I'll switch to the keyboard." in fake.spoken()
    assert "microphone stopped" in str(c.page.locator("#micHelp").text_content())
    _until(c, "document.getElementById('micBtn').dataset.state === 'idle'", 10)
    assert c.page.evaluate("JarvisAudio.isOpen()") is False
    assert c.errors == []


# ================================================================== the runaway check-in
def _tv(c: Console, fake: FakeVoice) -> None:
    fake.speak_audio = wav_bytes(seconds=0.3)
    c.page.evaluate("window.__tvFast()")  # someone talks every 2.6 s, forever
    c.page.locator("#micBtn").click()


def test_saying_yes_to_the_check_in_carries_on_and_it_is_not_asked_again(
    make: Callable[..., Console],
) -> None:
    c = make(
        device={"speak": "always", "keepListening": True, "endSilenceMs": 800},
        scripts=(TONE_MIC, FAST_TV, RECORD_LOOP),
    )
    fake = FakeVoice(c.page)
    c.open()
    _tv(c, fake)
    question = "Shall I keep listening, Sir?"
    deadline = time.monotonic() + 150
    while time.monotonic() < deadline and question not in fake.spoken():
        c.page.wait_for_timeout(300)
    assert question in fake.spoken()
    fake.transcript["text"] = "yes please"
    before = _count(fake, "/v1/voice/transcribe")
    for _ in range(300):
        if _count(fake, "/v1/voice/transcribe") >= before + 4:
            break
        c.page.wait_for_timeout(200)
    assert _count(fake, "/v1/voice/transcribe") >= before + 4  # it went on listening
    assert fake.spoken().count(question) == 1
    assert not c.page.evaluate("window.__loop.some(e => e.state === 'handover')")
    c.page.keyboard.press("Escape")
    assert c.errors == []


def test_with_the_check_in_off_the_same_room_runs_on(make: Callable[..., Console]) -> None:
    c = make(
        device={"speak": "always", "keepListening": True, "checkIn": False, "endSilenceMs": 800},
        scripts=(TONE_MIC, FAST_TV, RECORD_LOOP),
    )
    fake = FakeVoice(c.page)
    c.open()
    _tv(c, fake)
    for _ in range(400):
        if _count(fake, "/v1/voice/transcribe") >= 11:
            break
        c.page.wait_for_timeout(500)
    assert _count(fake, "/v1/voice/transcribe") >= 11
    assert "Shall I keep listening, Sir?" not in fake.spoken()
    c.page.keyboard.press("Escape")
    assert c.errors == []


# ================================================================== a typed reply never opens the microphone
def test_a_typed_message_with_spoken_replies_never_opens_the_microphone(
    make: Callable[..., Console],
) -> None:
    c = make(device={"speak": "always", "keepListening": True}, scripts=(SLOW_GUM,))
    FakeVoice(c.page)
    c.open()
    c.send("Read this out, please.")
    _wait(c, "() => window.__voice.speech.length >= 2")
    _wait(c, "() => !window.JarvisVoice.speaker.speaking()", 20000)
    c.page.wait_for_timeout(1500)
    assert c.page.evaluate("window.__streams.length") == 0
    assert c.page.evaluate("JarvisAudio.isOpen()") is False
    assert c.page.locator("#micBtn").get_attribute("data-state") == "idle"
    assert c.errors == []
