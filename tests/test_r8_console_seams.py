# tests/test_r8_console_seams.py -- R8 I0 seams, the console's half (docs/plans/r8-vision.md 4.2,
# 4.3, 4.9, section 7.1 S2, S3, S16, S17, S19, S20), by behaviour where it runs:
#   - S2 the port core: a Result reaches a use case only during a live() that names it; run()
#     and stream() tell none; live() needs a camera a tap started and stops when it stops; stream
#     honours opts.rate; tally() is frozen plain data with only the fixed widget kinds; reset();
#     the owner's D6: everyone in view by default, one body at a time (a state per body); "me"
#     is a lone body on this device (no face is matched here); a person only by their fp_ id
#   - S3 the R8 task module: `hands` v1, `digits` v1 and `pose` v2 are registered before the
#     seal and say "not installed" until builder A's and D's bodies and the model files arrive
# The Node scenarios are in tests/fixtures/r7/b_dom.js ("driver", "r8tasks").
from __future__ import annotations

from typing import Any

from r7_fakes_b import STATIC, run_dom

R8_MODULE = "console-vision-r8.js"


def _driver(*steps: dict[str, Any], **over: Any) -> dict[str, Any]:
    return run_dom("driver", steps=list(steps), **over)


def use(uid: str, *tasks: str) -> dict[str, Any]:
    return {"op": "use", "id": uid, "tasks": list(tasks)}


def live(tasks: list[str], uses: list[str], **opts: Any) -> dict[str, Any]:
    return {"op": "live", "tasks": tasks, "uses": uses, **opts}


def wait(ms: int) -> dict[str, Any]:
    return {"op": "wait", "ms": ms}


# ---- S2 · results only to the use cases a live look names ----------------------------------------
def test_results_reach_only_the_use_cases_a_live_look_names() -> None:
    out = _driver(
        use("named", "probe"),
        use("other", "probe"),
        live(["probe"], ["named"]),
        wait(300),
        {"op": "end"},
    )
    assert out["got"]["named"] >= 2 and out["got"]["other"] == 0
    assert out["errors"] == []


def test_run_and_stream_tell_no_use_case() -> None:
    out = _driver(
        use("named", "probe"),
        {"op": "run", "task": "probe"},
        {"op": "stream", "task": "probe"},
        wait(250),
        {"op": "stopstream"},
    )
    assert out["ran"] >= 1 and out["streamed"] >= 2
    assert out["got"]["named"] == 0  # the Look tab's results reach no use case


def test_live_needs_a_camera_a_tap_started() -> None:
    out = _driver(use("named", "probe"), live(["probe"], ["named"]), wait(200), camera=False)
    assert out["errors"] == ["The camera starts only from a tap."]
    assert out["frames"] == 0 and out["got"]["named"] == 0


def test_a_look_ends_when_the_camera_stops() -> None:
    out = _driver(
        use("named", "probe"),
        live(["probe"], ["named"]),
        wait(150),
        {"op": "camera", "on": False},
        {"op": "mark"},
        wait(300),
    )
    assert out["errors"] == ["The camera was stopped."]
    assert out["got"]["named"] == out["marked"]["named"]  # nothing after the camera stopped


def test_unknown_tasks_or_uses_start_nothing() -> None:
    out = _driver(use("named", "probe"), live(["nope"], ["named"]), live(["probe"], ["nobody"]))
    assert out["errors"] == ["That vision task is not installed."] * 2 and out["frames"] == 0


def test_stream_honours_opts_rate_never_above_the_tasks_own() -> None:
    slow = _driver(use("named", "probe"), live(["probe"], ["named"], rate=2),
                   wait(700), {"op": "end"})  # fmt: skip
    fast = _driver(use("named", "probe"), live(["probe"], ["named"], rate=99),
                   wait(700), {"op": "end"})  # fmt: skip
    assert 1 <= slow["got"]["named"] <= 2  # 2 a second: the first frame, then one 500 ms later
    assert fast["got"]["named"] >= 5  # capped at the task's 15 a second, never 99


def test_tally_is_frozen_plain_data_with_the_fixed_widgets_only() -> None:
    out = _driver(
        use("named", "probe"),
        live(["probe"], ["named"]),
        wait(200),
        {"op": "end"},
        {"op": "tally", "id": "named"},
        {"op": "tally", "id": "nobody"},
    )
    mine, nobody = out["tallies"]
    assert [w["kind"] for w in mine["view"]] == ["big", "paused"]  # "evil" and a function dropped
    assert mine["tally"]["count"] == out["got"]["named"] and mine["frozen"] is True
    assert nobody == {"view": [], "tally": None, "who": "", "frozen": True}


