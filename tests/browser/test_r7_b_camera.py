# tests/browser/test_r7_b_camera.py -- R7 Part B in a real Chromium (docs/plans/r7-mobile.md D0,
# D11-D14), with Chromium's fake camera (--use-fake-device-for-media-stream):
#   - `text` reads the numbers on a label drawn in the test, and `code` reads a QR drawn in the test
#     (segno's matrix), with JARVIS's own vendored tesseract.js and zxing-wasm, under the console's
#     CSP (no violation, no error)
#   - a live run and a photo look send no picture: no request carries image bytes or goes to an
#     upload route; Keep posts the result alone; the chip shows while live and Stop ends it
#   - locked: no live track, unlock() and start() from script are refused, a reload stays locked;
#     only a tap allows; a hidden page stops the camera; "cameras off" by voice locks it
#   - "Ask the AI about this photo" only while the brain answering sees pictures; Attach goes
#     through the one door and counts in "Pictures sent from this device today"
#   - before sign-in the panel asks the server nothing
#   - the visual gate (ui_checks.DOM_CHECKS_JS) at 1440x900 and 390x844, Night and Day, on the
#     Look, a photo's result, Results and Cameras
# ruff: noqa: E501 -- JavaScript strings
from __future__ import annotations

import json
import time
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import pytest
import segno
from test_console import DESKTOP, PHONE, Console
from test_ui_audit import NAMELESS_JS, WRAP_JS, _assert_clean
from ui_checks import DOM_CHECKS_JS, FINISH_ANIMATIONS_JS, install_mocks

sync_playwright = pytest.importorskip("playwright.sync_api").sync_playwright
pytestmark = pytest.mark.browser
FAKE_CAMERA = ["--use-fake-device-for-media-stream", "--use-fake-ui-for-media-stream"]
QR_TEXT = "https://example.com/r7-label-0042"
IMAGE_MARKS = (
    b"\x89PNG",
    b"\xff\xd8\xff",
    b"data:image",
    b"iVBORw0KGgo",
    b"/9j/",
    b"RIFF",
    b"GIF8",
)
UPLOADS = ("/v1/attachments", "/v1/vault", "/v1/files", "/app/share", "/phone/")
ASK = "Ask the AI about this photo (about ₹0.30)"
RESTORE_CAMERA = (
    "try { localStorage.setItem('jarvis_deck_v1', JSON.stringify("
    + json.dumps({"v": 1, "p": {"camera": {"open": True}}})
    + ")); } catch (e) {}"
)
LABEL_JS = """async () => {
  const c = document.createElement('canvas'); c.width = 900; c.height = 280;
  const x = c.getContext('2d'); x.fillStyle = '#fff'; x.fillRect(0, 0, c.width, c.height); x.fillStyle = '#000';
  x.font = 'bold 64px "DejaVu Sans", sans-serif';
  x.fillText('MRP Rs 125.00', 40, 110); x.fillText('NET WT 500 g', 40, 220);
  return JSON.parse(JSON.stringify(await window.JarvisVision.run('text', c)));
}"""
QR_JS = """async (rows) => {
  const k = 8, q = 4, n = rows.length, c = document.createElement('canvas');
  c.width = c.height = (n + 2 * q) * k;
  const x = c.getContext('2d'); x.fillStyle = '#fff'; x.fillRect(0, 0, c.width, c.height); x.fillStyle = '#000';
  rows.forEach((row, y) => row.forEach((on, i) => { if (on) x.fillRect((i + q) * k, (y + q) * k, k, k); }));
  return JSON.parse(JSON.stringify(await window.JarvisVision.run('code', c)));
}"""
SCRIPT_UNLOCK_JS = """() => { setTimeout(async () => {
  const active = navigator.userActivation.isActive, unlocked = window.JarvisCamera.unlock('panel');
  let code = 'started';
  try { await window.JarvisCamera.start({}); } catch (e) { code = e.code; }
  window.__r7b = { active, unlocked, code };
}, 6500); }"""
HIDE_JS = """() => { Object.defineProperty(document, 'hidden', { value: true, configurable: true });
  document.dispatchEvent(new Event('visibilitychange'));
  delete document.hidden; return window.JarvisCamera.live(); }"""


@pytest.fixture(scope="module")
def browser() -> Iterator[Any]:
    with sync_playwright() as p:
        b = p.chromium.launch(args=FAKE_CAMERA)
        yield b
        b.close()


