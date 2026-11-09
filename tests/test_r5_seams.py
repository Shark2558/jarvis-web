# tests/test_r5_seams.py
"""R5 I0 seams, the static half (docs/plans/r5-voice.md, "I0 seams").

The browser half is tests/browser/test_r5_seams.py. Here: the new files exist, are served and are
loaded in the planned order; the microphone is opened and SpeechRecognition built in one file only;
the command table (PHRASES) parses and its multi-word phrases are speech hints; the device defaults;
the status words; the stubs keep their frozen shapes; every console script stays within 800 lines.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
from httpx import AsyncClient

from jarvis.api.console import APP_ASSETS
from jarvis.voice.commands import BASE_PHRASES, COMMAND_HINTS

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "src/jarvis/api/static"

# the order console.html loads the voice scripts in (plan I0 item 7)
VOICE_ORDER = (
    "console-voice-capture.js",
    "console-voice-speech.js",
    "console-voice-commands.js",
    "console-wakeword.js",
    "console-voice.js",
    "console-voice-devices.js",
    "console-voice-devices-panel.js",
    "console-voice-pace.js",
    "console-voice-phrases.js",
    "console-voice-barge.js",
    "console-voice-conversation.js",
    "console-voice-wake.js",
    "console-voice-micoff.js",
    "console-voice-loop-glue.js",
    "console-voice-loop-browser.js",
    "console-voice-mic.js",
)
NEW_SCRIPTS = tuple(
    n for n in VOICE_ORDER if n not in ("console-voice-capture.js", "console-voice-speech.js")
)
NEW_SCRIPTS = tuple(
    n
    for n in NEW_SCRIPTS
    if n not in ("console-wakeword.js", "console-voice.js", "console-voice-mic.js")
)
EMPTY_HEADERS = (
    "console-voice-devices-panel.js",
    "console-voice-phrases.js",
    "console-voice-devices.css",
)
PHRASE_IDS = {
    "answer.yes",
    "answer.no",
    "mic.off",
    "speech.stop",
    "conversation.keyboard",
    "device.switch",
    "device.input",
    "device.list",
}


def read(name: str) -> str:
    return (STATIC / name).read_text(encoding="utf-8")


def phrases() -> dict[str, list[str]]:
    js = read("console-voice-commands.js")
    m = re.search(r"/\*PHRASES-BEGIN\*/(.*?)/\*PHRASES-END\*/", js, re.S)
    assert m, "PHRASES-BEGIN / PHRASES-END markers"
    data = json.loads(m.group(1))
    assert isinstance(data, dict)
    return data


# ---- assets and the page ----------------------------------------------------------------------
@pytest.mark.parametrize("name", (*NEW_SCRIPTS, "console-voice-devices.css"))
def test_each_new_file_exists_and_is_a_served_asset(name: str) -> None:
    assert (STATIC / name).is_file()
    assert name in APP_ASSETS
    assert ("css" if name.endswith(".css") else "javascript") in APP_ASSETS[name]


async def test_the_page_loads_the_voice_scripts_in_the_planned_order(client: AsyncClient) -> None:
    html = (await client.get("/")).text
    at = [html.index(f'<script src="/static/{n}" defer></script>') for n in VOICE_ORDER]
    assert at == sorted(at)
    assert html.index("console-offline.js") < at[0]  # after the console's own scripts
    # the next script after the mic is not a voice one: the order is exact, with no gaps in it
    tags = re.findall(r'<script src="/static/([^"]+)" defer></script>', html)
    start = tags.index(VOICE_ORDER[0])
    assert tuple(tags[start : start + len(VOICE_ORDER)]) == VOICE_ORDER
    assert '<link rel="stylesheet" href="/static/console-voice-devices.css">' in html


async def test_the_page_has_the_mic_off_button_the_struck_mic_and_the_offer_slot(
    client: AsyncClient,
) -> None:
    html = (await client.get("/")).text
    off = re.search(r"<button[^>]*\bid=\"micOffBtn\"[^>]*>", html)
    assert off, "#micOffBtn"
    assert re.search(r"\bhidden\b", off.group(0))
    assert 'aria-keyshortcuts="Control+Shift+Space"' in off.group(0)
    mic = html[html.index('id="micBtn"') : html.index("</button>", html.index('id="micBtn"'))]
    assert mic.count("<svg") == 2 and "mic-slash" in mic  # the plain mic and the struck one
    assert html.index('id="voiceLine"') < html.index('id="voiceOffer"')
    assert 'aria-label="Voice input"' in html  # the button's name stays stable (D2)


# ---- one place opens the microphone; one place builds a recogniser ---------------------------
def test_get_user_media_is_only_called_in_the_capture_module() -> None:
    for path in sorted(STATIC.glob("*.js")):
        if path.name == "console-voice-capture.js":
            continue
        assert "getUserMedia(" not in path.read_text(encoding="utf-8"), path.name


def test_speech_recognition_is_only_constructed_in_the_capture_module() -> None:
    bad = re.compile(r"new\s+(?:window\.)?(?:webkit)?SpeechRecognition\b|new R\(|new Speech\(")
    for path in sorted(STATIC.glob("*.js")):
        if path.name == "console-voice-capture.js":
            continue
        assert not bad.search(path.read_text(encoding="utf-8")), path.name
    assert "recognizer" in read("console-voice-capture.js")


def test_the_lock_is_the_only_owner_of_its_storage_key() -> None:
    for path in sorted(STATIC.glob("*.js")):
        has = "jarvis_mic_off_v1" in path.read_text(encoding="utf-8")
        assert has == (path.name == "console-voice-capture.js"), path.name


# ---- the command table --------------------------------------------------------------------------
def test_phrases_parse_and_hold_every_router_id() -> None:
    table = phrases()
    assert set(table) == PHRASE_IDS
    for key, items in table.items():
        assert items and all(isinstance(p, str) and p for p in items), key
        assert len(items) == len(set(items)), f"{key}: duplicates"


def test_phrases_are_written_the_way_the_router_normalises() -> None:
    for key, items in phrases().items():
        for p in items:
            assert p == p.lower() and p == p.strip() and "  " not in p, (key, p)
            assert re.fullmatch(r"[a-z0-9' {}]+", p), (key, p)
            assert len(p.split()) <= 8, (key, p)
            assert not p.startswith(("jarvis", "hey ", "please")), (key, p)
            if p != "not now":  # the one phrase whose "now" the router keeps
                assert not p.endswith((" please", " now", " sir", " thanks")), (key, p)
            assert not re.search(r"\b(turn|microphone|mike)\b", p), (key, p)  # normalised words


def test_the_owner_table_phrases_are_in_the_table() -> None:
    table = phrases()
    assert {"mic off", "switch off the mic", "mute yourself", "stop listening"} <= set(
        table["mic.off"]
    )
    assert {"stop", "wait", "hold on", "never mind", "that's enough"} <= set(table["speech.stop"])
    assert {"keyboard", "that's all", "goodbye", "i'll type"} <= set(table["conversation.keyboard"])
    assert {"yes", "go ahead", "keep listening"} <= set(table["answer.yes"])
    assert {"no", "not now", "leave it"} <= set(table["answer.no"])
    assert any("{device}" in p for p in table["device.switch"])
    assert any("{device}" in p and "mic" in p for p in table["device.input"])


def test_every_multi_word_phrase_is_a_speech_hint() -> None:
    hints = {h.lower() for h in COMMAND_HINTS}
    for key, items in phrases().items():
        for p in items:
            if " " in p and "{" not in p and not key.startswith("answer."):
                assert p in hints, (key, p)
    assert all(" " in h for h in COMMAND_HINTS)  # single words are never hints (D16)


def test_base_phrases_follow_d16() -> None:
    assert BASE_PHRASES[:3] == ("JARVIS", "Jarvis", "Hey Jarvis")
    low = [p.lower() for p in BASE_PHRASES]
    assert len(BASE_PHRASES) == len(set(BASE_PHRASES))  # "JARVIS" and "Jarvis" are both listed
    for p in (
        "mic off",
        "stop listening",
        "switch off the mic",
        "switch to the keyboard",
        "switch to my earphones",
        "switch to my speaker",
    ):
        assert p in low, p
    assert "stop" not in low  # a single common word is not a hint
    assert all(0 < len(p) <= 100 for p in (*BASE_PHRASES, *COMMAND_HINTS))
    assert set(BASE_PHRASES[3:]) <= set(COMMAND_HINTS)


# ---- device defaults and the status words ------------------------------------------------------
def test_device_defaults_carry_the_new_keys() -> None:
    js = read("console-voice.js")
    m = re.search(r"const DEVICE_DEFAULTS = Object\.freeze\(\{(.*?)\}\);", js, re.S)
    assert m
    pairs = dict(re.findall(r"(\w+): ('[^']*'|true|false|\d+)", m.group(1)))
    assert pairs == {
        "engine": "'auto'",
        "finish": "'comms'",
        "speak": "'voice'",
        "autoSend": "true",
        "keepListening": "true",
        "wake": "false",
        "interruptBy": "'auto'",
        "followUpS": "8",
        "longPauseS": "20",
        "endSilenceMs": "1200",
        "checkIn": "true",
        "cues": "true",
    }


def test_wake_words_know_the_mic_off_state() -> None:
    js = read("console-voice.js")
    assert re.search(r"WAKE_WORDS = \{[^}]*\bmicoff:", js, re.S)


def test_fx_status_words_and_voice_modes() -> None:
    js = read("console-fx.js")
    assert "standby: 'Standing by'" in js and "micoff: 'Mic off'" in js
    set_voice = js[js.index("VOICE_MODES") : js.index("function setBusy")]
    assert "standby" in set_voice and "micoff" in set_voice


# ---- the stubs keep their frozen shapes ----------------------------------------------------------
def test_stubs_define_their_frozen_objects() -> None:
    devices = read("console-voice-devices.js")
    assert "window.JarvisAudioRoute" in devices
    for key in (
        "supported",
        "refresh",
        "current",
        "chooseOutput",
        "chooseInput",
        "outputKind",
        "find",
        "on",
    ):
        assert re.search(rf"\b{key}\b", devices), key
    assert "outputKind: () => 'unknown'" in devices and "find: () => null" in devices
    barge = read("console-voice-barge.js")
    # part A replaced the stub: the frozen surface (policy, arm) stays, with the real gate behind it
    assert "window.JarvisBarge = Object.freeze({" in barge
    assert re.search(r"Object\.freeze\(\{[^}]*\bpolicy\b[^}]*\barm\b", barge)
    pace = read("console-voice-pace.js")
    assert "window.JarvisVoicePace" in pace and "last: () => null" in pace


@pytest.mark.parametrize("name", EMPTY_HEADERS)
def test_the_empty_headers_hold_a_comment_and_no_code(name: str) -> None:
    text = read(name)
    body = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
    body = re.sub(r"(?m)^\s*//.*$", "", body)
    assert body.strip() == "", name
    assert text.lstrip().startswith(("//", "/*")) and "r5-voice.md" in text


# ---- house rules for every script ---------------------------------------------------------------
def test_every_console_script_stays_within_800_lines() -> None:
    for path in STATIC.glob("console*.js"):
        assert len(path.read_text(encoding="utf-8").splitlines()) <= 800, path.name


@pytest.mark.parametrize("name", NEW_SCRIPTS)
def test_new_scripts_use_text_content_only_and_no_network(name: str) -> None:
    js = read(name)
    for bad in ("innerHTML", "outerHTML", "insertAdjacentHTML", "document.write", "eval(", "fetch(",
                "XMLHttpRequest", "WebSocket", "https://", "http://", "/approve"):  # fmt: skip
        assert bad not in js, (name, bad)


def test_the_capture_and_speech_edits_keep_the_house_rules() -> None:
    for name in (
        "console-voice-capture.js",
        "console-voice-speech.js",
        "console-voice-commands.js",
    ):
        js = read(name)
        for bad in ("innerHTML", "fetch(", "https://", "/approve"):
            assert bad not in js, (name, bad)


def test_the_router_refuses_anything_that_is_not_a_spoken_transcript() -> None:
    js = read("console-voice-commands.js")
    assert "source !== 'voice'" in js
    assert "textContent" not in js or "innerHTML" not in js


def test_no_server_call_carries_device_labels() -> None:
    for name in ("console-voice-devices.js", "console-voice-devices-panel.js"):
        js = read(name)
        assert "api(" not in js and "fetch(" not in js, name
