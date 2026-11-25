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


def test_the_contents_list_the_four_groups_and_a_page_opens(
    browser: Any, server_url: str, token: str
) -> None:
    c, fake = reader(browser, server_url, token)
    try:
        p = c.page
        assert title(c) == "What JARVIS is" and p.evaluate("location.hash") == "#pg_chapter_what"
        heads = p.locator("#brContents button.bk-part")
        assert [h.get_attribute("aria-label") for h in heads.all()] == [
            "The story, 2",
            "Modules, 2",
            "Screens, 2",
            "Outside services, 1",
        ]
        assert [h.get_attribute("aria-expanded") for h in heads.all()] == [
            "true",
            "true",
            "false",
            "false",
        ]
        vault = p.locator("#brContents .bk-chapbtn", has_text="Vault and documents")
        assert vault.get_attribute("aria-expanded") == "false" and "9 min" in vault.inner_text()
        vault.click()
        links = p.locator("#brCh-module_vault a")
        assert [a.inner_text().strip() for a in links.all()] == [
            "Vault and documents",
            "Attached documents",
            "Document vault",
            "DigiLocker import folder",
            "The Vault screen",
        ]
        links.nth(1).click()
        wait_title(c, "Attached documents")
        assert p.evaluate("location.hash") == "#pg_card_c07"
        assert "Page 2 of 5" in str(p.locator("#brPage .bk-crumb").text_content())
        now = p.locator("#brContents a[aria-current=page]")
        assert now.count() == 1 and now.get_attribute("data-page") == "pg_card_c07"
        (got,) = fake.to("GET", "/v1/book/pages/pg_card_c07")
        assert got["headers"]["x-jarvis-book"] == TOKEN
        assert len(fake.to("GET", "/v1/book/pages")) == 1
        p.go_back()
        wait_title(c, "What JARVIS is")
        assert (
            len(fake.to("GET", "/v1/book/pages/pg_chapter_what")) == 1
        )  # kept for this visit, not asked again
        assert p.locator("#brSearch").get_attribute("placeholder") == "Search 11 pages"
        assert p.locator("#brRelease").inner_text() == "R6.4 · v6.4.0 · " + RID  # I1: the label too
        clean(c)
    finally:
        c.close()


