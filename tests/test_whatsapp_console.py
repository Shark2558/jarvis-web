# tests/test_whatsapp_console.py — slice 12 console contract: console-whatsapp.js renders a reply's
# WhatsApp drafts (kind "whatsapp" in ChatResponse.cards) as a card — name and number, the text,
# the warning line, and Open in WhatsApp. Its one link is built in the browser from a checked
# number and encodeURIComponent(text), opens in a new tab with rel="noopener noreferrer" and only
# when the owner clicks it; everything else is textContent. Integrations gains Grant rows for
# Contacts and YouTube playlists, like the to-do row.
from __future__ import annotations

import re
import unicodedata
from pathlib import Path
from typing import Any

import pytest
from httpx import AsyncClient
from test_console_assets import _sinks, _visible_strings  # same directory (pytest prepend import)

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "src/jarvis/api/static"
JS = STATIC / "console-whatsapp.js"
CSS = STATIC / "console-whatsapp.css"
LINK = "a.href = link"  # the one URL the script assigns: from waLink(number, text)


async def test_served_like_the_other_console_assets(client: AsyncClient) -> None:
    for name, kind in (("console-whatsapp.js", "javascript"), ("console-whatsapp.css", "css")):
        r = await client.get(f"/static/{name}")
        assert r.status_code == 200 and kind in r.headers["content-type"]
        assert r.headers["cache-control"] == "no-store"


async def test_the_page_loads_it_before_the_console(client: AsyncClient) -> None:
    html = (await client.get("/")).text
    tag = '<script src="/static/console-whatsapp.js" defer></script>'
    assert html.index(tag) < html.index('<script src="/static/console.js" defer></script>')
    assert '<link rel="stylesheet" href="/static/console-whatsapp.css">' in html


def test_the_only_sink_is_one_link_built_from_a_checked_number() -> None:
    js = JS.read_text(encoding="utf-8")
    assert js.count(LINK) == 1
    assert _sinks(js.replace(LINK, "")) == []
    assert "'https://wa.me/' + digits + '?text=' + encodeURIComponent(text)" in js
    assert "/^[1-9][0-9]{6,14}$/" in js  # E.164 digits only, checked before the link exists
    assert "a.target = '_blank'" in js and "a.rel = 'noopener noreferrer'" in js
    assert "a.referrerPolicy = 'no-referrer'" in js
    assert "textContent" in js and "fetch(" not in js
    # opened only by the owner's own click: never by the script
    for never in ("window.open(", ".click()", "location.assign", "location.href", "location ="):
        assert never not in js, never


def test_the_text_and_name_are_checked_and_capped_client_side() -> None:
    js = JS.read_text(encoding="utf-8")
    assert "TEXT_MAX = 2000" in js and "MAX_CARDS = 5" in js
    assert "hidden(text)" in js and "catch (_)" in js  # hidden characters, lone surrogate: dropped
    assert "window.JarvisText.hasInvisible" in js  # the one rule (console-text.js), final review


def test_new_files_are_plain_ascii_with_escapes_only() -> None:
    for path in (JS, CSS):
        text = path.read_text(encoding="utf-8")
        bad = [(i, hex(ord(c))) for i, c in enumerate(text) if not (c in "\n\t" or " " <= c <= "~")]
        assert bad == [], (path.name, bad[:5])


def test_no_dollar_sign_in_anything_the_owner_reads() -> None:
    js = JS.read_text(encoding="utf-8")
    for lit in _visible_strings(js):
        assert "$" not in re.sub(r"\$\{", "", lit), lit[:80]


def test_console_js_hands_each_replys_cards_to_the_card() -> None:
    js = (STATIC / "console.js").read_text(encoding="utf-8")
    assert "window.JarvisWhatsApp.render(row, r.cards)" in js and "r.whatsapp" not in js
    wa = JS.read_text(encoding="utf-8")
    assert "const KIND = 'whatsapp';" in wa and "d.kind === KIND" in wa  # only its own kind


def test_styles_exist_for_the_card() -> None:
    css = CSS.read_text(encoding="utf-8")
    for sel in (".wadraft{", ".wadraft .watext{", ".wadraft .wawarn{", ".wadraft .waopen{"):
        assert sel in css
    assert "white-space:pre-wrap" in css and ":focus-visible" in css


# ---- review S3 / S5 / S7 / S8 -----------------------------------------------------------------


def _rule(css: str, selector: str) -> str:
    m = re.search(re.escape(selector) + r"\{([^}]*)\}", css)
    assert m is not None, selector
    return m.group(1)


