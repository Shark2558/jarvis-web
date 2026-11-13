# tests/browser/test_r7_a_share_review.py -- R7 Part A, the review follow-ups (security, code and
# python reviews of r7-a @ ec370a2), in a real browser against the real backend:
#   - a post that did not come from the phone's own share sheet (another site, another origin)
#     stores nothing, says so in plain words and goes to the console (not the tray);
#   - a real Android share-sheet launch ('none' or no header) and the console's own page still land;
#   - the whole body is capped (by its length, or by counting when there is none), the file count
#     is bounded, and a file whose first bytes are not its kind is refused;
#   - Cache Storage that is full or broken never turns the answer into an error page;
#   - the tray never opens over a launch (do=talk keeps the mic button focused), only for
#     something new; the 24 hours are enforced on every read and sign-out clears the tray;
#   - the tray's messages are ours or the picture door's own, never a raw browser error.
from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest
from test_console import DESKTOP, PHONE
from test_r7_a_share import MB, Tray, _registered, _two_pictures

_pw = pytest.importorskip("playwright.sync_api")
sync_playwright = _pw.sync_playwright
pytestmark = pytest.mark.browser

FOREIGN = "That did not come from your phone’s share sheet, so JARVIS kept nothing."
ONE_TEXT: dict[str, Any] = {"fields": {"text": "planted by a stranger"}}
ROOM = "No room left on this phone for that item, Sir."


@pytest.fixture(scope="module")
def browser() -> Iterator[Any]:
    with sync_playwright() as p:
        b = p.chromium.launch()
        yield b
        b.close()


def _refused(t: Tray) -> list[dict[str, str]]:
    notice = t.tray()["notice"]
    assert notice is not None
    out: list[dict[str, str]] = notice["refused"]
    return out


def _foreign_said(t: Tray) -> bool:
    """The refusal is on the phone: still in the worker's notice (signed out), or already shown by
    the tray (signed in, which opens for a new notice and takes it)."""
    for _ in range(150):
        notice = t.tray()["notice"]
        if notice and any(r["why"] == FOREIGN for r in notice["refused"]):
            return True
        if FOREIGN in t.page.locator("#shareTrayNote").all_inner_texts():
            return True
        t.page.wait_for_timeout(100)
    return False


# ---- security MEDIUM-1: who may post -----------------------------------------------------------
@pytest.mark.parametrize(
    "headers",
    [
        {"Sec-Fetch-Site": "cross-site"},
        {"Sec-Fetch-Site": "same-site"},
        {"Origin": "http://evil.example"},
        {"Sec-Fetch-Site": "cross-site", "Origin": "null"},
    ],
)
def test_a_post_from_another_site_or_origin_stores_nothing(
    browser: Any, server_url: str, token: str, headers: dict[str, str]
) -> None:
    t = Tray(browser, server_url, token, DESKTOP)
    try:
        t.at_health()
        res = t.share(ONE_TEXT | {"headers": headers})
        assert res == {"status": 303, "location": server_url + "/"}  # the console, not the tray
        got = t.tray()
        assert got["items"] == []
        assert _refused(t) == [{"name": "", "why": FOREIGN}]
        assert t.page.evaluate("window.__formRead") is False  # its body was never even read
    finally:
        t.close()


@pytest.mark.parametrize(
    "headers",
    [
        {"Sec-Fetch-Site": "none"},  # an app's share-sheet launch is a browser-initiated navigation
        {"Sec-Fetch-Site": "same-origin", "Origin": "SELF"},
        {"Origin": "null"},
        {},
    ],
)
def test_a_post_from_the_share_sheet_or_our_own_page_still_lands(
    browser: Any, server_url: str, token: str, headers: dict[str, str]
) -> None:
    t = Tray(browser, server_url, token, DESKTOP)
    try:
        t.at_health()
        sent = {k: (server_url if v == "SELF" else v) for k, v in headers.items()}
        res = t.share(ONE_TEXT | {"headers": sent})
        assert res == {"status": 303, "location": server_url + "/?do=shared"}
        assert [i["name"] for i in t.tray()["items"]] == ["Shared text"]
    finally:
        t.close()


