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
        self.removed: list[str] = []

    def handle(self, route: Any) -> None:
        req = route.request
        if req.method == "GET":
            body = {"items": self.items, "kept_days": 30}
            route.fulfill(status=200, content_type="application/json", body=json.dumps(body))
            return
        if req.method == "DELETE":  # "Remove now"
            iid = req.url.rsplit("/", 1)[-1]
            self.removed.append(iid)
            self.items = [it for it in self.items if it["id"] != iid]
            out = json.dumps({"removed": True, "id": iid})
            route.fulfill(status=200, content_type="application/json", body=out)
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
        assert rows.nth(2).locator('[data-act="restore"]').count() == 0
        rows.nth(1).locator('[data-act="restore"]').click()
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
        row.locator('[data-act="restore"]').click()
        c.page.locator("#delList .drow .lerr:not(:empty)").first.wait_for()
        text = c.page.locator("#delList .lerr:not(:empty)").first.text_content() or ""
        assert "30 days" in text and "expired" not in text
    finally:
        c.close()


def _reply_route(c: Console, refs: list[dict[str, str]]) -> None:
    body = json.dumps(_reply(refs))
    c.page.route(
        "**/v1/chat", lambda r: r.fulfill(status=200, content_type="application/json", body=body)
    )


@pytest.mark.parametrize(
    ("status", "body", "words"),
    [
        (410, {"error": "expired", "detail": "That was deleted more than 30 days ago."}, "30 days"),
        (409, {"error": "busy", "detail": "That is being restored right now."}, "right now"),
        (502, {"error": "restore_failed", "detail": "Google's service is unavailable."}, "Google"),
    ],
)
def test_a_failed_undo_says_why_next_to_the_chip(
    browser: Any,
    server_url: str,
    token: str,
    bin_: FakeBin,
    status: int,
    body: dict[str, str],
    words: str,
) -> None:
    """Slice 11 fix: not a tooltip — visible words next to the chip, in an aria-live region."""
    bin_.fail[DENTIST] = (status, body)
    c = _console(browser, server_url, token, DESKTOP, bin_)
    try:
        _reply_route(c, [{"undo_id": DENTIST, "kind": "event"}])
        c.open()
        c.send("Delete my dentist appointment")
        chip = c.page.locator(".row.jarvis .meta .uchip").first
        chip.wait_for()
        chip.click()
        line = c.page.locator(".row.jarvis .meta .umsg:not(:empty)")
        line.wait_for()
        text = line.text_content() or ""
        assert words in text and body["error"] not in text
        assert line.get_attribute("aria-live") == "polite" and line.is_visible()
        assert chip.get_attribute("aria-describedby") == line.get_attribute("id")
        assert chip.locator(".uw").text_content() == "Undo"  # can be tried again
        assert c.csp_violations() == []  # (the browser logs the 4xx itself)
    finally:
        c.close()


def test_keyboard_focus_stays_in_the_row_after_restore(
    browser: Any, server_url: str, token: str, bin_: FakeBin
) -> None:
    c = _console(browser, server_url, token, DESKTOP, bin_)
    try:
        c.open()
        c.open_panel("approvals")
        c.page.locator("#delSetBtn").click()
        go = c.page.locator(f'#delList .drow[data-id="{TODO}"] [data-act="restore"]')
        go.wait_for()
        go.focus()
        c.page.keyboard.press("Enter")
        c.page.locator(f'#delList .drow[data-id="{TODO}"] .dpill').wait_for()
        inside = c.page.evaluate(
            f"""() => {{ const a = document.activeElement;
                 return !!a && !!a.closest('.drow[data-id="{TODO}"]'); }}"""
        )
        assert inside, "focus fell out of the list after Restore"
        assert bin_.restores == [TODO]
    finally:
        c.close()


