# tests/test_r8_seams.py -- R8 I0 seams (docs/plans/r8-vision.md section 7.1, S1-S23), the
# server's half: the Result contract (`hands`, `pose` v2), the assets' `r8-1` release, the
# use-case registry and its tallies, the sealed coach stores, the Privacy rows, the routes, the
# brain's tool, the ports, the camera spots, the Vitals camera lines, the bridge's two routes,
# the posture nudge kind, the settings, the wiring slots and the version. The console's half is
# tests/test_r8_console_seams.py; the not-medical scan is tests/test_r8_not_medical.py.
from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from jarvis.vision.results import BODIES_MAX, HAND_POINTS, POSE_POINTS, TASKS, parse_result

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src" / "jarvis"
STATIC = SRC / "api" / "static"


def _result(task: str, data: dict[str, Any]) -> dict[str, Any]:
    return {
        "task": task,
        "v": 1,
        "at": 1764300000,
        "ms": 30,
        "device": "browser",
        "ok": True,
        "data": data,
        "quality": {"light": 0.5, "sharp": 0.5},
    }


def _hand(side: str = "left", n: int = HAND_POINTS, **point: float) -> dict[str, Any]:
    p = {"x": 0.4, "y": 0.5, "z": -0.02, **point}
    return {"side": side, "score": 0.93, "points": [dict(p) for _ in range(n)]}


def _body(n: int = POSE_POINTS) -> list[dict[str, float]]:
    return [{"x": 0.5, "y": 0.4, "z": -0.1, "visibility": 0.9} for _ in range(n)]


# ---- S1 · the Result contract: `hands` (v1) and `pose` v2 ---------------------------------------
def test_hands_and_digits_join_the_kept_tasks() -> None:
    assert TASKS == ("text", "code", "objects", "pose", "quality", "hands", "digits")
    assert HAND_POINTS == 21 and POSE_POINTS == 33 and BODIES_MAX == 4


def test_a_hands_result_is_two_hands_of_21_points_at_most() -> None:
    two = _result("hands", {"hands": [_hand("left"), _hand("right")]})
    assert parse_result(two) is not None
    assert parse_result(_result("hands", {"hands": []})) is not None  # no hand in view
    for bad in (
        {"hands": [_hand(), _hand(), _hand()]},  # a third hand
        {"hands": [_hand(n=20)]},  # a hand is all 21 points or none
        {"hands": [_hand(n=22)]},
        {"hands": [_hand(side="both")]},
        {"hands": [_hand(x=3.0)]},  # outside the frame's range
        {"hands": [{**_hand(), "label": "Akash"}]},  # nothing else rides along
        {"hands": [_hand()], "box": [0, 0, 1, 1]},
        {"hands": [{**_hand(), "score": 1.5}]},
    ):
        assert parse_result(_result("hands", bad)) is None, bad


def _bodies(*who: str) -> list[dict[str, Any]]:
    return [{"track": n, "who": w, "points": _body()} for n, w in enumerate(who)]


def test_pose_v2_carries_everyone_in_view_with_a_track_and_who() -> None:
    # the owner's D6: everyone in view by default; `who` is "", "me" or a consented fp_ id
    four = _result("pose", {"bodies": _bodies("me", "fp_0123456789ab", "", "")})
    assert parse_result(four) is not None
    assert parse_result(_result("pose", {"bodies": []})) is not None  # nobody in view
    assert parse_result(_result("pose", {"points": _body()})) is not None  # R7's v1 still fits
    for bad in (
        {"bodies": _bodies("", "", "", "", "")},  # at most four bodies
        {"bodies": _bodies("Shruti")},  # never a name
        {"bodies": [{"track": 0, "who": "", "points": _body()}] * 2},  # one track, one body
        {"bodies": [{"track": True, "who": "", "points": _body()}]},
        {"bodies": [{"track": 64, "who": "", "points": _body()}]},
        {"bodies": _bodies("me"), "points": _body()},  # v1 or v2, never both
        {"bodies": [{**_bodies("")[0], "face": [0.1, 0.2]}]},  # nothing rides along
        {"points": _body(66)},
    ):
        assert parse_result(_result("pose", bad)) is None, bad


def test_digits_are_a_displays_lines_and_nothing_else() -> None:
    reading = {"lines": [{"value": 128, "score": 0.97}, {"value": 82, "score": 0.95},
                         {"value": 71, "score": 0.9}]}  # fmt: skip
    assert parse_result(_result("digits", reading)) is not None
    for bad in (
        {"lines": [{"value": 1000, "score": 0.9}]},
        {"lines": [{"value": 12.5, "score": 0.9}]},
        {"lines": [{"value": 1, "score": 0.9}] * 5},
        {"lines": [{"value": 120, "score": 0.9, "label": "systolic"}]},
        {"lines": [], "text": "128/82"},
    ):
        assert parse_result(_result("digits", bad)) is None, bad


