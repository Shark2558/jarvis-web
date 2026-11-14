# src/jarvis/backup/verify.py
"""The restore drill's verifier (docs/plans/r14-hardening.md D4 "verifying", review A2): checks a
throw-away copy against the live database, BOTH sides read only (`ReadOnlyDocs`; the copy also
through `DrillWalk`), resumable within the tick's time. It never imports the live store's SDK
adapter nor the drill's log (D4 lock 3): it returns a `Progress` and `drill.py` stores it.

Units, in this order, each between two looks at the tick's time left (`ticks.time_left`; a unit
starts only with `RESERVE_S` to spare, so the tick never times out mid-way):
1. `canary`  the newest canary dated within 26 hours before the snapshot is in the copy, its hash
             equals the live one's and its sealed nonce opens with the live key (fingerprints
             match) -> else `canary_missing`, `canary_mismatch` or `key`;
2. `vault`   each owner's vault (`vault_probe.probe`), one owner a unit;
3. `list`    the collection-group ids to count and the root collections to sample;
4. `counts`  one `count()` per group; the sum must equal the backup's document count -> else
             `count_mismatch`;
5. `samples` one collection a unit (`walk_checks.compare_samples`) -> `sample_mismatch`; none
             compared at all -> `nothing_compared`.
The first failure ends the checks (the drill then cleans up). `outcome`: "failed" with that
reason, "skipped" (`no_vault`: no vault to open, never a pass), or "passed".
`Keys` are the comparisons' own fields (the app's); the eval's negative control swaps them for
Firestore's `update_time` to show that a restamped copy then compares nothing and fails.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from jarvis.backup import canary, walk_checks
from jarvis.backup.ports import DrillWalk, ReadOnlyDocs
from jarvis.backup.vault_probe import DocKey, ItemKey, doc_version, item_version, probe
from jarvis.keyring import Keyring
from jarvis.storage.docs import Query
from jarvis.ticks import time_left as tick_time_left

RESERVE_S = 8.0
CANARY_WINDOW = dt.timedelta(hours=26)
Phase = Literal["canary", "vault", "list", "counts", "samples", "done"]
TimeLeft = Callable[[], float | None]


@dataclass(frozen=True)
class Keys:
    doc: DocKey = doc_version
    item: ItemKey = item_version
    sample: walk_checks.TimeKey = walk_checks.own_time


APP_KEYS = Keys()


class Progress(BaseModel):
    """The verifier's cursor, stored in the drill's state between ticks (counts and ids only)."""

    model_config = ConfigDict(frozen=True, extra="ignore")

    phase: Phase = "canary"
    reason: str | None = None
    canary_ok: bool = False
    vault: str | None = None
    owners_done: tuple[str, ...] = ()
    items: int = 0
    files: int = 0
    groups: tuple[str, ...] = ()
    roots: tuple[str, ...] = ()
    collections: int = 0
    counted: int = 0
    samples: int = 0
    differ: tuple[str, ...] = Field(default=(), max_length=10)


@dataclass(frozen=True)
class VerifyJob:
    walk: DrillWalk
    drill: ReadOnlyDocs
    live: ReadOnlyDocs
    ring: Keyring
    prefix: str
    snapshot: dt.datetime
    expected: int
    owners: tuple[str, ...]
    keys: Keys = field(default=APP_KEYS)


def _fail(p: Progress, reason: str) -> Progress:
    return p.model_copy(update={"phase": "done", "reason": reason})


async def _canary(job: VerifyJob) -> str:
    col = f"{job.prefix}{canary.COLLECTION}"
    low, high = job.snapshot - CANARY_WINDOW, job.snapshot
    found = []
    for day, doc in await job.drill.query(Query(col)):
        at = canary.when(dict(doc))
        if at is not None and low <= at <= high:
            found.append((at, str(day), dict(doc)))
    if not found:
        return "canary_missing"
    _, day, doc = max(found, key=lambda f: f[0])
    live = await job.live.get(f"{col}/{day}")
    if live is None or live.get("hash") != doc.get("hash"):
        return "canary_mismatch"
    opened = canary.opens(job.ring, doc, day)
    return "ok" if opened == "ok" else ("key" if opened == "key" else "canary_mismatch")


async def _canary_unit(p: Progress, job: VerifyJob) -> Progress:
    got = await _canary(job)
    if got != "ok":
        return _fail(p, got)
    return p.model_copy(update={"phase": "vault", "canary_ok": True})


async def _vault_unit(p: Progress, job: VerifyJob) -> Progress:
    left = [uid for uid in job.owners if uid not in p.owners_done]
    if not left:
        return p.model_copy(update={"phase": "list", "vault": p.vault or "no_vault"})
    uid = left[0]
    got = await probe(
        uid,
        drill=job.drill,
        live=job.live,
        ring=job.ring,
        prefix=job.prefix,
        snapshot=job.snapshot,
        doc_key=job.keys.doc,
        item_key=job.keys.item,
    )
    if got.outcome == "failed":
        return _fail(p.model_copy(update={"vault": got.reason}), got.reason or "vault_mismatch")
    vault = "opened" if got.outcome == "opened" or p.vault == "opened" else "no_vault"
    return p.model_copy(
        update={
            "owners_done": (*p.owners_done, uid),
            "items": p.items + got.items,
            "files": p.files + got.files,
            "vault": vault,
        }
    )


async def _list_unit(p: Progress, job: VerifyJob) -> Progress:
    groups, roots = await walk_checks.group_ids(
        job.walk, job.drill, prefix=job.prefix, owners=job.owners
    )
    update = {"phase": "counts", "groups": tuple(groups), "roots": tuple(roots)}
    return p.model_copy(update={**update, "collections": len(groups)})


async def _count_unit(p: Progress, job: VerifyJob) -> Progress:
    if not p.groups:
        if p.counted != job.expected:
            return _fail(p, "count_mismatch")
        return p.model_copy(update={"phase": "samples"})
    counted = p.counted + await job.walk.count(p.groups[0])
    return p.model_copy(update={"groups": p.groups[1:], "counted": counted})


async def _sample_unit(p: Progress, job: VerifyJob) -> Progress:
    if not p.roots:
        return (
            _fail(p, "nothing_compared")
            if p.samples == 0
            else p.model_copy(update={"phase": "done"})
        )
    col = p.roots[0]
    compared, differs = await walk_checks.compare_samples(col, job.walk, job.live, job.keys.sample)
    p = p.model_copy(update={"roots": p.roots[1:], "samples": p.samples + compared})
    if differs:
        return _fail(p.model_copy(update={"differ": (*p.differ, col)[:10]}), "sample_mismatch")
    return p


_UNITS = {
    "canary": _canary_unit,
    "vault": _vault_unit,
    "list": _list_unit,
    "counts": _count_unit,
    "samples": _sample_unit,
}


def _short(time_left: TimeLeft) -> bool:
    left = time_left()
    return left is not None and left < RESERVE_S


async def advance(p: Progress, job: VerifyJob, *, time_left: TimeLeft = tick_time_left) -> Progress:
    """As many units as the tick's time allows; `p.phase == "done"` when the checks are over."""
    while p.phase != "done":
        if _short(time_left):
            return p
        p = await _UNITS[p.phase](p, job)
    return p


def outcome(p: Progress) -> tuple[Literal["passed", "failed", "skipped"], str | None]:
    if p.reason is not None:
        return "failed", p.reason
    if p.vault != "opened":
        return "skipped", "no_vault"
    return "passed", None


__all__ = [
    "APP_KEYS",
    "CANARY_WINDOW",
    "RESERVE_S",
    "Keys",
    "Progress",
    "VerifyJob",
    "advance",
    "outcome",
]
