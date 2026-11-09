# ruff: noqa: F811, E501  (imported fixtures; long lines are JS snippets and prose)
# tests/browser/test_voice_commands.py — R5 workstream A, the built-in voice commands (docs/plans/r5-voice.md
# D12): "mic off", "stop" and "switch to the keyboard" are matched on the whole utterance only, run before
# the chat, work with the AI off, and never see typed text. 100 cases live in
# tests/fixtures/voice_commands_cases.json (positives and negatives at 100 %).
from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path

import pytest
from test_console import Console
from test_voice import FakeVoice
from test_voice_robust import (  # noqa: F401  (fixtures)
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

CASES = json.loads(
    (Path(__file__).parent.parent / "fixtures" / "voice_commands_cases.json").read_text("utf-8")
)


def test_the_case_table_is_big_enough_and_has_both_kinds() -> None:
    assert len(CASES) >= 80
    assert sum(1 for c in CASES if c["id"] is None) >= 20
    assert {c["id"] for c in CASES} >= {"mic.off", "speech.stop", "conversation.keyboard", None}


def test_every_case_is_owned_by_the_right_command_and_nothing_else(
    make: Callable[..., Console],
) -> None:
    c = make()
    c.open()
    got = c.page.evaluate(
        "(cases) => cases.map(x => JarvisVoiceCommands.owns(x.text, x.state))", CASES
    )
    wrong = [
        (x["text"], x["state"], x["id"], g) for x, g in zip(CASES, got, strict=True) if g != x["id"]
    ]
    assert wrong == []  # positives and negatives, 100 %
    assert c.errors == []


def test_a_naive_substring_matcher_would_fail_many_of_the_negatives(
    make: Callable[..., Console],
) -> None:
    """Control: the guard that matters is "whole utterance only"; substring matching is clearly worse."""
    c = make()
    c.open()
    bad = c.page.evaluate(
        """(cases) => {
      const P = JarvisVoiceCommands.PHRASES, ids = ['mic.off', 'speech.stop', 'conversation.keyboard'];
      const naive = (t) => ids.find(id => P[id].some(p => t.toLowerCase().includes(p))) || null;
      return cases.filter(x => x.id === null && naive(x.text) !== null).length;
    }""",
        CASES,
    )
    assert bad >= 10
    assert c.errors == []


def test_typed_text_and_the_wrong_source_are_never_routed(make: Callable[..., Console]) -> None:
    c = make()
    c.open()
    got = c.page.evaluate(
        """async () => [
      await JarvisVoiceCommands.handle('mic off', { source: 'typed', state: 'listening' }),
      await JarvisVoiceCommands.handle('mic off', { source: 'answer', state: 'speaking' }),
      await JarvisVoiceCommands.handle('mic off', null),
    ]"""
    )
    assert got == [{"handled": False}] * 3
    assert c.page.evaluate("JarvisAudio.locked()") is False
    assert c.errors == []


def test_typed_mic_off_goes_to_the_chat_and_the_mic_stays_on(make: Callable[..., Console]) -> None:
    c = make(device={"keepListening": False})
    chats: list[int] = []
    c.page.route("**/v1/chat", lambda r: (chats.append(1), r.continue_()))
    c.open()
    c.send("mic off")
    c.page.wait_for_selector(".row.user")
    assert chats and c.page.evaluate("JarvisAudio.locked()") is False
    c.page.locator("#micBtn").click()
    assert c.page.locator("#micBtn").get_attribute("data-state") == "listening"
    c.page.keyboard.press("Escape")
    assert c.errors == []


def test_a_spoken_stop_in_a_listening_turn_is_not_sent_to_the_chat(
    make: Callable[..., Console],
) -> None:
    c = make(device={"keepListening": False})
    fake = FakeVoice(c.page)
    fake.transcript["text"] = "stop"
    chats: list[int] = []
    c.page.route("**/v1/chat", lambda r: (chats.append(1), r.continue_()))
    c.open()
    c.page.locator("#micBtn").click()
    for _ in range(300):
        if _count(fake, "/v1/voice/transcribe") >= 1:
            break
        c.page.wait_for_timeout(100)
    c.page.wait_for_timeout(500)
    assert _count(fake, "/v1/voice/transcribe") == 1 and chats == []
    assert c.page.locator("#micBtn").get_attribute("data-state") == "idle"
    assert c.errors == []


def test_a_spoken_mic_off_locks_the_microphone_before_any_chat_and_says_so(
    make: Callable[..., Console],
) -> None:
    c = make(device={"speak": "always", "keepListening": True})
    fake = FakeVoice(c.page)
    fake.transcript["text"] = "Jarvis, mic off please"
    chats: list[int] = []
    c.page.route("**/v1/chat", lambda r: (chats.append(1), r.continue_()))
    c.open()
    c.page.locator("#micBtn").click()
    _until(c, "JarvisAudio.locked()", 30)
    assert chats == []
    assert c.page.evaluate("JarvisAudio.isOpen()") is False
    _until(c, "document.getElementById('micBtn').dataset.state === 'off'", 15)
    assert "Microphone off, Sir." in fake.spoken()
    assert c.page.evaluate("localStorage.getItem('jarvis_mic_off_v1')") == "1"
    assert c.errors == []


def test_ask_waits_for_yes_or_no_and_times_out_quietly(make: Callable[..., Console]) -> None:
    c = make()
    c.open()
    got = c.page.evaluate(
        """async () => {
      const C = JarvisVoiceCommands, out = {};
      out.timeout = await C.ask('Shall I?', { timeoutMs: 150 });
      let yes = 0;
      const p = C.ask('Shall I?', { timeoutMs: 5000, yes: () => { yes++; } });
      out.pending = C.pending();
      out.handled = await C.handle('Yes please', { source: 'voice', state: 'listening' });
      out.answer = await p;
      out.yes = yes;
      out.noAsk = await C.handle('yes', { source: 'voice', state: 'listening' });
      const q1 = C.ask('One?', { timeoutMs: 5000 });
      const q2 = C.ask('Two?', { timeoutMs: 150 });
      out.cancelled = await q1;
      out.second = await q2;
      return out;
    }"""
    )
    assert got["timeout"] == "timeout"
    assert got["pending"] == "Shall I?"
    assert got["handled"]["id"] == "answer.yes" and got["answer"] == "yes" and got["yes"] == 1
    assert got["noAsk"] == {"handled": False}  # "yes" means nothing without a pending question
    assert got["cancelled"] == "cancelled" and got["second"] == "timeout"
    assert c.errors == []


def test_the_mic_stays_off_for_an_ask_while_locked(make: Callable[..., Console]) -> None:
    c = make(scripts=(TONE_MIC,))
    c.open()
    c.page.evaluate("JarvisAudio.lock('button')")
    got = c.page.evaluate("JarvisVoiceCommands.handle('stop', { source: 'voice', state: 'off' })")
    assert got == {"handled": False}
    assert c.errors == []
