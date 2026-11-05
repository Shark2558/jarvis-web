# tests/browser/test_vault.py -- the Vault panel (R2 D1-D8) in a real browser: the real console's
# `#p-vault > .pbody > #vaultBody` with its own console-vault*.js/.css (R2 I1 put them in
# console.html), opened from the dock; /v1/vault* is faked (shapes: src/jarvis/api/vault.py). They
# pin the console's side of the contract: the list, the unlock dialog (focus trap, Esc), the
# ticket/download hand-off, delete with Undo, upload then confirm, and that every server string is
# text only.
from __future__ import annotations

import base64
import json
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import pytest
from test_console import DESKTOP, PHONE, Console

_pw = pytest.importorskip("playwright.sync_api")
sync_playwright = _pw.sync_playwright

pytestmark = pytest.mark.browser

PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR4nGP4z8DwHwAFAAH/"
    "q842iQAAAABJRU5ErkJggg=="
)
HOSTILE = '<img src=x onerror="window.__pwned=1">Passport'
TOKEN_VALUE = "vt_" + "a" * 40


def item(**kw: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "id": "v_0123456789ab",
        "type": "passport",
        "type_label": "Passport",
        "normally_expires": True,
        "holder_id": "me",
        "holder": "you",
        "title": "Passport",
        "last4": "4821",
        "ends": "\u2022\u20224821",
        "note": "",
        "issued_on": "2020-01-01",
        "expires_on": "2026-12-13",
        "days_left": 38,
        "dates_confirmed": True,
        "needs_check": False,
        "reminders": [30, 7],
        "from_digilocker": False,
        "files": [{"fid": "f_0123456789ab", "mime": "image/png", "size": 70}],
        "proposal": None,
        "created_at": "2026-11-01T00:00:00+00:00",
    }
    return {**base, **kw}


def view(items: list[dict[str, Any]], required: str = "sign_in") -> dict[str, Any]:
    return {
        "available": True,
        "items": items,
        "holders": [
            {"id": "me", "label": "you", "count": sum(1 for i in items if i["holder_id"] == "me")},
            {"id": "h_01234567", "label": "Anjali", "count": 0},
        ],
        "totals": {"items": len(items), "max_items": 100, "mb": 0.1, "limit_mb": 150},
        "settings": {"alert_detail": "generic", "brief": True, "inbox_copy": False},
        "unlock": {"required": required, "console": True},
    }


def _json(route: Any, status: int, body: Any) -> None:
    route.fulfill(status=status, content_type="application/json", body=json.dumps(body))


class FakeVault:
    """Answers /v1/vault* and the Recently-deleted restore for one page; records every request."""

    def __init__(self, page: Any, data: dict[str, Any]) -> None:
        self.data = data
        self.calls: list[dict[str, Any]] = []
        self.unlock_answer: tuple[int, Any] | None = None
        self.inbox: dict[str, Any] = {"available": False}
        page.route("**/v1/vault**", self._vault)
        page.route("**/v1/deleted/**", self._deleted)

    def _record(self, route: Any) -> dict[str, Any]:
        req = route.request
        raw = req.post_data_buffer
        call = {
            "path": urlsplit(req.url).path,
            "query": urlsplit(req.url).query,
            "method": req.method,
            "raw": raw,
            "body": json.loads(raw)
            if raw and req.headers.get("content-type", "").startswith("application/json")
            else None,
            "headers": dict(req.headers),
        }
        self.calls.append(call)
        return call

    def _vault(self, route: Any) -> None:
        call = self._record(route)
        path, method = call["path"], call["method"]
        if path == "/v1/vault" and method == "GET":
            _json(route, 200, self.data)
        elif path == "/v1/vault/inbox/check":
            _json(route, 200, {"imported": 2, "skipped": 0, "more": False})
        elif path == "/v1/vault/inbox":
            _json(route, 200, self.inbox)
        elif path == "/v1/vault/unlock" and method == "POST":
            _json(
                route,
                *(self.unlock_answer or (200, {"token": TOKEN_VALUE, "until": "x", "minutes": 10})),
            )
        elif path == "/v1/vault/unlock":
            _json(route, 200, {"locked": True})
        elif path.endswith("/ticket"):
            ok = call["headers"].get("x-jarvis-vault") == TOKEN_VALUE
            _json(route, 200, {"ticket": "t" * 30, "expires_in_s": 60}) if ok else _json(
                route, 403, {"error": "locked", "detail": "Unlock the vault first."}
            )
        elif path.startswith("/v1/vault/download/"):
            route.fulfill(
                status=200,
                body=PNG,
                headers={
                    "Content-Type": "image/png",
                    "Content-Disposition": 'attachment; filename="passport.png"',
                },
            )
        elif path == "/v1/vault/upload":
            self.data = view(
                [
                    item(
                        id="v_aaaaaaaaaaaa",
                        dates_confirmed=False,
                        needs_check=True,
                        days_left=None,
                        expires_on=None,
                        issued_on=None,
                        last4=None,
                        ends=None,
                        reminders=[],
                        proposal={
                            "type": "passport",
                            "type_label": "Passport",
                            "issued_on": "2020-01-01",
                            "issued_label": "Date of issue",
                            "expires_on": "2030-01-01",
                            "expires_label": "Date of expiry",
                            "last4": "9999",
                        },
                    )
                ]
            )
            _json(
                route,
                201,
                {
                    "item": self.data["items"][0],
                    "proposal": self.data["items"][0]["proposal"],
                    "duplicate": False,
                },
            )
        elif method == "PATCH":
            body = call["body"]
            self.data = view(
                [item(id=call["path"].rsplit("/", 1)[-1], reminders=body.get("reminders", [30, 7]))]
            )
            _json(route, 200, self.data["items"][0])
        elif method == "DELETE":
            self.data = view([])
            _json(route, 200, {"undo_id": "del_" + "0" * 20, "kind": "vault_item"})
        else:
            _json(route, 200, {})

    def _deleted(self, route: Any) -> None:
        self._record(route)
        self.data = view([item()])
        _json(route, 200, {"status": "restored", "message": "Restored."})

    def to(self, method: str, prefix: str = "") -> list[dict[str, Any]]:
        return [c for c in self.calls if c["method"] == method and c["path"].startswith(prefix)]


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
        made.append(c)
        return c

    yield factory
    for c in made:
        c.close()