def test_reset_clears_a_use_cases_state() -> None:
    out = _driver(
        use("named", "probe"),
        live(["probe"], ["named"]),
        wait(200),
        {"op": "end"},
        {"op": "reset", "id": "named"},
        {"op": "tally", "id": "named"},
    )
    assert out["resets"] == [True] and out["tallies"][0]["tally"]["count"] == 0


# ---- S2 · the tracking target (the owner's D6: everyone by default, "me", or one person) ---------
FP = "fp_0123456789ab"


def test_everyone_in_view_is_told_one_body_at_a_time() -> None:
    out = _driver(
        use("coach", "pose"),
        {"op": "bodies", "value": ["", ""]},
        live(["pose"], ["coach"]),
        wait(200),
        {"op": "tracks", "id": "coach"},
        {"op": "end"},
        {"op": "tally", "id": "coach", "track": 1},
    )
    assert out["tracks"] == [[{"track": 0, "who": ""}, {"track": 1, "who": ""}]]
    assert out["seen"] == out["tracks"]  # who is in view, as the look sees it
    assert sorted(out["whos"]["coach"]) == ["0:", "1:"]
    assert out["tallies"][0]["tally"]["count"] >= 2 and out["tallies"][0]["who"] == ""


def test_a_lone_body_on_this_device_is_me_and_never_a_name() -> None:
    out = _driver(use("coach", "pose"), live(["pose"], ["coach"]), wait(150),
                  {"op": "tracks", "id": "coach"}, {"op": "end"})  # fmt: skip
    assert out["tracks"] == [[{"track": 0, "who": "me"}]]


def test_track_me_tells_only_my_body() -> None:
    out = _driver(
        use("coach", "pose"),
        {"op": "bodies", "value": ["", ""]},
        live(["pose"], ["coach"], target={"kind": "me"}),
        wait(200),
        {"op": "mark"},
        {"op": "bodies", "value": [""]},
        wait(200),
        {"op": "end"},
    )
    assert out["marked"]["coach"] == 0  # two in view and no face matched here: nobody is "me"
    assert out["got"]["coach"] >= 2 and out["whos"]["coach"] == ["0:me"]


def test_track_a_person_tells_only_that_person() -> None:
    out = _driver(
        use("coach", "pose"),
        {"op": "bodies", "value": [FP, "me", ""]},
        live(["pose"], ["coach"], target={"kind": "person", "person": FP}),
        wait(200),
        {"op": "end"},
    )
    assert out["whos"]["coach"] == [f"0:{FP}"]
    nobody = _driver(
        use("coach", "pose"),
        live(["pose"], ["coach"], target={"kind": "person", "person": "Shruti"}),
    )
    assert nobody["errors"] == ["That vision task is not installed."] and nobody["frames"] == 0


def test_things_in_view_reach_every_bodys_session() -> None:
    out = _driver(
        use("coach", "pose", "probe"),
        {"op": "bodies", "value": ["", ""]},
        live(["pose", "probe"], ["coach"]),
        wait(250),
        {"op": "end"},
        {"op": "tally", "id": "coach", "track": 0},
        {"op": "tally", "id": "coach", "track": 1},
    )
    first, second = (t["tally"]["count"] for t in out["tallies"])
    assert first > len([w for w in out["whos"]["coach"] if w.startswith("0:")])  # pose and probe


# ---- S3 · the R8 task module ---------------------------------------------------------------------
def test_hands_and_pose_v2_are_registered_and_say_not_installed() -> None:
    out = run_dom("r8tasks")
    tasks = {t["id"]: t for t in out["tasks"]}
    assert tasks["pose"]["v"] == 2 and tasks["hands"]["v"] == 1 and tasks["digits"]["v"] == 1
    assert out["sealed"] is True
    assert out["errors"] == {
        "pose": "not installed",
        "hands": "not installed",
        "digits": "not installed",
    }
    broken = run_dom("r8tasks", fetchStatus=500)
    no_load = "The vision tools could not load. Check the connection and try again."
    assert broken["errors"] == {"pose": no_load, "hands": no_load, "digits": "not installed"}


