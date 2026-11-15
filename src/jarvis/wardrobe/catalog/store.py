# src/jarvis/wardrobe/catalog/store.py
"""Part A's `WardrobeStore` (docs/plans/r13-wardrobe.md D2, D4.4, OPS-03; plan review H4, M9).

    {prefix}wardrobe/{uid}                     {rev, v, kid, blob, updated_at}
        blob = AES-GCM(the index: `WardrobeView.to_json()`, short keys), purpose `wardrobe`,
        AAD `wardrobe/index/{uid}/v1`
    {prefix}wardrobe_log/{uid}_{piece}_{page}  {v, kid, n, blob, updated_at}
        blob = AES-GCM(200 events a page, append-only), AAD `wardrobe/log/{uid}/{piece}/{page}/v1`

`transact(uid, fn)` runs `fn(view, tx)` inside one transaction: every read first (`fn` reads
through `tx`, so does B's writer), then the store settles each event's time (`fold.settle`),
drops a retry (its id or client id already in the log: "known"), re-folds each piece it touches
(`fold.fold`), asks the bound `ReviewWriter` for the entries of every `ReviewNeeded`, and writes
the index, the log pages, `fn`'s own writes (`Commit.extra`) and the entries LAST, in one commit:
a write that fails rolls everything back. Observers hear each changed piece once, after it.

Refused in plain words, nothing written: a sealed index past `index_max_bytes` (FULL: the byte
guard, whatever the count), more active pieces than `max_pieces`, an event for a piece that is
not in the index, a time outside D4.1's window. An index or a page that can't be read or opened
is `WardrobeUnavailable` and is never overwritten. Logs carry ids, counts and error classes only.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from jarvis.keyring import Keyring
from jarvis.logging import get_logger
from jarvis.storage.docs import Create, Delete, Docs, DocTx, Op, Set
from jarvis.wardrobe.catalog import fold as folding
from jarvis.wardrobe.catalog.logs import PAGE, LogPages
from jarvis.wardrobe.catalog.sealed import VERSION, Sealer, aad_index, check_owner, dumps
from jarvis.wardrobe.model import Event, Piece, WardrobeView, new_id
from jarvis.wardrobe.ports import (
    ChangeObserver,
    Commit,
    Committed,
    HistoryItem,
    Mark,
    PieceChange,
    Refused,
    ReviewNeeded,
    ReviewWriter,
)
from jarvis.wardrobe.states import State

log = get_logger(__name__)

UNAVAILABLE = "JARVIS couldn't open your wardrobe just now. Try again in a minute."
UNSAVED = "JARVIS couldn't save that to your wardrobe just now. Try again in a minute."
FULL = "Your wardrobe list is full: archive or remove a few pieces first."
NOT_IN = "That piece isn't in your wardrobe."
NOT_IN_LOG = "That event isn't in this piece's history."
# what only the fold sets: a record from a tool never changes them (the state is never by hand)
FOLD_OWNED: tuple[str, ...] = (
    *("state", "back_to", "place", "place_at", "hold", "expected_back", "wear", "wears"),
    *("last_worn", "events", "created_at"),
)
_PASS = (Refused, ValueError, LookupError, PermissionError)


class WardrobeUnavailable(RuntimeError):
    """The wardrobe can't be read or saved right now (plain words)."""


def empty_view(uid: str) -> WardrobeView:
    return WardrobeView.model_validate({"uid": uid})


def too_many(cap: int) -> str:
    return f"Your wardrobe holds at most {cap} pieces: archive or remove a few pieces first."


@dataclass
class _Work:
    """One commit's working set (private to `_fold_in`)."""

    pieces: dict[str, Piece]
    logs: dict[str, list[Event]] = field(default_factory=dict)
    new: dict[str, list[Event]] = field(default_factory=dict)
    marks: dict[str, Mark] = field(default_factory=dict)
    needed: list[ReviewNeeded] = field(default_factory=list)
    changes: list[PieceChange] = field(default_factory=list)


