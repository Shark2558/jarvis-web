# tests/browser/test_r7_c_phone.py -- R7 Part C in a real browser (docs/plans/r7-mobile.md D5, D21):
# Integrations -> Phone app. Signed out, neither of Part C's modules asks the server anything (a
# network spy). The card: no phone linked; "Link a phone" with the passkey (a phone_link check bound
# to the offer the server names), the code shown as two groups of four, the dialog closing once the
# phone has linked; a stale sign-in says to sign in again with a link; the linked phones with what
# each app may do, a hostile model word shown as text; Unlink needs the confirm and Cancel changes
# nothing; Sign out everywhere asks first. And the visual gate (ui_checks) on the card and the code
# dialog at 1440x900 and 390x844, Night and Day. /v1/phone* and /v1/session/* are answered here.
from __future__ import annotations

import json
from collections.abc import Iterator
from typing import Any

import pytest
from book_mocks import PASSKEY_STUB
from test_console import DESKTOP, PHONE, Console
from test_ui_audit import NAMELESS_JS, WRAP_JS, _assert_clean
from ui_checks import DOM_CHECKS_JS, FINISH_ANIMATIONS_JS

_pw = pytest.importorskip("playwright.sync_api")

pytestmark = pytest.mark.browser

HOSTILE = "<img src=x onerror=__pwned=1>Pixel"  # 34 characters: a model word is at most 40
OFFER = "pl_0123456789ab"
PHONE_A = {
    "id": "ph_0123456789ab",
    "model": "phone",
    "linked_at": "2026-11-13T08:30:00+00:00",
    "last_seen": "2026-11-13T09:05:00+00:00",
    "app_version": "7.0.0",
    "android": 36,
    "can": {"notifications": True, "health_read": True, "health_background": False,
            "location": True, "folder": False, "tile": True},
}  # fmt: skip


@pytest.fixture(scope="module")
def browser() -> Iterator[Any]:
    with _pw.sync_playwright() as p:
        b = p.chromium.launch()
        yield b
        b.close()


def j(route: Any, status: int, body: Any) -> None:
    route.fulfill(status=status, content_type="application/json", body=json.dumps(body),
                  headers={"Cache-Control": "no-store"})  # fmt: skip


class Fake:
    """/v1/phone* and /v1/session/end-all; records (method, path, body)."""

    def __init__(self, phones: list[dict[str, Any]] | None = None) -> None:
        self.phones = list(phones or [])
        self.calls: list[tuple[str, str, Any]] = []
        self.code_answer: tuple[int, Any] | None = None
        self.link_after_code = True

    def view(self) -> dict[str, Any]:
        return {"part": "phone", "ready": "ready", "enabled": True, "max": 3,
                "phones": self.phones, "code": None}  # fmt: skip

    def __call__(self, route: Any) -> None:
        req = route.request
        path = "/v1/" + req.url.split("/v1/", 1)[1]
        body = req.post_data_json if req.post_data else None
        self.calls.append((req.method, path, body))
        if path == "/v1/phone":
            return j(route, 200, self.view())
        if path == "/v1/phone/link-code":
            if self.code_answer is not None:
                return j(route, *self.code_answer)
            if not body or "proof" not in body:
                return j(route, 200, {"needs": "passkey", "target": OFFER, "detail": "Use it."})
            if self.link_after_code:
                self.phones.append(PHONE_A)
            return j(route, 200, {"code": "ABCD2345", "expires_in_s": 600})
        if path.endswith("/unlink"):
            self.phones = [p for p in self.phones if p["id"] not in path]
            return j(route, 200, {"unlinked": True})
        if path == "/v1/session/end-all":
            return j(
                route, 200, {"ended": True, "detail": "Every other device is signed out, Sir."}
            )
        return route.fallback()


def _card(browser: Any, url: str, token: str, fake: Fake, viewport: Any = DESKTOP) -> Console:
    c = Console(browser, url, token, viewport)
    c.page.route("**/v1/phone**", fake)
    c.page.route("**/v1/session/end-all", fake)
    c.open()
    c.page.evaluate(PASSKEY_STUB)
    c.open_panel("integrations")
    c.page.locator("#phoneSet .istate").wait_for()
    c.page.wait_for_function(
        "() => document.querySelector('#phoneSet').dataset.state !== 'loading'"
    )
    return c


