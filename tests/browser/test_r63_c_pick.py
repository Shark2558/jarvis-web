# tests/browser/test_r63_c_pick.py -- R6.3 Part C, row "23 Nov · pick" (console half;
# docs/plans/r6-3-book-content.md D7, D11's storage line, D12's Update, H2) in a real Chromium
# against C's fake server (tests/r63_fakes_c.py):
#   - the caps filled with the proposed defaults (Rs 1,500 / 500 / 1,000 / 80 %), the tier never
#     offered, the Gemini pick its own consent
#   - the first save, a raise, a paid brain and "update by itself" each show the SERVER's Rs words
#     and the YES box; "Keep" sends nothing; the YES resends the same pick with its terms_id;
#     lowering saves at once
#   - the first write's second YES on its estimate; Update's YES; Stop; a refusal's words under
#     the button; the 80 % storage line at the top of the panel
from __future__ import annotations

import json
import os
from collections.abc import Iterator
from typing import Any

import pytest
from book_mocks import PASSKEY_STUB, FakeBook
from r63_fake_server import FIRST_ESTIMATE, UPDATE_ESTIMATE
from r63_fakes_c import route_c, seen, serve_c, set_state, until
from test_console import Console

_pw = pytest.importorskip("playwright.sync_api")
pytestmark = pytest.mark.browser
LAPTOP = {"width": 1280, "height": 800}
WRITER = "#p-book .bk-writer"
DEFAULTS = {"trial": 100, "first": 1500, "release": 500, "month": 1000, "limit_pct": 80}


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


def writer_open(browser: Any, url: str, token: str, **state: Any) -> tuple[Console, list[Any]]:
    set_state(url, reset=True, **state)
    c = Console(browser, url, token, LAPTOP)
    sent: list[dict[str, Any]] = []

    def note(req: Any) -> None:
        if "/v1/book/writer" in req.url and req.method != "GET":
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
    c.page.locator("#bkCapFirst").wait_for()
    return c, sent


def text(c: Console) -> str:
    return str(c.page.locator(WRITER).inner_text())


def puts(sent: list[dict[str, Any]]) -> list[Any]:
    return [s["body"] for s in sent if s["method"] == "PUT"]


def save(c: Console) -> None:
    c.page.locator(WRITER).get_by_role("button", name="Save the pick").click()


def confirm(c: Console, typed: str = "YES") -> Any:
    dialog = c.page.locator("#bookYesDialog")
    dialog.wait_for()
    assert dialog.locator("#bookYes").input_value() == ""
    dialog.locator("#bookYes").fill(typed)
    dialog.get_by_role("button", name="Confirm").click()
    return dialog


def keep(c: Console) -> None:
    dialog = c.page.locator("#bookYesDialog")
    dialog.wait_for()
    dialog.get_by_role("button", name="Keep").click()
    until(c.page, lambda: not dialog.is_visible(), "the dialog to close")


def clean(c: Console, *expected: int) -> None:
    said = [f"status of {code} " for code in expected]
    errors = [e for e in c.errors if not any(s in e for s in said)]
    assert errors == [] and c.csp_violations() == []


def confirmed_pick(c: Console) -> None:
    save(c)
    confirm(c)
    until(c.page, lambda: "Saved." in text(c), "the pick saved")


def test_r63_c_pick_the_caps_are_filled_with_the_defaults(
    browser: Any, c_url: str, token: str
) -> None:
    c, sent = writer_open(browser, c_url, token)
    try:
        values = {
            k: c.page.locator(f"#bkCap{k}").input_value()
            for k in ("First", "Release", "Month", "Pct")
        }
        assert values == {"First": "1500", "Release": "500", "Month": "1000", "Pct": "80"}
        assert c.page.locator("#bkWriterAuto").get_attribute("aria-pressed") == "false"
        words = text(c)
        assert "Balanced tier, always" in words  # the tier is never offered
        assert (
            "the writer\u2019s own choice" in words
        )  # the Gemini pick is the writer's own consent (L8)
        options = c.page.locator("#bkWriterBrain option").all_inner_texts()
        assert options == ["Claude", "Gemini (free)"]
        assert sent == []
        clean(c)
    finally:
        c.close()


