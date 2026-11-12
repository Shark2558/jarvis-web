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
BOOK_HTML = (STATIC / "book.html").read_text(encoding="utf-8")  # R6: the show page, /book/show
# Loaded by other code, never by a tag in the page (each still has to be allow-listed):
NOT_IN_PAGE = {
    "console-3d-scenes.js": ("console-3d.js", "import('./console-3d-scenes.js')"),
    "console-sw.js": ("console-alerts.js", "'/static/console-sw.js'"),  # the service worker
    # R6 D15: the show's scene modules, imported by its 3D engine
    "console-book-scenes.js": ("console-book-3d.js", "import('./console-book-scenes.js')"),
    "console-book-scenes-flow.js": (
        "console-book-3d.js",
        "import('./console-book-scenes-flow.js')",
    ),
    "console-book-scenes-data.js": (
        "console-book-3d.js",
        "import('./console-book-scenes-data.js')",
    ),
    # R11 D19: the Helpers panel's shell loads its stylesheet and the four parts' tab modules
    "console-helpers.css": ("console-helpers.js", "'/static/console-helpers.css'"),
    "console-helpers-today.js": ("console-helpers.js", "import('./console-helpers-today.js')"),
    "console-helpers-house.js": ("console-helpers.js", "import('./console-helpers-house.js')"),
    "console-helpers-nudges.js": ("console-helpers.js", "import('./console-helpers-nudges.js')"),
    "console-helpers-kitchen.js": ("console-helpers.js", "import('./console-helpers-kitchen.js')"),
    # R11.1: one loader in the page brings the four parts' modules and stylesheets
    "console-r111-plan.js": ("console-r111.js", "import('./console-r111-plan.js')"),
    "console-r111-files.js": ("console-r111.js", "import('./console-r111-files.js')"),
    "console-r111-photos.js": ("console-r111.js", "import('./console-r111-photos.js')"),
    "console-r111-look.js": ("console-r111.js", "import('./console-r111-look.js')"),
    "console-r111-plan.css": ("console-r111.js", "'/static/console-r111-plan.css'"),
    "console-r111-files.css": ("console-r111.js", "'/static/console-r111-files.css'"),
    "console-r111-photos.css": ("console-r111.js", "'/static/console-r111-photos.css'"),
    "console-r111-look.css": ("console-r111.js", "'/static/console-r111-look.css'"),
}
# R6: linked from the show page (book.html), not the deck
ON_BOOK_PAGE = {
    "console-book-show.js",
    "console-book-voice.js",
    "console-book-3d.js",
    "console-book-2d.js",
    "console-book-talk.js",
}
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


@pytest.mark.parametrize("name", [n for n in ASSETS if n not in NOT_IN_PAGE])
def test_every_console_asset_is_linked_from_the_page(name: str) -> None:
    if name in ON_BOOK_PAGE:  # R6: the show page loads it, the deck never does
        assert _linked(name, BOOK_HTML) and not _linked(name), name
        return
    assert _linked(name), f"{name} is in static/ but console.html does not load it"


@pytest.mark.parametrize("name", sorted(NOT_IN_PAGE))
def test_the_assets_loaded_by_code_are_really_loaded_there(name: str) -> None:
    owner, needle = NOT_IN_PAGE[name]
    assert needle in (STATIC / owner).read_text(encoding="utf-8")
    assert not _linked(name) and not _linked(name, BOOK_HTML)


def test_new_stylesheets_come_after_the_older_ones() -> None:
    """D1: the R5.1 sheets are linked after every older sheet, so they never restyle old panels
    by cascade order."""
    links = re.findall(r'<link rel="stylesheet" href="/static/(console[^"]*\.css)">', HTML)
    first_new = min(links.index(n) for n in ("console-connectors.css", "console-people.css"))
    assert links.index("console-alerts.css") < first_new
    # R6: the Book panel's sheet comes after every older one
    assert links[-3:] == ["console-vitals.css", "console-systems.css", "console-book.css"]