def test_a_form_on_another_site_plants_nothing_in_the_tray_for_real(
    browser: Any, server_url: str, token: str
) -> None:
    page = (
        "<!doctype html><form id=f method=post enctype=multipart/form-data "
        f"action='{server_url}/app/share/in'><input name=text value='planted'>"
        "<input name=url value='https://example.com/x'></form>"
    )
    t = Tray(browser, server_url, token, PHONE)
    t.ctx.route(
        "http://evil.example/**",
        lambda r: r.fulfill(status=200, content_type="text/html", body=page),
    )
    try:
        t.open()  # sign in once: the share worker is registered
        _registered(t)
        t.page.goto("http://evil.example/")
        with t.page.expect_navigation(url=server_url + "/**"):
            t.page.evaluate("document.getElementById('f').submit()")
        posts = [u for m, u in t.requests if m == "POST" and "/app/share/in" in u]
        assert t.tray()["items"] == [], (posts, t.page.url)  # nothing landed
        assert _foreign_said(t)
        assert "do=shared" not in t.page.url
    finally:
        t.close()


# ---- security LOW-2 and LOW-3, code M1 ---------------------------------------------------------
def test_a_body_over_the_cap_by_its_length_is_refused_unread(
    browser: Any, server_url: str, token: str
) -> None:
    t = Tray(browser, server_url, token, DESKTOP)
    try:
        t.at_health()
        res = t.share(_two_pictures() | {"headers": {"Content-Length": str(80 * MB)}})
        assert res == {"status": 303, "location": server_url + "/?do=shared"}
        assert t.page.evaluate("window.__formRead") is False
        assert t.tray()["items"] == []
        assert _refused(t) == [{"name": "", "why": "That share is too big for JARVIS to take."}]
    finally:
        t.close()


def test_a_body_with_no_length_is_counted_and_refused_past_the_cap(
    browser: Any, server_url: str, token: str
) -> None:
    t = Tray(browser, server_url, token, DESKTOP)
    try:
        t.at_health()
        files = [{"name": f"p{i}.jpg", "type": "image/jpeg", "size": 9 * MB} for i in range(7)]
        t.share({"files": files})
        assert t.tray()["items"] == []
        assert _refused(t)[0]["why"] == "That share is too big for JARVIS to take."
    finally:
        t.close()


def test_more_than_ten_files_are_one_refusal_and_five_are_kept(
    browser: Any, server_url: str, token: str
) -> None:
    t = Tray(browser, server_url, token, DESKTOP)
    try:
        t.at_health()
        t.share(
            {"files": [{"name": f"p{i}.png", "type": "image/png", "size": 64} for i in range(12)]}
        )
        assert len(t.tray()["items"]) == 5
        why = [r["why"] for r in _refused(t)]
        assert "Too many files at once. JARVIS takes 5 at most." in why
    finally:
        t.close()


def test_a_file_whose_first_bytes_are_not_its_kind_is_refused(
    browser: Any, server_url: str, token: str
) -> None:
    t = Tray(browser, server_url, token, DESKTOP)
    try:
        t.at_health()
        html = list(b"<html><script>")
        t.share(
            {
                "files": [
                    {"name": "x.png", "type": "image/png", "bytes": html},
                    {"name": "y.pdf", "type": "application/pdf", "bytes": [0xFF, 0xD8, 0xFF, 0xE0]},
                    {"name": "z.jpg", "type": "image/jpeg", "bytes": [0x89, 0x50, 0x4E, 0x47]},
                    {"name": "ok.pdf", "type": "application/pdf", "size": 100},
                    {"name": "ok.webp", "type": "image/webp", "size": 100},
                ]
            }
        )
        assert [i["name"] for i in t.tray()["items"]] == ["ok.pdf", "ok.webp"]
        mismatch = "The file is not what its name says it is."
        assert {r["name"]: r["why"] for r in _refused(t)} == dict.fromkeys(
            ["x.png", "y.pdf", "z.jpg"], mismatch
        )
    finally:
        t.close()


FULL_PUT = """() => {
  const open = caches.open.bind(caches);
  caches.open = async (name) => {
    const c = await open(name), put = c.put.bind(c);
    c.put = async (req, res) => {
      if (new URL(req.url).pathname.startsWith('/app/share/item/')) {
        throw new DOMException('full', 'QuotaExceededError');
      }
      return put(req, res);
    };
    return c;
  };
}"""


