# tests/test_calls_langcheck_api.py — R18 B: the language routes' bodies: strict validation with
# plain words, estimate only by default (nothing sent), a run refused with 409 when its ₹ is not
# accepted, the owner's score, and the language table's shape.
from __future__ import annotations

import pytest
from calls_speech_fakes import World
from test_calls_langcheck_runner import result, setup

from jarvis.calls.langcheck.api import handle_check, handle_score, languages_view
from jarvis.calls.models import CallSettings
from jarvis.calls.ports import CallsRefused
from jarvis.config import Settings


async def test_the_default_is_an_estimate_of_the_default_languages() -> None:
    world = World()
    check, store = setup(world)
    out = await handle_check(check, {})
    # all 13 languages on Google go past its shared free hour: the estimate says so in ₹
    assert out["plan"]["total_inr"] > 0
    assert {p["lang"] for p in out["plan"]["pairs"]} >= {"en-IN", "hi-IN", "as-IN"}
    assert world.clock.t == 0.0 and await store.language_results() == []  # nothing ran


@pytest.mark.parametrize(
    "body",
    [
        {"languages": ["xx-IN"]},
        {"languages": []},
        {"accept_inr": -1},
        {"accept_inr": 10_000},
        {"surprise": True},
        {"options": ["skype"]},
    ],
)
async def test_bad_bodies_are_refused_plainly(body: dict[str, object]) -> None:
    check, _ = setup(World())
    with pytest.raises(CallsRefused) as e:
        await handle_check(check, body)
    assert e.value.status == 422 and "xx-IN" not in e.value.words


async def test_a_run_and_a_refused_run() -> None:
    world = World()
    check, _ = setup(world)
    out = await handle_check(check, {"languages": ["hi-IN"], "estimate_only": False})
    assert {r["option"] for r in out["results"]} == {"google", "azure"}
    assert "hi-IN laptop" in out["skipped"]
    priced, _ = setup(World(), settings=Settings(_env_file=None, voice_stt_free_seconds=0))
    with pytest.raises(CallsRefused) as e:
        await handle_check(priced, {"languages": ["hi-IN"], "estimate_only": False})
    assert e.value.status == 409 and "₹" in e.value.words


async def test_scores_are_validated_and_stored() -> None:
    check, _ = setup(World())
    await handle_check(check, {"languages": ["hi-IN"], "estimate_only": False})
    out = await handle_score(check, {"lang": "hi-IN", "option": "google", "scores": [4, 4, 5]})
    assert out["result"]["native_heard"] is True
    with pytest.raises(CallsRefused) as e:
        await handle_score(check, {"lang": "hi-IN", "option": "google", "scores": [6]})
    assert e.value.status == 422
    with pytest.raises(CallsRefused) as e:
        await handle_score(check, {"lang": "ta-IN", "option": "google", "scores": [5]})
    assert e.value.status == 404


def test_the_table_view() -> None:
    view = languages_view([result("hi-IN", "google")], CallSettings(), ["hi-IN", "or-IN"])
    hi, odia = view["languages"]
    assert hi["offered"] and hi["option"] == "google" and hi["native_heard"] is False
    assert not odia["offered"] and odia["why"] == ["not checked yet"]
