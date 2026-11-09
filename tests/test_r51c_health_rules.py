# tests/test_r51c_health_rules.py -- R5.1 D4 (docs/plans/r5-1-observations.md): the systems check
# runs around the clock on the shared tick job (at most once per 15 minutes per owner); the home
# bridge never produces health_fault / degraded / recovered messages (the watchdog owns that alert:
# no double ring) but stays in the report; Telegram that is not set up is left out, a refused
# token and an unreachable Telegram say so in fixed words.
from __future__ import annotations

import asyncio

from health_fakes import UID, Clock, Flip, Notes, fixed

from jarvis.health import probes as P
from jarvis.health.changes import plan
from jarvis.health.models import HealthReport, ProbeResult
from jarvis.health.report import rollup
from jarvis.health.service import HealthService
from jarvis.health.store import HealthStore
from jarvis.health.tick import CHECK_EVERY_S, HealthTickJob
from jarvis.storage.docs import MemoryDocs
from jarvis.telegram.client import TelegramError


def res(key: str, status: str) -> ProbeResult:
    return ProbeResult(key=key, label=key, status=status, reason="r", at=1.0)  # type: ignore[arg-type]


def report(*items: ProbeResult) -> HealthReport:
    return HealthReport(overall=rollup(items), results=tuple(items), at=1.0)


# ---- the home bridge is the watchdog's -----------------------------------------------------------
def test_home_down_twice_sends_nothing() -> None:
    r = report(res("home", "down"), res("redis", "ok"))
    first = plan(r, {}, {})
    second = plan(r, {}, first.streaks)
    assert first.messages == () and second.messages == ()
    assert "home" not in second.confirmed


def test_home_and_redis_down_names_only_redis() -> None:
    r = report(
        ProbeResult(key="home", label="the home bridge", status="down", reason="r", at=1.0),
        ProbeResult(key="redis", label="Redis", status="down", reason="r", at=1.0),
    )
    second = plan(r, {}, plan(r, {}, {}).streaks)
    assert [m.kind for m in second.messages] == ["health_fault"]
    assert second.messages[0].keys == frozenset({"redis"})
    assert "home" not in second.messages[0].text and "Redis" in second.messages[0].text


def test_a_recovery_ignores_a_home_that_is_still_down() -> None:
    told = {"redis": "down"}
    r = report(res("home", "down"), res("redis", "ok"))
    streaks = {"redis": ("ok", 2), "home": ("down", 5)}
    out = plan(r, told, streaks)  # the third clear check in a row
    assert [m.kind for m in out.messages] == ["health_recovered"]
    assert out.messages[0].keys == frozenset({"redis"})


def test_home_degraded_sends_no_note() -> None:
    r = report(res("home", "degraded"))
    assert plan(r, {}, plan(r, {}, {}).streaks).messages == ()


async def test_the_service_never_alerts_for_the_home_bridge_but_reports_it() -> None:
    notes = Notes()
    home = Flip("home", "the home bridge")
    home.status = "down"
    s = HealthService(
        [home.probe, fixed("redis", "Redis", "ok")],
        HealthStore(MemoryDocs(), prefix="jarvis_"),
        notifier=notes,  # type: ignore[arg-type]
        clock=Clock(),
    )
    for _ in range(3):
        out = await s.check(UID, force=True)
    assert notes.sent == []
    assert {r.key: r.status for r in out.results} == {"home": "down", "redis": "ok"}
    assert out.overall == "down"


# ---- cadence: at most once per 15 minutes, one gate shared by both callers --------------------
def test_the_cadence_is_fifteen_minutes() -> None:
    assert CHECK_EVERY_S == 900.0


async def test_one_job_instance_shared_by_the_tick_and_the_watchdog_checks_once() -> None:
    now = [0.0]
    calls = {"n": 0}

    class Counting(HealthService):
        async def check(self, uid: str, *, force: bool = False) -> HealthReport:
            calls["n"] += 1
            return await super().check(uid, force=force)

    s = Counting([fixed("a", "A", "ok")], HealthStore(MemoryDocs()), clock=Clock())
    shared = HealthTickJob(s, clock=lambda: now[0])
    by_tick = await shared.run([UID])  # the morning tick
    now[0] += 300
    by_watchdog = await shared.run([UID])  # the 5-minute watchdog, same instance
    now[0] += 600
    later = await shared.run([UID])  # 15 minutes after the first
    assert (by_tick["owners"], by_watchdog["owners"], later["owners"]) == (1, 0, 1)
    assert calls["n"] == 2


