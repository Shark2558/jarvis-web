# src/jarvis/buildbook/seal_notices.py
"""What the sealer tells and records (R6 D7; builder B; L8 notify, cross-cutting audit), kept out
of sealer.py. ONE `book_sealed` per release and ONE `book_seal_failed` per release and cause:
each is CLAIMED in the sealer's document (`seal_state.SealState`) before it goes and given back
when it could not go, so two runs at once, a restart, a rollback or a traffic split tell once, and
a notice that failed is sent by the next run. The `book_seal` audit line carries ids and MB only.
The words are `seal_words`'; nothing here holds book text, an address or a key.
"""

from __future__ import annotations

from typing import Any, Literal, Protocol

from jarvis.buildbook.model import MIB, Release
from jarvis.buildbook.ports import BookError
from jarvis.buildbook.seal_state import FAILED_KEPT, TOLD_KEPT, SealState, ids_in
from jarvis.buildbook.seal_words import FAILED, SEALED, kept_words
from jarvis.core.guardrails import ActionRisk
from jarvis.logging import get_logger
from jarvis.notify.ports import Notifier, Signal

log = get_logger(__name__)

Kind = Literal["book_sealed", "book_seal_failed"]


class Audit(Protocol):
    """The gateway's audit chain (`tools.audit.AuditTrail`), seen through what this file uses."""

    async def append(
        self,
        *,
        agent: str,
        tool: str,
        risk: ActionRisk,
        outcome: str,
        args: dict[str, Any],
        detail: str = "",
    ) -> object: ...


class SealNotices:
    def __init__(
        self,
        state: SealState,
        *,
        notifier: Notifier | None,
        audit: Audit | None,
        honorific: str,
    ) -> None:
        self._st = state
        self._notifier = notifier
        self._audit = audit
        self._h = honorific
        self._told: set[tuple[str, str]] = set()  # this process already knows these were told

    def words(self, template: str, release: Release | None = None, **kw: str) -> str:
        if release is not None:
            kw = {"label": release.label, "id": release.id, **kw}
        return template.format(h=self._h, **kw)

    async def _send(self, uid: str, kind: Kind, text: str) -> bool:
        if self._notifier is None:
            return True  # nobody to tell: count it as told
        try:
            await self._notifier.notify(uid, Signal(source="system", kind=kind), text)
        except Exception as exc:  # noqa: BLE001 - the next run tries again
            log.error("book notice not sent", extra={"kind": kind, "error": type(exc).__name__})
            return False
        return True

    async def fail_once(self, uid: str, key: str, text: str) -> None:
        """ONE `book_seal_failed` per key: claimed first, given back if it could not go."""
        if not await self._st.claim(uid, "failed", key, keep=FAILED_KEPT):
            return
        if not await self._send(uid, "book_seal_failed", text):
            await self._st.unclaim(uid, "failed", key)

    async def fail_quietly(self, uid: str, release: Release | None) -> None:
        """A run stopped by something unforeseen: told once for this release, best effort."""
        if release is None or not release.ok:
            return
        try:
            await self.fail_once(uid, release.id, self.words(FAILED, release))
        except Exception as exc:  # noqa: BLE001 - the state store is down too: next run
            log.warning("book failure notice deferred", extra={"error": type(exc).__name__})

    async def tell(self, uid: str, release: Release, kept: int) -> None:
        """ONE `book_sealed` per release: claimed first, given back if it could not go."""
        try:
            claimed = await self._st.claim(uid, "told", release.id, keep=TOLD_KEPT)
        except BookError:
            claimed = True  # can't record it: tell anyway (at least once beats never)
        if claimed and not await self._send(
            uid, "book_sealed", self.words(SEALED, release, kept=kept_words(kept))
        ):
            await self._st.unclaim(uid, "told", release.id)
            return
        self._told.add((uid, release.id))

    async def tell_if_untold(self, uid: str, release: Release, kept: int) -> None:
        if (uid, release.id) in self._told:
            return
        if release.id in ids_in(await self._st.read(uid), "told"):
            self._told.add((uid, release.id))
            return
        await self.tell(uid, release, kept)

    async def audit_seal(self, release: Release, removed: tuple[str, ...], size: int) -> None:
        if self._audit is None:
            return
        args = {"release": release.id, "label": release.label, "removed": list(removed)}
        try:
            await self._audit.append(
                agent="book",
                tool="book_seal",
                risk=ActionRisk.REVERSIBLE,
                outcome="executed",
                args={**args, "mb": round(size / MIB, 1)},
                detail="",
            )
        except Exception as exc:  # noqa: BLE001 - it already happened
            log.error("AUDIT WRITE FAILED for a book seal", extra={"error": type(exc).__name__})


__all__ = ["Audit", "SealNotices"]
