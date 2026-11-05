# tests/browser/test_privacy.py - R2 D14 in a real browser: the Privacy panel renders one card per
# category (text only, hostile strings inert), Export downloads, the delete dialog (focus trap,
# Escape, typed DELETE + re-sign-in, passkey proof bound to category and rev, 409 "changed") and a
# 390 px phone with no horizontal scroll.
# console.html gets its p-privacy panel at I1, so the panel is hosted on a small page here that has
# the same `#p-privacy .pbody`, the console's css tokens and a JarvisConsole.api with the console's
# error shape; /v1/privacy* is answered by the test (page.route).
from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

_pw = pytest.importorskip("playwright.sync_api")
sync_playwright = _pw.sync_playwright

pytestmark = pytest.mark.browser

STATIC = Path(__file__).resolve().parents[2] / "src" / "jarvis" / "api" / "static"
HOST = "http://harness.test"
HOSTILE = '<img src=x onerror="window.__pwned=1">Notes'

PAGE = """<!doctype html><html data-motion="calm"><head><meta charset="utf-8">
<style>:root{--ink:#0D1828;--ink-2:#44546A;--ink-3:#536176;--line-2:#E8EDF3;--ok-ink:#0A6F47;
--bad-ink:#B42318;--bad-tint:#FFF3F2;--bad-line:#F4C4BF;--tech:monospace;--r-sm:6px;--well-2:#f4f6f9}
body{font:14px system-ui;margin:0}.btn{height:32px;padding:0 10px}
.bnote{padding:8px;border:1px solid #ddd}</style></head>
<body><section id="p-privacy"><div class="pbody"></div></section>
<script>
window.__pwned = 0; window.__passkey = [];
window.JarvisConsole = { async api(path, opts = {}) {
  const has = opts.body !== undefined;
  const r = await fetch(path, { method: opts.method || (has ? 'POST' : 'GET'),
    headers: { 'Content-Type': 'application/json' },
    body: has ? JSON.stringify(opts.body) : undefined });
  if (!r.ok) { let j = {}; try { j = await r.json(); } catch (_) {}
    const e = new Error(j.detail || r.statusText); e.status = r.status;
    if (j.error) e.code = j.error;
    throw e; }
  return r.json();
} };
window.JarvisPasskey = { supported: () => true, prove: async (p, t) => {
  window.__passkey.push([p, t]); return { challenge_id: 'c1', credential: {} }; } };
</script></body></html>"""


def cat(cid: str, **kw: Any) -> dict[str, Any]:
    base = {
        "id": cid,
        "section": "What JARVIS remembers",
        "label": cid.title(),
        "what": f"The {cid}.",
        "count": 2,
        "unit": "items",
        "retention": "Until deleted.",
        "where": "Firestore",
        "size_hint": None,
        "encrypted_by_jarvis": False,
        "export": True,
        "delete": "simple",
        "recoverable": False,
        "note": "",
        "rev": f"rev{cid}",
        "available": True,
    }
    base.update(kw)
    return base


class Backend:
    def __init__(self, cats: list[dict[str, Any]], passkey: bool = False) -> None:
        self.cats, self.passkey = cats, passkey
        self.deletes: list[tuple[str, dict[str, Any]]] = []
        self.delete_reply: tuple[int, dict[str, Any]] = (
            200,
            {"deleted": 2, "category": "x", "remaining": 0},
        )
        self.gets = 0
        self.exports: list[tuple[str, str, dict[str, Any]]] = []

    def handle(self, route: Any) -> None:
        req = route.request
        path = req.url.removeprefix(HOST)
        if path == "/":
            route.fulfill(status=200, content_type="text/html", body=PAGE)
        elif path == "/v1/privacy" and req.method == "GET":
            self.gets += 1
            body = {"categories": self.cats, "passkey_in_force": self.passkey, "generated_at": "x"}
            route.fulfill(status=200, content_type="application/json", body=json.dumps(body))
        elif path.endswith("/export"):
            cid = path.split("/")[3]
            self.exports.append((req.method, cid, json.loads(req.post_data or "{}")))
            route.fulfill(
                status=200,
                content_type="application/json",
                body=json.dumps({"category": cid, "data": {"items": ["a"]}}),
            )
        elif path == "/v1/privacy/export-all":
            self.deletes.append(("export-all", json.loads(req.post_data or "{}")))
            route.fulfill(
                status=200,
                content_type="application/json",
                body=json.dumps({"categories": {}, "vault_files": "Vault"}),
            )
        elif path.endswith("/delete"):
            cid = path.split("/")[3]
            self.deletes.append((cid, json.loads(req.post_data or "{}")))
            status, body = self.delete_reply
            route.fulfill(status=status, content_type="application/json", body=json.dumps(body))
        else:
            route.fulfill(status=404, body="{}")


