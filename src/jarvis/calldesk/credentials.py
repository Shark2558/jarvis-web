# src/jarvis/calldesk/credentials.py
"""The desk's credentials (R18 build brief: "authenticated like the home bridge (its signed device
credentials; reuse jarvis.homebridge signing)"; I0's `DeskDoor`: linked with a code, like the home
bridge).

The owner presses "Link the call desk" in the console (`POST /v1/calls/desk/code`), types the code
into `install-calldesk.ps1 -Link`, and the desk sends it once (`link.py`); JARVIS answers the
desk's id and a 32-byte seed. From the seed `jarvis.home.signing` derives the UP and DOWN keys
(the one HMAC implementation), and the desk signs its WebSocket upgrade, `GET /v1/calls/desk/ws`,
exactly as the home bridge signs a request (`X-Jarvis-Home`: time, nonce, MAC), so the cloud
checks it with the desk's record. The seed is kept in the owner's profile folder
(`secret.json`, written atomically, mode 600); reads fail closed (unreadable means "not linked").
Nothing here logs a key or a seed.
"""

from __future__ import annotations

import base64
import binascii
import json
import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from jarvis.calls.protocol import DESK_WS_PATH
from jarvis.home import signing


class NotLinked(ValueError):
    """Plain words for the owner; never a secret."""


@dataclass(frozen=True, repr=False)
class DeskCredentials:
    desk_id: str
    keys: signing.HomeKeys

    def __repr__(self) -> str:
        return f"DeskCredentials({self.desk_id})"

    def upgrade_headers(self, now: float, *, target: str = DESK_WS_PATH) -> dict[str, str]:
        """The signed header for one WebSocket upgrade (an empty body)."""
        header = signing.sign(
            self.keys, "up", home_id=self.desk_id, method="GET", target=target, body=b"", now=now
        )
        return {signing.HEADER: header}


def _seed(text: object) -> bytes:
    if not isinstance(text, str):
        raise TypeError("seed")
    padded = text + "=" * (-len(text) % 4)
    if "-" in text or "_" in text:
        return base64.urlsafe_b64decode(padded.encode("ascii"))
    return base64.b64decode(padded, validate=True)


def parse_link(data: Mapping[str, Any]) -> tuple[str, bytes]:
    """(desk id, seed) from JARVIS's link answer or the saved file, or NotLinked."""
    try:
        desk_id = data.get("desk_id") or data.get("home_id")
        seed = _seed(data["seed"])
        keys = signing.derive_keys(seed)
        signing.sign(keys, "up", home_id=str(desk_id), method="GET", target="/", body=b"", now=0)
    except (ValueError, KeyError, TypeError, binascii.Error):
        raise NotLinked("JARVIS's answer was not a call desk link.") from None
    return str(desk_id), seed


class CredentialStore:
    def __init__(self, path: Path) -> None:
        self.path = path

    def load(self) -> DeskCredentials | None:
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
            if not isinstance(raw, dict):
                return None
            desk_id, seed = parse_link(raw)
        except (OSError, ValueError):
            return None
        return DeskCredentials(desk_id=desk_id, keys=signing.derive_keys(seed))

    def save(self, desk_id: str, seed: bytes) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        data = {"desk_id": desk_id, "seed": base64.b64encode(seed).decode("ascii")}
        tmp = self.path.with_suffix(".tmp")
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(data, fh)
        os.replace(tmp, self.path)

    def forget(self) -> None:
        self.path.unlink(missing_ok=True)


__all__ = ["CredentialStore", "DeskCredentials", "NotLinked", "parse_link"]
