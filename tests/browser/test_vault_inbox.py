# tests/browser/test_vault_inbox.py -- Integrations -> Google Drive -> "Use for DigiLocker import"
# (R2 D9) in a real browser. /v1/drive and /v1/vault/inbox are answered by the test (page.route):
# the button asks first (a modal with focus on the safe choice), the pick is a PUT with the CSRF
# header, the picked folder shows as the import folder with a Switch off, the plain-words refusal is
# shown, hostile folder names stay text, and a server without the inbox shows no such button.
from __future__ import annotations

import json
from collections.abc import Iterator
from typing import Any

import pytest
from test_console import DESKTOP, Console  # same directory (pytest prepend import)

_pw = pytest.importorskip("playwright.sync_api")
sync_playwright = _pw.sync_playwright

pytestmark = pytest.mark.browser

SA = "jarvis-run@proj-123.iam.gserviceaccount.com"
HOSTILE = '<img src=x onerror="window.__pwned=1">Vault inbox'
STEPS = "Open the folder in Google Drive and press Share."


@pytest.fixture(scope="module")
def browser() -> Iterator[Any]:
    with sync_playwright() as p:
        b = p.chromium.launch()
        yield b
        b.close()


def _json(route: Any, status: int, body: Any) -> None:
    route.fulfill(status=status, content_type="application/json", body=json.dumps(body))


def _drive(picked: bool, wired: bool = True) -> dict[str, Any]:
    folders: list[dict[str, Any]] = [
        {"id": "use1", "name": "Registry", "confirmed": True, "readable": True},
        {
            "id": "inbox1",
            "name": HOSTILE,
            "confirmed": False,
            "readable": True,
            **({"inbox": True} if picked else {}),
        },
    ]
    out: dict[str, Any] = {
        "configured": True,
        "service_email": SA,
        "folders": folders,
        "others": 0,
        "others_more": False,
        "max_folders": 20,
    }
    if wired:
        out["inbox_wired"] = True
    return out


def _inbox(picked: bool) -> dict[str, Any]:
    return {
        "available": True,
        "configured": picked,
        "folder": {"id": "inbox1", "name": HOSTILE} if picked else None,
        "offered": [],
        "last_check_at": None,
        "imported_total": 0,
        "waiting_review": 0,
        "skipped": [],
        "note": "Imported. You can delete the copy in Drive now; JARVIS keeps an encrypted one."
        if picked
        else STEPS,
    }


class Fakes:
    def __init__(self, page: Any, *, wired: bool = True, refuse: bool = False) -> None:
        self.picked = False
        self.wired = wired
        self.refuse = refuse
        self.calls: list[dict[str, Any]] = []
        page.route("**/v1/drive", lambda r: _json(r, 200, _drive(self.picked, self.wired)))
        page.route("**/v1/vault/inbox", self._inbox)

    def _inbox(self, route: Any) -> None:
        r = route.request
        self.calls.append(
            {
                "method": r.method,
                "body": r.post_data_json if r.post_data else None,
                "csrf": r.headers.get("x-requested-with"),
            }
        )
        if r.method == "PUT":
            if self.refuse:
                return _json(
                    route,
                    409,
                    {
                        "error": "in_use_folder",
                        "detail": "Pick a folder outside the folders JARVIS reads for you.",
                    },
                )
            self.picked = True
        if r.method == "DELETE":
            self.picked = False
        _json(route, 200, _inbox(self.picked))


def _open(browser: Any, server_url: str, token: str, **kw: Any) -> tuple[Console, Fakes]:
    c = Console(browser, server_url, token, DESKTOP)
    fakes = Fakes(c.page, **kw)
    c.open()
    c.open_panel("integrations")
    c.page.locator("#driveList").wait_for()
    return c, fakes


def test_pick_asks_first_then_shows_the_import_folder_and_switch_off(
    browser: Any, server_url: str, token: str
) -> None:
    c, fakes = _open(browser, server_url, token)
    try:
        assert (
            c.page.evaluate("window.__pwned") is None
            and c.page.locator("#driveSet img").count() == 0
        )
        btn = c.page.locator('#driveList .dinbox[data-id="inbox1"]')
        assert btn.text_content() == "Use for DigiLocker import"
        assert (
            c.page.locator('#driveList .dinbox[data-id="use1"]').count() == 0
        )  # a Use folder can't be one
        btn.click()
        c.page.locator("#driveDialog[open]").wait_for()
        text = str(c.page.locator("#driveDialog").text_content())
        assert (
            "DigiLocker" in text
            and "never read this folder" in text
            and "delete them yourself" in text
        )
        assert c.page.evaluate("document.activeElement.id") == "driveDialogNo"  # the safe choice
        c.page.locator("#driveDialogNo").click()
        assert [x for x in fakes.calls if x["method"] != "GET"] == []  # cancelled: nothing sent
        btn.click()
        c.page.locator("#driveDialogYes").click()
        c.page.locator("#driveInbox").wait_for()
        put = [x for x in fakes.calls if x["method"] == "PUT"][-1]
        assert put["body"] == {"folder_id": "inbox1"} and put["csrf"] == "JARVIS"
        assert HOSTILE in str(c.page.locator("#driveInbox").text_content())
        assert (
            c.page.locator('#driveList .dfolder[data-id="inbox1"] .dchip').text_content()
            == "DigiLocker import"
        )
        assert c.page.locator('#driveList .bsw[data-id="inbox1"]').count() == 0  # not a Use switch
        c.page.locator("#driveInboxOff").click()
        c.page.locator("#driveInbox").wait_for(state="detached")
        assert [x for x in fakes.calls if x["method"] == "DELETE"][-1]["csrf"] == "JARVIS"
        assert c.errors == [] and c.csp_violations() == []
    finally:
        c.close()


def test_a_refused_pick_says_why_in_plain_words(browser: Any, server_url: str, token: str) -> None:
    c, _ = _open(browser, server_url, token, refuse=True)
    try:
        c.page.locator('#driveList .dinbox[data-id="inbox1"]').click()
        c.page.locator("#driveDialogYes").click()
        c.page.locator("#driveNote.bad", has_text="outside the folders JARVIS reads").wait_for()
        assert c.page.locator("#driveInbox").count() == 0
    finally:
        c.close()


def test_a_server_without_the_inbox_shows_no_import_button(
    browser: Any, server_url: str, token: str
) -> None:
    c, fakes = _open(browser, server_url, token, wired=False)
    try:
        assert c.page.locator(".dinbox").count() == 0
        assert not [x for x in fakes.calls]  # /v1/vault/inbox was never asked
        assert c.errors == [] and c.csp_violations() == []
    finally:
        c.close()
