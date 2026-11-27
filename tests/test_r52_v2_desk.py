# tests/test_r52_v2_desk.py -- R5.2 V2: the call desk's laptop speech (I0 seams "R18 reuse"):
# R18's `jarvis.calldesk.speech_local.LocalSpeech` over the speech kit on the same laptop
# (`LOOPBACK_BASE`). `status()` is synchronous (the desk's `hello` and `prepare` read it), so the
# kit's health is cached for `health_s` and refreshed in the background; it offers only languages
# the kit both hears and speaks, and nothing while the kit is slow, old or away. Every kit failure
# is R18's `LocalSpeechUnavailable` in plain words, so the desk falls back to cloud speech.
#
# R18's call desk is not joined into r5-2-i0 yet: until it is, these tests stand R18's shapes from
# the seams doc in for `jarvis.calldesk.speech_local`; after the I1 join they run against R18's.
from __future__ import annotations

import ast
import asyncio
import hashlib
import importlib
import sys
import types
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

import pytest

from jarvis.calls.models import ENGLISH
from jarvis.localspeech import protocol as p
from jarvis.localspeech.memory import INDIAN_TEST_LANGUAGES, MemoryKit, default_health

SRC = Path(__file__).resolve().parents[1] / "src"
HINDI = INDIAN_TEST_LANGUAGES[0]
ONE_SECOND = b"\x01\x00" * p.SAMPLE_RATE
_FAKES = ("jarvis.calldesk", "jarvis.calldesk.speech_local")


def _r18_shapes() -> types.ModuleType:
    """R18's `speech_local` as the seams doc names it (status, transcribe, speak, the error)."""
    mod = types.ModuleType("jarvis.calldesk.speech_local")

    class LocalSpeechUnavailable(Exception):
        pass

    @dataclass(frozen=True)
    class LocalStatus:
        installed: bool
        languages: tuple[str, ...]
        reason: str = ""

    @dataclass(frozen=True)
    class LocalHeard:
        lang: str
        text: str
        confidence: float

    class LocalSpeech(Protocol):
        def status(self) -> Any: ...

        async def transcribe(self, pcm16k: bytes, languages: Sequence[str]) -> Any: ...

        async def speak(self, text: str, lang: str) -> bytes: ...

    for cls in (LocalSpeechUnavailable, LocalStatus, LocalHeard, LocalSpeech):
        cls.__module__ = mod.__name__
        setattr(mod, cls.__name__, cls)
    return mod


@pytest.fixture(scope="module")
def r18() -> Iterator[types.ModuleType]:
    stood_in = False
    try:
        real = importlib.import_module("jarvis.calldesk.speech_local")
    except ModuleNotFoundError:
        stood_in = True
        sys.modules["jarvis.calldesk"] = types.ModuleType("jarvis.calldesk")
        real = sys.modules["jarvis.calldesk.speech_local"] = _r18_shapes()
    sys.modules.pop("jarvis.localspeech.desk", None)
    yield real
    sys.modules.pop("jarvis.localspeech.desk", None)
    if stood_in:
        for name in _FAKES:
            sys.modules.pop(name, None)


@pytest.fixture
def desk(r18: types.ModuleType) -> types.ModuleType:
    return importlib.import_module("jarvis.localspeech.desk")


class Clock:
    def __init__(self) -> None:
        self.now = 1_000.0

    def __call__(self) -> float:
        return self.now


def local(desk: types.ModuleType, kit: MemoryKit, clock: Clock | None = None) -> Any:
    return desk.KitLocalSpeech(kit, health_s=30, clock=clock or Clock())


# ---- status: what the desk offers in its hello ---------------------------------------------------
async def test_before_any_check_nothing_is_offered(desk: types.ModuleType) -> None:
    speech = local(desk, MemoryKit())
    first = speech.status()  # no loop work yet: the background check is only started
    assert first.installed is False and first.languages == () and first.reason
    await asyncio.sleep(0)  # the check the first status() started
    await asyncio.sleep(0)
    assert speech.status().installed is True


async def test_it_offers_the_languages_the_kit_both_hears_and_speaks(
    desk: types.ModuleType,
) -> None:
    health = default_health()
    no_hindi_voice = tuple(
        e.model_copy(update={"languages": (INDIAN_TEST_LANGUAGES[1],)})
        if e.slot is p.EngineSlot.INDIC_PARLER
        else e
        for e in health.engines
    )
    kit = MemoryKit(health=health.model_copy(update={"engines": no_hindi_voice}))
    status = await local(desk, kit).refresh()
    assert status.installed is True
    assert status.languages == tuple(sorted((ENGLISH, INDIAN_TEST_LANGUAGES[1])))


@pytest.mark.parametrize("why", ["slow", "old", "offline", "unauthorized"])
async def test_a_slow_old_or_absent_kit_offers_nothing(desk: types.ModuleType, why: str) -> None:
    kit = MemoryKit()
    if why == "slow":
        kit.slow = True
    elif why == "old":
        kit.base_health = kit.base_health.model_copy(update={"protocol": p.PROTOCOL + 1})
    else:
        kit.down = why
    status = await local(desk, kit).refresh()
    assert status.installed is False and status.languages == ()
    assert status.reason and "Bearer" not in status.reason


