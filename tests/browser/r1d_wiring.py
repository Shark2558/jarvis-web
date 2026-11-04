# tests/browser/r1d_wiring.py -- loads builder D's console files into the page before the integrator
# (I1) has added their tags to console.html and their names to api/console.py APP_ASSETS.
#
# The page is fetched from the real server and the missing <link>/<script> tags are inserted exactly
# where I1 will put them; the assets come from disk. Once I1 has wired the real tags this is a no-op
# (a tag already present is not added twice) and the files can be dropped.
from __future__ import annotations

from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

STATIC = Path(__file__).resolve().parents[2] / "src" / "jarvis" / "api" / "static"
CSS = "console-family.css"
SCRIPTS_BEFORE_BRIEF = "console-brief-sections.js"
SCRIPT_AFTER_DRIVE = "console-family.js"


def _insert(html: str, anchor: str, tag: str, *, before: bool) -> str:
    if tag in html or anchor not in html:
        return html
    return html.replace(anchor, tag + anchor if before else anchor + tag, 1)


def wire(page: Any) -> None:
    def document(route: Any) -> None:
        resp = route.fetch()
        html = resp.text()
        link = f'<link rel="stylesheet" href="/static/{CSS}">\n'
        script = '<script src="/static/{}" defer></script>\n'
        html = _insert(html, "</head>", link, before=True)
        brief = '<script src="/static/console-brief.js" defer></script>'
        html = _insert(html, brief, script.format(SCRIPTS_BEFORE_BRIEF), before=True)
        drive = '<script src="/static/console-drive.js" defer></script>\n'
        html = _insert(html, drive, script.format(SCRIPT_AFTER_DRIVE), before=False)
        route.fulfill(response=resp, body=html)

    def asset(route: Any) -> None:
        path = STATIC / urlsplit(route.request.url).path.rsplit("/", 1)[-1]
        kind = "text/css" if path.suffix == ".css" else "application/javascript"
        route.fulfill(status=200, content_type=kind, body=path.read_text(encoding="utf-8"))

    page.route(lambda url: urlsplit(url).path == "/", document)
    for name in (CSS, SCRIPTS_BEFORE_BRIEF, SCRIPT_AFTER_DRIVE):
        page.route(f"**/static/{name}", asset)
