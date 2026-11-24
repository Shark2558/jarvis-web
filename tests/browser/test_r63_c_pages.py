# tests/browser/test_r63_c_pages.py -- R6.3 Part C, D14 and row 380 "grows" (console half;
# docs/plans/r6-3-book-content.md D14, G4) in a real Chromium against C's fake server
# (tests/r63_fakes_c.py), the R6 routes from book_mocks.FakeBook:
#   - the Full book under the owner's reader: parts as disclosures, chapters as rows, a page's six
#     sections (plain and example open, the rest closed), who wrote it, its references as chips;
#     a page not written yet says so (R6.3.1: "Written by the Workshop", no changed label)
#   - every request carries the owner's book session (X-Jarvis-Book); an older kept release reads
#     its own pages; a 403 (a guest's session) draws nothing at all
#   - continue where I left off: `jarvis_book_place_v1` {release, page}, ids only; reopening offers
#     "Continue: <title>"; Part D's tour fields in the same key merged, never overwritten (another
#     release's tour place left alone); a storage that throws breaks nothing
#   - the reader's limitations section: "+32 more in the full book" (owner session only)
#   - test_r63_c_a_new_card_is_listed: a page the index lists is in the Full book
from __future__ import annotations

import json
import os
from collections.abc import Iterator
from typing import Any

import pytest
from book_mocks import PASSKEY_STUB, TOKEN, FakeBook
from r63_fakes_c import route_c, serve_c, set_state, until
from test_console import Console

_pw = pytest.importorskip("playwright.sync_api")
pytestmark = pytest.mark.browser
LAPTOP = {"width": 1280, "height": 800}
PAGES = "#p-book .bk-pages"
PLACE = "jarvis_book_place_v1"


@pytest.fixture(scope="module")
def c_url(token: str) -> Iterator[str]:
    if os.environ.get("JARVIS_BROWSER_TESTS") != "1":
        pytest.skip("JARVIS_BROWSER_TESTS=1 not set")
    url, stop = serve_c(token)
    try:
        yield url
    finally:
        stop()


@pytest.fixture(scope="module")
def browser() -> Iterator[Any]:
    with _pw.sync_playwright() as p:
        b = p.chromium.launch()
        yield b
        b.close()


def owner(
    browser: Any, url: str, token: str, *, place: Any = None, **state: Any
) -> tuple[Console, list[Any]]:
    """An owner session open in the Book panel; every full-book request the page sent."""
    set_state(url, reset=True, **state)
    c = Console(browser, url, token, LAPTOP)
    if place is not None:
        c.page.add_init_script(f"localStorage.setItem('{PLACE}', {json.dumps(json.dumps(place))});")
    asked: list[Any] = []
    c.page.on("request", lambda r: asked.append(r) if "/v1/book/pages" in r.url else None)
    FakeBook(c.page)
    route_c(c.page)
    c.open()
    c.page.evaluate(PASSKEY_STUB)
    c.open_panel("book")
    c.page.get_by_role("button", name="Open for me").click()
    c.page.locator("#p-book .bk-reader").wait_for()
    return c, asked


def text(c: Console) -> str:
    return str(
        c.page.locator(PAGES).text_content()
    )  # as written (the heads are upper-cased by style)


def part(c: Console, title: str) -> Any:
    head = c.page.locator(f"{PAGES} .dsc", has_text=title).first
    head.wait_for()
    if head.get_attribute("aria-expanded") != "true":
        head.click()
    return head


def read(c: Console, title: str) -> None:
    row = c.page.locator(f"{PAGES} .bk-row", has_text=title).first
    row.get_by_role("button", name="Read").click()
    c.page.locator(f"{PAGES} .bk-rhead", has_text="Reading " + title).wait_for()


def clean(c: Console, *expected: int) -> None:
    said = [f"status of {code} " for code in expected]
    errors = [e for e in c.errors if not any(s in e for s in said)]
    assert errors == [] and c.csp_violations() == []