async def test_the_health_is_cached_then_refreshed_in_the_background(
    desk: types.ModuleType,
) -> None:
    kit, clock = MemoryKit(), Clock()
    speech = local(desk, kit, clock)
    await speech.refresh()
    for _ in range(5):
        assert speech.status().installed
    await asyncio.sleep(0)
    assert kit.calls == ["health"]  # fresh for 30 s: no new check
    clock.now += 31
    kit.down = "offline"
    assert speech.status().installed  # the cached answer, while the check runs
    await asyncio.sleep(0)
    await asyncio.sleep(0)
    assert kit.calls == ["health", "health"]
    assert speech.status().installed is False


def test_status_outside_an_event_loop_never_fails(desk: types.ModuleType) -> None:
    speech = local(desk, MemoryKit())
    assert speech.status().installed is False  # no loop: nothing started, nothing raised


# ---- hearing and speaking ------------------------------------------------------------------------
async def test_it_hears_in_the_first_language_the_kit_has(desk: types.ModuleType) -> None:
    said = {hashlib.sha256(ONE_SECOND).hexdigest(): "namaste"}
    speech = local(desk, MemoryKit(heard=said))
    await speech.refresh()
    heard = await speech.transcribe(ONE_SECOND, ["as-IN", HINDI, ENGLISH])
    assert (heard.lang, heard.text, heard.confidence) == (HINDI, "namaste", 0.9)


async def test_too_little_audio_is_heard_as_nothing(desk: types.ModuleType) -> None:
    kit = MemoryKit()
    speech = local(desk, kit)
    heard = await speech.transcribe(b"\x01\x00" * 100 + b"\x01", [ENGLISH])
    assert heard.text == "" and "stt" not in kit.calls


async def test_it_speaks_pcm_and_reads_long_text_in_parts(desk: types.ModuleType) -> None:
    kit = MemoryKit()
    speech = local(desk, kit)
    short = await speech.speak("Namaskar.", HINDI)
    assert len(short) % 2 == 0 and short
    words = " ".join(["word"] * 300)  # 1,499 characters: three requests of at most 600
    long = await speech.speak(words, ENGLISH)
    assert kit.calls.count("tts") == 4 and len(long) > len(short)
    assert await speech.speak("   ", ENGLISH) == b""


@pytest.mark.parametrize("reason", ["offline", "timeout", "busy"])
async def test_a_kit_failure_is_r18s_error_and_stops_the_offer(
    desk: types.ModuleType, r18: types.ModuleType, reason: p.UnavailableReason
) -> None:
    kit = MemoryKit()
    speech = local(desk, kit)
    await speech.refresh()
    kit.down = reason
    with pytest.raises(r18.LocalSpeechUnavailable) as heard:
        await speech.transcribe(ONE_SECOND, [ENGLISH])
    with pytest.raises(r18.LocalSpeechUnavailable):
        await speech.speak("Hello.", ENGLISH)
    assert str(heard.value) == str(p.KitUnavailable(reason))  # fixed words, nothing quoted
    assert speech.status().installed is False  # the next prepare uses cloud speech


async def test_a_language_without_an_engine_is_r18s_error(
    desk: types.ModuleType, r18: types.ModuleType
) -> None:
    speech = local(desk, MemoryKit())
    await speech.refresh()
    with pytest.raises(r18.LocalSpeechUnavailable):
        await speech.transcribe(ONE_SECOND, ["as-IN"])
    with pytest.raises(r18.LocalSpeechUnavailable):
        await speech.speak("x", "as-IN")
    with pytest.raises(r18.LocalSpeechUnavailable):
        await speech.speak("x", "xx-YY")


def test_the_desk_speech_factory_uses_the_loopback_gate(desk: types.ModuleType) -> None:
    from pydantic import SecretStr

    speech = desk.desk_speech(SecretStr("k" * 40))
    assert "loopback" in repr(speech.kit)


# ---- the desk can ship these files ---------------------------------------------------------------
KIT_SAFE_JARVIS = {
    "jarvis.localspeech.desk",
    "jarvis.localspeech.client",
    "jarvis.localspeech.protocol",
    "jarvis.offline.config",
    "jarvis.calls.models",
    "jarvis.calls.protocol",
    "jarvis.calldesk.speech_local",
}
KIT_SAFE_OUTSIDE = {"httpx", "pydantic"}


def _imports(path: Path) -> set[str]:
    found: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            found.update(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            found.add(node.module)
    return found


def test_the_desk_hook_and_client_import_only_what_the_call_desk_kit_ships() -> None:
    todo, seen = ["jarvis.localspeech.desk"], set()
    while todo:
        name = todo.pop()
        if name in seen or name == "jarvis.calldesk.speech_local":
            continue
        seen.add(name)
        for imported in _imports(SRC / (name.replace(".", "/") + ".py")):
            top = imported.split(".")[0]
            if top == "jarvis":
                assert imported in KIT_SAFE_JARVIS, f"{name} imports {imported}"
                todo.append(imported)
            else:
                assert top in sys.stdlib_module_names or top in KIT_SAFE_OUTSIDE, (name, top)
    assert {"jarvis.localspeech.client", "jarvis.offline.config"} <= seen
