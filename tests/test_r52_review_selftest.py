# tests/test_r52_review_selftest.py -- R5.2 combined review (BOOK-LIST 4.2): the kit's self-test
# measured listening only inside the voice round trip, so kit 1.0.0 (Whisper, no voice) never
# measured the plan's "listening faster than real time x3" (plan 5, "Laptop kit"). With a
# listening engine and no voice it now times listening alone on a few seconds of a test tone; the
# word error still needs a voice, and the report says so.
from __future__ import annotations

from pathlib import Path

import pytest
from kit_fakes import make_service

from jarvis.localspeech import selftest as st
from jarvis.localspeech.protocol import EngineSlot, SttRequest, SttResult

EARS = frozenset({EngineSlot.WHISPER_SMALL})


async def test_review_without_a_voice_listening_alone_is_timed(tmp_path: Path) -> None:
    pytest.importorskip("numpy")  # the synthetic tone
    service, _ = make_service(tmp_path, ready=EARS)
    checks = {c.name: c for c in await st.check_round_trip(service)}
    assert checks["listening"].ok is True, checks["listening"]
    assert "real time (bar 3x)" in checks["listening"].words
    assert "whisper-small" in checks["listening"].words
    assert checks["round trip"].ok is None and "voice" in checks["round trip"].words
    await service.close()


async def test_review_a_slow_listener_fails_the_bar_without_a_voice(tmp_path: Path) -> None:
    pytest.importorskip("numpy")
    service, _ = make_service(tmp_path, ready=EARS)
    real = service.stt

    async def slow(req: SttRequest) -> SttResult:
        heard = await real(req)
        return heard.model_copy(update={"elapsed_ms": int(heard.seconds * 1000)})  # 1x

    service.stt = slow  # type: ignore[method-assign]
    checks = {c.name: c for c in await st.check_round_trip(service)}
    assert checks["listening"].ok is False and "1.0x real time" in checks["listening"].words
    await service.close()


async def test_review_with_no_english_engine_nothing_is_timed(tmp_path: Path) -> None:
    service, _ = make_service(tmp_path, ready=frozenset())
    checks = await st.check_round_trip(service)
    assert [c.name for c in checks] == ["kit", "round trip"]
    await service.close()
