# tests/browser/test_r131_b_stage.py -- R13.1 Part B in a real Chromium (docs/plans/r13-1-try-on.md
# D2, D5-D9): the 3D figure's engine (console-tryon-3d.js) on the bare stage page of I0's fake
# server (GET /r131/stage?mod=b_stage.mjs, under the console's CSP, dressed in the console's own
# style sheets). What a pixel proves is proved here; the geometry and the walks are in
# tests/test_r131_b_figure.py (Node).
#   AVT-02  Front, Side and Back are three yaws (0, 90, 180) and three different pictures; a drag,
#           the arrow keys, the wheel and a double click work; the label is under the figure
#   AVT-05  the texture comes from his crop through the door's read-only thumb(); a card's and a
#           private piece's photo are never asked for; nothing is fetched but the engine's files
#   AVT-06  swapping the watch repaints the wrist only
#   AVT-08  front -> back keeps the pieces, the styling state and the weights
#   AVT-10  open -> closed redraws the jacket's front, the same jacket
#   AVT-11  two figures under one camera on one canvas, within the triangle budget
#   AVT-14  snapshot({caption}) is a PNG of the figure with the caption lines beneath it
#   AVT-15  the failure signals: no WebGL2, a file that fails, the context lost, a first frame that
#           never comes (10 s), and a second mount after dispose
# Only a Chromium without WebGL2 may skip the 3D tests; an engine that fails must fail them.
from __future__ import annotations

import base64
import io
from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Any

import pytest
from playwright.sync_api import Page, sync_playwright
from r131_fake_server import serve

pytestmark = pytest.mark.browser

PAGE_NOW = datetime(2026, 11, 17, 3, 30, tzinfo=UTC)  # 09:00 IST, the fakes' NOW
GL = [
    "--use-gl=angle",
    "--use-angle=swiftshader",
    "--enable-unsafe-swiftshader",
    "--ignore-gpu-blocklist",
]
LOADED = "() => window.__b && window.__b.loaded"


@pytest.fixture(scope="module")
def stage_url(token: str) -> Iterator[str]:
    url, stop = serve(token)
    try:
        yield url
    finally:
        stop()


@pytest.fixture(scope="module")
def browser() -> Iterator[Any]:
    with sync_playwright() as p:
        b = p.chromium.launch(args=GL)
        try:
            yield b
        finally:
            b.close()


class Stage:
    """One stage page: its console errors, its requests, and helpers over window.__b."""

    def __init__(
        self, browser: Any, url: str, query: str = "", scale: float = 1, frozen: bool = False
    ) -> None:
        self.page: Page = browser.new_page(
            viewport={"width": 620, "height": 760}, device_scale_factor=scale
        )
        self.errors: list[str] = []
        self.requests: list[str] = []
        self.page.on("pageerror", lambda e: self.errors.append(str(e)))
        self.page.on("request", lambda r: self.requests.append(r.url.replace(url, "")))
        if frozen:
            self.page.clock.install(time=PAGE_NOW)  # timers wait for the test (the 10 s rule)
        else:
            self.page.clock.set_fixed_time(PAGE_NOW)  # a pinned date; frames run
        self.page.add_init_script(
            "window.__frames = 0; const raf = window.requestAnimationFrame.bind(window);"
            "window.requestAnimationFrame = (f) => raf((t) => { window.__frames++; f(t); });"
        )
        self.page.goto(f"{url}/r131/stage?mod=b_stage.mjs&{query}")
        self.page.wait_for_function(LOADED, timeout=30000)
        assert self.js("b.error") == "", self.js("b.error")

    def js(self, expr: str) -> Any:
        return self.page.evaluate("async () => { const b = window.__b; return (" + expr + "); }")

    def need_3d(self) -> None:
        if self.js("b.engine.supported()"):
            return
        self.close()
        pytest.skip(
            "this Chromium has no WebGL2: the checklist path is covered by the signal tests"
        )

    def show(self, names: str, opts: str = "{}", weights: str = "undefined") -> Any:
        return self.js(f"await b.show({names}, {opts}, {weights})")

    def stats(self) -> Any:
        return self.js("b.stage.stats()")

    def shot(self) -> Any:
        from PIL import Image

        self.page.wait_for_timeout(150)
        return Image.open(io.BytesIO(self.page.locator("#stage canvas").screenshot())).convert(
            "RGB"
        )

    def close(self) -> None:
        self.page.close()


