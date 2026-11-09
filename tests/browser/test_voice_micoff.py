# ruff: noqa: F811, E501  (imported fixtures; long lines are JS snippets and prose)
# tests/browser/test_voice_micoff.py — R5 workstream A, mic off (docs/plans/r5-voice.md D11): the off button,
# Ctrl + Shift + Space, a tap on the locked mic, the spoken command, the Voice panel switch, reload,
# the Notes memo refusing, an in-flight transcription being dropped, and the negative control that
# nothing opens the microphone while it is off.
from __future__ import annotations

from collections.abc import Callable

import pytest
from test_console import Console
from test_notes import FakeNotes
from test_voice import FAKE_RECOGNITION, FAKE_WAKE, FakeVoice, _voice_panel
from test_voice_robust import (  # noqa: F401  (fixtures and helpers)
    LIVE_TRACKS,
    SLOW_GUM,
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

STATE = "document.getElementById('micBtn').dataset.state"


def test_the_off_button_is_shown_only_while_the_microphone_is_open_and_cuts_it(
    make: Callable[..., Console],
) -> None:
    c = make(device={"keepListening": True}, scripts=(SLOW_GUM, TONE_MIC))
    FakeVoice(c.page)
    c.open()
    off = c.page.locator("#micOffBtn")
    assert off.is_hidden()
    c.page.locator("#micBtn").click()
    _until(c, f"{STATE} === 'listening'", 5)
    off.wait_for(state="visible", timeout=3000)
    assert off.get_attribute("aria-keyshortcuts") == "Control+Shift+Space"
    off.click()
    assert c.page.evaluate("JarvisAudio.locked()") is True
    assert c.page.evaluate("JarvisAudio.isOpen()") is False
    assert c.page.evaluate(f"{STATE}") == "off"
    assert off.is_hidden()
    assert "switch" in str(c.page.locator("#voiceLine").text_content()).lower()
    assert c.errors == []


def test_ctrl_shift_space_switches_the_microphone_off_and_on(make: Callable[..., Console]) -> None:
    c = make(scripts=(SLOW_GUM,))
    c.open()
    c.page.keyboard.press("Control+Shift+Space")
    assert c.page.evaluate("JarvisAudio.locked()") is True
    assert c.page.evaluate(STATE) == "off"
    assert c.page.locator("#voiceLive").text_content() == "Microphone off"
    c.page.keyboard.press("Control+Shift+Space")
    assert c.page.evaluate("JarvisAudio.locked()") is False
    assert c.page.evaluate(STATE) == "idle"  # switching on never starts listening by itself
    assert c.page.evaluate("window.__streams.length") == 0
    assert c.errors == []


def test_a_tap_on_the_locked_mic_unlocks_and_listens(make: Callable[..., Console]) -> None:
    c = make(device={"keepListening": False}, scripts=(TONE_MIC,))
    FakeVoice(c.page)
    c.open()
    c.page.evaluate("JarvisAudio.lock('button')")
    assert c.page.evaluate(STATE) == "off"
    c.page.locator("#micBtn").click()
    assert c.page.evaluate("JarvisAudio.locked()") is False
    _until(c, f"{STATE} === 'listening'", 5)
    c.page.keyboard.press("Escape")
    assert c.errors == []


def test_ctrl_space_on_the_locked_mic_also_switches_it_on_and_listens(
    make: Callable[..., Console],
) -> None:
    c = make(device={"keepListening": False}, scripts=(TONE_MIC,))
    FakeVoice(c.page)
    c.open()
    c.page.evaluate("JarvisAudio.lock('shortcut')")
    c.page.keyboard.press("Control+Space")
    _until(c, f"{STATE} === 'listening'", 5)
    c.page.keyboard.press("Escape")
    assert c.errors == []


def test_the_voice_panel_switch_cuts_the_microphone(make: Callable[..., Console]) -> None:
    c = make(scripts=(SLOW_GUM,))
    c.open()
    _voice_panel(c)
    c.page.locator("#vMic").click()
    assert c.page.evaluate("JarvisAudio.locked()") is True
    assert c.page.evaluate(STATE) == "off"
    assert c.errors == []


def test_off_survives_a_reload_and_nothing_wakes_it(make: Callable[..., Console]) -> None:
    c = make(device={"wake": True}, scripts=(SLOW_GUM, FAKE_WAKE))
    FakeVoice(c.page)
    c.open()
    c.page.evaluate("JarvisAudio.lock('button')")
    c.page.reload()
    c.page.wait_for_function("() => window.JarvisAudio")
    c.page.wait_for_timeout(1500)
    assert c.page.evaluate("JarvisAudio.locked()") is True
    assert c.page.evaluate(STATE) == "off"
    assert c.page.evaluate("window.__wake.started") == 0  # "Hey Jarvis" waits; the setting is kept
    saved = c.page.evaluate("JSON.parse(localStorage.getItem('jarvis_voice_device_v1')).wake")
    assert saved is True
    assert c.page.evaluate("window.__streams.length") == 0
    assert c.errors == []


def test_a_memo_cannot_record_while_the_microphone_is_off(make: Callable[..., Console]) -> None:
    c = make(scripts=(SLOW_GUM,))
    FakeVoice(c.page)
    FakeNotes(c.page, [])
    c.open()
    c.page.evaluate("JarvisAudio.lock('button')")
    c.open_panel("notes")
    rec = c.page.locator("#nRecord")
    rec.wait_for(state="visible", timeout=5000)
    rec.click()
    c.page.wait_for_selector("#nMemo")
    assert "microphone is switched off" in str(c.page.locator("#nMemo").text_content())
    assert c.page.evaluate("window.__streams.length") == 0
    assert c.page.evaluate("JarvisAudio.isOpen()") is False
    assert c.errors == []


def test_locking_mid_recording_stops_the_memo_and_drops_what_was_not_sent(
    make: Callable[..., Console],
) -> None:
    c = make(scripts=(SLOW_GUM, TONE_MIC))
    FakeVoice(c.page)
    notes = FakeNotes(c.page, [])
    c.open()
    c.page.evaluate("window.__talk(true)")
    c.open_panel("notes")
    c.page.locator("#nRecord").click()
    _until(c, "JarvisAudio.isOpen()", 5)
    c.page.wait_for_timeout(700)
    c.page.evaluate("JarvisAudio.lock('button')")
    c.page.wait_for_timeout(500)
    assert c.page.evaluate("JarvisAudio.isOpen()") is False
    assert notes.to("POST", "/v1/voice/transcribe") == []  # the short piece was dropped, not sent
    assert c.errors == []


def test_a_transcription_in_flight_is_dropped_when_the_microphone_is_switched_off(
    make: Callable[..., Console],
) -> None:
    c = make(device={"keepListening": False}, scripts=(TONE_MIC,))
    fake = FakeVoice(c.page)
    fake.hold_transcribe = True
    chats = _chat_counter(c)
    c.open()
    c.page.evaluate("window.__talk(true)")
    c.page.locator("#micBtn").click()
    _until(c, "document.getElementById('voiceLive').textContent === 'Hearing you'", 10)
    c.page.wait_for_timeout(500)
    c.page.evaluate("window.__talk(false)")
    for _ in range(100):
        if fake.held_transcribe:
            break
        c.page.wait_for_timeout(100)
    assert fake.held_transcribe
    c.page.locator("#micOffBtn").click() if c.page.locator(
        "#micOffBtn"
    ).is_visible() else c.page.keyboard.press("Control+Shift+Space")
    assert c.page.evaluate("JarvisAudio.locked()") is True
    fake.release_transcribe()
    c.page.wait_for_timeout(800)
    assert chats == []  # the words that came back were dropped
    assert c.page.evaluate(STATE) == "off"
    assert c.errors == []


def test_nothing_opens_the_microphone_while_it_is_off(make: Callable[..., Console]) -> None:
    """Negative control: the lock holds across the timers, "Hey Jarvis" boot, pageshow and a recogniser.

    The page is locked before any script runs (as after a reload) and its clock is driven by the test:
    fast_forward(30 s) passes the wake word's 10 s late-module wait (WAKE_LATE_MS) and every other
    timer in one go, instead of sleeping through them.
    """
    c = make(
        device={"wake": True, "engine": "browser"},
        scripts=(
            "localStorage.setItem('jarvis_mic_off_v1', '1');",
            SLOW_GUM,
            FAKE_WAKE,
            FAKE_RECOGNITION,
        ),
    )
    FakeVoice(c.page)
    c.page.clock.install()
    c.open()
    assert c.page.evaluate("JarvisAudio.locked()") is True
    c.page.evaluate(
        """() => {
      document.dispatchEvent(new CustomEvent('jarvis:ready'));
      window.dispatchEvent(new PageTransitionEvent('pageshow', { persisted: true }));
      window.dispatchEvent(new Event('load'));
      document.dispatchEvent(new Event('DOMContentLoaded'));
      JarvisVoice.setDevice({ wake: true });
    }"""
    )
    c.page.clock.fast_forward(30000)
    assert c.page.evaluate("window.__streams.length") == 0  # getUserMedia was never asked
    assert c.page.evaluate("window.__rec.length") == 0  # no recogniser was built
    assert c.page.evaluate("window.__wake.started") == 0
    assert c.page.evaluate("JarvisAudio.open().then(() => 'opened', (e) => e.code)") == "mic_off"
    assert c.errors == []