def _panel(c: Console, data: dict[str, Any]) -> tuple[FakeVault, Any]:
    fake = FakeVault(c.page, data)
    c.open()
    c.open_panel("vault")  # the real panel, from the dock (or More on a phone)
    return fake, c.page.locator("#vaultBody")


def _toggle(c: Console, open_: bool) -> None:
    c.page.evaluate(
        "o => o ? window.JarvisDeck.open('vault') : window.JarvisDeck.close('vault')", open_
    )


def test_empty_vault_says_how_to_start(make: Callable[..., Console]) -> None:
    c = make()
    _, body = _panel(c, view([]))
    body.locator(".vempty").wait_for()
    text = str(body.text_content())
    assert "No documents yet" in text and "0.1 MB of 150 MB" in text
    assert c.errors == [] and c.csp_violations() == []


def test_list_shows_type_last4_and_time_left_in_words(make: Callable[..., Console]) -> None:
    c = make()
    items = [
        item(),
        item(
            id="v_bbbbbbbbbbbb",
            type="pan",
            type_label="PAN card",
            title="",
            dates_confirmed=False,
            holder_id="h_01234567",
            holder="Anjali",
            from_digilocker=True,
            expires_on=None,
            days_left=None,
        ),
    ]
    _, body = _panel(c, view(items))
    body.locator(".vitem").first.wait_for()
    text = str(body.text_content())
    assert "\u2022\u20224821" in text and "in 38 days" in text
    assert "Check details" in text and "From DigiLocker" in text and "Anjali" in text
    assert "\u20b9" not in text and "$" not in text


def test_hostile_titles_are_text_not_markup(make: Callable[..., Console]) -> None:
    c = make()
    _, body = _panel(c, view([item(title=HOSTILE)]))
    body.locator(".vitem").wait_for()
    assert "onerror" in str(body.locator(".vtitle").text_content())
    assert body.locator("img").count() == 0
    assert c.page.evaluate("window.__pwned") is None


def test_opening_asks_to_unlock_then_uses_ticket_and_shows_the_picture(
    make: Callable[..., Console],
) -> None:
    c = make()
    fake, body = _panel(c, view([item()]))
    body.locator(".vhead").click()
    body.get_by_role("button", name="Open", exact=True).click()
    c.page.locator(".vd-box").wait_for()
    assert fake.to("POST", "/v1/vault/unlock") == []  # nothing yet: the owner decides
    c.page.locator(".vd-box button[data-act=go]").click()
    body.locator("img.vpreview").wait_for()
    (ticket,) = [x for x in fake.calls if x["path"].endswith("/ticket")]
    assert ticket["headers"]["x-jarvis-vault"] == TOKEN_VALUE
    assert ticket["path"] == "/v1/vault/items/v_0123456789ab/files/f_0123456789ab/ticket"
    assert [x["path"] for x in fake.calls if "/download/" in x["path"]] == [
        "/v1/vault/download/" + "t" * 30
    ]
    # the token lives in memory only
    assert (
        c.page.evaluate("JSON.stringify([localStorage, sessionStorage, document.cookie])").count(
            TOKEN_VALUE
        )
        == 0
    )


