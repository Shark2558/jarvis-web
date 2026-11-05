# tests/browser/test_telegram.py -- R1 D1/D2/D4/D6 in a real browser: Integrations -> Telegram. Off
# with the steps in words (and no Pair button), the Pair dialog (code, t.me link, "Waiting for
# Telegram..." until paired), the private-reads switch with its confirm (and its cancel), alert
# switches, Test alert, Unpair with its confirm, hostile text shown as text, and a 390 px phone with
# no horizontal scroll. /v1/telegram* is answered by the test (page.route); the console is the real
# one, with its real console-telegram tags. 0 JS errors and 0 CSP reports throughout.
from __future__ import annotations

import json
from collections.abc import Iterator
from typing import Any

import pytest
from test_console import DESKTOP, PHONE, Console  # same directory (pytest prepend import)

_pw = pytest.importorskip("playwright.sync_api")
sync_playwright = _pw.sync_playwright

pytestmark = pytest.mark.browser

HOSTILE = '<img src=x onerror="window.__pwned=1">Telegram said no'
LINK = "https://t.me/jarvis_test_bot?start=AB12CD34"


@pytest.fixture(scope="module")
def browser() -> Iterator[Any]:
    with sync_playwright() as p:
        b = p.chromium.launch()
        yield b
        b.close()


class Fake:
    """The server side of /v1/telegram*, as the test wants it to look."""

    def __init__(self, view: dict[str, Any]) -> None:
        self.view = view
        self.calls: list[dict[str, Any]] = []
        self.pair_status = 200
        self.paired_after_pair = True

    def paired_view(self, **kw: Any) -> dict[str, Any]:
        base = {
            "configured": True, "bot_username": "jarvis_test_bot", "paired": True,
            "paired_at": "2027-01-15T03:00:00+00:00", "account_hint": "••1234",
            "webhook": {"registered": True, "pending": 0, "last_error": None},
            "allow_private_reads": False,
            "alerts": {"approval_waiting": True, "offline": True, "brief_ready": False},
        }  # fmt: skip
        return {**base, **kw}


def _wire(page: Any, server_url: str, fake: Fake) -> None:
    def api(route: Any) -> None:
        req = route.request
        path = req.url.split("/v1/telegram", 1)[1].split("?")[0]
        entry = {"method": req.method, "path": path, "csrf": req.headers.get("x-requested-with")}
        if req.post_data:
            entry["body"] = req.post_data_json
        fake.calls.append(entry)
        body: Any = fake.view
        status = 200
        if req.method == "POST" and path == "/pair":
            status = fake.pair_status
            body = {"code": "AB12CD34", "link": LINK, "expires_in_s": 600}
            if fake.paired_after_pair:
                fake.view = fake.paired_view()
        elif req.method == "DELETE":
            fake.view = {**fake.view, "paired": False, "account_hint": None}
            body = fake.view
        elif req.method == "PUT":
            b = req.post_data_json
            if "allow_private_reads" in b:
                fake.view = {**fake.view, "allow_private_reads": b["allow_private_reads"]}
            if "allow_personal_reads" in b:
                fake.view = {**fake.view, "allow_personal_reads": b["allow_personal_reads"]}
            if "alerts" in b:
                fake.view = {**fake.view, "alerts": {**fake.view["alerts"], **b["alerts"]}}
            body = fake.view
        elif req.method == "POST" and path == "/test-alert":
            body = {"sent": True}
        route.fulfill(status=status, content_type="application/json", body=json.dumps(body))

    page.route("**/v1/telegram", api)
    page.route("**/v1/telegram/**", api)


def _open(
    browser: Any, server_url: str, token: str, fake: Fake, viewport: dict[str, int]
) -> Console:
    c = Console(browser, server_url, token, viewport)
    _wire(c.page, server_url, fake)
    c.open()
    c.open_panel("integrations")
    c.page.locator("#telegramSet").wait_for()
    return c


def test_off_server_explains_how_to_switch_telegram_on(
    browser: Any, server_url: str, token: str
) -> None:
    fake = Fake({"configured": False})
    c = _open(browser, server_url, token, fake, DESKTOP)
    try:
        c.page.locator("#telegramSteps").wait_for()
        sec = c.page.locator("#telegramSet")
        assert "Off" in str(sec.locator(".istate").text_content())
        assert "not switched on yet" in str(sec.text_content())
        steps = c.page.locator("#telegramSteps li").all_text_contents()
        assert "@BotFather" in steps[0] and "--telegram" in steps[1] and "Pair" in steps[2]
        assert c.page.locator("#telegramPair").count() == 0
        assert c.errors == [] and c.csp_violations() == []
    finally:
        c.close()


