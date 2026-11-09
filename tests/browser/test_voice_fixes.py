# ruff: noqa: F811, E501  (imported fixtures; long lines are JS snippets and prose)
# tests/browser/test_voice_fixes.py — R5 workstream A, the fixer's regression tests (code + security
# review of r5-a): the Web Speech phrases refusal (V1), the bounds of a hands-free conversation (H1, SH1),
# the check-in (M2), handover races (M1), the mic lock hardening (SM1, SM6), echo guards (SM3, SM4),
# check clips (SM5), and the small ones. Each test names the finding it proves.
from __future__ import annotations

import json
from collections.abc import Callable

import pytest
from test_console import Console
from test_notes import FakeNotes
from test_voice import (
    FAKE_RECOGNITION,
    FAKE_WAKE,
    FakeVoice,
    _mic_state,
    _wait,
    wav_bytes,
)
from test_voice_loop import RECORD_LOOP, _say_one_sentence, _tv
from test_voice_robust import (  # noqa: F401  (fixtures and helpers)
    FAST_TV,
    REPLY_TV,
    SLOW_GUM,
    STALL,
    TONE_MIC,
    _chat_counter,
    _count,
    _line,
    _mic_file,
    _playwright,
    _until,
    browser,
    chat_reply,
    make,
    route_reply,
)

_pw = pytest.importorskip("playwright.sync_api")

pytestmark = pytest.mark.browser

# V1: a recogniser that, like Chrome 140+ in the cloud mode, refuses to start once it was given phrases.
# The phrases module (part C) is replaced after load by a counter that sets `phrases` on the recogniser.
PHRASE_REFUSING_REC = """
(() => {
  window.__applied = 0; window.__starts = [];
  window.addEventListener('load', () => {
    const Base = window.SpeechRecognition;
    class R2 extends Base {
      start() {
        window.__starts.push((this.phrases || []).length);
        if (this.phrases && this.phrases.length) {
          this.done = true;
          setTimeout(() => { this.onerror && this.onerror({ error: 'phrases-not-supported' }); this.onend && this.onend(); }, 10);
          return;
        }
        super.start();
      }
    }
    window.SpeechRecognition = window.webkitSpeechRecognition = R2;
    window.JarvisVoicePhrases = { apply(rec) { window.__applied++; rec.phrases = [{ phrase: 'Trivandrum' }]; return true; } };
  });
})();
"""


# ================================================================== V1
def test_a_browser_that_refuses_phrases_still_listens_and_is_never_offered_them_again(
    make: Callable[..., Console],
) -> None:
    """V1: phrases-not-supported retries the same turn at once without hints; no error line, no help."""
    c = make(
        device={"engine": "browser", "keepListening": False},
        scripts=(FAKE_RECOGNITION, PHRASE_REFUSING_REC),
    )
    FakeVoice(c.page)
    chats = _chat_counter(c)
    c.open()
    c.page.locator("#micBtn").click()
    c.page.locator(".row.user .bubble", has_text="Remind me about the review.").wait_for()
    assert c.page.evaluate("window.__starts") == [
        1,
        0,
    ]  # refused with phrases, then listened without
    assert c.page.evaluate("window.__applied") == 1
    assert _line(c) == "" and c.page.locator("#micHelp").is_hidden()
    _wait(c, "() => document.getElementById('micBtn').dataset.state === 'idle'")
    c.page.evaluate("window.__said = 'Second turn please.'")
    c.page.locator("#micBtn").click()
    c.page.locator(".row.user .bubble", has_text="Second turn please.").wait_for()
    assert (
        c.page.evaluate("window.__applied") == 1
    )  # apply() is never called again this page session
    assert len(chats) == 2 and c.errors == []


# ================================================================== SH1, pure parts
def test_the_clock_counts_from_the_last_real_turn_when_given_the_elapsed_time_sh1(
    make: Callable[..., Console],
) -> None:
    c = make()
    c.open()
    got = c.page.evaluate(
        """async () => {
      const sleep = (ms) => new Promise(r => setTimeout(r, ms)), log = [];
      const k = JarvisConversation.create({ followUpMs: 150, longPauseMs: 300,
        onStandby: () => log.push('standby'), onLongPause: () => log.push('pause') });
      k.replyEnded(0);
      await sleep(200);                              // the owner's turn was noise: the loop builds the clock again
      const before = k.sinceReplyMs();
      k.replyEnded(200);                             // ... from the same reply end, not from now
      const since = k.sinceReplyMs();
      await sleep(140);
      return { log, since, before };
    }"""
    )
    assert got["log"] == [
        "standby",
        "standby",
        "pause",
    ]  # the second clock fires its pause 100 ms on
    assert got["since"] >= 195
    assert c.errors == []


