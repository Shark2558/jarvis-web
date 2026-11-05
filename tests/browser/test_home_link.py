# tests/browser/test_home_link.py -- R3 A in a real browser: Integrations -> Home. The unlinked card
# with the 16 steps (collapsed), the kit link with its SHA-256, the Link dialog (code, countdown,
# polling until linked), the device picker (vendor names as text, a PUT with the chosen classes),
# the Unlink confirm (and its cancel), the "kit is older" notice, and a 390 px phone
# with no horizontal scroll. /v1/home* is answered by the test (page.route). The console is the
# real one, with I1's tags for console-home.js/css.
from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from test_console import DESKTOP, PHONE, Console  # same directory (pytest prepend import)

_pw = pytest.importorskip("playwright.sync_api")
sync_playwright = _pw.sync_playwright

pytestmark = pytest.mark.browser

STATIC = Path(__file__).resolve().parents[2] / "src" / "jarvis" / "api" / "static"
HOSTILE = '<img src=x onerror="window.__pwned=1">Lamp'
SHA = "ab" * 32


@pytest.fixture(scope="module")
def browser() -> Iterator[Any]:
    with sync_playwright() as p:
        b = p.chromium.launch()
        yield b
        b.close()


class Fake:
    def __init__(self, view: dict[str, Any]) -> None:
        self.view = view
        self.calls: list[dict[str, Any]] = []
        self.linked_after_code = True
        self.exposed: list[dict[str, Any]] = []

    def linked(self, **kw: Any) -> dict[str, Any]:
        base = {
            "available": True, "linked": True, "state": "online", "host": "laptop.tail1234.ts.net",
            "kit_outdated": False, "devices_available": True,
        }  # fmt: skip
        return {**base, **kw}


def _wire(page: Any, fake: Fake) -> None:
    def api(route: Any) -> None:
        req = route.request
        path = req.url.split("/v1/home", 1)[1].split("&")[0]
        entry: dict[str, Any] = {"method": req.method, "path": path}
        if req.post_data:
            entry["body"] = req.post_data_json
        fake.calls.append(entry)
        body: Any = fake.view
        if path == "/link-code":
            body = {"code": "ABCD-EFGH", "expires_in_s": 600}
            if fake.linked_after_code:
                fake.view = fake.linked()
        elif path == "/kit/info":
            body = {"sha256": SHA, "size": 10, "version": "1"}
        elif path.startswith("/devices") and req.method == "GET":
            if "catalogue" in path:
                body = {
                    "devices": [
                        {"entity_id": "light.lamp", "name": HOSTILE, "classes": ["everyday"]},
                        {"entity_id": "lock.gate", "name": "Gate", "classes": ["always_passkey"]},
                    ]
                }
            else:
                body = {"rev": 0, "entities": fake.exposed}
        elif path == "/devices" and req.method == "PUT":
            body = {"rev": 1, "count": len(req.post_data_json["entities"])}
        elif req.method == "DELETE":
            fake.view = {"available": True, "linked": False, "state": "not_linked"}
            body = {"unlinked": True}
        route.fulfill(status=200, content_type="application/json", body=json.dumps(body))

    page.route("**/v1/home", api)
    page.route("**/v1/home/**", api)
    page.route("**/v1/home?**", api)


def _open(
    browser: Any, server_url: str, token: str, fake: Fake, viewport: dict[str, int]
) -> Console:
    c = Console(browser, server_url, token, viewport)
    _wire(c.page, fake)
    c.open()
    c.open_panel("integrations")
    c.page.locator("#homeSet .istate:not(:has-text('Checking'))").wait_for()
    return c


def test_unlinked_card_shows_collapsed_steps_and_the_kit_with_its_hash(
    browser: Any, server_url: str, token: str
) -> None:
    fake = Fake({"available": True, "linked": False, "state": "not_linked"})
    c = _open(browser, server_url, token, fake, DESKTOP)
    try:
        assert "Not linked" in str(c.page.locator("#homeSet .istate").text_content())
        assert c.page.locator("#homeStepsBox").get_attribute("open") is None
        assert c.page.locator("#homeSteps li").count() == 16
        c.page.locator("#homeKitSha", has_text=SHA).wait_for()
        link = c.page.locator("#homeKit")
        assert link.get_attribute("href") == "/v1/home/kit"
        assert c.errors == [] and c.csp_violations() == []
    finally:
        c.close()


