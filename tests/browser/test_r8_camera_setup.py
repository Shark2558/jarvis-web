# tests/browser/test_r8_camera_setup.py -- R8 builder B in a real Chromium (docs/plans/r8-vision.md
# v8.0.4 sections 4.5, 4.6; rows 217, 184, 377; the approved mockup camera-setup.html), against the
# real app (mock brain) with camera setup wired the way I1 will (`build_camera_setup` on MemoryDocs)
# and a fake home laptop answering the camera check. Chromium's own fake camera; no picture is used.
#   - Camera -> Cameras: add this device's camera; its "Switch off" stops a live look on this device
#     within 2 s and a start is refused in plain words until a tap allows it again
#   - another device (its own browser context) stops within a minute ("cameras off" from the first)
#     and the "Camera on" chip shows exactly while a track is live
#   - a room switched off and a "never" room; "Allow cameras again" is a tap
#   - "Check a camera": a public address is refused; the two stages, then "Add as a home camera"
#   - no request carries a picture; the visual gate at 1920 x 1080 and 390 x 844, Night and Day
#     (screenshots only where R8_B_SHOTS says)
# ruff: noqa: E501 -- the test server's program reads best whole
from __future__ import annotations

import os
import socket
import subprocess
import sys
import time
import urllib.request
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import pytest
from test_console import Console
from test_ui_audit import NAMELESS_JS, WRAP_JS, _assert_clean
from ui_checks import DOM_CHECKS_JS, FINISH_ANIMATIONS_JS, install_mocks

sync_playwright = pytest.importorskip("playwright.sync_api").sync_playwright
pytestmark = pytest.mark.browser
SHOTS = os.environ.get("R8_B_SHOTS", "")
ROOT = Path(__file__).resolve().parents[2]
WIDE = {"width": 1920, "height": 1080}
PHONE = {"width": 390, "height": 844}
SPOT_OFF = "This camera is switched off in Camera, Cameras. Tap Allow there to switch it on."
SERVER = r"""
import sys
import uvicorn
from jarvis.api import create_app
from jarvis.api.camera_spots import build_camera_setup
from jarvis.keyring import Keyring
from jarvis.llm.mock_provider import MockProvider
from jarvis.storage.docs import MemoryDocs

NAMES = [("onvif", "JARVIS can find and name it (ONVIF)."),
         ("profiles", "It offers a main and a smaller sub-stream (ONVIF Profile S)."),
         ("rtsp_main", "Sends video on your Wi-Fi (RTSP, main stream)."),
         ("rtsp_sub", "Sends video on your Wi-Fi (RTSP, sub stream)."), ("h264", "Its video is H.264.")]


class Kit:  # the home laptop's camera check, as the bridge answers it (jarvis.homebridge.camcheck.view)
    def __init__(self):
        self.jobs = {}

    async def call(self, uid, method, path, body=None, *, query=None):
        ip, stage = body["ip"], body.get("stage", "first")
        if body.get("action") == "start":
            self.jobs[ip] = [stage, 0]
        job = self.jobs.setdefault(ip, [stage, 0])
        job[1] += 1
        checks = [{"id": i, "ok": True, "words": w} for i, w in NAMES]
        if job[0] == "first":
            off = {"id": "offline", "ok": None, "words": "Not checked yet: block its internet in your router, restart it, then check again."}
            return {"ip": ip, "stage": "first", "state": "done", "verdict": "half", "checks": checks + [off],
                    "missing": "", "rounds": 1, "rounds_done": 1}
        done = job[1] >= 2
        off = {"id": "offline", "ok": True if done else None,
               "words": "Still works with its internet blocked (checked for two minutes)." if done else "Round 1 of 5."}
        return {"ip": ip, "stage": "offline", "state": "done" if done else "running", "verdict": "pass" if done else "",
                "checks": checks + [off], "missing": "", "rounds": 5, "rounds_done": 5 if done else 1}


app = create_app(provider=MockProvider())
app.state.camera_setup = build_camera_setup(MemoryDocs(), Keyring(bytes(range(71, 103))), caller=Kit())
uvicorn.run(app, host="127.0.0.1", port=int(sys.argv[1]), log_level="warning")
"""


