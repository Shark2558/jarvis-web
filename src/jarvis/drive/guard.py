# src/jarvis/drive/guard.py
"""The parents check (slice 12 D1): before ANY read, an item must sit inside a folder the owner
chose. Google already limits what JARVIS's account can see (what was shared with it); this keeps
JARVIS inside what the owner confirmed, whatever else lands in its account (anyone who knows the
address can share things with it) and whatever id a model — or a hostile document — asks for.

    check(id, roots) → the item's fresh metadata, or NotInRoots ("not in your chosen folders")

- No confirmed roots: refused without asking Drive anything.
- The item itself is always fetched fresh (trashed or moved shows at once); in the trash → no.
- Its ancestors are walked through `parents` (breadth-first, so a file with two parents needs
  one confirmed path), each folder's metadata cached 10 minutes, at most 12 levels and 40
  look-ups. A confirmed root id on the way → allowed. A trashed folder, a folder Drive won't show
  (404: above what was shared), a cycle, or the limits reached → that path ends.
- Any other Drive error is raised as is (the call fails; nothing is read): fail closed.

`PARENTS_CHECK` is read at call time so the eval's negative control can switch it off (and must
then fail). Production never changes it.
"""

from __future__ import annotations

import time
from collections import OrderedDict
from collections.abc import Callable, Collection

from jarvis.drive.client import DriveClient, check_id
from jarvis.drive.ports import DriveFile, DriveNotFound, NotInRoots
from jarvis.logging import get_logger

log = get_logger(__name__)

PARENTS_CHECK = True
CACHE_TTL_S = 600.0
MAX_DEPTH = 12
MAX_LOOKUPS = 40
CACHE_SIZE = 2_000
NOT_IN_ROOTS = (
    "Not in your chosen folders: JARVIS reads only Drive folders you switched on in "
    "Integrations (and what is inside them)."
)


class WalkBudget:
    """Drive look-ups several walks may still make together (one search's hits)."""

    def __init__(self, left: int) -> None:
        self.left = left

    def cached(self, guard: ParentsGuard, fid: str) -> bool:
        hit = guard._cache.get(fid)
        return hit is not None and hit[0] > guard._clock()

    def take(self) -> bool:
        if self.left <= 0:
            return False
        self.left -= 1
        return True


class ParentsGuard:
    def __init__(self, client: DriveClient, *, clock: Callable[[], float] = time.monotonic) -> None:
        self.client = client
        self._clock = clock
        self._cache: OrderedDict[str, tuple[float, DriveFile | None]] = OrderedDict()

    def forget(self) -> None:
        self._cache.clear()

    async def _ancestor(self, fid: str) -> DriveFile | None:
        """A folder above the item: cached metadata, or None when Drive won't show it."""
        hit = self._cache.get(fid)
        now = self._clock()
        if hit is not None and hit[0] > now:
            self._cache.move_to_end(fid)
            return hit[1]
        try:
            f: DriveFile | None = await self.client.get(fid)
        except DriveNotFound:
            f = None
        self._cache[fid] = (now + CACHE_TTL_S, f)
        self._cache.move_to_end(fid)
        while len(self._cache) > CACHE_SIZE:
            self._cache.popitem(last=False)
        return f

    async def inside(
        self, item: DriveFile, roots: Collection[str], budget: WalkBudget | None = None
    ) -> bool:
        """Is the (fresh) `item` inside a confirmed root? `budget`: look-ups shared by several
        walks (one search); spent → no (fail closed)."""
        if not roots or item.trashed:
            return False
        if not PARENTS_CHECK:
            return True
        if item.id in roots:
            return True
        seen = {item.id}
        level = list(item.parents)
        lookups = 0
        for _ in range(MAX_DEPTH):
            if not level:
                return False
            if any(p in roots for p in level):
                return True
            nxt: list[str] = []
            for pid in level:
                if pid in seen:
                    continue  # a cycle (or a diamond already walked)
                seen.add(pid)
                lookups += 1
                if lookups > MAX_LOOKUPS:
                    log.warning("drive parents walk: too many look-ups")
                    return False
                if budget is not None and not budget.cached(self, pid) and not budget.take():
                    return False
                parent = await self._ancestor(pid)
                if parent is None or parent.trashed:
                    continue
                nxt.extend(p for p in parent.parents if p not in seen)
            level = nxt
        return False  # a root further than MAX_DEPTH levels up does not count

    async def check(self, file_id: str, roots: Collection[str]) -> DriveFile:
        """The item's fresh metadata when it is inside a confirmed root; else NotInRoots."""
        fid = check_id(file_id)
        if not roots:
            raise NotInRoots(NOT_IN_ROOTS)
        try:
            item = await self.client.get(fid)
        except DriveNotFound:
            raise NotInRoots(NOT_IN_ROOTS) from None
        if not await self.inside(item, roots):
            raise NotInRoots(NOT_IN_ROOTS)
        return item


__all__ = [
    "CACHE_TTL_S",
    "MAX_DEPTH",
    "NOT_IN_ROOTS",
    "PARENTS_CHECK",
    "ParentsGuard",
    "WalkBudget",
]
