# tests/test_r52_v1_engines.py -- R5.2 V1 (plan D2, D3, risk 1): the engine slots. Loaded on
# first use only; on the graphics card while they fit beside the others (the least recently used
# put away first), else on the CPU; a failure on the card retried once on the CPU; ready only with
# the runtime installed and the pinned files in place; the defaults' order from the protocol.
from __future__ import annotations

from pathlib import Path

import pytest
from kit_fakes import ALL, ENGLISH_ONLY, Engines, make_slots

from jarvis.localspeech import protocol as p
from jarvis.localspeech.device import DeviceInfo
from jarvis.localspeech.engines import GPU_MARGIN_MB, NO_RUNTIME, NOT_INSTALLED, SPECS

S = p.EngineSlot
CARD_FREE_MB = 3_500
CARD_4GB = DeviceInfo(p.Device.CUDA, gpu_free_mb=CARD_FREE_MB, gpu_total_mb=4_096)


def test_every_slot_has_one_spec_with_a_permissive_licence() -> None:
    assert [s.slot for s in SPECS] == list(S)
    for spec in SPECS:
        assert spec.licence in p.PERMISSIVE_LICENCES and spec.kind is p.SLOT_KIND[spec.slot]
        assert spec.loader.startswith("jarvis.localspeech.runtimes.")
    assert {s.slot: s.default_voice for s in SPECS}[S.KOKORO] == p.DEFAULT_ENGLISH_VOICE


def test_nothing_is_loaded_until_it_is_used(tmp_path: Path) -> None:
    slots, engines = make_slots(tmp_path)
    assert all(not e.loaded for e in slots.health()) and engines.loads == []
    slots.stt(S.WHISPER_SMALL)
    slots.stt(S.WHISPER_SMALL)
    assert engines.loads == [(S.WHISPER_SMALL, p.Device.CPU)]


def test_engines_share_the_card_and_the_oldest_is_put_away(tmp_path: Path) -> None:
    slots, engines = make_slots(tmp_path, device=CARD_4GB)
    budget = CARD_FREE_MB - GPU_MARGIN_MB  # 3,000 MB
    slots.stt(S.WHISPER_SMALL)  # 1,000
    slots.tts(S.KOKORO)  # 600
    slots.stt(S.INDIC_CONFORMER)  # 1,500: 3,100 > budget, so whisper-small goes
    assert slots.loaded() == {S.KOKORO: p.Device.CUDA, S.INDIC_CONFORMER: p.Device.CUDA}
    assert engines.made[S.WHISPER_SMALL].closed
    assert sum(next(s.vram_mb for s in SPECS if s.slot == k) for k in slots.loaded()) <= budget


def test_an_engine_too_big_for_the_card_runs_on_the_cpu(tmp_path: Path) -> None:
    small_card = DeviceInfo(p.Device.CUDA, gpu_free_mb=1_200)
    slots, engines = make_slots(tmp_path, device=small_card)
    slots.tts(S.INDIC_PARLER)
    assert engines.loads == [(S.INDIC_PARLER, p.Device.CPU)]
    rows = {e.slot: e for e in slots.health()}
    assert rows[S.INDIC_PARLER].device is p.Device.CPU and rows[S.INDIC_PARLER].loaded


def test_a_failure_on_the_card_is_tried_once_on_the_cpu(tmp_path: Path) -> None:
    slots, engines = make_slots(tmp_path, device=CARD_4GB, engines=Engines(fail_on={p.Device.CUDA}))
    slots.stt(S.WHISPER_SMALL)
    assert engines.loads == [(S.WHISPER_SMALL, p.Device.CUDA), (S.WHISPER_SMALL, p.Device.CPU)]
    assert slots.loaded() == {S.WHISPER_SMALL: p.Device.CPU}


def test_an_engine_that_never_loads_is_reported_until_reset(tmp_path: Path) -> None:
    engines = Engines(fail_on={p.Device.CPU})
    slots, _ = make_slots(tmp_path, engines=engines)
    with pytest.raises(p.KitRefused) as refused:
        slots.stt(S.WHISPER_SMALL)
    assert refused.value.code == "engine_not_ready"
    row = {e.slot: e for e in slots.health()}[S.WHISPER_SMALL]
    assert not row.ready and "self-test" in row.reason
    engines.fail_on.clear()
    slots.reset_failures()
    slots.stt(S.WHISPER_SMALL)


def test_ready_needs_the_runtime_and_the_pinned_files(tmp_path: Path) -> None:
    slots, _ = make_slots(tmp_path, ready=ENGLISH_ONLY)
    assert slots.why_not_ready(S.WHISPER_SMALL) is None
    assert slots.why_not_ready(S.INDIC_CONFORMER) == NOT_INSTALLED
    bare, _ = make_slots(tmp_path / "b", ready=ALL, runtime=False)
    assert bare.why_not_ready(S.KOKORO) == NO_RUNTIME
    assert all(not e.ready for e in bare.health())


def test_pick_follows_the_protocols_defaults(tmp_path: Path) -> None:
    slots, _ = make_slots(tmp_path, ready=ALL - {S.KOKORO})
    assert slots.pick(p.Kind.TTS, "en-IN", None) is S.PIPER  # Kokoro first, Piper next
    assert slots.pick(p.Kind.STT, "en-IN", None) is S.WHISPER_SMALL
    assert slots.pick(p.Kind.TTS, "ta-IN", None) is S.INDIC_PARLER
    with pytest.raises(p.KitRefused) as wrong:
        slots.pick(p.Kind.STT, "en-IN", S.INDIC_CONFORMER)
    assert wrong.value.code == "unsupported_language"


def test_putting_everything_away_closes_every_engine(tmp_path: Path) -> None:
    slots, engines = make_slots(tmp_path)
    slots.stt(S.WHISPER_SMALL)
    slots.tts(S.KOKORO)
    slots.unload_all()
    assert slots.loaded() == {} and all(e.closed for e in engines.made.values())
