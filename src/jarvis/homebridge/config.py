# src/jarvis/homebridge/config.py
"""The bridge's settings, read from `bridge.env` (R3 D3, D4). Ships in the home kit.

Each value is validated here; a bad one stops the bridge at start with a plain line that never
repeats the value (the Home Assistant token must not reach a log). The bridge talks only to
JARVIS's URL, Home Assistant, Frigate and Mosquitto.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlsplit

BRIDGE_VERSION = "0.1.0"
SIGNED_PORT = 8099  # the signed API (Funnel proxies to it)
LOCAL_PORT = 8098  # the local Faces page (never funnelled)
MAX_BODY_BYTES = 64 * 1024  # a signed request from the cloud
_HOST = re.compile(r"[A-Za-z0-9]([A-Za-z0-9.-]{0,251}[A-Za-z0-9])?")


class ConfigError(ValueError):
    """The message names the key and what is wrong, never the value."""


def _url(env: Mapping[str, str], key: str, *, schemes: tuple[str, ...], default: str = "") -> str:
    raw = env.get(key, default).strip()
    if not raw:
        return ""
    parts = urlsplit(raw)
    ok = (
        parts.scheme in schemes
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
            f"{key} is not a valid address (use {' or '.join(schemes)}://host[:port])"
        )
    return f"{parts.scheme}://{parts.netloc}"


@dataclass(frozen=True)
class BridgeConfig:
    jarvis_url: str
    data_dir: Path
    ha_url: str = "http://host.docker.internal:8123"
    ha_token: str = field(default="", repr=False)
    bind_host: str = "0.0.0.0"  # inside the container; compose publishes it on 127.0.0.1 only
    signed_port: int = SIGNED_PORT

    @property
    def ha_linked(self) -> bool:
        return bool(self.ha_token)


def load_config(env: Mapping[str, str]) -> BridgeConfig:
    jarvis = _url(env, "JARVIS_URL", schemes=("https",))
    if not jarvis:
        raise ConfigError("JARVIS_URL is missing (it is filled in by the home kit)")
    data = Path(env.get("BRIDGE_DATA_DIR", "/data"))
    token = env.get("HA_TOKEN", "").strip()
    if token and (
        len(token) > 4096
        or not token.isascii()
        or not token.isprintable()
        or any(c.isspace() for c in token)
    ):
        raise ConfigError("HA_TOKEN is not a valid token")
    return BridgeConfig(
        jarvis_url=jarvis,
        data_dir=data,
        ha_url=_url(
            env, "HA_URL", schemes=("http", "https"), default="http://host.docker.internal:8123"
        ),
        ha_token=token,
        bind_host=env.get("BRIDGE_BIND", "0.0.0.0"),
    )


__all__ = [
    "BRIDGE_VERSION",
    "LOCAL_PORT",
    "MAX_BODY_BYTES",
    "SIGNED_PORT",
    "BridgeConfig",
    "ConfigError",
    "load_config",
]
