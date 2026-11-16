# tests/r13_fakes_store.py -- R13 I0: the in-memory `WardrobeStore` B and C build against, and the
# REFERENCE fold (docs/plans/r13-wardrobe.md D4). Imported bare (`from r13_fakes_store import ...`)
# or through `r13_fakes`. `tests/test_r13_fold_conformance.py` holds this store and Part A's real
# one to the same rules. Clear JSON on MemoryDocs (Part A's store seals the same documents).
from __future__ import annotations

from collections.abc import Awaitable, Callable, Iterable, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from jarvis.storage.docs import Create, Delete, DocTx, MemoryDocs, Op, Set
from jarvis.wardrobe.model import Event, Piece, WardrobeView, admit
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
from jarvis.wardrobe.states import (
    HOLDING,
    STATE_SETTING,
    State,
    allowed,
    changes_availability,
    target_of,
)

PREFIX = "jarvis_"
PAGE = 200  # events a log page
DEVICE_WINDOW = timedelta(hours=24)  # a device's corrected time: never ahead, at most a day old
STATED_WINDOW = timedelta(days=30)  # a time he states: never ahead, at most 30 days back


@dataclass
class Folded:
    state: State | None = None
    back_to: State | None = None
    place: str | None = None
    place_at: datetime | None = None
    hold: str | None = None
    expected_back: Any = None
    wear: str | None = None
    wears: int = 0
    last_worn: datetime | None = None
    marks: dict[str, Mark] = field(default_factory=dict)


def _newest_verified(events: Sequence[Event], voided: set[str]) -> tuple[Any, ...] | None:
    keys = [
        e.sort_key()
        for e in events
        if e.verified and e.kind in STATE_SETTING and e.id not in voided
    ]
    return max(keys) if keys else None


def _apply_place(f: Folded, e: Event) -> bool:
    if e.place is None or e.place == f.place:
        return False
    f.place, f.place_at = e.place, e.at
    return True


def _land(f: Folded, e: Event, target: State) -> None:
    """Move to `target`, keeping what each kind remembers."""
    before = f.state
    if target == "review":
        if e.kind in HOLDING:
            f.back_to = before if before not in (None, "review") else f.back_to
        elif e.kind == "restored":
            f.back_to = "ready"
        f.hold = e.kind
    else:
        f.hold, f.back_to = None, None
    if e.kind == "wear_started":
        f.wear = e.plan or e.id
    elif e.kind == "wear_done":
        f.wear = None
    if e.kind == "sent_out":
        f.expected_back = e.due
    elif before == "with_provider":
        f.expected_back = None
    f.state = target
    _apply_place(f, e)


def _move(f: Folded, e: Event) -> Mark:
    target = target_of(e.kind, f.state, to=e.to, back_to=f.back_to)
    plan_moves = e.kind == "wear_started" and f.state == "in_use" and (e.plan or e.id) != f.wear
    if target is not None and target == f.state and not plan_moves:
        moved = _apply_place(f, e)
        if not moved and e.kind == "seen" and e.verified and f.place is not None:
            f.place_at = e.at  # a verified sighting refreshes when it was last seen there
        return "applied" if moved else "duplicate"
    if target is None or not allowed(e.kind, f.state):
        return "conflict"
    if not e.verified and changes_availability(f.state, target):
        f.back_to = f.state if f.state not in (None, "review") else f.back_to
        f.state, f.hold = "review", "unverified"
        return "held"
    _land(f, e, target)
    return "applied"


def _step(f: Folded, e: Event, newest: tuple[Any, ...] | None) -> Mark:
    if e.kind == "corrected":
        return "applied"
    older = not e.verified and newest is not None and e.sort_key() < newest
    mark: Mark = "superseded" if older else _move(f, e)
    if e.kind == "wear_done" and mark in ("applied", "superseded"):  # still a wear (D4.3)
        f.wears += 1
        f.last_worn = max(f.last_worn or e.at, e.at)
    return mark


def fold(history: Iterable[Event]) -> Folded:
    """Pure and order-independent: the piece's whole history, sorted by (at, recorded, id)."""
    events = sorted(history, key=Event.sort_key)
    voided = {e.voids for e in events if e.kind == "corrected" and e.voids}
    newest = _newest_verified(events, voided)
    f = Folded()
    for e in events:
        if e.id in voided:
            f.marks[e.id] = "voided"
            continue
        f.marks[e.id] = _step(f, e, newest)
    return f