def test_the_whole_text_shows_with_no_inner_scroll_box() -> None:
    text = _rule(CSS.read_text(encoding="utf-8"), ".wadraft .watext")
    assert (
        "max-height" not in text and "overflow:auto" not in text and "overflow:scroll" not in text
    )


def test_a_long_text_shows_its_line_count() -> None:
    js = JS.read_text(encoding="utf-8")
    assert "LONG_LINES" in js and "' lines'" in js and "walines" in js


def test_the_number_is_isolated_from_right_to_left_names() -> None:
    num = _rule(CSS.read_text(encoding="utf-8"), ".wadraft .wanum")
    assert "unicode-bidi:isolate" in num and "direction:ltr" in num


def test_the_hint_names_who_nothing_is_sent_to_and_what_opening_does() -> None:
    js = JS.read_text(encoding="utf-8")
    # "Nothing is sent to <name> until you press Send in WhatsApp." with the name isolated (<bdi>)
    assert "first.append('Nothing is sent to ', mk('bdi', 'wawho', who), " in js
    assert "' until you press Send in WhatsApp.');" in js
    assert "const who = d.name || shown(d.number);" in js
    assert "'Opening the link hands this text to WhatsApp.'" in js
    assert "Nothing is sent until you press Send there" not in js  # the old, vaguer hint


def test_an_assumed_country_is_said_on_the_card() -> None:
    js = JS.read_text(encoding="utf-8")
    assert "ASSUMED = 'Assumed India (+91)'" in js and "waassumed" in js


def test_the_browser_check_mirrors_the_servers_cleaning() -> None:
    js = JS.read_text(encoding="utf-8")
    # the same blank-rendering characters the server strips; a card still holding one is dropped
    # (the merge: the unassigned ones too, U+2065, U+FFF0-FFF8 and the whole tag block, which
    # takes in the variation selectors supplement U+E0100-E01EF)
    # (SEC-5: FE0E is always blank now, and so is the Khitan small script filler U+16FE4)
    hexes = ("3164", "115f", "1160", "ffa0", "2800", "034f", "17b4", "17b5", "180b", "180f",
             "fe00", "fe0e", "2065", "fff0", "fff8", "{e0000}", "{e0fff}", "{16fe4}")  # fmt: skip
    for code in hexes:
        assert "\\u" + code in js, code
    from jarvis.whatsapp.draft import _blank

    for code in (0x2065, 0xFFF0, 0xFFF8, 0xE0000, 0xE0100, 0xE01EF, 0xE0FFF, 0xFE0E, 0x16FE4):
        assert _blank(chr(code)), hex(code)  # the server drops the same ones
    assert not _blank("\ufe0f")  # an emoji's FE0F is judged in place (SEC-5 H1)
    assert "\\p{Cc}\\p{Cf}\\p{Co}\\p{Cs}" in js  # the categories the server drops
    assert "/^\\p{Cn}$/u" in js  # SEC-5 M3: and the unassigned code points, but future emoji
    assert "clean(text) !== text" in js  # anything the server would have changed is refused
    assert "\\n{4,}" in js  # more than two blank lines


# ---- security review SEC-5: one copy of each table per side, identical ------------------------


def _js_ranges(js: str, name: str) -> tuple[tuple[int, int], ...]:
    """The [first, last] pairs of `const NAME = codes([...]);` in console-whatsapp.js."""
    m = re.search(r"const " + name + r" = codes\(\[\n(.*?)\n\s*\]\);", js, re.S)
    assert m is not None, name
    body = m.group(1)
    pairs = re.findall(r"\[0x([0-9a-f]{4,6}), 0x([0-9a-f]{4,6})\]", body)
    assert len(pairs) == body.count("["), name  # every entry parsed: none in another spelling
    return tuple((int(a, 16), int(b, 16)) for a, b in pairs)


def _codes(table: tuple[tuple[int, int], ...]) -> set[int]:
    return {c for lo, hi in table for c in range(lo, hi + 1)}


def _well_formed(table: tuple[tuple[int, int], ...]) -> bool:
    """Sorted, each range lo <= hi, none touching or overlapping the next (merged)."""
    ok = all(lo <= hi for lo, hi in table)
    return ok and all(a[1] + 1 < b[0] for a, b in zip(table, table[1:], strict=False))


@pytest.mark.parametrize(
    ("js_name", "module", "attr"),
    [
        ("FE0F_BASES", "jarvis.whatsapp.pictographic", "EMOJI_FE0F_BASES"),
        ("VIRAMAS", "jarvis.whatsapp.joining", "VIRAMAS"),
        ("ARABIC_LETTERS", "jarvis.whatsapp.joining", "ARABIC_LETTERS"),
    ],
)
def test_the_consoles_tables_are_exactly_the_servers(js_name: str, module: str, attr: str) -> None:
    import importlib

    table = getattr(importlib.import_module(module), attr)
    assert _well_formed(table), attr
    assert _js_ranges(JS.read_text(encoding="utf-8"), js_name) == table


