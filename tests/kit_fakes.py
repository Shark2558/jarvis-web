# tests/kit_fakes.py -- R5.2 V1: fakes for the laptop speech kit's own tests (engines, the MP3
# encoder, a wake-word trainer) and one builder for a `KitService` over a temporary folder.
# Synthetic audio only (silence and tones); nothing here is a real model.
from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path

from jarvis.localspeech.clips import ClipVault
from jarvis.localspeech.device import DeviceInfo
from jarvis.localspeech.engines import Heard, LoadArgs, Loader, Slots, Spoken
from jarvis.localspeech.jobs import JobRunner
from jarvis.localspeech.ports import KINDS, Progress, WakeClip, WakeJob
from jarvis.localspeech.protocol import (
    OWNER_LICENCE,
    SAMPLE_RATE,
    SLOT_KIND,
    ArtifactInfo,
    Device,
    EngineSlot,
    JobKind,
    Kind,
    KitRefused,
    WakeArtifact,
    WakeModel,
    WakeModelIn,
    WakeStatus,
    WakeTrainIn,
    encode_pcm,
)
from jarvis.localspeech.service import KitService

KEY = "k" * 40  # a test key (>= 32 characters), never a real one
ALL = frozenset(EngineSlot)
ENGLISH_ONLY = frozenset(
    {EngineSlot.WHISPER_SMALL, EngineSlot.WHISPER_MEDIUM, EngineSlot.KOKORO, EngineSlot.PIPER}
)


def pcm(seconds: float = 1.0, level: int = 0) -> bytes:
    """PCM16 16 kHz mono: silence, or a square-ish pattern at `level` (distinct clips)."""
    sample = int(level).to_bytes(2, "little", signed=True)
    return sample * int(seconds * SAMPLE_RATE)


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class FakeStt:
    def __init__(self, heard: Mapping[str, str], log: list[str], *, broken: bool = False) -> None:
        self.heard = heard
        self.log = log
        self.broken = broken
        self.closed = False

    def transcribe(self, pcm16k: bytes, lang: str, phrases: Sequence[str]) -> Heard:
        self.log.append("transcribe")
        if self.broken:
            raise RuntimeError("cuda out of memory: secret words")
        return Heard(self.heard.get(sha(pcm16k), "hello jarvis"), 0.9, ("hello travis",))

    def close(self) -> None:
        self.closed = True


class FakeTts:
    def __init__(self, log: list[str], *, rate: int = SAMPLE_RATE, broken: bool = False) -> None:
        self.log = log
        self.rate = rate
        self.broken = broken
        self.closed = False

    @property
    def voices(self) -> frozenset[str]:
        return frozenset({"bm_george", "bm_lewis"})

    def synthesize(self, text: str, lang: str, voice: str, rate: float) -> Spoken:
        self.log.append("synthesize")
        if self.broken:
            raise RuntimeError("engine fell over")
        return Spoken(b"\x01\x00" * int(len(text) * 0.05 * self.rate), self.rate, voice, 120)

    def close(self) -> None:
        self.closed = True


class FakeMp3:
    def __init__(self) -> None:
        self.rates: list[int] = []

    def encode(self, pcm: bytes, sample_rate: int) -> bytes:
        self.rates.append(sample_rate)
        return b"ID3\x04" + bytes(16)


class Engines:
    """Loaders for every slot, recording what was loaded where (never what was said)."""

    def __init__(self, *, tts_rate: int = SAMPLE_RATE, fail_on: set[Device] | None = None) -> None:
        self.heard: dict[str, str] = {}
        self.log: list[str] = []
        self.loads: list[tuple[EngineSlot, Device]] = []
        self.made: dict[EngineSlot, FakeStt | FakeTts] = {}
        self.tts_rate = tts_rate
        self.fail_on = fail_on or set()

    def import_loader(self, path: str) -> Loader:
        assert path.startswith("jarvis.localspeech.runtimes.")  # a real runtime's name
        return self.load

    def load(self, args: LoadArgs) -> FakeStt | FakeTts:
        slot = slot_of(args)
        self.loads.append((slot, args.device))
        if args.device in self.fail_on:
            raise RuntimeError("no room on the card")
        made: FakeStt | FakeTts
        if SLOT_KIND[slot] is Kind.STT:
            made = FakeStt(self.heard, self.log)
        else:
            made = FakeTts(self.log, rate=self.tts_rate)
        self.made[slot] = made
        return made


