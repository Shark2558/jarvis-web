# tests/test_voice_storage.py — slice 9 storage on both Docs backends: the voice settings document
# and the allowance counters (map keys such as "tts_chirp3-hd") round-trip on the in-process twin
# and, in CI's emulator job, on Firestore.
from __future__ import annotations

import os
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime

import pytest

from jarvis.billing.meter import UsageMeter
from jarvis.storage.docs import Docs, MemoryDocs
from jarvis.voice.settings import VoiceSettingsPatch, VoiceSettingsStore

EMULATOR = os.environ.get("FIRESTORE_EMULATOR_HOST")
BACKENDS = ["memory", pytest.param("emulator", marks=pytest.mark.firestore_emulator)]
NOW = datetime(2026, 11, 15, 6, 0, tzinfo=UTC)


@pytest.fixture(params=BACKENDS)
async def docs(request: pytest.FixtureRequest) -> AsyncIterator[Docs]:
    if request.param == "memory":
        d: Docs = MemoryDocs()
    else:
        if not EMULATOR:
            if os.environ.get("JARVIS_REQUIRE_EMULATOR"):
                pytest.fail("JARVIS_REQUIRE_EMULATOR is set but FIRESTORE_EMULATOR_HOST is not")
            pytest.skip("FIRESTORE_EMULATOR_HOST not set")
        from jarvis.storage.firestore_docs import FirestoreDocs

        d = FirestoreDocs(project="demo-jarvis-test", database="(default)")
    yield d
    await d.close()


@pytest.fixture
def prefix() -> str:
    return f"t{uuid.uuid4().hex[:10]}_"


async def test_voice_settings_round_trip(docs: Docs, prefix: str) -> None:
    store = VoiceSettingsStore(docs, prefix=prefix)
    saved = await store.update(
        "u_owner", VoiceSettingsPatch(voice="en-GB-Studio-B", rate=0.9, wit="extra")
    )
    assert await VoiceSettingsStore(docs, prefix=prefix).get("u_owner") == saved


async def test_allowance_counters_round_trip(docs: Docs, prefix: str) -> None:
    meter = UsageMeter(docs, prefix=prefix)
    for key, units in (("tts_chirp3-hd", 120), ("tts_studio", 30), ("stt_seconds", 2.5)):
        await meter.add_units(
            "u_owner",
            key=key,
            units=units,
            free_units=100,
            usd_per_unit=0.001,
            inr_per_usd=95.24,
            label="voice",
            now=NOW,
        )
    await meter.add("u_owner", brain_id="anthropic", cost_usd=0.01, cost_inr=0.95, now=NOW)
    a = await meter.allowance(meter.allowance_month_of(NOW))
    assert a.units == {"tts_chirp3-hd": 120, "tts_studio": 30, "stt_seconds": 2.5}
    m = await meter.get("u_owner", "2026-11")
    assert m.by_brain_inr["voice"] == pytest.approx(20 * 0.001 * 95.24)
    assert m.calls == 2  # one priced voice call + one chat
