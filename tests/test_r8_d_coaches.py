# tests/test_r8_d_coaches.py -- R8 builder D: the desk coaches (docs/plans/r8-vision.md v8.0.4
# section 2.1 rows 224, 227, 238, 248, 262, 268, 276; docs/plans/r8-integration/ROWS.md). Each
# row's acceptance test, on synthetic data only (never a real person's):
#   - the console's use cases (console-coach-<x>.js) run in Node on the scripted sessions of
#     tests/fixtures/r8/desk_sequences.mjs, behind a stand-in for JarvisVision.use;
#   - the home camera's rules (jarvis.coach.home.seated, bp_posture) on the side-on bodies of
#     tests/fixtures/r8/desk_home.py;
#   - the reading rule (console-coach-bp.js) against the server's; drawn seven-segment screens
#     for the engine's `digits` reader (A's; it runs once that reader is on the branch); the
#     published category table (jarvis.coach.bp) with its source; the water log with Undo
#     (jarvis.coach.water).
# Every tally must fit its jarvis.coach.usecases model (a tally that doesn't is dropped), every
# view holds only the fixed widget kinds, and no view says anything medical.
from __future__ import annotations

import importlib.util
import json
import random
from collections.abc import Iterable, Mapping
from datetime import UTC, datetime
from types import ModuleType
from typing import Any, cast

import pytest
from r7_fakes_b import pure_problems, use_case_problems
from r8_fakes import FIXTURES, STATIC, run_node

from jarvis.coach import bp
from jarvis.coach.usecases import VIEW_KINDS, parse_tally
from jarvis.coach.words import PRACTICE, STOP, medical_hits

SEQ = FIXTURES / "desk_sequences.mjs"
USE_MODULES = {
    "reaction-game": "console-coach-reaction.js",
    "breath": "console-coach-breath.js",
    "water": "console-coach-water.js",
    "hand-rehab": "console-coach-handrehab.js",
    "reach-grasp": "console-coach-reach.js",
}


