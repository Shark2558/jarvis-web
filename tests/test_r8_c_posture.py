# tests/test_r8_c_posture.py -- R8 row 181 (docs/plans/r8-vision.md 2.1, 4.7; ROWS.md): posture
# checks from the home camera, on the home laptop, and the posture nudge in the cloud.
#   - the plan's check: >= 90 % of 60-s slouch or forward-head spans give a nudge; <= 1 false nudge
#     per synthetic hour of good posture; at most 3 nudges an hour; the rule's share of one laptop
#     core <= 10 % (its own time per frame x 2 frames a second)
#   - the workbook's check (ROWS.md): "Slouch 10 min -> a nudge."
#   - only counts and times are kept: the tally fits PostureTally, no point in a view or the state
#   - the nudge: off until he switches it on, inside his window, once per span, 3 an hour, 8 a day
#     whatever his caps, one fixed sentence, nothing about a person he enrolled
from __future__ import annotations

import dataclasses
import json
import logging
import time
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from r8_fakes_c import FORWARD_HEAD, SEATED, SLOUCH, START, UPRIGHT, body, frames, pose_result

from jarvis.coach.home import HomeUseCase
from jarvis.coach.home import posture as P
from jarvis.coach.usecases import parse_tally
from jarvis.coach.words import COACH_WORDS, POSTURE_NUDGE, medical_hits
from jarvis.home.ports import CoachReport

CALIB = [("upright", 15.0)]


Run = tuple[P.PostureCoach, P.PostureState, list[dict[str, Any]]]


def run(
    blocks: Sequence[tuple[str, float]],
    *,
    fps: float = 1.0,
    seed: int = 7,
    coach: P.PostureCoach | None = None,
) -> Run:
    """Feed the scripted blocks; return the coach, its state and every nudge tip it raised."""
    c = coach or P.PostureCoach(aspect=1.0)
    state: P.PostureState | None = None
    tips: dict[int, dict[str, Any]] = {}
    for _, _, results in frames(blocks, fps=fps, seed=seed):
        for r in results:
            if r["task"] in c.tasks:
                state = c.on_result(r, state)
        for w in c.summary(state)["view"]:
            if w["kind"] == "tip":
                tips.setdefault(w["since"], w)
    assert state is not None
    return c, state, list(tips.values())


def test_it_is_a_home_use_case_and_its_words_are_the_coachs_own() -> None:
    coach: HomeUseCase = P.create()  # mypy holds it to the home use-case contract
    assert coach.id == "posture" and coach.tasks == ("pose",)
    assert callable(coach.on_result) and callable(coach.summary)
    assert P.NUDGE == POSTURE_NUDGE
    assert {P.NUDGE, P.CALIBRATE, P.CALIBRATED} <= set(COACH_WORDS["posture"])
    assert all(medical_hits(w) == [] for w in P.WORDS)


def test_ten_seconds_of_sitting_up_straight_is_his_own_upright() -> None:
    c = P.PostureCoach(aspect=1.0)
    state = None
    for i in range(12):
        state = c.on_result(pose_result(body({**SEATED, "torso": 9, "neck": 16}), START + i), state)
        if i < 9:
            assert c.summary(state)["view"][0] == {"kind": "line", "text": P.CALIBRATE}
    assert state is not None and state.base is not None
    assert state.base == pytest.approx((9.0, 25.0), abs=0.6)  # the neck from the vertical
    assert state.samples == ()  # the calibration's angles are dropped once it is learnt
    # a slouch can't become his upright: the baseline is capped
    _, slumped, _ = run([("slouch", 15.0)])
    assert slumped.base == (P.BASE_MAX_TORSO, P.BASE_MAX_NECK)


def test_nine_in_ten_held_slouches_and_forward_heads_give_a_nudge() -> None:
    blocks: list[tuple[str, float]] = list(CALIB)
    spans = 0
    for i in range(24):  # 24 spans of 65 to 121 s, three an hour at most, over 9 hours
        blocks += [("upright", 1250.0), ("slouch" if i % 2 else "forward", 65.0 + (i % 5) * 14)]
        spans += 1
    _, state, tips = run(blocks)
    assert len(tips) >= 0.9 * spans
    tally = P.PostureCoach(aspect=1.0).summary(state)["tally"]
    assert tally is not None and tally["slouch_spans"] >= 0.9 * spans


def test_good_posture_with_short_leans_and_dark_frames_gives_no_false_nudge() -> None:
    hour: list[tuple[str, float]] = []
    for i in range(12):  # five minutes each: reaching, a stretch, a dark spell
        odd = ("lean" if i % 3 else "hidden", 25.0 + i)
        hour += [("upright", 240.0), odd, ("upright", 35.0 - i)]
    for seed in (3, 11, 29):
        _, state, tips = run(CALIB + hour * 3, seed=seed)
        assert len(tips) <= 3  # <= 1 false nudge per synthetic hour of good posture
        assert P.PostureCoach(aspect=1.0).summary(state)["tally"]["upright"] >= 90  # type: ignore[index]


