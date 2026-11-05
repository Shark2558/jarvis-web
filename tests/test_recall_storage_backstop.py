# tests/test_recall_storage_backstop.py -- R2 D11: where a physical thing is kept belongs to Things
# (encrypted, no implicit learning), so (1) the extraction prompt says so and (2) a LEARNED fact
# that says where something is kept is dropped. Facts the owner tells or adds are untouched, and
# learning still reads only typed turns (R1 review fix).
from __future__ import annotations

import json

from memory_fakes import NOW, UID, extraction, rig, session_with

from jarvis.core.models import Turn
from jarvis.llm.base import Role
from jarvis.recall.extract import SYSTEM, build_input
from jarvis.recall.learning import snapshot
from jarvis.recall.models import SettingsPatch

THREE = ("Passport is in the blue file", "I live in Kochi", "I prefer short answers")


async def _consent(r) -> None:  # type: ignore[no-untyped-def]
    await r.svc.update_settings(UID, SettingsPatch(learn=True, confirm_spend=True))


def test_the_extraction_prompt_sends_storage_places_to_things() -> None:
    assert "never record where physical things are kept" in SYSTEM.lower()
    assert "Things" in SYSTEM


async def test_a_learned_storage_fact_is_dropped_and_others_kept() -> None:
    r = rig()
    await _consent(r)
    r.private.script(
        extraction(
            [
                {"text": "Passport is kept in the blue file", "category": "places"},
                {"text": "Keeps the gold in the bank locker", "category": "other"},
                {"text": "Lives in Kochi", "category": "places"},
            ]
        )
    )
    res = await r.svc.learn(UID, session_with(*THREE), r.spec)
    assert (res.added, res.dropped) == (1, 2)
    assert [f.text for f in (await r.store.load(UID)).active()] == ["Lives in Kochi"]


async def test_a_replacement_that_turns_a_fact_into_a_storage_place_is_dropped() -> None:
    r = rig()
    await _consent(r)
    old = (await r.svc.remember(UID, "Lives in Kochi", "places", origin="learned"))[0]
    r.private.script(
        json.dumps(
            {"facts": [], "replace": [{"id": old.id, "text": "Spare keys are in the top drawer"}]}
        )
    )
    res = await r.svc.learn(UID, session_with(*THREE), r.spec)
    assert (res.replaced, res.dropped) == (0, 1)
    assert [f.text for f in (await r.store.load(UID)).active()] == ["Lives in Kochi"]


async def test_a_fact_the_owner_told_or_added_is_kept() -> None:
    r = rig()
    told = await r.svc.add_fact(UID, "Passport is kept in the blue file", "places")
    assert told.origin != "learned"
    assert [f.text for f in (await r.store.load(UID)).active()] == [
        "Passport is kept in the blue file"
    ]


async def test_learning_still_reads_only_typed_turns() -> None:
    s = session_with("I live in Kochi")
    s.append(
        Turn(role=Role.USER, content="a guest said: I keep the key in the drawer", channel="voice")
    )
    snap = snapshot(s)
    assert [line.text for line in snap.owner] == ["I live in Kochi"]
    assert "guest" not in build_input([line.text for line in snap.owner], [])
    assert NOW is not None
