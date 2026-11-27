# src/jarvis/localspeech/wakeword/formats.py
"""Row 83's two wake-word files and the rules both sides share (R5.2, plan 3.4, D5). Pure: the
standard library and Pydantic only, so the kit (which writes the files) and the cloud
(`jarvis.voice.wakeword_api`, which passes them to the console) both read it.

- Stage 1, the personal verifier (`VerifierFile`, JSON): openWakeWord's custom-verifier method, a
  logistic regression on the 16 x 96 embedding window the console's detector already computes,
  with the standard scaler folded into the weights (so his average voice features are not in the
  file). The console asks it only when today's detector scores at least `VERIFIER_GATE`, and its
  probability replaces the score, as `openwakeword.Model.predict` does.
- Stage 2, the owned model (ONNX in the console's format: [1, 16, 96] float32 -> [1, 1] score) with
  its MANIFEST (`ModelCard`) and `LicenseRef-Owner`; swapped in only when `beats_current`.

Licences (plan risk 2, recorded here): today's `hey_jarvis_v0.1.onnx` is CC BY-NC-SA 4.0, personal
use only, so stage 2 is required before any launch. The two feature models every stage reads
(`melspectrogram.onnx`, `embedding_model.onnx`) are recorded under the same licence in
`static/wakeword/MANIFEST.txt`: a launch also needs a permissive source for them (`LAUNCH_WORDS`).
"""

from __future__ import annotations

import hashlib
import math
from collections.abc import Sequence
from pathlib import Path
from typing import Final, Literal, Self

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, field_validator, model_validator

from jarvis.localspeech.protocol import OWNER_LICENCE, PERMISSIVE_LICENCES, SHA256

# ---- the console's detector (static/console-wakeword.js), mirrored by the kit's evals -----------
SAMPLE_RATE: Final = 16_000
FRAME_SAMPLES: Final = 1280  # 80 ms: one model step
FRAME_MS: Final = 80
FRAMES: Final = 16  # embeddings the wake model reads (1.28 s)
DIM: Final = 96
FEATURES: Final = FRAMES * DIM
THRESHOLD: Final = 0.5  # DEFAULT_THRESHOLD
PATIENCE: Final = 2  # PATIENCE_FRAMES
COOLDOWN_FRAMES: Final = 2000 // FRAME_MS  # COOLDOWN_MS
WARMUP: Final = 5  # WARMUP_FRAMES

# ---- the files -----------------------------------------------------------------------------------
VERIFIER_GATE: Final = 0.1  # openWakeWord's custom_verifier_threshold
VERIFIER_FORMAT: Final = "jarvis-wake-verifier"
VERIFIER_MAX_BYTES: Final = 200_000
OWNED_NAME: Final = "hey_jarvis_owned"
OWNED_FILE: Final = f"{OWNED_NAME}.onnx"
OWNED_MAX_BYTES: Final = 2_000_000
VERIFIER_MEDIA: Final = "application/json"
OWNED_MEDIA: Final = "application/octet-stream"
CURRENT_MODEL: Final = "hey_jarvis_v0.1.onnx"
MEL_MODEL: Final = "melspectrogram.onnx"
EMBEDDING_MODEL: Final = "embedding_model.onnx"
CURRENT_LICENCE: Final = "CC-BY-NC-SA-4.0"  # all three vendored models (static/wakeword)
LAUNCH_WORDS: Final = (
    "Today's Hey Jarvis model is licensed for personal, non-commercial use only (CC BY-NC-SA "
    "4.0). Your own model must replace it before any launch, and the two feature models it "
    "reads, recorded under the same licence, need a permissive source too."
)
FEATURES_PERMISSIVE: Final = False  # the feature models' recorded licence is CC BY-NC-SA 4.0
EVALS_MAX: Final = 12
WORDS_MAX: Final = 200
# The console's vendored models, in the installed package: the kit reads them (never downloads
# them), the cloud reads only their pinned hashes from MANIFEST.txt.
CONSOLE_MODELS_DIR: Final = Path(__file__).resolve().parents[2] / "api" / "static" / "wakeword"


def console_pins(folder: Path = CONSOLE_MODELS_DIR) -> dict[str, str]:
    """`sha256 <hex> <bytes> <name> ...` lines of the console's MANIFEST.txt -> {name: hex}."""
    pins: dict[str, str] = {}
    for line in (folder / "MANIFEST.txt").read_text(encoding="utf-8").splitlines():
        parts = line.split()
        if len(parts) >= 4 and parts[0] == "sha256":
            pins[parts[3]] = parts[1]
    return pins


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


def _finite(values: Sequence[float]) -> None:
    if not all(math.isfinite(v) for v in values):
        raise ValueError("every number must be finite")


def sigmoid(z: float) -> float:
    """The logistic function without overflow (the console's `1 / (1 + Math.exp(-z))`)."""
    if z >= 0:
        return 1.0 / (1.0 + math.exp(-z))
    e = math.exp(z)
    return e / (1.0 + e)


