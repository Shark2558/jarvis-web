# src/jarvis/sos/after.py
"""What follows an SOS send (docs/plans/r7-mobile.md D19), split out of `service.py` with no change
in what it does: the log entry, the audit line and the owner's notice `sos_sent`. They run side by
side, apart from the answer, and are waited for at most `AFTER_S` seconds, so a slow log, audit or
notifier never holds "sent" (and `told` / `logged` say false when it was not confirmed). A notifier,
a log or an audit that fails never fails the send. Counts and kinds only: never a name, never a
place.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import Any

from jarvis.alerts import AlertKind
from jarvis.core.guardrails import ActionRisk
from jarvis.logging import get_logger
from jarvis.notify.ports import Delivery, Notifier, Signal
from jarvis.sos.store import Entry, SosStore, SosUnavailable
from jarvis.tools.audit import AuditTrail

log = get_logger(__name__)

AFTER_S = 5.0  # the log, audit and owner's notice are waited for this long, never longer
AGENT = "sos"


class AfterSend:
    def __init__(
        self,
        store: SosStore,
        notifier: Callable[[], Notifier | None] | None,
        audit: AuditTrail | None,
    ) -> None:
        self._store = store
        self._notifier = notifier
        self._audit = audit
        self._bg: set[asyncio.Task[Any]] = set()

    def _background(self, coro: Awaitable[Any]) -> asyncio.Task[Any]:
        task = asyncio.ensure_future(coro)
        self._bg.add(task)
        task.add_done_callback(self._bg.discard)
        return task

    async def run(
        self,
        uid: str,
        kind: str,
        entry: Entry,
        outcome: str,
        args: dict[str, Any],
        detail: str,
        notice: str,
    ) -> tuple[bool, bool]:
        """The log, the audit line and the owner's notice, side by side, waited for `AFTER_S` at
        most. What did not finish is left running and reported as not done (never as done)."""
        log_t = self._background(self._log_entry(uid, entry))
        audit_t = self._background(self.note_audit(uid, f"sos_{kind}", outcome, args, detail))
        tell_t = self._background(self.tell(uid, "sos_sent", notice))
        done, _ = await asyncio.wait({log_t, audit_t, tell_t}, timeout=AFTER_S)
        if len(done) < 3:
            log.warning("an SOS side channel did not finish in time", extra={"kind": kind})
        logged = log_t in done and bool(log_t.result())
        told = tell_t in done and bool(tell_t.result())
        return logged, told

    async def _log_entry(self, uid: str, entry: Entry) -> bool:
        try:
            await self._store.log(uid, entry)
        except (SosUnavailable, ValueError) as exc:
            log.error("an SOS was not logged", extra={"error": type(exc).__name__})
            return False
        except Exception as exc:  # noqa: BLE001 - the send already happened
            log.error("an SOS was not logged", extra={"error": type(exc).__name__})
            return False
        return True

    async def tell(self, uid: str, kind: AlertKind, words: str) -> bool:
        """True only when the notifier really delivered (rang or was silent, to Telegram or a
        browser); a held or dropped notice, or one that reached no device, is not "told"."""
        notifier = self._notifier() if self._notifier is not None else None
        if notifier is None:
            log.warning("no notifier: the owner was not told", extra={"kind": kind})
            return False
        try:
            got = await notifier.notify(uid, Signal(source="system", kind=kind), words)
        except Exception as exc:  # noqa: BLE001 - the send already happened; say it was not told
            log.error(
                "the owner's SOS notice failed", extra={"kind": kind, "error": type(exc).__name__}
            )
            return False
        told = (
            isinstance(got, Delivery)
            and got.action in ("ring", "silent")
            and (got.telegram or got.push > 0)
        )
        if not told:
            log.warning("the owner's SOS notice was not delivered", extra={"kind": kind})
        return told

    async def note_audit(
        self, uid: str, tool: str, outcome: str, args: dict[str, Any], detail: str = ""
    ) -> None:
        if self._audit is None:
            return
        try:
            await self._audit.append(
                agent=AGENT,
                tool=tool,
                risk=ActionRisk.IRREVERSIBLE,
                outcome=outcome,
                args={**args, "owner": uid},
                detail=detail,
            )
        except Exception as exc:  # noqa: BLE001 - never stops an SOS; logged loudly
            log.error("an SOS audit line was not written", extra={"error": type(exc).__name__})