def test_the_check_in_accepts_only_a_strict_yes_sh1(make: Callable[..., Console]) -> None:
    """'okay', 'sure', 'yeah' and 'yep' are TV words: not a yes to the check-in (they still answer an offer)."""
    c = make()
    c.open()
    got = c.page.evaluate(
        """async () => {
      const C = JarvisVoiceCommands, out = {};
      const ctx = { source: 'voice', state: 'listening' };
      for (const said of ['okay', 'sure', 'yeah', 'yep', 'ok', 'go ahead', 'do it']) {
        const p = C.ask('Shall I keep listening, Sir?', { timeoutMs: 400, strict: true });
        const r = await C.handle(said, ctx);
        out[said] = [r.handled, await p];
      }
      for (const said of ['yes', 'yes please', 'keep listening', 'carry on', 'continue', 'go on', 'Jarvis, yes']) {
        const p = C.ask('Shall I keep listening, Sir?', { timeoutMs: 400, strict: true });
        const r = await C.handle(said, ctx);
        out[said] = [r.handled, await p];
      }
      const p = C.ask('Use it?', { timeoutMs: 400 });                   // a device offer: unchanged
      out.offerOkay = [(await C.handle('okay', ctx)).handled, await p];
      const n = C.ask('Shall I keep listening, Sir?', { timeoutMs: 400, strict: true });
      out.no = [(await C.handle('no', ctx)).handled, await n];
      return out;
    }"""
    )
    for said in ("okay", "sure", "yeah", "yep", "ok", "go ahead", "do it"):
        assert got[said] == [False, "timeout"], said
    for said in (
        "yes",
        "yes please",
        "keep listening",
        "carry on",
        "continue",
        "go on",
        "Jarvis, yes",
    ):
        assert got[said] == [True, "yes"], said
    assert got["offerOkay"] == [True, "yes"] and got["no"] == [True, "no"]
    assert c.errors == []


def test_an_ask_can_be_held_while_the_owner_is_still_answering_m2(
    make: Callable[..., Console],
) -> None:
    c = make()
    c.open()
    got = c.page.evaluate(
        """async () => {
      const C = JarvisVoiceCommands, sleep = (ms) => new Promise(r => setTimeout(r, ms));
      let busy = true;
      const p = C.ask('Shall I keep listening?', { timeoutMs: 150, hold: () => busy });
      await sleep(400);
      const stillOpen = C.pending() !== null;           // held past its time while the answer is on its way
      busy = false;
      const r = await C.handle('yes', { source: 'voice', state: 'listening' });
      return { stillOpen, answer: await p, handled: r.handled };
    }"""
    )
    assert got == {"stillOpen": True, "answer": "yes", "handled": True}
    assert c.errors == []


# ================================================================== helpers for the conversation tests
APPROVAL_LINE = "That one needs your approval on screen, Sir."
# JarvisChat.send answers false while window.__failSend (the loop must not be left hot with no clock).
FAIL_SEND = """
(() => {
  window.__failSend = false;
  let real = null;
  Object.defineProperty(window, 'JarvisChat', { configurable: true, get() { return real; },
    set(v) { real = Object.freeze(Object.assign({}, v, { send: (...a) => (window.__failSend ? Promise.resolve(false) : v.send(...a)) })); } });
})();
"""


# ================================================================== H1
def test_an_approval_after_a_spoken_turn_ends_the_conversation_and_closes_the_mic_h1(
    make: Callable[..., Console],
) -> None:
    c = make(device={"speak": "always", "keepListening": True}, scripts=(TONE_MIC,))
    fake = FakeVoice(c.page)
    route_reply(c, chat_reply(approvals=1))
    c.open()
    _say_one_sentence(c)
    _wait(c, "() => window.__voice.speech.length >= 1")
    _until(
        c,
        "document.getElementById('micBtn').dataset.state === 'idle' && !JarvisVoice.speaker.speaking()",
        20,
    )
    assert fake.spoken() == [APPROVAL_LINE]
    c.page.wait_for_timeout(600)
    assert c.page.evaluate("JarvisAudio.isOpen()") is False  # no hot mic, no clock, no conversation
    assert c.page.evaluate("JarvisVoiceLoop.inConversation()") is False
    assert c.errors == []


def test_with_speaking_set_to_never_the_conversation_keeps_a_clock_h1(
    make: Callable[..., Console],
) -> None:
    c = make(
        device={"speak": "never", "keepListening": True, "followUpS": 3, "longPauseS": 10},
        scripts=(TONE_MIC, RECORD_LOOP),
    )
    FakeVoice(c.page)
    c.open()
    _say_one_sentence(c)
    _until(c, "document.querySelectorAll('.row.user').length >= 1", 30)
    # nothing is said, so the loop goes straight back to listening, with the clock running ...
    _until(c, "window.__loop.filter(e => e.state === 'listening').length >= 2", 10)
    # ... and the clock hands over by itself (it would have stayed hot for ever before)
    _until(
        c,
        "document.getElementById('micBtn').dataset.state === 'idle' && window.__loop.some(e => e.state === 'standby')",
        20,
    )
    assert c.page.evaluate("JarvisAudio.isOpen()") is False
    assert "Switched to the keyboard" in _line(c)
    assert c.errors == []


def test_a_send_that_resolves_false_does_not_leave_the_mic_hot_h1(
    make: Callable[..., Console],
) -> None:
    c = make(
        device={"speak": "always", "keepListening": True, "followUpS": 3, "longPauseS": 10},
        scripts=(TONE_MIC, FAIL_SEND, RECORD_LOOP),
    )
    FakeVoice(c.page)
    c.open()
    c.page.evaluate("window.__failSend = true")
    _say_one_sentence(c)
    _until(c, "window.__loop.filter(e => e.state === 'thinking').length >= 1", 20)
    _until(
        c,
        "document.getElementById('micBtn').dataset.state === 'idle' && window.__loop.some(e => e.state === 'standby')",
        25,
    )
    assert c.page.evaluate("JarvisAudio.isOpen()") is False
    assert c.errors == []