# ---- S15 · the posture nudge kind and its caps ---------------------------------------------------
def test_the_posture_nudge_is_one_new_kind_in_every_table() -> None:
    from typing import get_args

    from jarvis.alerts import R8_ALERT_KINDS, AlertKind
    from jarvis.buildbook.plain import ALERT_WORDS
    from jarvis.helpers import kinds
    from jarvis.helpers.nudges.models import DEFAULTS, LABEL, kind_of
    from jarvis.helpers.nudges.words import describe
    from jarvis.notify.policy import DAYTIME_RING_KINDS, EPHEMERAL_KINDS
    from jarvis.notify.ports import DEFAULT_URGENCY
    from jarvis.notify.storm import NUDGE_KINDS
    from jarvis.webpush.service import TARGETS

    assert R8_ALERT_KINDS == ("nudge_posture",) and "nudge_posture" in get_args(AlertKind)
    assert "nudge_posture" in kinds.NUDGE_KINDS and "nudge_posture" in kinds.KINDS_OF["nudges"]
    assert kinds.DEFAULT_CAPS["nudge_posture"] == kinds.POSTURE_PER_DAY == 8
    assert kinds.POSTURE_PER_HOUR == 3
    assert DEFAULTS["nudge_posture"].on is False  # off until he switches it on
    assert DEFAULT_URGENCY["nudge_posture"] == "important"
    assert "nudge_posture" in DAYTIME_RING_KINDS and "nudge_posture" in EPHEMERAL_KINDS
    assert "nudge_posture" in NUDGE_KINDS and "nudge_posture" in TARGETS
    assert "nudge_posture" in ALERT_WORDS and LABEL["nudge_posture"] == "Sit up straight"
    assert kind_of("posture") == kind_of("slouching") == "nudge_posture"
    line = describe("nudge_posture", DEFAULTS["nudge_posture"])
    assert line.startswith("Sit up straight: off") and "at most 3 an hour" in line
    js = (STATIC / "console-alerts.js").read_text(encoding="utf-8")
    assert "['nudge_posture', " in js


# ---- S6 · the use-case registry and every tally --------------------------------------------------
NOON = 1764300000  # 28 Nov 2026, 08:50 IST


def _tally(**fields: Any) -> dict[str, Any]:
    return {"started_at": NOON, "ended_at": NOON + 600, **fields}


def test_the_registry_covers_all_34_rows_and_the_owners_cameras() -> None:
    from jarvis.coach import usecases as u
    from jarvis.vision.results import TASKS as ENGINE

    rows = {c.row for c in u.USE_CASES} | set(u.ROWS_WITHOUT_USE_CASE)
    assert (
        len(u.R8_ROWS) == 14 and len(u.R81_ROWS) == 20 and rows == set(u.R8_ROWS) | set(u.R81_ROWS)
    )
    assert len({c.id for c in u.USE_CASES}) == len(u.USE_CASES) == 29
    import re

    for c in u.USE_CASES:
        assert re.fullmatch(u.USE_ID, c.id) and set(c.tasks) <= set(ENGINE), c.id
        assert c.module.endswith(".js") == (c.source != "home"), c.id
    # the owner's D3: the whole-body desk rows look through the home camera, on the home laptop
    home = sorted(c.row for c in u.USE_CASES if c.source == "home")
    assert home == [181, 182, 227, 262]
    webcam = sorted(c.row for c in u.USE_CASES if c.source == "browser")
    assert webcam == [224, 238, 248, 268, 276]
    assert {c.source for c in u.USE_CASES if c.release == "R8.1"} == {"phone"}
    assert u.VIEW_KINDS == (
        "big",
        "line",
        "tip",
        "timer",
        "pacer",
        "targets",
        "checklist",
        "bar",
        "paused",
    )
    js = (STATIC / "console-vision.js").read_text(encoding="utf-8")
    assert "const VIEW_KINDS = Object.freeze(['" + "', '".join(u.VIEW_KINDS) + "']);" in js


