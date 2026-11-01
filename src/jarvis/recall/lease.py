# src/jarvis/recall/lease.py
"""Learning leases (slice 8 review, finding 3): pure transitions on `LearnState`.

Cloud Run throttles CPU outside requests, scales to zero and cancels tasks on shutdown, so a
learning run can stop anywhere. A run is therefore two-phase:

    claim   (transaction) store a lease {lease_id, started_at, start, end}; count the run —
            the cursor does NOT move
    call    the model (outside any transaction)
    apply   (transaction) only if our lease is still the one stored: merge the facts, move the
            cursor to `end` and drop the lease, all at once

A lease that failed, or is ≥ 5 minutes old (frozen / killed instance), is abandoned: the next
claim retries the same batch without counting a run. A batch that failed twice — or that was
claimed before "Forget everything" / "learning off" (an older `gen`) — is skipped: the cursor
moves past it and the caller audits it.
"""

from __future__ import annotations

import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum

from jarvis.recall.models import LearnState, Lease

LEASE_TTL = timedelta(minutes=5)
MAX_ATTEMPTS = 2
MAX_CURSORS = 50
LEASE_FORGET = timedelta(days=1)  # a lease on a conversation that is gone is dropped


class ClaimKind(StrEnum):
    NEW = "new"
    RETRY = "retry"
    SKIP = "skip"


class NoClaim(Exception):
    """Nothing to claim: "busy" (a live lease), "capped" (runs today), "not_due" (no turns)."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


@dataclass(frozen=True)
class Claim:
    kind: ClaimKind
    lease: Lease


def abandoned(lease: Lease, now: datetime) -> bool:
    return lease.failed or now - lease.started_at >= LEASE_TTL


def skippable(lease: Lease, gen: int) -> bool:
    """Two failed attempts, or claimed before a wipe / learning off: never called again."""
    return lease.attempts >= MAX_ATTEMPTS or lease.gen != gen


def _new_id() -> str:
    return secrets.token_hex(8)


def _with_lease(learn: LearnState, sid: str, lease: Lease, now: datetime) -> LearnState:
    leases = {
        k: v for k, v in learn.leases.items() if k != sid and now - v.started_at < LEASE_FORGET
    }
    leases[sid] = lease
    return learn.model_copy(update={"leases": leases})


def release(learn: LearnState, sid: str, end: int) -> LearnState:
    """The batch is done (applied, skipped or stale): cursor to `end`, lease gone."""
    cursors = {k: v for k, v in learn.cursors.items() if k != sid}
    cursors[sid] = max(learn.cursors.get(sid, 0), end)
    kept = dict(list(cursors.items())[-MAX_CURSORS:])
    leases = {k: v for k, v in learn.leases.items() if k != sid}
    return learn.model_copy(update={"cursors": kept, "leases": leases})


def mark_failed(learn: LearnState, sid: str, lease_id: str) -> LearnState | None:
    """Our call did not finish: retry at once (not after 5 minutes). None if not ours."""
    held = learn.leases.get(sid)
    if held is None or held.lease_id != lease_id:
        return None
    leases = {**learn.leases, sid: held.model_copy(update={"failed": True})}
    return learn.model_copy(update={"leases": leases})


def claim(
    learn: LearnState, sid: str, turn_count: int, *, day: str, max_runs: int, now: datetime
) -> tuple[LearnState, Claim]:
    """The claim transaction's change. Raises NoClaim."""
    held = learn.leases.get(sid)
    if held is not None:
        if not abandoned(held, now):
            raise NoClaim("busy")
        if skippable(held, learn.gen):
            return release(learn, sid, held.end), Claim(ClaimKind.SKIP, held)
        again = held.model_copy(
            update={
                "lease_id": _new_id(),
                "started_at": now,
                "attempts": held.attempts + 1,
                "failed": False,
            }
        )
        return _with_lease(learn, sid, again, now), Claim(ClaimKind.RETRY, again)
    runs = learn.runs if learn.day == day else 0
    if runs >= max_runs:
        raise NoClaim("capped")
    cursor = learn.cursors.get(sid, 0)
    if cursor >= turn_count:
        raise NoClaim("not_due")
    lease = Lease(lease_id=_new_id(), started_at=now, start=cursor, end=turn_count, gen=learn.gen)
    counted = learn.model_copy(update={"day": day, "runs": runs + 1})
    return _with_lease(counted, sid, lease, now), Claim(ClaimKind.NEW, lease)


__all__ = [
    "LEASE_TTL",
    "MAX_ATTEMPTS",
    "MAX_CURSORS",
    "Claim",
    "ClaimKind",
    "NoClaim",
    "abandoned",
    "claim",
    "mark_failed",
    "release",
    "skippable",
]
