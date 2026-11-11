# tests/browser/test_book_panel.py -- R6 D8, D9, D16 (docs/plans/r6-build-book.md): the Book panel
# against the Contract, stubbed with page.route (book_mocks.FakeBook; B and C build the real
# routes).
# Status (release, sealed releases, storage, last session), the open flow with the passkey bound to
# its audience, the stale sign-in hop to Google and the resume on ?reauth=done, passkey setup and
# reauth refusals, the owner's sections reader, an older release's code download with a ticket, the
# owner going on to the show, and Book settings. No JS errors, no CSP violations.
from __future__ import annotations

import json
from collections.abc import Iterator
from typing import Any

import pytest
from book_mocks import PASSKEY_STUB, TOKEN, FakeBook, script
from test_console import DESKTOP, PHONE, Console

_pw = pytest.importorskip("playwright.sync_api")

pytestmark = pytest.mark.browser


@pytest.fixture(scope="module")
def browser() -> Iterator[Any]:
    with _pw.sync_playwright() as p:
        b = p.chromium.launch()
        yield b
        b.close()


def _panel(
    browser: Any, url: str, token: str, viewport: dict[str, int] = DESKTOP, **status: Any
) -> tuple[Console, FakeBook]:
    c = Console(browser, url, token, viewport)
    fake = FakeBook(c.page, **status)
    c.open()
    c.page.evaluate(PASSKEY_STUB)
    c.open_panel("book")
    c.page.locator("#p-book .bk-release").wait_for()
    return c, fake


def _clean(c: Console, *expected: int) -> None:
    """No JS error, no CSP violation; the browser's own log line for an answer the test asked for
    (a 403 refusal, the unwired server's 503) is not an error of the page."""
    said = [f"status of {code} " for code in expected]
    errors = [e for e in c.errors if not any(s in e for s in said)]
    assert errors == [] and c.csp_violations() == []


@pytest.mark.parametrize("viewport", [DESKTOP, PHONE], ids=["desktop", "phone"])
def test_status_shows_the_release_the_sealed_books_and_the_two_opens(
    browser: Any, server_url: str, token: str, viewport: dict[str, int]
) -> None:
    c, _ = _panel(browser, server_url, token, viewport)
    try:
        body = c.page.locator("#p-book .pbody")
        assert "R6" in body.locator(".bk-release").inner_text()
        assert "3f2a1c9" in body.locator(".bk-release").inner_text()
        rows = body.locator(".bk-sealed li")
        assert rows.count() == 3
        assert "R5.1" in rows.nth(1).inner_text() and "MB" in rows.nth(1).inner_text()
        assert "13.1" in body.inner_text() and "60" in body.inner_text()
        last = body.locator(".bk-last").inner_text()  # D14: {last_closed_at, notified} only
        assert "Nov 9" in last and "conversation was deleted" in last and "undefined" not in last
        assert body.get_by_role("button", name="Open for me").is_visible()
        assert body.get_by_role("button", name="Show a guest").is_visible()
        _clean(c)
    finally:
        c.close()


def test_the_unwired_server_says_so_in_words(browser: Any, server_url: str, token: str) -> None:
    c = Console(browser, server_url, token, DESKTOP)
    try:
        c.open()
        # the real server has no encryption key: the book is off, and GET /v1/book says why with a
        # plain 200 {available: false, reason} (I1), so the console logs nothing at all
        c.open_panel("book")
        c.page.locator("#p-book .bk-note", has_text="no encryption key").wait_for()
        assert c.page.locator("#p-book button", has_text="Open for me").count() == 0
        _clean(c)
    finally:
        c.close()


def test_owner_open_uses_the_passkey_for_owner_then_reads_and_downloads(
    browser: Any, server_url: str, token: str
) -> None:
    c, fake = _panel(browser, server_url, token)
    try:
        c.page.get_by_role("button", name="Open for me").click()
        c.page.locator("#p-book .bk-reader").wait_for()
        assert c.page.evaluate("window.__proofs") == [["book_open", "owner"]]
        (opened,) = fake.to("POST", "/v1/book/open")
        assert opened["body"]["audience"] == "owner" and opened["body"]["proof"]["stub"] is True
        (sec,) = fake.to("GET", "/v1/book/sections")
        assert sec["headers"]["x-jarvis-book"] == TOKEN
        heads = c.page.locator("#p-book .bk-reader .dsc .dl").all_inner_texts()
        assert [h.lower() for h in heads][:3] == ["architecture", "stack", "libraries & licences"]
        lib = c.page.locator("#p-book .bk-reader .dsc", has_text="Libraries")
        lib.click()
        assert lib.get_attribute("aria-expanded") == "true"
        c.page.locator("#p-book .bk-flag", has_text="Non-commercial").first.wait_for()
        # the oldest kept release: its code, by a single-use ticket
        row = c.page.locator("#p-book .bk-sealed li", has_text="9b97eab")
        with c.page.expect_download() as dl:
            row.get_by_role("button", name="Download code").click()
        assert dl.value.suggested_filename == "JARVIS-source-9b97eab.zip"
        (ticket,) = fake.to("POST", "/v1/book/releases/9b97eab/ticket")
        assert ticket["headers"]["x-jarvis-book"] == TOKEN
        assert c.page.evaluate("sessionStorage.getItem('jarvis_book_token')") is None
        _clean(c)
    finally:
        c.close()