def test_a_tally_that_does_not_fit_is_dropped_never_repaired() -> None:
    from jarvis.coach.usecases import parse_tally

    good = _tally(slouch_spans=2, slouch_seconds=130.5, nudges=1, upright=82)
    assert parse_tally("posture", good) is not None
    for use, bad in (
        ("posture", {**good, "points": [[0.1, 0.2]]}),  # a body point never rides along
        ("posture", {**good, "upright": 101}),
        ("posture", {**good, "nudges": "1"}),
        ("posture", {**good, "ended_at": NOON - 1}),
        ("reps", _tally(exercise="deadlift", sets=1, reps=10, down_s=1.0, up_s=1.0)),
        (
            "bp-posture",
            _tally(back=1, feet=True, legs=True, arm=True, rested=True, still=True, score=90),
        ),  # fmt: skip
        ("space-check", _tally()),  # row 223 keeps nothing
        ("nobody", good),
    ):
        assert parse_tally(use, bad) is None, (use, bad)
    day = _tally(segments=[{"kind": "desk", "start": NOON, "end": NOON + 300}])
    assert parse_tally("activity", day) is not None
    assert (
        parse_tally("activity", _tally(segments=[{"kind": "sleeping", "start": 1, "end": 2}]))
        is None
    )


def test_the_registry_lists_what_the_panes_need() -> None:
    from jarvis.coach.usecases import listing

    rows = {r["id"]: r for r in listing()}
    assert rows["posture"]["source"] == "home" and rows["posture"]["module"] == ""
    assert rows["reaction-game"]["module"] == "console-coach-reaction.js"
    assert rows["space-check"]["keeps"] is False and rows["meal"]["spot"] == "table"


# ---- S27 · people and guests (D6 final: everyone's results are saved) ----------------------------
def _clock() -> Any:
    from datetime import UTC, datetime

    return lambda: datetime(2026, 11, 28, 3, 20, tzinfo=UTC)


KEY = bytes(range(11, 43))


async def test_an_unknown_body_becomes_guest_n_of_its_session_and_can_be_renamed_or_merged() -> (
    None
):
    from jarvis.coach.people import PeopleRefused, PeopleStore, new_session
    from jarvis.keyring import Keyring
    from jarvis.storage.docs import MemoryDocs

    docs = MemoryDocs()
    people = PeopleStore(docs, Keyring(KEY), now=_clock())
    one, two = new_session(), new_session()
    g1 = await people.guest_for("u1", one, 0)
    g2 = await people.guest_for("u1", one, 3)
    assert await people.guest_for("u1", one, 0) == g1  # one guest per body of a session
    g3 = await people.guest_for("u1", two, 0)
    labels = {g.id: g.label for g in await people.guests("u1")}
    assert (labels[g1], labels[g2], labels[g3]) == ("Guest 1", "Guest 2", "Guest 1")
    assert (await people.rename("u1", g2, "Shruti's friend")).label == "Shruti's friend"
    await people.merge("u1", g3, g1)
    await people.merge("u1", g1, "me")
    assert await people.resolve("u1", g3) == "me"  # merged twice: it follows
    with pytest.raises(PeopleRefused):
        await people.rename("u1", g2, "<script>")
    with pytest.raises(PeopleRefused):
        await people.merge("u1", g2, "Akash")
    raw = str(await docs.get("jarvis_coach_people/u1"))
    assert "Guest" not in raw and "friend" not in raw  # sealed under `coach`


async def test_no_keyring_keeps_nothing_in_clear() -> None:
    from jarvis.coach.people import CoachOff, PeopleStore, new_session
    from jarvis.coach.store import CoachStore
    from jarvis.storage.docs import MemoryDocs

    with pytest.raises(CoachOff):
        await PeopleStore(MemoryDocs(), None, now=_clock()).guest_for("u1", new_session(), 0)
    with pytest.raises(CoachOff):
        await CoachStore(MemoryDocs(), None, now=_clock()).keep(
            "u1", "posture", "me", new_session(), {}
        )


# ---- S7 · the sealed coach stores ----------------------------------------------------------------
async def test_tallies_are_kept_sealed_for_everyone_and_deleted_per_person() -> None:
    from jarvis.coach.people import new_session
    from jarvis.coach.store import CoachStore, Dropped
    from jarvis.keyring import Keyring
    from jarvis.storage.docs import MemoryDocs

    docs = MemoryDocs()
    store = CoachStore(docs, Keyring(KEY), now=_clock())
    s = new_session()
    t = _tally(slouch_spans=2, slouch_seconds=130.5, nudges=1, upright=82)
    await store.keep("u1", "posture", "me", s, t)
    await store.keep("u1", "posture", "fp_0123456789ab", s, t)
    await store.keep("u1", "posture", "gst_0123456789ab", s, t)
    with pytest.raises(Dropped):
        await store.keep("u1", "posture", "Shruti", s, t)  # never a name
    with pytest.raises(Dropped):
        await store.keep("u1", "posture", "me", s, {**t, "frame": "iVBOR"})
    assert await store.count("u1") == 3
    assert [i["who"] for i in await store.list("u1", who="me")] == ["me"]
    raw = str(
        await docs.query(
            __import__("jarvis.storage.docs", fromlist=["Query"]).Query("jarvis_coach_results")
        )
    )
    assert "slouch" not in raw and "fp_0123456789ab" not in raw  # sealed: not even who
    assert await store.delete_who("u1", lambda w: w.startswith("gst_")) == 1
    assert await store.count("u1") == 2