def _diff_box(a: Any, b: Any) -> tuple[int, int, int, int] | None:
    from PIL import ImageChops

    box: tuple[int, int, int, int] | None = ImageChops.difference(a, b).getbbox()
    return box


def _open(browser: Any, url: str, query: str = "", **kw: Any) -> Stage:
    s = Stage(browser, url, query, **kw)
    s.need_3d()
    return s


def test_avt02_the_basic_figure_turns_to_distinct_front_side_and_back_views(
    browser: Any, stage_url: str
) -> None:
    s = _open(browser, stage_url)
    try:
        res = s.js(
            "(b.mount(), b.stage.show([{body: b.L.body({height: 0.26}, ['height']),"
            " look: {slots: []}}], b.L.opts()))"
        )
        assert res["drawn"] == [] and res["cards"] == []
        s.js("await b.stage.ready")
        assert s.page.locator("#stage p.sfine").inner_text() == "Estimated from your measurements"
        assert s.page.locator("#stage canvas").count() == 1
        shots, yaws = {}, {}
        for name in ("front", "side", "back"):
            s.js(f"b.stage.view('{name}')")
            shots[name], yaws[name] = s.shot(), s.stats()["yaw"]
        assert yaws == {"front": 0, "side": 90, "back": 180}
        assert _diff_box(shots["front"], shots["side"]) and _diff_box(shots["side"], shots["back"])
        assert _diff_box(shots["front"], shots["back"])
        s.js("b.stage.view('front')")
        box = s.page.locator("#stage canvas").bounding_box()
        assert box is not None
        s.page.mouse.move(box["x"] + 240, box["y"] + 250)
        s.page.mouse.down()
        s.page.mouse.move(box["x"] + 300, box["y"] + 250, steps=4)
        s.page.mouse.up()
        assert s.stats()["yaw"] == 330  # a drag of 60 px turns it 30 degrees
        s.page.locator("#stage canvas").focus()
        s.page.keyboard.press("ArrowRight")
        assert s.stats()["yaw"] == 345
        for _ in range(9):
            s.page.keyboard.press("+")
        assert s.stats()["zoom"] == 4  # within limits
        s.page.mouse.wheel(0, 4000)
        assert s.stats()["zoom"] == 0
        s.js("b.stage.closer()")
        assert s.stats()["closer"] is True
        s.page.locator("#stage canvas").dblclick()
        st = s.stats()
        assert (st["yaw"], st["zoom"], st["closer"]) == (0, 0, False)
        assert st["state"] == "ready" and st["figures"] == 1 and 0 < st["triangles"] <= 32000
        assert s.errors == []
    finally:
        s.close()


def test_avt05_the_texture_is_his_crop_and_nothing_else_is_fetched(
    browser: Any, stage_url: str
) -> None:
    s = _open(browser, stage_url, "door=1")
    try:
        res = s.show("'withCard'")
        assert res["approx"]["top"] == ["template", "texture"] and res["cards"] == ["accessory"]
        s.page.wait_for_function("() => window.__b.door.asked.length > 0", timeout=10000)
        s.page.wait_for_timeout(300)
        assert s.js("b.door.asked") == ["wh_000000000041"]  # never the card's, never a private one
        plain = Stage(browser, stage_url)
        try:
            plain.show("'withCard'")
            assert _diff_box(s.shot(), plain.shot())  # the crop is on the shirt
            assert plain.js("b.door.asked") == []
        finally:
            plain.close()
        fetched = [
            r for r in s.requests if not r.startswith(("/r131/", "/static/console", "data:"))
        ]
        assert sorted(set(fetched)) == [
            "/static/vendor/mannequin/m1/body.glb",
            "/static/vendor/mannequin/m1/garments.glb",
            "/static/vendor/three-0.187.0/three.module.min.js",
        ]
        assert s.errors == []
    finally:
        s.close()