# ================================================================== SH1
def test_a_room_of_noise_that_transcribes_to_nothing_hands_over_after_three_empty_turns_sh1(
    make: Callable[..., Console],
) -> None:
    c = make(
        device={
            "speak": "always",
            "keepListening": True,
            "endSilenceMs": 800,
            "longPauseS": 60,
            "followUpS": 30,
        },
        scripts=(TONE_MIC, FAST_TV, RECORD_LOOP),
    )
    fake = FakeVoice(c.page)
    fake.transcript.update({"text": "", "no_speech": True})
    chats = _chat_counter(c)
    c.open()
    c.page.evaluate("window.__tvFast()")
    c.page.locator("#micBtn").click()
    _until(c, "window.__loop.some(e => e.state === 'speaking' || e.state === 'handover')", 60)
    _until(c, "document.getElementById('micBtn').dataset.state === 'idle'", 30)
    assert _count(fake, "/v1/voice/transcribe") == 3
    assert "I'll switch to the keyboard, Sir." in fake.spoken()
    assert "Switched to the keyboard" in _line(c)
    assert c.page.evaluate("JarvisAudio.isOpen()") is False and chats == []
    assert c.errors == []


def test_an_okay_does_not_answer_the_check_in_and_the_words_go_back_to_the_box_sh1_m3(
    make: Callable[..., Console],
) -> None:
    c = make(
        device={"speak": "always", "keepListening": True, "endSilenceMs": 800},
        scripts=(TONE_MIC, REPLY_TV, RECORD_LOOP),
    )
    fake = FakeVoice(c.page)
    c.open()
    _tv(c, fake)
    question = "Shall I keep listening, Sir?"
    _until(c, f"window.__voice.speech.some(d => d.text === {json.dumps(question)})", 150)
    fake.transcript["text"] = "okay"
    _until(c, "document.getElementById('micBtn').dataset.state === 'idle'", 40)
    assert (
        "Switched to the keyboard" in _line(c)
        or "I'll switch to the keyboard, Sir." in fake.spoken()
    )
    assert c.page.locator("#input").input_value() == "okay"  # M3: nothing the owner said is lost
    assert c.page.evaluate("JarvisAudio.isOpen()") is False
    assert c.errors == []


# ================================================================== SM1, SM6 and the lock lows
STATE = "document.getElementById('micBtn').dataset.state"
LOCK_KEY = "jarvis_mic_off_v1"
# a button that calls unlock() from inside a real click (user activation)
CLICK_UNLOCK = """() => {
  const b = document.createElement('button');
  b.id = 'unlockTest'; b.textContent = 'unlock';
  b.style.cssText = 'position:fixed;left:0;top:0;z-index:99999;width:120px;height:50px';
  b.onclick = () => { window.__unlocked = window.JarvisAudio.unlock('button'); };
  document.body.append(b);
}"""
# Playwright's evaluate() carries a user activation, so a script's own synthetic event looks "active" here:
# exactly the case isTrusted exists for.
SYNTHETIC_KEY = """() => document.dispatchEvent(new KeyboardEvent('keydown',
  { key: ' ', code: 'Space', ctrlKey: true, shiftKey: true, bubbles: true, cancelable: true }))"""


def test_a_synthetic_shortcut_never_unlocks_the_microphone_sm1(
    make: Callable[..., Console],
) -> None:
    c = make(scripts=(SLOW_GUM,))
    FakeVoice(c.page)
    c.open()
    c.page.evaluate("JarvisAudio.lock('button')")
    c.page.evaluate(SYNTHETIC_KEY)
    assert c.page.evaluate("JarvisAudio.locked()") is True and c.page.evaluate(STATE) == "off"
    c.page.keyboard.press("Control+Shift+Space")  # a real key press does
    assert c.page.evaluate("JarvisAudio.locked()") is False
    assert c.page.evaluate("window.__streams.length") == 0
    assert c.errors == []


def test_a_script_click_on_the_mic_or_the_panel_switch_never_unlocks_sm1(
    make: Callable[..., Console],
) -> None:
    c = make(scripts=(SLOW_GUM,))
    fake = FakeVoice(c.page)
    c.open()
    _voice_panel_open(c)
    c.page.evaluate("JarvisAudio.lock('button')")
    c.page.evaluate("document.getElementById('micBtn').click()")
    c.page.evaluate("document.getElementById('vMic').click()")
    c.page.wait_for_timeout(400)
    assert c.page.evaluate("JarvisAudio.locked()") is True and c.page.evaluate(STATE) == "off"
    assert c.page.evaluate("window.__streams.length") == 0
    assert fake.to("POST", "/v1/voice/transcribe") == []
    assert c.errors == []