def test_a_full_phone_refuses_the_item_in_plain_words_and_still_redirects(
    browser: Any, server_url: str, token: str
) -> None:
    t = Tray(browser, server_url, token, DESKTOP)
    try:
        t.at_health()
        t.page.evaluate(FULL_PUT)
        res = t.share(_two_pictures())
        assert res == {"status": 303, "location": server_url + "/?do=shared"}
        assert t.tray()["items"] == []
        assert {r["name"]: r["why"] for r in _refused(t)} == {
            "garden.jpg": ROOM,
            "receipt.png": ROOM,
        }
    finally:
        t.close()


def test_a_broken_cache_never_turns_the_answer_into_an_error(
    browser: Any, server_url: str, token: str
) -> None:
    t = Tray(browser, server_url, token, DESKTOP)
    try:
        t.at_health()
        t.page.evaluate(
            "() => { caches.open = async () => {"
            " throw new DOMException('no', 'QuotaExceededError'); }; }"
        )
        res = t.share(_two_pictures())
        assert res == {"status": 303, "location": server_url + "/?do=shared"}
    finally:
        t.close()


# ---- code M2: the tray opens by itself only for something new ----------------------------------
def _old_item(t: Tray) -> None:
    """An item the tray has already shown once: it is older than the 'last shown' mark."""
    t.at_health()
    t.share(ONE_TEXT)
    t.page.evaluate(
        "caches.open('jarvis-share-v1').then(c => c.delete('/app/share/notice'))"
        ".then(() => localStorage.setItem('jarvis_share_seen_v1', String(Date.now() + 5000)))"
    )


def test_an_old_item_does_not_cover_a_talk_launch(
    browser: Any, server_url: str, token: str
) -> None:
    t = Tray(browser, server_url, token, PHONE)
    try:
        _old_item(t)
        t.open("/?source=app&do=talk")
        t.page.wait_for_timeout(1500)
        assert t.page.locator("#shareTray[open]").count() == 0
        assert t.page.evaluate("document.activeElement && document.activeElement.id") == "micBtn"
        assert len(t.tray()["items"]) == 1  # still waiting, quietly
        assert t.errors == [] and t.csp_violations() == []
    finally:
        t.close()


def test_an_old_item_does_not_open_the_tray_on_an_ordinary_load(
    browser: Any, server_url: str, token: str
) -> None:
    t = Tray(browser, server_url, token, PHONE)
    try:
        _old_item(t)
        t.open()
        t.page.wait_for_timeout(1500)
        assert t.page.locator("#shareTray[open]").count() == 0
    finally:
        t.close()


def test_a_new_item_opens_the_tray_once_and_not_again_after_it_was_shown(
    browser: Any, server_url: str, token: str
) -> None:
    t = Tray(browser, server_url, token, PHONE)
    try:
        t.at_health()
        t.share(ONE_TEXT)
        t.open()
        t.page.locator("#shareTray[open]").wait_for(timeout=15_000)
        t.page.locator("#shareTrayClose").click()
        t.page.reload()
        t.page.locator("#welcome, #tokIn").first.wait_for()
        gate = t.page.locator("#tokIn")
        if gate.count():
            gate.fill(t.token)
            t.page.locator("#tokBtn").click()
        t.page.locator("#welcome").wait_for()
        t.page.wait_for_timeout(1500)
        assert t.page.locator("#shareTray[open]").count() == 0
        assert len(t.tray()["items"]) == 1
    finally:
        t.close()


def test_do_shared_still_opens_the_tray_with_an_old_item(
    browser: Any, server_url: str, token: str
) -> None:
    t = Tray(browser, server_url, token, PHONE)
    try:
        _old_item(t)
        t.open("/?do=shared")
        t.page.locator("#shareTray[open]").wait_for(timeout=15_000)
    finally:
        t.close()


# ---- security LOW-1: the 24 hours and sign-out -------------------------------------------------
STALE = """async () => {
  const c = await caches.open('jarvis-share-v1');
  await c.put(new Request('/app/share/item/old'), new Response('x', { headers: {
    'Content-Type': 'image/png', 'X-Jarvis-Kind': 'file', 'X-Jarvis-Name': 'old.png',
    'X-Jarvis-Size': '1', 'X-Jarvis-At': String(Date.now() - 25 * 3600 * 1000) } }));
}"""


def test_an_item_older_than_24_hours_is_swept_even_signed_out_and_asks_no_server(
    browser: Any, server_url: str, token: str
) -> None:
    t = Tray(browser, server_url, token, PHONE)
    try:
        t.at_health()
        t.page.evaluate(STALE)
        assert len(t.tray()["items"]) == 1
        before = len(t.requests)
        t.page.goto(server_url + "/")
        t.page.locator("#tokIn").wait_for()
        t.page.wait_for_timeout(800)
        assert t.tray()["items"] == []
        asked = [u for _, u in t.requests[before:] if "/v1/" in u or "/app/" in u]
        assert asked == []
    finally:
        t.close()


