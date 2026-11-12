# tests/browser/test_r11_a_today.py -- R11 Part A's Today tab (docs/plans/r11-free-helpers.md D19)
# in headless Chromium, held to the visual gate (tests/browser/ui_checks.py, read-only here) in
# Night and Day at 1440x900 and 390x844: no overlaps, no browser-default controls, theme fonts,
# nothing sideways, every control named and labelled before it, contrast >= 4.5:1, 44 px targets
# on the phone, no JS errors and no CSP violations. The tab's data is mocked with realistic shapes
# (a bill with an approved payment ready, one with no UPI ID, a varies bill, top priority, pending,
# birthdays on); "Show payment" draws the QR image and the Open-in-UPI-app button once.
from __future__ import annotations

import json
from collections.abc import Callable, Iterator
from typing import Any

import pytest
from test_console import DESKTOP, PHONE, Console
from test_ui_audit import NAMELESS_JS, WRAP_JS, _assert_clean
from ui_checks import DOM_CHECKS_JS, FINISH_ANIMATIONS_JS, install_mocks

from jarvis.helpers.today.qr import qr_data_uri

_pw = pytest.importorskip("playwright.sync_api")
sync_playwright = _pw.sync_playwright
Route = _pw.Route

pytestmark = pytest.mark.browser

LINK = "upi://pay?pa=test@okfake&pn=Power%20Co&am=1240.00&cu=INR&tn=Electricity%20Nov"
BILL = {
    "every_months": 1,
    "last4": "",
}
TODAY = {
    "bills": {
        "available": True,
        "note": "",
        "prefs": {"bills_at": "09:00", "birthdays_on": True, "birthday_at": "08:30"},
        "items": [
            {
                **BILL,
                "id": "a1b2c3d4e5f6",
                "label": "Electricity",
                "payee": "Power Co",
                "upi": "test@okfake",
                "amount": "₹1,240",
                "next_due": "2026-11-13",
                "when": "due tomorrow",
                "ready": True,
            },
            {
                **BILL,
                "id": "b1b2c3d4e5f6",
                "label": "Broadband and landline",
                "payee": "",
                "upi": "",
                "amount": "₹899",
                "next_due": "2026-11-20",
                "when": "due Fri 20 Nov",
                "ready": False,
            },
            {
                **BILL,
                "id": "c1b2c3d4e5f6",
                "label": "Water",
                "payee": "Water Board",
                "upi": "water.board@okfake",
                "amount": "(amount varies)",
                "next_due": "2026-11-11",
                "when": "overdue since Wed 11 Nov",
                "ready": False,
            },
        ],
    },
    "birthdays": {
        "on": True,
        "at": "08:30",
        "state": "ok",
        "note": "",
        "today": ["Asha Example"],
        "soon": [{"name": "Ravi Example", "on": "Sat 14 Nov"}],
    },
    "top": {
        "source": "Bills",
        "label": "Water (amount varies) overdue since Wed 11 Nov",
        "urgency": "overdue",
        "due": None,
    },
    "pending": [
        {
            "source": "Bills",
            "items": [
                {
                    "label": "Water (amount varies) overdue since Wed 11 Nov",
                    "urgency": "overdue",
                    "due": None,
                }
            ],
        },
        {
            "source": "Home",
            "items": [{"label": "Water-purifier filter due", "urgency": "today", "due": None}],
        },
        {
            "source": "To-dos",
            "items": [{"label": "File the GST return", "urgency": "soon", "due": None}],
        },
    ],
    "not_checked": [],
}


def _json(body: Any, status: int = 200) -> Callable[[Any], None]:
    def handle(route: Any) -> None:
        route.fulfill(status=status, content_type="application/json", body=json.dumps(body))

    return handle


def _today_routes(page: Any) -> list[str]:
    asked: list[str] = []

    def payment(route: Any) -> None:
        asked.append(route.request.url)
        body = {"link": LINK, "qr": qr_data_uri(LINK), "upi": "test@okfake", "payee": "Power Co",
                "amount": "₹1,240.00", "note": "Electricity Nov"}  # fmt: skip
        route.fulfill(status=200, content_type="application/json", body=json.dumps(body))

    page.route("**/v1/helpers/today", _json(TODAY))
    page.route("**/v1/helpers/today/bills/*/payment", payment)
    return asked


