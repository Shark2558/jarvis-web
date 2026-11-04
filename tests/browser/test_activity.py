# tests/browser/test_activity.py -- R1 B in a real browser: Activity "What JARVIS did" (D7/D8).
# Rows in plain words with Telegram / Voice / Offline chips, Undo only on a delete the bin can
# restore (it calls the existing restore route and the row then reads Restored), the reason on every
# other row, hostile text shown as text, the Yesterday tab, "Show full log" behind the list, a
# 390 px phone with no sideways scroll and 44 px targets.
# /v1/activity and /v1/deleted/{id}/restore are answered by the test (page.route). The console is
# the real one, with its real console-activity tags.
from __future__ import annotations

import json
from collections.abc import Iterator
from typing import Any

import pytest
from test_console import DESKTOP, PHONE, Console  # same directory (pytest prepend import)

_pw = pytest.importorskip("playwright.sync_api")
sync_playwright = _pw.sync_playwright

pytestmark = pytest.mark.browser

HOSTILE = '<img src=x onerror="window.__pwned=1">Remind you: call mum'
DEL = "del_0123456789abcdef0123"
GONE = "del_fedcba9876543210fedc"


def _row(i: int, words: str, **kw: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "id": f"act_{i:020x}",
        "at": "2026-11-05T09:30:00Z",
        "words": words,
        "outcome": "done",
        "channel": "console",
        "offline": False,
        "undo": None,
        "undo_note": "",
    }
    return {**base, **kw}


class FakeActivity:
    def __init__(self) -> None:
        self.restored = False
        self.restore_calls = 0
        self.fail_restore = False
        self.available = True

    def today(self) -> dict[str, Any]:
        state = "restored" if self.restored else "available"
        items = [
            _row(
                1,
                "You restored the event \u201cDentist\u201d",
                undo_note="Delete it again if you didn't want it back",
            )
            if self.restored
            else _row(1, "Looked at your calendar \u00b7 3 times"),
            _row(2, "Delete the event \u201cDentist\u201d", undo={"id": DEL, "state": state}),
            _row(
                3,
                HOSTILE,
                undo_note="Can't be undone from here \u2014 ask JARVIS to change or delete it",
                channel="telegram",
            ),
            _row(
                4,
                "Waiting for your OK: Send an email to a@b.com",
                outcome="waiting",
                undo_note="Nothing has happened yet",
            ),
            _row(
                5,
                "Send an email to a@b.com",
                channel="voice",
                offline=True,
                undo_note="Sent \u2014 can't be undone",
            ),
            _row(
                6,
                "Delete the to-do \u201cMilk\u201d",
                undo={"id": GONE, "state": "expired"},
                undo_note="Past the 30 days in Recently deleted \u2014 can't be undone",
            ),
            _row(
                7,
                "You declined: Send an email to c@d.com",
                outcome="declined",
                undo_note="Nothing was done",
            ),
        ]
        return {"day": "today", "items": items, "verified": True, "available": self.available}


@pytest.fixture(scope="module")
def browser() -> Iterator[Any]:
    with sync_playwright() as p:
        b = p.chromium.launch()
        yield b
        b.close()


def _wire(c: Console, fake: FakeActivity) -> None:
    def activity(route: Any) -> None:
        day = "yesterday" if "day=yesterday" in route.request.url else "today"
        body = (
            fake.today()
            if day == "today"
            else {"day": day, "items": [], "verified": True, "available": True}
        )
        if not fake.available:
            body = {"day": day, "items": [], "verified": True, "available": False}
        route.fulfill(status=200, content_type="application/json", body=json.dumps(body))

    def restore(route: Any) -> None:
        fake.restore_calls += 1
        if fake.fail_restore:
            route.fulfill(
                status=502,
                content_type="application/json",
                body=json.dumps(
                    {
                        "error": "restore_failed",
                        "detail": "Couldn't restore it just now. Try again in a moment.",
                    }
                ),
            )
            return
        fake.restored = True
        route.fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps(
                {
                    "status": "restored",
                    "message": "Restored",
                    "undo_id": DEL,
                    "kind": "event",
                    "title": "Dentist",
                }
            ),
        )

    c.page.route("**/v1/activity**", activity)
    c.page.route("**/v1/deleted/*/restore", restore)


def _open(c: Console, fake: FakeActivity) -> None:
    _wire(c, fake)
    c.open()
    c.open_panel("activity")
    c.page.locator("#actPanel").wait_for()
    c.page.evaluate("window.JarvisActivity.refresh()")