def test_a_page_draws_its_sections_its_flowchart_and_its_neighbours(
    browser: Any, server_url: str, token: str
) -> None:
    c, _ = reader(browser, server_url, token, at="pg_module_vault")
    try:
        p, page = c.page, "#brPage"
        assert title(c) == "Vault and documents"
        meta = p.locator(f"{page} .bk-meta").inner_text()
        assert (
            "Written by the Workshop · 24 Nov 2026" in meta
            and "2 min read" in meta
            and "3 files of code" in meta
        )
        assert (
            p.locator(f"{page} #brSec-plain .bk-lead").count() == 1
            and p.locator(f"{page} #brSec-plain .bk-p").count() == 2
        )
        assert p.locator(f"{page} #brSec-example h2").inner_text().strip().lower() == "example"
        assert p.locator(f"{page} .bk-ex .bk-tag").inner_text().lower() == "made-up example"
        assert p.locator(f"{page} #brSec-how code", has_text="POST /v1/attachments").count() == 1
        fig = p.locator(f"{page} #brSec-how .bk-fig .bk-flow")
        fig.locator("svg.fl-svg").wait_for()
        assert fig.locator("svg.fl-svg g.fl-node").count() == 11 and str(
            fig.locator("figcaption").text_content()
        ).startswith("A document")
        more = p.locator(f"{page} #brSec-how details.bk-more")
        assert more.get_attribute("open") is None and "3 files" in str(
            more.locator("summary").text_content()
        )
        more.locator("summary").click()
        assert more.locator(".bk-refs li").count() == 3
        assert (
            p.locator(f"{page} .bk-fails li").count() == 3
            and p.locator(f"{page} .bk-fails code").inner_text() == "DocumentRejected"
        )
        assert p.locator(f"{page} .bk-cost").count() == 0  # "cost nothing": no figure is made up
        prev, nxt = p.locator(f"{page} .bk-pn a").all()
        assert "Previous chapter" in str(prev.text_content()) and "Memory and knowledge" in str(
            prev.text_content()
        )
        assert "Next page" in str(nxt.text_content()) and "Attached documents" in str(
            nxt.text_content()
        )
        assert [a.inner_text() for a in p.locator("#brToc .bk-onpage a").all()] == [
            "In plain words",
            "Example",
            "How it works",
            "What it costs",
            "When it fails",
        ]
        assert (
            p.locator("#brToc .bk-chap a").count() == 5
            and p.locator("#brToc .bk-chap a[aria-current=page]").inner_text()
            == "Vault and documents"
        )
        p.locator("#brToc .bk-onpage a", has_text="When it fails").click()
        p.locator("#brToc .bk-onpage a.on", has_text="When it fails").wait_for()
        nxt.click()
        wait_title(c, "Attached documents")
        assert (
            p.evaluate("document.activeElement.id") == "brTitle"
        )  # the next page's title takes the focus
        p.evaluate("location.hash = 'pg_card_c42'")
        wait_title(c, "Document vault")
        assert p.locator(f"{page} .bk-cost .n b").inner_text() == "₹0"
        p.evaluate("location.hash = 'pg_screen_vault'")
        wait_title(c, "The Vault screen")
        assert "Next chapter" not in str(
            p.locator(f"{page} .bk-pn").text_content()
        )  # the last chapter of the book
        p.evaluate("location.hash = 'pg_card_c10'")
        wait_title(c, "Long-term memory")
        assert "Next chapter" in str(p.locator(f"{page} .bk-pn a.next").text_content())
        p.evaluate("location.hash = 'pg_card_c43'")
        wait_title(c, "DigiLocker import folder")
        assert "Not written yet" in p.locator(f"{page} .bk-meta").inner_text()
        clean(c)
    finally:
        c.close()


def test_play_asks_the_chapter_player_and_says_so_politely_when_it_cannot(
    browser: Any, server_url: str, token: str
) -> None:
    c, _ = reader(browser, server_url, token)
    try:
        p = c.page
        assert p.locator("#brPlay").count() == 0  # a story chapter that isn't narrated
        p.evaluate("location.hash = 'pg_card_c42'")
        wait_title(c, "Document vault")
        card = p.locator("#brPlay")
        assert (
            "Vault and documents" in card.inner_text()
            and "5 pages, about 9 minutes" in card.inner_text()
        )
        card.locator(
            ".pbtn"
        ).click()  # B's player can't load this chapter here (I1: the two joined)
        p.locator("#brPMsgText").wait_for()  # the player says why, with Back to reading
        p.locator("#brPBack").click()
        p.locator("#brPlayNote", has_text="can’t be played right now").wait_for()
        assert (
            p.locator("#brPage #brTitle").inner_text() == "Document vault"
        )  # the same page, as it was
        p.evaluate(
            "window.JarvisBookChapter = { open: (id, o) => { window.__played = [id, o]; return Promise.resolve(true); } }"
        )
        card.locator(".pbtn").click()
        p.wait_for_function("!!window.__played")
        assert p.evaluate("window.__played") == [
            "module_vault",
            {"line": None, "page": "pg_card_c42"},
        ]
        assert p.locator("#brPlayNote").is_hidden()
        p.locator(
            "#brPlay .bk-chaplist"
        ).click()  # Chapter list: the chapter opened in the rail, focused
        assert p.evaluate("document.activeElement.dataset.chapter") == "module_vault"
        clean(c, 404)  # this small book serves no chapter: the player's own 404
    finally:
        c.close()


