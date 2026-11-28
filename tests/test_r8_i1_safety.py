# tests/test_r8_i1_safety.py -- R8 I1 join, the review's three safety items (must):
#   - a blood-pressure reading above 180/120 shows the American Heart Association's own steps,
#     its source named (wait 5 minutes and measure again; if still that high, contact the doctor
#     right away; chest pain, shortness of breath, back pain, numbness or weakness, a change in
#     vision or difficulty speaking: emergency services, 112 in India), never a diagnosis or a dose
#   - a screen the `digits` reader can't be sure of is refused in plain words, never guessed
#   - posture nudges go to the owner ("me") only (tests/test_r8_c_posture.py holds on_report;
#     tests/test_r8_i1_wiring.py holds it through the joined webhook)
from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest
from r8_fakes import run_node

from jarvis.coach import bp
from jarvis.coach.words import medical_hits, scan

KEY = bytes(range(41, 73))  # a made-up token key
NOON = 1764300000


def _reading(s: int, d: int, p: int = 72) -> bp.BpReading:
    return bp.BpReading(systolic=s, diastolic=d, pulse=p, taken_at=NOON, source="camera")


@pytest.mark.parametrize("s,d", [(185, 100), (150, 125), (181, 80), (200, 130)])
def test_above_180_over_120_the_ahas_own_steps_come_first(s: int, d: int) -> None:
    shown = bp.reading_view(_reading(s, d), [])
    assert shown["steps"] == bp.SEVERE_STEPS
    assert list(shown)[0] == "steps"  # the steps first, then the category, the trend and the note
    assert shown["category"] is not None and shown["category"].startswith("Severe Hypertension")


@pytest.mark.parametrize("s,d", [(180, 120), (128, 82), (179, 119), (140, 90)])
def test_at_or_below_180_over_120_there_are_no_steps(s: int, d: int) -> None:
    assert bp.reading_view(_reading(s, d), [])["steps"] is None
    assert bp.severe(_reading(s, d)) is False


def test_the_steps_are_the_ahas_and_name_their_source() -> None:
    steps = bp.SEVERE_STEPS
    for said in (
        "American Heart Association",
        "Blood Pressure Categories, 2025",
        "wait 5 minutes and measure again",
        "If it is still that high, contact your doctor right away",
        "chest pain",
        "shortness of breath",
        "back pain",
        "numbness or weakness",
        "a change in vision",
        "difficulty speaking",
        "call emergency services now (112 in India)",
    ):
        assert said in steps, said
    assert bp.SOURCE is not None and bp.SOURCE.publisher == "American Heart Association"


def test_the_steps_and_the_refusal_say_nothing_medical() -> None:
    assert scan([bp.SEVERE_STEPS, bp.CANT_READ]) == []
    for planted in ("dose", "mg", "tablet", "medicine", "diagnos", "you have"):
        assert planted not in bp.SEVERE_STEPS.lower(), planted
    assert medical_hits("Take your tablet now.") != []  # the scan still bites (a control)


def test_the_panes_twin_says_the_same_words() -> None:
    js_steps = run_node("console-coach-bp.js", "mod.steps", {"systolic": 185, "diastolic": 100})
    assert js_steps == bp.SEVERE_STEPS
    edge, low = {"systolic": 180, "diastolic": 120}, {"systolic": 150, "diastolic": 121}
    assert run_node("console-coach-bp.js", "mod.steps", edge) is None
    assert run_node("console-coach-bp.js", "mod.steps", low) == js_steps

    def lines(*pairs: tuple[int, float]) -> list[dict[str, float]]:
        return [{"value": v, "score": s} for v, s in pairs]

    unsure = lines((185, 0.97), (100, 0.5), (70, 0.9))
    refused = run_node("console-coach-bp.js", "mod.shown", unsure)
    assert refused == {"proposal": None, "steps": None, "words": bp.CANT_READ}
    sure = lines((185, 0.97), (100, 0.95), (70, 0.9))
    read = run_node("console-coach-bp.js", "mod.shown", sure)
    assert read["proposal"] == {"systolic": 185, "diastolic": 100, "pulse": 70}
    assert read["steps"] == bp.SEVERE_STEPS and read["words"] == ""


def test_an_unsure_screen_is_refused_never_guessed() -> None:
    assert bp.proposal_from_digits([(185, 0.97), (100, 0.79), (70, 0.9)]) is None
    assert bp.proposal_from_digits([(185, 0.97), (100, 0.95)]) is None
    assert "type the numbers" in bp.CANT_READ and "retake" in bp.CANT_READ


def _client() -> Any:
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

    docs, ring = MemoryDocs(), Keyring(KEY)
    app = FastAPI()
    app.include_router(api.router)
    app.dependency_overrides[require_auth] = lambda: None
    app.dependency_overrides[current_user] = lambda: "u1"

    def now() -> datetime:
        return datetime.fromtimestamp(NOON, UTC)

    app.state.coach = api.CoachApp(
        CoachStore(docs, ring, now=now), PeopleStore(docs, ring, now=now),
        TargetStore(docs, now=now), RoutineStore(docs, ring, now=now),
    )  # fmt: skip
    return TestClient(app)


def test_a_confirmed_severe_reading_is_answered_with_the_steps_first() -> None:
    c = _client()

    def post(s: int, d: int) -> Any:
        reading = {"systolic": s, "diastolic": d, "pulse": 80, "taken_at": NOON, "source": "camera"}
        return c.post("/v1/coach/bp/readings", json={"confirmed": True, "reading": reading,
                                                      "session": "cs_0123456789ab"})  # fmt: skip

    calm = post(128, 82)
    assert calm.status_code == 201 and calm.json()["view"]["steps"] is None
    high = post(186, 104)
    assert high.status_code == 201
    view = high.json()["view"]
    assert view["steps"] == bp.SEVERE_STEPS and view["category"].startswith("Severe Hypertension")
    assert view["trend"].startswith("Your last 2 readings")  # the earlier one counts in the trend
    assert view["note"] == bp.NOT_MEDICAL
