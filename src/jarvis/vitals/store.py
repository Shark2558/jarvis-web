# src/jarvis/vitals/store.py
"""Vitals on the `Docs` port (R4 D2, D4; R5.1 D2: equality queries only, so no composite index).

    jarvis_vitals_providers/{name}   the manual record (+ user_id); listed by owner, sorted here
    jarvis_vitals_status/{name}      {user_id, status, at}: last status, for cross-line alerts

`name` is a hash of (uid, id) joined by a separator that neither may contain, so two different
(uid, id) pairs can never share a document. Only `manual` records are stored; `auto` ones are
computed from the meters. Metadata only: no key value is ever stored here. Errors carry plain
words, never the cause's text (the cause stays chained for logs).
"""

from __future__ import annotations

import hashlib
import re
from datetime import datetime
from typing import Any

from pydantic import ValidationError

from jarvis.logging import get_logger
from jarvis.storage.docs import Delete, Docs, DocTx, Query, Set
from jarvis.undo.store import owner_ok
from jarvis.vitals.models import ID_PATTERN, MAX_MANUAL, RANK, Provider, Status

log = get_logger(__name__)

UNAVAILABLE = "JARVIS couldn't open the Vitals list just now. Try again in a minute."
FULL = f"You are tracking the most keys allowed ({MAX_MANUAL}). Remove one first."
TAKEN = "That name is taken."
BAD_ID = "That isn't a valid key id."
LIST_LIMIT = MAX_MANUAL + 1
SEP = "\x1f"  # in neither a valid owner id nor a valid key id
NAME_LEN = 40


class VitalsUnavailable(RuntimeError):
    """Storage trouble (plain words)."""


class VitalsExists(RuntimeError):
    """A create-only write found the id already taken (plain words)."""


class VitalsFull(RuntimeError):
    """The per-owner record cap is reached (plain words)."""


def valid_id(pid: str) -> bool:
    return bool(re.fullmatch(ID_PATTERN, pid))


class VitalsStore:
    def __init__(self, docs: Docs, *, prefix: str = "jarvis_") -> None:
        self._d = docs
        self._providers = f"{prefix}vitals_providers"
        self._status = f"{prefix}vitals_status"

    @staticmethod
    def _name(uid: str, pid: str) -> str:
        if not owner_ok(uid):
            raise ValueError("bad owner id")
        if not valid_id(pid):
            raise ValueError(BAD_ID)
        return hashlib.sha256(f"{uid}{SEP}{pid}".encode()).hexdigest()[:NAME_LEN]

    async def _rows(self, uid: str) -> list[tuple[str, dict[str, Any]]]:
        if not owner_ok(uid):
            raise ValueError("bad owner id")
        try:  # equality only (R5.1 D2): no composite index; sorted in Python by `list_manual`
            rows = await self._d.query(
                Query(self._providers, where=("user_id", uid), limit=LIST_LIMIT)
            )
        except Exception as exc:
            self._trouble("vitals unreadable", exc)
            raise VitalsUnavailable(UNAVAILABLE) from exc
        return list(rows)

    @staticmethod
    def _trouble(what: str, exc: Exception) -> None:
        log.warning(what, extra={"reason": type(exc).__name__})
        log.debug(what, exc_info=True)

    async def list_manual(self, uid: str) -> list[Provider]:
        out: list[Provider] = []
        for _id, doc in await self._rows(uid):
            try:
                out.append(
                    Provider.model_validate({k: v for k, v in doc.items() if k != "user_id"})
                )
            except ValidationError:
                log.warning("vitals record skipped: unreadable")
        return sorted(out, key=lambda p: (p.label.casefold(), p.id))

    async def put(self, uid: str, p: Provider, *, create: bool = False) -> None:
        """Upsert; with `create` an existing id is refused (`VitalsExists`), never overwritten."""
        if p.source != "manual":
            raise ValueError("only manual records are stored")
        path = f"{self._providers}/{self._name(uid, p.id)}"
        rows = await self._rows(uid)  # raw rows: unreadable ones count toward the cap
        if all(doc.get("id") != p.id for _i, doc in rows) and len(rows) >= MAX_MANUAL:
            raise VitalsFull(FULL)
        doc = {**p.fields(), "user_id": uid}
        if not create:
            await self._write([Set(path, doc)])
            return

        async def first(tx: DocTx) -> bool:
            if await tx.get(path) is not None:
                return False
            tx.set(path, doc)
            return True

        try:
            made = await self._d.transaction(first)
        except Exception as exc:
            self._trouble("vitals write failed", exc)
            raise VitalsUnavailable(UNAVAILABLE) from exc
        if not made:
            raise VitalsExists(TAKEN)

    async def delete(self, uid: str, pid: str, *, status: bool = True) -> bool:
        """Remove a manual record. `status=False` keeps the shared last-status record (a manual
        record that shadows a built-in item must not wipe the built-in item's alert state)."""
        path = f"{self._providers}/{self._name(uid, pid)}"
        try:
            existed = await self._d.get(path) is not None
        except Exception as exc:
            self._trouble("vitals unreadable", exc)
            raise VitalsUnavailable(UNAVAILABLE) from exc
        ops = [Delete(path)]
        if status:
            ops.append(Delete(f"{self._status}/{self._name(uid, pid)}"))
        await self._write(ops)
        return existed

    async def last_status(self, uid: str, pid: str) -> Status | None:
        try:
            doc = await self._d.get(f"{self._status}/{self._name(uid, pid)}")
        except Exception as exc:
            self._trouble("vitals status unreadable", exc)
            raise VitalsUnavailable(UNAVAILABLE) from exc
        s: Any = doc.get("status") if doc else None
        return s if isinstance(s, str) and s in RANK else None  # type: ignore[return-value]

    async def set_status(self, uid: str, pid: str, status: Status, at: datetime) -> None:
        doc = {"user_id": uid, "status": status, "at": at.isoformat()}
        await self._write([Set(f"{self._status}/{self._name(uid, pid)}", doc)])

    async def _write(self, ops: list[Any]) -> None:
        try:
            await self._d.write(ops)
        except Exception as exc:
            self._trouble("vitals write failed", exc)
            raise VitalsUnavailable(UNAVAILABLE) from exc


__all__ = ["VitalsExists", "VitalsFull", "VitalsStore", "VitalsUnavailable", "valid_id"]