def _clean(c: Console) -> None:
    assert c.errors == [] and c.csp_violations() == []
    assert c.page.evaluate("() => window.__pwned") is None


# ---- ask nothing before sign-in ----------------------------------------------------------------
@pytest.mark.parametrize("path", ["/", "/?source=app"])
def test_before_sign_in_the_block_asks_the_server_nothing(
    browser: Any, server_url: str, token: str, path: str
) -> None:
    c = Console(browser, server_url, token, DESKTOP)
    asked: list[str] = []
    c.page.on("request", lambda r: asked.append(r.url))
    config = {"auth_mode": "google", "honorific": "Sir", "brain": "mock", "privacy_warning": ""}
    c.page.route("**/console/config", lambda r: j(r, 200, config))
    c.page.route("**/auth/me", lambda r: j(r, 401, {"detail": "sign in required"}))
    try:
        c.page.goto(server_url + path)
        c.page.locator("#gBtn").wait_for()
        c.page.wait_for_timeout(800)  # every module has loaded and had its chance to ask
        for el in ("#phoneSet", "#r7Lock"):
            assert c.page.locator(el).count() == 0, el
        c.page.mouse.click(5, 5)  # a real tap: still no "I'm here" before sign-in
        c.page.keyboard.press("Shift")
        c.page.wait_for_timeout(300)
        ours = [u for u in asked if "/v1/phone" in u or "/v1/session" in u or "assetlinks" in u]
        assert ours == []
        assert c.page.evaluate("() => sessionStorage.getItem('jarvis_app_v1')") == (
            "1" if "source=app" in path else None
        )
    finally:
        c.close()


# ---- the card ----------------------------------------------------------------------------------
def test_no_phone_linked_then_link_with_the_passkey_shows_the_code_until_linked(
    browser: Any, server_url: str, token: str
) -> None:
    fake = Fake()
    c = _card(browser, server_url, token, fake)
    try:
        card = c.page.locator("#phoneSet")
        assert card.locator(".istate").inner_text() == "NO PHONE LINKED"
        assert "own key" in card.inner_text()
        card.get_by_role("button", name="Link a phone").click()
        code = c.page.locator("#phoneCode")
        code.wait_for()
        assert code.inner_text() == "ABCD 2345"
        assert "works once, for 10 minutes" in c.page.locator("#phoneDialog").inner_text()
        assert c.page.evaluate("() => window.__proofs") == [["phone_link", OFFER]]
        posts = [b for m, p, b in fake.calls if p == "/v1/phone/link-code"]
        assert posts[0] == {} and posts[1]["id"] == OFFER
        assert posts[1]["proof"] == {"purpose": "phone_link", "target": OFFER, "stub": True}
        c.page.locator("#phoneDialog").wait_for(state="hidden", timeout=8000)  # the poll saw it
        assert c.page.locator("#phoneNote").inner_text().startswith("Linked.")
        assert card.locator(".istate").inner_text() == "1 PHONE LINKED"
        _clean(c)
    finally:
        c.close()


def test_a_stale_sign_in_says_to_sign_in_again(browser: Any, server_url: str, token: str) -> None:
    fake = Fake()
    fake.code_answer = (403, {"error": "reauth_required", "detail": "Sign in with Google again."})
    c = _card(browser, server_url, token, fake)
    try:
        c.page.locator("#phoneLink").click()
        note = c.page.locator("#phoneNote")
        note.wait_for()
        assert "Sign in with Google again" in note.inner_text()
        assert note.locator("a").get_attribute("href") == "/auth/login?reauth=1"
        assert c.page.locator("#phoneDialog[open]").count() == 0
        assert [e for e in c.errors if "403" not in e] == []
    finally:
        c.close()


