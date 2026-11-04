# tests/browser/test_brief_sections.py -- the Brief's "Deliveries" and "Family today" sections
# (R1 D13 / D15) in a real browser: rendering as text only, a brief without them, their one-line
# states, and the order (before the JARVIS section).
from __future__ import annotations

from collections.abc import Callable, Iterator
from typing import Any

import pytest
from r1d_wiring import wire
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
        wire(c.page)
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