def test_the_owner_goes_on_to_the_show_with_the_token_in_this_tab(
    browser: Any, server_url: str, token: str
) -> None:
    c, fake = _panel(browser, server_url, token)
    try:
        fake.script_answer = (200, script("owner"))
        c.page.get_by_role("button", name="Open for me").click()
        c.page.locator("#p-book .bk-reader").wait_for()
        c.page.get_by_role("button", name="Start the show").click()
        c.page.wait_for_url("**/book/show")
        c.page.locator("#shStart").wait_for()
        assert c.page.evaluate("sessionStorage.getItem('jarvis_book_token')") == TOKEN
        _clean(c)
    finally:
        c.close()


def test_a_guest_open_replaces_the_console_page_in_this_tab(
    browser: Any, server_url: str, token: str
) -> None:
    """The owner's console is not left as the show tab's Back entry (no back/forward-cache view)."""
    c, fake = _panel(browser, server_url, token)
    try:
        before = c.page.evaluate("history.length")
        c.page.get_by_role("button", name="Show a guest").click()
        c.page.wait_for_url("**/book/show")
        c.page.locator("#shStart").wait_for()
        assert c.page.evaluate("history.length") == before
        assert c.page.evaluate("sessionStorage.getItem('jarvis_book_token')") == TOKEN
        _clean(c)
    finally:
        c.close()


def test_the_focus_stays_on_its_control_when_the_panel_redraws(
    browser: Any, server_url: str, token: str
) -> None:
    c, _ = _panel(browser, server_url, token)
    try:
        c.page.get_by_role("button", name="Open for me").click()
        c.page.locator("#p-book .bk-reader").wait_for()
        row = c.page.locator("#p-book .bk-sealed li", has_text="9b97eab")
        with c.page.expect_download():
            row.get_by_role("button", name="Download code").click()
        c.page.locator("#p-book .bk-note", has_text="Saved the code").wait_for()
        assert c.page.evaluate(
            "document.activeElement.textContent === 'Download code'"
            " && document.activeElement.closest('li').textContent.includes('9b97eab')"
        )
        c.page.locator("#p-book .bk-set .dsc").click()
        c.page.locator("#p-book .bsw[data-key=talk_on]").click()
        c.page.locator("#p-book .bk-setnote", has_text="Saved").wait_for()
        assert c.page.evaluate("document.activeElement.dataset.key") == "talk_on"
        _clean(c)
    finally:
        c.close()


def test_a_stale_sign_in_hops_to_google_and_the_guest_open_resumes(
    browser: Any, server_url: str, token: str
) -> None:
    c, fake = _panel(browser, server_url, token, open={"passkey_ready": True, "fresh_left_s": 0})
    login: list[str] = []

    def google(route: Any) -> None:  # Google's round trip, as /auth/callback answers it
        login.append(route.request.url)
        route.fulfill(status=302, headers={"Location": "/?reauth=done"})

    c.page.route("**/auth/login*", google)
    try:
        c.page.get_by_role("button", name="Show a guest").click()
        dialog = c.page.locator("dialog.bdialog[open]")
        dialog.wait_for()
        assert c.page.evaluate("window.__proofs") == []  # no passkey spent before the sign-in
        dialog.get_by_role("button", name="Sign in with Google").click()
        c.page.wait_for_url("**/?reauth=done")
        assert login and login[0].endswith("/auth/login?reauth=1")
        c.page.locator("#welcome").wait_for()
        pending = json.loads(c.page.evaluate("sessionStorage.getItem('jarvis_book_pending')"))
        assert pending["audience"] == "guest"
        resume = c.page.locator("#p-book .bk-resume")
        resume.wait_for()
        assert "Signed in again" in resume.inner_text()
        c.page.evaluate(PASSKEY_STUB)
        fake.status["open"] = {"passkey_ready": True, "fresh_left_s": 290}
        resume.get_by_role("button", name="Use my passkey").click()
        c.page.wait_for_url("**/book/show")
        assert c.page.evaluate("sessionStorage.getItem('jarvis_book_pending')") is None
        assert c.page.evaluate("sessionStorage.getItem('jarvis_book_token')") == TOKEN
        (opened,) = fake.to("POST", "/v1/book/open")
        assert opened["body"]["audience"] == "guest"
        assert opened["body"]["proof"] == {"purpose": "book_open", "target": "guest", "stub": True}
    finally:
        c.close()


