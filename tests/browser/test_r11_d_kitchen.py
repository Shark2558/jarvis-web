# tests/browser/test_r11_d_kitchen.py -- R11 Part D (plan D19): the Helpers panel's Kitchen tab with
# realistic mocked data (pantry, tastes, saved recipes with nutrition, two months of grocery spend,
# the block plan) passes the visual gate (ui_checks.DOM_CHECKS_JS and the audit's own probes) at
# 1440x900 and 390x844, Night and Day, with no JS errors or CSP violations; and the calendar button
# only ever asks for an approval card (POST /blocks/propose), never writes anything itself.
from __future__ import annotations

import json
from collections.abc import Iterator
from typing import Any

import pytest
from test_console import DESKTOP, PHONE, Console
from test_ui_audit import NAMELESS_JS, WRAP_JS, _assert_clean, _open
from ui_checks import DOM_CHECKS_JS, FINISH_ANIMATIONS_JS, install_mocks

_pw = pytest.importorskip("playwright.sync_api")
sync_playwright = _pw.sync_playwright
pytestmark = pytest.mark.browser

VIEW: dict[str, Any] = {
    "sealed": True,
    "pantry": ["toor dal", "basmati rice", "onions", "tomatoes", "coconut", "curry leaves"],
    "prefs": {
        "diet": "veg",
        "spice": 2,
        "oil": 1,
        "cuisines": ["Kerala", "Odia"],
        "note": "less salt",
    },
    "recipes": [
        {
            "id": "r00000001",
            "title": "Dal tadka",
            "cuisine": "North Indian",
            "diet": "veg",
            "minutes": 30,
            "ingredients": 5,
            "nutrition": "About 640 kcal, 34 g protein, 12 g fat, 98 g carbohydrate, 22 g fibre, "
            "610 mg sodium. Nutrient values: USDA FoodData Central (public domain), raw "
            "ingredients; a rough guide.",
        },
        {
            "id": "r00000002",
            "title": "Avial with a long Kerala name to wrap on a phone screen",
            "cuisine": "Kerala",
            "diet": "veg",
            "minutes": 40,
            "ingredients": 8,
            "nutrition": None,
        },
    ],
    "blocks": {
        "cooking_at": "19:00",
        "cooking_minutes": 45,
        "washing_at": "20:30",
        "washing_minutes": 15,
        "days": ["mon", "wed", "fri"],
    },
    "spend": {
        "on": True,
        "can_scan": True,
        "last_at": "2026-11-10T01:00:00+00:00",
        "months": [
            {
                "month": "2026-11",
                "label": "November 2026",
                "total": "₹2,140.50",
                "total_paise": 214050,
                "orders": 4,
                "by_merchant": {},
            },
            {
                "month": "2026-10",
                "label": "October 2026",
                "total": "₹789",
                "total_paise": 78900,
                "orders": 1,
                "by_merchant": {},
            },
        ],
    },
    "nutrition": {
        "installed": True,
        "attribution": "Nutrient values: USDA FoodData Central "
        "(public domain), raw ingredients; a rough guide.",
    },
    "calendar": True,
    "words": {"diets": ["veg", "egg", "nonveg"], "spice": [], "oil": []},
}
PROPOSED = {
    "pending": True,
    "message": "Add to your calendar, repeating every Mon, Wed and Fri from tomorrow: Cooking "
    "19:00-19:45 and Washing-up 20:30-20:45. Only you are on them.",
}


class Rig:
    def __init__(self, browser: Any, url: str, token: str) -> None:
        self.browser, self.url, self.token = browser, url, token
        self.pages: dict[tuple[str, str], Console] = {}
        self.calls: list[tuple[str, str, Any]] = []

    def _kitchen(self, route: Any) -> None:
        req = route.request
        body = json.loads(req.post_data) if req.post_data else None
        self.calls.append((req.method, req.url.split("/v1/helpers/kitchen", 1)[1], body))
        answer = PROPOSED if req.url.endswith("/blocks/propose") else VIEW
        route.fulfill(status=200, content_type="application/json", body=json.dumps(answer))

    def get(self, vp: str, surface: str) -> Console:
        key = (vp, surface)
        if key not in self.pages:
            c = Console(self.browser, self.url, self.token, DESKTOP if vp == "desktop" else PHONE)
            install_mocks(c.page)
            c.page.route("**/v1/helpers/kitchen**", self._kitchen)
            c.open()
            if surface == "day":
                c.page.locator("#themeBtn").click()
                c.page.locator('label[for="jx-s-day"]').click()
                c.page.keyboard.press("Escape")
            c.page.wait_for_timeout(1000)
            self.pages[key] = c
        return self.pages[key]

    def close(self) -> None:
        for c in self.pages.values():
            c.close()


@pytest.fixture(scope="module")
def rig(server_url: str, token: str) -> Iterator[Rig]:
    with sync_playwright() as p:
        b = p.chromium.launch()
        r = Rig(b, server_url, token)
        yield r
        r.close()
        b.close()


def _kitchen_tab(c: Console) -> None:
    assert _open(c, "helpers") is None
    c.page.locator("#hpt-kitchen").click()
    c.page.locator("#hpp-kitchen .hp-row").first.wait_for(state="attached", timeout=5000)
    c.page.wait_for_timeout(300)
    c.page.evaluate(FINISH_ANIMATIONS_JS)


@pytest.mark.parametrize("surface", ["night", "day"])
@pytest.mark.parametrize("vp", ["desktop", "phone"])
def test_the_kitchen_tab_passes_the_visual_gate(rig: Rig, vp: str, surface: str) -> None:
    c = rig.get(vp, surface)
    _kitchen_tab(c)
    pane = c.page.locator("#hpp-kitchen")
    for words in ("toor dal", "Dal tadka", "November 2026", "Ask to add to my calendar"):
        assert words in (pane.text_content() or ""), words
    sel = "#p-helpers"
    res = c.page.evaluate(DOM_CHECKS_JS, sel)
    _assert_clean(
        res,
        c.page.evaluate(NAMELESS_JS, sel),
        c.page.evaluate(WRAP_JS, sel),
        vp,
        f"kitchen {vp} {surface}",
    )
    assert c.errors == [] and c.csp_violations() == []


def test_the_calendar_button_only_asks_for_a_card(rig: Rig) -> None:
    c = rig.get("desktop", "night")
    _kitchen_tab(c)
    rig.calls.clear()
    c.page.get_by_role("button", name="Ask to add to my calendar").click()
    c.page.locator("#hpp-kitchen .hp-note.ok").wait_for(timeout=5000)
    assert [(m, p) for m, p, _ in rig.calls] == [("PUT", "/blocks"), ("POST", "/blocks/propose")]
    assert rig.calls[0][2]["days"] == ["mon", "wed", "fri"]
    note = c.page.locator("#hpp-kitchen .hp-note").text_content() or ""
    assert note.startswith("Waiting in Approvals: Add to your calendar")
    assert c.errors == [] and c.csp_violations() == []