@pytest.fixture(scope="module")
def b_url(token: str) -> Iterator[str]:
    if os.environ.get("JARVIS_BROWSER_TESTS") != "1":
        pytest.skip("JARVIS_BROWSER_TESTS=1 not set")
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = int(s.getsockname()[1])
    env = {
        **os.environ, "PYTHONPATH": str(ROOT / "src"), "JARVIS_ENV": "dev",
        "JARVIS_LLM_BACKEND": "mock", "JARVIS_SESSION_BACKEND": "memory",
        "JARVIS_AUTH_MODE": "token", "JARVIS_API_TOKEN": token, "JARVIS_LOG_LEVEL": "WARNING",
        "JARVIS_USD_INR_LIVE": "0", "JARVIS_RATE_LIMIT_PER_MINUTE": "6000",
    }  # fmt: skip
    env.pop("JARVIS_ANTHROPIC_API_KEY", None)
    proc = subprocess.Popen([sys.executable, "-c", SERVER, str(port)], cwd=ROOT, env=env,
                            stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)  # fmt: skip
    url = f"http://127.0.0.1:{port}"
    deadline = time.monotonic() + 60
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            raise RuntimeError("the camera setup server exited early")
        try:
            with urllib.request.urlopen(url + "/health", timeout=1) as r:
                if r.status == 200:
                    break
        except OSError:
            time.sleep(0.2)
    else:
        proc.kill()
        raise RuntimeError("the camera setup server did not become healthy")
    try:
        yield url
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()


@pytest.fixture(scope="module")
def browser() -> Iterator[Any]:
    with sync_playwright() as p:
        b = p.chromium.launch(
            args=["--use-fake-device-for-media-stream", "--use-fake-ui-for-media-stream"]
        )
        yield b
        b.close()


def until(page: Any, check: Callable[[], bool], what: str, timeout_s: float = 30.0) -> None:
    end = time.monotonic() + timeout_s
    while time.monotonic() < end:
        if check():
            return
        page.wait_for_timeout(50)
    raise AssertionError(f"timed out waiting for {what}")


RESET_JS = """async () => {
  const api = window.JarvisConsole.api, v = await api('/v1/camera/spots');
  await api('/v1/camera/spots', { method: 'PUT', body: { rev: v.rev, cameras: [], rooms: [], all_off: false } });
}"""


def opened(
    browser: Any,
    url: str,
    token: str,
    viewport: dict[str, int] = WIDE,
    clock: bool = False,
    fresh: bool = True,
) -> Console:
    c = Console(browser, url, token, viewport)
    c.sent = []  # type: ignore[attr-defined]
    c.page.on("request", lambda r: c.sent.append((r.method, r.url, r.post_data_buffer or b"")))  # type: ignore[attr-defined]
    if clock:
        c.page.clock.install()
    install_mocks(c.page)
    c.open()
    if fresh:  # one server for the module: every test starts with no camera set up
        c.page.evaluate(RESET_JS)
    c.open_panel("camera")
    return c


def pane(c: Console, tab: str = "cameras") -> Any:
    """The tab's pane; for Cameras, this part's own box (the panel's "This device" section above it
    has its own Switch off / Allow: the device's lock)."""
    c.page.locator(f"#camt-{tab}").click()
    return c.page.locator("#camp-cameras .r8-setup" if tab == "cameras" else f"#camp-{tab}")


def disclose(p: Any) -> None:
    p.locator("button.dsc").click()  # its name carries the summary line while closed


def press(where: Any, name: str) -> None:
    where.get_by_role("button", name=name, exact=True).first.click()


def live(c: Console) -> bool:
    return bool(c.page.evaluate("() => window.JarvisCamera.live()"))


def chip(c: Console) -> bool:
    return bool(c.page.locator(".cam-chip").is_visible())


def add_this(c: Console, name: str = "Desk camera", room: str = "Study") -> Any:
    p = pane(c)
    p.get_by_role("button", name="Add this camera", exact=True).wait_for()
    p.get_by_label("Name this camera").fill(name)
    p.get_by_label("Room (optional)").fill(room)
    press(p, "Add this camera")
    p.get_by_role("button", name="Switch off", exact=True).wait_for()
    return p


def start_look(c: Console) -> None:
    look = pane(c, "look")
    c.page.locator("#camTask").select_option("quality")
    press(look, "Start the camera")
    until(c.page, lambda: live(c) and chip(c), "the look to start and the chip to show")


def no_picture_sent(c: Console) -> None:
    for method, url, body in c.sent:  # type: ignore[attr-defined]
        if "/v1/" not in url or method == "GET":
            continue
        assert len(body) < 4096, (method, url, len(body))
        assert b"image/" not in body and b"base64" not in body and b"\xff\xd8\xff" not in body, url


