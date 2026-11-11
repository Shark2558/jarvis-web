# tests/browser/test_r11_i1_paused.py -- R11 integrated review M2, in headless Chromium: the Helpers
# frame draws each part's fixed "paused" lines (GET /v1/helpers parts[].paused) at the top of that
# part's tab only, as text (textContent: markup in a line stays text), above the part's own content,
# and draws nothing for a part with none; no JS errors and no CSP violations.
from __future__ import annotations

import json
from collections.abc import Iterator
from typing import Any

import pytest
from test_console import DESKTOP, Console
from test_ui_audit import _open
from ui_checks import install_mocks

_pw = pytest.importorskip("playwright.sync_api")
sync_playwright = _pw.sync_playwright

pytestmark = pytest.mark.browser

BREACH = (
    "Breach watching paused: your Email permission is set to Ask first. Set it to Allow to let it "
    "run by itself."
)
ODD = "Birthdays paused: <b>your</b> Contacts permission is set to Never."


def _with_paused(route: Any) -> None:
    """The server's own view, with paused lines added to two parts."""
    got = route.fetch()
    view = got.json()
    for part in view.get("parts", []):
        part["paused"] = {"house": [BREACH], "today": [ODD]}.get(part["name"], [])
    route.fulfill(response=got, body=json.dumps(view), content_type="application/json")


@pytest.fixture(scope="module")
def browser() -> Iterator[Any]:
    with sync_playwright() as p:
        b = p.chromium.launch()
        yield b
        b.close()


def test_each_tab_shows_only_its_own_paused_lines_as_text(
    browser: Any, server_url: str, token: str
) -> None:
    c = Console(browser, server_url, token, DESKTOP)
    install_mocks(c.page)
    c.page.route("**/v1/helpers", _with_paused)
    c.open()
    try:
        page = c.page
        assert _open(c, "helpers") is None
        page.locator("#hpt-house").click()
        house = page.locator("#hpp-house .hp-paused")
        house.wait_for(state="visible", timeout=5000)
        assert house.inner_text().strip() == BREACH
        first = page.evaluate("document.querySelector('#hpp-house').firstElementChild.className")
        assert first == "hp-paused"  # above the part's own content
        page.locator("#hpt-today").click()
        today = page.locator("#hpp-today .hp-paused")
        today.wait_for(state="visible", timeout=5000)
        assert today.inner_text().strip() == ODD  # markup stays text
        assert page.locator("#hpp-today .hp-paused b").count() == 0
        page.locator("#hpt-kitchen").click()
        assert page.locator("#hpp-kitchen .hp-paused").is_hidden()
        assert page.locator("#hpp-nudges .hp-paused").is_hidden()
        assert c.errors == [] and c.csp_violations() == []
    finally:
        c.close()