class CatalogStore:
    def __init__(
        self,
        docs: Docs,
        keyring: Keyring,
        now: Callable[[], datetime],
        *,
        prefix: str = "jarvis_",
        max_pieces: int = 400,
        index_max_bytes: int = 900 * 1024,
    ) -> None:
        self.docs, self._now, self._p = docs, now, prefix
        self.sealer = Sealer(keyring)
        self.logs = LogPages(self.sealer, prefix)
        self.max_pieces, self.index_max_bytes = max_pieces, index_max_bytes
        self._writer: ReviewWriter | None = None
        self._observers: tuple[ChangeObserver, ...] = ()
        self.desk: Any = None  # Part A's own services (`part.Desk`), set once by `build`

    def bind(
        self,
        *,
        review_writer: ReviewWriter | None = None,
        observers: Sequence[ChangeObserver] = (),
    ) -> None:
        self._writer, self._observers = review_writer, tuple(observers)

    def now(self) -> datetime:
        return self._now()

    @property
    def prefix(self) -> str:
        return self._p

    # ---- paths ---------------------------------------------------------------------------------
    def index_path(self, uid: str) -> str:
        return f"{self._p}wardrobe/{check_owner(uid)}"

    def page_path(self, uid: str, pid: str, n: int) -> str:
        return self.logs.path(uid, pid, n)

    # ---- the index -----------------------------------------------------------------------------
    def _open_index(self, uid: str, doc: Mapping[str, Any] | None) -> WardrobeView:
        if doc is None:
            return empty_view(uid)
        if doc.get("v") != VERSION or not isinstance(doc.get("rev"), int):
            raise ValueError("envelope")
        raw = self.sealer.open("wardrobe", aad_index(uid), doc.get("blob"))
        view = WardrobeView.model_validate(raw)
        if view.uid != uid:
            raise ValueError("owner")
        return view

    def _seal_index(self, uid: str, view: WardrobeView) -> dict[str, Any]:
        blob = self.sealer.seal("wardrobe", aad_index(uid), view.to_json())
        stamp = self._now().isoformat()
        env = {"rev": view.rev, "v": VERSION, "kid": self.sealer.kid, "blob": blob}
        env["updated_at"] = stamp
        if len(dumps(env)) > self.index_max_bytes:
            raise Refused(FULL)
        return env

    async def view(self, uid: str) -> WardrobeView:
        path = self.index_path(uid)
        try:
            return self._open_index(uid, await self.docs.get(path))
        except Exception as exc:  # noqa: BLE001 - storage or data trouble: read nothing
            log.warning("wardrobe index unreadable", extra={"reason": type(exc).__name__})
            raise WardrobeUnavailable(UNAVAILABLE) from None

    # ---- the log -------------------------------------------------------------------------------
    async def _read_log(
        self, get: Callable[[str], Awaitable[Any]], uid: str, p: Piece
    ) -> list[Event]:
        try:
            return await self.logs.read(get, uid, p)
        except Exception as exc:  # noqa: BLE001 - a page that can't be opened: never written
            log.warning("wardrobe log unreadable", extra={"reason": type(exc).__name__})
            raise WardrobeUnavailable(UNAVAILABLE) from None

    async def events(self, uid: str, pid: str) -> list[Event]:
        """The piece's whole log as stored (the backup and the pilot read it)."""
        p = (await self.view(uid)).piece(pid)
        return [] if p is None else await self._read_log(self.docs.get, uid, p)

    async def history(self, uid: str, piece: str) -> tuple[HistoryItem, ...]:
        p = (await self.view(uid)).piece(piece)
        if p is None:
            return ()
        events = await self._read_log(self.docs.get, uid, p)
        marks = folding.fold(events).marks
        return tuple(HistoryItem(e, marks[e.id]) for e in sorted(events, key=Event.sort_key))

    # ---- the commit (D4.4) ---------------------------------------------------------------------
    async def transact(
        self,
        uid: str,
        fn: Callable[[WardrobeView, DocTx], Awaitable[Commit]],
        *,
        index: Callable[[WardrobeView], WardrobeView] | None = None,
        needed: Sequence[ReviewNeeded] = (),
    ) -> Committed:
        """`index` (A's own, beyond the contract): a change to the index's other records (a
        place's baseline, a pair) in the same commit; `needed`: entries to ask B's writer for
        with no event (the sweep: a hold without its entry, D4.4)."""
        result: dict[str, Any] = {}

        async def work(tx: DocTx) -> None:
            result.clear()
            view = await self._open_tx(uid, tx)
            commit = await fn(view, tx)
            result.update(await self._fold_in(uid, view, tx, commit, (index, tuple(needed))))

        await self._commit(work)
        await self._tell(result["changes"])
        return result["committed"]  # type: ignore[no-any-return]

    async def correct(self, uid: str, piece: str, event_id: str, *, note: str = "") -> Committed:
        async def fn(view: WardrobeView, tx: DocTx) -> Commit:
            p = view.piece(piece)
            if p is None:
                raise Refused(NOT_IN)
            if all(e.id != event_id for e in await self._read_log(tx.get, uid, p)):
                raise Refused(NOT_IN_LOG)
            now = self._now()
            fix = Event.model_validate(
                {"id": new_id("we"), "piece": piece, "kind": "corrected", "at": now,
                 "recorded": now, "source": "tap", "voids": event_id, "note": note[:120]}
            )  # fmt: skip
            return Commit(events=(fix,))

        return await self.transact(uid, fn)

    def _take_records(self, w: _Work, records: Sequence[Piece], now: datetime) -> None:
        for rec in records:
            old = w.pieces.get(rec.id)
            # a new record has no log yet, whatever it says; an old one keeps the fold's fields
            keep = {k: getattr(old, k) for k in FOLD_OWNED} if old is not None else {"events": 0}
            fresh = rec.model_copy(update={**keep, "updated_at": now})
            if old is None and fresh.created_at is None:
                fresh = fresh.model_copy(update={"created_at": now})
            w.pieces[rec.id] = fresh

    async def _append(self, w: _Work, uid: str, tx: DocTx, events: Sequence[Event]) -> None:
        now = self._now()
        for raw in events:
            p = w.pieces.get(raw.piece)
            if p is None:
                raise Refused(NOT_IN)
            if raw.piece not in w.logs:
                w.logs[raw.piece] = await self._read_log(tx.get, uid, p)
            known = w.logs[raw.piece]
            if any(
                x.id == raw.id or (raw.client_id and x.client_id == raw.client_id) for x in known
            ):
                w.marks[raw.id] = "known"
                continue
            e = folding.settle(raw, now, known)
            known.append(e)
            w.new.setdefault(e.piece, []).append(e)

    def _refold(self, w: _Work, uid: str, pid: str, now: datetime) -> None:
        log_, added = w.logs[pid], w.new[pid]
        f = folding.fold(log_)
        for e in added:
            w.marks[e.id] = f.marks[e.id]
            if (need := folding.needs(e, f.marks[e.id], f)) is not None:
                w.needed.append(need)
        if any(e.kind == "corrected" for e in added):
            ids = {e.id for e in added}
            w.needed += folding.rescans(
                pid, folding.fold(x for x in log_ if x.id not in ids).marks, f
            )
        before = w.pieces[pid]
        after = before.model_copy(
            update={
                "state": f.state or before.state, "back_to": f.back_to,
                "place": f.place or before.place, "place_at": f.place_at or before.place_at,
                "hold": f.hold, "expected_back": f.expected_back, "wear": f.wear,
                "wears": f.wears, "last_worn": f.last_worn, "events": len(log_), "updated_at": now,
            }
        )  # fmt: skip
        w.pieces[pid] = after
        if (before.state, before.place, before.wear) != (after.state, after.place, after.wear):
            last = max(added, key=Event.sort_key)
            prior: State | None = before.state if before.events else None
            w.changes.append(PieceChange(uid, pid, last.kind, prior, after.state, last.plan))

    def _check_cap(self, view: WardrobeView, pieces: Mapping[str, Piece]) -> None:
        def active(ps: Mapping[str, Piece]) -> int:
            return sum(p.state != "archived" and p.merged_into is None for p in ps.values())

        if active(pieces) > max(self.max_pieces, active(view.pieces)):
            raise Refused(too_many(self.max_pieces))

    async def _fold_in(
        self,
        uid: str,
        view: WardrobeView,
        tx: DocTx,
        commit: Commit,
        more: tuple[Callable[[WardrobeView], WardrobeView] | None, tuple[ReviewNeeded, ...]],
    ) -> dict[str, Any]:
        now, (index, asked) = self._now(), more
        w = _Work(pieces=dict(view.pieces), needed=list(asked))
        self._take_records(w, commit.records, now)
        await self._append(w, uid, tx, commit.events)
        for pid in w.new:
            self._refold(w, uid, pid, now)
        self._check_cap(view, w.pieces)
        fresh = view.model_copy(update={"pieces": w.pieces, "rev": view.rev + 1, "updated_at": now})
        if index is not None:
            fresh = index(fresh).model_copy(update={"pieces": w.pieces, "rev": fresh.rev})
        writes: list[Op] = list(commit.extra)
        if w.needed and self._writer is not None:
            writes += list(await self._writer.entries(uid, fresh, tx, tuple(w.needed)))
        self._write(tx, uid, fresh, w, writes)
        already = bool(commit.events) and all(m in ("duplicate", "known") for m in w.marks.values())
        stored = tuple(e for pid in w.new for e in w.new[pid])
        done = Committed(stored, w.marks, tuple(w.needed), tuple(c.piece for c in w.changes),
                         fresh, already)  # fmt: skip
        return {"committed": done, "changes": w.changes}

    def _write(self, tx: DocTx, uid: str, fresh: WardrobeView, w: _Work, writes: list[Op]) -> None:
        tx.set(self.index_path(uid), self._seal_index(uid, fresh))
        for pid, added in w.new.items():
            log_ = w.logs[pid]
            for op in self.logs.writes(uid, pid, log_, len(log_) - len(added), self._now()):
                apply_op(tx, op)
        for op in writes:
            apply_op(tx, op)

    async def rewrite(
        self,
        uid: str,
        fn: Callable[[WardrobeView, DocTx], Awaitable[tuple[WardrobeView, list[Op]]]],
    ) -> WardrobeView:
        """A change no event describes (a purge drops a record, his settings, the tagging ₹):
        `fn` returns the new view and its own writes; one commit, the same guards."""
        out: list[WardrobeView] = []

        async def work(tx: DocTx) -> None:
            out.clear()
            view = await self._open_tx(uid, tx)
            new, ops = await fn(view, tx)
            fresh = new.model_copy(update={"rev": view.rev + 1, "updated_at": self._now()})
            tx.set(self.index_path(uid), self._seal_index(uid, fresh))
            for op in ops:
                apply_op(tx, op)
            out.append(fresh)

        await self._commit(work)
        return out[0]

    async def _open_tx(self, uid: str, tx: DocTx) -> WardrobeView:
        try:
            return self._open_index(uid, await tx.get(self.index_path(uid)))
        except Exception as exc:  # noqa: BLE001 - never overwrite what can't be opened
            log.warning("wardrobe index corrupt", extra={"reason": type(exc).__name__})
            raise WardrobeUnavailable(UNAVAILABLE) from None

    async def _commit(self, work: Callable[[DocTx], Awaitable[None]]) -> None:
        try:
            await self.docs.transaction(work)
        except (WardrobeUnavailable, *_PASS):
            raise
        except Exception as exc:  # noqa: BLE001 - nothing was written
            log.warning("wardrobe commit failed", extra={"reason": type(exc).__name__})
            raise WardrobeUnavailable(UNSAVED) from None

    async def _tell(self, changes: Sequence[PieceChange]) -> None:
        for change in changes:
            for obs in self._observers:
                try:
                    await obs.changed(change)
                except Exception as exc:  # noqa: BLE001 - an observer never breaks the commit
                    log.warning("a wardrobe observer failed", extra={"error": type(exc).__name__})


def apply_op(tx: DocTx, op: Op) -> None:
    if isinstance(op, Set):
        tx.set(op.path, op.data)
    elif isinstance(op, Create):
        tx.create(op.path, op.data)
    elif isinstance(op, Delete):
        tx.delete(op.path)


__all__ = [
    "FULL",
    "NOT_IN",
    "PAGE",
    "UNAVAILABLE",
    "UNSAVED",
    "CatalogStore",
    "WardrobeUnavailable",
    "apply_op",
    "empty_view",
    "too_many",
]
