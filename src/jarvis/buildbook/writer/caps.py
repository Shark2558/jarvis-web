# src/jarvis/buildbook/writer/caps.py
"""R6.3 D8 (plan review M1, H7): the writer's rupee ledger, R13.1's pattern
(`wardrobe/seeme/cap.py`):

    {prefix}book_write_spend/{uid}_{YYYY-MM}   `model.SpendDoc` (his IST month; numbers only)

`reserve` reads and writes in ONE transaction (this month's document, and the month before's for
an hour after his month's end): a call's hold is refused with nothing written when the run's spend
and holds plus this hold would pass the run's cap, when release updates' spend this month would
pass the month cap, when his Vitals month (as metered, `Gate.used_inr`: every settled Book call is
in it) plus the ledger's open holds plus this hold would pass the % line of his monthly limit (no
limit: the caps only), or while a hold under 10 minutes exists for the same page (`busy`). A
counter that isn't a finite number >= 0 refuses (`unreadable`, never "Rs 0 spent").

A run's spend is `runs[key]`: `trial_<estimate id>` (each trial its own cap), `first` (one time),
`update_<release id>`; a hold kept an hour (`settle_old`, a call that may have been billed) has
lost its key and settles into its kind's own counter, which every run of that kind also counts
(the safe side). `settle` moves a hold into spend at the billed rupees; `release` gives it back. A
failed close is tried three times, then kept in this process (`pending`) and closed first, as it
was meant, by the next `close_later` (every run and step starts with it).
"""

from __future__ import annotations

import asyncio
import math
import re
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Literal
from zoneinfo import ZoneInfo

from pydantic import ValidationError

from jarvis.buildbook.writer.model import HOLD_BUSY_S, HOLD_STALE_S, SPEND, Hold, RunKind, SpendDoc
from jarvis.logging import get_logger
from jarvis.storage.docs import Docs, DocTx, Query

log = get_logger(__name__)
Code = Literal["cap", "month", "limit", "busy", "unreadable"]
CLOSE_WAITS_S = (0.05, 0.25)  # between the three tries of a settle or a release
EPS = 1e-9
_MONTH = re.compile(r"_(\d{4}-\d{2})$")


class CapRefused(Exception):
    """A hold that was not reserved: nothing was written, nothing is sent."""

    def __init__(self, code: Code) -> None:
        super().__init__(code)
        self.code: Code = code


@dataclass(frozen=True)
class Gate:
    """His Vitals month as metered, his monthly limit (None: none set) and the % line."""

    used_inr: float
    limit_inr: float | None
    pct: int


@dataclass(eq=False)
class Held:
    uid: str
    call_id: str
    inr: float
    month: str
    run: RunKind
    key: str
    closed: bool = False


def _finite(doc: SpendDoc) -> SpendDoc:
    numbers = [
        doc.spent_inr,
        doc.held_inr,
        *doc.runs.values(),
        *(h.inr for h in doc.holds.values()),
    ]
    if not all(math.isfinite(n) for n in numbers):
        raise CapRefused("unreadable")
    return doc


def decode(uid: str, raw: dict[str, object] | None) -> SpendDoc:
    if raw is None:
        return SpendDoc(owner=uid)
    try:
        return _finite(SpendDoc.model_validate(raw))
    except ValidationError:
        raise CapRefused("unreadable") from None


def encode(doc: SpendDoc, now: datetime) -> dict[str, object]:
    return doc.model_copy(update={"updated_at": now.isoformat()}).model_dump(mode="json")


def run_of(docs: Sequence[SpendDoc], key: str, kind: RunKind) -> float:
    """A run's spend and holds over these months (its kind's stale counter included)."""
    spent = sum(
        d.runs.get(key, 0.0) + (d.runs.get(kind, 0.0) if key != kind else 0.0) for d in docs
    )
    return spent + sum(h.inr for d in docs for h in d.holds.values() if h.run == kind)


def updates_of(docs: Sequence[SpendDoc]) -> float:
    spent = sum(v for d in docs[:1] for k, v in d.runs.items() if k.startswith("update"))
    return spent + sum(h.inr for d in docs[:1] for h in d.holds.values() if h.run == "update")