def test_a_forged_storage_event_never_unlocks_the_microphone_sm1(
    make: Callable[..., Console],
) -> None:
    c = make(device={"wake": True}, scripts=(SLOW_GUM, FAKE_WAKE))
    FakeVoice(c.page)
    c.open()
    _wait(c, "() => window.__wake.started === 1")
    c.page.evaluate("JarvisAudio.lock('button')")
    before = c.page.evaluate("window.__streams.length")
    c.page.evaluate(
        f"() => {{ localStorage.removeItem('{LOCK_KEY}');"
        f" window.dispatchEvent(new StorageEvent('storage', {{ key: '{LOCK_KEY}', storageArea: localStorage }})); }}"
    )
    c.page.wait_for_timeout(500)
    assert c.page.evaluate("JarvisAudio.locked()") is True
    assert c.page.evaluate("window.__streams.length") == before
    assert c.page.evaluate("window.__wake.started") == 1
    assert c.errors == []


def test_a_real_unlock_in_another_tab_does_not_open_this_ones_microphone_sm1(
    make: Callable[..., Console],
) -> None:
    a = make(device={"wake": True}, scripts=(SLOW_GUM, FAKE_WAKE))
    FakeVoice(a.page)
    a.open()
    _wait(a, "() => window.__wake.started === 1")
    a.page.evaluate("JarvisAudio.lock('button')")
    before = a.page.evaluate("window.__streams.length")
    b_page = a.ctx.new_page()
    b_page.goto(a.url + "/")
    b_page.wait_for_function("() => !!window.JarvisAudio && window.JarvisAudio.locked() === true")
    b_page.evaluate(CLICK_UNLOCK)
    b_page.locator("#unlockTest").click()
    a.page.wait_for_function("() => window.JarvisAudio.locked() === false")
    a.page.wait_for_timeout(800)
    assert a.page.evaluate(STATE) == "idle"
    assert (
        a.page.evaluate("window.__wake.started") == 1
    )  # still the first start: "ready", not listening
    assert a.page.evaluate("window.__streams.length") == before  # nothing was opened here
    a.page.locator("#welcome").click()  # a gesture in THIS tab
    _wait(a, "() => window.__wake.started === 2")
    assert a.errors == []
    b_page.close()


def test_a_throwing_speaker_still_leaves_the_microphone_locked_by_mic_off_sm6(
    make: Callable[..., Console],
) -> None:
    c = make(device={"speak": "always", "keepListening": True}, scripts=(TONE_MIC, THROWING_STOP))
    fake = FakeVoice(c.page)
    fake.transcript["text"] = "Jarvis, mic off"
    c.open()
    c.page.evaluate("window.__throwStop = true")
    _say_one_sentence(c)
    _until(c, "JarvisAudio.locked()", 20)
    assert c.page.evaluate("JarvisAudio.isOpen()") is False
    c.page.evaluate("window.__throwStop = false")
    assert c.errors == []


def test_a_lock_the_browser_cannot_store_says_it_will_not_survive_a_reload(
    make: Callable[..., Console],
) -> None:
    c = make(scripts=(NO_LOCK_STORAGE,))
    FakeVoice(c.page)
    c.open()
    c.page.evaluate("JarvisAudio.lock('button')")
    assert c.page.evaluate("JarvisAudio.locked()") is True
    assert "won't stay off after a reload" in _line(c)
    assert c.errors == []


def test_a_microphone_that_is_gone_is_not_retried_after_the_lock(
    make: Callable[..., Console],
) -> None:
    c = make(scripts=(GONE_MIC,))
    FakeVoice(c.page)
    c.open()
    c.page.evaluate("JarvisAudio.setInput('dev-42')")
    c.page.evaluate("void (window.__open = JarvisAudio.open().then(() => 'opened', (e) => e.code))")
    c.page.evaluate("JarvisAudio.lock('button')")  # while the first request is still pending
    c.page.wait_for_timeout(900)
    assert c.page.evaluate("window.__open") in ("closed", "mic_off")
    assert c.page.evaluate("window.__cons") == 1  # no second request, with the default microphone
    assert c.errors == []


THROWING_STOP = """
(() => {
  window.__throwStop = false;
  let real = null;
  Object.defineProperty(window, 'JarvisSpeaker', { configurable: true, get() { return real; },
    set(v) { real = Object.freeze(Object.assign({}, v, { create: (o) => {
      const sp = v.create(o), stop = sp.stop;
      sp.stop = (...a) => { if (window.__throwStop) throw new Error('boom'); return stop.apply(sp, a); };
      return sp; } })); } });
})();
"""
NO_LOCK_STORAGE = """
(() => {
  const set = Storage.prototype.setItem;
  Storage.prototype.setItem = function (k, v) { if (k === 'jarvis_mic_off_v1') throw new Error('blocked'); return set.call(this, k, v); };
})();
"""
GONE_MIC = """
(() => {
  window.__cons = 0;
  navigator.mediaDevices.getUserMedia = (c) => { window.__cons++;
    return new Promise((_, rej) => setTimeout(() => rej(new DOMException('gone', 'OverconstrainedError')), 500)); };
})();
"""


def _voice_panel_open(c: Console) -> None:
    c.open_panel("voice")
    c.page.locator("#vVoiceT").wait_for(state="visible")


