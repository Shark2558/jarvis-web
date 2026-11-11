# tests/browser/test_r11_i1_upi.py -- R11 I1, the approved UPI payment under a reply (kind 'upi'
# in ChatResponse.cards; console-helpers.js `JarvisUpi`), in headless Chromium: a well-made card
# draws the code's words, the QR image and "Open in UPI app" once, textContent only; a card with a
# link or QR the server would never make draws nothing; no JS errors and no CSP violations.
from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest
from test_console import DESKTOP, Console
from ui_checks import install_mocks

from jarvis.helpers.today.qr import qr_data_uri

_pw = pytest.importorskip("playwright.sync_api")
sync_playwright = _pw.sync_playwright

pytestmark = pytest.mark.browser

LINK = "upi://pay?pa=test@okfake&pn=Power%20Co&am=1240.00&cu=INR&tn=Electricity%20Nov"
WORDS = "₹1,240.00 to “Power Co” (test@okfake), note “Electricity Nov”. JARVIS never pays."
DRAW_JS = """([cards]) => {
  const row = document.createElement('div');
  row.id = 'upi-test-row';
  document.body.append(row);
  const box = window.JarvisUpi.render(row, cards);
  return { drawn: !!box, html: row.innerHTML.length, text: row.textContent,
           img: (row.querySelector('img') || {}).src || '',
           buttons: [...row.querySelectorAll('button')].map((b) => b.textContent) };
}"""


@pytest.fixture(scope="module")
def browser() -> Iterator[Any]:
    with sync_playwright() as p:
        b = p.chromium.launch()
        yield b
        b.close()


def test_an_approved_payment_draws_once_and_an_odd_card_draws_nothing(
    browser: Any, server_url: str, token: str
) -> None:
    c = Console(browser, server_url, token, DESKTOP)
    install_mocks(c.page)
    c.open()
    try:
        page = c.page
        page.wait_for_function("() => !!window.JarvisUpi")
        good = {"kind": "upi", "link": LINK, "qr": qr_data_uri(LINK), "words": WORDS}
        got = page.evaluate(DRAW_JS, [[good, {"kind": "places"}]])
        assert got["drawn"] and got["img"].startswith("data:image/svg+xml")
        assert WORDS in got["text"] and got["buttons"] == ["Open in UPI app", "Done"]
        page.evaluate("() => document.getElementById('upi-test-row').remove()")
        for bad in (
            {**good, "link": "javascript:alert(1)"},
            {**good, "link": "https://evil.example/pay"},
            {**good, "qr": "data:text/html,<b>x</b>"},
            {**good, "words": ""},
        ):
            odd = page.evaluate(DRAW_JS, [[bad]])
            assert odd["drawn"] is False and odd["html"] == 0, bad
            page.evaluate("() => document.getElementById('upi-test-row').remove()")
        assert c.csp_violations() == [] and c.errors == []
    finally:
        c.close()
