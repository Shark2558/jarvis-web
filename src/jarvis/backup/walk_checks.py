# src/jarvis/backup/walk_checks.py
"""The restore drill's counts and samples (docs/plans/r14-hardening.md D4 "verifying" (1) and
(4), review A2). Reads only: the drill copy through `DrillWalk` / `ReadOnlyDocs`, the live database
through `ReadOnlyDocs`. Never imports the live store's SDK adapter nor the drill's log (D4 lock 3).

Counts: one `count()` aggregation per collection GROUP (about one billed read per 1,000 index
entries, so about ₹0), over the ids `list_collections()` finds at the root, the sub-collection ids
the stores use (`KNOWN_SUBCOLLECTIONS`, pinned against the code by a test) and each owner's
activity days (`activity/{uid}/d{YYYYMMDD}`, listed in the copy's own `activity_days` index). Every
document sits in exactly one collection with one id, so the sum equals Google's document count
exactly when nothing is missing; an id nobody listed makes it short and the drill fails closed.

Samples: up to 20 documents a collection from the copy, each compared with live only when both
carry the same value of the document's OWN time field (`TIME_FIELDS`, never Firestore's
`update_time`, which a restore may restamp); then their content hashes must match. Names starting
and ending in `__` are Firestore's reserved ones and never part of a hash.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Callable, Mapping, Sequence
from datetime import date, datetime
from typing import Any

from jarvis.backup.ports import DrillWalk, ReadOnlyDocs
from jarvis.storage.docs import Query

KNOWN_SUBCOLLECTIONS: tuple[str, ...] = (
    "turns",  # storage/sessions.py: {prefix}sessions/{sid}/turns
    "vault_chunks",  # vault/store.py: {prefix}vault/{uid}/vault_chunks
    "chunks",  # documents/store.py: {prefix}attachments/{id}/chunks
    "pictures",  # documents/store.py: {prefix}attachments/{id}/pictures
    "book_chunks",  # buildbook/seal_chunks.py: {prefix}book/{uid}/book_chunks
    "items",  # undo/store.py: {prefix}deleted_items/{uid}/items
    "days",  # activity/store.py: {prefix}activity_days/{uid}/days
)
ACTIVITY_DAYS = "activity_days"
_DAY = re.compile(r"\d{8}")
_RESERVED = re.compile(r"^__.*__$")
SAMPLES_PER_COLLECTION = 20
SKIP_SAMPLES = ("backup_drill", "backup_status")  # the drill writes these itself meanwhile
TIME_FIELDS = ("updated_at", "updated", "at", "ts")
TimeKey = Callable[[Mapping[str, Any]], object]


def activity_group(day: str) -> str | None:
    return f"d{day}" if _DAY.fullmatch(day) else None


def own_time(doc: Mapping[str, Any]) -> object:
    """The document's own time field (the app's, never Firestore's), or None."""
    return next((doc[f] for f in TIME_FIELDS if doc.get(f) is not None), None)


def _plain(value: Any) -> str:
    if isinstance(value, datetime | date):
        return value.isoformat()
    if isinstance(value, bytes):
        return value.hex()
    return str(value)


def content_hash(doc: Mapping[str, Any]) -> str:
    kept = {k: v for k, v in doc.items() if not _RESERVED.match(str(k))}
    text = json.dumps(
        kept, sort_keys=True, default=_plain, ensure_ascii=False, separators=(",", ":")
    )
    return hashlib.sha256(text.encode()).hexdigest()


async def group_ids(
    walk: DrillWalk, drill: ReadOnlyDocs, *, prefix: str, owners: Sequence[str]
) -> tuple[list[str], list[str]]:
    """(every collection-group id to count, the root collections to sample)."""
    roots = sorted(set(await walk.collections()))
    days: set[str] = set()
    for uid in owners:
        rows = await drill.query(Query(f"{prefix}{ACTIVITY_DAYS}/{uid}/days"))
        days.update(g for g in (activity_group(str(d)) for d, _ in rows) if g is not None)
    groups = sorted(set(roots) | set(KNOWN_SUBCOLLECTIONS) | days)
    skip = {f"{prefix}{name}" for name in SKIP_SAMPLES}
    return groups, [r for r in roots if r not in skip]


async def compare_samples(
    collection: str, walk: DrillWalk, live: ReadOnlyDocs, key: TimeKey = own_time
) -> tuple[int, bool]:
    """(how many documents were compared, whether one of them differed)."""
    compared = 0
    for doc_id, copy in await walk.sample(collection, SAMPLES_PER_COLLECTION):
        stamp = key(copy)
        if stamp is None:
            continue
        found = await live.get(f"{collection}/{doc_id}")
        if found is None or key(found) != stamp:
            continue  # changed or deleted since the snapshot: not comparable
        compared += 1
        if content_hash(copy) != content_hash(found):
            return compared, True
    return compared, False


__all__ = [
    "ACTIVITY_DAYS",
    "KNOWN_SUBCOLLECTIONS",
    "SAMPLES_PER_COLLECTION",
    "SKIP_SAMPLES",
    "TIME_FIELDS",
    "TimeKey",
    "activity_group",
    "compare_samples",
    "content_hash",
    "group_ids",
    "own_time",
]