def test_the_r8_task_module_holds_bodies_only() -> None:
    js = (STATIC / R8_MODULE).read_text(encoding="utf-8")
    assert js.isascii() and len(js.splitlines()) <= 800
    for name in (
        "loadPose",
        "runPose",
        "loadHands",
        "runHands",
        "loadDigits",
        "runDigits",
        "unload",
    ):
        assert f"export function {name}(" in js or f"export async function {name}(" in js, name
    for bad in ("fetch(", "JarvisCamera", "getUserMedia", "JarvisVision", "localStorage",
                "innerHTML", "XMLHttpRequest", "sendBeacon", "WebSocket", "import("):  # fmt: skip
        assert bad not in js, bad


# ---- S20 · the coaches' shared geometry (pure), on S23's synthetic bodies ------------------------
def _geom(call: str, *args: Any) -> Any:
    from r8_fakes import run_node

    return run_node("console-coach-geom.js", call, *args)


def test_the_knee_angle_of_a_synthetic_body_is_its_script() -> None:
    for knee in (90, 120, 170):
        body = {"$fixture": "poses.body", "args": [{"knee": knee}]}
        pts = _geom("poses.body", {"knee": knee})
        got = _geom("mod.angle", pts[23], pts[25], pts[27])
        assert abs(got - knee) < 0.5, (knee, got)
        assert body  # the fixture form is the runner's own
    assert _geom("mod.angle", {"x": 0, "y": 0}, {"x": 0, "y": 0}, {"x": 1, "y": 0}) is None  # NaN


def test_a_rep_is_a_dip_below_down_then_a_rise_above_up() -> None:
    state = None
    for t, value in enumerate([170, 150, 95, 80, 100, 150, 172, 160, 85, 175, 120]):
        state = _geom("mod.reps", state, value, {"down": 90, "up": 165, "t": t})
    assert state["count"] == 2 and state["phase"] == "up"
    assert _geom("mod.reps", None, 120, {"down": 165, "up": 90})["count"] == 0  # bad limits: no rep


def test_hold_sway_sequence_and_ema() -> None:
    s = None
    for t, good in ((0, True), (1, True), (2, True), (3, False), (4, True), (5, True)):
        s = _geom("mod.hold", s, good, t)
    assert s["best"] == 2 and s["holding"] is True
    still = _geom("mod.sway", [{"x": 0.5, "y": 0.5}] * 5)
    moving = _geom("mod.sway", [{"x": 0.5 + d, "y": 0.5} for d in (0, 0.02, -0.02, 0.03, -0.03)])
    assert still["r"] == 0 and moving["r"] > 0.01
    seq = _geom("mod.sequence", ["a", "c", "b", "c", "d"], ["a", "b", "c", "d"])
    assert seq == {"matched": 4, "outOfOrder": 1, "missing": []}
    assert _geom("mod.ema", None, 10, 0.5) == 10 and _geom("mod.ema", 10, 20, 0.25) == 12.5


def test_the_synthetic_hands_are_the_engines_shape() -> None:
    h = _geom("hands.hand", {"side": "left", "open": 0.5})
    assert h["side"] == "left" and len(h["points"]) == 21
    assert set(h["points"][0]) == {"x", "y", "z"}
    assert len(_geom("hands.hands", [h, h, h])["hands"]) == 2
    two = _geom("poses.pose", [_geom("poses.body", {}), _geom("poses.body", {})])
    assert [b["track"] for b in two["bodies"]] == [0, 1] and {b["who"] for b in two["bodies"]} == {
        ""
    }


# ---- S19 · the guard runs on every console-coach-*.js; pure modules; the pixel panes -------------
def test_every_coach_module_passes_the_guard_and_geometry_is_the_one_import() -> None:
    from r7_fakes_b import (
        COACH_PANES,
        PURE_MODULES,
        pure_problems,
        use_case_modules,
        use_case_problems,
    )

    names = {p.name for p in use_case_modules()}
    coach = {p.name for p in STATIC.glob("console-coach-*.js")}
    assert coach - names == set(COACH_PANES) | {"console-coach-geom.js", "console-coach-bp.js"}
    for path in use_case_modules():
        assert use_case_problems(path.read_text(encoding="utf-8")) == [], path.name
    for name in PURE_MODULES:
        assert pure_problems((STATIC / name).read_text(encoding="utf-8")) == [], name
    use = "JarvisVision.use({ id: 'reps', tasks: ['pose'], onResult: (r, s) => s, summary: (s) => s"
    use += " });"
    assert use_case_problems("import { angle, reps } from './console-coach-geom.js';\n" + use) == []
    for sneak in (
        "import { fetch } from './console-coach-geom.js';",
        "import { angle } from './console-vision-r8.js';",
        "import * as g from './console-coach-geom.js';",
        "import { angle } from 'https://cdn.example/geom.js';",
    ):
        assert use_case_problems(sneak + "\n" + use) != [], sneak
    assert pure_problems("export function f() { return fetch('/x'); }") != []


