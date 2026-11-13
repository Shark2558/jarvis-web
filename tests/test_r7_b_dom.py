# tests/test_r7_b_dom.py -- R7 Part B, by behaviour (docs/plans/r7-mobile.md D11-D13): the
# console's camera door, the vision engine and the Camera panel run in Node on a small fake DOM
# (tests/fixtures/r7/b_dom.js) with a fake camera whose every frame is a planted pixel pattern,
# R5's real voice router and a spy on every way to send bytes.
#   - locked: no live track, and unlock() from script is false; only a tap unlocks; a hidden page
#     stops the camera; the "Camera on" chip shows exactly while a track is live; "cameras off" in
#     all 20 phrasings locks; "turn the camera on" by voice does nothing; another tab's switch
#     counts only from the browser's own storage event
#   - a use case receives Results only (frozen plain data: no frame, no canvas, no bitmap); a
#     task's answer outside its own schema is dropped (ok false, no data)
#   - during a photo look and a live run no request carries picture bytes and the picture door is
#     never called; Keep sends the result alone; the three buttons send through the one door and
#     count; "Ask the AI" is not offered while the brain answering does not see pictures; before
#     sign-in the panel asks the server nothing
from __future__ import annotations

from typing import Any

import pytest
from r7_fakes_b import run_dom

from jarvis.voice.commands import R7_PHRASES

UPLOAD_ROUTES = ("/v1/attachments", "/v1/vault", "/v1/chat", "/v1/files", "/app/share", "/phone/")
LOOK = [{"op": "open"}, {"op": "task", "task": "quality"}]
ASK = "Ask the AI about this photo (about \u20b90.30)"


def press(label: str) -> dict[str, str]:
    return {"op": "press", "label": label}


def mark(name: str) -> dict[str, str]:
    return {"op": "mark", "name": name}


def tap(op: str = "start") -> dict[str, Any]:
    return {"op": op, "tap": True}


def _steps(out: dict[str, Any]) -> list[dict[str, Any]]:
    steps: list[dict[str, Any]] = out["steps"]
    return steps


def picture_bytes_sent(out: dict[str, Any], since: int = 0) -> list[str]:
    """Every request (after `since`) whose body carries the planted pattern, is binary or goes to
    an upload route."""
    plant = out["plant"]
    bad = []
    for req in out["net"][since:]:
        body = req["body"]
        carries = any(p in body for p in (plant["ascii"], plant["base64"], plant["numbers"]))
        if (
            carries
            or req["binary"]
            or req["path"].startswith(UPLOAD_ROUTES)
            or req["kind"] == "chat"
        ):
            bad.append(f"{req['kind']} {req['method']} {req['path']}")
    return bad


def test_locked_there_is_no_live_track_and_script_cannot_unlock() -> None:
    out = run_dom("camera", steps=[
        {"op": "lock"}, {"op": "start", "tap": True}, {"op": "unlock", "tap": False},
        {"op": "start", "tap": True}, {"op": "unlock", "tap": True}, {"op": "start", "tap": True},
    ])  # fmt: skip
    lock, refused, script_unlock, still, tap_unlock, started = _steps(out)
    assert lock["locked"] and lock["stored"] == "1"
    assert refused["ok"] is False and refused["code"] == "camera_off" and refused["asked"] == 0
    assert script_unlock["ok"] is False and script_unlock["locked"] is True
    assert still["asked"] == 0 and still["liveTracks"] == 0
    assert (
        tap_unlock["ok"] is True and tap_unlock["locked"] is False and tap_unlock["stored"] is None
    )
    assert started["ok"] is True and started["live"] and started["asked"] == 1


def test_the_camera_starts_only_from_a_tap_and_the_chip_shows_while_live() -> None:
    out = run_dom("camera", steps=[
        {"op": "start", "tap": False}, tap(), {"op": "frame"}, {"op": "chipStop"},
    ])  # fmt: skip
    no_tap, started, frame, stopped = _steps(out)
    assert no_tap["ok"] is False and no_tap["code"] == "needs_tap" and no_tap["asked"] == 0
    assert started["live"] and started["chip"] and started["liveTracks"] == 1
    assert frame["ok"] is True
    assert not stopped["live"] and not stopped["chip"] and stopped["liveTracks"] == 0


def test_a_hidden_page_stops_the_camera_and_a_lock_stops_every_track() -> None:
    out = run_dom("camera", steps=[
        {"op": "start", "tap": True}, {"op": "hide"}, {"op": "start", "tap": True}, {"op": "lock"},
        {"op": "frame"},
    ])  # fmt: skip
    _, hidden, again, locked, frame = _steps(out)
    assert not hidden["live"] and hidden["liveTracks"] == 0 and not hidden["chip"]
    assert again["live"] and not locked["live"] and locked["liveTracks"] == 0 and not locked["chip"]
    assert frame["ok"] is False  # no frame once stopped


