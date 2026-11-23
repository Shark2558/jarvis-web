# src/jarvis/buildbook/writer/store.py
"""R6.3 D5-D7, D13 ("Data model"): the writer's documents (prefix `jarvis_`, flat ids, `owner`
and `updated_at` on each; ids, enums and numbers only outside a sealed blob):

    book_writer/{uid}               `model.WriterDoc`: the pick and its grants, the consents, the
                                    run, `update_ready`, the notice claims, the seconds a call
    book_write_lease/{uid}          `model.Lease`: one step at a time (two revisions in a rollout
                                    can't both write), held until the step's deadline + 30 s
    book_drafts/{uid}_{rid}_{page}  `model.Draft`: one page's draft, its text and template sealed
    book_trial/{uid}_{nn}           `model.TrialPage`: one trial page, never in a release

A blob is R6's envelope (`seal_index.BookCrypto.seal` under the release id and a fresh `bf_` file
id): `{"dek": <wrapped>, "c": [<chunks>]}`. An unreadable document refuses (`unavailable`), never
reads as empty; nothing here logs page text, a blob or a key.
"""

from __future__ import annotations

import datetime as dt
import json
import secrets
from collections.abc import Callable
from typing import Any, TypeVar

from pydantic import ValidationError

from jarvis.buildbook.seal_index import BookCrypto
from jarvis.buildbook.writer.model import (
    DRAFTS,
    KEEP_DAYS,
    LEASE,
    TRIAL,
    WRITER,
    Draft,
    Lease,
    TrialPage,
    WriterDoc,
)
from jarvis.buildbook.writer.texts import WriterRefused
from jarvis.keyring import Keyring
from jarvis.logging import get_logger
from jarvis.storage.docs import Delete, Docs, DocTx, Query

log = get_logger(__name__)
T = TypeVar("T")


