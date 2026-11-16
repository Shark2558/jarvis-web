# tests/browser/test_r13_d_camera.py -- R13 Part D in a real Chromium (docs/plans/r13-wardrobe.md D7-D9,
# OPS-01, LND-01, INV-05, "Browser"), against D's fake server (tests/r13_fakes_d.py over I0's
# tests/r13_fake_server.py) with Chromium's fake camera playing a clip drawn here (a QR label of his
# on a plain surface). Generated test patterns only: never a photo, never a real face.
#   - the four wardrobe tasks load the VENDORED models under the console's CSP and pass their
#     self-checks; a drawn face and a drawn silhouette are found, a laid shirt is neither
#   - the wake word and a wardrobe task share one runtime: one ORT module and one .wasm fetched
#   - Add pieces: a new piece (a chip, the suggested colour), its photo saved through the one door
#     (a JPEG of at most 512 px, counted in "Pictures sent from this device today"), its look
#     remembered; the same photo again offers that piece first and his tap keeps its id
#   - a photo with a face or a person keeps and sends nothing
#   - To laundry reads his label LIVE and sends one deposit; a network failure keeps it unsent in
#     memory until "Send now"; Stop ends the camera
#   - H2 (REVIEW-D-1): a 70 px face beside a piece in a 1600 x 1200 photo passes the whole-photo
#     check, and the real UltraFace on the crop at Save keeps and sends nothing; M1: a step change
#     ends the camera
#   - the visual gate at 1440x900 and 390x844, Night and Day; screenshots only where R13_D_SHOTS says
#   - the page clock is pinned (16 Nov 2026, 09:30 IST: the fake server's own time); no fixed sleeps
# ruff: noqa: E501 -- JavaScript strings
from __future__ import annotations

import json
import os
import time
import urllib.request
from collections.abc import Callable, Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from r13_fakes_d import NAVY, Picture, serve_d, y4m
from test_console import DESKTOP, PHONE, Console
from test_ui_audit import NAMELESS_JS, WRAP_JS, _assert_clean
from ui_checks import DOM_CHECKS_JS, FINISH_ANIMATIONS_JS, install_mocks

sync_playwright = pytest.importorskip("playwright.sync_api").sync_playwright
pytestmark = pytest.mark.browser
SHOTS = os.environ.get("R13_D_SHOTS", "")  # screenshots only when asked for
PAGE_NOW = datetime(2026, 11, 16, 4, 0, tzinfo=UTC)  # 09:30 IST, the fake server's SERVED_AT
PERSON = (
    "This picture shows a person. Lay the piece on a surface or hang it, and take the photo again."
)
SAVE = "Save this photo with the piece (sealed; only you)"
DRAW_JS = """(what) => {
  const c = document.createElement('canvas'); c.width = 640; c.height = 480;
  const x = c.getContext('2d'); x.fillStyle = 'rgb(232,228,220)'; x.fillRect(0, 0, 640, 480);
  const ell = (cx, cy, rx, ry, col) => { x.fillStyle = col; x.beginPath(); x.ellipse(cx, cy, rx, ry, 0, 0, Math.PI * 2); x.fill(); };
  if (what === 'shirt') { for (let i = 0; i < 12; i += 1) { x.fillStyle = i % 2 ? 'rgb(28,36,78)' : 'rgb(240,240,236)'; x.fillRect(220 + i * 14, 120, 14, 240); } }
  if (what === 'navy') { x.fillStyle = 'rgb(28,36,78)'; x.fillRect(200, 100, 240, 280); }
  if (what === 'face') { x.fillStyle = 'rgb(120,150,170)'; x.fillRect(0, 0, 640, 480); const s = 220, cx = 320, cy = 240;
    ell(cx, cy + s * 0.05, s * 0.42, s * 0.55, 'rgb(70,45,30)'); ell(cx, cy + s * 0.12, s * 0.36, s * 0.47, 'rgb(224,172,140)');
    [-0.14, 0.14].forEach((d) => { ell(cx + s * d, cy, s * 0.07, s * 0.035, 'rgb(250,250,250)'); ell(cx + s * d, cy, s * 0.03, s * 0.03, 'rgb(40,30,20)'); });
    ell(cx, cy + s * 0.15, s * 0.04, s * 0.08, 'rgb(200,140,110)'); ell(cx, cy + s * 0.32, s * 0.11, s * 0.035, 'rgb(170,70,70)'); }
  if (what === 'figure') { x.fillStyle = 'rgb(205,220,240)'; x.fillRect(0, 0, 640, 480); const k = 'rgb(30,28,34)';
    ell(320, 70, 36, 44, k); ell(320, 200, 78, 104, k); x.fillStyle = k; x.fillRect(264, 275, 48, 200); x.fillRect(330, 275, 48, 200);
    ell(232, 208, 20, 90, k); ell(408, 208, 20, 90, k); }
  return c;
}"""
TASKS_JS = (
    """async () => {
  const draw = """
    + DRAW_JS
    + """;
  const run = async (t, what) => { const r = await window.JarvisVision.run(t, draw(what)); return JSON.parse(JSON.stringify(r)); };
  const out = { embed: await run('embed', 'shirt'), colour: await run('colour', 'navy'),
    face: await run('face', 'face'), person: await run('person', 'figure'),
    clean_face: await run('face', 'shirt'), clean_person: await run('person', 'shirt') };
  out.tasks = window.JarvisVision.tasks().filter((t) => ['embed', 'colour', 'person', 'face'].includes(t.id));
  return out;
}"""
)


