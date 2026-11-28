# tests/browser/test_r8_desk_pane.py -- R8 builder C (docs/plans/r8-vision.md 4.3, 4.7, 4.10; D3, D6, D10, D12; rows
# 181, 182, 183) in a real Chromium with its fake camera (--use-fake-device-for-media-stream):
#   - Camera -> Desk shows the home camera's posture view (GET /v1/coach/live, D3), "Your day" (the strip, its totals,
#     the longest stretch and screen time, never a window title) and the promise for the tracking target (D6)
#   - a session on this laptop's camera starts only from a tap, looks on this device with the driver
#     (JarvisVision.live), draws the use case's view, sends no picture, and on Stop posts each body's tally only
#   - a switch read as off stops the look; "track <name>" can't start a session here (no face matching, D6)
#   - the small window (D10): the view moves into it; closing it stops the camera and keeps the tally
#   - two hours on the fake camera with the small window open (Playwright's clock): the look keeps its rate, the
#     camera stays on, the all-day tally is kept every 15 minutes (risk 1's browser proof, on a fake clock)
#   - the visual gate (ui_checks.DOM_CHECKS_JS) at 1920 x 1080 and 390 x 844, Night and Day; with JARVIS_SHOTS_DIR set,
#     each is saved there as a PNG (docs/plans/r8-integration/screens/c/)
# ruff: noqa: E501 -- JavaScript strings
from __future__ import annotations

import json
import os
import time
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import pytest
from test_console import PHONE, Console
from test_ui_audit import NAMELESS_JS, WRAP_JS, _assert_clean
from ui_checks import DOM_CHECKS_JS, FINISH_ANIMATIONS_JS, install_mocks

sync_playwright = pytest.importorskip("playwright.sync_api").sync_playwright
pytestmark = pytest.mark.browser
FAKE_CAMERA = ["--use-fake-device-for-media-stream", "--use-fake-ui-for-media-stream"]
WIDE = {"width": 1920, "height": 1080}
IMAGE_MARKS = (b"\x89PNG", b"\xff\xd8\xff", b"data:image", b"iVBORw0KGgo", b"/9j/", b"RIFF")
TITLE = "Salary slip - Private bank page"  # a window title that must never show
NOW = int(time.time())
DAY0 = NOW - NOW % 86400 - 19800  # a local midnight in Kolkata near now
POSTURE = {
    "use": "posture",
    "bodies": [{"track": 0, "who": "me", "at": NOW, "view": [
        {"kind": "line", "text": "Leaning towards the screen."},
        {"kind": "timer", "s": 75, "word": "slouching"},
        {"kind": "tip", "text": "Sit back and lift your head, Sir.", "since": NOW - 75, "held": 75},
        {"kind": "bar", "n": 82, "word": "upright"},
    ]}],
}  # fmt: skip


def _day() -> dict[str, Any]:
    h = 3600
    st = [("desk", 9 * h, 10 * h + 1500), ("phone", 10 * h + 1500, 10 * h + 1920), ("desk", 10 * h + 1920, 13 * h),
          ("eating", 13 * h, 13 * h + 1800), ("away", 13 * h + 1800, 14 * h), ("desk", 14 * h, 16 * h + 300),
          ("off", 16 * h + 300, 16 * h + 1200), ("desk", 16 * h + 1200, 17 * h)]  # fmt: skip
    stretches = [{"kind": k, "start": DAY0 + a, "end": DAY0 + b} for k, a, b in st]
    totals = {
        k: sum(b - a for kk, a, b in st if kk == k)
        for k in ("desk", "away", "phone", "eating", "off")
    }
    return {"day": {
        "day": "2026-11-28", "start": DAY0, "end": DAY0 + 86400, "stretches": stretches, "totals": totals,
        "longest": {"start": DAY0 + 14 * h, "end": DAY0 + 16 * h + 300},
        "screen": {"state": "ok", "active_minutes": 370.2, "programs": [
            {"name": "chrome", "minutes": 200.0}, {"name": "Code", "minutes": 150.5}, {"name": "Teams", "minutes": 40.0}]},
    }}  # fmt: skip


