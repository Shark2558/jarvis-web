# tests/browser/test_r11_c_nudges.py -- R11 Part C's Nudges tab in the Helpers panel (plan D19, D6):
# at 1440x900 and 390x844, on Night and Day, the tab (its switches, Snooze / Stop, settings, the
# water log and the free-time list) passes the visual gate's checks (tests/browser/ui_checks.py
# DOM_CHECKS_JS and the gate's own rules: no overlap, theme fonts, no sideways overflow, contrast,
# 44 px phone targets, every control named), with no JS error or CSP violation; and Snooze from the
# tab posts I0's gate route (/v1/helpers/gate/nudge_hydrate/snooze, 60 minutes) and the row then
# says it is snoozed. The tab's data is a stateful fake of /v1/helpers/nudges and the gate routes
# (page.route).
from __future__ import annotations

import json
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from test_console import DESKTOP, PHONE, Console
from test_ui_audit import NAMELESS_JS, WRAP_JS, _assert_clean
from ui_checks import DOM_CHECKS_JS, FINISH_ANIMATIONS_JS, install_mocks

sync_playwright = pytest.importorskip("playwright.sync_api").sync_playwright

pytestmark = pytest.mark.browser

VIEWPORTS = {"desktop": DESKTOP, "phone": PHONE}
SURFACES = ("night", "day")
SETTLE_MS = 700
TODAY = datetime.now(UTC).date().isoformat()


def _nudge(kind: str, name: str, label: str, line: str, **n: Any) -> dict[str, Any]:
    base = {
        "on": False,
        "start": "09:30",
        "end": "18:30",
        "days": [0, 1, 2, 3, 4, 5],
        "every": 0,
        "times": [],
        "meeting": False,
        "word": "stand-up",
        "words": [],
    }
    when = line.split(": ", 1)[1].split(", ", 1)[1]  # what the route's `when` says
    return {
        "kind": kind,
        "name": name,
        "label": label,
        "line": line,
        "when": when[:1].upper() + when[1:],
        **base,
        **n,
    }


def _view() -> dict[str, Any]:
    return {
        "enabled": True,
        "sealed": True,
        "calendar": True,
        "nudges": [
            _nudge(
                "nudge_standup",
                "standup",
                "Stand up and move",
                "Stand up and move: on, every 60 minutes, 09:30-18:30, Monday to Saturday.",
                on=True,
                every=60,
            ),
            _nudge(
                "nudge_hydrate",
                "water",
                "Drink water",
                "Drink water: on, every 90 minutes, 09:30-18:30, Monday to Saturday.",
                on=True,
                every=90,
            ),
            _nudge(
                "nudge_activity",
                "activity",
                "A planned activity that didn't happen",
                "A planned activity that didn't happen: off, 06:00-22:00, for walk, gym, every "
                "day.",
                start="06:00",
                end="22:00",
                words=["walk", "gym"],
            ),
            _nudge(
                "nudge_free_time",
                "free_time",
                "Ideas for free time",
                "Ideas for free time: off, at 18:00, every day.",
                times=["18:00"],
            ),
            _nudge(
                "nudge_focus",
                "focus",
                "Your top priority",
                "Your top priority: off, at 10:00, 15:00, Monday to Saturday.",
                times=["10:00", "15:00"],
            ),
        ],
        "gate": {"snoozed": {}, "stopped": {}, "today": TODAY},
        "today": {"water": 3, "stood": 2},
        "ideas": [
            {
                "id": "0000000a",
                "text": "Read a novel",
                "minutes": 45,
                "place": "indoor",
                "last_done": None,
            },
            {
                "id": "0000000b",
                "text": "Cycle by the lake",
                "minutes": 60,
                "place": "outdoor",
                "last_done": "2026-11-08",
            },
        ],
    }


