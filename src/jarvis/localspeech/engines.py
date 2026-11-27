# src/jarvis/localspeech/engines.py
"""The kit's engine slots (R5.2 V1; plan D2, D3, risk 1). Kit-safe: no model runtime is imported
here. Each slot is one model behind a small interface (`SttEngine` / `TtsEngine`); its runtime
module (`jarvis.localspeech.runtimes.<name>`) is imported only when the slot is first used, and
that module imports its package (faster-whisper, onnxruntime, ...) only inside its `load`.

`Slots` loads engines on demand so a 4 GB graphics card is enough: an engine goes on the card if
it fits beside the ones already there (the least recently used are put away first), else on the
CPU; a failure on the card is tried once more on the CPU. A slot is ready when its runtime is
installed and its pinned model files are (`manager.ModelManager`).

Call `stt`/`tts` while holding the kit's inference lock (`service.KitService` does): engines are
not shared between threads.
"""

from __future__ import annotations

import importlib
import importlib.util
import logging
import os
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Final, Protocol, runtime_checkable

from jarvis.calls.models import ENGLISH, SCHEDULED_LANGUAGES
from jarvis.localspeech.device import DeviceInfo
from jarvis.localspeech.protocol import (
    DEFAULT_ENGLISH_VOICE,
    SLOT_KIND,
    Device,
    EngineHealth,
    EngineSlot,
    Kind,
    KitRefused,
    default_slots,
)

log = logging.getLogger(__name__)

GPU_MARGIN_MB: Final = 512  # left free on the card for the system and the browser
NOT_INSTALLED: Final = "Not installed on this laptop yet (python -m jarvis.localspeech models)."
NO_RUNTIME: Final = "Its program is not installed in the kit (see the kit's README)."


# ---- what an engine gives back -------------------------------------------------------------------
@dataclass(frozen=True)
class Heard:
    text: str
    confidence: float
    alternatives: tuple[str, ...] = ()


@dataclass(frozen=True)
class Spoken:
    pcm: bytes  # PCM16 mono at `sample_rate`
    sample_rate: int
    voice: str
    first_audio_ms: int = 0


@runtime_checkable
class SttEngine(Protocol):
    def transcribe(self, pcm16k: bytes, lang: str, phrases: Sequence[str]) -> Heard: ...

    def close(self) -> None: ...


@runtime_checkable
class TtsEngine(Protocol):
    @property
    def voices(self) -> frozenset[str]: ...

    def synthesize(self, text: str, lang: str, voice: str, rate: float) -> Spoken: ...

    def close(self) -> None: ...


@dataclass(frozen=True)
class LoadArgs:
    model_dir: Path
    device: Device
    threads: int
    default_voice: str = ""


Engine = SttEngine | TtsEngine
Loader = Callable[[LoadArgs], Engine]


# ---- the slots ---------------------------------------------------------------------------------
@dataclass(frozen=True)
class EngineSpec:
    slot: EngineSlot
    languages: tuple[str, ...]
    model: str  # a short label, e.g. "small-int8"
    licence: str  # the model's licence (protocol.PERMISSIVE_LICENCES)
    vram_mb: int  # about how much of the graphics card it takes
    runtime: tuple[str, ...]  # the packages it needs (top-level import names)
    loader: str  # "module:function", imported on first use
    default_voice: str = ""

    @property
    def kind(self) -> Kind:
        return SLOT_KIND[self.slot]