def test_avt06_swapping_the_watch_changes_the_left_wrist_and_its_thumbnail(
    browser: Any, stage_url: str
) -> None:
    s = _open(browser, stage_url)
    try:
        s.show("b.L.formal()", "{view: 'side'}")
        before = s.shot()
        assert s.stats()["looks"][0]["pieces"]["watch"] == "wi_000000000006"
        res = s.show("b.L.swapWatch(b.L.formal(), 99, [230, 200, 60])", "{view: 'side'}")
        after = s.shot()
        assert (
            "watch" in res["drawn"]
            and s.stats()["looks"][0]["pieces"]["watch"] == "wi_000000000099"
        )
        box = _diff_box(before, after)
        assert box is not None
        w, h = before.size
        assert box[2] - box[0] < w * 0.2 and box[3] - box[1] < h * 0.1, (
            box
        )  # the wrist, nothing else
        assert h * 0.4 < box[1] < h * 0.75, box
    finally:
        s.close()


def test_avt08_front_to_back_keeps_the_same_pieces_layers_and_figure(
    browser: Any, stage_url: str
) -> None:
    s = _open(browser, stage_url)
    try:
        res = s.show("'withCard'", "{tucked: true, layers: 'all'}", "{height: 0.26, waist: 0.5}")
        front, front_shot = s.stats(), s.shot()
        s.js("b.stage.view('back')")
        back, back_shot = s.stats(), s.shot()
        assert back["yaw"] == 180 and front["yaw"] == 0 and _diff_box(front_shot, back_shot)
        assert back["looks"] == front["looks"] and back["triangles"] == front["triangles"]
        assert (
            back["looks"][0]["cards"] == ["accessory"] == res["cards"]
        )  # a photo-only piece: a card
        assert back["looks"][0]["state"] == {"tucked": True, "open": False, "layers": "all"}
        assert back["looks"][0]["weights"]["height"] == 0.26
    finally:
        s.close()


def test_avt10_closing_the_jacket_hides_the_shirt_front_and_keeps_the_same_jacket(
    browser: Any, stage_url: str
) -> None:
    s = _open(browser, stage_url)
    try:
        s.show("'formal'", "{open: true}")
        opened, piece = s.shot(), s.stats()["looks"][0]["pieces"]["outer"]
        s.show("'formal'", "{open: false}")
        closed, st = s.shot(), s.stats()["looks"][0]
        assert st["pieces"]["outer"] == piece and st["state"]["open"] is False
        w, h = opened.size
        mid = (
            w // 2,
            int(h * 0.36),
        )  # the middle of the chest: shirt when open, jacket when closed
        assert opened.getpixel(mid)[2] > 150 and sum(opened.getpixel(mid)) > 400, opened.getpixel(
            mid
        )
        assert sum(closed.getpixel(mid)) < 250, closed.getpixel(mid)
        tucked = s.show("'formal'", "{layers: 'no_outer', tucked: true}")
        loose = s.show("'formal'", "{layers: 'no_outer', tucked: false}")
        assert "belt" in tucked["drawn"] and loose["hidden"] == ["outer", "belt"]
        kurta = s.show("'festive'", "{tucked: true}")
        assert s.stats()["looks"][0]["state"]["tucked"] is False and "top" in kurta["drawn"]
    finally:
        s.close()


