# src/jarvis/buildbook/sealer.py
"""Seal the release this server runs, once (R6 D7; builder B; L7 vault, L8 notify).

`BookSealer.ensure(uid)` for the primary owner: the current release (`BookSource.current()`) not
yet in the sealed index -> take the lease `{prefix}book_lease/{uid}` (120 s, a transaction) ->
look again under the lease -> refuse a book that names an owner e-mail or its local part (D3) ->
make room under `book_max_total_mb` (the oldest goes first when needed) -> seal -> prune to 3 ->
audit `book_seal` (ids and MB only) -> ONE `book_sealed` notice. Anything that stops it ->
`book_seal_failed` once per release and cause, never repeated (not even after a restart); the
next run simply tries again. It runs from the `book_seal` TickJob and inside `GET /v1/book`
(`ensure_bounded`: one shared run per owner, a request waits at most 20 s), NEVER at start-up: a
Cloud Run candidate that fails gets no traffic, so it never seals a release that didn't go live.

The lease document (`seal_state.SealState`) also remembers what was told and what Privacy held.
No content goes in it, nor in a log or a notice.
"""

from __future__ import annotations

import asyncio
import datetime as dt
import json
import re
import unicodedata
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Literal, Protocol

from jarvis.buildbook.model import KEEP, MIB, FileKind, Release
from jarvis.buildbook.ports import BookError, BookSource, BookUnavailable, BookVault, VaultTampered
from jarvis.buildbook.seal import KINDS
from jarvis.buildbook.seal_state import SealState
from jarvis.core.guardrails import ActionRisk
from jarvis.logging import get_logger
from jarvis.notify.ports import Notifier, Signal
from jarvis.storage.docs import Docs
from jarvis.ticks import FAILED_COUNT

log = get_logger(__name__)

BOUNDED_S = 20.0  # a request's wait (Cloud Run gives CPU only during a request)
JOB_BUDGET_S = 45.0
LOCAL_PART_MIN = 3  # a shorter local part is a common word, not a name
SEALED = (
    "{h}, the build book for {label} ({id}) is sealed in your vault with this release's code. "
    "{kept} kept."
)
UNBUILT = "{h}, the build book for {label} ({id}) could not be built at deploy, so it isn't sealed."
FAILED = "{h}, the build book for {label} ({id}) could not be sealed in your vault; I'll try again."
PERSONAL = (
    "{h}, the build book for {label} ({id}) holds your e-mail address, so I refused to seal it."
)
INDEX_TAMPERED = "{h}, your sealed build books failed their integrity check, so they stay closed."
READ_TAMPERED = (
    "{h}, the sealed build book for {label} ({id}) failed its integrity check, so it stays closed."
)
State = Literal["none", "unbuilt", "failed", "held", "busy", "sealing", "kept", "sealed"]


def _now() -> dt.datetime:
    return dt.datetime.now(dt.UTC)


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


@dataclass(frozen=True)
class SealOutcome:
    state: State
    release: str | None = None
    kept: int = 0
    removed: tuple[str, ...] = ()


def _marks(emails: Sequence[str]) -> tuple[str, ...]:
    out: list[str] = []
    for raw in emails:
        email = unicodedata.normalize("NFKC", raw).casefold().strip()
        local, at, _ = email.partition("@")
        if not at or not local:
            continue
        out.append(email)
        if len(local) >= LOCAL_PART_MIN:
            out.append(local)
    return tuple(out)


def holds_owner_email(book: bytes, owner_emails: Sequence[str]) -> bool:
    """D3's last check before sealing: does book.json name a configured owner address or its
    local part, as a whole word (NFKC, case-folded, JSON escapes undone)?"""
    marks = _marks(owner_emails)
    if not marks:
        return False
    try:
        text = json.dumps(json.loads(book), ensure_ascii=False)
    except ValueError:
        text = book.decode("utf-8", "replace")
    text = unicodedata.normalize("NFKC", text).casefold()
    return any(re.search(rf"(?<![\w.+-]){re.escape(m)}(?![\w-])", text) for m in marks)


def _kept_words(n: int) -> str:
    return f"{n} release" if n == 1 else f"{n} releases"