def test_this_cameras_switch_stops_its_look_within_two_seconds(
    browser: Any, b_url: str, token: str
) -> None:
    c = opened(browser, b_url, token)
    try:
        p = add_this(c)
        assert c.page.evaluate("() => window.JarvisCamera.spot()") == "desk_camera"
        assert "This device \u00b7 Desk, in the study" in p.inner_text()
        start_look(c)
        p = pane(c)
        put = lambda r: r.request.method == "PUT" and r.url.endswith("/v1/camera/spots")  # noqa: E731
        with c.page.expect_response(put):
            press(p, "Switch off")
        t0 = time.monotonic()  # the switch is saved: from here this device has 2 s
        until(c.page, lambda: not live(c) and not chip(c), "the look to stop", timeout_s=2.0)
        assert time.monotonic() - t0 <= 2.0
        look = pane(c, "look")
        press(look, "Start the camera")
        until(c.page, lambda: SPOT_OFF in look.inner_text(), "the plain refusal")
        assert not live(c) and not chip(c)
        press(pane(c), "Allow")
        start_look(c)
        c.page.evaluate("() => window.JarvisCamera.stop()")
        no_picture_sent(c)
        assert c.errors == [] and c.csp_violations() == []
    finally:
        c.close()


def test_cameras_off_reaches_another_device_within_a_minute(
    browser: Any, b_url: str, token: str
) -> None:
    a = opened(browser, b_url, token)
    b = opened(browser, b_url, token, PHONE, clock=True, fresh=False)
    try:
        add_this(b, "Workout phone", "Living room")
        start_look(b)
        press(pane(a), "All cameras off")
        p = pane(a)
        p.get_by_role("button", name="Allow cameras again", exact=True).wait_for()
        assert a.page.evaluate("() => window.JarvisCamera.locked()") is True  # this device at once
        assert live(b) and chip(b)  # the other device has not read the switches yet
        b.page.clock.fast_forward(61_000)
        until(b.page, lambda: not live(b) and not chip(b), "the other device to stop", timeout_s=10)
        press(p, "Allow cameras again")
        until(
            a.page,
            lambda: p.get_by_role("button", name="Allow cameras again").count() == 0,
            "allowed",
        )
        assert a.page.evaluate("() => window.JarvisCamera.locked()") is False
        start_look(b)  # a tap starts it again
        b.page.evaluate("() => window.JarvisCamera.stop()")
        assert a.errors == [] and b.errors == []
    finally:
        a.close()
        b.close()


def test_a_room_switched_off_and_a_never_room(browser: Any, b_url: str, token: str) -> None:
    c = opened(browser, b_url, token)
    try:
        p = add_this(c, "Desk camera", "Study")
        sw = p.get_by_role("button", name="Study cameras", exact=True)
        assert sw.get_attribute("aria-pressed") == "true"
        sw.click()
        until(
            c.page,
            lambda: "Study is switched off, so Desk camera is too" in p.inner_text(),
            "the room off",
        )
        assert (
            p.get_by_role("button", name="Study cameras").get_attribute("aria-pressed") == "false"
        )
        p.get_by_label("Never use cameras here").check()
        until(c.page, lambda: "marked never for cameras" in p.inner_text(), "the never room")
        assert p.get_by_role("button", name="Study cameras").is_disabled()
        coach = c.page.evaluate(
            "async () => (await window.JarvisConsole.api('/v1/camera/spots')).coach"
        )
        assert coach == {"desk_camera": False}  # no coach can be chosen there
        start = pane(c, "look")
        press(start, "Start the camera")
        until(c.page, lambda: SPOT_OFF in start.inner_text(), "refused in a never room")
    finally:
        c.close()


def test_check_a_camera_in_two_stages_then_add_it(browser: Any, b_url: str, token: str) -> None:
    c = opened(browser, b_url, token)
    try:
        p = pane(c)
        disclose(p)
        assert "RTSP, with a main and a sub-stream" in p.inner_text()
        addr = p.get_by_label("The camera’s address on your Wi-Fi (its own app shows it)")
        addr.fill("8.8.8.8")
        press(p, "Check")
        until(c.page, lambda: "only a camera on your own Wi-Fi" in p.inner_text(), "the refusal")
        addr = p.get_by_label("The camera’s address on your Wi-Fi (its own app shows it)")
        addr.fill("192.168.1.40")
        press(p, "Check")
        until(c.page, lambda: "HALF WAY" in p.inner_text().upper(), "the first stage")
        again = p.get_by_role("button", name="Check again, internet blocked", exact=True)
        assert again.is_disabled()
        p.get_by_label("I blocked its internet and restarted it").check()
        press(p, "Check again, internet blocked")
        until(
            c.page,
            lambda: "No cloud service needed" in p.inner_text(),
            "the offline stage",
            timeout_s=20,
        )
        press(p, "Add as a home camera")
        until(c.page, lambda: "Home kit id: home_camera" in p.inner_text(), "the home camera added")
        no_picture_sent(c)
        refused = [e for e in c.errors if "422" in e and e.endswith("/v1/camera/check")]
        assert len(refused) == 1  # the public address, refused by the server (by design)
        assert [e for e in c.errors if e not in refused] == [] and c.csp_violations() == []
    finally:
        c.close()


