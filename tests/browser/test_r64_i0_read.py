# tests/browser/test_r64_i0_read.py -- R6.4 D1, D2 (docs/plans/r6-4-book-look.md): the full
# book's own page (/book/read) as I0 leaves it for builders A and B: with the owner's book token in
# THIS tab's sessionStorage it asks /v1/book/chapters with X-Jarvis-Book and is ready; without one
# it asks nothing and says how to open the book; a refused session forgets the token. The Book-only
# tokens apply (68ch measure, 16 px body, Orbitron title, Share Tech Mono labels), a phone gets the
# contents button at 44 px, and nothing breaks the CSP. Stubbed with book_mocks.FakeBook.
# ruff: noqa: E501 -- JavaScript strings
from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest
from book_mocks import TOKEN, FakeBook
from test_console import DESKTOP, PHONE, Console

_pw = pytest.importorskip("playwright.sync_api")

pytestmark = pytest.mark.browser

SEED = """
if (!sessionStorage.getItem('__seeded')) {
  sessionStorage.setItem('__seeded', '1');
  sessionStorage.setItem('jarvis_book_token', '%s');
  sessionStorage.setItem('jarvis_book_session', JSON.stringify({ audience: 'owner', session_id: 'bk_0123456789abcdef' }));
}
"""


@pytest.fixture(scope="module")
def browser() -> Iterator[Any]:
    with _pw.sync_playwright() as p:
        b = p.chromium.launch()
        yield b
        b.close()


def _read(browser: Any, url: str, token: str, *, seeded: bool = True,
          viewport: dict[str, int] = DESKTOP) -> tuple[Console, FakeBook]:  # fmt: skip
    c = Console(browser, url, token, viewport)
    if seeded:
        c.page.add_init_script(SEED % TOKEN)
    fake = FakeBook(c.page)
    c.page.goto(url + "/book/read")
    return c, fake


def _clean(c: Console, *expected: int) -> None:
    said = [f"status of {code} " for code in expected]
    errors = [e for e in c.errors if not any(s in e for s in said)]
    assert errors == [] and c.csp_violations() == []


def test_with_the_token_it_reads_the_chapters_and_is_ready(
    browser: Any, server_url: str, token: str
) -> None:
    c, fake = _read(browser, server_url, token)
    try:
        c.page.locator("#bookRead[data-state=ready]").wait_for()
        (got,) = fake.to("GET", "/v1/book/chapters")
        assert got["headers"]["x-jarvis-book"] == TOKEN
        assert c.page.evaluate("window.JarvisBookRead.state()") == "ready"
        assert c.page.evaluate("window.JarvisBookRead.chapters().length") == 2
        assert c.page.locator("#brRelease").inner_text() == "3f2a1c9"
        assert c.page.locator("#brGate").is_hidden()
        assert c.page.evaluate("typeof window.JarvisBookChapter.open") == "function"
        look = c.page.evaluate(
            "(() => { const h = getComputedStyle(document.documentElement), b = getComputedStyle(document.body);"
            " return { measure: h.getPropertyValue('--bk-measure').trim(), size: b.fontSize,"
            " word: getComputedStyle(document.querySelector('.bk-word')).fontFamily,"
            " label: getComputedStyle(document.querySelector('.bk-sub')).fontFamily }; })()"
        )
        assert look["measure"] == "68ch" and look["size"] == "16px"
        assert "Orbitron" in look["word"] and "Share Tech Mono" in look["label"]
        _clean(c)
    finally:
        c.close()


def test_without_a_token_it_asks_nothing_and_says_how_to_open_the_book(
    browser: Any, server_url: str, token: str
) -> None:
    c, fake = _read(browser, server_url, token, seeded=False)
    try:
        c.page.locator("#bookRead[data-state=closed]").wait_for()
        assert c.page.locator("#brGate").is_visible()
        assert "Read the full book" in c.page.locator("#brGateText").inner_text()
        assert [x for x in fake.calls if x["path"].startswith("/v1/book")] == []
        _clean(c)
    finally:
        c.close()


def test_a_refused_session_forgets_the_token(browser: Any, server_url: str, token: str) -> None:
    c = Console(browser, server_url, token, DESKTOP)
    c.page.add_init_script(SEED % TOKEN)
    fake = FakeBook(c.page)
    fake.chapters_answer = (
        403,
        {"error": "owner_only", "detail": "Only your own book session opens this."},
    )
    try:
        c.page.goto(server_url + "/book/read")
        c.page.locator("#bookRead[data-state=closed]").wait_for()
        assert "session ended" in c.page.locator("#brGateText").inner_text()
        assert c.page.evaluate("sessionStorage.getItem('jarvis_book_token')") is None
        _clean(c, 403)
    finally:
        c.close()


def test_a_phone_gets_the_contents_button_at_44_px(
    browser: Any, server_url: str, token: str
) -> None:
    c, _ = _read(browser, server_url, token, viewport=PHONE)
    try:
        c.page.locator("#bookRead[data-state=ready]").wait_for()
        menu = c.page.locator("#brMenu")
        assert menu.is_visible() and c.page.locator("#brSearchBox").is_hidden()
        for sel in ("#brMenu", "#brTour", "#brClose"):
            box = c.page.locator(sel).bounding_box()
            assert box is not None and box["height"] >= 44 and box["width"] >= 44, sel
        _clean(c)
    finally:
        c.close()
