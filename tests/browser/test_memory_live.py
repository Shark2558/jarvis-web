# tests/browser/test_memory_live.py — the Memory panel against the REAL /v1/memory backend.
# test_memory.py pins the console's side of the contract with a page.route fake; this file drives
# the same panel with no fake at all, so a drift between fake and real API fails here. Covers:
# add → badge → pin → edit → two-step delete, a sensitive refusal in the server's own words, About
# you save, the learning consent round trip, the "Used N memories" chip on a real reply, and Forget
# everything — with 0 JS errors.
from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pytest
from test_console import Console
from test_memory import _main, _quiet_errors, _row, _settings, browser, make  # noqa: F401

_pw = pytest.importorskip("playwright.sync_api")
expect = _pw.expect

pytestmark = pytest.mark.browser


def _fresh(c: Console) -> Any:
    """Start every live test from an empty memory (the server is shared by the module)."""
    page = c.page
    status = page.evaluate(
        """async (t) => (await fetch('/v1/memory', {method: 'DELETE', headers: {
            'Authorization': 'Bearer ' + t, 'X-Requested-With': 'JARVIS',
            'Content-Type': 'application/json'},
            body: JSON.stringify({confirm: 'FORGET'})})).status""",
        c.token,
    )
    assert status in (200, 204), status
    return page


def _view(c: Console) -> Any:
    return c.page.evaluate(
        """async (t) => (await fetch('/v1/memory',
            {headers: {'Authorization': 'Bearer ' + t}})).json()""",
        c.token,
    )


def test_live_add_pin_edit_delete_and_refusal(make: Callable[..., Console]) -> None:  # noqa: F811
    c = make()
    c.open()
    page = _fresh(c)
    _main(c)
    page.locator("#memAddText").fill("My favourite colour is teal.")
    page.locator("#memAddCat").select_option("preferences")
    page.locator("#memAddBtn").click()
    row = _row(c, "favourite colour is teal")
    row.wait_for()
    expect(row.locator(".mbadge")).to_have_text("added by you")
    # pin toggles against the real PATCH
    pin = row.get_by_role("button", name="Pin")
    before = pin.get_attribute("aria-pressed")
    pin.click()
    expect(pin).not_to_have_attribute("aria-pressed", str(before))
    # edit inline
    row.get_by_role("button", name="Edit").click()
    page.locator("#memList .medit textarea").fill("My favourite colour is deep teal.")
    page.locator("#memList .medit").get_by_role("button", name="Save").click()
    _row(c, "deep teal").wait_for()
    # the real server refuses a card number in its own plain words, not "[object Object]"
    page.locator("#memAddText").fill("My card is 4111 1111 1111 1111")
    page.locator("#memAddBtn").click()
    err = page.locator("#memAddErr")
    expect(err).not_to_have_text("")
    assert "object" not in str(err.text_content()).lower()
    assert _row(c, "4111").count() == 0
    # two-step delete
    _row(c, "deep teal").locator("[id^=mfDel-]").click()
    _row(c, "deep teal").locator("[id^=mfDelYes-]").click()
    expect(_row(c, "deep teal")).to_have_count(0)
    assert _quiet_errors(c) == []


def test_live_about_you_and_learning_consent(make: Callable[..., Console]) -> None:  # noqa: F811
    c = make()
    c.open()
    page = _fresh(c)
    _main(c)
    ta = page.locator("#memP-about")
    ta.fill("Akash. Call me Sir. Project lead in Thiruvananthapuram.")
    page.locator("#p-memory").get_by_role("button", name="Save").first.click()
    page.wait_for_timeout(600)
    view = _view(c)
    assert view["profile"]["about"].startswith("Akash. Call me Sir.")
    # learning: the dialog first, then the real PUT with confirm_spend
    _settings(c)
    page.locator("#memLearn").click()
    dialog = page.locator("#memoryDialog")
    dialog.wait_for(state="visible")
    assert "₹" in str(dialog.text_content()) or "rupee" in str(dialog.text_content()).lower()
    page.locator("#memoryDialogYes").click()
    page.wait_for_timeout(600)
    view = _view(c)
    assert view["settings"]["learn"] is True
    assert _quiet_errors(c) == []


def test_live_reply_chip_lists_the_memories_sent(make: Callable[..., Console]) -> None:  # noqa: F811
    c = make()
    c.open()
    page = _fresh(c)
    _main(c)
    page.locator("#memAddText").fill("My daughter's school is in Kowdiar.")
    page.locator("#memAddCat").select_option("people")
    page.locator("#memAddBtn").click()
    _row(c, "Kowdiar").wait_for()
    c.open_panel("chat")
    c.send("Where is my daughter's school?")
    page.get_by_text("Used 1 memory", exact=True).first.wait_for(timeout=15000)
    assert _quiet_errors(c) == []
