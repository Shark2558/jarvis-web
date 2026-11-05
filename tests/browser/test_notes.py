# tests/browser/test_notes.py -- the Notes panel (R2 C, console-notes*.js) in a real browser.
# The panel shell and the asset routes belong to the integrator (console.html,
# api/console.py), so this test brings its own: it adds <section id="p-notes"> to the real console
# page and serves the three files from disk. /v1/notes* is faked with page.route, shaped as
# docs/plans/r2-memory-vault.md says. Covers: empty and off states, add / search / filter,
# textContent only (hostile text stays text), links (https only, rel noopener noreferrer
# nofollow, punycode),
# Fetch page text (credit dialog with a focus trap), delete + Undo, the sensitive refusal, a voice
# memo (fake microphone -> transcript -> edit -> Save), export, 0 JS errors / CSP reports.
from __future__ import annotations

import copy
import json
import re
from collections.abc import Iterator
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlsplit

import pytest
from test_console import DESKTOP, Console

_pw = pytest.importorskip("playwright.sync_api")
sync_playwright, expect = _pw.sync_playwright, _pw.expect

pytestmark = pytest.mark.browser

STATIC = Path(__file__).resolve().parents[2] / "src" / "jarvis" / "api" / "static"
SHELL = (
    '<section class="card" id="p-notes" data-panel="notes" style="position:fixed;top:10px;'
    'left:10px;width:720px;max-height:90vh;overflow:auto;z-index:50">'
    '<div class="pbody"><div id="notes"></div></div></section>'
)
NOTES_URL = re.compile(r".*/v1/(?:notes(?:/[^?]*)?|deleted/del_[0-9a-f]+/restore)(?:\?.*)?$")
TRANSCRIBE_URL = re.compile(r".*/v1/voice/transcribe$")
VOUCH = ("typed", "memo", "imported")


def note(i: int, **over: Any) -> dict[str, Any]:
    n: dict[str, Any] = {
        "id": f"n_{i:012x}",
        "kind": "note",
        "title": f"Note {i}",
        "text": f"Body of note {i}",
        "tags": [],
        "origin": "typed",
        "created_at": "2026-11-03T09:00:00Z",
        "updated_at": f"2026-11-0{min(i, 9)}T09:00:00Z",
        "url": None,
        "host": None,
        "owner_note": "",
        "page": None,
        "trusted": True,
        "snippet": None,
    }
    n.update(over)
    return n