@pytest.fixture(scope="module")
def browser() -> Iterator[Any]:
    with sync_playwright() as p:
        b = p.chromium.launch()
        yield b
        b.close()


def open_panel(browser: Any, backend: Backend, viewport: dict[str, int] | None = None) -> Any:
    ctx = browser.new_context(
        viewport=viewport or {"width": 1200, "height": 900}, accept_downloads=True
    )
    page = ctx.new_page()
    errors: list[str] = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.route(HOST + "/**", backend.handle)
    page.goto(HOST + "/")
    page.add_style_tag(content=(STATIC / "console-privacy.css").read_text())
    page.add_script_tag(content=(STATIC / "console-privacy.js").read_text())
    page.evaluate(
        "document.dispatchEvent(new CustomEvent('jarvis:panel',{detail:{id:'privacy',open:true}}))"
    )
    page.locator(".pv-card").first.wait_for()
    page.errors = errors  # type: ignore[attr-defined]
    page.ctx = ctx  # type: ignore[attr-defined]
    return page


def test_cards_are_grouped_and_hostile_text_stays_text(browser: Any) -> None:
    be = Backend(
        [
            cat("notes", label=HOSTILE, encrypted_by_jarvis=True, delete="passkey"),
            cat(
                "audit",
                section="Settings and safety",
                delete="none",
                export=True,
                note="It is the security record, so it can't be deleted.",
            ),
            cat(
                "faces",
                section="Faces",
                count=0,
                export=False,
                delete="none",
                note="Not built yet. Nothing is stored.",
            ),
            cat(
                "drive",
                available=False,
                count=None,
                note="Couldn't check right now.",
                export=False,
                delete="none",
            ),
        ]
    )
    page = open_panel(browser, be)
    assert page.evaluate("window.__pwned") == 0 and page.locator("#pvRoot img").count() == 0
    assert HOSTILE in page.locator("#pv-notes .pv-label").inner_text()
    assert "Encrypted by JARVIS" in str(page.locator("#pv-notes").text_content())
    assert page.locator(".pv-h").all_text_contents() == [
        "What JARVIS remembers",
        "Settings and safety",
        "Faces",
    ]
    assert "Not built yet. Nothing is stored." in page.locator("#pv-faces").inner_text()
    assert page.locator("#pv-faces button").count() == 0
    assert "Couldn't check right now" in page.locator("#pv-drive").inner_text()
    assert page.locator("#pv-drive button").count() == 0
    assert page.locator("#pv-audit button", has_text="Delete").count() == 0
    assert "2 kinds" in page.locator("#pvSum").inner_text()
    assert page.errors == []  # type: ignore[attr-defined]
    page.ctx.close()  # type: ignore[attr-defined]


def test_export_downloads_a_json_file(browser: Any) -> None:
    page = open_panel(browser, Backend([cat("places")]))
    with page.expect_download() as dl:
        page.locator("#pv-places button", has_text="Export").click()
    assert dl.value.suggested_filename.startswith("jarvis-places-")
    data = json.loads(Path(dl.value.path()).read_text())
    assert data["category"] == "places"
    page.ctx.close()  # type: ignore[attr-defined]


