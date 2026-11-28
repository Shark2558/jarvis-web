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
# (tests/test_r81_e_coaches.py). The workout CSS is the console's own since the R8.1 join (console-coach.css).
# R8.1 I1 join (docs/plans/r8-integration/R81-I1-NOTES.md):
#   - each session's setup reaches live(..., {setup}): the wall or spotter, the boxing stance (optional), the agility
#     marks he taps, the partner's agreement (that session follows everyone and keeps his own tallies as `me`), the
#     walk test's typed course length, tai-chi's recording or his recorded form
#   - a recording comes back as tally.record and is PUT to /v1/coach/routines/{rid}, never posted as a result
#   - the body lines: drawn from pose points in the page (a stand-in `body-lines` feeds the pane's own reader), and no
#     point ever leaves the page: no request, no storage
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
USES = ("reps", "form", "band", "handstand", "partner-stretch", "space-check", "warm-up", "plank", "boxing", "agility",
        "walk-test", "tai-chi", "dance")  # fmt: skip
USECASES = {"usecases": [
    {"id": u, "row": 0, "release": "R8.1", "spot": "workout", "source": "phone", "tasks": ["quality"], "rate": 4,
     "health": u != "space-check", "keeps": u != "space-check", "module": ""} for u in USES
], "views": ["big", "line", "tip", "timer", "pacer", "targets", "checklist", "bar", "paused"]}  # fmt: skip
VOICE = """(() => { const said = []; window.__said = said;
  Object.defineProperty(window, 'speechSynthesis', { configurable: true, value: { speak: (u) => said.push(u.text), cancel: () => {} } });
  window.SpeechSynthesisUtterance = function (t) { this.text = t; }; })();"""
FAKES = """async () => { const V = window.JarvisVision, n = (s, r) => ({ n: ((s && s.n) || 0) + (r.ok ? 1 : 0), first: s ? s.first : r.at, last: r.at });
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
  ['boxing', 'agility', 'walk-test', 'partner-stretch', 'dance'].forEach((id) => V.use({ id, tasks: ['quality'], onResult: (r, s) => n(s, r),
    summary: (s) => ({ view: [{ kind: 'big', n: (s && s.n) || 0, word: 'count' }], tally: s ? { started_at: s.first, ended_at: s.last, n: s.n } : null }) }));
  const ROWS = Array.from({ length: 150 }, (_, i) => [10, 20, 30, 40, 50, 60, 70, 80, (i * 2) % 360]);
  V.use({ id: 'tai-chi', tasks: ['quality'], onResult: (r, s) => Object.assign(n(s, r), { setup: r.setup || null }), summary: (s) => ({
    view: [{ kind: 'timer', s: 3, word: 'recorded' }], tally: !s ? null : s.setup && s.setup.record
      ? { record: { rid: 'tai-chi-1', kind: 'tai-chi', chunks: [ROWS.slice(0, 100), ROWS.slice(100)] } }
      : { started_at: s.first, ended_at: s.last, routine: 1, steps: 3, done: 3, missed: 0, smooth: 80 } }) });
  const m = await import('/static/console-coach-workout.js');
  V.use({ id: 'body-lines', tasks: ['quality'], onResult: (r, s) => m.takeLines(Object.freeze(Object.assign({}, r, { track: 0,
    data: Object.freeze({ points: window.__points }), aspect: 0.5625 })), s), summary: () => ({ view: [], tally: null }) });
  window.__lives = [];
  const real = window.JarvisVision;
  window.JarvisVision = Object.freeze(Object.assign({}, real, { live: (ids, o) => { window.__lives.push(JSON.parse(JSON.stringify({ ids,
    uses: o.uses, target: o.target, setup: o.setup === undefined ? null : o.setup }))); return real.live(ids, o); } }));
  V.use({ id: 'space-check', tasks: ['quality'], onResult: (r, s) => n(s, r), summary: (s) => ({
    view: [{ kind: 'line', text: s && s.n >= 3 ? 'Clear: nothing in your space to trip on or hit.' : 'Looking around you\\u2026' }], tally: null }) });
  V.use({ id: 'warm-up', tasks: ['quality'], onResult: (r, s) => n(s, r), summary: (s) => ({ view: [
      { kind: 'big', n: 2, word: 'of 6 done' }, { kind: 'checklist', items: [{ text: 'Reach overhead: 5 of 5', ok: true },
      { text: 'Lift your knees: 10 of 10', ok: true }, { text: 'Squat: 2 of 5', ok: null }, { text: 'Bend to each side: 0 of 6', ok: null },
      { text: 'Hinge at the hips: 0 of 5', ok: null }, { text: 'Jumping jacks: 0 of 10', ok: null }] }], tally: null }) });
}"""