@pytest.mark.parametrize("phrase", R7_PHRASES["camera.off"])
def test_every_cameras_off_phrasing_locks_this_device(phrase: str) -> None:
    out = run_dom("camera", steps=[
        {"op": "start", "tap": True}, {"op": "voice", "text": f"Jarvis, {phrase}"},
    ])  # fmt: skip
    said = _steps(out)[1]
    assert said["ok"] is True and said["locked"] and not said["live"], phrase
    assert said["code"] == "The camera on this device is off, Sir."


def test_there_are_twenty_phrasings_and_no_voice_turns_the_camera_on() -> None:
    assert len(R7_PHRASES["camera.off"]) == 20
    out = run_dom("camera", steps=[
        {"op": "lock"}, {"op": "voice", "text": "Jarvis, turn the camera on"},
        {"op": "voice", "text": "switch on the camera"}, {"op": "voice", "text": "cameras on"},
        {"op": "voice", "text": "start the camera"},
    ])  # fmt: skip
    for step in _steps(out)[1:]:
        assert step["ok"] is False and step["locked"] and step["asked"] == 0, step


def test_another_tab_counts_only_through_the_browsers_own_storage_event() -> None:
    out = run_dom("camera", steps=[
        {"op": "lock"}, {"op": "storage", "value": None, "trusted": False},
        {"op": "storage", "value": None, "trusted": True},
        {"op": "storage", "value": "1", "trusted": True},
    ])  # fmt: skip
    _, forged, other_tab_on, other_tab_off = _steps(out)
    assert forged["locked"] is True
    assert other_tab_on["locked"] is False and other_tab_off["locked"] is True


def test_a_use_case_receives_frozen_plain_results_only() -> None:
    out = run_dom("engine", probe={"n": 1})
    assert [g["keys"] for g in out["got"]] == [
        ["at", "data", "device", "ms", "ok", "quality", "task", "v"]
    ] * 2
    for got in out["got"]:
        for kind in got["kinds"]:
            assert kind in (
                "number",
                "string",
                "boolean",
                "[object Object]:frozen",
                "[object Array]:frozen",
            ), kind
    probe, quality = out["results"]
    assert probe["ok"] is True and probe["data"] == {"n": 1}
    assert quality["ok"] is True and set(quality["data"]) == {"light", "sharp"}
    assert 0 <= quality["data"]["light"] <= 1 and quality["device"] == "phone"


def test_an_answer_outside_its_schema_is_dropped() -> None:
    out = run_dom("engine", probe={"n": 2, "pixels": [82, 55, 80]})
    probe = out["results"][0]
    assert probe["ok"] is False and probe["data"] == {}
    assert out["got"][0]["r"]["data"] == {}


def test_the_engine_lists_the_five_tasks() -> None:
    tasks = {t["id"]: t for t in run_dom("engine", probe={"n": 1})["tasks"]}
    assert {"text", "code", "objects", "pose", "quality"} <= set(tasks)
    assert {tasks[t]["input"] for t in ("text", "code", "objects", "pose", "quality")} == {"both"}


def test_a_live_run_sends_no_picture_and_keep_sends_the_result_alone() -> None:
    out = run_dom("look", steps=[
        *LOOK, mark("start"), press("Start the camera"), {"op": "wait", "ms": 1600},
        mark("kept"), press("Keep"), press("Stop"),
    ])  # fmt: skip
    assert out["cam"]["asked"] == 1 and out["out"].startswith("Light ")
    assert picture_bytes_sent(out) == [] and out["door"] == []
    kept = out["net"][out["marks"]["kept"]["net"] :]
    assert [(r["method"], r["path"]) for r in kept] == [("POST", "/v1/vision/results")]
    assert '"task":"quality"' in kept[0]["body"] and len(kept[0]["body"]) < 2000
    assert not out["cam"]["live"] and out["cam"]["liveTracks"] == 0


def test_a_photo_look_sends_nothing_until_a_button_that_says_so() -> None:
    out = run_dom("look", sees=False, steps=[
        *LOOK, press("Choose a photo"), {"op": "pick"}, mark("looked"),
    ])  # fmt: skip
    assert out["out"].startswith("Light ") and picture_bytes_sent(out) == [] and out["door"] == []
    assert ASK not in out["buttons"]  # the brain answering now can't see pictures
    assert {"Add to my vault", "Attach to my message", "Keep"} <= set(out["buttons"])
    assert out["sent"] == "Pictures sent from this device today: 0"


