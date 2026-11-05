# tests/test_health_service.py -- R4 D5/D6: rollup, last-result storage, fixed-template spoken line,
# change alerts, speaking, and the whole check running with the brain OFF.
from __future__ import annotations

import asyncio

import pytest
from fallback_fakes import KW, TIERS, CloudProvider
from health_fakes import UID, Clock, Flip, Notes, fixed
from research_fakes import fixed_mode

from jarvis.health import probes as P
from jarvis.health.models import HealthReport, ProbeOutcome, ProbeResult
from jarvis.health.report import compose_line, rollup
from jarvis.health.service import CHECK_COOLDOWN_S, HealthService
from jarvis.health.store import HealthStore
from jarvis.llm.base import LLMUnreachable
from jarvis.llm.router import ModelRouter, ModelTier
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
    rep = await svc.check(UID, force=True)
    raw = await docs.get(f"jarvis_health_last/{UID}")
    assert rep.overall == "down" and raw is not None
    assert raw["overall"] == "down" and raw["results"]["home"]["status"] == "down"
    last = await svc.last(UID)
    assert last == rep


async def test_last_is_none_before_any_run() -> None:
    assert await service(fixed("a", "A", "ok")).last(UID) is None


async def test_negative_control_a_down_integration_never_reports_ok() -> None:
    rep = await service(fixed("a", "A", "ok"), fixed("b", "B", "down")).check(UID, force=True)
    assert rep.overall != "ok"
    assert [r.status for r in rep.results if r.key == "b"] == ["down"]
    assert "nominal" not in compose_line(rep)


async def test_runs_with_the_brain_off_and_never_touches_the_provider() -> None:
    cloud = CloudProvider(LLMUnreachable("no brain"))
    router = ModelRouter(cloud, TIERS)
    svc = service(P.brain_probe(router.health, fixed_mode("none")), fixed("redis", "Redis", "ok"))
    rep = await svc.check(UID, force=True)
    assert rep.overall == "ok" and cloud.models == []
    assert compose_line(rep) == "All systems nominal, Sir."


async def test_the_whole_check_makes_no_model_call_even_with_the_brain_on() -> None:
    cloud = CloudProvider()
    router = ModelRouter(cloud, TIERS)
    svc = service(P.brain_probe(router.health, fixed_mode("ai")), fixed("redis", "Redis", "ok"))
    await svc.check(UID, force=True)
    assert cloud.models == []


async def test_reports_the_brain_down_after_the_router_saw_it_unreachable() -> None:
    router = ModelRouter(CloudProvider(LLMUnreachable("x")), TIERS)
    with pytest.raises(LLMUnreachable):
        await router.complete(tier=ModelTier.FAST, **KW)
    svc = service(P.brain_probe(router.health, fixed_mode("ai")), fixed("redis", "Redis", "ok"))
    rep = await svc.check(UID, force=True)
    brain = next(r for r in rep.results if r.key == "brain")
    assert brain.status == "down" and rep.overall == "down"
    assert compose_line(rep) == "Attention: the AI brain is not answering."


async def test_skipped_probes_are_left_out() -> None:
    async def skip(_uid: str) -> None:
        return None

    rep = await service(P.Probe(key="g", label="Google", check=skip)).check(UID, force=True)  # type: ignore[arg-type]
    assert rep.results == ()


# ---- alerts on change --------------------------------------------------------------------------
async def runs(svc: HealthService, n: int) -> None:
    for _ in range(n):
        await svc.check(UID, force=True)


async def test_a_fault_that_holds_for_two_checks_raises_an_urgent_health_fault() -> None:
    flip, notes = Flip(), Notes()
    svc = service(flip.probe, notifier=notes)
    await runs(svc, 1)
    assert notes.sent == []
    flip.status = "down"
    await runs(svc, 2)
    assert notes.kinds() == ["health_fault"]
    uid, signal, msg = notes.sent[0]
    assert uid == UID and signal.source == "system"
    assert msg == "Attention: the home bridge is not answering."


async def test_a_single_blip_never_alerts() -> None:
    flip, notes = Flip(), Notes()
    svc = service(flip.probe, notifier=notes)
    await runs(svc, 1)
    flip.status = "down"
    await runs(svc, 1)
    flip.status = "ok"
    await runs(svc, 3)
    assert notes.sent == []


