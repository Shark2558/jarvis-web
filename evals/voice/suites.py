# evals/voice/suites.py
"""Slice 9 mock suites: speakable shaping, persona assembly, billing (+ negative control),
provider error mapping and transcribe input validation. Every gate is hard (100 %)."""

from __future__ import annotations

import json
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import httpx
from harness import (
    RATE,
    UID,
    WAV,
    GoogleShaped,
    ScriptedSTT,
    ScriptedTTS,
    Tokens,
    app_client,
    settings,
    wav,
)

from jarvis.billing import (
    Billing,
    BudgetReached,
    BudgetStore,
    BudgetUnavailable,
    FxRates,
    UsageMeter,
)
from jarvis.core.brain import Brain
from jarvis.core.models import ChatRequest
from jarvis.core.prompts import (
    HARD_LIMITS,
    VOICE_RULE_HEADING,
    WIT_LEVELS,
    build_system_prompt,
)
from jarvis.llm.brains import BrainRegistry, BrainSpec
from jarvis.llm.mock_provider import MockProvider
from jarvis.llm.router import ModelTier
from jarvis.memory.inmemory import InMemorySessionStore
from jarvis.storage.docs import DocTx, MemoryDocs
from jarvis.voice.catalogue import PriceList
from jarvis.voice.google_cloud import GoogleSTT, GoogleTTS
from jarvis.voice.service import SpeakRequest, VoiceEngines, VoiceService
from jarvis.voice.settings import VoiceSettingsStore
from jarvis.voice.speakable import speakable

HERE = Path(__file__).parent


def _load(name: str) -> list[dict[str, Any]]:
    text = (HERE / name).read_text(encoding="utf-8")
    return [json.loads(ln) for ln in text.split("\n") if ln.strip()]


@contextmanager
def patched(obj: Any, attr: str, value: Any) -> Iterator[None]:
    old = getattr(obj, attr)
    setattr(obj, attr, value)
    try:
        yield
    finally:
        setattr(obj, attr, old)


def _verdict(results: list[dict[str, Any]], **extra: Any) -> dict[str, Any]:
    rate = sum(r["passed"] for r in results) / len(results) if results else 0.0
    return {
        "cases": len(results),
        "pass_rate": rate,
        "gate": rate == 1,
        **extra,
        "results": results,
    }


# ---- speakable -------------------------------------------------------------------------------


def suite_speakable() -> dict[str, Any]:
    results = []
    for c in _load("cases_speakable.jsonl"):
        got = speakable(c["in"])
        fails: list[str] = []
        if "out" in c and got != c["out"]:
            fails.append(f"got {got!r}")
        if c.get("empty") and got:
            fails.append(f"expected nothing, got {got!r}")
        if "max" in c and len(got) > c["max"]:
            fails.append(f"{len(got)} > {c['max']} chars")
        if "min" in c and len(got) < c["min"]:
            fails.append(f"{len(got)} < {c['min']} chars")
        if "ends" in c and not got.endswith(c["ends"]):
            fails.append(f"does not end with {c['ends']!r}")
        fails += [f"contains {x!r}" for x in c.get("not", []) if x in got]
        results.append({"id": c["id"], "why": c["why"], "passed": not fails, "failures": fails})
    out = _verdict(results)
    out["gate"] = out["gate"] and len(results) >= 40
    return out


# ---- persona ---------------------------------------------------------------------------------


class _Wit:
    def __init__(self, level: str) -> None:
        self.level = level

    async def wit_for(self, uid: str) -> str:
        return self.level


def _brain(level: str, *, training: bool) -> tuple[Brain, MockProvider]:
    p = MockProvider()
    model = "gemini-3.8-flash" if training else "mock-balanced"
    spec = BrainSpec(
        id="b",
        label="B",
        provider=p,
        tiers={t: model for t in ModelTier},
        trains_on_content=training,
    )
    reg = BrainRegistry([spec], default_id="b")
    brain = Brain(brains=reg, store=InMemorySessionStore(), settings=settings(), wit=_Wit(level))
    return brain, p


