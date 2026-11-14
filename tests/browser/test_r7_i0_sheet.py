# tests/browser/test_r7_i0_sheet.py -- R7 I0 seam 10 (docs/plans/r7-mobile.md): console-dock.js
# builds the More sheet's entries from the dock, so console.html could free 19 lines. The proof is
# a before-and-after comparison in the browser: the 19 entries the page had at R11.1
# (tests/fixtures/r7/more_sheet_before.html, copied from console.html on 5519e2d) are exactly the
# first 19 the page now builds, byte for byte (order, words, markup); the 20th is the new Camera
# tab's, made the same way from its own tab. A folded tab still opens its panel from the sheet.
from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from test_console import Console

sync_playwright = pytest.importorskip("playwright.sync_api").sync_playwright
pytestmark = pytest.mark.browser
BEFORE = Path(__file__).resolve().parents[1] / "fixtures" / "r7" / "more_sheet_before.html"
# a template in the test's own page context: the fixture is the page's old markup, never run
BEFORE_JS = """(html) => {
  const t = document.createElement('template');
  t.innerHTML = html;
  return [...t.content.querySelectorAll('.sheet-item')].map((b) => b.outerHTML);
}"""
ENTRIES_JS = (
    "() => [...document.querySelectorAll('#moreSheet .sheet-item')].map((b) => b.outerHTML)"
)


@pytest.fixture(scope="module")
def browser() -> Iterator[Any]:
    with sync_playwright() as p:
        b = p.chromium.launch()
        yield b
        b.close()


def _plain(html: str) -> str:
    """outerHTML with the `hidden` the fitter sets taken out (the page had none in its markup)."""
    return html.replace(' hidden=""', "")


def test_the_built_sheet_equals_the_page_it_replaced(
    browser: Any, server_url: str, token: str
) -> None:
    before = BEFORE.read_text(encoding="utf-8")
    assert len(before.splitlines()) == 19
    c = Console(browser, server_url, token, {"width": 1440, "height": 900})
    try:
        c.open()
        built = [_plain(h) for h in c.page.evaluate(ENTRIES_JS)]
        # the old markup, read by the same browser (an SVG <path/> serialises as <path></path>)
        old = c.page.evaluate(BEFORE_JS, before)
        assert len(old) == 19 and len(built) == 20
        assert built[:19] == old  # same order, same words, same markup
        camera = built[19]
        head = '<button class="sheet-item" type="button" data-sheet-open="camera">'
        words = "<b>Camera</b><small>Look at a photo or the live picture, on this device</small>"
        assert camera.startswith(head) and words in camera
        icon = c.page.evaluate(
            "() => document.querySelector('#dock [data-open=\"camera\"] svg').outerHTML"
        )
        assert icon in camera  # the tab's own icon
        assert c.errors == []
    finally:
        c.close()


def test_a_folded_tab_still_opens_from_the_sheet_on_a_phone(
    browser: Any, server_url: str, token: str
) -> None:
    c = Console(browser, server_url, token, {"width": 390, "height": 844})
    try:
        c.open()
        for panel in ("camera", "helpers", "media"):
            c.open_panel(panel)  # its tab, or its entry in the More sheet when the tab is folded
            assert c.page.locator(f'.panel[data-panel="{panel}"]').is_visible(), panel
        assert c.errors == []
    finally:
        c.close()
