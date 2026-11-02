# tests/test_media_console.py — slice 12 D3/D4 console contract (static checks; the browser tests
# drive it for real): the CSP gains exactly `frame-src https://www.youtube-nocookie.com`, the
# console page keeps Referrer-Policy no-referrer (only the player's iframe sends its origin, which
# is all YouTube's embed check needs), the Media panel and its own script/style are served and
# packaged, the phone tab bar keeps ≤ 8 tabs (Media sits behind More), and the new scripts write
# text only (no HTML sinks, no fetch, no other hosts but the one embed origin and Google Maps
# links from the card).
from __future__ import annotations

import re

from httpx import AsyncClient

from jarvis.api.console import APP_ASSETS, CONSOLE_CSP

BEFORE = (
    "default-src 'none'; script-src 'self' 'wasm-unsafe-eval'; "
    "style-src 'self' 'unsafe-inline'; connect-src 'self'; img-src 'self' data:; "
    "font-src 'self'; base-uri 'none'; form-action 'self'; frame-ancestors 'none'"
)
MEDIA_FILES = ("console-media.js", "console-media.css")
HTML_SINKS = (
    "innerHTML",
    "outerHTML",
    "insertAdjacentHTML",
    "document.write",
    "createContextualFragment",
    "parseFromString",
    "setHTMLUnsafe",
    "srcdoc",
    "eval(",
    "new Function",
)


def test_csp_adds_only_the_youtube_nocookie_frame_source() -> None:
    assert CONSOLE_CSP == BEFORE + "; frame-src https://www.youtube-nocookie.com"
    assert "youtube.com" not in CONSOLE_CSP.replace("youtube-nocookie.com", "")
    assert "child-src" not in CONSOLE_CSP and "img-src 'self' data:;" in CONSOLE_CSP


async def test_console_page_headers(client: AsyncClient) -> None:
    """The page itself sends no referrer anywhere; only the player's own iframe carries
    referrerpolicy=strict-origin-when-cross-origin (its origin, for YouTube's embed check)."""
    r = await client.get("/")
    assert r.headers["content-security-policy"] == CONSOLE_CSP
    assert r.headers["referrer-policy"] == "no-referrer"
    assert r.headers["x-frame-options"] == "DENY"


def test_only_the_player_iframe_sends_its_origin() -> None:
    from pathlib import Path

    import jarvis.api.console as console

    assert not hasattr(console, "CONSOLE_REFERRER_POLICY")
    js = (Path(console.__file__).parent / "static" / "console-media.js").read_text()
    assert js.count("referrerPolicy") == 1
    assert "f.referrerPolicy = 'strict-origin-when-cross-origin'" in js


async def test_media_assets_are_served_no_store_and_loaded_after_the_console(
    client: AsyncClient,
) -> None:
    for name in MEDIA_FILES:
        assert name in APP_ASSETS
        r = await client.get(f"/static/{name}")
        assert r.status_code == 200 and r.headers["cache-control"] == "no-store"
    html = (await client.get("/")).text
    assert '<link rel="stylesheet" href="/static/console-media.css">' in html
    order = [html.index(f'src="/static/{n}"') for n in ("console.js", "console-media.js")]
    assert order == sorted(order)


async def test_media_script_writes_text_only_and_talks_only_to_its_own_server(
    client: AsyncClient,
) -> None:
    js = (await client.get("/static/console-media.js")).text
    assert [s for s in HTML_SINKS if s in js] == []
    assert "fetch(" not in js and "XMLHttpRequest" not in js and "WebSocket" not in js
    hosts = set(re.findall(r"https://([a-z0-9.-]+)", js))
    assert hosts <= {
        "www.youtube-nocookie.com",
        "maps.google.com",
        "www.google.com",
        "google.com",
        "maps.app.goo.gl",
    }
    assert "autoplay=1" in js  # set only on the iframe made by the owner's click on Play
    assert re.search(r"/\^\[A-Za-z0-9_-\]\{11\}\$/", js)  # the video id check
    assert "'Google Maps'" in js and "'YouTube'" in js  # attribution lines


async def test_media_panel_dock_tab_sits_behind_more_on_a_phone(client: AsyncClient) -> None:
    html = (await client.get("/")).text
    assert 'data-panel="media"' in html and 'id="t-media"' in html
    dock = html[html.index('<nav class="dock card"') : html.index("</nav>")]
    tabs = re.findall(r'<button class="dk([^"]*)" type="button" data-open="(\w+)"', dock)
    on_phone = [n for cls, n in tabs if "ovf" not in cls.split()]
    assert ("media" in [n for _, n in tabs]) and "media" not in on_phone
    assert len(on_phone) + 1 <= 8  # + More
    assert 'data-sheet-open="media"' in html
    # no iframe in the page itself: one exists only after the owner presses Play
    assert "<iframe" not in html
    deck = (await client.get("/static/console-deck.js")).text
    assert "'media'" in deck and re.search(r"\bmedia: \{ x:", deck)


async def test_vitals_and_integrations_have_their_maps_and_youtube_lines(
    client: AsyncClient,
) -> None:
    html = (await client.get("/")).text
    assert 'id="sMaps"' in html and 'id="sYouTube"' in html
    js = (await client.get("/static/console-media.js")).text
    assert "'/v1/quota'" in js and "'/v1/maps/places'" in js
    assert "searches / ${of(rt)} routes this month" in js and "YouTube searches today" in js
    assert "₹" not in js
    # never a dollar sign shown to the owner: no "$" inside any quoted string's text
    literals = re.findall(r"'([^'\n]*)'|`([^`\n]*)`", js)
    shown = [re.sub(r"\$\{[^}]*\}", "", a or b) for a, b in literals]
    assert not [s for s in shown if "$" in s and not s.startswith("^")]