async def suite_persona() -> dict[str, Any]:
    results: list[dict[str, Any]] = []

    def check(cid: str, why: str, ok: bool) -> None:
        results.append({"id": cid, "why": why, "passed": bool(ok), "failures": [] if ok else [why]})

    prompts = {w.id: build_system_prompt(honorific="Sir", wit=w.id) for w in WIT_LEVELS}
    for w in WIT_LEVELS:
        p = prompts[w.id]
        missing = [h for h in HARD_LIMITS if h not in p]
        check(f"p-{w.id}-limits", f"{w.id}: every hard limit present", not missing)
        check(
            f"p-{w.id}-stable",
            f"{w.id}: stable string",
            p == build_system_prompt(honorific="Sir", wit=w.id),
        )
    check("p-distinct", "three distinct variants", len(set(prompts.values())) == 3)
    check("p-default", "default is film", build_system_prompt(honorific="Sir") == prompts["film"])
    for w in WIT_LEVELS:
        for training in (False, True):
            brain, prov = _brain(w.id, training=training)
            tag = f"{w.id}{'-training' if training else ''}"
            await brain.chat(ChatRequest(message="hi", user_id=UID))
            await brain.chat(ChatRequest(message="hi", user_id=UID, channel="voice"))
            async for _ in brain.chat_stream(
                ChatRequest(message="hi", user_id=UID, channel="voice")
            ):
                pass
            text, voice, stream = prov.calls[0], prov.calls[1], prov.calls[2]
            check(
                f"b-{tag}-wit",
                f"{tag}: the owner's variant is sent",
                all(c.system.startswith(prompts[w.id]) for c in (text, voice, stream)),
            )
            check(
                f"b-{tag}-text",
                f"{tag}: no voice rule on text",
                VOICE_RULE_HEADING not in text.system,
            )
            check(
                f"b-{tag}-voice",
                f"{tag}: voice rule on voice (chat + stream)",
                (VOICE_RULE_HEADING in voice.system and VOICE_RULE_HEADING in stream.system),
            )
            if training:
                check(
                    f"b-{tag}-tools",
                    f"{tag}: still no tools",
                    all(c.tools is None for c in prov.calls),
                )
    return _verdict(results)


# ---- billing ---------------------------------------------------------------------------------

M = 1_000_000
# (id, why, api, voice, used, month ₹, limit, units, expect, priced units)
BILL_CASES: list[tuple[str, str, str, str, float, float, int | str | None, int, str, float]] = [
    ("v01", "TTS within allowance, no limit", "tts", "chirp", 0, 0, None, 300, "made", 0),
    ("v02", "TTS within allowance, at the limit", "tts", "chirp", 5000, 600, 500, 300, "made", 0),
    (
        "v03",
        "TTS crossing the allowance: only the excess",
        "tts",
        "chirp",
        M - 100,
        0,
        None,
        300,
        "made",
        200,
    ),
    (
        "v04",
        "TTS above the allowance, under the limit",
        "tts",
        "chirp",
        M,
        10,
        500,
        400,
        "made",
        400,
    ),
    (
        "v05",
        "TTS above the allowance, at the limit",
        "tts",
        "chirp",
        M,
        500,
        500,
        400,
        "refused",
        0,
    ),
    (
        "v06",
        "TTS above the allowance, over the limit",
        "tts",
        "chirp",
        M,
        900,
        500,
        50,
        "refused",
        0,
    ),
    (
        "v07",
        "Studio above the allowance, at the limit",
        "tts",
        "studio",
        M,
        500,
        500,
        100,
        "refused",
        0,
    ),
    (
        "v08",
        "Studio crossing the allowance at US$160/1M",
        "tts",
        "studio",
        M - 50,
        0,
        None,
        150,
        "made",
        100,
    ),
    (
        "v09",
        "TTS crossing the allowance at the limit",
        "tts",
        "chirp",
        M - 10,
        600,
        500,
        300,
        "refused",
        0,
    ),
    ("v10", "per-type allowance: Studio still free", "tts", "studio", 0, 600, 500, 300, "made", 0),
    (
        "v11",
        "unreadable limit, priced → refused",
        "tts",
        "chirp",
        M,
        0,
        "corrupt",
        100,
        "refused",
        0,
    ),
    ("v12", "unreadable limit, free → made", "tts", "chirp", 0, 0, "corrupt", 100, "made", 0),
    ("v13", "STT within allowance at the limit", "stt", "", 100, 600, 500, 5, "made", 0),
    ("v14", "STT above allowance under the limit", "stt", "", 3600, 1, 500, 7, "made", 7),
    ("v15", "STT above allowance at the limit", "stt", "", 3600, 500, 500, 7, "refused", 0),
    ("v16", "STT crossing the allowance at the limit", "stt", "", 3598, 700, 500, 5, "refused", 0),
]
VOICE_IDS = {"chirp": "en-GB-Chirp3-HD-Algieba", "studio": "en-GB-Studio-B"}


