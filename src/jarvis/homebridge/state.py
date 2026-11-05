# src/jarvis/homebridge/state.py
"""What the bridge keeps in its data volume (R3 D4; Layer 7 at home). Ships in the home kit.

    /data/secret.json        {home_id, seed}            mode 600, the home's one secret
    /data/link-pending.json  {secret, until}            mode 600, written by `link` while linking
    /data/state.json         BridgeState (revs, arm, faces ids, exposed devices, settings)

Writes are atomic (temp file, then rename). Reads fail closed: an unreadable secret means "not
linked" (the bridge answers nothing), an unreadable state means "nothing applied yet" (it asks the
cloud again). A part of a new state is applied only if its `rev` is newer than the one held, so a
delayed push can't undo a newer one.
"""

from __future__ import annotations

import base64
import json
import os
import time
from dataclasses import dataclass
from pathlib import Path

from pydantic import ValidationError

from jarvis.home import signing
from jarvis.home.ports import BridgeState, is_home_id

SECRET = "secret.json"
PENDING = "link-pending.json"
STATE = "state.json"
PENDING_TTL_S = 900.0


@dataclass(frozen=True, repr=False)
class Linked:
    home_id: str
    keys: signing.HomeKeys

    def __repr__(self) -> str:
        return f"Linked({self.home_id})"


def _write_private(path: Path, data: object) -> None:
    tmp = path.with_suffix(".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        json.dump(data, fh)
    os.replace(tmp, path)


class BridgeStore:
    def __init__(self, data_dir: Path, *, clock: object = time.time) -> None:
        self._dir = data_dir
        self._clock = clock
        self._state = BridgeState()
        self._loaded_for: str | None = None

    # ---- the secret ----------------------------------------------------------------------------

    def linked(self) -> Linked | None:
        try:
            raw = json.loads((self._dir / SECRET).read_text(encoding="utf-8"))
            home_id = raw["home_id"]
            seed = base64.b64decode(raw["seed"], validate=True)
            if not is_home_id(home_id):
                return None
            found = Linked(home_id=home_id, keys=signing.derive_keys(seed))
        except (OSError, ValueError, KeyError, TypeError):
            return None
        if self._loaded_for != found.home_id:  # a new link starts from nothing
            self._loaded_for = found.home_id
            self._state = self._read_state()
        return found

    def save_link(self, home_id: str, seed: bytes) -> None:
        self._dir.mkdir(parents=True, exist_ok=True)
        _write_private(
            self._dir / SECRET,
            {"home_id": home_id, "seed": base64.b64encode(seed).decode("ascii")},
        )
        self._state = BridgeState()
        self._loaded_for = home_id
        self._write_state()
        self.clear_pending()

    def forget_link(self) -> None:
        """The cloud no longer knows this home: drop the secret and everything armed."""
        (self._dir / SECRET).unlink(missing_ok=True)
        self._state = BridgeState()
        self._loaded_for = None
        self._write_state()

    # ---- the one-time link secret --------------------------------------------------------------

    def set_pending(self, secret: bytes) -> None:
        self._dir.mkdir(parents=True, exist_ok=True)
        until = float(self._clock()) + PENDING_TTL_S  # type: ignore[operator]
        _write_private(
            self._dir / PENDING,
            {
                "secret": base64.urlsafe_b64encode(secret).decode("ascii").rstrip("="),
                "until": until,
            },
        )

    def pending_keys(self) -> signing.HomeKeys | None:
        try:
            raw = json.loads((self._dir / PENDING).read_text(encoding="utf-8"))
            if float(raw["until"]) < float(self._clock()):  # type: ignore[operator]
                return None
            return signing.derive_keys(base64.urlsafe_b64decode(raw["secret"] + "="))
        except (OSError, ValueError, KeyError, TypeError):
            return None

    def clear_pending(self) -> None:
        (self._dir / PENDING).unlink(missing_ok=True)

    # ---- the state -----------------------------------------------------------------------------

    @property
    def state(self) -> BridgeState:
        if self._loaded_for is None:
            self.linked()  # loads the saved state for this link
        return self._state

    def _read_state(self) -> BridgeState:
        try:
            return BridgeState.model_validate_json((self._dir / STATE).read_text("utf-8"))
        except (OSError, ValueError, ValidationError):
            return BridgeState()

    def _write_state(self) -> None:
        try:
            self._dir.mkdir(parents=True, exist_ok=True)
            _write_private(self._dir / STATE, json.loads(self._state.model_dump_json()))
        except OSError:
            pass  # the state is rebuilt from the cloud at the next heartbeat

    def apply(self, new: BridgeState) -> BridgeState:
        """The parts of `new` that are newer than what is held; also keeps them. The returned
        state carries only what changed (what plugins should be told)."""
        old = self._state
        changed = BridgeState(
            arm=new.arm if new.arm and (old.arm is None or new.arm.rev > old.arm.rev) else None,
            faces=new.faces
            if new.faces and (old.faces is None or new.faces.rev > old.faces.rev)
            else None,
            devices=new.devices
            if new.devices and (old.devices is None or new.devices.rev > old.devices.rev)
            else None,
            settings=new.settings
            if new.settings and (old.settings is None or new.settings.rev > old.settings.rev)
            else None,
        )
        if any(v is not None for v in changed.model_dump().values()):
            self._state = old.merged(changed)
            self._write_state()
        return changed


__all__ = ["BridgeStore", "Linked"]