def test_pairing_shows_the_code_and_link_then_closes_when_telegram_confirms(
    browser: Any, server_url: str, token: str
) -> None:
    fake = Fake(
        {"configured": True, "bot_username": "jarvis_test_bot", "paired": False,
         "paired_at": None, "account_hint": None,
         "webhook": {"registered": True, "pending": 0, "last_error": None},
         "allow_private_reads": False,
         "alerts": {"approval_waiting": True, "offline": True, "brief_ready": False}}
    )  # fmt: skip
    c = _open(browser, server_url, token, fake, DESKTOP)
    try:
        c.page.locator("#telegramPair").click()
        c.page.locator("#telegramDialog[open]").wait_for()
        assert c.page.locator("#telegramCode").text_content() == "AB12CD34"
        link = c.page.locator("#telegramLink")
        assert (
            link.get_attribute("href") == LINK
            and link.get_attribute("rel") == "noopener noreferrer"
        )
        assert "Waiting for Telegram" in str(c.page.locator("#telegramWaiting").text_content())
        pair_calls = [x for x in fake.calls if x["method"] == "POST" and x["path"] == "/pair"]
        assert pair_calls and pair_calls[0]["csrf"] == "JARVIS"
        # the poll (every 3 s) sees the pairing and closes the dialog
        c.page.locator("#telegramDialog").wait_for(state="hidden", timeout=15000)
        c.page.locator("#telegramSet .istate", has_text="Paired").wait_for()
        assert "••1234" in str(c.page.locator("#telegramBody").text_content())
        assert c.errors == [] and c.csp_violations() == []
    finally:
        c.close()


def test_cancelling_the_pair_dialog_stops_waiting(
    browser: Any, server_url: str, token: str
) -> None:
    fake = Fake({"configured": True, "bot_username": "jarvis_test_bot", "paired": False,
                 "account_hint": None, "webhook": {"registered": True, "pending": 0},
                 "allow_private_reads": False, "alerts": {}})  # fmt: skip
    fake.paired_after_pair = False
    c = _open(browser, server_url, token, fake, DESKTOP)
    try:
        c.page.locator("#telegramPair").click()
        c.page.locator("#telegramDialog[open]").wait_for()
        c.page.locator("#telegramDialogNo").click()
        assert not c.page.evaluate("document.getElementById('telegramDialog').open")
        before = len(fake.calls)
        c.page.wait_for_timeout(3600)
        assert len(fake.calls) == before  # no more polling
        assert c.page.locator("#telegramPair").count() == 1
    finally:
        c.close()


def test_a_voided_or_expired_code_is_said_in_the_dialog(
    browser: Any, server_url: str, token: str
) -> None:
    fake = Fake(
        {"configured": True, "bot_username": "jarvis_test_bot", "paired": False,
         "account_hint": None, "pairing_pending": False,
         "webhook": {"registered": True, "pending": 0}, "allow_private_reads": False,
         "alerts": {}}
    )  # fmt: skip
    fake.paired_after_pair = False
    c = _open(browser, server_url, token, fake, DESKTOP)
    try:
        c.page.locator("#telegramPair").click()
        c.page.locator("#telegramWaiting", has_text="expired or was voided").wait_for(timeout=10000)
    finally:
        c.close()


def test_paired_controls_confirm_save_and_unpair(browser: Any, server_url: str, token: str) -> None:
    fake = Fake({})
    fake.view = fake.paired_view(webhook={"registered": True, "pending": 2, "last_error": HOSTILE})
    c = _open(browser, server_url, token, fake, DESKTOP)
    try:
        c.page.locator("#telegramReads").wait_for()
        # hostile text is text, never markup
        assert c.page.evaluate("window.__pwned") is None
        assert c.page.locator("#telegramSet img").count() == 0
        # private reads: cancel changes nothing, confirm saves
        reads = c.page.locator("#telegramReads")
        assert reads.get_attribute("aria-pressed") == "false"
        reads.click()
        c.page.locator("#telegramDialog[open]").wait_for()
        said = str(c.page.locator("#telegramDialogText").text_content())
        assert "end-to-end" in said
        # the switch also covers family calendars and recently deleted items (R1 review fix)
        assert "family calendars" in said and "recently deleted" in said
        c.page.locator("#telegramDialogNo").click()
        assert not [x for x in fake.calls if x["method"] == "PUT"]
        c.page.locator("#telegramReads").click()
        c.page.locator("#telegramDialogYes").click()
        c.page.locator('#telegramReads[aria-pressed="true"]').wait_for()
        put = [x for x in fake.calls if x["method"] == "PUT"][-1]
        assert put["body"] == {"allow_private_reads": True} and put["csrf"] == "JARVIS"
        # switching it off needs no confirm
        c.page.locator("#telegramReads").click()
        c.page.locator('#telegramReads[aria-pressed="false"]').wait_for()
        # an alert switch
        c.page.locator("#telegramAlert_brief_ready").click()
        c.page.locator('#telegramAlert_brief_ready[aria-pressed="true"]').wait_for()
        assert [x for x in fake.calls if x["method"] == "PUT"][-1]["body"] == {
            "alerts": {"brief_ready": True}
        }
        # test alert
        c.page.locator("#telegramTest").click()
        c.page.locator("#telegramNote", has_text="Test alert sent").wait_for()
        # unpair asks first
        c.page.locator("#telegramUnpair").click()
        c.page.locator("#telegramDialog[open]").wait_for()
        c.page.locator("#telegramDialogYes").click()
        c.page.locator("#telegramPair").wait_for()
        assert [x for x in fake.calls if x["method"] == "DELETE"][-1]["csrf"] == "JARVIS"
        assert c.errors == [] and c.csp_violations() == []
    finally:
        c.close()


