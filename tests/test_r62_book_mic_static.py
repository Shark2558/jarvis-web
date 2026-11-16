# tests/test_r62_book_mic_static.py -- R6.2 Part 1 (Phase A findings 4.5): the static seams of
# the Book's "Ask by voice" fix, beside the browser tests (tests/browser/test_r62_book_mic.py). One
# table of microphone words lives in the shared R5 capture module (JarvisAudio.words) and the
# console and the Book both read it (no fork); the Book switches "Mic off" back on only through
# JarvisAudio.unlock('button') behind a real tap (isTrusted, R5 D11); the show page carries the
# status line and the switch-on button with the existing styles only.
from __future__ import annotations

import re
from pathlib import Path

STATIC = Path(__file__).resolve().parents[1] / "src/jarvis/api/static"
CODES = ("blocked", "no_mic", "busy", "unsupported", "failed", "ended", "silent")


def _read(name: str) -> str:
    return (STATIC / name).read_text(encoding="utf-8")


def _words_table(capture: str) -> str:
    m = re.search(r"const WORDS = Object\.freeze\(\{(.*?)\n  \}\);", capture, re.S)
    assert m, "the WORDS table"
    return m.group(1)


def test_the_capture_module_holds_the_one_table_of_microphone_words() -> None:
    capture = _read("console-voice-capture.js")
    table = _words_table(capture)
    for code in CODES:
        assert re.search(rf"\b{code}:", table), code
    assert "WORDS, words," in capture  # exposed on window.JarvisAudio
    for step in ("Chrome", "Windows", "Android", "Site settings", "tap the mic again"):
        assert step in table, step


def test_the_console_reads_the_shared_table_and_keeps_only_its_own_lines() -> None:
    mic = _read("console-voice-mic.js")
    assert "const HELP = Object.freeze(Object.assign({}, A.WORDS, {" in mic
    for gone in ("No microphone was found", "Another app is using the microphone"):
        assert gone not in mic, gone  # no second copy to drift
    assert "mic_off: LOCKED_LINE" in mic and "cloud_down:" in mic  # the console's own controls


def test_the_book_reads_the_same_words_and_never_forks_the_capture() -> None:
    talk, voice = _read("console-book-talk.js"), _read("console-book-voice.js")
    assert ".words(" in talk
    for name, text in (("talk", talk), ("voice", voice)):
        assert "getUserMedia" not in text and "AudioWorkletNode" not in text, name
        assert "No microphone was found" not in text, name


def test_only_a_real_tap_switches_the_microphone_back_on() -> None:
    talk = _read("console-book-talk.js")
    m = re.search(r"function micOn\(e\) \{(.*?)\n  \}", talk, re.S)
    assert m, "micOn"
    body = m.group(1)
    assert "e.isTrusted" in body and ".unlock('button')" in body
    # security review 1, H1: only the owner's own show may lift his lock, never a guest's tap
    assert "S.owner" in body and body.index("S.owner") < body.index(".unlock('button')")
    assert talk.count(".unlock(") == 1  # nothing else in the Book unlocks it
    assert "jarvis_mic_off_v1" not in talk and "localStorage" not in talk


def test_the_talk_panel_is_told_whose_show_it_is() -> None:
    show, talk = _read("console-book-show.js"), _read("console-book-talk.js")
    assert "audience: S.script.audience" in show  # the server's own script answer, never the tab
    assert "S.owner = !!(opts && opts.audience === 'owner')" in talk
    m = re.search(r"function micState\(\) \{(.*?)\n  \}", talk, re.S)
    assert m and "S.owner" in m.group(1), "the switch-on button is the owner's only"


def test_the_show_page_has_the_status_line_and_the_switch_on_button() -> None:
    html = _read("book.html")
    assert re.search(r'<p class="hint" id="shHear" role="status" aria-live="polite" hidden>', html)
    assert re.search(r'<button class="btn lift" id="shMicOn" type="button" hidden>', html)
    mic = re.search(r'<button class="icon-btn sh-mic" id="shMic"[^>]*>', html)
    assert mic and 'aria-describedby="shHear"' in mic.group(0)
    assert html.index('id="shMicOn"') < html.index('id="shFinish"')


def test_the_book_listens_only_through_the_shared_recogniser() -> None:
    """Decision 4: the browser's recogniser comes from JarvisAudio.recognizer() (the one
    constructor, which the "Mic off" lock refuses and aborts); the Book never builds its own."""
    talk, voice, capture = (
        _read("console-book-talk.js"),
        _read("console-book-voice.js"),
        _read("console-voice-capture.js"),
    )
    for name, text in (("talk", talk), ("voice", voice)):
        assert "SpeechRecognition" not in text, name
    assert ".recognizer()" in voice and "lang = 'en-IN'" in voice
    assert capture.count("new R()") == 1 and "canRecognise" in capture
    table = _words_table(capture)
    for code in ("rec_unsupported", "rec_refused", "rec_network", "rec_language", "rec_stopped"):
        assert re.search(rf"\b{code}:", table) and "Type your question" in table, code


def test_the_switch_is_pointed_to_for_the_owner_only_and_never_flipped_by_the_page() -> None:
    talk = _read("console-book-talk.js")
    m = re.search(r"const recWords = \(code\) => (.*?);\n", talk)
    assert m and "S.owner" in m.group(1), "the pointer to the switch is the owner's only"
    assert "/v1/book/settings" not in talk  # the show never changes the setting by itself