class VerifierFile(_Frozen):
    """Stage 1's plain JSON weights. `score` is the console's rule, line for line."""

    format: Literal["jarvis-wake-verifier"] = VERIFIER_FORMAT
    version: Literal[1] = 1
    licence: Literal["LicenseRef-Owner"] = OWNER_LICENCE
    frames: Literal[16] = FRAMES
    dim: Literal[96] = DIM
    embedding_sha256: str = Field(pattern=SHA256)  # the features it reads
    gate: float = Field(default=VERIFIER_GATE, gt=0, lt=1)
    weights: tuple[float, ...] = Field(min_length=FEATURES, max_length=FEATURES)
    bias: float
    trained_at: AwareDatetime
    clips: int = Field(ge=1)  # his "Hey Jarvis" clips it was trained on
    evals: dict[str, float] = Field(default_factory=dict, max_length=EVALS_MAX)

    @model_validator(mode="after")
    def _numbers(self) -> Self:
        _finite((*self.weights, self.bias, *self.evals.values()))
        return self

    def score(self, base: float, window: Sequence[float]) -> float:
        """`base` is today's detector's score for the frame, `window` its 16 x 96 embeddings
        (oldest first, row-major): below the gate the score stands; above, the verifier's
        probability that it is the owner saying it."""
        if base < self.gate:
            return base
        if len(window) != FEATURES:
            raise ValueError("a window is 16 x 96 numbers")
        z = self.bias + math.fsum(w * x for w, x in zip(self.weights, window, strict=True))
        return sigmoid(z)

    def to_bytes(self) -> bytes:
        return self.model_dump_json().encode("utf-8")

    @classmethod
    def parse(cls, data: bytes) -> VerifierFile:
        """ValueError (in fixed words) for anything but one of these files."""
        if len(data) > VERIFIER_MAX_BYTES:
            raise ValueError("the verifier file is too large")
        try:
            return cls.model_validate_json(data)
        except ValueError:
            raise ValueError("not a JARVIS wake-word verifier file") from None


class DataSource(_Frozen):
    """One kind of audio a model was trained on, with its licence (plan risk 2)."""

    name: str = Field(min_length=1, max_length=80)
    licence: str
    detail: str = Field(default="", max_length=WORDS_MAX)

    @field_validator("licence")
    @classmethod
    def _licence(cls, v: str) -> str:
        if v not in PERMISSIVE_LICENCES | {OWNER_LICENCE}:
            raise ValueError("training audio whose licence is not permissive is left out")
        return v


class ModelCard(_Frozen):
    """The owned model's MANIFEST: what it is, what it read, what it was trained on, how it did."""

    sha256: str = Field(pattern=SHA256)
    size: int = Field(ge=1, le=OWNED_MAX_BYTES)
    trained_at: AwareDatetime
    feature_models: dict[str, str]  # name -> sha256 (the console's vendored files)
    sources: tuple[DataSource, ...] = Field(min_length=1, max_length=24)
    evals: dict[str, float] = Field(default_factory=dict, max_length=EVALS_MAX)
    current_evals: dict[str, float] = Field(default_factory=dict, max_length=EVALS_MAX)
    beats_current: bool

    def text(self) -> str:
        lines = [
            'JARVIS owned "Hey Jarvis" wake-word model (R5.2 row 83, stage 2).',
            "Trained on the owner's laptop by src/jarvis/localspeech/wakeword (owned_train.py).",
            "",
            f"name:      {OWNED_NAME}",
            f"licence:   {OWNER_LICENCE} (trained by and owned by the owner)",
            "format:    ONNX opset 13; input [1, 16, 96] float32 openWakeWord embeddings,",
            "           output [1, 1] float32 score (the console's format)",
            f"trained:   {self.trained_at.isoformat(timespec='seconds')}",
            f"beats:     {'yes' if self.beats_current else 'no'} (swapped in only when yes)",
            f"evals:     {_pairs(self.evals)}",
            f"current:   {_pairs(self.current_evals)} ({CURRENT_MODEL}, {CURRENT_LICENCE})",
            "reads:     the console's vendored feature models, recorded "
            f"{CURRENT_LICENCE} (static/wakeword/LICENSE.txt):",
            *(f"           {sha} {name}" for name, sha in sorted(self.feature_models.items())),
            "data:",
            *(f"           {s.name} [{s.licence}] {s.detail}".rstrip() for s in self.sources),
            "",
            f"sha256 {self.sha256} {self.size} {OWNED_FILE}",
        ]
        return "\n".join(lines) + "\n"


def _pairs(values: dict[str, float]) -> str:
    return ", ".join(f"{k} {v:.4g}" for k, v in sorted(values.items())) or "none"


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def manifest_sha256(text: str) -> str | None:
    """The `sha256 <hex> <bytes> <name>` line of a MANIFEST for the owned model, if any."""
    for line in text.splitlines():
        parts = line.split()
        if len(parts) == 4 and parts[0] == "sha256" and parts[3] == OWNED_FILE:
            return parts[1]
    return None


def compact_evals(values: dict[str, float]) -> dict[str, float]:
    """At most `EVALS_MAX` finite numbers, rounded for display (ArtifactInfo.evals)."""
    kept = {k: round(v, 6) for k, v in sorted(values.items()) if math.isfinite(v)}
    return dict(list(kept.items())[:EVALS_MAX])


__all__ = [
    "CONSOLE_MODELS_DIR",
    "COOLDOWN_FRAMES",
    "CURRENT_LICENCE",
    "CURRENT_MODEL",
    "DIM",
    "EMBEDDING_MODEL",
    "FEATURES",
    "FEATURES_PERMISSIVE",
    "FRAMES",
    "FRAME_SAMPLES",
    "LAUNCH_WORDS",
    "MEL_MODEL",
    "OWNED_FILE",
    "OWNED_MAX_BYTES",
    "OWNED_MEDIA",
    "PATIENCE",
    "THRESHOLD",
    "VERIFIER_GATE",
    "VERIFIER_MAX_BYTES",
    "VERIFIER_MEDIA",
    "WARMUP",
    "DataSource",
    "ModelCard",
    "VerifierFile",
    "compact_evals",
    "console_pins",
    "manifest_sha256",
    "sha256_hex",
    "sigmoid",
]
