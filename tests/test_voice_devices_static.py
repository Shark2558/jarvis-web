# tests/test_voice_devices_static.py
"""R5 workstream B, the static half (docs/plans/r5-voice.md D13, D14).

Device labels can hold personal names ("Akash's AirPods"), so the two device modules must never
talk to the server; they write the DOM through textContent only; they never open the microphone to
get names; they keep their size limits; and they register the three device.* voice commands.
The browser half is tests/browser/test_voice_devices.py.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "src/jarvis/api/static"
MODULES = ("console-voice-devices.js", "console-voice-devices-panel.js")
MAX_LINES = 800
MAX_FUNCTION_LINES = 50


def read(name: str) -> str:
    return (STATIC / name).read_text(encoding="utf-8")


def code_only(src: str) -> str:
    """The source without // comments, so a sentence in a comment can't trip a check."""
    return "\n".join(re.sub(r"(?<![:'\"])//.*$", "", ln) for ln in src.splitlines())


@pytest.mark.parametrize("name", MODULES)
def test_no_server_call_can_carry_a_device_label(name: str) -> None:
    js = code_only(read(name))
    assert not re.search(r"\bapi\(|\bfetch\(|XMLHttpRequest|sendBeacon|WebSocket|EventSource", js)


@pytest.mark.parametrize("name", MODULES)
def test_the_dom_is_written_with_text_content_only(name: str) -> None:
    js = read(name)
    assert "textContent" in js or name == "console-voice-devices.js"  # the route touches no DOM
    assert not re.search(r"innerHTML|outerHTML|insertAdjacentHTML|document\.write", js)


@pytest.mark.parametrize("name", MODULES)
def test_nothing_loads_from_a_remote_origin(name: str) -> None:
    js = code_only(read(name))
    assert not re.search(r"https?://|importScripts|\bimport\(", js)


@pytest.mark.parametrize("name", MODULES)
def test_the_microphone_is_never_opened_to_read_device_names(name: str) -> None:
    js = code_only(read(name))
    assert "getUserMedia" not in js
    assert "JarvisAudio.open" not in js and "JarvisAudio.prime" not in js
    assert "SpeechRecognition" not in js


@pytest.mark.parametrize("name", MODULES)
def test_every_localstorage_access_is_inside_a_try(name: str) -> None:
    js = read(name)
    lines = js.splitlines()
    for i, line in enumerate(lines):
        if "localStorage" in line and not line.strip().startswith("//"):
            window = "\n".join(lines[max(0, i - 3) : i + 1])
            assert "try" in window, f"{name}:{i + 1} touches localStorage outside a try"


@pytest.mark.parametrize("name", (*MODULES, "console-voice-devices.css"))
def test_files_stay_within_the_size_limit(name: str) -> None:
    assert len(read(name).splitlines()) <= MAX_LINES


@pytest.mark.parametrize("name", MODULES)
def test_no_function_is_longer_than_fifty_lines(name: str) -> None:
    lines = read(name).splitlines()
    starts = [
        i
        for i, ln in enumerate(lines)
        if re.match(
            r"^\s{2,}(async )?function \w+\(|^\s{2,}(const|let) \w+ = (async )?\(.*\) => \{$", ln
        )
    ]
    for i in starts:
        indent = len(lines[i]) - len(lines[i].lstrip())
        end = next(
            (j for j in range(i + 1, len(lines)) if lines[j].startswith(" " * indent + "}")),
            len(lines),
        )
        assert end - i + 1 <= MAX_FUNCTION_LINES, f"{name}:{i + 1} is {end - i + 1} lines"


def test_the_route_keeps_its_frozen_public_shape() -> None:
    js = read("console-voice-devices.js")
    assert "window.JarvisAudioRoute" in js and "Object.freeze" in js
    for key in ("supported", "refresh", "current", "chooseOutput", "chooseInput"):
        assert re.search(rf"\b{key}\b", js), key
    for key in ("outputKind", "find", "on"):
        assert re.search(rf"\b{key}\b", js), key


def test_the_three_device_commands_are_registered_with_the_router() -> None:
    js = read("console-voice-devices.js")
    for cid in ("device.switch", "device.input", "device.list"):
        assert f"'{cid}'" in js, cid
    assert "JarvisVoiceCommands" in js and ".register(" in js


def test_spoken_lines_go_through_the_voice_loop_and_the_speaker_seams() -> None:
    js = read("console-voice-devices.js")
    for seam in ("JarvisVoiceLoop", "setSink", "sinkSupported", "JarvisAudio", "setInput"):
        assert seam in js, seam
    assert re.search(r"hands-\??free", js, re.I)


def test_the_panel_renders_into_the_devices_slot_and_can_play_a_test_tone() -> None:
    js = read("console-voice-devices-panel.js")
    assert "panelSlot('devices')" in js and "jarvis:voice-panel" in js
    assert ".tone(" in js
    assert "Device names appear after you allow the microphone once" in js


def test_the_stylesheet_uses_theme_tokens_not_remote_assets() -> None:
    css = read("console-voice-devices.css")
    assert css.strip() and "url(" not in css and "@import" not in css
    assert "var(--" in css