# a body for the body lines, front on: each x ends in ...07319 and each y in ...04271, so a coordinate anywhere in a
# request or in storage is found by its digits (R8.1 I1: no point ever leaves the page)
_BASE = {0: (0.50, 0.12), 11: (0.42, 0.25), 12: (0.58, 0.25), 13: (0.38, 0.38), 14: (0.62, 0.38), 15: (0.36, 0.50),
         16: (0.64, 0.50), 23: (0.45, 0.52), 24: (0.55, 0.52), 25: (0.44, 0.70), 26: (0.56, 0.70), 27: (0.44, 0.88),
         28: (0.56, 0.88), 31: (0.42, 0.92), 32: (0.58, 0.92)}  # fmt: skip
POINTS = [
    {"x": round(_BASE.get(i, (0.5, 0.12))[0] + 0.0007319, 7), "y": round(_BASE.get(i, (0.5, 0.12))[1] + 0.0004271, 7),
     "z": 0, "visibility": 0.9 if i in _BASE else 0.2}
    for i in range(33)
]  # fmt: skip
MARKS = ("07319", "04271")


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
        self.puts: list[tuple[str, dict[str, Any]]] = []
        self.routine: dict[str, Any] | None = None  # GET /v1/coach/routines/{rid}: 404 while None
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

        def routines(route: Any) -> None:
            rid = route.request.url.rsplit("/", 1)[-1]
            if route.request.method == "PUT":
                self.puts.append((rid, json.loads(route.request.post_data or "{}")))
                route.fulfill(status=200, json={"routine": {"kind": "tai-chi", "rows": 1}})
            elif self.routine is None:
                route.fulfill(status=404, json={"error": "not_found", "detail": "No routine yet."})
            else:
                route.fulfill(status=200, json={"routine": self.routine})

        self.page.route("**/v1/coach/routines/*", routines)

    def workout(self) -> None:
        self.c.open()
        assert self.page.evaluate(  # the R8.1 join: the pane's places are the console's own CSS now
            "() => [...document.styleSheets].some((s) => { try { return [...s.cssRules].some((r) => (r.selectorText || '').includes('.r8-wo .r8-nums')); } catch (e) { return false; } })"
        )
        self.page.evaluate(f"window.__points = {json.dumps(POINTS)}")
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


def _lives(r: Rig) -> list[dict[str, Any]]:
    return list(r.page.evaluate("window.__lives"))


def _stop(r: Rig) -> None:
    r.page.locator("#p-camera").get_by_role("button", name="Stop", exact=True).click()
    until(r.page, lambda: not r.live(), "the stop")