class WriterCaps:
    def __init__(self, docs: Docs, prefix: str, *, tz: str, clock: Callable[[], datetime]) -> None:
        self.docs, self.prefix, self.tz, self.clock = docs, prefix, ZoneInfo(tz), clock
        self.pending: dict[str, tuple[Held, float]] = {}  # call id -> a close still to do

    def month_of(self, at: datetime) -> str:
        return at.astimezone(self.tz).strftime("%Y-%m")

    def path(self, uid: str, month: str) -> str:
        return f"{self.prefix}{SPEND}/{uid}_{month}"

    def keys_now(self) -> tuple[str, ...]:
        """This month, then the one before while within an hour of this one's start."""
        now = self.clock()
        this, before = self.month_of(now), self.month_of(now - timedelta(seconds=HOLD_STALE_S))
        return (this,) if before == this else (this, before)

    async def month(self, uid: str, month: str | None = None) -> SpendDoc:
        key = month or self.month_of(self.clock())
        return decode(uid, await self.docs.get(self.path(uid, key)))

    async def run_spent(self, uid: str, key: str, kind: RunKind) -> float:
        return run_of([await self.month(uid, m) for m in self.keys_now()], key, kind)

    async def months(self, uid: str) -> list[tuple[str, SpendDoc]]:
        rows = await self.docs.query(Query(f"{self.prefix}{SPEND}", where=("owner", uid)))
        found = [(m.group(1), d) for i, d in rows if (m := _MONTH.search(i)) is not None]
        return sorted((month, decode(uid, d)) for month, d in found)

    def _check(
        self, docs: Sequence[SpendDoc], held: Hold, key: str, cap: int, month_cap: int | None,
        gate: Gate,
    ) -> None:  # fmt: skip
        fresh = self.clock() - timedelta(seconds=HOLD_BUSY_S)
        if any(
            h.page == held.page and datetime.fromisoformat(h.at) > fresh
            for d in docs
            for h in d.holds.values()
        ):
            raise CapRefused("busy")
        if run_of(docs, key, held.run) + held.inr > cap + EPS:
            raise CapRefused("cap")
        if month_cap is not None and updates_of(docs) + held.inr > month_cap + EPS:
            raise CapRefused("month")
        if gate.limit_inr is not None:
            open_holds = sum(d.held_inr for d in docs)
            if gate.used_inr + open_holds + held.inr > gate.pct / 100 * gate.limit_inr + EPS:
                raise CapRefused("limit")

    async def reserve(
        self, uid: str, *, call_id: str, page: str, run: RunKind, key: str, hold_inr: float,
        cap_inr: int, month_cap: int | None, gate: Gate,
    ) -> Held:  # fmt: skip
        if not math.isfinite(hold_inr) or hold_inr < 0:
            raise CapRefused("unreadable")
        if self.pending:
            await self.close_later(uid)
        months = self.keys_now()
        held = Hold(inr=round(hold_inr, 2), at=self.clock().isoformat(), run=run, page=page)

        async def fn(tx: DocTx) -> None:
            docs = [decode(uid, await tx.get(self.path(uid, m))) for m in months]
            self._check(docs, held, key, cap_inr, month_cap, gate)
            this = docs[0]
            new = this.model_copy(
                update={
                    "held_inr": this.held_inr + held.inr,
                    "holds": {**this.holds, call_id: held},
                }
            )
            tx.set(self.path(uid, months[0]), encode(new, self.clock()))

        try:
            await self.docs.transaction(fn)
        except CapRefused:
            raise
        except Exception as exc:  # noqa: BLE001 - fail closed: no call we can't account for
            log.error("book writer ledger unreadable", extra={"error": type(exc).__name__})
            raise CapRefused("unreadable") from None
        return Held(uid, call_id, held.inr, months[0], run, key)

    async def _close(self, h: Held, inr: float, waits: Sequence[float]) -> None:
        if h.closed:
            return
        h.closed = True  # before the first await: two closes cannot both pass
        path = self.path(h.uid, h.month)

        async def fn(tx: DocTx) -> None:
            doc = decode(h.uid, await tx.get(path))
            mine = doc.holds.get(h.call_id)
            if mine is None:
                return  # already closed (a retry after a lost reply counts nothing twice)
            holds = {k: v for k, v in doc.holds.items() if k != h.call_id}
            runs = {**doc.runs, h.key: doc.runs.get(h.key, 0.0) + inr} if inr else doc.runs
            new = doc.model_copy(
                update={
                    "spent_inr": doc.spent_inr + inr,
                    "held_inr": max(0.0, doc.held_inr - mine.inr),
                    "holds": holds,
                    "runs": runs,
                    "calls": doc.calls + (1 if inr else 0),
                }
            )
            tx.set(path, encode(new, self.clock()))

        try:
            await _tries(lambda: self.docs.transaction(fn), waits)
        except BaseException as exc:
            h.closed = False  # a failed close may be tried again, as it was meant
            self.pending[h.call_id] = (h, inr)
            log.error("book writer hold kept for later", extra={"error": type(exc).__name__})
            raise
        self.pending.pop(h.call_id, None)

    async def settle(self, h: Held, inr: float, *, waits: Sequence[float] = CLOSE_WAITS_S) -> None:
        """The hold becomes spend at the billed rupees (the caller records it in billing)."""
        if not math.isfinite(inr) or inr < 0:
            raise CapRefused("unreadable")
        await self._close(h, round(inr, 4), waits)

    async def release(self, h: Held, *, waits: Sequence[float] = CLOSE_WAITS_S) -> None:
        """Nothing was billed (the call never left): the hold goes back."""
        await self._close(h, 0.0, waits)

    async def close_later(self, uid: str) -> int:
        closed = 0
        for h, inr in [v for v in self.pending.values() if v[0].uid == uid]:
            try:
                await self._close(h, inr, CLOSE_WAITS_S)
            except Exception:  # noqa: BLE001 - logged by _close and kept for the next try
                continue
            closed += 1
        return closed

    async def settle_old(self, uid: str) -> int:
        """Holds older than an hour become spend at their hold (a call that may have been
        billed), under their kind's own counter; a close kept from this process goes first."""
        await self.close_later(uid)
        cutoff = self.clock() - timedelta(seconds=HOLD_STALE_S)
        moved = 0
        for month, doc in await self.months(uid):
            for call_id, h in doc.holds.items():
                if datetime.fromisoformat(h.at) <= cutoff and call_id not in self.pending:
                    await self.settle(Held(uid, call_id, h.inr, month, h.run, h.run), h.inr)
                    moved += 1
        return moved


async def _tries(write: Callable[[], Awaitable[None]], waits: Sequence[float]) -> None:
    for wait in waits:
        try:
            await write()
            return
        except Exception as exc:  # noqa: BLE001 - a store blip: tried again
            log.warning(
                "book writer close failed, trying again", extra={"error": type(exc).__name__}
            )
            await asyncio.sleep(wait)
    await write()


__all__ = ["CLOSE_WAITS_S", "CapRefused", "Gate", "Held", "WriterCaps", "decode", "encode"]
