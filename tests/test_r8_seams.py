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
