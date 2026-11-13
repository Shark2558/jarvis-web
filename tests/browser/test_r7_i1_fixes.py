# tests/browser/test_r7_i1_fixes.py -- R7 I1 fixer (the Workshop's decisions on the reviews):
# the share tray while the app lock's cover is up (security L2), and dates in one shape (code M1).
from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest
from test_console import PHONE
from test_r7_a_share import Tray
from test_r7_a_share_review import ONE_TEXT

_pw = pytest.importorskip("playwright.sync_api")
sync_playwright = _pw.sync_playwright
pytestmark = pytest.mark.browser


@pytest.fixture(scope="module")
def browser() -> Iterator[Any]:
    with sync_playwright() as p:
        b = p.chromium.launch()
        yield b
        b.close()


def _item_waiting(t: Tray) -> None:
    t.at_health()
    t.share(ONE_TEXT)


def test_the_share_tray_never_opens_over_the_cover_and_a_do_shared_launch_waits_for_unlock(
    browser: Any, server_url: str, token: str
) -> None:
    t = Tray(browser, server_url, token, PHONE)
    try:
        _item_waiting(t)
        t.open("/?source=app")
        t.page.wait_for_function("() => window.JarvisConsole && window.JarvisConsole.ready()")
        t.page.wait_for_function("() => window.JarvisMobile && window.JarvisMobile.parts.share")
        t.page.wait_for_timeout(1500)
        t.page.evaluate(
            "() => { const s = document.getElementById('shareTray'); if (s && s.open) s.close(); }"
        )
        # the cover goes up (the same attribute console.js sets on a 423 device_locked)
        t.page.evaluate("() => { document.documentElement.dataset.locked = 'device'; }")
        # a tapped alert asks for the tray, and so does a hand on the tray's own door
        t.page.evaluate(
            "() => { const c = new BroadcastChannel('jarvis-launch');"
            " c.postMessage({ type: 'launch', do: 'shared', open: '' }); c.close(); }"
        )
        t.page.evaluate("() => JarvisMobile.parts.share.open()")
        t.page.wait_for_timeout(1500)
        assert t.page.locator("#shareTray[open]").count() == 0
        # the launch waits: unlock reloads the page and then it opens the tray
        t.page.evaluate("() => location.reload()")
        t.page.locator("#shareTray[open]").wait_for(timeout=15_000)
    finally:
        t.close()
