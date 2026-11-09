# ruff: noqa: F811, E501  (imported fixtures; long lines are JS snippets and prose)
# tests/browser/test_voice_fixes.py — R5 workstream A, the fixer's regression tests (code + security
# review of r5-a): the Web Speech phrases refusal (V1), the bounds of a hands-free conversation (H1, SH1),
# the check-in (M2), handover races (M1), the mic lock hardening (SM1, SM6), echo guards (SM3, SM4),
# check clips (SM5), and the small ones. Each test names the finding it proves.
from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

import pytest
from test_console import Console
from test_voice import FAKE_RECOGNITION, FAKE_WAKE, FakeVoice, _json, _wait
from test_voice_loop import RECORD_LOOP, _say_one_sentence, _tv
from test_voice_robust import (  # noqa: F401  (fixtures and helpers)
    FAST_TV,
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
    make,
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


def _chat_reply(
    approvals: int = 0, text: str = "Done, Sir. It is ready to send."
) -> dict[str, Any]:
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


def _route_reply(c: Console, reply: dict[str, Any]) -> None:
    c.page.route("**/v1/chat", lambda r: _json(r, 200, reply))


# ================================================================== H1
def test_an_approval_after_a_spoken_turn_ends_the_conversation_and_closes_the_mic_h1(
    make: Callable[..., Console],
) -> None:
    c = make(device={"speak": "always", "keepListening": True}, scripts=(TONE_MIC,))
    fake = FakeVoice(c.page)
    _route_reply(c, _chat_reply(approvals=1))
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
        scripts=(TONE_MIC, FAST_TV, RECORD_LOOP),
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
