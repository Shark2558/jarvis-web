# src/jarvis/localspeech/kitconfig.py
"""Where the laptop speech kit keeps its things, and its key (R5.2 V1). Kit-safe: the standard
library and Pydantic only; never imported by the cloud.

Everything lives in one private folder on the laptop (the installer locks it to the owner's
account): `%LOCALAPPDATA%\\JARVIS\\LocalSpeech` on Windows, `~/.jarvis-local-speech` elsewhere,
or `JARVIS_SPEECH_KIT_DIR`. Inside it:

    key            the gate's key (made by the start script; the cloud and the call desk hold it)
    clips.secret   the key the session's recordings are encrypted with (only the kit holds it)
    clips/         the session's recordings, encrypted at rest
    models/        the pinned model files, each with its LICENCE.txt beside it
    installed.json what this kit installed
    wakeword/      the wake-word files trained here (V4's)

The kit's server listens on `127.0.0.1:SERVER_PORT` only; the address is not configurable.
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from pydantic import SecretStr

from jarvis.localspeech.protocol import KEY_MIN_CHARS, SERVER_PORT

KIT_VERSION_NOW: Final = "1.0.0"  # the kit's own track (protocol.KIT_VERSION), never JARVIS's
HOST: Final = "127.0.0.1"
PORT: Final = SERVER_PORT
ENV_DIR: Final = "JARVIS_SPEECH_KIT_DIR"
ENV_KEY: Final = "JARVIS_LOCAL_SPEECH_KEY"  # the same name the cloud's config reads
ENV_DEVICE: Final = "JARVIS_SPEECH_KIT_DEVICE"  # auto (default), cpu or cuda
ENV_MANIFEST: Final = "JARVIS_SPEECH_KIT_MANIFEST"
DEVICES: Final = ("auto", "cpu", "cuda")
MANIFEST_NAME: Final = "models.json"


class KitConfigError(RuntimeError):
    """The kit can't start as configured (plain words, never the key)."""


def default_dir() -> Path:
    if sys.platform == "win32":
        base = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
        return Path(base) / "JARVIS" / "LocalSpeech"
    return Path.home() / ".jarvis-local-speech"


def default_manifest() -> Path:
    """The manifest beside the kit's scripts: `deploy/local-speech/models.json` in a checkout, the
    kit folder's own copy when installed from the kit zip."""
    here = Path(__file__).resolve()
    for parent in here.parents:
        for candidate in (
            parent / "deploy" / "local-speech" / MANIFEST_NAME,
            parent / MANIFEST_NAME,
        ):
            if candidate.is_file():
                return candidate
    return here.parents[3] / "deploy" / "local-speech" / MANIFEST_NAME


@dataclass(frozen=True)
class KitConfig:
    data_dir: Path
    manifest: Path
    key: SecretStr | None = None
    device: str = "auto"

    def __repr__(self) -> str:  # the key never appears, even in a traceback
        return f"KitConfig(data_dir={self.data_dir!s}, device={self.device})"

    @property
    def clips_dir(self) -> Path:
        return self.data_dir / "clips"

    @property
    def clip_key_file(self) -> Path:
        return self.data_dir / "clips.secret"

    @property
    def models_dir(self) -> Path:
        return self.data_dir / "models"

    @property
    def installed_file(self) -> Path:
        return self.data_dir / "installed.json"

    @property
    def wakeword_dir(self) -> Path:
        return self.data_dir / "wakeword"

    @property
    def key_file(self) -> Path:
        return self.data_dir / "key"

    def require_key(self) -> str:
        """The gate's key, or KitConfigError: the server never starts without one (fail closed)."""
        value = self.key.get_secret_value() if self.key is not None else ""
        if len(value) < KEY_MIN_CHARS:
            raise KitConfigError(
                f"The kit's key is missing or shorter than {KEY_MIN_CHARS} characters. "
                "Start the kit with its start script, which makes the key."
            )
        return value

    @classmethod
    def from_env(cls, env: dict[str, str] | None = None) -> KitConfig:
        values = dict(os.environ if env is None else env)
        device = values.get(ENV_DEVICE, "auto").strip().lower() or "auto"
        if device not in DEVICES:
            raise KitConfigError(f"{ENV_DEVICE} must be one of: {', '.join(DEVICES)}.")
        data_dir = Path(values[ENV_DIR]) if values.get(ENV_DIR) else default_dir()
        manifest = Path(values[ENV_MANIFEST]) if values.get(ENV_MANIFEST) else default_manifest()
        raw_key = values.get(ENV_KEY, "").strip()
        return cls(
            data_dir=data_dir,
            manifest=manifest,
            key=SecretStr(raw_key) if raw_key else None,
            device=device,
        )


def private_dir(path: Path) -> Path:
    """Make `path` (and its parents) and keep it to the owner: 0700 where the system has modes
    (on Windows the installer locks the folder with icacls)."""
    path.mkdir(parents=True, exist_ok=True)
    if os.name != "nt":
        path.chmod(0o700)
    return path


def write_private(path: Path, data: bytes) -> None:
    """Write a file only the owner can read, atomically (a temporary file, then a rename)."""
    private_dir(path.parent)
    tmp = path.with_name(f".{path.name}.tmp")
    flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC | getattr(os, "O_BINARY", 0)
    fd = os.open(tmp, flags, 0o600)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise
    os.replace(tmp, path)


__all__ = [
    "DEVICES",
    "ENV_DEVICE",
    "ENV_DIR",
    "ENV_KEY",
    "ENV_MANIFEST",
    "HOST",
    "KIT_VERSION_NOW",
    "PORT",
    "KitConfig",
    "KitConfigError",
    "default_dir",
    "default_manifest",
    "private_dir",
    "write_private",
]