_R = "jarvis.localspeech.runtimes"
SPECS: Final[tuple[EngineSpec, ...]] = (
    EngineSpec(
        EngineSlot.WHISPER_SMALL,
        (ENGLISH,),
        "small-int8",
        "MIT",
        vram_mb=1_000,
        runtime=("faster_whisper", "ctranslate2"),
        loader=f"{_R}.whisper:load",
    ),
    EngineSpec(
        EngineSlot.WHISPER_MEDIUM,
        (ENGLISH,),
        "medium-int8",
        "MIT",
        vram_mb=2_000,
        runtime=("faster_whisper", "ctranslate2"),
        loader=f"{_R}.whisper:load",
    ),
    EngineSpec(
        EngineSlot.KOKORO,
        (ENGLISH,),
        "kokoro-82m-v1.0",
        "Apache-2.0",
        vram_mb=600,
        runtime=("kokoro_onnx", "onnxruntime"),
        loader=f"{_R}.kokoro:load",
        default_voice=DEFAULT_ENGLISH_VOICE,
    ),
    EngineSpec(
        EngineSlot.PIPER,
        (ENGLISH,),
        "piper-en-gb",
        "MIT",
        vram_mb=200,
        runtime=("piper", "onnxruntime"),
        loader=f"{_R}.piper:load",
    ),
    EngineSpec(
        EngineSlot.INDIC_CONFORMER,
        SCHEDULED_LANGUAGES,
        "indic-conformer-600m-int8",
        "MIT",
        vram_mb=1_500,
        runtime=("onnxruntime", "torch", "torchaudio", "transformers"),
        loader=f"{_R}.indic_conformer:load",
    ),
    EngineSpec(
        EngineSlot.INDIC_PARLER,
        SCHEDULED_LANGUAGES,
        "indic-parler-tts",
        "Apache-2.0",
        vram_mb=2_500,
        runtime=("parler_tts", "torch", "transformers"),
        loader=f"{_R}.indic_parler:load",
    ),
)


def _has_module(name: str) -> bool:
    try:
        return importlib.util.find_spec(name) is not None
    except (ImportError, ValueError):
        return False


def _import_loader(path: str) -> Loader:
    module_name, _, function = path.partition(":")
    loader: Loader = getattr(importlib.import_module(module_name), function)
    return loader


@dataclass
class _Loaded:
    engine: Engine
    device: Device
    used_at: float = field(default_factory=time.monotonic)