async def test_a_blood_pressure_reading_is_kept_only_confirmed() -> None:
    from jarvis.coach.people import new_session
    from jarvis.coach.store import BP_USE, CoachStore, Dropped
    from jarvis.keyring import Keyring
    from jarvis.storage.docs import MemoryDocs

    store = CoachStore(MemoryDocs(), Keyring(KEY), now=_clock())
    reading = {"systolic": 128, "diastolic": 82, "pulse": 71, "taken_at": NOON, "source": "camera"}
    assert (await store.keep("u1", BP_USE, "me", new_session(), reading))["tally"][
        "systolic"
    ] == 128
    with pytest.raises(Dropped):
        await store.keep(
            "u1", BP_USE, "me", new_session(), {**reading, "systolic": 70, "diastolic": 90}
        )


async def test_his_routines_are_joint_angles_only() -> None:
    from pydantic import ValidationError

    from jarvis.coach.store import RoutineStore
    from jarvis.keyring import Keyring
    from jarvis.storage.docs import MemoryDocs

    routines = RoutineStore(MemoryDocs(), Keyring(KEY), now=_clock())
    await routines.put("u1", "dance-1", {"kind": "dance", "angles": [[90.0, 45.5], [91.0, 44.0]]})
    got = await routines.get("u1", "dance-1")
    assert got is not None and got.angles[1] == (91.0, 44.0)
    with pytest.raises(ValidationError):
        await routines.put(
            "u1", "dance-2", {"kind": "dance", "angles": [[0.4, 0.5, 0.1]] * 2, "points": []}
        )
    with pytest.raises(ValueError):
        await routines.put("u1", "../vault", {"kind": "dance", "angles": [[1.0]]})


def test_the_coach_key_purpose_is_its_own() -> None:
    from jarvis.keyring import PURPOSES, Keyring

    assert PURPOSES[-1] == "coach" and len(PURPOSES) == len(set(PURPOSES)) == 28
    ring = Keyring(KEY)
    blob = ring.cipher("coach").encrypt(b"x", aad="coach_results/u/v1")
    with pytest.raises(Exception):  # noqa: B017 - the vision key never opens a coach blob
        ring.cipher("vision").decrypt(blob, aad="coach_results/u/v1")


# ---- S8 · Privacy's "Health and fitness" ---------------------------------------------------------
async def test_privacy_has_three_rows_and_each_deletes_only_its_people() -> None:
    from jarvis.coach.people import PeopleStore, new_session
    from jarvis.coach.privacy import SECTION, coach_privacy
    from jarvis.coach.store import CoachStore
    from jarvis.keyring import Keyring
    from jarvis.storage.docs import MemoryDocs

    docs, ring = MemoryDocs(), Keyring(KEY)
    store, people = CoachStore(docs, ring, now=_clock()), PeopleStore(docs, ring, now=_clock())
    s, t = new_session(), _tally(sips=4, glasses=1)
    for who in ("me", "fp_0123456789ab", "gst_0123456789ab", "gst_0123456789ac"):
        await store.keep("u1", "water", who, s, t)
    rows = coach_privacy(store, people)
    assert [r.id for r in rows] == ["coach_me", "coach_people", "coach_guests"]
    views = [await r.describe("u1") for r in rows]
    assert {v.section for v in views} == {SECTION} and [v.count for v in views] == [1, 1, 2]
    assert all("Never kept: a camera frame" in v.note for v in views)
    assert len((await rows[2].export("u1"))["results"]) == 2
    assert await rows[2].delete("u1") == 2 and [(await r.describe("u1")).count for r in rows] == [
        1,
        1,
        0,
    ]


# ---- S10 · the brain's tool ----------------------------------------------------------------------
def test_the_coach_tool_is_read_only_filed_under_health_and_private_on_telegram() -> None:
    import json
    from fnmatch import fnmatchcase

    from jarvis.coach.store import CoachStore
    from jarvis.coach.tools import NAME, results_tool
    from jarvis.core.guardrails import ActionRisk
    from jarvis.storage.docs import MemoryDocs
    from jarvis.telegram.rules import PRIVATE_PATTERNS

    async def names(uid: str) -> dict[str, str]:
        return {"me": "you"}

    tool = results_tool(CoachStore(MemoryDocs(), None, now=_clock()), names)
    assert tool.name == NAME == "coach_results" and tool.risk == ActionRisk.READ_ONLY
    register = json.loads((SRC / "skills" / "catalogue.json").read_text(encoding="utf-8"))
    health = next(s for s in register["skills"] if s["id"] == "health")
    assert any("coach_*" in g["tools"] for g in health["groups"])
    assert any(fnmatchcase(NAME, p) for p in PRIVATE_PATTERNS)
    with pytest.raises(ValueError):
        tool.check({"who": "Shruti"})  # type: ignore[misc]


