# tests/browser/test_r51_dock.py -- R5.1: every dock tab is reachable on a desktop. Nineteen tabs
# ran 82 px past each edge of a 1440 px window (Chat and Construct cut off, so they could not be
# clicked); the dock now stays inside the window at its usual size and scrolls sideways.
from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest
from test_console import Console

sync_playwright = pytest.importorskip("playwright.sync_api").sync_playwright

pytestmark = pytest.mark.browser

DOCK_JS = (
    "() => { const r = document.getElementById('dock').getBoundingClientRect();"
    " return [r.left, r.right, innerWidth,"
    " [...document.querySelectorAll('#dock .dk:not(.more)')].map(b => b.offsetWidth)]; }"
)


@pytest.fixture(scope="module")
def browser() -> Iterator[Any]:
    with sync_playwright() as p:
        b = p.chromium.launch()
        yield b
        b.close()


@pytest.mark.parametrize("width", [1280, 1366, 1440, 1920])
def test_the_dock_stays_in_the_window_and_every_tab_is_reachable(
    browser: Any, server_url: str, token: str, width: int
) -> None:
    c = Console(browser, server_url, token, {"width": width, "height": 900})
    try:
        c.open()
        left, right, vw, widths = c.page.evaluate(DOCK_JS)
        assert left >= 0 and right <= vw, (left, right, vw)
        assert set(widths) == {78, 102}  # every tab keeps its usual size (Integrations is wide)
        for panel in ("construct", "media", "brief"):
            c.page.locator(f'.dk[data-open="{panel}"]').click()  # scrolled into view, then opened
            c.page.locator(f"#p-{panel}").wait_for(state="visible")
        c.page.locator('.dk[data-open="chat"]').scroll_into_view_if_needed()
        box = c.page.locator('.dk[data-open="chat"]').bounding_box()
        assert box is not None and box["x"] >= 0, box
        assert c.errors == []
    finally:
        c.close()
