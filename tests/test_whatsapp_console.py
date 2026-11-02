# tests/test_whatsapp_console.py — slice 12 console contract: console-whatsapp.js renders a reply's
# WhatsApp drafts (ChatResponse.whatsapp) as a card — name and number, the text, the warning line,
# and Open in WhatsApp. Its one link is built in the browser from a checked number and
# encodeURIComponent(text), opens in a new tab with rel="noopener noreferrer" and only when the
# owner clicks it; everything else is textContent. Integrations gains Grant rows for Contacts and
# YouTube playlists, like the to-do row.
from __future__ import annotations

import re
from pathlib import Path

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
    assert "INVISIBLE" in js and "catch (_)" in js  # a malformed text (lone surrogate) is dropped


def test_new_files_are_plain_ascii_with_escapes_only() -> None:
    for path in (JS, CSS):
        text = path.read_text(encoding="utf-8")
        bad = [(i, hex(ord(c))) for i, c in enumerate(text) if not (c in "\n\t" or " " <= c <= "~")]
        assert bad == [], (path.name, bad[:5])


def test_no_dollar_sign_in_anything_the_owner_reads() -> None:
    js = JS.read_text(encoding="utf-8")
    for lit in _visible_strings(js):
        assert "$" not in re.sub(r"\$\{", "", lit), lit[:80]


def test_console_js_hands_each_reply_to_the_card() -> None:
    js = (STATIC / "console.js").read_text(encoding="utf-8")
    assert "window.JarvisWhatsApp.render(row, r.whatsapp)" in js


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
    hexes = ("3164", "115f", "1160", "ffa0", "2800", "034f", "17b4", "17b5", "180b", "180f",
             "fe00", "fe0d", "{e0100}", "{e01ef}")  # fmt: skip
    for code in hexes:
        assert "\\u" + code in js, code
    assert "\\p{Cc}\\p{Cf}\\p{Co}\\p{Cs}" in js  # the categories the server drops
    assert "clean(text) !== text" in js  # anything the server would have changed is refused
    assert "\\n{4,}" in js  # more than two blank lines