# ---- S25 · the tracking target (D6) --------------------------------------------------------------
async def test_track_me_everyone_or_a_name_only_through_consented_faces() -> None:
    from jarvis.coach.target import EVERYONE, TargetStore, TrackTarget, phrase_target, resolve_name
    from jarvis.storage.docs import MemoryDocs

    class Faces:
        async def find(self, uid: str, name: str) -> str | None:
            return "fp_0123456789ab" if name.lower() == "shruti" else None

    assert phrase_target("Jarvis, track me.") == TrackTarget(kind="me")
    assert phrase_target("track everyone") == EVERYONE
    assert phrase_target("Jarvis track Shruti") == "shruti"
    assert phrase_target("turn on the lights") is None
    assert await resolve_name("u1", "shruti", Faces()) == TrackTarget(
        kind="person", person="fp_0123456789ab"
    )
    assert (
        await resolve_name("u1", "ravi", Faces())
        == "I don't know Ravi yet: enrol their face first."
    )
    store = TargetStore(MemoryDocs(), now=_clock())
    assert await store.get("u1") == EVERYONE  # the default
    await store.set("u1", TrackTarget(kind="me"))
    assert (await store.get("u1")).kind == "me"
    with pytest.raises(ValueError):
        TrackTarget(kind="person")  # a person target names one enrolled id
    with pytest.raises(ValueError):
        TrackTarget(kind="person", person="Shruti")


# ---- S26 · the blood-pressure reading (D7) -------------------------------------------------------
def test_the_camera_reading_is_a_proposal_until_he_confirms_it() -> None:
    from pydantic import ValidationError

    from jarvis.coach import bp

    assert bp.proposal_from_digits([(128, 0.97), (82, 0.95), (71, 0.9)]) == bp.BpProposal(
        systolic=128, diastolic=82, pulse=71
    )
    assert bp.proposal_from_digits([(128, 0.97), (82, 0.5), (71, 0.9)]) is None  # never a guess
    assert bp.proposal_from_digits([(128, 0.97), (82, 0.95)]) is None
    assert bp.proposal_from_digits([(82, 0.97), (128, 0.95), (71, 0.9)]) is None
    with pytest.raises(ValidationError):
        bp.BpConfirm.model_validate({"confirmed": False, "reading": {}})
    # the category table ships empty: no category is shown until D fills it from a named source
    assert bp.CATEGORIES == () and bp.SOURCE is None
    assert bp.category_of(bp.BpProposal(systolic=128, diastolic=82, pulse=71)) is None
    row = bp.BpCategory("Example", 120, 129, 0, 79, "and", True)
    src = bp.Source("A guideline", "A publisher", 2025, "https://example.org/guideline")
    assert bp.category_line(row, src) == (
        "Example (by A publisher, A guideline, 2025). Talk to your doctor about this reading."
    )


# ---- S14, S24 · the bridge's two routes, the home camera's reports and the coach state -----------
def _report(**over: Any) -> dict[str, Any]:
    base = {
        "id": "ev-1",
        "type": "coach",
        "at": 1764300000.0,
        "camera": "desk_cam",
        "use": "posture",
        "session": "cs_0123456789ab",
        "track": 0,
        "who": "me",
        "view": [{"kind": "big", "n": 3, "word": "slouches"}],
        "tally": {"started_at": 1764300000, "ended_at": 1764300600, "slouch_spans": 3},
    }
    return {**base, **over}


def test_a_coach_report_holds_views_and_tallies_and_nothing_like_a_picture() -> None:
    import json

    from jarvis.home.ports import (
        BRIDGE_ROUTES,
        CAMERA_CHECK_ROUTE,
        EVENT_TYPES,
        SCREENTIME_ROUTE,
        CoachReport,
        EventRejected,
        parse_event,
    )

    assert {SCREENTIME_ROUTE, CAMERA_CHECK_ROUTE} <= BRIDGE_ROUTES and len(BRIDGE_ROUTES) == 13
    assert EVENT_TYPES[-1] == "coach"
    assert isinstance(parse_event(json.dumps(_report()).encode()), CoachReport)
    for bad in (
        _report(view=[{"kind": "frame", "b64": "iVBOR"}]),  # not a widget kind
        _report(view=[{"kind": "big", "points": [[0.1, 0.2]]}]),  # no nested numbers
        _report(tally={"points": [[0.1, 0.2, 0.3]]}),
        _report(who="Shruti"),  # never a name
        _report(session="today"),
        _report(snapshot="/9j/4AAQ"),
        _report(view=[{"kind": "big", "word": "x" * 121}]),
    ):
        with pytest.raises(EventRejected):
            parse_event(json.dumps(bad).encode())