def _need(e: Event, mark: Mark, f: Folded) -> ReviewNeeded | None:
    if mark == "conflict":
        return ReviewNeeded("conflict", e.piece, e.id, reason="refused")
    if mark == "held":
        return ReviewNeeded("hold", e.piece, e.id, back_to=f.back_to, reason="unverified")
    if mark == "applied" and e.kind in (*HOLDING, "restored"):
        return ReviewNeeded("hold", e.piece, e.id, back_to=f.back_to, reason=e.kind)
    return None


class MemoryWardrobeStore:
    """`WardrobeStore` on MemoryDocs: the index `{p}wardrobe/{uid}`, the logs
    `{p}wardrobe_log/{uid}_{piece}_{page}` (200 events a page, append-only)."""

    def __init__(self, docs: MemoryDocs, now: Callable[[], datetime], *, prefix: str = PREFIX):
        self.docs, self._now, self._p = docs, now, prefix
        self._writer: ReviewWriter | None = None
        self._observers: tuple[ChangeObserver, ...] = ()

    def bind(
        self,
        *,
        review_writer: ReviewWriter | None = None,
        observers: Sequence[ChangeObserver] = (),
    ) -> None:
        self._writer, self._observers = review_writer, tuple(observers)

    # ---- paths and reads -----------------------------------------------------------------------
    def _index(self, uid: str) -> str:
        return f"{self._p}wardrobe/{uid}"

    def _page(self, uid: str, pid: str, n: int) -> str:
        return f"{self._p}wardrobe_log/{uid}_{pid}_{n}"

    @staticmethod
    def _view_of(uid: str, doc: dict[str, Any] | None) -> WardrobeView:
        return WardrobeView.model_validate(doc) if doc else WardrobeView(uid=uid)

    async def view(self, uid: str) -> WardrobeView:
        return self._view_of(uid, await self.docs.get(self._index(uid)))

    async def _log(self, get: Callable[[str], Awaitable[Any]], uid: str, p: Piece) -> list[Event]:
        out: list[Event] = []
        for n in range((p.events + PAGE - 1) // PAGE):
            page = await get(self._page(uid, p.id, n))
            out += [Event.model_validate(x) for x in (page or {}).get("events", [])]
        return out

    async def history(
        self, uid: str, piece: str, *, view: WardrobeView | None = None
    ) -> tuple[HistoryItem, ...]:
        p = (view if view is not None else await self.view(uid)).piece(piece)
        if p is None:
            return ()
        events = await self._log(self.docs.get, uid, p)
        marks = fold(events).marks
        return tuple(HistoryItem(e, marks[e.id]) for e in sorted(events, key=Event.sort_key))

    # ---- time (D4.1) ---------------------------------------------------------------------------
    def _settle(self, e: Event, now: datetime, log: Sequence[Event]) -> Event:
        if e.sent is not None:
            at = e.at + (now - e.sent)
            if at > now or at < now - DEVICE_WINDOW:
                raise Refused("That scan's time is outside the last 24 hours: scan it again.")
        else:
            at = e.at
            if at > now or at < now - STATED_WINDOW:
                raise Refused("A time can be at most 30 days back and never ahead.")
        # arrival breaks a tie: each event is recorded after every one before it in the log
        last = max((x.recorded for x in log), default=None)
        tick = timedelta(microseconds=1)
        recorded = max(now, last + tick) if last is not None else now
        return e.model_copy(update={"at": at, "recorded": recorded})

    # ---- the commit (D4.4) ---------------------------------------------------------------------
    async def transact(
        self, uid: str, fn: Callable[[WardrobeView, DocTx], Awaitable[Commit]]
    ) -> Committed:
        result: dict[str, Any] = {}

        async def work(tx: DocTx) -> None:
            result.clear()
            view = self._view_of(uid, await tx.get(self._index(uid)))
            commit = await fn(view, tx)
            result.update(await self._fold_in(uid, view, tx, commit))

        await self.docs.transaction(work)
        await self._tell(result["changes"])
        return result["committed"]  # type: ignore[no-any-return]

    async def correct(self, uid: str, piece: str, event_id: str, *, note: str = "") -> Committed:
        from r13_fakes import ev  # noqa: PLC0415 - the fakes' event helper, one way to build one

        fix = ev(piece, "corrected", self._now(), voids=event_id, note=note)

        async def fn(view: WardrobeView, tx: DocTx) -> Commit:
            return Commit(events=(fix,))

        return await self.transact(uid, fn)

    async def _fold_in(
        self, uid: str, view: WardrobeView, tx: DocTx, commit: Commit
    ) -> dict[str, Any]:
        now = self._now()
        pieces = dict(view.pieces)
        for rec in commit.records:
            old = pieces.get(rec.id)
            keep = {"events": old.events} if old is not None else {}
            pieces[rec.id] = rec.model_copy(update=keep)
        logs: dict[str, list[Event]] = {}
        marks: dict[str, Mark] = {}
        new: dict[str, list[Event]] = {}
        stored: list[Event] = []
        for raw in commit.events:
            p = pieces.get(raw.piece)
            if p is None:
                raise Refused("That piece isn't in your wardrobe.")
            if raw.piece not in logs:
                logs[raw.piece] = await self._log(tx.get, uid, p)
            log = logs[raw.piece]
            if any(x.id == raw.id or (raw.client_id and x.client_id == raw.client_id) for x in log):
                marks[raw.id] = "known"
                continue
            e = self._settle(admit(raw), now, log)
            log.append(e)
            new.setdefault(e.piece, []).append(e)
            stored.append(e)
        needed: list[ReviewNeeded] = []
        changes: list[PieceChange] = []
        for pid, added in new.items():
            f = fold(logs[pid])
            for e in added:
                marks[e.id] = f.marks[e.id]
                need = _need(e, f.marks[e.id], f)
                if e.kind == "corrected" and f.state == "review" and f.hold:
                    if pieces[pid].state != "review":  # it leaves the piece held: its check (H3)
                        need = ReviewNeeded("hold", pid, e.id, back_to=f.back_to, reason=f.hold)
                if need is not None:
                    needed.append(need)
            before = pieces[pid]
            after = self._record(before, f, len(logs[pid]), now)
            pieces[pid] = after
            if (before.state, before.place, before.wear) != (after.state, after.place, after.wear):
                last = max(added, key=Event.sort_key)
                prior: State | None = before.state if before.events else None
                changes.append(PieceChange(uid, pid, last.kind, prior, after.state, last.plan))
        fresh = view.model_copy(update={"pieces": pieces, "rev": view.rev + 1})
        writes: list[Op] = list(commit.extra)
        if needed and self._writer is not None:
            writes += list(await self._writer.entries(uid, fresh, tx, tuple(needed)))
        self._write(tx, uid, fresh, logs, new, writes)
        already = bool(commit.events) and all(m in ("duplicate", "known") for m in marks.values())
        committed = Committed(
            events=tuple(stored),
            marks=marks,
            needed=tuple(needed),
            changed=tuple(c.piece for c in changes),
            view=fresh,
            already=already,
        )
        return {"committed": committed, "changes": changes}

    @staticmethod
    def _record(p: Piece, f: Folded, n_events: int, now: datetime) -> Piece:
        return p.model_copy(
            update={
                "state": f.state or p.state,
                "back_to": f.back_to,
                "place": f.place or p.place,
                "place_at": f.place_at or p.place_at,
                "hold": f.hold,
                "expected_back": f.expected_back,
                "wear": f.wear,
                "wears": f.wears,
                "last_worn": f.last_worn,
                "events": n_events,
                "updated_at": now,
            }
        )

    def _write(
        self,
        tx: DocTx,
        uid: str,
        fresh: WardrobeView,
        logs: dict[str, list[Event]],
        new: dict[str, list[Event]],
        writes: Sequence[Op],
    ) -> None:
        tx.set(self._index(uid), fresh.model_copy(update={"updated_at": self._now()}).to_json())
        for pid in new:
            log = logs[pid]
            first_new = len(log) - len(new[pid])
            for n in range(first_new // PAGE, (len(log) + PAGE - 1) // PAGE):
                page = [e.to_json() for e in log[n * PAGE : (n + 1) * PAGE]]
                body = {"events": page, "updated_at": self._now().isoformat()}
                tx.set(self._page(uid, pid, n), body)
        for op in writes:
            if isinstance(op, Set):
                tx.set(op.path, op.data)
            elif isinstance(op, Create):
                tx.create(op.path, op.data)
            elif isinstance(op, Delete):
                tx.delete(op.path)

    async def _tell(self, changes: Sequence[PieceChange]) -> None:
        for change in changes:
            for obs in self._observers:
                try:
                    await obs.changed(change)
                except Exception:  # noqa: BLE001, S112 - an observer never breaks the commit
                    continue


def memory_store(docs: MemoryDocs, now: Callable[[], datetime]) -> MemoryWardrobeStore:
    return MemoryWardrobeStore(docs, now)


__all__ = ["PAGE", "Folded", "MemoryWardrobeStore", "fold", "memory_store"]