def test_at_most_three_nudges_in_any_hour() -> None:
    blocks = CALIB + [("slouch", 70.0), ("upright", 20.0)] * 80  # a slouch every 90 s for 2 hours
    _, state, tips = run(blocks)
    at = sorted(t["since"] for t in tips)
    assert at and all(sum(1 for b in at if a <= b < a + 3600) <= P.PER_HOUR for a in at)
    assert state.nudges == len(tips) <= 6


def test_slouching_ten_minutes_gives_a_nudge_the_workbooks_check() -> None:
    _, state, tips = run(CALIB + [("upright", 300.0), ("slouch", 600.0)])
    assert len(tips) == 1 and tips[0]["text"] == POSTURE_NUDGE
    assert tips[0]["held"] >= P.HOLD_S
    tally = P.PostureCoach(aspect=1.0).summary(state)["tally"]
    assert tally is not None and tally["slouch_spans"] == 1 and tally["nudges"] == 1
    assert 540 <= tally["slouch_seconds"] <= 620  # static-duration accuracy within 10 %


def test_the_kept_tally_fits_its_model_and_holds_no_point() -> None:
    _, state, _ = run(CALIB + [("upright", 200.0), ("slouch", 90.0), ("upright", 100.0)])
    out = P.PostureCoach(aspect=1.0).summary(state)
    tally = parse_tally("posture", out["tally"])
    assert tally is not None and tally.slouch_spans == 1 and tally.nudges == 1
    assert set(out["tally"] or {}) == {"started_at", "ended_at", "slouch_spans", "slouch_seconds",
                                       "nudges", "upright"}  # fmt: skip
    flat = json.dumps([dataclasses.asdict(state), out], default=str)
    for key in ('"x"', '"y"', '"z"', '"visibility"', '"points"'):
        assert key not in flat  # only angles and times: never a point


def test_every_view_fits_a_coach_report() -> None:
    c = P.PostureCoach(aspect=1.0)
    state = None
    seen: set[str] = set()
    for _, _, results in frames(CALIB + [("upright", 30.0), ("slouch", 80.0), ("away", 30.0)]):
        for r in results:
            if r["task"] == "pose":
                state = c.on_result(r, state)
        out = c.summary(state)
        view = out["view"]
        seen.update(w["kind"] for w in view)
        CoachReport(type="coach", id="e1", at=float(START), camera="desk_cam", use="posture",
                    session="cs_0123456789ab", track=0, who="me", view=tuple(view),
                    tally=out["tally"])  # fmt: skip
        assert all(medical_hits(str(v)) == [] for w in view for v in w.values())
    assert {"line", "timer", "tip", "bar"} <= seen


def test_the_rate_asks_for_two_frames_a_second_only_while_a_slouch_is_suspected() -> None:
    c = P.PostureCoach(aspect=1.0)
    state = None
    rates = []
    for _, truth, results in frames(CALIB + [("upright", 10.0), ("slouch", 20.0)]):
        for r in results:
            if r["task"] == "pose":
                state = c.on_result(r, state)
        rates.append((truth, c.wanted_rate(state)))
    assert rates[20][1] == 1.0 and rates[-1][1] == 2.0


def test_the_picture_is_wide_so_the_angles_are_corrected() -> None:
    lean = body({**SEATED, "torso": 30, "neck": 0})
    wide = [{**p, "x": 0.5 + (p["x"] - 0.5) * 9 / 16} for p in lean]  # the same body on 16:9
    torso, _ = P.angles(wide, 16 / 9) or (0.0, 0.0)
    assert torso == pytest.approx(30.0, abs=0.5)
    assert P.angles([{"x": 0.5, "y": 0.5, "z": 0, "visibility": 0.1}] * 33) is None


def test_the_rule_costs_well_under_a_tenth_of_one_laptop_core() -> None:
    results = [r for _, _, rs in frames(CALIB + [("upright", 600.0), ("slouch", 600.0)])
               for r in rs if r["task"] == "pose"]  # fmt: skip
    c = P.PostureCoach(aspect=1.0)
    state = None
    began = time.perf_counter()
    for r in results:
        state = c.on_result(r, state)
        c.summary(state)
    per_frame = (time.perf_counter() - began) / len(results)
    assert per_frame * P.SUSPECT_RATE < 0.01  # under 1 % of a core at 2 frames a second


