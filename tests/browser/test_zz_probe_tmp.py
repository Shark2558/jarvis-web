# tests/browser/test_r64_a_reader.py -- R6.4 A (docs/plans/r6-4-book-look.md D1-D4; the approved mockups A-D, G-I, K):
# the full book's reader on /book/read in a real Chromium, the book routes stubbed (book_mocks.FakeBook with the small
# book of r64_a_book.py):
#   - the contents (The story, Modules opening to their pages, Screens, Outside services, minutes) and opening a page
#     (its address #<page id>, the rail's mark, Back to the page before without asking again)
#   - a page: lead, the made-up example and its tag, inline code, the flowchart drawn, "Where in the code" closed, the
#     amber failures, a rupee figure only for a plain amount, previous and next (chapters at the ends), "On this page"
#   - Play calls the chapter player, and a polite note when it says no; no Play card outside a narrated chapter
#   - Continue from the remembered place (the tour's fields merged, never overwritten; a storage that throws is harmless)
#   - read dots kept per release
#   - search: debounced, marks built as nodes (hostile text stays text), "Showing N of M", the keys, IME-safe Enter,
#     the helpful "no results"
#   - Close asks first; tab order and visible focus; the phone's sheet and Play bar at 44 px; no token: I0's gate
#   - the Book panel no longer holds the old in-panel full book
# ruff: noqa: E501 -- JavaScript strings
from __future__ import annotations

import json
from collections.abc import Iterator
from typing import Any

import pytest
from book_mocks import PASSKEY_STUB, TOKEN, FakeBook
from r64_a_book import PAGES, RID, install
from test_console import DESKTOP, PHONE, Console
from test_ui_audit import NAMELESS_JS, WRAP_JS, _assert_clean
from ui_checks import DOM_CHECKS_JS, FINISH_ANIMATIONS_JS

_pw = pytest.importorskip("playwright.sync_api")
pytestmark = pytest.mark.browser
PLACE, READ = "jarvis_book_place_v1", "jarvis_book_read_v1"
SEED = (
    "if (!sessionStorage.getItem('__seeded')) { sessionStorage.setItem('__seeded', '1');"
    f" sessionStorage.setItem('jarvis_book_token', '{TOKEN}');"
    " sessionStorage.setItem('jarvis_book_session', JSON.stringify({ audience: 'owner', session_id: 'bk_0123456789abcdef' })); }"
)


@pytest.fixture(scope="module")
def browser() -> Iterator[Any]:
    with _pw.sync_playwright() as p:
        b = p.chromium.launch()
        yield b
        b.close()


def reader(browser: Any, url: str, token: str, *, at: str = "", viewport: dict[str, int] = DESKTOP,
           store: dict[str, Any] | None = None, seeded: bool = True, script: str = "") -> tuple[Console, FakeBook]:  # fmt: skip
    c = Console(browser, url, token, viewport)
    if seeded:
        c.page.add_init_script(SEED)
    if store:
        c.page.add_init_script("if (!sessionStorage.getItem('__stored')) { sessionStorage.setItem('__stored', '1');"
                               + "".join(f"localStorage.setItem({json.dumps(k)}, {json.dumps(json.dumps(v))});" for k, v in store.items()) + "}")  # fmt: skip
    if script:
        c.page.add_init_script(script)
    fake = FakeBook(c.page)
    install(fake)
    c.page.goto(url + "/book/read" + (f"#{at}" if at else ""))
    if seeded:
        c.page.locator("#brTitle").wait_for()
    return c, fake


def title(c: Console) -> str:
    return str(c.page.locator("#brTitle").inner_text())


def wait_title(c: Console, words: str) -> None:
    c.page.locator("#brTitle", has_text=words).wait_for()


def clean(c: Console, *expected: int) -> None:
    said = [f"status of {code} " for code in expected]
    assert [e for e in c.errors if not any(s in e for s in said)] == [] and c.csp_violations() == []


TABS_JS = """() => { const a = document.activeElement; return a.id || a.dataset.page || a.dataset.group || a.className; }"""
RING_JS = """() => { const s = getComputedStyle(document.activeElement); return [s.outlineStyle, parseFloat(s.outlineWidth)]; }"""

def reader_slow(browser, url, token, *, at=""):
    c = Console(browser, url, token, DESKTOP)
    c.page.add_init_script(SEED)
    cdp = c.page.context.new_cdp_session(c.page)
    cdp.send("Emulation.setCPUThrottlingRate", {"rate": 12})
    fake = FakeBook(c.page)
    install(fake)
    c.page.goto(url + "/book/read" + (f"#{at}" if at else ""))
    c.page.locator("#brTitle").wait_for()
    return c, fake


def test_probe_slow(
    browser: Any, server_url: str, token: str
) -> None:
    c, _ = reader_slow(browser, server_url, token, at="pg_module_vault")
    try:
        p = c.page
        assert p.evaluate(
            "document.activeElement === document.body"
        )  # the first page takes no focus
        seen = []
        for _ in range(5):
            p.keyboard.press("Tab")
            seen.append(p.evaluate(TABS_JS))
            style, width = p.evaluate(RING_JS)
            assert style != "none" and width >= 2, seen[-1]
        assert seen == ["brSearch", "brTour", "brClose", "story", "pg_chapter_what"]
        tops = p.evaluate(
            "[...document.querySelectorAll('#brPage a, #brPage button, #brPage summary')].map((e) => e.getBoundingClientRect().top)"
        )
        assert tops == sorted(tops)
        clean(c)
    finally:
        c.close()

