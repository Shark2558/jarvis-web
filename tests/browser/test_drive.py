# tests/browser/test_drive.py — slice 12 D1 in a real browser: Integrations → Google Drive. JARVIS's
# address with Copy, the three numbered steps, the folder list with a Use switch (On / Off in words,
# a PUT through the console's transport with the CSRF header), the "not offered: shared by another
# account" line, hostile folder names shown as text (never markup), a server without Drive (the
# section stays hidden), and a 390 px phone with no horizontal scroll. /v1/drive is answered by the
# test (page.route); everything else is the real app. 0 JS errors and 0 CSP reports throughout.
from __future__ import annotations

import json
import time
from collections.abc import Iterator
from typing import Any

import pytest
from test_console import DESKTOP, PHONE, Console  # same directory (pytest prepend import)

_pw = pytest.importorskip("playwright.sync_api")
sync_playwright = _pw.sync_playwright

pytestmark = pytest.mark.browser

SA = "jarvis-run@proj-123.iam.gserviceaccount.com"
HOSTILE = '<img src=x onerror="window.__pwned=1">Board papers'


def _view(confirmed: bool = False) -> dict[str, Any]:
    return {
        "configured": True,
        "service_email": SA,
        "folders": [
            {"id": "root1", "name": "Registry", "confirmed": confirmed, "readable": True},
            {"id": "root2", "name": HOSTILE, "confirmed": False, "readable": True},
            # switched on earlier; JARVIS can't read it now (un-shared, or re-shared by another)
            {"id": "root3", "name": "Old board", "confirmed": True, "readable": False},
        ],
        "others": 2,
        "others_more": False,
        "max_folders": 20,
    }


@pytest.fixture(scope="module")
def browser() -> Iterator[Any]:
    with sync_playwright() as p:
        b = p.chromium.launch()
        yield b
        b.close()


def _drive_routes(page: Any, puts: list[dict[str, Any]]) -> None:
    state = {"on": False}

    def get(route: Any) -> None:
        route.fulfill(
            status=200, content_type="application/json", body=json.dumps(_view(state["on"]))
        )

    def put(route: Any) -> None:
        req = route.request
        puts.append(
            {
                "url": req.url,
                "body": req.post_data_json,
                "csrf": req.headers.get("x-requested-with"),
            }
        )
        state["on"] = bool(req.post_data_json.get("use"))
        route.fulfill(
            status=200, content_type="application/json", body=json.dumps(_view(state["on"]))
        )

    page.route("**/v1/drive", get)
    page.route("**/v1/drive/roots/*", put)


def test_drive_section_shows_address_steps_folders_and_switches(
    browser: Any, server_url: str, token: str
) -> None:
    c = Console(browser, server_url, token, DESKTOP)
    try:
        puts: list[dict[str, Any]] = []
        _drive_routes(c.page, puts)
        c.ctx.grant_permissions(["clipboard-read", "clipboard-write"], origin=server_url)
        c.open()
        c.open_panel("integrations")
        sec = c.page.locator("#driveSet")
        sec.wait_for()
        c.page.locator("#driveList").wait_for()
        assert c.page.locator("#driveAddr").input_value() == SA
        assert "No folders in use" in str(sec.locator(".istate").text_content())
        # the hostile folder name is text, never markup
        assert c.page.evaluate("window.__pwned") is None
        assert c.page.locator("#driveSet img").count() == 0
        names = c.page.locator("#driveList .dfolder b").all_text_contents()
        assert names == ["Registry", HOSTILE, "Old board"]
        # switched on but unreadable: said truthfully, and the switch still turns it off
        old = c.page.locator('#driveList .dfolder[data-id="root3"]')
        assert "Switched on, but JARVIS can't currently read it" in str(old.text_content())
        old_sw = old.locator(".bsw")
        assert old_sw.get_attribute("aria-pressed") == "true"
        assert old_sw.get_attribute("aria-disabled") is None
        # three numbered steps (behind "How to share another folder" once folders exist)
        c.page.locator("#driveSet details.dhow summary").click()
        steps = c.page.locator("#driveSteps li").all_text_contents()
        assert steps[0].startswith("Open the folder in Google Drive") and "Viewer" in steps[2]
        # others: a count, never their names
        assert "2 folders not offered: shared by another account" in str(
            c.page.locator("#driveOthers").text_content()
        )
        # Copy puts the address on the clipboard
        c.page.locator("#driveCopy").click()
        c.page.locator("#driveNote", has_text="Address copied").wait_for()
        assert c.page.evaluate("navigator.clipboard.readText()") == SA
        # Use: off → on (asked first, FE-1), through the console's transport with the CSRF header
        sw = c.page.locator('#driveList .bsw[data-id="root1"]')
        assert (
            sw.get_attribute("aria-pressed") == "false"
            and sw.locator(".st").text_content() == "Off"
        )
        assert sw.get_attribute("aria-label") == "Use “Registry”"  # FE-10: same text
        sw.click()
        c.page.locator("#driveDialog[open]").wait_for()
        c.page.locator("#driveDialogYes").click()
        c.page.locator('#driveList .bsw[data-id="root1"][aria-pressed="true"]').wait_for()
        assert c.page.locator('#driveList .bsw[data-id="root1"] .st').text_content() == "On"
        assert puts and puts[-1]["body"] == {"use": True} and puts[-1]["csrf"] == "JARVIS"
        assert puts[-1]["url"].endswith("/v1/drive/roots/root1")
        assert "1 in use" in str(sec.locator(".istate").text_content())
        assert c.errors == [] and c.csp_violations() == []
    finally:
        c.close()