@pytest.fixture(scope="module")
def browser() -> Iterator[Any]:
    with sync_playwright() as p:
        b = p.chromium.launch()
        yield b
        b.close()


def _open_today(
    browser: Any, url: str, token: str, size: dict[str, int], surface: str
) -> tuple[Console, list[str]]:
    c = Console(browser, url, token, size)
    install_mocks(c.page)
    asked = _today_routes(c.page)
    c.open()
    if surface == "day":
        c.choose_day()
    c.page.wait_for_timeout(800)
    c.open_panel("helpers")
    c.page.locator("#hpt-today").click()
    c.page.locator("#hpp-today .hp-row").first.wait_for(state="visible")
    c.page.wait_for_timeout(700)
    return c, asked


@pytest.mark.parametrize("surface", ["night", "day"])
@pytest.mark.parametrize("vp", ["desktop", "phone"])
def test_the_today_tab_passes_the_visual_gate(
    browser: Any, server_url: str, token: str, vp: str, surface: str
) -> None:
    size = DESKTOP if vp == "desktop" else PHONE
    c, _ = _open_today(browser, server_url, token, size, surface)
    try:
        page = c.page
        assert page.locator("html").get_attribute("data-surface") == surface
        text = str(page.locator("#hpp-today").text_content())
        for words in (
            "Top priority now",
            "Electricity",
            "Show payment",
            "Set UPI ID",
            "Asha Example",
            "Birthday reminders",
        ):
            assert words in text, words
        page.evaluate(FINISH_ANIMATIONS_JS)
        res = page.evaluate(DOM_CHECKS_JS, "#p-helpers")
        _assert_clean(
            res,
            page.evaluate(NAMELESS_JS, "#p-helpers"),
            page.evaluate(WRAP_JS, "#p-helpers"),
            vp,
            f"today {vp} {surface}",
        )
        assert c.csp_violations() == [] and c.errors == []
    finally:
        c.close()


def test_show_payment_draws_the_qr_and_the_upi_button_once(
    browser: Any, server_url: str, token: str
) -> None:
    c, asked = _open_today(browser, server_url, token, DESKTOP, "night")
    try:
        page = c.page
        page.locator("#hpp-today button", has_text="Show payment").first.click()
        img = page.locator('#hpp-today img[alt="QR code of this UPI payment"]')
        img.wait_for(state="visible")
        assert str(img.get_attribute("src")).startswith("data:image/svg+xml")
        assert page.evaluate("document.querySelector('#hpp-today img').naturalWidth") > 0
        assert page.locator("#hpp-today button", has_text="Open in UPI app").count() == 1
        assert "JARVIS never pays" in str(page.locator("#hpp-today").inner_text())
        assert len(asked) == 1
        page.locator("#hpp-today button", has_text="Done").click()
        assert page.locator("#hpp-today img").count() == 0
        page.evaluate(FINISH_ANIMATIONS_JS)
        res = page.evaluate(DOM_CHECKS_JS, "#p-helpers")
        assert res["overlaps"] == [] and res["contrast"] == []
        assert c.csp_violations() == [] and c.errors == []
    finally:
        c.close()


def test_a_varies_bill_asks_for_the_amount_inline_and_no_html_is_injected(
    browser: Any, server_url: str, token: str
) -> None:
    c, _ = _open_today(browser, server_url, token, PHONE, "night")
    try:
        page = c.page
        water = page.locator('#hpp-today [data-bill="c1b2c3d4e5f6"]')
        water.get_by_role("button", name="Pay", exact=True).click()
        field = page.locator("#hpp-today label", has_text="amount varies").locator("input")
        field.wait_for(state="visible")
        assert page.locator("#hpp-today script, #hpp-today b > *").count() == 0
        page.evaluate(FINISH_ANIMATIONS_JS)
        res = page.evaluate(DOM_CHECKS_JS, "#p-helpers")
        assert res["smallTargets"] == [] and res["unlabelled"] == []
        assert c.errors == []
    finally:
        c.close()
