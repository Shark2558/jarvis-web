# tests/browser/test_r64_i1_book.py -- R6.4 I1 (docs/plans/r6-4-book-look.md D3, D7; the approved
# mockup's chip): the full book's reader (builder A) and the chapter player (builder B) joined, in a
# real Chromium. The reader's small book (r64_a_book.install) with the REAL Vault chapter and its
# five pages (r64_chapter_fakes.serve_vault) and a browser voice under the test's control:
#   - Play the Vault chapter from its Play card, skip to its second page, Stop: the reader shows the
#     page being told (its address #<page id>); Continue offers the chapter at its line ("Continue
#     the chapter: Vault and documents", "Line 25 of 80"); after a reload too; a tap plays it from
#     there; once the owner chooses a page to read, the chapter is no longer the newer place
#   - Continue weighs the player's heard_at against the reader's read_at (one card, plain words)
#   - the release chip: "R6.4 · v6.4.0 · <id>", and version and id only for an answer with no label
# ruff: noqa: E501 -- JavaScript strings
from __future__ import annotations

import json
from collections.abc import Iterator
from typing import Any

import pytest
from book_mocks import TOKEN, FakeBook
from r64_a_book import CHAPTERS, RID, install
from r64_chapter_fakes import HOLD, serve_vault
from test_console import DESKTOP, Console

_pw = pytest.importorskip("playwright.sync_api")
pytestmark = pytest.mark.browser
PLACE = "jarvis_book_place_v1"
SEED = (
    "if (!sessionStorage.getItem('__seeded')) { sessionStorage.setItem('__seeded', '1');"
    f" sessionStorage.setItem('jarvis_book_token', '{TOKEN}');"
    " sessionStorage.setItem('jarvis_book_session', JSON.stringify({ audience: 'owner', session_id: 'bk_0123456789abcdef' })); }"
)
READ_PLACE = f"() => JSON.parse(localStorage.getItem('{PLACE}') || 'null')"


@pytest.fixture(scope="module")
def browser() -> Iterator[Any]:
    with _pw.sync_playwright() as p:
        b = p.chromium.launch()
        yield b
        b.close()


def reader(browser: Any, url: str, token: str, *, at: str = "pg_module_vault", store: dict[str, Any] | None = None,
           chapters: dict[str, Any] | None = None) -> tuple[Console, FakeBook]:  # fmt: skip
    c = Console(browser, url, token, DESKTOP)
    c.page.add_init_script(SEED)
    c.page.add_init_script(HOLD)  # each line ends only when the test says so
    if store is not None:
        c.page.add_init_script("if (!sessionStorage.getItem('__stored')) { sessionStorage.setItem('__stored', '1');"
                               f" localStorage.setItem('{PLACE}', {json.dumps(json.dumps(store))}); }}")  # fmt: skip
    fake = FakeBook(c.page)
    install(fake)
    if chapters is not None:
        fake.chapters_answer = (200, chapters)
    serve_vault(c.page, fake)  # the real Vault chapter and pages (the same page ids as the small book's)
    c.page.goto(url + "/book/read#" + at)
    c.page.locator("#brTitle").wait_for()
    return c, fake


def wait_title(c: Console, words: str) -> None:
    c.page.locator("#brTitle", has_text=words).wait_for()


def at_line(c: Console, n: int) -> None:
    c.page.wait_for_function(f"() => window.JarvisBookChapter.state().open && window.JarvisBookChapter.state().line === {n}")


def clean(c: Console) -> None:
    assert c.errors == [] and c.csp_violations() == []