def test_link_dialog_shows_the_code_and_closes_when_the_laptop_has_linked(
    browser: Any, server_url: str, token: str
) -> None:
    fake = Fake({"available": True, "linked": False, "state": "not_linked"})
    c = _open(browser, server_url, token, fake, DESKTOP)
    try:
        c.page.locator("#homeLink").click()
        c.page.locator("#homeDialog[open]").wait_for()
        assert c.page.locator("#homeCode").text_content() == "ABCD-EFGH"
        assert "s left" in str(c.page.locator("#homeWaiting").text_content())
        c.page.locator("#homeDialog").wait_for(state="hidden", timeout=15000)
        c.page.locator("#homeSet .istate", has_text="Online").wait_for()
        assert "laptop.tail1234.ts.net" in str(c.page.locator("#homeBody").text_content())
        assert c.errors == [] and c.csp_violations() == []
    finally:
        c.close()


def test_cancelling_the_link_dialog_stops_polling(
    browser: Any, server_url: str, token: str
) -> None:
    fake = Fake({"available": True, "linked": False, "state": "not_linked"})
    fake.linked_after_code = False
    c = _open(browser, server_url, token, fake, DESKTOP)
    try:
        c.page.locator("#homeLink").click()
        c.page.locator("#homeDialog[open]").wait_for()
        c.page.locator("#homeDialogNo").click()
        before = len(fake.calls)
        c.page.wait_for_timeout(3600)
        assert len(fake.calls) == before
    finally:
        c.close()


def test_device_picker_shows_vendor_names_as_text_and_saves_the_chosen_class(
    browser: Any, server_url: str, token: str
) -> None:
    fake = Fake({})
    fake.view = fake.linked(kit_outdated=True)
    c = _open(browser, server_url, token, fake, DESKTOP)
    try:
        assert "older than this JARVIS" in str(c.page.locator("#homeBody").text_content())
        c.page.locator("#homeDevices").click()
        c.page.locator("#homeDialog[open]").wait_for()
        assert c.page.evaluate("window.__pwned") is None
        assert c.page.locator("#homeDialog img").count() == 0
        rows = c.page.locator("#homeRows .hrow")
        assert rows.count() == 2
        rows.nth(0).locator("input[type=checkbox]").check()
        rows.nth(0).locator("input[type=text]").fill("Lamp")
        c.page.locator("#homeDialogYes").click()
        c.page.locator("#homeNote", has_text="Saved 1 device").wait_for()
        put = [x for x in fake.calls if x["method"] == "PUT"]
        assert put and put[0]["body"] == {
            "entities": [{"entity_id": "light.lamp", "class": "everyday", "label": "Lamp"}]
        }
        assert c.errors == [] and c.csp_violations() == []
    finally:
        c.close()


def test_unlink_needs_a_confirm_and_cancel_changes_nothing(
    browser: Any, server_url: str, token: str
) -> None:
    fake = Fake({})
    fake.view = fake.linked()
    c = _open(browser, server_url, token, fake, DESKTOP)
    try:
        c.page.locator("#homeUnlink").click()
        c.page.locator("#homeDialog[open]").wait_for()
        c.page.locator("#homeDialogNo").click()
        assert not [x for x in fake.calls if x["method"] == "DELETE"]
        c.page.locator("#homeUnlink").click()
        c.page.locator("#homeDialogYes").click()
        c.page.locator("#homeSet .istate", has_text="Not linked").wait_for()
        dels = [x for x in fake.calls if x["method"] == "DELETE"]
        assert dels and dels[0]["path"].startswith("/link?confirm=1")
    finally:
        c.close()


def test_phone_has_no_horizontal_scroll(browser: Any, server_url: str, token: str) -> None:
    fake = Fake({})
    fake.view = fake.linked()
    c = _open(browser, server_url, token, fake, PHONE)
    try:
        wide = c.page.evaluate("document.documentElement.scrollWidth > window.innerWidth")
        assert wide is False
    finally:
        c.close()
