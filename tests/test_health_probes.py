# tests/test_health_probes.py -- R4 D5: one probe per integration; no side effect; a timeout each;
# ok | degraded | down with a one-line fixed reason; no LLM on the path.
from __future__ import annotations

import asyncio

import pytest
from fallback_fakes import TIERS, CloudProvider
from health_fakes import NOW, UID, Clock
from research_fakes import fixed_mode

from jarvis.health import probes as P
from jarvis.health.models import LABELS, ProbeOutcome, ProbeResult
from jarvis.home.models import HomeStatus
from jarvis.home.store import HomeStoreUnavailable
from jarvis.integrations.google import GoogleAPIError, GoogleNotConnected, GoogleServiceDisabled
from jarvis.llm.router import BrainHealth, ModelRouter
from jarvis.storage.docs import MemoryDocs
from jarvis.telegram.client import TelegramError
from jarvis.web.ports import CreditsExhausted, VendorUsage, WebError


async def run(probe: P.Probe) -> ProbeResult | None:
    return await P.run_probe(probe, UID, clock=Clock())


# ---- the runner --------------------------------------------------------------------------------
async def test_a_probe_that_hangs_is_down_within_its_timeout() -> None:
    async def hang(_uid: str) -> ProbeOutcome:
        await asyncio.sleep(10)
        return ProbeOutcome("ok", "never")

    res = await run(P.Probe(key="x", label="x", check=hang, timeout_s=0.05))
    assert res is not None and res.status == "down" and "did not answer in time" in res.reason


async def test_a_probe_that_raises_is_down_and_the_reason_hides_vendor_text() -> None:
    async def bad(_uid: str) -> ProbeOutcome:
        raise RuntimeError("secret sk-ant-123 leaked")

    res = await run(P.Probe(key="x", label="x", check=bad))
    assert res is not None and res.status == "down"
    assert "sk-ant" not in res.reason and "secret" not in res.reason


async def test_a_probe_may_skip_itself_and_is_left_out() -> None:
    async def skip(_uid: str) -> None:
        return None

    assert await run(P.Probe(key="x", label="x", check=skip)) is None


async def test_the_result_carries_key_label_time() -> None:
    async def ok(_uid: str) -> ProbeOutcome:
        return ProbeOutcome("ok", "good")

    res = await run(P.Probe(key="redis", label="Redis", check=ok))
    assert res is not None
    assert (res.key, res.label, res.status, res.reason, res.at) == (
        "redis",
        "Redis",
        "ok",
        "good",
        NOW,
    )


# ---- brains (free: read from the router, never a model call) ----------------------------------
def reading(state: str, *, on_laptop: bool = False):  # type: ignore[no-untyped-def]
    calls = {"n": 0}

    def read() -> BrainHealth:
        calls["n"] += 1
        return BrainHealth(state=state, on_laptop=on_laptop)  # type: ignore[arg-type]

    return read, calls


@pytest.mark.parametrize(
    ("state", "on_laptop", "status"),
    [
        ("unknown", False, "ok"),
        ("ok", False, "ok"),
        ("busy", False, "degraded"),
        ("odd", False, "degraded"),
        ("refused", False, "down"),
        ("unreachable", False, "down"),
        ("unreachable", True, "degraded"),
    ],
)
async def test_brain_probe_reports_the_routers_last_outcome(
    state: str, on_laptop: bool, status: str
) -> None:
    read, _ = reading(state, on_laptop=on_laptop)
    res = await run(P.brain_probe(read, fixed_mode("ai")))
    assert res is not None and res.status == status


async def test_brain_probe_with_the_brain_off_reads_nothing_and_is_ok() -> None:
    read, calls = reading("unreachable")
    res = await run(P.brain_probe(read, fixed_mode("none")))
    assert res is not None and res.status == "ok" and "switched off" in res.reason
    assert calls["n"] == 0


async def test_brain_probe_makes_no_model_call_at_all() -> None:
    router = ModelRouter(CloudProvider(), TIERS)
    res = await run(P.brain_probe(router.health, fixed_mode("ai")))
    assert res is not None and res.status == "ok"
    assert router.provider.models == []  # type: ignore[attr-defined]


