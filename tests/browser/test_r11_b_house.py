# tests/browser/test_r11_b_house.py -- R11 Part B's Home tab in the Helpers panel (docs/plans/
# r11-free-helpers.md D19): with a realistic Home view (chores with a rota, upkeep with a starter,
# his place, a SACHET warning with SACHET's own words, a SACHET outage, breach watching on), the
# tab passes the visual gate's DOM checks (tests/browser/ui_checks.py, the same rules as
# test_ui_audit.py) at 1440x900 and 390x844, Night and Day, with no JS error or CSP violation; it
# says the official SACHET app, SMS and cell broadcast come first and shows the outage; SACHET's
# words appear only as SACHET's; a Done tap posts to its own route and repaints from the answer.
from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

import pytest
from test_console import DESKTOP, PHONE, Console, browser  # noqa: F401 - the browser fixture
from test_ui_audit import _audit
from ui_checks import install_mocks

pytestmark = pytest.mark.browser

OUTSIDE: dict[str, Any] = {
    "available": True,
    "off": None,
    "states": ["Karnataka", "Kerala", "Tamil Nadu"],
    "official_first": "JARVIS is a second channel. The official SACHET app, SMS and cell "
    "broadcast warnings come first: keep them on.",
    "attribution": {
        "weather": "Weather data by Open-Meteo.com (CC BY 4.0)",
        "sachet": "Warnings from NDMA SACHET (public domain)",
    },
    "weather_enabled": True,
    "disaster_enabled": True,
    "breach_how": "Sign up your own address at Have I Been Pwned's free 'Notify me'.",
    "breach_link": "https://haveibeenpwned.com/NotifyMe",
    "google_linked": True,
    "place": {"district": "Ernakulam", "state": "Kerala", "lat": 9.98, "lon": 76.28, "lgd": None},
    "point_known": True,
    "feed": "kerala",
    "thresholds": {"rain_hour_mm": 15, "rain_day_mm": 64.5, "feels_c": 40, "gust_kmh": 50},
    "weather": {
        "summary": {"day": "2026-11-10", "t_max": 31, "rain_from": "15:00", "at": "x"},
        "checked_at": "2026-11-10T06:30:00+00:00",
        "ok_at": "2026-11-10T06:30:00+00:00",
        "fail_since": None,
    },
    "sachet": {
        "checked_at": "2026-11-10T06:30:00+00:00",
        "ok_at": "2026-11-10T05:30:00+00:00",
        "fail_since": "2026-11-10T06:00:00+00:00",
        "warnings": [
            {
                "kind": "disaster_alert",
                "event": "Landslide",
                "until": "2026-11-10T18:00:00+05:30",
                "outside_text": {
                    "headline": "Landslide warning for the hilly parts of Ernakulam district.",
                    "instruction": "Move away from steep slopes.",
                },
            }
        ],
    },
    "breach": {"on": True, "checked_at": None, "last_day": "2026-11-09", "notices": 1},
}
CHORE = {
    "id": "0000000a", "label": "Dishes", "freq": "daily", "how_often": "every day", "days": [],
    "every": None, "at": "21:00", "members": ["Partner", "Me"], "whose": "Partner",
    "next": "2026-11-10", "today": True, "done_today": False,
}  # fmt: skip
VIEW: dict[str, Any] = {
    "chores": [CHORE],
    "upkeep": [
        {
            "id": "0000000b",
            "label": "AC service",
            "every": 180,
            "unit": "days",
            "last_done": "2026-05-14",
            "lead": 7,
            "due": "2026-11-10",
            "state": "due",
        },
    ],  # fmt: skip
    "starters": [{"label": "Water-purifier filter", "every": 90, "unit": "days"}],
    "adults_only": "Adults only: JARVIS keeps no children's data. Reminders go only to you.",
    "outside": OUTSIDE,
}
DONE = {**VIEW, "chores": [{**CHORE, "done_today": True, "whose": "Me"}]}


def _json(body: Any) -> Callable[[Any], None]:
    def handle(route: Any) -> None:
        route.fulfill(status=200, content_type="application/json", body=json.dumps(body))

    return handle


def _open(c: Console, surface: str = "night") -> None:
    install_mocks(c.page)
    c.page.route("**/v1/helpers/house", _json(VIEW))
    c.page.route("**/v1/helpers/house/chores/0000000a/done", _json(DONE))
    c.open()
    _surface(c, surface)
    c.open_panel("helpers")
    c.page.locator("#hpt-house").click()
    c.page.locator("#hpp-house .hp-row").first.wait_for()
    c.page.wait_for_timeout(500)


def _surface(c: Console, surface: str) -> None:
    if surface == "day":
        c.page.locator("#themeBtn").click()
        c.page.locator('label[for="jx-s-day"]').click()
        c.page.keyboard.press("Escape")
    assert c.page.locator("html").get_attribute("data-surface") == surface


@pytest.mark.parametrize("surface", ["night", "day"])
@pytest.mark.parametrize("vp", ["desktop", "phone"])
def test_the_home_tab_passes_the_visual_gate(
    browser: Any,  # noqa: F811 - the fixture imported above
    server_url: str,
    token: str,
    vp: str,
    surface: str,
) -> None:
    c = Console(browser, server_url, token, DESKTOP if vp == "desktop" else PHONE)
    try:
        _open(c, surface)
        pane = c.page.locator("#hpp-house")
        text = pane.inner_text()
        assert "official SACHET app, SMS and cell broadcast" in text
        assert "Can’t reach SACHET since" in text  # the outage shows
        assert "From SACHET: Landslide warning" in text  # SACHET's words, as SACHET's
        assert "Adults only" in text and "Weather data by Open-Meteo.com (CC BY 4.0)" in text
        _audit(c, "#p-helpers", vp, f"helpers/house {vp} {surface}")
        assert c.errors == [] and c.csp_violations() == []
    finally:
        c.close()


def test_done_posts_to_its_route_and_repaints(
    browser: Any,  # noqa: F811
    server_url: str,
    token: str,
) -> None:
    c = Console(browser, server_url, token, DESKTOP)
    try:
        _open(c)
        with c.page.expect_request("**/v1/helpers/house/chores/0000000a/done") as req:
            c.page.locator("#hpp-house .hp-row").first.get_by_role("button", name="Done").click()
        assert req.value.method == "POST"
        assert req.value.headers.get("x-requested-with") == "JARVIS"
        c.page.get_by_text("Done today").first.wait_for()
        assert c.errors == []
    finally:
        c.close()
