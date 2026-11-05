# tests/browser/test_brief_sections.py -- the Brief's "Deliveries" and "Family today" sections
# (R1 D13 / D15) in a real browser: rendering as text only, a brief without them, their one-line
# states, and the order (before the JARVIS section).
from __future__ import annotations

from collections.abc import Callable, Iterator
from typing import Any

import pytest
from test_brief import FakeBrief, brief_record, today_state
from test_console import DESKTOP, Console  # same directory (pytest prepend import)

_pw = pytest.importorskip("playwright.sync_api")
sync_playwright = _pw.sync_playwright

pytestmark = pytest.mark.browser

HOSTILE = '<img src=x onerror="window.__pwned=1">Parcel'

DELIVERIES = {
    "total": 7,
    "state": "ok",
    "items": [
        {
            "item": "Shipped: your order",
            "status": "shipped",
            "merchant": "Amazon",
            "carrier": "Amazon Logistics",
            "expected": "2026-11-09",
        },
        {
            "item": HOSTILE,
            "status": "out_for_delivery",
            "merchant": "",
            "carrier": "",
            "expected": "",
        },
    ],
}
FAMILY = {
    "state": "ok",
    "members": [
        {
            "name": "Anjali",
            "busy_only": False,
            "unavailable": False,
            "events": [{"when": "10:00", "title": "Dentist"}],
        },
        {
            "name": "Ravi",
            "busy_only": True,
            "unavailable": False,
            "events": [{"when": "10:00–11:00", "title": ""}],
        },
        {"name": "Meera", "busy_only": False, "unavailable": False, "events": []},
        {"name": "Old", "busy_only": False, "unavailable": True, "events": []},
    ],
}


def state_with(**extra: Any) -> dict[str, Any]:
    record = brief_record()
    record["data"] = {**record["data"], **extra}
    return today_state(brief=record)


@pytest.fixture(scope="module")
def browser() -> Iterator[Any]:
    with sync_playwright() as p:
        b = p.chromium.launch()
        yield b
        b.close()


@pytest.fixture
def make(browser: Any, server_url: str, token: str) -> Iterator[Callable[..., Console]]:
    made: list[Console] = []

    def factory() -> Console:
        c = Console(browser, server_url, token, DESKTOP)
        made.append(c)
        return c

    yield factory
    for c in made:
        c.close()


def _view(c: Console) -> Any:
    c.open()
    c.open_panel("brief")
    view = c.page.locator("#brief .bview")
    view.wait_for()
    return view


def test_both_sections_render_as_text_before_the_jarvis_section(
    make: Callable[..., Console],
) -> None:
    c = make()
    FakeBrief(c.page, state_with(deliveries=DELIVERIES, family=FAMILY))
    view = _view(c)
    text = str(view.text_content())
    for words in (
        "Deliveries",
        "7 on the way or just delivered",
        "Shipped",
        "“Shipped: your order”",
        "Amazon · Amazon Logistics · expected",
        "Out for delivery",
        "… and 5 more.",
        "Family today",
        "Anjali",
        "“Dentist”",
        "Ravi",
        "busy times only",
        "10:00–11:00",
        "busy",
        "Meera: nothing today.",
        "Old: not shared with you any more.",
    ):
        assert words in text, words
    assert HOSTILE in text
    assert c.page.locator("#p-brief img").count() == 0
    assert c.page.evaluate("window.__pwned") is None
    headings = view.locator("h3").all_text_contents()
    order = [
        next(i for i, h in enumerate(headings) if name in h)
        for name in ("Deliveries", "Family today", "JARVIS")
    ]
    assert order == sorted(order)
    assert c.errors == [] and c.csp_violations() == []


def test_a_brief_without_them_shows_neither(make: Callable[..., Console]) -> None:
    c = make()
    FakeBrief(c.page, today_state())
    text = str(_view(c).text_content())
    assert "Deliveries" not in text and "Family today" not in text


def test_states_are_one_plain_line_each(make: Callable[..., Console]) -> None:
    c = make()
    FakeBrief(
        c.page,
        state_with(
            deliveries={"state": "unavailable", "total": 0, "items": []},
            family={"state": "not_connected", "members": []},
        ),
    )
    text = str(_view(c).text_content())
    assert "Couldn't read your deliveries just now." in text
    assert "Connect Google to see your family calendars here." in text


def test_empty_deliveries_say_so(make: Callable[..., Console]) -> None:
    c = make()
    FakeBrief(c.page, state_with(deliveries={"state": "ok", "total": 0, "items": []}))
    assert "No parcels on the way." in str(_view(c).text_content())


# ---- the two switches in the Brief's settings --------------------------------------------------


def _open_settings(c: Console) -> None:
    btn = c.page.locator("#briefSetBtn")
    if btn.get_attribute("aria-expanded") != "true":
        btn.click()
    c.page.locator("#briefSetBody").wait_for(state="visible")


def _with_switches(c: Console, **over: Any) -> Any:
    state = state_with()
    state["settings"] = {**state["settings"], "deliveries": True, "family": True, **over}
    calls: list[dict[str, Any]] = []

    def save(body: dict[str, Any]) -> tuple[int, Any]:
        calls.append(body)
        state["settings"] = {**state["settings"], **body}
        return 200, state["settings"]

    FakeBrief(c.page, state, settings=save)
    return calls


def test_the_two_switches_mirror_the_server_and_send_only_their_own_field(
    make: Callable[..., Console],
) -> None:
    c = make()
    calls = _with_switches(c, family=False)
    _view(c)
    _open_settings(c)
    assert c.page.locator("#briefDeliveries").get_attribute("aria-pressed") == "true"
    assert c.page.locator("#briefFamily").get_attribute("aria-pressed") == "false"
    c.page.locator("#briefDeliveries").click()
    c.page.locator("#briefDeliveries[aria-pressed='false']").wait_for()
    c.page.locator("#briefFamily").click()
    c.page.locator("#briefFamily[aria-pressed='true']").wait_for()
    assert calls == [{"deliveries": False}, {"family": True}]  # no confirm, no other field
    c.page.locator(".bnote.ok", has_text="Family today on from the next brief.").wait_for()
    assert c.errors == []


def test_a_server_without_the_fields_shows_no_switches(make: Callable[..., Console]) -> None:
    c = make()
    FakeBrief(c.page, today_state())
    _view(c)
    _open_settings(c)
    assert c.page.locator("#briefDeliveries").count() == 0
    assert c.page.locator("#briefFamily").count() == 0
    assert c.page.locator("#briefAi").count() == 1


def test_home_overnight_renders_as_text_and_is_left_out_when_absent(
    make: Callable[..., Console],
) -> None:
    c = make()
    home = {
        "total": 7,
        "held": 2,
        "state": "ok",
        "items": [
            {"when": "23:41", "words": HOSTILE},
            {"when": "02:10", "words": "A parcel came."},
        ],
    }
    FakeBrief(c.page, state_with(home=home))
    text = str(_view(c).text_content())
    for words in (
        "Home overnight",
        "7 things",
        "23:41",
        "A parcel came.",
        "2 alerts were held",
        "… and 5 more.",
    ):
        assert words in text, words
    assert HOSTILE in text and c.page.locator("#p-brief img").count() == 0
    assert c.page.evaluate("window.__pwned") is None
    assert c.errors == [] and c.csp_violations() == []


def test_a_brief_without_home_shows_no_home_section(make: Callable[..., Console]) -> None:
    c = make()
    FakeBrief(c.page, today_state())
    assert "Home overnight" not in str(_view(c).text_content())
