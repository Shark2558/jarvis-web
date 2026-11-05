# tests/test_health_tool_tick.py -- R4 D6/D14: `systems_check` through the gateway, and the TickJob.
from __future__ import annotations

from health_fakes import UID, Clock, Flip, Notes, fixed

from jarvis.core.guardrails import ActionRisk, ConfirmationGate
from jarvis.health.service import HealthService
from jarvis.health.store import HealthStore
from jarvis.health.tick import HealthTickJob
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
    assert out.result["spoken"] == "Attention: the home bridge is not answering."
    assert {s["name"]: s["status"] for s in out.result["systems"]} == {
        "Redis": "ok",
        "the home bridge": "down",
    }
    assert out.trusted is True


async def test_systems_check_all_ok() -> None:
    gw, _ = gateway(svc(fixed("a", "Redis", "ok")))
    out = await gw.execute(ToolCall(id="c", name="systems_check", arguments={}), scope=SCOPE)
    assert out.result["spoken"] == "All systems nominal, Sir."


# ---- tick job ----------------------------------------------------------------------------------
def test_tick_job_has_a_name_and_a_budget_and_fits_the_protocol() -> None:
    job = HealthTickJob(svc())
    assert isinstance(job, TickJob) and job.name == "health_check"
    assert 0 < job.budget_s <= 60


async def test_tick_runs_the_check_for_each_owner_and_alerts_on_change() -> None:
    flip, notes = Flip(), Notes()
    s = svc(flip.probe, notifier=notes)
    job = HealthTickJob(s)
    assert await job.run(["u1", "u2"]) == {"owners": 2, "faults": 0, "failed": 0}
    flip.status = "down"
    counts = await job.run(["u1", "u2"])
    assert counts == {"owners": 2, "faults": 2, "failed": 0}
    assert notes.kinds() == ["health_fault", "health_fault"]


async def test_tick_counts_an_owner_it_could_not_serve_and_carries_on() -> None:
    class Flaky(HealthService):
        async def check(self, uid: str):  # type: ignore[no-untyped-def]
            if uid == "bad":
                raise RuntimeError("store")
            return await super().check(uid)

    s = Flaky([fixed("a", "A", "ok")], HealthStore(MemoryDocs(), prefix="jarvis_"), clock=Clock())
    counts = await HealthTickJob(s).run(["bad", "good"])
    assert counts["failed"] == 1 and counts["owners"] == 2
    assert await s.last("good") is not None


async def test_run_jobs_reports_failed_when_an_owner_failed() -> None:
    class Boom(HealthService):
        async def check(self, uid: str):  # type: ignore[no-untyped-def]
            raise RuntimeError("x")

    s = Boom([], HealthStore(MemoryDocs(), prefix="jarvis_"), clock=Clock())
    assert await run_jobs([HealthTickJob(s)], [UID]) == {"health_check": "failed"}


async def test_tick_job_runs_with_no_owners() -> None:
    assert await HealthTickJob(svc()).run([]) == {"owners": 0, "faults": 0, "failed": 0}