class FakeNotes:
    def __init__(self, page: Any, items: list[dict[str, Any]] | None = None) -> None:
        self.items = copy.deepcopy(items or [])
        self.calls: list[dict[str, Any]] = []
        self.available = True
        self.refuse: tuple[int, dict[str, Any]] | None = None
        self.transcript = "call the bank tomorrow"
        self.transcribe_status = 200
        self.hold = False
        self.held: list[Any] = []
        page.route(NOTES_URL, self._notes)
        page.route(TRANSCRIBE_URL, self._transcribe)

    def to(self, method: str, path: str) -> list[dict[str, Any]]:
        return [c for c in self.calls if c["method"] == method and c["path"] == path]

    def _transcribe(self, route: Any) -> None:
        self.calls.append({"method": "POST", "path": "/v1/voice/transcribe", "body": None})
        if self.hold:
            self.held.append(route)
            return
        if self.transcribe_status != 200:
            route.fulfill(
                status=self.transcribe_status,
                content_type="application/json",
                body=json.dumps({"error": "voice_unavailable", "detail": "off"}),
            )
            return
        body = {"text": self.transcript, "no_speech": False, "seconds": 2.0}
        route.fulfill(status=200, content_type="application/json", body=json.dumps(body))

    def release(self) -> None:
        """Answer every transcription that was held back."""
        held, self.held, self.hold = self.held, [], False
        body = {"text": self.transcript, "no_speech": False, "seconds": 2.0}
        for route in held:
            route.fulfill(status=200, content_type="application/json", body=json.dumps(body))

    def _notes(self, route: Any) -> None:
        req = route.request
        parts = urlsplit(req.url)
        call = {
            "method": req.method,
            "path": parts.path,
            "query": parse_qs(parts.query),
            "body": json.loads(req.post_data) if req.post_data else None,
        }
        self.calls.append(call)
        status, body = self._answer(call)
        route.fulfill(status=status, content_type="application/json", body=json.dumps(body))

    def _page(self, q: dict[str, list[str]]) -> dict[str, Any]:
        items = list(self.items)
        if q.get("kind"):
            items = [n for n in items if n["kind"] == q["kind"][0]]
        if q.get("q"):
            items = [n for n in items if q["q"][0].lower() in (n["title"] + n["text"]).lower()]
        counts = {k: sum(1 for n in self.items if n["kind"] == k) for k in ("note", "memo", "link")}
        return {
            "items": items,
            "total": len(items),
            "page": 1,
            "pages": 1,
            "counts": counts,
            "available": True,
        }

    def _answer(self, c: dict[str, Any]) -> tuple[int, Any]:
        m, p, body = c["method"], c["path"], c["body"] or {}
        if m == "GET" and p == "/v1/notes":
            if not self.available:
                return 200, {
                    "available": False,
                    "reason": "Notes are not available on this server (no encryption key).",
                    "items": [],
                    "total": 0,
                    "page": 1,
                    "pages": 1,
                    "counts": {"note": 0, "memo": 0, "link": 0},
                }
            return 200, self._page(c["query"])
        if m == "GET" and p == "/v1/notes/export":
            return 200, {"format": "jarvis-notes", "version": 1, "notes": self.items}
        if m == "POST" and p.startswith("/v1/deleted/") and p.endswith("/restore"):
            return 200, {"status": "restored", "message": "Restored the note."}
        if self.refuse and m in ("POST", "PATCH"):
            return self.refuse
        if m == "POST" and p == "/v1/notes":
            n = note(
                50 + len(self.items),
                kind=body["kind"],
                title=body.get("title") or (body.get("text") or body.get("url", ""))[:40],
                text=body.get("text", ""),
                origin="memo" if body["kind"] == "memo" else "typed",
                url=body.get("url"),
                owner_note=body.get("owner_note", ""),
                host="xn--bcher-kva.example" if body.get("url") else None,
            )
            self.items.insert(0, n)
            return 201, n
        mm = re.fullmatch(r"/v1/notes/(n_[0-9a-f]{12})(/fetch)?", p)
        if mm:
            found = next((n for n in self.items if n["id"] == mm.group(1)), None)
            if found is None:
                return 404, {"error": "not_found", "detail": "There is no such note."}
            if m == "DELETE":
                self.items.remove(found)
                return 200, {"undo_id": "del_" + "a" * 20, "kind": "note"}
            if mm.group(2) and m == "POST":
                found["page"] = {
                    "title": "Story",
                    "excerpt": "monsoon words <b>x</b>",
                    "fetched_at": "2026-11-05T00:00:00Z",
                }
                found["trusted"] = False
                return 200, found
            if m == "PATCH":
                found.update({k: v for k, v in body.items() if v is not None})
                return 200, found
        return 404, {"error": "not_found", "detail": "nothing here"}


@pytest.fixture(scope="module")
def browser() -> Iterator[Any]:
    with sync_playwright() as p:
        b = p.chromium.launch(
            args=["--use-fake-device-for-media-stream", "--use-fake-ui-for-media-stream"]
        )
        yield b
        b.close()


@pytest.fixture
def console(browser: Any, server_url: str, token: str) -> Iterator[Console]:
    c = Console(browser, server_url, token, DESKTOP)
    c.ctx.grant_permissions(["microphone"])
    yield c
    c.close()