class Slots:
    """Every slot's state; loads and puts away engines on demand."""

    def __init__(
        self,
        specs: Sequence[EngineSpec] = SPECS,
        *,
        installed: Callable[[EngineSlot], Path | None],
        device: DeviceInfo,
        has_module: Callable[[str], bool] = _has_module,
        import_loader: Callable[[str], Loader] = _import_loader,
        threads: int | None = None,
    ) -> None:
        self._specs: dict[EngineSlot, EngineSpec] = {s.slot: s for s in specs}
        self._installed = installed
        self._device = device
        self._has_module = has_module
        self._import_loader = import_loader
        self._threads = threads or max(1, (os.cpu_count() or 2) // 2)
        self._loaded: dict[EngineSlot, _Loaded] = {}
        self._failed: dict[EngineSlot, str] = {}
        free = device.gpu_free_mb or 0
        self._gpu_budget = max(0, free - GPU_MARGIN_MB) if device.device is Device.CUDA else 0

    # ---- state ----------------------------------------------------------------------------
    @property
    def device(self) -> Device:
        return self._device.device

    def spec(self, slot: EngineSlot) -> EngineSpec | None:
        return self._specs.get(slot)

    def why_not_ready(self, slot: EngineSlot) -> str | None:
        """None when `slot` can serve; else plain words why not."""
        spec = self._specs.get(slot)
        if spec is None:
            return "This kit has no such engine."
        if slot in self._failed:
            return self._failed[slot]
        if not all(self._has_module(m) for m in spec.runtime):
            return NO_RUNTIME
        if self._installed(slot) is None:
            return NOT_INSTALLED
        return None

    def health(self) -> tuple[EngineHealth, ...]:
        rows = []
        for spec in self._specs.values():
            reason = self.why_not_ready(spec.slot)
            loaded = self._loaded.get(spec.slot)
            rows.append(
                EngineHealth(
                    slot=spec.slot,
                    kind=spec.kind,
                    languages=spec.languages,
                    model=spec.model,
                    licence=spec.licence,
                    ready=reason is None,
                    loaded=loaded is not None,
                    device=loaded.device if loaded else self._planned_device(spec),
                    reason=reason or "",
                )
            )
        return tuple(rows)

    def _planned_device(self, spec: EngineSpec) -> Device:
        return Device.CUDA if spec.vram_mb <= self._gpu_budget else Device.CPU

    def pick(self, kind: Kind, lang: str, asked: EngineSlot | None) -> EngineSlot:
        """The slot to use for `kind` in `lang`: the one asked for, or the first ready default.
        KitRefused: `unsupported_language` (no slot serves it), `engine_not_ready`."""
        if asked is not None:
            spec = self._specs.get(asked)
            if spec is None or spec.kind is not kind or lang not in spec.languages:
                raise KitRefused(
                    "unsupported_language", "That engine does not serve that language."
                )
            reason = self.why_not_ready(asked)
            if reason is not None:
                raise KitRefused("engine_not_ready", reason)
            return asked
        serving = [s for s in default_slots(kind, lang) if s in self._specs]
        serving = [s for s in serving if lang in self._specs[s].languages]
        if not serving:
            raise KitRefused("unsupported_language", "That language has no engine on the laptop.")
        for slot in serving:
            if self.why_not_ready(slot) is None:
                return slot
        reason = self.why_not_ready(serving[0]) or NOT_INSTALLED
        raise KitRefused("engine_not_ready", reason)

    def reset_failures(self) -> None:
        self._failed.clear()

    # ---- engines --------------------------------------------------------------------------
    def stt(self, slot: EngineSlot) -> SttEngine:
        engine = self._engine(slot)
        if not isinstance(engine, SttEngine):
            raise KitRefused("internal", "That engine is not a listening engine.")
        return engine

    def tts(self, slot: EngineSlot) -> TtsEngine:
        engine = self._engine(slot)
        if not isinstance(engine, TtsEngine):
            raise KitRefused("internal", "That engine is not a speaking engine.")
        return engine

    def _engine(self, slot: EngineSlot) -> Engine:
        found = self._loaded.get(slot)
        if found is not None:
            found.used_at = time.monotonic()
            return found.engine
        reason = self.why_not_ready(slot)
        if reason is not None:
            raise KitRefused("engine_not_ready", reason)
        return self._load(self._specs[slot])

    def _load(self, spec: EngineSpec) -> Engine:
        model_dir = self._installed(spec.slot)
        assert model_dir is not None  # why_not_ready checked it
        loader = self._import_loader(spec.loader)
        devices = [Device.CPU]
        if self._device.device is Device.CUDA and self._make_room(spec.vram_mb):
            devices.insert(0, Device.CUDA)
        for device in devices:
            args = LoadArgs(model_dir, device, self._threads, spec.default_voice)
            started = time.monotonic()
            try:
                engine = loader(args)
            except Exception as exc:  # noqa: BLE001 - a model that won't load is reported
                log.warning(
                    "engine %s did not load on %s: %s", spec.slot, device, type(exc).__name__
                )
                continue
            log.info(
                "engine %s loaded on %s in %.1f s", spec.slot, device, time.monotonic() - started
            )
            self._loaded[spec.slot] = _Loaded(engine, device)
            return engine
        self._failed[spec.slot] = "It would not load on this laptop (run the kit's self-test)."
        raise KitRefused("engine_not_ready", self._failed[spec.slot])

    def _gpu_used(self) -> int:
        return sum(
            self._specs[s].vram_mb for s, e in self._loaded.items() if e.device is Device.CUDA
        )

    def _make_room(self, need_mb: int) -> bool:
        """Put away the least recently used engines on the card until `need_mb` fits."""
        if need_mb > self._gpu_budget:
            return False
        while self._gpu_used() + need_mb > self._gpu_budget:
            on_gpu = [(e.used_at, s) for s, e in self._loaded.items() if e.device is Device.CUDA]
            if not on_gpu:
                return False
            self.unload(min(on_gpu)[1])
        return True

    def unload(self, slot: EngineSlot) -> None:
        found = self._loaded.pop(slot, None)
        if found is None:
            return
        try:
            found.engine.close()
        except Exception as exc:  # noqa: BLE001 - putting an engine away never fails the kit
            log.warning("engine %s did not close cleanly: %s", slot, type(exc).__name__)

    def unload_all(self) -> None:
        for slot in list(self._loaded):
            self.unload(slot)

    def loaded(self) -> Mapping[EngineSlot, Device]:
        return {s: e.device for s, e in self._loaded.items()}


__all__ = [
    "NOT_INSTALLED",
    "NO_RUNTIME",
    "SPECS",
    "EngineSpec",
    "Heard",
    "LoadArgs",
    "Loader",
    "Slots",
    "Spoken",
    "SttEngine",
    "TtsEngine",
]
