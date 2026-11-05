# tests/browser/test_faces.py -- the Faces panel (R3 D13) in a browser: the real console with I1's
# #p-faces shell, dock button and tags; /v1/faces* is answered by the test
# (shapes: src/jarvis/api/faces.py). Pins: empty first, Add person with the consent statement by age and
# the right body + CSRF header, no pictures anywhere, yearly check, delete behind a focus-trapped confirm
# then a passkey bound to face:<id>, "deleting when it's back", hostile text shown as text, a phone
# without sideways scroll. 0 JS errors and 0 CSP reports.
# ruff: noqa: E501  (long comment lines and the embedded page / script fixtures)
from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import pytest
from test_console import Console  # same directory (pytest prepend import)

_pw = pytest.importorskip("playwright.sync_api")
sync_playwright = _pw.sync_playwright

pytestmark = pytest.mark.browser

STATIC = Path(__file__).resolve().parents[2] / "src" / "jarvis" / "api" / "static"
HOSTILE = '<img src=x onerror="window.__pwned=1">Anjali'
A = "fp_3a9c12ab34cd"
STATEMENTS = {
    "version": "fc1",
    "adult": "<name> agreed that the camera at my home may recognise their face and greet them by name; their face pictures stay on my laptop; they can ask me to delete them at any time",
    "child": "<name> is under 18 and I am their parent or legal guardian (or have their parent's agreement)",
}
STUB = (
    "window.__proofs = []; window.JarvisPasskey = { supported: () => true, message: () => 'no',"
    " prove: async (purpose, target) => { window.__proofs.push([purpose, target]);"
    " return { challenge_id: 'x'.repeat(20) }; } };"
)


def until(page: Any, check: Any, what: str = "condition") -> None:
    """Poll from Python: Playwright's wait_for_function evals a string, which the page's CSP forbids."""
    for _ in range(100):
        if check():
            return
        page.wait_for_timeout(50)
    raise AssertionError("timed out waiting for " + what)


def person(**kw: Any) -> dict[str, Any]:
    base = {
        "id": A,
        "name": "Anjali",
        "relation": "friend",
        "child": False,
        "vip": False,
        "state": "consented",
        "consent_at": "2026-10-01T10:00:00+00:00",
        "consent_version": "fc1",
        "renewal_due": False,
        "pictures": 0,
        "laptop_code": A,
    }
    return {**base, **kw}


@pytest.fixture(scope="module")
def browser() -> Iterator[Any]:
    with sync_playwright() as p:
        b = p.chromium.launch()
        yield b
        b.close()


def _json(route: Any, status: int, body: Any) -> None:
    route.fulfill(status=status, content_type="application/json", body=json.dumps(body))


class Fake:
    def __init__(self, page: Any, people: list[dict[str, Any]], *, available: bool = True) -> None:
        self.people = list(people)
        self.available = available
        self.calls: list[dict[str, Any]] = []
        self.delete_needs_passkey = True
        page.route("**/v1/faces", self._serve)
        page.route("**/v1/faces/**", self._serve)

    def _serve(self, route: Any) -> None:
        r, path = route.request, urlsplit(route.request.url).path
        self.calls.append(
            {
                "method": r.method,
                "path": path,
                "body": r.post_data_json if r.post_data else None,
                "csrf": r.headers.get("x-requested-with"),
            }
        )
        if path == "/v1/faces/local":
            return _json(route, 200, {"url": "http://localhost:8098/faces", "laptop_online": False})
        if path == "/v1/faces" and r.method == "GET":
            if not self.available:
                return _json(
                    route,
                    200,
                    {
                        "available": False,
                        "reason": "Not available on this server (no encryption key).",
                        "people": [],
                        "total": 0,
                        "limit": 30,
                        "statements": STATEMENTS,
                    },
                )
            return _json(
                route,
                200,
                {
                    "available": True,
                    "people": self.people,
                    "total": len(self.people),
                    "limit": 30,
                    "statements": STATEMENTS,
                },
            )
        if path == "/v1/faces" and r.method == "POST":
            body = r.post_data_json
            if body["confirm"] is not True:
                return _json(
                    route,
                    422,
                    {
                        "error": "consent_missing",
                        "detail": "Tick the consent statement first: JARVIS names nobody without it.",
                    },
                )
            self.people.append(
                person(
                    name=body["name"],
                    child=body["child"],
                    vip=body["vip"],
                    relation=body["relation"],
                )
            )
            return _json(route, 201, {"person": self.people[-1]})
        if path.endswith("/delete"):
            if self.delete_needs_passkey and not (r.post_data_json or {}).get("proof"):
                return _json(
                    route,
                    403,
                    {"error": "passkey_required", "detail": "Approve this with your passkey."},
                )
            self.people = [p for p in self.people if p["id"] not in path]
            return _json(route, 200, {"id": A, "deleting": True, "waiting_for_laptop": False})
        if r.method == "PATCH":
            self.people[0] = {**self.people[0], "renewal_due": False}
            return _json(route, 200, {"person": self.people[0]})
        return _json(route, 404, {"error": "not_found", "detail": "no"})