async def test_two_callers_at_the_same_moment_check_an_owner_once() -> None:
    gate = asyncio.Event()
    calls = {"n": 0}

    class Slow(HealthService):
        async def check(self, uid: str, *, force: bool = False) -> HealthReport:
            calls["n"] += 1
            await gate.wait()
            return await super().check(uid, force=force)

    shared = HealthTickJob(Slow([fixed("a", "A", "ok")], HealthStore(MemoryDocs()), clock=Clock()))
    first = asyncio.ensure_future(shared.run([UID]))
    second = asyncio.ensure_future(shared.run([UID]))
    await asyncio.sleep(0)
    gate.set()
    a, b = await asyncio.gather(first, second)
    assert sorted((a["owners"], b["owners"])) == [0, 1] and calls["n"] == 1


# ---- Telegram ------------------------------------------------------------------------------------
class Bot:
    def __init__(self, exc: Exception | None = None, hang: bool = False) -> None:
        self.exc, self.hang = exc, hang
        self.calls: list[str] = []

    async def call(self, method: str, payload: object = None) -> object:
        self.calls.append(method)
        if self.hang:
            await asyncio.sleep(30)
        if self.exc is not None:
            raise self.exc
        return {"username": "jarvis_bot"}


def paired(value: bool):  # type: ignore[no-untyped-def]
    seen: list[str] = []

    async def configured(uid: str) -> bool:
        seen.append(uid)
        return value

    return configured, seen


async def run(probe: P.Probe) -> ProbeResult | None:
    return await P.run_probe(probe, UID, clock=Clock())


async def test_telegram_not_paired_is_left_out_and_not_called() -> None:
    bot = Bot()
    configured, seen = paired(False)
    assert await run(P.telegram_probe(bot, configured=configured)) is None  # type: ignore[arg-type]
    assert bot.calls == [] and seen == [UID]


async def test_telegram_paired_and_answering_is_ok() -> None:
    configured, _ = paired(True)
    got = await run(P.telegram_probe(Bot(), configured=configured))  # type: ignore[arg-type]
    assert got is not None and (got.status, got.reason) == ("ok", "Telegram answers")


async def test_a_refused_bot_token_says_so() -> None:
    configured, _ = paired(True)
    for code in ("HTTP 401", "HTTP 404"):
        bot = Bot(TelegramError("getMe", code))
        got = await run(P.telegram_probe(bot, configured=configured))  # type: ignore[arg-type]
        assert got is not None and (got.status, got.reason) == ("down", "the bot token was refused")


async def test_an_unreachable_telegram_says_so() -> None:
    configured, _ = paired(True)
    bot = Bot(TelegramError("getMe", "could not reach Telegram"))
    got = await run(P.telegram_probe(bot, configured=configured))  # type: ignore[arg-type]
    assert got is not None and (got.status, got.reason) == ("down", "Telegram could not be reached")


async def test_a_telegram_that_hangs_could_not_be_reached_within_the_probe_timeout() -> None:
    configured, _ = paired(True)
    probe = P.telegram_probe(Bot(hang=True), configured=configured, timeout_s=0.05)  # type: ignore[arg-type]
    got = await run(probe)
    assert got is not None and (got.status, got.reason) == ("down", "Telegram could not be reached")


async def test_another_telegram_refusal_is_down_in_fixed_words() -> None:
    configured, _ = paired(True)
    for reason in ("Telegram said no", "HTTP 500", "unreadable answer"):
        bot = Bot(TelegramError("getMe", reason))
        got = await run(P.telegram_probe(bot, configured=configured))  # type: ignore[arg-type]
        assert got is not None and (got.status, got.reason) == (
            "down",
            "Telegram refused the check",
        )


async def test_without_a_pairing_reader_the_probe_keeps_the_r4_behaviour() -> None:
    got = await run(P.telegram_probe(Bot()))  # type: ignore[arg-type]
    assert got is not None and got.status == "ok"