def test_the_coach_state_rides_the_push_and_never_carries_the_alarm() -> None:
    from pydantic import ValidationError

    from jarvis.home.ports import ArmState, BridgeState, CoachState

    coach = CoachState(rev=3, uses={"desk_cam": ("posture", "activity")}, target="me")
    state = BridgeState(arm=ArmState(armed=True, rev=7)).merged(BridgeState(coach=coach))
    assert state.coach == coach and state.arm is not None and state.arm.armed  # untouched
    assert "arm" not in CoachState.model_fields and "armed" not in CoachState.model_fields
    with pytest.raises(ValidationError):
        CoachState(rev=1, target="person")
    with pytest.raises(ValidationError):
        CoachState(rev=1, uses={"desk_cam": ("posture", "activity", "seated", "bp-posture", "x")})


async def test_the_three_r8_plugins_are_registered_stubs_that_refuse_in_plain_words() -> None:
    from pathlib import Path as P

    from jarvis.home.ports import HomeRefused
    from jarvis.homebridge.plugins import PLUGIN_ENV_KEYS, BridgeContext, check_routes
    from jarvis.homebridge.r8_stub import NOT_BUILT
    from jarvis.homebridge.registry import PLUGINS

    ctx = BridgeContext(env={}, data_dir=P("/tmp"), events=None)  # type: ignore[arg-type]
    plugins = [f(ctx) for f in PLUGINS[3:]]
    assert [p.name for p in plugins] == ["homevision", "activitywatch", "camcheck"]
    check_routes(plugins)
    assert plugins[0].routes() == () and plugins[0].tasks() == ()  # runs nothing at I0
    for plugin in plugins[1:]:
        (route,) = plugin.routes()
        with pytest.raises(HomeRefused) as refused:
            await route.handler({}, {})
        assert refused.value.code == "not_built" and refused.value.message == NOT_BUILT
    assert {"HOMEVISION_RTSP_URL", "HOMEVISION_CAMERA", "AW_URL"} <= PLUGIN_ENV_KEYS
    assert "HA_TOKEN" not in PLUGIN_ENV_KEYS


# ---- S9 · the coaches' routes --------------------------------------------------------------------
def _coach_client(*, sealed: bool = True) -> Any:
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from jarvis.api import coach as api
    from jarvis.api.auth import require_auth
    from jarvis.api.identity import current_user
    from jarvis.coach.people import PeopleStore
    from jarvis.coach.store import CoachStore, RoutineStore
    from jarvis.coach.target import TargetStore
    from jarvis.keyring import Keyring
    from jarvis.storage.docs import MemoryDocs

    docs, ring = MemoryDocs(), Keyring(KEY) if sealed else None
    app = FastAPI()
    app.include_router(api.router)
    app.dependency_overrides[require_auth] = lambda: None
    app.dependency_overrides[current_user] = lambda: "u1"
    now = _clock()
    app.state.coach = api.CoachApp(
        CoachStore(docs, ring, now=now), PeopleStore(docs, ring, now=now),
        TargetStore(docs, now=now), RoutineStore(docs, ring, now=now),
    )  # fmt: skip
    return TestClient(app)


def test_the_routes_keep_everyones_tallies_and_an_unknown_body_as_a_guest() -> None:
    c = _coach_client()
    assert c.get("/v1/coach/usecases").json()["views"][0] == "big"
    t = _tally(sips=2, glasses=1)
    mine = c.post("/v1/coach/results", json={"use": "water", "session": "cs_0123456789ab",
                                              "who": "me", "tally": t})  # fmt: skip
    guest = c.post("/v1/coach/results", json={"use": "water", "session": "cs_0123456789ab",
                                               "who": "", "track": 1, "tally": t})  # fmt: skip
    assert mine.status_code == guest.status_code == 201
    assert guest.json()["kept"]["who"].startswith("gst_")
    assert [g["label"] for g in c.get("/v1/coach/people").json()["guests"]] == ["Guest 1"]
    bad = c.post(
        "/v1/coach/results",
        json={
            "use": "water",
            "session": "cs_0123456789ab",
            "who": "me",
            "tally": {**t, "frame": "iVBOR"},
        },
    )
    assert bad.status_code == 422 and bad.json()["error"] == "dropped"
    assert len(c.get("/v1/coach/results").json()["results"]) == 2
    assert c.get("/v1/coach/results?who=Shruti").status_code == 422
    assert c.delete("/v1/coach/people/me").status_code == 501  # the passkey's path, at I1
    assert mine.headers["cache-control"] == "no-store"