def test_avt11_a_formal_and_a_festive_look_compare_with_both_lists_and_their_readiness(
    browser: Any, stage_url: str
) -> None:
    s = _open(browser, stage_url, "w=560")
    try:
        res = s.show("['formal', 'festive']")
        st = s.stats()
        assert st["figures"] == 2 and 0 < st["triangles"] <= 64000
        assert s.page.locator("#stage canvas").count() == 1  # one camera, one light set, one canvas
        assert [f["drawn"][0] for f in res["figures"]] == ["top", "top"]
        assert st["looks"][0]["pieces"]["top"] != st["looks"][1]["pieces"]["top"]
        img = s.shot()
        w, h = img.size
        halves = [img.crop((0, 0, w // 2, h)), img.crop((w // 2, 0, w, h))]
        for half in halves:  # a figure in each half
            assert len(half.getcolors(maxcolors=1 << 20) or []) > 200
        s.js("b.stage.view('back')")
        assert s.stats()["yaw"] == 180 and s.stats()["figures"] == 2
    finally:
        s.close()


def test_avt14_a_shared_look_shows_the_dressed_figure_and_only_approved_details(
    browser: Any, stage_url: str
) -> None:
    from PIL import Image

    s = _open(browser, stage_url, "door=1")
    try:
        s.show(
            "{slots: [...b.L.formal().slots, {slot: 'underwear', private: true,"
            " piece: 'wi_5ec2e7000000', photo: 'wh_5ec2e7000000', rgb: [255, 0, 255]}]}"
        )
        png = s.js(
            "await (async () => { const blob = await b.stage.snapshot({caption: ["
            "'Tue 17 Nov, 18:00',"
            " 'Light blue shirt', 'Base layer (covered)']});"
            " const buf = new Uint8Array(await blob.arrayBuffer()); let t = '';"
            " for (const x of buf) t += String.fromCharCode(x); return [blob.type, btoa(t)]; })()"
        )
        assert png[0] == "image/png"
        img = Image.open(io.BytesIO(base64.b64decode(png[1]))).convert("RGB")
        canvas = s.page.locator("#stage canvas").bounding_box()
        assert canvas is not None
        assert img.size[0] == round(canvas["width"]) and img.size[1] > round(canvas["height"]) + 60
        figure = img.crop((0, 0, img.size[0], round(canvas["height"])))
        words = img.crop((0, round(canvas["height"]), *img.size))
        assert len(figure.getcolors(maxcolors=1 << 20) or []) > 500  # the dressed figure
        assert (
            2 < len(words.getcolors(maxcolors=1 << 20) or []) < 400
        )  # only the lines, on the panel
        assert not [
            c
            for _, c in (img.getcolors(maxcolors=1 << 22) or [])
            if c[0] > 240 and c[1] < 30 and c[2] > 240
        ]
        assert s.js("b.door.asked") == []  # the private piece's crop is never read
        bare = s.js("await (async () => (await b.stage.snapshot({})).size)()")
        assert 0 < bare < len(base64.b64decode(png[1])) + 1
        assert s.errors == []
    finally:
        s.close()


@pytest.mark.parametrize("surface", ["day", "night"])
def test_the_figure_takes_the_consoles_surface_and_a_phone_keeps_its_pixel_ratio(
    browser: Any, stage_url: str, surface: str
) -> None:
    s = _open(browser, stage_url, f"surface={surface}&w=360&h=520", scale=3)
    try:
        s.show("'formal'")
        st = s.stats()
        assert st["dpr"] <= 1.5 and st["state"] == "ready"
        px = s.shot().getpixel((6, 6))
        assert (sum(px) > 600) is (surface == "day"), (
            px
        )  # the panel shows through: no colour of ours
        s.js("document.dispatchEvent(new CustomEvent('jarvis:theme', {detail: {}}))")
        assert s.errors == []
    finally:
        s.close()


def test_the_figure_draws_on_demand_and_stays_still_with_motion_off(
    browser: Any, stage_url: str
) -> None:
    s = _open(browser, stage_url)
    try:
        s.show("'casual'")
        s.page.wait_for_timeout(400)
        rest = s.js("window.__frames")
        s.page.wait_for_timeout(600)
        assert s.js("window.__frames") == rest  # no loop at rest
        s.js("b.stage.spin(true)")
        s.page.wait_for_timeout(700)
        assert s.js("window.__frames") > rest + 3 and s.stats()["yaw"] != 0
        s.js("b.stage.spin(false)")
        s.js("document.documentElement.dataset.motion = 'off'")
        s.js("b.stage.view('front')")
        s.js("b.stage.spin(true)")
        s.page.wait_for_timeout(500)
        assert s.stats()["yaw"] == 0  # Motion Off: "Turn around" stays still
    finally:
        s.close()


def test_avt15_signals_no_webgl2_is_said_before_anything_is_drawn(
    browser: Any, stage_url: str
) -> None:
    s = Stage(browser, stage_url, "fail=no-webgl2")
    try:
        assert s.js("b.engine.supported()") is False
        threw = s.js("(() => { try { b.mount(); return ''; } catch (e) { return e.message; } })()")
        assert threw == "This device cannot draw the 3D view."
        assert s.page.locator("#stage canvas").count() == 0
        assert not [r for r in s.requests if "mannequin" in r or "three" in r]
    finally:
        s.close()


@pytest.mark.parametrize("fail", ["asset", "lost"])
def test_avt15_signals_a_failed_file_or_a_lost_context_calls_on_lost_once(
    browser: Any, stage_url: str, fail: str
) -> None:
    s = _open(browser, stage_url, f"fail={fail}")
    try:
        got = s.js("(b.mount(), b.stage.show([b.L.figure(b.L.formal())], b.L.opts()))")
        assert "top" in got["drawn"]  # what is worn is known at once: the checklist never waits
        s.page.wait_for_function("() => window.__b.lost.length > 0", timeout=20000)
        s.page.wait_for_timeout(300)
        assert s.js("b.lost") == [fail] and s.stats()["state"] == "lost"
        s.js("b.stage.dispose()")
    finally:
        s.close()


def test_avt15_signals_a_missing_file_is_a_failed_file(browser: Any, stage_url: str) -> None:
    s = Stage(browser, stage_url)
    try:
        s.need_3d()
        s.page.route(
            "**/vendor/mannequin/m1/garments.glb", lambda r: r.fulfill(status=404, body="")
        )
        s.js("(b.mount(), b.stage.show([b.L.figure(b.L.formal())], b.L.opts()))")
        s.page.wait_for_function("() => window.__b.lost.length > 0", timeout=20000)
        assert s.js("b.lost") == ["asset"]
    finally:
        s.close()


def test_avt15_signals_a_first_frame_that_never_comes_is_lost_after_ten_seconds(
    browser: Any, stage_url: str
) -> None:
    s = _open(browser, stage_url, "fail=timeout", frozen=True)
    try:
        s.js("(b.mount(), b.stage.show([b.L.figure(b.L.formal())], b.L.opts()))")
        s.page.clock.run_for(9000)
        assert s.js("b.lost") == [] and s.stats()["state"] == "loading"
        s.page.clock.run_for(1100)
        assert s.js("b.lost") == ["timeout"]
    finally:
        s.close()


def test_one_stage_at_a_time_dispose_frees_it_and_a_second_mount_works(
    browser: Any, stage_url: str
) -> None:
    s = _open(browser, stage_url)
    try:
        s.show("'formal'")
        first = s.stats()["triangles"]
        s.js("b.stage.dispose()")
        assert s.stats()["state"] == "disposed"
        assert (
            s.page.locator("#stage canvas").count() == 0 and s.page.locator("#stage p").count() == 0
        )
        rest = s.js("window.__frames")
        s.js(
            "document.dispatchEvent(new CustomEvent('jarvis:theme', {detail: {}}))"
        )  # no listener left
        s.page.wait_for_timeout(300)
        assert s.js("window.__frames") == rest
        s.js("(b.stage = null, 0)")
        again = s.show("'formal'")
        assert "outer" in again["drawn"] and s.stats()["triangles"] == first
        assert s.stats()["state"] == "ready" and s.page.locator("#stage canvas").count() == 1
        assert (
            len([r for r in s.requests if r.endswith(".glb")]) == 2
        )  # the files are read once a page
        assert s.js("b.lost") == [] and s.errors == []
    finally:
        s.close()