def test_the_three_buttons_send_through_the_one_door_and_count() -> None:
    out = run_dom("look", sees=True, steps=[
        *LOOK, press("Choose a photo"), {"op": "pick"}, press(ASK),
        press("Add to my vault"), press("Attach to my message"),
    ])  # fmt: skip
    assert [d["how"] for d in out["door"]] == ["ask", "vault", "attach"]
    assert out["door"][0]["text"] == "What can you see in this photo?"
    assert out["sent"] == "Pictures sent from this device today: 3"
    assert picture_bytes_sent(out) == []  # the door itself sends; the panel never does


def test_a_closed_panel_stops_the_camera() -> None:
    out = run_dom(
        "look",
        steps=[
            *LOOK,
            {"op": "press", "label": "Start the camera"},
            {"op": "wait"},
            {"op": "close"},
        ],
    )
    assert out["cam"]["asked"] == 1 and not out["cam"]["live"] and out["cam"]["liveTracks"] == 0


def test_before_sign_in_the_block_asks_the_server_nothing() -> None:
    steps = [{"op": "open"}, {"op": "wait"}, mark("in"), {"op": "signin"}]
    out = run_dom("look", signed=False, steps=steps)
    assert out["marks"]["in"]["net"] == 0
    assert [r["path"] for r in out["net"]] == ["/v1/vision"]


def test_a_task_that_is_not_installed_says_so_and_cannot_look() -> None:
    out = run_dom("look", steps=[{"op": "open"}, {"op": "task", "task": "pose"}])
    assert "Body points (not installed)" in out["options"]
    assert "Everyday things (not installed)" in out["options"] and "Read text" in out["options"]
    assert "Not installed on this server yet: its model file has not arrived." in out["notes"]
    assert {"Choose a photo", "Start the camera"} <= set(out["disabled"])
    assert out["cam"]["asked"] == 0 and [r["path"] for r in out["net"]] == ["/v1/vision"]


def test_body_points_carry_the_model_cards_limits_once_installed() -> None:
    installed = {"installed": True, "why": ""}
    tasks = {t: installed for t in ("text", "code", "quality", "objects", "pose")}
    out = run_dom("look", answers={"/v1/vision": {"tasks": tasks}},
                  steps=[{"op": "open"}, {"op": "task", "task": "pose"}])  # fmt: skip
    assert "Body points" in out["options"] and not out["disabled"]
    assert any("never to recognise who someone is" in n for n in out["notes"])


# ---- review follow-ups (code M1-M4, security LOW-1/2, wake lock, focus, stale words) --------
INSTALLED = {
    "/v1/vision": {
        "tasks": {
            t: {"installed": True, "why": ""}
            for t in ("text", "code", "quality", "objects", "pose")
        }
    }
}
CAN_NOT_LOAD = "The vision tools could not load. Check the connection and try again."


def test_a_tap_elsewhere_on_the_page_cannot_start_or_unlock_the_camera() -> None:
    out = run_dom("camera", steps=[
        {"op": "start", "tap": "elsewhere"}, {"op": "lock"}, {"op": "unlock", "tap": "elsewhere"},
        {"op": "unlock", "tap": True}, {"op": "start", "tap": True},
    ])  # fmt: skip
    elsewhere, _, no_unlock, unlocked, started = _steps(out)
    assert elsewhere["ok"] is False and elsewhere["code"] == "needs_tap" and elsewhere["asked"] == 0
    assert no_unlock["ok"] is False and no_unlock["locked"] is True
    assert unlocked["ok"] is True and unlocked["locked"] is False
    assert started["live"] and started["asked"] == 1


def test_the_chip_shows_from_the_moment_a_track_exists() -> None:
    out = run_dom("camera", play="hang", steps=[
        {"op": "start", "tap": True, "nowait": True}, {"op": "chipStop"},
    ])  # fmt: skip
    started, stopped = _steps(out)
    assert started["liveTracks"] == 1 and started["chip"] is True  # play() has not resolved
    assert not stopped["live"] and not stopped["chip"]


def test_a_stop_while_the_browser_still_asks_leaves_no_track_live() -> None:
    out = run_dom("camera", gum={"hold": True}, steps=[
        {"op": "start", "tap": True, "nowait": True}, {"op": "stop"}, {"op": "release"},
    ])  # fmt: skip
    asked, _, released = _steps(out)
    assert asked["asked"] == 1 and not asked["live"]
    assert not released["live"] and released["liveTracks"] == 0 and not released["chip"]


def test_two_starts_while_a_wake_lock_is_pending_hold_only_one_lock() -> None:
    out = run_dom("camera", wake=True, steps=[
        {"op": "start", "tap": True}, {"op": "start", "tap": True}, {"op": "wake"},
        {"op": "stop"}, {"op": "wake"},
    ])  # fmt: skip
    *_, live_after_wake, stopped, after_stop = _steps(out)
    assert live_after_wake["wakeHeld"] <= 1
    assert stopped["wakeHeld"] == 0 and after_stop["wakeHeld"] == 0