def _home_fixture() -> ModuleType:
    spec = importlib.util.spec_from_file_location("r8_desk_home", FIXTURES / "desk_home.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


H = _home_fixture()


def node(call: str, *args: Any) -> Any:
    return run_node(SEQ, f"mod.{call}", *args)


def _texts(view: Iterable[dict[str, Any]]) -> list[str]:
    return [str(v) for w in view for k, v in w.items() if k != "kind" and isinstance(v, str)]


def _fits(use: str, tally: dict[str, Any] | None) -> None:
    assert tally is not None, use
    assert parse_tally(use, tally) is not None, (use, tally)  # never dropped: it fits its model


def _plain_view(use: str, view: list[dict[str, Any]]) -> None:
    assert view and len(view) <= 8, use
    assert {w["kind"] for w in view} <= set(VIEW_KINDS), use
    assert [t for t in _texts(view) if medical_hits(t)] == [], use


# ---- the guard: each module is a use case (or pure), registers once, and keeps nothing ---------
@pytest.mark.parametrize("use, name", sorted(USE_MODULES.items()))
def test_each_desk_coach_passes_the_use_case_guard_and_registers_once(use: str, name: str) -> None:
    js = (STATIC / name).read_text(encoding="utf-8")
    assert js.isascii() and len(js.splitlines()) <= 400
    assert use_case_problems(js) == [], name
    assert js.count("JarvisVision.use(") == 1 and f"id: '{use}'" in js


def test_the_reading_module_is_pure_and_holds_the_rule_only() -> None:
    js = (STATIC / "console-coach-bp.js").read_text(encoding="utf-8")
    assert pure_problems(js) == [] and js.isascii()
    assert "export function proposal(" in js and "READ_MIN_SCORE = 0.8" in js
    assert (
        "readDisplay" not in js
    )  # the engine alone sees pixels: the reader is the `digits` task's


# ---- row 224: the reaction game ---------------------------------------------------------------
def test_224_touches_are_counted_and_timed_within_100_ms() -> None:
    hits = touches = 0
    for seed in (1, 2, 3, 4, 5, 6):
        out = node("reactionGame", {"seed": seed, "skip": [7, 15], "noise": 0.003})
        assert out["over"] is True and out["n"] == 20
        truths = [t for t in out["truths"] if t is not None]
        touches += len(truths)
        hits += out["hits"]
        assert out["misses"] == 2  # an untouched circle is missed, never a hit
        assert len(out["rts"]) == len(truths)
        for measured, truth in zip(out["rts"], truths, strict=True):
            assert abs(measured - truth) <= 100, (seed, measured, truth)
        _fits("reaction-game", out["tally"])
        _plain_view("reaction-game", out["view"])
    assert hits / touches >= 0.95


def test_224_the_same_game_scores_the_same_and_slower_scores_lower() -> None:
    quick = node("reactionGame", {"seed": 9, "delays": [0.2] * 20, "move": 0.2})
    again = node("reactionGame", {"seed": 9, "delays": [0.2] * 20, "move": 0.2})
    slow = node("reactionGame", {"seed": 9, "delays": [1.4] * 20, "move": 0.4})
    assert quick["tally"] == again["tally"]
    assert slow["tally"]["mean_ms"] > quick["tally"]["mean_ms"] + 900
    assert slow["tally"]["score"] < quick["tally"]["score"]


# ---- row 238: the breath pacer ----------------------------------------------------------------
@pytest.mark.parametrize("rhythm", ["4-4", "4-7-8", "box", "6-a-minute", "5-5"])
def test_238_the_pacer_is_exact_to_a_tenth_of_a_second_at_each_rhythm(rhythm: str) -> None:
    out = node("breathSession", {"rhythm": rhythm, "seconds": 45, "perMinute": 8})
    assert out["checked"] > 400 and out["mismatches"] == 0
    assert out["tally"]["rhythm"] == rhythm
    _fits("breath", out["tally"])


@pytest.mark.parametrize("per_minute", [6, 8, 11, 14, 17, 20])
def test_238_the_breath_rate_is_within_one_a_minute(per_minute: int) -> None:
    for seed, noise in ((3, 0.0015), (8, 0.003)):
        out = node("breathSession", {"perMinute": per_minute, "seed": seed, "noise": noise})
        assert abs(out["tally"]["per_minute"] - per_minute) <= 1, (per_minute, seed, out["tally"])
        _plain_view("breath", out["view"])


def test_238_no_breathing_gives_no_rate_and_it_says_it_is_not_a_medical_measure() -> None:
    out = node("breathSession", {"still": True, "noise": 0.003})
    assert out["tally"]["per_minute"] == 0 and out["tally"]["breaths"] <= 1
    assert "A practice estimate, not a medical measure." in _texts(out["view"])
    assert not any(w["kind"] == "big" for w in out["view"])


# ---- row 248: the water counter ---------------------------------------------------------------
def test_248_ninety_percent_of_sips_are_counted_and_at_most_one_false_an_hour() -> None:
    counted = truth = 0
    for seed in (1, 2, 3, 4):
        events = node("waterEvents", {"seed": seed})
        out = node("waterDay", {"seconds": 3600, "events": events, "seed": seed, "hidden": 0.3})
        counted += min(out["tally"]["sips"], out["truth"])
        truth += out["truth"]
        assert out["tally"]["sips"] - out["truth"] <= 1, seed
        _fits("water", out["tally"])
        _plain_view("water", out["view"])
    assert counted / truth >= 0.9
    none = node(
        "waterDay",
        {
            "seconds": 3600,
            "seed": 8,
            "events": node("waterEvents", {"sips": 0, "others": 40, "seed": 8}),
        },
    )
    assert none["tally"]["sips"] <= 1  # an hour of cups moved, phones raised and hands to the face


def test_248_every_few_sips_make_a_glass() -> None:
    events = [{"kind": "sip", "at": 20 + 30 * i, "dur": 2.5} for i in range(12)]
    eight = node("waterDay", {"seconds": 400, "events": events})
    four = node("waterDay", {"seconds": 400, "events": events, "setup": {"sips_per_glass": 4}})
    assert eight["tally"]["sips"] == 12 and eight["tally"]["glasses"] == 1
    assert four["tally"]["glasses"] == 3


# ---- row 248: the glass goes to his existing water log, with Undo ------------------------------
class _Docs:
    """Just enough of the Docs port for the wellbeing store (get, transaction)."""

    def __init__(self) -> None:
        self.rows: dict[str, dict[str, Any]] = {}

    async def get(self, path: str) -> dict[str, Any] | None:
        return self.rows.get(path)

    async def transaction(self, fn: Any) -> Any:
        docs = self

        class Tx:
            async def get(self, path: str) -> dict[str, Any] | None:
                return docs.rows.get(path)

            def set(self, path: str, value: dict[str, Any]) -> None:
                docs.rows[path] = value

        return await fn(Tx())


def _water(keyring: Any, clock: list[float]) -> tuple[Any, Any]:
    from jarvis.coach.water import CoachWaterLog
    from jarvis.helpers.nudges.service import NudgeService
    from jarvis.helpers.nudges.store import WellbeingStore

    well = WellbeingStore(cast(Any, _Docs()), keyring)
    noon = datetime(2026, 11, 28, 6, 30, tzinfo=UTC)
    svc = NudgeService(
        store=cast(Any, None),
        well=well,
        gate=cast(Any, None),
        sender=cast(Any, None),
        agenda=cast(Any, None),
        rain=cast(Any, None),
        pending=tuple,
        tz="Asia/Kolkata",
        now=lambda: noon,
    )
    return CoachWaterLog(svc, clock=lambda: clock[0]), well


async def test_248_a_glass_lands_in_his_water_log_and_undo_takes_it_off_once() -> None:
    from r8_fakes import KEY

    from jarvis.keyring import Keyring

    clock = [1000.0]
    log, well = _water(Keyring(KEY), clock)
    first = await log.add_glass("u1")
    await log.add_glass("u1")
    assert (await well.day("u1", "2026-11-28")).water == 2
    assert await log.undo("u2", first) is False  # another owner's id changes nothing
    assert await log.undo("u1", first) is True
    assert await log.undo("u1", first) is False  # spent
    assert (await well.day("u1", "2026-11-28")).water == 1
    late = await log.add_glass("u1")
    clock[0] += 11 * 60  # past the ten minutes
    assert await log.undo("u1", late) is False and (await well.day("u1", "2026-11-28")).water == 2
    assert await log.undo("u1", "wu_not_one") is False


async def test_248_with_no_keyring_the_water_log_is_off_never_in_clear() -> None:
    from jarvis.helpers.nudges.store import WellbeingOff

    log, _ = _water(None, [0.0])
    with pytest.raises(WellbeingOff):
        await log.add_glass("u1")


# ---- row 262: the monitor's reading (D7) ------------------------------------------------------
def test_262_the_engines_reader_reads_these_screens_right_on_95_percent_and_never_wrong() -> None:
    """D's screens are a second, independent set for the `digits` task's reader (builder A's body
    in console-vision-r8.js): it runs as soon as that reader is on the branch (the I1 join)."""
    out = node("bpDisplays", {"n": 240, "seed": 77})
    if "skipped" in out:
        pytest.skip(out["skipped"])
    assert out["right"] / out["n"] >= 0.95, out["misses"]
    assert out["wrong"] == 0, out["misses"]  # a reading it can't be sure of is no reading


def test_262_the_screens_are_drawn_as_asked() -> None:
    screen = node("bpScreen", {"w": 120, "h": 100, "noise": 0, "gradient": 0, "clock": False})
    assert screen["w"] == 120 and screen["h"] == 100 and len(screen["px"]) == 120 * 100
    assert set(screen["px"]) == {185, 45}  # a light screen and dark segments, nothing else
    backlit = node("bpScreen", {"w": 120, "h": 100, "noise": 0, "gradient": 0, "backlit": True})
    assert set(backlit["px"]) == {35, 215}


def test_262_the_reading_rule_is_the_servers_rule() -> None:
    cases = [
        [(128, 0.97), (82, 0.95), (71, 0.9)],
        [(128, 0.97), (82, 0.5), (71, 0.9)],
        [(82, 0.97), (128, 0.95), (71, 0.9)],
        [(128, 0.97), (82, 0.95)],
        [(300, 0.97), (82, 0.95), (71, 0.9)],
        [(119, 0.81), (79, 0.8), (64, 0.99)],
    ]
    for lines in cases:
        js = run_node(
            "console-coach-bp.js", "mod.proposal", [{"value": v, "score": s} for v, s in lines]
        )
        py = bp.proposal_from_digits(lines)
        assert js == (py.model_dump() if py else None), lines


def test_262_the_category_table_is_the_named_published_one() -> None:
    assert bp.SOURCE is not None and bp.SOURCE.publisher == "American Heart Association"
    assert bp.SOURCE.title == "Blood Pressure Categories" and bp.SOURCE.year == 2025
    assert bp.SOURCE.url.startswith("https://www.heart.org/")
    names = [c.name for c in bp.CATEGORIES]
    assert names == [
        "Normal",
        "Elevated",
        "Stage 1 Hypertension (High Blood Pressure)",
        "Stage 2 Hypertension (High Blood Pressure)",
        "Severe Hypertension",
    ]
    assert [c.talk_to_doctor for c in bp.CATEGORIES] == [False, False, False, False, True]

    def cat(s: int, d: int) -> str:
        found = bp.category_of(bp.BpProposal(systolic=s, diastolic=d, pulse=70))
        assert found is not None
        return str(found.name)

    assert cat(118, 76) == "Normal" and cat(125, 79) == "Elevated"
    assert cat(125, 82).startswith("Stage 1") and cat(135, 70).startswith("Stage 1")
    assert cat(150, 85).startswith("Stage 2") and cat(122, 95).startswith("Stage 2")
    assert cat(185, 100) == "Severe Hypertension" and cat(150, 125) == "Severe Hypertension"
    assert cat(180, 120).startswith("Stage 2")  # "higher than 180 and/or higher than 120"
    severe = bp.category_line(bp.CATEGORIES[-1], bp.SOURCE)
    assert severe == (
        "Severe Hypertension (by American Heart Association, Blood Pressure Categories,"
        " 2025). Talk to your doctor about this reading."
    )


def test_262_a_confirmed_reading_shows_its_trend_and_category_and_nothing_more() -> None:
    def reading(s: int, d: int, p: int, at: int) -> bp.BpReading:
        return bp.BpReading(systolic=s, diastolic=d, pulse=p, taken_at=at, source="camera")

    earlier = [reading(130 + i, 85, 70, 1764300000 + i) for i in range(5)]
    earlier += [reading(124, 80, 68, 1764400000 + i) for i in range(4)]
    shown = bp.reading_view(reading(126, 80, 70, 1764500000), earlier)
    assert shown["category"] is not None and shown["category"].startswith("Stage 1 Hypertension")
    assert shown["trend"] == (
        "Your last 5 readings: on average 124/80, pulse 68. The top number is 8"
        " lower than the 5 before, the bottom number 5 lower than them."
    )
    assert shown["note"] == PRACTICE
    assert medical_hits(str(shown["trend"])) == [] and medical_hits(PRACTICE) == []
    one = bp.reading_view(reading(118, 76, 64, 1), [])
    assert one["trend"] == "Your last reading: on average 118/76, pulse 64." and one["category"]
    assert bp.trend_of([]) is None


# ---- row 262: the checklist before a reading (home camera) ------------------------------------
FAULT_ITEM = {
    "lean": "back",
    "feet": "feet",
    "crossed": "legs",
    "arm_low": "arm",
    "arm_hang": "arm",
}


def test_262_each_checklist_item_is_judged_right_on_90_percent_of_synthetic_poses() -> None:
    from jarvis.coach.home.bp_posture import BpPostureCoach

    coach = BpPostureCoach()
    right = dict.fromkeys(("back", "feet", "legs", "arm"), 0)
    n = 400
    for i in range(n):
        rnd = random.Random(i)
        fault = rnd.choice([None, *FAULT_ITEM])
        pts = H.bp_body(
            [fault] if fault else [], noise=0.003, rng=random.Random(1000 + i), vary=rnd
        )
        state = coach.on_result(H.result("pose", {"points": pts}, 0.0), None)
        for item in right:
            right[item] += state.checks[item] == (FAULT_ITEM.get(fault or "") != item)
    assert all(v / n >= 0.9 for v in right.values()), right


@pytest.mark.parametrize("fault", [None, "lean", "feet", "crossed", "arm_low", "moving"])
def test_262_five_minutes_still_and_right_ticks_every_line(fault: str | None) -> None:
    from jarvis.coach.home.bp_posture import BpPostureCoach

    coach = BpPostureCoach()
    state = None
    for r in H.bp_frames(305, [fault] if fault else []):
        state = coach.on_result(r, state)
    tally = coach.summary(state)["tally"]
    _fits("bp-posture", tally)
    assert tally is not None
    if fault is None:
        assert tally["score"] == 100 and all(
            tally[k] for k in ("back", "feet", "legs", "arm", "rested", "still")
        )
    else:
        wrong = {"moving": "still"}.get(fault, FAULT_ITEM.get(fault, ""))
        assert tally[wrong] is False and tally["rested"] is False and tally["score"] < 100


def test_262_standing_up_starts_the_five_minutes_again_and_the_view_is_plain() -> None:
    from jarvis.coach.home.bp_posture import BpPostureCoach

    coach = BpPostureCoach()
    state = None
    for r in H.bp_frames(250, [], stand_at=240):
        state = coach.on_result(r, state)
    for r in H.bp_frames(200, []):
        state = coach.on_result({**r, "t": r["t"] + 251, "at": r["at"] + 251}, state)
    out = coach.summary(state)
    assert out["tally"] is not None and out["tally"]["rested"] is False  # 200 s since he sat again
    rest = next(w for w in out["view"] if w.get("item") == "rested")
    assert rest["state"] == "wait" and rest["hint"].endswith("left")
    _report_ok("bp-posture", out)


def _report_ok(use: str, out: Mapping[str, Any]) -> None:
    """The home view and tally fit the bridge's CoachReport (scalars only, the fixed widgets)."""
    from jarvis.home.ports import CoachReport, parse_event

    report = {
        "id": "ev-1",
        "type": "coach",
        "at": 1764300000.0,
        "camera": "desk_cam",
        "use": use,
        "session": "cs_0123456789ab",
        "track": 0,
        "who": "me",
        "view": out["view"],
        "tally": out["tally"],
    }
    assert isinstance(parse_event(json.dumps(report).encode()), CoachReport)
    _plain_view(use, out["view"])


# ---- row 227: the adaptive seated coach (home camera) -----------------------------------------
@pytest.mark.parametrize("move", sorted(H.SWINGS))
def test_227_reps_within_one_per_set_of_ten_for_each_seated_move(move: str) -> None:
    from jarvis.coach.home.seated import SeatedCoach, SeatedState

    coach = SeatedCoach()
    for seed, noise, period in ((3, 0.002, 2.5), (11, 0.004, 1.8), (5, 0.003, 3.5)):
        state: SeatedState | None = None
        counts = []
        for r in H.seated_session(move, [10, 10], period=period, noise=noise, seed=seed):
            before = state.blocks.get(move) if state else None
            state = coach.on_result(r, state)
            after = state.blocks.get(move)
            if after is not None and after != before:
                counts.append(after.reps - (before.reps if before else 0))
        assert len(counts) == 2 and all(abs(c - 10) <= 1 for c in counts), (move, seed, counts)
        out = coach.summary(state)
        assert out["tally"] is not None and out["tally"]["move"] == move
        _fits("seated", out["tally"])
        _report_ok("seated", out)


def test_227_the_next_set_adapts_fewer_after_an_unfinished_set_more_after_two_easy() -> None:
    from jarvis.coach.home.seated import TARGET0, SeatedCoach, SeatedState

    coach = SeatedCoach()

    def targets(sets: list[int], slow: list[float]) -> list[int]:
        state: SeatedState | None = None
        seen: list[int] = []
        for r in H.seated_session("arm_raise", sets, slow_down=slow):
            before = state.blocks.get("arm_raise") if state else None
            state = coach.on_result(r, state)
            after = state.blocks.get("arm_raise")
            if after is not None and after != before:
                seen.append(after.target)
        return seen

    assert TARGET0 == 10
    assert targets([6], []) == [8]  # unfinished: fewer
    assert targets([10, 10], []) == [10, 12]  # two easy sets: more
    assert targets([10, 10], [0.0, 1.0]) == [10, 10]  # the second slowed down: not easy
    assert targets([10, 10, 12], []) == [10, 12, 12]  # one easy set at the new target: same


def test_227_a_second_move_starts_its_own_sets() -> None:
    from jarvis.coach.home.seated import SeatedCoach

    coach = SeatedCoach()
    state = None
    frames = list(H.seated_session("knee_lift", [10]))
    tail = frames[-1]["t"] + 1.0
    for r in frames:
        state = coach.on_result(r, state)
    for r in H.seated_session("neck_turn", [10]):
        state = coach.on_result({**r, "t": r["t"] + tail, "at": r["at"] + int(tail)}, state)
    assert state is not None
    assert {k: (b.sets, b.reps) for k, b in state.blocks.items()} == {
        "knee_lift": (1, 10),
        "neck_turn": (1, 10),
    }


def test_227_and_262_say_stop_and_practice_and_nothing_medical() -> None:
    from jarvis.coach.home import bp_posture, seated

    assert seated.STOP == STOP and seated.PRACTICE == PRACTICE and bp_posture.PRACTICE == PRACTICE
    assert f"{PRACTICE} {STOP}" in _texts(seated.SeatedCoach().summary(None)["view"])
    for words in (
        seated.WORDS.values(),
        seated.NAMES.values(),
        bp_posture.TEXT.values(),
        bp_posture.HINT.values(),
    ):
        assert [w for w in words if medical_hits(w)] == []


# ---- row 268: hand and finger exercises -------------------------------------------------------
@pytest.mark.parametrize("exercise", ["open_close", "finger_tap", "thumb_to_finger"])
def test_268_counts_within_one_per_ten_for_each_exercise(exercise: str) -> None:
    for opts in (
        {},
        {"peak": 50, "rest": 10, "noise": 0.003, "seed": 4},
        {"period": 1.2, "second": True, "side": "left", "seed": 9},
    ):
        out = node("rehabSession", {"exercise": exercise, **opts})
        tally = out["tally"]
        assert tally["exercise"] == exercise  # the one he does, without being told
        assert abs(tally["reps"] - out["truth"]["reps"]) <= 1, (exercise, opts, tally)
        _fits("hand-rehab", tally)
        _plain_view("hand-rehab", out["view"])
        assert STOP in _texts(out["view"])  # during


RANGES = {"open_close": ((70, 0), (55, 5), (50, 10)), "finger_tap": ((70, 0), (50, 10), (35, 5))}


@pytest.mark.parametrize("exercise", sorted(RANGES))
def test_268_range_of_motion_within_ten_degrees(exercise: str) -> None:
    for peak, rest in RANGES[exercise]:
        opts = {"exercise": exercise, "peak": peak, "rest": rest, "noise": 0.003}
        out = node("rehabSession", opts)
        assert abs(out["tally"]["range_deg"] - out["truth"]["range"]) <= 10, (opts, out["tally"])


def test_268_stop_if_it_hurts_is_shown_before_the_first_hand() -> None:
    before = node("emptySummary", "console-coach-handrehab.js")
    assert STOP in _texts(before["view"]) and PRACTICE in _texts(before["view"])


# ---- row 276: reach and grasp -----------------------------------------------------------------
def test_276_reach_time_within_150_ms() -> None:
    for seed, noise in ((31, 0.002), (5, 0.003), (12, 0.002)):
        out = node("reachSession", {"seed": seed, "noise": noise})
        assert out["phase"] == "over" and len(out["trials"]) == 10
        for measured, truth in zip(out["trials"], out["truths"], strict=True):
            assert measured is not None and abs(measured - truth) <= 150, (seed, measured, truth)
        _fits("reach-grasp", out["tally"])
        _plain_view("reach-grasp", out["view"])


def test_276_the_same_sequence_always_gives_the_same_score_and_a_miss_scores_nothing() -> None:
    one = node("reachSession", {"seed": 7})
    two = node("reachSession", {"seed": 7})
    assert one["tally"] == two["tally"] and one["trials"] == two["trials"]
    missed = node("reachSession", {"seed": 7, "skip": [4]})
    assert missed["trials"][3] is None and missed["tally"]["reaches"] == 9
    assert missed["tally"]["score"] < one["tally"]["score"]
    assert "Practice score, not a clinical rating." in _texts(one["view"])


# ---- every desk coach: before anything is seen ------------------------------------------------
@pytest.mark.parametrize("use, name", sorted(USE_MODULES.items()))
def test_every_coach_has_a_plain_view_before_its_first_result(use: str, name: str) -> None:
    out = node("emptySummary", name)
    assert out["tally"] is None
    _plain_view(use, out["view"])