USECASES = {"usecases": [  # the registry the pane follows; `water` looks with `quality` here (no model on this server)
    {"id": "water", "row": 248, "release": "R8", "spot": "desk", "source": "browser", "tasks": ["quality"], "rate": 1,
     "health": False, "keeps": True, "module": "console-coach-water.js"},
    {"id": "reaction-game", "row": 224, "release": "R8", "spot": "desk", "source": "browser", "tasks": ["hands"],
     "rate": 15, "health": True, "keeps": True, "module": "console-coach-reaction.js"},
], "views": ["big", "line", "tip", "timer", "pacer", "targets", "checklist", "bar", "paused"]}  # fmt: skip
FAKE_WATER = """() => window.JarvisVision.use({ id: 'water', tasks: ['quality'],
  onResult: (r, s) => ({ n: ((s && s.n) || 0) + (r.ok ? 1 : 0), first: s ? s.first : r.at, last: r.at }),
  summary: (s) => ({ view: [{ kind: 'big', n: (s && s.n) || 0, word: 'looks' }, { kind: 'line', text: 'Counting sips.' },
    { kind: 'checklist', items: [{ text: 'Cup in view', ok: true }, { text: 'Bottle in view', ok: null }] }],
    tally: s ? { started_at: s.first, ended_at: s.last, sips: 0, glasses: 0 } : null }) })"""
FAKE_PIP = """(() => { // a browser without Document Picture-in-Picture: a same-origin frame stands in for the small window
  if (window.documentPictureInPicture) return;
  window.documentPictureInPicture = { requestWindow: async () => {
    const f = document.createElement('iframe'); f.id = 'r8-fake-pip'; f.style.cssText = 'position:fixed;right:0;bottom:0;width:360px;height:320px;border:0';
    document.body.append(f); await new Promise((r) => setTimeout(r, 0)); return f.contentWindow; } };
})();"""
PIP_TEXT = """() => { const d = window.documentPictureInPicture, f = document.getElementById('r8-fake-pip');
  const w = (d && d.window) || (f && f.contentWindow); return w && w.document.body ? w.document.body.innerText : ''; }"""
PIP_CLOSE = """() => { const d = window.documentPictureInPicture, f = document.getElementById('r8-fake-pip');
  if (f) { f.contentWindow.dispatchEvent(new Event('pagehide')); f.remove(); return 'frame'; }
  if (d && d.window) { d.window.close(); return 'window'; } return ''; }"""


@pytest.fixture(scope="module")
def browser() -> Iterator[Any]:
    with sync_playwright() as p:
        b = p.chromium.launch(args=FAKE_CAMERA)
        yield b
        b.close()


class Rig:
    def __init__(self, c: Console) -> None:
        self.c, self.page = c, c.page
        self.posts: list[dict[str, Any]] = []
        self.reqs: list[tuple[str, str, bytes]] = []
        self.spots: dict[str, Any] = {"spots": {"rev": 1, "all_off": False, "rooms": [{"id": "study", "label": "Study", "never": False}],
                                                "cameras": [{"id": "desk_web", "kind": "device", "source": "browser", "label": "Desk camera",
                                                             "spot": "desk", "room": "study", "on": True}]}}  # fmt: skip
        self.target: dict[str, Any] = {"kind": "all", "person": None}
        self.page.on("request", self._on)

    def _on(self, req: Any) -> None:
        try:
            body = req.post_data_buffer or b""
        except Exception:  # noqa: BLE001 - a body the browser can't hand over counts as binary
            body = b"\x89PNG?"
        self.reqs.append((req.method, req.url, body))

    def pictures(self) -> list[str]:
        return [
            f"{m} {u}"
            for m, u, b in self.reqs
            if any(k in b for k in IMAGE_MARKS) or len(b) > 64 * 1024
        ]

    def routes(self) -> None:
        p = self.page

        def fulfil(body: Callable[[], Any], status: int = 200) -> Callable[[Any], None]:
            return lambda route: route.fulfill(status=status, json=body())

        def results(route: Any) -> None:
            if route.request.method == "POST":
                self.posts.append(json.loads(route.request.post_data or "{}"))
                route.fulfill(status=201, json={"kept": {"id": "ct_000000000001", "who": "me"}})
            else:
                route.fulfill(status=200, json={"sealed": True, "keep_days": 90, "results": []})

        def live(route: Any) -> None:
            use = route.request.url.split("use=", 1)[-1]
            route.fulfill(
                status=200, json=POSTURE if use == "posture" else {"use": use, "bodies": []}
            )

        p.route("**/v1/coach/usecases", fulfil(lambda: USECASES))
        p.route("**/v1/coach/target", fulfil(lambda: {"target": self.target}))
        p.route("**/v1/coach/day*", fulfil(_day))
        p.route("**/v1/coach/live*", live)
        p.route("**/v1/coach/results", results)
        p.route("**/v1/camera/spots", fulfil(lambda: self.spots))

    def desk(self) -> None:
        self.c.open()
        self.c.open_panel("camera")
        self.page.locator("#p-camera").get_by_role("tab", name="Desk").click()
        self.page.locator("#p-camera .r8-strip .r8-seg").first.wait_for()
        self.page.locator("#p-camera .r8-card .r8-tip").first.wait_for()

    def start(self, name: str = "Water") -> None:
        self.page.evaluate(FAKE_WATER)
        self.page.locator("#p-camera").get_by_role("button", name="Start " + name).click()

    def looks(self) -> int:
        n = self.page.evaluate(
            "() => { const t = window.JarvisVision.tally('water'); const w = t.view.find((x) => x.kind === 'big'); return w ? w.n : 0; }"
        )
        return int(n)