async def _seed(
    docs: MemoryDocs, billing: Billing, key: str, used: float, inr: float, limit: Any
) -> None:
    month = billing.meter.month_of(billing.clock())

    async def fn(tx: DocTx) -> None:
        tx.set(f"jarvis_usage/{UID}_{month}", {"inr_total": inr, "units": {key: used}})
        if limit is not None:
            value = limit if isinstance(limit, int) else "lots"
            tx.set(f"jarvis_budget/{UID}", {"monthly_limit_inr": value})

    await docs.transaction(fn)


async def _bill_case(c: tuple[Any, ...]) -> dict[str, Any]:
    cid, why, api, voice, used, inr, limit, units, expect, priced = c
    s = settings()
    docs = MemoryDocs()
    billing = Billing(
        fx=FxRates(docs=None, http=None, default_rate=RATE),
        meter=UsageMeter(docs),
        budgets=BudgetStore(docs),
        brains=BrainRegistry.from_settings(s, MockProvider()),
    )
    prices = PriceList.from_settings(s)
    price = (
        prices.tts("studio" if voice == "studio" else "chirp3-hd") if api == "tts" else prices.stt
    )
    await _seed(docs, billing, price.key, used, inr, limit)
    tts, stt = ScriptedTTS(), ScriptedSTT()
    svc = VoiceService(
        store=VoiceSettingsStore(docs),
        billing=billing,
        prices=prices,
        engines=VoiceEngines(tts=tts, stt=stt, tokens=Tokens()),
        language="en-IN",
        honorific="Sir",
    )
    cost = 0.0
    try:
        if api == "tts":
            cost = (
                await svc.speak(UID, SpeakRequest(text="a" * units, voice=VOICE_IDS[voice]))
            ).cost_inr
        else:
            cost = (await svc.transcribe(UID, wav(float(units)))).cost_inr
        outcome = "made"
    except (BudgetReached, BudgetUnavailable):
        outcome = "refused"
    calls = len(tts.calls) + len(stt.calls)
    want_inr = round(priced * price.usd_per_unit * RATE, 4)
    fails = []
    if outcome != expect:
        fails.append(f"{outcome}, expected {expect}")
    if calls != (1 if expect == "made" else 0):
        fails.append(f"{calls} engine call(s)")
    if abs(round(cost, 4) - want_inr) > 1e-4:
        fails.append(f"₹{cost:.4f}, expected ₹{want_inr:.4f}")
    return {
        "id": cid,
        "why": why,
        "passed": not fails,
        "failures": fails,
        "priced_calls_past_limit": calls if expect == "refused" else 0,
        "cost_inr": round(cost, 4),
    }


async def _bill_all() -> list[dict[str, Any]]:
    return [await _bill_case(c) for c in BILL_CASES]


async def suite_billing() -> dict[str, Any]:
    results = await _bill_all()

    async def no_gate(self: Billing, uid: str, **kw: Any) -> None:
        return None

    with patched(Billing, "ensure_units_allowed", no_gate):
        control = await _bill_all()
    failed = sum(not r["passed"] for r in control)
    past = sum(r["priced_calls_past_limit"] for r in control)
    past_now = sum(r["priced_calls_past_limit"] for r in results)
    out = _verdict(results, priced_calls_past_limit=past_now)
    out["negative_control"] = {
        "suite_failed": failed > 0 and past > 0,
        "failed_cases": failed,
        "priced_calls_past_limit": past,
    }
    out["gate"] = out["gate"] and past_now == 0 and out["negative_control"]["suite_failed"]
    return out


# ---- provider error mapping ------------------------------------------------------------------


def _google_error(
    status: int, reason: str = "", grpc: str = ""
) -> Callable[[httpx.Request], httpx.Response]:
    body = {
        "error": {
            "code": status,
            "message": "VENDOR-TEXT must never reach the owner",
            "status": grpc,
            "details": [{"@type": "type.googleapis.com/google.rpc.ErrorInfo", "reason": reason}],
        }
    }
    return lambda r: httpx.Response(status, json=body)


def _raise(exc: Exception) -> Callable[[httpx.Request], httpx.Response]:
    def handler(r: httpx.Request) -> httpx.Response:
        raise exc

    return handler


