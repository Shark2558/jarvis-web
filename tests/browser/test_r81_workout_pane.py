# tests/browser/test_r81_workout_pane.py -- R8.1 builder E (docs/plans/r8-vision.md 2.2, 4.3, 6; D6; the approved
# mockup workout-phone.html) in a real Chromium at 390 x 844 with its fake camera:
#   - Camera -> Workout opens on the picker (the promise for the tracking target, the two setup steps, the kinds and
#     the sessions, "Stop if anything hurts.") and starts nothing
#   - a session starts only from a tap, fills the phone, lays the view out big, says counts and tips in the browser's
#     voice, pauses with the camera off and the counts kept, resumes from a tap, and on Stop keeps each use case's
#     tally only (no picture leaves)
#   - a handstand needs "a wall" or "a spotter", a partner stretch the partner's agreement, before the camera starts
#   - the band's anchor: one tap on the picture; the area's brightness print and its "moved" rule (pure)
#   - the setup checks look briefly with space-check and keep nothing; a switch read as off, or a named person,
#     starts nothing
#   - the visual gate (ui_checks.DOM_CHECKS_JS) on the picker and a session, 390 x 844 and 1920 x 1080, Night and Day;
#     with JARVIS_SHOTS_DIR set, each is saved there as a PNG (docs/plans/r8-integration/screens/e/)
# The use cases here are stand-ins on `quality` (this server has no pose model); the real ones are proved in Node
# (tests/test_r81_e_coaches.py). The workout CSS is staged in tests/fixtures/r8/workout_pane.css (C's file takes it
# at the join) and injected until the console carries it.
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
CSS = (Path(__file__).resolve().parents[1] / "fixtures" / "r8" / "workout_pane.css").read_text(
    encoding="utf-8"
)
USES = ("reps", "form", "band", "handstand", "partner-stretch", "space-check", "warm-up", "plank")
USECASES = {"usecases": [
    {"id": u, "row": 0, "release": "R8.1", "spot": "workout", "source": "phone", "tasks": ["quality"], "rate": 4,
     "health": u != "space-check", "keeps": u != "space-check", "module": ""} for u in USES
], "views": ["big", "line", "tip", "timer", "pacer", "targets", "checklist", "bar", "paused"]}  # fmt: skip
VOICE = """(() => { const said = []; window.__said = said;
  Object.defineProperty(window, 'speechSynthesis', { configurable: true, value: { speak: (u) => said.push(u.text), cancel: () => {} } });
  window.SpeechSynthesisUtterance = function (t) { this.text = t; }; })();"""
