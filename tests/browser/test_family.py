# tests/browser/test_family.py -- Integrations -> Family calendars (R1 D15) in a real browser. The
# /v1/family endpoints are faked with page.route (shapes: src/jarvis/api/family.py), so these tests
# pin the console's side of the contract: listing, adding with the right body, the plain-English
# refusal, remove behind a confirm, "not available", and that every server string is text only.
from __future__ import annotations

import json
from collections.abc import Callable, Iterator
from typing import Any
from urllib.parse import urlsplit

import pytest
from r1d_wiring import wire
from test_console import DESKTOP, LINKED, Console  # same directory (pytest prepend import)

_pw = pytest.importorskip("playwright.sync_api")
sync_playwright = _pw.sync_playwright

pytestmark = pytest.mark.browser

HOW_TO = "Ask each person to share their Google Calendar with your Gmail address."
HOSTILE = '<img src=x onerror="window.__pwned=1">Anjali'
ANJALI = {
    "id": "fam_0123456789ab",
    "name": "Anjali",
    "calendar_id": "anjali@gmail.com",
    "access": "writer",
    "can_write": True,
    "added_at": "2026-11-05T00:00:00Z",
}


def _json(route: Any, status: int, body: Any) -> None:
    route.fulfill(status=status, content_type="application/json", body=json.dumps(body))


class FakeFamily:
    """Answers /v1/family for one page and records every request."""

    def __init__(
        self, page: Any, members: list[dict[str, Any]], *, configured: bool = True
    ) -> None:
        self.members = list(members)
        self.configured = configured
        self.calls: list[dict[str, Any]] = []
        self.add_answer: tuple[int, Any] | None = None
        page.route("**/v1/integrations", lambda r: _json(r, 200, LINKED))
        page.route("**/v1/family", self._collection)
        page.route("**/v1/family/*", self._item)

    def _record(self, route: Any) -> dict[str, Any]:
        req = route.request
        call = {
            "path": urlsplit(req.url).path,
            "method": req.method,
            "body": json.loads(req.post_data) if req.post_data else None,
            "headers": dict(req.headers),
        }
        self.calls.append(call)
        return call

    def _collection(self, route: Any) -> None:
        call = self._record(route)
        if not self.configured:
            _json(route, 200, {"configured": False})
        elif call["method"] == "POST":
            if self.add_answer is not None:
                _json(route, *self.add_answer)
                return
            body = call["body"]
            member = {
                **ANJALI,
                "id": "fam_aaaaaaaaaaaa",
                "name": body["name"],
                "calendar_id": body["calendar_id"],
            }
            self.members.append(member)
            _json(route, 201, member)
        else:
            _json(
                route,
                200,
                {"configured": True, "members": self.members, "max_members": 8, "how_to": HOW_TO},
            )

    def _item(self, route: Any) -> None:
        call = self._record(route)
        mid = call["path"].rsplit("/", 1)[-1]
        self.members = [m for m in self.members if m["id"] != mid]
        _json(route, 200, {"removed": mid})

    def to(self, method: str) -> list[dict[str, Any]]:
        return [c for c in self.calls if c["method"] == method]


@pytest.fixture(scope="module")
def browser() -> Iterator[Any]:
    with sync_playwright() as p:
        b = p.chromium.launch()
        yield b
        b.close()


@pytest.fixture
def make(browser: Any, server_url: str, token: str) -> Iterator[Callable[..., Console]]:
    made: list[Console] = []

    def factory(viewport: dict[str, int] = DESKTOP) -> Console:
        c = Console(browser, server_url, token, viewport)
        wire(c.page)
        made.append(c)
        return c

    yield factory
    for c in made:
        c.close()


def _open(c: Console) -> Any:
    c.open()
    c.open_panel("integrations")
    card = c.page.locator("#familySet")
    card.wait_for()
    return card


