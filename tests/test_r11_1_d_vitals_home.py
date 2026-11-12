# tests/test_r11_1_d_vitals_home.py -- R11.1 Part D, O10 (docs/plans/r11-1-observations.md D18):
# "Home laptop link reports a problem" while the laptop is on. The laptop's heartbeat already says
# WHICH part failed (the camera watcher, or the camera's messenger); the Vitals row and the systems
# check now name it, with its own fix steps, in fixed words from a map keyed by the part. A device
# name (a camera's id) never reaches the row.
from __future__ import annotations

import json
import re
from pathlib import Path
from unittest.mock import patch

import pytest
from r11_1_fakes_d import HomeRig

from jarvis.health.briefing import compose_briefing
from jarvis.storage.docs import Set
from jarvis.vitals import words
from jarvis.vitals.words import HOME_FAULTS, home_fault

KIT = Path(__file__).resolve().parents[1] / "deploy" / "home"
PANEL_REASON_MAX = 120  # console-vitals.js keeps this much of a row's reason
BRIEFING_LINE_MAX = 160  # health.briefing.TEXT_MAX: one impact / fix line


async def _row(**parts: object):  # type: ignore[no-untyped-def]
    home = HomeRig()
    await home.link()
    await home.beat(**parts)
    return home, await home.row()


# ---- each failing part has its own words ---------------------------------------------------------
async def test_the_camera_watcher_is_named_with_its_own_fix_steps() -> None:
    _, v = await _row(frigate=False, mqtt=True)

    assert v.status == "amber"
    assert v.reason == "is on, but the camera watcher (Frigate) is not answering"
    assert "burglar alerts can't arrive" in v.impact
    assert "start-home.ps1" in v.fix and "docker restart jarvis-home-frigate-1" in v.fix
    assert "mosquitto" not in v.fix


async def test_the_cameras_messenger_is_named_with_its_own_fix_steps() -> None:
    _, v = await _row(frigate=True, mqtt=False)

    assert v.status == "amber"
    assert v.reason == (
        "is on, but the camera's messenger (MQTT) is not connected, so burglar alerts can't arrive"
    )
    assert "start-home.ps1" in v.fix
    assert "docker restart jarvis-home-mosquitto-1 jarvis-home-bridge-1" in v.fix
    assert "frigate" not in v.fix.lower()


async def test_both_parts_down_names_both_and_restarts_both() -> None:
    _, v = await _row(frigate=False, mqtt=False)

    assert v.status == "amber"
    assert "the camera watcher (Frigate) is not answering" in v.reason
    assert "the camera's messenger (MQTT) is not connected" in v.reason
    assert "jarvis-home-frigate-1" in v.fix and "jarvis-home-mosquitto-1" in v.fix


async def test_the_three_rows_differ_from_each_other_and_from_the_old_words() -> None:
    rows = [
        (await _row(frigate=False, mqtt=True))[1],
        (await _row(frigate=True, mqtt=False))[1],
        (await _row(frigate=False, mqtt=False))[1],
    ]

    assert len({v.reason for v in rows}) == len({v.fix for v in rows}) == 3
    for v in rows:
        assert "reports a problem" not in v.reason
        assert v.reason.startswith("is on, but ")  # the laptop IS on: say so first
        assert v.provider.note.startswith("Last heartbeat ")


# ---- never a device name, never a guess ----------------------------------------------------------
async def test_a_cameras_name_never_reaches_the_row() -> None:
    home, v = await _row(
        frigate=False, mqtt=False, cameras=[{"id": "gate_cam_x9", "online": False}]
    )

    board = json.dumps((await home.rig.svc.board("u_owner")).to_json())
    assert "gate_cam_x9" not in board and "gate_cam" not in v.reason + v.impact + v.fix