def test_rows_in_plain_words_with_undo_only_where_it_can_work(
    browser: Any, server_url: str, token: str
) -> None:
    fake = FakeActivity()
    c = Console(browser, server_url, token, DESKTOP)
    try:
        _open(c, fake)
        rows = c.page.locator("#actList .arow")
        rows.first.wait_for()
        assert rows.count() == 7
        assert (
            rows.nth(0).locator(".awords").text_content()
            == "Looked at your calendar \u00b7 3 times"
        )
        # Undo exists on exactly one row: the delete whose copy is still in Recently deleted
        assert c.page.locator("#actList [data-act=undo]").count() == 1
        assert rows.nth(1).locator("[data-act=undo]").count() == 1
        # every other row says why
        assert "Can't be undone from here" in str(rows.nth(2).text_content())
        assert "Nothing has happened yet" in str(rows.nth(3).text_content())
        assert "Sent" in str(rows.nth(4).text_content())
        assert "Past the 30 days" in str(rows.nth(5).text_content())
        assert "Nothing was done" in str(rows.nth(6).text_content())
        # chips
        assert "Telegram" in str(rows.nth(2).locator(".ahead").text_content())
        head = str(rows.nth(4).locator(".ahead").text_content())
        assert "Voice" in head and "Offline" in head
        # hostile words are text
        assert rows.nth(2).locator(".awords").text_content() == HOSTILE
        assert c.page.locator("#actList img").count() == 0
        assert c.page.evaluate("window.__pwned") is None
        assert c.csp_violations() == [] and c.errors == []
    finally:
        c.close()


def test_undo_calls_the_restore_route_once_and_the_row_says_restored(
    browser: Any, server_url: str, token: str
) -> None:
    fake = FakeActivity()
    c = Console(browser, server_url, token, DESKTOP)
    try:
        _open(c, fake)
        c.page.locator("#actList [data-act=undo]").click()
        c.page.locator("#actList .apill", has_text="Restored").wait_for()
        assert fake.restore_calls == 1
        assert c.page.locator("#actList [data-act=undo]").count() == 0
        assert c.page.locator("#actList .awords", has_text="You restored the event").count() == 1
        assert c.errors == []
    finally:
        c.close()


def test_a_failed_undo_says_why_and_can_be_retried(
    browser: Any, server_url: str, token: str
) -> None:
    fake = FakeActivity()
    fake.fail_restore = True
    c = Console(browser, server_url, token, DESKTOP)
    try:
        _open(c, fake)
        c.page.locator("#actList [data-act=undo]").click()
        err = c.page.locator("#actList .lerr")
        err.wait_for()
        assert "Try again" in str(err.text_content())
        assert c.page.locator("#actList [data-act=undo]").is_enabled()
        fake.fail_restore = False
        c.page.locator("#actList [data-act=undo]").click()
        c.page.locator("#actList .apill", has_text="Restored").wait_for()
    finally:
        c.close()


def test_yesterday_tab_and_the_full_log_sits_behind_a_button(
    browser: Any, server_url: str, token: str
) -> None:
    fake = FakeActivity()
    c = Console(browser, server_url, token, DESKTOP)
    try:
        _open(c, fake)
        c.page.locator("#actList .arow").first.wait_for()
        assert c.page.locator("#audit").is_hidden()
        c.page.locator("#actLogBtn").click()
        assert c.page.locator("#audit").is_visible()
        assert c.page.locator("#actLogBtn").get_attribute("aria-expanded") == "true"
        c.page.locator('.atab[data-day="yesterday"]').click()
        c.page.locator("#actList .empty", has_text="Nothing from yesterday").wait_for()
        assert c.page.locator('.atab[data-day="yesterday"]').get_attribute("aria-pressed") == "true"
        assert c.page.locator("#auditOk").is_visible()  # the Log verified badge stays in the header
    finally:
        c.close()


def test_a_server_without_activity_says_so_and_keeps_the_raw_log(
    browser: Any, server_url: str, token: str
) -> None:
    fake = FakeActivity()
    fake.available = False
    c = Console(browser, server_url, token, DESKTOP)
    try:
        _open(c, fake)
        c.page.locator("#actList .empty", has_text="doesn't record its activity").wait_for()
        assert c.page.locator("#audit").is_visible()
        assert c.page.locator("#actLogBtn").is_hidden()
    finally:
        c.close()


def test_phone_layout_has_no_sideways_scroll_and_44px_targets(
    browser: Any, server_url: str, token: str
) -> None:
    fake = FakeActivity()
    c = Console(browser, server_url, token, PHONE)
    try:
        _open(c, fake)
        c.page.locator("#actList .arow").first.wait_for()
        assert c.page.evaluate("document.documentElement.scrollWidth <= window.innerWidth + 1")
        box = c.page.locator("#actList [data-act=undo]").bounding_box()
        assert box is not None and box["height"] >= 43
        assert c.csp_violations() == [] and c.errors == []
    finally:
        c.close()
