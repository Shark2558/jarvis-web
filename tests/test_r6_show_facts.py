# tests/test_r6_show_facts.py -- R6 I1: A's show facts follow what D's scenes draw (INTEGRATION-D
# "Facts each scene reads"). Seen on the real server with the real book: scene 2 drew every layer
# twice (a parts and a lines fact each, 9 plates: L6-L8 and X missing), scene 4's purposes were
# drawn as vault labels (group "key", not "purpose"), scene 6 drew three voice prices as flow steps
# and scene 7 had no laptop at the edge and nothing inside the home.
from __future__ import annotations

import pytest
from book_gen_fakes import ROOT

from jarvis.buildbook.gen import show, write
from jarvis.buildbook.gen.repo import Repo
from jarvis.buildbook.model import LAYERS, Scene, load_book
from jarvis.buildbook.sections import Step, Workflow


@pytest.fixture(scope="module")
def scenes() -> dict[str, Scene]:
    """This checkout's own book (the fixture repo has no keyring purposes or home flow)."""
    book = load_book(write.build(Repo.from_git(ROOT)).book)
    return {s.id: s for s in book.show.scenes}


def test_scene_2_has_one_plate_per_layer_with_its_part_count(scenes: dict[str, Scene]) -> None:
    facts = scenes["layers"].facts
    assert [f.value for f in facts] == [lid for lid, _ in LAYERS]  # L1..L8, X: nine plates
    assert all(f.n is not None and f.n >= 0 and f.n == int(f.n) for f in facts)


def test_scene_4_names_the_keyrings_purposes(scenes: dict[str, Scene]) -> None:
    facts = scenes["memory"].facts
    assert facts and all(f.group == "purpose" for f in facts)


def test_scene_6_is_the_voice_flow_only(scenes: dict[str, Scene]) -> None:
    facts = scenes["voice"].facts
    assert facts and len(facts) <= 12 and all(not f.value.startswith("₹") for f in facts)


def test_scene_7_puts_the_laptop_at_the_edge_and_faces_at_home(scenes: dict[str, Scene]) -> None:
    groups = [f.group for f in scenes["home"].facts]
    assert groups.count("edge") == 1 and groups.count("home") >= 2
    assert len(groups) <= 24  # D15: at most 24 labels a scene


def test_flow_steps_carry_the_accent_hints_d_draws() -> None:
    flow = Workflow(
        id="chat_turn",
        title="One conversation turn",
        steps=[
            Step(label="The input guard checks it", symbol="jarvis.core.guardrails:guard_input"),
            Step(label="The gateway decides", symbol="jarvis.tools.gateway:Gateway.execute"),
            Step(label="The audit chain records it", symbol="jarvis.tools.audit:AuditLog.append"),
            Step(label="Your passkey", symbol="jarvis.permissions.service:Svc.check_approval"),
            Step(label="The reply", symbol="jarvis.api.routes:chat"),
        ],
    )
    assert [f.group for f in show.flow_facts(flow)] == [
        "guard",
        "gateway",
        "audit",
        "passkey",
        "step",
    ]
