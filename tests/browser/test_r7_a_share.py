# tests/browser/test_r7_a_share.py -- R7 Part A, sharing into JARVIS (docs/plans/r7-mobile.md
# D12, D15; acceptance check 7) in a real browser against the real backend (mock brain):
#   - the share worker (app-share-sw.js, run here with a stand-in `self` and the page's real Cache
#     Storage): a form post of two files gives two tray items and a 303 to /?do=shared; a sixth
#     item, an 11 MB file and an .exe are refused in plain words; a line of text is kept;
#   - for real: the tray registers the worker (scope /app/share/), a share-sheet form post lands
#     in the tray with two items, and the POST never reached the network;
#   - with no worker the server's page says "Open JARVIS once, then share again.";
#   - no request leaves the browser until a button is pressed (a network spy), then exactly one;
#   - signed out the tray asks the server nothing and keeps its items; after sign-in it opens;
#   - a WebP is redrawn as a JPEG of at most 1,568 px before it is sent (I0's one picture door);
#   - "Ask the AI" reads "The brain answering now can't see pictures." and sends nothing;
#   - the tray passes the visual gate at 1440x900 and 390x844, Night and Day; 0 JS errors, 0 CSP
#     reports.
from __future__ import annotations

import base64
import json
import sys
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from test_console import DESKTOP, PHONE, Console
from test_ui_audit import NAMELESS_JS, WRAP_JS, _assert_clean
from ui_checks import DOM_CHECKS_JS, FINISH_ANIMATIONS_JS

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from jarvis.documents.imagecheck import _jpeg_size  # noqa: E402

_pw = pytest.importorskip("playwright.sync_api")
sync_playwright = _pw.sync_playwright
pytestmark = pytest.mark.browser

STATIC = Path(__file__).resolve().parents[2] / "src" / "jarvis" / "api" / "static"
SW_SRC = (STATIC / "app-share-sw.js").read_text(encoding="utf-8")
MB = 1024 * 1024
SENDS = ("/v1/attachments", "/v1/vault/upload", "/v1/chat", "/v1/input/estimate")

# Runs the share worker's fetch handler in the page (same origin, the page's real Cache Storage)
# with files drawn in the page: {name, type, draw: [w, h]} (a picture) or {name, type, size}.
HARNESS = """async ([src, spec]) => {
  const MAGIC = { 'image/jpeg': [0xff, 0xd8, 0xff],
    'image/png': [0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a],
    'image/webp': [0x52, 0x49, 0x46, 0x46, 0, 0, 0, 0, 0x57, 0x45, 0x42, 0x50],
    'application/pdf': [0x25, 0x50, 0x44, 0x46, 0x2d] };
  const handlers = {};
  const fake = { addEventListener: (n, f) => { handlers[n] = f; }, skipWaiting() {},
    location: new URL(location.origin + '/app/share/sw.js'), crypto: self.crypto };
  new Function('self', src)(fake);
  const form = new FormData();
  for (const [k, v] of Object.entries(spec.fields || {})) form.append(k, v);
  for (const f of spec.files || []) {
    let blob;
    if (f.draw) {
      const c = new OffscreenCanvas(f.draw[0], f.draw[1]), g = c.getContext('2d');
      const [w, h] = f.draw;
      g.fillStyle = '#3a6ea5'; g.fillRect(0, 0, w, h);
      g.fillStyle = '#f2c14e'; g.fillRect(w / 4, h / 4, w / 2, h / 2);
      blob = await c.convertToBlob({ type: f.type });
    } else {
      const bytes = new Uint8Array(f.size || 0);
      const head = f.bytes || MAGIC[f.type] || [];
      bytes.set(head.slice(0, bytes.length));
      blob = new Blob([f.bytes && !f.size ? new Uint8Array(f.bytes) : bytes], { type: f.type });
    }
    form.append('files', new File([blob], f.name, { type: f.type }));
  }
  let request = new Request(location.origin + '/app/share/in', { method: spec.method || 'POST',
    body: spec.method === 'GET' ? undefined : form });
  // Headers a page may not set (Origin, Sec-Fetch-Site, Content-Length): a stand-in reports them.
  window.__formRead = false;
  if (spec.headers) {
    const real = request;
    request = { method: real.method, url: real.url, clone: () => real.clone(),
      headers: { get: (k) => (k in spec.headers ? spec.headers[k] : null) },
      formData: () => { window.__formRead = true; return real.formData(); } };
  }
  let answer = null;
  handlers.fetch({ request, respondWith: (p) => { answer = p; } });
  const res = answer ? await answer : null;
  return res ? { status: res.status, location: res.headers.get('Location') } : null;
}"""
TRAY = """async () => {
  const cache = await caches.open('jarvis-share-v1'), out = { items: [], notice: null };
  for (const req of await cache.keys()) {
    const res = await cache.match(req), path = new URL(req.url).pathname;
    if (path === '/app/share/notice') { out.notice = await res.json(); continue; }
    const h = (k) => res.headers.get(k);
    out.items.push({ path, kind: h('X-Jarvis-Kind'), type: h('Content-Type'),
      name: decodeURIComponent(h('X-Jarvis-Name')), size: (await res.blob()).size });
  }
  return out;
}"""
# A file is sent as a Blob, whose bytes the browser does not show a test from outside: keep a copy
# of each upload's body inside the page.
UPLOAD_SPY = """(() => {
  const real = window.fetch; window.__uploads = [];
  window.fetch = async function (url, opts) {
    try {
      const up = /\\/v1\\/(attachments|vault\\/upload)$/.test(String(url))
        && opts && opts.method === 'POST';
      if (up && opts.body && opts.body.arrayBuffer) {
        const buf = new Uint8Array(await opts.body.arrayBuffer()); let bin = '';
        for (let i = 0; i < buf.length; i += 0x8000) {
          bin += String.fromCharCode.apply(null, buf.subarray(i, i + 0x8000));
        }
        window.__uploads.push({ url: String(url), b64: btoa(bin) });
      }
    } catch (_) {}
    return real.apply(this, arguments);
  };
})();"""


