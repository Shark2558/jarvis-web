# src/jarvis/wardrobe/seeme/cap.py
"""R13.1 Part C: the try-on ₹ cap, atomic, his month, GST counted, fail closed
(docs/plans/r13-1-try-on.md D15; plan review M1, L9; R6.2's `Hold`, `billing/meter.py`).

    {prefix}tryon_spend/{uid}_{YYYY-MM}   {owner, month, spent_inr, held_inr, holds {request_id:
                                          {inr, at}}, done {request_id: outcome} (<= 50),
                                          done_order [request_id, ...] (the answers' order: a
                                          Firestore map keeps none), pictures, blocked,
                                          updated_at}: numbers and ids only, his IST month
    {prefix}tryon_spend/{uid}_prefs       {owner, on, cap_inr, keep_days, updated_at}: his own
                                          See it on me switch, cap and keep days (None: the
                                          deployment's); kept with the spend, so a delete of his
                                          photo or OPS-05 never resets a cap he lowered

`reserve` reads and writes in ONE transaction: a repeated request id answers its `done` outcome
(a billed one only: a release is not kept there, so a retry after "nothing was charged" asks
Google again; I1's security review, finding 2);
refused with nothing written while a hold under 10 minutes old exists (`busy`, so two instances
in a rollout can't both pass) or when spent + held + the hold would pass the cap (`cap_reached`,
"This month's try-on limit of ₹300 is used: ..."). A counter that isn't a finite number >= 0 is
unreadable and refuses (never "₹0 spent"). `settle` moves the hold into spend; `release` gives it
back (never below 0). Both set `released` before the first await and undo it when the write fails,
so a failed one can be tried again and a second one is a no-op. A settle or a release is tried
three times (`CLOSE_WAITS_S` between); one that still fails is logged at ERROR with its request
id and kept in `pending` (this process's memory), which the next `reserve` of his and the daily
job close first, as they were meant: a release never becomes spend (review C-1, finding 5).
`settle_old` (the daily job) turns holds older than an hour into spend at their hold: a call that
may have been billed. It records nothing in his usage month: the press records every billed call
whatever its settle did, so only a crash in the call is left out (recording here would count a
press whose settle failed twice).
"""

from __future__ import annotations

import asyncio
import math
import re
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from jarvis.billing.meter import UsageMeter
from jarvis.logging import get_logger
from jarvis.storage.docs import Docs, DocTx, Query
from jarvis.wardrobe.seeme import texts
from jarvis.wardrobe.seeme.estimate import rupees
from jarvis.wardrobe.tryon.model import BUSY_MINUTES, DONE_MAX, SETTLE_HOURS, SPEND

log = get_logger(__name__)
_MONTH = re.compile(r"_(\d{4}-\d{2})$")
_MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")
PREFS_ID = "prefs"
CAP_MAX, KEEP_MAX = 2000, 30
CLOSE_WAITS_S = (0.05, 0.25)  # between the three tries of a settle or a release


CapRefused = texts.SeeMeRefused


def unreadable() -> CapRefused:
    return CapRefused(503, "cap_unreadable", texts.CAP_UNREADABLE)


@dataclass(frozen=True)
class Month:
    month: str
    spent_inr: float = 0.0
    held_inr: float = 0.0
    holds: Mapping[str, Mapping[str, Any]] = field(default_factory=dict)
    done: Mapping[str, Mapping[str, Any]] = field(default_factory=dict)
    pictures: int = 0
    blocked: int = 0
    order: tuple[str, ...] = ()  # `done`'s ids, oldest first (pruned from the front)


@dataclass(frozen=True)
class Done:
    """A request id already answered: its outcome (`{"picture": id}` or `{"error": code}`)."""

    outcome: Mapping[str, Any]


@dataclass(eq=False)
class CapHold:
    uid: str
    request_id: str
    inr: float
    month: str
    released: bool = False