def test_each_session_passes_its_setup_through_live(
    browser: Any, server_url: str, token: str
) -> None:
    r = rig(browser, server_url, token)
    try:
        r.workout()
        lead = r.page.locator("#p-camera")
        lead.locator("label.seg-opt", has_text="Dynamic").click()
        r.start("Handstand")
        lead.get_by_role("button", name="A spotter with me").click()
        until(r.page, lambda: r.live() and len(_lives(r)) == 1, "the handstand look")
        assert _lives(r)[0]["setup"] == {"support": "spotter"} and _lives(r)[0]["uses"][0] == "handstand"
        _stop(r)
        r.start("Shadowboxing")
        until(r.page, lambda: "Which foot is in front" in r.text(), "the stance question")
        assert r.live() is False
        lead.get_by_role("button", name="Right foot forward").click()
        until(r.page, lambda: r.live() and len(_lives(r)) == 2, "the boxing look")
        assert _lives(r)[1]["setup"] == {"stance": "southpaw"}
        _stop(r)
        r.start("Shadowboxing")
        lead.get_by_role("button", name="Skip").click()
        until(r.page, lambda: r.live() and len(_lives(r)) == 3, "the boxing look, no stance")
        assert _lives(r)[2]["setup"] is None
        _stop(r)
        r.start("Agility")
        video = lead.locator(".r8-markpick video.r8-anchorpick")
        video.wait_for()
        done = lead.get_by_role("button", name="Done: start")
        assert done.is_disabled() and len(_lives(r)) == 3  # two marks at least, and nothing looks yet
        box = video.bounding_box()
        assert box is not None
        video.click(position={"x": box["width"] * 0.25, "y": box["height"] * 0.5})
        video.click(position={"x": box["width"] * 0.75, "y": box["height"] * 0.5})
        until(r.page, lambda: "2 marks" in r.text(), "two marks")
        done.click()
        until(r.page, lambda: len(_lives(r)) == 4, "the agility look")
        marks = _lives(r)[3]["setup"]["marks"]
        assert len(marks) == 2 and all(0 <= m["x"] <= 1 and 0 <= m["y"] <= 1 for m in marks)
        assert abs(marks[0]["x"] - 0.25) < 0.05 and abs(marks[1]["x"] - 0.75) < 0.05
        assert lead.locator("video").count() == 0  # the picture shows only while he marks
        _stop(r)
        lead.locator("label.seg-opt", has_text="More").click()
        r.start("Six-minute walk")
        field = lead.get_by_label("Course length in metres (1 to 100)")
        field.fill("0")
        lead.get_by_role("button", name="Start the walk").click()
        until(r.page, lambda: "Type a length from 1 to 100 metres." in r.text(), "the refusal")
        assert r.live() is False
        field.fill("25")
        lead.get_by_role("button", name="Start the walk").click()
        until(r.page, lambda: r.live() and len(_lives(r)) == 5, "the walk look")
        assert _lives(r)[4]["setup"] == {"course_m": 25}
        _stop(r)
        assert r.c.errors == [] and r.c.csp_violations() == []
    finally:
        r.c.close()


def test_a_partner_stretch_follows_everyone_and_keeps_only_his_own_as_me(
    browser: Any, server_url: str, token: str
) -> None:
    r = rig(browser, server_url, token)
    try:
        r.target = {"kind": "me", "person": None}
        r.workout()
        r.page.evaluate("() => document.dispatchEvent(new Event('jarvis:ready'))")
        until(r.page, lambda: "Only you are followed." in r.text(), "the promise")
        r.page.locator("#p-camera label.seg-opt", has_text="More").click()
        r.start("Partner stretch")
        before = int(time.time())
        r.page.locator("#p-camera").get_by_role("button", name="My partner agrees: start").click()
        until(r.page, lambda: r.live() and len(_lives(r)) == 1, "the look")
        one = _lives(r)[0]
        assert one["target"] == {"kind": "all"} and "body-lines" not in one["uses"]
        assert one["setup"]["consent"] is True and abs(one["setup"]["consent_at"] - before) <= 2
        _stop(r)
        until(r.page, lambda: len(r.posts) == 1, "his tally")
        assert r.posts[0]["use"] == "partner-stretch" and r.posts[0]["who"] == "me"
    finally:
        r.c.close()


def test_a_recording_is_put_to_routines_and_a_recorded_form_is_followed(
    browser: Any, server_url: str, token: str
) -> None:
    r = rig(browser, server_url, token)
    try:
        r.workout()
        lead = r.page.locator("#p-camera")
        lead.locator("label.seg-opt", has_text="Flow").click()
        r.start("Tai chi")
        until(r.page, lambda: "First record your form" in r.text(), "the record line")
        assert "A recording stops at 5 minutes." in r.text() and r.live() is False
        lead.get_by_role("button", name="Record it now").click()
        until(r.page, lambda: r.live() and len(_lives(r)) == 1, "the recording")
        assert _lives(r)[0]["setup"] == {"routine": 1, "record": True}
        _stop(r)
        until(r.page, lambda: len(r.puts) == 1, "the PUT")
        rid, body = r.puts[0]
        assert rid == "tai-chi-1" and body["kind"] == "tai-chi" and len(body["angles"]) == 150
        assert set(body) == {"kind", "angles"} and r.posts == []  # never posted as a result
        assert "Your recording is kept (joint angles only)." in r.text()
        r.routine = {"kind": "tai-chi", "angles": body["angles"]}
        r.start("Tai chi")
        until(r.page, lambda: "Follow the form you recorded" in r.text(), "the follow line")
        lead.get_by_role("button", name="Follow my recording").click()
        until(r.page, lambda: r.live() and len(_lives(r)) == 2, "the follow look")
        setup = _lives(r)[1]["setup"]
        assert setup["routine"] == 1 and [len(c) for c in setup["chunks"]] == [100, 50]
        assert [row for c in setup["chunks"] for row in c] == body["angles"]
        _stop(r)
        until(r.page, lambda: len(r.posts) == 1, "the follow tally")
        assert r.posts[0]["use"] == "tai-chi" and "record" not in r.posts[0]["tally"] and len(r.puts) == 1
    finally:
        r.c.close()


