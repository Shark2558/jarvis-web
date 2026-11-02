# tests/browser/test_attach.py — slice 10 E in a real browser against the real backend (mock brain):
# paperclip → chip (Reading… → ready) → send → the file tag under the message and its text in the
# reply; plain errors for an unsupported file (refused in the page) and for a file the server
# refuses; removing a chip; drag-and-drop onto the Conversation panel. No console errors, no CSP
# violations.
from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest
from test_console import DESKTOP, PHONE, Console  # same directory (pytest prepend import)

_pw = pytest.importorskip("playwright.sync_api")
sync_playwright = _pw.sync_playwright

pytestmark = pytest.mark.browser


@pytest.fixture(scope="module")
def browser() -> Iterator[Any]:
    with sync_playwright() as p:
        b = p.chromium.launch()
        yield b
        b.close()


@pytest.fixture
def console(browser: Any, server_url: str, token: str) -> Iterator[Console]:
    c = Console(browser, server_url, token, DESKTOP)
    yield c
    c.close()


def _attach(c: Console, name: str, data: bytes, mime: str = "text/plain") -> None:
    c.page.locator("#attachInput").set_input_files(
        files=[{"name": name, "mimeType": mime, "buffer": data}]
    )


def _ready_chip(c: Console, name: str) -> Any:
    chip = c.page.locator('#attachChips .achip[data-state="ready"]', has_text=name)
    chip.wait_for()
    return chip


def test_attach_shows_a_chip_then_sends_the_file_with_the_message(console: Console) -> None:
    console.open()
    _attach(console, "lease notes.txt", b"Rent is due on the 5th of every month.")
    chip = _ready_chip(console, "lease notes.txt")
    assert "word" in str(chip.locator(".ameta").text_content())
    assert (
        console.page.locator("#input").get_attribute("placeholder") == "Ask about the attached file"
    )
    reply = console.send("When is rent due?")
    assert (
        "Rent is due on the 5th" in reply
    )  # the mock brain echoes what it was given: the file too
    tag = console.page.locator(".row.user .meta .afile")
    assert tag.count() == 1 and tag.text_content() == "lease notes.txt"
    assert console.page.locator("#attachChips").is_hidden()
    assert console.page.locator("#input").get_attribute("placeholder") == "Message JARVIS"
    assert console.csp_violations() == [] and console.errors == []


def test_an_unsupported_file_gets_a_plain_error_and_no_chip(console: Console) -> None:
    console.open()
    uploads: list[str] = []
    console.page.on(
        "request", lambda r: uploads.append(r.url) if "/v1/attachments" in r.url else None
    )
    _attach(console, "setup.exe", b"MZ\x90\x00", "application/octet-stream")
    err = console.page.locator("#attachErr")
    err.wait_for()
    assert "JARVIS can read PDF, Word (.docx)" in str(err.text_content())
    assert console.page.locator("#attachChips .achip").count() == 0 and uploads == []
    # the server's own refusal (a "PDF" that is really text) reads just as plainly
    _attach(console, "fake.pdf", b"just some text", "application/pdf")
    console.page.locator("#attachErr", has_text="don't match its name").wait_for()
    assert console.page.locator("#attachChips .achip").count() == 0
    assert console.csp_violations() == []


def test_removing_a_chip_deletes_the_waiting_upload(console: Console) -> None:
    console.open()
    _attach(console, "draft.md", b"# Draft\nSecond line.")
    chip = _ready_chip(console, "draft.md")
    with console.page.expect_request(
        lambda r: r.method == "DELETE" and "/v1/attachments/doc_" in r.url
    ):
        chip.locator(".arm").click()
    assert console.page.locator("#attachChips .achip").count() == 0
    assert console.page.locator("#attachChips").is_hidden()
    assert console.page.evaluate("document.activeElement.id") == "attachBtn"


def test_a_phone_composer_with_a_long_named_chip_has_no_horizontal_scroll(
    browser: Any, server_url: str, token: str
) -> None:
    c = Console(browser, server_url, token, PHONE)
    try:
        c.open()
        long_name = "Kerala Unified Registry programme operations manual final v7.txt"
        _attach(c, long_name, b"Operations manual text.")
        chip = _ready_chip(c, "Kerala Unified")
        widths = c.page.evaluate(
            "[document.documentElement.scrollWidth, document.body.scrollWidth, window.innerWidth]"
        )
        assert widths[0] <= widths[2] and widths[1] <= widths[2], widths
        box = chip.bounding_box()
        assert box is not None and box["x"] >= 0 and box["x"] + box["width"] <= PHONE["width"]
        assert c.page.locator("#attachBtn").is_visible() and c.page.locator("#send").is_visible()
        assert c.errors == []
    finally:
        c.close()


def test_dropping_a_file_on_the_conversation_panel_attaches_it(console: Console) -> None:
    console.open()
    console.page.evaluate(
        """() => {
          const dt = new DataTransfer();
          dt.items.add(new File(['name,amount\\nAsha,1200\\n'], 'dues.csv', { type: 'text/csv' }));
          const zone = document.getElementById('p-chat');
          const opts = { dataTransfer: dt, bubbles: true, cancelable: true };
          for (const type of ['dragenter', 'dragover', 'drop']) {
            zone.dispatchEvent(new DragEvent(type, opts));
          }
        }"""
    )
    _ready_chip(console, "dues.csv")
    assert "dropping" not in str(console.page.locator("#p-chat").get_attribute("class"))
    assert console.errors == []
