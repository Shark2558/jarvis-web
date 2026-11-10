# tests/browser/test_r6_seams.py -- R6 I0 in a real browser (docs/plans/r6-build-book.md "Seams the
# I0 adds" item 9): the Book dock button opens the empty Book panel (desktop and, behind More, on a
# phone); a 423 from the server takes the console to the show; the show page /book/show boots
# console-fx.js and console-permissions.js WITHOUT the deck DOM (no page error, no CSP violation)
# and exposes JarvisFX and JarvisPasskey. The visual gate for #p-book: test_ui_audit.py.
from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest
from test_console import CSP_SPY, DESKTOP, PHONE, Console

sync_playwright = pytest.importorskip("playwright.sync_api").sync_playwright

pytestmark = pytest.mark.browser


@pytest.fixture(scope="module")
def browser() -> Iterator[Any]:
    with sync_playwright() as p:
        b = p.chromium.launch()
        yield b
        b.close()


@pytest.mark.parametrize("viewport", [DESKTOP, PHONE], ids=["desktop", "phone"])
def test_the_book_tab_opens_the_empty_book_panel(
    browser: Any, server_url: str, token: str, viewport: dict[str, int]
) -> None:
    c = Console(browser, server_url, token, viewport)
    try:
        c.open()
        c.open_panel("book")
        panel = c.page.locator("#p-book")
        assert "isn't available on this server yet" in str(panel.text_content())
        assert c.page.locator('.dk[data-open="book"]').get_attribute("aria-pressed") == "true"
        c.page.wait_for_timeout(500)
        assert c.csp_violations() == [] and c.errors == []
    finally:
        c.close()


def test_a_423_from_the_server_takes_the_console_to_the_show(
    browser: Any, server_url: str, token: str
) -> None:
    c = Console(browser, server_url, token, DESKTOP)
    try:
        c.open()
        c.page.route(
            "**/v1/brains",
            lambda route: route.fulfill(
                status=423,
                content_type="application/json",
                body='{"error": "show_locked", "detail": "locked"}',
            ),
        )
        c.page.evaluate("window.JarvisConsole.api('/v1/brains').catch(() => null)")
        c.page.wait_for_url("**/book/show", timeout=5000)
        c.page.locator("#show").wait_for()
    finally:
        c.close()


@pytest.mark.parametrize("viewport", [DESKTOP, PHONE], ids=["desktop", "phone"])
def test_the_show_page_boots_without_the_deck(
    browser: Any, server_url: str, viewport: dict[str, int]
) -> None:
    ctx = browser.new_context(viewport=viewport)
    page = ctx.new_page()
    errors: list[str] = []
    page.add_init_script(CSP_SPY)
    page.on("pageerror", lambda e: errors.append(f"pageerror: {e}"))
    page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
    try:
        page.goto(server_url + "/book/show")
        page.locator("#showCard").wait_for(state="visible")
        page.wait_for_timeout(800)  # deferred scripts and the module settle
        booted = page.evaluate(
            "() => ({fx: typeof window.JarvisFX, pk: typeof window.JarvisPasskey,"
            " prove: typeof (window.JarvisPasskey || {}).prove,"
            " surface: document.documentElement.dataset.surface,"
            " deck: !!document.getElementById('dock')})"
        )
        assert booted == {
            "fx": "object",
            "pk": "object",
            "prove": "function",
            "surface": "night",
            "deck": False,
        }
        # an unknown purpose is refused without a server call; the book ones are allowed through
        refused = page.evaluate(
            "() => window.JarvisPasskey.prove('home_arm').then(() => 'ok', (e) => e.message)"
        )
        assert refused == "The passkey check didn't work. Please try again."
        assert page.evaluate("window.__csp") == [] and errors == []
        assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
    finally:
        ctx.close()


@pytest.mark.parametrize("width", [1440, 1280, 1920])
def test_the_dock_stays_in_the_window_and_every_tab_is_reachable(
    browser: Any, server_url: str, token: str, width: int
) -> None:
    """R6 I0: twenty tabs do not fit a 1440 px desktop (nineteen already ran 82 px past each
    edge). The dock stays inside the window at its usual size and scrolls sideways."""
    c = Console(browser, server_url, token, {"width": width, "height": 900})
    try:
        c.open()
        box = c.page.evaluate(
            "() => { const r = document.getElementById('dock').getBoundingClientRect();"
            " return [r.left, r.right, innerWidth,"
            " [...document.querySelectorAll('#dock .dk:not(.more)')].map(b => b.offsetWidth)]; }"
        )
        left, right, vw, widths = box
        assert left >= 0 and right <= vw, box
        assert set(widths) == {78, 102}  # every tab keeps its usual size (Integrations is wide)
        for panel in ("construct", "media", "book"):
            c.page.locator(f'.dk[data-open="{panel}"]').click()  # scrolled into view
            c.page.locator(f"#p-{panel}").wait_for(state="visible")
        c.page.locator('.dk[data-open="chat"]').scroll_into_view_if_needed()
        assert c.errors == []
    finally:
        c.close()