def test_continue_offers_the_remembered_place_and_keeps_the_tours(
    browser: Any, server_url: str, token: str
) -> None:
    c, _ = reader(
        browser,
        server_url,
        token,
        store={PLACE: {"release": RID, "page": "pg_card_c42", "scene": 4}},
    )
    try:
        p = c.page
        card = p.locator("#brContinue")
        assert (
            card.is_visible()
            and "Continue: Document vault" in card.inner_text()
            and "Vault and documents · page 3 of 5" in card.inner_text()
        )
        card.click()
        wait_title(c, "Document vault")
        assert card.is_hidden() and p.evaluate("document.activeElement.id") == "brTitle"
        kept = json.loads(p.evaluate(f"localStorage.getItem('{PLACE}')"))
        assert isinstance(
            kept.pop("read_at"), int
        )  # I1: when he chose the page (Continue weighs it against a chapter)
        assert kept == {"scene": 4, "release": RID, "page": "pg_card_c42"}
        clean(c)
    finally:
        c.close()
    other = {"release": "aebff3a", "scene": 3}
    c, _ = reader(browser, server_url, token, store={PLACE: other})
    try:
        assert c.page.locator("#brContinue").is_hidden()
        assert (
            json.loads(c.page.evaluate(f"localStorage.getItem('{PLACE}')")) == other
        )  # another release's tour place stays
        clean(c)
    finally:
        c.close()
    broken = (
        "Object.defineProperty(window, 'localStorage', { get() { throw new Error('blocked'); } });"
    )
    c, _ = reader(browser, server_url, token, script=broken)
    try:
        c.page.evaluate("location.hash = 'pg_card_c07'")
        wait_title(c, "Attached documents")
        assert (
            c.page.locator("#brContents .bk-dot.read").count() == 2
        )  # nothing kept, but this visit's dots still show
        clean(c)
    finally:
        c.close()


def test_read_dots_mark_the_pages_opened_in_this_release(
    browser: Any, server_url: str, token: str
) -> None:
    c, _ = reader(
        browser, server_url, token, store={READ: [{"r": "aebff3a", "ids": ["pg_card_c43"]}]}
    )
    try:
        p = c.page
        p.evaluate("location.hash = 'pg_module_vault'")
        wait_title(c, "Vault and documents")
        read = sorted(
            a.get_attribute("data-page") for a in p.locator("#brContents a:has(.bk-dot.read)").all()
        )
        assert read == ["pg_chapter_what", "pg_module_vault"]
        assert (
            p.locator("#brContents a[data-page=pg_module_vault] .bk-said").text_content()
            == ", read"
        )
        assert (
            p.locator("#brContents a[data-page=pg_card_c43] .bk-dot.read").count() == 0
        )  # another release's
        kept = json.loads(p.evaluate(f"localStorage.getItem('{READ}')"))
        assert (
            kept[0] == {"r": RID, "ids": ["pg_chapter_what", "pg_module_vault"]}
            and kept[1]["r"] == "aebff3a"
        )
        p.reload()
        c.page.locator("#brTitle").wait_for()
        assert p.locator("#brContents a[data-page=pg_module_vault] .bk-dot.read").count() == 1
        clean(c)
    finally:
        c.close()