def test_h1_a_content_export_carries_a_proof_bound_to_the_export(browser: Any) -> None:
    be = Backend([cat("notes", delete="passkey"), cat("places")], passkey=True)
    page = open_panel(browser, be)
    with page.expect_download() as dl:
        page.locator("#pv-notes button", has_text="Export").click()
    assert dl.value.suggested_filename.startswith("jarvis-notes-")
    assert page.evaluate("window.__passkey") == [["privacy_export", "export:notes"]]
    assert be.exports[0][:2] == ("POST", "notes") and be.exports[0][2]["proof"]["challenge_id"]
    with page.expect_download():
        page.locator("#pv-places button", has_text="Export").click()
    assert be.exports[1] == ("POST", "places", {})  # a simple category needs no proof
    assert len(page.evaluate("window.__passkey")) == 1
    page.ctx.close()  # type: ignore[attr-defined]


def test_h1_a_stale_sign_in_on_export_offers_to_sign_in_again(browser: Any) -> None:
    be = Backend([cat("notes", delete="passkey")])
    page = open_panel(browser, be)
    page.route(
        HOST + "/v1/privacy/notes/export",
        lambda r: r.fulfill(
            status=403,
            content_type="application/json",
            body=json.dumps(
                {"error": "proof_required", "reason": "reauth", "detail": "Sign in again first."}
            ),
        ),
    )
    page.locator("#pv-notes button", has_text="Export").click()
    page.locator("#pvReauth").wait_for()
    assert "Sign in again first." in page.locator("#pvNote").inner_text()
    page.ctx.close()  # type: ignore[attr-defined]


def test_m5_the_dialog_shows_what_the_delete_removes_not_the_whole_count(browser: Any) -> None:
    be = Backend([cat("spend", count=3, unit="months", delete_count=2, delete="passkey")])
    page = open_panel(browser, be)
    page.locator("#pv-spend button", has_text="Delete").click()
    text = page.locator("[role=dialog]").inner_text()
    assert "2 months" in text and "3 months" not in text
    page.ctx.close()  # type: ignore[attr-defined]


def test_m4_a_delete_that_left_rows_says_how_many_are_still_there(browser: Any) -> None:
    be = Backend([cat("places")])
    be.delete_reply = (200, {"deleted": 1, "category": "places", "remaining": 3})
    page = open_panel(browser, be)
    page.locator("#pv-places button", has_text="Delete").click()
    page.locator("#pvGo").click()
    page.locator("[role=dialog]").wait_for(state="detached")
    text = page.locator("#pvNote").inner_text()
    assert "Deleted 1" in text and "3 are still there" in text
    assert "bad" in str(page.locator("#pvNote").get_attribute("class"))
    page.ctx.close()  # type: ignore[attr-defined]


def test_simple_delete_confirms_posts_the_rev_and_reloads(browser: Any) -> None:
    be = Backend([cat("places")])
    page = open_panel(browser, be)
    page.locator("#pv-places button", has_text="Delete").click()
    dlg = page.locator("[role=dialog]")
    assert "Delete Places?" in dlg.inner_text() and "2 items" in dlg.inner_text()
    assert not page.locator("#pvType").is_visible()
    before = be.gets
    page.locator("#pvGo").click()
    page.locator("[role=dialog]").wait_for(state="detached")
    assert be.deletes == [("places", {"rev": "revplaces"})]
    assert "Deleted 2" in page.locator("#pvNote").inner_text()
    assert be.gets == before + 1
    page.ctx.close()  # type: ignore[attr-defined]


