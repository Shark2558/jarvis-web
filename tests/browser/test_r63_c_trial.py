# tests/browser/test_r63_c_trial.py -- R6.3 Part C, row "23 Nov · trial" (console half;
# docs/plans/r6-3-book-content.md D6, D5's step, D8's rupees): Book settings -> Book writer ->
# Writer trial in a real Chromium against C's fake server (tests/r63_fakes_c.py):
#   - the estimate comes first: about Rs 40 (Rs 26-52), the Rs 100 cap, the time, what is sent
#     and to whom, the GST note; nothing is asked of the trial routes before his YES
#   - the YES box is empty, sends exactly what he typed, and "yes" is refused by the SERVER (the
#     console shows its words and nothing starts); "Not now" sends nothing
#   - his YES starts it; "Step while I watch" steps while Book settings is open, 6 a minute at most
#   - a stale estimate asks again; offline says so
#   - the side by side: both brains' five pages with their checks, Rs and seconds; one sample page
from __future__ import annotations

import json
import os
from collections.abc import Iterator
from typing import Any

import pytest
from book_mocks import PASSKEY_STUB, FakeBook
from r63_fake_server import TRIAL_ESTIMATE
from r63_fakes_c import STALE_ESTIMATE, route_c, seen, serve_c, set_state, until
from test_console import Console

_pw = pytest.importorskip("playwright.sync_api")
pytestmark = pytest.mark.browser
LAPTOP = {"width": 1280, "height": 800}
WRITER = "#p-book .bk-writer"


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


def writer_open(
    browser: Any, url: str, token: str, *, clock: bool = False, **state: Any
) -> tuple[Console, list[dict[str, Any]]]:
    """The Book panel with the writer's disclosure open; every writer request the page sent."""
    set_state(url, reset=True, **state)
    c = Console(browser, url, token, LAPTOP)
    if clock:
        c.page.clock.install()
    sent: list[dict[str, Any]] = []

    def note(req: Any) -> None:
        if "/v1/book/writer" in req.url:
            body = req.post_data
            sent.append(
                {"method": req.method, "url": req.url, "body": json.loads(body) if body else None}
            )

    c.page.on("request", note)
    FakeBook(c.page)
    route_c(c.page)
    c.open()
    c.page.evaluate(PASSKEY_STUB)
    c.open_panel("book")
    head = c.page.locator(f"{WRITER} .dsc").first
    head.wait_for()
    head.click()
    return c, sent


def text(c: Console) -> str:
    return str(c.page.locator(WRITER).inner_text())


def posts(sent: list[dict[str, Any]], tail: str) -> list[dict[str, Any]]:
    return [s for s in sent if s["method"] != "GET" and s["url"].split("?")[0].endswith(tail)]


def clean(c: Console, *expected: int) -> None:
    said = [f"status of {code} " for code in expected]
    errors = [e for e in c.errors if not any(s in e for s in said)]
    assert errors == [] and c.csp_violations() == []


def test_r63_c_trial_the_estimate_what_is_sent_and_to_whom_come_first(
    browser: Any, c_url: str, token: str
) -> None:
    c, sent = writer_open(browser, c_url, token)
    try:
        until(c.page, lambda: "About ₹40" in text(c), "the estimate")
        words = text(c)
        assert "₹26–52" in words and "₹100" in words  # the range and the cap
        assert "6–10 minutes" in words and "Book settings open" in words
        assert "JARVIS's public code and its facts only" in words  # sent_to, the server's words
        assert "may add 18 % GST" in words and "$" not in words
        assert c.page.locator(WRITER).get_by_role("button", name="Start the trial").is_visible()
        assert posts(sent, "/trial") == [] and seen(c_url)["calls"] == []
        clean(c)
    finally:
        c.close()


def test_r63_c_trial_the_yes_box_refuses_yes_by_the_servers_word(
    browser: Any, c_url: str, token: str
) -> None:
    c, sent = writer_open(browser, c_url, token)
    try:
        c.page.locator(WRITER).get_by_role("button", name="Start the trial").click()
        dialog = c.page.locator("#bookYesDialog")
        dialog.wait_for()
        box = dialog.locator("#bookYes")
        assert box.input_value() == ""  # never pre-filled
        assert "About ₹40" in dialog.inner_text() and "₹100" in dialog.inner_text()
        box.fill("yes")
        dialog.get_by_role("button", name="Start").click()
        dialog.get_by_text("Type YES in capitals to go ahead.").wait_for()  # the server's words
        (refused,) = posts(sent, "/trial")
        assert refused["body"] == {"typed": "yes", "estimate_id": TRIAL_ESTIMATE}  # as typed
        assert (
            seen(c_url)["calls"] == [] and seen(c_url)["run"]["state"] == "none"
        )  # nothing starts
        dialog.get_by_role("button", name="Not now").click()
        until(c.page, lambda: not dialog.is_visible(), "the dialog to close")
        assert len(posts(sent, "/trial")) == 1  # "Not now" sends nothing
        clean(c, 422)
    finally:
        c.close()