def test_drive_section_stays_hidden_without_drive(
    browser: Any, server_url: str, token: str
) -> None:
    c = Console(browser, server_url, token, DESKTOP)
    try:
        c.open()  # the real server has JARVIS_DRIVE off: {configured: false}
        c.open_panel("integrations")
        c.page.locator("#driveSet[hidden]").wait_for(state="attached")  # CSP: no string eval
        assert c.errors == [] and c.csp_violations() == []
    finally:
        c.close()


def test_drive_section_fits_a_phone(browser: Any, server_url: str, token: str) -> None:
    c = Console(browser, server_url, token, PHONE)
    try:
        _drive_routes(c.page, [])
        c.open()
        c.open_panel("integrations")
        c.page.locator("#driveList").wait_for()
        overflow = c.page.evaluate(
            "document.documentElement.scrollWidth - document.documentElement.clientWidth"
        )
        assert overflow <= 0
        box = c.page.locator('#driveList .bsw[data-id="root1"]').bounding_box()
        assert box is not None and box["height"] >= 44  # touch target
        assert c.errors == []
    finally:
        c.close()


# ---- review FE-1: switching a folder ON asks first; switching off stays one tap ----------------


def _focused_id(c: Console) -> str | None:
    return c.page.evaluate("document.activeElement && document.activeElement.dataset.id || null")


@pytest.mark.parametrize("viewport", [DESKTOP, PHONE], ids=["desktop", "phone"])
def test_switching_a_folder_on_asks_first_and_esc_sends_nothing(
    browser: Any, server_url: str, token: str, viewport: dict[str, int]
) -> None:
    c = Console(browser, server_url, token, viewport)
    try:
        puts: list[dict[str, Any]] = []
        _drive_routes(c.page, puts)
        c.open()
        c.open_panel("integrations")
        c.page.locator("#driveList").wait_for()
        dlg = c.page.locator("#driveDialog")
        # Off -> On by keyboard: the dialog names the (hostile) folder as text, never markup
        sw = c.page.locator('#driveList .bsw[data-id="root2"]')
        sw.focus()
        c.page.keyboard.press("Enter")
        c.page.locator("#driveDialog[open]").wait_for()
        assert c.page.evaluate("document.getElementById('driveDialog').matches(':modal')")
        text = str(dlg.text_content())
        assert HOSTILE in text
        assert f"JARVIS will be able to read the files in “{HOSTILE}”" in text
        assert "sends what it reads to the brain (Claude)" in text
        assert c.page.locator("#driveDialog img").count() == 0
        assert c.page.evaluate("window.__pwned") is None
        assert c.page.evaluate("document.activeElement.id") == "driveDialogNo"  # the safe choice
        # Esc = Not now: no PUT, the dialog closes, focus is back on the switch, panel stays open
        c.page.keyboard.press("Escape")
        c.page.wait_for_function("!document.getElementById('driveDialog').open")
        c.page.wait_for_timeout(200)
        assert puts == []
        assert _focused_id(c) == "root2"
        assert c.page.locator("#p-integrations").is_visible()
        assert sw.get_attribute("aria-pressed") == "false"
        # "Not now" is the same
        sw.click()
        c.page.locator("#driveDialog[open]").wait_for()
        c.page.locator("#driveDialogNo").click()
        c.page.wait_for_timeout(200)
        assert puts == [] and _focused_id(c) == "root2"
        # Confirm: PUT {use: true}, focus back on the switch
        c.page.locator('#driveList .bsw[data-id="root1"]').click()
        c.page.locator("#driveDialog[open]").wait_for()
        assert "“Registry”" in str(dlg.text_content())
        c.page.locator("#driveDialogYes").click()
        c.page.locator('#driveList .bsw[data-id="root1"][aria-pressed="true"]').wait_for()
        assert [p["body"] for p in puts] == [{"use": True}]
        assert puts[0]["url"].endswith("/v1/drive/roots/root1")
        assert _focused_id(c) == "root1"
        note = str(c.page.locator("#driveNote").text_content())
        assert note == "JARVIS can now read “Registry” and what is inside it."  # FE-10
        # switching off is one tap: no dialog
        c.page.locator('#driveList .bsw[data-id="root1"]').click()
        c.page.locator('#driveList .bsw[data-id="root1"][aria-pressed="false"]').wait_for()
        assert [p["body"] for p in puts] == [{"use": True}, {"use": False}]
        assert c.page.evaluate("document.getElementById('driveDialog').open") is False
        assert c.errors == [] and c.csp_violations() == []
    finally:
        c.close()


# ---- review FE-9: console-drive.js arriving after jarvis:ready still loads an open panel -------

SIGNED_IN = "sessionStorage.setItem('jarvis_token', {})"  # boot() runs at once, no gate to fill
INTEG_OPEN = (
    "try { localStorage.setItem('jarvis_deck_v1', JSON.stringify("
    "{v: 1, p: {chat: {open: true}, integrations: {open: true}}})); } catch (_) {}"
)


def test_a_late_drive_script_still_loads_when_integrations_is_open(
    browser: Any, server_url: str, token: str
) -> None:
    c = Console(browser, server_url, token, DESKTOP)
    try:
        _drive_routes(c.page, [])

        def late(route: Any) -> None:
            time.sleep(1.0)  # the page keeps running: console.js signs in meanwhile
            route.continue_()

        c.page.route("**/static/console-drive.js", late)
        c.page.add_init_script(INTEG_OPEN)
        c.page.add_init_script(SIGNED_IN.format(json.dumps(c.token)))
        c.page.goto(c.url)
        c.page.locator("#welcome").wait_for()
        c.page.locator("#p-integrations").wait_for(state="visible")
        c.page.locator("#driveSet #driveList").wait_for(timeout=8000)
        assert c.errors == []
    finally:
        c.close()