def test_a_reading_is_stored_only_confirmed_and_the_target_by_kind() -> None:
    c = _coach_client()
    reading = {"systolic": 128, "diastolic": 82, "pulse": 71, "taken_at": NOON, "source": "camera"}
    ok = c.post("/v1/coach/bp/readings", json={"confirmed": True, "reading": reading,
                                                "session": "cs_0123456789ab"})  # fmt: skip
    assert ok.status_code == 201
    no = c.post("/v1/coach/bp/readings", json={"confirmed": False, "reading": reading,
                                                "session": "cs_0123456789ab"})  # fmt: skip
    assert no.status_code == 422
    assert c.get("/v1/coach/target").json()["target"] == {"kind": "all", "person": None}
    assert c.put("/v1/coach/target", json={"kind": "me"}).json()["target"]["kind"] == "me"
    assert c.put("/v1/coach/target", json={"name": "Shruti"}).status_code == 501  # Faces at I1
    assert c.get("/v1/coach/live?use=posture").status_code == 501  # the home laptop's, J


def test_without_a_key_nothing_is_kept_and_it_says_so() -> None:
    c = _coach_client(sealed=False)
    r = c.post(
        "/v1/coach/results",
        json={
            "use": "water",
            "session": "cs_0123456789ab",
            "who": "me",
            "tally": _tally(sips=1, glasses=0),
        },
    )
    assert r.status_code == 409 and r.json()["error"] == "not_sealed"


# ---- S12 · camera spots (B's skeleton) and S13 · Vitals' camera lines ----------------------------
def test_the_off_switches_and_never_rooms() -> None:
    from pydantic import ValidationError

    from jarvis.camera.spots import Camera, Room, Spots, coach_allowed, looking_allowed

    desk = Camera(id="desk_cam", kind="home", source="home", label="Desk camera", room="study")
    phone = Camera(id="tripod", kind="device", source="phone", label="Workout phone", room="bed")
    spots = Spots(
        cameras=(desk, phone),
        rooms=(Room(id="study", label="Study"), Room(id="bed", label="Bedroom", never=True)),
    )
    assert looking_allowed(spots, "desk_cam") and not coach_allowed(spots, "tripod")
    assert not looking_allowed(spots.model_copy(update={"all_off": True}), "desk_cam")
    assert not looking_allowed(spots, "nobody")
    with pytest.raises(ValidationError):
        Camera(id="desk_cam", kind="home", source="browser", label="x")
    with pytest.raises(ValidationError):
        Spots(cameras=(desk,))  # its room isn't one of his


def test_vitals_has_one_line_per_camera_amber_after_a_day_unseen() -> None:
    from jarvis.coach.ports import CameraLine
    from jarvis.vitals.own import camera_item
    from jarvis.vitals.service import reserved
    from jarvis.vitals.words import words_for

    now = 1764300000.0
    seen = camera_item(CameraLine("desk_cam", "Desk camera", "home", True, now - 180, 1.0), now)
    assert seen is not None and seen.base == ("ok", "") and seen.provider.id == "camera_desk_cam"
    assert seen.provider.note == "Seen 3 min ago, 1 frame a second."
    old = camera_item(CameraLine("tripod", "Phone", "phone", True, now - 90_000, 15.0), now)
    assert old is not None and old.base[0] == "amber"
    off = camera_item(CameraLine("tripod", "Phone", "phone", False, None, None), now)
    assert off is not None and off.base == ("ok", "is switched off")
    assert camera_item(CameraLine("Bad Id!", "x", "phone", True, now, 1.0), now) is None
    assert words_for("camera_desk_cam", "Desk camera")[0].startswith("If this stops")
    assert reserved("camera_desk_cam") and reserved("screen_time")  # never a manual record


# ---- S4 · the r8-1 release, S5 · the fetch-and-hash workflow ------------------------------------
def test_the_r8_release_lists_its_two_models_not_installed() -> None:
    import json

    from jarvis.vision import assets

    assert assets.R8_RELEASE == "r8-1"
    assert assets.R8_FILES == {"hands": ("hand_landmarker.task",),
                               "pose_full": ("pose_landmarker_full.task",)}  # fmt: skip
    doc = json.loads((assets.FOLDER / "r8-1" / "MANIFEST.json").read_text(encoding="utf-8"))
    assert doc["release"] == "r8-1" and doc["files"] == {}
    assert set(doc["models"]) == {assets.HAND_MODEL, assets.POSE_FULL_MODEL}
    assert {m["licence"] for m in doc["models"].values()} == {"Apache-2.0"}
    r7 = {n: "x" for n in (*assets.MEDIAPIPE, assets.POSE_MODEL)}
    assert "hands" not in assets.installed(r7)  # R7's answer is unchanged without r8-1
    assert assets.installed(r7, None, {})["hands"] is False
    assert assets.installed(r7, None, {assets.HAND_MODEL: "x"})["hands"] is True
    assert assets.installed({}, None, {assets.HAND_MODEL: "x"})["hands"] is False  # no runtime