# ================================================================== M1, M2
def test_an_unplugged_microphone_during_a_spoken_turn_sends_nothing_m1(
    make: Callable[..., Console],
) -> None:
    c = make(device={"speak": "always", "keepListening": True}, scripts=(SLOW_GUM,))
    fake = FakeVoice(c.page)
    fake.hold_transcribe = True
    chats = _chat_counter(c)
    c.open()
    c.page.locator("#micBtn").click()
    for _ in range(300):
        if fake.held_transcribe:
            break
        c.page.wait_for_timeout(100)
    assert fake.held_transcribe  # the words are with the cloud, JARVIS is "thinking"
    assert _mic_state(c) == "thinking"
    c.page.evaluate("window.__streams[0].getAudioTracks()[0].dispatchEvent(new Event('ended'))")
    _until(c, "window.__voice.speech.length >= 1", 10)
    fake.release_transcribe()  # the transcript arrives after "I'll switch to the keyboard"
    c.page.wait_for_timeout(1200)
    assert chats == []
    assert "The microphone stopped, Sir. I'll switch to the keyboard." in fake.spoken()
    _until(c, "document.getElementById('micBtn').dataset.state === 'idle'", 10)
    assert c.errors == []


def test_a_reply_arriving_during_the_handover_line_is_not_said_and_nothing_sticks_m1(
    make: Callable[..., Console],
) -> None:
    c = make(device={"speak": "always", "keepListening": True}, scripts=(TONE_MIC,))
    fake = FakeVoice(c.page)
    fake.transcript["text"] = "switch to the keyboard"
    fake.speak_audio = wav_bytes(seconds=2.5)
    c.open()
    for round_ in (1, 2):  # twice: a stuck "handing over" would make the second handover silent
        _say_one_sentence(c)
        _until(c, "document.getElementById('micBtn').dataset.state === 'speaking'", 30)
        c.page.evaluate(
            "document.dispatchEvent(new CustomEvent('jarvis:answer',"
            " { detail: { channel: 'voice', text: 'A late reply that must not be said.', approvals: 0 } }))"
        )
        _until(c, "document.getElementById('micBtn').dataset.state === 'idle'", 15)
        assert fake.spoken().count("I'll switch to the keyboard, Sir.") == round_
        c.page.wait_for_timeout(300)
    assert "A late reply that must not be said." not in fake.spoken()
    assert c.page.evaluate("JarvisAudio.isOpen()") is False
    assert c.errors == []


def test_a_yes_heard_after_the_ask_would_have_timed_out_still_counts_m2(
    make: Callable[..., Console],
) -> None:
    c = make(
        device={"speak": "always", "keepListening": True, "endSilenceMs": 800},
        scripts=(TONE_MIC, REPLY_TV, RECORD_LOOP),
    )
    fake = FakeVoice(c.page)
    c.open()
    _tv(c, fake)
    question = "Shall I keep listening, Sir?"
    _until(c, f"window.__voice.speech.some(d => d.text === {json.dumps(question)})", 150)
    fake.hold_transcribe = True  # the owner's "yes" is on its way to the cloud ...
    fake.transcript["text"] = "yes please"
    for _ in range(100):
        if fake.held_transcribe:
            break
        c.page.wait_for_timeout(100)
    assert fake.held_transcribe
    c.page.wait_for_timeout(9000)  # ... for longer than the eight seconds the question waits
    assert not c.page.evaluate("window.__loop.some(e => e.state === 'handover')")
    fake.hold_transcribe = False
    before = _count(fake, "/v1/voice/transcribe")
    fake.release_transcribe()
    for _ in range(100):
        if _count(fake, "/v1/voice/transcribe") >= before + 2:
            break
        c.page.wait_for_timeout(200)
    assert _count(fake, "/v1/voice/transcribe") >= before + 2  # it went on listening
    assert not c.page.evaluate("window.__loop.some(e => e.state === 'handover')")
    assert fake.spoken().count(question) == 1
    c.page.keyboard.press("Escape")
    assert c.errors == []


def test_ending_or_cancelling_a_conversation_cancels_a_question_waiting_for_a_yes_m2(
    make: Callable[..., Console],
) -> None:
    c = make(device={"keepListening": True}, scripts=(TONE_MIC,))
    FakeVoice(c.page)
    c.open()
    ended = c.page.evaluate(
        """async () => { const p = JarvisVoiceLoop.ask('Use the earphones?', { timeoutMs: 20000 });
      JarvisVoiceLoop.end('keyboard'); return [await p, JarvisVoiceCommands.pending()]; }"""
    )
    assert ended == ["cancelled", None]
    c.page.locator("#micBtn").click()  # a listening turn
    _until(c, f"{STATE} === 'listening'", 5)
    c.page.evaluate(
        "void (window.__ask = JarvisVoiceLoop.ask('Use the earphones?', { timeoutMs: 20000 }))"
    )
    assert c.page.evaluate("JarvisVoiceCommands.pending()") == "Use the earphones?"
    c.page.keyboard.press("Escape")  # Esc cancels the turn, and with it the question
    assert c.page.evaluate("JarvisVoiceCommands.pending()") is None
    assert c.page.evaluate("window.__ask") == "cancelled"
    assert c.errors == []