def test_the_fe0f_bases_are_emoji_whose_emoji_form_needs_the_selector() -> None:
    """EMOJI_FE0F_BASES (Unicode 17.0, derived with Node 22's \\p{RGI_Emoji}): Extended_
    Pictographic code points with Emoji_Presentation=No. tests/browser/test_whatsapp.py derives
    the table again from the browser's own RGI_Emoji."""
    from jarvis.whatsapp.pictographic import EMOJI_FE0F_BASES, UNICODE_VERSION, emoji_fe0f_base
    from jarvis.whatsapp.pictographic import extended_pictographic as ep

    codes = _codes(EMOJI_FE0F_BASES)
    assert UNICODE_VERSION == "17.0" and len(codes) == 207
    assert all(ep(chr(c)) for c in codes)
    for base in (0x00A9, 0x2640, 0x2764, 0x1F3F3, 0x1F441, 0x1F5E8):  # (c), female sign, heart ...
        assert emoji_fe0f_base(chr(base)), hex(base)
    for not_one in (0x231A, 0x1F600, 0x1F3FD, 0x31, 0x23, ord("A"), 0x0D4D):
        assert not emoji_fe0f_base(chr(not_one)), hex(not_one)  # emoji-style already, or no emoji
    assert not emoji_fe0f_base("") and not emoji_fe0f_base("\u2764\ufe0f")


def _found(pick: Any) -> set[int]:
    return {c for c in range(0x110000) if pick(chr(c))}


@pytest.mark.parametrize(
    ("attr", "pick"),
    [
        ("VIRAMAS", lambda ch: unicodedata.combining(ch) == 9),
        (
            "ARABIC_LETTERS",
            lambda ch: (
                unicodedata.category(ch)[0] == "L"
                and unicodedata.name(ch, "").startswith("ARABIC LETTER ")
            ),
        ),
    ],
)
def test_the_joiner_tables_are_python_3_12s_unicode_15(attr: str, pick: Any) -> None:
    """VIRAMAS (canonical combining class 9) and ARABIC_LETTERS (letters named "ARABIC LETTER")
    were generated with Python 3.12 (Unicode 15.0). An older Python knows fewer (the rest are
    unassigned there, so cleaning drops them anyway); 15.x knows exactly these."""
    from jarvis.whatsapp import joining

    table = _codes(getattr(joining, attr))
    found = _found(pick)
    major = int(unicodedata.unidata_version.split(".")[0])
    assert joining.UNICODE_VERSION == "15.0"
    if major == 15:
        assert table == found
    elif major < 15:
        assert found <= table
        assert all(unicodedata.category(chr(c)) == "Cn" for c in table - found)
    else:
        assert table <= found


def test_the_approval_card_never_marks_an_emojis_selector() -> None:
    """SEC-5 H1: every FE0F the rule keeps changes the glyph, so the approval card's generic
    INVISIBLE markers stay without FE0E / FE0F (no "[U+FE0F]" after every heart)."""
    console = (STATIC / "console.js").read_text(encoding="utf-8")
    m = re.search(r"const INVISIBLE = /\[(.*?)\]/g;", console)
    assert m is not None
    assert "fe0" not in m.group(1).lower()


def test_the_draft_text_and_the_approval_quote_take_their_own_direction() -> None:
    """SEC-5 (low): a right-to-left draft reads in its own direction on both cards (dir="auto"),
    and only the WhatsApp quote changes: every other approval keeps its one plain paragraph."""
    js = JS.read_text(encoding="utf-8")
    assert "body.dir = 'auto';" in js and "mk('p', 'watext', d.text)" in js
    console = (STATIC / "console.js").read_text(encoding="utf-8")
    assert '<p class="waquote" dir="auto">${esc(visible(wa.quote))}</p>' in console
    assert "return `<p>${esc(visible(a.summary))}</p>`;" in console
    assert "a.tool === 'whatsapp_draft'" in console


def test_the_name_is_cut_by_code_points_like_the_server() -> None:
    """SEC-5 (low): NAME_MAX counts code points on both sides (Python's str), never UTF-16 units."""
    js = JS.read_text(encoding="utf-8")
    assert "Array.from(d.name.replace(/\\s+/g, ' ').trim()).slice(0, NAME_MAX).join('')" in js
