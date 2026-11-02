# tests/browser/test_deleted.py — slice 11 D1 in a real browser: the Undo chip under a reply that
# deleted something (title filled in as text, restores, then says "Restored"), the "Recently
# deleted" section in the Approvals panel (collapsed above Permissions, Restore buttons, restored
# rows, plain errors), hostile titles shown as text only, and a 390 px phone with no horizontal
# scroll.
# /v1/chat, /v1/deleted and its restore route are answered by the test (page.route).
from __future__ import annotations

import json
from collections.abc import Iterator
from typing import Any

import pytest
from test_console import DESKTOP, PHONE, Console  # same directory (pytest prepend import)

_pw = pytest.importorskip("playwright.sync_api")
sync_playwright = _pw.sync_playwright

pytestmark = pytest.mark.browser

HOSTILE = '<img src=x onerror="window.__pwned=1">Dentist'
DENTIST = "del_0123456789abcdef0123"
TODO = "del_fedcba9876543210fedc"


def _item(iid: str, kind: str, title: str, restored: bool = False) -> dict[str, Any]:
    return {
        "id": iid,
        "kind": kind,
        "title": title,
        "deleted_at": "2026-11-02T09:00:00Z",
        "expires_at": "2026-12-02T09:00:00Z",
        "restored": restored,
    }


def _reply(undo: list[Any]) -> dict[str, Any]:
    return {
        "session_id": "sess_undo",
        "reply": "Deleted, Sir. Say undo if that was a mistake.",
        "tool_calls": 1,
        "pending_approvals": [],
        "trace_id": "t1",
        "model": "mock-balanced",
        "brain": "mock",
        "usage": {"input_tokens": 10, "output_tokens": 5},
        "cost_usd": 0.0,
        "cost_inr": 0.0,
        "total_cost_usd": 0.0,
        "total_cost_inr": 0.0,
        "latency_ms": 120,
        "turn_count": 2,
        "memory_used": [],
        "sources": [],
        "undo": undo,
    }


class FakeBin:
    """/v1/deleted and /v1/deleted/{id}/restore, answered in the page."""

    def __init__(self, items: list[dict[str, Any]], fail: dict[str, tuple[int, dict[str, str]]]):
        self.items, self.fail, self.restores = items, fail, []

    def handle(self, route: Any) -> None:
        req = route.request
        if req.method == "GET":
            body = {"items": self.items, "kept_days": 30}
            route.fulfill(status=200, content_type="application/json", body=json.dumps(body))
            return
        iid = req.url.rsplit("/", 2)[-2]
        self.restores.append(iid)
        if iid in self.fail:
            status, body = self.fail[iid]
            route.fulfill(status=status, content_type="application/json", body=json.dumps(body))
            return
        for it in self.items:
            if it["id"] == iid:
                it["restored"] = True
        out = {"status": "restored", "message": "Restored the event.", "title": "x", "undo_id": iid}
        route.fulfill(status=200, content_type="application/json", body=json.dumps(out))


@pytest.fixture(scope="module")
def browser() -> Iterator[Any]:
    with sync_playwright() as p:
        b = p.chromium.launch()
        yield b
        b.close()


def _console(
    browser: Any, url: str, token: str, viewport: dict[str, int], fake: FakeBin
) -> Console:
    c = Console(browser, url, token, viewport)
    c.page.add_init_script(
        "try { localStorage.removeItem('jarvis_session');"
        " localStorage.removeItem('jarvis_deleted_open'); } catch (_) {}"
    )
    c.page.route("**/v1/deleted**", fake.handle)
    return c


@pytest.fixture
def bin_() -> FakeBin:
    items = [_item(DENTIST, "event", HOSTILE), _item(TODO, "task", "Pay electricity bill")]
    items.append(_item("del_00000000000000000001", "task", "Old one", restored=True))
    return FakeBin(items, {})