# ================================================================== SM4
def test_his_own_closing_words_coming_back_through_the_room_are_not_a_command_sm4(
    make: Callable[..., Console],
) -> None:
    """A reply ending 'say mic off.' must not lock the mic when the room hands it back 400 ms later."""
    c = make(
        device={"speak": "always", "keepListening": True, "endSilenceMs": 800},
        scripts=(TONE_MIC, RECORD_LOOP, COMMAND_COUNT),
    )
    fake = FakeVoice(c.page)
    chats = route_reply(c, chat_reply(text="Whenever you like, just say mic off."))
    c.open()
    fake.speak_audio = wav_bytes(seconds=0.8)
    _say_one_sentence(c)  # "Turn on the lights ..." goes to the chat
    _until(c, "document.getElementById('micBtn').dataset.state === 'speaking'", 30)
    fake.transcript["text"] = "mic off"  # what the next relisten "hears": the end of his own reply
    _until(c, "document.getElementById('micBtn').dataset.state !== 'speaking'", 10)
    before = _count(fake, "/v1/voice/transcribe")
    c.page.evaluate("window.__talk(true)")
    c.page.wait_for_timeout(1500)
    c.page.evaluate("window.__talk(false)")
    for _ in range(100):  # the reverb turn really was transcribed ...
        if _count(fake, "/v1/voice/transcribe") > before:
            break
        c.page.wait_for_timeout(100)
    assert _count(fake, "/v1/voice/transcribe") > before
    c.page.wait_for_timeout(1000)
    assert c.page.evaluate("JarvisAudio.locked()") is False  # ... and went nowhere
    assert c.page.evaluate("window.__commands") == 0  # the router never saw it
    assert len(chats) == 1  # and it was not sent as a message either
    c.page.keyboard.press("Escape")
    assert c.errors == []


COMMAND_COUNT = """
window.__commands = 0;
document.addEventListener('jarvis:voice-command', () => { window.__commands++; });
"""


# ================================================================== the router: his own voice, clips, marks
def test_the_router_ignores_what_he_just_said_while_he_speaks_and_a_clip_needs_the_name_sm4(
    make: Callable[..., Console],
) -> None:
    c = make(scripts=(HOLD_LOOP,))
    FakeVoice(c.page)
    c.open()
    got = c.page.evaluate(
        """async () => {
      const C = JarvisVoiceCommands, out = {};
      const h = async (t, ctx) => { const r = await C.handle(t, Object.assign({ source: 'voice' }, ctx)); return r.handled ? r.id : null; };
      const said = 'please stop talking about it';
      out.echo = await h('stop talking', { state: 'speaking', spoken: said });                   // his own words, quiet
      out.loud = await h('stop talking', { state: 'speaking', spoken: said, peak: 99 });          // far louder than his echo
      out.later = await h('stop talking', { state: 'listening', spoken: said });                  // he is not speaking now
      out.clipBare = await h('mic off', { state: 'speaking', clip: true });
      out.clipNamed = await h('Jarvis, mic off', { state: 'speaking', clip: true });
      out.turnBare = await h('mic off', { state: 'listening' });
      const p = C.ask('Shall I keep listening?', { timeoutMs: 2000, strict: true });
      out.answer = await h('keep listening', { state: 'speaking', spoken: 'Shall I keep listening, Sir?' });
      await p;
      return out;
    }"""
    )
    assert got == {
        "echo": None, "loud": "speech.stop", "later": "speech.stop", "clipBare": None,
        "clipNamed": "mic.off", "turnBare": "mic.off", "answer": "answer.yes",
    }  # fmt: skip
    assert c.errors == []


# The loop's own actions held back, so a command that would lock the mic can be asked about harmlessly.
HOLD_LOOP = """
(() => {
  let real = null;
  Object.defineProperty(window, 'JarvisVoiceCommands', { configurable: true, get() { return real; },
    set(v) { real = Object.freeze(Object.assign({}, v, { bindLoop: () => undefined })); } });
})();
"""


# ================================================================== M7: a memo and a conversation do not share the mic
def test_starting_a_memo_ends_the_voice_conversation_and_sends_nothing_to_the_chat_m7(
    make: Callable[..., Console],
) -> None:
    c = make(device={"keepListening": True}, scripts=(TONE_MIC, SLOW_GUM))
    FakeVoice(c.page)
    notes = FakeNotes(c.page, [])
    chats = _chat_counter(c)
    c.open()
    c.page.locator("#micBtn").click()
    _until(c, f"{STATE} === 'listening'", 5)
    assert c.page.evaluate("JarvisVoiceLoop.inConversation()") is True
    c.open_panel("notes")
    c.page.evaluate("window.__talk(true)")
    c.page.locator("#nRecord").click()
    _until(c, "!JarvisVoiceLoop.inConversation()", 5)
    assert c.page.evaluate(STATE) == "idle"
    _until(c, "JarvisAudio.isOpen()", 5)  # the memo has the microphone, alone
    c.page.wait_for_timeout(1500)
    c.page.evaluate("window.__talk(false)")
    c.page.locator("#nRecord").click()  # Stop
    _until(c, "!JarvisAudio.isOpen()", 5)  # and gives it back for good, not into a conversation
    c.page.wait_for_selector("#nMemoText")
    assert len(notes.to("POST", "/v1/voice/transcribe")) >= 1  # the words went into the memo ...
    assert chats == []  # ... and nowhere else
    assert c.errors == []


# ================================================================== M4: pace and device integration
# A stand-in for part C's timing module, installed after the page's scripts: it records mark(stage, at).
MARKS = """
window.__marks = [];
window.addEventListener('load', () => {
  window.JarvisVoicePace = { cue() {}, mark(stage, at) { window.__marks.push({ stage, at: at ?? null, now: performance.now() }); }, last: () => null };
});
"""
LOOP_TIMES = """
window.__times = [];
document.addEventListener('jarvis:voice-loop', (e) => window.__times.push({ state: e.detail.state, barge: e.detail.barge, at: performance.now() }));
"""