@pytest.fixture(scope="module")
def d_url(token: str) -> Iterator[str]:
    if os.environ.get("JARVIS_BROWSER_TESTS") != "1":
        pytest.skip("JARVIS_BROWSER_TESTS=1 not set")
    url, stop = serve_d(token)
    try:
        yield url
    finally:
        stop()


@pytest.fixture(scope="module")
def browser(tmp_path_factory: pytest.TempPathFactory) -> Iterator[Any]:
    clip = tmp_path_factory.mktemp("r13d") / "label.y4m"
    y4m(clip, [Picture(640, 480).qr(220, 120, "jw1:abcdefgh", k=7)] * 3)
    args = ["--use-fake-device-for-media-stream", "--use-fake-ui-for-media-stream"]
    with sync_playwright() as p:
        b = p.chromium.launch(args=[*args, f"--use-file-for-fake-video-capture={clip}"])
        yield b
        b.close()


def until(page: Any, check: Callable[[], bool], what: str, timeout_s: float = 60.0) -> None:
    end = time.monotonic() + timeout_s
    while time.monotonic() < end:
        if check():
            return
        page.wait_for_timeout(100)
    raise AssertionError(f"timed out waiting for {what}")


def seen(url: str, token: str, path: str = "/v1/test/r13-d") -> Any:
    req = urllib.request.Request(url + path, headers={"Authorization": f"Bearer {token}"})
    with urllib.request.urlopen(req, timeout=5) as r:
        return json.loads(r.read())


def wardrobe(browser: Any, url: str, token: str, viewport: dict[str, int] = DESKTOP) -> Console:
    c = Console(browser, url, token, viewport)
    c.page.clock.set_system_time(PAGE_NOW)  # "today" on the door's counter is this day, every run
    install_mocks(c.page)
    c.open()
    c.open_panel("camera")
    c.page.locator("#camt-wardrobe").click()
    c.page.locator("#camp-wardrobe").get_by_role("button", name="Add pieces", exact=True).wait_for()
    return c


def button(c: Console, name: str) -> Any:
    return c.page.locator("#camp-wardrobe").get_by_role("button", name=name, exact=True)


def pane_text(c: Console) -> str:
    return str(c.page.locator("#camp-wardrobe").inner_text())


def choose(c: Console, path: Path) -> None:
    with c.page.expect_file_chooser() as fc:
        button(c, "Choose a photo").click()
    fc.value.set_files(str(path))


def picture(tmp: Path, name: str, pic: Picture) -> Path:
    path = tmp / f"{name}.png"
    path.write_bytes(pic.png())
    return path


def test_the_four_tasks_self_check_and_find_a_drawn_face_and_figure(
    browser: Any, d_url: str, token: str
) -> None:
    c = wardrobe(browser, d_url, token)
    try:
        r = c.page.evaluate(TASKS_JS)
        assert all(t["ready"] for t in r["tasks"]), r["tasks"]
        assert r["embed"]["ok"] and len(r["embed"]["data"]["v"]) == 1708
        assert r["embed"]["data"]["model"] == "mnv2-int8-1"
        assert r["colour"]["data"]["name"] == "navy"
        assert r["face"]["data"]["found"] is True and r["person"]["data"]["found"] is True
        assert r["clean_face"]["data"]["found"] is False
        assert r["clean_person"]["data"]["found"] is False
        assert c.errors == [] and c.csp_violations() == []
    finally:
        c.close()