def test_empty_list_says_how_to_start_and_shows_the_form(make: Callable[..., Console]) -> None:
    c = make()
    FakeFamily(c.page, [])
    card = _open(c)
    card.locator("text=No family calendars yet").wait_for()
    assert card.locator("#familyAddBtn").is_visible()
    assert HOW_TO in str(card.text_content())
    assert c.errors == [] and c.csp_violations() == []


def test_adding_posts_the_trimmed_body_and_lists_the_member(make: Callable[..., Console]) -> None:
    c = make()
    fake = FakeFamily(c.page, [])
    card = _open(c)
    card.locator("#familyName").fill("  Anjali ")
    card.locator("#familyAddr").fill(" Anjali@Gmail.com ")
    card.locator("#familyAddBtn").click()
    card.locator(".fmember").wait_for()
    (post,) = fake.to("POST")
    assert post["body"] == {"name": "Anjali", "calendar_id": "anjali@gmail.com"}
    assert post["headers"].get("x-requested-with") == "JARVIS" or "authorization" in post["headers"]
    text = str(card.text_content())
    assert "Anjali" in text and "anjali@gmail.com" in text and "added." in text


def test_a_refusal_is_shown_in_the_servers_plain_words(make: Callable[..., Console]) -> None:
    c = make()
    fake = FakeFamily(c.page, [])
    fake.add_answer = (
        422,
        {"error": "not_shared", "detail": "Not shared with you yet. Ask them to share it."},
    )
    card = _open(c)
    card.locator("#familyName").fill("Ravi")
    card.locator("#familyAddr").fill("ravi@gmail.com")
    card.locator("#familyAddBtn").click()
    card.locator("#familyNote", has_text="Not shared with you yet").wait_for()
    assert card.locator(".fmember").count() == 0


def test_empty_fields_do_not_reach_the_server(make: Callable[..., Console]) -> None:
    c = make()
    fake = FakeFamily(c.page, [])
    card = _open(c)
    card.locator("#familyAddBtn").click()
    card.locator("#familyNote", has_text="Enter a name").wait_for()
    assert fake.to("POST") == []


def test_remove_asks_first_and_keep_changes_nothing(make: Callable[..., Console]) -> None:
    c = make()
    fake = FakeFamily(c.page, [ANJALI])
    card = _open(c)
    card.locator(".fmember >> text=can add events").wait_for()
    card.get_by_role("button", name="Remove Anjali").click()
    card.locator(".confirm").wait_for()
    card.get_by_role("button", name="Keep").click()
    assert card.locator(".confirm").count() == 0 and fake.to("DELETE") == []
    card.get_by_role("button", name="Remove Anjali").click()
    card.locator(".confirm").get_by_role("button", name="Remove").click()
    card.locator(".fmember").wait_for(state="detached")
    (gone,) = fake.to("DELETE")
    assert gone["path"] == "/v1/family/fam_0123456789ab"


def test_not_configured_says_not_available(make: Callable[..., Console]) -> None:
    c = make()
    FakeFamily(c.page, [], configured=False)
    card = _open(c)
    card.locator("text=Not available in this setup").wait_for()
    assert card.locator("#familyAdd").count() == 0


def test_hostile_names_are_text_not_markup(make: Callable[..., Console]) -> None:
    c = make()
    FakeFamily(c.page, [{**ANJALI, "name": HOSTILE}])
    card = _open(c)
    card.locator(".fmember").wait_for()
    assert HOSTILE[:20] in str(card.locator(".fmember").text_content())
    assert card.locator("img").count() == 0
    assert c.page.evaluate("window.__pwned") is None


def test_phone_layout_has_no_sideways_scroll(make: Callable[..., Console]) -> None:
    from test_console import PHONE

    c = make(PHONE)
    FakeFamily(c.page, [ANJALI])
    card = _open(c)
    card.locator(".fmember").wait_for()
    wide = c.page.evaluate(
        "document.documentElement.scrollWidth > document.documentElement.clientWidth"
    )
    assert wide is False