FAKES = """() => { const V = window.JarvisVision, n = (s, r) => ({ n: ((s && s.n) || 0) + (r.ok ? 1 : 0), first: s ? s.first : r.at, last: r.at });
  V.use({ id: 'reps', tasks: ['quality'], onResult: (r, s) => n(s, r), summary: (s) => ({ view: [
      { kind: 'big', n: (s && s.n) || 0, word: 'reps' }, { kind: 'timer', s: 72, word: 'this set' }, { kind: 'line', text: 'Set 1' },
      { kind: 'line', text: 'Tempo: down 2.0 s, up 1.0 s' }, { kind: 'line', text: 'Squats' }, { kind: 'line', text: 'Stop if anything hurts.' }],
    tally: s ? { started_at: s.first, ended_at: s.last, exercise: 'squat', sets: 1, reps: s.n, down_s: 2, up_s: 1 } : null }) });
  V.use({ id: 'form', tasks: ['quality'], onResult: (r, s) => n(s, r), summary: (s) => ({
    view: s && s.n >= 2 ? [{ kind: 'tip', text: 'Keep your chest up.' }, { kind: 'bar', n: 64, word: 'Clean reps' }] : [{ kind: 'line', text: 'Good rep.' }],
    tally: s ? { started_at: s.first, ended_at: s.last, exercise: 'squat', reps: 2, clean: 1, tips: 1 } : null }) });
  V.use({ id: 'band', tasks: ['quality'], onResult: (r, s) => n(s, r), summary: (s) => ({ view: [{ kind: 'big', n: (s && s.n) || 0, word: 'reps' }],
    tally: s ? { started_at: s.first, ended_at: s.last, reps: s.n, prompts: 0 } : null }) });
  V.use({ id: 'handstand', tasks: ['quality'], onResult: (r, s) => n(s, r), summary: () => ({ view: [{ kind: 'timer', s: 5, word: 'hold' }], tally: null }) });
  V.use({ id: 'space-check', tasks: ['quality'], onResult: (r, s) => n(s, r), summary: (s) => ({
    view: [{ kind: 'line', text: s && s.n >= 3 ? 'Clear: nothing in your space to trip on or hit.' : 'Looking around you\\u2026' }], tally: null }) });
  V.use({ id: 'warm-up', tasks: ['quality'], onResult: (r, s) => n(s, r), summary: (s) => ({ view: [
      { kind: 'big', n: 2, word: 'of 6 done' }, { kind: 'checklist', items: [{ text: 'Reach overhead: 5 of 5', ok: true },
      { text: 'Lift your knees: 10 of 10', ok: true }, { text: 'Squat: 2 of 5', ok: null }, { text: 'Bend to each side: 0 of 6', ok: null },
      { text: 'Hinge at the hips: 0 of 5', ok: null }, { text: 'Jumping jacks: 0 of 10', ok: null }] }], tally: null }) });
}"""


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
        self.spots: dict[str, Any] = {"spots": {"rev": 1, "all_off": False, "rooms": [{"id": "hall", "label": "Hall", "never": False}],
                                                "cameras": [{"id": "wo_phone", "kind": "device", "source": "phone", "label": "Workout phone",
                                                             "spot": "workout", "room": "hall", "on": True}]}}  # fmt: skip
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
        def fulfil(body: Callable[[], Any]) -> Callable[[Any], None]:
            return lambda route: route.fulfill(status=200, json=body())

        def results(route: Any) -> None:
            if route.request.method == "POST":
                self.posts.append(json.loads(route.request.post_data or "{}"))
                route.fulfill(status=201, json={"kept": {"id": "ct_000000000001", "who": "me"}})
            else:
                route.fulfill(status=200, json={"sealed": True, "keep_days": 90, "results": []})

        self.page.route("**/v1/coach/usecases", fulfil(lambda: USECASES))
        self.page.route("**/v1/coach/target", fulfil(lambda: {"target": self.target}))
        self.page.route("**/v1/coach/results", results)
        self.page.route("**/v1/camera/spots", fulfil(lambda: self.spots))

    def workout(self) -> None:
        self.c.open()
        if not self.page.evaluate(
            "() => [...document.styleSheets].some((s) => { try { return [...s.cssRules].some((r) => (r.selectorText || '').includes('.r8-wo .r8-nums')); } catch (e) { return false; } })"
        ):
            self.page.add_style_tag(content=CSS)
        self.c.open_panel("camera")
        self.page.locator("#p-camera").get_by_role("tab", name="Workout").click()
        self.page.locator("#p-camera .r8-wo .r8-rows .hp-row").first.wait_for()
        self.page.evaluate(FAKES)

    def start(self, name: str) -> None:
        self.page.locator("#p-camera").get_by_role("button", name="Start " + name).click()

    def live(self) -> bool:
        return bool(self.page.evaluate("window.JarvisCamera.live()"))

    def text(self) -> str:
        return str(self.page.locator("#p-camera .r8-wo").inner_text())


def until(page: Any, check: Callable[[], bool], what: str, timeout_s: float = 30.0) -> None:
    end = time.monotonic() + timeout_s
    while time.monotonic() < end:
        if check():
            return
        page.wait_for_timeout(100)
    raise AssertionError(f"timed out waiting for {what}")


def rig(browser: Any, url: str, token: str, viewport: dict[str, int] = PHONE) -> Rig:
    c = Console(browser, url, token, viewport)
    c.page.add_init_script(VOICE)
    install_mocks(c.page)
    r = Rig(c)
    r.routes()
    return r


def test_the_picker_shows_the_steps_and_sessions_and_starts_nothing(
    browser: Any, server_url: str, token: str
) -> None:
    r = rig(browser, server_url, token)
    try:
        r.workout()
        until(r.page, lambda: "Everyone in view is followed" in r.text(), "the promise")
        text = r.text()
        for words in ("BEFORE YOUR FIRST SESSION", "Place the phone".upper(), "Clear the space".upper(), "Warm-up", "Squats",
                      "Push-ups", "Plank", "Band work", "Stop if anything hurts.", "only counts and times are kept"):  # fmt: skip
            assert words.lower() in text.lower(), words
        r.page.locator("#p-camera label.seg-opt", has_text="Dynamic").click()
        assert "Handstand" in r.text() and "Squats" not in r.text()
        assert r.live() is False and r.posts == []
        assert r.c.errors == [] and r.c.csp_violations() == []
    finally:
        r.c.close()


