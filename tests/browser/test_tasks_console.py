# tests/browser/test_tasks_console.py — slice 10 C in a real browser: the Integrations panel's
# "To-do list — permission needed · Grant" row and the Brief panel's To-do section. The API is
# faked with page.route (shapes: /v1/integrations google.tasks_granted; BriefData.todo and
# sections_status.todo, docs/plans/phase2-slice10-tools-wave.md §C).
from __future__ import annotations

import copy
import json
from collections.abc import Iterator
from typing import Any

import pytest
from test_brief import HOSTILE, FakeBrief, brief_record, today_state  # same directory
from test_console import DESKTOP, LINKED, Console

_pw = pytest.importorskip("playwright.sync_api")
sync_playwright = _pw.sync_playwright

pytestmark = pytest.mark.browser

TODO = {
    "total": 12,
    "overdue": 2,
    "items": [
        {"title": "Pay electricity bill", "due": "2026-10-29", "overdue": True, "list": "Home"},
        {"title": HOSTILE, "due": "2026-10-31", "overdue": True, "list": "Work"},
        {"title": "Call plumber", "due": "2026-11-01", "overdue": False, "list": "Home"},
    ],
}


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


def _integrations(console: Console, google: dict[str, Any]) -> None:
    body = json.dumps({"google": google})
    console.page.route(
        "**/v1/integrations",
        lambda r: r.fulfill(status=200, content_type="application/json", body=body),
    )


# ---- Integrations: the optional to-do permission ----------------------------------------------


def test_integrations_offers_grant_for_the_todo_list_and_grant_reruns_connect(
    console: Console,
) -> None:
    went: list[str] = []

    def consent(route: Any) -> None:
        went.append(route.request.url)
        route.fulfill(status=200, content_type="text/plain", body="Google consent")

    _integrations(console, {**LINKED["google"], "tasks_granted": False})
    console.page.route("**/connect/google", consent)
    console.open()
    console.open_panel("integrations")
    row = console.page.locator("#integrations .iopt")
    row.wait_for()
    assert "To-do list — permission needed" in row.text_content()
    grant = console.page.locator("#googleGrantTasks")
    assert grant.text_content() == "Grant"
    grant.click()
    console.page.wait_for_url("**/connect/google")
    assert len(went) == 1 and went[0].endswith("/connect/google")
    assert console.errors == []


def test_integrations_shows_no_grant_row_once_granted(console: Console) -> None:
    google = {**LINKED["google"], "tasks_granted": True}
    google["scopes"] = [*google["scopes"], "https://www.googleapis.com/auth/tasks"]
    _integrations(console, google)
    console.open()
    console.open_panel("integrations")
    row = console.page.locator('#integrations .integ[data-state="linked"]')
    row.wait_for()
    text = row.text_content()
    assert "To-do list: read & edit" in text and "to-do list" in text.split("Unlocks:", 1)[1]
    assert console.page.locator("#integrations .iopt").count() == 0
    assert console.errors == []


def test_an_older_server_without_the_field_never_shows_the_grant_row(console: Console) -> None:
    _integrations(console, LINKED["google"])  # no tasks_granted (before slice 10)
    console.open()
    console.open_panel("integrations")
    console.page.locator('#integrations .integ[data-state="linked"]').wait_for()
    assert console.page.locator("#integrations .iopt").count() == 0
    assert console.errors == []


# ---- Brief: the To-do section -----------------------------------------------------------------


def _brief(make_state: dict[str, Any]) -> dict[str, Any]:
    return today_state(brief=make_state)


def _record(todo: Any, state: str | None) -> dict[str, Any]:
    rec = brief_record()
    data = copy.deepcopy(rec["data"])
    if todo is not None:
        data["todo"] = todo
    if state is not None:
        data["sections_status"] = {**data["sections_status"], "todo": state}
    return {**rec, "data": data}


def test_the_brief_lists_overdue_then_today_as_text_with_a_more_line(console: Console) -> None:
    FakeBrief(console.page, _brief(_record(TODO, "ok")))
    console.open()
    console.open_panel("brief")
    sec = console.page.locator("#brief section.bsec[aria-labelledby='bsec-todo']")
    sec.wait_for()
    head = console.page.locator("#bsec-todo").text_content()
    assert "To-do" in head and "12 due" in head and "2 overdue" in head
    rows = sec.locator("li")
    assert rows.count() == 3
    first, second, third = (rows.nth(i).text_content() for i in range(3))
    assert "Pay electricity bill" in first and "Overdue" in first and "Home" in first
    assert HOSTILE in second  # shown as text, never parsed
    assert "Call plumber" in third and "Today" in third
    assert sec.locator("li.overdue").count() == 2
    assert "Showing 3 of 12" in sec.text_content()
    assert sec.locator("img, a, script").count() == 0
    assert console.page.evaluate("window.__pwned === undefined")
    # it sits between the inbox and the JARVIS section
    order = console.page.evaluate(
        "[...document.querySelectorAll('#brief section.bsec')]"
        ".map(s => s.getAttribute('aria-labelledby'))"
    )
    assert order.index("bsec-inbox") < order.index("bsec-todo") < order.index("bsec-jarvis")
    assert console.errors == [] and console.csp_violations() == []


def test_the_brief_asks_for_the_grant_and_opens_integrations(console: Console) -> None:
    FakeBrief(console.page, _brief(_record(None, "not_granted")))
    console.open()
    console.open_panel("brief")
    sec = console.page.locator("#brief section.bsec[aria-labelledby='bsec-todo']")
    sec.wait_for()
    assert "Grant" in sec.text_content() and "to-do list" in sec.text_content()
    console.page.locator("#briefIntegTodo").click()
    console.page.locator("#p-integrations").wait_for(state="visible")
    assert console.errors == []


@pytest.mark.parametrize(
    ("todo", "state", "line"),
    [
        ({"total": 0, "overdue": 0, "items": []}, "ok", "Nothing due today or overdue."),
        (None, "unavailable", "Couldn't read your to-do list just now."),
        (None, "not_connected", "Connect Google to see your to-do list here."),
    ],
)
def test_the_brief_todo_states_read_plainly(
    console: Console, todo: Any, state: str, line: str
) -> None:
    FakeBrief(console.page, _brief(_record(todo, state)))
    console.open()
    console.open_panel("brief")
    sec = console.page.locator("#brief section.bsec[aria-labelledby='bsec-todo']")
    sec.wait_for()
    assert line in sec.text_content()
    assert console.errors == []


def test_an_older_brief_without_the_todo_section_shows_none(console: Console) -> None:
    FakeBrief(console.page, _brief(brief_record()))  # data has no todo, status has no todo
    console.open()
    console.open_panel("brief")
    console.page.locator("#brief .bview").wait_for()
    assert console.page.locator("#bsec-todo").count() == 0
    assert console.errors == []
