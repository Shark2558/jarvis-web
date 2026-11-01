# src/jarvis/permissions/store.py
"""The owner's permission choices (slice 10 D; Layer 7 via the `Docs` port).

    {prefix}permissions/{uid}   user_id, groups {group id: allow|ask|deny}, require_passkey, rev,
                                updated_at

The gateway reads it on every tool call (`rules_for`), so reads go through an in-process cache
(15 s; one instance runs) that a change refreshes at once — an owner's "Never" applies to the very
next call. When storage can't be read the last value seen is used, whatever its age; with none,
the error propagates and the gateway fails closed (nothing runs). Writes are transactions on the
stored value with `rev` bumped, so two tabs can't lose each other's change. A stored value that is
not valid (hand-edited, a group renamed) reads as the default, field by field.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from jarvis.logging import get_logger
from jarvis.permissions.groups import rules_for, stored_choices
from jarvis.storage.docs import Docs, DocTx
from jarvis.storage.sessions import safe_id
from jarvis.tools.policy import Effect, PolicyRule

log = get_logger(__name__)
CACHE_S = 15.0


class OwnerPermissions(BaseModel):
    model_config = ConfigDict(frozen=True)

    choices: dict[str, Effect] = Field(default_factory=dict)
    require_passkey: bool = False
    rev: int = 0
    updated_at: str | None = None


def decode(doc: Any) -> OwnerPermissions:
    if not isinstance(doc, dict):
        return OwnerPermissions()
    rev = doc.get("rev")
    at = doc.get("updated_at")
    return OwnerPermissions(
        choices=stored_choices(doc.get("groups")),
        require_passkey=doc.get("require_passkey") is True,
        rev=rev if isinstance(rev, int) and not isinstance(rev, bool) and rev >= 0 else 0,
        updated_at=at if isinstance(at, str) else None,
    )


class PermissionsStore:
    def __init__(
        self,
        docs: Docs,
        *,
        prefix: str = "jarvis_",
        clock: Callable[[], float] = time.monotonic,
        cache_s: float = CACHE_S,
    ) -> None:
        self._d = docs
        self._col = f"{prefix}permissions"
        self._clock = clock
        self._cache_s = cache_s
        self._cache: dict[str, tuple[float, OwnerPermissions]] = {}

    def _path(self, uid: str) -> str:
        if not safe_id(uid):
            raise ValueError("invalid user id")
        return f"{self._col}/{uid}"

    async def get(self, uid: str) -> OwnerPermissions:
        path = self._path(uid)
        hit = self._cache.get(uid)
        if hit is not None and self._clock() - hit[0] < self._cache_s:
            return hit[1]
        try:
            value = decode(await self._d.get(path))
        except Exception as exc:
            if hit is None:
                raise
            log.warning(
                "permissions unreadable; using the last value seen",
                extra={"error": type(exc).__name__},
            )
            return hit[1]
        self._cache[uid] = (self._clock(), value)
        return value

    async def rules_for(self, uid: str) -> list[PolicyRule]:
        """The `OwnerRules` port the gateway calls on every tool call."""
        return rules_for((await self.get(uid)).choices)

    async def update(
        self, uid: str, change: Callable[[OwnerPermissions], OwnerPermissions]
    ) -> OwnerPermissions:
        """Apply `change` to the stored value in a transaction (it may raise to refuse)."""
        path = self._path(uid)
        at = datetime.now(UTC).isoformat()

        async def fn(tx: DocTx) -> OwnerPermissions:
            cur = decode(await tx.get(path))
            new = change(cur).model_copy(update={"rev": cur.rev + 1, "updated_at": at})
            tx.set(
                path,
                {
                    "user_id": uid,
                    "groups": {k: v.value for k, v in new.choices.items()},
                    "require_passkey": new.require_passkey,
                    "rev": new.rev,
                    "updated_at": at,
                },
            )
            return new

        new = await self._d.transaction(fn)
        self._cache[uid] = (self._clock(), new)
        return new


__all__ = ["CACHE_S", "OwnerPermissions", "PermissionsStore", "decode"]
