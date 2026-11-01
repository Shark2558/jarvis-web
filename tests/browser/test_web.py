# tests/browser/test_web.py — slice 10 B in a real browser: the "Sources" row under a reply
# (numbered link chips, https only, punycode host, rel="noopener noreferrer nofollow", new tab, text
# only — never markup), the same row on a restored conversation, the Vitals "Web search" line, and a
# 390 px phone with no horizontal scroll. /v1/chat, /v1/sessions/{id} and /v1/web/usage are
# answered by the test (page.route); everything else is the real app.
from __future__ import annotations

import json
from collections.abc import Iterator
from typing import Any

import pytest
from test_console import DESKTOP, PHONE, Console  # same directory (pytest prepend import)

_pw = pytest.importorskip("playwright.sync_api")
sync_playwright = _pw.sync_playwright

pytestmark = pytest.mark.browser

HOSTILE_TITLE = '<img src=x onerror="window.__pwned=1">Rates held'
SOURCES: list[dict[str, Any]] = [
    {"n": 2, "title": "Monsoon arrives early", "url": "https://www.example.com/a", "domain": "x"},
    {"n": 1, "title": HOSTILE_TITLE, "url": "https://news.example.org/rbi", "domain": "x"},
    {"n": 3, "title": "Bücher", "url": "https://bücher.de/x", "domain": "bücher.de"},
    {"n": 4, "title": "Not https", "url": "http://plain.example/x", "domain": "plain.example"},
    {"n": 5, "title": "Script", "url": "javascript:alert(1)", "domain": "x"},
    {"n": 6, "title": "Userinfo", "url": "https://user:pw@evil.example/", "domain": "x"},
    {"n": 0, "title": "Zero", "url": "https://zero.example/", "domain": "x"},
    {"n": "7", "title": "String n", "url": "https://seven.example/", "domain": "x"},
    "junk",
]


@pytest.fixture(scope="module")
def browser() -> Iterator[Any]:
    with sync_playwright() as p:
        b = p.chromium.launch()
        yield b
        b.close()


def _reply(text: str, sources: list[Any], sid: str = "sess_web_reply") -> dict[str, Any]:
    return {
        "session_id": sid,
        "reply": text,
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
        "sources": sources,
    }


def _route_json(page: Any, pattern: str, body: Any) -> None:
    page.route(
        pattern,
        lambda route: route.fulfill(
            status=200, content_type="application/json", body=json.dumps(body)
        ),
    )


@pytest.fixture
def web(browser: Any, server_url: str, token: str) -> Iterator[Console]:
    c = Console(browser, server_url, token, DESKTOP)
    c.page.add_init_script("try { localStorage.removeItem('jarvis_session'); } catch (_) {}")
    _route_json(
        c.page,
        "**/v1/web/usage",
        {
            "configured": True,
            "month": "2026-11",
            "used": 12,
            "limit": 900,
            "left": 888,
            "reached": False,
            "unreadable": False,
        },
    )
    yield c
    c.close()


def _chips(page: Any) -> list[dict[str, Any]]:
    return list(
        page.evaluate(
            """() => [...document.querySelectorAll('.row.jarvis .wsources a')].map(a => ({
                 n: a.querySelector('b').textContent, domain: a.querySelector('span').textContent,
                 href: a.getAttribute('href'), rel: a.getAttribute('rel'),
                 target: a.getAttribute('target'), title: a.title,
                 policy: a.referrerPolicy, label: a.getAttribute('aria-label') }))"""
        )
    )