class FakeNudges:
    def __init__(self) -> None:
        self.view = _view()
        self.posts: list[tuple[str, Any]] = []

    def _ok(self, route: Any, body: Any) -> None:
        route.fulfill(status=200, content_type="application/json", body=json.dumps(body))

    def nudges(self, route: Any) -> None:
        req = route.request
        if req.method == "GET":
            return self._ok(route, self.view)
        self.posts.append((req.url.split("/v1/")[1], req.post_data_json if req.post_data else None))
        if req.url.endswith("/water"):
            self.view["today"]["water"] += 1
        return self._ok(route, self.view)

    def gate(self, route: Any) -> None:
        req = route.request
        path = req.url.split("/v1/helpers/gate/")[1]
        self.posts.append((path, req.post_data_json if req.post_data else None))
        kind, action = path.split("/")
        key = "*" if kind == "all" else kind
        if action == "snooze":
            until = datetime.now(UTC) + timedelta(minutes=60)
            self.view["gate"]["snoozed"][key] = until.isoformat()
        elif action == "stop":
            self.view["gate"]["stopped"][key] = TODAY
        else:
            self.view["gate"]["snoozed"].pop(key, None)
            self.view["gate"]["stopped"].pop(key, None)
        self._ok(route, {"enabled": True})


@pytest.fixture(scope="module")
def browser() -> Iterator[Any]:
    with sync_playwright() as p:
        b = p.chromium.launch()
        yield b
        b.close()


def _open(browser: Any, url: str, token: str, vp: str, surface: str) -> tuple[Console, FakeNudges]:
    c, fake = Console(browser, url, token, VIEWPORTS[vp]), FakeNudges()
    install_mocks(c.page)
    c.page.route("**/v1/helpers/nudges**", fake.nudges)
    c.page.route("**/v1/helpers/gate/**", fake.gate)
    c.open()
    if surface == "day":
        c.page.locator("#themeBtn").click()
        c.page.locator('label[for="jx-s-day"]').click()
        c.page.keyboard.press("Escape")
    assert c.page.locator("html").get_attribute("data-surface") == surface
    c.open_panel("helpers")
    c.page.locator("#hpt-nudges").click()
    c.page.locator('#hpp-nudges [data-nudge="water"]').wait_for()
    c.page.wait_for_timeout(SETTLE_MS)
    return c, fake


@pytest.mark.parametrize("surface", SURFACES)
@pytest.mark.parametrize("vp", list(VIEWPORTS))
def test_helpers_nudges_tab_passes_the_visual_gate(
    browser: Any, server_url: str, token: str, vp: str, surface: str
) -> None:
    c, _ = _open(browser, server_url, token, vp, surface)
    try:
        sel = "#p-helpers"
        c.page.evaluate(FINISH_ANIMATIONS_JS)
        res = c.page.evaluate(DOM_CHECKS_JS, sel)
        nameless, wraps = c.page.evaluate(NAMELESS_JS, sel), c.page.evaluate(WRAP_JS, sel)
        assert not res.get("missing")
        _assert_clean(res, nameless, wraps, vp, f"helpers/nudges {vp} {surface}")
        tab = c.page.locator("#hpp-nudges").inner_text()
        assert "Drink water" in tab and "3 glasses today" in tab and "Read a novel" in tab
        assert c.errors == [] and c.csp_violations() == []
    finally:
        c.close()


@pytest.mark.parametrize("vp", list(VIEWPORTS))
def test_helpers_nudges_snooze_from_the_tab_uses_the_gate_route(
    browser: Any, server_url: str, token: str, vp: str
) -> None:
    c, fake = _open(browser, server_url, token, vp, "night")
    try:
        row = c.page.locator('#hpp-nudges [data-nudge="water"]')
        row.get_by_role("button", name="Snooze Drink water for 1 hour").click()
        row.get_by_text("Snoozed until").wait_for()
        assert ("nudge_hydrate/snooze", {"minutes": 60}) in fake.posts
        assert row.get_by_role("button", name="Resume Drink water").is_visible()
        row.get_by_role("button", name="Resume Drink water").click()
        row.get_by_role("button", name="Snooze Drink water for 1 hour").wait_for()
        pane = c.page.locator("#hpp-nudges")
        pane.get_by_role("button", name="Stop every nudge for today").click()
        row.get_by_text("Stopped for today").wait_for()
        row.get_by_role("button", name="Resume Drink water").click()  # held by "all": resumes all
        row.get_by_role("button", name="Snooze Drink water for 1 hour").wait_for()
        assert ("all/resume", None) in fake.posts
        c.page.locator("#hpp-nudges").get_by_role("button", name="Log a glass of water").click()
        c.page.locator("#hpp-nudges").get_by_text("4 glasses today").wait_for()
        assert c.errors == [] and c.csp_violations() == []
    finally:
        c.close()
