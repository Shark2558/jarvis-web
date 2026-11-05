# tests/test_health_service.py -- R4 D5/D6: rollup, last-result storage, fixed-template spoken line,
# change alerts, speaking, and the whole check running with the brain OFF.
from __future__ import annotations

import pytest
from health_fakes import UID, BoomProvider, Clock, Flip, Notes, fixed

from jarvis.health import probes as P
from jarvis.health.models import HealthReport, ProbeResult
from jarvis.health.report import compose_line, rollup
from jarvis.health.service import HealthService
from jarvis.health.store import HealthStore
from jarvis.llm.base import LLMUnreachable
from jarvis.storage.docs import MemoryDocs, Set
from jarvis.voice.service import SpeakRequest


def res(key: str, label: str, status: str) -> ProbeResult:
    return ProbeResult(key=key, label=label, status=status, reason="r", at=1.0)  # type: ignore[arg-type]


def report(*items: ProbeResult) -> HealthReport:
    return HealthReport(overall=rollup(items), results=tuple(items), at=1.0)


# ---- rollup and the spoken line ----------------------------------------------------------------
def test_rollup_is_the_worst_status() -> None:
    assert rollup([]) == "ok"
    assert rollup([res("a", "A", "ok")]) == "ok"
    assert rollup([res("a", "A", "ok"), res("b", "B", "degraded")]) == "degraded"
    assert rollup([res("a", "A", "degraded"), res("b", "B", "down")]) == "down"


def test_all_ok_line_is_the_fixed_nominal_sentence() -> None:
    assert compose_line(report(res("a", "Redis", "ok"))) == "All systems nominal, Sir."


def test_one_down_names_it_in_the_attention_template() -> None:
    line = compose_line(report(res("home", "the home bridge", "down"), res("r", "Redis", "ok")))
    assert line == "Attention: the home bridge is not answering."


def test_several_down_and_a_degraded_are_joined() -> None:
    line = compose_line(
        report(
            res("home", "the home bridge", "down"),
            res("r", "Redis", "down"),
            res("w", "web search", "degraded"),
        )
    )
    assert line == (
        "Attention: the home bridge and Redis are not answering. Web search is degraded."
    )


def test_line_never_contains_reason_text() -> None:
    bad = ProbeResult(key="x", label="Redis", status="down", reason="sk-ant-9 boom", at=1.0)
    assert "sk-ant" not in compose_line(report(bad))


def test_nothing_watched_has_its_own_line() -> None:
    assert "no systems" in compose_line(report()).lower()


# ---- the service -------------------------------------------------------------------------------
def service(*probes: P.Probe, notifier: Notes | None = None, voice: object = None) -> HealthService:
    return HealthService(
        list(probes),
        HealthStore(MemoryDocs(), prefix="jarvis_"),
        notifier=notifier,
        voice=voice,  # type: ignore[arg-type]
        clock=Clock(),
    )


async def test_check_stores_the_last_result_per_integration_and_overall() -> None:
    docs = MemoryDocs()
    svc = HealthService(
        [fixed("redis", "Redis", "ok"), fixed("home", "the home bridge", "down")],
        HealthStore(docs, prefix="jarvis_"),
        clock=Clock(),
    )
    rep = await svc.check(UID)
    raw = await docs.get(f"jarvis_health_last/{UID}")
    assert rep.overall == "down" and raw is not None
    assert raw["overall"] == "down" and raw["results"]["home"]["status"] == "down"
    last = await svc.last(UID)
    assert last == rep


async def test_last_is_none_before_any_run() -> None:
    assert await service(fixed("a", "A", "ok")).last(UID) is None


async def test_negative_control_a_down_integration_never_reports_ok() -> None:
    rep = await service(fixed("a", "A", "ok"), fixed("b", "B", "down")).check(UID)
    assert rep.overall != "ok"
    assert [r.status for r in rep.results if r.key == "b"] == ["down"]
    assert "nominal" not in compose_line(rep)


async def test_runs_with_the_brain_off_and_never_touches_the_provider() -> None:
    prov = BoomProvider(LLMUnreachable("no brain"))
    svc = service(
        P.brain_probe(P.provider_ping(prov, "m"), brain_mode="none"),  # type: ignore[arg-type]
        fixed("redis", "Redis", "ok"),
    )
    rep = await svc.check(UID)
    assert rep.overall == "ok" and prov.calls == 0
    assert compose_line(rep) == "All systems nominal, Sir."


