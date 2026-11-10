# tests/test_r51_console_assets_linked.py -- R5.1 I1 (Part A review): every console stylesheet and
# script in the static folder is BOTH linked from console.html AND served by the /static
# allow-list (`api/console.APP_ASSETS`). R4 shipped four panel scripts whose CSS was never linked;
# this fails the build the next time a file is added to the folder but not wired.
from __future__ import annotations

import re
from pathlib import Path

import pytest

from jarvis.api.console import APP_ASSETS

STATIC = Path(__file__).resolve().parents[1] / "src" / "jarvis" / "api" / "static"
HTML = (STATIC / "console.html").read_text(encoding="utf-8")
SHOW_HTML = (STATIC / "book.html").read_text(encoding="utf-8")
# Loaded by other code, never by a tag in the page (each still has to be allow-listed):
NOT_IN_PAGE = {
    "console-3d-scenes.js": ("console-3d.js", "import('./console-3d-scenes.js')"),
    "console-sw.js": ("console-alerts.js", "'/static/console-sw.js'"),  # the service worker
    # R6 D15: the show's scene modules, imported by its 3D engine (statically or with import())
    "console-book-scenes.js": ("console-book-3d.js", "'./console-book-scenes.js'"),
    "console-book-scenes-flow.js": ("console-book-3d.js", "'./console-book-scenes-flow.js'"),
    "console-book-scenes-data.js": ("console-book-3d.js", "'./console-book-scenes-data.js'"),
}
# R6 D16: the show's own files are loaded by book.html (/book/show), never by the console
IN_SHOW_PAGE = frozenset(
    {
        "console-book-voice.js",
        "console-book-2d.js",
        "console-book-show.js",
        "console-book-talk.js",
        "console-book-3d.js",
    }
)
ASSETS = sorted(p.name for p in [*STATIC.glob("console-*.css"), *STATIC.glob("console-*.js")])


def _linked(name: str, html: str = HTML) -> bool:
    if name.endswith(".css"):
        return (
            re.search(rf'<link rel="stylesheet" href="/static/{re.escape(name)}">', html)
            is not None
        )
    return re.search(rf'<script (type="module" )?src="/static/{re.escape(name)}"', html) is not None


def test_the_folder_has_the_r51_files() -> None:  # a sanity floor: the glob found the folder
    for name in ("console-vitals.css", "console-systems.css", "console-systems-modal.js"):
        assert name in ASSETS


@pytest.mark.parametrize("name", ASSETS)
def test_every_console_asset_is_allow_listed(name: str) -> None:
    assert name in APP_ASSETS, f"{name} is in static/ but /static/{name} would 404"


@pytest.mark.parametrize("name", [n for n in ASSETS if n not in {*NOT_IN_PAGE, *IN_SHOW_PAGE}])
def test_every_console_asset_is_linked_from_the_page(name: str) -> None:
    assert _linked(name), f"{name} is in static/ but console.html does not load it"


@pytest.mark.parametrize("name", sorted(IN_SHOW_PAGE))
def test_the_show_files_are_linked_from_the_show_page_only(name: str) -> None:
    assert name in ASSETS
    assert _linked(name, SHOW_HTML), f"book.html does not load {name}"
    assert not _linked(name), f"console.html must not load the show's {name}"


@pytest.mark.parametrize("name", sorted(NOT_IN_PAGE))
def test_the_assets_loaded_by_code_are_really_loaded_there(name: str) -> None:
    owner, needle = NOT_IN_PAGE[name]
    assert needle in (STATIC / owner).read_text(encoding="utf-8")
    assert not _linked(name)


def test_new_stylesheets_come_after_the_older_ones() -> None:
    """D1: the R5.1 sheets are linked after every older sheet, so they never restyle old panels
    by cascade order; R6's Book panel sheet comes after them."""
    links = re.findall(r'<link rel="stylesheet" href="/static/(console[^"]*\.css)">', HTML)
    first_new = min(links.index(n) for n in ("console-connectors.css", "console-people.css"))
    assert links.index("console-alerts.css") < first_new
    assert links[-3:] == ["console-vitals.css", "console-systems.css", "console-book.css"]