def test_dialog_traps_focus_and_escape_returns_it(browser: Any) -> None:
    page = open_panel(browser, Backend([cat("notes", delete="passkey")]))
    opener = page.locator("#pv-notes button", has_text="Delete")
    opener.click()
    assert page.evaluate("document.activeElement.id") == "pvType"
    seen = set()
    for _ in range(6):
        page.keyboard.press("Tab")
        seen.add(page.evaluate("document.activeElement.id"))
        assert page.evaluate("!!document.activeElement.closest('[role=dialog]')")
    assert {"pvNo", "pvGo", "pvType"} <= seen
    page.keyboard.press("Escape")
    assert page.locator("[role=dialog]").count() == 0
    assert page.evaluate("document.activeElement.getAttribute('aria-label')") == "Delete Notes"
    page.ctx.close()  # type: ignore[attr-defined]


def test_without_passkeys_a_hard_delete_needs_typed_delete_then_a_fresh_sign_in(
    browser: Any,
) -> None:
    be = Backend([cat("notes", delete="passkey")])
    page = open_panel(browser, be)
    page.locator("#pv-notes button", has_text="Delete").click()
    page.locator("#pvType").fill("delete")
    page.locator("#pvGo").click()
    assert "Type DELETE" in page.locator("[role=dialog] [role=alert]").inner_text()
    assert be.deletes == []
    be.delete_reply = (
        403,
        {
            "error": "proof_required",
            "reason": "reauth",
            "detail": "Sign in with Google again first (it counts for 5 minutes).",
        },
    )
    page.locator("#pvType").fill("DELETE")
    page.locator("#pvGo").click()
    page.locator("#pvReauth").wait_for()
    assert be.deletes == [("notes", {"rev": "revnotes", "confirm": "DELETE"})]
    page.ctx.close()  # type: ignore[attr-defined]


def test_with_a_passkey_the_proof_is_bound_to_the_category_and_rev(browser: Any) -> None:
    be = Backend([cat("notes", delete="passkey")], passkey=True)
    page = open_panel(browser, be)
    page.locator("#pv-notes button", has_text="Delete").click()
    assert not page.locator("#pvType").is_visible()
    page.locator("#pvGo").click()
    page.locator("[role=dialog]").wait_for(state="detached")
    assert page.evaluate("window.__passkey") == [["privacy_delete", "notes:revnotes"]]
    assert be.deletes[0][1]["proof"]["challenge_id"] == "c1" and "confirm" not in be.deletes[0][1]
    page.ctx.close()  # type: ignore[attr-defined]


def test_a_changed_rev_says_so_and_reloads(browser: Any) -> None:
    be = Backend([cat("places")])
    be.delete_reply = (409, {"error": "changed", "detail": "This changed - check again."})
    page = open_panel(browser, be)
    before = be.gets
    page.locator("#pv-places button", has_text="Delete").click()
    page.locator("#pvGo").click()
    page.locator("[role=dialog]").wait_for(state="detached")
    assert "This changed" in page.locator("#pvNote").inner_text()
    page.wait_for_function("() => true")
    assert be.gets == before + 1
    page.ctx.close()  # type: ignore[attr-defined]


def test_download_everything_uses_a_passkey_proof_when_in_force(browser: Any) -> None:
    be = Backend([cat("places")], passkey=True)
    page = open_panel(browser, be)
    with page.expect_download() as dl:
        page.locator("#pvAll").click()
    assert dl.value.suggested_filename.startswith("jarvis-everything-")
    assert page.evaluate("window.__passkey") == [["privacy_export", "all"]]
    assert be.deletes[0][0] == "export-all" and "proof" in be.deletes[0][1]
    page.ctx.close()  # type: ignore[attr-defined]


def test_a_phone_has_no_horizontal_scroll(browser: Any) -> None:
    cats = [
        cat(c, where="Firestore, Google-encrypted " * 3, what="A long description " * 8)
        for c in ("memory", "conversations", "vault", "notes")
    ]
    page = open_panel(browser, Backend(cats), {"width": 390, "height": 844})
    assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
    page.ctx.close()  # type: ignore[attr-defined]
