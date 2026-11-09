# tests/test_r51c_stream.py -- R5.1 D5/D7 (docs/plans/r5-1-observations.md): the streamed systems
# check. `HealthService.check_stream` keeps check()'s lock, cooldown (forced from the pop-up),
# debounce and alerts; it yields `plan` (every probe, fixed order), one `result` per probe as it
# completes, then `done` (the full report + the briefing). `POST /v1/health/run/stream` answers
# NDJSON with the same auth and per-owner rate limit as /run; /v1/health and /run add `briefing`.
from __future__ import annotations

import asyncio
import json
from typing import Any

import pytest
from fastapi import Depends, FastAPI, HTTPException
from health_fakes import UID, Clock, Flip, Notes, fixed
from httpx import ASGITransport, AsyncClient
from r51c_fakes import VitalsFake, board, view

from jarvis.health.api import RUN_PER_MINUTE, health_router
from jarvis.health.briefing import VITALS_UNREADABLE
from jarvis.health.models import ProbeOutcome
from jarvis.health.probes import Probe
from jarvis.health.service import (
    CHECK_COOLDOWN_S,
    CHECK_DEADLINE_S,
    MAX_WATCHERS,
    CheckBusy,
    HealthService,
)
from jarvis.health.store import HealthStore
from jarvis.storage.docs import MemoryDocs


def timed(key: str, label: str, delay: float, status: str = "ok") -> Probe:
    async def check(_uid: str) -> ProbeOutcome:
        await asyncio.sleep(delay)
        return ProbeOutcome(status, f"{key} reason")  # type: ignore[arg-type]

    return Probe(key=key, label=label, check=check)


def skipped(key: str, label: str) -> Probe:
    async def check(_uid: str) -> None:
        return None

    return Probe(key=key, label=label, check=check)


def service(*probes: Probe, notes: Notes | None = None, vitals: Any = None, clock: Any = None):  # type: ignore[no-untyped-def]
    return HealthService(
        list(probes),
        HealthStore(MemoryDocs(), prefix="jarvis_"),
        notifier=notes,  # type: ignore[arg-type]
        vitals=vitals,
        clock=clock or Clock(),
    )


async def collect(svc: HealthService, **kw: Any) -> list[dict[str, Any]]:
    return [e async for e in svc.check_stream(UID, **kw)]


# ---- the service --------------------------------------------------------------------------------
async def test_events_come_plan_then_each_result_as_it_completes_then_done() -> None:
    svc = service(
        timed("google", "Google", 0.05),
        timed("redis", "Redis", 0.0),
        skipped("telegram", "Telegram"),
    )
    events = await collect(svc, force=True)
    assert [e["type"] for e in events] == ["plan", "result", "result", "result", "done"]
    assert events[0]["systems"] == [
        {"key": "google", "name": "Google"},
        {"key": "redis", "name": "Redis"},
        {"key": "telegram", "name": "Telegram"},
    ]
    results = [e for e in events if e["type"] == "result"]
    assert results[-1]["key"] == "google"  # the slow one arrives last
    by_key = {e["key"]: e for e in results}
    assert by_key["redis"]["status"] == "ok" and by_key["redis"]["name"] == "Redis"
    assert by_key["telegram"]["status"] == "skipped"
    done = events[-1]
    assert done["overall"] == "ok" and [s["key"] for s in done["systems"]] == ["google", "redis"]
    assert done["briefing"]["spoken"].startswith("Systems check complete, Sir. I checked 2 systems")
    assert done["spoken"] == "All systems nominal, Sir."  # the R4 one-liner, kept


async def test_a_stream_inside_the_cooldown_replays_without_running_probes() -> None:
    n = {"runs": 0}

    async def counted(_uid: str) -> ProbeOutcome:
        n["runs"] += 1
        return ProbeOutcome("ok", "fine")

    svc = service(Probe(key="redis", label="Redis", check=counted))
    await collect(svc, force=True)
    again = await collect(svc)
    assert n["runs"] == 1
    assert [e["type"] for e in again] == ["plan", "result", "done"]
    forced = await collect(svc, force=True)
    assert n["runs"] == 2 and forced[-1]["type"] == "done"


async def test_stream_and_check_share_the_debounce_and_alert_once() -> None:
    notes, flip = Notes(), Flip("redis", "Redis")
    flip.status = "down"
    svc = service(flip.probe, notes=notes)
    await svc.check(UID, force=True)  # first bad check: no alert yet
    await collect(svc, force=True)  # second, through the stream: the fault holds -> one alert
    await collect(svc, force=True)
    assert notes.kinds() == ["health_fault"]
    last = await svc.last(UID)
    assert last is not None and last.overall == "down"