def test_search_marks_its_words_and_answers_the_keys(
    browser: Any, server_url: str, token: str
) -> None:
    c, fake = reader(browser, server_url, token)
    try:
        p = c.page
        p.locator("#brMain").focus()
        p.keyboard.press("/")
        assert p.evaluate("document.activeElement.id") == "brSearch"
        p.keyboard.type("e")
        p.wait_for_timeout(450)
        assert fake.to("GET", "/v1/book/pages/search") == []  # one character asks nothing
        p.keyboard.type("xpiry")
        box = p.locator("#brResults")
        box.locator("[role=option]").first.wait_for()
        assert len(fake.to("GET", "/v1/book/pages/search")) == 1  # typed fast: asked once
        (got,) = fake.to("GET", "/v1/book/pages/search")
        assert got["query"]["q"] == "expiry" and got["headers"]["x-jarvis-book"] == TOKEN
        opts = box.locator("[role=option]")
        assert opts.count() == 2 and p.locator("#brSearch").get_attribute("aria-expanded") == "true"
        assert (
            opts.nth(0).locator("mark").inner_text() == "expiry"
            and opts.nth(0).locator(".kind").inner_text().lower() == "module"
        )
        hostile = opts.nth(1)
        assert (
            hostile.locator("img, b").count() == 0 and "<img" in hostile.locator(".ti").inner_text()
        )
        assert [m.inner_text() for m in hostile.locator("mark").all()] == [
            "expires"
        ]  # overlapping and outside marks dropped
        assert "Showing 2 of 26" in box.locator(".foot").inner_text() and "26 pages mention" in str(
            box.locator(".head").text_content()
        )
        p.keyboard.press("ArrowDown")
        p.keyboard.press("ArrowDown")
        assert p.locator("#brSearch").get_attribute("aria-activedescendant") == opts.nth(
            1
        ).get_attribute("id")
        assert opts.nth(1).get_attribute("aria-selected") == "true"
        p.keyboard.press("Enter")
        wait_title(c, "Document vault")
        assert box.is_hidden() and p.evaluate("document.activeElement.id") == "brTitle"
        assert p.evaluate("window.__pwned") is None
        p.locator("#brSearch").focus()  # the same words: the list comes back, Enter opens the first
        box.locator("[role=option]").first.wait_for()
        p.evaluate(
            "document.getElementById('brSearch').dispatchEvent(new KeyboardEvent('keydown', {key: 'Enter', isComposing: true, bubbles: true}))"
        )
        p.wait_for_timeout(200)
        assert (
            title(c) == "Document vault" and box.is_visible()
        )  # an input method's Enter is not ours
        p.keyboard.press("Enter")
        wait_title(c, "Vault and documents")
        clean(c)
    finally:
        c.close()


def test_search_with_no_match_says_what_to_try_and_esc_closes_then_clears(
    browser: Any, server_url: str, token: str
) -> None:
    c, _ = reader(browser, server_url, token)
    try:
        p = c.page
        p.locator("#brSearch").fill("zzqq")
        none = p.locator("#brResults .bk-none")
        none.wait_for()
        assert (
            "No page mentions “zzqq”." in none.inner_text()
            and "Try a shorter word, or open the contents." in none.inner_text()
        )
        p.locator("#brNote", has_text="No page mentions").wait_for()
        p.keyboard.press("Escape")
        assert (
            p.locator("#brResults").is_hidden() and p.locator("#brSearch").input_value() == "zzqq"
        )
        p.keyboard.press("Escape")
        assert p.locator("#brSearch").input_value() == ""
        clean(c)
    finally:
        c.close()


def test_close_asks_first(browser: Any, server_url: str, token: str) -> None:
    c, fake = reader(browser, server_url, token)
    try:
        p = c.page
        p.locator("#brClose").click()
        d = p.locator("#brConfirm")
        assert d.is_visible() and "Close the book?" in str(d.text_content())
        assert p.evaluate("document.activeElement.id") == "brKeep"
        p.locator("#brKeep").click()
        assert d.is_hidden() and fake.to("POST", "/v1/book/close") == []
        assert p.evaluate("sessionStorage.getItem('jarvis_book_token')") == TOKEN
        p.locator("#brClose").click()
        p.keyboard.press("Escape")
        assert (
            d.is_hidden()
            and p.evaluate("document.activeElement.id") == "brClose"
            and fake.to("POST", "/v1/book/close") == []
        )
        p.locator("#brClose").click()
        with p.expect_navigation():
            p.locator("#brCloseNow").click()
        assert len(fake.to("POST", "/v1/book/close")) == 1
        assert p.evaluate("sessionStorage.getItem('jarvis_book_token')") is None
        assert p.evaluate("location.pathname") == "/"
    finally:
        c.close()


TABS_JS = """() => { const a = document.activeElement; return a.id || a.dataset.page || a.dataset.group || a.className; }"""
RING_JS = """() => { const s = getComputedStyle(document.activeElement); return [s.outlineStyle, parseFloat(s.outlineWidth)]; }"""