def test_cancel_and_escape_do_nothing_and_return_focus(make: Callable[..., Console]) -> None:
    c = make()
    fake, body = _panel(c, view([item()]))
    body.locator(".vhead").click()
    opener = body.get_by_role("button", name="Open", exact=True)
    opener.click()
    c.page.locator(".vd-box").wait_for()
    c.page.keyboard.press("Escape")
    c.page.locator(".vd-box").wait_for(state="detached")
    assert fake.to("POST", "/v1/vault/unlock") == [] and not [
        x for x in fake.calls if "ticket" in x["path"]
    ]
    opener.click()
    c.page.locator(".vd-box").wait_for()
    for _ in range(4):  # Tab never leaves the dialog
        c.page.keyboard.press("Tab")
        assert c.page.evaluate("!!document.activeElement.closest('.vd-box')") is True
    c.page.locator(".vd-box button[data-act='']").click()
    c.page.locator(".vd-box").wait_for(state="detached")


def test_passkey_is_used_when_the_server_requires_it(make: Callable[..., Console]) -> None:
    c = make()
    fake, body = _panel(c, view([item()], required="passkey"))
    c.page.evaluate(
        "window.JarvisPasskey = Object.assign({}, window.JarvisPasskey,"
        " {prove: async (p) => ({purpose: p, stub: true})})"
    )
    body.locator(".vhead").click()
    body.get_by_role("button", name="Open", exact=True).click()
    c.page.locator(".vd-box button[data-act=go]").click()
    body.locator("img.vpreview").wait_for()
    (unlock,) = fake.to("POST", "/v1/vault/unlock")
    assert unlock["body"] == {"proof": {"purpose": "vault_unlock", "stub": True}}


def test_a_reauth_answer_offers_google_sign_in_and_no_file_is_fetched(
    make: Callable[..., Console],
) -> None:
    c = make()
    fake, body = _panel(c, view([item()]))
    fake.unlock_answer = (403, {"error": "reauth_required", "detail": "Sign in with Google again."})
    body.locator(".vhead").click()
    body.get_by_role("button", name="Open", exact=True).click()
    c.page.locator(".vd-box button[data-act=go]").click()
    c.page.locator(".vd-box", has_text="Sign in with Google again").wait_for()
    assert not [x for x in fake.calls if "/download/" in x["path"]]


def test_closing_the_panel_forgets_the_unlock(make: Callable[..., Console]) -> None:
    c = make()
    fake, body = _panel(c, view([item()]))
    body.locator(".vhead").click()
    body.get_by_role("button", name="Open", exact=True).click()
    c.page.locator(".vd-box button[data-act=go]").click()
    body.locator("img.vpreview").wait_for()
    _toggle(c, False)
    c.page.wait_for_function("true")
    _toggle(c, True)
    body.locator(".vitem").wait_for()
    assert fake.to("DELETE", "/v1/vault/unlock")
    body.locator(".vhead").click()
    body.get_by_role("button", name="Open", exact=True).click()
    c.page.locator(".vd-box").wait_for()  # asked again


def test_delete_asks_first_then_offers_undo(make: Callable[..., Console]) -> None:
    c = make()
    fake, body = _panel(c, view([item()]))
    body.locator(".vhead").click()
    body.get_by_role("button", name="Delete", exact=True).click()
    c.page.locator(".vd-box button[data-act='']").click()
    assert fake.to("DELETE", "/v1/vault/items") == []
    body.get_by_role("button", name="Delete", exact=True).click()
    c.page.locator(".vd-box button[data-act=del]").click()
    body.locator(".vnote button", has_text="Undo").wait_for()
    body.locator(".vnote button", has_text="Undo").click()
    body.locator(".vitem").wait_for()
    (restore,) = fake.to("POST", "/v1/deleted/")
    assert restore["path"] == "/v1/deleted/del_" + "0" * 20 + "/restore"