def test_spoke_is_marked_when_the_words_ended_not_when_they_began_m4(
    make: Callable[..., Console],
) -> None:
    c = make(
        device={"keepListening": False, "endSilenceMs": 800, "speak": "never"},
        scripts=(TONE_MIC, MARKS, LOOP_TIMES),
    )
    FakeVoice(c.page)
    c.open()
    c.page.evaluate("window.__talk(true)")
    c.page.locator("#micBtn").click()
    _until(c, "document.getElementById('voiceLive').textContent === 'Hearing you'", 10)
    c.page.wait_for_timeout(600)
    c.page.evaluate("window.__talk(false)")
    _until(c, "window.__times.some(e => e.state === 'thinking')", 10)
    marks = [m for m in c.page.evaluate("window.__marks") if m["stage"] == "spoke"]
    assert len(marks) == 1  # once per turn, from the VAD's end
    thinking = next(e["at"] for e in c.page.evaluate("window.__times") if e["state"] == "thinking")
    assert (
        750 <= thinking - marks[0]["at"] <= 1300
    )  # the silence that ended it: endSilenceMs, plus a frame or two
    assert c.errors == []


def test_a_device_commands_line_is_said_but_does_not_replace_the_one_on_screen_m4(
    make: Callable[..., Console],
) -> None:
    c = make(device={"speak": "always", "keepListening": False}, scripts=(TONE_MIC,))
    fake = FakeVoice(c.page)
    fake.transcript["text"] = "test the device"
    c.open()
    c.page.evaluate(
        """() => JarvisVoiceCommands.register('device.test', {
      match: (n) => (n === 'test the device' ? {} : null),
      run: () => { document.getElementById('voiceLine').textContent = 'Output: Test earphones';
        return { say: 'Now speaking through the earphones.' }; } })"""
    )
    _say_one_sentence(c)
    _until(c, "window.__voice.speech.length >= 1", 30)
    assert fake.spoken() == ["Now speaking through the earphones."]
    assert _line(c) == "Output: Test earphones"  # B's line (the device's name) stays on screen
    assert c.errors == []


# ================================================================== the small ones
VAD_SPY = """
(() => {
  window.__vad = [];
  let real = null;
  Object.defineProperty(window, 'JarvisVad', { configurable: true, get() { return real; },
    set(v) { real = Object.freeze(Object.assign({}, v, { create: (o) => { window.__vad.push(Object.assign({}, o)); return v.create(o); } })); } });
})();
"""
IPAD = """
Object.defineProperty(navigator, 'userAgent', { get: () => 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 Safari/605.1.15' });
Object.defineProperty(navigator, 'maxTouchPoints', { get: () => 5 });
window.__hidden = false;
Object.defineProperty(document, 'hidden', { get: () => window.__hidden });
"""


def test_a_waiting_turn_has_no_55_s_limit_so_the_long_pause_hands_over_aloud_d5(
    make: Callable[..., Console],
) -> None:
    c = make(
        device={"speak": "always", "keepListening": True, "followUpS": 8, "longPauseS": 60},
        scripts=(TONE_MIC, RECORD_LOOP),
    )
    fake = FakeVoice(c.page)
    route_reply(c)
    c.page.clock.install()
    c.open()
    _say_one_sentence(c)
    _until(c, "window.__loop.filter(e => e.state === 'listening').length >= 2", 40)
    c.page.clock.fast_forward(56000)  # past the 55 s a listening turn used to be cut at
    assert c.page.evaluate(STATE) in ("listening", "standby")  # still waiting, not silently ended
    assert "I'll switch to the keyboard, Sir." not in fake.spoken()
    c.page.clock.fast_forward(6000)  # the 60 s long pause: said out loud
    _until(c, "window.__voice.speech.some(d => d.text.includes('switch to the keyboard'))", 10)
    assert "Switched to the keyboard" in _line(c)
    assert c.errors == []


def test_the_strict_start_gate_begins_when_standby_does_not_350_ms_after_the_reply_s(
    make: Callable[..., Console],
) -> None:
    c = make(
        device={"speak": "always", "keepListening": True, "followUpS": 8, "longPauseS": 30},
        scripts=(TONE_MIC, VAD_SPY, RECORD_LOOP),
    )
    FakeVoice(c.page)
    route_reply(c)
    c.open()
    _say_one_sentence(c)
    _until(c, "window.__vad.some(o => o.strictAfterMs > 0)", 40)
    strict = c.page.evaluate("window.__vad.filter(o => o.strictAfterMs > 0)[0].strictAfterMs")
    # standby starts 8 s after the reply ended; this listening turn began after the 350 ms beat and the tone
    assert 6500 < strict < 7600, strict
    c.page.keyboard.press("Escape")
    assert c.errors == []