def test_undo_chip_under_a_reply_restores_and_says_so(
    browser: Any, server_url: str, token: str, bin_: FakeBin
) -> None:
    c = _console(browser, server_url, token, DESKTOP, bin_)
    try:
        refs = [{"undo_id": DENTIST, "kind": "event"}, {"undo_id": "evil<b>", "kind": "event"}]
        body = json.dumps(_reply(refs))
        c.page.route(
            "**/v1/chat",
            lambda r: r.fulfill(status=200, content_type="application/json", body=body),
        )
        c.open()
        c.send("Delete my dentist appointment")
        chip = c.page.locator(".row.jarvis .meta .uchip")
        chip.first.wait_for()
        assert chip.count() == 1  # the malformed ref is dropped
        c.page.wait_for_function(
            "() => document.querySelector('.uchip .ut').textContent.length > 0"
        )
        assert chip.locator(".ut").text_content() == HOSTILE  # text, never markup
        assert c.page.locator(".row.jarvis img").count() == 0
        assert "Dentist" in (chip.get_attribute("aria-label") or "")
        chip.click()
        c.page.wait_for_function("() => document.querySelector('.uchip').dataset.state === 'done'")
        assert chip.locator(".uw").text_content() == "Restored"
        assert chip.get_attribute("aria-disabled") == "true"
        assert bin_.restores == [DENTIST]
        chip.dispatch_event("click")  # restored (aria-disabled): a second click does nothing
        c.page.wait_for_timeout(150)
        assert bin_.restores == [DENTIST]
        assert c.page.evaluate("window.__pwned === undefined")
        assert c.csp_violations() == [] and c.errors == []
    finally:
        c.close()


def test_recently_deleted_section_lists_and_restores(
    browser: Any, server_url: str, token: str, bin_: FakeBin
) -> None:
    c = _console(browser, server_url, token, DESKTOP, bin_)
    try:
        c.open()
        c.open_panel("approvals")
        btn = c.page.locator("#delSetBtn")
        btn.wait_for()
        order = c.page.evaluate(
            """() => { const b = document.querySelector('#p-approvals .pbody');
                 const kids = [...b.children].map(n => n.id); return kids; }"""
        )
        assert order.index("approvals") < order.index("delSet") < order.index("permSet")
        assert btn.get_attribute("aria-expanded") == "false"
        c.page.wait_for_function("() => document.querySelector('#delSum').textContent.length > 0")
        assert "2 items you can restore" in (c.page.locator("#delSum").text_content() or "")
        btn.click()
        rows = c.page.locator("#delList .drow")
        rows.first.wait_for()
        assert rows.count() == 3
        assert rows.nth(0).locator("b").text_content() == HOSTILE
        assert "Event" in (rows.nth(0).locator("small").text_content() or "")
        assert rows.nth(2).locator(".dpill").text_content() == "Restored"
        assert rows.nth(2).locator("button").count() == 0
        rows.nth(1).locator("button", has_text="Restore").click()
        c.page.locator("#delList .drow").nth(1).locator(".dpill").wait_for()
        assert bin_.restores == [TODO]
        assert "Restored" in (c.page.locator("#delSet .bnote").text_content() or "")
        assert c.page.locator(".row.jarvis img").count() == 0
        assert c.csp_violations() == [] and c.errors == []
    finally:
        c.close()


def test_a_failed_restore_says_why_in_plain_words(
    browser: Any, server_url: str, token: str, bin_: FakeBin
) -> None:
    bin_.fail[DENTIST] = (
        410,
        {"error": "expired", "detail": "That was deleted more than 30 days ago."},
    )
    c = _console(browser, server_url, token, DESKTOP, bin_)
    try:
        c.open()
        c.open_panel("approvals")
        c.page.locator("#delSetBtn").click()
        row = c.page.locator("#delList .drow").first
        row.wait_for()
        row.locator("button").click()
        c.page.locator("#delList .drow .lerr:not(:empty)").first.wait_for()
        text = c.page.locator("#delList .lerr:not(:empty)").first.text_content() or ""
        assert "30 days" in text and "expired" not in text
    finally:
        c.close()


def test_phone_fits_without_horizontal_scroll(
    browser: Any, server_url: str, token: str, bin_: FakeBin
) -> None:
    c = _console(browser, server_url, token, PHONE, bin_)
    try:
        c.open()
        c.open_panel("approvals")
        c.page.locator("#delSetBtn").click()
        c.page.locator("#delList .drow").first.wait_for()
        width = c.page.evaluate("() => document.documentElement.scrollWidth")
        assert width <= PHONE["width"]
        h = c.page.locator("#delList .drow button").first.bounding_box()
        assert h is not None and h["height"] >= 44
        assert c.errors == []
    finally:
        c.close()