def open_page(
    browser: Any,
    server_url: str,
    token: str,
    people: list[dict[str, Any]],
    *,
    available: bool = True,
    size: dict[str, int] | None = None,
) -> tuple[Any, Fake, list[str]]:
    c = Console(browser, server_url, token, size or {"width": 1200, "height": 800})
    fake = Fake(c.page, people, available=available)
    c.open()
    c.page.evaluate(STUB)  # the passkey ceremony is console-permissions.js's; stubbed here
    c.open_panel("faces")
    c.page.wait_for_selector("#facesAdd")
    return c.page, fake, c.errors


def test_empty_state_explains_consent_and_the_laptop(
    browser: Any, server_url: str, token: str
) -> None:
    page, _, errors = open_page(browser, server_url, token, [])
    until(page, lambda: "Nobody is added" in page.inner_text("#facesState"), "empty state")
    assert "only works on your home laptop" in page.inner_text("#facesLocal")
    assert "never leave it" in page.inner_text("#faces")
    assert errors == []


def test_add_an_adult_sends_the_consent_and_csrf(browser: Any, server_url: str, token: str) -> None:
    page, fake, errors = open_page(browser, server_url, token, [])
    page.wait_for_selector("#facesAdd")
    page.click("#facesAdd")
    assert page.is_visible("#facesDialog")
    page.fill("#facesName", "Ravi")
    assert page.inner_text("#facesStatement").startswith("Ravi agreed that the camera")
    page.check("#facesChild")
    assert "under 18" in page.inner_text("#facesStatement")
    page.uncheck("#facesChild")
    page.check("#facesConsent")
    page.click("#facesDialog button:has-text('Add')")
    page.wait_for_selector("li.trow")
    post = next(c for c in fake.calls if c["method"] == "POST")
    assert post["csrf"] == "JARVIS"
    assert post["body"] == {
        "name": "Ravi",
        "relation": "family",
        "child": False,
        "vip": False,
        "given_by": "self",
        "consent_version": "fc1",
        "confirm": True,
    }
    assert "Add pictures on your laptop" in page.inner_text("li.trow")
    assert errors == []


def test_a_child_is_added_with_a_guardians_consent(
    browser: Any, server_url: str, token: str
) -> None:
    page, fake, _ = open_page(browser, server_url, token, [])
    page.wait_for_selector("#facesAdd")
    page.click("#facesAdd")
    page.fill("#facesName", "Mini")
    page.check("#facesChild")
    page.check("#facesConsent")
    page.click("#facesDialog button:has-text('Add')")
    page.wait_for_selector("li.trow")
    post = next(c for c in fake.calls if c["method"] == "POST")
    assert post["body"]["child"] is True and post["body"]["given_by"] == "parent_guardian"
    assert "under 18" in page.inner_text("li.trow")