def test_the_body_lines_are_drawn_here_and_no_point_leaves_the_page(
    browser: Any, server_url: str, token: str
) -> None:
    r = rig(browser, server_url, token)
    try:
        r.workout()
        r.page.evaluate("""() => { window.__sent = [];
          const keep = (k) => (...a) => { window.__sent.push(k + ' ' + JSON.stringify(a).slice(0, 4000)); };
          navigator.sendBeacon = keep('beacon'); window.WebSocket = function (u) { keep('ws')(u); throw new Error('no'); }; }""")
        r.start("Squats")
        fig = r.page.locator("#p-camera .r8-view.figs svg.r8-body")
        until(r.page, lambda: fig.count() == 1 and fig.locator("path.bone").count() == 1, "the body lines")
        assert fig.locator("circle.joint").count() == 12 and fig.locator("circle.head").count() == 1
        assert "BODY LINES ONLY" in r.text().upper() and "the picture stays on this phone" in r.text()
        assert _lives(r)[0]["uses"] == ["reps", "form", "body-lines"]
        r.page.wait_for_timeout(1500)  # several looks' worth of frames
        _stop(r)
        until(r.page, lambda: len(r.posts) == 2, "the tallies")
        assert fig.count() == 0 and r.page.locator("#p-camera svg.r8-body *").count() == 0
        sent = [b.decode("utf-8", "replace") for _, _, b in r.reqs] + list(r.page.evaluate("window.__sent"))
        stored = r.page.evaluate(
            "() => JSON.stringify([Object.entries(localStorage), Object.entries(sessionStorage)])"
        )
        for mark in MARKS:
            assert not any(mark in s for s in sent), mark
            assert mark not in stored, mark
        assert not any('"points"' in s or '"visibility"' in s for s in sent)
        assert r.page.evaluate("window.__sent") == []
        pure = r.page.evaluate(
            """async (pts) => { const m = await import('/static/console-coach-workout.js');
              const a = m.bodyLines(pts, 0.5625, true), b = m.bodyLines(pts, 1, false), none = m.bodyLines(pts.slice(1), 1, false);
              return { w: a.w, bones: a.bones.length, joints: a.joints.length, mx: a.joints[0][0], x: b.joints[0][0], none }; }""",
            POINTS,
        )
        assert pure == {"w": 563, "bones": 14, "joints": 12, "mx": round((1 - POINTS[11]["x"]) * 562.5), "x": round(POINTS[11]["x"] * 1000), "none": None}  # fmt: skip
    finally:
        r.c.close()


SHOTS = (
    ("picker", PHONE),
    ("session", PHONE),
    ("paused", PHONE),
    ("warm-up", PHONE),
    ("course", PHONE),
    ("routine", PHONE),
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
        if state == "session":
            until(r.page, lambda: r.page.locator("#p-camera .r8-view.figs").count() == 1, "the body lines")
        if state == "course":
            r.page.locator("#p-camera label.seg-opt", has_text="More").click()
            r.start("Six-minute walk")
            until(r.page, lambda: "How long is your walking course" in r.text(), "the course")
        if state == "routine":
            r.page.locator("#p-camera label.seg-opt", has_text="Flow").click()
            r.start("Tai chi")
            until(r.page, lambda: "First record your form" in r.text(), "the record line")
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