@pytest.fixture(scope="module")
def browser() -> Iterator[Any]:
    with sync_playwright() as p:
        b = p.chromium.launch()
        yield b
        b.close()


class Tray(Console):
    """A console page with every request it (and its workers) made recorded."""

    def __init__(self, browser: Any, url: str, token: str, viewport: dict[str, int]) -> None:
        super().__init__(browser, url, token, viewport)
        self.requests: list[tuple[str, str]] = []
        self.ctx.on("request", lambda r: self.requests.append((r.method, r.url)))
        self.page.add_init_script(UPLOAD_SPY)

    def share(self, spec: dict[str, Any]) -> Any:
        return self.page.evaluate(HARNESS, [SW_SRC, spec])

    def tray(self) -> dict[str, Any]:
        out: dict[str, Any] = self.page.evaluate(TRAY)
        return out

    def sent(self, since: int = 0) -> list[tuple[str, str]]:
        return [(m, u) for m, u in self.requests[since:] if u.split("?")[0].endswith(SENDS)]

    @property
    def uploads(self) -> list[dict[str, Any]]:
        seen = self.page.evaluate("window.__uploads")
        return [{"url": u["url"], "body": base64.b64decode(u["b64"])} for u in seen]

    def pretend_uploads(self) -> None:
        def upload(route: Any) -> None:
            name = route.request.headers.get("x-jarvis-filename", "file")
            ref = {"id": "doc_" + "0" * 20, "name": name, "kind": "jpg", "size": 1000}
            ref |= {"pages": None, "words": 0, "chars": 0, "truncated": False, "pictures": 1}
            route.fulfill(status=201, content_type="application/json", body=json.dumps(ref))

        self.page.route("**/v1/attachments", upload)

    def at_health(self) -> None:
        self.page.goto(self.url + "/health")


def _two_pictures() -> dict[str, Any]:
    return {
        "fields": {"title": "", "text": ""},
        "files": [
            {"name": "garden.jpg", "type": "image/jpeg", "draw": [640, 480]},
            {"name": "receipt.png", "type": "image/png", "draw": [300, 400]},
        ],
    }