@dataclass(frozen=True)
class Later:
    """A settle or release that failed after its tries: closed later, as it was meant."""

    hold: CapHold
    spend: float
    outcome: Mapping[str, Any]
    picture: int
    blocked: int


@dataclass(frozen=True)
class Prefs:
    on: bool = True
    cap_inr: int | None = None
    keep_days: int | None = None


def _money(v: object) -> float:
    if isinstance(v, bool) or not isinstance(v, int | float) or not math.isfinite(v) or v < 0:
        raise unreadable()
    return float(v)


def _count(v: object) -> int:
    if isinstance(v, bool) or not isinstance(v, int) or v < 0:
        raise unreadable()
    return v


def _when(v: object) -> datetime:
    try:
        at = datetime.fromisoformat(str(v))
    except ValueError:
        raise unreadable() from None
    if at.tzinfo is None:
        raise unreadable()
    return at


def _holds(v: object) -> dict[str, dict[str, Any]]:
    if not isinstance(v, dict):
        raise unreadable()
    out: dict[str, dict[str, Any]] = {}
    for rid, h in v.items():
        if not isinstance(h, dict):
            raise unreadable()
        out[str(rid)] = {"inr": _money(h.get("inr")), "at": _when(h.get("at")).isoformat()}
    return out


def _order(v: object, done: Mapping[str, Any]) -> tuple[str, ...]:
    """`done_order` as written, then any answer it doesn't name (oldest: pruned first)."""
    if not isinstance(v, list) or not all(isinstance(r, str) for r in v):
        raise unreadable()
    known = tuple(r for r in dict.fromkeys(v) if r in done)
    return (*sorted(r for r in done if r not in set(known)), *known)


def decode(doc: Mapping[str, Any] | None, month: str) -> Month:
    if doc is None:
        return Month(month)
    done = doc.get("done", {})
    if not isinstance(done, dict) or not all(isinstance(o, dict) for o in done.values()):
        raise unreadable()
    return Month(
        month=month, spent_inr=_money(doc.get("spent_inr", 0.0)),
        held_inr=_money(doc.get("held_inr", 0.0)), holds=_holds(doc.get("holds", {})),
        done=dict(done), pictures=_count(doc.get("pictures", 0)),
        blocked=_count(doc.get("blocked", 0)), order=_order(doc.get("done_order", []), done),
    )  # fmt: skip


def encode(uid: str, m: Month, now: datetime) -> dict[str, Any]:
    order = [r for r in m.order if r in m.done][-DONE_MAX:]  # the last 50 answers, in order
    return {
        "owner": uid, "month": m.month, "spent_inr": round(m.spent_inr, 2),
        "held_inr": round(max(0.0, m.held_inr), 2), "holds": dict(m.holds),
        "done": {r: m.done[r] for r in order}, "done_order": order, "pictures": m.pictures,
        "blocked": m.blocked, "updated_at": now.isoformat(),
    }  # fmt: skip


def reached_words(cap: int, spent: float, now: datetime, tz: str) -> str:
    """ "This month's try-on limit of ₹300 is used: ₹291.6 spent. It resets on 1 Dec, ..." """
    local = now.astimezone(ZoneInfo(tz))
    nxt = 1 if local.month == 12 else local.month + 1
    return texts.CAP_REACHED.format(
        cap=rupees(cap), spent=rupees(spent), day=f"1 {_MONTHS[nxt - 1]}"
    )