def test_the_probe_module_has_no_provider_ping_and_no_vendor_import() -> None:
    assert not hasattr(P, "provider_ping")
    assert not hasattr(P, "ChatMessage")


# ---- the runner never lets one probe kill the check ---------------------------------------------
async def test_an_overlong_reason_is_down_not_an_exception() -> None:
    async def wordy(_uid: str) -> ProbeOutcome:
        return ProbeOutcome("ok", "x" * 500)

    res = await run(P.Probe(key="x", label="x", check=wordy))
    assert res is not None and res.status == "down" and len(res.reason) < 120


@pytest.mark.parametrize("bad", ["ok", 7, ("ok", "fine"), {"status": "ok"}])
async def test_a_probe_answering_the_wrong_type_is_down(bad: object) -> None:
    async def odd(_uid: str) -> object:
        return bad

    res = await run(P.Probe(key="x", label="x", check=odd))  # type: ignore[arg-type]
    assert res is not None and res.status == "down"


async def test_an_unknown_status_value_is_down() -> None:
    async def odd(_uid: str) -> ProbeOutcome:
        return ProbeOutcome("great", "fine")  # type: ignore[arg-type]

    res = await run(P.Probe(key="x", label="x", check=odd))
    assert res is not None and res.status == "down"


def test_the_label_registry_covers_every_probe_key() -> None:
    assert set(LABELS) == {"brain", "google", "telegram", "home", "docs", "redis", "web"}


# ---- Google ------------------------------------------------------------------------------------
class FakeGoogle:
    def __init__(self, status: dict | None = None, exc: Exception | None = None) -> None:
        self._status = status or {"connected": True, "needs_reconnect": False}
        self._exc = exc
        self.requests: list[tuple[str, str]] = []

    async def status(self, uid: str) -> dict:
        return self._status

    async def request(self, uid: str, method: str, url: str, **kw: object) -> dict:
        self.requests.append((method, url))
        if self._exc:
            raise self._exc
        return {"id": "primary"}


async def test_google_ok_makes_one_get_metadata_call_only() -> None:
    g = FakeGoogle()
    res = await run(P.google_probe(g))  # type: ignore[arg-type]
    assert res is not None and res.status == "ok"
    assert [m for m, _ in g.requests] == ["GET"]


async def test_google_never_connected_is_left_out() -> None:
    g = FakeGoogle({"connected": False, "needs_reconnect": False})
    assert await run(P.google_probe(g)) is None  # type: ignore[arg-type]
    assert g.requests == []


async def test_google_needing_a_reconnect_is_degraded() -> None:
    g = FakeGoogle({"connected": False, "needs_reconnect": True})
    res = await run(P.google_probe(g))  # type: ignore[arg-type]
    assert res is not None and res.status == "degraded" and "reconnect" in res.reason


@pytest.mark.parametrize(
    ("exc", "status"),
    [
        (GoogleNotConnected("x"), "degraded"),
        (GoogleServiceDisabled("x"), "degraded"),
        (GoogleAPIError("x"), "down"),
        (OSError("net"), "down"),
    ],
)
async def test_google_errors_are_classified(exc: Exception, status: str) -> None:
    res = await run(P.google_probe(FakeGoogle(exc=exc)))  # type: ignore[arg-type]
    assert res is not None and res.status == status


# ---- Telegram ----------------------------------------------------------------------------------
class FakeTelegram:
    def __init__(self, exc: Exception | None = None) -> None:
        self.exc = exc
        self.calls: list[str] = []

    async def call(self, method: str, payload: object = None) -> object:
        self.calls.append(method)
        if self.exc:
            raise self.exc
        return {"username": "jarvis_bot"}


async def test_telegram_calls_get_me_only() -> None:
    t = FakeTelegram()
    res = await run(P.telegram_probe(t))  # type: ignore[arg-type]
    assert res is not None and res.status == "ok" and t.calls == ["getMe"]