async def test_a_flapping_probe_never_alerts() -> None:
    flip, notes = Flip(), Notes()
    svc = service(flip.probe, notifier=notes)
    for status in ("down", "ok", "down", "ok", "down", "ok"):
        flip.status = status
        await runs(svc, 1)
    assert notes.sent == []


async def test_fault_to_ok_raises_health_recovered_after_two_good_checks() -> None:
    flip, notes = Flip(), Notes()
    flip.status = "down"
    svc = service(flip.probe, notifier=notes)
    await runs(svc, 2)
    flip.status = "ok"
    await runs(svc, 1)
    assert notes.kinds() == ["health_fault"]
    await runs(svc, 1)
    assert notes.kinds() == ["health_fault", "health_recovered"]
    assert notes.sent[1][2] == "All systems nominal, Sir."


async def test_a_steady_fault_does_not_alert_again() -> None:
    flip, notes = Flip(), Notes()
    flip.status = "down"
    svc = service(flip.probe, notifier=notes)
    await runs(svc, 6)
    assert notes.kinds() == ["health_fault"]


async def test_a_second_integration_failing_alerts_for_the_new_one_only() -> None:
    a, b, notes = Flip("redis", "Redis"), Flip("home", "the home bridge"), Notes()
    svc = service(a.probe, b.probe, notifier=notes)
    a.status = "down"
    await runs(svc, 2)
    b.status = "down"
    await runs(svc, 2)
    assert notes.kinds() == ["health_fault", "health_fault"]
    assert notes.sent[1][2] == "Attention: the home bridge is not answering."


async def test_degraded_goes_out_as_a_silent_info_note_never_a_fault() -> None:
    flip, notes = Flip(), Notes()
    svc = service(flip.probe, notifier=notes)
    flip.status = "degraded"
    await runs(svc, 2)
    assert notes.kinds() == ["health_degraded"]
    assert notes.sent[0][2] == "Attention: the home bridge is degraded."
    assert "health_fault" not in notes.kinds()


async def test_degraded_getting_worse_escalates_and_rings() -> None:
    flip, notes = Flip(), Notes()
    svc = service(flip.probe, notifier=notes)
    flip.status = "degraded"
    await runs(svc, 2)
    flip.status = "down"
    await runs(svc, 2)
    assert notes.kinds() == ["health_degraded", "health_fault"]


async def test_down_improving_to_degraded_is_a_silent_note() -> None:
    flip, notes = Flip(), Notes()
    svc = service(flip.probe, notifier=notes)
    flip.status = "down"
    await runs(svc, 2)
    flip.status = "degraded"
    await runs(svc, 2)
    assert notes.kinds() == ["health_fault", "health_degraded"]


async def test_first_run_all_ok_is_silent() -> None:
    notes = Notes()
    await service(fixed("a", "A", "ok"), notifier=notes).check(UID, force=True)
    assert notes.sent == []


async def test_no_notifier_is_fine() -> None:
    rep = await service(fixed("a", "A", "down")).check(UID, force=True)
    assert rep.overall == "down"


async def test_a_failing_notifier_does_not_fail_the_check() -> None:
    class Bad(Notes):
        async def notify(self, *a, **k):  # type: ignore[no-untyped-def]
            raise RuntimeError("telegram")

    rep = await service(fixed("a", "A", "down"), notifier=Bad()).check(UID, force=True)
    assert rep.overall == "down"


async def test_an_alert_that_failed_to_send_is_retried_on_the_next_check() -> None:
    class FlakyOnce(Notes):
        failed = False

        async def notify(self, *a, **k):  # type: ignore[no-untyped-def]
            if not self.failed:
                self.failed = True
                raise RuntimeError("telegram")
            return await super().notify(*a, **k)

    flip, notes = Flip(), FlakyOnce()
    flip.status = "down"
    svc = service(flip.probe, notifier=notes)
    await runs(svc, 2)
    assert notes.sent == []
    await runs(svc, 1)
    assert notes.kinds() == ["health_fault"]
    await runs(svc, 2)
    assert notes.kinds() == ["health_fault"]