def test_a_session_fills_the_phone_pauses_resumes_and_keeps_only_tallies(
    browser: Any, server_url: str, token: str
) -> None:
    r = rig(browser, server_url, token)
    try:
        r.workout()
        r.start("Squats")
        until(
            r.page,
            lambda: r.live() and r.page.locator("#p-camera .r8-num.reps").count() == 1,
            "the session",
        )
        assert r.page.evaluate("document.getElementById('p-camera').classList.contains('r8-full')")
        assert r.page.locator("#p-camera .r8-wo .r8-picker").is_hidden()
        until(r.page, lambda: "Keep your chest up." in r.text(), "the form tip")
        tile = r.page.locator("#p-camera .r8-num.reps b")
        until(r.page, lambda: int(tile.inner_text() or 0) >= 3, "three counts")
        until(r.page, lambda: len(r.page.evaluate("window.__said")) >= 2, "the voice")
        said = r.page.evaluate("window.__said")
        assert "Keep your chest up." in said and any(s.isdigit() for s in said)
        r.page.locator("#p-camera").get_by_role("button", name="Pause").click()
        until(r.page, lambda: not r.live(), "the camera off")
        before = int(tile.inner_text())
        assert (
            "Camera off. Counting is paused." in r.text()
            and "Your counts so far are kept." in r.text()
        )
        r.page.locator("#p-camera").get_by_role("button", name="Resume").click()
        until(
            r.page, lambda: r.live() and int(tile.inner_text() or 0) > before, "the count going on"
        )
        r.page.locator("#p-camera").get_by_role("button", name="Stop", exact=True).click()
        until(r.page, lambda: len(r.posts) == 2, "both tallies")
        until(r.page, lambda: not r.live(), "the camera to stop")
        uses = sorted(p["use"] for p in r.posts)
        assert uses == ["form", "reps"] and all(
            p["session"].startswith("cs_") and p["who"] == "me" for p in r.posts
        )
        reps = next(p for p in r.posts if p["use"] == "reps")
        assert set(reps["tally"]) == {
            "started_at",
            "ended_at",
            "exercise",
            "sets",
            "reps",
            "down_s",
            "up_s",
        }
        assert reps["tally"]["reps"] > before
        assert r.pictures() == [] and "The session ended. Its counts are kept." in r.text()
        assert not r.page.evaluate(
            "document.getElementById('p-camera').classList.contains('r8-full')"
        )
        assert r.c.errors == [] and r.c.csp_violations() == []
    finally:
        r.c.close()


def test_a_handstand_or_a_partner_stretch_needs_its_line_first(
    browser: Any, server_url: str, token: str
) -> None:
    r = rig(browser, server_url, token)
    try:
        r.workout()
        r.page.locator("#p-camera label.seg-opt", has_text="Dynamic").click()
        r.start("Handstand")
        until(
            r.page,
            lambda: "Is there a wall behind you or a spotter with you?" in r.text(),
            "the question",
        )
        r.page.wait_for_timeout(500)
        assert r.live() is False  # nothing starts until he picks one
        r.page.locator("#p-camera").get_by_role("button", name="A wall behind me").click()
        until(
            r.page,
            lambda: r.live() and r.page.locator("#p-camera .r8-num").count() == 1,
            "the session",
        )
        r.page.locator("#p-camera").get_by_role("button", name="Stop", exact=True).click()
        until(r.page, lambda: not r.live(), "the stop")
        assert r.posts == [] and "Nothing to keep." in r.text()
        r.page.locator("#p-camera label.seg-opt", has_text="More").click()
        r.start("Partner stretch")
        until(
            r.page, lambda: "Your partner agrees to this session." in r.text(), "the partner line"
        )
        assert r.live() is False
    finally:
        r.c.close()