def test_without_ticking_consent_the_server_words_are_shown(
    browser: Any, server_url: str, token: str
) -> None:
    page, fake, _ = open_page(browser, server_url, token, [])
    page.wait_for_selector("#facesAdd")
    page.click("#facesAdd")
    page.fill("#facesName", "Ravi")
    page.click("#facesDialog button:has-text('Add')")
    until(page, lambda: "Tick the consent" in page.inner_text("#facesNote"), "consent words")
    assert fake.people == []


def test_pictures_count_and_hostile_names_are_text(
    browser: Any, server_url: str, token: str
) -> None:
    page, _, errors = open_page(
        browser, server_url, token, [person(name=HOSTILE, pictures=5, state="enrolled", vip=True)]
    )
    page.wait_for_selector("li.trow")
    text = page.inner_text("li.trow")
    assert "5 pictures on your laptop" in text and "VIP" in text and "<img" in text
    assert page.evaluate("window.__pwned") is None
    assert page.locator("li.trow img").count() == 0
    assert errors == []


def test_the_yearly_check_asks_and_renews(browser: Any, server_url: str, token: str) -> None:
    page, fake, _ = open_page(browser, server_url, token, [person(renewal_due=True)])
    page.wait_for_selector(".fdue")
    assert "Still OK to recognise Anjali?" in page.inner_text(".fdue")
    page.click("button:has-text('Yes, still OK')")
    until(page, lambda: page.locator(".fdue").count() == 0, "check renewed")
    assert any(c["method"] == "PATCH" and c["body"] == {"reconfirm": True} for c in fake.calls)


def test_delete_asks_first_traps_focus_then_uses_a_passkey_for_that_person(
    browser: Any, server_url: str, token: str
) -> None:
    page, fake, errors = open_page(
        browser, server_url, token, [person(pictures=3, state="enrolled")]
    )
    page.wait_for_selector("li.trow")
    page.click("button[aria-label='Delete Anjali']")
    assert page.is_visible("#facesDialog")
    for _ in range(4):
        page.keyboard.press("Tab")
        assert page.evaluate(
            "document.getElementById('facesDialog').contains(document.activeElement)"
        )
    page.keyboard.press("Escape")
    assert not page.is_visible("#facesDialog") and fake.people
    page.click("button[aria-label='Delete Anjali']")
    page.click("#facesDialog button:has-text('Delete')")
    until(page, lambda: page.locator("li.trow").count() == 0, "row gone")
    assert page.evaluate("window.__proofs") == [["privacy_delete", "face:" + A]]
    posts = [c for c in fake.calls if c["path"].endswith("/delete")]
    assert posts[0]["body"] == {} and "proof" in posts[1]["body"]
    assert all("403" in e for e in errors)  # only the expected passkey_required answer is logged


def test_a_person_being_deleted_says_so_and_has_no_delete_button(
    browser: Any, server_url: str, token: str
) -> None:
    page, _, _ = open_page(browser, server_url, token, [person(state="deleting")])
    page.wait_for_selector("li.trow")
    assert "Deleting on your laptop when it's back." in page.inner_text("li.trow")
    assert page.locator("li.trow button").count() == 0


def test_not_available_says_so_and_add_is_inert(browser: Any, server_url: str, token: str) -> None:
    page, fake, _ = open_page(browser, server_url, token, [], available=False)
    until(page, lambda: "no encryption key" in page.inner_text("#facesState"), "unavailable words")
    page.click("#facesAdd", force=True)
    assert not page.is_visible("#facesDialog") and fake.people == []


def test_phone_has_no_sideways_scroll(browser: Any, server_url: str, token: str) -> None:
    page, _, _ = open_page(
        browser,
        server_url,
        token,
        [person(name="A very long name " * 2, pictures=2)],
        size={"width": 390, "height": 844},
    )
    page.wait_for_selector("li.trow")
    assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