def test_upload_then_confirm_sends_the_checked_dates(
    make: Callable[..., Console], tmp_path: Path
) -> None:
    c = make()
    fake, body = _panel(c, view([]))
    body.locator("#vaultAdd").click()
    png = tmp_path / "passport.png"
    png.write_bytes(PNG)
    body.locator("#vaultFile").set_input_files(str(png))
    body.get_by_role("button", name="Add to vault").click()
    body.locator("#vaultEExp").wait_for()
    (up,) = fake.to("POST", "/v1/vault/upload")
    assert up["raw"] == PNG
    assert body.locator("#vaultEExp").input_value() == "2030-01-01"
    body.locator("#vaultELast4").fill("1234")
    body.get_by_role("button", name="Confirm", exact=True).click()
    body.locator(".vitem").wait_for()
    (patch,) = fake.to("PATCH")
    assert patch["body"]["confirm"] is True and patch["body"]["last4"] == "1234"
    assert patch["body"]["expires_on"] == "2030-01-01"


def test_a_wrong_file_type_never_reaches_the_server(
    make: Callable[..., Console], tmp_path: Path
) -> None:
    c = make()
    fake, body = _panel(c, view([]))
    body.locator("#vaultAdd").click()
    bad = tmp_path / "notes.txt"
    bad.write_text("hello")
    body.locator("#vaultFile").set_input_files(str(bad))
    body.get_by_role("button", name="Add to vault").click()
    body.locator(".vnote", has_text="Use a PDF, JPEG or PNG").wait_for()
    assert fake.to("POST", "/v1/vault/upload") == []


def test_reminder_ticks_send_the_new_list(make: Callable[..., Console]) -> None:
    c = make()
    fake, body = _panel(c, view([item()]))
    body.locator(".vhead").click()
    body.get_by_label("90 days").check()
    body.locator(".vtick input").first.wait_for()
    (patch,) = fake.to("PATCH")
    assert patch["body"] == {"reminders": [90, 30, 7]}


def test_export_uses_a_ticket_and_downloads(make: Callable[..., Console]) -> None:
    c = make()
    fake, body = _panel(c, view([item()]))
    body.locator("#vaultExport").click()
    with c.page.expect_download() as dl:
        c.page.locator(".vd-box button[data-act=go]").click()
    assert dl.value.suggested_filename == "passport.png"
    assert [x for x in fake.calls if x["path"] == "/v1/vault/export/ticket"]


def test_unavailable_says_why(make: Callable[..., Console]) -> None:
    c = make()
    _, body = _panel(
        c,
        {
            "available": False,
            "reason": "Not available on this server (no encryption key).",
            "items": [],
            "holders": [],
        },
    )
    body.locator("text=no encryption key").wait_for()
    assert body.locator("#vaultAdd").count() == 0


def test_phone_layout_has_no_sideways_scroll(make: Callable[..., Console]) -> None:
    c = make(PHONE)
    _, body = _panel(c, view([item(title="A very long document title " * 3)]))
    body.locator(".vitem").wait_for()
    assert (
        c.page.evaluate(
            "document.documentElement.scrollWidth > document.documentElement.clientWidth"
        )
        is False
    )


def test_brief_documents_section_shows_type_and_time_only(make: Callable[..., Console]) -> None:
    c = make()
    _panel(c, view([]))
    text = c.page.evaluate(
        """() => window.JarvisBriefSections.render({vault: {total: 7, items: [
          {type_label: 'Passport', whose: 'family', expires_on: '2026-12-13', days_left: 38},
          {type_label: 'PUC certificate', whose: 'you', expires_on: '2026-11-01', days_left: -4}]}})
          .map((n) => n.textContent).join('|')"""
    )
    assert "Passport" in text and "expires in 38 days" in text and "expired 4 days ago" in text
    assert "family" in text and "5 more" in text and "4821" not in text
    assert c.page.evaluate("window.JarvisBriefSections.render({}).length") == 0


def test_check_digilocker_now_reports_how_many_came_in(make: Callable[..., Console]) -> None:
    c = make()
    fake = FakeVault(c.page, view([]))
    fake.inbox = {"available": True, "configured": True}
    c.open()
    c.open_panel("vault")
    c.page.locator("#vaultCheck").click()
    c.page.locator(".vnote", has_text="2 documents imported").wait_for()
    assert fake.to("POST", "/v1/vault/inbox/check")


def test_not_set_up_inbox_points_to_integrations(make: Callable[..., Console]) -> None:
    c = make()
    fake = FakeVault(c.page, view([]))
    fake.inbox = {"available": True, "configured": False}
    c.open()
    c.open_panel("vault")
    c.page.locator("text=set it up in Integrations").wait_for()
    assert c.page.locator("#vaultCheck").count() == 0