class BookSealer:
    def __init__(
        self,
        source: BookSource,
        vault: BookVault,
        docs: Docs,
        *,
        notifier: Notifier | None,
        audit: Audit | None,
        owner_emails: Sequence[str] = (),
        honorific: str = "Sir",
        limit_mb: int = 60,
        prefix: str = "jarvis_",
        clock: Callable[[], dt.datetime] = _now,
        keep: int = KEEP,
    ) -> None:
        self._source = source
        self._vault = vault
        self._notifier = notifier
        self._audit = audit
        self._emails = tuple(owner_emails)
        self._h = honorific
        self._limit = limit_mb * MIB
        self._st = SealState(docs, prefix=prefix, clock=clock)
        self._clock = clock
        self._keep = keep  # D5: fixed at 3; a parameter only so the seal eval's control can vary it
        self._told: set[tuple[str, str]] = set()
        self._inflight: dict[str, asyncio.Task[SealOutcome]] = {}

    # ---- notices and the audit -----------------------------------------------------------------

    def _words(self, template: str, release: Release | None = None, **kw: str) -> str:
        if release is not None:
            kw = {"label": release.label, "id": release.id, **kw}
        return template.format(h=self._h, **kw)

    async def _send(
        self, uid: str, kind: Literal["book_sealed", "book_seal_failed"], text: str
    ) -> bool:
        if self._notifier is None:
            return True  # nobody to tell: count it as told
        try:
            await self._notifier.notify(uid, Signal(source="system", kind=kind), text)
        except Exception as exc:  # noqa: BLE001 - the next run tries again
            log.error("book notice not sent", extra={"kind": kind, "error": type(exc).__name__})
            return False
        return True

    async def _fail_once(self, uid: str, key: str, text: str) -> None:
        if key in (await self._st.read(uid)).get("failed", []):
            return
        if await self._send(uid, "book_seal_failed", text):
            await self._st.mark_failed(uid, key)

    async def _tell(self, uid: str, release: Release, kept: int) -> None:
        """ONE `book_sealed` per release: claimed first, given back if it could not go."""
        try:
            claimed = await self._st.claim(uid, "told", release.id)
        except BookError:
            claimed = True  # can't record it: tell anyway (at least once beats never)
        if claimed and not await self._send(
            uid, "book_sealed", self._words(SEALED, release, kept=_kept_words(kept))
        ):
            await self._st.unclaim(uid, "told", release.id)
            return
        self._told.add((uid, release.id))

    async def _tell_if_untold(self, uid: str, release: Release, kept: int) -> None:
        if (uid, release.id) in self._told:
            return
        if (await self._st.read(uid)).get("told") == release.id:
            self._told.add((uid, release.id))
            return
        await self._tell(uid, release, kept)

    async def _audit_seal(self, release: Release, removed: tuple[str, ...], size: int) -> None:
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

    # ---- the run -------------------------------------------------------------------------------

    async def ensure(self, uid: str) -> SealOutcome:
        """Seal the current release for `uid` if it isn't yet. Never raises a BookError."""
        release = self._source.current()
        if release is None:
            return SealOutcome("none")
        try:
            if not release.ok:
                await self._fail_once(uid, release.id, self._words(UNBUILT, release))
                return SealOutcome("unbuilt", release.id)
            return await self._ensure_good(uid, release)
        except BookError as exc:
            log.error("book seal check failed", extra={"error": type(exc).__name__})
            return SealOutcome("failed", release.id)

    async def _ensure_good(self, uid: str, release: Release) -> SealOutcome:
        try:
            sealed = await self._vault.releases(uid)
        except VaultTampered:
            await self._fail_once(uid, "index", self._words(INDEX_TAMPERED))
            return SealOutcome("failed", release.id)
        if any(r.id == release.id for r in sealed):
            return await self._kept(uid, release, len(sealed))
        if (await self._st.read(uid)).get("held") == release.id:
            return SealOutcome("held", release.id)
        holder = await self._st.lease(uid)
        if holder is None:
            return SealOutcome("busy", release.id)
        try:
            return await self._seal_leased(uid, release)
        finally:
            await self._st.unlease(uid, holder)

    async def _kept(self, uid: str, release: Release, count: int) -> SealOutcome:
        removed = await self._prune(uid)  # also retries chunk deletes that failed before
        kept = count - len(removed)
        await self._tell_if_untold(uid, release, kept)
        return SealOutcome("kept", release.id, kept=kept, removed=removed)

    async def _prune(self, uid: str) -> tuple[str, ...]:
        try:
            return await self._vault.prune(uid, keep=self._keep)
        except BookError as exc:
            log.warning("book prune deferred", extra={"error": type(exc).__name__})
            return ()

    async def _seal_leased(self, uid: str, release: Release) -> SealOutcome:
        sealed = await self._vault.releases(uid)  # look again: another run may have sealed it
        if any(r.id == release.id for r in sealed):
            return await self._kept(uid, release, len(sealed))
        try:
            files: dict[FileKind, bytes] = {k: self._source.read(k) for k in KINDS}
        except BookUnavailable:
            await self._fail_once(uid, release.id, self._words(FAILED, release))
            return SealOutcome("failed", release.id)
        if holds_owner_email(files["book"], self._emails):
            log.error("book seal refused: the book names an owner address")
            await self._fail_once(uid, f"{release.id}:personal", self._words(PERSONAL, release))
            return SealOutcome("failed", release.id)
        removed = await self._store(uid, release, files)
        if removed is None:
            return SealOutcome("failed", release.id)
        kept = len(sealed) + 1 - len(removed)
        await self._audit_seal(release, removed, sum(len(b) for b in files.values()))
        await self._tell(uid, release, kept)
        return SealOutcome("sealed", release.id, kept=kept, removed=removed)

    async def _store(
        self, uid: str, release: Release, files: Mapping[FileKind, bytes]
    ) -> tuple[str, ...] | None:
        """Make room, seal, prune to 3: the release ids that went, or None when it failed."""
        try:
            early: tuple[str, ...] = ()
            incoming = sum(len(b) for b in files.values())
            if await self._vault.used_bytes(uid) + incoming > self._limit:
                early = await self._vault.prune(uid, keep=max(1, self._keep - 1))
            await self._vault.seal(uid, release, files, now=self._clock())
        except VaultTampered:
            await self._fail_once(uid, "index", self._words(INDEX_TAMPERED))
            return None
        except BookError as exc:
            log.error("book seal failed", extra={"error": type(exc).__name__})
            await self._fail_once(uid, release.id, self._words(FAILED, release))
            return None
        return early + await self._prune(uid)

    async def _guarded(self, uid: str) -> SealOutcome:
        try:
            return await self.ensure(uid)
        except Exception as exc:  # noqa: BLE001 - a run never takes a request or the tick down
            log.error("book seal run failed", extra={"error": type(exc).__name__})
            return SealOutcome("failed")

    async def ensure_bounded(self, uid: str, *, within_s: float = BOUNDED_S) -> SealOutcome:
        """`ensure` shared by every caller in this process, waited on at most `within_s`; past
        that the run goes on and the answer is "sealing" (ask again)."""
        task = self._inflight.get(uid)
        if task is None or task.done():
            task = asyncio.ensure_future(self._guarded(uid))
            self._inflight[uid] = task

            def forget(done: asyncio.Task[SealOutcome], uid: str = uid) -> None:
                if self._inflight.get(uid) is done:
                    del self._inflight[uid]

            task.add_done_callback(forget)
        try:
            return await asyncio.wait_for(asyncio.shield(task), within_s)
        except TimeoutError:
            return SealOutcome("sealing")

    # ---- Privacy and reads -----------------------------------------------------------------------

    async def hold(self, uid: str) -> str | None:
        """Privacy -> Delete: don't seal the current release again (the next one seals)."""
        release = self._source.current()
        if release is None or not release.ok:
            return None
        await self._st.set(uid, "held", release.id)
        return release.id

    async def report_tampered(self, uid: str, rid: str, label: str) -> None:
        """A sealed read failed its check (the routes): `book_seal_failed` once per release."""
        text = self._words(READ_TAMPERED, label=label, id=rid)
        try:
            await self._fail_once(uid, f"{rid}:read", text)
        except BookError:
            log.warning("book tamper notice deferred")


class BookSealJob:
    """D7's `book_seal` on the existing tick and R5.1's 5-minute watchdog: the PRIMARY owner only
    (`identity.primary_user_id`), whatever owners the tick passes."""

    name = "book_seal"
    budget_s = JOB_BUDGET_S

    def __init__(self, sealer: BookSealer, uid: str) -> None:
        self._sealer = sealer
        self._uid = uid

    async def run(self, owners: Sequence[str]) -> dict[str, int]:
        out = await self._sealer.ensure_bounded(self._uid, within_s=self.budget_s - 5)
        return {
            "sealed": int(out.state == "sealed"),
            "removed": len(out.removed),
            FAILED_COUNT: int(out.state == "failed"),
        }


__all__ = [
    "BOUNDED_S",
    "JOB_BUDGET_S",
    "Audit",
    "BookSealJob",
    "BookSealer",
    "SealOutcome",
    "holds_owner_email",
]