_GARBAGE = lambda r: httpx.Response(200, text="<html>not json</html>")  # noqa: E731
# (id, why, api, handler, status, error, reason)
ERROR_CASES: list[
    tuple[str, str, str, Callable[[httpx.Request], httpx.Response], int, str, str | None]
] = [
    (
        "e01",
        "TTS API switched off",
        "tts",
        _google_error(403, "SERVICE_DISABLED", "PERMISSION_DENIED"),
        503,
        "voice_unavailable",
        "api_disabled",
    ),
    (
        "e02",
        "TTS permission denied",
        "tts",
        _google_error(403, "IAM_PERMISSION_DENIED", "PERMISSION_DENIED"),
        503,
        "voice_unavailable",
        "api_disabled",
    ),
    (
        "e03",
        "TTS token refused",
        "tts",
        _google_error(401, "", "UNAUTHENTICATED"),
        503,
        "voice_unavailable",
        "upstream_error",
    ),
    (
        "e04",
        "TTS throttled",
        "tts",
        _google_error(429, "RATE_LIMIT_EXCEEDED", "RESOURCE_EXHAUSTED"),
        429,
        "voice_busy",
        None,
    ),
    (
        "e05",
        "TTS invalid voice",
        "tts",
        _google_error(400, "", "INVALID_ARGUMENT"),
        422,
        "input_rejected",
        None,
    ),
    (
        "e06",
        "TTS internal error",
        "tts",
        _google_error(500, "", "INTERNAL"),
        503,
        "voice_unavailable",
        "upstream_error",
    ),
    (
        "e07",
        "TTS unavailable",
        "tts",
        _google_error(503, "", "UNAVAILABLE"),
        503,
        "voice_unavailable",
        "upstream_error",
    ),
    (
        "e08",
        "TTS timeout",
        "tts",
        _raise(httpx.ReadTimeout("slow")),
        503,
        "voice_unavailable",
        "timeout",
    ),
    (
        "e09",
        "TTS unreachable",
        "tts",
        _raise(httpx.ConnectError("down")),
        503,
        "voice_unavailable",
        "upstream_error",
    ),
    ("e10", "TTS garbage body", "tts", _GARBAGE, 503, "voice_unavailable", "upstream_error"),
    (
        "e11",
        "STT API switched off",
        "stt",
        _google_error(403, "SERVICE_DISABLED", "PERMISSION_DENIED"),
        503,
        "voice_unavailable",
        "api_disabled",
    ),
    (
        "e12",
        "STT throttled",
        "stt",
        _google_error(429, "", "RESOURCE_EXHAUSTED"),
        429,
        "voice_busy",
        None,
    ),
    (
        "e13",
        "STT bad request",
        "stt",
        _google_error(400, "", "INVALID_ARGUMENT"),
        422,
        "input_rejected",
        None,
    ),
    (
        "e14",
        "STT internal error",
        "stt",
        _google_error(500, "", "INTERNAL"),
        503,
        "voice_unavailable",
        "upstream_error",
    ),
    (
        "e15",
        "STT timeout",
        "stt",
        _raise(httpx.ConnectTimeout("slow")),
        503,
        "voice_unavailable",
        "timeout",
    ),
]
_PATHS = {"tts": "/v1/text:synthesize", "stt": "/v1/speech:recognize"}


def _engines(g: GoogleShaped, tokens: Tokens) -> VoiceEngines:
    http = g.client()
    return VoiceEngines(
        tts=GoogleTTS(http, tokens), stt=GoogleSTT(http, tokens), tokens=tokens, http=http
    )


async def _call(c: Any, api: str) -> httpx.Response:
    if api == "tts":
        return await c.post("/v1/voice/speak", json={"text": "Good evening."})
    return await c.post("/v1/voice/transcribe", content=wav(1.0), headers=WAV)


async def _error_case(case: tuple[Any, ...]) -> dict[str, Any]:
    cid, why, api, handler, status, error, reason = case
    g = GoogleShaped()
    g.routes[_PATHS[api]] = handler
    async with app_client(_engines(g, Tokens())) as c:
        r = await _call(c, api)
        sent = len(g.requests)
        again = await _call(c, api)
        body = r.json()
        fails = []
        if r.status_code != status or body.get("error") != error or body.get("reason") != reason:
            fails.append(f"{r.status_code} {body.get('error')} {body.get('reason')}")
        if "VENDOR-TEXT" in r.text or "html" in r.text:
            fails.append("vendor text reached the owner")
        remembered = len(g.requests) == sent  # api_disabled: Google is not asked again
        if (reason == "api_disabled") != remembered:
            fails.append(
                "api_disabled not remembered"
                if reason == "api_disabled"
                else "transient error remembered"
            )
        if again.status_code != status:
            fails.append(f"second call {again.status_code}")
    return {"id": cid, "why": why, "passed": not fails, "failures": fails}