def test_remove_now_asks_once_then_removes_the_copy(
    browser: Any, server_url: str, token: str, bin_: FakeBin
) -> None:
    c = _console(browser, server_url, token, DESKTOP, bin_)
    try:
        c.open()
        c.open_panel("approvals")
        c.page.locator("#delSetBtn").click()
        rm = c.page.locator(f'#delList .drow[data-id="{TODO}"] [data-act="remove"]')
        rm.wait_for()
        assert rm.text_content() == "Remove now"
        rm.click()
        assert rm.text_content() == "Remove for good?" and bin_.removed == []
        rm.click()
        c.page.wait_for_function(
            f"() => !document.querySelector('#delList .drow[data-id=\"{TODO}\"]')"
        )
        assert bin_.removed == [TODO]
        assert "Removed" in (c.page.locator("#delSet .bnote").text_content() or "")
        assert c.csp_violations() == [] and c.errors == []
    finally:
        c.close()


NOTE_ID = "del_aaaaaaaaaaaaaaaaaaaa"


class PasskeyBin(FakeBin):
    """R2: Remove now on a note answers 403 passkey_required until the DELETE carries a proof."""

    def __init__(self, items: list[dict[str, Any]]) -> None:
        super().__init__(items, {})
        self.bodies: list[Any] = []

    def handle(self, route: Any) -> None:
        req = route.request
        if req.method == "DELETE":
            body = req.post_data_json if req.post_data else None
            self.bodies.append(body)
            if not (body and body.get("proof")):
                out = {"error": "passkey_required", "detail": "Approve this with your passkey."}
                route.fulfill(status=403, content_type="application/json", body=json.dumps(out))
                return
        super().handle(route)


def test_remove_now_on_a_note_asks_for_the_passkey_bound_to_that_entry(
    browser: Any, server_url: str, token: str
) -> None:
    fake = PasskeyBin([_item(NOTE_ID, "note", "A note from 3 Nov")])
    c = _console(browser, server_url, token, DESKTOP, fake)
    try:
        c.open()
        c.page.evaluate(
            "window.__proofs = []; window.JarvisPasskey = { supported: () => true,"
            " message: () => '', prove: async (p, t) => { window.__proofs.push([p, t]);"
            " return { challenge_id: 'c'.repeat(20), credential: {} }; } };"
        )
        c.open_panel("approvals")
        c.page.locator("#delSetBtn").click()
        rm = c.page.locator(f'#delList .drow[data-id="{NOTE_ID}"] [data-act="remove"]')
        rm.wait_for()
        rm.click()
        rm.click()
        c.page.wait_for_function(
            f"() => !document.querySelector('#delList .drow[data-id=\"{NOTE_ID}\"]')"
        )
        assert c.page.evaluate("window.__proofs") == [["privacy_delete", NOTE_ID]]
        assert fake.bodies[0] is None and fake.bodies[1]["proof"]["challenge_id"] == "c" * 20
        assert fake.removed == [NOTE_ID]
        # the 403 the fake answers first is logged by the browser itself; no script error
        assert c.csp_violations() == [] and not [e for e in c.errors if "pageerror" in e]
    finally:
        c.close()


def test_a_stale_sign_in_offers_signing_in_again(browser: Any, server_url: str, token: str) -> None:
    class Stale(FakeBin):
        def handle(self, route: Any) -> None:
            if route.request.method == "DELETE":
                out = {
                    "error": "proof_required",
                    "detail": "Sign in with Google again (within 5 minutes) to remove it for good.",
                    "reason": "reauth",
                }
                route.fulfill(status=403, content_type="application/json", body=json.dumps(out))
                return
            super().handle(route)

    fake = Stale([_item(NOTE_ID, "thing", "A thing you noted")], {})
    c = _console(browser, server_url, token, DESKTOP, fake)
    try:
        c.open()
        c.open_panel("approvals")
        c.page.locator("#delSetBtn").click()
        rm = c.page.locator(f'#delList .drow[data-id="{NOTE_ID}"] [data-act="remove"]')
        rm.wait_for()
        rm.click()
        rm.click()
        row = c.page.locator(f'#delList .drow[data-id="{NOTE_ID}"]')
        row.locator('[data-act="reauth"]').wait_for()
        assert "Sign in with Google again" in str(row.locator(".lerr").text_content())
        assert fake.removed == []
        assert c.csp_violations() == [] and not [e for e in c.errors if "pageerror" in e]
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