def until(page: Any, check: Callable[[], bool], what: str, timeout_s: float = 30.0) -> None:
    end = time.monotonic() + timeout_s
    while time.monotonic() < end:
        if check():
            return
        page.wait_for_timeout(100)
    raise AssertionError(f"timed out waiting for {what}")


def rig(
    browser: Any, url: str, token: str, viewport: dict[str, int] = WIDE, *, clock: bool = False
) -> Rig:
    c = Console(browser, url, token, viewport)
    if clock:  # the console's own animations off, so a fake hour runs in seconds (Motion Off, as the owner can set)
        c.page.add_init_script("try { localStorage.setItem('jarvis_motion', 'off'); } catch (e) {}")
        c.page.clock.install()
    install_mocks(c.page)
    r = Rig(c)
    r.routes()
    return r


def test_the_desk_pane_shows_posture_the_day_and_screen_time(
    browser: Any, server_url: str, token: str
) -> None:
    r = rig(browser, server_url, token)
    try:
        r.desk()
        pane = r.page.locator("#p-camera .hp-pane:not([hidden])")
        text = pane.inner_text()
        assert "Everyone in view is followed" in text and "only counts and times are kept" in text
        assert (
            "Sit back and lift your head, Sir." in text and "SLOUCHING" in text and "82 %" in text
        )
        assert r.page.locator("#p-camera .r8-strip .r8-seg").count() == 8
        for words in ("At the desk", "On the phone", "Eating", "Away", "Camera off", "Longest sitting stretch: 2 h 05 m"):  # fmt: skip
            assert words in text, words
        assert "chrome" in text and "SCREEN TIME \u00b7 6 H 10 M" in text and TITLE not in text
        assert "Practice only, not medical advice. Stop if anything hurts." in text
        assert (
            r.page.evaluate("window.JarvisCamera.live()") is False
        )  # opening the pane starts nothing
        assert r.c.errors == [] and r.c.csp_violations() == []
    finally:
        r.c.close()


def test_a_session_looks_here_sends_no_picture_and_keeps_only_its_tally(
    browser: Any, server_url: str, token: str
) -> None:
    r = rig(browser, server_url, token)
    try:
        r.desk()
        r.start()
        chip = r.page.locator(".cam-chip")
        until(r.page, lambda: r.looks() >= 2, "two looks")
        assert chip.is_visible() and r.page.evaluate("window.JarvisCamera.live()") is True
        until(
            r.page, lambda: "looks" in r.page.locator("#p-camera .r8-live").inner_text(), "the view"
        )
        assert "Cup in view" in r.page.locator("#p-camera .r8-live .r8-checks").inner_text()
        r.page.locator("#p-camera .r8-live").get_by_role("button", name="Stop").click()
        until(r.page, lambda: bool(r.posts), "the kept tally")
        until(r.page, lambda: not chip.is_visible(), "the chip to go")
        (post,) = r.posts
        assert post["use"] == "water" and post["who"] == "me" and post["session"].startswith("cs_")
        assert set(post["tally"]) == {"started_at", "ended_at", "sips", "glasses"}
        assert r.pictures() == [] and r.page.evaluate("window.JarvisCamera.live()") is False
        assert "The session ended. Its counts are kept." in r.page.locator("#p-camera").inner_text()
        assert r.c.errors == [] and r.c.csp_violations() == []
    finally:
        r.c.close()


def test_a_switch_read_as_off_or_a_named_target_starts_nothing(
    browser: Any, server_url: str, token: str
) -> None:
    r = rig(browser, server_url, token)
    try:
        r.spots["spots"]["all_off"] = True
        r.desk()
        r.start()
        until(
            r.page,
            lambda: "switched off in Cameras" in r.page.locator("#p-camera").inner_text(),
            "the refusal",
        )
        assert r.page.evaluate("window.JarvisCamera.live()") is False and r.posts == []
        r.spots["spots"]["all_off"] = False
        r.target = {"kind": "person", "person": "fp_0123456789ab"}
        r.page.evaluate("() => document.dispatchEvent(new Event('jarvis:ready'))")
        until(
            r.page,
            lambda: "One person is followed" in r.page.locator("#p-camera").inner_text(),
            "the promise",
        )
        r.page.locator("#p-camera").get_by_role("button", name="Start Water").click()
        until(
            r.page,
            lambda: "only on the home camera" in r.page.locator("#p-camera").inner_text(),
            "the D6 rule",
        )
        assert r.page.evaluate("window.JarvisCamera.live()") is False
    finally:
        r.c.close()


