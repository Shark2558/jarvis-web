# tests/test_web_console.py — slice 10 B console contract: console-web.js is served like the other
# console scripts, loads BEFORE console.js (so a restored conversation always finds it), never
# parses server text as HTML (its one link target is a URL it has checked is https), no "$" in
# anything the owner reads, and the Vitals panel has the web-search line.
from __future__ import annotations

import re
from pathlib import Path

from httpx import AsyncClient
from test_console_assets import _sinks, _visible_strings  # same directory (pytest prepend import)

ROOT = Path(__file__).resolve().parents[1]
JS = ROOT / "src/jarvis/api/static/console-web.js"
# The one URL the script ever assigns: a link target from `safeUrl` (https, no user info).
LINK = "a.href = s.href"


async def test_served_as_javascript_with_no_store(client: AsyncClient) -> None:
    r = await client.get("/static/console-web.js")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("application/javascript")
    assert r.headers["cache-control"] == "no-store"


async def test_loads_before_the_console_and_vitals_has_the_line(client: AsyncClient) -> None:
    html = (await client.get("/")).text
    web = html.index('<script src="/static/console-web.js" defer></script>')
    assert web < html.index('<script src="/static/console.js" defer></script>')
    assert '<div class="kv"><span>Web search</span><b id="sWeb">—</b></div>' in html


def test_the_only_sink_is_one_checked_https_link() -> None:
    js = JS.read_text(encoding="utf-8")
    assert js.count(LINK) == 1
    assert _sinks(js.replace(LINK, "")) == []
    assert "u.protocol !== 'https:'" in js and "u.username || u.password" in js
    assert "href: u.href" in js  # the href comes from the parsed, checked URL
    assert "a.rel = REL" in js and "const REL = 'noopener noreferrer nofollow'" in js
    assert "a.target = '_blank'" in js and "a.referrerPolicy = 'no-referrer'" in js
    assert "textContent" in js and "fetch(" not in js  # the console's own transport only


def test_no_dollar_sign_in_anything_the_owner_reads() -> None:
    js = JS.read_text(encoding="utf-8")
    for lit in _visible_strings(js):
        assert "$" not in re.sub(r"\$\{", "", lit), lit[:80]
    assert "₹0" in js


def test_console_js_hands_fresh_and_restored_replies_to_the_sources_row() -> None:
    js = (ROOT / "src/jarvis/api/static/console.js").read_text(encoding="utf-8")
    assert "window.JarvisSources.render(row, r.sources)" in js
    assert "window.JarvisSources.render(row, t.sources)" in js


def test_styles_exist_for_the_row() -> None:
    css = (ROOT / "src/jarvis/api/static/console.css").read_text(encoding="utf-8")
    assert ".wsources{" in css and ".wsources .wsrc{" in css and ":focus-visible" in css