# ---- the worker on its own ---------------------------------------------------------------------
def test_two_files_become_two_tray_items_and_a_303(
    browser: Any, server_url: str, token: str
) -> None:
    t = Tray(browser, server_url, token, DESKTOP)
    try:
        t.at_health()
        res = t.share(_two_pictures())
        assert res == {"status": 303, "location": server_url + "/?do=shared"}
        got = t.tray()
        assert [(i["name"], i["kind"], i["type"]) for i in got["items"]] == [
            ("garden.jpg", "file", "image/jpeg"),
            ("receipt.png", "file", "image/png"),
        ]
        assert all(i["size"] > 0 and i["path"].startswith("/app/share/item/") for i in got["items"])
        assert got["notice"]["refused"] == []
        assert t.share({"method": "GET"}) is None  # it takes the one POST and nothing else
        assert t.sent() == [] and not [u for _, u in t.requests if "/app/share/in" in u]
    finally:
        t.close()


def test_a_sixth_item_a_big_file_and_an_exe_are_refused_in_plain_words(
    browser: Any, server_url: str, token: str
) -> None:
    t = Tray(browser, server_url, token, DESKTOP)
    try:
        t.at_health()
        t.share(_two_pictures())
        t.share(
            {
                "files": [
                    {"name": "set-up.exe", "type": "application/x-msdownload", "size": 2048},
                    {"name": "huge.jpg", "type": "image/jpeg", "size": 11 * MB},
                    {"name": "a.jpg", "type": "image/jpeg", "draw": [50, 50]},
                    {"name": "b.webp", "type": "image/webp", "draw": [50, 50]},
                    {"name": "letter.pdf", "type": "application/pdf", "size": 900},
                    {"name": "sixth.png", "type": "image/png", "draw": [50, 50]},
                ]
            }
        )
        got = t.tray()
        assert [i["name"] for i in got["items"]] == [
            "garden.jpg", "receipt.png", "a.jpg", "b.webp", "letter.pdf"
        ]  # fmt: skip
        refused = {r["name"]: r["why"] for r in got["notice"]["refused"]}
        assert refused == {
            "set-up.exe": "JARVIS takes photos (JPEG, PNG or WebP), PDFs and text only.",
            "huge.jpg": "It is over 10 MB, the most JARVIS takes.",
            "sixth.png": (
                "The tray holds 5 items at most. Discard one there, then share this again."
            ),
        }
    finally:
        t.close()


def test_a_line_of_text_is_kept_and_a_title_alone_beside_files_is_not(
    browser: Any, server_url: str, token: str
) -> None:
    t = Tray(browser, server_url, token, DESKTOP)
    try:
        t.at_health()
        t.share(
            {"fields": {"title": "A recipe", "text": "Dal\ntadka", "url": "https://example.com/r"}}
        )
        t.share({"fields": {"title": "Photo caption"}, "files": [_two_pictures()["files"][0]]})
        t.share({"fields": {"text": "x" * 2001}})
        got = t.tray()
        assert [(i["name"], i["kind"]) for i in got["items"]] == [
            ("Shared text", "text"),
            ("garden.jpg", "file"),
        ]
        assert got["notice"]["refused"] == [
            {"name": "Shared text", "why": "The text is longer than 2,000 characters."}
        ]
    finally:
        t.close()


# ---- for real: the registered worker, the tray, the network ------------------------------------
def _registered(t: Tray) -> None:
    for _ in range(150):
        ok = t.page.evaluate(
            "navigator.serviceWorker.getRegistration('/app/share/').then(r => !!(r && r.active))"
        )
        if ok:
            return
        t.page.wait_for_timeout(100)
    raise AssertionError("the share worker was not registered")


SUBMIT = """() => {
  const f = document.createElement('form');
  f.method = 'post'; f.enctype = 'multipart/form-data'; f.action = '/app/share/in';
  f.id = 'r7aShare';
  const files = document.createElement('input');
  files.type = 'file'; files.name = 'files'; files.multiple = true;
  files.id = 'r7aFiles'; files.hidden = true; f.append(files); document.body.append(f);
}"""


