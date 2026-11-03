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
from pathlib import Path
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


WA = "whatsapp"  # a draft's kind in ChatResponse.cards
# ChatResponse.cards: one list for every card under a reply; console-whatsapp.js draws only its kind
PLACE = {"kind": "places", "attribution": "Google Maps", "query": "cafe",
         "items": [{"name": "Cafe", "address": "1 MG Road", "url": "https://maps.google.com/?cid=1",
                    "place_id": "ChIJone"}]}  # fmt: skip
DRAFTS = [
    PLACE,
    {"kind": WA, "name": HOSTILE, "number": "+919876543210", "text": TEXT,
     "link": _link("919876543210", TEXT), "warning": ""},
    {"kind": WA, "name": "", "number": "+442079460958", "text": "Confirmed for Friday",
     "link": _link("442079460958", "Confirmed for Friday"), "warning": WARN},
    {"kind": WA, "name": "x", "number": "919876543210", "text": "no plus", "link": "",
     "warning": ""},
    {"kind": WA, "name": "x", "number": "+919876543210", "text": "pay \u202eexe", "link": "",
     "warning": ""},
    {"kind": WA, "name": "x", "number": "+919876543210", "text": "y" * 2001, "link": "",
     "warning": ""},
    {"name": "no kind", "number": "+919876543210", "text": "not a draft card", "link": "",
     "warning": ""},
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
        "cards": drafts,
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
        assert cards.count() == 2  # the three malformed drafts and the kind-less one are dropped
        assert c.page.locator(".row.jarvis .mcards .mcard").count() == 1  # the Maps card, beside
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


@pytest.mark.parametrize(
    ("field", "avail"),
    [("contacts_granted", "contacts_available"), ("youtube_granted", "youtube_available")],
)
def test_a_grant_that_is_not_available_shows_no_row(
    console: Console, field: str, avail: str
) -> None:
    """Review C7: no YouTube tools on this server (no API key), or the row set to Never."""
    google = {**LINKED["google"], "tasks_granted": False, "contacts_granted": True,
              "youtube_granted": True, field: False, avail: False}  # fmt: skip
    _integrations(console, google)
    console.open()
    console.open_panel("integrations")
    rows = console.page.locator("#integrations .iopt")
    rows.first.wait_for()
    assert rows.count() == 1  # the to-do row only: the unavailable one is not offered
    assert "To-do list" in (rows.first.text_content() or "")
    assert console.errors == []


def test_a_held_grant_switched_off_is_not_listed_in_unlocks(console: Console) -> None:
    google = {**LINKED["google"], "tasks_granted": True, "contacts_granted": True,
              "youtube_granted": True, "contacts_available": False}  # fmt: skip
    _integrations(console, google)
    console.open()
    console.open_panel("integrations")
    row = console.page.locator('#integrations .integ[data-state="linked"]')
    row.wait_for()
    unlocks = (row.text_content() or "").split("Unlocks:", 1)[1]
    assert "to-do list" in unlocks and "contacts" not in unlocks
    assert console.errors == []


# ---- review S3 / S5 / S7 / S8: whole text, assumed country, hint, isolated number --------------

LONG = "\n".join(["Bank details below"] + [f"line {i}: " + "x" * 60 for i in range(13)])
RTL = "\u05e8\u05d1\u05d9"  # a Hebrew name: right-to-left


def _draft(**over: Any) -> dict[str, Any]:
    """A draft card as the server makes it: its link is wa_link(number, text) unless given."""
    base = {"kind": WA, "name": "", "number": "+919876543210", "text": "hi", "warning": ""}
    d = {**base, **over}
    d.setdefault("link", _link(str(d["number"]).lstrip("+"), str(d["text"])))
    return d


def _console_with(browser: Any, url: str, token: str, drafts: list[Any]) -> Console:
    c = Console(browser, url, token, DESKTOP)
    c.page.add_init_script("try { localStorage.removeItem('jarvis_session'); } catch (_) {}")
    body = json.dumps(_reply(drafts))
    c.page.route(
        "**/v1/chat", lambda r: r.fulfill(status=200, content_type="application/json", body=body)
    )
    return c


def test_a_long_draft_shows_every_line_without_a_scroll_box_and_says_how_many(
    browser: Any, server_url: str, token: str
) -> None:
    c = _console_with(browser, server_url, token, [_draft(text=LONG, name="Ravi")])
    try:
        c.open()
        c.send("WhatsApp Ravi the details")
        card = c.page.locator(".row.jarvis .wadraft").first
        card.wait_for()
        assert card.locator(".walines").text_content() == "14 lines"
        text = card.locator(".watext")
        assert text.text_content() == LONG
        fits = text.evaluate("el => el.scrollHeight <= el.clientHeight + 1")
        assert fits is True  # no inner scroll box: every line is on screen in the card
        assert text.evaluate("el => getComputedStyle(el).overflowY") == "visible"
        assert c.errors == []
    finally:
        c.close()


def test_the_hint_says_who_nothing_is_sent_to_and_what_opening_does(
    browser: Any, server_url: str, token: str
) -> None:
    drafts = [_draft(name="Ravi Kumar"), _draft(number="+442079460958")]
    c = _console_with(browser, server_url, token, drafts)
    try:
        c.open()
        c.send("WhatsApp them")
        cards = c.page.locator(".row.jarvis .wadraft")
        cards.nth(1).wait_for()
        first = cards.nth(0).locator(".wahint").text_content() or ""
        assert "Nothing is sent to Ravi Kumar until you press Send in WhatsApp." in first
        assert "Opening the link hands this text to WhatsApp." in first
        second = cards.nth(1).locator(".wahint").text_content() or ""
        assert "Nothing is sent to +442079460958 until you press Send in WhatsApp." in second
        assert cards.nth(0).locator(".walines").count() == 0  # a short text: no count
    finally:
        c.close()


def test_an_assumed_country_is_shown_and_the_number_is_isolated_from_a_rtl_name(
    browser: Any, server_url: str, token: str
) -> None:
    drafts = [_draft(name=RTL, assumed="Assumed India (+91)"), _draft(number="+442079460958")]
    c = _console_with(browser, server_url, token, drafts)
    try:
        c.open()
        c.send("WhatsApp him")
        cards = c.page.locator(".row.jarvis .wadraft")
        cards.nth(1).wait_for()
        assert cards.nth(0).locator(".waassumed").text_content() == "Assumed India (+91)"
        assert cards.nth(1).locator(".waassumed").count() == 0
        num = cards.nth(0).locator(".wanum")
        style = num.evaluate(
            "el => [getComputedStyle(el).unicodeBidi, getComputedStyle(el).direction]"
        )
        assert style == ["isolate", "ltr"]
        assert num.text_content() == "+91 98765 43210"
        assert c.errors == []
    finally:
        c.close()


@pytest.mark.parametrize(
    "text",
    [
        "hi\u3164there",  # a Hangul filler: the server would have stripped it
        "hi\u2800",  # braille blank
        "a\n\n\n\nb",  # more than two blank lines in a row
        "trailing   \nspaces",  # spaces at the end of a line
        "\ufe0fstart",  # a variation selector with nothing before it
    ],
)
def test_a_draft_the_server_would_have_cleaned_is_dropped(
    browser: Any, server_url: str, token: str, text: str
) -> None:
    c = _console_with(browser, server_url, token, [_draft(text=text), _draft(text="ok")])
    try:
        c.open()
        c.send("WhatsApp")
        cards = c.page.locator(".row.jarvis .wadraft")
        cards.first.wait_for()
        assert cards.count() == 1 and cards.first.locator(".watext").text_content() == "ok"
        assert c.page.evaluate("(t) => window.JarvisWhatsApp.clean(t)", text) != text
    finally:
        c.close()


def test_a_card_whose_link_differs_from_its_number_and_text_is_dropped(
    browser: Any, server_url: str, token: str
) -> None:
    """Review FE-7: the server builds the link from the same number and text; a card whose link
    is not exactly that string (here: one character off) was not made by the server, so it is
    dropped rather than shown with a link the console made up."""
    good = _link("919876543210", "ok")
    bad = good[:-1] + "K"  # one character different
    drafts = [_draft(text="ok", link=bad), _draft(text="ok", link=good, name="Kept")]
    c = _console_with(browser, server_url, token, drafts)
    try:
        c.open()
        c.send("WhatsApp")
        cards = c.page.locator(".row.jarvis .wadraft")
        cards.first.wait_for()
        assert cards.count() == 1 and cards.first.locator(".waname").text_content() == "Kept"
        assert cards.first.locator("a.waopen").get_attribute("href") == good
        assert c.errors == []
    finally:
        c.close()


ZALGO = "Hi" + "̐" * 120  # 120 combining marks stacked on one letter


def test_stacked_combining_marks_are_dropped_like_the_server_refuses_them(
    browser: Any, server_url: str, token: str
) -> None:
    """Review FE-8: the server refuses a text with more than 4 combining marks (Unicode M*) in a
    row on one base character; the console mirrors that and drops such a card. Four are fine
    (Malayalam and Devanagari stack a few)."""
    four = "a" + "́̂̃̄" + " ok"
    five = "a" + "́̂̃̄̅"
    ml = "ക്ഷേ"  # Malayalam: virama and a vowel sign are marks
    c = _console_with(browser, server_url, token, [])
    try:
        c.open()
        c.page.wait_for_function("!!window.JarvisWhatsApp")

        def kept(text: str) -> int:
            return int(
                c.page.evaluate(
                    "(d) => window.JarvisWhatsApp.normal([d]).length",
                    _draft(text=text, link=_link("919876543210", text)),
                )
            )

        assert kept(ZALGO) == 0
        assert kept(five) == 0
        assert kept("x " + five + " y") == 0
        assert kept(four) == 1 and kept(ml) == 1 and kept("plain") == 1
        assert c.page.evaluate("(t) => window.JarvisWhatsApp.stacked(t)", ZALGO) is True
        assert c.page.evaluate("(t) => window.JarvisWhatsApp.stacked(t)", four) is False
        assert c.errors == []
    finally:
        c.close()


def test_the_card_says_the_character_count_when_it_differs_from_what_you_see(
    browser: Any, server_url: str, token: str
) -> None:
    """Review FE-8: a text whose characters differ from what renders (marks, a family emoji) says
    how many characters WhatsApp gets; a plain text does not."""
    accented = "Café at 5"  # 10 characters, 9 visible
    drafts = [
        _draft(text=accented, link=_link("919876543210", accented), name="Marks"),
        _draft(text="Plain text", link=_link("919876543210", "Plain text"), name="Plain"),
    ]
    c = _console_with(browser, server_url, token, drafts)
    try:
        c.open()
        c.send("WhatsApp")
        cards = c.page.locator(".row.jarvis .wadraft")
        cards.nth(1).wait_for()
        assert cards.nth(0).locator(".wachars").text_content() == "10 characters"
        assert cards.nth(1).locator(".wachars").count() == 0
        assert c.errors == []
    finally:
        c.close()


FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "whatsapp_clean_cases.json"


def test_the_console_cleans_exactly_like_the_server_over_the_shared_fixture(
    browser: Any, server_url: str, token: str
) -> None:
    """Security review SEC-1: the console's clean() gives the server's output for every case of
    tests/fixtures/whatsapp_clean_cases.json, and a card is dropped wherever the server refuses
    the text (only blank, or stacked marks). The fixture's emoji are emoji to the browser's own
    \\p{Extended_Pictographic} AND to the server's table (jarvis.whatsapp.pictographic)."""
    from jarvis.whatsapp.pictographic import extended_pictographic

    cases = json.loads(FIXTURE.read_text(encoding="ascii"))
    c = _console_with(browser, server_url, token, [])
    try:
        c.open()
        c.page.wait_for_function("!!window.JarvisWhatsApp")
        js = """(cases) => cases.map((k) => {
            const W = window.JarvisWhatsApp;
            const out = W.clean(k.in);
            const card = {kind: 'whatsapp', name: '', number: '+919876543210', text: out,
                          link: W.waLink('+919876543210', out), warning: ''};
            return {out, shown: out !== '' && W.normal([card]).length === 1};
        })"""
        got = c.page.evaluate(js, cases)
        for case, res in zip(cases, got, strict=True):
            if case["out"] is None:
                assert not res["shown"], case["why"]
            else:
                assert res["out"] == case["out"], case["why"]
                assert res["shown"], case["why"]
        emoji = sorted({ch for k in cases for ch in k["in"] if ord(ch) >= 0x2000})
        browser_says = c.page.evaluate(
            "(cs) => cs.map((ch) => /^\\p{Extended_Pictographic}$/u.test(ch))", emoji
        )
        assert browser_says == [extended_pictographic(ch) for ch in emoji]
        assert c.errors == []
    finally:
        c.close()


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


# ---- final review fix 9: a reopened conversation gets its drafts back -------------------------


def _turn(role: str, content: str, **over: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "id": f"turn_{role}_{len(content)}",
        "role": role,
        "content": content,
        "blocks": [],
        "created_at": "2026-11-03T00:00:00Z",
        "model": "mock-balanced" if role == "assistant" else None,
        "sources": [],
        "attachments": [],
        "channel": "text",
    }
    base.update(over)
    return base


def test_a_reopened_conversation_shows_its_draft_cards_again(
    browser: Any, server_url: str, token: str
) -> None:
    good = DRAFTS[1]
    session = {
        "id": "sess_back",
        "user_id": "owner",
        "created_at": "2026-11-03T00:00:00Z",
        "updated_at": "2026-11-03T00:01:00Z",
        "turns": [
            _turn("user", "WhatsApp Ravi in Malayalam"),
            _turn("assistant", ""),  # the tool exchange: no text of its own
            _turn("user", ""),
            _turn("assistant", "It's ready - tap Open in WhatsApp, then Send."),
        ],
        "metadata": {},
        "total_input_tokens": 0,
        "total_output_tokens": 0,
        "total_cost_usd": 0.0,
        "total_cost_inr": 0.0,
        "drafts": [
            {"turn": 3, "card": good},
            {"turn": 3, "card": DRAFTS[3]},  # a malformed one is still dropped
            {"turn": "3", "card": good},  # so is a bad turn index
        ],
    }
    wa = WaMe()
    c = Console(browser, server_url, token, DESKTOP)
    try:
        c.page.add_init_script(
            "try { localStorage.setItem('jarvis_session', 'sess_back'); } catch (_) {}"
        )
        c.ctx.route(re.compile(r"^https://wa\.me/.*"), wa.handle)
        body = json.dumps(session)
        c.page.route(
            "**/v1/sessions/sess_back",
            lambda r: r.fulfill(status=200, content_type="application/json", body=body),
        )
        c.open()
        card = c.page.locator(".row.jarvis .wadraft")
        card.first.wait_for()
        assert card.count() == 1
        assert card.locator(".watext").text_content() == TEXT
        link = card.locator("a.waopen")
        assert link.get_attribute("href") == _link("919876543210", TEXT)
        assert link.get_attribute("rel") == "noopener noreferrer"
        assert wa.opened == []  # nothing opens by itself on reload
        assert c.page.evaluate("window.__pwned") is None
        assert c.errors == [] and c.csp_violations() == []
    finally:
        c.close()
