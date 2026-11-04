# tests/browser/test_permissions_rows.py -- R1 B (plan D9): Approvals -> Permissions never drops a
# row. The server sends every group (tests/test_permissions_rows_listed.py); the console used to
# drop, without a word, any group whose choices it did not recognise (console-permissions.js
# normal()), and gave a row no hook a test or the owner could rely on. Now:
#   * every server group id is a row with data-group="<id>", at 390 px and at desktop width
#   * an unrecognised choice set -> the row stays, read-only, "Reload the page to change this"
#   * an unavailable feature -> the note sits under the hint and the control stays usable
# GET /v1/permissions is rewritten in the page (page.route); the PUT goes to the real server.
from __future__ import annotations

import json
from typing import Any

import pytest
from test_console import DESKTOP, PHONE, Console  # same directory (pytest prepend import)

from jarvis.permissions.groups import GROUPS

_pw = pytest.importorskip("playwright.sync_api")
sync_playwright = _pw.sync_playwright

pytestmark = pytest.mark.browser


@pytest.fixture(scope="module")
def browser() -> Any:
    with sync_playwright() as p:
        b = p.chromium.launch()
        yield b
        b.close()


def _open(c: Console) -> None:
    c.open()
    c.open_panel("approvals")
    btn = c.page.locator("#permSetBtn")
    if btn.get_attribute("aria-expanded") != "true":
        btn.click()
    c.page.locator("#permGroups .pgrp").first.wait_for()


def _set_whatsapp(c: Console, token: str, choice: str) -> None:
    c.page.evaluate(
        "([t, v]) => fetch('/v1/permissions', {method: 'PUT', headers: {'Content-Type': "
        "'application/json', 'Authorization': 'Bearer ' + t, 'X-Requested-With': 'JARVIS'}, "
        "body: JSON.stringify({groups: {whatsapp: v}})})",
        [token, choice],
    )


def _rewrite(c: Console, change: Any) -> None:
    """Answer GET /v1/permissions with the real body after `change(body)`; pass the rest on."""

    def handler(route: Any) -> None:
        if route.request.method != "GET":
            route.continue_()
            return
        resp = route.fetch()
        body = json.loads(resp.text())
        change(body)
        route.fulfill(response=resp, body=json.dumps(body))

    c.page.route("**/v1/permissions", handler)


@pytest.mark.parametrize("viewport", [PHONE, DESKTOP], ids=["390px", "desktop"])
def test_every_server_group_is_a_visible_row(
    browser: Any, server_url: str, token: str, viewport: dict[str, int]
) -> None:
    c = Console(browser, server_url, token, viewport)
    try:
        _open(c)
        page = c.page
        ids = [g.id for g in GROUPS]
        shown = page.locator("#permGroups .pgrp").evaluate_all(
            "els => els.map(e => e.dataset.group)"
        )
        assert shown == ids  # same rows, same order, none dropped
        whatsapp = page.locator('#permGroups [data-group="whatsapp"]')
        whatsapp.scroll_into_view_if_needed()
        assert whatsapp.is_visible()
        assert "Write WhatsApp drafts" in str(whatsapp.text_content())
        assert whatsapp.locator(".seg-opt").all_text_contents() == ["Allow", "Ask first", "Never"]
        assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth + 1")
        assert c.csp_violations() == [] and c.errors == []
    finally:
        c.close()


def test_a_row_with_choices_the_page_does_not_know_is_kept_read_only(
    browser: Any, server_url: str, token: str
) -> None:
    def change(body: dict[str, Any]) -> None:
        for g in body["groups"]:
            if g["id"] == "whatsapp":
                g["choices"] = ["limit"]  # a vocabulary this page has never heard of
                g["effect"] = "limit"

    c = Console(browser, server_url, token, DESKTOP)
    try:
        _rewrite(c, change)
        _open(c)
        row = c.page.locator('#permGroups [data-group="whatsapp"]')
        row.wait_for()
        assert "Write WhatsApp drafts" in str(row.text_content())
        assert "Reload the page to change this" in str(row.text_content())
        assert row.locator("input[type=radio]").count() == 0
        others = c.page.locator("#permGroups .pgrp").count()
        assert others == len(GROUPS)
        assert c.errors == []
    finally:
        c.close()


def test_a_row_with_no_choices_at_all_is_kept_read_only(
    browser: Any, server_url: str, token: str
) -> None:
    def change(body: dict[str, Any]) -> None:
        for g in body["groups"]:
            if g["id"] == "whatsapp":
                g["choices"] = []

    c = Console(browser, server_url, token, PHONE)
    try:
        _rewrite(c, change)
        _open(c)
        row = c.page.locator('#permGroups [data-group="whatsapp"]')
        row.wait_for()
        assert "Reload the page to change this" in str(row.text_content())
    finally:
        c.close()


def test_an_unavailable_feature_shows_its_note_and_stays_usable(
    browser: Any, server_url: str, token: str
) -> None:
    note = "Drafts by name also need the Contacts Grant in Integrations."

    def change(body: dict[str, Any]) -> None:
        for g in body["groups"]:
            if g["id"] == "whatsapp":
                g["available"] = False
                g["note"] = note

    c = Console(browser, server_url, token, DESKTOP)
    try:
        _rewrite(c, change)
        _open(c)
        row = c.page.locator('#permGroups [data-group="whatsapp"]')
        row.wait_for()
        shown = row.locator(".pgnote")
        assert shown.text_content() == note
        small = "e => e.compareDocumentPosition(e.parentElement.querySelector('.pgnote'))"
        assert row.locator("small").first.evaluate(small) & 4  # the note follows the hint
        never = row.get_by_text("Never", exact=True)
        never.click()  # the control is usable: Never can be pre-set
        c.page.locator("#permNote", has_text="Write WhatsApp drafts: Never.").wait_for()
        assert row.locator("input[value=deny]").is_checked()
        assert row.locator(".pgnote").text_content() == note  # a change keeps the note
        # a group without a note shows none
        assert c.page.locator('#permGroups [data-group="memory_save"] .pgnote').count() == 0
    finally:
        c.close()


def test_integrations_always_has_a_whatsapp_drafts_line(
    browser: Any, server_url: str, token: str
) -> None:
    """R1 D9: the line is there even with no Google link; the row set to Never says so, and Open
    takes the owner to that row in Approvals -> Permissions."""
    c = Console(browser, server_url, token, DESKTOP)
    try:
        c.open()
        _set_whatsapp(c, token, "allow")  # the server is shared with the other tests of this file
        c.open()
        c.open_panel("integrations")
        line = c.page.locator("#waLine")
        line.wait_for()
        assert "WhatsApp drafts" in str(line.text_content())
        assert "Ready for typed numbers" in str(line.text_content())
        _set_whatsapp(c, token, "deny")
        c.open()
        c.open_panel("integrations")
        c.page.locator("#waLine", has_text="Switched off in Permissions").wait_for()
        c.page.locator("#waOpen").click()
        c.page.locator('#permGroups [data-group="whatsapp"]').wait_for()
        assert c.page.locator('#permGroups [data-group="whatsapp"] input[value=deny]').is_checked()
        assert c.csp_violations() == [] and c.errors == []
    finally:
        c.close()