def test_the_wake_word_and_a_wardrobe_task_share_one_runtime(
    browser: Any, d_url: str, token: str
) -> None:
    c = wardrobe(browser, d_url, token)
    try:
        fetched: list[str] = []
        c.page.on("request", lambda req: fetched.append(req.url))
        c.page.add_script_tag(url="/static/console-wakeword.js")
        c.page.evaluate("() => window.JarvisWake.load()")
        assert c.page.evaluate("() => window.JarvisWake.state") == "idle"
        ok = c.page.evaluate(
            "async () => (await window.JarvisVision.run('embed', (" + DRAW_JS + ")('shirt'))).ok"
        )
        assert ok is True
        ort = [u for u in fetched if "/static/vendor/ort-1.30.0/" in u]
        assert sum(u.endswith("ort.wasm.min.mjs") for u in ort) <= 1
        assert sum(u.endswith(".wasm") for u in ort) == 1  # one runtime binary for both
        assert c.errors == [] and c.csp_violations() == []
    finally:
        c.close()


def test_add_a_piece_save_and_remember_it_then_the_same_photo_offers_it(
    browser: Any, d_url: str, token: str, tmp_path: Path
) -> None:
    shirt = picture(tmp_path, "shirt", Picture(640, 480).shirt(220, 110, 1.0))
    c = wardrobe(browser, d_url, token)
    try:
        before = seen(d_url, token)
        choose(c, shirt)
        button(c, "Shirt").wait_for()
        assert "PIECE 1 OF 1" in pane_text(c).upper()  # one shirt, one box (.hp-h is uppercase)
        assert "Colour:" in pane_text(c) and "(suggested)" in pane_text(c)
        button(c, "Shirt").click()
        button(c, "Save as a new piece").click()
        button(c, SAVE).wait_for()
        button(c, SAVE).click()
        until(c.page, lambda: "Saved with the piece" in pane_text(c), "the photo saved")
        button(c, "Remember how it looks").click()
        until(c.page, lambda: "Remembered" in pane_text(c), "the look remembered")
        assert "Pictures sent from this device today: 1" in pane_text(c)
        got = seen(d_url, token)
        [pid] = got["added"][len(before["added"]) :]
        [photo] = got["photos"][len(before["photos"]) :]
        assert photo["piece"] == pid and photo["view"] == "front"
        assert photo["size"] and max(photo["size"]) <= 512 and photo["bytes"] <= 200 * 1024
        assert pid in got["fingerprints"]
        button(c, "Clear").click()
        choose(c, shirt)
        offer = c.page.locator("#camp-wardrobe button", has_text="(likely this one)").first
        offer.wait_for()
        offer.click()
        until(c.page, lambda: ": this piece." in pane_text(c), "his tap")
        history = seen(d_url, token, f"/v1/wardrobe/pieces/{pid}")["history"]
        kinds = sorted(e["kind"] for e in history)  # the same id, seen again (not its order: the
        assert kinds == ["registered", "seen"]  # page's clock and the server's differ by ms)
        assert c.errors == [] and c.csp_violations() == []
    finally:
        c.close()


@pytest.mark.parametrize("who", ["face", "figure"])
def test_a_photo_with_a_face_or_a_person_keeps_and_sends_nothing(
    browser: Any, d_url: str, token: str, tmp_path: Path, who: str
) -> None:
    pic = Picture(640, 480, (120, 150, 170)).face(320, 240, 220)
    if who == "figure":
        pic = Picture(640, 480, (205, 220, 240)).figure(320, 40, 1.4)
    c = wardrobe(browser, d_url, token)
    try:
        before = seen(d_url, token)
        choose(c, picture(tmp_path, who, pic))
        until(c.page, lambda: PERSON in pane_text(c), "the refusal")
        assert button(c, SAVE).count() == 0
        assert button(c, "Remember how it looks").count() == 0
        after = seen(d_url, token)
        assert after["photos"] == before["photos"] and after["tags"] == before["tags"]
        assert after["fingerprints"] == before["fingerprints"]
        assert "Pictures sent from this device today: 0" in pane_text(c)
    finally:
        c.close()


def test_to_laundry_reads_his_label_live_and_an_unsent_scan_waits(
    browser: Any, d_url: str, token: str
) -> None:
    c = wardrobe(browser, d_url, token)
    try:
        button(c, "To laundry").click()
        button(c, "Start the camera").click()
        until(c.page, lambda: "Its label was read" in pane_text(c), "his label read live")
        c.page.route("**/v1/wardrobe/scan", lambda route: route.abort())
        button(c, "Put in laundry").click()
        until(c.page, lambda: "Not sent yet: keep this page open. (1)" in pane_text(c), "unsent")
        c.page.unroute("**/v1/wardrobe/scan")
        button(c, "Send now").click()
        until(c.page, lambda: "Not sent yet" not in pane_text(c), "the scan sent")
        piece = seen(d_url, token, f"/v1/wardrobe/pieces/{NAVY}")
        assert piece["piece"]["state"] == "in_laundry"
        assert [e["kind"] for e in piece["history"]][-1] == "deposited"
        button(c, "Stop").click()
        assert c.page.evaluate("window.JarvisCamera.live()") is False
        aborted = [e for e in c.errors if e.endswith("/v1/wardrobe/scan")]  # this test's own abort
        assert [e for e in c.errors if e not in aborted] == [] and c.csp_violations() == []
    finally:
        c.close()


