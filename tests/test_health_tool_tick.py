# tests/test_health_tool_tick.py -- R4 D6/D14: `systems_check` through the gateway, and the TickJob.
from __future__ import annotations

import asyncio

from health_fakes import UID, Clock, Flip, Notes, fixed

from jarvis.core.guardrails import ActionRisk, ConfirmationGate
from jarvis.health.models import ProbeOutcome
from jarvis.health.probes import Probe
from jarvis.health.service import HealthService
from jarvis.health.store import HealthStore
from jarvis.health.tick import FAULTS_COUNT, MAX_PARALLEL_OWNERS, OWNERS_COUNT, HealthTickJob
from jarvis.health.tools import health_tools
from jarvis.llm.base import ToolCall
from jarvis.storage.docs import MemoryDocs
from jarvis.ticks import TickJob, run_jobs
from jarvis.tools.audit import AuditLog
from jarvis.tools.gateway import Gateway, GatewayOutcome
from jarvis.tools.policy import Policy
from jarvis.tools.registry import ToolRegistry

SCOPE = f"{UID}:sess_1"


def svc(*probes, notifier=None) -> HealthService:  # type: ignore[no-untyped-def]
    return HealthService(
        list(probes), HealthStore(MemoryDocs(), prefix="jarvis_"), notifier=notifier, clock=Clock()
    )


def gateway(s: HealthService) -> tuple[Gateway, AuditLog]:
    reg, audit = ToolRegistry(), AuditLog()
    for t in health_tools(s):
        reg.register(t)
    return Gateway(registry=reg, policy=Policy([]), gate=ConfirmationGate(), audit=audit), audit


def test_one_read_only_tool_matching_the_systems_row() -> None:
    (tool,) = health_tools(svc())
    assert tool.name == "systems_check" and tool.risk is ActionRisk.READ_ONLY
    assert tool.input_schema["properties"] == {}
    assert tool.activity_words


async def test_systems_check_runs_the_probes_and_returns_the_fixed_line() -> None:
    gw, _ = gateway(svc(fixed("a", "Redis", "ok"), fixed("b", "the home bridge", "down")))
    out = await gw.execute(ToolCall(id="c", name="systems_check", arguments={}), scope=SCOPE)
    assert out.outcome is GatewayOutcome.EXECUTED
    assert out.result["overall"] == "down"
    assert out.result["headline"] == "Attention: the home bridge is not answering."
    # R5.1 D5: the tool (and so the voice and no-AI mode) says the full fixed-template briefing
    assert out.result["spoken"].startswith("Systems check complete, Sir. I checked 2 systems")
    assert out.result["spoken"].endswith("Shall I set a reminder to fix this?")
    assert [c["key"] for c in out.result["concerns"]] == ["b"]
    assert {s["name"]: s["status"] for s in out.result["systems"]} == {
        "Redis": "ok",
        "the home bridge": "down",
    }
    assert out.trusted is True


async def test_systems_check_all_ok() -> None:
    gw, _ = gateway(svc(fixed("a", "Redis", "ok")))
    out = await gw.execute(ToolCall(id="c", name="systems_check", arguments={}), scope=SCOPE)
    assert out.result["headline"] == "All systems nominal, Sir."
    assert out.result["spoken"] == (
        "Systems check complete, Sir. I checked 1 system: Redis. It is working. "
        "All systems nominal, Sir."
    )
    assert out.result["concerns"] == []


# ---- tick job ----------------------------------------------------------------------------------
def test_tick_job_has_a_name_and_a_budget_and_fits_the_protocol() -> None:
    job = HealthTickJob(svc())
    assert isinstance(job, TickJob) and job.name == "health_check"
    assert 0 < job.budget_s <= 60


async def test_tick_runs_the_check_for_each_owner_and_alerts_on_change() -> None:
    flip, notes = Flip(), Notes()
    s = svc(flip.probe, notifier=notes)
    job = HealthTickJob(s, every_s=0)
    assert await job.run(["u1", "u2"]) == {"owners": 2, "faults": 0, "failed": 0}
    flip.status = "down"
    await job.run(["u1", "u2"])
    counts = await job.run(["u1", "u2"])
    assert counts == {"owners": 2, "faults": 2, "failed": 0}
    assert notes.kinds() == ["health_fault", "health_fault"]