def test_the_panes_register_their_modes_and_load_their_use_cases() -> None:
    from jarvis.coach.usecases import USE_CASES

    desk = (STATIC / "console-coach-desk.js").read_text(encoding="utf-8")
    workout = (STATIC / "console-coach-workout.js").read_text(encoding="utf-8")
    setup = (STATIC / "console-camera-setup.js").read_text(encoding="utf-8")
    assert "modes.register('desk'," in desk and "modes.register('workout'," in workout
    assert "modes.register('cameras'," in setup and "import('./console-vision-check.js')" in setup
    for u in USE_CASES:
        if not u.module.endswith(".js"):
            continue
        pane = desk if u.spot == "desk" else workout
        assert f"'{u.id}': () => import('./{u.module}')" in pane, u.id
    for js in (desk, workout, setup):
        assert js.isascii() and "innerHTML" not in js and "fetch(" not in js


# ---- S16, S17 · the Camera panel's panes and the deep links (open, never act) --------------------
def test_the_camera_panel_has_desk_and_workout_panes_and_no_new_dock_tab() -> None:
    out = run_dom("look", steps=[{"op": "open"}])
    assert out["cam"]["live"] is False  # opening never starts the camera
    js = (STATIC / "console-camera-panel.js").read_text(encoding="utf-8")
    assert "['desk', 'Desk'], ['workout', 'Workout']" in js and len(js.splitlines()) <= 483
    html = (STATIC / "console.html").read_text(encoding="utf-8")
    assert 'data-open="desk"' not in html and 'data-open="workout"' not in html


def test_the_deep_links_open_three_panes_and_never_start_the_camera() -> None:
    from r7_fakes_a import links_words

    from jarvis.mobile.ports import LAUNCH_WORDS

    assert links_words() == list(LAUNCH_WORDS)
    assert LAUNCH_WORDS[-3:] == ("desk", "workout", "cameras")
    js = (STATIC / "console-r7-links.js").read_text(encoding="utf-8")
    assert (
        "else if (PANES.includes(l.do)) { if (D) D.open('camera', { focus: true }); "
        "partCall('panel', 'choose', l.do); }" in js
    )
    assert "start(" not in js and "JarvisCamera" not in js


# ---- S28 · the bar's layout model (D13, part I) --------------------------------------------------
BAR = ["chat", "brief", "approvals", "activity", "vault", "camera", "calls"]


def _dock(call: str, *args: Any) -> Any:
    from r8_fakes import run_node

    return run_node("console-dock-layout.js", call, *args)


def test_no_saved_layout_is_the_shipped_bar_exactly() -> None:
    layout = _dock("mod.apply", BAR, None)
    assert layout == {"v": 1, "order": BAR, "more": [], "hidden": False}
    assert _dock("mod.isDefault", BAR, layout) is True
    assert _dock("mod.parse", "not json") is None and _dock("mod.parse", '{"v": 2}') is None


def test_moves_removals_and_a_later_release_lose_nothing() -> None:
    saved = {
        "v": 1,
        "order": ["camera", "chat", "brief"],
        "more": ["vault", "chat"],
        "hidden": True,
    }
    parsed = _dock("mod.parse", __import__("json").dumps(saved))
    assert parsed["more"] == ["vault"]  # chat can never be removed
    drawn = _dock("mod.apply", [*BAR, "newtab"], parsed)
    assert drawn["order"][:3] == ["camera", "chat", "brief"]
    assert drawn["order"][-1] == "newtab" and set(drawn["order"]) | set(drawn["more"]) == {
        *BAR,
        "newtab",
    }
    assert drawn["hidden"] is True and drawn["more"] == ["vault"]
    gone = _dock(
        "mod.apply", ["chat", "brief"], parsed
    )  # a tab the console no longer has is dropped
    assert gone["order"] == ["chat", "brief"] and gone["more"] == []
    base = _dock("mod.apply", BAR, None)
    assert _dock("mod.toMore", base, "chat") == base  # chat stays
    moved = _dock("mod.move", base, "calls", 0)
    assert moved["order"][0] == "calls" and _dock("mod.isDefault", BAR, moved) is False
    back = _dock("mod.fromMore", _dock("mod.toMore", base, "vault"), "vault", 1)
    assert back["order"][1] == "vault" and back["more"] == []
    text = _dock("mod.serialize", _dock("mod.hide", base, True))
    assert _dock("mod.parse", text)["hidden"] is True