def test_r63_c_pages_the_full_book_lists_parts_chapters_and_who_wrote_each(
    browser: Any, c_url: str, token: str
) -> None:
    c, asked = owner(browser, c_url, token)
    try:
        until(c.page, lambda: "Full book" in text(c), "the full book")
        heads = c.page.locator(f"{PAGES} .dsc .dl").all_text_contents()  # as written, not as styled
        assert heads == ["JARVIS in plain words", "Modules", "Parts", "Outside services"]
        part(c, "Parts")
        until(c.page, lambda: "The demo" in text(c), "the chapter")
        words = text(c)
        assert "Demo router" in words and "Written by the Workshop" in words
        assert "Changed in this release" not in words  # R6.3.1: no Update to wait for
        assert "Not written yet" in words  # Demo store, Demo console
        assert all(r.headers.get("x-jarvis-book") == TOKEN for r in asked)
        assert asked and all("release=3f2a1c9" in r.url for r in asked)
        clean(c)
    finally:
        c.close()


def test_r63_c_pages_a_written_page_its_sections_and_references(
    browser: Any, c_url: str, token: str
) -> None:
    c, _ = owner(browser, c_url, token)
    try:
        part(c, "Parts")
        read(c, "Demo router")
        words = text(c)
        assert "Written by the Workshop \u00b7 24 Nov 2026" in words  # R6.3.1 D8: plain
        sections = c.page.locator(f"{PAGES} .bk-sec > .dsc")
        labels = [s.locator(".dl").text_content() for s in sections.all()]
        assert labels == [
            "In plain words", "Example (made up)", "How it works", "What it costs", "When it fails",
            "Where in the code",
        ]  # fmt: skip
        opened = [s.get_attribute("aria-expanded") for s in sections.all()]
        assert opened == ["true", "true", "false", "false", "false", "false"]
        assert "picks one tier for each request" in words and "3 tries at most" in words
        sections.nth(5).click()
        chips = c.page.locator(f"{PAGES} .bchip").all_inner_texts()
        assert chips == ["src/jarvis/demo/router.py"]
        sections.nth(2).click()
        assert c.page.locator(f"{PAGES} .blines li").count() == 3  # "- " lines as a list
        c.page.locator(PAGES).get_by_role("button", name="Back to the contents").click()
        c.page.locator(f"{PAGES} .dsc", has_text="Parts").wait_for()
        clean(c)
    finally:
        c.close()


def test_r63_c_pages_a_page_not_written_by_ai_says_so(browser: Any, c_url: str, token: str) -> None:
    c, _ = owner(browser, c_url, token)
    try:
        part(c, "Parts")
        read(c, "Demo console")
        assert "Not written yet" in text(c) and "Written by" not in text(c)
        clean(c)
    finally:
        c.close()


def test_r63_c_pages_an_older_release_reads_its_own_pages(
    browser: Any, c_url: str, token: str
) -> None:
    c, asked = owner(browser, c_url, token)
    try:
        until(c.page, lambda: "Full book" in text(c), "the full book")
        c.page.locator("#p-book .bk-sealed li", has_text="aebff3a").get_by_role(
            "button", name="Read"
        ).click()
        until(c.page, lambda: any("release=aebff3a" in r.url for r in asked), "the older index")
        part(c, "Parts")
        until(c.page, lambda: "Demo router" in text(c), "the older rows")
        assert "Written by" not in text(c)
        read(c, "Demo router")
        assert any("/pages/pg_card_c01?release=aebff3a" in r.url for r in asked)
        clean(c)
    finally:
        c.close()


def kept(c: Console) -> Any:
    return json.loads(c.page.evaluate(f"localStorage.getItem('{PLACE}')") or "null")


def test_r63_c_pages_continue_where_i_left_off(browser: Any, c_url: str, token: str) -> None:
    c, _ = owner(browser, c_url, token)
    try:
        part(c, "Parts")
        read(c, "Demo router")
        assert kept(c) == {"release": "3f2a1c9", "page": "pg_card_c01"}  # ids only
        c.page.get_by_role("button", name="End session").click()
        c.page.locator("#bookDialog").get_by_role("button", name="End").click()
        c.page.get_by_role("button", name="Open for me").click()
        go = c.page.locator(PAGES).get_by_role("button", name="Continue: Demo router")
        go.wait_for()
        go.click()
        c.page.locator(f"{PAGES} .bk-rhead", has_text="Reading Demo router").wait_for()
        clean(c)
    finally:
        c.close()


