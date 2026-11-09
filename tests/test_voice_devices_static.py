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
MODULES = (
    "console-voice-devices-match.js",
    "console-voice-devices.js",
    "console-voice-devices-panel.js",
)
PURE_MODULES = ("console-voice-devices-match.js", "console-voice-devices.js")  # touch no DOM tree
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
    # the route and the matcher touch no DOM tree, so they need no textContent
    assert "textContent" in js or name in PURE_MODULES
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


def literal_keys(src: str, assignment: str) -> set[str]:
    """The top-level keys of the `Object.freeze({ ... })` literal that follows `assignment`."""
    start = src.index(assignment)
    body_start = src.index("{", start)
    depth, i = 0, body_start
    while True:
        depth += {"{": 1, "}": -1}.get(src[i], 0)
        if depth == 0:
            break
        i += 1
    body = src[body_start + 1 : i]
    keys: set[str] = set()
    depth = 0
    for part in re.split(r"([{}()\[\]])", body):
        if part in ("{", "(", "["):
            depth += 1
        elif part in ("}", ")", "]"):
            depth -= 1
        elif depth == 0:
            keys.update(re.findall(r"(?:^|,)\s*(\w+)\s*(?=[,:(]|$)", part))
    return keys


def test_the_route_keeps_its_frozen_public_shape() -> None:
    js = read("console-voice-devices.js")
    assert "window.JarvisAudioRoute = Object.freeze({" in js
    keys = literal_keys(js, "window.JarvisAudioRoute = Object.freeze(")
    assert keys == {
        "supported",
        "refresh",
        "current",
        "chooseOutput",
        "chooseInput",
        "outputKind",
        "find",
        "on",
    }
    assert "window.JarvisAudioRoutePrefs = prefsApi;" in js


def test_the_prefs_api_has_exactly_the_keys_the_panel_needs() -> None:
    js = read("console-voice-devices.js")
    keys = literal_keys(js, "const prefsApi = Object.freeze(")
    assert keys == {
        "prefs",
        "devices",
        "setKind",
        "setName",
        "setOnConnect",
        "canRoute",
        "onAndroid",
        "defaultKind",
        "status",
        "setStatus",
        "inputPending",
        "text",
    }


def test_the_three_device_commands_are_registered_with_the_router() -> None:
    js = read("console-voice-devices.js")
    for cid in ("device.switch", "device.input", "device.list"):
        assert f"'{cid}'" in js, cid
    assert "JarvisVoiceCommands" in js and ".register(" in js


def test_lines_go_through_the_voice_loop_and_the_speaker_seams() -> None:
    js = read("console-voice-devices.js")
    for seam in ("JarvisVoiceLoop", "setSink", "sinkSupported", "JarvisAudio", "setInput"):
        assert seam in js, seam
    assert re.search(r"hands-\??free", read("console-voice-devices-match.js"), re.I)


def test_no_spoken_template_interpolates_a_device_name() -> None:
    """Spoken text reaches the cloud voice: it may name a kind, never a label or nickname (D18)."""
    js = read("console-voice-devices.js")
    spoken = re.findall(r"(?:announceLine|speak|done)\(\s*`([^`]*)`", js)
    spoken += re.findall(r"(?:const|let) said = `([^`]*)`", js)
    spoken += re.findall(r"withScreen\([^`]*`[^`]*`,\s*`([^`]*)`", js)
    assert len(spoken) >= 6
    for template in spoken:
        assert not re.search(r"\.(name|label|plain)\b|args\.x|\$\{x\}", template), template


def test_the_matcher_shared_strings_live_in_the_route_not_in_two_places() -> None:
    route, panel = read("console-voice-devices.js"), read("console-voice-devices-panel.js")
    assert "Device names appear after you allow the microphone once" in route
    assert "Device names appear" not in panel and "Windows + Ctrl + V" not in panel
    assert "Quick Settings" not in panel


def test_the_panel_renders_into_the_devices_slot_and_can_play_a_test_tone() -> None:
    js = read("console-voice-devices-panel.js")
    assert "panelSlot('devices')" in js and "jarvis:voice-panel" in js
    assert ".tone(" in js


def test_the_stylesheet_uses_theme_tokens_not_remote_assets() -> None:
    css = read("console-voice-devices.css")
    assert css.strip() and "url(" not in css and "@import" not in css
    assert "var(--" in css


def test_long_labels_wrap_instead_of_overflowing() -> None:
    css = read("console-voice-devices.css")
    assert "overflow-wrap:anywhere" in css and "min-width:0" in css


def test_lookups_by_name_cannot_reach_the_object_prototype() -> None:
    js = read("console-voice-devices.js") + read("console-voice-devices-match.js")
    assert "new Map(" in read("console-voice-devices-match.js")
    assert "Object.create(null)" in js
    assert not re.search(r"\bALIASES\[", js) and not re.search(r"\bP\.(names|kinds)\[", js)


def test_hidden_and_bidi_characters_are_stripped_in_one_place() -> None:
    js = read("console-voice-devices-match.js")
    for code in ("\\u200b-\\u200f", "\\u202a-\\u202e", "\\u2066-\\u2069", "\\ufeff"):
        assert code in js, code