def _post_share(t: Tray, files: list[dict[str, Any]]) -> None:
    t.page.evaluate(SUBMIT)
    t.page.set_input_files("#r7aFiles", files=files)
    with t.page.expect_navigation():
        t.page.evaluate("document.getElementById('r7aShare').submit()")


def test_a_share_sheet_post_lands_in_the_tray_and_never_reaches_the_network(
    browser: Any, server_url: str, token: str
) -> None:
    t = Tray(browser, server_url, token, PHONE)
    reached: list[str] = []
    t.ctx.route("**/app/share/in", lambda r: (reached.append(r.request.method), r.continue_()))
    try:
        t.open()
        _registered(t)
        scope = t.page.evaluate(
            "navigator.serviceWorker.getRegistration('/app/share/').then(r => r.scope)"
        )
        assert scope == server_url + "/app/share/"
        assert t.page.evaluate("!navigator.serviceWorker.controller")  # it controls no page
        jpeg = _drawn(t, "image/jpeg", 800, 600)
        png = _drawn(t, "image/png", 120, 90)
        _post_share(
            t,
            [
                {"name": "garden.jpg", "mimeType": "image/jpeg", "buffer": jpeg},
                {"name": "plan.png", "mimeType": "image/png", "buffer": png},
            ],
        )
        t.page.locator("#welcome, #tokIn").first.wait_for()
        gate = t.page.locator("#tokIn")
        if gate.count():  # token mode keeps the token for the tab only: sign in again
            gate.fill(t.token)
            t.page.locator("#tokBtn").click()
        t.page.locator("#shareTray[open]").wait_for(timeout=15_000)
        names = t.page.locator("#shareTrayList .r7s-name").all_text_contents()
        assert names == ["garden.jpg", "plan.png"]
        assert reached == []  # the worker answered in the browser: the POST never left it
        assert "do=" not in t.page.url  # the launch word is gone from the address
        assert t.sent() == []
        assert t.errors == [] and t.csp_violations() == []
    finally:
        t.close()


def _drawn(t: Tray, kind: str, w: int, h: int) -> bytes:
    b64 = t.page.evaluate(
        """async ([kind, w, h]) => {
          const c = new OffscreenCanvas(w, h), g = c.getContext('2d');
          g.fillStyle = '#2b7a78'; g.fillRect(0, 0, w, h);
          g.fillStyle = '#def2f1'; g.fillRect(8, 8, w / 3, h / 3);
          const buf = new Uint8Array(await (await c.convertToBlob({ type: kind })).arrayBuffer());
          let bin = ''; buf.forEach((b) => { bin += String.fromCharCode(b); }); return btoa(bin);
        }""",
        [kind, w, h],
    )
    return base64.b64decode(b64)


def test_with_no_worker_the_server_says_open_jarvis_once(
    browser: Any, server_url: str, token: str
) -> None:
    t = Tray(browser, server_url, token, PHONE)
    try:
        t.at_health()  # never opened the console: no worker
        _post_share(
            t, [{"name": "garden.jpg", "mimeType": "image/jpeg", "buffer": b"\xff\xd8\xff"}]
        )
        assert "Open JARVIS once, then share again." in t.page.locator("main").inner_text()
        assert t.page.locator("a.cta[href='/']").count() == 1
        assert ("POST", server_url + "/app/share/in") in t.requests
    finally:
        t.close()


def _tray_open(t: Tray, spec: dict[str, Any]) -> None:
    """Items put by the worker (stand-in), then the console signed in: the tray opens by itself."""
    t.at_health()
    t.share(spec)
    t.open()
    t.page.locator("#shareTray[open]").wait_for(timeout=15_000)


