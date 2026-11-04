# tests/test_console_integrations.py — slice 12 review C5/C7: the Integrations section moved out of
# console.js into console-integrations.js (every console*.js stays at most 800 lines). It loads
# before console.js, which boots it through window.JarvisIntegrations; it writes text only, no
# markup sink. A Grant row is offered only when the server says the Grant is available (its tools
# exist here and its permission row is not Never); an older server without the field shows it.
from __future__ import annotations

import re
from pathlib import Path

from httpx import AsyncClient
from test_console_assets import _sinks, _visible_strings  # same directory (pytest prepend import)

from jarvis.api.console import APP_ASSETS

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "src/jarvis/api/static"
NAME = "console-integrations.js"
JS = STATIC / NAME
MAX_LINES = 800


def test_every_console_script_is_at_most_800_lines() -> None:
    scripts = sorted(STATIC.glob("console*.js"))
    assert len(scripts) >= 20
    for path in scripts:
        lines = len(path.read_text(encoding="utf-8").splitlines())
        assert lines <= MAX_LINES, (path.name, lines)


async def test_served_like_the_other_console_assets(client: AsyncClient) -> None:
    assert APP_ASSETS[NAME] == "text/javascript; charset=utf-8" or "javascript" in APP_ASSETS[NAME]
    r = await client.get(f"/static/{NAME}")
    assert r.status_code == 200 and "javascript" in r.headers["content-type"]
    assert r.headers["cache-control"] == "no-store"


async def test_the_page_loads_it_before_the_console(client: AsyncClient) -> None:
    html = (await client.get("/")).text
    tag = f'<script src="/static/{NAME}" defer></script>'
    assert html.index(tag) < html.index('<script src="/static/console.js" defer></script>')


def test_the_section_moved_out_of_the_console_whole() -> None:
    js = JS.read_text(encoding="utf-8")
    console = (STATIC / "console.js").read_text(encoding="utf-8")
    for name in ("SCOPE_WORDS", "GRANTS", "function grantRow", "function integBody",
                 "function integActions", "function renderIntegrations", "function askDisconnect",
                 "function afterConnectRedirect"):  # fmt: skip
        assert name in js and name not in console, name
    assert "window.JarvisIntegrations = Object.freeze({" in js
    assert "window.JarvisIntegrations" in console  # boot hands over to it


def test_it_writes_text_only_and_talks_through_the_consoles_transport() -> None:
    js = JS.read_text(encoding="utf-8")
    assert _sinks(js) == [] and "fetch(" not in js
    assert "window.JarvisConsole" in js and "textContent" in js
    for lit in _visible_strings(js):
        assert "$" not in re.sub(r"\$\{", "", lit), lit[:80]


SLICE12_FILES = (  # review FE-10: every slice 12 console file is plain ASCII, like the older ones
    NAME,
    "console-drive.js",
    "console-drive.css",
    "console-media.js",
    "console-media.css",
    "console-whatsapp.js",
    "console-whatsapp.css",
)
# the slice 12 lines of console.html (the rest of the page predates the rule)
SLICE12_HTML_MARKS = (
    'id="integrations"', "integMaps", "console-media.js", 'id="sMaps"', 'id="sYouTube"',
    'data-open="media"', 'data-sheet-open="media"', "/static/console-drive.",
    "/static/console-media.", "/static/console-whatsapp.", "/static/console-integrations.",
    "driveDialog",
)  # fmt: skip


def _not_ascii(text: str) -> list[tuple[int, str]]:
    return [(i, hex(ord(c))) for i, c in enumerate(text) if not (c in "\n\t" or " " <= c <= "~")]


def test_plain_ascii_with_escapes_only() -> None:
    for name in SLICE12_FILES:
        bad = _not_ascii((STATIC / name).read_text(encoding="utf-8"))
        assert bad == [], (name, bad[:5])


def _slice12_html() -> list[str]:
    lines = (STATIC / "console.html").read_text(encoding="utf-8").splitlines()
    picked = [ln for ln in lines if any(m in ln for m in SLICE12_HTML_MARKS)]
    start = next(i for i, ln in enumerate(lines) if "<!-- Media (slice 12" in ln)
    end = next(i for i in range(start, len(lines)) if lines[i].strip() == "</section>")
    return picked + lines[start : end + 1]


def test_the_slice12_lines_of_the_page_are_plain_ascii() -> None:
    picked = _slice12_html()
    assert len(picked) >= 30  # the Media panel, the Vitals rows, the dock / sheet, the dialog
    assert any('id="driveDialog"' in ln for ln in picked)
    for ln in picked:
        assert _not_ascii(ln) == [], ln[:120]


def test_a_grant_row_needs_the_grant_missing_and_available() -> None:
    js = JS.read_text(encoding="utf-8")
    for gid, field, avail in (
        ("googleGrantTasks", "tasks_granted", "tasks_available"),
        ("googleGrantContacts", "contacts_granted", "contacts_available"),
        ("googleGrantYoutube", "youtube_granted", "youtube_available"),
    ):
        assert f"['{field}', " in js and f"'{gid}'" in js and f"'{avail}'" in js
    # a row only for a field that is exactly false, and not when the server says unavailable
    assert "g[x[0]] === false && g[x[5]] !== false" in js
    assert "'/connect/google?add=' + name" in js
    assert "Contacts \\u2014 permission needed" in js
    assert "YouTube playlists \\u2014 permission needed" in js
    assert "'contacts.readonly'" in js and "'youtube.readonly'" in js  # scope words


def test_a_whatsapp_drafts_line_is_always_drawn_and_never_conditional_on_google() -> None:
    """R1 D9: the line is appended by every render, whatever the Google state or the Grants."""
    js = JS.read_text(encoding="utf-8")
    assert "id = 'waLine'" in js and "renderWhatsapp();" in js
    assert "Switched off in Permissions" in js and "Ready for typed numbers" in js
    assert "by name after the Contacts Grant" in js
    start = js.index("function renderWhatsapp()")
    body = js[start : js.index("async function loadWhatsapp")]
    assert "contacts_granted" not in body and "googleState" not in body  # no Google gate here
