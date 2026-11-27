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


# ---- S2 · results only to the use cases a live look names -----------------------------------------
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
    nobody = _driver(use("coach", "pose"), live(["pose"], ["coach"], target={"kind": "person", "person": "Shruti"}))
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


# ---- S3 · the R8 task module ----------------------------------------------------------------------
def test_hands_and_pose_v2_are_registered_and_say_not_installed() -> None:
    out = run_dom("r8tasks")
    tasks = {t["id"]: t for t in out["tasks"]}
    assert tasks["pose"]["v"] == 2 and tasks["hands"]["v"] == 1 and tasks["digits"]["v"] == 1
    assert out["sealed"] is True
    assert out["errors"] == {"pose": "not installed", "hands": "not installed", "digits": "not installed"}
    broken = run_dom("r8tasks", fetchStatus=500)
    no_load = "The vision tools could not load. Check the connection and try again."
    assert broken["errors"] == {"pose": no_load, "hands": no_load, "digits": "not installed"}


def test_the_r8_task_module_holds_bodies_only() -> None:
    js = (STATIC / R8_MODULE).read_text(encoding="utf-8")
    assert js.isascii() and len(js.splitlines()) <= 800
    for name in ("loadPose", "runPose", "loadHands", "runHands", "loadDigits", "runDigits", "unload"):
        assert f"export function {name}(" in js or f"export async function {name}(" in js, name
    for bad in ("fetch(", "JarvisCamera", "getUserMedia", "JarvisVision", "localStorage",
                "innerHTML", "XMLHttpRequest", "sendBeacon", "WebSocket", "import("):  # fmt: skip
        assert bad not in js, bad
