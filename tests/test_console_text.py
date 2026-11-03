# tests/test_console_text.py — slice 12 final review: ONE invisible-character rule for the console
# (console-text.js, window.JarvisText), used by the Maps / YouTube cards, Home and Work, the Drive
# folder names and the WhatsApp draft card. It KEEPS the zero-width non-joiner and joiner (U+200C /
# U+200D): Malayalam and other Indic scripts need them to spell words (console-media.js used to
# strip them). The same rule is checked in a real browser by tests/browser/test_media.py.
from __future__ import annotations

import re
from pathlib import Path

from httpx import AsyncClient

from jarvis.api.console import APP_ASSETS

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "src/jarvis/api/static"
JS = STATIC / "console-text.js"
USERS = ("console-media.js", "console-drive.js", "console-whatsapp.js")
# chillu n (written with a ZWJ) and a ZWNJ conjunct: real Malayalam spellings
MALAYALAM = (
    "\u0d2e\u0d32\u0d2f\u0d3e\u0d33\u0d02 \u0d05\u0d35\u0d28\u0d4d\u200d \u0d15\u0d4d\u200c\u0d15"
)


def _class() -> str:
    """The character class console-text.js builds its RegExp from, as JavaScript reads it (with
    its `u` flag), written for Python's re: \\u{XXXXX} becomes \\UXXXXXXXX."""
    js = JS.read_text(encoding="ascii")
    m = re.search(r"const INVISIBLE_CLASS = '(\[[^']+\])';", js)
    assert m is not None
    cls = m.group(1).replace("\\\\", "\\")  # the string literal's doubled backslashes
    return re.sub(r"\\u\{([0-9a-fA-F]{1,6})\}", lambda g: "\\U" + g.group(1).zfill(8), cls)


def _strip(text: str) -> str:
    return re.sub(_class(), "", text)  # \uXXXX ranges read the same in Python and JavaScript


def test_it_is_served_and_loads_before_every_module_that_uses_it() -> None:
    assert APP_ASSETS["console-text.js"] == "application/javascript"
    html = (STATIC / "console.html").read_text(encoding="utf-8")
    at = html.index('<script src="/static/console-text.js" defer></script>')
    for user in USERS:
        assert at < html.index(f'<script src="/static/{user}" defer></script>'), user


async def test_the_route_serves_it(client: AsyncClient) -> None:
    r = await client.get("/static/console-text.js")
    assert r.status_code == 200 and "javascript" in r.headers["content-type"]


def test_malayalam_keeps_its_joiners() -> None:
    assert _strip(MALAYALAM) == MALAYALAM
    emoji = "\U0001f468\u200d\U0001f469\u200d\U0001f467"  # a family: three emoji joined by ZWJ
    assert _strip(emoji) == emoji


def test_what_can_not_be_seen_or_reorders_text_is_removed() -> None:
    hidden = "\u200b\u200e\u200f\u202a\u202e\u2066\u2069\u2060\ufeff\u061c\u0007\u0085\u2028"
    assert _strip(f"a{hidden}b") == "ab"
    assert _strip("line one\nline two\ttab") == "line one\nline two\ttab"


def test_each_module_uses_the_shared_rule_and_has_none_of_its_own() -> None:
    for name in USERS:
        js = (STATIC / name).read_text(encoding="utf-8")
        assert "window.JarvisText." in js, name
        assert "const INVISIBLE" not in js, name  # no second, drifting copy
        assert "\\u200b-\\u200f" not in js, name  # the old range that dropped ZWNJ / ZWJ


def test_the_new_file_is_plain_ascii() -> None:
    assert JS.read_bytes().isascii()
    assert "innerHTML" not in JS.read_text(encoding="ascii")


# ---- final review LOW 2: tag characters and the other blank-rendering ones ----------------------

TAGS = "\U000e0068\U000e0069\U000e007f"  # invisible tag letters ("ASCII smuggling") and CANCEL TAG


def test_the_regexp_reads_code_points_so_tag_characters_can_be_matched() -> None:
    js = JS.read_text(encoding="ascii")
    assert "new RegExp(INVISIBLE_CLASS, 'u')" in js and "new RegExp(INVISIBLE_CLASS, 'gu')" in js
    assert "\\\\u{e0000}-\\\\u{e007f}" in js


def test_tag_characters_soft_hyphen_cgj_and_mongolian_separator_are_removed() -> None:
    assert _strip("pay" + TAGS + "ment") == "payment"
    assert _strip("a\u00ad\u034f\u180e\U000e0000\U000e0001b") == "ab"
    assert _strip(MALAYALAM + TAGS) == MALAYALAM  # and Malayalam keeps its joiners