class Spy:
    """Every request the page makes, with its body."""

    def __init__(self, page: Any) -> None:
        self.reqs: list[tuple[str, str, bytes]] = []
        page.on("request", self._on)

    def _on(self, req: Any) -> None:
        try:
            body = req.post_data_buffer or b""
        except Exception:  # noqa: BLE001 - a body the browser can't hand over counts as binary
            body = b"\x89PNG?"
        self.reqs.append((req.method, req.url, body))

    def mark(self) -> int:
        return len(self.reqs)

    def pictures(self, since: int = 0, extra: tuple[bytes, ...] = ()) -> list[str]:
        bad = []
        for method, url, body in self.reqs[since:]:
            path = "/" + url.split("/", 3)[-1]
            if (
                any(m in body for m in (*IMAGE_MARKS, *extra))
                or len(body) > 64 * 1024
                or path.startswith(UPLOADS)
            ):
                bad.append(f"{method} {path} ({len(body)} bytes)")
        return bad

    def paths(self, since: int = 0) -> list[str]:
        return ["/" + u.split("/", 3)[-1] for _, u, _ in self.reqs[since:]]


def until(page: Any, check: Callable[[], bool], what: str, timeout_s: float = 60.0) -> None:
    end = time.monotonic() + timeout_s
    while time.monotonic() < end:
        if check():
            return
        page.wait_for_timeout(100)
    raise AssertionError(f"timed out waiting for {what}")


def camera(
    browser: Any, url: str, token: str, viewport: dict[str, int] = DESKTOP, *, sees: bool = False
) -> tuple[Console, Spy]:
    c = Console(browser, url, token, viewport)
    install_mocks(c.page)
    if sees:

        def brains(route: Any) -> None:
            r = route.fetch()
            data = r.json()
            for b in data if isinstance(data, list) else data.get("brains", []):
                b["sees_pictures"] = True
            route.fulfill(response=r, json=data)

        c.page.route("**/v1/brains", brains)
    spy = Spy(c.page)
    c.open()
    c.open_panel("camera")
    c.page.locator("#camTask").wait_for()
    until(
        c.page,
        lambda: "not installed" in c.page.locator("#camTask").inner_text(),
        "the server's task list",
    )
    return c, spy


def button(c: Console, name: str) -> Any:
    return c.page.locator("#p-camera").get_by_role("button", name=name, exact=True)


def out_text(c: Console) -> str:
    return str(c.page.locator("#p-camera .cam-out").text_content() or "")


def test_text_reads_the_numbers_on_a_label_drawn_in_the_test(
    browser: Any, server_url: str, token: str
) -> None:
    c, spy = camera(browser, server_url, token)
    try:
        before = spy.mark()
        r = c.page.evaluate(LABEL_JS)
        assert r["ok"] is True and r["task"] == "text", r
        assert "125" in r["data"]["text"] and "500" in r["data"]["text"], r["data"]
        assert spy.pictures(before) == []
        got = spy.paths(before)
        assert got and all(p.startswith("/static/vendor/vision/r7-1/") for p in got), got
        assert c.errors == [] and c.csp_violations() == []
    finally:
        c.close()


def test_code_reads_a_qr_drawn_in_the_test(browser: Any, server_url: str, token: str) -> None:
    rows = [[bool(v) for v in row] for row in segno.make(QR_TEXT, error="m", micro=False).matrix]
    c, spy = camera(browser, server_url, token)
    try:
        before = spy.mark()
        r = c.page.evaluate(QR_JS, rows)
        assert r["ok"] is True and r["data"]["codes"] == [
            {"format": "qr_code", "value": QR_TEXT}
        ], r
        assert spy.pictures(before) == []
        assert c.errors == [] and c.csp_violations() == []
    finally:
        c.close()