def test_esc_in_the_beat_before_he_listens_again_ends_the_conversation(
    make: Callable[..., Console],
) -> None:
    c = make(device={"speak": "always", "keepListening": True}, scripts=(TONE_MIC, RECORD_LOOP))
    FakeVoice(c.page)
    route_reply(c)
    c.page.add_init_script(
        """
    (() => {
      let spoke = false;
      document.addEventListener('jarvis:voice-loop', (e) => {
        if (e.detail.state === 'speaking') spoke = true;
        else if (spoke && e.detail.state === 'idle') {
          spoke = false;
          setTimeout(() => document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true, cancelable: true })), 60);
        }
      });
    })();"""
    )
    c.open()
    _say_one_sentence(c)
    _until(c, "window.__voice.speech.length >= 1", 30)
    _until(c, "window.__loop.some(e => e.state === 'idle')", 30)
    c.page.wait_for_timeout(1500)
    assert c.page.evaluate("JarvisVoiceLoop.inConversation()") is False
    assert (
        c.page.evaluate("window.__loop.filter(e => e.state === 'listening').length") == 1
    )  # no second turn
    assert c.page.evaluate("JarvisAudio.isOpen()") is False
    assert c.errors == []


def test_a_command_that_asks_for_nothing_more_does_not_end_a_conversation(
    make: Callable[..., Console],
) -> None:
    c = make(device={"speak": "never", "keepListening": True}, scripts=(TONE_MIC, RECORD_LOOP))
    fake = FakeVoice(c.page)
    fake.transcript["text"] = "go quiet for a while"
    c.open()
    c.page.evaluate(
        "JarvisVoiceCommands.register('test.idle', { match: (n) => (n === 'go quiet for a while' ? {} : null),"
        " run: () => ({ then: 'idle' }) });"
        " window.__ran = []; document.addEventListener('jarvis:voice-command', (e) => window.__ran.push(e.detail.id))"
    )
    _say_one_sentence(c)
    _until(c, "window.__ran.includes('test.idle')", 20)  # the command was heard and run
    c.page.wait_for_timeout(1500)
    assert c.page.evaluate(STATE) in (
        "listening",
        "standby",
    )  # and he is listening again, not at rest
    assert c.page.evaluate("JarvisVoiceLoop.inConversation()") is True
    c.page.keyboard.press("Escape")
    assert c.errors == []


def test_an_ipad_that_says_it_is_a_mac_gets_the_spoken_handover_when_hidden(
    make: Callable[..., Console],
) -> None:
    c = make(device={"speak": "always", "keepListening": True}, scripts=(IPAD, TONE_MIC))
    fake = FakeVoice(c.page)
    c.open()
    c.page.locator("#micBtn").click()
    _until(c, f"{STATE} === 'listening'", 5)
    c.page.evaluate("window.__hidden = true; document.dispatchEvent(new Event('visibilitychange'))")
    _until(c, "window.__voice.speech.length >= 1", 10)
    assert "I'll switch to the keyboard, Sir." in fake.spoken()
    assert c.errors == []


def test_hey_jarvis_switched_on_while_he_speaks_stays_on_afterwards(
    make: Callable[..., Console],
) -> None:
    c = make(
        device={"interruptBy": "name", "speak": "always", "keepListening": True, "wake": False},
        scripts=(TONE_MIC, FAKE_WAKE, RECORD_LOOP),
        barge=True,
    )
    fake = FakeVoice(c.page)
    route_reply(c)
    c.open()
    fake.speak_audio = wav_bytes(seconds=5.0)
    _say_one_sentence(c)
    _until(c, f"{STATE} === 'speaking'", 30)
    _wait(c, "() => window.__wake.started === 1")  # the model runs for his speech only (D8)
    c.page.evaluate("JarvisVoice.setDevice({ wake: true })")  # the owner switches it on meanwhile
    _until(c, f"{STATE} !== 'speaking'", 15)
    c.page.wait_for_timeout(600)
    assert c.page.evaluate("window.__wake.stopped") == 0  # not halted when the speech ended
    assert c.page.evaluate("window.JarvisWake.state") in ("listening", "paused")
    c.page.keyboard.press("Escape")
    assert c.errors == []


def test_the_interrupt_help_says_what_clips_do_and_where_they_do_not_happen(
    make: Callable[..., Console],
) -> None:
    c = make()
    FakeVoice(c.page)
    c.open()
    c.open_panel("voice")
    c.page.locator("#vInterrupt").wait_for(state="attached")
    text = c.page.locator("#p-voice").inner_text()
    assert "only during a voice conversation you started" in text
    assert 'begins with "Jarvis" becomes your next turn' in text
    assert "browser's own listening engine" in text
    assert c.errors == []


def test_a_check_in_cancelled_by_another_question_is_asked_again_afterwards(
    make: Callable[..., Console],
) -> None:
    c = make(
        device={"speak": "always", "keepListening": True, "endSilenceMs": 800},
        scripts=(TONE_MIC, REPLY_TV, RECORD_LOOP),
    )
    fake = FakeVoice(c.page)
    c.open()
    _tv(c, fake)
    question = "Shall I keep listening, Sir?"
    _until(c, f"window.__voice.speech.some(d => d.text === {json.dumps(question)})", 150)
    # another module asks something; that cancels the check-in's question, which is not an answer
    c.page.evaluate("void JarvisVoiceCommands.ask('Use the earphones?', { timeoutMs: 1500 })")
    _until(
        c, f"window.__voice.speech.filter(d => d.text === {json.dumps(question)}).length >= 2", 40
    )
    assert not c.page.evaluate("window.__loop.some(e => e.state === 'handover')")
    c.page.keyboard.press("Escape")
    assert c.errors == []