def test_the_tab_order_is_the_visual_order_and_focus_is_always_seen(
    browser: Any, server_url: str, token: str
) -> None:
    c, _ = reader(browser, server_url, token, at="pg_module_vault")
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


def test_a_phone_gets_the_contents_sheet_and_the_play_bar(
    browser: Any, server_url: str, token: str
) -> None:
    c, _ = reader(browser, server_url, token, viewport=PHONE, at="pg_module_vault")
    try:
        p = c.page
        assert (
            p.locator("#brRail").is_hidden()
            and p.locator("#brToc").is_hidden()
            and p.locator("#brMini").is_hidden()
        )
        p.locator("#brMenu").click()
        sheet = p.locator("#brSheet")
        sheet.locator("a[aria-current=page]").wait_for()
        assert sheet.is_visible() and sheet.locator("#brSheetSearch").is_visible()
        for el in [
            *sheet.locator("a[data-page]:visible, button:visible").all(),
            p.locator("#brSheetSearch"),
        ]:
            box = el.bounding_box()
            assert box is not None and box["height"] >= 44, el
        sheet.locator("a[data-page=pg_card_c07]").click()
        wait_title(c, "Attached documents")
        assert sheet.is_hidden()
        p.locator("#brFind").click()
        assert p.evaluate("document.activeElement.id") == "brSheetSearch"
        p.keyboard.type("expiry")
        sheet.locator("[role=option]").first.wait_for()
        p.keyboard.press("Escape")  # the list closes, the sheet stays
        assert sheet.is_visible() and sheet.locator(".bk-results").is_hidden()
        p.keyboard.press("Escape")
        p.keyboard.press("Escape")
        assert sheet.is_hidden()
        p.evaluate("location.hash = 'pg_module_vault'")
        wait_title(c, "Vault and documents")
        mini = p.locator("#brMini")
        assert mini.is_hidden()
        p.evaluate(
            "document.getElementById('brMain').scrollTop = document.getElementById('brSec-how').offsetTop"
        )
        mini.wait_for()
        assert "Vault and documents" in mini.inner_text()
        for sel in (
            "#brMenu",
            "#brFind",
            "#brTour",
            "#brClose",
            "#brMini .pbtn",
            "#brPage .bk-pn a",
            "#brPage details summary",
        ):
            box = p.locator(sel).first.bounding_box()
            assert box is not None and box["height"] >= 44 and box["width"] >= 44, sel
        assert p.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
        p.evaluate("document.getElementById('brMain').scrollTop = 0")
        mini.wait_for(state="hidden")
        clean(c)
    finally:
        c.close()


def test_without_a_token_the_reader_asks_for_nothing(
    browser: Any, server_url: str, token: str
) -> None:
    c, fake = reader(browser, server_url, token, seeded=False)
    try:
        c.page.locator("#bookRead[data-state=closed]").wait_for()
        assert c.page.locator("#brGate").is_visible() and fake.calls == []
        assert c.page.locator("#brPage").inner_text() == ""
        clean(c)
    finally:
        c.close()


def test_a_page_refused_mid_visit_ends_the_session_and_a_missing_one_says_so(
    browser: Any, server_url: str, token: str
) -> None:
    c, fake = reader(browser, server_url, token)
    try:
        p = c.page
        fake.page_answers["pg_card_c07"] = (
            404,
            {"error": "no_page", "detail": "That page isn't in this release."},
        )
        p.evaluate("location.hash = 'pg_card_c07'")
        p.locator("#brPage .bk-err", has_text="isn’t in this release").wait_for()
        assert (
            p.evaluate("sessionStorage.getItem('jarvis_book_token')") == TOKEN
        )  # a missing page is not a lost session
        fake.page_answers["pg_card_c42"] = (
            401,
            {"error": "session_gone", "detail": "The book session ended."},
        )
        p.evaluate("location.hash = 'pg_card_c42'")
        p.locator("#bookRead[data-state=closed]").wait_for()
        assert p.evaluate("sessionStorage.getItem('jarvis_book_token')") is None
        clean(c, 404, 401)
    finally:
        c.close()


