# tests/browser/test_r7_a_manifest.py -- R7 Part A (docs/plans/r7-mobile.md D3): Chromium itself
# reads the console's web app manifest (DevTools `Page.getAppManifest`) with no error and finds
# nothing that stops "Install app" (`Page.getInstallabilityErrors`), on a desktop and a phone, with
# the console's CSP (`manifest-src 'self'`) and no CSP report.
from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest
from test_console import DESKTOP, PHONE, Console

_pw = pytest.importorskip("playwright.sync_api")
sync_playwright = _pw.sync_playwright
pytestmark = pytest.mark.browser


@pytest.fixture(scope="module")
def browser() -> Iterator[Any]:
    with sync_playwright() as p:
        b = p.chromium.launch()
        yield b
        b.close()


@pytest.mark.parametrize("size", ["desktop", "phone"])
def test_chromium_reads_the_manifest_and_finds_nothing_that_stops_installing(
    browser: Any, server_url: str, token: str, size: str
) -> None:
    c = Console(browser, server_url, token, DESKTOP if size == "desktop" else PHONE)
    try:
        c.open()
        c.page.wait_for_timeout(1000)
        cdp = c.ctx.new_cdp_session(c.page)
        manifest = cdp.send("Page.getAppManifest")
        assert manifest["url"] == server_url + "/manifest.webmanifest"
        assert manifest["errors"] == []
        assert '"share_target"' in manifest["data"] and '"shortcuts"' in manifest["data"]
        assert cdp.send("Page.getInstallabilityErrors") == {"installabilityErrors": []}
        assert c.errors == [] and c.csp_violations() == []
    finally:
        c.close()