async def test_tick_counts_an_owner_it_could_not_serve_and_carries_on() -> None:
    class Flaky(HealthService):
        async def check(self, uid: str, *, force: bool = False):  # type: ignore[no-untyped-def]
            if uid == "bad":
                raise RuntimeError("store")
            return await super().check(uid, force=force)

    s = Flaky([fixed("a", "A", "ok")], HealthStore(MemoryDocs(), prefix="jarvis_"), clock=Clock())
    counts = await HealthTickJob(s).run(["bad", "good"])
    assert counts["failed"] == 1 and counts["owners"] == 2
    assert await s.last("good") is not None


async def test_run_jobs_reports_failed_when_an_owner_failed() -> None:
    class Boom(HealthService):
        async def check(self, uid: str, *, force: bool = False):  # type: ignore[no-untyped-def]
            raise RuntimeError("x")

    s = Boom([], HealthStore(MemoryDocs(), prefix="jarvis_"), clock=Clock())
    assert await run_jobs([HealthTickJob(s)], [UID]) == {"health_check": "failed"}


async def test_tick_job_runs_with_no_owners() -> None:
    assert await HealthTickJob(svc()).run([]) == {"owners": 0, "faults": 0, "failed": 0}


# ---- review fixes ------------------------------------------------------------------------------
async def test_tick_always_forces_a_fresh_check_past_the_cooldown() -> None:
    flip = Flip()
    s = svc(flip.probe)
    job = HealthTickJob(s, every_s=0)
    await job.run([UID])
    flip.status = "down"
    counts = await job.run([UID])  # same clock: inside the cooldown, but the tick forces
    assert counts["faults"] == 1


async def test_owners_are_checked_in_parallel_but_bounded() -> None:
    state = {"now": 0, "peak": 0}

    async def slow(_uid: str) -> ProbeOutcome:
        state["now"] += 1
        state["peak"] = max(state["peak"], state["now"])
        await asyncio.sleep(0.01)
        state["now"] -= 1
        return ProbeOutcome("ok", "fine")

    s = svc(Probe(key="redis", label="Redis", check=slow))
    owners = [f"u{i}" for i in range(MAX_PARALLEL_OWNERS * 3)]
    counts = await HealthTickJob(s).run(owners)
    assert counts["owners"] == len(owners) and counts["failed"] == 0
    assert 1 < state["peak"] <= MAX_PARALLEL_OWNERS


async def test_owners_still_unserved_at_the_deadline_are_counted_failed() -> None:
    async def hang(_uid: str) -> ProbeOutcome:
        await asyncio.sleep(10)
        return ProbeOutcome("ok", "never")

    s = svc(Probe(key="redis", label="Redis", check=hang, timeout_s=30))
    counts = await HealthTickJob(s, deadline_s=0.05).run(["u1", "u2", "u3"])
    assert counts == {"owners": 3, "faults": 0, "failed": 3}


async def test_an_owner_whose_result_could_not_be_saved_counts_as_failed() -> None:
    class DownStore(HealthStore):
        async def state(self, uid: str):  # type: ignore[no-untyped-def]
            raise OSError("down")

        async def save(self, uid: str, state):  # type: ignore[no-untyped-def]
            raise OSError("down")

    s = HealthService([fixed("a", "A", "ok")], DownStore(MemoryDocs()), clock=Clock())
    counts = await HealthTickJob(s).run([UID])
    assert counts["failed"] == 1


def test_the_counter_names_are_constants() -> None:
    assert (OWNERS_COUNT, FAULTS_COUNT) == ("owners", "faults")


# ---- cadence (R4 I2 F5) -------------------------------------------------------------------------
async def test_an_owner_is_checked_at_most_once_per_half_hour() -> None:
    now = [0.0]
    s = svc(fixed("a", "A", "ok"))
    job = HealthTickJob(s, clock=lambda: now[0])

    first = await job.run([UID])
    now[0] += 60
    second = await job.run([UID])  # the next tick, a minute later: not due
    now[0] += 1800
    third = await job.run([UID])

    assert first["owners"] == 1 and second["owners"] == 0 and third["owners"] == 1
