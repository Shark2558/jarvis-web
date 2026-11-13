# tests/browser/test_r7_i1_brief.py -- R7 I1 (D18, acceptance 8): the console's brief draws
# `brief.data.sleep` (the pinned SleepLine) as ONE fixed line, "Sleep: 6 h 40 min, 23:50 to 06:30 ·
# from your watch", naming where the night came from (watch, phone, another health app, typed by
# him); a line of the wrong shape, or none, draws nothing; text only.
from __future__ import annotations

from collections.abc import Callable, Iterator
from typing import Any

import pytest
from test_brief import FakeBrief, brief_record, today_state
from test_console import DESKTOP, Console  # same directory (pytest prepend import)

_pw = pytest.importorskip("playwright.sync_api")
sync_playwright = _pw.sync_playwright

pytestmark = pytest.mark.browser

LINE = {"minutes": 400, "start": "23:50", "end": "06:30", "source": "watch"}


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


def test_last_nights_sleep_is_one_line_in_the_brief(make: Callable[..., Console]) -> None:
    c = make()
    FakeBrief(c.page, state_with(sleep=LINE))
    c.open()
    c.open_panel("brief")
    view = c.page.locator("#brief .bview")
    view.wait_for()
    line = c.page.locator("#bsec-sleep").locator("xpath=..").locator("li")
    assert line.all_text_contents() == ["Sleep: 6 h 40 min, 23:50 to 06:30 · from your watch"]
    headings = view.locator("h3").all_text_contents()
    assert any("Last night" in h for h in headings)
    assert c.errors == [] and c.csp_violations() == []


@pytest.mark.parametrize(
    ("over", "words"),
    [
        ({"source": "phone", "minutes": 420}, "Sleep: 7 h, 23:50 to 06:30 · from your phone"),
        ({"source": "app"}, "Sleep: 6 h 40 min, 23:50 to 06:30 · from another health app"),
        ({"source": "typed", "minutes": 45}, "Sleep: 45 min, 23:50 to 06:30 · typed by you"),
    ],
)
def test_the_line_names_where_the_night_came_from(
    make: Callable[..., Console], over: dict[str, Any], words: str
) -> None:
    c = make()
    c.open()
    got = c.page.evaluate(
        "(sleep) => window.JarvisBriefSections.render({ sleep }).map((s) => s.textContent)",
        {**LINE, **over},
    )
    assert got == ["Last night" + words]


@pytest.mark.parametrize(
    "bad",
    [
        None,
        "Sleep: 6 h",
        {**LINE, "source": "guess"},
        {**LINE, "minutes": -5},
        {**LINE, "minutes": 2000},
        {**LINE, "start": "<img src=x onerror=1>"},
        {**LINE, "minutes": "400"},
    ],
)
def test_a_line_of_the_wrong_shape_draws_nothing(make: Callable[..., Console], bad: Any) -> None:
    c = make()
    c.open()
    got = c.page.evaluate("(sleep) => window.JarvisBriefSections.render({ sleep }).length", bad)
    assert got == 0
    assert c.page.locator("img").count() == 0