def test_the_book_panel_no_longer_holds_the_old_full_book(
    browser: Any, server_url: str, token: str
) -> None:
    c = Console(browser, server_url, token, DESKTOP)
    fake = FakeBook(c.page)
    install(fake)
    try:
        c.open()
        c.page.evaluate(PASSKEY_STUB)
        c.open_panel("book")
        c.page.get_by_role("button", name="Open for me").click()
        c.page.get_by_role("button", name="Read the full book").wait_for()
        assert c.page.get_by_role("button", name="Short tour").is_visible()
        c.page.locator("#p-book .dsc", has_text="Limitations").first.click()
        c.page.wait_for_timeout(300)
        assert c.page.locator("#p-book .bk-pages, #p-book .bk-flow").count() == 0
        assert "more in the full book" not in str(c.page.locator("#p-book").text_content())
        assert fake.to("GET", "/v1/book/pages") == []
        assert (
            c.page.evaluate(
                "[...document.scripts].some((s) => s.src.includes('console-book-pages.js'))"
            )
            is False
        )
        assert c.page.evaluate("'JarvisBookPages' in window") is False
        clean(c)
    finally:
        c.close()


def test_every_small_book_page_opens_cleanly(browser: Any, server_url: str, token: str) -> None:
    c, _ = reader(browser, server_url, token)
    try:
        for pid, pg in PAGES.items():
            c.page.evaluate(f"location.hash = '{pid}'")
            wait_title(c, pg["title"])
            assert c.page.locator("#brPage .bk-sec").count() >= 4, pid
        clean(c)
    finally:
        c.close()


def gate(c: Console, sel: str, vp: str, what: str) -> None:
    """The console's visual gate (tests/test_ui_audit.py) on one part of the reader. The search
    box's "/" hint sits in the box's own right padding (aria-hidden, no pointer events, gone once
    the box has focus or words): the generic overlap probe's one known false positive here."""
    c.page.evaluate("() => document.fonts.ready.then(() => true)")
    c.page.evaluate(FINISH_ANIMATIONS_JS)
    res = c.page.evaluate(DOM_CHECKS_JS, sel)
    assert not res.get("missing"), what
    res["overlaps"] = [o for o in res["overlaps"] if "bk-kbd" not in o["a"] + o["b"]]
    _assert_clean(res, c.page.evaluate(NAMELESS_JS, sel), c.page.evaluate(WRAP_JS, sel), vp, what)


@pytest.mark.parametrize(
    ("size", "surface"), [(s, f) for s in ("laptop", "phone") for f in ("night", "day")]
)
def test_the_reader_passes_the_consoles_visual_gate(
    browser: Any, server_url: str, token: str, size: str, surface: str
) -> None:
    phone = size == "phone"
    c, _ = reader(browser, server_url, token, at="pg_module_vault", viewport=PHONE if phone else DESKTOP,
                  script=f"localStorage.setItem('jarvis_surface', '{surface}');")  # fmt: skip
    vp = "phone" if phone else "desktop"
    try:
        p = c.page
        assert p.locator("html").get_attribute("data-surface") == surface
        p.locator("#brPage svg.fl-svg").wait_for()
        gate(c, "#bookRead", vp, f"reader top {size} {surface}")
        p.evaluate(
            "document.getElementById('brMain').scrollTop = document.getElementById('brSec-how').offsetTop"
        )
        gate(c, "#bookRead", vp, f"reader at the flowchart {size} {surface}")
        if phone:
            p.locator("#brFind").click()
            p.keyboard.type("expiry")
            p.locator("#brSheet [role=option]").first.wait_for()
            gate(c, "#brSheet", vp, f"contents sheet and search {size} {surface}")
        else:
            p.locator("#brSearch").click()
            p.keyboard.type("expiry")
            p.locator("#brResults [role=option]").first.wait_for()
            gate(c, "#brResults", vp, f"search results {size} {surface}")
            gate(c, "#brTop", vp, f"top bar while searching {size} {surface}")
        clean(c)
    finally:
        c.close()
