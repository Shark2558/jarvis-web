# tests/browser/r2b_shell.py -- R2 builder B: until I1 puts the Things panel in console.html and
# lists its assets in APP_ASSETS, the browser tests add them to the page themselves: the panel shell
# and dock button are inserted into the served HTML, and the two asset files are answered from disk.
# This is also the markup contract I1 copies (see the report): a section #p-things with a .pbody, a
# dock button data-open="things", 'things' in console-deck.js ORDER and defaults(), the stylesheet
# in the head and the script after console.js.
from __future__ import annotations

from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

STATIC = Path(__file__).resolve().parents[2] / "src/jarvis/api/static"
SHELL = (
    '<section class="panel card" id="p-things" data-panel="things" '
    'aria-labelledby="t-things" hidden>'
    '<header class="ptitle"><h2 id="t-things">Things</h2><div class="pacts">'
    '<button class="pbtn" type="button" data-close aria-label="Close Things panel">x</button>'
    '</div></header><div class="pbody"></div></section>'
)
DOCK = (
    '<button class="dk" type="button" data-open="things" aria-controls="p-things" '
    'aria-pressed="false"><span>Things</span></button>'
)


def add_things_panel(page: Any) -> None:
    """Serve the console with the Things panel and its two files."""

    def home(route: Any) -> None:
        resp = route.fetch()
        html = resp.text()
        html = html.replace(
            '<nav class="dock card" id="dock"', SHELL + '<nav class="dock card" id="dock"', 1
        )
        html = html.replace('<span class="sep"', DOCK + '<span class="sep"', 1)
        html = html.replace(
            "</head>", '<link rel="stylesheet" href="/static/console-things.css"></head>', 1
        )
        html = html.replace(
            "</body>", '<script src="/static/console-things.js" defer></script></body>', 1
        )
        route.fulfill(response=resp, body=html)

    def asset(name: str, kind: str) -> Any:
        return lambda route: route.fulfill(
            status=200,
            content_type=kind,
            body=(STATIC / name).read_text(encoding="utf-8"),
            headers={"cache-control": "no-store"},
        )

    def deck(route: Any) -> None:
        resp = route.fetch()
        body = resp.text().replace("'media', 'construct']", "'media', 'construct', 'things']", 1)
        row = "things: { x: 400, y: 60, w: 380, h: null, open: false },\n      construct: {"
        body = body.replace("construct: {", row, 1)
        route.fulfill(response=resp, body=body)

    page.route(lambda url: urlsplit(url).path == "/", home)
    page.route("**/static/console-deck.js", deck)
    page.route("**/static/console-things.js", asset("console-things.js", "text/javascript"))
    page.route("**/static/console-things.css", asset("console-things.css", "text/css"))