async def test_telegram_failure_is_down() -> None:
    t = FakeTelegram(TelegramError("getMe", "boom"))
    res = await run(P.telegram_probe(t))  # type: ignore[arg-type]
    assert res is not None and res.status == "down"


# ---- home bridge -------------------------------------------------------------------------------
class FakeHome:
    def __init__(self, status: HomeStatus | None, exc: Exception | None = None) -> None:
        self._s, self._e = status, exc

    async def status(self, uid: str) -> HomeStatus | None:
        if self._e:
            raise self._e
        return self._s


def home_status(seen: float | None, state: str = "online") -> HomeStatus:
    return HomeStatus(home_id="h", state=state, linked_at=1.0, last_seen_at=seen)  # type: ignore[arg-type]


async def home(status: HomeStatus | None, exc: Exception | None = None) -> ProbeResult | None:
    probe = P.home_probe(FakeHome(status, exc), clock=Clock(), offline_after_s=720)  # type: ignore[arg-type]
    return await run(probe)


async def test_home_with_a_fresh_heartbeat_is_ok() -> None:
    res = await home(home_status(NOW - 60))
    assert res is not None and res.status == "ok"


async def test_home_with_a_stale_heartbeat_is_down() -> None:
    res = await home(home_status(NOW - 3600))
    assert res is not None and res.status == "down" and "60 minutes" in res.reason


async def test_home_marked_offline_is_down_even_with_a_recent_stamp() -> None:
    res = await home(home_status(NOW - 10, "offline"))
    assert res is not None and res.status == "down"


async def test_home_that_never_reported_is_down() -> None:
    res = await home(home_status(None))
    assert res is not None and res.status == "down"


async def test_home_not_linked_is_left_out() -> None:
    assert await home(None) is None


async def test_home_store_trouble_is_down() -> None:
    res = await home(None, HomeStoreUnavailable("x"))
    assert res is not None and res.status == "down"


# ---- docs, redis, web search -------------------------------------------------------------------
async def test_docs_probe_reads_one_document_and_writes_nothing() -> None:
    docs = MemoryDocs()
    res = await run(P.docs_probe(docs, prefix="jarvis_"))
    assert res is not None and res.status == "ok"
    assert docs.reads == 1 and docs.sets == 0


async def test_docs_probe_failure_is_down() -> None:
    class Broken(MemoryDocs):
        async def get(self, path: str):  # type: ignore[no-untyped-def]
            raise ConnectionError("firestore")

    res = await run(P.docs_probe(Broken(), prefix="jarvis_"))
    assert res is not None and res.status == "down"


async def test_redis_probe_ok_and_down() -> None:
    async def good() -> object:
        return True

    async def bad() -> object:
        raise ConnectionError("refused")

    ok, down = await run(P.redis_probe(good)), await run(P.redis_probe(bad))
    assert ok is not None and ok.status == "ok"
    assert down is not None and down.status == "down"


class FakeUsage:
    def __init__(self, out: VendorUsage | None = None, exc: Exception | None = None) -> None:
        self.out, self.exc = out, exc

    async def usage(self) -> VendorUsage:
        if self.exc:
            raise self.exc
        assert self.out is not None
        return self.out


async def test_web_probe_uses_the_free_usage_call() -> None:
    res = await run(P.web_probe(FakeUsage(VendorUsage(used=3, limit=1000))))  # type: ignore[arg-type]
    assert res is not None and res.status == "ok"


async def test_web_probe_credits_gone_is_degraded() -> None:
    res = await run(P.web_probe(FakeUsage(VendorUsage(used=1000, limit=1000, exhausted=True))))  # type: ignore[arg-type]
    assert res is not None and res.status == "degraded" and "credits" in res.reason


@pytest.mark.parametrize("exc", [WebError("x"), CreditsExhausted("x"), OSError("n")])
async def test_web_probe_errors_are_not_ok(exc: Exception) -> None:
    res = await run(P.web_probe(FakeUsage(exc=exc)))  # type: ignore[arg-type]
    assert res is not None and res.status in ("degraded", "down")