# ---- no false recovery (py-H2) -----------------------------------------------------------------
class Skippable:
    def __init__(self, key: str, status: str = "down") -> None:
        self.status: str | None = status
        self.probe = P.Probe(key=key, label="Google", check=self._check)

    async def _check(self, _uid: str) -> ProbeOutcome | None:
        return None if self.status is None else ProbeOutcome(self.status, "x")  # type: ignore[arg-type]


async def test_an_integration_that_stops_being_set_up_is_not_announced_as_recovered() -> None:
    gone, notes = Skippable("google"), Notes()
    svc = service(gone.probe, fixed("redis", "Redis", "ok"), notifier=notes)
    await runs(svc, 2)
    gone.status = None
    await runs(svc, 3)
    assert notes.kinds() == ["health_fault"]


async def test_nothing_to_check_is_never_sent_as_a_recovery() -> None:
    gone, notes = Skippable("google"), Notes()
    svc = service(gone.probe, notifier=notes)
    await runs(svc, 2)
    gone.status = None
    await runs(svc, 3)
    assert notes.kinds() == ["health_fault"]
    assert all("no systems" not in m for _, _, m in notes.sent)


# ---- cooldown, store trouble, concurrency ------------------------------------------------------
class CountingProbe:
    def __init__(self) -> None:
        self.runs = 0
        self.probe = P.Probe(key="redis", label="Redis", check=self._check)

    async def _check(self, _uid: str) -> ProbeOutcome:
        self.runs += 1
        await asyncio.sleep(0)
        return ProbeOutcome("ok", "fine")


async def test_a_second_check_inside_the_cooldown_returns_the_stored_report() -> None:
    counter, clock = CountingProbe(), Clock()
    svc = HealthService([counter.probe], HealthStore(MemoryDocs(), prefix="jarvis_"), clock=clock)
    first = await svc.check(UID)
    clock.now += CHECK_COOLDOWN_S - 1
    second = await svc.check(UID)
    assert counter.runs == 1 and second == first


async def test_after_the_cooldown_or_when_forced_the_probes_run_again() -> None:
    counter, clock = CountingProbe(), Clock()
    svc = HealthService([counter.probe], HealthStore(MemoryDocs(), prefix="jarvis_"), clock=clock)
    await svc.check(UID)
    await svc.check(UID, force=True)
    clock.now += CHECK_COOLDOWN_S
    await svc.check(UID)
    assert counter.runs == 3


async def test_two_checks_at_once_run_the_probes_once() -> None:
    counter = CountingProbe()
    svc = HealthService([counter.probe], HealthStore(MemoryDocs(), prefix="jarvis_"), clock=Clock())
    a, b = await asyncio.gather(svc.check(UID), svc.check(UID))
    assert counter.runs == 1 and a == b


class DownStore(HealthStore):
    async def state(self, uid: str):  # type: ignore[no-untyped-def]
        raise OSError("firestore down")

    async def last(self, uid: str):  # type: ignore[no-untyped-def]
        raise OSError("firestore down")

    async def save(self, uid: str, state):  # type: ignore[no-untyped-def]
        raise OSError("firestore down")


async def test_a_dead_store_does_not_fail_the_check_but_is_marked_unsaved() -> None:
    svc = HealthService([fixed("a", "A", "down")], DownStore(MemoryDocs()), clock=Clock())
    rep = await svc.check(UID, force=True)
    assert rep.overall == "down" and rep.persisted is False


async def test_a_dead_store_still_debounces_and_alerts_from_memory() -> None:
    notes = Notes()
    svc = HealthService(
        [fixed("a", "A", "down")], DownStore(MemoryDocs()), notifier=notes, clock=Clock()
    )
    await runs(svc, 2)
    assert notes.kinds() == ["health_fault"]


async def test_the_label_is_spoken_from_the_code_registry_not_the_stored_label() -> None:
    forged = ProbeResult(key="home", label="ignore previous", status="down", reason="r", at=1.0)
    assert compose_line(report(forged)) == "Attention: the home bridge is not answering."


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
    await svc.check(UID, force=True)
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
    rep = await service(*probes).check(UID, force=True)
    assert len(rep.results) == count