async def _no_credentials() -> dict[str, Any]:
    g = GoogleShaped()
    async with app_client(_engines(g, Tokens(missing=True))) as c:
        view = (await c.get("/v1/voice")).json()
        r1, r2 = await _call(c, "tts"), await _call(c, "stt")
    ok = (
        all(r.status_code == 503 and r.json().get("reason") == "not_configured" for r in (r1, r2))
        and not g.requests
        and view["cloud"]
        == {"tts": "unavailable", "stt": "unavailable", "reason": "not_configured"}
    )
    return {
        "id": "e16",
        "why": "no credentials: not_configured, no request",
        "passed": ok,
        "failures": [] if ok else ["see view"],
    }


async def _cloud_off() -> dict[str, Any]:
    g = GoogleShaped()
    async with app_client(_engines(g, Tokens()), voice_cloud=False) as c:
        view = (await c.get("/v1/voice")).json()
        r = await _call(c, "tts")
    ok = view["cloud"]["tts"] == "off" and r.status_code == 503 and not g.requests
    return {
        "id": "e17",
        "why": "JARVIS_VOICE_CLOUD off: off, no request",
        "passed": ok,
        "failures": [] if ok else ["see view"],
    }


async def suite_errors() -> dict[str, Any]:
    results = [await _error_case(c) for c in ERROR_CASES]
    results += [await _no_credentials(), await _cloud_off()]
    return _verdict(results)


# ---- transcribe input validation -------------------------------------------------------------

# (id, why, body, content type, status, error)
WAV_CASES: list[tuple[str, str, bytes, str, int, str | None]] = [
    ("w01", "valid 16 kHz mono PCM16", wav(1.0), "audio/wav", 200, None),
    ("w02", "valid, audio/x-wav", wav(0.5), "audio/x-wav", 200, None),
    ("w03", "MP3 bytes", b"ID3\x04\x00" + b"\x00" * 500, "audio/wav", 422, "bad_audio"),
    ("w04", "Ogg bytes", b"OggS" + b"\x00" * 500, "audio/wav", 422, "bad_audio"),
    ("w05", "not audio at all", b"hello world", "audio/wav", 422, "bad_audio"),
    ("w06", "wrong content type", wav(1.0), "audio/mpeg", 422, "bad_audio"),
    ("w07", "stereo", wav(1.0, channels=2), "audio/wav", 422, "bad_audio"),
    ("w08", "44.1 kHz", wav(1.0, rate=44_100), "audio/wav", 422, "bad_audio"),
    ("w09", "48 kHz", wav(1.0, rate=48_000), "audio/wav", 422, "bad_audio"),
    ("w10", "8-bit", wav(1.0, bits=8), "audio/wav", 422, "bad_audio"),
    ("w11", "float PCM", wav(1.0, fmt=3), "audio/wav", 422, "bad_audio"),
    ("w12", "too short (0.1 s)", wav(0.1), "audio/wav", 422, "bad_audio"),
    ("w13", "too long (61 s, under the byte cap)", wav(61.0), "audio/wav", 422, "bad_audio"),
    ("w14", "oversize (> 2,000,000 bytes)", b"\x00" * 2_000_001, "audio/wav", 413, "too_large"),
    ("w15", "truncated", wav(1.0)[:-200], "audio/wav", 422, "bad_audio"),
    ("w16", "60 s exactly is fine", wav(60.0), "audio/wav", 200, None),
]


async def suite_wav() -> dict[str, Any]:
    results = []
    for cid, why, body, ctype, status, error in WAV_CASES:
        stt = ScriptedSTT()
        async with app_client(VoiceEngines(tts=ScriptedTTS(), stt=stt, tokens=Tokens())) as c:
            r = await c.post("/v1/voice/transcribe", content=body, headers={"Content-Type": ctype})
        fails = []
        if r.status_code != status or (error and r.json().get("error") != error):
            fails.append(f"{r.status_code} {r.text[:80]}")
        if len(stt.calls) != (1 if status == 200 else 0):
            fails.append(f"{len(stt.calls)} STT call(s)")
        results.append({"id": cid, "why": why, "passed": not fails, "failures": fails})
    return _verdict(results)


__all__ = [
    "suite_billing",
    "suite_errors",
    "suite_persona",
    "suite_speakable",
    "suite_wav",
]