class TryonCap:
    def __init__(self, docs: Docs, prefix: str, *, tz: str, now: Callable[[], datetime]) -> None:
        self.docs, self.prefix, self.tz, self.now = docs, prefix, tz, now
        self._meter = UsageMeter(docs, prefix=prefix, tz=tz)
        self.pending: dict[str, Later] = {}  # request id -> a close still to do

    def month_of(self, at: datetime) -> str:
        return self._meter.month_of(at)

    def path(self, uid: str, month: str) -> str:
        return f"{self.prefix}{SPEND}/{uid}_{month}"

    async def month(self, uid: str, *, month: str | None = None) -> Month:
        key = month or self.month_of(self.now())
        return decode(await self.docs.get(self.path(uid, key)), key)

    async def months(self, uid: str) -> list[Month]:
        rows = await self.docs.query(Query(f"{self.prefix}{SPEND}", where=("owner", uid)))
        found = [(m.group(1), d) for i, d in rows if (m := _MONTH.search(i)) is not None]
        return sorted((decode(d, key) for key, d in found), key=lambda m: m.month)

    def _check(self, m: Month, request_id: str, hold_inr: float, cap_inr: int) -> Done | None:
        if request_id in m.done:
            return Done(m.done[request_id])
        fresh = self.now() - timedelta(minutes=BUSY_MINUTES)
        if request_id in m.holds or any(_when(h["at"]) > fresh for h in m.holds.values()):
            raise CapRefused(409, "busy", texts.BUSY)
        if cap_inr <= 0:
            raise CapRefused(402, "cap_reached", texts.CAP_OFF)
        if m.spent_inr + m.held_inr + hold_inr > cap_inr + 1e-9:
            words = reached_words(cap_inr, m.spent_inr, self.now(), self.tz)
            raise CapRefused(402, "cap_reached", words)
        return None

    async def reserve(
        self, uid: str, request_id: str, hold_inr: float, cap_inr: int
    ) -> CapHold | Done:
        hold = _money(hold_inr)
        if self.pending:
            await self.close_later(uid)  # a close kept from before goes first (never "busy")
        key = self.month_of(self.now())
        path = self.path(uid, key)

        async def fn(tx: DocTx) -> Done | None:
            m = decode(await tx.get(path), key)
            done = self._check(m, request_id, hold, cap_inr)
            if done is not None:
                return done
            holds = {**m.holds, request_id: {"inr": hold, "at": self.now().isoformat()}}
            new = replace(m, held_inr=m.held_inr + hold, holds=holds)
            tx.set(path, encode(uid, new, self.now()))
            return None

        found = await self.docs.transaction(fn)
        return found if found is not None else CapHold(uid, request_id, hold, key)

    async def _close(
        self, hold: CapHold, spend: float, outcome: Mapping[str, Any], picture: int, blocked: int
    ) -> None:
        if hold.released:
            return
        hold.released = True  # before the first await: two cannot both pass
        path = self.path(hold.uid, hold.month)

        async def fn(tx: DocTx) -> None:
            m = decode(await tx.get(path), hold.month)
            held = dict(m.holds)
            mine = held.pop(hold.request_id, None)
            spent = m.spent_inr + spend if mine is not None else m.spent_inr
            took = float(mine["inr"]) if mine is not None else 0.0
            once = 1 if mine is not None else 0  # a retry after a lost reply counts nothing twice
            rid = hold.request_id
            done = {r: o for r, o in m.done.items() if r != rid}
            kept = (*(r for r in m.order if r != rid), rid)
            if not (spend or picture or blocked):  # a release: nothing billed, nothing to replay,
                kept = kept[:-1]  # so "press again" asks Google again (security review finding 2)
            else:
                done[rid] = dict(outcome)
            new = replace(
                m, spent_inr=spent, held_inr=m.held_inr - took, holds=held, done=done, order=kept,
                pictures=m.pictures + picture * once, blocked=m.blocked + blocked * once,
            )  # fmt: skip
            tx.set(path, encode(hold.uid, new, self.now()))

        try:
            await _tries(lambda: self.docs.transaction(fn))
        except BaseException as exc:
            hold.released = False  # a failed one may be tried again: now, later or by the job
            self.pending[hold.request_id] = Later(hold, spend, outcome, picture, blocked)
            why = {"request_id": hold.request_id, "error": type(exc).__name__}
            log.error("see it on me: a hold couldn't be closed, kept for later", extra=why)
            raise
        self.pending.pop(hold.request_id, None)

    async def settle(
        self, hold: CapHold, billed_inr: float, *, outcome: Mapping[str, Any],
        picture: bool = False, blocked: bool = False,
    ) -> None:  # fmt: skip
        await self._close(hold, _money(billed_inr), outcome, int(picture), int(blocked))

    async def release(self, hold: CapHold, *, outcome: Mapping[str, Any]) -> None:
        await self._close(hold, 0.0, outcome, 0, 0)

    async def close_later(self, uid: str) -> int:
        """His closes kept from a failed try, closed now as they were meant (a release stays a
        release); one that fails again stays kept. How many closed."""
        closed = 0
        for later in [x for x in self.pending.values() if x.hold.uid == uid]:
            try:
                await self._close(later.hold, later.spend, later.outcome, later.picture,
                                  later.blocked)  # fmt: skip
            except Exception:  # noqa: BLE001 - logged by _close and kept for the next try
                continue
            closed += 1
        return closed

    async def settle_old(self, uid: str) -> int:
        """Holds older than an hour become spend at their hold (the daily job); a close kept from
        this process goes first, as it was meant. Nothing is recorded in his usage month."""
        await self.close_later(uid)
        cutoff = self.now() - timedelta(hours=SETTLE_HOURS)
        moved = 0
        for m in await self.months(uid):
            old = {r: h for r, h in m.holds.items()
                   if _when(h["at"]) <= cutoff and r not in self.pending}  # fmt: skip
            for rid, h in old.items():
                hold = CapHold(uid, rid, float(h["inr"]), m.month)
                await self.settle(hold, float(h["inr"]), outcome={"error": "maybe_billed"})
                moved += 1
        return moved

    # ---- his own settings (the switch, his cap, the keep days) -------------------------------
    def prefs_path(self, uid: str) -> str:
        return f"{self.prefix}{SPEND}/{uid}_{PREFS_ID}"

    async def prefs(self, uid: str) -> Prefs:
        doc = await self.docs.get(self.prefs_path(uid))
        if doc is None:
            return Prefs()
        on, cap, keep = doc.get("on", True), doc.get("cap_inr"), doc.get("keep_days")
        ok = isinstance(on, bool) and _bounded(cap, 0, CAP_MAX) and _bounded(keep, 1, KEEP_MAX)
        if not ok:
            raise unreadable()  # fail closed: never the deployment's (maybe higher) cap
        return Prefs(on=on, cap_inr=cap, keep_days=keep)

    async def set_prefs(self, uid: str, prefs: Prefs) -> None:
        body = {"owner": uid, "on": prefs.on, "cap_inr": prefs.cap_inr,
                "keep_days": prefs.keep_days, "updated_at": self.now().isoformat()}  # fmt: skip
        path = self.prefs_path(uid)

        async def fn(tx: DocTx) -> None:
            tx.set(path, body)

        await self.docs.transaction(fn)


async def _tries(write: Callable[[], Awaitable[None]]) -> None:
    """The write, tried again after each wait of `CLOSE_WAITS_S` (three tries in all)."""
    for wait in CLOSE_WAITS_S:
        try:
            await write()
            return
        except Exception as exc:  # noqa: BLE001 - a store blip: tried again
            log.warning("see it on me: a hold's close failed, trying again",
                        extra={"error": type(exc).__name__})  # fmt: skip
            await asyncio.sleep(wait)
    await write()


def _bounded(v: object, lo: int, hi: int) -> bool:
    return v is None or (isinstance(v, int) and not isinstance(v, bool) and lo <= v <= hi)


__all__ = [
    "CapHold",
    "CapRefused",
    "Done",
    "Later",
    "Month",
    "Prefs",
    "TryonCap",
    "decode",
    "encode",
    "reached_words",
    "unreadable",
]
