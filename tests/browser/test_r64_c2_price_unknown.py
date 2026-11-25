# tests/browser/test_r64_c2_price_unknown.py — R6.4 D9 follow-up (row 393, builder C2) in a real
# browser: a reply from a model with no known price says "price unknown" in its meta line (never
# ₹0, never $), and Vitals' "This conversation" says so beside the conversation's rupees, also for
# a conversation opened again. A priced reply keeps its "≈ ₹" figure.
# /v1/chat and /v1/sessions/{id} are answered by the test (page.route).
from __future__ import annotations

import json
from collections.abc import Iterator
from typing import Any

import pytest
from test_console import DESKTOP, Console  # same directory (pytest prepend import)

_pw = pytest.importorskip("playwright.sync_api")
sync_playwright = _pw.sync_playwright

pytestmark = pytest.mark.browser

COST = "() => document.querySelector('#sCost').textContent"


def _reply(*, unpriced: bool, calls: int, cost: float, total: float) -> dict[str, Any]:
    """A ChatResponse as POST /v1/chat answers it (src/jarvis/core/models.py)."""
    return {
        "session_id": "sess_price",
        "reply": "Here you are, Sir.",
        "tool_calls": 0,
        "pending_approvals": [],
        "trace_id": "t1",
        "model": "llama-local-70b" if unpriced else "claude-sonnet-5-5",
        "brain": "mock",
        "usage": {"input_tokens": 10, "output_tokens": 5},
        "cost_usd": cost / 95.24,
        "cost_inr": cost,
        "total_cost_usd": total / 95.24,
        "total_cost_inr": total,
        "unpriced": unpriced,
        "unpriced_calls": calls,
        "latency_ms": 120,
        "turn_count": 2,
        "memory_used": [],
        "sources": [],
    }


def _json(route: Any, body: Any) -> None:
    route.fulfill(status=200, content_type="application/json", body=json.dumps(body))


@pytest.fixture(scope="module")
def browser() -> Iterator[Any]:
    with sync_playwright() as p:
        b = p.chromium.launch()
        yield b
        b.close()


def _console(browser: Any, url: str, token: str) -> Console:
    c = Console(browser, url, token, DESKTOP)
    c.page.add_init_script("try { localStorage.removeItem('jarvis_session'); } catch (_) {}")
    return c


def _meta(c: Console) -> str:
    meta = c.page.locator(".row.jarvis .meta").last
    meta.wait_for()
    return str(meta.text_content())


def test_an_unpriced_reply_says_price_unknown_never_rupees_zero(
    browser: Any, server_url: str, token: str
) -> None:
    c = _console(browser, server_url, token)
    try:
        body = _reply(unpriced=True, calls=1, cost=0.0, total=0.0)
        c.page.route("**/v1/chat", lambda r: _json(r, body))
        c.open()
        c.send("what does this cost?")
        spans = c.page.locator(".row.jarvis .meta").last.locator("span").all_text_contents()
        assert "price unknown" in spans  # its own meta item, in the meta row's plain style
        text = _meta(c)
        assert "₹0" not in text and "$" not in text
        c.page.wait_for_function(f"{COST} === 'Price unknown'")
        assert c.errors == [] and c.csp_violations() == []
    finally:
        c.close()


def test_a_mixed_conversation_shows_its_rupees_and_price_unknown(
    browser: Any, server_url: str, token: str
) -> None:
    c = _console(browser, server_url, token)
    try:
        body = _reply(unpriced=False, calls=2, cost=0.4667, total=0.9714)
        c.page.route("**/v1/chat", lambda r: _json(r, body))
        c.open()
        c.send("and on Claude?")
        text = _meta(c)
        assert "≈ ₹0.47" in text and "price unknown" not in text  # this reply has a price
        c.page.wait_for_function(f"{COST} === '≈ ₹0.97 + price unknown'")
        assert c.errors == [] and c.csp_violations() == []
    finally:
        c.close()


def test_a_priced_reply_is_unchanged(browser: Any, server_url: str, token: str) -> None:
    c = _console(browser, server_url, token)
    try:
        body = _reply(unpriced=False, calls=0, cost=0.4667, total=0.9714)
        c.page.route("**/v1/chat", lambda r: _json(r, body))
        c.open()
        c.send("cost?")
        assert "≈ ₹0.47" in _meta(c)
        c.page.wait_for_function(f"{COST} === '≈ ₹0.97'")
        assert c.errors == []
    finally:
        c.close()


def test_a_reopened_conversation_says_price_unknown(
    browser: Any, server_url: str, token: str
) -> None:
    session = {
        "id": "sess_back",
        "user_id": "owner",
        "created_at": "2026-11-25T09:00:00Z",
        "updated_at": "2026-11-25T09:05:00Z",
        "turns": [
            {"role": "user", "content": "hello", "created_at": "2026-11-25T09:00:00Z"},
            {
                "role": "assistant",
                "content": "Hello, Sir.",
                "model": "llama-local-70b",
                "created_at": "2026-11-25T09:00:01Z",
                "unpriced": True,
            },
        ],
        "metadata": {},
        "total_cost_usd": 0.0,
        "total_cost_inr": 0.0,
        "unpriced_calls": 1,
        "drafts": [],
    }
    c = Console(browser, server_url, token, DESKTOP)
    try:
        c.page.add_init_script(
            "try { localStorage.setItem('jarvis_session', 'sess_back'); } catch (_) {}"
        )
        c.page.route("**/v1/sessions/sess_back", lambda r: _json(r, session))
        c.open()
        c.page.locator(".row.jarvis .bubble").first.wait_for()
        c.page.wait_for_function(f"{COST} === 'Price unknown'")
        assert c.errors == [] and c.csp_violations() == []
    finally:
        c.close()
