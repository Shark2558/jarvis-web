# src/jarvis/calldesk/config.py
"""The call desk's settings (R18 C). Ships in the call desk kit.

`desk.env` in the kit folder holds JARVIS's public address only (not a secret; the kit download
writes it). Everything the desk keeps lives in the owner's own profile folder,
`%LOCALAPPDATA%\\JARVIS\\CallDesk` (private to his Windows account, unlike a folder on C:\\):

    secret.json        the desk's link to JARVIS (desk id and seed)
    local-speech.key   R5.2: the laptop speech kit's key, when the kit is on this laptop
                       (install-calldesk.ps1 copies it from the kit's own private folder; or
                       JARVIS_LOCAL_SPEECH_KEY in the desk's environment). Without it the desk
                       offers no laptop speech and calls use cloud speech.
    audio-state.json   what the desk changed in Windows' sound settings (see `micguard`)
    stop.request       written by stop-calldesk.ps1; the desk and its watchdog stop
    calldesk.log       what happened (never audio, transcripts, numbers or secrets)

A bad value stops the desk at start with a plain line that never repeats the value.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlsplit

from pydantic import SecretStr

DESK_ENV = "desk.env"
SPEECH_KEY_FILE = "local-speech.key"
SPEECH_KEY_ENV = "JARVIS_LOCAL_SPEECH_KEY"  # the name the kit and the cloud use too
SPEECH_KEY_MIN = 32  # = jarvis.localspeech.protocol.KEY_MIN_CHARS
_HOST = re.compile(r"[A-Za-z0-9]([A-Za-z0-9.-]{0,251}[A-Za-z0-9])?")
_KEY = re.compile(r"[A-Z][A-Z0-9_]{0,63}")


class ConfigError(ValueError):
    """Names the setting and what is wrong, never its value."""


@dataclass(frozen=True)
class DeskConfig:
    jarvis_url: str
    data_dir: Path
    kit_dir: Path
    speech_key: SecretStr | None = field(default=None, repr=False)  # R5.2: the speech kit's

    @property
    def audio_state(self) -> Path:
        return self.data_dir / "audio-state.json"

    @property
    def secret(self) -> Path:
        return self.data_dir / "secret.json"

    @property
    def stop_request(self) -> Path:
        return self.data_dir / "stop.request"

    @property
    def log_file(self) -> Path:
        return self.data_dir / "calldesk.log"


def read_env_file(path: Path) -> dict[str, str]:
    """KEY=VALUE lines ('#' starts a comment); a missing file is empty."""
    try:
        text = path.read_text(encoding="utf-8-sig")
    except FileNotFoundError:
        return {}
    values: dict[str, str] = {}
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        key = key.strip()
        if _KEY.fullmatch(key):
            values[key] = value.strip()
    return values


def jarvis_url(raw: str) -> str:
    parts = urlsplit(raw.strip())
    ok = (
        parts.scheme == "https"
        and parts.hostname is not None
        and _HOST.fullmatch(parts.hostname) is not None
        and not parts.username
        and not parts.password
        and parts.path in ("", "/")
        and not parts.query
        and not parts.fragment
    )
    if not ok:
        raise ConfigError(
            "JARVIS_URL is not a valid address (https://host): download the kit again"
        )
    return f"https://{parts.netloc}"


def default_data_dir(environ: Mapping[str, str]) -> Path:
    override = environ.get("JARVIS_DESK_DATA", "").strip()
    if override:
        return Path(override)
    local = environ.get("LOCALAPPDATA", "").strip()
    if local:
        return Path(local) / "JARVIS" / "CallDesk"
    return Path.home() / ".jarvis-calldesk"


def speech_key(data_dir: Path, environ: Mapping[str, str]) -> SecretStr | None:
    """The laptop speech kit's key: the environment's, else the desk's own copy; None when
    neither holds one of `SPEECH_KEY_MIN`+ characters (then the desk uses cloud speech)."""
    raw = environ.get(SPEECH_KEY_ENV, "").strip()
    if not raw:
        try:
            raw = (data_dir / SPEECH_KEY_FILE).read_text(encoding="utf-8-sig").strip()
        except (OSError, UnicodeDecodeError):
            return None
    return SecretStr(raw) if len(raw) >= SPEECH_KEY_MIN else None


def load(kit_dir: Path, environ: Mapping[str, str]) -> DeskConfig:
    values = read_env_file(kit_dir / DESK_ENV)
    raw = environ.get("JARVIS_URL") or values.get("JARVIS_URL", "")
    if not raw.strip():
        raise ConfigError("JARVIS_URL is missing from desk.env: download the kit again")
    data_dir = default_data_dir(environ)
    return DeskConfig(
        jarvis_url=jarvis_url(raw),
        data_dir=data_dir,
        kit_dir=kit_dir,
        speech_key=speech_key(data_dir, environ),
    )


__all__ = [
    "DESK_ENV",
    "SPEECH_KEY_ENV",
    "SPEECH_KEY_FILE",
    "ConfigError",
    "DeskConfig",
    "default_data_dir",
    "jarvis_url",
    "load",
    "speech_key",
]
