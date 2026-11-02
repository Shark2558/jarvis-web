# tests/browser/test_approve_all.py — "Approve all (n)" in a real Chromium (slice 11 D6), against
# the real app of test_permissions.py (permissions_server.py: everything real but Google's half of
# sign-in and the model). A spoken turn makes three reversible cards and one that can't be undone;
# the button shows only for the three, runs them with one tap and one reply, and the irreversible
# card stays with its own Approve. 0 JS errors and 0 CSP reports.
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
        assert "The card that can't be undone keeps its own Approve." in hint
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