def test_a_reauth_refusal_after_the_passkey_also_offers_the_sign_in(
    browser: Any, server_url: str, token: str
) -> None:
    c, fake = _panel(browser, server_url, token)
    try:
        fake.open_answers.append(
            (403, {"error": "reauth_required", "detail": "Sign in with Google again first."})
        )
        c.page.get_by_role("button", name="Open for me").click()
        dialog = c.page.locator("dialog.bdialog[open]")
        dialog.wait_for()
        assert "Sign in with Google again" in dialog.inner_text()
        dialog.get_by_role("button", name="Not now").click()
        assert c.page.evaluate("sessionStorage.getItem('jarvis_book_pending')") is None
        _clean(c, 403)
    finally:
        c.close()


def test_no_passkey_points_to_permissions_and_never_falls_back(
    browser: Any, server_url: str, token: str
) -> None:
    c, fake = _panel(browser, server_url, token, open={"passkey_ready": False, "fresh_left_s": 200})
    try:
        fake.open_answers.append(
            (403, {"error": "passkey_setup_needed", "detail": "Set up a passkey first."})
        )
        c.page.get_by_role("button", name="Show a guest").click()
        note = c.page.locator("#p-book .bk-note.bad")
        note.wait_for()
        assert "passkey" in note.inner_text().lower()
        assert c.page.evaluate("window.__proofs") == []
        c.page.locator("#p-book").get_by_role("button", name="Set up a passkey").click()
        c.page.locator("#p-approvals").wait_for(state="visible")
        _clean(c, 403)
    finally:
        c.close()


def test_settings_save_the_creator_name_and_ask_before_a_training_brain(
    browser: Any, server_url: str, token: str
) -> None:
    c, fake = _panel(browser, server_url, token)
    try:
        c.page.locator("#p-book .bk-set .dsc").click()
        name = c.page.locator("#bkCreator")
        name.fill("Akira Tester")
        c.page.locator("#p-book").get_by_role("button", name="Save name").click()
        c.page.locator("#p-book .bk-setnote", has_text="Saved").wait_for()
        (put,) = fake.to("PUT", "/v1/book/settings")
        assert put["body"] == {"creator_name": "Akira Tester"}
        c.page.locator("#p-book .bsw[data-key=allow_training_brain]").click()
        dialog = c.page.locator("dialog.bdialog[open]")
        dialog.wait_for()
        dialog.get_by_role("button", name="Keep it off").click()
        assert len(fake.to("PUT", "/v1/book/settings")) == 1  # nothing changed without a yes
        _clean(c)
    finally:
        c.close()


# ---- R6.1 decision 3: the version sits next to the commit id; sealed R6 rows have none --------
R61 = {
    "id": "8308815",
    "label": "R6.1",
    "version": "v6.1.0",
    "sha": "8308815" + "0" * 33,
    "committed_at": "2026-11-11T09:00:00+05:30",
}
R61_ROW = {k: R61[k] for k in ("id", "label", "version")} | {
    "sealed_at": "2026-11-11T09:12:00+05:30",
    "mb": 4.7,
}
R6_ROW = {"id": "37c3bfd", "label": "R6", "sealed_at": "2026-11-10T19:40:00+05:30", "mb": 4.6}


def test_the_release_and_its_sealed_row_show_the_version_next_to_the_id(
    browser: Any, server_url: str, token: str
) -> None:
    c, _ = _panel(browser, server_url, token, release=R61, sealed=[R61_ROW, R6_ROW])
    try:
        body = c.page.locator("#p-book .pbody")
        assert body.locator(".bk-release .ihead b").inner_text() == "R6.1 · v6.1.0 · 8308815"
        names = [t.strip() for t in body.locator(".bk-sealed li .bk-rtxt b").all_inner_texts()]
        assert names == ["R6.1 · v6.1.0 · 8308815", "R6 · 37c3bfd"]  # an R6 row: as before
        _clean(c)
    finally:
        c.close()


def test_a_bad_version_is_never_shown(browser: Any, server_url: str, token: str) -> None:
    bad = {**R61, "version": "<img src=x onerror=alert(1)>"}
    c, _ = _panel(browser, server_url, token, release=bad, sealed=[])
    try:
        head = c.page.locator("#p-book .bk-release .ihead b")
        assert head.inner_text() == "R6.1 · 8308815"
        assert c.page.locator("#p-book img").count() == 0
        _clean(c)
    finally:
        c.close()