async def test_runs_and_classifies_when_the_brain_is_unreachable() -> None:
    prov = BoomProvider(LLMUnreachable("down"))
    svc = service(
        P.brain_probe(P.provider_ping(prov, "m"), brain_mode="ai"),  # type: ignore[arg-type]
        fixed("redis", "Redis", "ok"),
    )
    rep = await svc.check(UID)
    brain = next(r for r in rep.results if r.key == "brain")
    assert brain.status == "down" and rep.overall == "down"
    assert compose_line(rep) == "Attention: the AI brain is not answering."


async def test_skipped_probes_are_left_out() -> None:
    async def skip(_uid: str) -> None:
        return None

    rep = await service(P.Probe(key="g", label="Google", check=skip)).check(UID)  # type: ignore[arg-type]
    assert rep.results == ()


# ---- alerts on change --------------------------------------------------------------------------
async def test_ok_to_fault_raises_an_urgent_health_fault_from_the_system_source() -> None:
    flip, notes = Flip(), Notes()
    svc = service(flip.probe, notifier=notes)
    await svc.check(UID)
    assert notes.sent == []
    flip.status = "down"
    await svc.check(UID)
    assert notes.kinds() == ["health_fault"]
    uid, signal, msg = notes.sent[0]
    assert uid == UID and signal.source == "system"
    assert msg == "Attention: the home bridge is not answering."


async def test_fault_to_ok_raises_health_recovered() -> None:
    flip, notes = Flip(), Notes()
    flip.status = "down"
    svc = service(flip.probe, notifier=notes)
    await svc.check(UID)
    flip.status = "ok"
    await svc.check(UID)
    assert notes.kinds() == ["health_fault", "health_recovered"]
    assert notes.sent[1][2] == "All systems nominal, Sir."


async def test_a_steady_fault_does_not_alert_again() -> None:
    flip, notes = Flip(), Notes()
    flip.status = "down"
    svc = service(flip.probe, notifier=notes)
    await svc.check(UID)
    await svc.check(UID)
    await svc.check(UID)
    assert notes.kinds() == ["health_fault"]


async def test_a_second_integration_failing_alerts_for_the_new_one_only() -> None:
    a, b, notes = Flip("redis", "Redis"), Flip("home", "the home bridge"), Notes()
    svc = service(a.probe, b.probe, notifier=notes)
    a.status = "down"
    await svc.check(UID)
    b.status = "down"
    await svc.check(UID)
    assert notes.kinds() == ["health_fault", "health_fault"]
    assert notes.sent[1][2] == "Attention: the home bridge is not answering."


async def test_first_run_all_ok_is_silent() -> None:
    notes = Notes()
    await service(fixed("a", "A", "ok"), notifier=notes).check(UID)
    assert notes.sent == []


async def test_no_notifier_is_fine() -> None:
    rep = await service(fixed("a", "A", "down")).check(UID)
    assert rep.overall == "down"


async def test_a_failing_notifier_does_not_fail_the_check() -> None:
    class Bad(Notes):
        async def notify(self, *a, **k):  # type: ignore[no-untyped-def]
            raise RuntimeError("telegram")

    rep = await service(fixed("a", "A", "down"), notifier=Bad()).check(UID)
    assert rep.overall == "down"


# ---- speaking ----------------------------------------------------------------------------------
class FakeVoice:
    def __init__(self) -> None:
        self.said: list[tuple[str, SpeakRequest]] = []

    async def speak(self, uid: str, req: SpeakRequest) -> object:
        self.said.append((uid, req))
        return "speech"


async def test_speak_reads_the_fixed_line_through_the_voice_service() -> None:
    voice = FakeVoice()
    svc = service(fixed("a", "A", "ok"), voice=voice)
    await svc.check(UID)
    out = await svc.speak(UID)
    assert out == "speech" and voice.said[0][1].text == "All systems nominal, Sir."


async def test_speak_without_a_voice_or_a_result_says_nothing() -> None:
    assert await service(fixed("a", "A", "ok")).speak(UID) is None
    svc = service(fixed("a", "A", "ok"), voice=FakeVoice())
    assert await svc.speak(UID) is None


# ---- store robustness --------------------------------------------------------------------------
async def test_unreadable_stored_doc_reads_as_none() -> None:
    docs = MemoryDocs()
    await docs.write([Set(f"jarvis_health_last/{UID}", {"overall": "weird", "results": 5})])
    assert await HealthStore(docs, prefix="jarvis_").last(UID) is None


@pytest.mark.parametrize("count", [1, 25])
async def test_many_probes_run_and_all_are_reported(count: int) -> None:
    probes = [fixed(f"k{i}", f"S{i}", "ok") for i in range(count)]
    rep = await service(*probes).check(UID)
    assert len(rep.results) == count
