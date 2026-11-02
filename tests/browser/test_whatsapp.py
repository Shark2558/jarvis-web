# tests/browser/test_whatsapp.py — slice 12 D6/D7 in a real browser: the WhatsApp draft card under a
# reply (name and number, the text as text, the warning line, Open in WhatsApp) — the link is
# exactly https://wa.me/<digits>?text=<encodeURIComponent(text)>, opens a new tab only when the
# owner clicks it, without a referrer; malformed drafts are dropped; a 390 px phone has no
# horizontal scroll. And Integrations' Grant rows for Contacts and YouTube playlists.
# /v1/chat and /v1/integrations are answered by the test (page.route); wa.me never leaves the box.
from __future__ import annotations

import json
import re
from collections.abc import Iterator
from typing import Any
from urllib.parse import quote

import pytest
from test_console import DESKTOP, LINKED, PHONE, Console  # same directory (pytest prepend import)

_pw = pytest.importorskip("playwright.sync_api")
sync_playwright = _pw.sync_playwright

pytestmark = pytest.mark.browser

HOSTILE = '<img src=x onerror="window.__pwned=1">Ravi'
TEXT = "നാളെ കാണാം \U0001f468\u200d\U0001f469\u200d\U0001f467\n(see you) 100% & ok! <b>not bold</b>"
WARN = "This number didn’t come from you or your contacts — check it before you send."


def _link(digits: str, text: str) -> str:
    return f"https://wa.me/{digits}?text={quote(text, safe=chr(33) + '*' + chr(39) + '()')}"


DRAFTS = [
    {"name": HOSTILE, "number": "+919876543210", "text": TEXT,
     "link": _link("919876543210", TEXT), "warning": ""},
    {"name": "", "number": "+442079460958", "text": "Confirmed for Friday",
     "link": _link("442079460958", "Confirmed for Friday"), "warning": WARN},
    {"name": "x", "number": "919876543210", "text": "no plus", "link": "", "warning": ""},
    {"name": "x", "number": "+919876543210", "text": "pay \u202eexe", "link": "", "warning": ""},
    {"name": "x", "number": "+919876543210", "text": "y" * 2001, "link": "", "warning": ""},
]  # fmt: skip


def _reply(drafts: list[Any]) -> dict[str, Any]:
    return {
        "session_id": "sess_wa",
        "reply": "It's ready — tap Open in WhatsApp, then Send.",
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
        "undo": [],
        "whatsapp": drafts,
    }


@pytest.fixture(scope="module")
def browser() -> Iterator[Any]:
    with sync_playwright() as p:
        b = p.chromium.launch()
        yield b
        b.close()


class WaMe:
    """wa.me answered in the browser: records what was opened and with which referrer."""

    def __init__(self) -> None:
        self.opened: list[tuple[str, str | None]] = []

    def handle(self, route: Any) -> None:
        self.opened.append((route.request.url, route.request.headers.get("referer")))
        route.fulfill(status=200, content_type="text/html", body="<p>WhatsApp</p>")


def _console(browser: Any, url: str, token: str, viewport: dict[str, int], wa: WaMe) -> Console:
    c = Console(browser, url, token, viewport)
    c.page.add_init_script("try { localStorage.removeItem('jarvis_session'); } catch (_) {}")
    c.ctx.route(re.compile(r"^https://wa\.me/.*"), wa.handle)
    body = json.dumps(_reply(DRAFTS))
    c.page.route(
        "**/v1/chat", lambda r: r.fulfill(status=200, content_type="application/json", body=body)
    )
    return c