async def test_a_check_and_a_stream_for_one_owner_never_overlap() -> None:
    running = {"now": 0, "peak": 0}

    async def slow(_uid: str) -> ProbeOutcome:
        running["now"] += 1
        running["peak"] = max(running["peak"], running["now"])
        await asyncio.sleep(0.02)
        running["now"] -= 1
        return ProbeOutcome("ok", "fine")

    svc = service(Probe(key="redis", label="Redis", check=slow))
    await asyncio.gather(svc.check(UID, force=True), collect(svc, force=True))
    assert running["peak"] == 1


async def test_a_client_that_goes_away_mid_stream_still_gets_the_check_saved() -> None:
    svc = service(timed("redis", "Redis", 0.05, "down"))
    agen = svc.check_stream(UID, force=True)
    first = await agen.__anext__()
    assert first["type"] == "plan"
    await agen.aclose()  # the browser closed the pop-up
    for _ in range(50):
        if await svc.last(UID) is not None:
            break
        await asyncio.sleep(0.01)
    last = await svc.last(UID)
    assert last is not None and last.overall == "down"


async def test_the_briefing_carries_vitals_and_a_vitals_failure_never_fails_the_check() -> None:
    hot = view("github", "GitHub token", "amber", reason="expires in 3 days")
    ok = service(fixed("redis", "Redis", "ok"), vitals=VitalsFake(board(hot, used=120, limit=500)))
    done = (await collect(ok, force=True))[-1]
    spoken = done["briefing"]["spoken"]
    assert "AI spend is ₹120 of ₹500 this month, 24 percent." in spoken
    assert [c["key"] for c in done["briefing"]["concerns"]] == ["vitals.github"]

    broken = service(fixed("redis", "Redis", "ok"), vitals=VitalsFake(exc=RuntimeError("503")))
    done = (await collect(broken, force=True))[-1]
    assert done["overall"] == "ok" and VITALS_UNREADABLE in done["briefing"]["spoken"]


async def test_a_vitals_board_that_hangs_is_given_up_on() -> None:
    class Hangs:
        async def board(self, uid: str) -> Any:
            await asyncio.sleep(30)

    svc = service(fixed("redis", "Redis", "ok"), vitals=Hangs())
    svc._vitals_timeout_s = 0.05  # noqa: SLF001 - the test does not wait the real 5 s
    report = await svc.check(UID, force=True)
    brief = await svc.briefing(UID, report)
    assert VITALS_UNREADABLE in brief.spoken


async def test_a_probe_that_crashes_is_down_in_the_stream_too() -> None:
    async def boom(_uid: str) -> ProbeOutcome:
        raise RuntimeError("vendor text sk-ant-1")

    svc = service(Probe(key="redis", label="Redis", check=boom))
    events = await collect(svc, force=True)
    result = next(e for e in events if e["type"] == "result")
    assert result["status"] == "down" and "sk-ant" not in json.dumps(events)


async def test_a_failure_inside_the_check_ends_the_stream_with_an_error_event() -> None:
    svc = service(fixed("redis", "Redis", "ok"))

    async def broken(*_a: Any, **_k: Any) -> Any:
        raise RuntimeError("store exploded sk-live-2")

    svc._run_probes = broken  # type: ignore[method-assign]  # noqa: SLF001
    events = await collect(svc, force=True)
    assert events[-1] == {"type": "error", "detail": "The check did not complete."}
    assert "sk-live" not in json.dumps(events)


# ---- the routes ---------------------------------------------------------------------------------
def app(svc: Any, *, deny: bool = False) -> FastAPI:
    def auth() -> None:
        if deny:
            raise HTTPException(401, "no")

    a = FastAPI()
    a.include_router(health_router(svc, user=lambda: UID, dependencies=[Depends(auth)]))
    return a


async def call(a: FastAPI, method: str, path: str, body: Any = None) -> Any:
    async with AsyncClient(transport=ASGITransport(app=a), base_url="http://t") as c:
        return await c.request(method, path, json=body)


def ndjson(text: str) -> list[dict[str, Any]]:
    return [json.loads(line) for line in text.splitlines() if line.strip()]