def _asset_handler(path: Path) -> Any:
    kind = "text/css" if path.suffix == ".css" else "application/javascript"

    def handle(route: Any) -> None:
        route.fulfill(status=200, content_type=kind, body=path.read_text(encoding="utf-8"))

    return handle


def serve_assets(page: Any) -> None:
    for name in ("console-notes.js", "console-notes-memo.js", "console-notes.css"):
        page.route(f"**/static/{name}", _asset_handler(STATIC / name))


def open_notes(console: Console, items: list[dict[str, Any]] | None = None) -> FakeNotes:
    page = console.page
    fake = FakeNotes(page, items)
    serve_assets(page)
    console.open()
    page.evaluate("html => document.body.insertAdjacentHTML('beforeend', html)", SHELL)
    page.add_style_tag(url="/static/console-notes.css")
    page.add_script_tag(url="/static/console-notes.js")
    page.add_script_tag(url="/static/console-notes-memo.js")
    page.evaluate(
        "document.dispatchEvent(new CustomEvent('jarvis:panel', "
        "{detail: {id: 'notes', open: true}}))"
    )
    return fake


def clean(console: Console) -> None:
    assert console.csp_violations() == []
    assert console.errors == []


def test_empty_list_says_what_to_do_and_loads_lazily(console: Console) -> None:
    fake = open_notes(console)
    console.page.locator("#notes .empty").wait_for()
    assert "Nothing saved yet" in str(console.page.locator("#notes .empty").text_content())
    assert len(fake.to("GET", "/v1/notes")) == 1
    clean(console)


def test_off_without_a_key_says_why(console: Console) -> None:
    page = console.page
    fake = FakeNotes(page)
    fake.available = False
    serve_assets(page)
    console.open()
    page.evaluate("html => document.body.insertAdjacentHTML('beforeend', html)", SHELL)
    page.add_script_tag(url="/static/console-notes.js")
    page.evaluate(
        "document.dispatchEvent(new CustomEvent('jarvis:panel', "
        "{detail: {id: 'notes', open: true}}))"
    )
    expect(page.locator("#notes .empty")).to_contain_text("no encryption key")
    assert page.locator("#nAdd").count() == 0


def test_add_search_and_filter(console: Console) -> None:
    fake = open_notes(console, [note(1, title="Plumber", text="Ravi on Tuesdays")])
    page = console.page
    page.locator("#nAdd").click()
    page.locator("#nfText").fill("Gym renews in March")
    page.locator("#nfTags").fill("fitness, bills")
    page.locator("#nfSave").click()
    expect(page.locator("#notes .nlist .nrow")).to_have_count(2)
    sent = fake.to("POST", "/v1/notes")[0]["body"]
    assert sent == {"kind": "note", "text": "Gym renews in March", "tags": ["fitness", "bills"]}
    expect(page.locator("#notes .bnote")).to_contain_text("Note saved")
    page.locator("#nSearch").fill("plumber")
    page.locator("#nSearch").press("Enter")
    expect(page.locator("#notes .nlist .nrow")).to_have_count(1)
    assert fake.to("GET", "/v1/notes")[-1]["query"]["q"] == ["plumber"]
    page.get_by_role("button", name="Links").click()
    expect(page.locator("#notes .empty")).to_be_visible()
    clean(console)


def test_hostile_text_stays_text(console: Console) -> None:
    hostile = '<img src=x onerror="window.__pwned=1"><script>window.__pwned=2</script>'
    open_notes(console, [note(1, title=hostile, text=hostile, snippet=hostile)])
    page = console.page
    expect(page.locator("#notes .nt")).to_have_text(hostile[:160])
    page.locator("#nOpen-n_000000000001").click()
    assert page.locator("#notes img, #notes script").count() == 0
    assert page.evaluate("window.__pwned") is None
    clean(console)