def test_a_live_run_sends_no_picture_and_the_chip_shows_while_live(
    browser: Any, server_url: str, token: str
) -> None:
    c, spy = camera(browser, server_url, token)
    try:
        kept = {"kept": {"id": "vr_000000000001"}}  # this server has no token key: Keep is mocked
        c.page.route("**/v1/vision/results", lambda r: r.fulfill(status=201, json=kept))
        c.page.select_option("#camTask", "quality")
        before = spy.mark()
        button(c, "Start the camera").click()
        until(c.page, lambda: out_text(c).startswith("Light "), "a live result")
        chip = c.page.locator(".cam-chip")
        assert chip.is_visible() and c.page.evaluate("window.JarvisCamera.live()") is True
        box = chip.bounding_box()
        assert box and box["height"] >= 44
        assert c.page.locator("#cameraMeta").text_content() == "On"
        c.page.wait_for_timeout(1500)  # a few more looks at the capped rate
        keep_at = spy.mark()
        button(c, "Keep").click()
        until(c.page, lambda: "/v1/vision/results" in spy.paths(keep_at), "Keep's request")
        posts = [(m, "/" + u.split("/", 3)[-1], b) for m, u, b in spy.reqs[keep_at:] if m == "POST"]
        assert [(m, p) for m, p, _ in posts] == [("POST", "/v1/vision/results")]
        assert json.loads(posts[0][2])["task"] == "quality" and len(posts[0][2]) < 2000
        assert spy.pictures(before) == []
        button(c, "Stop").click()
        until(c.page, lambda: not chip.is_visible(), "the chip to go")
        assert c.page.evaluate("window.JarvisCamera.live()") is False
        assert c.errors == [] and c.csp_violations() == []
    finally:
        c.close()


def _photo(c: Console, path: Path) -> None:
    with c.page.expect_file_chooser() as fc:
        button(c, "Choose a photo").click()
    fc.value.set_files(str(path))
    until(c.page, lambda: out_text(c).startswith("Light "), "the photo's result")


def _png(tmp_path: Path) -> tuple[Path, bytes]:
    from PIL import Image, ImageDraw

    img = Image.new("RGB", (480, 320), "white")
    ImageDraw.Draw(img).rectangle((40, 40, 440, 280), outline="black", width=6)
    for x in range(0, 480, 2):  # a planted pixel pattern along the top row
        img.putpixel((x, 0), (0x52, 0x37, 0x50))
    path = tmp_path / "label.png"
    img.save(path)
    return path, path.read_bytes()


def test_a_photo_look_sends_nothing_and_ask_waits_for_a_seeing_brain(
    browser: Any, server_url: str, token: str, tmp_path: Path
) -> None:
    path, raw = _png(tmp_path)
    c, spy = camera(browser, server_url, token)
    try:
        c.page.select_option("#camTask", "quality")
        before = spy.mark()
        _photo(c, path)
        assert spy.pictures(before, extra=(raw[-64:],)) == []
        assert button(c, ASK).count() == 0
        assert "can’t see pictures" in c.page.locator("#p-camera").inner_text()
        assert "Pictures sent from this device today: 0" in c.page.locator("#p-camera").inner_text()
        button(c, "Attach to my message").click()
        until(
            c.page,
            lambda: c.page.locator("#attachChips").is_visible(),
            "the picture in the paperclip's tray",
        )
        assert "Pictures sent from this device today: 1" in c.page.locator("#p-camera").inner_text()
        assert c.errors == [] and c.csp_violations() == []
    finally:
        c.close()


def test_ask_is_offered_while_the_brain_answering_sees_pictures(
    browser: Any, server_url: str, token: str, tmp_path: Path
) -> None:
    path, _ = _png(tmp_path)
    c, _ = camera(browser, server_url, token, sees=True)
    try:
        c.page.select_option("#camTask", "quality")
        _photo(c, path)
        until(c.page, lambda: button(c, ASK).count() == 1, "the Ask button")
        assert c.errors == []
    finally:
        c.close()


def test_locked_there_is_no_track_and_script_cannot_unlock(
    browser: Any, server_url: str, token: str
) -> None:
    c, _ = camera(browser, server_url, token)
    try:
        c.page.locator("#camt-cameras").click()
        button(c, "Switch off").click()
        assert c.page.locator("#cameraMeta").text_content() == "Switched off"
        # Playwright's own evaluate counts as a gesture, so "from script" is a timer that fires after
        # the last gesture's activation (a few seconds, as for R5's microphone) has ended
        c.page.evaluate(SCRIPT_UNLOCK_JS)
        c.page.wait_for_timeout(7500)  # nothing may touch the page meanwhile
        assert c.page.evaluate("window.__r7b") == {
            "active": False,
            "unlocked": False,
            "code": "camera_off",
        }
        code = c.page.evaluate("window.JarvisCamera.start({}).then(() => 'started', (e) => e.code)")
        assert code == "camera_off" and c.page.evaluate("window.JarvisCamera.live()") is False
        c.page.reload()
        c.page.locator("#welcome, #tokIn").first.wait_for()
        c.open_panel("camera")
        assert c.page.evaluate("window.JarvisCamera.locked()") is True
        c.page.locator("#camt-look").click()
        assert (
            button(c, "Allow the camera").is_visible()
            and button(c, "Start the camera").count() == 0
        )
        button(c, "Allow the camera").click()  # a real tap
        assert c.page.evaluate("window.JarvisCamera.locked()") is False
    finally:
        c.close()


