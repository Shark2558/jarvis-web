# src/jarvis/offline/mode.py
"""The owner's AI on / no-AI switch (R4 D7, D-D3).

The switch exists to guarantee "no model spend", so it is persisted: `<prefix>settings/<uid>`
holds `{brain_mode, set_by, updated_at}` and survives a restart. It is read per turn (cached for
`CACHE_S` seconds) and every flip appends an audit entry. A document that cannot be read, or holds
an unknown value, reads as `none` (fail closed: no model is called when we cannot tell).

Without a document store (CLI, tests) the deployment `Settings.brain_mode` is the mode, read live.
With a store, `current` is FAIL-CLOSED (R4 I2 F1): until an owner has been read it is `none`, never
the env default, and it is `none` while ANY loaded owner is `none`. The cache is per owner.
`current` is synchronous because `ModelRouter` asks it on every call; `load` / `load_known`
refresh it (the router, background jobs and the lifespan all call them).
"""

from __future__ import annotations

import time
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Literal

from jarvis.config import Settings
from jarvis.core.guardrails import ActionRisk
from jarvis.logging import get_logger
from jarvis.storage.docs import Docs, DocTx
from jarvis.tools.audit import AuditTrail

log = get_logger(__name__)

Mode = Literal["ai", "none"]
CACHE_S = 5.0
AUDIT_AGENT = "settings"
AUDIT_TOOL = "brain_mode_set"
_MODES: tuple[Mode, ...] = ("ai", "none")


class BrainMode:
    def __init__(
        self,
        settings: Settings,
        docs: Docs | None = None,
        *,
        audit: AuditTrail | None = None,
        prefix: str = "jarvis_",
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._s = settings
        self._docs = docs
        self._audit = audit
        self._prefix = prefix
        self._clock = clock
        self._cache: dict[str, tuple[Mode, float]] = {}  # uid -> (value, read_at)

    @property
    def current(self) -> Mode:
        """The mode as last read. Without a store: the setting. With one: `none` until an owner
        has been read, and `none` while any read owner is `none` (fail closed)."""
        if self._docs is None:
            return self._s.brain_mode
        if not self._cache or any(v == "none" for v, _ in self._cache.values()):
            return "none"
        return "ai"

    @property
    def state(self) -> str:
        """`current`, or "unloaded" while a store exists and no owner has been read (for logs)."""
        return "unloaded" if self._docs is not None and not self._cache else self.current

    def _path(self, uid: str) -> str:
        return f"{self._prefix}settings/{uid}"

    async def load(self, uid: str) -> Mode:
        """Refresh from the store when the cached read is older than `CACHE_S`."""
        if self._docs is None:
            return self._s.brain_mode
        hit = self._cache.get(uid)
        if hit is not None and self._clock() - hit[1] < CACHE_S:
            return hit[0]
        try:
            raw = await self._docs.get(self._path(uid))
        except Exception as exc:  # noqa: BLE001 — fail closed: cannot tell, so no model
            log.error("brain mode unreadable; no-AI", extra={"reason": type(exc).__name__})
            return self._remember(uid, "none")
        if raw is None:
            return self._remember(uid, self._s.brain_mode)
        value = raw.get("brain_mode")
        if value not in _MODES:
            log.error("brain mode document invalid; no-AI")
            return self._remember(uid, "none")
        return self._remember(uid, value)

    async def load_known(self, *, force: bool = False) -> None:
        """Refresh every owner read so far (cached `CACHE_S`; `force` skips the cache)."""
        for uid in tuple(self._cache):
            if force:
                self._cache.pop(uid, None)
                self._cache[uid] = ("none", float("-inf"))  # closed while the re-read runs
            await self.load(uid)

    def _remember(self, uid: str, value: Mode) -> Mode:
        self._cache[uid] = (value, self._clock())
        return value

    async def set(self, uid: str, mode: Mode, *, by: str) -> Mode:
        """Persist the switch (when there is a store), apply it now, and audit the flip."""
        if mode not in _MODES:
            raise ValueError("mode must be 'ai' or 'none'")
        if self._docs is None:
            self._s.brain_mode = mode
        else:
            doc = {"brain_mode": mode, "set_by": by, "updated_at": datetime.now(UTC).isoformat()}

            async def work(tx: DocTx) -> None:
                tx.set(self._path(uid), doc)

            await self._docs.transaction(work)
            self._remember(uid, mode)
        if self._audit is not None:
            await self._audit.append(
                agent=AUDIT_AGENT,
                tool=AUDIT_TOOL,
                risk=ActionRisk.REVERSIBLE,
                outcome=mode,
                args={"mode": mode},
                detail=f"set by {by}",
            )
        return mode


__all__ = ["CACHE_S", "BrainMode", "Mode"]