def test_h2_a_small_face_only_its_crop_shows_keeps_and_sends_nothing(
    browser: Any, d_url: str, token: str, tmp_path: Path
) -> None:
    pic = Picture(1600, 1200).rect(500, 300, 500, 600, (28, 36, 78)).face(1080, 360, 70)
    c = wardrobe(browser, d_url, token)
    try:
        before = seen(d_url, token)
        choose(c, picture(tmp_path, "small-face", pic))
        button(c, "Shirt").wait_for()
        assert PERSON not in pane_text(c)  # the whole photo's check passed: the miss H2 closes
        button(c, "Shirt").click()
        button(c, "Save as a new piece").click()
        button(c, SAVE).wait_for()  # offered: the crop's own check runs at the press
        button(c, SAVE).click()
        until(c.page, lambda: PERSON in pane_text(c), "the crop's refusal")
        assert button(c, SAVE).count() == 0 and button(c, "Remember how it looks").count() == 0
        after = seen(d_url, token)
        assert (
            after["photos"] == before["photos"] and after["fingerprints"] == before["fingerprints"]
        )
        assert "Pictures sent from this device today: 0" in pane_text(c)
        assert c.errors == [] and c.csp_violations() == []
    finally:
        c.close()


def test_m1_a_step_change_ends_the_live_camera(browser: Any, d_url: str, token: str) -> None:
    c = wardrobe(browser, d_url, token)
    try:
        button(c, "To laundry").click()
        button(c, "Start the camera").click()
        until(c.page, lambda: "Its label was read" in pane_text(c), "his label read live")
        button(c, "Add pieces").click()
        until(c.page, lambda: c.page.evaluate("window.JarvisCamera.live()") is False, "camera off")
        assert c.page.locator("#camp-wardrobe video").count() == 0
        assert "Its label was read" not in pane_text(c)
    finally:
        c.close()


def _audit(c: Console, vp: str, what: str, shot: str) -> None:
    c.page.evaluate("() => document.fonts.ready.then(() => true)")
    c.page.evaluate(FINISH_ANIMATIONS_JS)
    sel = "#p-camera"
    res = c.page.evaluate(DOM_CHECKS_JS, sel)
    assert not res.get("missing"), what
    _assert_clean(res, c.page.evaluate(NAMELESS_JS, sel), c.page.evaluate(WRAP_JS, sel), vp, what)
    if SHOTS:
        Path(SHOTS).mkdir(parents=True, exist_ok=True)
        c.page.screenshot(path=str(Path(SHOTS) / f"{shot}.png"))


@pytest.mark.parametrize("surface", ["night", "day"])
@pytest.mark.parametrize("vp", ["desktop", "phone"])
def test_camera_wardrobe_passes_the_visual_gate(
    browser: Any, d_url: str, token: str, tmp_path: Path, vp: str, surface: str
) -> None:
    shirt = picture(tmp_path, "shirt", Picture(640, 480).shirt(220, 110, 1.0))
    c = wardrobe(browser, d_url, token, DESKTOP if vp == "desktop" else PHONE)
    try:
        if surface == "day":
            c.choose_day()
            c.open_panel("camera")
            c.page.locator("#camt-wardrobe").click()
        size = "1440x900" if vp == "desktop" else "390x844"
        _audit(c, vp, f"wardrobe mode {vp} {surface}", f"camera-wardrobe-start-{size}-{surface}")
        choose(c, shirt)
        button(c, "Shirt").wait_for()
        _audit(c, vp, f"wardrobe card {vp} {surface}", f"camera-wardrobe-card-{size}-{surface}")
        button(c, "Shirt").click()  # a saved piece: its crop shown first (M2), its side (L7)
        button(c, "Save as a new piece").click()
        button(c, SAVE).wait_for()
        c.page.locator("#camp-wardrobe .wd-crop").scroll_into_view_if_needed()
        _audit(c, vp, f"wardrobe saved {vp} {surface}", f"camera-wardrobe-saved-{size}-{surface}")
        button(c, "To laundry").click()
        _audit(
            c, vp, f"wardrobe laundry {vp} {surface}", f"camera-wardrobe-laundry-{size}-{surface}"
        )
        assert c.errors == [] and c.csp_violations() == []
    finally:
        c.close()