def test_a_hidden_page_and_cameras_off_by_voice_stop_it(
    browser: Any, server_url: str, token: str
) -> None:
    c, _ = camera(browser, server_url, token)
    try:
        c.page.select_option("#camTask", "quality")
        button(c, "Start the camera").click()
        until(c.page, lambda: c.page.evaluate("window.JarvisCamera.live()"), "the camera")
        assert c.page.evaluate(HIDE_JS) is False and not c.page.locator(".cam-chip").is_visible()
        button(c, "Start the camera").click()
        until(c.page, lambda: c.page.evaluate("window.JarvisCamera.live()"), "the camera again")
        said = c.page.evaluate(
            "window.JarvisVoiceCommands.handle('Jarvis, cameras off', {source: 'voice', state: 'listening'})"
        )
        assert (
            said["handled"] is True
            and said["result"]["say"] == "The camera on this device is off, Sir."
        )
        assert c.page.evaluate("[window.JarvisCamera.live(), window.JarvisCamera.locked()]") == [
            False,
            True,
        ]
        on = c.page.evaluate(
            "window.JarvisVoiceCommands.handle('turn the camera on', {source: 'voice', state: 'listening'})"
        )
        assert on["handled"] is False and c.page.evaluate("window.JarvisCamera.locked()") is True
    finally:
        c.close()


def test_before_sign_in_the_block_asks_the_server_nothing(
    browser: Any, server_url: str, token: str
) -> None:
    c = Console(browser, server_url, token, DESKTOP)
    try:
        c.page.add_init_script(RESTORE_CAMERA)  # last visit left the Camera panel open
        install_mocks(c.page)
        spy = Spy(c.page)
        c.page.goto(server_url + "/")
        c.page.locator("#tokIn").wait_for()
        c.page.wait_for_timeout(1500)
        assert not [p for p in spy.paths() if p.startswith("/v1/vision")]
        c.page.locator("#tokIn").fill(token)
        c.page.locator("#tokBtn").click()
        c.page.locator("#welcome").wait_for()
        until(c.page, lambda: "/v1/vision" in spy.paths(), "the status once signed in")
        assert c.errors == [] and c.csp_violations() == []
    finally:
        c.close()


def _audit(c: Console, vp: str, what: str) -> None:
    c.page.wait_for_timeout(400)
    c.page.evaluate(FINISH_ANIMATIONS_JS)
    sel = "#p-camera"
    res = c.page.evaluate(DOM_CHECKS_JS, sel)
    assert not res.get("missing"), what
    _assert_clean(res, c.page.evaluate(NAMELESS_JS, sel), c.page.evaluate(WRAP_JS, sel), vp, what)


@pytest.mark.parametrize("surface", ["night", "day"])
@pytest.mark.parametrize("vp", ["desktop", "phone"])
def test_the_camera_panel_passes_the_visual_gate(
    browser: Any, server_url: str, token: str, tmp_path: Path, vp: str, surface: str
) -> None:
    path, _ = _png(tmp_path)
    c, _ = camera(browser, server_url, token, DESKTOP if vp == "desktop" else PHONE)
    try:
        if surface == "day":
            c.choose_day()
            c.open_panel("camera")
        _audit(c, vp, f"camera look {vp} {surface}")
        c.page.select_option("#camTask", "quality")
        _photo(c, path)
        _audit(c, vp, f"camera photo result {vp} {surface}")
        c.page.locator("#camt-results").click()
        c.page.locator("#camp-results .snote").first.wait_for()
        _audit(c, vp, f"camera results {vp} {surface}")
        c.page.locator("#camt-cameras").click()
        _audit(c, vp, f"camera cameras {vp} {surface}")
        assert c.errors == [] and c.csp_violations() == []
    finally:
        c.close()