def test_stop_shows_the_page_told_and_continue_offers_the_chapter_until_a_page_is_chosen(
    browser: Any, server_url: str, token: str
) -> None:
    c, _ = reader(browser, server_url, token)
    try:
        p = c.page
        p.locator("#brPlay .pbtn").click()  # the page's Play card: the Vault chapter from its start
        at_line(c, 1)
        p.locator("#brPNextPage").click()  # its second page, "Attached documents"
        at_line(c, 25)
        p.locator("#brPStop").click()
        wait_title(c, "Attached documents")
        assert p.evaluate("location.hash") == "#pg_card_c07" and p.locator("#bookRead").get_attribute("data-mode") is None
        card = p.locator("#brContinue")
        card.wait_for(state="visible")
        assert card.get_attribute("data-chapter") == "module_vault"
        assert "Continue the chapter: Vault and documents" in card.inner_text() and "Line 25 of 80" in card.inner_text()
        kept = p.evaluate(READ_PLACE)
        assert (kept["release"], kept["chapter"], kept["line"], kept["page"]) == (RID, "module_vault", 25, "pg_card_c07")
        assert kept["heard_at"] > 0 and "read_at" not in kept  # the page told was not the owner's choice

        p.reload()
        wait_title(c, "Attached documents")
        card.wait_for(state="visible")
        assert "Continue the chapter: Vault and documents" in card.inner_text() and "Line 25 of 80" in card.inner_text()
        card.click()  # plays the chapter from where he stopped
        at_line(c, 25)
        assert p.locator("#bookRead").get_attribute("data-mode") == "player" and p.evaluate("location.hash") == "#pg_card_c07"
        p.locator("#brPStop").click()
        wait_title(c, "Attached documents")
        card.wait_for(state="visible")

        p.locator("#brContents a[data-page=pg_card_c42]").click()  # he chooses a page to read
        wait_title(c, "Document vault")
        assert card.is_hidden()  # the chapter is no longer the newer place, and this is the page read
        kept = p.evaluate(READ_PLACE)
        assert kept["page"] == "pg_card_c42" and kept["read_at"] >= kept["heard_at"] and kept["chapter"] == "module_vault"
        p.goto(server_url + "/book/read?again=1#pg_module_vault")  # a new visit: Continue offers the page he chose
        wait_title(c, "Vault and documents")
        card.wait_for(state="visible")
        assert "Continue: Document vault" in card.inner_text() and card.get_attribute("data-chapter") is None
        clean(c)
    finally:
        c.close()


@pytest.mark.parametrize(
    ("heard", "read", "words"),
    [
        (3000, 2000, ["Continue the chapter: Vault and documents", "Line 23 of 80"]),
        (1000, 2000, ["Continue: Document vault", "Vault and documents · page 3 of 5"]),
        (None, None, ["Continue the chapter: Vault and documents", "Line 23 of 80"]),
    ],
)
def test_continue_offers_whichever_came_last_in_one_card(
    browser: Any, server_url: str, token: str, heard: int | None, read: int | None, words: list[str]
) -> None:
    store: dict[str, Any] = {"release": RID, "page": "pg_card_c42", "chapter": "module_vault", "line": 23, "scene": 4}
    if heard is not None:
        store["heard_at"] = heard
    if read is not None:
        store["read_at"] = read
    c, _ = reader(browser, server_url, token, store=store)
    try:
        cards = c.page.locator(".bk-cont:visible")
        assert cards.count() == 1 and all(w in cards.inner_text() for w in words)
        clean(c)
    finally:
        c.close()


def test_another_releases_chapter_is_never_offered(browser: Any, server_url: str, token: str) -> None:
    other = {"release": "aebff3a", "chapter": "module_vault", "line": 23, "heard_at": 9}
    c, _ = reader(browser, server_url, token, store=other)
    try:
        assert c.page.locator("#brContinue").is_hidden()
        assert c.page.evaluate(READ_PLACE) == other  # another release's place stays as the player wrote it
        clean(c)
    finally:
        c.close()


def test_the_release_chip_says_label_version_and_id(browser: Any, server_url: str, token: str) -> None:
    c, _ = reader(browser, server_url, token)
    try:
        assert c.page.locator("#brRelease").inner_text() == "R6.4 · v6.4.0 · " + RID
    finally:
        c.close()
    old = {k: v for k, v in CHAPTERS.items() if k != "label"}  # an answer from before the label
    c, _ = reader(browser, server_url, token, chapters=old)
    try:
        assert c.page.locator("#brRelease").inner_text() == "v6.4.0 · " + RID
        clean(c)
    finally:
        c.close()