def slot_of(args: LoadArgs) -> EngineSlot:
    return EngineSlot(args.model_dir.name)


def make_slots(
    tmp: Path,
    *,
    ready: frozenset[EngineSlot] = ALL,
    engines: Engines | None = None,
    device: DeviceInfo | None = None,
    runtime: bool = True,
) -> tuple[Slots, Engines]:
    engines = engines or Engines()
    for slot in ready:
        (tmp / "models" / slot.value).mkdir(parents=True, exist_ok=True)

    def installed(slot: EngineSlot) -> Path | None:
        return tmp / "models" / slot.value if slot in ready else None

    slots = Slots(
        installed=installed,
        device=device or DeviceInfo(Device.CPU),
        has_module=lambda name: runtime,
        import_loader=engines.import_loader,
        threads=1,
    )
    return slots, engines


def make_service(
    tmp: Path,
    *,
    ready: frozenset[EngineSlot] = ALL,
    engines: Engines | None = None,
    mp3: FakeMp3 | None = None,
    trainer: FakeTrainer | None = None,
    device: DeviceInfo | None = None,
) -> tuple[KitService, Engines]:
    slots, engines = make_slots(tmp, ready=ready, engines=engines, device=device)
    service = KitService(
        slots=slots,
        vault=ClipVault(tmp / "clips", tmp / "clips.secret"),
        runner=JobRunner(),
        wakeword=trainer,
        mp3=mp3,
        memory=lambda: (3_000, 8_000),
    )
    return service, engines


class FakeTrainer:
    """V4's `WakewordKit` in miniature (I1): trains instantly into memory, counts the clips it was
    given. A blocking run reports progress until released, so a cancel stops it at a step."""

    def __init__(self, *, block: bool = False) -> None:
        self.files: dict[WakeArtifact, bytes] = {}
        self.given: list[int] = []
        self.block = block
        self.released = False

    def job_kind(self, artifact: WakeArtifact) -> JobKind:
        return KINDS[artifact]

    def prepare(self, req: WakeTrainIn, clips: Sequence[WakeClip]) -> WakeJob:
        return WakeJob(artifact=req.artifact, session_id=req.session_id, clips=tuple(clips))

    def train(self, job: WakeJob, progress: Progress) -> ArtifactInfo:
        import time

        self.given.append(len(job.clips))
        while self.block and not self.released:
            progress(0.5, "training")  # the kit's report raises once the job is cancelled
            time.sleep(0.01)
        data = json.dumps({"artifact": job.artifact.value, "clips": len(job.clips)}).encode()
        self.files[job.artifact] = data
        progress(1.0, "trained")
        return self._info(job.artifact, data)

    @staticmethod
    def _info(artifact: WakeArtifact, data: bytes) -> ArtifactInfo:
        return ArtifactInfo(
            artifact=artifact,
            sha256=sha(data),
            size=len(data),
            trained_at=datetime.now(UTC),
            licence=OWNER_LICENCE,
        )

    def status(self) -> WakeStatus:
        found = {a: self._info(a, d) for a, d in self.files.items()}
        return WakeStatus(
            verifier=found.get(WakeArtifact.VERIFIER), owned=found.get(WakeArtifact.OWNED)
        )

    def model(self, req: WakeModelIn) -> WakeModel:
        artifact = req.artifact
        data = self.files.get(artifact)
        if data is None:
            raise KitRefused("not_found", "That wake-word file has not been trained yet.")
        return WakeModel(
            artifact=artifact,
            data=encode_pcm(data),
            format="json",
            sha256=sha(data),
            licence=OWNER_LICENCE,
        )

    def delete(self) -> int:
        n = len(self.files)
        self.files.clear()
        return n