def test_r63_c_pick_the_first_save_shows_the_servers_words_and_keep_sends_nothing(
    browser: Any, c_url: str, token: str
) -> None:
    c, sent = writer_open(browser, c_url, token)
    try:
        save(c)
        dialog = c.page.locator("#bookYesDialog")
        dialog.get_by_text(
            "Up to Rs 1,500 for the first full write"
        ).wait_for()  # the server's words
        assert puts(sent) == [{"brain": "anthropic", "caps": DEFAULTS, "auto_update": False}]
        keep(c)
        assert len(puts(sent)) == 1  # "Keep" sends nothing
        assert seen(c_url)["pick"]["brain"] is None
        save(c)
        confirm(c)
        until(c.page, lambda: "Saved." in text(c), "the pick saved")
        first, _, again = puts(sent)
        assert first == {"brain": "anthropic", "caps": DEFAULTS, "auto_update": False}
        assert again["typed"] == "YES" and again["terms_id"].startswith("wt_")
        assert {k: v for k, v in again.items() if k not in ("typed", "terms_id")} == first
        assert seen(c_url)["pick"]["confirmed"]["terms_id"] == again["terms_id"]
        clean(c, 422)
    finally:
        c.close()


def test_r63_c_pick_yes_typed_lower_case_is_refused_by_the_server(
    browser: Any, c_url: str, token: str
) -> None:
    c, sent = writer_open(browser, c_url, token)
    try:
        save(c)
        dialog = confirm(c, "yes")
        dialog.get_by_text("Type YES in capitals to go ahead.").wait_for()
        assert puts(sent)[-1]["typed"] == "yes"
        assert seen(c_url)["pick"]["brain"] is None  # nothing saved
        clean(c, 422)
    finally:
        c.close()


def test_r63_c_pick_a_raise_a_training_brain_a_paid_brain_and_update_by_itself_each_ask(
    browser: Any, c_url: str, token: str
) -> None:
    c, sent = writer_open(browser, c_url, token)
    try:
        confirmed_pick(c)
        c.page.locator("#bkCapMonth").fill("1200")  # a raise
        save(c)
        keep(c)
        assert seen(c_url)["pick"]["caps"]["month"] == 1000
        c.page.locator("#bkCapMonth").fill("1000")
        c.page.locator("#bkWriterBrain").select_option("gemini")  # a brain that may learn
        save(c)
        confirm(c)
        until(c.page, lambda: seen(c_url)["pick"]["brain"] == "gemini", "Gemini picked")
        c.page.locator("#bkWriterBrain").select_option("anthropic")  # a paid brain
        save(c)
        keep(c)
        assert seen(c_url)["pick"]["brain"] == "gemini"
        c.page.locator("#bkWriterBrain").select_option("gemini")
        c.page.locator("#bkWriterAuto").click()  # update by itself
        save(c)
        dialog = c.page.locator("#bookYesDialog")
        dialog.get_by_text("by itself after each deploy, with no question asked").wait_for()
        confirm(c)
        until(c.page, lambda: seen(c_url)["pick"]["auto_update"] is True, "auto update on")
        asked = [b for b in puts(sent) if "typed" not in b]
        assert len(asked) == 5  # the first save, the raise, Gemini, Claude and auto: each asked
        clean(c, 422)
    finally:
        c.close()


def test_r63_c_pick_lowering_saves_at_once(browser: Any, c_url: str, token: str) -> None:
    c, sent = writer_open(browser, c_url, token)
    try:
        confirmed_pick(c)
        before = len(puts(sent))
        c.page.locator("#bkCapRelease").fill("300")
        save(c)
        until(c.page, lambda: seen(c_url)["pick"]["caps"]["release"] == 300, "the lower cap")
        assert len(puts(sent)) == before + 1 and "typed" not in puts(sent)[-1]
        assert not c.page.locator("#bookYesDialog").is_visible()
        clean(c, 422)
    finally:
        c.close()