def test_signing_out_clears_the_tray(browser: Any, server_url: str, token: str) -> None:
    t = Tray(browser, server_url, token, DESKTOP)
    try:
        t.at_health()
        t.share(_two_pictures())
        t.open()
        t.page.locator("#shareTray[open]").wait_for(timeout=15_000)
        t.page.locator("#shareTrayClose").click()
        with t.page.expect_navigation():
            t.page.evaluate("document.getElementById('logoutBtn').click()")
        t.page.locator("#tokIn, #welcome").first.wait_for()
        assert t.tray()["items"] == []
        assert t.page.evaluate("localStorage.getItem('jarvis_share_seen_v1')") is None
    finally:
        t.close()


# ---- code L1, L3, L6, L2 -----------------------------------------------------------------------
def test_a_second_opening_does_not_wipe_the_refusal_note(
    browser: Any, server_url: str, token: str
) -> None:
    t = Tray(browser, server_url, token, DESKTOP)
    try:
        t.at_health()
        t.share({"files": [{"name": "set-up.exe", "type": "application/x-msdownload", "size": 9}]})
        t.open()
        t.page.locator("#shareTray[open]").wait_for(timeout=15_000)
        assert "set-up.exe" in t.page.locator("#shareTrayNote").inner_text()
        t.page.evaluate("JarvisMobile.parts.share.open()")
        t.page.wait_for_timeout(500)
        assert "set-up.exe" in t.page.locator("#shareTrayNote").inner_text()
    finally:
        t.close()


def test_a_failed_look_brings_the_sheet_back_with_the_reason(
    browser: Any, server_url: str, token: str
) -> None:
    t = Tray(browser, server_url, token, DESKTOP)
    try:
        t.at_health()
        t.share({"files": [_two_pictures()["files"][0]]})
        t.open()
        t.page.locator("#shareTray[open]").wait_for(timeout=15_000)
        t.page.evaluate(
            "() => { JarvisMobile.parts.panel.look = async () => {"
            " throw new Error('The camera is busy.'); }; }"
        )
        t.page.get_by_role("button", name="Look at it here").click()
        t.page.locator("#shareTrayNote").filter(has_text="The camera is busy.").wait_for()
        assert t.page.locator("#shareTray[open]").count() == 1
    finally:
        t.close()


def test_a_raw_browser_error_never_reaches_the_owner(
    browser: Any, server_url: str, token: str
) -> None:
    t = Tray(browser, server_url, token, DESKTOP)
    try:
        t.at_health()
        t.share({"files": [_two_pictures()["files"][0]]})
        t.open()
        t.page.locator("#shareTray[open]").wait_for(timeout=15_000)
        t.page.route("**/v1/vault/upload", lambda r: r.abort("failed"))
        t.page.get_by_role("button", name="Add to my vault").click()
        note = t.page.locator("#shareTrayNote")
        note.filter(has_text="sent").wait_for()
        assert note.inner_text() == "It wasn’t sent. Try again in a moment."
    finally:
        t.close()


def test_two_windows_cannot_press_the_same_item_at_once(
    browser: Any, server_url: str, token: str
) -> None:
    t = Tray(browser, server_url, token, DESKTOP)
    try:
        t.pretend_uploads()
        t.at_health()
        t.share({"files": [_two_pictures()["files"][0]]})
        t.open()
        t.page.locator("#shareTray[open]").wait_for(timeout=15_000)
        lock = t.page.locator(".r7s-item").first.get_attribute("data-lock")
        other = t.ctx.new_page()
        other.goto(server_url + "/health")
        other.evaluate(
            "(id) => { window.__held = new Promise((done) => { window.__free = done; });"
            " return new Promise((ok) => navigator.locks.request('jarvis-share-' + id,"
            " () => { ok(true); return window.__held; })); }",
            lock,
        )
        before = len(t.requests)
        t.page.get_by_role("button", name="Attach to my message").click()
        t.page.locator("#shareTrayNote").filter(has_text="Another window").wait_for()
        assert t.sent(before) == [] and len(t.tray()["items"]) == 1
        other.evaluate("window.__free()")
    finally:
        t.close()