async def test_a_problem_with_no_known_part_keeps_the_plain_words() -> None:
    home = HomeRig()
    await home.link()
    await home.beat(frigate=False)
    # the stored parts lost their meaning (an older record, or a part this version doesn't know)
    doc = await home.docs.get("jarvis_home/u_owner")
    assert doc is not None
    await home.docs.write([Set("jarvis_home/u_owner", {**doc, "parts": {"new_part": False}})])

    v = await home.row()

    assert (v.status, v.reason) == ("amber", "reports a problem")
    assert "restart the JARVIS bridge" in v.fix  # the general fix, as before


@pytest.mark.parametrize("bad", ["no", 0, None, [], {"up": False}])
async def test_only_a_plain_false_counts_as_a_failing_part(bad: object) -> None:
    assert home_fault({"frigate": bad, "mqtt": True}) is None
    assert home_fault("frigate") is None and home_fault(None) is None


async def test_a_part_that_comes_back_clears_the_row() -> None:
    home, v = await _row(frigate=False, mqtt=True)
    assert v.status == "amber"

    await home.beat(frigate=True, mqtt=True)

    v = await home.row()
    assert (v.status, v.reason) == ("ok", "")


# ---- the systems check says it too ---------------------------------------------------------------
async def test_the_systems_check_names_the_part_and_the_first_fix_step() -> None:
    home, _ = await _row(frigate=False, mqtt=True)
    board = await home.rig.svc.board("u_owner")

    said = compose_briefing(None, board)

    line = next(ln for ln in said.lines if ln.startswith("Home laptop link"))
    assert "the camera watcher (Frigate) is not answering" in line
    assert "start-home.ps1" in line and line.endswith(".")
    assert line in said.spoken
    concern = next(c for c in said.concerns if c.key == "vitals.home_link")
    assert concern.fix.endswith("docker restart jarvis-home-frigate-1")  # not cut short


# ---- the words themselves ------------------------------------------------------------------------
def test_the_words_come_from_a_map_keyed_by_the_part() -> None:
    assert set(HOME_FAULTS) == {"frigate", "mqtt"}
    for part, fault in HOME_FAULTS.items():
        one = home_fault({part: False})
        assert one is not None and fault.name in one.reason and one.fix == fault.fix


def test_every_line_fits_the_panel_and_the_briefing() -> None:
    cases = [{"frigate": False}, {"mqtt": False}, {"frigate": False, "mqtt": False}]
    for parts in cases:
        f = home_fault(parts)
        assert f is not None
        assert len(f.reason) <= PANEL_REASON_MAX, f.reason
        assert f.impact.startswith("Now: ")
        assert len(f.impact) - len("Now: ") <= BRIEFING_LINE_MAX, f.impact
        assert len(f.fix) <= BRIEFING_LINE_MAX, f.fix
        assert (f.reason + f.impact + f.fix).isascii()
        assert "$" not in f.reason + f.impact + f.fix


def test_the_fix_steps_name_what_the_home_kit_really_has() -> None:
    compose = (KIT / "docker-compose.yml").read_text(encoding="utf-8")
    project = re.search(r"^name: ([a-z-]+)$", compose, re.M)
    assert project is not None and (KIT / "start-home.ps1").is_file()
    said = " ".join(f.fix for f in HOME_FAULTS.values())
    containers = set(re.findall(r"\bjarvis-home-[a-z]+-1\b", said))
    assert containers == {
        "jarvis-home-frigate-1",
        "jarvis-home-mosquitto-1",
        "jarvis-home-bridge-1",
    }
    for name in containers:
        service = name.removeprefix(f"{project.group(1)}-").removesuffix("-1")
        assert re.search(rf"^  {service}:$", compose, re.M), service


# ---- the negative control: without the map the old, vague row is back ----------------------------
async def test_with_the_fault_map_emptied_the_row_is_vague_again() -> None:
    with patch.object(words, "HOME_FAULTS", {}):
        _, v = await _row(frigate=False, mqtt=False)

    assert v.reason == "reports a problem" and "docker restart" not in v.fix