def test_the_script_fetches_r8_models_only_into_r8_1() -> None:
    import importlib.util
    import sys

    spec = importlib.util.spec_from_file_location(
        "vision_assets_r8", ROOT / "scripts" / "vision_assets.py"
    )
    assert spec is not None and spec.loader is not None
    va = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = va  # a dataclass module must be importable by its own name
    spec.loader.exec_module(va)
    picked = va.plan_models(None, "r8-1")
    assert [s.name for s in picked] == ["hand_landmarker.task", "pose_landmarker_full.task"]
    assert all(
        s.release == "r8-1" and s.url.startswith("https://storage.googleapis.com/") for s in picked
    )
    assert [s.name for s in va.plan_models(None)] == ["pose_landmarker_lite.task"]  # R7 unchanged
    assert va.main(["check", "--release", "r8-1"]) == 0


def test_the_workflow_fetches_twice_compares_and_keeps_the_files_a_week() -> None:
    import re

    wf = (ROOT / ".github" / "workflows" / "vision-models.yml").read_text(encoding="utf-8")
    assert "workflow_dispatch:" in wf and "src/jarvis/api/static/vendor/vision/**" in wf
    assert re.search(r"^permissions:\n  contents: read$", wf, re.M)
    assert "for run in one two; do" in wf and "the two fetches differ" in wf
    assert "--release r8-1" in wf and "retention-days: 7" in wf and "GITHUB_STEP_SUMMARY" in wf
    for use in re.findall(r"uses: (\S+)", wf):
        assert re.fullmatch(r"[\w./-]+@[0-9a-f]{40}", use), use  # every action pinned by its commit
    assert "secrets." not in wf


# ---- S22 · the wiring skeleton, the settings, the version ----------------------------------------
def test_the_version_is_eight_and_the_book_names_r8() -> None:
    import jarvis
    from jarvis.buildbook.gen import plans
    from jarvis.buildbook.gen.repo import Repo

    assert jarvis.__version__ == "8.0.0"  # the exact number: test_about.py
    repo = Repo.from_git(ROOT)
    assert (
        plans.release_label(repo) == "R8" and plans.plan_paths(repo)[0] == "docs/plans/r8-vision.md"
    )


def test_the_coach_settings_have_safe_defaults_and_ranges() -> None:
    from pydantic import ValidationError

    from jarvis.config import Settings

    s = Settings(_env_file=None)  # type: ignore[call-arg]
    assert s.coach_enabled is True and s.coach_keep_days == 90
    for bad in (6, 366):
        with pytest.raises(ValidationError):
            Settings(_env_file=None, coach_keep_days=bad)  # type: ignore[call-arg]


def test_the_wiring_mounts_the_routes_and_builds_the_coach_only_when_enabled() -> None:
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from jarvis.api.auth import require_auth
    from jarvis.api.coach import CoachApp
    from jarvis.api.identity import current_user
    from jarvis.api.r8_wiring import install_r8_routes, r8_privacy_sources, r8_tools, wire_r8
    from jarvis.config import Settings
    from jarvis.keyring import Keyring
    from jarvis.storage.docs import MemoryDocs

    app = FastAPI()
    install_r8_routes(app)
    app.dependency_overrides[require_auth] = lambda: None
    app.dependency_overrides[current_user] = lambda: "u1"
    c = TestClient(app)
    assert c.get("/v1/coach/usecases").status_code == 200
    assert c.get("/v1/coach/results").status_code == 404  # no coach wired: coach_off
    assert c.get("/v1/camera/spots").status_code == 501  # B's skeleton
    s = Settings(_env_file=None)  # type: ignore[call-arg]
    coach = wire_r8(app, s, MemoryDocs(), Keyring(KEY), _clock())
    assert isinstance(coach, CoachApp) and app.state.coach is coach and coach.store.keep_days == 90

    async def names(uid: str) -> dict[str, str]:
        return {}

    assert [r.id for r in r8_privacy_sources(app)] == ["coach_me", "coach_people", "coach_guests"]
    assert [t.name for t in r8_tools(app, names)] == ["coach_results"]
    off = Settings(_env_file=None, coach_enabled=False)  # type: ignore[call-arg]
    assert wire_r8(app, off, MemoryDocs(), None, _clock()) is None and app.state.coach is None
    assert r8_privacy_sources(app) == () and r8_tools(app, names) == []