def test_links_open_safely_and_never_as_javascript(console: Console) -> None:
    items = [
        note(
            1,
            kind="link",
            title="Books",
            url="https://www.bücher.example/x",
            host="xn--bcher-kva.example",
        ),
        note(2, kind="link", title="Evil", url="javascript:alert(1)", host="evil"),
    ]
    open_notes(console, items)
    page = console.page
    page.locator("#nOpen-n_000000000001").click()
    a = page.locator("#notes a.nanchor")
    expect(a).to_have_text("xn--bcher-kva.example")
    assert a.get_attribute("target") == "_blank"
    assert set((a.get_attribute("rel") or "").split()) == {"noopener", "noreferrer", "nofollow"}
    assert a.get_attribute("href").startswith("https://")  # type: ignore[union-attr]
    page.locator("#nOpen-n_000000000002").click()
    assert page.locator("#notes a[href^='javascript']").count() == 0
    clean(console)


def test_fetch_page_text_asks_first_and_marks_the_text_as_theirs(console: Console) -> None:
    fake = open_notes(
        console,
        [note(1, kind="link", title="Story", url="https://example.com/s", host="example.com")],
    )
    page = console.page
    page.locator("#nOpen-n_000000000001").click()
    page.locator("#nFetch-n_000000000001").click()
    dlg = page.locator("#notes dialog[open]")
    expect(dlg).to_contain_text("1 of your 900 monthly web credits")
    page.keyboard.press("Tab")
    page.keyboard.press("Tab")
    page.keyboard.press("Tab")
    assert page.evaluate("document.activeElement.closest('dialog') !== null")  # the trap holds
    page.keyboard.press("Escape")
    expect(dlg).to_have_count(0)
    assert fake.to("POST", "/v1/notes/n_000000000001/fetch") == []
    page.locator("#nFetch-n_000000000001").click()
    page.get_by_role("button", name="Fetch it").click()
    expect(page.locator("#notes .npage")).to_contain_text("other people's words")
    expect(page.locator("#notes .npage .ntext")).to_have_text("monsoon words <b>x</b>")
    assert fake.to("POST", "/v1/notes/n_000000000001/fetch")[0]["body"] == {"confirm_credit": True}
    clean(console)


def test_delete_is_two_step_and_can_be_undone(console: Console) -> None:
    fake = open_notes(console, [note(1)])
    page = console.page
    page.locator("#nOpen-n_000000000001").click()
    page.locator("#nDel-n_000000000001").click()
    page.locator("#nKeep-n_000000000001").click()
    assert fake.to("DELETE", "/v1/notes/n_000000000001") == []
    page.locator("#nDel-n_000000000001").click()
    page.locator("#nDelYes-n_000000000001").click()
    expect(page.locator("#notes .nundo")).to_be_visible()
    expect(page.locator("#notes .bnote")).to_contain_text("30 days")
    page.locator("#nUndo").click()
    assert len(fake.to("POST", "/v1/deleted/del_" + "a" * 20 + "/restore")) == 1
    clean(console)


def test_edit_saves_a_change(console: Console) -> None:
    fake = open_notes(console, [note(1)])
    page = console.page
    page.locator("#nOpen-n_000000000001").click()
    page.locator("#nEdit-n_000000000001").click()
    page.locator("#neText").fill("Changed body")
    page.locator("#neSave").click()
    assert fake.to("PATCH", "/v1/notes/n_000000000001")[0]["body"]["text"] == "Changed body"
    clean(console)


def test_a_sensitive_refusal_says_where_ids_go(console: Console) -> None:
    fake = open_notes(console)
    fake.refuse = (422, {"error": "sensitive", "detail": "IDs go in the Vault."})
    page = console.page
    page.locator("#nAdd").click()
    page.locator("#nfText").fill("anything")
    page.locator("#nfSave").click()
    expect(page.locator("#notes form .mstat")).to_contain_text("IDs go in the Vault")
    assert page.locator("#nfText").input_value() == "anything"  # nothing is lost
    assert console.csp_violations() == []  # (the browser logs the 422 itself, by design)


