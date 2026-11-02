# tests/browser/test_approve_all.py — "Approve all (n)" in a real Chromium (slice 11 D6), against
# the real app of test_permissions.py (permissions_server.py: everything real but Google's half of
# sign-in and the model). A spoken turn makes three reversible cards and one that can't be undone;
# the button shows only for the three, runs them with one tap and one reply, and the irreversible
# card stays with its own Approve. 0 JS errors and 0 CSP reports. Review MEDIUM-1 (token server,
# the approvals routes faked in the page): cards the server marks not bulk_ok (a memory write, an
# untyped draft) stay out of the batch; a changed batch holds the button, and the tap sends exactly
# the ids shown.
from __future__ import annotations

import json
import urllib.request
from typing import Any

import pytest
from test_console import DESKTOP, PHONE, Console  # same directory (pytest prepend import)
from test_permissions import TOKEN, _errors, _get, _google_open, browser, perm_url  # noqa: F401

pytest.importorskip("playwright.sync_api")
pytestmark = pytest.mark.browser


def _post(url: str, path: str, body: dict[str, Any]) -> Any:
    req = urllib.request.Request(
        url + path,
        data=json.dumps(body).encode(),
        headers={"Authorization": f"Bearer {TOKEN}", "Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=10) as r:
        return json.loads(r.read())


def _ran(url: str, tool: str) -> int:
    entries = _get(url, "/v1/audit?limit=100")["entries"]
    return [e["outcome"] for e in entries if e["tool"] == tool].count("executed")


@pytest.mark.parametrize("viewport", [DESKTOP, PHONE], ids=["desktop", "phone"])
def test_approve_all_runs_the_undoable_cards_and_leaves_the_other(
    browser: Any,  # noqa: F811
    perm_url: str,  # noqa: F811
    viewport: dict[str, int],
) -> None:
    before = _ran(perm_url, "create_reminder")
    made = _post(perm_url, "/v1/chat", {"message": "batch: 3", "channel": "voice"})
    risks = [p["tool_risk"] for p in made["pending_approvals"]]
    assert risks == ["reversible"] * 3 + ["irreversible"]
    c = Console(browser, perm_url, TOKEN, viewport)
    try:
        _google_open(c)
        if viewport is PHONE:  # on a desktop, new cards open the panel by themselves
            c.open_panel("approvals")
        page = c.page
        page.locator("#p-approvals").wait_for(state="visible")
        page.locator("#approvals .approval").nth(3).wait_for()
        btn = page.locator("#approveAllBtn")
        btn.wait_for(state="visible")
        assert btn.text_content() == "Approve all (3)"
        hint = str(page.locator("#approveAllHint").text_content())
        assert "1 needs you one by one." in hint  # the send card keeps its own Approve
        # the bar sits above the cards, inside the panel, with no sideways scroll on a phone
        box, first = page.locator("#approveAll").bounding_box(), page.locator(".approval").first
        assert box is not None and box["y"] < (first.bounding_box() or {"y": 0})["y"]
        assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")

        btn.click()
        # the conversation opens (its first reply), then ONE reply for the whole batch; the button
        # sends only the cards that can be undone, so the server never even sees the other one
        page.locator(".row.jarvis .bubble", has_text="Noted, Sir.").nth(1).wait_for()
        page.locator("#approveAll").wait_for(state="hidden")
        assert page.locator(".row.jarvis .bubble").count() == 2
        cards = page.locator("#approvals .approval")
        assert cards.count() == 1
        assert "send message" in str(cards.first.locator(".title").text_content())
        assert _ran(perm_url, "create_reminder") == before + 3
        assert _ran(perm_url, "send_message") == 0  # never through Approve all
        assert c.csp_violations() == [] and _errors(c) == []
    finally:
        c.close()
        for p in _get(perm_url, "/v1/approvals"):  # leave nothing waiting for the next case
            _post(perm_url, f"/v1/approvals/{p['id']}/decline", {"session_id": p["session_id"]})


# ---- review MEDIUM-1: cards the owner reviews one by one; the batch sent is the one shown -------

SID = "sess_review0000000000"


def _card(n: int, tool: str, reason: str, bulk: bool) -> dict[str, Any]:
    return {
        "id": f"card{n}", "tool": tool, "summary": f"{tool.replace('_', ' ')} {n}",
        "arguments": {"n": n}, "risk": "irreversible", "expires_at": "2030-01-01T00:00:00Z",
        "session_id": SID, "tool_risk": "reversible", "passkey_required": False,
        "reason": reason, "bulk_ok": bulk,
    }  # fmt: skip


REPLY = {
    "session_id": SID, "reply": "Both events are in, Sir.", "trace_id": "t", "model": "mock",
    "brain": "mock", "usage": {}, "cost_usd": 0, "latency_ms": 5, "turn_count": 2,
    "tool_calls": 3, "pending_approvals": [], "results": [],
}  # fmt: skip


def _json(route: Any, body: Any) -> None:
    route.fulfill(status=200, content_type="application/json", body=json.dumps(body))


def test_review_cards_stay_out_and_the_batch_sent_is_the_one_shown(
    browser: Any,  # noqa: F811
    server_url: str,
    token: str,
) -> None:
    """After a mail: 2 calendar cards are one tap; the memory and the untyped draft keep their own
    Approve. A card arriving changes the label at once and holds the button ~1.5 s; a tap in that
    moment sends nothing; the tap after sends exactly the 3 ids on the button."""
    cards = [
        _card(1, "calendar_create_event", "untrusted_context", True),
        _card(2, "memory_save", "untrusted_context", False),
        _card(3, "calendar_create_event", "untrusted_context", True),
        _card(4, "gmail_create_draft", "draft_recipient", False),
    ]
    sent: list[dict[str, Any]] = []
    c = Console(browser, server_url, token, DESKTOP)
    page = c.page
    page.route("**/v1/approvals", lambda r: _json(r, cards))
    page.route(f"**/v1/sessions/{SID}", lambda r: _json(
        r, {"id": SID, "turns": [], "metadata": {}, "total_cost_inr": 0}))  # fmt: skip

    def approve_all(route: Any) -> None:
        sent.append(json.loads(route.request.post_data or "{}"))
        _json(route, REPLY)

    page.route("**/v1/approvals/approve-all", approve_all)
    try:
        c.open()  # on a desktop, waiting cards open the Approvals panel by themselves
        page.locator("#p-approvals").wait_for(state="visible")
        page.locator("#approvals .approval").nth(3).wait_for()
        btn = page.locator("#approveAllBtn")
        btn.wait_for(state="visible")
        assert btn.text_content() == "Approve all (2)"
        assert "2 need you one by one." in str(page.locator("#approveAllHint").text_content())
        for i in (1, 3):  # the memory and the draft keep their own Approve
            assert page.locator("#approvals .approval").nth(i).locator(".approve").is_enabled()
        page.locator("#approveAllBtn:not([disabled])").wait_for()  # the first showing's hold

        more = [*cards, _card(5, "reminder_add", "untrusted_context", True)]
        page.evaluate(
            "cards => document.dispatchEvent(new CustomEvent('jarvis:approvals',"
            " { detail: { count: cards.length, fresh: true, cards } }))",
            more,
        )
        assert btn.text_content() == "Approve all (3)" and btn.is_disabled()
        page.evaluate("document.getElementById('approveAllBtn').click()")  # a tap in the hold
        page.wait_for_timeout(300)
        assert sent == []
        btn.click()  # Playwright waits until it is enabled again
        page.locator(".row.jarvis .bubble", has_text="Both events are in, Sir.").wait_for()
        assert sent == [{"session_id": SID, "ids": ["card1", "card3", "card5"]}]
        assert c.csp_violations() == [] and c.errors == []
    finally:
        c.close()
