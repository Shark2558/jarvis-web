# src/jarvis/homebridge/arm.py
"""The bridge's own copy of what the cloud told it about the alarm and the cameras (R3 D8).

`camera_state.json` in the data volume (mode 600, written atomically) keeps the arm state, the
camera settings and the ids of consented people so a restart of the laptop does not forget them.
The cloud is the authority: a state part is applied only when its `rev` is newer (or equal, which
is a replay and changes nothing). Until the first state ever arrives the bridge is DISARMED and
sends no person detections (D1); the heartbeat reply brings the cloud's state within 2 minutes.

This is a bridge-kit module: standard library, pydantic and `jarvis.home.ports` only.
"""

from __future__ import annotations

import contextlib
import json
import logging
import os
import tempfile
from pathlib import Path

from pydantic import BaseModel, ConfigDict, ValidationError

from jarvis.home.ports import ArmState as WireArm
from jarvis.home.ports import BridgeState, PersonId, SettingsState

log = logging.getLogger(__name__)


class _Saved(BaseModel):
    model_config = ConfigDict(extra="ignore")

    arm: WireArm | None = None
    settings: SettingsState | None = None
    faces: tuple[PersonId, ...] = ()
    faces_rev: int = 0


class ArmState:
    """Arm state, camera settings and consented ids; `apply` takes the cloud's `BridgeState`."""

    def __init__(self, path: Path) -> None:
        self._path = path
        self._saved = self._load()

    # ---- file --------------------------------------------------------------------------------

    def _load(self) -> _Saved:
        try:
            return _Saved.model_validate_json(self._path.read_bytes())
        except FileNotFoundError:
            return _Saved()
        except (ValidationError, OSError, ValueError):
            log.error("camera state unreadable; starting disarmed")
            return _Saved()

    def _save(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=self._path.parent, prefix=".camera_state.")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(self._saved.model_dump_json())
            os.chmod(tmp, 0o600)
            os.replace(tmp, self._path)
        except OSError:
            with contextlib.suppress(OSError):
                os.unlink(tmp)
            log.error("camera state not saved")

    # ---- reading -----------------------------------------------------------------------------

    @property
    def armed(self) -> bool:
        return self._saved.arm is not None and self._saved.arm.armed

    @property
    def rev(self) -> int:
        return self._saved.arm.rev if self._saved.arm is not None else 0

    @property
    def settings(self) -> SettingsState | None:
        return self._saved.settings

    @property
    def faces(self) -> frozenset[str]:
        return frozenset(self._saved.faces)

    # ---- applying ----------------------------------------------------------------------------

    def apply(self, state: BridgeState) -> int | None:
        """Take every newer part of `state`. Returns the arm rev now in force when the state
        carried an arm part at or above ours (the caller acks it), else None."""
        changed = False
        arm_rev: int | None = None
        if state.arm is not None and state.arm.rev >= self.rev:
            if self._saved.arm != state.arm:
                self._saved = self._saved.model_copy(update={"arm": state.arm})
                changed = True
            arm_rev = state.arm.rev
        if state.settings is not None and (
            self._saved.settings is None or state.settings.rev >= self._saved.settings.rev
        ):
            if self._saved.settings != state.settings:
                self._saved = self._saved.model_copy(update={"settings": state.settings})
                changed = True
        if state.faces is not None and state.faces.rev >= self._saved.faces_rev:
            ids = tuple(p for p in state.faces.people if p not in set(state.faces.deleting))
            if ids != self._saved.faces or state.faces.rev != self._saved.faces_rev:
                self._saved = self._saved.model_copy(
                    update={"faces": ids, "faces_rev": state.faces.rev}
                )
                changed = True
        if changed:
            self._save()
        return arm_rev

    def dump(self) -> str:
        return json.dumps(self._saved.model_dump(mode="json"))


__all__ = ["ArmState"]