def test_voice_memo_becomes_an_editable_transcript_then_saves(console: Console) -> None:
    fake = open_notes(console)
    page = console.page
    page.locator("#nRecord").click()
    expect(page.locator("#nRecord")).to_have_text("Stop")
    page.wait_for_timeout(1500)
    page.locator("#nRecord").click()
    box = page.locator("#nMemoText")
    expect(box).to_have_value("call the bank tomorrow")
    box.fill("Call the bank tomorrow morning")
    page.locator("#nMemoSave").click()
    sent = fake.to("POST", "/v1/notes")[0]["body"]
    assert sent == {"kind": "memo", "text": "Call the bank tomorrow morning"}
    assert len(fake.to("POST", "/v1/voice/transcribe")) >= 1
    expect(page.locator("#nMemo")).to_have_count(0)
    clean(console)


def test_discarding_a_memo_stores_nothing(console: Console) -> None:
    fake = open_notes(console)
    page = console.page
    page.locator("#nRecord").click()
    page.wait_for_timeout(800)
    page.locator("#nRecord").click()
    page.locator("#nMemoDiscard").click()
    assert fake.to("POST", "/v1/notes") == []
    expect(page.locator("#nMemo")).to_have_count(0)


def test_export_downloads_a_json_file(console: Console) -> None:
    open_notes(console, [note(1)])
    page = console.page
    page.locator("#notes summary").click()
    with page.expect_download() as dl:
        page.locator("#nExport").click()
    assert dl.value.suggested_filename.startswith("jarvis-notes-")
    assert dl.value.suggested_filename.endswith(".json")


def test_a_late_transcript_after_discard_leaves_no_ghost_text(console: Console) -> None:
    fake = open_notes(console)
    fake.hold = True
    page = console.page
    page.locator("#nRecord").click()
    page.wait_for_timeout(1500)
    page.locator("#nRecord").click()  # Stop: the piece is on its way, the answer is held back
    expect(page.locator("#nMemoDiscard")).to_be_visible()
    page.locator("#nMemoDiscard").click()
    fake.release()
    page.wait_for_timeout(500)
    expect(page.locator("#nMemo")).to_have_count(0)
    assert fake.to("POST", "/v1/notes") == []
    page.locator("#nRecord").click()  # a new memo starts clean
    page.wait_for_timeout(500)
    page.locator("#nRecord").click()
    expect(page.locator("#nMemoText")).to_have_value("call the bank tomorrow")
    clean(console)


def test_save_waits_until_the_whole_recording_is_in_words(console: Console) -> None:
    fake = open_notes(console)
    fake.hold = True
    page = console.page
    page.locator("#nRecord").click()
    page.wait_for_timeout(1500)
    page.locator("#nRecord").click()
    save = page.locator("#nMemoSave")
    expect(save).to_have_attribute("aria-disabled", "true")
    save.click(force=True)
    assert fake.to("POST", "/v1/notes") == []  # a half-finished memo is never stored
    fake.release()
    expect(page.locator("#nMemoText")).to_have_value("call the bank tomorrow")
    expect(save).not_to_have_attribute("aria-disabled", "true")
    save.click()
    assert fake.to("POST", "/v1/notes")[0]["body"]["text"] == "call the bank tomorrow"
    clean(console)


def test_editing_an_outside_note_asks_before_taking_it_as_mine(console: Console) -> None:
    fake = open_notes(console, [note(1, origin="outside", trusted=False)])
    page = console.page
    page.locator("#nOpen-n_000000000001").click()
    page.locator("#nEdit-n_000000000001").click()
    page.locator("#neText").fill("Changed body")
    page.locator("#neSave").click()
    assert "adopt" not in fake.to("PATCH", "/v1/notes/n_000000000001")[0]["body"]
    page.locator("#nEdit-n_000000000001").click()
    page.locator("#neAdopt").check()
    page.locator("#neSave").click()
    assert fake.to("PATCH", "/v1/notes/n_000000000001")[1]["body"]["adopt"] is True
    clean(console)