def test_no_request_leaves_the_browser_until_a_button_is_pressed(
    browser: Any, server_url: str, token: str
) -> None:
    t = Tray(browser, server_url, token, DESKTOP)
    try:
        t.pretend_uploads()
        _tray_open(t, _two_pictures())
        t.page.wait_for_timeout(1500)
        assert t.sent() == []  # two pictures waiting, the tray open, nothing sent
        assert [u for u in t.uploads] == []
        before = len(t.requests)
        t.page.locator(".r7s-item", has_text="garden.jpg").get_by_role(
            "button", name="Attach to my message"
        ).click()
        # the chip shows at once; the upload follows once the picture is redrawn (I1: every picture)
        t.page.locator('#attachChips .achip[data-state="ready"]').first.wait_for()
        assert [m for m, _ in t.sent(before)] == ["POST"]  # exactly the one the button says
        assert len(t.uploads) == 1 and t.uploads[0]["url"].endswith("/v1/attachments")
        assert t.tray()["items"][0]["name"] == "receipt.png"  # the other one still waits
        assert t.errors == [] and t.csp_violations() == []
    finally:
        t.close()


def test_a_webp_is_redrawn_as_a_jpeg_of_at_most_1568_px_before_it_is_sent(
    browser: Any, server_url: str, token: str
) -> None:
    t = Tray(browser, server_url, token, DESKTOP)
    try:
        t.pretend_uploads()
        _tray_open(
            t, {"files": [{"name": "beach.webp", "type": "image/webp", "draw": [3000, 2000]}]}
        )
        t.page.get_by_role("button", name="Attach to my message").click()
        t.page.locator('#attachChips .achip[data-state="ready"]').first.wait_for()
        (up,) = t.uploads
        assert up["body"][:3] == b"\xff\xd8\xff"  # a JPEG, never the WebP as it was
        w, h = _jpeg_size(up["body"])
        assert max(w, h) <= 1568 and (w, h) == (1568, 1045)
        assert t.tray()["items"] == []
    finally:
        t.close()


def test_ask_says_the_brain_cannot_see_and_sends_nothing(
    browser: Any, server_url: str, token: str
) -> None:
    t = Tray(browser, server_url, token, DESKTOP)
    try:
        _tray_open(t, _two_pictures())
        line = "The brain answering now can’t see pictures."
        blocked = t.page.locator("#shareTrayList button", has_text=line)
        assert blocked.count() == 2 and blocked.first.is_disabled()
        assert t.page.get_by_role("button", name="Ask the AI about it (about ₹0.30)").count() == 0
        assert t.sent() == []
        assert (
            "Pictures sent from this device today: 0"
            in t.page.locator("#shareTraySent").inner_text()
        )
    finally:
        t.close()


def test_discard_removes_the_item_and_sends_nothing(
    browser: Any, server_url: str, token: str
) -> None:
    t = Tray(browser, server_url, token, PHONE)
    try:
        _tray_open(t, _two_pictures())
        t.page.locator(".r7s-item", has_text="garden.jpg").get_by_role(
            "button", name="Discard"
        ).click()
        t.page.locator(".r7s-item").filter(has_text="garden.jpg").wait_for(state="detached")
        assert [i["name"] for i in t.tray()["items"]] == ["receipt.png"]
        assert t.sent() == []
    finally:
        t.close()


def test_text_goes_into_the_message_box_and_nothing_is_sent(
    browser: Any, server_url: str, token: str
) -> None:
    t = Tray(browser, server_url, token, PHONE)
    try:
        _tray_open(
            t, {"fields": {"text": "Pick up the made-up parcel", "url": "https://example.com/p"}}
        )
        t.page.get_by_role("button", name="Put it in my message").click()
        t.page.locator("#shareTray[open]").wait_for(state="detached")
        assert t.page.locator("#input").input_value() == (
            "Pick up the made-up parcel https://example.com/p"
        )
        assert not t.page.locator("#send").is_disabled() and t.sent() == []
    finally:
        t.close()


# ---- signed out --------------------------------------------------------------------------------
def test_before_sign_in_the_block_asks_the_server_nothing(
    browser: Any, server_url: str, token: str
) -> None:
    t = Tray(browser, server_url, token, PHONE)
    try:
        t.at_health()
        t.share(_two_pictures())
        before = len(t.requests)
        t.page.goto(server_url + "/?source=app&do=shared")
        t.page.locator("#tokIn").wait_for()
        t.page.wait_for_timeout(2000)
        asked = [u for _, u in t.requests[before:] if "/v1/" in u or "/app/" in u]
        assert asked == []  # no /app/status, no worker, no upload: nothing at all
        assert t.page.locator("#shareTray").count() == 0
        assert len(t.tray()["items"]) == 2  # it keeps its items
        assert t.page.evaluate("location.search") == "?source=app"
        t.page.locator("#tokIn").fill(t.token)
        t.page.locator("#tokBtn").click()
        t.page.locator("#shareTray[open]").wait_for(timeout=15_000)  # after sign-in it opens
        assert t.page.locator("#shareTrayList .r7s-item").count() == 2
        assert t.errors == [] and t.csp_violations() == []
    finally:
        t.close()