def test_closing_the_panel_while_the_camera_is_still_being_asked_leaves_it_off() -> None:
    out = run_dom("look", gum={"hold": True}, steps=[
        *LOOK, press("Start the camera"), {"op": "close"}, {"op": "release"},
    ])  # fmt: skip
    assert out["cam"]["asked"] == 1
    assert not out["cam"]["live"] and out["cam"]["liveTracks"] == 0 and not out["cam"]["chip"]


def test_a_second_photo_replaces_a_look_still_running_and_the_old_answer_never_shows() -> None:
    out = run_dom("look", runDelays=[400, 0], steps=[
        *LOOK, press("Choose a photo"), {"op": "pick"}, press("Choose a photo"), {"op": "pick"},
        {"op": "wait", "ms": 700},
    ])  # fmt: skip
    assert out["out"] == "Light 20 %, sharpness 50 %." and out["state"] == ""


def test_changing_the_task_during_a_look_drops_the_old_answer() -> None:
    out = run_dom("look", runDelays=[400], answers=INSTALLED, steps=[
        *LOOK, press("Choose a photo"), {"op": "pick"}, {"op": "task", "task": "objects"},
        {"op": "wait", "ms": 700},
    ])  # fmt: skip
    assert out["boxHidden"] is True and not out["out"].startswith("Light")
    assert "not installed" in out["state"].lower()


def test_a_look_that_cannot_load_says_so_and_does_not_keep_the_old_result() -> None:
    out = run_dom("look", answers=INSTALLED, fetchStatus=500, steps=[
        *LOOK, {"op": "task", "task": "pose"}, press("Choose a photo"), {"op": "pick"},
    ])  # fmt: skip
    assert out["state"] == CAN_NOT_LOAD and out["boxHidden"] is True


def test_a_live_look_that_cannot_load_says_so_instead_of_staying_silent() -> None:
    out = run_dom("look", answers=INSTALLED, fetchStatus=500, steps=[
        *LOOK, {"op": "task", "task": "objects"}, press("Start the camera"),
        {"op": "wait", "ms": 200},
    ])  # fmt: skip
    assert out["state"] == CAN_NOT_LOAD
    assert "Nothing leaves this device" not in out["state"]


def test_a_live_look_whose_model_has_not_arrived_says_that() -> None:
    out = run_dom("look", answers=INSTALLED, fetchStatus=404, steps=[
        *LOOK, {"op": "task", "task": "pose"}, press("Start the camera"), {"op": "wait", "ms": 200},
    ])  # fmt: skip
    assert out["state"] == "Not installed on this server yet: its model file has not arrived."


def test_a_dropped_frame_does_not_end_a_live_look() -> None:
    out = run_dom("look", blank=2, steps=[
        *LOOK, press("Start the camera"), {"op": "wait", "ms": 2600},
    ])  # fmt: skip
    assert out["out"].startswith("Light ") and out["cam"]["live"]


@pytest.mark.parametrize(
    ("error", "words"),
    [
        ("NotAllowedError", "wasn\u2019t allowed"),
        ("NotFoundError", "No camera was found"),
        ("OverconstrainedError", "No camera was found"),
        ("NotReadableError", "busy in another app"),
        ("TypeError", "That didn\u2019t work"),
        ("SomethingNewError", "That didn\u2019t work"),
    ],
)
def test_a_camera_that_will_not_start_is_told_in_plain_words(error: str, words: str) -> None:
    out = run_dom("look", gum={"error": error}, steps=[*LOOK, press("Start the camera")])
    assert words in out["state"] and "raw browser text" not in out["state"], error
    assert not out["cam"]["live"] and out["cam"]["liveTracks"] == 0


def test_a_server_failure_is_plain_words_and_never_the_raw_text() -> None:
    fail = {"__fail": {"status": 500, "message": "Traceback (most recent call last)"}}
    out = run_dom("look", answers={"/v1/vision/results": fail}, steps=[
        *LOOK, press("Choose a photo"), {"op": "pick"}, press("Keep"),
    ])  # fmt: skip
    assert out["state"] and "Traceback" not in out["state"] and "most recent" not in out["state"]


def test_a_lock_or_idle_stop_updates_the_words_and_the_stage() -> None:
    out = run_dom("look", steps=[*LOOK, press("Start the camera"), {"op": "lock"}])
    assert out["state"] == "The camera was switched off." and out["stageKids"] == 0
    assert out["meta"] == "Switched off"


def test_the_keyboard_focus_stays_on_a_button_when_the_buttons_are_repainted() -> None:
    out = run_dom("look", steps=[*LOOK, press("Start the camera")])
    assert out["focus"] in ("Take a photo", "Stop", "Read now")