def test_the_band_anchor_is_one_tap_and_its_print_says_when_it_moved(
    browser: Any, server_url: str, token: str
) -> None:
    r = rig(browser, server_url, token)
    try:
        r.workout()
        r.start("Band work")
        until(r.page, lambda: "Tap the band\u2019s anchor on the picture." in r.text(), "the ask")
        video = r.page.locator("#p-camera video.r8-anchorpick")
        video.wait_for()
        video.click(position={"x": 40, "y": 40})
        until(
            r.page,
            lambda: (
                "Anchor marked." in r.text()
                and r.page.locator("#p-camera .r8-num.reps").count() == 1
            ),
            "the session",
        )
        assert (
            r.page.locator("#p-camera video").count() == 0
        )  # the picture shows only for that one tap
        out = r.page.evaluate("""async () => { const m = await import('/static/console-coach-workout.js');
          const img = (f) => { const w = 8, h = 8, d = new Uint8ClampedArray(w * h * 4); for (let i = 0; i < w * h; i += 1) { const v = f(i % w, Math.floor(i / w)); d.set([v, v, v, 255], i * 4); } return { data: d, width: w, height: h }; };
          const a = m.fingerprint(img((x, y) => (x + y) * 12)), same = m.fingerprint(img((x, y) => (x + y) * 12 + 3));
          const covered = m.fingerprint(img(() => 10)), shifted = m.fingerprint(img((x, y) => (14 - x - y) * 12));
          return { n: a.length, same: m.anchorMoved(a, same), covered: m.anchorMoved(a, covered), shifted: m.anchorMoved(a, shifted), none: m.anchorMoved(a, null) }; }""")
        assert out == {"n": 16, "same": False, "covered": True, "shifted": True, "none": True}
        r.page.locator("#p-camera").get_by_role("button", name="Stop", exact=True).click()
        until(r.page, lambda: len(r.posts) == 1, "the band's tally")
        assert r.posts[0]["use"] == "band" and set(r.posts[0]["tally"]) == {
            "started_at",
            "ended_at",
            "reps",
            "prompts",
        }
        assert r.pictures() == []
    finally:
        r.c.close()


def test_the_setup_checks_keep_nothing_and_switches_or_a_name_start_nothing(
    browser: Any, server_url: str, token: str
) -> None:
    r = rig(browser, server_url, token)
    try:
        r.workout()
        r.page.locator("#p-camera").get_by_role("button", name="Check the space").click()
        until(
            r.page,
            lambda: "Clear: nothing in your space to trip on or hit." in r.text(),
            "the verdict",
            20,
        )
        until(r.page, lambda: not r.live(), "the camera off after the check")
        assert r.posts == []
        r.spots["spots"]["all_off"] = True
        r.start("Squats")
        until(r.page, lambda: "switched off in Cameras" in r.text(), "the refusal")
        assert r.live() is False and r.posts == []
        r.spots["spots"]["all_off"] = False
        r.target = {"kind": "person", "person": "fp_0123456789ab"}
        r.page.evaluate("() => document.dispatchEvent(new Event('jarvis:ready'))")
        until(r.page, lambda: "One person is followed." in r.text(), "the promise")
        r.start("Squats")
        until(r.page, lambda: "needs the home camera" in r.text(), "the D6 rule")
        assert r.live() is False
    finally:
        r.c.close()


SHOTS = (
    ("picker", PHONE),
    ("session", PHONE),
    ("paused", PHONE),
    ("warm-up", PHONE),
    ("picker", WIDE),
)


@pytest.mark.parametrize("surface", ["night", "day"])
@pytest.mark.parametrize(
    "shot", range(len(SHOTS)), ids=[f"{s}-{'phone' if v is PHONE else 'wide'}" for s, v in SHOTS]
)
def test_the_workout_pane_passes_the_visual_gate(
    browser: Any, server_url: str, token: str, shot: int, surface: str
) -> None:
    state, vp = SHOTS[shot]
    size = "phone" if vp is PHONE else "wide"
    r = rig(browser, server_url, token, vp)
    try:
        r.workout()
        if surface == "day":
            r.c.choose_day()
        if state in ("session", "paused"):
            r.start("Squats")
            until(r.page, lambda: "Keep your chest up." in r.text(), "the tip")
            if state == "paused":
                r.page.locator("#p-camera").get_by_role("button", name="Pause").click()
                until(r.page, lambda: "Counting is paused" in r.text(), "the pause")
        if state == "warm-up":
            r.start("Warm-up")
            until(r.page, lambda: "Reach overhead" in r.text(), "the checklist")
        r.page.evaluate(FINISH_ANIMATIONS_JS)
        sel = "#p-camera .hp-pane:not([hidden])"
        _assert_clean(
            r.page.evaluate(DOM_CHECKS_JS, sel),
            r.page.evaluate(NAMELESS_JS, sel),
            r.page.evaluate(WRAP_JS, sel),
            size,
            f"workout {state} {size} {surface}",
        )
        shots = os.environ.get("JARVIS_SHOTS_DIR", "")
        if shots:
            Path(shots).mkdir(parents=True, exist_ok=True)
            r.page.locator("#p-camera .pbody").evaluate("(el) => { el.scrollTop = 0; }")
            r.page.screenshot(path=str(Path(shots) / f"workout-{state}-{size}-{surface}.png"))
        assert r.c.errors == [] and r.c.csp_violations() == []
    finally:
        r.c.close()