class WriterStore:
    def __init__(
        self, docs: Docs, ring: Keyring, *, prefix: str, clock: Callable[[], dt.datetime]
    ) -> None:
        self.docs, self.prefix, self.clock = docs, prefix, clock
        self._c = BookCrypto(ring)
        self._me = secrets.token_hex(6)

    def path(self, col: str, doc_id: str) -> str:
        return f"{self.prefix}{col}/{doc_id}"

    # ---- book_writer/{uid} -------------------------------------------------------------------
    def _decode(self, uid: str, raw: dict[str, Any] | None) -> WriterDoc:
        if raw is None:
            return WriterDoc(owner=uid)
        try:
            return WriterDoc.model_validate(raw)
        except ValidationError:
            log.error("book writer document unreadable")
            raise WriterRefused("unavailable") from None

    async def doc(self, uid: str) -> WriterDoc:
        try:
            raw = await self.docs.get(self.path(WRITER, uid))
        except Exception as exc:  # noqa: BLE001 - fail closed, plain words
            log.error("book writer document unreadable", extra={"error": type(exc).__name__})
            raise WriterRefused("unavailable") from None
        return self._decode(uid, raw)

    async def change(self, uid: str, fn: Callable[[WriterDoc], tuple[WriterDoc | None, T]]) -> T:
        """Read-modify-write in one transaction; `fn` is pure (it may run again)."""
        path = self.path(WRITER, uid)

        async def run(tx: DocTx) -> T:
            doc = self._decode(uid, await tx.get(path))
            new, result = fn(doc)
            if new is not None and new != doc:
                stamped = new.model_copy(
                    update={"rev": doc.rev + 1, "updated_at": self.clock().isoformat()}
                )
                tx.set(path, stamped.model_dump(mode="json"))
            return result

        try:
            return await self.docs.transaction(run)
        except WriterRefused:
            raise
        except Exception as exc:  # noqa: BLE001
            log.error("book writer document not saved", extra={"error": type(exc).__name__})
            raise WriterRefused("unavailable") from None

    # ---- book_write_lease/{uid} ----------------------------------------------------------------
    async def lease(self, uid: str, seconds: float) -> str | None:
        """The lease for one step (its holder id), or None while another step holds it."""
        now, path = self.clock(), self.path(LEASE, uid)
        holder = f"{self._me}:{secrets.token_hex(4)}"

        async def take(tx: DocTx) -> str | None:
            raw = await tx.get(path)
            if raw is not None:
                try:
                    held = Lease.model_validate(raw)
                    if dt.datetime.fromisoformat(held.until) > now:
                        return None
                except ValidationError:
                    pass  # an unreadable lease is free (R6's rule)
            until = (now + dt.timedelta(seconds=seconds)).isoformat()
            lease = Lease(owner=uid, holder=holder, until=until, updated_at=now.isoformat())
            tx.set(path, lease.model_dump(mode="json"))
            return holder

        try:
            return await self.docs.transaction(take)
        except Exception as exc:  # noqa: BLE001
            log.error("book writer lease unreadable", extra={"error": type(exc).__name__})
            raise WriterRefused("unavailable") from None

    async def unlease(self, uid: str, holder: str) -> None:
        path = self.path(LEASE, uid)

        async def give(tx: DocTx) -> None:
            raw = await tx.get(path)
            if raw is not None and raw.get("holder") == holder:
                tx.delete(path)

        try:
            await self.docs.transaction(give)
        except Exception as exc:  # noqa: BLE001 - it simply expires
            log.warning("book writer lease left to expire", extra={"error": type(exc).__name__})

    # ---- sealed blobs --------------------------------------------------------------------------
    def seal(self, uid: str, rid: str, data: bytes) -> tuple[str, str]:
        fid = f"bf_{secrets.token_hex(6)}"
        wrapped, chunks = self._c.seal(uid, rid, fid, data)
        return fid, json.dumps({"dek": wrapped, "c": chunks}, separators=(",", ":"))

    def open(self, uid: str, rid: str, fid: str, blob: str) -> bytes:
        try:
            raw = json.loads(blob)
            dek = self._c.unwrap(uid, rid, fid, raw["dek"])
            chunks = raw["c"]
            return b"".join(
                self._c.open_chunk(dek, uid, rid, fid, n, len(chunks), c)
                for n, c in enumerate(chunks)
            )
        except (RuntimeError, ValueError, KeyError, TypeError):
            log.error("a writer blob failed its check")
            raise WriterRefused("unavailable") from None

    # ---- book_drafts and book_trial ----------------------------------------------------------
    async def put(self, col: str, doc_id: str, body: dict[str, Any]) -> None:
        async def fn(tx: DocTx) -> None:
            tx.set(self.path(col, doc_id), {**body, "updated_at": self.clock().isoformat()})

        await self.docs.transaction(fn)

    async def _mine(self, col: str, uid: str, start: str) -> list[tuple[str, dict[str, Any]]]:
        rows = await self.docs.query(Query(f"{self.prefix}{col}", where=("owner", uid)))
        return sorted((i, d) for i, d in rows if i.startswith(start))

    async def drafts(self, uid: str, rid: str) -> dict[str, Draft]:
        rows = await self._mine(DRAFTS, uid, f"{uid}_{rid}_")
        out: dict[str, Draft] = {}
        for _, raw in rows:
            try:
                d = Draft.model_validate(raw)
            except ValidationError:
                continue  # a draft that won't read is written again
            out[d.page] = d
        return out

    async def put_draft(self, uid: str, rid: str, draft: Draft) -> None:
        await self.put(DRAFTS, f"{uid}_{rid}_{draft.page}", draft.model_dump(mode="json"))

    async def trials(self, uid: str) -> dict[int, TrialPage]:
        out: dict[int, TrialPage] = {}
        for _, raw in await self._mine(TRIAL, uid, f"{uid}_"):
            try:
                t = TrialPage.model_validate(raw)
            except ValidationError:
                continue
            out[t.nn] = t
        return out

    async def put_trial(self, uid: str, page: TrialPage) -> None:
        await self.put(TRIAL, f"{uid}_{page.nn:02d}", page.model_dump(mode="json"))

    async def drop(self, col: str, uid: str, start: str | None = None) -> int:
        rows = await self._mine(col, uid, start or f"{uid}_")
        if rows:
            await self.docs.write([Delete(self.path(col, i)) for i, _ in rows])
        return len(rows)

    async def drop_old(self, uid: str) -> int:
        """Trial pages and drafts kept past `KEEP_DAYS` go (owner question 11)."""
        cutoff = self.clock() - dt.timedelta(days=KEEP_DAYS)
        gone = 0
        for col in (TRIAL, DRAFTS):
            old = [
                i
                for i, d in await self._mine(col, uid, f"{uid}_")
                if _older(d.get("updated_at"), cutoff)
            ]
            if old:
                await self.docs.write([Delete(self.path(col, i)) for i in old])
                gone += len(old)
        return gone


def _older(at: object, cutoff: dt.datetime) -> bool:
    try:
        return dt.datetime.fromisoformat(str(at)) < cutoff
    except ValueError:
        return True


__all__ = ["WriterStore"]
