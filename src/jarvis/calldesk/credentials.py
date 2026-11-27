# src/jarvis/calldesk/credentials.py
"""The desk's credentials (R18 build brief: "authenticated like the home bridge (its signed device
credentials; reuse jarvis.homebridge signing)").

The desk signs its WebSocket upgrade, `GET /v1/calls/desk/ws`, exactly as the home bridge signs a
request: `X-Jarvis-Home` from `jarvis.home.signing` (the one HMAC implementation) with the home's
UP key, so the cloud checks it with the home's record (time window, nonce, MAC). The credentials
are the home link's: the home id and the 32-byte seed in the bridge's own `secret.json` format.
`install-calldesk.ps1 -Link` copies them from JARVIS Home's bridge (inside WSL) into the owner's
profile folder; `python -m jarvis.calldesk link-home` reads that file's JSON from stdin.

Reads fail closed: anything unreadable means "not linked". Nothing here logs a key or a seed.
"""

from __future__ import annotations

import base64
import json
import os
from dataclasses import dataclass
from pathlib import Path

from jarvis.calls.protocol import DESK_WS_PATH
from jarvis.home import signing


class NotLinked(ValueError):
    """Plain words for the owner; never a secret."""


@dataclass(frozen=True, repr=False)
class DeskCredentials:
    home_id: str
    keys: signing.HomeKeys

    def __repr__(self) -> str:
        return f"DeskCredentials({self.home_id})"

    def upgrade_headers(self, now: float, *, target: str = DESK_WS_PATH) -> dict[str, str]:
        """The signed header for one WebSocket upgrade (an empty body)."""
        header = signing.sign(
            self.keys, "up", home_id=self.home_id, method="GET", target=target, body=b"", now=now
        )
        return {signing.HEADER: header}


def parse_secret(text: str) -> tuple[str, bytes]:
    """(home_id, seed) from the bridge's `secret.json`, or NotLinked."""
    try:
        raw = json.loads(text)
        home_id = raw["home_id"]
        seed = base64.b64decode(raw["seed"], validate=True)
        keys = signing.derive_keys(seed)
        signing.sign(keys, "up", home_id=home_id, method="GET", target="/", body=b"", now=0.0)
    except (ValueError, KeyError, TypeError):
        raise NotLinked("That is not JARVIS Home's link: is JARVIS Home linked?") from None
    return str(home_id), seed


class CredentialStore:
    def __init__(self, path: Path) -> None:
        self.path = path

    def load(self) -> DeskCredentials | None:
        try:
            home_id, seed = parse_secret(self.path.read_text(encoding="utf-8"))
        except (OSError, NotLinked):
            return None
        return DeskCredentials(home_id=home_id, keys=signing.derive_keys(seed))

    def save(self, home_id: str, seed: bytes) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        data = {"home_id": home_id, "seed": base64.b64encode(seed).decode("ascii")}
        tmp = self.path.with_suffix(".tmp")
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(data, fh)
        os.replace(tmp, self.path)

    def link_from_bridge(self, text: str) -> str:
        """Save the bridge's secret (validated); returns the home id."""
        home_id, seed = parse_secret(text)
        self.save(home_id, seed)
        return home_id

    def forget(self) -> None:
        self.path.unlink(missing_ok=True)


__all__ = ["CredentialStore", "DeskCredentials", "NotLinked", "parse_secret"]