# ---- the look ----------------------------------------------------------------------------------
@pytest.mark.parametrize("surface", ["night", "day"])
@pytest.mark.parametrize("vp", ["desktop", "phone"])
def test_the_tray_passes_the_visual_gate(
    browser: Any, server_url: str, token: str, vp: str, surface: str
) -> None:
    t = Tray(browser, server_url, token, DESKTOP if vp == "desktop" else PHONE)
    try:
        t.at_health()
        t.share(_two_pictures())
        t.share(
            {
                "fields": {"text": "A made-up note to remember"},
                "files": [
                    {"name": "set-up.exe", "type": "application/x-msdownload", "size": 10},
                    {"name": "a-very-long-file-name-for-the-made-up-electricity-bill.pdf",
                     "type": "application/pdf", "size": 2048},
                ],
            }
        )  # fmt: skip
        if surface == "day":  # the Appearance menu's choice, as it is kept (console-fx.js)
            t.page.evaluate("localStorage.setItem('jarvis_surface', 'day')")
        t.open()
        t.page.locator("#shareTray[open]").wait_for(timeout=15_000)
        assert t.page.locator("html").get_attribute("data-surface") == surface
        assert "Not kept: set-up.exe." in t.page.locator("#shareTrayNote").inner_text()
        t.page.wait_for_timeout(500)
        t.page.evaluate(FINISH_ANIMATIONS_JS)
        sel = "#shareTray"
        res = t.page.evaluate(DOM_CHECKS_JS, sel)
        assert not res.get("missing")
        _assert_clean(
            res,
            t.page.evaluate(NAMELESS_JS, sel),
            t.page.evaluate(WRAP_JS, sel),
            vp,
            f"share tray {vp} {surface}",
        )
        widths = t.page.evaluate("[document.documentElement.scrollWidth, window.innerWidth]")
        assert widths[0] <= widths[1], widths
        assert t.errors == [] and t.csp_violations() == []
    finally:
        t.close()


def test_ask_sends_through_the_one_door_when_the_brain_sees_pictures(
    browser: Any, server_url: str, token: str
) -> None:
    t = Tray(browser, server_url, token, DESKTOP)
    chats: list[dict[str, Any]] = []

    def brains(route: Any) -> None:
        got = route.fetch().json()
        body = [{**b, "sees_pictures": True} for b in got]
        route.fulfill(status=200, content_type="application/json", body=json.dumps(body))

    def chat(route: Any) -> None:  # the picture is a stand-in upload: send the words on alone
        body = json.loads(route.request.post_data)
        chats.append(dict(body))
        body.pop("attachments", None)
        route.continue_(post_data=json.dumps(body))

    try:
        t.pretend_uploads()
        t.page.route("**/v1/brains", brains)
        t.page.route("**/v1/chat", chat)
        _tray_open(t, {"files": [_two_pictures()["files"][0]]})
        assert t.sent() == []
        t.page.get_by_role("button", name="Ask the AI about it (about ₹0.30)").click()
        t.page.locator(".row.jarvis .bubble:not(.typing)").first.wait_for(timeout=20_000)
        assert [u.rsplit("/", 1)[1] for _, u in t.sent()] == ["attachments", "chat"]
        assert chats[0]["message"] == "What can you tell me about this picture?"
        assert chats[0]["attachments"] == ["doc_" + "0" * 20]
        assert t.tray()["items"] == []
        sent = t.page.evaluate("JSON.parse(localStorage.getItem('jarvis_r7_sent_v1')).n")
        assert sent == 1  # the one "Pictures sent from this device today" count
        assert t.errors == [] and t.csp_violations() == []
    finally:
        t.close()