def test_the_draft_card_shows_the_number_and_text_and_opens_only_on_click(
    browser: Any, server_url: str, token: str
) -> None:
    wa = WaMe()
    c = _console(browser, server_url, token, DESKTOP, wa)
    try:
        c.open()
        c.send("WhatsApp Ravi in Malayalam")
        cards = c.page.locator(".row.jarvis .wadraft")
        cards.first.wait_for()
        assert cards.count() == 2  # the three malformed drafts are dropped
        first, second = cards.nth(0), cards.nth(1)
        assert first.locator(".wanum").text_content() == "+91 98765 43210"
        assert first.locator(".waname").text_content() == HOSTILE  # text, never markup
        assert first.locator(".watext").text_content() == TEXT
        assert c.page.locator(".wadraft img, .wadraft b:not(.waname)").count() == 0
        assert first.locator(".wawarn").count() == 0
        assert second.locator(".wawarn").text_content() == WARN
        assert second.locator(".wanum").text_content() == "+442079460958"
        assert "Not sent" in (first.locator(".wastate").text_content() or "")

        link = first.locator("a.waopen")
        assert link.text_content() == "Open in WhatsApp"
        assert link.get_attribute("href") == _link("919876543210", TEXT)
        assert link.get_attribute("target") == "_blank"
        assert link.get_attribute("rel") == "noopener noreferrer"
        assert link.get_attribute("referrerpolicy") == "no-referrer"

        c.page.wait_for_timeout(300)  # nothing opens by itself
        assert len(c.ctx.pages) == 1 and wa.opened == []
        with c.ctx.expect_page() as opened:
            link.click()
        tab = opened.value
        tab.wait_for_load_state()
        assert tab.url == _link("919876543210", TEXT)
        assert wa.opened == [(_link("919876543210", TEXT), None)]  # no referrer sent
        assert c.page.evaluate("window.__pwned === undefined")
        assert c.errors == [] and c.csp_violations() == []
    finally:
        c.close()


def test_on_a_phone_the_card_fits_without_horizontal_scroll(
    browser: Any, server_url: str, token: str
) -> None:
    c = _console(browser, server_url, token, PHONE, WaMe())
    try:
        c.open()
        c.send("WhatsApp Ravi")
        c.page.locator(".row.jarvis .wadraft").first.wait_for()
        wide = c.page.evaluate("document.documentElement.scrollWidth > window.innerWidth")
        assert wide is False
        box = c.page.locator(".wadraft a.waopen").first.bounding_box()
        assert box is not None and box["height"] >= 44  # a thumb-sized target
        assert c.errors == []
    finally:
        c.close()


# ---- Integrations: Grant rows for Contacts and YouTube playlists (D7) ----------------------------


def _integrations(console: Console, google: dict[str, Any]) -> None:
    body = json.dumps({"google": google})
    console.page.route(
        "**/v1/integrations",
        lambda r: r.fulfill(status=200, content_type="application/json", body=body),
    )


@pytest.fixture
def console(browser: Any, server_url: str, token: str) -> Iterator[Console]:
    c = Console(browser, server_url, token, DESKTOP)
    yield c
    c.close()


@pytest.mark.parametrize(
    ("field", "button", "words", "name"),
    [
        ("contacts_granted", "#googleGrantContacts", "Contacts — permission needed", "contacts"),
        ("youtube_granted", "#googleGrantYoutube", "YouTube playlists — permission needed",
         "youtube"),
    ],
)  # fmt: skip
def test_grant_rows_rerun_connect_with_exactly_that_name(
    console: Console, field: str, button: str, words: str, name: str
) -> None:
    went: list[str] = []

    def consent(route: Any) -> None:
        went.append(route.request.url)
        route.fulfill(status=200, content_type="text/plain", body="Google consent")

    google = {**LINKED["google"], "tasks_granted": True, "contacts_granted": True,
              "youtube_granted": True, field: False}  # fmt: skip
    _integrations(console, google)
    console.page.route(re.compile(r".*/connect/google(\?.*)?$"), consent)
    console.open()
    console.open_panel("integrations")
    rows = console.page.locator("#integrations .iopt")
    rows.first.wait_for()
    assert rows.count() == 1 and words in (rows.first.text_content() or "")
    console.page.locator(button).click()
    console.page.wait_for_url(re.compile(rf".*/connect/google\?add={name}$"))
    assert len(went) == 1 and went[0].endswith(f"/connect/google?add={name}")
    assert console.errors == []


def test_every_grant_held_shows_no_rows_and_says_what_it_unlocks(console: Console) -> None:
    google = {**LINKED["google"], "tasks_granted": True, "contacts_granted": True,
              "youtube_granted": True}  # fmt: skip
    _integrations(console, google)
    console.open()
    console.open_panel("integrations")
    row = console.page.locator('#integrations .integ[data-state="linked"]')
    row.wait_for()
    text = row.text_content() or ""
    unlocks = text.split("Unlocks:", 1)[1]
    assert "to-do list" in unlocks and "contacts (read only)" in unlocks
    assert "YouTube playlists (read only)" in unlocks
    assert console.page.locator("#integrations .iopt").count() == 0
    assert console.errors == []
