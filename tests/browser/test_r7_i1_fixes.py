# tests/browser/test_r7_i1_fixes.py -- R7 I1 fixer (the Workshop's decisions on the reviews):
# the share tray while the app lock's cover is up (security L2), and dates in one shape (code M1).
from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest
from test_console import PHONE
from test_r7_a_share import Tray
from test_r7_a_share_review import ONE_TEXT
from test_r7_d_body import Rig
from test_ui_audit import _open

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


# ---- code M1: one date shape, "12 Nov, 14:05", whatever the browser's own locale --------------
class UsBrowser:
    """A browser whose every context is US English, in UTC (the Workshop's headless Chromium)."""

    def __init__(self, real: Any) -> None:
        self._real = real

    def new_context(self, **kw: Any) -> Any:
        return self._real.new_context(locale="en-US", timezone_id="UTC", **kw)


@pytest.fixture(scope="module")
def us_rig(browser: Any, server_url: str, token: str) -> Iterator[Rig]:
    rig = Rig(UsBrowser(browser), server_url, token)
    yield rig
    rig.close()


WHEN_CASES = """() => {
  const W = window.JarvisMobile.when;
  return [W('2026-11-12T14:05:00+00:00', true), W('2026-11-12T14:05:00+00:00', false),
          W('2026-11-12T00:07:00+00:00', true), W('nonsense', true), W(null, false)];
}"""


def test_the_one_date_helper_reads_the_same_in_a_us_locale(us_rig: Rig) -> None:
    c = us_rig.page("desktop", "night")
    assert c.page.evaluate("() => navigator.language") == "en-US"
    got = c.page.evaluate(WHEN_CASES)
    assert got == ["12 Nov, 14:05", "12 Nov", "12 Nov, 00:07", "", ""]


def test_the_sos_card_and_the_watch_tab_show_12_nov_14_05_style_dates_under_en_us(
    us_rig: Rig,
) -> None:
    c = us_rig.page("desktop", "night")
    assert _open(c, "integrations") is None
    card = c.page.locator("#sosCard")
    card.locator(".sos-contact").first.wait_for(timeout=5000)
    text = card.text_content() or ""
    assert "12 Nov, 08:35" in text and "AM" not in text and "Nov 12" not in text
    assert _open(c, "helpers") is None
    c.page.locator("#hpt-watch").click()
    pane = c.page.locator("#hpp-watch")
    pane.locator(".hp-row").first.wait_for(timeout=5000)
    words = pane.text_content() or ""
    assert "Last synced: 12 Nov, 03:42." in words and "AM" not in words
    c.page.locator("#hpt-today").click()


def test_no_r7_console_file_formats_a_date_on_its_own() -> None:
    from pathlib import Path

    static = Path(__file__).resolve().parents[2] / "src" / "jarvis" / "api" / "static"
    for name in (
        "console-helpers-watch.js",
        "console-r7-sos.js",
        "console-camera-panel.js",
        "console-r7-phone.js",
    ):
        src = (static / name).read_text(encoding="utf-8")
        assert "toLocaleString" not in src.replace("steps.toLocaleString()", ""), name
        assert "toLocaleDateString" not in src and "toLocaleTimeString" not in src, name
        assert "DateTimeFormat" not in src, name
        assert "JarvisMobile.when" in src or "M.when" in src, name