def test_linked_phones_say_what_each_may_do_and_unlink_asks_first(
    browser: Any, server_url: str, token: str
) -> None:
    fake = Fake([PHONE_A, {**PHONE_A, "id": "ph_ba9876543210", "model": HOSTILE, "can": {}}])
    c = _card(browser, server_url, token, fake)
    try:
        rows = c.page.locator("#phoneList .phone")
        assert rows.count() == 2
        first = rows.nth(0).inner_text()
        assert "Allowed on the phone: Alerts, Watch data, SOS location, Talk tile" in first
        assert "app 7.0.0" in first
        assert HOSTILE in rows.nth(1).inner_text()  # as text, never markup
        assert "Nothing allowed on the phone yet." in rows.nth(1).inner_text()
        rows.nth(0).get_by_role("button", name="Unlink this phone").click()
        dlg = c.page.locator("#phoneDialog")
        dlg.wait_for()
        assert "no longer reach JARVIS" in dlg.inner_text()
        dlg.get_by_role("button", name="Cancel").click()
        assert not [p for m, p, b in fake.calls if p.endswith("/unlink")]
        rows.nth(0).get_by_role("button", name="Unlink this phone").click()
        dlg.get_by_role("button", name="Unlink").click()
        c.page.locator("#phoneNote", has_text="Unlinked").wait_for()
        assert [p for m, p, b in fake.calls if p.endswith("/unlink")] == [
            "/v1/phone/ph_0123456789ab/unlink"
        ]
        assert c.page.locator("#phoneList .phone").count() == 1
        _clean(c)
    finally:
        c.close()


def test_sign_out_everywhere_asks_first(browser: Any, server_url: str, token: str) -> None:
    fake = Fake([PHONE_A])
    c = _card(browser, server_url, token, fake)
    try:
        c.page.locator("#phoneEndAll").click()
        dlg = c.page.locator("#phoneDialog")
        assert "This one stays signed in" in dlg.inner_text()
        dlg.get_by_role("button", name="Cancel").click()
        assert not [p for m, p, b in fake.calls if p == "/v1/session/end-all"]
        c.page.locator("#phoneEndAll").click()
        dlg.get_by_role("button", name="Sign out everywhere").click()
        c.page.locator("#phoneNote", has_text="signed out").wait_for()
        assert [p for m, p, b in fake.calls if p == "/v1/session/end-all"] == [
            "/v1/session/end-all"
        ]
        _clean(c)
    finally:
        c.close()


def test_three_phones_is_the_most(browser: Any, server_url: str, token: str) -> None:
    three = [{**PHONE_A, "id": f"ph_00000000000{i}"} for i in range(3)]
    c = _card(browser, server_url, token, Fake(three))
    try:
        assert c.page.locator("#phoneLink").is_disabled()
        assert "the most JARVIS allows" in c.page.locator("#phoneSet").inner_text()
    finally:
        c.close()


# ---- the visual gate -----------------------------------------------------------------------------
def _audit(c: Console, sel: str, vp: str, what: str) -> None:
    c.page.evaluate(FINISH_ANIMATIONS_JS)
    res = c.page.evaluate(DOM_CHECKS_JS, sel)
    assert not res.get("missing"), f"{what}: {sel} is not in the page"
    _assert_clean(res, c.page.evaluate(NAMELESS_JS, sel), c.page.evaluate(WRAP_JS, sel), vp, what)


@pytest.mark.parametrize("vp", ["desktop", "phone"])
@pytest.mark.parametrize("surface", ["night", "day"])
def test_the_card_and_the_code_pass_the_visual_gate(
    browser: Any, server_url: str, token: str, vp: str, surface: str
) -> None:
    fake = Fake([PHONE_A, {**PHONE_A, "id": "ph_ba9876543210", "model": "tablet", "can": {}}])
    fake.link_after_code = False
    c = _card(browser, server_url, token, fake, DESKTOP if vp == "desktop" else PHONE)
    try:
        if surface == "day":
            c.choose_day()
        c.page.locator("#phoneSet").scroll_into_view_if_needed()
        _audit(c, "#phoneSet", vp, f"Phone app card ({vp}, {surface})")
        c.page.locator("#phoneLink").click()
        c.page.locator("#phoneCode").wait_for()
        _audit(c, "#phoneDialog", vp, f"link code dialog ({vp}, {surface})")
        assert c.page.evaluate("() => document.documentElement.scrollWidth <= innerWidth")
        _clean(c)
    finally:
        c.close()
