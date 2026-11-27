# src/jarvis/calls/settings.py
"""The owner's call settings (R18; Layer 7 via the `Docs` port), with the brief's defaults.

    {prefix}call_settings/{uid}   CallSettings fields + updated_at

`defaults(s)` is `CallSettings` with the deployment's caps (`JARVIS_CALLS_*`). A stored field that
is not valid (hand-edited, a cap above its ceiling) reads as its default, field by field, so one bad
value never switches answering on or lifts a cap. `apply` checks a change first (unknown field or a
bad value: `CallSettingsRejected`, nothing written); `CallSettingsStore.save` applies it in one
transaction on the stored value, so two tabs can't lose each other's change.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from pydantic import ValidationError

from jarvis.calls.models import CallSettings
from jarvis.storage.docs import Delete, Docs, DocTx
from jarvis.storage.sessions import safe_id

if TYPE_CHECKING:
    from jarvis.config import Settings

SETTINGS_COLL = "call_settings"
CHANGEABLE = frozenset(CallSettings.model_fields) - {"updated_at"}


class CallSettingsRejected(ValueError):
    """A change that is not valid; the words name the setting, never echo the value."""


def owner_key(uid: str) -> str:
    """The owner's id as a document id (never a path: a slash or `__x__` is refused)."""
    if not safe_id(uid):
        raise ValueError("not an owner id")
    return uid


def defaults(s: Settings | None = None) -> CallSettings:
    if s is None:
        return CallSettings()
    return CallSettings(
        month_cap_inr=s.calls_month_cap_inr,
        call_cap_inr=s.calls_call_cap_inr,
        call_max_minutes=s.calls_max_minutes,
        retention_days=s.calls_retention_days,
    )


def read(raw: Mapping[str, Any] | None, base: CallSettings) -> CallSettings:
    """The stored settings over `base`, field by field: an invalid field reads as its default."""
    if not raw:
        return base
    out = base
    for name in CallSettings.model_fields:
        if name not in raw:
            continue
        try:
            out = CallSettings.model_validate(out.model_dump() | {name: raw[name]})
        except ValidationError:
            continue
    return out


def apply(current: CallSettings, changes: Mapping[str, Any]) -> CallSettings:
    unknown = sorted(k for k in changes if k not in CHANGEABLE)
    if unknown:
        raise CallSettingsRejected(f"Unknown call setting: {', '.join(unknown)[:120]}")
    try:
        return CallSettings.model_validate(current.model_dump() | dict(changes))
    except ValidationError as exc:
        names = sorted({str(e["loc"][0]) for e in exc.errors() if e["loc"]})
        raise CallSettingsRejected(f"Check {', '.join(names) or 'the call settings'}.") from None


class CallSettingsStore:
    def __init__(
        self,
        docs: Docs,
        *,
        prefix: str = "jarvis_",
        base: CallSettings | None = None,
        now: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self.docs = docs
        self._coll = f"{prefix}{SETTINGS_COLL}"
        self.base = base or CallSettings()
        self._now = now

    def _path(self, uid: str) -> str:
        return f"{self._coll}/{owner_key(uid)}"

    async def get(self, uid: str) -> CallSettings:
        return read(await self.docs.get(self._path(uid)), self.base)

    async def saved(self, uid: str) -> bool:
        """Has he saved any setting (else the defaults apply)?"""
        return await self.docs.get(self._path(uid)) is not None

    async def reset(self, uid: str) -> bool:
        """The Privacy panel's delete: his settings go, the defaults apply again."""
        if not await self.saved(uid):
            return False
        await self.docs.write([Delete(self._path(uid))])
        return True

    async def save(self, uid: str, changes: Mapping[str, Any]) -> CallSettings:
        async def work(tx: DocTx) -> CallSettings:
            new = apply(read(await tx.get(self._path(uid)), self.base), changes)
            new = new.model_copy(update={"updated_at": self._now()})
            tx.set(self._path(uid), new.model_dump(mode="json"))
            return new

        return await self.docs.transaction(work)


__all__ = [
    "CHANGEABLE",
    "SETTINGS_COLL",
    "CallSettingsRejected",
    "CallSettingsStore",
    "apply",
    "defaults",
    "owner_key",
    "read",
]
