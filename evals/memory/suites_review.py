# evals/memory/suites_review.py
"""Slice 8 review evals (fix round), wired into run.py:

recall_small     13, 20, 30, 40 planted facts: when they fit the budget all are sent (the
                 "send all" path), and every question's fact is in the notes block; the
                 larger sets fall back to ranked selection (recall ≥ 80 %).
scale            500 facts (50 planted + 450 distractors) imported in < 1 s; 50 questions:
                 recall ≥ 80 %, every recall < 250 ms of loop time; export → forget
                 everything → import at 500 is identical and < 1 s.
learning_safety  a learning run in flight across "Forget everything" or "learning off" stores
                 nothing; extraction cannot replace a fact the owner added. Negative control:
                 with the generation bump disabled the wipe case MUST fail.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from harness import UID, Rig, distractors, old_session, rig

import jarvis.recall.ops as ops_mod
from jarvis.core.models import ChatRequest
from jarvis.llm.base import Completion
from jarvis.recall import extract
from jarvis.recall.models import SettingsPatch
from jarvis.recall.retrieval import select_facts

SMALL_SIZES = (13, 20, 30, 40)
SCALE_FACTS = 500
IMPORT_BOUND_S = 1.0
RECALL_BOUND_S = 0.25


@contextmanager
def _patched(obj: Any, attr: str, value: Any) -> Iterator[None]:
    old = getattr(obj, attr)
    setattr(obj, attr, value)
    try:
        yield
    finally:
        setattr(obj, attr, old)


async def _consent(r: Rig) -> None:
    await r.svc.update_settings(UID, SettingsPatch(learn=True, confirm_spend=True))


# ---- recall with 13–40 facts ------------------------------------------------------------------


async def _small_run(cases: list[dict[str, Any]], n: int) -> dict[str, Any]:
    r = rig()
    planted = cases[:n]
    ids = {}
    for c in planted:
        f = await r.svc.add_fact(UID, c["text"], c["category"], keywords=c["keywords"])
        ids[c["id"]] = f.id
    active = (await r.svc.store.load(UID)).active()
    send_all = len(select_facts(active, "", r.clock(), tz="Asia/Kolkata")) == n
    hits = 0
    for c in planted:
        before = len(r.private.calls)
        await r.brain.chat(ChatRequest(message=c["question"], user_id=UID))
        hits += f"[{ids[c['id']]}]" in r.private.calls[before].system
    await r.svc.drain()
    return {"facts": n, "send_all": send_all, "hits": hits}


async def suite_recall_small(cases: list[dict[str, Any]]) -> dict[str, Any]:
    runs = [await _small_run(cases, n) for n in SMALL_SIZES]
    asked = sum(x["facts"] for x in runs)
    rate = sum(x["hits"] for x in runs) / asked
    whole = [x for x in runs if x["send_all"]]
    return {
        "runs": runs,
        "send_all_runs": len(whole),
        "recall": round(rate, 4),
        "gate": bool(whole) and all(x["hits"] == x["facts"] for x in whole) and rate >= 0.8,
    }


# ---- 500 facts ----------------------------------------------------------------------------------


def _export_key(state: Any) -> list[tuple[Any, ...]]:
    return sorted((f.text, f.category, f.keywords, f.pinned) for f in state.active())


async def _round_trip(r: Rig) -> dict[str, Any]:
    before = await r.svc.store.load(UID)
    data = await r.svc.export(UID)
    await r.svc.forget_all(UID)
    t0 = time.perf_counter()
    res = await r.svc.import_(UID, data)
    took = time.perf_counter() - t0
    after = await r.svc.store.load(UID)
    return {
        "added": res.added,
        "seconds": round(took, 3),
        "identical": _export_key(after) == _export_key(before),
    }


async def suite_scale(cases: list[dict[str, Any]]) -> dict[str, Any]:
    r = rig()
    noise = distractors(SCALE_FACTS - len(cases))
    facts = [{k: d[k] for k in ("text", "category", "keywords")} for d in [*noise, *cases]]
    t0 = time.perf_counter()
    imported = await r.svc.import_(UID, {"version": 1, "facts": facts})
    import_s = time.perf_counter() - t0
    by_text = {f.text: f.id for f in (await r.svc.store.load(UID)).active()}
    hits, slowest = 0, 0.0
    for c in cases:
        t = time.perf_counter()
        rec = await r.svc.recall(UID, r.private_spec, c["question"])
        slowest = max(slowest, time.perf_counter() - t)
        hits += any(u.id == by_text.get(c["text"]) for u in rec.used)
    trip = await _round_trip(r)
    rate = hits / len(cases)
    return {
        "facts": imported.added,
        "import_seconds": round(import_s, 3),
        "recall": round(rate, 4),
        "slowest_recall_ms": round(slowest * 1000, 1),
        "round_trip": trip,
        "gate": imported.added == SCALE_FACTS
        and import_s < IMPORT_BOUND_S
        and rate >= 0.8
        and slowest < RECALL_BOUND_S
        and trip["identical"]
        and trip["added"] == SCALE_FACTS
        and trip["seconds"] < IMPORT_BOUND_S,
    }


# ---- learning safety --------------------------------------------------------------------------


def _hold_extraction(r: Rig) -> asyncio.Event:
    """The extraction call waits for the event: a run in flight (a throttled instance)."""
    gate = asyncio.Event()
    orig = r.private.complete

    async def held(**kw: Any) -> Completion:
        if kw.get("system") == extract.SYSTEM:
            await gate.wait()
        return await orig(**kw)

    r.private.complete = held  # type: ignore[method-assign]
    return gate


async def in_flight_case(action: str) -> dict[str, Any]:
    r = rig()
    await _consent(r)
    gate = _hold_extraction(r)
    session = old_session("I live in Kochi", "I like tea", "I have a cat", sid=f"sess_{action}")
    task = asyncio.create_task(r.svc.learn(UID, session, r.private_spec))
    await asyncio.sleep(0.05)
    if action == "forget_all":
        await r.svc.forget_all(UID)
    else:
        await r.svc.update_settings(UID, SettingsPatch(learn=False))
    gate.set()
    res = await task
    stored = len((await r.svc.store.load(UID)).active())
    return {"id": action, "status": res.status.value, "stored": stored, "passed": stored == 0}


async def told_case() -> dict[str, Any]:
    r = rig()
    await _consent(r)
    told = await r.svc.add_fact(UID, "Lives in Kochi", "places")
    res = await r.svc.learn(UID, old_session("I moved to Thiruvananthapuram"), r.private_spec)
    state = await r.svc.store.load(UID)
    kept = any(f.id == told.id for f in state.active())
    return {"id": "replace_told", "replaced": res.replaced, "passed": kept and res.replaced == 0}


async def suite_learning_safety() -> dict[str, Any]:
    results = [await in_flight_case(a) for a in ("forget_all", "learn_off")]
    results.append(await told_case())
    with _patched(ops_mod, "next_generation", lambda s: s):
        control = [await in_flight_case("forget_all")]
    failed_control = sum(not x["passed"] for x in control)
    rate = sum(x["passed"] for x in results) / len(results)
    return {
        "cases": len(results),
        "pass_rate": rate,
        "negative_control": {"failed_cases": failed_control, "suite_failed": failed_control > 0},
        "results": results,
        "gate": rate == 1 and failed_control > 0,
    }


__all__ = ["suite_learning_safety", "suite_recall_small", "suite_scale"]