async def test_the_stream_route_answers_ndjson_in_order() -> None:
    svc = service(timed("google", "Google", 0.03, "down"), timed("redis", "Redis", 0.0))
    async with AsyncClient(transport=ASGITransport(app=app(svc)), base_url="http://t") as c:
        async with c.stream("POST", "/v1/health/run/stream", json={"force": True}) as r:
            assert r.status_code == 200
            assert r.headers["content-type"].startswith("application/x-ndjson")
            assert r.headers["cache-control"] == "no-store"
            lines = [json.loads(line) async for line in r.aiter_lines() if line.strip()]
    assert [e["type"] for e in lines] == ["plan", "result", "result", "done"]
    assert [e["key"] for e in lines if e["type"] == "result"] == ["redis", "google"]
    done = lines[-1]
    assert done["overall"] == "down"
    assert done["briefing"]["concerns"][0]["key"] == "google"
    assert set(done["briefing"]["concerns"][0]) == {"key", "label", "severity", "impact", "fix"}


async def test_the_stream_route_without_a_body_uses_the_cooldown() -> None:
    n = {"runs": 0}

    async def counted(_uid: str) -> ProbeOutcome:
        n["runs"] += 1
        return ProbeOutcome("ok", "fine")

    a = app(service(Probe(key="redis", label="Redis", check=counted)))
    await call(a, "POST", "/v1/health/run/stream")
    r = await call(a, "POST", "/v1/health/run/stream")
    assert n["runs"] == 1 and ndjson(r.text)[-1]["type"] == "done"
    await call(a, "POST", "/v1/health/run/stream", {"force": True})
    assert n["runs"] == 2


async def test_the_stream_route_shares_the_run_rate_limit_and_the_auth() -> None:
    a = app(service(fixed("redis", "Redis", "ok")))
    codes = [(await call(a, "POST", "/v1/health/run")).status_code for _ in range(RUN_PER_MINUTE)]
    assert codes == [200] * RUN_PER_MINUTE
    assert (await call(a, "POST", "/v1/health/run/stream")).status_code == 429
    denied = app(service(fixed("redis", "Redis", "ok")), deny=True)
    assert (await call(denied, "POST", "/v1/health/run/stream")).status_code == 401


async def test_the_stream_route_refuses_unknown_body_fields() -> None:
    a = app(service(fixed("redis", "Redis", "ok")))
    assert (await call(a, "POST", "/v1/health/run/stream", {"force": "yes"})).status_code == 422
    assert (await call(a, "POST", "/v1/health/run/stream", {"uid": "other"})).status_code == 422


async def test_a_service_without_streaming_answers_404_so_the_console_falls_back() -> None:
    class Old:  # the R4 shape (LiveHealth before I1 adds the new methods)
        def __init__(self, svc: HealthService) -> None:
            self._svc = svc

        async def last(self, uid: str) -> Any:
            return await self._svc.last(uid)

        async def check(self, uid: str, *, force: bool = False) -> Any:
            return await self._svc.check(uid, force=force)

        async def speak(self, uid: str) -> Any:
            return None

    a = app(Old(service(fixed("redis", "Redis", "down"))))
    assert (await call(a, "POST", "/v1/health/run/stream")).status_code == 404
    run = (await call(a, "POST", "/v1/health/run")).json()
    assert run["briefing"]["concerns"][0]["key"] == "redis"  # no vitals, still a briefing


async def test_get_and_run_carry_the_briefing_and_keep_the_one_liner() -> None:
    a = app(service(fixed("redis", "Redis", "ok"), fixed("telegram", "Telegram", "down")))
    empty = (await call(a, "GET", "/v1/health")).json()
    assert empty["briefing"] == {"spoken": "", "lines": [], "concerns": [], "spend": ""}
    run = (await call(a, "POST", "/v1/health/run")).json()
    got = (await call(a, "GET", "/v1/health")).json()
    assert run == got
    assert run["spoken"] == "Attention: Telegram is not answering."
    assert run["briefing"]["spoken"].endswith("Shall I set a reminder to fix this?")
    assert "alerts and Telegram chat won't reach you" in run["briefing"]["spoken"]


@pytest.mark.parametrize("path", ["/v1/health", "/v1/health/run"])
async def test_a_failing_vitals_board_never_fails_the_route(path: str) -> None:
    svc = service(fixed("redis", "Redis", "ok"), vitals=VitalsFake(exc=RuntimeError("x")))
    await svc.check(UID, force=True)
    r = await call(app(svc), "GET" if path == "/v1/health" else "POST", path)
    assert r.status_code == 200 and VITALS_UNREADABLE in r.json()["briefing"]["spoken"]


