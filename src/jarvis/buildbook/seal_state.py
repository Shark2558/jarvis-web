# src/jarvis/buildbook/seal_state.py
"""The sealer's own document (R6 D7; builder B; Layer 7):

    {prefix}book_lease/{uid}   {holder, until, told, failed, held}

`holder`/`until`: the 120-second lease one sealing run takes in a transaction, so two instances
(or two runs in one) never seal at once; an expired or unreadable lease is free. `told`: the
release whose `book_sealed` notice went. `failed`: the failure notices already sent (keys such as
`<release id>`, `<release id>:personal`, `<release id>:read`, `index`; the newest 8). `held`: the
release Privacy -> Delete asked not to seal again. Ids only: no content, ever. Storage failures are
a `BookError` with fixed words (logged by class name).
"""

from __future__ import annotations

import datetime as dt
import secrets
from collections.abc import Callable
from typing import Any, TypeVar

from jarvis.buildbook.ports import BookError
from jarvis.logging import get_logger
from jarvis.storage.docs import Docs, DocTx

log = get_logger(__name__)
T = TypeVar("T")
Doc = dict[str, Any]

LEASE_S = 120
FAILED_KEPT = 8


def _live(until: object, now: dt.datetime) -> bool:
    if not isinstance(until, str):
        return False
    try:
        return dt.datetime.fromisoformat(until) > now
    except ValueError:
        return False


class SealState:
    def __init__(self, docs: Docs, *, prefix: str, clock: Callable[[], dt.datetime]) -> None:
        self._d = docs
        self._col = f"{prefix}book_lease"
        self._clock = clock
        self._me = secrets.token_hex(8)

    def _path(self, uid: str) -> str:
        return f"{self._col}/{uid}"

    async def read(self, uid: str) -> Doc:
        try:
            return dict(await self._d.get(self._path(uid)) or {})
        except Exception as exc:  # noqa: BLE001
            log.error("book sealer state unreadable", extra={"error": type(exc).__name__})
            raise BookError("The build book's state can't be read right now.") from None

    async def update(self, uid: str, fn: Callable[[Doc], tuple[Doc | None, T]]) -> T:
        """Read-modify-write in a transaction; `fn` is pure: (the new doc or None, a result)."""

        async def run(tx: DocTx) -> T:
            new, result = fn(dict(await tx.get(self._path(uid)) or {}))
            if new is not None:
                tx.set(self._path(uid), new)
            return result

        try:
            return await self._d.transaction(run)
        except Exception as exc:  # noqa: BLE001
            log.error("book sealer state not saved", extra={"error": type(exc).__name__})
            raise BookError("The build book's state can't be saved right now.") from None

    async def lease(self, uid: str) -> str | None:
        """The lease for one run (its holder id), or None while another run holds it."""
        now = self._clock()
        holder = f"{self._me}:{secrets.token_hex(4)}"

        def take(st: Doc) -> tuple[Doc | None, str | None]:
            if st.get("holder") and _live(st.get("until"), now):
                return None, None
            until = (now + dt.timedelta(seconds=LEASE_S)).isoformat()
            return {**st, "holder": holder, "until": until}, holder

        return await self.update(uid, take)

    async def unlease(self, uid: str, holder: str) -> None:
        """Give the lease back (only our own); if that fails it simply expires."""

        def give(st: Doc) -> tuple[Doc | None, None]:
            if st.get("holder") != holder:
                return None, None
            return {**st, "holder": None, "until": None}, None

        try:
            await self.update(uid, give)
        except BookError:
            log.warning("book lease left to expire")

    async def mark_failed(self, uid: str, key: str) -> None:
        def mark(st: Doc) -> tuple[Doc, None]:
            fails = [f for f in st.get("failed", []) if isinstance(f, str) and f != key]
            return {**st, "failed": [*fails, key][-FAILED_KEPT:]}, None

        await self.update(uid, mark)

    async def set(self, uid: str, field: str, value: str) -> None:
        """`held` = a release id."""
        await self.update(uid, lambda st: ({**st, field: value}, None))

    async def claim(self, uid: str, field: str, value: str) -> bool:
        """Set `field` = `value` unless it already is (True: this caller claimed it). `told` is
        claimed BEFORE the notice goes, so two runs (a lease that ran out mid-seal) tell once."""

        def take(st: Doc) -> tuple[Doc | None, bool]:
            return (None, False) if st.get(field) == value else ({**st, field: value}, True)

        return await self.update(uid, take)

    async def unclaim(self, uid: str, field: str, value: str) -> None:
        """Give a claim back (the notice could not go: the next run tries again)."""

        def give(st: Doc) -> tuple[Doc | None, None]:
            return (None, None) if st.get(field) != value else ({**st, field: None}, None)

        try:
            await self.update(uid, give)
        except BookError:
            log.warning("book notice claim left in place")


__all__ = ["FAILED_KEPT", "LEASE_S", "SealState"]