def test_the_personal_switch_names_exactly_what_it_opens(
    browser: Any, server_url: str, token: str
) -> None:
    """R2 D12: vault metadata (never files), notes and things; its own switch, its own PUT."""
    fake = Fake({})
    fake.view = fake.paired_view(allow_personal_reads=False)
    c = _open(browser, server_url, token, fake, DESKTOP)
    try:
        sw = c.page.locator("#telegramPersonal")
        sw.wait_for()
        assert sw.get_attribute("aria-pressed") == "false"
        label = str(c.page.locator("#telegramSet").text_content())
        assert "vault list, notes and things (never files)" in label
        sw.click()
        c.page.locator("#telegramDialog[open]").wait_for()
        said = str(c.page.locator("#telegramDialogText").text_content())
        assert "end-to-end" in said
        assert "vault list" in said and "never the files" in said and "last 4" in said
        assert "notes" in said and "voice memos" in said and "saved links" in said
        assert "where you keep things" in said
        assert "email" not in said.lower()  # this switch opens nothing of the other one
        assert c.page.evaluate("document.activeElement.id") == "telegramDialogNo"
        c.page.locator("#telegramDialogNo").click()
        assert not [x for x in fake.calls if x["method"] == "PUT"]
        sw.click()
        c.page.locator("#telegramDialogYes").click()
        c.page.locator('#telegramPersonal[aria-pressed="true"]').wait_for()
        put = [x for x in fake.calls if x["method"] == "PUT"][-1]
        assert put["body"] == {"allow_personal_reads": True} and put["csrf"] == "JARVIS"
        assert c.page.locator('#telegramReads[aria-pressed="false"]').count() == 1
        # the vault alert switch (D5), off by default
        va = c.page.locator("#telegramAlert_vault_expiry")
        assert va.get_attribute("aria-pressed") == "false"
        va.click()
        c.page.locator('#telegramAlert_vault_expiry[aria-pressed="true"]').wait_for()
        assert [x for x in fake.calls if x["method"] == "PUT"][-1]["body"] == {
            "alerts": {"vault_expiry": True}
        }
        assert c.errors == [] and c.csp_violations() == []
    finally:
        c.close()


def test_phone_has_no_horizontal_scroll_and_reachable_controls(
    browser: Any, server_url: str, token: str
) -> None:
    fake = Fake({})
    fake.view = fake.paired_view()
    c = _open(browser, server_url, token, fake, PHONE)
    try:
        c.page.locator("#telegramReads").wait_for()
        assert c.page.evaluate(
            "document.documentElement.scrollWidth <= document.documentElement.clientWidth"
        )
        assert c.page.evaluate("document.getElementById('telegramSet').scrollWidth <= 390")
        box = c.page.locator("#telegramTest").bounding_box()
        assert box is not None and box["height"] >= 44
        assert c.errors == [] and c.csp_violations() == []
    finally:
        c.close()


def test_a_server_error_offers_retry(browser: Any, server_url: str, token: str) -> None:
    fake = Fake({})
    c = Console(browser, server_url, token, DESKTOP)
    try:
        _wire(c.page, server_url, fake)
        c.page.route(
            "**/v1/telegram",
            lambda r: r.fulfill(
                status=503, content_type="application/json",
                body=json.dumps({"error": "telegram_unavailable", "detail": "No."}),
            ),
        )  # fmt: skip
        c.open()
        c.open_panel("integrations")
        c.page.locator("#telegramRetry").wait_for()
        assert "Couldn't check Telegram" in str(c.page.locator("#telegramBody").text_content())
    finally:
        c.close()
