# tests/browser/test_r18_review_calls.py -- R18 combined review, in a real Chromium: the Calls
# panel's changes. Settings reads the limits, the caps' ranges and Sarvam's prices from the server
# (never typed in the console) and has an Unlink for the call desk (after his yes); Languages has
# the voice-score entry (the owner step of plan 5.3.2), says no "mock call", and says plainly
# when Bhashini is left out because its price is unknown.
# ruff: noqa: E501 -- JavaScript strings
from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest
from test_r18_e_calls import Calls, browser, until  # noqa: F401 -- browser: the module's fixture

pytestmark = pytest.mark.browser


@pytest.fixture
def c(browser: Any, server_url: str, token: str) -> Iterator[Calls]:  # noqa: F811
    page = Calls(browser, server_url, token)
    yield page
    page.close()


def _settings(c: Calls) -> Any:
    c.calls()
    c.tab("Languages")
    c.pane("langs").locator(".hp-row").first.wait_for()
    c.tab("Settings")
    pane = c.pane("settings")
    month = pane.get_by_label("Calls in a month, in rupees")
    until(c.page, lambda: month.input_value() == "200", "the settings")
    return pane


def test_review_the_limits_and_sarvam_s_prices_come_from_the_server(c: Calls) -> None:
    c.stub.limits = {**c.stub.limits, "calls_per_day": 8, "quiet_from": "20:30"}  # type: ignore[dict-item]
    c.stub.prices = {"sarvam": {"hear_inr_per_minute": 0.6, "voice_inr_per_1k_chars": 2.5}}
    _settings(c)
    text = c.text("#clp-settings")
    assert "8 calls a day" in text and "no calls 20:30–08:00 IST" in text
    assert "10 calls a day" not in text  # nothing typed in the console
    assert "₹0.60 a minute of hearing and ₹2.50 per 1,000 characters of voice" in text
    c.page.get_by_role("button", name="Sarvam speech (paid)").click()
    box = c.text("#clp-settings .mbox")
    assert "₹0.60 a minute of their speech and ₹2.50 per 1,000 characters" in box
    assert "free options first" in box
    c.button("Not now", "#clp-settings").click()
    c.clean()


def test_review_unknown_limits_or_prices_are_said_never_guessed(c: Calls) -> None:
    c.stub.limits = None
    c.stub.prices = {"sarvam": None}  # type: ignore[dict-item]
    _settings(c)
    text = c.text("#clp-settings")
    assert "couldn’t read them just now" in text and "10 calls a day" not in text
    assert "price isn’t known on this server" in text and "₹0.50" not in text
    c.clean()


def test_review_the_caps_ranges_follow_the_server(c: Calls) -> None:
    pane = _settings(c)
    pane.get_by_label("Calls in a month, in rupees").fill("3500")
    c.button("Save the caps", "#clp-settings").click()
    assert "from ₹0 to ₹3,000" in c.text("#clp-settings .lerr")
    assert not c.stub.calls("PUT", "/v1/calls/settings")
    c.clean()


def test_review_unlink_asks_first_then_unlinks_the_desk(c: Calls) -> None:
    _settings(c)
    unlink = c.button("Unlink", "#clp-settings")
    unlink.wait_for()
    unlink.click()
    box = c.text("#clp-settings .mbox")
    assert "Unlink the call desk?" in box and "new code" in box
    assert c.page.evaluate("document.activeElement.textContent") == "Not now"
    c.button("Not now", "#clp-settings").click()
    assert not c.stub.calls("DELETE", "/v1/calls/desk")
    unlink.click()
    c.button("Unlink", "#clp-settings .mbox").click()
    until(c.page, lambda: c.stub.calls("DELETE", "/v1/calls/desk"), "the unlink")
    until(c.page, lambda: "The call desk is unlinked." in c.text("#clp-settings"), "its words")
    c.clean()


def test_review_a_checked_voice_is_scored_from_the_languages_tab(c: Calls) -> None:
    c.calls()
    c.tab("Languages")
    pane = c.pane("langs")
    pane.locator(".hp-row").first.wait_for()
    assert "mock call" not in c.text("#clp-langs")
    row = pane.locator(".hp-row", has=c.page.locator("b", has_text="Malayalam"))
    row.get_by_role("button", name="Score the voice: Malayalam").click()
    box = pane.locator(".cl-score")
    box.wait_for(state="visible")
    assert "Score the Malayalam voice (Google)" in str(box.text_content())
    assert c.page.evaluate("document.activeElement.textContent") == "Not now"
    c.button("Save the scores", "#clp-langs .cl-score").click()
    assert "Score at least one sample" in str(box.text_content())
    assert not c.stub.calls("POST", "/languages/score")
    for sample, score in ((1, "4"), (2, "5"), (3, "4")):
        group = box.get_by_role("radiogroup", name=f"Sample {sample}")
        group.get_by_text(score, exact=True).click()
    c.button("Save the scores", "#clp-langs .cl-score").click()
    until(c.page, lambda: c.stub.calls("POST", "/languages/score"), "the scores")
    assert c.stub.calls("POST", "/languages/score")[-1][2] == {
        "lang": "ml-IN",
        "option": "google",
        "scores": [4, 5, 4],
    }
    until(c.page, lambda: "Scores saved for Malayalam." in c.text("#clp-langs"), "saved")
    until(
        c.page,
        lambda: "Not yet heard by a native speaker." not in str(row.text_content()),
        "the table read again",
    )
    c.clean()


def test_review_the_estimate_says_bhashini_is_left_out(c: Calls) -> None:
    c.calls()
    c.tab("Languages")
    c.pane("langs").locator(".hp-row").first.wait_for()
    c.button("Run language check", "#clp-langs").click()
    box = c.pane("langs").locator(".mbox", has_text="Run the language check")
    box.wait_for(state="visible")
    words = str(box.text_content())
    assert "Left out: Bhashini" in words and "unknown price as ₹0" in words
    assert all(
        "accept_unknown" not in (s[2] or {}) for s in c.stub.calls("POST", "/languages/check")
    )
    c.button("Not now", "#clp-langs").click()
    c.clean()