def _gate(c: Console, vp: str, what: str) -> None:
    c.page.evaluate("() => document.fonts.ready.then(() => true)")
    c.page.evaluate(FINISH_ANIMATIONS_JS)
    sel = "#p-camera"
    res = c.page.evaluate(DOM_CHECKS_JS, sel)
    assert not res.get("missing"), what
    _assert_clean(res, c.page.evaluate(NAMELESS_JS, sel), c.page.evaluate(WRAP_JS, sel), vp, what)


@pytest.mark.parametrize("surface", ["night", "day"])
@pytest.mark.parametrize("vp", ["desktop", "phone"])
def test_the_cameras_pane_passes_the_visual_gate(
    browser: Any, b_url: str, token: str, vp: str, surface: str
) -> None:
    c = opened(browser, b_url, token, WIDE if vp == "desktop" else PHONE)
    try:
        if surface == "day":
            c.choose_day()
        p = pane(c)
        p.get_by_role("button", name="Add this camera", exact=True).wait_for()
        _gate(c, vp, f"first use, {vp} {surface}")
        if SHOTS:
            Path(SHOTS).mkdir(parents=True, exist_ok=True)
            p.locator(".r8-promise").evaluate("(n) => n.scrollIntoView({ block: 'start' })")
            c.page.screenshot(path=str(Path(SHOTS) / f"cameras-first-{vp}-{surface}.png"))
        add_this(c, "Workout phone" if vp == "phone" else "Desk camera", "Study")
        disclose(p)
        p.get_by_label("The camera’s address on your Wi-Fi (its own app shows it)").fill(
            "192.168.1.40"
        )
        press(p, "Check")
        until(c.page, lambda: "HALF WAY" in p.inner_text().upper(), "the first stage")
        _gate(c, vp, f"set up with a check, {vp} {surface}")
        if SHOTS:
            p.locator(".r8-card").evaluate("(n) => n.scrollIntoView({ block: 'end' })")
            c.page.screenshot(path=str(Path(SHOTS) / f"cameras-check-{vp}-{surface}.png"))
            p.locator(".r8-promise").evaluate("(n) => n.scrollIntoView({ block: 'start' })")
            c.page.screenshot(path=str(Path(SHOTS) / f"cameras-set-{vp}-{surface}.png"))
        assert c.errors == [] and c.csp_violations() == []
    finally:
        c.close()


def test_the_six_tabs_are_three_by_two_and_this_device_has_one_switch(
    browser: Any, b_url: str, token: str
) -> None:
    """R8 I1 (the join's visual fixes): the Camera panel's six tabs sit 3 x 2 (the mockup), and
    once this device is in the list its row is its one switch: the panel's own "This device"
    row (the device's lock) hides; it shows again while this device isn't listed."""
    c = opened(browser, b_url, token)
    try:
        tops = c.page.evaluate(
            "() => [...document.querySelectorAll('#p-camera .hp-tabs .hp-tab')]"
            ".map((b) => Math.round(b.getBoundingClientRect().top))"
        )
        assert len(tops) == 6 and tops[0] == tops[1] == tops[2] and tops[3] == tops[4] == tops[5]
        assert tops[3] > tops[0]
        switches = (
            "() => [...document.querySelectorAll('#camp-cameras button')].filter((b) =>"
            " b.offsetParent !== null && /^(Switch off|Allow)$/.test(b.textContent.trim())).length"
        )
        pane(c)
        assert c.page.evaluate(switches) == 1  # not listed yet: the panel's own row only
        add_this(c)
        until(c.page, lambda: c.page.evaluate(switches) == 1, "one switch for this device")
        assert c.errors == [] and c.csp_violations() == []
    finally:
        c.close()
