# tests/test_r51c_console_static.py -- R5.1 Part C console files, read as text: size limits (D6),
# ASCII, no HTML sinks, the console's own transport, no new colours or fonts (D1), rupees only, and
# the one local voice command that opens the pop-up (never typed text, never a server call).
from __future__ import annotations

import re
from pathlib import Path

import pytest

STATIC = Path(__file__).resolve().parents[1] / "src/jarvis/api/static"
MODAL, CARD, CSS = "console-systems-modal.js", "console-systems.js", "console-systems.css"
VOICE = "console-voice-commands.js"
SINKS = (
    "innerHTML",
    "outerHTML",
    "insertAdjacentHTML",
    "document.write",
    "eval(",
    "new Function",
    "createContextualFragment",
    "DOMParser",
    "srcdoc",
)


def read(name: str) -> str:
    return (STATIC / name).read_text(encoding="utf-8")


def test_sizes_stay_within_the_plan() -> None:
    assert len(read(MODAL).splitlines()) <= 400
    assert len(read(CSS).splitlines()) <= 300
    assert len(read(CARD).splitlines()) <= 800
    assert len(read(VOICE).splitlines()) <= 800


@pytest.mark.parametrize("name", [MODAL, CARD, CSS])
def test_new_files_are_ascii(name: str) -> None:
    assert read(name).isascii()


@pytest.mark.parametrize("name", [MODAL, CARD])
def test_scripts_write_text_never_markup(name: str) -> None:
    js = read(name)
    assert [s for s in SINKS if s in js] == []
    assert not re.search(r"\.(?:href|src|action)\s*=(?!=)", js)
    assert "textContent" in js
    assert "<script" not in js and "import(" not in js


def test_the_pop_up_uses_the_console_transport_and_its_own_routes() -> None:
    js = read(MODAL)
    assert "fetch(" not in js  # JarvisChat.raw / JarvisConsole.api carry auth + the CSRF header
    for path in ("/v1/health/run/stream", "/v1/health/run", "/v1/health/remind"):
        assert f"'{path}'" in js
    urls = set(re.findall(r"https?://[^\s'\"]+", js))
    assert urls == {"http://www.w3.org/2000/svg"}  # the SVG namespace, never a request
    strings = re.findall(r"'(?:[^'\\\n]|\\.)*'|`(?:[^`\\]|\\.)*`", js)
    assert [s for s in strings if "$" in s.replace("${", "")] == []  # rupees only, no dollar text
    assert "CLOSE_AFTER_MS = 10000" in js


def test_the_pop_up_never_speaks_when_told_never_and_respects_motion() -> None:
    js = read(MODAL)
    assert "dev.speak === 'never'" in js
    assert "prefers-reduced-motion" in js
    css = read(CSS)
    assert 'html[data-motion="calm"]' in css and 'html[data-motion="off"]' in css


def test_the_stylesheet_adds_no_colour_or_font_of_its_own() -> None:
    css = read(CSS)
    base = read("console.css") + read("console-deck.css")
    for colour in set(re.findall(r"#[0-9A-Fa-f]{3,8}\b", css)):
        assert colour in base, colour
    assert not re.findall(r"rgba?\(", css)
    families = re.findall(r"font(?:-family)?:[^;}]*", css)
    for decl in families:
        named = re.findall(r"\"[^\"]+\"|'[^']+'", decl)
        assert named == [], decl  # fonts only through the theme tokens (var(--tech) ...)


def test_one_local_voice_command_opens_the_pop_up_and_keeps_the_router_rules() -> None:
    js = read(VOICE)
    assert js.count("register('systems.check'") == 1
    block = js[js.index("register('systems.check'") :]
    block = block[: block.index("});") + 3]
    assert "jarvis:systems-check" in block and "via: 'voice'" in block
    assert "JarvisSystemsCheck" in block and ".matches(" in block
    assert "'speaking'" not in block  # not while JARVIS speaks (his closing line names it)
    assert "source !== 'voice'" in js  # typed text never reaches the router
    for bad in ("innerHTML", "fetch(", "https://", "/approve"):
        assert bad not in js