def test_r63_c_pick_out_of_bounds_is_said_and_not_sent(
    browser: Any, c_url: str, token: str
) -> None:
    c, sent = writer_open(browser, c_url, token)
    try:
        c.page.locator("#bkCapFirst").fill("9000")
        save(c)
        until(c.page, lambda: "from ₹0 to ₹5,000" in text(c), "the bound")
        assert puts(sent) == []
        clean(c)
    finally:
        c.close()


def test_r63_c_pick_the_first_writes_second_yes_on_its_estimate(
    browser: Any, c_url: str, token: str
) -> None:
    c, sent = writer_open(browser, c_url, token)
    try:
        confirmed_pick(c)
        c.page.locator(WRITER).get_by_role("button", name="Write the full book").click()
        dialog = c.page.locator("#bookYesDialog")
        dialog.get_by_text("About ₹1,140").wait_for()  # the Rs first, from the estimate
        words = dialog.inner_text()
        assert "152 pages" in words and "₹1,500" in words and "$" not in words
        dialog.locator("#bookYes").fill("YES")
        dialog.get_by_role("button", name="Start").click()
        until(c.page, lambda: "of 152 pages" in text(c), "the run")
        first = [s["body"] for s in sent if s["url"].endswith("/first")]
        assert first == [{"typed": "YES", "estimate_id": FIRST_ESTIMATE}]
        assert seen(c_url)["calls"] == ["first"]
        clean(c, 422)
    finally:
        c.close()


def test_r63_c_pick_a_refusal_shows_its_words_under_the_button(
    browser: Any, c_url: str, token: str
) -> None:
    c, _ = writer_open(
        browser,
        c_url,
        token,
        refuse={"first": [409, "already_written", "The full book is written already."]},
    )
    try:
        confirmed_pick(c)
        c.page.locator(WRITER).get_by_role("button", name="Write the full book").click()
        dialog = c.page.locator("#bookYesDialog")
        dialog.locator("#bookYes").fill("YES")
        dialog.get_by_role("button", name="Start").click()
        until(c.page, lambda: "The full book is written already." in text(c), "the refusal")
        assert not dialog.is_visible() and seen(c_url)["calls"] == []
        clean(c, 409, 422)
    finally:
        c.close()


def test_r63_c_pick_update_asks_its_yes_and_stop_stops(
    browser: Any, c_url: str, token: str
) -> None:
    c, sent = writer_open(browser, c_url, token, update_ready=True)
    try:
        confirmed_pick(c)
        assert "The AI pages wait for your Update (about ₹300)" in text(c)
        c.page.locator(WRITER).get_by_role("button", name="Update", exact=True).click()
        dialog = c.page.locator("#bookYesDialog")
        dialog.get_by_text("About ₹300").wait_for()
        dialog.locator("#bookYes").fill("YES")
        dialog.get_by_role("button", name="Start").click()
        until(c.page, lambda: "of 40 pages" in text(c), "the update run")
        assert [s["body"] for s in sent if s["url"].endswith("/update")] == [
            {"typed": "YES", "estimate_id": UPDATE_ESTIMATE}
        ]
        c.page.locator(WRITER).get_by_role("button", name="Stop").click()
        until(c.page, lambda: seen(c_url)["run"]["state"] == "stopped", "the stop")
        until(c.page, lambda: "You stopped it." in text(c), "the stop's words")
        clean(c, 422)
    finally:
        c.close()


def test_r63_c_pick_the_storage_line_sits_at_the_top_of_the_panel(
    browser: Any, c_url: str, token: str
) -> None:
    c, _ = writer_open(browser, c_url, token, storage_warn=True)
    try:
        top = c.page.locator("#p-book .bk-wtop")
        until(c.page, lambda: top.is_visible(), "the storage line")
        assert "49.6 of 60 MiB (83 %)" in top.inner_text()
        first = c.page.locator("#p-book .pbody > *:not([hidden])").first
        assert "bk-wtop" in (first.get_attribute("class") or "")
        clean(c)
    finally:
        c.close()
