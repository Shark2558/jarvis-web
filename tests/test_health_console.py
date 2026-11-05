# tests/test_health_console.py -- R4 D6: the Systems panel script and the /v1/health routes.
from __future__ import annotations

import re
from pathlib import Path

from fastapi import Depends, FastAPI
from health_fakes import UID, Clock, fixed
from httpx import ASGITransport, AsyncClient

from jarvis.health.api import RUN_PER_MINUTE, health_router
from jarvis.health.models import ProbeOutcome
from jarvis.health.probes import Probe
from jarvis.health.service import HealthService
from jarvis.health.store import HealthStore
from jarvis.storage.docs import MemoryDocs
from jarvis.voice.ports import VoiceUnavailable

JS = Path(__file__).resolve().parents[1] / "src/jarvis/api/static/console-systems.js"


def test_script_is_ascii_small_and_self_hosted() -> None:
    text = JS.read_text(encoding="utf-8")
    assert text.isascii() and len(text.splitlines()) <= 800
    assert not re.search(r"https?://", text.replace("// ", ""))
    assert "<script" not in text and "import(" not in text


def test_script_only_writes_text_never_markup() -> None:
    text = JS.read_text(encoding="utf-8")
    for banned in ("innerHTML", "outerHTML", "insertAdjacentHTML", "document.write", "eval("):
        assert banned not in text
    assert "textContent" in text


def test_script_has_run_and_speak_and_the_three_states() -> None:
    text = JS.read_text(encoding="utf-8")
    for needle in ("/v1/health", "/v1/health/run", "Run", "Speak", "ok", "degraded", "down"):
        assert needle in text


def test_script_shows_no_currency() -> None:
    text = JS.read_text(encoding="utf-8")
    assert "USD" not in text and "dollar" not in text.lower()


# ---- routes ------------------------------------------------------------------------------------
class Voice:
    def __init__(self, exc: Exception | None = None) -> None:
        self.exc = exc

    async def speak(self, uid: str, req: object):  # type: ignore[no-untyped-def]
        if self.exc:
            raise self.exc

        class S:
            audio = b"MP3"
            chars = 3
            cost_inr = 0.0

        return S()


def app(voice: object = None) -> tuple[FastAPI, HealthService]:
    s = HealthService(
        [fixed("a", "Redis", "ok"), fixed("b", "the home bridge", "down")],
        HealthStore(MemoryDocs(), prefix="jarvis_"),
        voice=voice,  # type: ignore[arg-type]
        clock=Clock(),
    )
    a = FastAPI()
    a.include_router(health_router(s, user=lambda: UID, dependencies=[Depends(lambda: None)]))
    return a, s


async def get(a: FastAPI, method: str, path: str):  # type: ignore[no-untyped-def]
    async with AsyncClient(transport=ASGITransport(app=a), base_url="http://t") as c:
        return await c.request(method, path)


async def test_get_before_any_run_says_so() -> None:
    a, _ = app()
    r = await get(a, "GET", "/v1/health")
    assert r.status_code == 200 and r.json()["overall"] is None and r.json()["systems"] == []


async def test_run_then_get_shows_each_integration_and_the_line() -> None:
    a, _ = app()
    run = await get(a, "POST", "/v1/health/run")
    last = await get(a, "GET", "/v1/health")
    assert run.json() == last.json()
    body = last.json()
    assert body["overall"] == "down"
    assert body["spoken"] == "Attention: the home bridge is not answering."
    assert {s["name"]: s["status"] for s in body["systems"]} == {
        "Redis": "ok",
        "the home bridge": "down",
    }


async def test_speak_returns_audio_of_the_last_result() -> None:
    a, s = app(Voice())
    await s.check(UID)
    r = await get(a, "POST", "/v1/health/speak")
    assert (
        r.status_code == 200 and r.content == b"MP3" and r.headers["content-type"] == "audio/mpeg"
    )


async def test_speak_with_nothing_run_is_409_and_voice_trouble_is_503() -> None:
    a, s = app(Voice())
    assert (await get(a, "POST", "/v1/health/speak")).status_code == 409
    await s.check(UID)
    a2, s2 = app(Voice(VoiceUnavailable("not_configured")))
    await s2.check(UID)
    assert (await get(a2, "POST", "/v1/health/speak")).status_code == 503


async def test_speak_other_voice_error_is_422_and_no_voice_is_503() -> None:
    from jarvis.voice.ports import NothingToSay

    a, s = app(Voice(NothingToSay()))
    await s.check(UID)
    assert (await get(a, "POST", "/v1/health/speak")).status_code == 422
    a2, s2 = app(None)
    await s2.check(UID)
    assert (await get(a2, "POST", "/v1/health/speak")).status_code == 503


# ---- review fixes ------------------------------------------------------------------------------
async def test_the_empty_answer_is_a_fresh_dict_each_time() -> None:
    a, _ = app()
    first = (await get(a, "GET", "/v1/health")).json()
    first["systems"].append("x")
    assert (await get(a, "GET", "/v1/health")).json()["systems"] == []


async def test_voice_unavailable_never_echoes_the_vendor_reason() -> None:
    a, s = app(Voice(VoiceUnavailable("not_configured")))
    await s.check(UID, force=True)
    r = await get(a, "POST", "/v1/health/speak")
    assert r.status_code == 503 and "not_configured" not in r.text and "reason" not in r.json()


async def test_run_and_speak_are_rate_limited_per_owner_inside_the_router() -> None:
    a, s = app(Voice())
    await s.check(UID, force=True)
    codes = [
        (await get(a, "POST", "/v1/health/run")).status_code for _ in range(RUN_PER_MINUTE + 2)
    ]
    assert codes[:RUN_PER_MINUTE] == [200] * RUN_PER_MINUTE and codes[-1] == 429
    assert (await get(a, "POST", "/v1/health/speak")).status_code == 429  # shared budget


async def test_a_run_inside_the_cooldown_does_not_rerun_the_probes() -> None:
    n = {"runs": 0}

    async def counted(_uid: str) -> ProbeOutcome:
        n["runs"] += 1
        return ProbeOutcome("ok", "fine")

    s = HealthService(
        [Probe(key="redis", label="Redis", check=counted)],
        HealthStore(MemoryDocs(), prefix="jarvis_"),
        clock=Clock(),
    )
    a = FastAPI()
    a.include_router(health_router(s, user=lambda: UID))
    await get(a, "POST", "/v1/health/run")
    await get(a, "POST", "/v1/health/run")
    assert n["runs"] == 1
