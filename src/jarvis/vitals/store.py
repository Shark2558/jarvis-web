# src/jarvis/vitals/store.py
"""Vitals on the `Docs` port (R4 D2, D4; equality + a single order_by only).

    jarvis_vitals_providers/{uid}__{id}   the manual record (+ user_id)
    jarvis_vitals_status/{uid}__{id}      {user_id, status, at}: last status, for cross-line alerts

Only `manual` records are stored; `auto` ones are computed from the meters. Metadata only: no key
value is ever stored here. Errors carry plain words, never the cause's text.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import ValidationError

from jarvis.logging import get_logger
from jarvis.storage.docs import Delete, Docs, Query, Set
from jarvis.undo.store import owner_ok
from jarvis.vitals.models import MAX_MANUAL, RANK, Provider, Status

log = get_logger(__name__)

UNAVAILABLE = "JARVIS couldn't open the Vitals list just now. Try again in a minute."
FULL = f"You are tracking the most keys allowed ({MAX_MANUAL}). Remove one first."
LIST_LIMIT = MAX_MANUAL + 1


class VitalsUnavailable(RuntimeError):
    """Storage trouble (plain words)."""


class VitalsFull(RuntimeError):
    """The per-owner record cap is reached (plain words)."""


class VitalsStore:
    def __init__(self, docs: Docs, *, prefix: str = "jarvis_") -> None:
        self._d = docs
        self._providers = f"{prefix}vitals_providers"
        self._status = f"{prefix}vitals_status"

    @staticmethod
    def _name(uid: str, pid: str) -> str:
        if not owner_ok(uid):
            raise ValueError("bad owner id")
        return f"{uid}__{pid}"

    async def list_manual(self, uid: str) -> list[Provider]:
        if not owner_ok(uid):
            raise ValueError("bad owner id")
        try:
            rows = await self._d.query(
                Query(self._providers, where=("user_id", uid), order_by="label", limit=LIST_LIMIT)
            )
        except Exception as exc:  # noqa: BLE001 - storage trouble: plain words
            log.warning("vitals unreadable", extra={"reason": type(exc).__name__})
            raise VitalsUnavailable(UNAVAILABLE) from None
        out: list[Provider] = []
        for _id, doc in rows:
            try:
                out.append(
                    Provider.model_validate({k: v for k, v in doc.items() if k != "user_id"})
                )
            except ValidationError:
                log.warning("vitals record skipped: unreadable")
        return out

    async def put(self, uid: str, p: Provider) -> None:
        if p.source != "manual":
            raise ValueError("only manual records are stored")
        path = f"{self._providers}/{self._name(uid, p.id)}"
        existing = await self.list_manual(uid)
        if all(e.id != p.id for e in existing) and len(existing) >= MAX_MANUAL:
            raise VitalsFull(FULL)
        await self._write([Set(path, {**p.fields(), "user_id": uid})])

    async def delete(self, uid: str, pid: str) -> bool:
        path = f"{self._providers}/{self._name(uid, pid)}"
        try:
            existed = await self._d.get(path) is not None
        except Exception as exc:  # noqa: BLE001
            log.warning("vitals unreadable", extra={"reason": type(exc).__name__})
            raise VitalsUnavailable(UNAVAILABLE) from None
        await self._write([Delete(path), Delete(f"{self._status}/{self._name(uid, pid)}")])
        return existed

    async def last_status(self, uid: str, pid: str) -> Status | None:
        try:
            doc = await self._d.get(f"{self._status}/{self._name(uid, pid)}")
        except Exception as exc:  # noqa: BLE001
            log.warning("vitals status unreadable", extra={"reason": type(exc).__name__})
            raise VitalsUnavailable(UNAVAILABLE) from None
        s: Any = doc.get("status") if doc else None
        return s if isinstance(s, str) and s in RANK else None  # type: ignore[return-value]

    async def set_status(self, uid: str, pid: str, status: Status, at: datetime) -> None:
        doc = {"user_id": uid, "status": status, "at": at.isoformat()}
        await self._write([Set(f"{self._status}/{self._name(uid, pid)}", doc)])

    async def _write(self, ops: list[Any]) -> None:
        try:
            await self._d.write(ops)
        except Exception as exc:  # noqa: BLE001
            log.warning("vitals write failed", extra={"reason": type(exc).__name__})
            raise VitalsUnavailable(UNAVAILABLE) from None


__all__ = ["VitalsFull", "VitalsStore", "VitalsUnavailable"]