def test_r63_c_trial_yes_starts_it_and_steps_while_i_watch(
    browser: Any, c_url: str, token: str
) -> None:
    c, sent = writer_open(browser, c_url, token, clock=True)
    try:
        c.page.locator(WRITER).get_by_role("button", name="Start the trial").click()
        dialog = c.page.locator("#bookYesDialog")
        dialog.locator("#bookYes").fill(" YES ")  # the server trims; the page sends it as typed
        dialog.get_by_role("button", name="Start").click()
        until(c.page, lambda: "1 of 10 pages" in text(c), "the first step")
        (started,) = posts(sent, "/trial")
        assert started["body"] == {"typed": " YES ", "estimate_id": TRIAL_ESTIMATE}
        assert seen(c_url)["calls"] == ["trial"]
        assert len(posts(sent, "/step")) == 1  # one step at once, then the 10 s gap (6 a minute)
        c.page.clock.fast_forward(11_000)
        until(c.page, lambda: "2 of 10 pages" in text(c), "the second step")
        c.page.locator(WRITER).get_by_role("button", name="Pause watching").click()
        c.page.clock.fast_forward(30_000)
        c.page.wait_for_timeout(300)
        assert len(posts(sent, "/step")) == 2  # paused: no step
        c.page.locator(WRITER).get_by_role("button", name="Step while I watch").click()
        until(c.page, lambda: "3 of 10 pages" in text(c), "the step resumed")
        c.page.locator(f"{WRITER} .dsc").first.click()  # Book writer closed: the stepping stops
        c.page.clock.fast_forward(30_000)
        c.page.wait_for_timeout(300)
        assert len(posts(sent, "/step")) == 3
        clean(c)
    finally:
        c.close()


def test_r63_c_trial_a_stale_estimate_asks_again(browser: Any, c_url: str, token: str) -> None:
    c, sent = writer_open(browser, c_url, token, stale={"trial": 1})
    try:
        c.page.locator(WRITER).get_by_role("button", name="Start the trial").click()
        dialog = c.page.locator("#bookYesDialog")
        dialog.locator("#bookYes").fill("YES")
        dialog.get_by_role("button", name="Start").click()
        dialog.get_by_text("The estimate changed").wait_for()  # asked again, with the new one
        assert dialog.locator("#bookYes").input_value() == ""
        dialog.locator("#bookYes").fill("YES")
        dialog.get_by_role("button", name="Start").click()
        until(c.page, lambda: seen(c_url)["calls"] == ["trial"], "the trial to start")
        ids = [p["body"]["estimate_id"] for p in posts(sent, "/trial")]
        assert ids == [STALE_ESTIMATE, TRIAL_ESTIMATE]
        clean(c, 409)
    finally:
        c.close()


def test_r63_c_trial_offline_says_so_and_nothing_starts(
    browser: Any, c_url: str, token: str
) -> None:
    c, _ = writer_open(browser, c_url, token)
    try:
        c.page.locator(WRITER).get_by_role("button", name="Start the trial").click()
        dialog = c.page.locator("#bookYesDialog")
        dialog.locator("#bookYes").fill("YES")
        c.ctx.set_offline(True)
        dialog.get_by_role("button", name="Start").click()
        dialog.get_by_text("Can’t reach JARVIS. Check your connection.").wait_for()
        c.ctx.set_offline(False)
        assert seen(c_url)["calls"] == []
        assert [e for e in c.errors if "ERR_INTERNET_DISCONNECTED" not in e] == []
    finally:
        c.close()


def test_r63_c_trial_side_by_side_with_checks_and_one_sample_page(
    browser: Any, c_url: str, token: str
) -> None:
    c, _ = writer_open(browser, c_url, token, trial_done=True)
    try:
        until(c.page, lambda: "Passed after one redraft" in text(c), "the side by side")
        words = text(c)
        for title in ("Chapter example", "Card C16", "Module wardrobe", "Screen vitals"):
            assert title.lower() in words.lower(), (
                title
            )  # the headings are upper-cased by the style
        rows = c.page.locator(f"{WRITER} .bev")
        assert rows.count() == 10
        assert "Claude" in rows.nth(0).inner_text() and "Gemini (free)" in rows.nth(1).inner_text()
        assert "Passed every check the first time" in words
        assert "a number typed instead of taken from the code" in words  # nn 4's first try
        assert "Refused: a file or name that is not in the code" in words  # nn 9
        assert "₹7.60" in words and "38 s" in words and "₹0" in words
        rows.nth(1).get_by_role("button", name="Read").click()
        until(
            c.page,
            lambda: "Written by Gemini (free) (balanced tier, gemini-3.8-flash)" in text(c),
            "the page",
        )
        heads = c.page.locator(
            f"{WRITER} .bk-sec .dl"
        ).all_text_contents()  # as written, not as styled
        assert "In plain words" in heads and "Example (made up)" in heads
        clean(c)
    finally:
        c.close()