def test_sources_row_shows_only_safe_https_chips_as_text(web: Console) -> None:
    _route_json(
        web.page, "**/v1/chat", _reply("Rates held [1], rains early [2], books [3].", SOURCES)
    )
    web.open()
    web.send("what happened?")
    web.page.locator(".row.jarvis .wsources").wait_for()
    chips = _chips(web.page)
    assert [c["n"] for c in chips] == ["1", "2", "3"]  # sorted; bad ones dropped
    assert [c["domain"] for c in chips] == ["news.example.org", "example.com", "xn--bcher-kva.de"]
    for c in chips:
        assert c["href"].startswith("https://")
        assert c["rel"] == "noopener noreferrer nofollow" and c["target"] == "_blank"
        assert c["policy"] == "no-referrer"
        assert "opens in a new tab" in c["label"]
    assert HOSTILE_TITLE in chips[0]["title"]  # shown as text in the tooltip, never markup
    assert web.page.locator(".row.jarvis img").count() == 0
    assert web.page.evaluate("window.__pwned === undefined")
    label = web.page.locator(".row.jarvis .wsources .wslabel").text_content()
    assert label == "Sources"
    assert web.page.locator(".row.jarvis .wsources").get_attribute("aria-label") == "Sources"
    assert web.csp_violations() == [] and web.errors == []


def test_no_row_when_nothing_was_cited(web: Console) -> None:
    _route_json(web.page, "**/v1/chat", _reply("Just chatting, Sir.", []))
    web.open()
    web.send("hello")
    web.page.wait_for_timeout(200)
    assert web.page.locator(".wsources").count() == 0
    assert web.errors == []


def test_a_restored_conversation_shows_its_sources(
    browser: Any, server_url: str, token: str
) -> None:
    c = Console(browser, server_url, token, DESKTOP)
    try:
        c.page.add_init_script(
            "try { localStorage.setItem('jarvis_session', 'sess_web1'); } catch (_) {}"
        )
        turn = {
            "role": "assistant",
            "content": "Earlier answer [1].",
            "model": "mock-balanced",
            "sources": [SOURCES[1]],
        }
        _route_json(
            c.page,
            "**/v1/sessions/sess_web1",
            {
                "id": "sess_web1",
                "user_id": "owner",
                "turns": [{"role": "user", "content": "earlier question"}, turn],
                "metadata": {},
                "total_cost_inr": 0.0,
            },
        )
        c.open()
        c.page.locator(".sys", has_text="Earlier conversation restored.").wait_for()
        chips = _chips(c.page)
        assert [(x["n"], x["domain"]) for x in chips] == [("1", "news.example.org")]
        assert c.errors == []
    finally:
        c.close()


def test_vitals_says_how_many_web_searches_are_left(web: Console) -> None:
    web.open()
    web.open_panel("vitals")
    line = web.page.locator("#sWeb")
    line.wait_for()
    web.page.wait_for_function("document.getElementById('sWeb').textContent !== '—'")
    assert line.text_content() == "12 of 900 this month"
    assert "$" not in str(line.get_attribute("title")) and "₹0" in str(line.get_attribute("title"))
    assert web.errors == []


def test_vitals_says_not_set_up_without_a_key(browser: Any, server_url: str, token: str) -> None:
    c = Console(browser, server_url, token, DESKTOP)
    try:
        c.open()  # the real server has no Tavily key: {configured: false}
        c.open_panel("vitals")
        c.page.wait_for_function("document.getElementById('sWeb').textContent === 'Not set up'")
        assert c.errors == []
    finally:
        c.close()


def test_many_long_sources_fit_a_phone(browser: Any, server_url: str, token: str) -> None:
    c = Console(browser, server_url, token, PHONE)
    try:
        many = [
            {
                "n": i,
                "title": "A very long title " * 5,
                "url": f"https://very-long-subdomain-name-{i}.some-really-long-domain.example/x",
                "domain": "x",
            }
            for i in range(1, 9)
        ]
        _route_json(c.page, "**/v1/chat", _reply("Many [1][2][3][4][5][6][7][8].", many))
        c.open()
        c.send("many sources please")
        c.page.locator(".row.jarvis .wsources").wait_for()
        assert len(_chips(c.page)) == 8
        overflow = c.page.evaluate(
            "document.documentElement.scrollWidth - document.documentElement.clientWidth"
        )
        assert overflow <= 0
        assert c.errors == []
    finally:
        c.close()