# ---- the nudge in the cloud ---------------------------------------------------------------------
@pytest.fixture
def rig() -> Any:
    from r11_fakes_c import part

    from jarvis.helpers.nudges.posture import PostureNudger

    r = part(at=datetime(2026, 11, 26, 6, 0, tzinfo=UTC))  # Thursday 11:30 in Kolkata
    svc = r.part.services["service"]
    return r, svc, PostureNudger(svc)


async def _switch_on(svc: Any, **window: Any) -> None:
    from r11_fakes import UID

    await svc.store.change(UID, lambda s: s.changed("nudge_posture", {"on": True, **window}))


def _ts(r: Any) -> float:
    return float(r.clock().timestamp())


async def test_off_until_he_switches_it_on_then_once_per_span(rig: Any) -> None:
    from r11_fakes import UID

    r, svc, nudger = rig
    at = _ts(r)
    assert await nudger.slouched(UID, held_s=61, at=at) is False and r.notifier.calls == []
    await _switch_on(svc)
    assert await nudger.slouched(UID, held_s=59, at=at) is False  # not held a minute yet
    assert await nudger.slouched(UID, held_s=61, at=at) is True
    assert await nudger.slouched(UID, held_s=75, at=at + 14) is False  # the same span: once
    assert [c[1:3] for c in r.notifier.calls] == [("nudge_posture", POSTURE_NUDGE)]


async def test_outside_his_window_nothing_goes(rig: Any) -> None:
    from r11_fakes import UID

    r, svc, nudger = rig
    await _switch_on(svc, start="14:00", end="18:00")
    assert await nudger.slouched(UID, held_s=61, at=_ts(r)) is False
    assert r.notifier.calls == []


async def test_three_an_hour_and_eight_a_day_whatever_his_caps(rig: Any) -> None:
    from r11_fakes import UID

    r, svc, nudger = rig
    await _switch_on(svc, start="06:00", end="23:00")
    await svc.gate.set_caps(UID, {"nudge_posture": 20})
    sent = []
    for i in range(30):  # a new held slouch every 10 minutes for 5 hours
        r.clock.at = datetime(2026, 11, 26, 6, 0, tzinfo=UTC) + timedelta(minutes=10 * i)
        sent.append(await nudger.slouched(UID, held_s=61, at=_ts(r)))
    times = [i for i, ok in enumerate(sent) if ok]
    assert len(times) == 8  # the day's ceiling
    assert all(sum(1 for b in times if a <= b < a + 6) <= 3 for a in times)  # 6 x 10 min = 1 h


async def test_no_count_or_angle_in_the_message_or_a_log_line(
    rig: Any, caplog: pytest.LogCaptureFixture
) -> None:
    from r11_fakes import UID

    r, svc, nudger = rig
    await _switch_on(svc)
    with caplog.at_level(logging.DEBUG):
        assert await nudger.slouched(UID, held_s=97.5, at=_ts(r)) is True
    text = r.notifier.calls[0][2]
    assert text == POSTURE_NUDGE and not any(ch.isdigit() for ch in text)
    for rec in caplog.records:
        line = rec.getMessage() + json.dumps(getattr(rec, "__dict__", {}), default=str)
        assert "97" not in line and "slouch_seconds" not in line


async def test_a_report_nudges_for_him_or_an_unknown_body_never_an_enrolled_other(rig: Any) -> None:
    from r11_fakes import UID

    from jarvis.helpers.nudges.posture import on_report

    r, svc, nudger = rig
    await _switch_on(svc)
    since = int(_ts(r)) - 70
    tip = {"kind": "tip", "text": POSTURE_NUDGE, "since": since, "held": 70}

    def report(who: str, use: str = "posture") -> CoachReport:
        return CoachReport(type="coach", id="e2", at=_ts(r), camera="desk_cam", use=use,
                           session="cs_0123456789ab", track=1, who=who,
                           view=({"kind": "line", "text": P.SLOUCHING}, tip))  # fmt: skip

    assert await on_report(nudger, UID, report("fp_0123456789ab")) is False
    assert await on_report(nudger, UID, report("me", use="seated")) is False
    assert await on_report(nudger, UID, report("me")) is True
    assert await on_report(nudger, UID, report("")) is False  # the same span, already nudged
    assert len(r.notifier.calls) == 1


def test_the_plans_angles_are_what_the_fixtures_draw() -> None:
    for a, want in ((UPRIGHT, (3, 9)), (SLOUCH, (24, 58)), (FORWARD_HEAD, (4, 34))):
        torso, neck = P.angles(body({**SEATED, **a})) or (0.0, 0.0)
        assert torso == pytest.approx(want[0], abs=0.5) and neck == pytest.approx(want[1], abs=0.5)
