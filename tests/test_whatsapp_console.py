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


def test_integrations_offers_grant_rows_for_contacts_and_youtube() -> None:
    js = (STATIC / "console.js").read_text(encoding="utf-8")
    pairs = (
        ("googleGrantTasks", "tasks_granted"),
        ("googleGrantContacts", "contacts_granted"),
        ("googleGrantYoutube", "youtube_granted"),
    )
    for gid, field in pairs:
        assert f"['{field}', " in js and f"'{gid}'" in js
    # a row only for a field that is exactly false (an older server without the field: none)
    assert "GRANTS.filter(x => g[x[0]] === false)" in js
    assert "'/connect/google?add=' + name" in js
    assert "Contacts \\u2014 permission needed" in js
    assert "YouTube playlists \\u2014 permission needed" in js
    assert "'contacts.readonly'" in js and "'youtube.readonly'" in js  # scope words


def test_styles_exist_for_the_card() -> None:
    css = CSS.read_text(encoding="utf-8")
    for sel in (".wadraft{", ".wadraft .watext{", ".wadraft .wawarn{", ".wadraft .waopen{"):
        assert sel in css
    assert "white-space:pre-wrap" in css and ":focus-visible" in css
