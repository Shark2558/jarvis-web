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
# Loaded by other code, never by a tag in the page (each still has to be allow-listed):
NOT_IN_PAGE = {
    "console-3d-scenes.js": ("console-3d.js", "import('./console-3d-scenes.js')"),
    "console-sw.js": ("console-alerts.js", "'/static/console-sw.js'"),  # the service worker
}
ASSETS = sorted(p.name for p in [*STATIC.glob("console-*.css"), *STATIC.glob("console-*.js")])


def _linked(name: str) -> bool:
    if name.endswith(".css"):
        return (
            re.search(rf'<link rel="stylesheet" href="/static/{re.escape(name)}">', HTML)
            is not None
        )
    return re.search(rf'<script (type="module" )?src="/static/{re.escape(name)}"', HTML) is not None


def test_the_folder_has_the_r51_files() -> None:  # a sanity floor: the glob found the folder
    for name in ("console-vitals.css", "console-systems.css", "console-systems-modal.js"):
        assert name in ASSETS


@pytest.mark.parametrize("name", ASSETS)
def test_every_console_asset_is_allow_listed(name: str) -> None:
    assert name in APP_ASSETS, f"{name} is in static/ but /static/{name} would 404"


@pytest.mark.parametrize("name", [n for n in ASSETS if n not in NOT_IN_PAGE])
def test_every_console_asset_is_linked_from_the_page(name: str) -> None:
    assert _linked(name), f"{name} is in static/ but console.html does not load it"


@pytest.mark.parametrize("name", sorted(NOT_IN_PAGE))
def test_the_assets_loaded_by_code_are_really_loaded_there(name: str) -> None:
    owner, needle = NOT_IN_PAGE[name]
    assert needle in (STATIC / owner).read_text(encoding="utf-8")
    assert not _linked(name)


def test_new_stylesheets_come_after_the_older_ones() -> None:
    """D1: the R5.1 sheets are linked after every older sheet, so they never restyle old panels
    by cascade order."""
    links = re.findall(r'<link rel="stylesheet" href="/static/(console[^"]*\.css)">', HTML)
    first_new = min(links.index(n) for n in ("console-connectors.css", "console-people.css"))
    assert links.index("console-alerts.css") < first_new
    assert links[-2:] == ["console-vitals.css", "console-systems.css"]