def test_r63_c_pages_the_tours_place_in_the_same_key_is_merged_never_overwritten(
    browser: Any, c_url: str, token: str
) -> None:
    """Part D's tour keeps {release, scene} (an integer) under the same key: the reader reads it
    first and keeps D's fields as they are; another release's tour place is left alone; a
    storage that throws (full or blocked) keeps nothing and breaks nothing."""
    c, _ = owner(browser, c_url, token, place={"release": "3f2a1c9", "scene": 7})
    try:
        part(c, "Parts")
        read(c, "Demo router")
        assert kept(c) == {"release": "3f2a1c9", "scene": 7, "page": "pg_card_c01"}
        older = {"release": "aebff3a", "scene": 3}
        c.page.evaluate(f"(v) => localStorage.setItem('{PLACE}', JSON.stringify(v))", older)
        c.page.locator(PAGES).get_by_role("button", name="Back to the contents").click()
        read(c, "Demo console")
        assert kept(c) == older  # D's place of another release: not replaced by the reader's
        c.page.evaluate(
            """(key) => {
              const S = Storage.prototype, get = S.getItem, set = S.setItem;
              const no = () => { throw new DOMException('no room', 'QuotaExceededError'); };
              S.getItem = function (k) { return k === key ? no() : get.call(this, k); };
              S.setItem = function (k, v) { return k === key ? no() : set.call(this, k, v); };
            }""",
            PLACE,
        )
        c.page.locator(PAGES).get_by_role("button", name="Back to the contents").click()
        read(c, "Demo router")  # still reads
        clean(c)
    finally:
        c.close()


def test_r63_c_pages_another_releases_place_is_not_offered(
    browser: Any, c_url: str, token: str
) -> None:
    c, _ = owner(browser, c_url, token, place={"release": "aebff3a", "page": "pg_card_c01"})
    try:
        until(c.page, lambda: "Full book" in text(c), "the full book")
        assert (
            c.page.locator(PAGES).get_by_role("button", name="Continue: Demo router").count() == 0
        )
        clean(c)
    finally:
        c.close()


def test_r63_c_pages_the_limitations_say_how_many_more_the_full_book_has(
    browser: Any, c_url: str, token: str
) -> None:
    c, _ = owner(browser, c_url, token)
    try:
        until(c.page, lambda: "Full book" in text(c), "the full book")
        c.page.locator("#p-book .bk-reader .dsc", has_text="Limitations").click()
        c.page.locator("#p-book .bk-reader", has_text="+32 more in the full book").wait_for()
        clean(c)
    finally:
        c.close()


def test_r63_c_pages_a_guest_session_gets_nothing(browser: Any, c_url: str, token: str) -> None:
    set_state(c_url, reset=True)
    c = Console(browser, c_url, token, LAPTOP)
    try:
        FakeBook(c.page)
        route_c(c.page)
        refusal = json.dumps({"error": "owner_only", "detail": "The full book is the owner's."})
        for pattern in ("**/v1/book/pages", "**/v1/book/pages?*", "**/v1/book/pages/**"):
            c.page.route(
                pattern,
                lambda r: r.fulfill(status=403, body=refusal, content_type="application/json"),
            )
        c.open()
        c.page.evaluate(PASSKEY_STUB)
        c.open_panel("book")
        c.page.get_by_role("button", name="Open for me").click()
        c.page.locator("#p-book .bk-reader").wait_for()
        c.page.locator("#p-book .bk-reader .dsc", has_text="Limitations").click()
        c.page.wait_for_timeout(500)
        host = c.page.locator(PAGES)
        assert host.count() == 1 and not host.is_visible() and host.inner_text() == ""
        assert "more in the full book" not in c.page.locator("#p-book").inner_text()
        clean(c, 403)
    finally:
        c.close()


def test_r63_c_a_new_card_is_listed(browser: Any, c_url: str, token: str) -> None:
    c, _ = owner(browser, c_url, token, new_card=True)
    try:
        part(c, "Parts")
        until(c.page, lambda: "A new card" in text(c), "C74's page")
        read(c, "A new card")
        assert "Not written yet" in text(c)
        clean(c)
    finally:
        c.close()