def test_closing_the_small_window_stops_the_camera_and_keeps_the_tally(
    browser: Any, server_url: str, token: str
) -> None:
    r = rig(browser, server_url, token)
    try:
        r.page.add_init_script(FAKE_PIP)
        r.desk()
        r.start()
        until(r.page, lambda: r.looks() >= 1, "a look")
        r.page.locator("#p-camera .r8-live").get_by_role(
            "button", name="Keep a small window on top"
        ).click()
        until(
            r.page,
            lambda: "LOOKS" in r.page.evaluate(PIP_TEXT).upper(),
            "the view in the small window",
        )
        assert (
            "Camera on" in r.page.evaluate(PIP_TEXT)
            and r.page.locator("#p-camera .r8-live .r8-big").count() == 0
        )
        assert r.page.evaluate(PIP_CLOSE)
        until(r.page, lambda: bool(r.posts), "the kept tally")
        until(
            r.page,
            lambda: r.page.evaluate("window.JarvisCamera.live()") is False,
            "the camera to stop",
        )
        assert (
            r.page.locator("#p-camera .r8-live .r8-view").count() == 1
        )  # the view came back to the pane
        assert r.pictures() == []
    finally:
        r.c.close()


def test_two_hours_on_the_fake_camera_with_the_small_window_open(
    browser: Any, server_url: str, token: str
) -> None:
    r = rig(browser, server_url, token, clock=True)
    try:
        r.page.add_init_script(FAKE_PIP)
        r.desk()
        r.start()
        until(r.page, lambda: r.looks() >= 1, "a look")
        r.page.locator("#p-camera .r8-live").get_by_role(
            "button", name="Keep a small window on top"
        ).click()
        until(r.page, lambda: "Camera on" in r.page.evaluate(PIP_TEXT), "the small window")
        first = r.looks()
        for minute in range(
            1, 121
        ):  # two hours, a minute at a time; each minute's looks finish before the next
            r.page.clock.run_for(60_000)
            until(
                r.page,
                lambda m=minute: r.looks() >= first + 54 * m,
                f"minute {minute}'s looks",
                20.0,
            )
            assert r.page.evaluate("window.JarvisCamera.live()") is True, minute
        assert r.looks() - first >= 0.9 * 7200
        assert len(r.posts) == 8  # the all-day coach's tally, every 15 minutes
        assert r.page.evaluate(PIP_CLOSE)
        until(r.page, lambda: len(r.posts) == 9, "the last tally")
        assert r.page.evaluate("window.JarvisCamera.live()") is False and r.pictures() == []
    finally:
        r.c.close()


@pytest.mark.parametrize("surface", ["night", "day"])
@pytest.mark.parametrize("size", ["wide", "phone"])
def test_the_desk_pane_passes_the_visual_gate(
    browser: Any, server_url: str, token: str, size: str, surface: str
) -> None:
    vp = WIDE if size == "wide" else PHONE
    r = rig(browser, server_url, token, vp)
    try:
        r.desk()
        if surface == "day":
            r.c.choose_day()
        r.page.locator("#p-camera .r8-strip").scroll_into_view_if_needed()
        r.page.evaluate(FINISH_ANIMATIONS_JS)
        sel = "#p-camera .hp-pane:not([hidden])"
        res = r.page.evaluate(DOM_CHECKS_JS, sel)
        _assert_clean(
            res,
            r.page.evaluate(NAMELESS_JS, sel),
            r.page.evaluate(WRAP_JS, sel),
            size,
            f"desk {size} {surface}",
        )
        shots = os.environ.get("JARVIS_SHOTS_DIR", "")
        if shots:
            Path(shots).mkdir(parents=True, exist_ok=True)
            r.page.locator("#p-camera .pbody").evaluate("(el) => { el.scrollTop = 0; }")
            r.page.screenshot(path=str(Path(shots) / f"desk-{size}-{surface}-top.png"))
            r.page.locator("#p-camera .r8-add").first.scroll_into_view_if_needed()
            r.page.screenshot(path=str(Path(shots) / f"desk-{size}-{surface}-sessions.png"))
        assert r.c.errors == [] and r.c.csp_violations() == []
    finally:
        r.c.close()
