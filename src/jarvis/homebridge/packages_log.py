# src/jarvis/homebridge/packages_log.py
"""The doorstep (R3 D16): Frigate's state classification -> `Package` events, and a 7-day log.

`frigate/<camera>/classification/doorstep` carries the state when it changes (the payload shape is
not verified against Frigate 0.17: a bare word or a JSON object with `state`, `label` or `class`
are all read). Only `package` and `empty` count; anything else is ignored. A repeat of the state we
already have is ignored. The log (`packages.jsonl`, mode 600) keeps the changes for 7 days and
answers `GET /bridge/v1/packages` (camera history, D15). A change is marked `delivered` when a
person stood in the doorstep zone in the 2 minutes before.

Bridge-kit module: standard library, pydantic and `jarvis.home.ports` only.
"""

from __future__ import annotations

import json
import logging
import os
import re
from collections.abc import Callable
from pathlib import Path
from typing import Any

from jarvis.home.ports import LABEL_ID, Package

log = logging.getLogger(__name__)

KEEP_S = 7 * 86400.0
MAX_ROWS = 2000
STATES = {"package": "package", "empty": "empty"}


def state_of(payload: bytes) -> str | None:
    """`package` | `empty` from a classification payload, else None."""
    if len(payload) > 4096:
        return None
    text = payload.decode("utf-8", "replace").strip()
    word: Any = text
    if text.startswith("{"):
        try:
            obj = json.loads(text)
        except ValueError:
            return None
        word = next((obj[k] for k in ("state", "label", "class") if k in obj), None)
    if not isinstance(word, str):
        return None
    return STATES.get(word.strip().strip('"').lower())


class PackagesLog:
    def __init__(self, path: Path, now: Callable[[], float]) -> None:
        self._path = path
        self._now = now
        self._state: dict[tuple[str, str], str] = {}

    def _rows(self) -> list[dict[str, Any]]:
        try:
            lines = self._path.read_text(encoding="utf-8").splitlines()
        except FileNotFoundError:
            return []
        except OSError:
            log.error("package log unreadable")
            return []
        rows = []
        for line in lines:
            try:
                row = json.loads(line)
            except ValueError:
                continue
            if isinstance(row, dict):
                rows.append(row)
        return rows

    def _write(self, rows: list[dict[str, Any]]) -> None:
        cutoff = self._now() - KEEP_S
        kept = [r for r in rows if isinstance(r.get("at"), int | float) and r["at"] >= cutoff]
        data = "".join(json.dumps(r, separators=(",", ":")) + "\n" for r in kept[-MAX_ROWS:])
        self._path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self._path.with_suffix(".tmp")
        try:
            tmp.write_text(data, encoding="utf-8")
            os.chmod(tmp, 0o600)
            os.replace(tmp, self._path)
        except OSError:
            log.error("package log not saved")

    def on_state(
        self, camera: str, zone: str, state: str, *, delivered: bool, at: float
    ) -> Package | None:
        """Log a change and return the event to send; None when the state did not change."""
        if not re.fullmatch(LABEL_ID, camera) or not re.fullmatch(LABEL_ID, zone):
            return None
        key = (camera, zone)
        if self._state.get(key) == state:
            return None
        self._state[key] = state
        delivered = delivered and state == "package"
        self._write(
            [
                *self._rows(),
                {"camera": camera, "zone": zone, "state": state, "at": at, "delivered": delivered},
            ]
        )
        return Package(
            type="package",
            id=f"pkg:{camera}:{int(at)}",
            camera=camera,
            zone=zone,
            state=state,  # type: ignore[arg-type]
            at=at,
            delivered=delivered,
        )

    def query(
        self, after: float, before: float, camera: str | None, limit: int
    ) -> tuple[list[dict[str, Any]], bool]:
        rows = [
            r
            for r in self._rows()
            if after <= r.get("at", 0) <= before and (camera is None or r.get("camera") == camera)
        ]
        rows.sort(key=lambda r: r["at"], reverse=True)
        return [
            {k: r[k] for k in ("camera", "zone", "state", "at", "delivered") if k in r}
            for r in rows[:limit]
        ], len(rows) > limit


__all__ = ["KEEP_S", "PackagesLog", "state_of"]