def test_the_cooldown_is_unchanged() -> None:
    assert CHECK_COOLDOWN_S == 30.0


# ---- review fixes: hangs, partial failures, coalescing, the deadline ----------------------------
async def test_a_probe_that_hangs_past_its_timeout_is_down_and_done_still_arrives() -> None:
    async def hangs(_uid: str) -> ProbeOutcome:
        await asyncio.sleep(30)
        return ProbeOutcome("ok", "never")

    svc = service(
        Probe(key="redis", label="Redis", check=hangs, timeout_s=0.05),
        timed("google", "Google", 0.0),
    )
    events = await collect(svc, force=True)
    assert [e["type"] for e in events][-1] == "done"
    redis = next(e for e in events if e["type"] == "result" and e["key"] == "redis")
    assert redis["status"] == "down" and redis["reason"] == "did not answer in time"


async def test_an_error_after_partial_results_ends_with_the_error_event_and_no_done() -> None:
    svc = service(timed("google", "Google", 0.0), timed("redis", "Redis", 0.0))

    async def broken(*_a: Any, **_k: Any) -> Any:
        raise RuntimeError("alert store exploded sk-live-9")

    svc._deliver = broken  # type: ignore[method-assign]  # noqa: SLF001
    events = await collect(svc, force=True)
    assert [e["type"] for e in events] == ["plan", "result", "result", "error"]
    assert events[-1] == {"type": "error", "detail": "The check did not complete."}
    assert "sk-live" not in json.dumps(events)


async def test_a_forced_stream_while_one_runs_attaches_to_it_instead_of_queueing() -> None:
    n = {"runs": 0}

    async def counted(_uid: str) -> ProbeOutcome:
        n["runs"] += 1
        await asyncio.sleep(0.05)
        return ProbeOutcome("ok", "fine")

    svc = service(Probe(key="redis", label="Redis", check=counted))
    first = asyncio.create_task(collect(svc, force=True))
    await asyncio.sleep(0.02)  # the first run is in flight
    second = await collect(svc, force=True)  # attaches: replays plan, then the live events
    one = await first
    assert n["runs"] == 1
    assert [e["type"] for e in second] == ["plan", "result", "done"]
    assert second == one
    again = await collect(svc, force=True)  # the run is over: a new forced run starts
    assert n["runs"] == 2 and again[-1]["type"] == "done"


async def test_other_owners_are_never_coalesced() -> None:
    n = {"runs": 0}

    async def counted(_uid: str) -> ProbeOutcome:
        n["runs"] += 1
        await asyncio.sleep(0.03)
        return ProbeOutcome("ok", "fine")

    svc = service(Probe(key="redis", label="Redis", check=counted))

    async def run(uid: str) -> list[dict[str, Any]]:
        return [e async for e in svc.check_stream(uid, force=True)]

    a, b = await asyncio.gather(run("u_a"), run("u_b"))
    assert n["runs"] == 2 and a[-1]["type"] == b[-1]["type"] == "done"


async def test_too_many_waiting_requests_get_a_busy_answer_and_a_429_on_the_route() -> None:
    svc = service(timed("redis", "Redis", 0.15))
    held = [svc.check_stream(UID, force=True) for _ in range(MAX_WATCHERS)]
    with pytest.raises(CheckBusy):
        svc.check_stream(UID, force=True)
    r = await call(app(svc), "POST", "/v1/health/run/stream", {"force": True})
    assert r.status_code == 429
    assert r.json()["detail"]["detail"] == "A check is already running, Sir. Wait a moment."
    for agen in held:
        assert [e async for e in agen][-1]["type"] == "done"


async def test_a_total_deadline_ends_unfinished_probes_as_down_and_done_still_arrives() -> None:
    svc = service(
        Probe(key="redis", label="Redis", check=timed("x", "x", 30).check, timeout_s=60.0),
        timed("google", "Google", 0.0),
    )
    svc._deadline_s = 0.1  # noqa: SLF001 - the test does not wait the real 45 s
    events = await collect(svc, force=True)
    assert [e["type"] for e in events][-1] == "done"
    redis = next(e for e in events if e["type"] == "result" and e["key"] == "redis")
    assert redis["status"] == "down" and redis["reason"] == "did not answer in time"
    last = await svc.last(UID)
    assert last is not None and last.overall == "down"  # stored, alerts still go through
    assert svc._locks[UID].locked() is False  # noqa: SLF001


def test_the_total_deadline_is_forty_five_seconds() -> None:
    assert CHECK_DEADLINE_S == 45.0
